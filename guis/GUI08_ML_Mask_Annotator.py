# -*- coding: utf-8 -*-
"""
Correct a pipeline mask by hand and record the corrections for training.
パイプラインのマスクを手で修正し、その修正を学習用に記録する。

The pixel models for binarization and the background fiber mask are trained by
distillation: their labels are the masks the classical pipeline computes. A
model taught only from those can imitate the pipeline but never beat it. This
GUI is where a person supplies the judgements that lift that ceiling. It loads a
``.b2z`` bundle, rebuilds exactly the mask the trainer would use as its label,
lets the reviewer paint corrections onto it, and writes them to a sidecar beside
the bundle. Output is one ``<stem>_mask_labels.b2z`` per bundle; the ``.b2z``
itself is never modified.
二値化と背景繊維マスクの画素モデルは蒸留で学習する。ラベルは古典パイプラインが計算
するマスクである。それだけで学習したモデルはパイプラインを模倣できても上回れない。
本 GUI は、その上限を外す判断を人が与える場所である。``.b2z`` バンドルを読み込み、
学習側がラベルとして使うのと厳密に同じマスクを再構築し、検分者がその上に修正を描き、
バンドルの隣の sidecar へ書き出す。出力はバンドルごとに 1 つの
``<stem>_mask_labels.b2z`` で、``.b2z`` 自体は決して変更しない。

What you see and what is stored / 表示するものと保存するもの
--------------------------------------------------------------
The editing pane shows the corrected mask itself -- white fiber on black
background -- either alone or over the height image, because the judgement being
made is about the mask, and comparing a mask against a colored height map is
harder than reading the mask directly. Three previews below it show the height
image, the pipeline's own mask, and the corrected mask side by side, so what the
corrections changed stays visible while working.
編集ペインは修正後のマスクそのものを表示する。黒い背景に白い繊維であり、マスク単独と
高さ画像への重ね描きを切り替えられる。下すべき判断はマスクについてのものであり、色付き
の高さマップとマスクを見比べるより、マスクを直接読む方が易しいためである。その下の 3 面
プレビューは高さ画像・パイプラインのマスク・修正後のマスクを並べ、作業中も修正が何を
変えたかを見えるようにする。

Painting edits the mask, and what the sidecar stores is where that mask ends up
differing from the pipeline's -- a three-valued edit layer derived at save time,
never a finished mask. Keeping the difference rather than the result is what
lets a pixel a person changed stay distinguishable from a pixel the algorithm
happened to get right that nobody examined; the contract and the reasoning
behind it live in `lib.ml_mask_labels`.
ペイントはマスクを編集する操作であり、sidecar が保存するのは、そのマスクが最終的に
パイプラインのものと食い違った箇所である。すなわち保存時に導出する 3 値の編集レイヤで
あって、完成マスクではない。結果ではなく差分を保つことにより、人が変更した画素と、
たまたまアルゴリズムが正解していて誰も見ていない画素とを区別できる。契約とその論拠は
`lib.ml_mask_labels` にある。

Because the record is the difference, painting is exactly as idempotent as it
looks: brushing fiber over a pixel the pipeline already calls fiber changes
nothing and records nothing, and brushing a mistakenly flipped pixel back to the
pipeline's answer removes the judgement instead of asserting the opposite one.
No separate eraser is needed, and no judgement can be recorded that the mask
does not show.
記録が差分であるため、ペイントは見た目どおりに冪等である。パイプラインが既に繊維と
呼んでいる画素へ繊維を塗っても何も変わらず何も記録されない。誤って反転させた画素を
パイプラインの答えへ塗り戻せば、逆の主張を立てるのではなく判断そのものが取り除かれる。
専用の消しゴムは不要であり、マスクが示していない判断が記録されることもない。

The base mask comes from the trainer's own code path / ベースは学習側と同じ経路
--------------------------------------------------------------------------------
The mask shown here is produced by `lib.ml_dataset.load_image_and_label`, the
same function the trainer calls per bundle. Reimplementing the base locally
would let the two drift apart, and a correction drawn over a slightly different
mask means something slightly different from what is trained on -- a discrepancy
that raises nothing and shows up only as worse accuracy.
ここに表示するマスクは `lib.ml_dataset.load_image_and_label` が生成する。学習側が
バンドルごとに呼ぶのと同じ関数である。ベースをここで作り直せば両者はずれうるし、
わずかに異なるマスクの上に描かれた修正は、学習される内容とわずかに異なる意味を持つ。
これは例外を出さず、精度の悪化としてしか現れない差異である。

This is an annotation tool, not a measurement tool. GUI01 remains the place
preprocessing is run and is not modified: a model must first be shown to beat
the classical pipeline in GUI06 before it is offered there.
本ツールはアノテーション用であり計測用ではない。前処理を実行する場所は GUI01 の
ままで、GUI01 は変更しない。モデルは GUI06 で古典パイプラインを上回ると示せてから、
はじめて GUI01 で提供される。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Values must remain plain string literals because they are passed to literal_eval.
# Main.py がこのファイルを AST 解析で読み取るため、値は literal_eval 可能な
# 文字列リテラルのままにする（_() で包まない）。
PLUGIN_INFO = {
    "name": "ML Mask Annotator",
    "description": (
        "Paint corrections onto the pipeline mask a .b2z bundle would train "
        "the ML Model Trainer with, for the binarization or background "
        "fiber-candidate task. Brush pixels to fiber or to background, either "
        "on the mask alone or over the height image, compare the result "
        "against the pipeline's own mask in the previews, and save to a "
        "mask-label file beside the bundle; the bundle itself is never "
        "modified. Those corrections let a model improve on the classical "
        "pipeline instead of only imitating it."
    )
}

# ===== Standard library =====
import os
import queue
import threading
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# ===== Project libraries =====
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_ttk_theme, setup_matplotlib_style,
    create_scrolled_text, compute_auto_vrange,
    save_figure_with_dialog, drain_ui_queue, LogMixin, ToolTip,
)

# Mask values a brush writes. These are mask values, not edit-layer values: the
# reviewer paints the mask, and which pixels count as a judgement follows from
# where that mask ends up differing from the pipeline's (see `_edit_layer`).
# ブラシが書き込むマスクの値。編集レイヤの値ではなくマスクの値である。検分者は
# マスクを塗り、どの画素が判断にあたるかは、そのマスクがパイプラインのものと
# 食い違った箇所から決まる（`_edit_layer` 参照）。
PAINT_FIBER = 1
PAINT_BACKGROUND = 0

# Paintable tasks, mapping display label -> fixed task identifier (the
# vocabulary is owned by lib.ml_schema and narrowed to masks by
# lib.ml_mask_labels.MASK_LABEL_TASKS).
# ペイント可能なタスク。表示ラベル -> 固定のタスク識別子（語彙は lib.ml_schema が
# 持ち、lib.ml_mask_labels.MASK_LABEL_TASKS がマスクに限定する）。
TASK_LABELS = {
    "Binarization (calibrated -> fiber mask)": "binarize",
    "Background mask (raw -> fiber candidates)": "bg_mask",
}

# Editing-pane view modes. Fixed English identifiers held by the radio buttons;
# their visible labels are localized separately.
# 編集ペインの表示モード。ラジオボタンが保持する固定英語の識別子で、表示ラベルは
# 別途ローカライズする。
VIEW_MASK_ONLY = "mask"
VIEW_OVERLAY = "overlay"

# Colormaps. The mask is plain black/white so the edited shape is read directly.
# The height image uses `afmhot`, the same map the rest of the project uses for
# AFM height, so a scan looks here the way it looks in the other GUIs.
# カラーマップ。マスクは編集した形を直接読めるよう単純な白黒とする。高さ画像は
# プロジェクトの他所が AFM の高さに用いるのと同じ `afmhot` を使い、走査が他の GUI
# と同じ見え方になるようにする。
MASK_CMAP = "gray"
HEIGHT_CMAP = "afmhot"

# Opacity of each layer in the combined view. Both are translucent so neither
# reads as solid: an opaque height image hides the mask's exact edge, while an
# opaque mask hides the height evidence the judgement is based on. Seeing both
# at once is the whole point of that view.
# 重ね表示における各層の不透明度。どちらも半透明にし、いずれも塗りつぶしに見えない
# ようにする。高さ画像が不透明だとマスクの正確な境界が隠れ、マスクが不透明だと判断の
# 根拠である高さの情報が隠れる。両方を同時に見ることがこの表示の目的である。
OVERLAY_IMAGE_ALPHA = 0.65
MASK_OVERLAY_RGBA = np.array((0.13, 0.59, 0.95, 0.50), dtype=np.float32)
CLEAR_RGBA = np.zeros(4, dtype=np.float32)

# Titles of the three comparison previews, per task. Fixed English: these are
# plot titles, not localized UI text.
# タスクごとの 3 面比較プレビューの見出し。固定英語：プロットのタイトルであり、
# ローカライズ対象の UI 文字列ではない。
PREVIEW_TITLES = {
    "binarize": ("Calibrated", "Pipeline mask", "Corrected mask"),
    "bg_mask": ("Raw height", "Pipeline mask", "Corrected mask"),
}

# Brush radius bounds in image pixels. One pixel is the finest correction the
# label format can express; the upper bound keeps a stray drag from repainting
# a whole scan.
# 画像画素単位のブラシ半径の範囲。1 画素はラベル形式が表現できる最小の修正である。
# 上限は、誤ったドラッグが走査全体を塗り替えるのを防ぐ。
BRUSH_MIN = 1
BRUSH_MAX = 40
BRUSH_DEFAULT = 3

# How many strokes can be undone. Each level holds one copy of the edit layer
# (one byte per pixel), so twenty levels stay small even for a large scan.
# 取り消せるストローク数。各段は編集レイヤの複製 1 つ（1 画素 1 バイト）を保持する
# ため、大きな走査でも 20 段は小さく収まる。
UNDO_LIMIT = 20


class App(tk.Tk, LogMixin):
    """
    Main window for painting and saving mask corrections.
    マスク修正の描画と保存を行うメインウィンドウ。
    """

    def __init__(self) -> None:
        """
        Initialize the window, state, controls, and figures.
        ウィンドウ・状態・操作部・図を初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])

        setup_matplotlib_style(font_size=10)
        self._clam_bg = setup_ttk_theme(self)
        apply_window_size(self, 1320, 960, min_w=1050, min_h=760)

        # Loaded bundle state; all None/empty until a bundle is opened.
        # 読み込んだバンドルの状態。バンドルを開くまではすべて None／空。
        self._bundle_path: str = ""
        self._task: str = ""
        self._image: Optional[np.ndarray] = None
        self._base_label: Optional[np.ndarray] = None
        # The corrected mask is the only edit state held: it is what the pane
        # draws, what a stroke updates, and what the saved edit layer is derived
        # from. Tracking an edit layer alongside it would be a second copy of
        # the same information that could fall out of step with the display.
        # 保持する編集状態は修正後のマスクだけである。ペインが描画し、ストロークが
        # 更新し、保存する編集レイヤの導出元にもなる。編集レイヤを並行して持つと、
        # 同じ情報の 2 つ目の複製となり、表示とずれうる。
        self._mask: Optional[np.ndarray] = None
        self._image_hash: str = ""
        self._input_sha256: Optional[str] = None
        # True when a sidecar exists but does not describe the loaded image, so
        # saving would overwrite someone's work for a different bundle state.
        # sidecar は存在するが読み込んだ画像を記述していない場合に True。保存すると
        # 別の状態に対する誰かの作業を上書きすることになる。
        self._stale_sidecar: bool = False
        self._dirty: bool = False

        # Undo stack of whole masks; see UNDO_LIMIT.
        # マスク全体の取り消しスタック。UNDO_LIMIT 参照。
        self._undo: List[np.ndarray] = []
        self._stroke_active: bool = False
        self._last_point: Optional[Tuple[int, int]] = None

        # Matplotlib artists kept so a stroke updates pixels instead of
        # redrawing the whole figure (see `_refresh_view`).
        # ストロークが図全体を描き直さず画素だけを更新できるよう保持する
        # Matplotlib のアーティスト（`_refresh_view` 参照）。
        self._mask_artist = None
        self._overlay: Optional[np.ndarray] = None
        self._overlay_artist = None
        self._preview_mask_artist = None

        self.ui_queue: queue.Queue = queue.Queue()
        self.is_running = False

        self._build_ui()
        self._log_initial_message()
        self._update_controls_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        """
        Build the two-pane layout: controls left, editor and previews right.
        2 ペイン構成を構築する。左が操作部、右が編集ペインとプレビュー。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=4)

        self._build_bundle_panel(left)
        self._build_brush_panel(left)
        self._build_action_bar(left)

        self._build_figure_panel(right)
        self._build_preview_panel(right)
        self._build_log_panel(right)

    def _build_bundle_panel(self, parent: ttk.Frame) -> None:
        """
        Build the task selector and the bundle-open control.
        タスク選択とバンドルを開く操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("バンドル（.b2z）"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        row = ttk.Frame(lf)
        row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(row, text=_("修正するタスク")).pack(anchor="w")
        self.task_var = tk.StringVar(value=list(TASK_LABELS)[0])
        task_cb = ttk.Combobox(row, textvariable=self.task_var,
                               values=list(TASK_LABELS), state="readonly", width=34)
        task_cb.pack(anchor="w", pady=2)
        ToolTip(task_cb, _("マスクは学習側と同じ経路で再構築されます。"
                           "背景マスクは .b2z に生画像が必要です。"))

        self.btn_open = ttk.Button(
            lf, text=_("バンドルを開く..."), command=self.on_open_bundle)
        self.btn_open.pack(anchor="w", padx=6, pady=4)

        self.bundle_var = tk.StringVar(value=_("未読み込み。"))
        ttk.Label(lf, textvariable=self.bundle_var, justify="left").pack(
            anchor="w", padx=6, pady=(0, 6))

    def _build_brush_panel(self, parent: ttk.Frame) -> None:
        """
        Build the brush mode, brush size, and edit-count controls.
        ブラシのモード・大きさ・編集件数の操作部を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ブラシ"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        # Mode values are the mask values themselves, so no lookup sits between
        # what is selected and what is written. The swatches use the mask's own
        # black and white, so the brush shows what it will paint.
        # モードの値はマスクの値そのものであり、選択と書き込みの間に変換を挟まない。
        # 見本はマスクと同じ白黒を使い、ブラシが何を塗るかを示す。
        self.mode_var = tk.IntVar(value=PAINT_FIBER)
        for value, text, fill in (
            (PAINT_FIBER, _("繊維として塗る（白）"), "#ffffff"),
            (PAINT_BACKGROUND, _("背景として塗る（黒）"), "#000000"),
        ):
            row = ttk.Frame(lf)
            row.pack(fill=tk.X, padx=6, pady=1)
            swatch = tk.Canvas(row, width=14, height=14, highlightthickness=0)
            swatch.create_rectangle(0, 0, 14, 14, outline="#888888", fill=fill)
            swatch.pack(side=tk.LEFT, padx=(0, 6))
            ttk.Radiobutton(row, text=text, value=value,
                            variable=self.mode_var).pack(side=tk.LEFT)

        size_row = ttk.Frame(lf)
        size_row.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(size_row, text=_("ブラシ半径 (px)")).pack(side=tk.LEFT)
        self.brush_var = tk.IntVar(value=BRUSH_DEFAULT)
        spin = ttk.Spinbox(size_row, from_=BRUSH_MIN, to=BRUSH_MAX, width=5,
                           textvariable=self.brush_var)
        spin.pack(side=tk.LEFT, padx=4)

        btn_row = ttk.Frame(lf)
        btn_row.pack(fill=tk.X, padx=6, pady=(4, 6))
        self.btn_undo = ttk.Button(
            btn_row, text=_("元に戻す"), command=self.on_undo)
        self.btn_undo.pack(side=tk.LEFT, padx=2)
        self.btn_clear = ttk.Button(
            btn_row, text=_("修正をすべて消す"), command=self.on_clear_edits)
        self.btn_clear.pack(side=tk.LEFT, padx=2)

        self.counts_var = tk.StringVar(value="")
        counts_label = ttk.Label(lf, textvariable=self.counts_var, justify="left")
        counts_label.pack(anchor="w", padx=6, pady=(0, 6))
        ToolTip(counts_label,
                _("パイプラインのマスクと食い違った画素だけが保存されます。"
                  "元の値へ塗り戻せばその判断は取り消されます。"))

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        """
        Build the save control and the progress indicator.
        保存の操作部と進捗表示を構築する。
        """
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, padx=4, pady=(2, 6))

        self.btn_save = ttk.Button(
            bar, text=_("修正を保存"), command=self.on_save)
        self.btn_save.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_save,
                _("バンドルの隣に修正ファイルを書き出します。"
                  "ML Model Trainer でラベルの出所に Manual corrections を"
                  "選ぶと使われます。"))

        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=110)
        self.progress.pack(side=tk.RIGHT, padx=4)

    def _build_figure_panel(self, parent: ttk.Frame) -> None:
        """
        Build the view selector, the editing canvas, and the paint handlers.
        表示切り替え、編集キャンバス、描画ハンドラを構築する。
        """
        view_row = ttk.Frame(parent)
        view_row.pack(fill=tk.X, padx=6, pady=(2, 0))
        ttk.Label(view_row, text=_("編集ペインの表示")).pack(side=tk.LEFT)
        self.view_var = tk.StringVar(value=VIEW_MASK_ONLY)
        for value, text in (
            (VIEW_MASK_ONLY, _("マスクのみ")),
            (VIEW_OVERLAY, _("画像＋マスク")),
        ):
            ttk.Radiobutton(view_row, text=text, value=value,
                            variable=self.view_var,
                            command=self._on_view_changed).pack(
                side=tk.LEFT, padx=6)

        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig = plt.Figure(figsize=(7.2, 5.0), dpi=90)
        self.ax = self.fig.add_subplot(111)
        self.ax.axis("off")

        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # NavigationToolbar2Tk uses pack internally, so isolate it in its own
        # frame. Zoom matters here: a single-pixel correction cannot be aimed
        # at full extent on a dense scan.
        # NavigationToolbar2Tk は内部で pack を使うため専用フレームへ隔離する。
        # Zoom は重要である。高密度の走査では、全体表示のまま 1 画素の修正を狙えない。
        toolbar_frame = ttk.Frame(parent)
        toolbar_frame.pack(fill=tk.X, padx=4)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()
        try:
            self.toolbar.configure(bg=self._clam_bg)
        except tk.TclError:
            pass

        ttk.Button(toolbar_frame, text=_("図を保存..."),
                   command=self.on_save_figure).pack(side=tk.RIGHT, padx=6)

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.draw()

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        """
        Build the three side-by-side comparison previews.
        3 面並置の比較プレビューを構築する。

        Separate figure and canvas from the editing pane, so a stroke can never
        land on a preview and so refreshing one does not redraw the other.
        編集ペインとは figure・canvas を分ける。ストロークがプレビューへ届くことが
        なくなり、一方の更新が他方の再描画を伴わなくなる。
        """
        lf = ttk.LabelFrame(parent, text=_("比較"))
        lf.pack(fill=tk.X, padx=4, pady=4)

        self.preview_fig = plt.Figure(figsize=(7.2, 2.1), dpi=80)
        self.preview_axes = self.preview_fig.subplots(1, 3)
        for ax in self.preview_axes:
            ax.axis("off")
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, master=lf)
        self.preview_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.draw()

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log text area.
        ログテキスト領域を構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ログ"))
        lf.pack(fill=tk.X, padx=4, pady=4)
        self.log_text, _sb = create_scrolled_text(lf, height=4, width=40)
        self.log_text.configure(state=tk.DISABLED)

    # ----- Logging ---------------------------------------------------------
    # `_log` / `_log_exception` come from LogMixin (they drive self.log_text).
    # `_log` / `_log_exception` は LogMixin 由来（self.log_text を操作する）。

    def _log_initial_message(self) -> None:
        """
        Log a short usage hint at startup.
        起動時に短い使い方の案内をログへ表示する。
        """
        self._log(_("バンドルを開き、マスクの誤りをドラッグで塗り直します。"
                    "保存するとバンドルの隣に修正ファイルが書かれます。"))

    # ----- Bundle loading --------------------------------------------------

    def on_open_bundle(self) -> None:
        """
        Choose a bundle and rebuild its base mask in a worker.
        バンドルを選び、そのベースマスクをワーカーで再構築する。
        """
        if self.is_running:
            return
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title=_(".b2z バンドルを選択"),
            filetypes=[("b2z bundles", "*.b2z"), ("All files", "*.*")])
        if not path:
            return

        task = TASK_LABELS[self.task_var.get()]
        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("{name} を読み込み中...").format(name=os.path.basename(path)))
        threading.Thread(
            target=self._worker_load, args=(path, task), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _worker_load(self, path: str, task: str) -> None:
        """
        Rebuild the trainer's base mask and restore any saved corrections.
        学習側のベースマスクを再構築し、保存済みの修正があれば復元する。

        Runs off the main thread because rebuilding the base re-runs a pipeline
        stage (the Segmenter or the background calibrator), which takes seconds
        on a real scan.
        ベースの再構築はパイプラインの段（Segmenter または背景補正器）を再実行し、
        実測走査では数秒かかるため、メインスレッド外で実行する。
        """
        try:
            from lib import ml_dataset as md
            from lib import ml_mask_labels as mk
            from lib.blosc2_io import load_bundle_meta
        except ImportError as exc:
            self.ui_queue.put(("fatal", {"text": str(exc)}))
            return

        try:
            self.ui_queue.put(("log", _("ベースマスクを再構築中...")))
            # The same call the trainer makes, so the mask painted on is the
            # mask trained against (see the module docstring).
            # 学習側と同じ呼び出し。描く対象のマスクが学習対象のマスクと一致する
            # （モジュール docstring 参照）。
            image, base = md.load_image_and_label(
                path, task=task, label_source=md.LABEL_SEGMENTER_INTERMEDIATE)
            meta = load_bundle_meta(path)
            image_hash = mk.image_sha256(image)

            mask = (np.asarray(base) != 0).astype(np.uint8)
            restored = 0
            stale_reason = ""
            sidecar = mk.label_path_for(path)
            if os.path.isfile(sidecar):
                try:
                    labels = mk.load_mask_labels(
                        sidecar,
                        expected_image_sha256=image_hash,
                        expected_task=task,
                        expected_base_source=mk.DEFAULT_BASE_SOURCE[task],
                        expected_shape=image.shape,
                    )
                    # Reopening resumes from the corrected mask, which is the
                    # base with the saved differences applied.
                    # 開き直しは修正後のマスクから再開する。これはベースへ保存済みの
                    # 差分を適用したものである。
                    mask = mk.apply_edits(base, labels.edits).astype(np.uint8)
                    restored = labels.n_edited
                except ValueError as exc:
                    # Refused rather than merged: corrections made for a
                    # different image or base do not mean here what they meant
                    # there, and loading them anyway would put wrong judgements
                    # on screen as if the reviewer had made them.
                    # 統合せず拒否する。別の画像やベース向けの修正はここでは同じ
                    # 意味を持たず、それでも読み込めば、検分者が下したかのような
                    # 誤った判断が画面に載ることになる。
                    stale_reason = str(exc)

            self.ui_queue.put(("loaded", {
                "path": path,
                "task": task,
                "image": image,
                "base": base,
                "mask": mask,
                "image_hash": image_hash,
                "input_sha256": meta.get("input_sha256"),
                "restored": restored,
                "stale_reason": stale_reason,
            }))
        except Exception as exc:  # noqa: BLE001 - report any load failure.
            self.ui_queue.put(("fatal", {
                "text": str(exc), "trace": traceback.format_exc()}))

    # ----- Queue polling ---------------------------------------------------

    def _poll_ui_queue(self) -> None:
        """
        Drain worker messages and keep polling while a worker is active.
        ワーカーメッセージを処理し、ワーカー実行中はポーリングを継続する。
        """
        def _on_loaded(payload):
            self._set_running(False)
            self._handle_loaded(payload)
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
            "loaded": _on_loaded,
            "fatal": _on_fatal,
        })
        if should_continue:
            self.after(50, self._poll_ui_queue)

    def _handle_loaded(self, payload: Dict) -> None:
        """
        Store the loaded bundle and draw its mask.
        読み込んだバンドルを保存し、そのマスクを描画する。
        """
        self._bundle_path = payload["path"]
        self._task = payload["task"]
        self._image = payload["image"]
        self._base_label = payload["base"]
        self._mask = payload["mask"]
        self._image_hash = payload["image_hash"]
        self._input_sha256 = payload["input_sha256"]
        self._stale_sidecar = bool(payload["stale_reason"])
        self._dirty = False
        self._undo = []
        self._last_point = None

        self.bundle_var.set(os.path.basename(self._bundle_path))
        if payload["restored"]:
            self._log(_("保存済みの修正 {n} 画素を復元しました。").format(
                n=payload["restored"]))
        if payload["stale_reason"]:
            self._log(payload["stale_reason"])
            messagebox.showwarning(
                _("既存の修正を読み込めません"),
                _("バンドルの隣に修正ファイルがありますが、いま表示している"
                  "マスクのものではありません。\n"
                  "空の状態で開始します。保存すると既存のファイルを上書きします。"))

        self._draw()
        self._update_counts()
        self._update_controls_state()

    # ----- Drawing ---------------------------------------------------------

    def _edit_layer(self) -> np.ndarray:
        """
        Derive the edit layer from where the mask differs from the pipeline's.
        マスクがパイプラインのものと食い違う箇所から編集レイヤを導出する。

        The judgement recorded for a pixel is exactly the disagreement visible
        on screen, so a pixel painted back to the pipeline's own answer carries
        no judgement at all. Deriving the layer here rather than accumulating it
        as the reviewer paints is what makes that true by construction: there is
        no way to record something the mask does not show.
        画素について記録される判断は、画面上に見えている食い違いそのものである。
        したがって、パイプラインの答えへ塗り戻した画素は判断を持たない。検分者が塗る
        たびに蓄積するのではなくここで導出することが、それを構成上の性質にしている。
        マスクが示していないものを記録する経路が存在しない。

        Returns
        -------
        numpy.ndarray
            ``uint8`` layer holding the `lib.ml_mask_labels` edit values.
            `lib.ml_mask_labels` の編集値を保持する ``uint8`` のレイヤ。
        """
        from lib.ml_mask_labels import EDIT_BACKGROUND, EDIT_FIBER, EDIT_NONE

        base = np.asarray(self._base_label) != 0
        mask = np.asarray(self._mask) != 0
        edits = np.full(mask.shape, EDIT_NONE, dtype=np.uint8)
        edits[mask & ~base] = EDIT_FIBER
        edits[~mask & base] = EDIT_BACKGROUND
        return edits

    def _draw(self) -> None:
        """
        Rebuild the editing pane and the previews from the current state.
        現在の状態から編集ペインとプレビューを作り直す。
        """
        self.ax.clear()
        self.ax.axis("off")
        self._mask_artist = None
        self._overlay = None
        self._overlay_artist = None

        if self._mask is None:
            self.canvas.draw()
            self._draw_previews()
            return

        if self.view_var.get() == VIEW_MASK_ONLY:
            self._mask_artist = self.ax.imshow(
                self._mask, cmap=MASK_CMAP, vmin=0, vmax=1,
                interpolation="nearest")
        else:
            # Composite the translucent layers over an explicit black layer,
            # not over the figure's white background: `afmhot` renders low
            # height as black, so a white backdrop shows through the dark
            # majority of the scan and washes the whole image out to gray.
            # The backdrop is drawn as an image rather than set as the axes
            # facecolor because `axis("off")` suppresses the axes patch
            # entirely, so a facecolor would silently have no effect.
            # 半透明の層を、図の白背景ではなく明示的な黒の層の上で合成する。`afmhot` は
            # 低い高さを黒で描くため、白い下地では走査の大部分を占める暗部から透けてしまい、
            # 画像全体が灰色に白ちゃける。下地を軸の facecolor ではなく画像として描くのは、
            # `axis("off")` が軸のパッチ自体の描画を止めるため、facecolor では黙って
            # 無効になるからである。
            self.ax.imshow(np.zeros(self._image.shape, dtype=np.uint8),
                           cmap="gray", vmin=0, vmax=1, interpolation="nearest")
            vmin, vmax = compute_auto_vrange(self._image)
            self.ax.imshow(self._image, cmap=HEIGHT_CMAP, vmin=vmin, vmax=vmax,
                           alpha=OVERLAY_IMAGE_ALPHA, interpolation="nearest")
            self._overlay = self._build_overlay()
            self._overlay_artist = self.ax.imshow(
                self._overlay, interpolation="nearest")

        self.fig.tight_layout()
        self.canvas.draw()
        self._draw_previews()

    def _build_overlay(self) -> np.ndarray:
        """
        Build the RGBA layer that draws the corrected mask over the image.
        修正後のマスクを画像へ重ねて描く RGBA レイヤを作る。
        """
        h, w = self._mask.shape
        rgba = np.zeros((h, w, 4), dtype=np.float32)
        rgba[self._mask != 0] = MASK_OVERLAY_RGBA
        return rgba

    def _draw_previews(self) -> None:
        """
        Draw the height image, the pipeline mask, and the corrected mask.
        高さ画像・パイプラインのマスク・修正後のマスクを描画する。

        Rebuilt only on load and on a whole-layer change; a stroke refreshes the
        corrected-mask preview alone through `_refresh_previews`.
        作り直すのは読み込み時とレイヤ全体の変更時のみ。ストロークでは
        `_refresh_previews` が修正後マスクのプレビューだけを更新する。
        """
        titles = PREVIEW_TITLES.get(self._task, PREVIEW_TITLES["binarize"])
        self._preview_mask_artist = None
        for ax, title in zip(self.preview_axes, titles):
            ax.clear()
            ax.axis("off")
            ax.set_title(title, fontsize=9)

        if self._mask is not None:
            vmin, vmax = compute_auto_vrange(self._image)
            self.preview_axes[0].imshow(
                self._image, cmap=HEIGHT_CMAP, vmin=vmin, vmax=vmax,
                interpolation="nearest")
            self.preview_axes[1].imshow(
                self._base_label, cmap=MASK_CMAP, vmin=0, vmax=1,
                interpolation="nearest")
            self._preview_mask_artist = self.preview_axes[2].imshow(
                self._mask, cmap=MASK_CMAP, vmin=0, vmax=1,
                interpolation="nearest")

        self.preview_fig.tight_layout()
        self.preview_canvas.draw()

    def _refresh_view(self) -> None:
        """
        Push the current mask to the editing canvas without rebuilding it.
        現在のマスクを、編集キャンバスを作り直さずに反映する。

        Called on every stroke segment, so it must not clear the axes: doing so
        would reset the zoom the reviewer set to aim the correction, and would
        redraw the whole pane on each mouse move.
        ストロークの区間ごとに呼ばれるため、軸をクリアしてはならない。クリアすると
        検分者が修正を狙うために設定したズームが解除され、マウス移動のたびにペイン
        全体を描き直すことになる。
        """
        if self._mask_artist is not None:
            self._mask_artist.set_data(self._mask)
        if self._overlay_artist is not None:
            self._overlay_artist.set_data(self._overlay)
        self.canvas.draw_idle()

    def _refresh_previews(self) -> None:
        """
        Update the corrected-mask preview only.
        修正後マスクのプレビューだけを更新する。

        The height image and the pipeline mask never change while a bundle is
        open, so redrawing them on every stroke would be wasted work.
        高さ画像とパイプラインのマスクはバンドルを開いている間は変化しないため、
        ストロークごとに描き直すのは無駄である。
        """
        if self._preview_mask_artist is None:
            return
        self._preview_mask_artist.set_data(self._mask)
        self.preview_canvas.draw_idle()

    def _on_view_changed(self) -> None:
        """
        Rebuild the editing pane after the view mode is switched.
        表示モードを切り替えた後に編集ペインを作り直す。
        """
        if self._mask is not None:
            self._draw()

    # ----- Painting --------------------------------------------------------

    def _on_press(self, event) -> None:
        """
        Begin a stroke and paint its first point.
        ストロークを開始し、その最初の点を塗る。

        Ignored while a toolbar mode is active so panning or zooming to reach a
        region cannot paint over it on the way.
        ツールバーのモード実行中は無視する。領域へ到達するためのパンやズームが、
        その途中でその領域を塗ってしまわないようにする。
        """
        point = self._event_pixel(event)
        if point is None:
            return
        # Snapshot before the first change so one stroke is one undo step.
        # 最初の変更の前に控えを取り、1 ストロークを 1 段の取り消しにする。
        self._push_undo()
        self._stroke_active = True
        self._last_point = point
        self._paint_at(point)

    def _on_motion(self, event) -> None:
        """
        Continue a stroke, filling the gap since the previous event.
        ストロークを継続し、前回のイベントからの間を埋める。

        Motion events arrive far apart during a fast drag, so painting only at
        the reported positions would leave a dotted line instead of a stroke.
        速いドラッグではモーションイベントが飛び飛びに届くため、報告された位置だけを
        塗ると、ストロークではなく点線になる。
        """
        if not self._stroke_active:
            return
        point = self._event_pixel(event)
        if point is None:
            return
        if self._last_point is not None:
            for step in _interpolate(self._last_point, point):
                self._paint_at(step, refresh=False)
        self._last_point = point
        self._paint_at(point)

    def _on_release(self, _event) -> None:
        """
        End the stroke, discarding its undo step if nothing changed.
        ストロークを終了する。何も変わっていなければ取り消し段を捨てる。
        """
        if not self._stroke_active:
            return
        self._stroke_active = False
        self._last_point = None
        if self._undo and np.array_equal(self._undo[-1], self._mask):
            self._undo.pop()
        else:
            self._dirty = True
        self._refresh_previews()
        self._update_counts()
        self._update_controls_state()

    def _event_pixel(self, event) -> Optional[Tuple[int, int]]:
        """
        Return the image pixel a mouse event points at, or None if unusable.
        マウスイベントが指す画像画素を返す。使えない場合は None。
        """
        if self.is_running or self._mask is None:
            return None
        if event.inaxes is not self.ax:
            return None
        if getattr(self.toolbar, "mode", ""):
            return None
        if event.button != 1 and self._stroke_active is False:
            return None
        if event.xdata is None or event.ydata is None:
            return None
        h, w = self._mask.shape
        x = int(round(float(event.xdata)))
        y = int(round(float(event.ydata)))
        if not (0 <= x < w and 0 <= y < h):
            return None
        return x, y

    def _paint_at(self, point: Tuple[int, int], refresh: bool = True) -> None:
        """
        Apply the current brush at one image pixel.
        現在のブラシを画像の 1 画素へ適用する。
        """
        x, y = point
        value = int(self.mode_var.get())
        radius = self._brush_radius()

        h, w = self._mask.shape
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        x0, x1 = max(0, x - radius), min(w, x + radius + 1)
        if y0 >= y1 or x0 >= x1:
            return

        yy, xx = np.ogrid[y0:y1, x0:x1]
        disc = (yy - y) ** 2 + (xx - x) ** 2 <= radius * radius
        mask_block = self._mask[y0:y1, x0:x1]
        # Only pixels the brush actually changes count. Brushing a value a pixel
        # already holds is a no-op here and therefore records nothing.
        # ブラシが実際に変える画素だけが対象である。既に同じ値を持つ画素へ塗るのは
        # ここで何もせず、したがって何も記録されない。
        changed = disc & (mask_block != value)
        if not changed.any():
            return
        mask_block[changed] = value

        # Repaint only the touched pixels of the overlay; a full rebuild on
        # every stroke segment would make a large scan unusable.
        # 重ね描きは触れた画素だけを塗り直す。ストロークの区間ごとに全体を作り直すと
        # 大きな走査では使いものにならない。
        if self._overlay is not None:
            self._overlay[y0:y1, x0:x1][changed] = (
                MASK_OVERLAY_RGBA if value == PAINT_FIBER else CLEAR_RGBA)
        if refresh:
            self._refresh_view()

    def _brush_radius(self) -> int:
        """
        Return the brush radius, clamped, tolerating a half-typed spinbox.
        ブラシ半径を範囲内に丸めて返す。入力途中のスピンボックスも許容する。

        Read on every stroke segment, so a value the user is still typing must
        not raise; an unusable entry falls back to the default rather than
        interrupting the stroke.
        ストロークの区間ごとに読むため、入力途中の値で例外を出してはならない。
        解釈できない入力は、ストロークを中断せず既定値へ戻す。
        """
        try:
            radius = int(self.brush_var.get())
        except (tk.TclError, ValueError):
            radius = BRUSH_DEFAULT
        return max(BRUSH_MIN, min(BRUSH_MAX, radius))

    def _push_undo(self) -> None:
        """
        Record the mask so the coming stroke can be undone.
        これから行うストロークを取り消せるよう、マスクを控える。
        """
        self._undo.append(np.array(self._mask, dtype=np.uint8))
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)

    # ----- Edit commands ---------------------------------------------------

    def on_undo(self) -> None:
        """
        Restore the mask as it was before the last stroke.
        直前のストローク前のマスクへ戻す。
        """
        if self.is_running or not self._undo:
            return
        self._mask = self._undo.pop()
        self._apply_whole_layer_change()

    def on_clear_edits(self) -> None:
        """
        Discard every correction, restoring the pipeline's own mask.
        すべての修正を破棄し、パイプライン自身のマスクへ戻す。
        """
        if self.is_running or self._mask is None:
            return
        if not self._has_corrections():
            return
        if not messagebox.askyesno(
                _("確認"),
                _("この画像の修正をすべて消します。よろしいですか。")):
            return
        self._push_undo()
        self._mask = (np.asarray(self._base_label) != 0).astype(np.uint8)
        self._apply_whole_layer_change()

    def _has_corrections(self) -> bool:
        """
        Report whether the mask differs from the pipeline's anywhere.
        マスクがどこかでパイプラインのものと食い違っているかを返す。
        """
        if self._mask is None:
            return False
        return bool(np.any((np.asarray(self._mask) != 0)
                           != (np.asarray(self._base_label) != 0)))

    def _apply_whole_layer_change(self) -> None:
        """
        Refresh both panes after an edit that replaced the whole mask.
        マスク全体を置き換えた編集の後、両ペインを更新する。
        """
        self._dirty = True
        if self._overlay is not None:
            self._overlay = self._build_overlay()
        self._refresh_view()
        self._refresh_previews()
        self._update_counts()
        self._update_controls_state()

    # ----- Saving ----------------------------------------------------------

    def on_save(self) -> None:
        """
        Write the current corrections to the mask-label sidecar.
        現在の修正をマスクラベル sidecar へ書き出す。
        """
        if self.is_running or self._mask is None:
            return
        try:
            from lib import ml_mask_labels as mk
        except ImportError as exc:
            messagebox.showerror(_("エラー"), str(exc))
            return

        if not self._has_corrections():
            messagebox.showinfo(
                _("修正がありません"),
                _("保存する修正がありません。マスクの誤りを塗ってから保存してください。"))
            return
        if self._stale_sidecar and not messagebox.askyesno(
                _("上書きの確認"),
                _("別のマスク向けの修正ファイルが既にあります。上書きしますか。")):
            return

        edits = self._edit_layer()
        try:
            meta = mk.make_mask_meta(
                self._bundle_path, self._task,
                mk.DEFAULT_BASE_SOURCE[self._task], self._image_hash,
                created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                input_sha256=self._input_sha256)
            path = mk.save_mask_labels(
                mk.label_path_for(self._bundle_path), edits, meta)
        except Exception as exc:  # noqa: BLE001 - report any save failure.
            messagebox.showerror(_("保存に失敗しました"), str(exc))
            return

        counts = mk.edit_counts(edits)
        self._dirty = False
        self._stale_sidecar = False
        self._log(_("修正を保存しました: {p}").format(p=os.path.basename(path)))
        messagebox.showinfo(
            _("保存しました"),
            _("{n} 画素の修正を保存しました。\n{p}").format(
                n=counts["total"], p=path))

    def on_save_figure(self) -> None:
        """
        Save the current editing view via the shared helper.
        現在の編集ペインの表示を共有ヘルパー経由で保存する。
        """
        save_figure_with_dialog(self, self.fig, initial_name="mask_annotation")

    # ----- State -----------------------------------------------------------

    def _update_counts(self) -> None:
        """
        Refresh the per-class correction counters.
        クラスごとの修正件数の表示を更新する。
        """
        if self._mask is None:
            self.counts_var.set("")
            return
        base = np.asarray(self._base_label) != 0
        mask = np.asarray(self._mask) != 0
        n_fiber = int(np.count_nonzero(mask & ~base))
        n_background = int(np.count_nonzero(~mask & base))
        # Counts carry no unit; the sentence around them is localized.
        # 件数に単位はない。それを囲む文はローカライズする。
        self.counts_var.set(
            _("修正した画素: 繊維 {f} / 背景 {b}").format(
                f=n_fiber, b=n_background))

    def _update_controls_state(self) -> None:
        """
        Enable the editing controls only once a bundle is loaded.
        バンドルを読み込んだときのみ編集の操作部を有効化する。
        """
        if self.is_running:
            return
        loaded = self._mask is not None
        self.btn_save.configure(state=tk.NORMAL if loaded else tk.DISABLED)
        self.btn_clear.configure(state=tk.NORMAL if loaded else tk.DISABLED)
        self.btn_undo.configure(
            state=tk.NORMAL if loaded and self._undo else tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        """
        Toggle controls and the progress bar while a worker is active.
        ワーカー実行中に操作部と進捗バーを切り替える。
        """
        self.is_running = running
        self.btn_open.configure(state=tk.DISABLED if running else tk.NORMAL)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()
            self._update_controls_state()

    def _confirm_discard(self) -> bool:
        """
        Ask before discarding unsaved corrections; return whether to proceed.
        未保存の修正を破棄する前に確認し、続行してよいかを返す。

        Corrections exist only in memory until saved, and painting them is slow
        human work, so opening another bundle must not drop them silently.
        修正は保存するまでメモリ上にしか存在せず、その作画は時間のかかる人手の作業で
        ある。別のバンドルを開く操作でそれを黙って捨ててはならない。
        """
        if not self._dirty:
            return True
        return messagebox.askyesno(
            _("未保存の修正"),
            _("保存していない修正があります。破棄して続行しますか。"))

    def _on_close(self) -> None:
        """
        Confirm before closing with unsaved corrections.
        未保存の修正がある状態で閉じる前に確認する。
        """
        if self._confirm_discard():
            self.destroy()


def _interpolate(start: Tuple[int, int], end: Tuple[int, int]) -> List[Tuple[int, int]]:
    """
    Return the intermediate pixels between two stroke points.
    ストロークの 2 点間にある中間画素を返す。

    Endpoints are excluded because the caller paints them itself.
    端点は呼び出し側が塗るため除く。
    """
    x0, y0 = start
    x1, y1 = end
    steps = int(max(abs(x1 - x0), abs(y1 - y0)))
    if steps <= 1:
        return []
    xs = np.linspace(x0, x1, steps + 1)[1:-1]
    ys = np.linspace(y0, y1, steps + 1)[1:-1]
    return [(int(round(x)), int(round(y))) for x, y in zip(xs, ys)]


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
