# -*- coding: utf-8 -*-
"""
Apply a machine-learning binarization model and compare it to the classical result.
機械学習の二値化モデルを適用し、古典的な結果と比較する。

This GUI loads a ``.afmml`` binarization model, applies it to ``.b2z`` bundles,
and shows the model's mask beside the classical reference mask (the same label
the model was trained against) with agreement metrics. It is the maturity gate
for the ML binarization model: it is where a trained model is checked against
the classical pipeline before any decision to integrate it into GUI01. Inputs
are a ``.afmml`` model plus ``.b2z`` bundles; there is no output file (this is a
comparison tool).
本 GUI は ``.afmml`` 二値化モデルを読み込み、``.b2z`` バンドルへ適用し、モデルの
マスクを古典参照マスク（モデルが学習対象とした同じラベル）と並べて一致指標
とともに表示する。ML 二値化モデルの成熟度ゲートであり、学習済みモデルを GUI01
へ統合する判断の前に古典パイプラインと照合する場所である。入力は ``.afmml``
モデルと ``.b2z`` バンドルで、出力ファイルはない（比較ツール）。

The machine-learning libraries (onnxruntime and the feature stack) are imported
lazily inside the worker thread, so this plugin starts without them and reports
a clear install hint if applying a model needs them.
機械学習ライブラリ（onnxruntime と特徴スタック）はワーカースレッド内で遅延
import する。したがって本プラグインはそれら無しで起動し、モデル適用時に必要に
なれば明確な導入案内を表示する。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Values must remain plain string literals because they are passed to literal_eval.
# Main.py がこのファイルを AST 解析で読み取るため、値は literal_eval 可能な
# 文字列リテラルのままにする（_() で包まない）。
PLUGIN_INFO = {
    "name": "ML Model Compare",
    "description": (
        "Apply a trained .afmml preprocessing model to .b2z bundles and compare "
        "it against the classical result. A binarization or background-mask "
        "model is scored mask-to-mask with Dice / IoU / agreement; a "
        "background-surface model is scored in nanometers against the surface "
        "the pipeline subtracted. Use this to check whether an ML model is "
        "worth integrating before adding it to the preprocessing pipeline. "
        "The ML libraries are optional and loaded only when a model is applied."
    )
}

# ===== Standard library =====
import os
import queue
import threading
import traceback
from typing import Dict, List, Optional

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ===== Project libraries =====
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_ttk_theme, setup_matplotlib_style,
    create_scrolled_text, create_scrolled_treeview,
    compute_auto_vrange, ToolTip,
    save_figure_with_dialog, drain_ui_queue, LogMixin,
)

# Classical reference choices, mirroring lib.ml_dataset.LABEL_SOURCES. Each
# reference fixes the pipeline stage the comparison runs at, and `_compare_one`
# processes the model's mask to match that stage, so the two sides are always
# compared like-for-like:
#   - Binarized image in .b2z bundle (default): the final mask GUI01 saved
#     (thresholding + component filters). The model's mask is run through the
#     same component filters, so this scores the integrated end-to-end result.
#   - Segmenter intermediate (pre-filter): the per-pixel threshold mask before
#     the component filters -- the binarize model's actual training target. The
#     model's mask is compared raw, so this scores learning fidelity.
# 古典参照の選択肢。lib.ml_dataset.LABEL_SOURCES と一致。各参照は比較を行う
# パイプライン段を定め、`_compare_one` がモデルのマスクをその段に合わせて処理する
# ため、両者を常に同条件で比較できる：
#   - Binarized image in .b2z bundle（既定）：GUI01 が保存した最終マスク（しきい値
#     ＋成分フィルタ）。モデルのマスクにも同じ成分フィルタを掛けるので、統合後の
#     end-to-end 結果を採点する。
#   - Segmenter intermediate (pre-filter)：成分フィルタ前の画素単位しきい値マスク。
#     binarize モデルが実際に学習した対象。モデルのマスクは生のまま比較するので、
#     学習忠実度を採点する。
REFERENCE_LABELS = {
    "Binarized image in .b2z bundle": "bundle_binarized",
    "Segmenter intermediate (pre-filter)": "segmenter_intermediate",
}

# Subplot titles are fixed English plot text (not localized, per the UI-string
# policy for scientific/plot labels).
# サブプロットのタイトルは固定英語のプロット文字（科学的・プロットラベルの
# UI 文字列方針によりローカライズしない）。
_PANEL_TITLES = ("Calibrated", "ML mask", "Classical", "Difference")
_REGRESSION_PANEL_TITLES = (
    "Raw height", "ML background (nm)", "Classical background (nm)",
    "Difference (nm)")


class App(tk.Tk, LogMixin):
    """
    Main window for applying a model and comparing it to the classical mask.
    モデルを適用し古典マスクと比較するメインウィンドウ。
    """

    def __init__(self) -> None:
        """
        Initialize the window, state, controls, and figure.
        ウィンドウ・状態・操作部・図を初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])

        setup_matplotlib_style(font_size=10)
        self._clam_bg = setup_ttk_theme(self)
        apply_window_size(self, 1300, 820, min_w=1050, min_h=680)

        # Loaded model (lib.ml_model.LoadedModel) and its manifest; None until
        # a model is loaded.
        # 読み込み済みモデル（lib.ml_model.LoadedModel）とその manifest。
        # モデル読み込みまで None。
        self._model = None
        self._model_path: str = ""
        # Flat list of bundle paths added for comparison.
        # 比較用に追加したバンドルパスのフラットな一覧。
        self.bundles: List[str] = []
        # Aggregate metrics from the last "Compare all" run.
        # 直近の「Compare all」実行による集計指標。
        self._aggregate: Optional[Dict] = None

        self.ui_queue: queue.Queue = queue.Queue()
        self.is_running = False

        self._build_ui()
        self._log_initial_message()
        self._update_controls_state()

    # ----- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        """
        Build the two-pane layout: controls left, figure and metrics right.
        2 ペイン構成を構築する。左が操作部、右が図と指標。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=2)
        outer.add(right, weight=3)

        self._build_model_panel(left)
        self._build_reference_panel(left)
        self._build_image_panel(left)
        self._build_action_bar(left)

        self._build_figure_panel(right)
        self._build_metrics_panel(right)
        self._build_log_panel(right)

    def _build_model_panel(self, parent: ttk.Frame) -> None:
        """
        Build the model-load button and manifest-info display.
        モデル読み込みボタンと manifest 情報の表示を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("モデル（.afmml）"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        ttk.Button(lf, text=_("モデルを読み込み..."), command=self.on_load_model).pack(
            anchor="w", padx=6, pady=4)

        self.model_info_var = tk.StringVar(value=_("モデル未読み込み。"))
        ttk.Label(lf, textvariable=self.model_info_var, justify="left").pack(
            anchor="w", padx=6, pady=(0, 4))

    def _build_reference_panel(self, parent: ttk.Frame) -> None:
        """
        Build the classical-reference and threshold controls.
        古典参照としきい値の操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("比較"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        grid = ttk.Frame(lf)
        grid.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(grid, text=_("古典参照")).grid(
            row=0, column=0, sticky="w", padx=2, pady=2)
        self.reference_var = tk.StringVar(value=list(REFERENCE_LABELS)[0])
        self.reference_combo = ttk.Combobox(
            grid, textvariable=self.reference_var,
            values=list(REFERENCE_LABELS), state="readonly", width=30)
        self.reference_combo.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        # Re-render the currently selected image when the reference changes so
        # the right pane always shows the mask against the chosen reference.
        # 参照を切り替えたら選択中の画像を再描画し、右ペインが常に選択した参照に
        # 対するマスクを表示するようにする。
        self.reference_combo.bind(
            "<<ComboboxSelected>>", self._on_reference_changed)
        ToolTip(
            self.reference_combo,
            _("右ペインの Classical に表示する古典マスクを選びます。"
              "選んだ段にモデル出力もそろえて比較します。\n"
              "Binarized image in .b2z bundle: GUI01 が .b2z に保存した最終マスク"
              "（しきい値二値化＋小さい・低い・曲がった塊の除去）。モデル出力にも"
              "同じ除去処理を掛けて、統合後の実性能を比べます。\n"
              "Segmenter intermediate (pre-filter): 除去処理前の二値化だけのマスク。"
              "モデル出力も生のまま比べ、モデル自体の精度を見ます。"))

        ttk.Label(grid, text=_("ファイバーしきい値")).grid(
            row=1, column=0, sticky="w", padx=2, pady=2)
        # Blank means use the model's recorded threshold.
        # 空欄はモデルに記録されたしきい値を使う意味。
        self.threshold_var = tk.StringVar(value="")
        ttk.Entry(grid, textvariable=self.threshold_var, width=10).grid(
            row=1, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(grid, text=_("（空欄でモデル既定値）")).grid(
            row=1, column=2, sticky="w", padx=2, pady=2)

    def _build_image_panel(self, parent: ttk.Frame) -> None:
        """
        Build the bundle list and its add/remove controls.
        バンドル一覧と追加/削除操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("画像（.b2z バンドル）"))
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
            btn_row, text=_("削除"), command=self.on_remove)
        self.btn_remove.pack(side=tk.LEFT, padx=2)
        self.btn_clear = ttk.Button(
            btn_row, text=_("クリア"), command=self.on_clear)
        self.btn_clear.pack(side=tk.LEFT, padx=2)

        tree_frame = ttk.Frame(lf)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.tree, _sb = create_scrolled_treeview(
            tree_frame,
            columns=("bundle",),
            show="headings",
            selectmode="browse",
            height=8,
            headings={"bundle": _("バンドル")},
            column_options={"bundle": {"width": 240, "anchor": "w"}},
        )
        self.tree.bind("<<TreeviewSelect>>", self._on_select_image)

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        """
        Build the compare-all button and progress indicator.
        全比較ボタンと進捗表示を構築する。
        """
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, padx=4, pady=(2, 6))

        self.btn_compare_all = ttk.Button(
            bar, text=_("全比較"), command=self.on_compare_all)
        self.btn_compare_all.pack(side=tk.LEFT, padx=2)
        self.btn_save_fig = ttk.Button(
            bar, text=_("図を保存..."), command=self.on_save_figure)
        self.btn_save_fig.pack(side=tk.LEFT, padx=2)

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=130)
        self.progress.pack(side=tk.RIGHT, padx=4)

    def _build_figure_panel(self, parent: ttk.Frame) -> None:
        """
        Build the 2x2 comparison figure embedded in the window.
        ウィンドウに埋め込む 2x2 比較図を構築する。
        """
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig = plt.Figure(figsize=(6.4, 6.0), dpi=90)
        self.axes = self.fig.subplots(2, 2)
        for ax, title in zip(self.axes.ravel(), _PANEL_TITLES):
            ax.set_title(title)
            ax.axis("off")
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()

    def _build_metrics_panel(self, parent: ttk.Frame) -> None:
        """
        Build the metrics text area.
        指標テキスト領域を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("指標"))
        lf.pack(fill=tk.X, padx=4, pady=4)
        self.metrics_text, _sb = create_scrolled_text(lf, height=6, width=40)
        self.metrics_text.configure(state=tk.DISABLED)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log text area.
        ログテキスト領域を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ログ"))
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.log_text, _sb = create_scrolled_text(lf, height=5, width=40)
        self.log_text.configure(state=tk.DISABLED)

    # ----- Logging ---------------------------------------------------------
    # `_log` / `_log_exception` come from LogMixin (they drive self.log_text).
    # `_log` / `_log_exception` は LogMixin 由来（self.log_text を操作する）。

    def _log_initial_message(self) -> None:
        """
        Log a short usage hint at startup.
        起動時に短い使い方の案内をログへ表示する。
        """
        self._log(_(".afmml モデルを読み込み .b2z バンドルを追加し、"
                    "画像を選択して比較するか Compare all を使います。"))

    # ----- Model loading ---------------------------------------------------

    def on_load_model(self) -> None:
        """
        Load and validate a ``.afmml`` binarization model.
        ``.afmml`` 二値化モデルを読み込み検証する。
        """
        path = filedialog.askopenfilename(
            title=_(".afmml モデルを選択"),
            filetypes=[("AFM ML model", "*.afmml"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            from lib import ml_model as mm
            from lib.ml_schema import (
                BACKGROUND_TASKS, SEGMENTATION_TASKS, validate_manifest)
        except ImportError as exc:
            messagebox.showerror(
                _("エラー"),
                _("機械学習ライブラリがインストールされていません。\n{err}")
                .format(err=str(exc)))
            return
        try:
            model = mm.load_model(path)
        except Exception as exc:  # noqa: BLE001 - report any load failure.
            messagebox.showerror(_("読み込みに失敗しました"), str(exc))
            return

        # Every per-pixel model can be compared here; a fragment-pair
        # (`connect`) model cannot, and is rejected with a message naming the
        # accepted tasks rather than producing a silently wrong result.
        # 画素単位モデルはいずれもここで比較できる。断片ペア（`connect`）モデルは
        # 比較できないため、受理タスクを明示して拒否し、黙って誤った結果を
        # 出さない。
        accepted = tuple(SEGMENTATION_TASKS) + tuple(BACKGROUND_TASKS)
        problems = validate_manifest(model.manifest, require_task=accepted)
        if problems:
            messagebox.showerror(_("モデルが不適切"), "; ".join(problems))
            return

        self._model = model
        self._model_path = path
        self._show_model_info(model)
        self._log(_("モデルを読み込みました: {p}").format(p=os.path.basename(path)))
        self._update_controls_state()

    def _show_model_info(self, model) -> None:
        """
        Display key manifest fields for the loaded model.
        読み込んだモデルの主要 manifest 項目を表示する。
        """
        m = model.manifest
        dice = ""
        metrics = m.get("metrics") or {}
        if "dice_mean" in metrics:
            # Fixed metric label; only the surrounding text is localized.
            # 指標ラベルは固定。周囲の文のみローカライズする。
            dice = "  CV dice={:.4f}".format(metrics["dice_mean"])
        self.model_info_var.set(
            _("id: {id}\ntask: {task}  しきい値: {thr}{dice}").format(
                id=m.get("model_id", "?"), task=m.get("task", "?"),
                thr=model.fiber_threshold, dice=dice))

    # ----- Image list management ------------------------------------------

    def on_add_folder(self) -> None:
        """
        Add every ``.b2z`` file in a chosen folder.
        選択したフォルダ内の全 ``.b2z`` ファイルを追加する。
        """
        folder = filedialog.askdirectory(title=_(".b2z バンドルを含むフォルダを選択"))
        if not folder:
            return
        paths = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                 if n.lower().endswith(".b2z")]
        self._add_paths(paths)

    def on_add_files(self) -> None:
        """
        Add chosen ``.b2z`` files.
        選択した ``.b2z`` ファイルを追加する。
        """
        paths = filedialog.askopenfilenames(
            title=_(".b2z バンドルファイルを選択"),
            filetypes=[("b2z bundles", "*.b2z"), ("All files", "*.*")])
        self._add_paths(list(paths))

    def _add_paths(self, paths: List[str]) -> None:
        """
        Append new bundle paths, skipping duplicates, and add tree rows.
        新しいバンドルパスを追加し、重複を省いて行を挿入する。
        """
        existing = set(self.bundles)
        added = 0
        for p in paths:
            if p in existing:
                continue
            existing.add(p)
            self.bundles.append(p)
            self.tree.insert("", tk.END, values=(os.path.basename(p),))
            added += 1
        self._update_controls_state()
        if added == 0 and paths:
            self._log(_("選択したバンドルはすべて既に一覧にあります。"))

    def on_remove(self) -> None:
        """
        Remove the selected bundle from the list.
        選択したバンドルを一覧から削除する。
        """
        selected = self.tree.selection()
        if not selected:
            return
        for iid in sorted((self.tree.index(i) for i in selected), reverse=True):
            self.tree.delete(self.tree.get_children()[iid])
            del self.bundles[iid]
        self._update_controls_state()

    def on_clear(self) -> None:
        """
        Remove all bundles from the list.
        一覧から全バンドルを削除する。
        """
        self.bundles = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._update_controls_state()

    # ----- Controls state --------------------------------------------------

    def _update_controls_state(self) -> None:
        """
        Enable Compare all only when a model and at least one bundle exist.
        モデルとバンドルが 1 つ以上あるときのみ Compare all を有効化する。
        """
        if self.is_running:
            return
        ready = self._model is not None and bool(self.bundles)
        self.btn_compare_all.configure(state=tk.NORMAL if ready else tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        """
        Toggle controls and the progress bar while a worker is active.
        ワーカー実行中に操作部と進捗バーを切り替える。
        """
        self.is_running = running
        state = tk.DISABLED if running else tk.NORMAL
        for b in (self.btn_add_folder, self.btn_add_files, self.btn_remove,
                  self.btn_clear, self.btn_compare_all):
            b.configure(state=state)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()
            self._update_controls_state()

    # ----- Threshold -------------------------------------------------------

    def _resolved_threshold(self) -> Optional[float]:
        """
        Return the override threshold, or None to use the model default.
        上書きしきい値を返す。モデル既定を使う場合は None。

        Raises
        ------
        ValueError
            If the entry is non-empty and not a number in ``[0, 1]``.
            入力が空でなく、``[0, 1]`` の数値でない場合。
        """
        txt = self.threshold_var.get().strip()
        if txt == "":
            return None
        value = float(txt)
        if not (0.0 <= value <= 1.0):
            raise ValueError(_("ファイバーしきい値は 0〜1 の範囲で指定してください。"))
        return value

    # ----- Single-image comparison ----------------------------------------

    def _on_reference_changed(self, _event=None) -> None:
        """
        Re-render the current single-image comparison with the new reference.
        参照を切り替えたとき、現在の単一画像比較を新しい参照で再描画する。

        Delegates to `_on_select_image`, which reads the tree selection and the
        reference dropdown together, so switching the reference recomputes the
        right-pane masks and metrics against the newly chosen classical
        reference. It is a no-op when no model is loaded or no image is selected.
        `_on_select_image` に委譲する。ツリー選択と参照ドロップダウンを併せて読む
        ため、参照を切り替えると右ペインのマスクと指標が新しい古典参照で再計算
        される。モデル未読み込みまたは画像未選択のときは何もしない。
        """
        self._on_select_image()

    def _on_select_image(self, _event=None) -> None:
        """
        Compare the selected bundle in a worker and draw the result.
        選択したバンドルをワーカーで比較し、結果を描画する。
        """
        if self.is_running or self._model is None:
            return
        selected = self.tree.selection()
        if not selected:
            return
        idx = self.tree.index(selected[0])
        path = self.bundles[idx]
        try:
            threshold = self._resolved_threshold()
        except ValueError as exc:
            messagebox.showerror(_("入力エラー"), str(exc))
            return

        reference = REFERENCE_LABELS[self.reference_var.get()]
        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("{name} を比較中...").format(name=os.path.basename(path)))
        threading.Thread(
            target=self._worker_compare_one,
            args=(path, reference, threshold), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _compare_one(
        self, path: str, reference: str, threshold: Optional[float]
    ) -> Dict:
        """
        Apply the model to one bundle and score it against the classical result.
        1 バンドルへモデルを適用し、古典的な結果と照合して採点する。

        Dispatches on the model's task: a classifier is compared mask-to-mask,
        while the background-surface regressor is compared in nanometers
        against the surface the pipeline actually subtracted.
        モデルのタスクで振り分ける。分類器はマスク同士で比較し、背景面回帰器は
        パイプラインが実際に差し引いた背景面と nm 単位で比較する。
        """
        from lib import ml_dataset as md

        task = self._model.task
        image, classical = md.load_image_and_label(
            path, task=task, label_source=reference)

        if self._model.is_regression:
            predicted = self._model.predict_surface(image)
            metrics = _surface_metrics(predicted, classical)
            panels = (image, predicted, classical, predicted - classical)
        else:
            predicted = self._model.predict_mask(image, threshold=threshold)
            # For the post-filter reference, put the model's mask through the
            # same component filters the pipeline applies, so both sides sit at
            # the same stage (fair end-to-end) instead of raw-vs-filtered. Only
            # the binarize task has these filters; other mask tasks (e.g.
            # bg_mask) are compared as raw predictions.
            # フィルタ後の参照では、モデルのマスクにもパイプラインと同じ成分
            # フィルタを掛け、両者を同じ段にそろえる（統合後の end-to-end）。
            # このフィルタを持つのは binarize タスクのみで、他のマスクタスク
            # （例：bg_mask）は生の予測のまま比較する。
            if task == "binarize" and reference == md.LABEL_BUNDLE_BINARIZED:
                predicted = md.apply_pipeline_component_filters(path, predicted, image)
            classical = classical.astype(bool)
            metrics = _mask_metrics(predicted, classical)
            panels = (image, predicted, classical,
                      predicted.astype(np.int8) - classical.astype(np.int8))

        return {
            "name": os.path.basename(path),
            "task": task,
            "regression": self._model.is_regression,
            "panels": panels,
            "metrics": metrics,
        }

    def _worker_compare_one(
        self, path: str, reference: str, threshold: Optional[float]
    ) -> None:
        """
        Compute the model mask, classical mask, and metrics for one bundle.
        1 バンドルのモデルマスク・古典マスク・指標を計算する。
        """
        try:
            from lib import ml_dataset as md
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return
        try:
            payload = self._compare_one(path, reference, threshold)
            self.ui_queue.put(("compared_one", payload))
        except Exception as exc:  # noqa: BLE001 - report any comparison failure.
            self.ui_queue.put(("fatal", {
                "text": str(exc), "trace": traceback.format_exc()}))

    # ----- Compare all -----------------------------------------------------

    def on_compare_all(self) -> None:
        """
        Compute aggregate agreement metrics over every bundle in a worker.
        全バンドルにわたる集計一致指標をワーカーで計算する。
        """
        if self.is_running or self._model is None or not self.bundles:
            return
        try:
            threshold = self._resolved_threshold()
        except ValueError as exc:
            messagebox.showerror(_("入力エラー"), str(exc))
            return

        reference = REFERENCE_LABELS[self.reference_var.get()]
        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("全 {n} バンドルを比較中...").format(n=len(self.bundles)))
        threading.Thread(
            target=self._worker_compare_all,
            args=(list(self.bundles), reference, threshold), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _worker_compare_all(
        self, paths: List[str], reference: str, threshold: Optional[float]
    ) -> None:
        """
        Accumulate per-image metrics across all bundles off the main thread.
        メインスレッド外で全バンドルの画像ごと指標を積算する。
        """
        try:
            from lib import ml_dataset as md
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return

        per_image: List[Dict] = []
        for i, path in enumerate(paths, start=1):
            name = os.path.basename(path)
            try:
                metrics = self._compare_one(path, reference, threshold)["metrics"]
                metrics["name"] = name
                per_image.append(metrics)
                self.ui_queue.put(("log", _("[{i}/{n}] {name}: {s}").format(
                    i=i, n=len(paths), name=name, s=_summarize_metrics(metrics))))
            except Exception as exc:  # noqa: BLE001 - skip a failed bundle, keep going.
                self.ui_queue.put(("log", _("[{i}/{n}] {name}: スキップ（{err}）").format(
                    i=i, n=len(paths), name=name, err=str(exc))))

        if not per_image:
            self.ui_queue.put(("fatal", {"text": _("比較できるバンドルがありませんでした。")}))
            return
        self.ui_queue.put(("compared_all", {"per_image": per_image}))

    # ----- Queue polling ---------------------------------------------------

    def _poll_ui_queue(self) -> None:
        """
        Drain worker messages and keep polling while a worker is active.
        ワーカーメッセージを処理し、ワーカー実行中はポーリングを継続する。
        """
        def _on_compared_one(payload):
            self._set_running(False)
            self._draw_comparison(payload)
            self._show_single_metrics(payload["name"], payload["metrics"])
            return False

        def _on_compared_all(payload):
            self._set_running(False)
            self._show_aggregate_metrics(payload["per_image"])
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
            "compared_one": _on_compared_one,
            "compared_all": _on_compared_all,
            "fatal": _on_fatal,
        })
        if should_continue:
            self.after(50, self._poll_ui_queue)

    # ----- Rendering -------------------------------------------------------

    def _draw_comparison(self, payload: Dict) -> None:
        """
        Draw the calibrated image, both masks, and their difference.
        補正画像・両マスク・その差分を描画する。
        """
        image, predicted, classical, diff = payload["panels"]
        regression = payload.get("regression", False)
        titles = _REGRESSION_PANEL_TITLES if regression else _PANEL_TITLES

        # compute_auto_vrange always returns an int (vmin, vmax), falling back
        # to DEFAULT_VMIN/DEFAULT_VMAX for empty or all-NaN images.
        # compute_auto_vrange は常に int の (vmin, vmax) を返し、空または全 NaN の
        # 画像では DEFAULT_VMIN/DEFAULT_VMAX にフォールバックする。
        vmin, vmax = compute_auto_vrange(image)

        span, s_min, s_max = 1.0, 0.0, 1.0
        if regression:
            # The two surfaces share one range so they are visually comparable,
            # and the difference gets a symmetric range centred on zero so that
            # over- and under-estimation are distinguishable by colour.
            # 2 枚の背景面は視覚的に比較できるよう同一レンジを共有し、差分は
            # ゼロ中心の対称レンジとして過大推定と過小推定を色で区別できるようにする。
            both = np.concatenate([np.ravel(predicted), np.ravel(classical)])
            s_min, s_max = float(np.min(both)), float(np.max(both))
            span = float(np.max(np.abs(diff))) or 1.0

        for ax, title, data in zip(
            self.axes.ravel(), titles, (image, predicted, classical, diff)
        ):
            ax.clear()
            ax.set_title(title)
            ax.axis("off")
            if title in ("Calibrated", "Raw height"):
                ax.imshow(data, cmap="afmhot", vmin=vmin, vmax=vmax)
            elif title.startswith("Difference"):
                limit = span if regression else 1
                ax.imshow(data, cmap="bwr", vmin=-limit, vmax=limit)
            elif regression:
                ax.imshow(data, cmap="afmhot", vmin=s_min, vmax=s_max)
            else:
                ax.imshow(data, cmap="gray", vmin=0, vmax=1)
        self.fig.tight_layout()
        self.canvas.draw()

    def _show_single_metrics(self, name: str, metrics: Dict) -> None:
        """
        Show agreement metrics for the selected image.
        選択画像の一致指標を表示する。
        """
        # Metric names (dice, iou, ...) are fixed English; the header line is
        # localized. Keep the model-vs-classical framing explicit.
        # 指標名（dice, iou, ...）は固定英語。見出し行はローカライズする。
        lines = [_("選択中: {name}").format(name=name)]
        if "dice" in metrics:
            lines.append("  dice={dice:.4f}  iou={iou:.4f}".format(**metrics))
            lines.append(
                "  agreement={agreement:.4f}  ".format(**metrics)
                + "ml_fiber={ml_fiber:.4f}  classical_fiber={cl_fiber:.4f}".format(
                    ml_fiber=metrics["ml_fiber_frac"],
                    cl_fiber=metrics["classical_fiber_frac"]))
        else:
            lines.append(
                "  mae={mae_nm:.3f} nm  rmse={rmse_nm:.3f} nm".format(**metrics))
            lines.append(
                "  bias={bias_nm:+.3f} nm  max_abs={max_abs_nm:.3f} nm".format(**metrics))
        self._set_metrics_text("\n".join(lines))

    def _show_aggregate_metrics(self, per_image: List[Dict]) -> None:
        """
        Show mean/min/max of the per-image agreement metrics.
        画像ごと一致指標の平均/最小/最大を表示する。
        """
        self._aggregate = per_image
        lines = [_("{n} 画像の集計:").format(n=len(per_image))]
        if "dice" in per_image[0]:
            dice = np.array([m["dice"] for m in per_image], dtype=float)
            iou = np.array([m["iou"] for m in per_image], dtype=float)
            agree = np.array([m["agreement"] for m in per_image], dtype=float)
            lines += [
                "  dice  mean={:.4f}  min={:.4f}  max={:.4f}".format(
                    dice.mean(), dice.min(), dice.max()),
                "  iou   mean={:.4f}  min={:.4f}  max={:.4f}".format(
                    iou.mean(), iou.min(), iou.max()),
                "  agreement mean={:.4f}".format(agree.mean()),
                "",
                _("dice 下位 3 件:"),
            ]
            worst = sorted(per_image, key=lambda m: m["dice"])[:3]
            for m in worst:
                lines.append("  {name}: dice={dice:.4f}".format(**m))
        else:
            mae = np.array([m["mae_nm"] for m in per_image], dtype=float)
            rmse = np.array([m["rmse_nm"] for m in per_image], dtype=float)
            bias = np.array([m["bias_nm"] for m in per_image], dtype=float)
            lines += [
                "  mae  mean={:.3f} nm  min={:.3f}  max={:.3f}".format(
                    mae.mean(), mae.min(), mae.max()),
                "  rmse mean={:.3f} nm".format(rmse.mean()),
                "  bias mean={:+.3f} nm".format(bias.mean()),
                "",
                _("mae 上位 3 件:"),
            ]
            worst = sorted(per_image, key=lambda m: -m["mae_nm"])[:3]
            for m in worst:
                lines.append("  {name}: mae={mae_nm:.3f} nm".format(**m))
        self._set_metrics_text("\n".join(lines))
        self._log(_("全比較完了: {n} 画像。").format(n=len(per_image)))

    def _set_metrics_text(self, text: str) -> None:
        """
        Replace the metrics text area content.
        指標テキスト領域の内容を置き換える。
        """
        self.metrics_text.configure(state=tk.NORMAL)
        self.metrics_text.delete("1.0", tk.END)
        self.metrics_text.insert(tk.END, text)
        self.metrics_text.configure(state=tk.DISABLED)

    def on_save_figure(self) -> None:
        """
        Save the current comparison figure via the shared helper.
        現在の比較図を共有ヘルパー経由で保存する。
        """
        save_figure_with_dialog(self, self.fig, initial_name="ml_comparison")


def _surface_metrics(predicted: np.ndarray, classical: np.ndarray) -> Dict:
    """
    Compare a predicted background surface with the pipeline's, in nanometers.
    予測した背景面をパイプラインのものと nm 単位で比較する。

    Reported in the target's own unit so the numbers read directly as the height
    error the correction would introduce. ``bias`` is the signed mean error: a
    nonzero bias shifts every corrected height, which matters more for fiber
    height measurement than a symmetric spread of the same magnitude.
    ターゲット自身の単位で報告し、補正が持ち込む高さ誤差としてそのまま読める
    ようにする。``bias`` は符号付き平均誤差で、ゼロでない偏りは補正後の全高さを
    ずらす。これは同じ大きさの対称的なばらつきより繊維高さ計測に効く。
    """
    diff = np.asarray(predicted, dtype=float) - np.asarray(classical, dtype=float)
    return {
        "mae_nm": float(np.mean(np.abs(diff))),
        "rmse_nm": float(np.sqrt(np.mean(diff ** 2))),
        "bias_nm": float(np.mean(diff)),
        "max_abs_nm": float(np.max(np.abs(diff))) if diff.size else 0.0,
    }


def _summarize_metrics(metrics: Dict) -> str:
    """
    Format a one-line summary of whichever metric family a result carries.
    結果が持つ指標系統に応じた 1 行要約を整形する。
    """
    if "dice" in metrics:
        return "dice={:.4f}".format(metrics["dice"])
    return "mae={:.3f} nm".format(metrics.get("mae_nm", float("nan")))


def _mask_metrics(ml_mask: np.ndarray, classical: np.ndarray) -> Dict:
    """
    Compute agreement metrics between a model mask and the classical mask.
    モデルマスクと古典マスクの一致指標を計算する。

    Parameters
    ----------
    ml_mask, classical
        Boolean masks of the same shape; ``True`` marks fiber.
        同形状の真偽マスク。``True`` が繊維。

    Returns
    -------
    dict
        ``dice``, ``iou``, ``agreement`` (fraction of pixels that agree), and
        the fiber fractions of each mask. Dice/IoU are for the fiber class; an
        empty-vs-empty case scores 1.0 (perfect agreement on "no fiber").
        ``dice``、``iou``、``agreement``（一致画素の割合）、各マスクの繊維率。
        Dice/IoU は繊維クラスに対する値で、両者とも空の場合は 1.0（「繊維なし」
        で完全一致）とする。
    """
    a = ml_mask.astype(bool)
    b = classical.astype(bool)
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    a_sum = int(np.count_nonzero(a))
    b_sum = int(np.count_nonzero(b))
    n = a.size

    # Both empty: define as perfect agreement on the fiber class rather than 0/0.
    # 両方空：0/0 ではなく繊維クラスで完全一致と定義する。
    dice = 1.0 if (a_sum + b_sum) == 0 else (2.0 * inter) / (a_sum + b_sum)
    iou = 1.0 if union == 0 else inter / union
    agreement = float(np.count_nonzero(a == b)) / n if n else 1.0
    return {
        "dice": float(dice),
        "iou": float(iou),
        "agreement": float(agreement),
        "ml_fiber_frac": (a_sum / n) if n else 0.0,
        "classical_fiber_frac": (b_sum / n) if n else 0.0,
    }


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
