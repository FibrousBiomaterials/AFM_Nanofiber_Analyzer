# -*- coding: utf-8 -*-
"""
Annotate manual fiber connections on top of the GUI04 fiber-tracking view.
GUI04 のファイバー追跡ビューの上で、ファイバーの手動連結をアノテーションする。

Built by extending the GUI04 fiber tracker rather than replacing it: the folder
and file lists, the fiber table, the AFM overview with per-fiber boxes, the
height profiles, the automatic fiber-connection toggle, and the height filter
all behave as in GUI04. On top of that view the reviewer connects fibers by
hand -- picking two fibers and asserting they belong to the same fibril, or
marking a pair as not connected -- to correct what the automatic connector did.
The judgements are written to a label sidecar beside the bundle to train the
connection model. Output is one ``<stem>_connect_labels.json`` per bundle; the
``.b2z`` itself is never modified.
GUI04 のファイバートラッカーを置き換えず拡張して作る。フォルダ／ファイル一覧、
ファイバー表、ファイバー枠付きの AFM 全体像、高さプロファイル、自動ファイバー連結
トグル、高さフィルターはすべて GUI04 と同じ挙動である。そのビューの上で、検分者は
ファイバーを手で連結する。すなわち 2 本を選んで同一フィブリルに属すると主張するか、
連結しないと印を付け、自動連結器の結果を修正する。判断はバンドルの隣のラベル sidecar
へ書き出し、連結モデルの学習に使う。出力はバンドルごとに 1 つの
``<stem>_connect_labels.json`` で、``.b2z`` 自体は決して変更しない。

The automatic connector is kept, not removed: it reconnects fragments into
fibrils exactly as in GUI04, and the manual annotation records where a person
disagrees with or extends that automatic result. This is an annotation tool,
not a measurement tool; GUI04 remains the place fiber statistics are produced.
自動連結器は削除せず残す。GUI04 と同じく断片をフィブリルへ再結合し、手動アノテーション
は人がその自動結果に異を唱える箇所や補う箇所を記録する。本ツールはアノテーション用で
あり計測用ではない。ファイバー統計を生成する場所は GUI04 のままである。

Notes
-----
Each analyzed dataset is represented by one ``*.b2z`` file in the GUI01 output
folder. The bundle must contain ``calibrated``, ``skeletonized``, ``bp``,
``ep``, ``kp``, ``dp``, and ``ka`` keys.
GUI01 の出力フォルダ内では、1 解析対象につき 1 つの ``*.b2z`` ファイルを
使用する。バンドルには ``calibrated``、``skeletonized``、``bp``、``ep``、
``kp``、``dp``、``ka`` キーが必要である。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain plain string literals; do not wrap them with gettext _().
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "ML Connect Annotator",
    "description": (
        "Annotate manual fiber connections on top of the GUI04 fiber-tracking "
        "view. Load a GUI01 .b2z bundle, see the detected fibers in a list and "
        "as boxes over the AFM image, then connect two fibers by hand to "
        "assert they belong to the same fibril, or mark a pair as not "
        "connected, correcting the automatic connector. The judgements are "
        "saved to a label file beside the bundle to train the connection "
        "model; the bundle itself is never modified. Point the folder selector "
        "at the GUI01 output folder."
    )
}

# ===== Standard library =====
import os
import math
import traceback
import queue
import threading
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
import matplotlib.patheffects as pe
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ===== Project libraries =====
# Import the lib modules that provide the AFM image-processing core.
# lib/ フォルダ内の各モジュールをインポートする。これらが AFM 画像処理の本体。
from lib.fiber_tracking_image import FiberTrackingImage
from lib.fiber import Fiber
from lib.fiber_connector import ConnectParams, filter_fibers_by_height
from lib.blosc2_io import bundle_has_keys, load_bundle, BUNDLE_EXT
from lib.measure import (
    TRACKING_BUNDLE_KEYS, compute_fiber_stats,
    measure_bundle, read_scan_size_from_bundle, write_fiber_csv,
)
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_matplotlib_style, save_figure_with_dialog, ToolTip,
    setup_ttk_theme, rewrite_entries, mark_entry_state, replace_log_tail,
    save_text_widget_log, create_scrolled_text, create_scrolled_treeview,
    drain_ui_queue, extent_scale_and_unit, save_csv_with_dialog,
    UnconfirmedEntryMixin, LogMixin, localized_combobox_width,
    PLOT_FS_DEFAULTS, UNIT_MICROMETER,
    DEFAULT_VMIN, DEFAULT_VMAX,
)

# ===== Constants =====

# Required keys used to identify analyzed GUI01 bundle files.
# GUI01 が出力するバンドル内に含まれるべきキー（存在チェックに使用）。
# A .b2z bundle is treated as analyzed data only when all keys are present.
# .b2z バンドル内にこれら全てが揃っていれば解析済みデータとして扱う。
# The key list is owned by lib.bundle_schema and re-exported by lib.measure so
# the CLI and this GUI stay in sync.
# キー一覧は lib.bundle_schema が管理し、lib.measure から再公開することで
# CLI と本 GUI の整合を保つ。
REQUIRED_BUNDLE_KEYS = TRACKING_BUNDLE_KEYS

DEFAULT_HEIGHT_YLIM:           float = 20.0
# The full image size is entered in micrometers and converted to nanometers internally.
# 画像全体のサイズはユーザー入力では µm 単位、内部計算では nm 単位で扱う。
# Match GUI01: entry values stay in micrometers, while tick labels can switch units.
# GUI01 と仕様を揃え、入力欄の単位は µm 固定で、軸目盛単位の表示だけ µm/nm を切り替える。
DEFAULT_IMAGE_SIZE_UM:         float = 2.0               # 画像全体のサイズ (µm)
# Fiber analysis is always parallelized with ThreadPoolExecutor.
# ファイバー解析は常に ThreadPoolExecutor で並列化する。

# AFM overview display modes. Internal state keys (fixed English identifiers),
# selected by the mode radio buttons and read by the overview renderers.
# "height" keeps the afmhot image with per-fiber boxes; "fibers" scatters each
# fiber in its own color over the binarized silhouette.
# AFM 全体像の表示モード。モード選択ラジオが設定し全体像描画が参照する
# 内部状態キー（固定英語識別子）。"height" は afmhot 画像＋ファイバー枠、
# "fibers" は二値化シルエット上に各ファイバーを個別色で散布する。
OVERVIEW_MODE_HEIGHT = "height"
OVERVIEW_MODE_FIBERS = "fibers"

# Verdict identifiers for a manual connection, mirroring lib.ml_connect_labels.
# Kept as local literals so plugin startup does not import the label module.
# 手動連結の判定識別子。lib.ml_connect_labels と一致させる。プラグイン起動時に
# 当該モジュールを import しないよう、ローカルのリテラルとして保持する。
VERDICT_UNREVIEWED = "unreviewed"
VERDICT_CONNECT = "connect"
VERDICT_REJECT = "reject"
VERDICT_UNCERTAIN = "uncertain"

# Order verdicts are counted in. Fixed English identifiers.
# 判定を集計する順序。固定英語の識別子。
VERDICT_ORDER = (
    VERDICT_UNREVIEWED, VERDICT_CONNECT, VERDICT_REJECT, VERDICT_UNCERTAIN)

# Colors used to draw a connection by verdict. Plot styling, not localized text.
# 判定ごとに連結を描く色。プロットの体裁であり、ローカライズ対象の文字列ではない。
VERDICT_COLORS = {
    VERDICT_UNREVIEWED: "#9e9e9e",
    VERDICT_CONNECT: "#2e7d32",
    VERDICT_REJECT: "#c62828",
    VERDICT_UNCERTAIN: "#ef6c00",
}

# Outline drawn around each connection line so it stays visible over the warm
# afmhot image. afmhot has no cool tones, so cyan stands out over both the
# bright fibers and the dark background where a warm color alone would blend in.
# 各連結線の周囲に描く輪郭色。暖色系の afmhot 画像上でも見えるようにする。afmhot は
# 寒色を含まないため、シアンは明るい繊維と暗い背景の双方で目立つ。暖色だけでは紛れる。
CONNECTION_HALO_COLOR = "#00e5ff"

# Connection source tag, mirroring lib.ml_connect_labels. Every connection made
# here is hand-drawn, so "manual" is the source recorded.
# 連結の source タグ。lib.ml_connect_labels と一致させる。ここで作る連結はすべて
# 手動なので、記録する source は "manual"。
SOURCE_MANUAL = "manual"


# ===== Utility functions =====

def find_analyzed_stems(folder: str) -> List[str]:
    """
    Find GUI01 analyzed dataset stems in a folder.
    フォルダ内から GUI01 の解析済みデータセットのステムを検出する。

    Parameters
    ----------
    folder
        Folder that contains GUI01 output bundles.
        GUI01 の出力バンドルを含むフォルダ。

    Returns
    -------
    list of str
        Full paths without the bundle extension, sorted by dataset name.
        バンドル拡張子を除いたフルパスを、データセット名順に並べたリスト。

    Notes
    -----
    Only bundles that contain all required keys are accepted. For
    ``sample.b2z``, this function returns the stem used later as
    ``stem + BUNDLE_EXT``.
    必須キーが全て揃っているバンドルだけを対象とする。``sample.b2z`` に
    対しては、後段で ``stem + BUNDLE_EXT`` として使うステムを返す。
    """
    stems = []
    try:
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(BUNDLE_EXT):
                continue
            base = fn[: -len(BUNDLE_EXT)]
            stem = os.path.join(folder, base)
            ok, _missing = bundle_has_keys(stem + BUNDLE_EXT, REQUIRED_BUNDLE_KEYS)
            if ok:
                stems.append(stem)
    except OSError:
        pass
    return stems


# ===== Main window =====

class App(tk.Tk, UnconfirmedEntryMixin, LogMixin):
    """
    Main window for GUI04 fiber tracking.
    GUI04_Tracking のメインウィンドウ。

    Attributes
    ----------
    folder_path
        Folder containing GUI01 output bundles.
        GUI01 の出力バンドルを含むフォルダ。
    current_image
        Currently loaded AFM tracking image, or ``None`` before selection.
        現在読み込まれている AFM 追跡画像。未選択時は ``None``。
    current_fibers
        Fibers detected in the current image.
        現在画像から検出されたファイバー。

    Notes
    -----
    The layout has a top bar, a file list, a fiber table, an AFM overview, and
    a log area. Fiber detail images and height profiles are displayed in one
    non-modal ``FiberDetailWindow`` that follows the selected fiber.
    レイアウトはトップバー、ファイル一覧、ファイバー一覧、AFM 全体像、ログ領域で
    構成される。ファイバー拡大像と高さプロファイルは、選択ファイバーに追従する
    非モーダルの ``FiberDetailWindow`` で表示する。
    """

    def __init__(self) -> None:
        """
        Initialize the main tracking window and its persistent UI state.
        メイン追跡ウインドウと永続的な UI 状態を初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])
        setup_matplotlib_style(font_size=10)

        setup_ttk_theme(self)

        apply_window_size(self, 1450, 850, min_w=1100, min_h=700)

        # -- Application state --
        self.folder_path:    str = ""
        self.current_image:  Optional[FiberTrackingImage] = None
        self.current_fibers: List[Fiber] = []    # measure_bundle() の結果
        self.current_stem:   str = ""

        # Index of the selected fiber in the current table.
        self._sel_idx: Optional[int] = None

        # Height filter state.
        self._filter_active:   bool = False
        self._filtered_fibers: List[Fiber] = []

        # Cache the AFM overview background; only the highlight patch changes.
        self._highlight_patch: Optional[object] = None
        self._overview_bg_drawn: bool = False

        # Cache fiber statistics so table rebuilds do not recompute them.
        self._fiber_stats: List[tuple] = []   # [(median, max), ...]

        # Progress-bar state. The first update of a run appends a fresh log
        # line; later updates overwrite it in place via replace_log_tail.
        # 進捗バーの状態。各実行の最初の更新でログ行を 1 行追加し、以降は
        # replace_log_tail で同じ行を上書きしていく。
        self._progress_started: bool = False

        # Flag used while a worker thread is loading a dataset.
        self.is_running: bool = False

        # Keep at most one non-modal detail window for the enlarged image and profile.
        # 個別表示（拡大像 + プロファイル）への参照。非モーダルで1つだけ開く。
        self._detail_window: Optional["FiberDetailWindow"] = None

        # ===== Committed internal state for Enter-to-commit entries =====
        # Entry display values live in StringVar objects; committed state is separate.
        # Entry の表示値は textvariable (StringVar) に持たせ、内部状態は別に保持する。
        # Pressing Enter updates this state, and plots read only committed values.
        # Enter で確定する際にこの内部状態を更新し、各図の描画はこの内部状態を参照する。
        # Match GUI01: scale_um entries stay fixed in micrometers.
        # scale_um は GUI01 と仕様を揃え、入力欄の単位は µm 固定。
        # Tick-display units switch immediately through unit_var.
        # 軸目盛単位の表示（µm / nm）は unit_var で即時切替する。
        # scale_um is the X (width) size; scale_y_um is the optional Y (height)
        # size for rectangular scans. None means "same as X" (square scan).
        # scale_um は X（幅）サイズ、scale_y_um は矩形スキャン用の任意の Y（高さ）
        # サイズ。None は「X と同値」（正方スキャン）を意味する。
        self.scale_um: float = DEFAULT_IMAGE_SIZE_UM
        self.scale_y_um: Optional[float] = None
        self.vmin:     float = DEFAULT_VMIN
        self.vmax:     float = DEFAULT_VMAX
        self.filter_min: float = 1.6
        self.filter_max: float = 4.0

        # Split AFM overview font sizes into title, labels, ticks, and colorbar.
        # AFM全体像 フォントサイズ4分割（タイトル/軸ラベル/軸目盛/カラーバー）。
        # Use the shared ui_tools defaults for consistency across GUIs.
        # PLOT_FS_DEFAULTS（ui_tools の共通定数）に揃える。
        self.fs_title: float = float(PLOT_FS_DEFAULTS["title_fs"])  # 16
        self.fs_label: float = float(PLOT_FS_DEFAULTS["label_fs"])  # 14
        self.fs_tick:  float = float(PLOT_FS_DEFAULTS["tick_fs"])   # 13
        self.fs_cbar:  float = float(PLOT_FS_DEFAULTS["cbar_fs"])   # 13

        # -- tkinter variables for Entry display --
        self.scale_um_var         = tk.StringVar(value=self._fmt_num(self.scale_um))
        self.scale_y_um_var       = tk.StringVar(value="")
        self.vmin_var             = tk.StringVar(value=self._fmt_num(self.vmin))
        self.vmax_var             = tk.StringVar(value=self._fmt_num(self.vmax))
        self.filter_min_var       = tk.StringVar(value=self._fmt_num(self.filter_min))
        self.filter_max_var       = tk.StringVar(value=self._fmt_num(self.filter_max))
        self.fs_title_var         = tk.StringVar(value=self._fmt_num(self.fs_title))
        self.fs_label_var         = tk.StringVar(value=self._fmt_num(self.fs_label))
        self.fs_tick_var          = tk.StringVar(value=self._fmt_num(self.fs_tick))
        self.fs_cbar_var          = tk.StringVar(value=self._fmt_num(self.fs_cbar))

        # -- Tick-display units (micrometers / nanometers), applied immediately like GUI01 --
        # ── 軸目盛単位（µm / nm）── GUI01 と同じくラジオで即時反映。
        # Entry units stay fixed in micrometers; only display units switch here.
        # 入力欄の単位は µm 固定で、表示の単位だけここで切り替える。
        # When nanometers are selected, extent uses scale_um * 1000.
        # nm を選んだ場合は extent = scale_um * 1000 (= nm 値) に乗算して表示する。
        self.unit_var             = tk.StringVar(value=UNIT_MICROMETER)

        # -- Automatic setting mode, updated on dataset changes when enabled --
        # ── 自動設定モード切替（ON のときデータ切替で自動更新する）──
        # Detail windows always recompute the profile y-limit from the selected fiber.
        # 個別表示側で選択ファイバーからプロファイル y 上限を常時再計算する。
        self.auto_vrange_var      = tk.BooleanVar(value=True)   # vmin/vmax 自動

        # -- Height-filter checkbox --
        # Default is off; toggling applies or resets the filter immediately.
        # デフォルト OFF。即時反映で適用/リセット。
        self.filter_enabled_var   = tk.BooleanVar(value=False)

        # -- Fiber-connection (whole-fibril) toggle and its parameters --
        # Default is off; toggling re-analyzes the current dataset. When on,
        # GUI01 skeleton fragments split at crossings/branches are reconnected
        # into whole fibrils before measurement (see lib.fiber_connector).
        # ── ファイバー連結（フィブリル一本化）トグルとパラメータ ──
        # 既定 OFF。切替で現在データを再解析する。ON のとき、GUI01 が交差・分岐で
        # 分断した骨格断片を計測前に 1 本のフィブリルへ再結合する
        # （lib.fiber_connector を参照）。
        self.connect_enabled_var  = tk.BooleanVar(value=False)
        self.connect_params: ConnectParams = ConnectParams()
        # Keep at most one non-modal connection-settings window.
        # 連結設定ウインドウは非モーダルで 1 つだけ保持する。
        self._connect_window: Optional["ConnectSettingsWindow"] = None

        # -- Manual fiber-connection annotation state --
        # Independent of the automatic connector above: the reviewer connects
        # fibers by hand and the judgements are saved as connection labels. The
        # endpoints of the currently displayed fibers are what a label records,
        # so a fiber index maps to the fiber's own ends.
        # ── 手動ファイバー連結アノテーションの状態 ──
        # 上の自動連結器とは独立。検分者がファイバーを手で連結し、判断を連結ラベルとして
        # 保存する。ラベルが記録するのは現在表示中のファイバーの端点であり、ファイバー番号は
        # そのファイバー自身の端点に対応する。
        #
        # skeleton_sha256 binds a label file to this exact skeleton; the input
        # hash is kept for provenance only.
        # skeleton_sha256 はラベルファイルをこの骨格そのものへ結び付ける。入力ハッシュ
        # は来歴のためだけに保持する。
        self._skeleton_hash: str = ""
        self._input_sha256: Optional[str] = None
        # Recorded connections: dicts {"a": int, "b": int, "a_xy": (x, y),
        # "b_xy": (x, y), "verdict": str}. `a`/`b` are fiber indices; the xy pair
        # is the closest endpoint pair that identifies the connection.
        # 記録した連結: 辞書 {"a": int, "b": int, "a_xy": (x, y),
        # "b_xy": (x, y), "verdict": str}。`a`/`b` はファイバー番号、xy は連結を
        # 同定する最近接端点ペア。
        self._connections: List[Dict] = []
        # First fiber picked while forming a connection, or None.
        # 連結を作る際に最初に選んだファイバー番号。無ければ None。
        self._pending_fiber: Optional[int] = None
        # Selected row in the connection list, or None.
        # 連結一覧で選択中の行。無ければ None。
        self._conn_sel_idx: Optional[int] = None
        # Unsaved-connection flag, distinct from the fiber-analysis running flag.
        # 未保存の連結があるかのフラグ。ファイバー解析中フラグとは別に持つ。
        self._labels_dirty: bool = False
        # Matplotlib artists for the drawn connections; replaced on each redraw.
        # 描画した連結の Matplotlib アーティスト。再描画のたびに差し替える。
        self._connection_artists: List[object] = []

        # -- Profile element checkboxes --
        # ── プロファイル描画要素チェックボックス ──
        self.show_kink_var   = tk.BooleanVar(value=True)
        self.show_medmax_var = tk.BooleanVar(value=True)

        # -- AFM overview display mode (height image vs. color-coded fibers) --
        # Height and fiber modes are two renderings of the same overview and
        # share vmin/vmax, fonts, selection, and the height filter; the radio
        # only re-renders in place. The value is an internal state key.
        # ── AFM 全体像の表示モード（高さ画像／ファイバー色分け）──
        # 両モードは同一全体像の描き分けで、vmin/vmax・フォント・選択・高さ
        # フィルターを共有し、ラジオは同じ場所を再描画するだけ。値は内部状態キー。
        self.overview_mode_var = tk.StringVar(value=OVERVIEW_MODE_HEIGHT)

        # ===== Unconfirmed-entry registry for the main window =====
        # Each entry is (entry_widget, committed-value getter, commit callback).
        # 各要素: (entry_widget, 内部状態取得関数, 確定コールバック)。
        # FiberDetailWindow has its own registry.
        # FiberDetailWindow は独自の登録簿を持つ。
        self._init_unconfirmed_registry()

        # -- Build UI --
        self._build_topbar()
        self._build_main()
        self._init_figures()

        # Poll UI queue for current worker-thread messages and future async extensions.
        # キューポーリング（将来の非同期拡張用）。
        self.ui_queue: "queue.Queue" = queue.Queue()
        self.after(50, self._poll_ui_queue)

    # =========================================================================
    # UI construction
    # =========================================================================

    def _build_topbar(self) -> None:
        """
        Build the top toolbar with folder, scale, filter, and unit controls.
        フォルダ、スケール、フィルター、単位コントロールを持つ上部バーを構築する。
        """
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x", padx=8, pady=5)

        ttk.Button(bar, text=_("📂 フォルダ選択"), command=self._on_select_folder).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        # -- Scale (micrometers): same Enter-to-commit behavior as GUI01 --
        # ── スケール(µm) ── GUI01 と同じ仕様。Enter 確定方式。
        # Entry units stay fixed in micrometers; the radio buttons only change tick units.
        # 入力欄の単位は µm 固定で、右の µm/nm ラジオは軸目盛表示の単位のみを切替える。
        # Nanometer display uses extent = scale_um * 1000.
        # nm 選択時は extent が scale_um * 1000 (= nm 値) になる。
        ttk.Label(bar, text=_("スケール") + " (µm)").pack(side="left", padx=(2, 1))
        # "X" / "Y" labels mark each axis so first-time users can tell the two
        # fields apart (width vs. height).
        # "X" / "Y" ラベルで各軸を示し、初見のユーザーが 2 つの欄（幅・高さ）を
        # 区別できるようにする。
        ttk.Label(bar, text="X").pack(side="left", padx=(0, 1))
        self.ent_scale_um = ttk.Entry(bar, width=7, textvariable=self.scale_um_var)
        self.ent_scale_um.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_scale_um,
            lambda: self._fmt_num(self.scale_um),
            self._commit_scale_um,
        )
        ToolTip(
            self.ent_scale_um,
            _("AFM 画像の X（幅）方向の実寸") + " (µm)。\n"
            + _("ファイバー解析の長さ・座標換算に使われる重要な値。") + "\n"
            + _("変更すると現在のファイルが再解析される。"),
        )
        # Optional Y (height) size for rectangular scans. The "X" / "Y" labels
        # mark which field is which; an empty Y means a square scan (Y = X),
        # reinforced by the "= X" ghost placeholder shown while Y is blank.
        # 矩形スキャン用の任意の Y（高さ）サイズ。"X" / "Y" ラベルでどちらの欄か
        # を示す。Y 空欄は正方スキャン（Y = X）を意味し、Y が空のときに表示する
        # "= X" ゴーストプレースホルダでもそれを補強する。
        ttk.Label(bar, text="×").pack(side="left", padx=(0, 1))
        ttk.Label(bar, text="Y").pack(side="left", padx=(0, 1))
        self.ent_scale_y_um = ttk.Entry(bar, width=7, textvariable=self.scale_y_um_var)
        self.ent_scale_y_um.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_scale_y_um,
            lambda: "" if self.scale_y_um is None
            else self._fmt_num(self.scale_y_um),
            self._commit_scale_y_um,
        )
        ToolTip(
            self.ent_scale_y_um,
            _("AFM 画像の Y（高さ）方向の実寸") + " (µm)。\n"
            + _("空欄なら X（幅）と同じ（正方スキャン）。") + "\n"
            + _("変更すると現在のファイルが再解析される。"),
        )
        # Ghost placeholder overlaid on the empty Y field so first-time users
        # see that a blank Y means "Y = X" (square scan). It is a separate
        # Label placed on top of the Entry rather than inserted text, so
        # Entry.get() stays "" and the Enter-to-commit / validation machinery
        # keeps treating an untouched Y field as unset. Border and padding are
        # stripped so the ghost fits inside the Entry height.
        # 空の Y 欄に重ねるゴーストプレースホルダ。空欄が「Y = X」（正方スキャン）
        # を意味することを初見のユーザーに伝える。入力テキストではなく Entry に
        # 重ねた別 Label なので Entry.get() は "" のままとなり、Enter 確定・検証
        # 機構は未入力の Y 欄を未設定として扱い続ける。枠と余白を除去して Entry の
        # 高さに収める。
        field_bg = ttk.Style(self).lookup("TEntry", "fieldbackground") or "white"
        self._scale_y_ph = tk.Label(
            self.ent_scale_y_um, text="= X", fg="#8a8a8a", bg=field_bg,
            bd=0, padx=0, pady=0, highlightthickness=0,
        )
        # Clicking the ghost text focuses the underlying Entry.
        # ゴーストテキストのクリックで下の Entry にフォーカスを移す。
        self._scale_y_ph.bind(
            "<Button-1>", lambda _e: self.ent_scale_y_um.focus_set()
        )
        self.ent_scale_y_um.bind(
            "<FocusIn>", self._refresh_scale_y_placeholder, add="+"
        )
        self.ent_scale_y_um.bind(
            "<FocusOut>", self._refresh_scale_y_placeholder, add="+"
        )
        self._refresh_scale_y_placeholder()

        # -- Tick units: radio buttons redraw immediately without reanalysis --
        # ── 軸目盛単位（µm / nm）── ラジオで即時反映（再解析は走らない）。
        ttk.Label(bar, text=_("軸目盛単位")).pack(side="left", padx=(10, 2))
        ttk.Radiobutton(
            bar, text=UNIT_MICROMETER, value=UNIT_MICROMETER,
            variable=self.unit_var, command=self._on_unit_changed,
        ).pack(side="left", padx=(0, 2))
        ttk.Radiobutton(
            bar, text="nm", value="nm",
            variable=self.unit_var, command=self._on_unit_changed,
        ).pack(side="left", padx=(0, 2))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        # -- Height filter: checkbox applies or resets immediately --
        # ── 高さフィルター ── チェックボックス化（即適用/即リセット）。
        ttk.Checkbutton(
            bar, text=_("高さフィルター"),
            variable=self.filter_enabled_var,
            command=self._on_filter_toggle,
        ).pack(side="left", padx=(2, 4))
        ttk.Label(bar, text=_("最小")).pack(side="left", padx=(4, 1))
        self.ent_filter_min = ttk.Entry(bar, width=5, textvariable=self.filter_min_var)
        self.ent_filter_min.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_filter_min,
            lambda: self._fmt_num(self.filter_min),
            self._commit_filter_range,
        )
        ttk.Label(bar, text=_("最大")).pack(side="left", padx=(4, 1))
        self.ent_filter_max = ttk.Entry(bar, width=5, textvariable=self.filter_max_var)
        self.ent_filter_max.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_filter_max,
            lambda: self._fmt_num(self.filter_max),
            self._commit_filter_range,
        )

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        # -- Fiber connection: checkbox re-analyzes; button opens the settings window --
        # ── ファイバー連結 ── チェックボックスで再解析、ボタンで設定ウインドウを開く。
        chk_connect = ttk.Checkbutton(
            bar, text=_("ファイバー連結"),
            variable=self.connect_enabled_var,
            command=self._on_connect_toggle,
        )
        chk_connect.pack(side="left", padx=(2, 2))
        ToolTip(chk_connect, _(
            "ON時: 交差・分岐で分断された骨格断片を 1 本のフィブリルへ再結合してから計測する。\n"
            "OFF時: 各骨格断片を 1 本のファイバーとして扱う（従来動作）。\n"
            "切り替えると現在のデータセットを再解析する。"
        ))
        ttk.Button(
            bar, text=_("連結設定…"),
            command=self._open_connect_settings,
        ).pack(side="left", padx=(0, 4))

    def _build_main(self) -> None:
        """
        Build the main horizontal pane that contains file and analysis views.
        ファイル表示と解析表示を含むメイン横ペインを構築する。
        """
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left   = ttk.Frame(paned)
        center = ttk.Frame(paned)
        paned.add(left,   weight=1)
        paned.add(center, weight=8)

        self._build_left_pane(left)
        self._build_center_pane(center)

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        """
        Build the dataset list pane.
        データセット一覧ペインを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ファイル一覧"))
        lf.pack(fill="both", expand=True, padx=4, pady=4)

        self.file_tree, _file_vsb = create_scrolled_treeview(
            lf,
            columns=("name",),
            show="headings",
            selectmode="browse",
            height=30,
            headings={"name": _("データセット名")},
            column_options={"name": {"width": 140, "anchor": "w"}},
        )
        self.file_tree.bind("<<TreeviewSelect>>", self._on_file_select)

    def _build_center_pane(self, parent: ttk.Frame) -> None:
        """
        Build the center pane with the fiber table, AFM overview, and log.
        ファイバー一覧、AFM 全体像、ログを持つ中央ペインを構築する。

        The right side is split vertically into the AFM overview above and log
        below.
        右側はさらに上下分割で AFM 全体像（上）・ログ（下）を配置する。
        """
        horiz = ttk.PanedWindow(parent, orient="horizontal")
        horiz.pack(fill="both", expand=True)

        # -- Fiber table on the left --
        tbl_outer = ttk.Frame(horiz)
        horiz.add(tbl_outer, weight=2)
        tbl_header = ttk.Frame(tbl_outer)
        tbl_header.pack(side="top", fill="x", padx=2, pady=(2, 0))
        ttk.Label(tbl_header, text=_("ファイバー一覧"), font=("", 9, "bold")).pack(side="left", padx=4)
        ttk.Button(tbl_header, text=_("CSVで保存"), command=self._export_csv).pack(side="left", padx=4)
        tbl_frame = ttk.Frame(tbl_outer)
        tbl_frame.pack(fill="both", expand=True, padx=2, pady=2)
        self._build_fiber_table(tbl_frame)

        # -- Manual fiber-connection annotation, below the fiber table --
        # ── ファイバー表の下に、手動ファイバー連結アノテーションを配置 ──
        self._build_connection_panel(tbl_outer)

        # -- Right side: AFM overview above log --
        right_outer = ttk.Frame(horiz)
        horiz.add(right_outer, weight=5)
        vert = ttk.PanedWindow(right_outer, orient="vertical")
        vert.pack(fill="both", expand=True)

        self._build_afm_overview(vert)
        self._build_log_panel(vert)

    def _build_afm_overview(self, parent: ttk.Frame) -> None:
        """
        Build the AFM overview panel (controls, font sizes, and plot frame).
        AFM 全体像パネル（操作部・フォントサイズ・描画フレーム）を構築する。
        """
        # -- AFM overview, upper row --
        afm_outer = ttk.Frame(parent)
        parent.add(afm_outer, weight=4)

        self._build_afm_controls(afm_outer)
        self._build_afm_font_row(afm_outer)

        self._afm_frame = ttk.Frame(afm_outer)
        self._afm_frame.pack(fill="both", expand=True, padx=2, pady=2)

    def _build_afm_controls(self, afm_outer: ttk.Frame) -> None:
        """
        Build AFM overview row 1: title, auto mode, vmin/vmax, and action buttons.
        AFM 全体像 行1（タイトル・自動・vmin/vmax・操作ボタン）を構築する。
        """
        # Row 1: title, vmin/vmax, auto mode, and action buttons.
        afm_header1 = ttk.Frame(afm_outer)
        afm_header1.pack(side="top", fill="x", padx=2, pady=(2, 0))
        ttk.Label(afm_header1, text=_("AFM 全体像"), font=("", 9, "bold")).pack(side="left", padx=4)

        # Display-mode switch: height image (current) vs. color-coded fibers.
        # Same canvas is re-rendered; this is a mode radio, not a separate tab.
        # 表示モード切替：高さ画像（現行）／ファイバー色分け。同一キャンバスを
        # 再描画する（別タブではなくモードラジオ）。
        rb_height = ttk.Radiobutton(
            afm_header1, text=_("高さ"),
            variable=self.overview_mode_var, value=OVERVIEW_MODE_HEIGHT,
            command=self._on_overview_mode_change,
        )
        rb_height.pack(side="left", padx=(6, 0))
        rb_fibers = ttk.Radiobutton(
            afm_header1, text=_("ファイバー色分け"),
            variable=self.overview_mode_var, value=OVERVIEW_MODE_FIBERS,
            command=self._on_overview_mode_change,
        )
        rb_fibers.pack(side="left", padx=(0, 2))
        ToolTip(rb_fibers, _(
            "各ファイバーを個別色で二値化像上に散布表示します。\n"
            "どの骨格がひとつのフィブリルに繋がったかを一目で確認でき、\n"
            "ファイバー連結の結果検証に有効です。"
        ))
        ttk.Separator(afm_header1, orient="vertical").pack(side="left", fill="y", padx=6, pady=2)

        # Auto checkbox to the left of vmin.
        chk_auto = ttk.Checkbutton(
            afm_header1, text=_("自動"),
            variable=self.auto_vrange_var,
            command=self._on_auto_vrange_toggle,
        )
        chk_auto.pack(side="left", padx=(6, 2))
        ToolTip(chk_auto, _(
            "ON時: 画像ごとに vmin/vmax を自動計算。\n"
            "  vmin = 画像最小値 を切り下げ\n"
            "  vmax = 画像最大値 + 1 を切り上げ\n"
            "OFF時: 入力欄の vmin / vmax を固定使用。"
        ))

        # vmin / vmax use Enter-to-commit entries.
        ttk.Label(afm_header1, text=_("vmin")).pack(side="left", padx=(6, 1))
        self.ent_vmin = ttk.Entry(afm_header1, width=6, textvariable=self.vmin_var)
        self.ent_vmin.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_vmin,
            lambda: self._fmt_num(self.vmin),
            self._commit_vrange,
        )
        ttk.Label(afm_header1, text=_("vmax")).pack(side="left", padx=(4, 1))
        self.ent_vmax = ttk.Entry(afm_header1, width=6, textvariable=self.vmax_var)
        self.ent_vmax.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_vmax,
            lambda: self._fmt_num(self.vmax),
            self._commit_vrange,
        )

        # Action buttons.
        ttk.Button(afm_header1, text=_("画像を保存"),
                   command=self._export_overview).pack(side="left", padx=(10, 4))
        ttk.Button(
            afm_header1, text=_("個別表示"),
            command=self._open_detail_window,
        ).pack(side="left", padx=4)

    def _build_afm_font_row(self, afm_outer: ttk.Frame) -> None:
        """
        Build AFM overview row 2: title, axis-label, tick, and colorbar font sizes.
        AFM 全体像 行2（タイトル/軸ラベル/軸目盛/カラーバーのフォントサイズ）を構築する。
        """
        # Row 2: four font sizes for title, axis label, ticks, and colorbar.
        afm_header2 = ttk.Frame(afm_outer)
        afm_header2.pack(side="top", fill="x", padx=2, pady=(0, 2))

        ttk.Label(afm_header2, text=_("フォントサイズ：タイトル")).pack(side="left", padx=(8, 1))
        self.ent_fs_title = ttk.Entry(afm_header2, width=4, textvariable=self.fs_title_var)
        self.ent_fs_title.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_fs_title,
            lambda: self._fmt_num(self.fs_title),
            self._commit_afm_font_sizes,
        )

        ttk.Label(afm_header2, text=_("軸ラベル")).pack(side="left", padx=(8, 1))
        self.ent_fs_label = ttk.Entry(afm_header2, width=4, textvariable=self.fs_label_var)
        self.ent_fs_label.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_fs_label,
            lambda: self._fmt_num(self.fs_label),
            self._commit_afm_font_sizes,
        )

        ttk.Label(afm_header2, text=_("軸目盛")).pack(side="left", padx=(8, 1))
        self.ent_fs_tick = ttk.Entry(afm_header2, width=4, textvariable=self.fs_tick_var)
        self.ent_fs_tick.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_fs_tick,
            lambda: self._fmt_num(self.fs_tick),
            self._commit_afm_font_sizes,
        )

        ttk.Label(afm_header2, text=_("カラーバー")).pack(side="left", padx=(8, 1))
        self.ent_fs_cbar = ttk.Entry(afm_header2, width=4, textvariable=self.fs_cbar_var)
        self.ent_fs_cbar.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_fs_cbar,
            lambda: self._fmt_num(self.fs_cbar),
            self._commit_afm_font_sizes,
        )

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log panel (save-log button and scrolled text), matching GUI01.
        ログパネル（ログ保存ボタンとスクロール付きテキスト）を GUI01 と同様に構築する。
        """
        # -- Log, lower row: match GUI01 behavior --
        # ── ログ（下段） ── GUI01 と同じ仕様に揃える。
        # Use only a Save Log button in the header, without a LabelFrame.
        # ・LabelFrame は使わず、「ログを保存」ボタンのみをヘッダー行に置く。
        # Keep the text area and scrollbar in the inner log container.
        # ・テキストエリアとスクロールバーは内側コンテナ log_inner にまとめる。
        log_outer = ttk.Frame(parent)
        parent.add(log_outer, weight=1)

        # Put the Save Log button at the left edge of the header row.
        # ログヘッダー行：「ログを保存」ボタンを左端に配置する。
        # The button text and text area make the log context clear without an extra label.
        # ボタンのテキスト自体が「ログを保存」と明示しており、直下のテキスト領域が
        # obviously represents the log, so an additional Log label is unnecessary.
        # ログであることは自明なので、別途「ログ」ラベルは設けない。
        log_header = ttk.Frame(log_outer)
        log_header.pack(side="top", fill="x", padx=2, pady=(2, 2))
        self.btn_save_log = ttk.Button(log_header, text=_("ログを保存"),
                                       command=self.on_save_log)
        self.btn_save_log.pack(side="left")
        self.btn_clear_log = ttk.Button(log_header, text=_("ログをクリア"),
                                        command=self._clear_log)
        self.btn_clear_log.pack(side="left", padx=(4, 0))

        # Inner container for log text and scrollbar.
        log_inner = ttk.Frame(log_outer)
        log_inner.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.log_text, _log_vsb = create_scrolled_text(
            log_inner,
            wrap="word",
            state="disabled",
            font=("", 8),
            height=6,
        )

    def _build_fiber_table(self, parent: ttk.Frame) -> None:
        """
        Build the fiber table used for selecting tracked fibers.
        追跡済みファイバーを選択するための一覧テーブルを構築する。
        """
        cols = ("#", "length (nm)", "median (nm)", "max (nm)", "EP count", "Kink count")
        self.fiber_tree, _fiber_vsb = create_scrolled_treeview(
            parent, columns=cols, show="headings", selectmode="browse",
        )
        col_widths = {"#": 30, "length (nm)": 65, "median (nm)": 70, "max (nm)": 70, "EP count": 55, "Kink count": 65}
        for col in cols:
            self.fiber_tree.heading(col, text=col)
            self.fiber_tree.column(col, width=col_widths[col], anchor="center")
        self.fiber_tree.bind("<<TreeviewSelect>>", self._on_fiber_select)

    # =========================================================================
    # Manual fiber-connection annotation
    # 手動ファイバー連結アノテーション
    # =========================================================================

    def _build_connection_panel(self, parent: ttk.Frame) -> None:
        """
        Build the manual fiber-connection panel below the fiber table.
        ファイバー表の下に、手動ファイバー連結のパネルを構築する。
        """
        lf = ttk.LabelFrame(parent, text=_("ファイバー連結（手動）"))
        lf.pack(side="bottom", fill="x", padx=2, pady=(2, 2))

        ttk.Label(
            lf, justify="left", wraplength=280,
            text=_("一覧か全体像でファイバーを選び、「始点に設定」を押し、別の"
                   "ファイバーを選んで「連結」で 2 本を結びます。自動連結の誤りは、"
                   "連結を選んで「つながらない」で正します。"),
        ).pack(anchor="w", padx=6, pady=(4, 2))

        pick = ttk.Frame(lf)
        pick.pack(fill="x", padx=6, pady=1)
        self.btn_set_first = ttk.Button(
            pick, text=_("始点に設定"), command=self._on_set_first)
        self.btn_set_first.pack(side="left")
        self.pending_var = tk.StringVar(value=_("始点: —"))
        ttk.Label(pick, textvariable=self.pending_var).pack(side="left", padx=6)
        self.btn_connect = ttk.Button(
            pick, text=_("連結") + " (connect)", command=self._on_connect_selected)
        self.btn_connect.pack(side="right")

        conn_frame = ttk.Frame(lf)
        conn_frame.pack(fill="both", expand=False, padx=4, pady=2)
        # Column headings stay fixed English per the analysis-table convention.
        # 列見出しは分析表の規約に従い固定英語のままにする。
        self.conn_tree, _conn_sb = create_scrolled_treeview(
            conn_frame, columns=("#", "fibers", "verdict"),
            show="headings", selectmode="browse", height=6,
            headings={"#": "#", "fibers": "fibers", "verdict": "verdict"},
            column_options={
                "#": {"width": 34, "anchor": "center"},
                "fibers": {"width": 80, "anchor": "center"},
                "verdict": {"width": 90, "anchor": "center"},
            },
        )
        # Color each row's text by verdict so the list is scannable.
        # 判定ごとに行の文字色を付け、一覧を一目で追えるようにする。
        for verdict in VERDICT_ORDER:
            self.conn_tree.tag_configure(
                verdict, foreground=VERDICT_COLORS[verdict])
        self.conn_tree.bind("<<TreeviewSelect>>", self._on_conn_row_select)

        # No fixed button widths: the labels differ in length across languages
        # (e.g. Japanese "つながる" vs. English "Same fiber"), so let each button
        # size to its own text instead of clipping it.
        # ボタン幅は固定しない。ラベル長は言語で異なる（例：日本語「つながる」対
        # 英語「Same fiber」）ため、各ボタンを自身の文字に合わせて伸縮させ、
        # 文字切れを防ぐ。
        vb = ttk.Frame(lf)
        vb.pack(fill="x", padx=6, pady=(1, 2))
        self.btn_v_connect = ttk.Button(
            vb, text=_("つながる"),
            command=lambda: self._set_conn_verdict(VERDICT_CONNECT))
        self.btn_v_connect.pack(side="left", padx=1)
        self.btn_v_reject = ttk.Button(
            vb, text=_("つながらない"),
            command=lambda: self._set_conn_verdict(VERDICT_REJECT))
        self.btn_v_reject.pack(side="left", padx=1)
        self.btn_v_uncertain = ttk.Button(
            vb, text=_("保留"),
            command=lambda: self._set_conn_verdict(VERDICT_UNCERTAIN))
        self.btn_v_uncertain.pack(side="left", padx=1)
        self.btn_delete_conn = ttk.Button(
            vb, text=_("削除"), command=self._on_delete_connection)
        self.btn_delete_conn.pack(side="left", padx=1)

        save = ttk.Frame(lf)
        save.pack(fill="x", padx=6, pady=(0, 4))
        self.btn_save_labels = ttk.Button(
            save, text=_("ラベルを保存"), command=self.on_save_labels)
        self.btn_save_labels.pack(side="left")
        self.conn_counts_var = tk.StringVar(value="")
        ttk.Label(save, textvariable=self.conn_counts_var).pack(
            side="left", padx=8)

    # ----- Connection table ------------------------------------------------

    def _conn_row_values(self, index: int, conn: Dict) -> tuple:
        """
        Return the connection-table row tuple for one connection.
        1 件の連結ぶんの、連結テーブル行タプルを返す。
        """
        return (index, "{a}–{b}".format(a=conn["a"], b=conn["b"]),
                conn["verdict"])

    def _populate_connection_table(self) -> None:
        """
        Rebuild the connection table from the current connection list.
        現在の連結リストから連結テーブルを作り直す。
        """
        for iid in self.conn_tree.get_children():
            self.conn_tree.delete(iid)
        for index, conn in enumerate(self._connections):
            self.conn_tree.insert(
                "", "end", iid=str(index),
                values=self._conn_row_values(index, conn),
                tags=(conn["verdict"],))
        self._update_connection_counts()

    def _refresh_conn_row(self, index: int) -> None:
        """
        Refresh one connection row after its verdict changed.
        判定が変わった 1 件の連結行を更新する。
        """
        iid = str(index)
        if self.conn_tree.exists(iid):
            conn = self._connections[index]
            self.conn_tree.item(
                iid, values=self._conn_row_values(index, conn),
                tags=(conn["verdict"],))

    def _update_connection_counts(self) -> None:
        """
        Refresh the connection counter shown beside the save button.
        保存ボタンの横に表示する連結カウンタを更新する。
        """
        if not self._connections:
            self.conn_counts_var.set("")
            return
        counts = {v: 0 for v in VERDICT_ORDER}
        for conn in self._connections:
            counts[conn["verdict"]] = counts.get(conn["verdict"], 0) + 1
        # Verdict names stay fixed English; the label around them is localized.
        # 判定名は固定英語のまま。囲むラベルはローカライズする。
        self.conn_counts_var.set(
            _("連結 {n} 件").format(n=len(self._connections))
            + "  (connect={c} reject={r} uncertain={u})".format(
                c=counts[VERDICT_CONNECT], r=counts[VERDICT_REJECT],
                u=counts[VERDICT_UNCERTAIN]))

    # ----- Connection selection -------------------------------------------

    def _on_conn_row_select(self, _event=None) -> None:
        """
        Update the selected connection and refresh the overview highlight.
        選択中の連結を更新し、全体像の強調表示を更新する。
        """
        sel = self.conn_tree.selection()
        if not sel:
            return
        try:
            index = int(sel[0])
        except ValueError:
            return
        if index == self._conn_sel_idx:
            return
        self._conn_sel_idx = index
        self._refresh_overview()
        self._update_connection_controls()

    def _select_connection(self, index: int) -> None:
        """
        Select a connection row by index and scroll it into view.
        連結行を添字で選び、表示範囲へスクロールする。
        """
        iid = str(index)
        if not self.conn_tree.exists(iid):
            return
        self._conn_sel_idx = index
        self.conn_tree.selection_set(iid)
        self.conn_tree.focus(iid)
        self.conn_tree.see(iid)
        self._refresh_overview()
        self._update_connection_controls()

    def _current_connection(self) -> Optional[Dict]:
        """
        Return the selected connection, or None when nothing is selected.
        選択中の連結を返す。未選択なら None。
        """
        if self._conn_sel_idx is None or self._conn_sel_idx >= len(self._connections):
            return None
        return self._connections[self._conn_sel_idx]

    # ----- Connection editing ---------------------------------------------

    def _on_set_first(self) -> None:
        """
        Set the currently selected fiber as the connection's first endpoint.
        現在選択中のファイバーを連結の 1 本目に設定する。
        """
        if self._sel_idx is None:
            return
        self._pending_fiber = self._sel_idx
        self.pending_var.set(_("始点: #{i}").format(i=self._pending_fiber))
        self._update_connection_controls()

    def _on_connect_selected(self) -> None:
        """
        Connect the pending first fiber to the currently selected fiber.
        保留中の 1 本目と、現在選択中のファイバーを連結する。
        """
        a = self._pending_fiber
        b = self._sel_idx
        if a is None or b is None or a == b:
            return
        if self._has_connection(a, b):
            self._log(_("その 2 本はすでに連結されています。"))
            return
        fibers = self._displayed_fibers()
        if a >= len(fibers) or b >= len(fibers):
            return
        pair = self._nearest_endpoint_pair(
            self._fiber_ends(fibers[a]), self._fiber_ends(fibers[b]))
        if pair is None:
            self._log(_("端点が見つからないため連結できません。"))
            return
        a_xy, b_xy = pair
        self._connections.append({
            "a": a, "b": b, "a_xy": a_xy, "b_xy": b_xy,
            "verdict": VERDICT_CONNECT})
        new_index = len(self._connections) - 1
        self.conn_tree.insert(
            "", "end", iid=str(new_index),
            values=self._conn_row_values(new_index, self._connections[new_index]),
            tags=(VERDICT_CONNECT,))
        self._labels_dirty = True
        self._pending_fiber = None
        self.pending_var.set(_("始点: —"))
        self._log(_("ファイバー #{a} と #{b} を連結しました。").format(a=a, b=b))
        self._update_connection_counts()
        self._select_connection(new_index)

    def _set_conn_verdict(self, verdict: str) -> None:
        """
        Set the selected connection's verdict.
        選択中の連結の判定を設定する。
        """
        conn = self._current_connection()
        if conn is None:
            return
        if conn["verdict"] != verdict:
            conn["verdict"] = verdict
            self._labels_dirty = True
        self._refresh_conn_row(self._conn_sel_idx)
        self._update_connection_counts()
        self._refresh_overview()

    def _on_delete_connection(self) -> None:
        """
        Remove the selected connection.
        選択中の連結を削除する。
        """
        if self._conn_sel_idx is None or self._conn_sel_idx >= len(self._connections):
            return
        del self._connections[self._conn_sel_idx]
        self._conn_sel_idx = None
        self._labels_dirty = True
        self._populate_connection_table()
        self._refresh_overview()
        self._update_connection_controls()

    def _has_connection(self, a: int, b: int) -> bool:
        """
        Return whether fibers ``a`` and ``b`` are already connected.
        ファイバー ``a`` と ``b`` がすでに連結されているかを返す。
        """
        pair = frozenset((a, b))
        return any(frozenset((c["a"], c["b"])) == pair for c in self._connections)

    def _displayed_fibers(self) -> List[Fiber]:
        """
        Return the fibers currently shown, respecting the height filter.
        現在表示中のファイバーを返す（高さフィルターを反映）。
        """
        return self._filtered_fibers if self._filter_active else self.current_fibers

    def _fiber_ends(self, fiber: Fiber) -> List[Tuple[int, int]]:
        """
        Return one fiber's endpoint coordinates in the skeleton frame.
        1 本のファイバーの端点座標を骨格座標系で返す。

        Computed from the fiber object itself so it stays correct regardless of
        the height filter's re-indexing, and matches the coordinates a label
        sidecar records.
        ファイバーオブジェクト自体から算出するため、高さフィルターの再採番に関わらず
        正しく、ラベル sidecar が記録する座標と一致する。
        """
        from lib import ml_connect_features as cf
        return [end.xy for end in cf.fragment_ends([fiber])]

    def _nearest_endpoint_pair(
        self, ends_a: List[Tuple[int, int]], ends_b: List[Tuple[int, int]]
    ) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
        """
        Return the closest endpoint pair between two fibers' endpoints.
        2 本のファイバーの端点集合の間で、最も近い端点ペアを返す。

        A connection is recorded as the two real fragment endpoints that a
        label sidecar stores, so the closest ends are chosen as the pair that
        identifies where the two fibers meet.
        連結はラベル sidecar が保存する 2 つの実在断片端点として記録するため、
        2 本が接する箇所を同定するペアとして最近接の端点を選ぶ。
        """
        best: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None
        best_d: Optional[float] = None
        for pa in ends_a:
            for pb in ends_b:
                d = (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2
                if best_d is None or d < best_d:
                    best_d, best = d, (pa, pb)
        return best

    def _update_connection_controls(self) -> None:
        """
        Enable connection controls to match the current selection state.
        現在の選択状態に合わせて連結の操作部を有効化する。
        """
        if self.is_running:
            return
        loaded = self.current_image is not None
        has_fiber = loaded and self._sel_idx is not None
        self.btn_set_first.configure(
            state=tk.NORMAL if has_fiber else tk.DISABLED)
        can_connect = (
            has_fiber and self._pending_fiber is not None
            and self._pending_fiber != self._sel_idx
            and not self._has_connection(self._pending_fiber, self._sel_idx))
        self.btn_connect.configure(
            state=tk.NORMAL if can_connect else tk.DISABLED)
        has_conn = self._current_connection() is not None
        for btn in (self.btn_v_connect, self.btn_v_reject,
                    self.btn_v_uncertain, self.btn_delete_conn):
            btn.configure(state=tk.NORMAL if has_conn else tk.DISABLED)
        self.btn_save_labels.configure(
            state=tk.NORMAL if (loaded and self._connections) else tk.DISABLED)

    # ----- Overview connection drawing ------------------------------------

    def _refresh_overview(self) -> None:
        """
        Redraw the overview highlight and connections for the current selection.
        現在の選択に合わせて全体像の強調表示と連結を再描画する。
        """
        if self.current_image is not None:
            self._draw_overview(selected_fiber=self._current_fiber())

    def _draw_connections(self) -> None:
        """
        Draw every recorded connection over the overview, emphasizing the
        selected one.
        記録済みの全連結を全体像へ描画し、選択中のものを強調する。

        Pixel endpoint coordinates are converted to the overview's physical
        extent (per axis) the same way the fiber boxes are, so the lines land
        on the fibers.
        画素の端点座標を、ファイバー枠と同じ方法で全体像の物理 extent（軸別）へ
        変換し、線がファイバー上に載るようにする。
        """
        for art in self._connection_artists:
            try:
                art.remove()
            except (ValueError, AttributeError):
                pass
        self._connection_artists = []
        if self.current_image is None or not self._connections:
            return
        x_scale, y_scale, _unit = self._get_extent_scale_xy_and_unit()
        img = self.current_image.calibrated_image
        h_px, w_px = img.shape[:2]
        x_spp = x_scale / w_px
        y_spp = y_scale / h_px
        halo = [pe.Stroke(linewidth=4.2, foreground=CONNECTION_HALO_COLOR),
                pe.Normal()]
        for index, conn in enumerate(self._connections):
            (ax_, ay), (bx, by) = conn["a_xy"], conn["b_xy"]
            color = VERDICT_COLORS[conn["verdict"]]
            selected = (index == self._conn_sel_idx)
            xs = [ax_ * x_spp, bx * x_spp]
            ys = [ay * y_spp, by * y_spp]
            line, = self._afm_ax.plot(
                xs, ys, "-", linewidth=3.2 if selected else 1.8, color=color,
                path_effects=halo, zorder=5)
            dots, = self._afm_ax.plot(
                xs, ys, linestyle="none", marker="o",
                markersize=7 if selected else 5, markerfacecolor=color,
                markeredgecolor=CONNECTION_HALO_COLOR, markeredgewidth=1.2,
                zorder=6)
            self._connection_artists.extend((line, dots))

    # ----- Saving connection labels ---------------------------------------

    def on_save_labels(self) -> None:
        """
        Write the recorded connections to the connection-label sidecar.
        記録した連結を、連結ラベル sidecar へ書き出す。
        """
        if self.is_running or not self.current_stem:
            return
        if not self._connections:
            messagebox.showinfo(
                _("連結がありません"),
                _("保存する連結がありません。ファイバーを連結してから保存してください。"))
            return
        try:
            from lib import ml_connect_labels as cl
        except ImportError as exc:
            messagebox.showerror(_("エラー"), str(exc))
            return
        from dataclasses import asdict
        # Record the connector's parameters so the labels can be interpreted
        # later against the gates the automatic proposals came from.
        # 自動提示の元になったゲートに照らして後からラベルを解釈できるよう、
        # 連結器のパラメータを記録する。
        params = asdict(self.connect_params)
        decisions = [
            cl.make_decision(
                cl.point(*conn["a_xy"]), cl.point(*conn["b_xy"]),
                conn["verdict"], source=SOURCE_MANUAL,
                fragments=[conn["a"], conn["b"]])
            for conn in self._connections
        ]
        try:
            labels = cl.make_labels(
                self.current_stem + BUNDLE_EXT, self._skeleton_hash,
                params, decisions,
                created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                input_sha256=self._input_sha256)
            path = cl.save_labels(
                cl.label_path_for(self.current_stem + BUNDLE_EXT), labels)
        except Exception as exc:  # noqa: BLE001 - report any save failure.
            messagebox.showerror(_("保存に失敗しました"), str(exc))
            return
        self._labels_dirty = False
        self._log(_("ラベルを保存しました: {p}").format(p=os.path.basename(path)))
        messagebox.showinfo(
            _("保存しました"),
            _("連結 {n} 件を保存しました。\n{p}").format(
                n=len(self._connections), p=path))

    # =========================================================================
    # matplotlib figure initialization
    # =========================================================================

    def _init_figures(self) -> None:
        """
        Initialize the AFM overview matplotlib figure.
        AFM 全体像用の matplotlib Figure を初期化する。
        """

        # Only the AFM overview remains in the main window.
        # AFM 全体像（メインウインドウに残るのはこれだけ）。
        self._afm_fig = plt.Figure(figsize=(6.0, 6.0), dpi=90)
        self._afm_ax  = self._afm_fig.add_subplot(111)
        self._afm_ax.axis("off")
        self._afm_canvas = FigureCanvasTkAgg(self._afm_fig, master=self._afm_frame)
        self._afm_canvas.get_tk_widget().pack(fill="both", expand=True)

        # Store the overview colorbar so redraws can remove and recreate it.
        # AFM 全体像のカラーバー参照（再描画のたびに remove して作り直す）。
        self._afm_cbar = None

        # Call tight_layout only once at initialization because it is expensive.
        # tight_layout は初期化時に1回だけ呼ぶ（描画のたびに呼ぶのは高コスト）。
        self._afm_fig.tight_layout(pad=0.5)

    # =========================================================================
    # Logging
    # =========================================================================
    # _log is inherited from ui_tools.LogMixin.

    # =========================================================================
    # Unconfirmed-entry mechanism, equivalent to GUI01 / GUI02
    # =========================================================================
    # Each Entry compares the displayed text with committed internal state on KeyRelease.
    # 各 Entry は「内部状態 (self.* の値) と入力欄テキストが一致しているか」を
    # evaluate on each KeyRelease event.
    # KeyRelease のたびに評価する。
    # A mismatch gets the unconfirmed style, and Enter commits all entries in the registry.
    # 不一致なら未確定スタイル (薄青) を当て、Enter で同じ登録簿上の全未確定 Entry の
    # callbacks at once into internal state.
    # commit_cb がまとめて呼ばれて内部状態に一括反映される。
    # Focus-out intentionally does not commit values.
    # フォーカスアウトでは確定しない（Enter のみが確定動作）。
    # FiberDetailWindow uses its own registry, selected by the registry argument.
    # FiberDetailWindow は独自の登録簿を持ち、registry 引数で切り替えて利用する。
    #
    # Shared implementation is centralized in ui_tools.UnconfirmedEntryMixin.
    # 共通実装は ui_tools.UnconfirmedEntryMixin に集約済み。
    # _fmt_num / _register_unconfirmed_entry / _commit_all_unconfirmed /
    # _refresh_all_entry_states は Mixin から継承する。

    def _commit_scale_um(self) -> bool:
        """
        Commit the scale in micrometers and reload if the value changed.
        スケール (µm) を確定し、値が変化していれば再読み込みする。
        """
        old_scale = self.scale_um

        def _on_success():
            """
            Reload the dataset after a committed scale change.
            確定済みスケール変更後にデータセットを再読み込みする。
            """
            # Reload only when a dataset exists and the committed scale changed.
            # 値が変化していてデータが読み込まれていれば再解析する。
            if abs(self.scale_um - old_scale) > 1e-9 \
                    and self.current_stem and self.current_image is not None:
                self._log(
                    (_("スケール変更") + " ({old} → {new} µm): "
                     + _("ファイバーを再解析します...")).format(
                        old=self._fmt_num(old_scale), new=self._fmt_num(self.scale_um)
                    )
                )
                self._overview_bg_drawn = False
                self._reload_current_file()

        return self._commit_float_fields(
            [(self.ent_scale_um, "scale_um", "scale_um")],
            validator=lambda v: None if v["scale_um"] > 0
            else _("スケール") + " (µm) " + _("には正の数値を入力してください。"),
            on_success=_on_success,
        )

    def _commit_scale_y_um(self) -> bool:
        """
        Commit the optional Y (height) scale and reload if the value changed.
        任意の Y（高さ）スケールを確定し、値が変化していれば再読み込みする。

        An empty field commits ``None``, meaning the Y size follows the X size
        (square scan); a non-empty field must be a positive number. Handled
        separately from `_commit_scale_um` because the shared
        `_commit_float_fields` helper cannot express the empty-means-default
        case.
        空欄は ``None`` を確定し、Y サイズが X サイズに従う（正方スキャン）こと
        を意味する。非空欄は正の数であること。空欄を既定値として扱う仕様は共有
        ヘルパー `_commit_float_fields` では表現できないため別実装とする。
        """
        old_scale_y = self.scale_y_um
        raw = self.ent_scale_y_um.get().strip()
        if raw == "":
            self.scale_y_um = None
            committed = ""
        else:
            try:
                value = float(raw)
            except ValueError:
                messagebox.showerror(_("エラー"), _("数値を入力してください"))
                return False
            if not (value > 0):
                messagebox.showerror(
                    _("エラー"),
                    _("スケール") + " (µm) " + _("には正の数値を入力してください。"),
                )
                return False
            self.scale_y_um = value
            committed = self._fmt_num(value)
        rewrite_entries(((self.ent_scale_y_um, committed),))
        mark_entry_state(self.ent_scale_y_um, committed)
        # Re-show the "= X" ghost when the field committed back to empty.
        # 空欄に確定した場合は "= X" ゴーストを再表示する。
        self._refresh_scale_y_placeholder()
        # Reload only when the committed Y scale changed and a dataset exists.
        # Y スケールが変化していてデータが読み込まれている場合のみ再解析する。
        changed = (old_scale_y is None) != (self.scale_y_um is None) or (
            old_scale_y is not None and self.scale_y_um is not None
            and abs(old_scale_y - self.scale_y_um) > 1e-9
        )
        if changed and self.current_stem and self.current_image is not None:
            self._log(_("Y スケール変更: ファイバーを再解析します..."))
            self._overview_bg_drawn = False
            self._reload_current_file()
        return True

    def _refresh_scale_y_placeholder(self, _event=None) -> None:
        """
        Show or hide the "= X" ghost on the Y (height) scale field.
        Y（高さ）スケール欄の "= X" ゴーストの表示/非表示を切り替える。

        The ghost is shown only while the Y field is empty and unfocused, so it
        reads as placeholder text hinting that a blank Y follows X (square
        scan) without ever contributing to ``Entry.get()``.
        ゴーストは Y 欄が空かつ非フォーカスのときだけ表示し、空の Y が X に従う
        （正方スキャン）ことを示すプレースホルダとして読ませる。Entry.get() には
        一切影響しない。
        """
        entry = self.ent_scale_y_um
        try:
            focused = entry.focus_get() is entry
            empty = entry.get() == ""
        except tk.TclError:
            return
        if empty and not focused:
            # Overlay the ghost at the left inner edge of the field.
            # フィールド左内側にゴーストを重ねる。
            self._scale_y_ph.place(x=4, rely=0.5, anchor="w")
        else:
            self._scale_y_ph.place_forget()

    def _scale_xy_um(self) -> tuple:
        """
        Return the (X, Y) scan size in micrometers; Y falls back to X when unset.
        走査範囲 (X, Y) を µm で返す。Y 未設定時は X にフォールバックする。
        """
        y = self.scale_y_um if self.scale_y_um is not None else self.scale_um
        return self.scale_um, y

    def _on_unit_changed(self) -> None:
        """
        Handle tick-unit changes without rerunning fiber analysis.
        軸目盛単位の変更時に、解析を再実行せず表示だけ更新する。
        """
        if self.current_image is None:
            return
        # Tick-unit changes invalidate the cached background, including axis labels.
        # 軸目盛変更は背景キャッシュ（軸ラベル含む）を無効化する。
        self._overview_bg_drawn = False
        fiber = self._current_fiber()
        self._draw_overview(selected_fiber=fiber)
        # Redraw the detail image if open; profiles are fixed in nanometers.
        # 個別表示が開いていれば拡大像を再描画（プロファイルは nm 固定なので不要）。
        if self._detail_window_alive():
            try:
                self._detail_window.redraw_fiber_only()
            except Exception:
                pass

    # ---------- Save log ----------
    def on_save_log(self) -> None:
        """
        Save the log text box through the shared log-save helper.
        共通のログ保存ヘルパーでログテキストボックスの内容を保存する。
        """
        save_text_widget_log(
            self,
            self.log_text,
            initial_dir=self._default_save_dir(),
            initialfile="log.txt",
            log_cb=self._log,
            success_message=_("ログ保存: {path}"),
            error_title=_("ログ保存失敗"),
        )

    # ---------- Scale conversion utilities ----------
    def _get_scale_nm(self) -> float:
        """
        Return the committed scale in nanometers for internal processing.
        内部処理用に、確定済みスケールを nm 単位で返す。
        """
        sc = self.scale_um if self.scale_um > 0 else DEFAULT_IMAGE_SIZE_UM
        return sc * 1000.0

    def _get_extent_scale_xy_and_unit(self) -> tuple:
        """
        Return per-axis extent scales and the shared unit label.
        軸別の extent スケールと共通の単位ラベルを返す。

        X uses the width scale and Y the height scale, so rectangular scans and
        non-square pixel grids draw with the correct physical aspect. The input
        fields are fixed in micrometers; nanometer display multiplies by 1000.
        X は幅スケール、Y は高さスケールを使い、矩形スキャンや非正方ピクセル格子
        を正しい物理アスペクトで描画する。入力欄は µm 固定で、nm 表示では 1000 倍する。
        """
        x_um, y_um = self._scale_xy_um()
        unit = self.unit_var.get()
        x_scale, unit_label = extent_scale_and_unit(x_um, unit)
        y_scale, _unit_label = extent_scale_and_unit(y_um, unit)
        return x_scale, y_scale, unit_label

    def _commit_vrange(self) -> bool:
        """
        Validate and commit vmin and vmax together.
        vmin / vmax をまとめて検証・確定する。
        """
        def _on_success():
            """
            Redraw overview and detail image after vmin/vmax commit.
            vmin/vmax 確定後に全体像と個別拡大像を再描画する。
            """
            # Redraw the AFM overview and any open detail image.
            # AFM全体像 + 個別表示拡大像を再描画する。
            if self.current_image is not None:
                self._overview_bg_drawn = False
                self._rebuild_overview_bg()
                fiber = self._current_fiber()
                if fiber is not None:
                    self._draw_overview(selected_fiber=fiber)
                    self._update_detail_window(fiber)
                else:
                    self._afm_canvas.draw_idle()

        return self._commit_float_fields(
            [
                (self.ent_vmin, "vmin", "vmin"),
                (self.ent_vmax, "vmax", "vmax"),
            ],
            validator=lambda v: None if v["vmax"] >= v["vmin"]
            else _("vmin は vmax 以下にしてください。"),
            on_success=_on_success,
        )

    def _commit_filter_range(self) -> bool:
        """
        Validate and commit the height-filter minimum and maximum.
        高さフィルターの min/max をまとめて検証・確定する。
        """
        def _on_success():
            """
            Reapply the height filter after range commit when enabled.
            有効時は範囲確定後に高さフィルターを再適用する。
            """
            if self.filter_enabled_var.get() and self.current_image is not None:
                self._apply_filter()

        return self._commit_float_fields(
            [
                (self.ent_filter_min, "filter_min", "filter_min"),
                (self.ent_filter_max, "filter_max", "filter_max"),
            ],
            validator=lambda v: None if v["filter_min"] < v["filter_max"]
            else _("最小値 < 最大値 となるように入力してください。"),
            on_success=_on_success,
        )

    def _commit_afm_font_sizes(self) -> bool:
        """
        Validate and commit the four AFM overview font sizes.
        AFM 全体像の 4 種類のフォントサイズをまとめて検証・確定する。
        """
        def _on_success():
            """
            Redraw the overview after AFM font-size commit.
            AFM フォントサイズ確定後に全体像を再描画する。
            """
            # Redraw only the AFM overview; detail image and profile are unaffected.
            # AFM全体像のみ再描画（拡大像・プロファイルには効かない）。
            if self.current_image is not None:
                self._overview_bg_drawn = False
                fiber = self._current_fiber()
                self._draw_overview(selected_fiber=fiber)

        def _check(v):
            """
            Validate AFM overview font-size ranges.
            AFM 全体像のフォントサイズ範囲を検証する。
            """
            if not all(1 <= v[k] <= 60
                       for k in ("fs_title", "fs_label", "fs_tick", "fs_cbar")):
                return _("フォントサイズは 1〜60 の範囲で入力してください。")
            return None

        return self._commit_float_fields(
            [
                (self.ent_fs_title, "fs_title", "title"),
                (self.ent_fs_label, "fs_label", "label"),
                (self.ent_fs_tick,  "fs_tick",  "tick"),
                (self.ent_fs_cbar,  "fs_cbar",  "cbar"),
            ],
            validator=_check,
            on_success=_on_success,
        )

    def _reload_current_file(self) -> None:
        """
        Reload the current file after committed settings such as scale change.
        スケール変更などの確定済み設定に合わせて現在ファイルを再読み込みする。
        """
        sel = self.file_tree.selection()
        if sel:
            self._on_file_select()

    # =========================================================================
    # Automatic value helpers
    # =========================================================================
    # vmin/vmax auto calculation is centralized in ui_tools.py and shared by GUI02/GUI04.
    # 注: vmin/vmax の自動計算 (compute_auto_vrange) は ui_tools.py に集約済み。
    # GUI02 and GUI04 share the same helper function.
    # GUI02 / GUI04 で同じ関数を共有する。
    # ylim auto calculation stays here because it is specific to GUI04 profiles.
    # ylim の自動計算は GUI04 固有のロジックのためここに残す。

    def _compute_auto_ylim(self, fiber: Fiber) -> int:
        """
        Compute an automatic profile Y-axis upper limit from a fiber.
        ファイバープロファイルから Y 軸上限を自動計算する。

        The upper limit is ``ceil(max(height) + 1)`` with a default fallback.
        上限は ``ceil(max(height) + 1)`` とし、失敗時は既定値に戻す。
        """
        if fiber is None or len(fiber.height) == 0:
            return int(math.ceil(DEFAULT_HEIGHT_YLIM))
        try:
            mx = float(np.nanmax(fiber.height))
        except (ValueError, TypeError):
            return int(math.ceil(DEFAULT_HEIGHT_YLIM))
        return int(math.ceil(mx + 1.0))

    # =========================================================================
    # Folder selection
    # =========================================================================

    def _default_save_dir(self) -> str:
        """
        Return the selected GUI01 output folder for save dialogs.
        保存ダイアログ用に、選択済みの GUI01 出力フォルダを返す。
        """
        return self.folder_path or os.getcwd()

    def _on_select_folder(self) -> None:
        """
        Handle folder selection and reset dataset-dependent UI state.
        フォルダ選択時に、データセット依存の UI 状態を初期化する。
        """
        folder = filedialog.askdirectory(title=_("GUI01 の出力フォルダを選択"))
        if not folder:
            return
        self.folder_path = folder
        self._log(_("フォルダ: {folder}").format(folder=folder))

        stems = find_analyzed_stems(folder)
        for iid in self.file_tree.get_children():
            self.file_tree.delete(iid)

        # -- Reset state when switching folders --
        # Clear the height-filter checkbox but keep the Entry values.
        # 高さフィルター はチェック OFF、Entry 値は保持する。
        self.filter_enabled_var.set(False)
        self._filter_active   = False
        self._filtered_fibers = []
        # Clear retained dataset objects.
        self.current_image  = None
        self.current_fibers = []
        self.current_stem   = ""
        self._fiber_stats   = []
        self._sel_idx       = None
        self._overview_bg_drawn = False
        self._highlight_patch   = None
        # Clear the fiber table.
        for iid in self.fiber_tree.get_children():
            self.fiber_tree.delete(iid)
        # Clear the AFM overview.
        self._afm_ax.clear()
        self._afm_ax.axis("off")
        if self._afm_cbar is not None:
            try:
                self._afm_cbar.remove()
            except Exception:
                pass
            self._afm_cbar = None
        self._afm_canvas.draw_idle()
        # Clear detail-window plots if a detail window is open.
        if self._detail_window_alive():
            try:
                self._detail_window.clear_for_no_selection()
            except Exception:
                pass

        if not stems:
            self._log(_("解析済みデータセットが見つかりませんでした。"))
            return

        for stem in stems:
            self.file_tree.insert("", "end", iid=stem, values=(os.path.basename(stem),))
        self._log(_("{count} 件のデータセットを検出しました。").format(count=len(stems)))
        # Do not auto-select; after folder selection, the dataset intentionally stays unselected.
        # 自動選択は行わない（仕様変更：フォルダ選択直後は未選択）。

    # =========================================================================
    # File selection
    # =========================================================================

    def _on_file_select(self, _event=None) -> None:
        """
        Start loading and analyzing the selected GUI01 bundle in a worker thread.
        選択された GUI01 バンドルの読み込みと解析をワーカースレッドで開始する。
        """
        sel = self.file_tree.selection()
        if not sel:
            return
        stem = sel[0]
        if self.is_running:
            self._log(_("読み込み中です。しばらくお待ちください。"))
            return

        self.is_running = True

        # Default the scale to the bundle's recorded scan size so fiber lengths
        # are reproduced from the bundle alone. Both axes are adopted: a
        # distinct Y size keeps a rectangular scan, an equal one leaves the Y
        # entry empty (square scan). The user can still override via the
        # entries; bundles without a recorded scan size keep the current value.
        # スケールをバンドル記録の走査範囲で既定化し、ファイバー長をバンドル単体で
        # 再現する。両軸を採用し、Y が異なれば矩形スキャン、等しければ Y 欄は空
        # （正方スキャン）とする。入力欄で上書きは可能で、走査範囲未記録の
        # バンドルは現在値を保持する。
        recorded = read_scan_size_from_bundle(stem + BUNDLE_EXT)
        if recorded is not None:
            rec_x, rec_y = recorded
            new_scale_y = rec_y if abs(rec_y - rec_x) > 1e-9 else None
            x_changed = abs(rec_x - self.scale_um) > 1e-9
            y_changed = (new_scale_y is None) != (self.scale_y_um is None) or (
                new_scale_y is not None and self.scale_y_um is not None
                and abs(new_scale_y - self.scale_y_um) > 1e-9
            )
            if x_changed or y_changed:
                self.scale_um = rec_x
                self.scale_um_var.set(self._fmt_num(self.scale_um))
                self.scale_y_um = new_scale_y
                self.scale_y_um_var.set(
                    "" if new_scale_y is None else self._fmt_num(new_scale_y)
                )
                # Refresh the "= X" ghost after mirroring the recorded Y size.
                # 記録された Y サイズを反映した後に "= X" ゴーストを更新する。
                self._refresh_scale_y_placeholder()
                if new_scale_y is None:
                    self._log(
                        (_("バンドル記録のスケール {scale} µm を使用します。")).format(
                            scale=self._fmt_num(self.scale_um)
                        )
                    )
                else:
                    self._log(
                        (_("バンドル記録のスケール {x}×{y} µm を使用します。")).format(
                            x=self._fmt_num(self.scale_um),
                            y=self._fmt_num(new_scale_y),
                        )
                    )

        # Use committed internal scale, not unconfirmed Entry text. While an
        # Entry is unconfirmed, the old committed value remains active.
        # スケールは入力欄の未確定文字列ではなく内部の確定済み値を参照し、
        # Enter で確定するまでは従来値を使う。
        scale_um = self.scale_um
        # measure_bundle takes micrometers. Derive the worker value from
        # _get_scale_nm() to keep its non-positive-input fallback semantics.
        # measure_bundle は µm 単位を受け取る。非正値入力時のフォールバック挙動を
        # 維持するため、ワーカーへ渡す値は _get_scale_nm() から導出する。
        worker_scale_um = self._get_scale_nm() / 1000.0
        # None lets measure_bundle reuse the X scale for Y (square scan).
        # None なら measure_bundle が Y に X スケールを流用する（正方スキャン）。
        worker_scale_y_um = self.scale_y_um

        # Capture the connection state now so the worker is not affected by later
        # UI toggles; ConnectParams is immutable, so sharing the reference is safe.
        # 後続の UI 操作の影響を受けないよう連結状態をここで確定する。ConnectParams
        # は不変なので参照共有で安全。
        connect_fibers = bool(self.connect_enabled_var.get())
        connect_params = self.connect_params

        self._log(
            (_("読み込み中: {name}  スケール={scale}") + " µm ...").format(
                name=os.path.basename(stem), scale=self._fmt_num(scale_um)
            )
        )
        if connect_fibers:
            self._log(_("ファイバー連結が有効です（断片を再結合します）。"))
        self._set_ui_enabled(False)
        self._show_progress(_("ファイル読み込み中..."), 0)

        def _worker(stem=stem, scale_um=worker_scale_um,
                    scale_y_um=worker_scale_y_um,
                    connect_fibers=connect_fibers,
                    connect_params=connect_params):
            """
            Load one bundle and run fiber analysis off the Tk main thread.
            Tk メインスレッド外で 1 つのバンドル読み込みとファイバー解析を実行する。

            Loading, tracing, and statistics are delegated to
            `lib.measure.measure_bundle`, the same code path as `cli.py
            measure`, so GUI and CLI results are identical.
            読み込み・追跡・統計は `cli.py measure` と同一経路の
            `lib.measure.measure_bundle` へ委譲し、GUI と CLI の結果を一致させる。
            """
            try:
                from lib import ml_connect_features as cf
                from lib import ml_connect_labels as cl
                from lib.blosc2_io import load_bundle as _load_bundle
                from lib.blosc2_io import load_bundle_meta

                # Fiber analysis always runs in a ThreadPoolExecutor inside
                # measure_bundle; the overhead is negligible for small sets.
                # ファイバー解析は measure_bundle 内で常に ThreadPoolExecutor に
                # より並列実行される。少数本でもオーバーヘッドはほぼ無い。
                self.ui_queue.put(("log", _("ファイバー解析を開始 (並列処理)...")))

                _last_pct_ref = [-1]
                def _progress(done: int, total: int) -> None:
                    """
                    Forward fiber-analysis progress to the UI queue.
                    ファイバー解析の進捗を UI キューへ転送する。
                    """
                    pct = int(done / total * 100) if total > 0 else 0
                    if pct != _last_pct_ref[0]:
                        _last_pct_ref[0] = pct
                        self.ui_queue.put(("progress", (done, total)))

                result = measure_bundle(
                    stem + BUNDLE_EXT,
                    scale_um=scale_um,
                    progress_cb=_progress,
                    scale_y_um=scale_y_um,
                    connect_fibers=connect_fibers,
                    connect_params=connect_params,
                )
                image, fibers = result.image, result.fibers

                # Precompute (median, max) pairs for table rebuilds.
                # テーブル再構築用に (中央値, 最大値) ペアを事前計算しておく。
                stats = [
                    (s.height_median_nm, s.height_max_nm) for s in result.stats
                ]

                # The skeleton hash binds a label file to this exact skeleton;
                # a connection's endpoints are read from the fiber objects on
                # demand, so no per-index endpoint map is carried here.
                # 骨格ハッシュはラベルファイルをこの骨格そのものへ結び付ける。連結の
                # 端点は必要時にファイバーオブジェクトから読むため、番号ごとの端点表は
                # ここでは持ち回らない。
                arrays = _load_bundle(stem + BUNDLE_EXT, keys=["skeletonized"])
                skeleton_hash = cl.skeleton_sha256(arrays["skeletonized"])
                meta = load_bundle_meta(stem + BUNDLE_EXT)

                # Restore any saved review, mapping each decision's endpoints
                # back to the fiber indices they belong to. A decision whose
                # endpoints are not ends of the current fibers is skipped.
                # 保存済み検分を復元する。各判断の端点を、それが属するファイバー番号へ
                # 対応づけ直す。現在のファイバーの端点でない判断は読み飛ばす。
                lookup = cf.endpoint_lookup(fibers)
                connections: List[Dict] = []
                label_path = cl.label_path_for(stem + BUNDLE_EXT)
                if os.path.exists(label_path):
                    labels = cl.load_labels(
                        label_path, expected_skeleton_hash=skeleton_hash)
                    for decision in labels["decisions"]:
                        pa, pb = cl.decision_key(decision)
                        end_a, end_b = lookup.get(pa), lookup.get(pb)
                        if end_a is None or end_b is None:
                            continue
                        connections.append({
                            "a": end_a.fragment_index,
                            "b": end_b.fragment_index,
                            "a_xy": pa, "b_xy": pb,
                            "verdict": decision["verdict"]})

                self.ui_queue.put(("file_loaded", (
                    stem, image, fibers, stats, skeleton_hash,
                    meta.get("input_sha256"), connections)))
            except Exception:
                self.ui_queue.put(("file_error", (stem, traceback.format_exc())))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_file_loaded(self, stem: str, image, fibers: List[Fiber],
                        stats: List[tuple], skeleton_hash: str,
                        input_sha256: Optional[str],
                        connections: List[Dict]) -> None:
        """
        Apply worker-thread load results to the UI on the main thread.
        ワーカースレッドから受け取った読み込み結果をメインスレッドで UI に反映する。
        """
        self.current_image   = image
        self.current_stem    = stem
        self.current_fibers  = fibers
        self._fiber_stats    = stats
        self._sel_idx        = None
        # Filter activation follows the checkbox and is applied later if enabled.
        # フィルターはチェックボックスの状態を参照する（チェックONなら後で適用）。
        self._filter_active  = False
        self._filtered_fibers = []
        self._overview_bg_drawn = False   # 背景キャッシュを無効化
        self._highlight_patch   = None

        # -- Manual-connection annotation state for this dataset --
        # ── このデータセットの手動連結アノテーション状態 ──
        self._skeleton_hash  = skeleton_hash
        self._input_sha256   = input_sha256
        self._connections    = connections
        self._pending_fiber  = None
        self._conn_sel_idx   = None
        self._labels_dirty   = False

        # -- Auto-update vmin/vmax only when auto mode is enabled --
        if self.auto_vrange_var.get() and image.calibrated_image is not None:
            self._apply_auto_vrange(image.calibrated_image, log=True)

        self._log(_("読み込み完了: {name}  ファイバー数: {count}").format(
            name=os.path.basename(stem), count=len(fibers)
        ))
        if connections:
            self._log(_("既存ラベルから連結 {n} 件を復元しました。").format(
                n=len(connections)))
        self._populate_fiber_table(fibers)
        self._populate_connection_table()
        # Dispatch by display mode so the fiber view survives a file switch.
        # 表示モードで分岐し、ファイル切替後も色分け表示を維持する。
        self._rebuild_overview_bg()

        # Auto-select the first fiber after file selection, unlike folder selection.
        # 先頭ファイバーを自動選択（ファイル選択時は内部選択を行う、フォルダ選択時とは別）。
        children = self.fiber_tree.get_children()
        if children:
            self.fiber_tree.selection_set(children[0])
            self.fiber_tree.focus(children[0])
            self._on_fiber_select()

        # If a new file is selected while the height filter is on, apply it automatically.
        # 高さフィルター ON のまま新ファイルに切り替わった場合、自動で適用する。
        if self.filter_enabled_var.get():
            self._apply_filter()
        self._update_connection_controls()

    def _set_ui_enabled(self, enabled: bool) -> None:
        """
        Enable or disable selection widgets during loading.
        読み込み中の誤操作を防ぐため、選択ウィジェットを有効化または無効化する。
        """
        self.file_tree.configure(selectmode="browse" if enabled else "none")
        self.fiber_tree.configure(selectmode="browse" if enabled else "none")

    # =========================================================================
    # Fiber table
    # =========================================================================

    def _populate_fiber_table(self, fibers: List[Fiber]) -> None:
        """
        Rebuild the fiber table and reuse cached statistics when available.
        ファイバー一覧テーブルを再構築し、可能なら統計値キャッシュを再利用する。
        """
        for iid in self.fiber_tree.get_children():
            self.fiber_tree.delete(iid)

        # Use direct index lookup when no filter is active and the cache is valid.
        # フィルターなし かつ キャッシュが有効な場合はインデックスで直接参照する。
        use_cache = (not self._filter_active) and len(self._fiber_stats) == len(fibers)
        if not use_cache:
            # Recompute through lib.measure so filtered rows use the same
            # statistic definitions as the worker and the CSV export.
            # フィルター後の行もワーカー・CSV 出力と同じ統計定義になるよう、
            # lib.measure 経由で再計算する。
            fresh = [
                (s.height_median_nm, s.height_max_nm)
                for s in compute_fiber_stats(fibers)
            ]

        for i, f in enumerate(fibers):
            med, mx = self._fiber_stats[i] if use_cache else fresh[i]
            self.fiber_tree.insert("", "end", iid=str(i), values=(
                i,
                f"{f.length:.0f}",
                f"{med:.2f}",
                f"{mx:.2f}",
                len(f.ep_indices),
                len(f.kink_indices),
            ))

    # =========================================================================
    # Fiber selection
    # =========================================================================

    def _on_fiber_select(self, _event=None) -> None:
        """
        Update overview highlighting and detail windows after fiber selection.
        ファイバー選択後に全体像のハイライトと個別表示を更新する。
        """
        sel = self.fiber_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._sel_idx = idx

        fiber = self._current_fiber()
        if fiber is None:
            return

        # The detail window owns automatic profile Y-limit updates.
        # プロファイルY上限の自動更新は個別表示側で行う（_update_detail_window 経由）。
        # Detail display always recomputes the profile y-limit for the selected fiber.
        # 個別表示では選択ファイバーごとにプロファイル y 上限を常に再計算する。

        self._draw_overview(selected_fiber=fiber)   # Replace only the highlight.

        # Keep the non-modal detail window synchronized if it is open.
        # 個別表示が開いていれば追従させる（非モーダル）。
        self._update_detail_window(fiber)

        # The connect buttons depend on which fiber is selected.
        # 連結ボタンの有効・無効は、どのファイバーが選択されているかに依存する。
        self._update_connection_controls()

    def _current_fiber(self) -> Optional[Fiber]:
        """
        Return the currently selected fiber, or ``None`` if no fiber is selected.
        現在選択中の Fiber を返し、未選択なら ``None`` を返す。
        """
        if self._sel_idx is None:
            return None
        fibers = self._filtered_fibers if self._filter_active else self.current_fibers
        if self._sel_idx >= len(fibers):
            return None
        return fibers[self._sel_idx]

    # =========================================================================
    # Drawing: AFM overview
    # =========================================================================

    def _draw_overview_background(
        self,
        labeled_fibers: Optional[List[tuple]] = None,
        title_suffix: str = "",
    ) -> None:
        """
        Draw and cache the AFM overview background.
        AFM 全体像の背景を描画してキャッシュする。

        Parameters
        ----------
        labeled_fibers
            Fiber/display-index pairs to draw. ``None`` uses all fibers with
            their original indices.
            描画するファイバーと表示番号のペア。``None`` の場合は全ファイバーを
            元の番号で表示する。
        title_suffix
            Extra title text, such as the filtered-fiber count.
            フィルター件数など、タイトルに付加する文字列。

        Notes
        -----
        This expensive background draw is reserved for dataset loads and
        vmin/vmax/scale changes; selection changes replace only the highlight.
        この高コストな背景描画は、データセット読み込み時や vmin/vmax/scale
        変更時に限定し、選択変更時はハイライトだけ差し替える。
        """
        if self.current_image is None:
            return
        # Use committed internal state so unconfirmed Entry text has no effect.
        # 内部状態を参照（Entry が未確定でも影響を受けない）。
        vmin = self.vmin
        vmax = self.vmax
        # Extent and unit labels follow unit_var; nanometers use scale_um * 1000 like GUI01.
        # extent に使うスケール値と軸単位ラベルは unit_var に従う（µm / nm 切替）。
        # As in GUI01, nanometer display uses scale_um * 1000.
        # GUI01 と同じく、nm 選択時は scale_um * 1000 を使う。
        x_scale, y_scale, unit_label = self._get_extent_scale_xy_and_unit()

        img = self.current_image.calibrated_image
        h_px, w_px = img.shape[:2]
        # Per-axis pixel size keeps the correct physical aspect for rectangular
        # scans and non-square pixel grids (X from width, Y from height).
        # 軸別ピクセルサイズで矩形スキャン・非正方格子の物理アスペクトを保つ
        # （X は幅、Y は高さ由来）。
        x_spp = x_scale / w_px
        y_spp = y_scale / h_px
        extent = [0, w_px * x_spp, h_px * y_spp, 0]

        ax = self._afm_ax
        ax.clear()
        # Remove the previous colorbar to avoid one being added on every redraw.
        # 既存カラーバーを削除（再描画のたびに増殖するのを防ぐ）。
        if self._afm_cbar is not None:
            try:
                self._afm_cbar.remove()
            except Exception:
                pass
            self._afm_cbar = None
        ax.axis("on")
        im = ax.imshow(img, cmap="afmhot", vmin=vmin, vmax=vmax, extent=extent, aspect="equal")

        # Decide which fibers to draw.
        if labeled_fibers is None:
            labeled_fibers = list(enumerate(self.current_fibers))

        for disp_i, f in labeled_fibers:
            # f.data is OpenCV stats (x, y, width, height, area); here `h` is the
            # width (X extent) and `w` is the height (Y extent).
            # f.data は OpenCV 統計 (x, y, 幅, 高さ, 面積)。ここで `h` は幅
            # （X 方向）、`w` は高さ（Y 方向）。
            x, y, h, w, _unused = f.data
            # Convert pixels to the physical scale used by extent (per axis).
            x_p = x * x_spp
            y_p = y * y_spp
            h_p = h * x_spp
            w_p = w * y_spp
            ax.add_patch(plt.Rectangle(
                (x_p, y_p), h_p, w_p,
                linewidth=1.0, linestyle="--", edgecolor="white", facecolor="none", alpha=0.6,
            ))
            ax.text(x_p + h_p / 2, y_p + w_p / 2, str(disp_i),
                    color="white", fontsize=7, ha="center", va="center", fontweight="bold")

        kp_x, kp_y = self.current_image.all_kink_coordinates
        if len(kp_x) > 0:
            ax.scatter(kp_x * x_spp, kp_y * y_spp,
                       c="cyan", s=4, alpha=0.7, linewidths=0)

        # Use the four committed font-size settings.
        fs_title = self.fs_title
        fs_label = self.fs_label
        fs_tick  = self.fs_tick
        fs_cbar  = self.fs_cbar

        ax.set_xlabel("({0})".format(unit_label), fontsize=fs_label)
        ax.set_ylabel("({0})".format(unit_label), fontsize=fs_label)
        ax.tick_params(labelsize=fs_tick)

        # Add a colorbar with the same height as the AFM image.
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.08)
        self._afm_cbar = self._afm_fig.colorbar(im, cax=cax)
        self._afm_cbar.ax.tick_params(labelsize=fs_cbar)
        self._afm_cbar.set_label("Height (nm)", fontsize=fs_cbar)

        base_title = f"{self.current_image.name}"
        ax.set_title(
            base_title + title_suffix,
            fontsize=fs_title, pad=3,
        )
        # Call tight_layout only for background redraws because it is expensive.
        # tight_layout は背景描画時のみ（描画コストが高いため）。
        self._afm_fig.tight_layout(pad=0.5)

        self._highlight_patch    = None
        self._overview_bg_drawn  = True
        # Do not call draw_idle here; callers own the final canvas draw.
        # draw_idle はここでは呼ばない。
        # The caller, such as _draw_overview or _on_file_loaded, is responsible for drawing.
        # 呼び出し元(_draw_overview / _on_file_loaded)が責任を持って描画する。

    def _rebuild_overview_bg(self) -> None:
        """
        Rebuild the AFM overview background with the current filter state.
        現在のフィルター状態に合わせて AFM 全体像の背景を再構築する。

        Without a filter, every fiber is shown with a dashed white box and its
        original index. With the height filter on, each surviving fiber keeps
        the same dashed white box and number (renumbered over the filtered
        list, matching the fiber table) and additionally has its extracted
        skeleton pixels scattered in magenta over the AFM image, matching the
        pixel-level ``specific_height_fibers`` extraction: a fiber contributes
        only the sub-segments whose calibrated height lies in the selected
        range.
        フィルターなしでは全ファイバーを破線白枠と元番号で表示する。高さ
        フィルター ON でも各残存ファイバーを同じ破線白枠と番号（フィルター後
        リストで振り直した、一覧テーブルと一致する番号）で表示し、さらに抽出
        されたスケルトン画素をマゼンタで AFM 像上に散布表示して、画素単位の
        ``specific_height_fibers`` 抽出（補正高さが範囲内の区間のみ残る）に
        一致させる。

        In color-coded fiber mode the height background is replaced entirely by
        `_draw_overview_fibers_bg`, which honors the same filter state.
        色分けモードでは高さ背景を `_draw_overview_fibers_bg` で丸ごと差し替える
        （同じフィルター状態を反映する）。
        """
        # Color-coded fiber mode owns its own background renderer.
        # 色分けモードは専用の背景描画に委譲する。
        if self.overview_mode_var.get() == OVERVIEW_MODE_FIBERS:
            self._draw_overview_fibers_bg()
            return

        if not self._filter_active:
            self._draw_overview_background()
            return

        # Filter-active path.
        filtered = self._filtered_fibers
        # Compute per-axis pixel size in the selected tick-display unit.
        # 軸表示単位に合わせて軸別ピクセルサイズを計算（µm / nm）。
        x_scale, y_scale, _unit_label = self._get_extent_scale_xy_and_unit()
        img = self.current_image.calibrated_image
        h_px, w_px = img.shape[:2]
        x_spp = x_scale / w_px
        y_spp = y_scale / h_px

        # Box and number each surviving fiber with the filtered-list index so
        # the overview labels match the fiber table, then overlay the magenta
        # skeleton scatter below.
        # 残存ファイバーをフィルター後リストの番号で枠付け・番号付けし、一覧
        # テーブルと一致させたうえで、下にマゼンタのスケルトン散布を重ねる。
        self._draw_overview_background(
            labeled_fibers=list(enumerate(filtered)),
            title_suffix="  [filter: {count} segments]".format(count=len(filtered)),
        )
        ax = self._afm_ax
        # Scatter the surviving skeleton pixels of each extracted segment. The
        # track arrays are bbox-local (xtrack = global_x - x), so add the bbox
        # origin before scaling to the physical tick-display unit.
        # 抽出された各区間の残存スケルトン画素を散布表示する。track 配列は BBox
        # ローカル座標（xtrack = グローバルx - x）なので、物理表示単位へスケール
        # する前に BBox 原点を加える。
        for f in filtered:
            x, y, _h, _w, _unused = f.data
            ax.scatter(
                (f.xtrack + x) * x_spp,
                (f.ytrack + y) * y_spp,
                c="magenta", s=4, edgecolors="none",
            )

    def _binarized_backdrop(self) -> Optional[np.ndarray]:
        """
        Return the binarized fiber mask for the current dataset, or ``None``.
        現在データセットの二値化ファイバーマスクを返す。取得できなければ ``None``。

        ``binarized`` is a required ``.b2z`` key but `measure_bundle` does not
        load it, so it is read lazily on first use and cached on the tracking
        image to avoid re-reading the bundle on every color-mode redraw.
        ``binarized`` は ``.b2z`` の必須キーだが `measure_bundle` は読み込まない
        ため、初回に遅延読み込みして tracking 画像へキャッシュし、色分けモードの
        再描画ごとにバンドルを読み直さないようにする。
        """
        image = self.current_image
        if image is None:
            return None
        if image.binarized_image is not None:
            return image.binarized_image
        if not self.current_stem:
            return None
        try:
            arrays = load_bundle(self.current_stem + BUNDLE_EXT, keys=["binarized"])
            image.binarized_image = arrays["binarized"]
        except Exception:
            # Leave it unset so the caller falls back to the grayscale height image.
            # 未設定のままにし、呼び出し側でグレースケール高さ画像にフォールバックする。
            image.binarized_image = None
        return image.binarized_image

    def _draw_overview_fibers_bg(self) -> None:
        """
        Draw and cache the color-coded fiber overview background.
        色分けファイバー表示の背景を描画してキャッシュする。

        Each fiber (the filtered subset when the height filter is active,
        otherwise every fiber) is scattered in its own color over the binarized
        fiber silhouette, so which skeleton pixels belong to one fibril is
        visible at a glance. This is the primary way to verify the
        fiber-connection result, which the single-color height overview cannot
        show. vmin/vmax do not apply because the background is binary, so no
        height colorbar is drawn.
        各ファイバー（高さフィルター有効時は残存分、無効時は全ファイバー）を
        二値化シルエット上に個別色で散布し、どの骨格画素が 1 本のフィブリルに
        属するかを一目で確認できるようにする。単色の高さ表示では見えない
        ファイバー連結の結果を検証する主手段。背景が二値のため vmin/vmax は
        効かず、高さカラーバーも描かない。
        """
        if self.current_image is None:
            return
        # Extent and units follow unit_var, matching the height overview.
        # extent と単位は unit_var に従い、高さ表示と揃える。
        x_scale, y_scale, unit_label = self._get_extent_scale_xy_and_unit()
        img = self.current_image.calibrated_image
        h_px, w_px = img.shape[:2]
        x_spp = x_scale / w_px
        y_spp = y_scale / h_px
        extent = [0, w_px * x_spp, h_px * y_spp, 0]

        ax = self._afm_ax
        ax.clear()
        # A binary background carries no height scale, so drop the colorbar left
        # over from height mode instead of stacking a new one each redraw.
        # 二値背景に高さスケールは無いため、高さモードのカラーバーを削除する
        # （再描画ごとに増殖させない）。
        if self._afm_cbar is not None:
            try:
                self._afm_cbar.remove()
            except Exception:
                pass
            self._afm_cbar = None
        ax.axis("on")

        # Prefer the binarized silhouette as a clean, high-contrast backdrop;
        # fall back to the grayscale height image if it cannot be read.
        # 高コントラストな背景として二値化シルエットを優先し、読み込めない場合は
        # グレースケールの高さ画像にフォールバックする。
        backdrop = self._binarized_backdrop()
        if backdrop is None:
            backdrop = img
        ax.imshow(backdrop, cmap="gray", extent=extent, aspect="equal")

        # Color each fiber the same way in both filtered and unfiltered states.
        # フィルター有無にかかわらず同じ方式で各ファイバーを配色する。
        fibers = self._filtered_fibers if self._filter_active else self.current_fibers
        n = len(fibers)
        if n > 0:
            # Deterministic shuffle: neighboring fibers get distinct colors while
            # the same dataset always colors identically across redraws (unlike
            # the reference notebook, which re-randomizes every run).
            # 決定論的シャッフル：近接ファイバーに異なる色を与えつつ、同一データ
            # セットでは再描画ごとに同じ配色になる（毎回ランダム化する参照
            # ノートブックとは異なる）。
            order = np.random.default_rng(0).permutation(n)
            cmap = plt.get_cmap("rainbow")
            denom = max(n - 1, 1)
            for color_idx, f in zip(order, fibers):
                # f.data is OpenCV stats (x, y, width, height, area); tracks are
                # bbox-local, so add the bbox origin before scaling.
                # f.data は OpenCV 統計 (x, y, 幅, 高さ, 面積)。track は BBox
                # ローカルなので、スケールする前に BBox 原点を加える。
                x, y, _h, _w, _unused = f.data
                ax.scatter(
                    (f.xtrack + x) * x_spp,
                    (f.ytrack + y) * y_spp,
                    color=cmap(color_idx / denom),
                    s=4, alpha=0.7, edgecolors="none",
                )

        # Reuse the committed font sizes; the colorbar size is unused here.
        # 確定済みフォントサイズを流用する（ここではカラーバー用は未使用）。
        ax.set_xlabel("({0})".format(unit_label), fontsize=self.fs_label)
        ax.set_ylabel("({0})".format(unit_label), fontsize=self.fs_label)
        ax.tick_params(labelsize=self.fs_tick)

        suffix = (
            "  [filter: {count} segments]".format(count=n)
            if self._filter_active
            else "  [fibers: {count}]".format(count=n)
        )
        ax.set_title(self.current_image.name + suffix, fontsize=self.fs_title, pad=3)
        self._afm_fig.tight_layout(pad=0.5)

        self._highlight_patch   = None
        self._overview_bg_drawn = True
        # Do not call draw_idle here; the caller owns the final canvas draw.
        # draw_idle はここでは呼ばない。呼び出し元が最終描画を行う。

    def _draw_overview(self, selected_fiber: Optional[Fiber] = None) -> None:
        """
        Replace only the overview highlight patch.
        全体像のハイライトパッチだけを差し替える。

        The cached background is reused. If it is invalid, it is rebuilt first.
        背景は再描画せずキャッシュを使う。背景未描画の場合は先に再構築する。
        """
        if self.current_image is None:
            return

        # Rebuild invalid backgrounds after vmin/vmax changes or explicit redraws.
        # 背景が無効なら再構築（vmin/vmax変更後の再描画ボタン経由など）。
        if not self._overview_bg_drawn:
            self._rebuild_overview_bg()

        # Remove the previous highlight patch.
        if self._highlight_patch is not None:
            try:
                self._highlight_patch.remove()
            except ValueError:
                pass
            self._highlight_patch = None

        # Add the new highlight patch.
        if selected_fiber is not None:
            x, y, h, w, _unused = selected_fiber.data
            # Convert pixels to the selected physical tick-display unit (per
            # axis). `h` is the width (X extent), `w` the height (Y extent).
            # 軸表示単位に合わせて px → 物理スケールへ軸別変換する。`h` は幅
            # （X 方向）、`w` は高さ（Y 方向）。
            x_scale, y_scale, _unit_label = self._get_extent_scale_xy_and_unit()
            img = self.current_image.calibrated_image
            h_px, w_px = img.shape[:2]
            x_spp = x_scale / w_px
            y_spp = y_scale / h_px
            patch = plt.Rectangle(
                (x * x_spp, y * y_spp), h * x_spp, w * y_spp,
                linewidth=2.0, linestyle="-", edgecolor="yellow", facecolor="none",
            )
            self._afm_ax.add_patch(patch)
            self._highlight_patch = patch

        # Draw the manual connections on top of the highlight so both are
        # refreshed together on every selection change.
        # 手動連結をハイライトの上に描き、選択が変わるたびに両者をまとめて更新する。
        self._draw_connections()

        self._afm_canvas.draw_idle()   # Do not call tight_layout().

    # =========================================================================
    # Drawing: fiber enlarged image
    # =========================================================================

    # =========================================================================
    # Drawing: fiber enlarged image / height profile
    # Detail image/profile actions are owned by FiberDetailWindow.
    # これらは FiberDetailWindow（別ウインドウ）に移管された。
    # The main window requests detail redraws through _update_detail_window().
    # メインウィンドウからは _update_detail_window() を経由して再描画依頼する。
    # =========================================================================

    @staticmethod
    def _format_progress_bar(done: int, total: int, width: int = 24) -> str:
        """
        Render a smooth text progress bar for the log.
        ログ用に滑らかなテキスト進捗バーを生成する。

        Eighth-block characters give the bar 8x the resolution of a whole-cell
        bar, so each ~1% worker update visibly advances it instead of standing
        still for several updates and then jumping a full cell.
        1/8 ブロック文字でセル単位バーの 8 倍の解像度を持たせる。これにより
        ワーカーからの約 1% ごとの更新でバーが必ず少し進み、数回分まったく
        動かずに突然 1 セル飛ぶ「飛び飛び」表示を防ぐ。
        """
        frac = (done / total) if total > 0 else 0.0
        frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
        # Quantize to eighth-cell steps (width * 8 sub-steps total).
        eighths = int(round(frac * width * 8))
        full, rem = divmod(eighths, 8)
        partials = " ▏▎▍▌▋▊▉"   # index 0 = none, 1..7 = left eighth blocks
        bar = "█" * full
        if full < width:
            if rem:
                bar += partials[rem] + "░" * (width - full - 1)
            else:
                bar += "░" * (width - full)
        pct = int(round(frac * 100))
        return f"  [{bar}] {done}/{total} ({pct}%)"

    def _show_progress(self, label: str = "", value: int = 0) -> None:
        """
        Begin a progress run shown as a single, in-place log line.
        進捗の表示を開始する（ログ内の 1 行を上書き更新する方式）。

        Progress is rendered in the log rather than a separate widget, so this
        only arms the next update to append a fresh bar line; subsequent
        updates overwrite that line.
        進捗は専用ウィジェットではなくログに描画するため、ここでは次の更新で
        バー行を新規追加するよう状態を整えるだけ。以降の更新は同じ行を上書きする。
        """
        self._progress_started = False

    def _hide_progress(self) -> None:
        """
        End the current progress run.
        進捗の表示を終了する。

        Resets the in-place update state so the next run starts on a new line.
        上書き更新の状態をリセットし、次回の進捗が新しい行から始まるようにする。
        """
        self._progress_started = False

    # =========================================================================
    # Height filter
    # =========================================================================

    def _on_filter_toggle(self) -> None:
        """
        Handle height-filter checkbox changes.
        高さフィルターのチェックボックス変更を処理する。

        On applies the committed filter range; off resets the filter.
        ON では確定済み範囲を適用し、OFF ではフィルターを解除する。
        """
        if self.current_image is None:
            # Keep only the checkbox state until a dataset is selected.
            # データ未選択ならチェック状態だけ保持する（後で適用される）。
            return
        if self.filter_enabled_var.get():
            self._apply_filter()
        else:
            self._reset_filter()

    def _apply_filter(self) -> None:
        """
        Apply the committed height-filter range in a worker thread.
        確定済みの高さフィルター範囲をワーカースレッドで適用する。
        """
        if self.current_image is None:
            return
        # Use committed filter_min/filter_max values.
        # 内部状態（確定済みの filter_min/max）を使う。
        lo = self.filter_min
        hi = self.filter_max
        if lo >= hi:
            # Invalid committed state should be rare because commit already validates it.
            # 内部状態が不正なら適用しない（commit時にチェック済みなので通常起きない）。
            return

        self._set_ui_enabled(False)
        self._show_progress(_("フィルター適用中..."), 0)
        self._log(
            (_("フィルター適用中: 高さ {lo}〜{hi}") + " nm").format(lo=lo, hi=hi)
        )

        image = self.current_image
        # Compose with fiber connection: when connection is active, filter the
        # connected fibrils (current_fibers) rather than the raw skeleton, so the
        # "connect, then filter" order is preserved and the connector cannot
        # bridge across regions the filter removes.
        # ファイバー連結との合成：連結が有効なときは生スケルトンではなく連結済み
        # フィブリル（current_fibers）をフィルターする。これにより「連結してから
        # フィルター」の順序が保たれ、連結器がフィルターで除去した領域を橋渡しで
        # 埋め戻すことはない。
        connect_fibers = bool(self.connect_enabled_var.get())
        connected_fibers = self.current_fibers

        def _worker():
            """
            Extract specific-height fiber segments off the Tk main thread.
            Tk メインスレッド外で特定高さのファイバー区間を抽出する。
            """
            try:
                _last_pct_ref = [-1]
                def _progress(done: int, total: int) -> None:
                    """
                    Forward height-filter rebuild progress to the UI queue.
                    高さフィルター再構築の進捗を UI キューへ転送する。
                    """
                    pct = int(done / total * 100) if total > 0 else 0
                    if pct != _last_pct_ref[0]:
                        _last_pct_ref[0] = pct
                        self.ui_queue.put(("progress", (done, total)))

                if connect_fibers:
                    # Connect-then-filter: test each connected fibril against its
                    # own height profile (including interpolated bridge heights)
                    # and slice out the in-band runs, so an in-band bridge keeps
                    # the fibril joined instead of re-splitting it.
                    # 連結してからフィルター：連結済みフィブリルを自身の高さ
                    # プロファイル（橋渡し補間値を含む）で判定し帯域内区間を
                    # 切り出す。帯域内の橋渡しはフィブリルを連結したまま保つ。
                    result = filter_fibers_by_height(
                        image, connected_fibers, lo, hi, progress_cb=_progress,
                    )
                else:
                    # Pixel-level extraction on the raw skeleton: keep only
                    # skeleton pixels whose calibrated height is within [lo, hi]
                    # and rebuild fibers from them. Delegates to
                    # FiberTrackingImage.specific_height_fibers so the GUI matches
                    # the reference height-filter behavior, which isolates the
                    # portions at a target height (e.g. dents) rather than
                    # selecting whole fibers by a summary statistic.
                    # 生スケルトン上の画素単位抽出。補正高さが [lo, hi] の
                    # スケルトン画素のみを残して再構築する。specific_height_fibers
                    # に委譲し、要約統計でファイバーを丸ごと選ぶのではなく特定
                    # 高さの箇所（凹みなど）を切り出す、本来の高さフィルター仕様に
                    # 一致させる。
                    result = image.specific_height_fibers(lo, hi, progress_cb=_progress)
                self.ui_queue.put(("filter_done", (result, lo, hi)))
            except Exception:
                self.ui_queue.put(("filter_error", traceback.format_exc()))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_filter_done(self, filtered, lo, hi) -> None:
        """
        Apply completed filter results to the UI.
        完了したフィルター結果を UI に反映する。
        """
        self._filter_active   = True
        self._filtered_fibers = filtered
        self._populate_fiber_table(filtered)

        # Rebuild the overview so the extracted skeleton pixels are scattered
        # over the AFM image. The drawing itself lives in _rebuild_overview_bg
        # so the filtered overview is defined in one place.
        # 抽出スケルトン画素を AFM 像上に散布表示するため全体像を再構築する。
        # 描画本体は _rebuild_overview_bg に一本化している。
        self._overview_bg_drawn = False
        self._rebuild_overview_bg()
        self._afm_canvas.draw_idle()

        self._log(
            (_("フィルター適用完了: 高さ {lo}〜{hi}") + " nm → "
             + _("{count} 件")).format(lo=lo, hi=hi, count=len(filtered))
        )

    def _reset_filter(self) -> None:
        """
        Clear the height filter and restore the full fiber table.
        高さフィルターを解除し、全ファイバーの一覧に戻す。
        """
        self._filter_active   = False
        self._filtered_fibers = []
        if self.current_image is not None:
            self._populate_fiber_table(self.current_fibers)
            self._overview_bg_drawn = False
            self._rebuild_overview_bg()
            self._afm_canvas.draw_idle()
        self._log(_("フィルターをリセットしました。"))

    # =========================================================================
    # Fiber connection (whole-fibril)
    # =========================================================================

    def _on_connect_toggle(self) -> None:
        """
        Handle the fiber-connection checkbox by re-analyzing the dataset.
        ファイバー連結チェックボックスの切替でデータセットを再解析する。

        Connection changes how fibers are built from the skeleton, so the only
        way to reflect it is to re-run the analysis. When no dataset is loaded,
        the checkbox state is kept and applied on the next selection.
        連結はスケルトンからのファイバー構築方法を変えるため、反映には解析の
        再実行が必要。データ未読込ならチェック状態のみ保持し、次の選択で適用する。
        """
        state = _("有効") if self.connect_enabled_var.get() else _("無効")
        self._log(_("ファイバー連結: {state}").format(state=state))
        if self.current_stem and self.current_image is not None and not self.is_running:
            self._reload_current_file()

    def _open_connect_settings(self) -> None:
        """
        Open the non-modal connection-settings window, reusing one instance.
        非モーダルの連結設定ウインドウを開く（インスタンスは 1 つを再利用）。
        """
        if self._connect_window is not None and self._connect_window.winfo_exists():
            try:
                self._connect_window.deiconify()
                self._connect_window.lift()
                self._connect_window.focus_set()
            except Exception:
                # Recreate the window if the stored reference is stale.
                # 参照が壊れていれば作り直す。
                self._connect_window = None
                self._open_connect_settings()
            return
        self._connect_window = ConnectSettingsWindow(self)

    def _apply_connect_params(self, params: ConnectParams) -> None:
        """
        Store new connection parameters and re-analyze if connection is active.
        新しい連結パラメータを保存し、連結が有効なら再解析する。
        """
        self.connect_params = params
        self._log(_("連結パラメータを更新しました。"))
        if self.connect_enabled_var.get() and self.current_stem \
                and self.current_image is not None and not self.is_running:
            self._reload_current_file()

    def _on_connect_window_closed(self) -> None:
        """
        Clear the stored connection-settings window reference after close.
        連結設定ウインドウのクローズ後に参照をクリアする。
        """
        self._connect_window = None

    # =========================================================================
    # Automatic vrange toggle
    # =========================================================================

    def _on_auto_vrange_toggle(self) -> None:
        """
        Handle the vmin/vmax auto checkbox.
        vmin/vmax の自動チェックボックスを処理する。

        Switching on recomputes vmin/vmax from the current image; switching off
        keeps the current values.
        ON へ切り替えた瞬間に現在画像から再計算し、OFF では現在値を維持する。
        """
        if not self.auto_vrange_var.get():
            return
        if self.current_image is None or self.current_image.calibrated_image is None:
            return
        self._apply_auto_vrange(self.current_image.calibrated_image, log=True)
        # Update the drawings as well.
        self._overview_bg_drawn = False
        fiber = self._current_fiber()
        if fiber is not None:
            self._draw_overview(selected_fiber=fiber)
            self._update_detail_window(fiber)
        elif self.current_image is not None:
            # Dispatch by display mode so a mode-mismatched background is not drawn.
            # 表示モードで分岐し、モード不一致の背景を描かないようにする。
            self._rebuild_overview_bg()
            self._afm_canvas.draw_idle()

    def _on_overview_mode_change(self) -> None:
        """
        Redraw the overview in place after switching display mode.
        表示モード切替後に全体像を同じ場所で再描画する。

        Height and fiber modes are two renderings of the same overview, so only
        the cached background is invalidated and rebuilt; the current selection,
        height filter, vmin/vmax, and font sizes are preserved.
        高さ／色分けは同一全体像の描き分けなので、背景キャッシュだけを無効化して
        再構築し、選択・高さフィルター・vmin/vmax・フォントサイズは保持する。
        """
        if self.current_image is None:
            return
        self._overview_bg_drawn = False
        fiber = self._current_fiber()
        if fiber is not None:
            # _draw_overview rebuilds the invalidated background (mode-aware via
            # _rebuild_overview_bg) and re-adds the selection highlight.
            # _draw_overview は無効化した背景を（_rebuild_overview_bg 経由で
            # モード対応で）再構築し、選択ハイライトを付け直す。
            self._draw_overview(selected_fiber=fiber)
        else:
            self._rebuild_overview_bg()
            self._afm_canvas.draw_idle()

    def _redraw_profile(self) -> None:
        """
        Redraw only the detail-window profile after display-option changes.
        表示オプション変更後、個別表示のプロファイルだけを再描画する。
        """
        if self._detail_window_alive():
            self._detail_window.redraw_profile_only()

    # =========================================================================
    # Detail-window management
    # =========================================================================

    def _detail_window_alive(self) -> bool:
        """
        Return whether the detail window exists and is alive.
        個別表示ウインドウが存在し、生きているかを返す。
        """
        return self._detail_window is not None and self._detail_window.winfo_exists()

    def _open_detail_window(self) -> None:
        """
        Open the non-modal detail window for the selected fiber.
        選択ファイバー用の非モーダル個別表示ウインドウを開く。
        """
        fiber = self._current_fiber()
        if fiber is None:
            messagebox.showinfo(_("情報"), _("ファイバーを選択してください。"))
            return

        if self._detail_window_alive():
            # Bring the existing window forward and update it to the current fiber.
            # 既に開いていれば前面に出して内容を最新に更新する。
            try:
                self._detail_window.update_fiber(fiber)
                self._detail_window.deiconify()
                self._detail_window.lift()
                self._detail_window.focus_set()
            except Exception:
                # Recreate the window if the stored reference is stale.
                # ウインドウ参照が壊れていれば作り直す。
                self._detail_window = None
                self._open_detail_window()
            return

        self._detail_window = FiberDetailWindow(self, fiber)

    def _update_detail_window(self, fiber: Fiber) -> None:
        """
        Update an open detail window without opening a new one.
        個別表示が開いている場合だけ更新し、新規には開かない。
        """
        if self._detail_window_alive():
            try:
                self._detail_window.update_fiber(fiber)
            except Exception:
                self._detail_window = None

    def _on_detail_window_closed(self) -> None:
        """
        Clear the stored detail-window reference after close notification.
        クローズ通知を受けた後、個別表示ウインドウ参照をクリアする。
        """
        self._detail_window = None

    # =========================================================================
    # Export
    # =========================================================================

    def _export_overview(self) -> None:
        """
        Export the current AFM overview figure through a save dialog.
        現在の AFM 全体像 Figure を保存ダイアログ経由で出力する。
        """
        name = self.current_image.name if self.current_image else "overview"
        save_figure_with_dialog(
            self, self._afm_fig,
            initial_name=f"{name}_overview.png",
            initial_dir=self._default_save_dir(),
            title=_("画像を保存"),
            log_cb=self._log,
        )

    def _export_csv(self) -> None:
        """
        Export fiber statistics for the current table to CSV.
        現在テーブルのファイバー統計値を CSV に出力する。
        """
        if self.current_image is None:
            messagebox.showinfo(_("情報"), _("データセットを選択してください。"))
            return

        fibers = self._filtered_fibers if self._filter_active else self.current_fibers
        if not fibers:
            messagebox.showinfo(_("情報"), _("エクスポートするファイバーがありません。"))
            return

        name = self.current_image.name
        def _write_csv(path):
            # Columns and formatting are owned by lib.measure. A complete,
            # unfiltered export is byte-identical to `cli.py measure`; an
            # active height filter intentionally writes only retained portions.
            # 列と書式は lib.measure が管理する。全件・フィルターなしなら
            # `cli.py measure` とバイト単位で一致し、高さフィルター有効時は
            # 意図どおり残った部分だけを書き出す。
            write_fiber_csv(path, compute_fiber_stats(fibers))

        save_csv_with_dialog(
            self,
            _write_csv,
            initial_dir=self._default_save_dir(),
            initial_name=f"{name}_fibers.csv",
            title=_("CSVで保存"),
            log_cb=lambda msg: self._log(
                _("{msg} ({count} 件)").format(msg=msg, count=len(fibers))
            ),
        )

    # =========================================================================
    # Queue polling for worker messages and future async extensions
    # =========================================================================

    def _poll_ui_queue(self) -> None:
        """
        Poll worker-thread messages and apply them on the Tk main thread.
        ワーカースレッドからのメッセージを Tk メインスレッドで処理する。
        """
        def _on_progress(payload):
            done, total = payload
            bar_line = self._format_progress_bar(done, total)
            # First update of a run appends a new line; later ones overwrite it
            # so the bar advances in place instead of flooding the log.
            # 実行の最初の更新で行を追加し、以降は同じ行を上書きしてバーをその場で
            # 進める（ログが大量の行で埋まらないようにする）。
            if not self._progress_started:
                self._log(bar_line)
                self._progress_started = True
            else:
                replace_log_tail(self.log_text, bar_line)

        def _on_file_loaded(payload):
            (stem, image, fibers, stats, skeleton_hash, input_sha256,
             connections) = payload
            self.is_running = False
            self._hide_progress()
            self._set_ui_enabled(True)
            self._on_file_loaded(stem, image, fibers, stats, skeleton_hash,
                                 input_sha256, connections)

        def _on_file_error(payload):
            stem, tb = payload
            self.is_running = False
            self._hide_progress()
            self._set_ui_enabled(True)
            self._log(_("読み込みエラー: {name}\n{tb}").format(
                name=os.path.basename(stem), tb=tb
            ))

        def _on_filter_done(payload):
            filtered, lo, hi = payload
            self._hide_progress()
            self._set_ui_enabled(True)
            self._on_filter_done(filtered, lo, hi)

        def _on_filter_error(payload):
            tb = payload
            self._hide_progress()
            self._set_ui_enabled(True)
            self._log(_("フィルターエラー:\n{tb}").format(tb=tb))

        drain_ui_queue(self.ui_queue, {
            "log": lambda payload: self._log(str(payload)),
            "progress": _on_progress,
            "file_loaded": _on_file_loaded,
            "file_error": _on_file_error,
            "filter_done": _on_filter_done,
            "filter_error": _on_filter_error,
        })
        self.after(50, self._poll_ui_queue)


# ===== Detail view: enlarged fiber image and height profile =====

class FiberDetailWindow(tk.Toplevel, UnconfirmedEntryMixin):
    """
    Non-modal detail window for the selected fiber.
    選択中ファイバーを表示する非モーダル個別表示ウインドウ。

    Attributes
    ----------
    _app
        Main application window that owns the dataset and shared plot settings.
        データセットと共有描画設定を保持するメインアプリケーションウインドウ。
    _fiber
        Currently displayed fiber.
        現在表示しているファイバー。

    Notes
    -----
    The left panel shows the enlarged AFM fiber image and inherits
    ``vmin``, ``vmax``, ``scale_um``, and ``unit_var`` from the main window to
    avoid duplicated settings. The right panel shows the height profile with
    local controls for figure size, fonts, tick direction, grid, and displayed
    elements. The profile Y-axis limit is recalculated whenever the displayed
    fiber changes.
    左側には拡大 AFM 像を表示し、設定の重複による同期問題を避けるため
    ``vmin``、``vmax``、``scale_um``、``unit_var`` はメインウインドウから継承する。
    右側には高さプロファイルを表示し、Figure サイズ、フォント、目盛り向き、
    グリッド、表示要素を本ウインドウ内で調整できる。プロファイルの Y 軸上限は
    表示ファイバーが変わるたびに自動再計算する。
    """

    def __init__(self, parent: "App", fiber: "Fiber") -> None:
        """
        Initialize the non-modal detail window for one fiber.
        1 本のファイバーを表示する非モーダル個別表示ウインドウを初期化する。
        """
        super().__init__(parent)
        self._app: "App" = parent
        self._fiber: "Fiber" = fiber
        self._update_title()


        apply_window_size(self, 1300, 700, min_w=700, min_h=600)

        # -- ttk theme: keep the same clam theme as the main window --
        # Style is application-wide; the main window already applies it, but this is explicit.
        # Style はアプリケーション全体で共有されるため、メイン側で既に "clam" が
        # already applied, but this window repeats it for clarity.
        # 適用済みだが、念のためここでも明示しておく。
        setup_ttk_theme(self)

        # -- Committed internal state for Enter-to-commit entries --
        # Sizes assume a side-by-side layout: enlarged image on the left, profile on the right.
        # サイズは横並び（左：拡大像 / 右：プロファイル）を前提に決定。
        self._fiber_w:    int   = 520
        self._fiber_h:    int   = 600
        self._prof_w:     int   = 520
        self._prof_h:     int   = 600

        # Use shared ui_tools font defaults.
        # フォントサイズは ui_tools の共通定数（PLOT_FS_DEFAULTS）に揃える。
        # The enlarged image splits label, tick, and colorbar font sizes.
        # 拡大像は軸ラベル/軸目盛/カラーバーの3分割。
        # Colorbar ticks and label share one value, following GUI01 / GUI02.
        # カラーバーは目盛とラベルを一つの値で制御する GUI01 / GUI02 流儀。
        self._fiber_label_fs: float = float(PLOT_FS_DEFAULTS["label_fs"])   # 14
        self._fiber_tick_fs:  float = float(PLOT_FS_DEFAULTS["tick_fs"])    # 13
        self._fiber_cbar_fs:  float = float(PLOT_FS_DEFAULTS["cbar_fs"])    # 13

        # Profile font sizes are split into labels, ticks, and legend.
        # プロファイルも軸ラベル/軸目盛/凡例の3分割。
        self._label_fs:   float = float(PLOT_FS_DEFAULTS["label_fs"])       # 14
        self._tick_fs:    float = float(PLOT_FS_DEFAULTS["tick_fs"])        # 13
        self._legend_fs:  float = float(PLOT_FS_DEFAULTS["legend_fs"])      # 12

        # Profile Y-axis upper limit is local to this window and computed from the selected fiber.
        # プロファイル y軸最大値（nm）は本ウインドウ内で完結。
        # The initial value is computed automatically from the current fiber.
        # 初期値は現在選択中のファイバーから自動算出する。
        self._ylim: float = float(DEFAULT_HEIGHT_YLIM)
        if self._fiber is not None:
            try:
                self._ylim = float(self._app._compute_auto_ylim(self._fiber))
            except Exception:
                self._ylim = float(DEFAULT_HEIGHT_YLIM)

        # -- tk variables for profile settings --
        self._prof_w_var      = tk.StringVar(value=self._app._fmt_num(self._prof_w))
        self._prof_h_var      = tk.StringVar(value=self._app._fmt_num(self._prof_h))
        self._label_fs_var    = tk.StringVar(value=self._app._fmt_num(self._label_fs))
        self._tick_fs_var     = tk.StringVar(value=self._app._fmt_num(self._tick_fs))
        self._legend_fs_var   = tk.StringVar(value=self._app._fmt_num(self._legend_fs))
        self._ylim_var        = tk.StringVar(value=self._app._fmt_num(self._ylim))
        self._tick_dir_var    = tk.StringVar(value="")
        self._grid_var        = tk.StringVar(value="")
        self._legend_loc_var  = tk.StringVar(value="")

        # -- tk variables for enlarged-image settings --
        self._fiber_w_var         = tk.StringVar(value=self._app._fmt_num(self._fiber_w))
        self._fiber_h_var         = tk.StringVar(value=self._app._fmt_num(self._fiber_h))
        self._fiber_label_fs_var  = tk.StringVar(value=self._app._fmt_num(self._fiber_label_fs))
        self._fiber_tick_fs_var   = tk.StringVar(value=self._app._fmt_num(self._fiber_tick_fs))
        self._fiber_cbar_fs_var   = tk.StringVar(value=self._app._fmt_num(self._fiber_cbar_fs))

        self._tick_dir_choices = [
            ("out", _("外向き")),
            ("in", _("内向き")),
            ("inout", _("両方")),
        ]
        self._grid_choices = [
            ("x", _("x軸")),
            ("y", _("y軸")),
            ("both", _("両方")),
            ("none", _("無し")),
        ]
        self._tick_dir_label_to_key = {label: key for key, label in self._tick_dir_choices}
        self._grid_label_to_key = {label: key for key, label in self._grid_choices}
        self._tick_dir_var.set(self._tick_dir_choices[0][1])  # default: 外向き
        self._grid_var.set(self._grid_choices[-1][1])         # default: 無し

        # -- Legend location choices --
        # Use nine matplotlib loc strings, best, outside-right, and off.
        # matplotlib の loc 文字列 9種 + best + 軸外右 + 非表示(OFF)。
        # The internal "axes_right" key maps to an outside-axes placement.
        # 内部キーのうち "axes_right" は loc="upper left",
        # and bbox_to_anchor=(1.02, 1), placing the legend outside the axes.
        # bbox_to_anchor=(1.02, 1) として軸の外に出す特別扱い。
        # "off" suppresses legend drawing entirely.
        # "off" は凡例自体を描画しない。
        self._legend_loc_choices = [
            ("best",         _("自動(best)")),
            ("upper right",  _("右上")),
            ("upper left",   _("左上")),
            ("lower right",  _("右下")),
            ("lower left",   _("左下")),
            ("upper center", _("上中央")),
            ("lower center", _("下中央")),
            ("center left",  _("左中央")),
            ("center right", _("右中央")),
            ("center",       _("中央")),
            ("axes_right",   _("軸外(右)")),
            ("off",          _("非表示")),
        ]
        self._legend_loc_label_to_key = {label: key for key, label in self._legend_loc_choices}
        # Default legend placement is the upper-right corner of the axes.
        # 凡例の既定位置は軸内の右上。
        self._legend_loc_var.set(self._legend_loc_choices[1][1])

        # -- Unconfirmed-entry registry local to the detail window --
        self._init_unconfirmed_registry()

        # -- Build UI --
        self._build_canvases_and_controls()

        # Initial draw.
        self._redraw_fiber_image()
        self._redraw_profile()

        # Do not call grab_set() so this window stays non-modal.
        # 非モーダルにするため grab_set() は呼ばない。
        # Do not call transient(); otherwise minimized windows may disappear from the taskbar.
        # transient() も呼ばない（最小化時にタスクバーから消えないようにするため）。
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.lift()
        self.focus_set()

    # -- Public methods --------------------------------------------------------

    def update_fiber(self, fiber: "Fiber") -> None:
        """
        Update this window to display a newly selected fiber.
        新しく選択されたファイバーを表示するように本ウインドウを更新する。
        """
        self._fiber = fiber
        self._update_title()
        # Recompute automatic ylim and synchronize the committed state with the StringVar.
        # 自動 ylim を再計算して内部状態と表示用 StringVar を同期させる。
        try:
            new_ylim = float(self._app._compute_auto_ylim(fiber))
            if new_ylim > 0:
                self._ylim = new_ylim
                self._ylim_var.set(self._app._fmt_num(self._ylim))
        except Exception:
            pass
        self._redraw_fiber_image()
        self._redraw_profile()
        # Refresh Entry styles so automatic updates do not look unconfirmed.
        # Entry スタイルを再評価（自動更新で薄青になるのを防ぐ）。
        try:
            self._refresh_all_entry_states()
        except Exception:
            pass

    def redraw_profile_only(self) -> None:
        """
        Redraw only the profile after main-window display toggles change.
        メイン側の表示チェックボックス変更時にプロファイルだけを再描画する。
        """
        self._redraw_profile()

    def redraw_fiber_only(self) -> None:
        """
        Redraw only the enlarged image after main-window unit changes.
        メイン側の軸目盛単位変更などで拡大像だけを再描画する。
        """
        self._redraw_fiber_image()

    def clear_for_no_selection(self) -> None:
        """
        Clear both plots when no dataset or fiber is selected.
        データセットまたはファイバーが未選択になったとき、両方の図を空にする。
        """
        self._fiber = None
        try:
            self._fiber_ax.clear()
            self._fiber_ax.axis("off")
            if self._fiber_cbar is not None:
                try:
                    self._fiber_cbar.remove()
                except Exception:
                    pass
                self._fiber_cbar = None
            self._fiber_canvas.draw_idle()
        except Exception:
            pass
        try:
            self._prof_ax.clear()
            self._prof_ax.axis("off")
            self._prof_canvas.draw_idle()
        except Exception:
            pass
        self._update_title()

    # -- Title -----------------------------------------------------------------

    def _update_title(self) -> None:
        """
        Update the detail-window title from the current fiber index.
        現在のファイバー番号から個別表示ウインドウのタイトルを更新する。
        """
        app = self._app
        name = app.current_image.name if app.current_image is not None else "fiber"
        idx  = app._sel_idx
        if idx is None:
            self.title(_("個別表示 – {name}").format(name=name))
        else:
            self.title(_("個別表示 – {name} / fiber #{idx}").format(name=name, idx=idx))

    # -- UI construction -------------------------------------------------------

    def _build_canvases_and_controls(self) -> None:
        """
        Build the side-by-side detail-window controls and plot canvases.
        個別表示ウインドウの左右 2 分割コントロールと描画 Canvas を構築する。

        Each column contains a settings row and a plot canvas. Settings sections
        are marked with row prefixes instead of LabelFrames, following GUI01.
        各カラムは「設定 + 図」のセットで構成する。GUI01 の流儀に合わせ、
        LabelFrame は使わず、設定セクションは行頭プレフィックスで区別する。
        """
        horiz = ttk.PanedWindow(self, orient="horizontal")
        horiz.pack(fill="both", expand=True, padx=8, pady=8)

        # =====================================================================
        # Left column: enlarged-image settings and canvas.
        # =====================================================================
        fiber_outer = ttk.Frame(horiz)
        horiz.add(fiber_outer, weight=1)
        self._build_fiber_settings(fiber_outer)
        self._build_fiber_canvas(fiber_outer)

        # =====================================================================
        # Right column: profile settings and canvas.
        # =====================================================================
        prof_outer = ttk.Frame(horiz)
        horiz.add(prof_outer, weight=1)
        self._build_profile_settings(prof_outer)
        self._build_profile_canvas(prof_outer)

    def _build_fiber_settings(self, parent: ttk.Frame) -> None:
        """
        Build the enlarged-image settings row (size, fonts, save button).
        拡大像の設定行（サイズ・フォント・画像保存ボタン）を構築する。
        """
        # -- Enlarged-image display settings, row 1: width, height, and font sizes --
        # Use a leading label instead of a LabelFrame.
        # LabelFrame は使わず、行頭ラベルでセクションを示す。
        # Font-size entries sit to the right of the height entry after the layout change.
        # 各フォントサイズ入力欄（軸ラベル/軸目盛/カラーバー）は高さ入力欄の右側に並べる（仕様変更）。
        f_row1 = ttk.Frame(parent)
        f_row1.pack(side="top", fill="x", padx=2, pady=(2, 2))
        ttk.Label(f_row1, text=_("幅") + " (px)").pack(side="left", padx=(0, 6))
        self.ent_fiber_w = ttk.Entry(f_row1, width=5, textvariable=self._fiber_w_var)
        self.ent_fiber_w.pack(side="left", padx=(2, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_w,
            lambda: self._app._fmt_num(self._fiber_w),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(f_row1, text=_("高さ") + " (px)").pack(side="left")
        self.ent_fiber_h = ttk.Entry(f_row1, width=5, textvariable=self._fiber_h_var)
        self.ent_fiber_h.pack(side="left", padx=(2, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_h,
            lambda: self._app._fmt_num(self._fiber_h),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )
        # Split font sizes into axis label, tick, and colorbar controls.
        # フォントサイズは軸ラベル・軸目盛・カラーバーの3分割（高さの右側に配置）。
        # Colorbar tick and label fonts share one value, following GUI01 / GUI02.
        # カラーバーは目盛とラベルを同じ値で制御（GUI01 / GUI02 と同じ流儀）。
        ttk.Label(f_row1, text=_("フォントサイズ：軸ラベル")).pack(side="left", padx=(0, 2))
        self.ent_fiber_label_fs = ttk.Entry(f_row1, width=4,
                                            textvariable=self._fiber_label_fs_var)
        self.ent_fiber_label_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_label_fs,
            lambda: self._app._fmt_num(self._fiber_label_fs),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(f_row1, text=_("軸目盛")).pack(side="left", padx=(0, 2))
        self.ent_fiber_tick_fs = ttk.Entry(f_row1, width=4,
                                           textvariable=self._fiber_tick_fs_var)
        self.ent_fiber_tick_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_tick_fs,
            lambda: self._app._fmt_num(self._fiber_tick_fs),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(f_row1, text=_("カラーバー")).pack(side="left", padx=(0, 2))
        self.ent_fiber_cbar_fs = ttk.Entry(f_row1, width=4,
                                           textvariable=self._fiber_cbar_fs_var)
        self.ent_fiber_cbar_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_cbar_fs,
            lambda: self._app._fmt_num(self._fiber_cbar_fs),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )

        ttk.Button(f_row1, text=_("画像を保存"),
                   command=self._save_fiber_image).pack(side="left", padx=(2, 4))

    def _build_fiber_canvas(self, parent: ttk.Frame) -> None:
        """
        Build the enlarged-image canvas and its Matplotlib figure.
        拡大像 Canvas と Matplotlib Figure を構築する。
        """
        # -- Enlarged-image canvas --
        fiber_canvas_holder = tk.Canvas(parent, highlightthickness=0,
                                        borderwidth=0)
        fiber_canvas_holder.pack(side="top", fill="both", expand=True)
        self._fiber_holder = fiber_canvas_holder
        self._fiber_inner  = ttk.Frame(fiber_canvas_holder)
        fiber_canvas_holder.create_window((0, 0), window=self._fiber_inner,
                                          anchor="nw")

        self._fiber_fig    = plt.Figure()
        self._fiber_ax     = self._fiber_fig.add_subplot(111)
        self._fiber_cbar   = None
        self._fiber_canvas = FigureCanvasTkAgg(self._fiber_fig, master=self._fiber_inner)
        self._fiber_canvas.get_tk_widget().pack(side="top", anchor="nw")

    def _build_profile_settings(self, parent: ttk.Frame) -> None:
        """
        Build the three profile-settings rows (entries, display options, save).
        プロファイル設定の3行（入力欄・表示オプション・保存）を構築する。
        """
        # Row 1: profile width, height, Y-axis maximum, then label/tick/legend fonts.
        # 行1: プロファイル表示設定: 幅 / 高さ / y軸最大値 / 軸ラベルfs / 軸目盛fs / 凡例fs。
        # Y-axis maximum sits between the height entry and the font-size entries.
        # y軸最大値(nm) は高さ入力欄と各フォントサイズ入力欄の間に配置する。
        p_row1 = ttk.Frame(parent)
        p_row1.pack(side="top", fill="x", padx=2, pady=(2, 2))
        ttk.Label(p_row1, text=_("幅") + " (px)").pack(side="left", padx=(0, 6))
        self.ent_prof_w = ttk.Entry(p_row1, width=5, textvariable=self._prof_w_var)
        self.ent_prof_w.pack(side="left", padx=(2, 8))
        self._app._register_unconfirmed_entry(
            self.ent_prof_w,
            lambda: self._app._fmt_num(self._prof_w),
            self._commit_profile_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(p_row1, text=_("高さ") + " (px)").pack(side="left")
        self.ent_prof_h = ttk.Entry(p_row1, width=5, textvariable=self._prof_h_var)
        self.ent_prof_h.pack(side="left", padx=(2, 8))
        self._app._register_unconfirmed_entry(
            self.ent_prof_h,
            lambda: self._app._fmt_num(self._prof_h),
            self._commit_profile_settings,
            registry=self._unconfirmed_entries,
        )
        # Place Y-axis maximum to the left of the axis-label font size after the layout change.
        # y軸最大値(nm) は軸ラベル fs の左（高さ入力欄の右）に配置（仕様変更）。
        # Synchronize _ylim and _ylim_var with _fmt_num to avoid a false
        # unconfirmed state during initial drawing.
        # 内部状態 self._ylim と表示用 StringVar self._ylim_var を _fmt_num で同期させて、
        # 初期描画時に「未確定」状態（青色）になるバグを回避する。
        ttk.Label(p_row1, text=_("Y最大") + " (nm)").pack(side="left", padx=(0, 2))
        self.ent_ylim = ttk.Entry(p_row1, width=5, textvariable=self._ylim_var)
        self.ent_ylim.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_ylim,
            lambda: self._app._fmt_num(self._ylim),
            self._commit_ylim,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(p_row1, text=_("フォントサイズ：軸ラベル")).pack(side="left", padx=(0, 2))
        self.ent_label_fs = ttk.Entry(p_row1, width=4, textvariable=self._label_fs_var)
        self.ent_label_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_label_fs,
            lambda: self._app._fmt_num(self._label_fs),
            self._commit_profile_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(p_row1, text=_("軸目盛")).pack(side="left", padx=(0, 2))
        self.ent_tick_fs = ttk.Entry(p_row1, width=4, textvariable=self._tick_fs_var)
        self.ent_tick_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_tick_fs,
            lambda: self._app._fmt_num(self._tick_fs),
            self._commit_profile_settings,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(p_row1, text=_("凡例")).pack(side="left", padx=(0, 2))
        self.ent_legend_fs = ttk.Entry(p_row1, width=4, textvariable=self._legend_fs_var)
        self.ent_legend_fs.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_legend_fs,
            lambda: self._app._fmt_num(self._legend_fs),
            self._commit_profile_settings,
            registry=self._unconfirmed_entries,
        )

        # Row 2: tick direction, grid mode, and legend location.
        # 行2: 目盛りの向き / グリッド表示 / 凡例位置。
        # Display-element checkboxes live with the save button in row 3.
        # 表示要素チェックボックスは行3の保存ボタンと同じ行に置く。
        # Profile y-limits are recomputed automatically for each selected fiber.
        # プロファイル y 上限は選択ファイバーごとに自動再計算する。
        p_row2 = ttk.Frame(parent)
        p_row2.pack(side="top", fill="x", padx=2, pady=(0, 2))
        ttk.Label(p_row2, text=_("目盛りの向き")).pack(side="left")
        tick_dir_labels = [label for _key, label in self._tick_dir_choices]
        cb_tick_dir = ttk.Combobox(p_row2, textvariable=self._tick_dir_var,
                                   values=tick_dir_labels,
                                   state="readonly",
                                   width=localized_combobox_width(
                                       tick_dir_labels, min_width=7, max_width=14))
        cb_tick_dir.pack(side="left", padx=(2, 8))
        ttk.Label(p_row2, text=_("グリッド表示")).pack(side="left")
        grid_labels = [label for _key, label in self._grid_choices]
        cb_grid = ttk.Combobox(p_row2, textvariable=self._grid_var,
                               values=grid_labels,
                               state="readonly",
                               width=localized_combobox_width(
                                   grid_labels, min_width=7, max_width=14))
        cb_grid.pack(side="left", padx=(2, 8))
        ttk.Label(p_row2, text=_("凡例位置")).pack(side="left")
        legend_loc_labels = [label for _key, label in self._legend_loc_choices]
        cb_legend_loc = ttk.Combobox(p_row2, textvariable=self._legend_loc_var,
                                     values=legend_loc_labels,
                                     state="readonly",
                                     width=localized_combobox_width(
                                         legend_loc_labels, min_width=9, max_width=24))
        cb_legend_loc.pack(side="left", padx=(2, 8))

        # Row 3: display-element checkboxes, then the Save Image button.
        # 行3: 表示要素チェックボックス → 画像保存ボタン。
        p_row3 = ttk.Frame(parent)
        p_row3.pack(side="top", fill="x", padx=2, pady=(0, 2))
        # Display-element label and checkboxes, placed left of the save button.
        # 表示要素ラベル＋チェックボックス（画像を保存ボタンの左に配置）。
        ttk.Label(p_row3, text=_("表示：")).pack(side="left", padx=(2, 4))
        ttk.Checkbutton(
            p_row3, text=_("キンク"),
            variable=self._app.show_kink_var,
            command=self._redraw_profile,
        ).pack(side="left", padx=(0, 4))
        ttk.Checkbutton(
            p_row3, text=_("中央値/最大値"),
            variable=self._app.show_medmax_var,
            command=self._redraw_profile,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(p_row3, text=_("画像を保存"),
                   command=self._save_profile_image).pack(side="left", padx=(0, 4))
        # Combobox selections redraw immediately.
        cb_tick_dir.bind("<<ComboboxSelected>>", lambda _e: self._redraw_profile())
        cb_grid.bind("<<ComboboxSelected>>", lambda _e: self._redraw_profile())
        cb_legend_loc.bind("<<ComboboxSelected>>", lambda _e: self._redraw_profile())

    def _build_profile_canvas(self, parent: ttk.Frame) -> None:
        """
        Build the profile canvas and its Matplotlib figure.
        プロファイル Canvas と Matplotlib Figure を構築する。
        """
        # -- Profile canvas --
        prof_canvas_holder = tk.Canvas(parent, highlightthickness=0,
                                       borderwidth=0)
        prof_canvas_holder.pack(side="top", fill="both", expand=True)
        self._prof_holder = prof_canvas_holder
        self._prof_inner  = ttk.Frame(prof_canvas_holder)
        prof_canvas_holder.create_window((0, 0), window=self._prof_inner,
                                         anchor="nw")

        self._prof_fig    = plt.Figure()
        self._prof_ax     = self._prof_fig.add_subplot(111)
        self._prof_canvas = FigureCanvasTkAgg(self._prof_fig, master=self._prof_inner)
        self._prof_canvas.get_tk_widget().pack(side="top", anchor="nw")

    # -- Commit callbacks local to the detail window ---------------------------

    def _commit_fiber_settings(self) -> bool:
        """
        Commit enlarged-image size and font settings together.
        拡大像のサイズとフォント設定をまとめて確定する。
        """
        try:
            new_w     = max(200, int(self._fiber_w_var.get().strip()))
            new_h     = max(150, int(self._fiber_h_var.get().strip()))
            new_lblfs = float(self._fiber_label_fs_var.get().strip())
            new_tkfs  = float(self._fiber_tick_fs_var.get().strip())
            new_cbfs  = float(self._fiber_cbar_fs_var.get().strip())
        except ValueError:
            messagebox.showerror(_("エラー"), _("拡大像の設定値が不正です。"))
            return False
        if not all(1 <= v <= 60 for v in (new_lblfs, new_tkfs, new_cbfs)):
            messagebox.showerror(_("エラー"), _("フォントサイズは 1〜60 の範囲で入力してください。"))
            return False
        self._fiber_w        = new_w
        self._fiber_h        = new_h
        self._fiber_label_fs = new_lblfs
        self._fiber_tick_fs  = new_tkfs
        self._fiber_cbar_fs  = new_cbfs
        rewrite_entries((
            (self.ent_fiber_w,        self._fiber_w),
            (self.ent_fiber_h,        self._fiber_h),
            (self.ent_fiber_label_fs, self._fiber_label_fs),
            (self.ent_fiber_tick_fs,  self._fiber_tick_fs),
            (self.ent_fiber_cbar_fs,  self._fiber_cbar_fs),
        ), formatter=self._fmt_num)
        self._redraw_fiber_image()
        self._refresh_all_entry_states()
        return True

    def _commit_profile_settings(self) -> bool:
        """
        Commit profile size and font settings together.
        プロファイルのサイズとフォント設定をまとめて確定する。
        """
        try:
            new_w  = max(200, int(self._prof_w_var.get().strip()))
            new_h  = max(150, int(self._prof_h_var.get().strip()))
            new_lfs = float(self._label_fs_var.get().strip())
            new_tfs = float(self._tick_fs_var.get().strip())
            new_efs = float(self._legend_fs_var.get().strip())
        except ValueError:
            messagebox.showerror(_("エラー"), _("プロファイルの設定値が不正です。"))
            return False
        if not all(1 <= v <= 60 for v in (new_lfs, new_tfs, new_efs)):
            messagebox.showerror(_("エラー"), _("フォントサイズは 1〜60 の範囲で入力してください。"))
            return False
        self._prof_w    = new_w
        self._prof_h    = new_h
        self._label_fs  = new_lfs
        self._tick_fs   = new_tfs
        self._legend_fs = new_efs
        rewrite_entries((
            (self.ent_prof_w,    self._prof_w),
            (self.ent_prof_h,    self._prof_h),
            (self.ent_label_fs,  self._label_fs),
            (self.ent_tick_fs,   self._tick_fs),
            (self.ent_legend_fs, self._legend_fs),
        ), formatter=self._fmt_num)
        self._redraw_profile()
        self._refresh_all_entry_states()
        return True

    def _commit_ylim(self) -> bool:
        """
        Commit the profile Y-axis upper limit.
        プロファイルの Y 軸最大値を確定する。
        """
        return self._commit_float_fields(
            [(self.ent_ylim, "_ylim", "y軸最大値")],
            validator=lambda v: None if v["_ylim"] > 0
            else _("y軸最大値には正の数値を入力してください。"),
            on_success=self._redraw_profile,
        )

    # -- Drawing: enlarged image -----------------------------------------------

    def _redraw_fiber_image(self) -> None:
        """
        Redraw the enlarged AFM image for the current fiber.
        現在ファイバーの拡大 AFM 像を再描画する。

        This window inherits ``vmin``, ``vmax``, ``scale_um``, and tick-display
        units from the main app; only figure size and local font sizes are
        adjusted here.
        本ウインドウはメインアプリの ``vmin``、``vmax``、``scale_um``、
        軸目盛単位を継承し、ここでは Figure サイズとローカルフォントサイズだけを調整する。
        """
        app = self._app
        fiber = self._fiber

        # Do nothing when no fiber is selected; clear_for_no_selection already clears plots.
        # ファイバー未選択時は何もしない（clear_for_no_selection で空にされる）。
        if fiber is None:
            return

        # Use the main window's committed state and selected tick-display unit.
        # メイン側の確定済み内部状態を参照する。
        # Tick-display units follow the main-window radio buttons.
        # 軸目盛単位（µm / nm）はメイン側ラジオの選択に従う。
        vmin = app.vmin
        vmax = app.vmax
        x_scale, y_scale, unit_label = app._get_extent_scale_xy_and_unit()

        # Derive per-axis physical scale per pixel from the main image size
        # (X from width, Y from height).
        # 物理スケール/px をメイン画像サイズから軸別に算出する（X は幅、Y は高さ）。
        if app.current_image is not None:
            full_h, full_w = app.current_image.calibrated_image.shape[:2]
            x_spp = x_scale / full_w
            y_spp = y_scale / full_h
        else:
            # Fallback when no dataset is loaded: assume a 1024 px image and
            # derive the pixel size from the committed scale (already in the
            # axis-label unit), so this path stays consistent with the
            # scale-entry fallback instead of assuming a separate fixed size.
            # データ未ロード時のフォールバック：1024 px 画像を仮定し、確定済み
            # スケールから画素サイズを導出する（軸ラベル単位に換算済み）。
            # スケール入力欄のフォールバックと別の固定サイズを仮定せず整合を保つ。
            x_spp = x_scale / 1024.0
            y_spp = y_scale / 1024.0

        # Use the three local font-size settings.
        fs_label = self._fiber_label_fs
        fs_tick  = self._fiber_tick_fs
        fs_cbar  = self._fiber_cbar_fs
        w_px = self._fiber_w
        h_px = self._fiber_h

        dpi = 100
        self._fiber_fig.set_size_inches(w_px / dpi, h_px / dpi)
        # Match the Tk widget size to the Figure pixel size.
        # Tk ウィジェット側も Figure と同じピクセルサイズに揃える。
        # Otherwise stale pixels can remain when the Figure becomes smaller.
        # これをやらないと、Figure を小さくした時に親フレームに残る
        # as clipped remnants from stale canvas pixels.
        # 古いキャンバス画素が切れ端として表示されてしまう。
        self._fiber_canvas.get_tk_widget().configure(width=w_px, height=h_px)
        try:
            self._fiber_holder.configure(scrollregion=(0, 0, w_px, h_px))
        except Exception:
            pass

        ax = self._fiber_ax
        ax.clear()
        if self._fiber_cbar is not None:
            try:
                self._fiber_cbar.remove()
            except Exception:
                pass
            self._fiber_cbar = None
        ax.axis("on")

        img = fiber.fiber_image
        h_px_img, w_px_img = img.shape[:2]
        extent = [0, w_px_img * x_spp, h_px_img * y_spp, 0]

        im = ax.imshow(img, cmap="afmhot", vmin=vmin, vmax=vmax,
                       extent=extent, aspect="equal")

        # Add a colorbar with the same height as the heatmap.
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.05)
        self._fiber_cbar = self._fiber_fig.colorbar(im, cax=cax)
        # Control colorbar ticks and label with the same fs_cbar value.
        # カラーバーは目盛とラベルを同じ fs_cbar で制御（GUI01 / GUI02 流儀）。
        self._fiber_cbar.ax.tick_params(labelsize=fs_cbar)
        self._fiber_cbar.set_label("Height (nm)", fontsize=fs_cbar)

        # Fiber track line.
        if len(fiber.xtrack) > 0:
            ax.plot(fiber.xtrack * x_spp, fiber.ytrack * y_spp,
                    color="lime", lw=1.0, alpha=0.75, zorder=4)

        # Kink points.
        if len(fiber.kink_indices) > 0:
            kx = fiber.xtrack[fiber.kink_indices] * x_spp
            ky = fiber.ytrack[fiber.kink_indices] * y_spp
            ax.scatter(kx, ky, c="cyan", s=20, zorder=5)

        ax.set_xlabel("({0})".format(unit_label), fontsize=fs_label)
        ax.set_ylabel("({0})".format(unit_label), fontsize=fs_label)
        ax.tick_params(labelsize=fs_tick)
        self._fiber_fig.tight_layout(pad=0.4)
        self._fiber_canvas.draw_idle()

    # -- Drawing: profile -------------------------------------------------------

    def _redraw_profile(self) -> None:
        """
        Redraw the height profile using main-window display toggles.
        メイン側の表示切替を参照して高さプロファイルを再描画する。
        """
        app = self._app
        fiber = self._fiber

        # Do nothing when no fiber is selected.
        if fiber is None:
            return

        # Use committed local state.
        ylim = self._ylim if self._ylim > 0 else DEFAULT_HEIGHT_YLIM
        w_px = self._prof_w
        h_px = self._prof_h
        label_fs  = self._label_fs
        tick_fs   = self._tick_fs
        legend_fs = self._legend_fs

        tick_dir  = self._tick_dir_label_to_key.get(self._tick_dir_var.get(), "out")
        grid_mode = self._grid_label_to_key.get(self._grid_var.get(), "none")
        legend_loc = self._legend_loc_label_to_key.get(
            self._legend_loc_var.get(), "upper right")

        dpi = 100
        self._prof_fig.set_size_inches(w_px / dpi, h_px / dpi)
        # Match the Tk widget size to the Figure pixel size.
        # Tk ウィジェット側も Figure と同じピクセルサイズに揃える。
        self._prof_canvas.get_tk_widget().configure(width=w_px, height=h_px)
        try:
            self._prof_holder.configure(scrollregion=(0, 0, w_px, h_px))
        except Exception:
            pass

        ax = self._prof_ax
        ax.clear()
        ax.axis("on")
        ax.plot(fiber.horizon, fiber.height, color="dimgray", lw=1.5)

        # Median and maximum guide lines follow the main-window checkbox.
        # 中央値・最大値の水平線（メイン側のチェック状態を参照）。
        if app.show_medmax_var.get():
            med = float(np.median(fiber.height))
            mx  = float(np.max(fiber.height))
            ax.axhline(y=med, color="blue",      linestyle="--", lw=1.5, alpha=0.85,
                       label=f"Median {med:.2f} nm")
            ax.axhline(y=mx,  color="red", linestyle="--", lw=1.5, alpha=0.85,
                       label=f"Max {mx:.2f} nm")

        # Kink locations as vertical dashed lines.
        # キンク位置（垂直破線）。
        if app.show_kink_var.get() and len(fiber.kink_indices) > 0:
            for i, ki in enumerate(fiber.kink_indices):
                if ki < len(fiber.horizon):
                    ax.axvline(x=fiber.horizon[ki], color="cyan", linestyle="--", lw=1.0,
                               label="Kink" if i == 0 else None)

        if len(fiber.horizon) > 0:
            ax.set_xlim(0, fiber.horizon[-1])
        ax.set_ylim(0, ylim)
        ax.set_xlabel("Length (nm)", fontsize=label_fs)
        ax.set_ylabel("Height (nm)", fontsize=label_fs)
        ax.tick_params(axis="both", labelsize=tick_fs, direction=tick_dir)

        # Draw a legend only when plotted elements provide labels.
        # legend は描画要素がある場合のみ。凡例 fs は独立した内部状態を使用。
        # Legend location follows the Combobox key:
        # 凡例位置は Combobox の選択キーに従う:
        #   "off"        ... do not draw a legend
        #   "off"        ... 凡例を描画しない
        #   "axes_right" ... place it outside the axes to avoid overlap
        #   "axes_right" ... 軸の外（右側）に配置（プロットとの重なりを物理的に回避）
        #   other keys   ... pass the matplotlib loc string through
        #   それ以外      ... matplotlib の loc 文字列をそのまま使用
        handles = ax.get_legend_handles_labels()[0]
        if handles and legend_loc != "off":
            if legend_loc == "axes_right":
                ax.legend(fontsize=legend_fs, loc="upper left",
                          bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)
            else:
                ax.legend(fontsize=legend_fs, loc=legend_loc)

        # Grid lines.
        ax.grid(False)
        if grid_mode == "x":
            ax.grid(True, axis="x")
        elif grid_mode == "y":
            ax.grid(True, axis="y")
        elif grid_mode == "both":
            ax.grid(True, axis="both")

        self._prof_fig.tight_layout(pad=0.8)
        self._prof_canvas.draw_idle()

    # -- Image saving ----------------------------------------------------------

    def _default_save_name(self, suffix: str) -> str:
        """
        Build a default export filename for the current fiber or dataset.
        現在のファイバーまたはデータセットから既定の出力ファイル名を組み立てる。
        """
        app = self._app
        name = app.current_image.name if app.current_image is not None else "fiber"
        idx  = app._sel_idx
        if idx is None:
            return f"{name}_{suffix}"
        return f"{name}_fiber{idx}_{suffix}"

    def _save_fig_with_dialog(self, fig: plt.Figure, suffix: str, title: str,
                            ref_w_var: tk.StringVar) -> None:
        """
        Save a Figure through a dialog with DPI derived from the reference width.
        参照幅から DPI を算出し、ダイアログ経由で Figure を保存する。
        """
        # Dynamic DPI calculation is specific to this window.
        # 動的DPI計算はこのウインドウ固有の仕様なので呼び出し側で算出する。
        try:
            dpi = max(72, int(ref_w_var.get()) // int(fig.get_size_inches()[0]))
        except (ValueError, ZeroDivisionError):
            dpi = 150
        save_figure_with_dialog(
            self, fig,
            initial_name=self._default_save_name(suffix),
            initial_dir=self._app._default_save_dir(),
            title=title,
            dpi=dpi,
            log_cb=self._app._log,   # Report the result in the log, matching the other GUIs.
        )

    def _save_fiber_image(self) -> None:
        """
        Save the enlarged fiber image.
        ファイバー拡大像を保存する。
        """
        self._save_fig_with_dialog(self._fiber_fig, "detail",
                                   _("画像を保存"), self._fiber_w_var)

    def _save_profile_image(self) -> None:
        """
        Save the height profile image.
        高さプロファイル画像を保存する。
        """
        self._save_fig_with_dialog(self._prof_fig, "profile",
                                   _("画像を保存"), self._prof_w_var)

    # -- Close -----------------------------------------------------------------

    def _on_close(self) -> None:
        """
        Close matplotlib figures and notify the main app.
        matplotlib Figure を閉じ、メインアプリへ通知する。
        """
        try:
            plt.close(self._fiber_fig)
        except Exception:
            pass
        try:
            plt.close(self._prof_fig)
        except Exception:
            pass
        # Notify the main app so it can clear the stored reference.
        # メインアプリへ通知（参照クリア）。
        try:
            self._app._on_detail_window_closed()
        except Exception:
            pass
        self.destroy()


# ===== Dialog: fiber-connection settings =====

class ConnectSettingsWindow(tk.Toplevel):
    """
    Non-modal window to edit fiber-connection parameters.
    ファイバー連結パラメータを編集する非モーダルウインドウ。

    Attributes
    ----------
    _app
        Main application window that owns `connect_params` and re-analysis.
        `connect_params` と再解析を保持するメインアプリケーションウインドウ。

    Notes
    -----
    Fields map one-to-one onto `lib.fiber_connector.ConnectParams`. Applying
    validates all six values, stores a new immutable `ConnectParams` on the main
    window, and re-analyzes the current dataset when connection is enabled.
    各入力欄は `lib.fiber_connector.ConnectParams` と 1 対 1 に対応する。適用時に
    6 値を検証し、新しい不変 `ConnectParams` をメインウインドウへ保存し、連結が
    有効なら現在のデータセットを再解析する。
    """

    def __init__(self, parent: "App") -> None:
        """
        Build the connection-settings window from the app's current parameters.
        アプリの現在パラメータから連結設定ウインドウを構築する。
        """
        super().__init__(parent)
        self._app: "App" = parent
        self.title(_("ファイバー連結の設定"))
        setup_ttk_theme(self)
        apply_window_size(self, 460, 340, min_w=420, min_h=300)

        p = parent.connect_params
        # Row spec: (attr, label text, kind, help text). The label keeps fixed
        # scientific units in English (§6.2); "kind" drives validation.
        # 行仕様: (属性, ラベル, 種別, 補足)。ラベルの科学単位は英語固定（§6.2）。
        # "kind" が検証方法を決める。
        self._rows = (
            ("clusters_range",  _("連結距離") + " (px)", "pos_float",
             _("端点どうしがこの距離以内なら連結候補にする。")),
            ("angle_threshold", _("直線性の角度しきい値") + " (degree)", "angle",
             _("両端点の角度がこの値を超える（＝ほぼ直線）ときのみ連結する。")),
            ("lookback_length", _("方向推定の振り返り点数"), "int_ge2",
             _("端点での向きを推定するのに使うトラック点数。")),
            ("num_avg_points",  _("橋渡し高さの平均点数"), "int_ge1",
             _("連結部の高さを決めるために平均する端点サンプル数。")),
            ("height_diff_ratio", _("高さ差の許容比"), "pos_float",
             _("高さ中央値の相対差がこの値以下の断片のみ連結する。大きいほど緩い。")),
            ("trim_points",     _("交差ノイズのトリミング点数"), "int_ge0",
             _("連結前に接合部付近から切り落とす骨格点数。")),
        )

        self._vars: dict = {}
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=8)

        for r, (attr, label, _kind, hint) in enumerate(self._rows):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", padx=(0, 6), pady=3)
            var = tk.StringVar(value=self._fmt_value(getattr(p, attr)))
            ent = ttk.Entry(body, width=10, textvariable=var)
            ent.grid(row=r, column=1, sticky="w", pady=3)
            self._vars[attr] = var
            ToolTip(ent, hint)
        body.columnconfigure(0, weight=1)

        btns = ttk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text=_("適用"), command=self._on_apply).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text=_("既定値に戻す"), command=self._on_reset).pack(side="right", padx=(4, 0))
        ttk.Button(btns, text=_("閉じる"), command=self._on_close).pack(side="right", padx=(4, 0))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @staticmethod
    def _fmt_value(value) -> str:
        """
        Format a parameter value for its entry (ints without a decimal point).
        パラメータ値を入力欄用に整形する（整数は小数点なしで表示）。
        """
        if isinstance(value, int):
            return str(value)
        # Trim a trailing ".0" so 20.0 shows as "20" while 0.3 stays "0.3".
        # 末尾の ".0" を落とし、20.0 は "20"、0.3 は "0.3" と表示する。
        text = f"{value:g}"
        return text

    def _parse_field(self, attr: str, kind: str, raw: str) -> float:
        """
        Parse and range-check one field, raising ``ValueError`` on invalid input.
        1 つの入力欄を解析・範囲検査し、不正なら ``ValueError`` を送出する。
        """
        raw = raw.strip()
        if kind.startswith("int"):
            value: float = int(round(float(raw)))
        else:
            value = float(raw)

        if kind == "pos_float" and not (value > 0):
            raise ValueError(_("正の数値を入力してください。"))
        if kind == "angle" and not (0 < value <= 180):
            raise ValueError(_("0 より大きく 180 以下の角度を入力してください。"))
        if kind == "int_ge2" and value < 2:
            raise ValueError(_("2 以上の整数を入力してください。"))
        if kind == "int_ge1" and value < 1:
            raise ValueError(_("1 以上の整数を入力してください。"))
        if kind == "int_ge0" and value < 0:
            raise ValueError(_("0 以上の整数を入力してください。"))
        return value

    def _on_apply(self) -> None:
        """
        Validate all fields and push a new `ConnectParams` to the main window.
        全欄を検証し、新しい `ConnectParams` をメインウインドウへ渡す。
        """
        values: dict = {}
        for attr, label, kind, _hint in self._rows:
            try:
                values[attr] = self._parse_field(attr, kind, self._vars[attr].get())
            except ValueError as exc:
                messagebox.showerror(
                    _("入力エラー"),
                    "{label}: {msg}".format(label=label, msg=str(exc)),
                    parent=self,
                )
                return
        self._app._apply_connect_params(ConnectParams(**values))

    def _on_reset(self) -> None:
        """
        Reset all entry fields to the `ConnectParams` defaults.
        全入力欄を `ConnectParams` の既定値に戻す。
        """
        defaults = ConnectParams()
        for attr, _label, _kind, _hint in self._rows:
            self._vars[attr].set(self._fmt_value(getattr(defaults, attr)))

    def _on_close(self) -> None:
        """
        Notify the main window and close this settings window.
        メインウインドウへ通知してこの設定ウインドウを閉じる。
        """
        try:
            self._app._on_connect_window_closed()
        except Exception:
            pass
        self.destroy()


# ===== Entry point =====

def main() -> None:
    """
    Launch the GUI04 fiber tracking application.
    GUI04 ファイバー追跡アプリケーションを起動する。
    """
    app = App()
    app.mainloop()

# Run main only when this file is executed directly, not when imported.
if __name__ == "__main__":
    main()
