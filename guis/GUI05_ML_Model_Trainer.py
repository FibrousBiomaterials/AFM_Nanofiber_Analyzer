# -*- coding: utf-8 -*-
"""
Train and export a machine-learning binarization model from ``.b2z`` bundles.
``.b2z`` バンドルから機械学習の二値化モデルを学習・エクスポートする。

This GUI builds a per-pixel training dataset from GUI01 output bundles, trains a
decision-tree classifier to reproduce the pipeline's binarization decision, and
exports the trained model as a ``.afmml`` file for use in the preprocessing
pipeline. Inputs are ``.b2z`` bundles (their ``calibrated`` image plus the
re-run Segmenter's pre-filter mask as the label); output is one ``.afmml``
model file (ONNX graph plus manifest).
本 GUI は GUI01 出力バンドルから画素単位の教師データを構築し、パイプラインの
二値化判断を再現する決定木分類器を学習し、学習済みモデルを前処理パイプラインで
使う ``.afmml`` ファイルとしてエクスポートする。入力は ``.b2z`` バンドル
（その ``calibrated`` 画像と、再実行した Segmenter のフィルタ前マスクをラベル
とする）、出力は 1 つの ``.afmml`` モデルファイル（ONNX グラフと manifest）。

For the two mask tasks the label can instead be the pipeline's mask with hand
-painted corrections applied, drawn in the ML Mask Annotator and stored in a
sidecar beside each bundle. A model distilled from the pipeline alone can
imitate it but never beat it; the corrections are what lift that ceiling.
2 つのマスクタスクでは、ラベルをパイプラインのマスクへ手描きの修正を適用した
ものにもできる。修正は ML Mask Annotator で描き、各バンドルの隣の sidecar に
保存される。パイプラインだけから蒸留したモデルはそれを模倣できても上回れない。
この上限を外すのが修正である。

The machine-learning libraries (scikit-learn, skl2onnx, onnxruntime) are
optional and imported lazily inside the worker thread, so this plugin starts
without them and reports a clear install hint if a training run needs them.
機械学習ライブラリ（scikit-learn, skl2onnx, onnxruntime）は任意で、ワーカー
スレッド内で遅延 import する。したがって本プラグインはそれら無しで起動し、
学習実行時に必要になれば明確な導入案内を表示する。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Values must remain plain string literals because they are passed to literal_eval.
# Main.py がこのファイルを AST 解析で読み取るため、値は literal_eval 可能な
# 文字列リテラルのままにする（_() で包まない）。
PLUGIN_INFO = {
    "name": "ML Model Trainer",
    "description": (
        "Train a machine-learning preprocessing model from .b2z bundles and "
        "export it as a .afmml model file. Choose the task: binarization, "
        "background fiber-candidate mask, or background-surface regression "
        "(the last two are the alternative background-correction approaches "
        "and need the raw image in the bundle). Select folders of Image "
        "Preprocessor bundles, build a pixel dataset, cross-validate a "
        "decision-tree model, and save it. For the two mask tasks the label "
        "can be the pipeline's own mask or that mask with hand-painted "
        "corrections from the ML Mask Annotator applied. "
        "The ML libraries are optional and loaded only when training runs."
    )
}

# ===== Standard library =====
import os
import queue
import threading
import traceback
from typing import Dict, List, Optional

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# ===== Project libraries =====
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_ttk_theme,
    create_scrolled_text, create_scrolled_treeview,
    save_text_widget_log, drain_ui_queue,
    LogMixin, ToolTip,
)

# Classifier kinds offered in the UI. These identifier strings mirror
# lib.ml_train.MODEL_KINDS (imported lazily in the worker); kept as local
# literals so plugin startup does not import scikit-learn. The mapping is
# display label -> fixed model-kind identifier.
# UI が提示する分類器の種類。識別子文字列は lib.ml_train.MODEL_KINDS
# （ワーカーで遅延 import）と一致させる。プラグイン起動時に scikit-learn を
# import しないようローカルのリテラルとして保持する。対応は表示ラベル ->
# 固定のモデル種別識別子。
MODEL_KIND_LABELS = {
    "Random Forest": "random_forest",
    "HistGradientBoosting": "hist_gradient_boosting",
}

# Label-source choices, mirroring lib.ml_dataset.LABEL_SOURCES. The default
# intermediate mask is the Segmenter's pre-component-filter output, which is the
# decision the binarization model actually replaces (see lib.ml_dataset).
# ラベル出所の選択肢。lib.ml_dataset.LABEL_SOURCES と一致。既定の中間マスクは
# Segmenter の成分フィルタ前出力で、二値化モデルが実際に置き換える判断
# （lib.ml_dataset 参照）。
LABEL_SOURCE_LABELS = {
    "Segmenter intermediate (pre-filter)": "segmenter_intermediate",
    "Bundle binarized (final)": "bundle_binarized",
    "Pipeline mask (distilled)": "segmenter_intermediate",
    "Manual corrections (painted)": "expert_corrected",
}

# Which of the labels above each task offers. A task absent from this mapping
# has no choice to make, because its label follows from the task alone.
# "Pipeline mask (distilled)" is bg_mask's name for the default value: bg_mask
# always rebuilds its base from the BGCalibrator and ignores the distilled
# choice, so the value passed there only has to be a valid non-correction one.
# 上記のうち各タスクが提示する選択肢。この対応に無いタスクは選択の余地がない。
# ラベルがタスクだけで定まるためである。"Pipeline mask (distilled)" は bg_mask に
# おける既定値の呼び名である。bg_mask はベースを常に BGCalibrator から再構築し、
# 蒸留側の選択を無視するため、そこへ渡す値は修正以外の有効な値であればよい。
TASK_LABEL_SOURCES = {
    "binarize": ("Segmenter intermediate (pre-filter)",
                 "Bundle binarized (final)",
                 "Manual corrections (painted)"),
    "bg_mask": ("Pipeline mask (distilled)",
                "Manual corrections (painted)"),
}

# Trainable tasks offered in the UI, mapping display label -> fixed task
# identifier (the vocabulary is owned by lib.ml_schema). The two background
# tasks are the alternative process-A approaches kept side by side so they can
# be compared: `bg_mask` classifies fiber candidates and reuses the existing
# background fill, `background_surface` regresses the background height itself.
# UI が提示する学習可能タスク。表示ラベル -> 固定のタスク識別子（語彙は
# lib.ml_schema が持つ）。2 つの背景タスクは比較のため併存させる工程Aの代替
# 方式で、`bg_mask` は繊維候補を分類して既存の背景生成を再利用し、
# `background_surface` は背景高さ自体を回帰する。
TASK_LABELS = {
    "Binarization (calibrated -> fiber mask)": "binarize",
    "Background mask (raw -> fiber candidates)": "bg_mask",
    "Background surface (raw -> background nm)": "background_surface",
}

# Tasks that regress a continuous target; mirrors lib.ml_dataset.REGRESSION_TASKS.
# 連続値を回帰するタスク。lib.ml_dataset.REGRESSION_TASKS と対応。
_REGRESSION_TASKS = ("background_surface",)

# Metric keys shown in the results table, in display order, per task family.
# Fixed English: these are scientific/reporting labels, not localized UI text.
# タスク系統ごとに結果テーブルへ表示する指標キー（表示順）。固定英語：科学的・
# 報告用ラベルであり、ローカライズ対象の UI 文字列ではない。
_METRIC_ROWS = ("precision", "recall", "dice", "iou", "accuracy")
_REGRESSION_METRIC_ROWS = ("mae", "rmse", "bias", "r2")


class App(tk.Tk, LogMixin):
    """
    Main window for building a dataset, training, and exporting a model.
    データセット構築・学習・モデルエクスポートを行うメインウィンドウ。
    """

    def __init__(self) -> None:
        """
        Initialize the window, state, controls, and progress polling.
        ウィンドウ・状態・操作部・進捗ポーリングを初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])

        self._clam_bg = setup_ttk_theme(self)

        apply_window_size(self, 1250, 800, min_w=1000, min_h=650)

        # Flat list of scanned bundles; tree rows correspond to it one-to-one,
        # in order, so a selected row maps to `self.bundles[tree.index(row)]`.
        # 走査済みバンドルのフラットな一覧。ツリー行と順序どおり 1 対 1 対応し、
        # 選択行は `self.bundles[tree.index(row)]` に対応する。
        self.bundles: List = []
        # In-memory result of the last successful training run, kept for export.
        # 直近の学習成功結果をエクスポート用にメモリ保持する。
        self._train_result = None
        self._dataset_provenance: Optional[List[Dict]] = None
        self._trained_kind: str = ""
        self._trained_task: str = ""
        # False while a trained model is held in memory but not yet exported.
        # Drives the save reminders on retrain and on window close, because the
        # result lives only in memory and both actions would discard it.
        # 学習済みモデルをメモリ保持しつつ未エクスポートの間は False。
        # 結果はメモリ上にしか存在せず、再学習と終了はどちらもそれを破棄する
        # ため、両者の保存確認を制御する。
        self._model_saved: bool = True

        self.ui_queue: queue.Queue = queue.Queue()
        self.is_running = False

        self._build_ui()
        self._log_initial_message()
        self._update_controls_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        """
        Build the two-pane layout: controls on the left, results on the right.
        2 ペイン構成を構築する。左が操作部、右が結果。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=2)
        outer.add(right, weight=3)

        self._build_dataset_panel(left)
        self._build_sampling_panel(left)
        self._build_model_panel(left)
        self._build_action_bar(left)

        self._build_results_panel(right)
        self._build_log_panel(right)

    def _build_dataset_panel(self, parent: ttk.Frame) -> None:
        """
        Build the bundle-folder list and its add/remove controls.
        バンドルフォルダ一覧と追加/削除操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("データセット（.b2z バンドル）"))
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        btn_row = ttk.Frame(lf)
        btn_row.pack(fill=tk.X, padx=4, pady=4)
        self.btn_add_folder = ttk.Button(
            btn_row, text=_("フォルダ追加..."), command=self.on_add_folder)
        self.btn_add_folder.pack(side=tk.LEFT, padx=2)
        self.btn_add_files = ttk.Button(
            btn_row, text=_("ファイル追加..."), command=self.on_add_files)
        self.btn_add_files.pack(side=tk.LEFT, padx=2)
        self.btn_remove = ttk.Button(
            btn_row, text=_("削除"), command=self.on_remove_entry)
        self.btn_remove.pack(side=tk.LEFT, padx=2)
        self.btn_clear = ttk.Button(
            btn_row, text=_("クリア"), command=self.on_clear_entries)
        self.btn_clear.pack(side=tk.LEFT, padx=2)

        # Column headings are UI labels; "usable"/"reason" values are English.
        # 列見出しは UI ラベル。usable/reason の値は英語。
        tree_frame = ttk.Frame(lf)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tree, _sb = create_scrolled_treeview(
            tree_frame,
            columns=("bundle", "usable", "reason"),
            show="headings",
            selectmode="extended",
            height=8,
            headings={
                "bundle": _("バンドル"),
                "usable": _("使用可否"),
                "reason": _("理由"),
            },
            column_options={
                "bundle": {"width": 220, "anchor": "w"},
                "usable": {"width": 60, "anchor": "center"},
                "reason": {"width": 240, "anchor": "w"},
            },
        )

        self.summary_var = tk.StringVar(value="")
        ttk.Label(lf, textvariable=self.summary_var).pack(
            anchor="w", padx=6, pady=(0, 4))

    def _build_sampling_panel(self, parent: ttk.Frame) -> None:
        """
        Build the sampling controls (label source, balancing, sample cap, seed).
        サンプリング操作部（ラベル出所・均衡・サンプル上限・乱数種）を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("サンプリング"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(grid, text=_("学習するタスク")).grid(
            row=0, column=0, sticky="w", padx=2, pady=2)
        self.task_var = tk.StringVar(value=list(TASK_LABELS)[0])
        task_cb = ttk.Combobox(grid, textvariable=self.task_var,
                               values=list(TASK_LABELS), state="readonly", width=32)
        task_cb.grid(row=0, column=1, columnspan=3, sticky="w", padx=2, pady=2)
        task_cb.bind("<<ComboboxSelected>>", self._on_task_changed)
        ToolTip(task_cb, _("背景マスクと背景面は工程Aの代替方式です。"
                           "どちらも .b2z に生画像が必要です。"))

        ttk.Label(grid, text=_("ラベルの出所")).grid(row=1, column=0, sticky="w", padx=2, pady=2)
        # Values are filled by _on_task_changed(), which knows the choices the
        # selected task offers.
        # 値は _on_task_changed() が埋める。選択中のタスクが提示する選択肢を
        # 知っているのはそちらである。
        self.label_source_var = tk.StringVar(value=TASK_LABEL_SOURCES["binarize"][0])
        cb = ttk.Combobox(grid, textvariable=self.label_source_var,
                          values=[], state="readonly", width=32)
        cb.grid(row=1, column=1, columnspan=3, sticky="w", padx=2, pady=2)
        self.label_source_combo = cb
        ToolTip(cb, _("Segmenter intermediate はモデルが置き換える成分フィルタ前のマスク、"
                      "bundle binarized は保存済みの最終マスクです。"
                      "Manual corrections は ML Mask Annotator で描いた手修正を"
                      "適用したマスクで、バンドルごとに sidecar が必要です。"))

        ttk.Label(grid, text=_("画像あたり最大サンプル数")).grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.max_samples_var = tk.StringVar(value="20000")
        e1 = ttk.Entry(grid, textvariable=self.max_samples_var, width=10)
        e1.grid(row=2, column=1, sticky="w", padx=2, pady=2)

        ttk.Label(grid, text=_("乱数シード")).grid(row=2, column=2, sticky="w", padx=2, pady=2)
        self.seed_var = tk.StringVar(value="0")
        e2 = ttk.Entry(grid, textvariable=self.seed_var, width=8)
        e2.grid(row=2, column=3, sticky="w", padx=2, pady=2)

        self.balance_var = tk.BooleanVar(value=True)
        self.balance_check = ttk.Checkbutton(
            grid, text=_("画像ごとに繊維/背景を均衡させる"), variable=self.balance_var)
        self.balance_check.grid(row=3, column=0, columnspan=4, sticky="w", padx=2, pady=2)

        self._on_task_changed()

    def _on_task_changed(self, _event=None) -> None:
        """
        Enable only the controls that apply to the selected task.
        選択したタスクに該当する操作部のみを有効化する。

        The label sources differ per task, and class balancing is meaningless
        for a regression target, so the combo is refilled and the checkbox is
        dimmed rather than silently ignored.
        ラベルの出所はタスクごとに異なり、クラス均衡は回帰ターゲットに意味が
        ない。黙って無視せず、コンボボックスは選択肢を入れ替え、チェックボックス
        は淡色表示にする。
        """
        task = TASK_LABELS[self.task_var.get()]
        choices = TASK_LABEL_SOURCES.get(task, ())
        if choices:
            self.label_source_combo.configure(
                values=list(choices), state="readonly")
            # Carrying a choice the new task does not offer would send a label
            # source the dataset builder rejects, so fall back to the default.
            # 新しいタスクが提示しない選択を持ち越すと、データセット構築側が拒否する
            # ラベル出所を送ることになるため、既定へ戻す。
            if self.label_source_var.get() not in choices:
                self.label_source_var.set(choices[0])
        else:
            self.label_source_combo.configure(state=tk.DISABLED)
        self.balance_check.configure(
            state=tk.DISABLED if task in _REGRESSION_TASKS else tk.NORMAL)
        # Re-scanning under a new task is required because usability differs
        # (process A needs the raw image), so make the stale list obvious.
        # タスクが変わると使用可否の条件も変わる（工程Aは生画像が必要）ため、
        # 再走査が必要であることを分かるようにする。
        if self.bundles:
            self._log(_("タスクを変更しました。バンドルを再走査してください。"))

    def _build_model_panel(self, parent: ttk.Frame) -> None:
        """
        Build the classifier-choice and hyperparameter controls.
        分類器選択とハイパーパラメータの操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("モデル"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(grid, text=_("分類器")).grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.kind_var = tk.StringVar(value=list(MODEL_KIND_LABELS)[0])
        ttk.Combobox(grid, textvariable=self.kind_var,
                     values=list(MODEL_KIND_LABELS), state="readonly", width=24).grid(
            row=0, column=1, columnspan=3, sticky="w", padx=2, pady=2)

        # n_estimators applies to Random Forest; max_iter to HistGradientBoosting.
        # The worker passes both to ModelConfig, which uses the relevant one.
        # n_estimators は Random Forest、max_iter は HistGradientBoosting に効く。
        # ワーカーは両方を ModelConfig へ渡し、該当する側だけが使われる。
        ttk.Label(grid, text=_("木の本数／反復数")).grid(row=1, column=0, sticky="w", padx=2, pady=2)
        self.n_estimators_var = tk.StringVar(value="200")
        ttk.Entry(grid, textvariable=self.n_estimators_var, width=8).grid(
            row=1, column=1, sticky="w", padx=2, pady=2)

        ttk.Label(grid, text=_("交差検証の分割数")).grid(row=1, column=2, sticky="w", padx=2, pady=2)
        self.n_splits_var = tk.StringVar(value="5")
        ttk.Entry(grid, textvariable=self.n_splits_var, width=6).grid(
            row=1, column=3, sticky="w", padx=2, pady=2)

        # "Fiber threshold" is the probability cutoff recorded as the model's
        # segmentation_threshold; label stays with the fixed unit-free notion.
        # 「Fiber threshold」は繊維判定の確率しきい値で、モデルの
        # segmentation_threshold として記録される。
        ttk.Label(grid, text=_("ファイバーしきい値")).grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.threshold_var = tk.StringVar(value="0.5")
        ttk.Entry(grid, textvariable=self.threshold_var, width=8).grid(
            row=2, column=1, sticky="w", padx=2, pady=2)

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        """
        Build the train and export buttons and the progress indicator.
        学習・エクスポートボタンと進捗表示を構築する。
        """
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, padx=4, pady=(2, 6))

        self.btn_train = ttk.Button(bar, text=_("学習"), command=self.on_train)
        self.btn_train.pack(side=tk.LEFT, padx=2)
        self.btn_export = ttk.Button(
            bar, text=_("モデルをエクスポート..."), command=self.on_export)
        self.btn_export.pack(side=tk.LEFT, padx=2)

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=140)
        self.progress.pack(side=tk.RIGHT, padx=4)

    def _build_results_panel(self, parent: ttk.Frame) -> None:
        """
        Build the cross-validation metrics table and feature-importance view.
        交差検証の指標テーブルと特徴重要度ビューを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("結果"))
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Metric names are fixed English scientific labels; only the column
        # headings are localized.
        # 指標名は固定英語の科学的ラベル。ローカライズするのは列見出しのみ。
        self.metrics_tree, _sb = create_scrolled_treeview(
            lf,
            columns=("metric", "mean", "std"),
            show="headings",
            height=6,
            headings={
                "metric": _("指標"),
                "mean": _("平均"),
                "std": _("標準偏差"),
            },
            column_options={
                "metric": {"width": 140, "anchor": "w"},
                "mean": {"width": 90, "anchor": "e"},
                "std": {"width": 90, "anchor": "e"},
            },
        )

        ttk.Label(lf, text=_("特徴重要度の上位")).pack(anchor="w", padx=6, pady=(4, 0))
        self.importance_text, _sb2 = create_scrolled_text(lf, height=8, width=40)
        self.importance_text.configure(state=tk.DISABLED)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log text area and its save button.
        ログテキスト領域と保存ボタンを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ログ"))
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log_text, _sb = create_scrolled_text(lf, height=8, width=40)
        self.log_text.configure(state=tk.DISABLED)

        ttk.Button(lf, text=_("ログを保存..."), command=self.on_save_log).pack(
            anchor="e", padx=6, pady=4)

    # ----- Logging ---------------------------------------------------------
    # `_log` / `_log_exception` come from LogMixin (they drive self.log_text).
    # `_log` / `_log_exception` は LogMixin 由来（self.log_text を操作する）。

    def _log_initial_message(self) -> None:
        """
        Log a short usage hint at startup.
        起動時に短い使い方の案内をログへ表示する。
        """
        self._log(_(".b2z バンドルのフォルダを追加して Train を押します。"
                    "Export は前処理パイプライン用の .afmml モデルを保存します。"))

    # ----- Dataset entry management ---------------------------------------

    def on_add_folder(self) -> None:
        """
        Add every ``.b2z`` bundle in a chosen folder as one dataset entry.
        選択したフォルダ内の全 ``.b2z`` バンドルを 1 つのデータセット項目として追加する。
        """
        folder = filedialog.askdirectory(title=_(".b2z バンドルを含むフォルダを選択"))
        if not folder:
            return
        self._add_entry(folder, is_dir=True)

    def on_add_files(self) -> None:
        """
        Add one or more chosen ``.b2z`` files as individual dataset entries.
        選択した 1 つ以上の ``.b2z`` ファイルを個別のデータセット項目として追加する。
        """
        paths = filedialog.askopenfilenames(
            title=_(".b2z バンドルファイルを選択"),
            filetypes=[("b2z bundles", "*.b2z"), ("All files", "*.*")],
        )
        for p in paths:
            self._add_entry(p, is_dir=False)

    def _add_scanned(self, new_infos: List) -> None:
        """
        Append scanned bundle infos, skipping duplicate paths, and add rows.
        走査済みバンドル情報を追加し、重複パスは省いて行を挿入する。
        """
        existing = {info.path for info in self.bundles}
        added = 0
        for info in new_infos:
            if info.path in existing:
                continue
            existing.add(info.path)
            self.bundles.append(info)
            self.tree.insert(
                "", tk.END,
                values=(os.path.basename(info.path),
                        "yes" if info.usable else "no",
                        info.reason),
            )
            added += 1
        self._update_summary()
        self._update_controls_state()
        if added == 0 and new_infos:
            self._log(_("選択したバンドルはすべて既に一覧にあります。"))

    def _add_entry(self, path: str, is_dir: bool) -> None:
        """
        Scan a folder or file for bundles and add them to the flat list.
        フォルダまたはファイルを走査し、フラットな一覧へ追加する。

        Scanning imports the (numpy/pipeline, not scikit-learn) dataset module
        lazily, so this stays responsive and does not pull the ML stack.
        走査は（numpy/pipeline、scikit-learn ではない）データセットモジュールを
        遅延 import するため、応答性を保ち ML スタックを引き込まない。
        """
        task = TASK_LABELS[self.task_var.get()]
        label_source = LABEL_SOURCE_LABELS[self.label_source_var.get()]
        try:
            from lib import ml_dataset as md
            if is_dir:
                infos = md.scan_bundle_folder(path, task=task, label_source=label_source)
            else:
                infos = [md.inspect_bundle(path, task=task, label_source=label_source)]
        except Exception as exc:  # noqa: BLE001 - surface any scan failure to the user.
            messagebox.showerror(_("走査に失敗しました"), str(exc))
            return
        self._add_scanned(infos)

    def on_remove_entry(self) -> None:
        """
        Remove the selected bundles from the list.
        選択したバンドルを一覧から削除する。
        """
        selected = self.tree.selection()
        if not selected:
            return
        # Map each selected row to its index, delete high-to-low so earlier
        # indices stay valid, and drop the same positions from self.bundles.
        # 各選択行を添字へ対応付け、後方から削除して前方の添字を保ち、
        # self.bundles から同じ位置を除く。
        indices = sorted((self.tree.index(iid) for iid in selected), reverse=True)
        for idx in indices:
            self.tree.delete(self.tree.get_children()[idx])
            del self.bundles[idx]
        self._update_summary()
        self._update_controls_state()

    def on_clear_entries(self) -> None:
        """
        Remove all bundles from the list.
        一覧から全バンドルを削除する。
        """
        self.bundles = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._update_summary()
        self._update_controls_state()

    def _usable_paths(self) -> List[str]:
        """
        Return the paths of all usable bundles.
        使用可能な全バンドルのパスを返す。
        """
        return [info.path for info in self.bundles if info.usable]

    def _update_summary(self) -> None:
        """
        Update the "N usable of M" summary label.
        「M 件中 N 件が使用可能」の要約ラベルを更新する。
        """
        total = len(self.bundles)
        usable = len(self._usable_paths())
        # Fixed unit-free counts; the sentence itself is localized.
        # 単位のない件数。文自体はローカライズする。
        self.summary_var.set(
            _("{total} 件中 {usable} 件が使用可能").format(usable=usable, total=total))

    # ----- Controls state --------------------------------------------------

    def _update_controls_state(self) -> None:
        """
        Enable Train when usable bundles exist and Export when a model is trained.
        使用可能バンドルがあれば Train を、学習済みなら Export を有効化する。
        """
        if self.is_running:
            return
        self.btn_train.configure(
            state=tk.NORMAL if self._usable_paths() else tk.DISABLED)
        self.btn_export.configure(
            state=tk.NORMAL if self._train_result is not None else tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        """
        Toggle controls and the progress bar while a worker is active.
        ワーカー実行中に操作部と進捗バーを切り替える。
        """
        self.is_running = running
        state = tk.DISABLED if running else tk.NORMAL
        for b in (self.btn_add_folder, self.btn_add_files, self.btn_remove,
                  self.btn_clear, self.btn_train, self.btn_export):
            b.configure(state=state)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()
            self._update_controls_state()

    # ----- Unsaved-model guards --------------------------------------------

    def _has_unsaved_model(self) -> bool:
        """
        Report whether a trained model is in memory but not yet exported.
        学習済みモデルがメモリ上にあり未エクスポートかを返す。
        """
        return self._train_result is not None and not self._model_saved

    def _on_close(self) -> None:
        """
        Confirm before closing while an unexported model is in memory.
        未エクスポートのモデルがメモリ上にある場合、閉じる前に確認する。
        """
        if self._has_unsaved_model() and not messagebox.askyesno(
                _("未保存のモデル"),
                _("学習済みモデルがまだ保存されていません。\n"
                  "保存せずに終了しますか？")):
            return
        self.destroy()

    # ----- Training --------------------------------------------------------

    def on_train(self) -> None:
        """
        Validate inputs and start dataset build + training in a worker thread.
        入力を検証し、データセット構築＋学習をワーカースレッドで開始する。
        """
        if self.is_running:
            return
        paths = self._usable_paths()
        if not paths:
            messagebox.showwarning(_("データなし"), _("使用可能な .b2z バンドルを 1 つ以上追加してください。"))
            return

        params = self._collect_train_params()
        if params is None:
            return

        # Retraining overwrites the in-memory result, so confirm first when the
        # previous model has not been exported yet.
        if self._has_unsaved_model() and not messagebox.askyesno(
                _("未保存のモデル"),
                _("学習済みモデルがまだ保存されていません。\n"
                  "再学習すると破棄されます。続行しますか？")):
            return

        self._train_result = None
        self._dataset_provenance = None
        self._update_controls_state()

        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("データセット構築と学習中..."))
        threading.Thread(
            target=self._worker_train, args=(paths, params), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _collect_train_params(self) -> Optional[Dict]:
        """
        Read and validate the sampling and model controls.
        サンプリングとモデルの操作部を読み取り検証する。

        Returns the parameter dict, or ``None`` after showing an error dialog.
        パラメータ辞書を返す。エラーダイアログ表示後は ``None``。
        """
        try:
            max_samples_txt = self.max_samples_var.get().strip()
            max_samples = None if max_samples_txt == "" else int(max_samples_txt)
            if max_samples is not None and max_samples <= 0:
                raise ValueError(_("画像あたりの最大サンプル数は正の整数または空欄にしてください。"))
            seed = int(self.seed_var.get().strip())
            n_estimators = int(self.n_estimators_var.get().strip())
            if n_estimators <= 0:
                raise ValueError(_("木の本数／反復数は正の整数にしてください。"))
            n_splits = int(self.n_splits_var.get().strip())
            if n_splits < 2:
                raise ValueError(_("交差検証の分割数は 2 以上にしてください。"))
            threshold = float(self.threshold_var.get().strip())
            if not (0.0 <= threshold <= 1.0):
                raise ValueError(_("ファイバーしきい値は 0〜1 の範囲で指定してください。"))
        except ValueError as exc:
            messagebox.showerror(_("入力エラー"), str(exc))
            return None

        return {
            "task": TASK_LABELS[self.task_var.get()],
            "label_source": LABEL_SOURCE_LABELS[self.label_source_var.get()],
            "max_samples": max_samples,
            "balance": bool(self.balance_var.get()),
            "seed": seed,
            "kind": MODEL_KIND_LABELS[self.kind_var.get()],
            "n_estimators": n_estimators,
            "n_splits": n_splits,
            "threshold": threshold,
        }

    def _worker_train(self, paths: List[str], params: Dict) -> None:
        """
        Build the dataset and train the model off the main thread.
        メインスレッド外でデータセットを構築しモデルを学習する。

        Results and progress flow back through ``self.ui_queue``; the ML
        libraries are imported here so plugin startup never loads them, and a
        missing optional dependency is reported as a clear message.
        結果と進捗は ``self.ui_queue`` 経由で返す。ML ライブラリはここで
        import し、プラグイン起動時に読み込まれないようにする。任意依存の欠落は
        明確なメッセージとして報告する。
        """
        try:
            from lib import ml_dataset as md
            from lib import ml_train as mt
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return

        try:
            self.ui_queue.put(("log", _("{n} 個のバンドルから画素データセットを構築中...")
                               .format(n=len(paths))))
            dataset = md.build_pixel_dataset(
                paths, task=params["task"],
                label_source=params["label_source"],
                max_samples_per_image=params["max_samples"],
                balance=params["balance"],
                random_state=params["seed"],
            )
            self.ui_queue.put(("log", _("データセット: {n} サンプル、{g} 画像グループ、"
                                        "繊維 {f} / 背景 {b}。").format(
                n=dataset.X.shape[0], g=len(dataset.group_names),
                f=dataset.n_fiber, b=dataset.n_background)))

            # Report the hand-corrected share explicitly: it is the only part of
            # the label a person actually looked at, and a run that silently
            # included none of it would otherwise look identical to one that did.
            # 手修正の割合は明示して報告する。ラベルのうち人が実際に見た唯一の部分で
            # あり、それが黙って 1 画素も入らなかった実行は、そうでない実行と見分けが
            # 付かなくなるためである。
            n_edited = sum(int(rec.get("n_edited", 0))
                           for rec in dataset.provenance if rec.get("used"))
            if n_edited:
                self.ui_queue.put(("log", _("うち手動修正画素: {n}。").format(n=n_edited)))

            config = mt.ModelConfig(
                kind=params["kind"],
                n_estimators=params["n_estimators"],
                max_iter=params["n_estimators"],
                random_state=params["seed"],
            )

            def progress_cb(stage: str) -> None:
                self.ui_queue.put(("log", _("段階: {s}").format(s=stage)))

            result = mt.train(
                dataset, config,
                n_splits=params["n_splits"],
                fiber_threshold=params["threshold"],
                progress_cb=progress_cb,
            )
            self.ui_queue.put(("trained", {
                "result": result,
                "provenance": dataset.provenance,
                "kind": params["kind"],
                "task": params["task"],
            }))
        except Exception as exc:  # noqa: BLE001 - report any training failure.
            self.ui_queue.put(("fatal", {
                "text": str(exc), "trace": traceback.format_exc()}))

    # ----- Export ----------------------------------------------------------

    def _prompt_save_model(self) -> None:
        """
        Offer to export the model immediately after a successful training run.
        学習成功直後にモデルのエクスポートを提案する。

        Declining is deliberately cheap so sweeping classifier parameters stays
        practical, and it avoids forcing the skl2onnx conversion (only reached
        from `on_export`) on runs the user only wants metrics from. The retrain
        and close guards catch the model afterwards.
        分類器パラメータを振る作業を実用的に保つため、断るコストは意図的に
        低くしてある。指標だけを見たい実行で skl2onnx 変換（`on_export` から
        のみ到達）を強制しないためでもある。取りこぼしは再学習時と終了時の
        確認が拾う。
        """
        if self._train_result is None:
            return
        if messagebox.askyesno(
                _("モデルを保存"),
                _("学習が完了しました。モデルを今すぐ保存しますか？")):
            self.on_export()
        else:
            self._log(
                _("モデルは未保存です。[モデルをエクスポート...] からいつでも保存できます。"))

    def on_export(self) -> None:
        """
        Validate, ask for a path, and export the trained model in a worker.
        検証し、保存先を尋ね、学習済みモデルをワーカーでエクスポートする。
        """
        if self.is_running or self._train_result is None:
            return
        model_id = self._ask_model_id()
        if not model_id:
            return
        path = filedialog.asksaveasfilename(
            title=_("モデルを保存"),
            defaultextension=".afmml",
            filetypes=[("AFM ML model", "*.afmml")],
        )
        if not path:
            return

        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("モデルを ONNX へエクスポート中..."))
        threading.Thread(
            target=self._worker_export,
            args=(path, model_id, self._train_result, self._dataset_provenance),
            daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _ask_model_id(self) -> Optional[str]:
        """
        Prompt for a model identifier, defaulting to the classifier kind.
        モデル識別子を尋ねる。既定は分類器の種類。
        """
        default = f"{self._trained_task or 'model'}-{self._trained_kind or 'rf'}"
        return simpledialog.askstring(
            _("モデル ID"), _("モデルファイルに記録する識別子:"),
            initialvalue=default, parent=self)

    def _worker_export(self, path: str, model_id: str, result, provenance) -> None:
        """
        Export the trained classifier to a ``.afmml`` file off the main thread.
        学習済み分類器を ``.afmml`` ファイルへメインスレッド外でエクスポートする。
        """
        try:
            from lib import ml_model as mm
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return
        try:
            manifest = mm.save_pixel_model(
                path, result, model_id=model_id, dataset_provenance=provenance)
            final = path if path.lower().endswith(".afmml") else path + ".afmml"
            self.ui_queue.put(("exported", {"path": final, "model_id": manifest["model_id"]}))
        except Exception as exc:  # noqa: BLE001 - report any export failure.
            self.ui_queue.put(("fatal", {
                "text": str(exc), "trace": traceback.format_exc()}))

    # ----- Queue polling ---------------------------------------------------

    def _poll_ui_queue(self) -> None:
        """
        Drain worker messages and keep polling while a worker is active.
        ワーカーメッセージを処理し、ワーカー実行中はポーリングを継続する。
        """
        def _on_trained(payload):
            # Store the result before re-deriving control state: _set_running()
            # asks _update_controls_state() whether Export may be enabled, and
            # that check reads self._train_result, which _handle_trained sets.
            # The finally clause keeps the controls unlocked even if rendering
            # the metrics fails.
            try:
                self._handle_trained(payload)
            finally:
                self._set_running(False)
            # Prompt after _set_running(False): on_export() refuses to run while
            # a worker is still flagged as active.
            self._prompt_save_model()
            return False

        def _on_exported(payload):
            self._set_running(False)
            self._model_saved = True
            self._log(_("モデルを保存しました: {p}").format(p=payload["path"]))
            messagebox.showinfo(
                _("エクスポート完了"),
                _("モデル '{id}' を次へ保存しました:\n{p}").format(
                    id=payload["model_id"], p=payload["path"]))
            return False

        def _on_fatal(payload):
            self._set_running(False)
            messagebox.showerror(_("エラー"), payload.get("text", _("不明なエラー")))
            trace = payload.get("trace", "")
            if trace:
                self._log(trace)
            return False

        should_continue = drain_ui_queue(self.ui_queue, {
            "log": self._log,
            "trained": _on_trained,
            "exported": _on_exported,
            "fatal": _on_fatal,
        })
        if should_continue:
            self.after(50, self._poll_ui_queue)

    def _handle_trained(self, payload: Dict) -> None:
        """
        Store the trained model and show its metrics and feature importances.
        学習済みモデルを保存し、指標と特徴重要度を表示する。
        """
        result = payload["result"]
        self._train_result = result
        self._dataset_provenance = payload["provenance"]
        self._trained_kind = payload["kind"]
        self._trained_task = payload["task"]
        self._model_saved = False

        self._log(_("学習完了: {n} サンプル、{g} 画像グループ。").format(
            n=result.n_samples, g=result.n_groups))

        # Metrics table: mean/std per metric from cross-validation.
        # 指標テーブル：交差検証による指標ごとの平均/標準偏差。
        for item in self.metrics_tree.get_children():
            self.metrics_tree.delete(item)
        cv = result.cv_metrics
        if not cv:
            self._log(_("交差検証をスキップしました（画像グループが 2 つ以上必要）。"))
        rows = (_REGRESSION_METRIC_ROWS
                if self._trained_task in _REGRESSION_TASKS else _METRIC_ROWS)
        for metric in rows:
            mean = cv.get(f"{metric}_mean")
            std = cv.get(f"{metric}_std")
            if mean is None:
                continue
            self.metrics_tree.insert(
                "", tk.END,
                values=(metric, f"{mean:.4f}", f"{std:.4f}"))

        self._show_importances(result.feature_importances)

    def _show_importances(self, importances: Dict[str, float]) -> None:
        """
        Display feature importances sorted by descending weight.
        特徴重要度を重み降順で表示する。
        """
        self.importance_text.configure(state=tk.NORMAL)
        self.importance_text.delete("1.0", tk.END)
        if not importances:
            self.importance_text.insert(
                tk.END, _("（この分類器では利用できません）"))
        else:
            ranked = sorted(importances.items(), key=lambda kv: -kv[1])
            for name, weight in ranked:
                self.importance_text.insert(tk.END, f"{weight:7.4f}  {name}\n")
        self.importance_text.configure(state=tk.DISABLED)

    # ----- Log saving ------------------------------------------------------

    def on_save_log(self) -> None:
        """
        Save the log text to a file via the shared helper.
        共有ヘルパー経由でログテキストをファイルへ保存する。
        """
        save_text_widget_log(self, self.log_text)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
