# -*- coding: utf-8 -*-
"""
Apply a machine-learning binarization model and compare it to the classical result.
機械学習の二値化モデルを適用し、古典的な結果と比較する。

This GUI loads a per-pixel preprocessing model, applies it to ``.b2z`` bundles,
and shows a 2x3 panel grid comparing the model against the classical pipeline,
with agreement metrics. It is the maturity gate for the ML preprocessing
models: it is where a trained model is checked against the classical pipeline
before any decision to integrate it into GUI01. Inputs are a model file
(extension per task, see `lib.ml_schema.MODEL_EXT_BY_TASK`) plus ``.b2z``
bundles; there is no output file (this is a comparison tool).
本 GUI は画素単位の前処理モデルを読み込み、``.b2z`` バンドルへ適用し、モデルと
古典パイプラインを比較する 2x3 のパネル図を一致指標とともに表示する。ML 前処理
モデルの成熟度ゲートであり、学習済みモデルを GUI01 へ統合する判断の前に古典
パイプラインと照合する場所である。入力はモデルファイル（拡張子はタスク別、
`lib.ml_schema.MODEL_EXT_BY_TASK` 参照）と ``.b2z`` バンドルで、出力ファイルは
ない（比較ツール）。

Panel layout / パネル構成
-------------------------
Every task reads the same way column by column: the left column holds the
model's input and the difference between the two results, the middle column
holds each side's raw output, and the right column holds each side's result at
the stage the pipeline actually delivers. The top row is always the model and
the bottom row the classical pipeline. What "raw output" and "delivered result"
mean differs per task, because each task replaces a different decision:
どのタスクも列ごとに同じ読み方をする。左列はモデルの入力と両結果の差分、中列は
各側の素の出力、右列はパイプラインが実際に渡す段での各側の結果である。上段が常に
モデル、下段が古典パイプライン。「素の出力」と「渡される結果」の意味はタスクごとに
異なる。各タスクが置き換える判断が異なるためである：

===================== ===================== ==============================
task                  middle column         right column
===================== ===================== ==============================
``binarize``          threshold mask        after the Segmenter's component
                                            filters
``bg_mask``           fiber-candidate mask  after the background stage's
                                            small-component removal and
                                            dilation
``background_surface`` background surface   raw image minus that surface
                       (nm)                 (nm)
===================== ===================== ==============================

The difference panel shows the right column (what integration would actually
change), while the metrics text reports both stages, so the figure answers
"what does this change downstream" and the numbers answer "how faithful is the
model itself".
差分パネルは右列（統合したとき実際に変わるもの）を表示し、指標テキストは両段を
報告する。図が「下流で何が変わるか」に、数値が「モデル自体がどれだけ忠実か」に
答える分担である。

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
        "Apply a trained preprocessing model to .b2z bundles and compare "
        "it against the classical result, panel by panel, both as the raw "
        "stage output and as the result the pipeline would deliver. A "
        "binarization or background-mask model is scored mask-to-mask with "
        "Dice and the fiber fraction of each mask at both stages; a "
        "background-surface model is scored in nanometers against the surface "
        "the pipeline subtracted. Use this to check whether an ML model is "
        "worth integrating before adding it to the preprocessing pipeline. "
        "The ML libraries are optional and loaded only when a model is applied."
    )
}

# ===== Standard library =====
import os
import queue
import textwrap
import threading
import traceback
from dataclasses import dataclass
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

# Subplot titles are fixed English plot text (not localized, per the UI-string
# policy for scientific/plot labels). Each tuple is in Matplotlib's row-major
# order for the 2x3 grid, i.e. top-left, top-middle, top-right, bottom-left,
# bottom-middle, bottom-right; see the module docstring for what the columns
# mean. Panel lists built below follow the same order.
# サブプロットのタイトルは固定英語のプロット文字（科学的・プロットラベルの
# UI 文字列方針によりローカライズしない）。各タプルは 2x3 格子に対する Matplotlib
# の行優先順、すなわち左上・中上・右上・左下・中下・右下の順である。列の意味は
# モジュール docstring 参照。以下で組み立てるパネル一覧も同じ順に従う。
_MASK_STAGE_TITLES = (
    "ML mask (pre-filter)", "ML mask (post-filter)",
    "Difference (post-filter)",
    "Classical mask (pre-filter)", "Classical mask (post-filter)",
)
_BINARIZE_PANEL_TITLES = ("Calibrated",) + _MASK_STAGE_TITLES
_BG_MASK_PANEL_TITLES = ("Raw height",) + _MASK_STAGE_TITLES
_SURFACE_PANEL_TITLES = (
    "Raw height", "ML background (nm)", "ML corrected (nm)",
    "Difference (nm)", "Classical background (nm)", "Classical corrected (nm)",
)

# Colormaps, matching the rest of the project: height maps use the AFM colormap,
# masks a plain 0/1 grayscale, and differences a diverging map centred on zero
# so over- and under-detection are distinguishable by colour.
# カラーマップはプロジェクト全体と同じ方針。高さマップは AFM 用、マスクは 0/1 の
# 素のグレースケール、差分はゼロ中心の発散マップとし、過検出と過小検出を色で
# 区別できるようにする。
_CMAP_HEIGHT = "afmhot"
_CMAP_MASK = "gray"
_CMAP_DIFF = "bwr"

# The two stages a mask task is scored at, as (metric-key suffix, display
# label). Both are fixed English: the suffix is an internal key and the label
# is reporting text shown beside the fixed metric names.
# マスクタスクを採点する 2 つの段。(指標キーの接尾辞, 表示ラベル) の組。いずれも
# 固定英語である。接尾辞は内部キーであり、ラベルは固定の指標名の横に出す報告用の
# 文字列である。
_MASK_STAGES = (("pre", "pre-filter"), ("post", "post-filter"))


@dataclass
class _Panel:
    """
    One subplot's data and how to draw it.
    1 つのサブプロットのデータと描画方法。

    Attributes
    ----------
    data
        Image to draw, or ``None`` when this panel could not be computed.
        描画する画像。計算できなかった場合は ``None``。
    title
        Fixed English plot title.
        固定英語のプロットタイトル。
    cmap, vmin, vmax
        Matplotlib colormap and display range.
        Matplotlib のカラーマップと表示レンジ。
    note
        Reason shown in place of the image when `data` is ``None``.
        `data` が ``None`` のとき画像の代わりに表示する理由。

    Notes
    -----
    The worker thread fills these in, so the display range of a panel pair that
    must share one scale (the two background surfaces, say) is decided once,
    where both arrays are in hand, rather than rediscovered at draw time.
    ワーカースレッドがこれらを埋めるため、同一スケールを共有すべきパネル対
    （例：2 枚の背景面）の表示レンジは、両配列が揃っている場所で 1 度だけ決まる。
    描画時に再導出することはない。
    """

    data: Optional[np.ndarray]
    title: str
    cmap: str = _CMAP_MASK
    vmin: float = 0.0
    vmax: float = 1.0
    note: str = ""


def _threshold_from_manifest(manifest: Dict) -> float:
    """
    Return a manifest's fiber threshold, defaulting to 0.5.
    manifest の繊維しきい値を返す。既定は 0.5。

    Mirrors `lib.ml_model.LoadedModel.fiber_threshold` so a pre-load manifest
    peek shows the same threshold the verified model would, without building a
    `LoadedModel`. An explicit ``None`` check is required because a recorded
    threshold of ``0.0`` is a valid value, not a "use the default" signal.
    `lib.ml_model.LoadedModel.fiber_threshold` に倣い、`LoadedModel` を作らずに
    読み込み前の manifest ピークでも検証後と同じしきい値を表示する。記録値
    ``0.0`` は有効な値であり「既定を使う」の合図ではないため、明示的な ``None``
    判定が必要。
    """
    value = manifest.get("segmentation_threshold")
    return float(value) if value is not None else 0.5


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
        # Wider than the other plugins on purpose: the right pane holds six
        # panels side by side, and the panels are the tool's actual output --
        # the metrics text only ranks bundles, the panels are where a person
        # judges which side was wrong.
        # 他プラグインより意図的に横長にしている。右ペインに 6 枚のパネルが並び、
        # そのパネルこそが本ツールの実質的な出力だからである。指標テキストは
        # バンドルの順位付けに過ぎず、どちらが誤っていたかを人が判断するのは
        # パネル上である。
        apply_window_size(self, 1520, 860, min_w=1180, min_h=700)

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
        # Most of any extra width goes to the panels: the controls need a fixed
        # amount of space, while six panels keep getting more readable with it.
        # 余った横幅の大半をパネル側へ回す。操作部が必要とする幅は一定だが、6 枚の
        # パネルは幅が増えるほど読みやすくなり続けるためである。
        outer.add(left, weight=1)
        outer.add(right, weight=3)

        self._build_model_panel(left)
        self._build_threshold_panel(left)
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
        # A plain Frame, not a LabelFrame: an untitled LabelFrame still reserves
        # a blank row for the missing title and draws a border around a group
        # that needs no heading. Keep the inner padx at 6 so the button lines up
        # with the contents of the titled panels below.
        # LabelFrame ではなく素の Frame を使う。見出しのない LabelFrame でも空の
        # 見出し行分の高さを確保し、見出し不要のまとまりに枠線を描いてしまうため。
        # 内側の padx は 6 のままにし、下の見出し付きパネルの内容と左端をそろえる。
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=4, pady=4)

        ttk.Button(frame, text=_("モデルを読み込み..."), command=self.on_load_model).pack(
            anchor="w", padx=6, pady=4)

        # wraplength keeps a long model path from widening the left pane; the
        # path is the first line of this label (see `_show_model_info`).
        # wraplength は長いモデルパスが左ペインを押し広げるのを防ぐ。パスは本ラベル
        # の先頭行に表示される（`_show_model_info` 参照）。
        self.model_info_var = tk.StringVar(value=_("モデル未読み込み。"))
        ttk.Label(frame, textvariable=self.model_info_var, justify="left",
                  wraplength=360).pack(anchor="w", padx=6, pady=(0, 4))

    def _build_threshold_panel(self, parent: ttk.Frame) -> None:
        """
        Build the fiber-threshold control.
        ファイバーしきい値の操作部を構築する。
        """
        # Plain Frame for the same reason as the model panel above.
        # 上のモデルパネルと同じ理由で素の Frame を使う。
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=4, pady=4)

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X, padx=4, pady=4)

        threshold_label = ttk.Label(grid, text=_("ファイバーしきい値"))
        threshold_label.grid(row=0, column=0, sticky="w", padx=2, pady=2)
        # Blank means use the model's recorded threshold.
        # 空欄はモデルに記録されたしきい値を使う意味。
        self.threshold_var = tk.StringVar(value="")
        ttk.Entry(grid, textvariable=self.threshold_var, width=10).grid(
            row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(grid, text=_("（空欄でモデル既定値）")).grid(
            row=0, column=2, sticky="w", padx=2, pady=2)
        ToolTip(
            threshold_label,
            _("モデルの出力確率を繊維と判定するしきい値です。"
              "背景面モデルには適用されません。"))

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
        Build the 2x3 comparison figure embedded in the window.
        ウィンドウに埋め込む 2x3 比較図を構築する。
        """
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig = plt.Figure(figsize=(9.0, 6.2), dpi=90)
        self.axes = self.fig.subplots(2, 3)
        # No titles until a comparison runs: which panels the grid holds depends
        # on the loaded model's task, so labelling them now would announce a
        # layout that a background-surface model does not use.
        # 比較を実行するまでタイトルは付けない。格子が何のパネルを持つかは読み込んだ
        # モデルのタスクに依存するため、今ラベルを付けると背景面モデルでは使わない
        # 構成を予告してしまう。
        for ax in self.axes.ravel():
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
        # Not expanded: the figure frame above is the only widget that should
        # absorb spare vertical space, because six panels lose readability fast.
        # 伸縮させない。縦の余白を吸収してよいのは上の図フレームだけである。6 枚の
        # パネルは縦が減ると急速に見づらくなるため。
        lf = ttk.LabelFrame(parent, text=_("ログ"))
        lf.pack(fill=tk.X, padx=4, pady=4)
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
        self._log(_("モデルを読み込み .b2z バンドルを追加し、"
                    "画像を選択して比較するか Compare all を使います。"))

    # ----- Model loading ---------------------------------------------------

    def on_load_model(self) -> None:
        """
        Load and validate a per-pixel preprocessing model.
        画素単位の前処理モデルを読み込み検証する。
        """
        try:
            from lib import ml_model as mm
            from lib.ml_schema import (
                BACKGROUND_TASKS, MODEL_EXT_BY_TASK, SEGMENTATION_TASKS,
                validate_manifest)
        except ImportError as exc:
            messagebox.showerror(
                _("エラー"),
                _("機械学習ライブラリがインストールされていません。\n{err}")
                .format(err=str(exc)))
            return

        # Offer only this stage's model extensions in the picker (segmentation
        # + background tasks); a fragment-pair `connect` model cannot be
        # compared here, so its extension is left out of the default filter.
        # このピッカーには当段のモデル拡張子（二値化＋背景タスク）のみを提示する。
        # 断片ペアの `connect` モデルはここで比較できないため、その拡張子は既定
        # フィルタから外す。
        accepted = tuple(SEGMENTATION_TASKS) + tuple(BACKGROUND_TASKS)
        patterns = " ".join(f"*{MODEL_EXT_BY_TASK[t]}" for t in accepted)
        path = filedialog.askopenfilename(
            title=_("モデルを選択"),
            filetypes=[("AFM ML model", patterns), ("All files", "*.*")],
        )
        if not path:
            return
        # Peek the manifest first (cheap: no ONNX bytes, no onnxruntime) so the
        # model's task is shown as soon as a file is picked, before the heavier
        # verified load. read_manifest does not validate, so the full load below
        # still gates actual use; on a load failure the peeked task stays visible
        # as a "which model did I pick" diagnostic.
        # まず manifest だけを覗く（軽量：ONNX バイト列も onnxruntime も読まない）。
        # ファイル選択直後に、本検証読み込みの前に task を表示する。read_manifest は
        # 検証しないため実使用の可否は下の本読み込みが担う。読み込み失敗時も、覗いた
        # task は「どのモデルを選んだか」の手がかりとして表示に残す。
        try:
            peeked = mm.read_manifest(path)
        except Exception as exc:  # noqa: BLE001 - report any read failure.
            messagebox.showerror(_("読み込みに失敗しました"), str(exc))
            return
        self._show_model_info(peeked, _threshold_from_manifest(peeked), path)

        try:
            model = mm.load_model(path)
        except Exception as exc:  # noqa: BLE001 - report any load failure.
            messagebox.showerror(_("読み込みに失敗しました"), str(exc))
            return

        # Every per-pixel model can be compared here; a fragment-pair
        # (`connect`) model cannot, and is rejected with a message naming the
        # accepted tasks rather than producing a silently wrong result. The
        # picker's extension filter already steers toward `accepted`, but the
        # extension is not authoritative, so revalidate against the manifest.
        # 画素単位モデルはいずれもここで比較できる。断片ペア（`connect`）モデルは
        # 比較できないため、受理タスクを明示して拒否し、黙って誤った結果を
        # 出さない。ピッカーの拡張子フィルタは既に `accepted` へ誘導するが、拡張子は
        # 正準ではないため manifest で再検証する。
        problems = validate_manifest(model.manifest, require_task=accepted)
        if problems:
            messagebox.showerror(_("モデルが不適切"), "; ".join(problems))
            return

        self._model = model
        self._model_path = path
        self._show_model_info(model.manifest, model.fiber_threshold, path)
        self._log(_("モデルを読み込みました: {p}").format(p=os.path.basename(path)))
        self._update_controls_state()

    def _show_model_info(
        self, manifest: Dict, threshold: float, path: str
    ) -> None:
        """
        Display the model's file location and key manifest fields.
        モデルのファイル位置と主要 manifest 項目を表示する。

        Takes the manifest, threshold, and path directly (not a `LoadedModel`)
        so the same display serves both the pre-load manifest peek (via
        `read_manifest`) and the verified load, without opening the ONNX graph
        for the peek.
        `LoadedModel` ではなく manifest・しきい値・パスを直接受け取り、読み込み前の
        manifest ピーク（`read_manifest` 経由）と検証読み込みの両方で同じ表示を
        使えるようにする。ピークでは ONNX グラフを開かない。

        The folder is shown above the file name because training runs export
        models under the same file name, so the folder is often the only thing
        that says which run the loaded model came from.
        フォルダをファイル名の上に表示するのは、学習実行ごとに同じファイル名で
        モデルを書き出すため、読み込んだモデルがどの実行のものかを示すのは
        フォルダだけということが多いからである。
        """
        m = manifest
        dice = ""
        metrics = m.get("metrics") or {}
        if "dice_mean" in metrics:
            # Fixed metric label; only the surrounding text is localized.
            # 指標ラベルは固定。周囲の文のみローカライズする。
            dice = "  CV dice={:.4f}".format(metrics["dice_mean"])
        # A file path is not translatable text, so it is concatenated outside
        # the gettext message rather than embedded in it.
        # ファイルパスは翻訳対象の文ではないため、gettext メッセージに埋め込まず
        # 外側で連結する。
        directory, filename = os.path.split(path)
        location = "{}\n{}\n".format(directory, filename) if directory else filename + "\n"
        self.model_info_var.set(
            location
            + _("id: {id}\ntask: {task}  しきい値: {thr}{dice}").format(
                id=m.get("model_id", "?"), task=m.get("task", "?"),
                thr=threshold, dice=dice))

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

        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("{name} を比較中...").format(name=os.path.basename(path)))
        threading.Thread(
            target=self._worker_compare_one,
            args=(path, threshold), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _compare_one(self, path: str, threshold: Optional[float]) -> Dict:
        """
        Apply the model to one bundle and score it against the classical result.
        1 バンドルへモデルを適用し、古典的な結果と照合して採点する。

        Dispatches on the model's task, because each task's classical
        counterpart and integrated stage differ; see the module docstring for
        the resulting panel layout. Panels and metrics are built together so a
        displayed number can never describe a different computation than the
        picture beside it.
        モデルのタスクで振り分ける。タスクごとに古典側の対応物と統合後の段が
        異なるためである。結果のパネル構成はモジュール docstring 参照。パネルと
        指標は一緒に組み立てる。表示される数値が、隣の図と別の計算を指すことが
        起こらないようにするためである。
        """
        from lib import ml_dataset as md

        task = self._model.task
        if self._model.is_regression:
            panels, metrics = self._compare_surface(md, path)
        elif task == "bg_mask":
            panels, metrics = self._compare_bg_mask(md, path, threshold)
        else:
            panels, metrics = self._compare_binarize(md, path, threshold)

        return {
            "name": os.path.basename(path),
            "task": task,
            "regression": self._model.is_regression,
            "panels": panels,
            "metrics": metrics,
        }

    def _compare_binarize(
        self, md, path: str, threshold: Optional[float]
    ) -> tuple:
        """
        Build the binarize panels: threshold mask, then component-filtered mask.
        binarize のパネルを構築する。しきい値マスクと、成分フィルタ後のマスク。

        The stored ``binarized`` mask is the post-filter side and is always
        available, while the pre-filter side has to be reconstructed by re-running
        the Segmenter from the bundle's stored parameters -- which also gates the
        model's post-filter panel, since the model's mask must pass through those
        same filters. A bundle without parameters therefore keeps the panels it
        can still show instead of failing the whole comparison.
        保存済み ``binarized`` マスクがフィルタ後側であり常に得られる。一方フィルタ前側は
        バンドル保存パラメータから Segmenter を再実行して復元する必要があり、これは
        モデルのフィルタ後パネルの可否も左右する。モデルのマスクも同じフィルタを通す
        必要があるためである。したがってパラメータの無いバンドルでは、比較全体を失敗と
        せず、表示できるパネルだけを残す。
        """
        image, classical_post = md.load_image_and_label(
            path, task="binarize", label_source=md.LABEL_BUNDLE_BINARIZED)
        classical_post = classical_post.astype(bool)
        ml_pre = self._model.predict_mask(image, threshold=threshold)

        try:
            _image, classical_pre = md.load_image_and_label(
                path, task="binarize",
                label_source=md.LABEL_SEGMENTER_INTERMEDIATE)
            classical_pre = classical_pre.astype(bool)
            ml_post = md.apply_pipeline_component_filters(path, ml_pre, image)
            note = ""
        except Exception as exc:  # noqa: BLE001 - degrade to the panels we have.
            classical_pre = ml_post = None
            note = _reason_text(exc, path)

        return _mask_panels(
            image, _BINARIZE_PANEL_TITLES, ml_pre, ml_post,
            classical_pre, classical_post, note,
        ), _mask_stage_metrics(ml_pre, classical_pre, ml_post, classical_post)

    def _compare_bg_mask(self, md, path: str, threshold: Optional[float]) -> tuple:
        """
        Build the bg_mask panels: candidate mask, then the calibrator's cleanup.
        bg_mask のパネルを構築する。候補マスクと、補正器の整形処理後。

        The classical side is the gradient-ridge mask recovered by re-running
        `BGCalibrator`, so the bundle's parameters are already required to get
        here; the cleanup applied to both sides reads its settings from those
        same parameters (see `lib.bg_mask_filter`).
        古典側は `BGCalibrator` を再実行して復元する勾配リッジマスクなので、ここへ
        到達する時点でバンドルのパラメータは既に必須である。両側へ適用する整形処理も
        設定を同じパラメータから読む（`lib.bg_mask_filter` 参照）。
        """
        from lib.bg_mask_filter import filter_bg_fiber_mask_for_bundle, read_bundle_params

        image, classical_pre = md.load_image_and_label(path, task="bg_mask")
        classical_pre = classical_pre.astype(bool)
        ml_pre = self._model.predict_mask(image, threshold=threshold)

        params = read_bundle_params(path)
        classical_post = filter_bg_fiber_mask_for_bundle(path, classical_pre, params)
        ml_post = filter_bg_fiber_mask_for_bundle(path, ml_pre, params)

        return _mask_panels(
            image, _BG_MASK_PANEL_TITLES, ml_pre, ml_post,
            classical_pre, classical_post, "",
        ), _mask_stage_metrics(ml_pre, classical_pre, ml_post, classical_post)

    def _compare_surface(self, md, path: str) -> tuple:
        """
        Build the background-surface panels: the surfaces and both corrections.
        背景面のパネルを構築する。背景面 2 枚と、両者の補正後画像。

        The right column subtracts each background from the same raw image, which
        turns an abstract nanometer difference into the corrected images a person
        already knows how to read. The classical corrected image is derived by
        subtraction rather than read back from the bundle so both columns come
        from one arithmetic, and the metrics stay those of the surfaces (the
        difference between the corrected images is the same array negated).
        右列は同じ生画像から各背景を差し引く。これにより抽象的な nm の差が、人が
        既に読み慣れた補正後画像になる。古典側の補正後画像はバンドルから読み戻さず
        減算で導く。両列を 1 つの演算から出すためである。指標は背景面のものを保つ
        （補正後画像同士の差は同じ配列の符号反転である）。
        """
        image, classical_bg = md.load_image_and_label(
            path, task="background_surface")
        predicted_bg = self._model.predict_surface(image)
        diff = predicted_bg - classical_bg
        classical_corrected = image - classical_bg
        ml_corrected = image - predicted_bg

        raw_vmin, raw_vmax = compute_auto_vrange(image)
        # Each pair shares one range so the two sides are visually comparable;
        # the difference gets a symmetric range centred on zero.
        # 各対は同一レンジを共有して視覚的に比較できるようにし、差分はゼロ中心の
        # 対称レンジとする。
        both_bg = np.concatenate([np.ravel(predicted_bg), np.ravel(classical_bg)])
        bg_vmin, bg_vmax = float(np.min(both_bg)), float(np.max(both_bg))
        corrected_vmin, corrected_vmax = compute_auto_vrange(classical_corrected)
        span = float(np.max(np.abs(diff))) or 1.0

        titles = _SURFACE_PANEL_TITLES
        panels = [
            _Panel(image, titles[0], _CMAP_HEIGHT, raw_vmin, raw_vmax),
            _Panel(predicted_bg, titles[1], _CMAP_HEIGHT, bg_vmin, bg_vmax),
            _Panel(ml_corrected, titles[2], _CMAP_HEIGHT,
                   corrected_vmin, corrected_vmax),
            _Panel(diff, titles[3], _CMAP_DIFF, -span, span),
            _Panel(classical_bg, titles[4], _CMAP_HEIGHT, bg_vmin, bg_vmax),
            _Panel(classical_corrected, titles[5], _CMAP_HEIGHT,
                   corrected_vmin, corrected_vmax),
        ]
        return panels, _surface_metrics(predicted_bg, classical_bg)

    def _worker_compare_one(self, path: str, threshold: Optional[float]) -> None:
        """
        Compute the model mask, classical mask, and metrics for one bundle.
        1 バンドルのモデルマスク・古典マスク・指標を計算する。
        """
        try:
            # Probe the optional ML stack. The import must execute -- locating
            # the module (importlib.util.find_spec) would always succeed, since
            # what fails is lib.ml_dataset's own scipy/skimage imports.
            from lib import ml_dataset  # noqa: F401 - imported to raise here
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return
        try:
            payload = self._compare_one(path, threshold)
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

        self.ui_queue = queue.Queue()
        self._set_running(True)
        self._log(_("全 {n} バンドルを比較中...").format(n=len(self.bundles)))
        threading.Thread(
            target=self._worker_compare_all,
            args=(list(self.bundles), threshold), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _worker_compare_all(
        self, paths: List[str], threshold: Optional[float]
    ) -> None:
        """
        Accumulate per-image metrics across all bundles off the main thread.
        メインスレッド外で全バンドルの画像ごと指標を積算する。
        """
        try:
            # Same pre-flight probe as _worker_compare_one.
            from lib import ml_dataset  # noqa: F401 - imported to raise here
        except ImportError as exc:
            self.ui_queue.put(("fatal", {
                "text": _("機械学習ライブラリがインストールされていません。\n{err}")
                        .format(err=str(exc))}))
            return

        per_image: List[Dict] = []
        for i, path in enumerate(paths, start=1):
            name = os.path.basename(path)
            try:
                metrics = self._compare_one(path, threshold)["metrics"]
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
            # Panels the worker could not compute carry their reason; log it in
            # full, since the panel itself only has room for a truncated copy.
            # 計算できなかったパネルは理由を持つ。パネル自体には切り詰めた写ししか
            # 収まらないため、ここで全文をログに残す。
            for note in {p.note for p in payload["panels"] if p.data is None and p.note}:
                self._log(note)
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
        Draw the six comparison panels prepared by the worker.
        ワーカーが用意した 6 枚の比較パネルを描画する。

        Every drawing decision (colormap, display range, shared scales) is
        already fixed in each `_Panel`, so this method stays task-agnostic and
        adding a task cannot require a change here.
        描画の判断（カラーマップ・表示レンジ・共有スケール）は各 `_Panel` で既に
        確定しているため、本メソッドはタスク非依存のままであり、タスクを追加しても
        ここを変更する必要はない。
        """
        for ax, panel in zip(self.axes.ravel(), payload["panels"]):
            ax.clear()
            ax.set_title(panel.title)
            ax.axis("off")
            if panel.data is None:
                # Reason text is a fixed English message from lib; wrapped
                # because an axes has no automatic wrapping and truncated
                # because the full text is already in the log.
                # 理由の文言は lib 由来の固定英語メッセージ。軸は自動折り返しを
                # しないため折り返し、全文は既にログにあるため切り詰める。
                ax.text(0.5, 0.5,
                        textwrap.fill(
                            panel.note or _("このパネルは計算できませんでした。"),
                            30)[:300],
                        ha="center", va="center", fontsize=7,
                        transform=ax.transAxes)
                continue
            ax.imshow(panel.data, cmap=panel.cmap,
                      vmin=panel.vmin, vmax=panel.vmax)
        self.fig.tight_layout()
        self.canvas.draw()

    def _show_single_metrics(self, name: str, metrics: Dict) -> None:
        """
        Show the mask-overlap summary for the selected image.
        選択画像のマスク重なり要約を表示する。

        Judging a single image is the Difference panel's job, not this text's:
        the panel shows where and in what shape the two masks disagree, which is
        what tells an expert whether the model or the classical result was the
        wrong one. The fiber fractions are kept because they give the direction
        of the disagreement (over- or under-detection) that a scalar hides.
        1 画像の判断は本テキストではなく Difference パネルの役割である。パネルは
        両マスクがどこにどんな形でずれたかを示し、モデルと古典のどちらが誤って
        いたかを専門家が判断する材料になる。繊維率を残すのは、スカラーでは
        隠れる不一致の向き（過検出か過小検出か）を示すためである。
        """
        # Metric names (dice, ml_fiber, ...) are fixed English; the header line
        # is localized. Keep the model-vs-classical framing explicit.
        # 指標名（dice, ml_fiber, ...）は固定英語。見出し行はローカライズする。
        #
        # `_mask_metrics` also returns iou and agreement; both are deliberately
        # left out of the display. Within one image iou is a monotone transform
        # of dice (dice = 2*iou/(1+iou)), so it flags no failure dice misses.
        # agreement counts background pixels too, and at the few-percent fiber
        # fractions of AFM images it stays near 1.0 for a good mask and for an
        # all-background one alike.
        # `_mask_metrics` は iou と agreement も返すが、いずれも意図的に表示しない。
        # 1 画像内では iou は dice の単調変換（dice = 2*iou/(1+iou)）であり、dice が
        # 見逃す失敗を一つも検出しない。agreement は背景画素も数えるため、繊維率が
        # 数 % の AFM 画像では良いマスクでも全背景マスクでも 1.0 近くに張り付く。
        #
        # Both stages are listed because they answer different questions: the
        # pre-filter row is how faithfully the model reproduces the decision it
        # replaces, the post-filter row is what integrating it would deliver.
        # The Difference panel shows only the latter, so the former exists here.
        # 両段を併記するのは、それぞれ別の問いに答えるためである。フィルタ前の行は
        # モデルが置き換える判断をどれだけ忠実に再現したか、フィルタ後の行は統合した
        # ときに得られるものである。Difference パネルは後者しか示さないため、前者は
        # ここに置く。
        lines = [_("選択中: {name}").format(name=name)]
        if _is_surface_metrics(metrics):
            lines.append(
                "  mae={mae_nm:.3f} nm  rmse={rmse_nm:.3f} nm".format(**metrics))
            lines.append(
                "  bias={bias_nm:+.3f} nm  max_abs={max_abs_nm:.3f} nm".format(**metrics))
        elif _has_stage_metrics(metrics):
            for key, label in _MASK_STAGES:
                if f"dice_{key}" not in metrics:
                    continue
                lines.append(
                    "  {label:<12} dice={dice:.4f}  ml_fiber={ml:.4f}  "
                    "classical_fiber={cl:.4f}".format(
                        label=label + ":", dice=metrics[f"dice_{key}"],
                        ml=metrics[f"ml_fiber_frac_{key}"],
                        cl=metrics[f"classical_fiber_frac_{key}"]))
        else:
            lines.append(_("  採点できた段がありません（ログを参照）。"))
        self._set_metrics_text("\n".join(lines))

    def _show_aggregate_metrics(self, per_image: List[Dict]) -> None:
        """
        Rank the per-image results and name the bundles worth opening.
        画像ごとの結果を順位付けし、開く価値のあるバンドルを名指しする。

        Dice is reported here as a sort key for triage, not as an accuracy
        score. The reference is the classical pipeline's own output, so a low
        dice means the two disagree, not that the model was wrong -- the
        classical result may have been the wrong one. This list only narrows a
        folder of bundles down to the few worth inspecting in the panels.
        ここでの dice は精度スコアではなく、トリアージ用の並べ替えキーとして出す。
        参照は古典パイプライン自身の出力なので、dice が低いことは両者がずれている
        ことを意味するだけで、モデルが誤っていたとは限らない（古典側が誤っていた
        可能性もある）。この一覧は、フォルダ内のバンドルをパネルで確認すべき数枚
        まで絞り込むためのものである。
        """
        self._aggregate = per_image
        lines = [_("{n} 画像の集計:").format(n=len(per_image))]
        # Decided over every image, not the first one: a bundle whose stages
        # could not be reconstructed carries no metric at all and would
        # otherwise decide the format for the whole run.
        # 先頭 1 件ではなく全画像で判定する。段を復元できなかったバンドルは指標を
        # 一切持たず、そうしないと実行全体の書式をそれが決めてしまうためである。
        if any(_is_surface_metrics(m) for m in per_image):
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
        elif any(_has_stage_metrics(m) for m in per_image):
            for key, label in _MASK_STAGES:
                dice = np.array([m[f"dice_{key}"] for m in per_image
                                 if f"dice_{key}" in m], dtype=float)
                if dice.size == 0:
                    continue
                lines.append(
                    "  dice {label:<12} mean={:.4f}  min={:.4f}  max={:.4f}".format(
                        dice.mean(), dice.min(), dice.max(), label=label))
            # Ranked by the post-filter stage: this list exists to pick which
            # bundles to open, and what an integrated model would deliver is
            # what makes a bundle worth opening.
            # 順位付けはフィルタ後の段で行う。この一覧は開くバンドルを選ぶために
            # あり、開く価値を決めるのは統合したモデルが実際に出すものだからである。
            lines += ["", _("dice 下位 3 件:")]
            worst = sorted(per_image, key=_worst_dice_key)[:3]
            for m in worst:
                stages = "  ".join(
                    "{}={:.4f}".format(label, m[f"dice_{key}"])
                    for key, label in _MASK_STAGES if f"dice_{key}" in m)
                lines.append("  {name}: {stages}".format(
                    name=m["name"], stages=stages))
        else:
            lines.append(_("  採点できた段がありません（ログを参照）。"))
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
    if _is_surface_metrics(metrics):
        return "mae={:.3f} nm".format(metrics["mae_nm"])
    if _has_stage_metrics(metrics):
        return "  ".join(
            "dice {}={:.4f}".format(label, metrics[f"dice_{key}"])
            for key, label in _MASK_STAGES if f"dice_{key}" in metrics)
    # Named, not left blank: in the per-image log line this is the only sign
    # that a bundle was processed but could not be scored at any stage.
    # 空欄にせず明示する。画像ごとのログ行では、そのバンドルが処理されたものの
    # どの段でも採点できなかったことを示すのはこの表示だけだからである。
    return _("採点できた段がありません")


def _is_surface_metrics(metrics: Dict) -> bool:
    """
    Return whether a metrics dict came from the background-surface task.
    指標辞書が背景面タスク由来かどうかを返す。

    Notes
    -----
    Tested on the surface side, not the mask side: a mask task whose stages
    could not be reconstructed carries no dice at all, and asking "does it have
    dice" would then route an unscored mask result into the surface formatting
    and fail on a missing key.
    マスク側ではなく背景面側で判定する。段を復元できなかったマスクタスクは dice を
    一切持たないため、「dice を持つか」で判定すると、採点できなかったマスクの結果が
    背景面の書式へ流れ、存在しないキーで失敗するからである。
    """
    return "mae_nm" in metrics


def _reason_text(exc: Exception, path: str) -> str:
    """
    Strip the bundle path that a lib error prefixes, leaving the reason itself.
    lib のエラーが前置するバンドルパスを取り除き、理由本体だけを残す。

    `lib.ml_dataset` prefixes its messages with the bundle path so a batch log
    stays unambiguous. In a panel a few centimetres wide the path crowds out the
    explanation, and the bundle is already named in the metrics text above.
    `lib.ml_dataset` は一括処理のログを曖昧にしないため、メッセージにバンドルパスを
    前置する。しかし数センチ幅のパネルではパスが説明を押し出してしまい、対象の
    バンドル名は上の指標テキストに既に出ている。
    """
    return str(exc).replace(f"{path}: ", "", 1)


def _has_stage_metrics(metrics: Dict) -> bool:
    """
    Return whether a mask task was scored at at least one stage.
    マスクタスクが少なくとも一方の段で採点できたかどうかを返す。
    """
    return any(f"dice_{key}" in metrics for key, _label in _MASK_STAGES)


def _worst_dice_key(metrics: Dict) -> float:
    """
    Return the dice a bundle should be ranked by, preferring the post-filter one.
    バンドルの順位付けに使う dice を返す。フィルタ後の値を優先する。

    A bundle whose post-filter stage could not be reconstructed still needs a
    place in the ranking, so its pre-filter dice stands in; ranking it last
    would hide a disagreement, and dropping it would hide the bundle.
    フィルタ後の段を復元できなかったバンドルも順位に位置を要するため、フィルタ前の
    dice で代用する。最下位に置けば不一致が見えなくなり、除外すればバンドル自体が
    見えなくなる。
    """
    if "dice_post" in metrics:
        return float(metrics["dice_post"])
    return float(metrics.get("dice_pre", 1.0))


def _mask_stage_metrics(
    ml_pre: np.ndarray,
    classical_pre: Optional[np.ndarray],
    ml_post: Optional[np.ndarray],
    classical_post: Optional[np.ndarray],
) -> Dict:
    """
    Score a mask task at both stages, skipping a stage that is unavailable.
    マスクタスクを両段で採点する。得られない段は飛ばす。

    Returns
    -------
    dict
        `_mask_metrics` entries suffixed with each stage's key, so a caller can
        report the stages side by side and tell a missing stage from a zero.
        各段のキーを接尾辞に付けた `_mask_metrics` の項目。呼び出し側が両段を
        並べて報告でき、欠落した段と 0 の値を区別できる。
    """
    metrics: Dict = {}
    for key, (ml, classical) in (
        ("pre", (ml_pre, classical_pre)),
        ("post", (ml_post, classical_post)),
    ):
        if ml is None or classical is None:
            continue
        for name, value in _mask_metrics(ml, classical).items():
            metrics[f"{name}_{key}"] = value
    return metrics


def _mask_panels(
    image: np.ndarray,
    titles: tuple,
    ml_pre: np.ndarray,
    ml_post: Optional[np.ndarray],
    classical_pre: Optional[np.ndarray],
    classical_post: np.ndarray,
    note: str,
) -> List[_Panel]:
    """
    Lay out the six panels shared by the two mask tasks.
    2 つのマスクタスクで共通の 6 パネルを配置する。

    Both mask tasks differ only in what produced their masks, not in how the
    comparison reads, so the layout lives here rather than in each builder.
    2 つのマスクタスクの違いはマスクの生成元だけで、比較の読み方は同じであるため、
    配置は各構築関数ではなくここに置く。

    Parameters
    ----------
    titles
        Panel titles in the grid's row-major order.
        格子の行優先順に並べたパネルタイトル。
    note
        Reason attached to panels that could not be computed.
        計算できなかったパネルに添える理由。
    """
    vmin, vmax = compute_auto_vrange(image)
    # The difference is drawn for the post-filter stage: it is what integrating
    # the model would actually change downstream (see the module docstring).
    # 差分はフィルタ後の段について描く。モデルを統合したとき下流で実際に変わるのは
    # そこだからである（モジュール docstring 参照）。
    diff = None
    if ml_post is not None and classical_post is not None:
        diff = ml_post.astype(np.int8) - classical_post.astype(np.int8)

    def mask_panel(data, title):
        return _Panel(data, title, _CMAP_MASK, 0, 1, note)

    return [
        _Panel(image, titles[0], _CMAP_HEIGHT, vmin, vmax),
        mask_panel(ml_pre, titles[1]),
        mask_panel(ml_post, titles[2]),
        _Panel(diff, titles[3], _CMAP_DIFF, -1, 1, note),
        mask_panel(classical_pre, titles[4]),
        mask_panel(classical_post, titles[5]),
    ]


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
