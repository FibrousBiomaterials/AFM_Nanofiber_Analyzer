# -*- coding: utf-8 -*-
"""
Interactive fiber tracking GUI for AFM datasets exported by GUI01.
GUI01 が出力した AFM データセットを対話的に追跡する GUI。

Loads ``.b2z`` bundle files produced by GUI01, rebuilds
``FiberTrackingImage`` objects, and lets users inspect individual nanofibers,
height profiles, and summary statistics.
GUI01 が生成した ``.b2z`` バンドルファイルを読み込み、``FiberTrackingImage``
を再構築して、ナノファイバーの個別追跡・高さプロファイル・統計情報を
対話的に確認する。

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
    "name": "Fiber Tracker",
    "description": (
        "Image Preprocessor で生成した解析済みファイルを読み込み、\n"
        "ナノファイバーを個別に追跡・表示します。\n"
        "\n"
        "・AFM全体像とファイバー一覧の対応表示\n"
        "・ファイバーごとの高さプロファイル（キンク位置・端点・中央値/最大値線）\n"
        "・統計値（高さ中央値・最大値・長さ・端点数・キンク数・キンク角度）\n"
        "・ファイバー連結（交差・分岐で分断された断片を1本のフィブリルへ再結合、ON/OFF・パラメータ設定可）\n"
        "・高さ範囲フィルター（specific_height_fibers 相当）\n"
        "・高さプロファイル、ファイバー拡大像、およびAFM全体像の PNG 出力\n"
        "・全ファイバーの統計値 CSV エクスポート\n"
        "\n"
        "入力フォルダは GUI01 の出力フォルダをそのまま指定してください。\n"
    )
}

# ===== Standard library =====
import os
import math
import traceback
import queue
import threading
from typing import Optional, List

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
# Import the lib modules that provide the AFM image-processing core.
# lib/ フォルダ内の各モジュールをインポートする。これらが AFM 画像処理の本体。
from lib.fiber_tracking_image import FiberTrackingImage
from lib.fiber import Fiber
from lib.fiber_connector import ConnectParams, filter_fibers_by_height
from lib.blosc2_io import bundle_has_keys, load_bundle, BUNDLE_EXT
from lib.measure import (
    TRACKING_BUNDLE_KEYS, compute_fiber_stats, isolated_fiber_flags,
    measure_bundle, read_scan_size_from_bundle, write_fiber_csv,
)
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_matplotlib_style, save_figure_with_dialog, ToolTip,
    setup_ttk_theme, rewrite_entries, mark_entry_state, replace_log_tail,
    save_text_widget_log, create_scrolled_text, create_scrolled_treeview,
    drain_ui_queue, extent_scale_and_unit, save_csv_with_dialog,
    bind_mousewheel_scroll, build_pan_zoom_toolbar,
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
# Margin in pixels drawn around the tracked bounding box in the enlarged view.
# The bounding box is tight, so both fiber ends touch the frame and one cannot
# tell whether tracking stopped at a real end point or at a crossing with a
# neighboring fiber; the margin brings that surrounding context into view.
# Display only: no measured value is derived from the padded crop.
# 個別表示の拡大像で、追跡した外接矩形の周囲に付ける余白（px）。外接矩形は
# 密着しているため両端が必ず枠に接し、追跡が本当の端点で終わったのか隣接
# ファイバーとの交差で切れたのかを判別できない。余白はその周辺状況を可視化
# する。表示専用であり、余白付き切り出しから計測値を算出することはない。
DEFAULT_FIBER_PAD_PX:          int   = 10
# Upper bound for the margin entry. A margin wide enough to swallow the fiber
# itself defeats the enlarged view, so the entry is capped rather than left open.
# 余白入力欄の上限。ファイバー自体が埋もれるほど広い余白は拡大表示の意味を
# 失わせるため、入力を無制限にせず上限を設ける。
MAX_FIBER_PAD_PX:              int   = 200
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


def crop_with_margin(image: np.ndarray, bbox: tuple, pad: int) -> tuple:
    """
    Crop a fiber bounding box with a surrounding margin, clipped to the image.
    ファイバーの外接矩形を周囲余白付きで切り出す（画像端でクリップする）。

    Parameters
    ----------
    image
        Calibrated height image the fiber was tracked in.
        ファイバーを追跡した補正済み高さ画像。
    bbox
        Bounding box ``(x, y, width, height)`` in pixels, as stored in
        ``Fiber.data``.
        画素単位の外接矩形 ``(x, y, 幅, 高さ)``。``Fiber.data`` の保持形式。
    pad
        Requested margin in pixels on each side.
        各辺に付ける余白 (px)。

    Returns
    -------
    tuple
        ``(crop, off_x, off_y)``: the cropped image, and the bounding-box origin
        measured inside that crop.
        ``(切り出し画像, off_x, off_y)``。off_* は切り出し画像内での外接矩形の原点。

    Notes
    -----
    Near an image border the margin is clipped, so the applied margin is
    asymmetric and smaller than ``pad``. Overlays must be offset by the returned
    origin rather than by ``pad``; otherwise the centerline and kink markers
    drift off the fiber for every fiber that touches a border.
    画像端では余白がクリップされ、実際の余白は非対称かつ ``pad`` より小さくなる。
    重ね描きのオフセットには ``pad`` ではなく戻り値の原点を使う必要がある。
    さもないと画像端に接する全ファイバーで中心線・キンク点が像からずれる。
    """
    x, y, w, h = (int(v) for v in bbox[:4])
    img_h, img_w = image.shape[:2]
    pad = max(0, int(pad))
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(img_w, x + w + pad)
    y1 = min(img_h, y + h + pad)
    return image[y0:y1, x0:x1], x - x0, y - y0


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

        # Keep the theme background: the matplotlib navigation toolbar uses
        # classic tk widgets that ignore the ttk theme and must be matched by hand.
        # テーマ背景色を保持する。matplotlib のナビゲーションツールバーは ttk
        # テーマ外の tk ウィジェットのため、手動で色を合わせる必要がある。
        self._clam_bg = setup_ttk_theme(self)

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

        # -- AFM overview pan/zoom view state --
        # Full-view limits captured after each background draw, used by the
        # reset button and to clamp panning at the image edge.
        # 背景描画ごとに取得する全体表示の軸範囲。リセットボタンと、画像端で
        # パンを止めるクランプに使う。
        self._afm_home_limits: Optional[tuple] = None
        # Signature of the data extent. A background rebuild keeps the current
        # zoom only while this is unchanged; a unit or scale switch rescales the
        # axes, so the old limits would frame a different region.
        # データ extent の識別子。これが同じ間だけ再構築後もズームを維持する。
        # 単位やスケールの切り替えで軸が張り替わると、旧い軸範囲は別の領域を
        # 指してしまうため。
        self._afm_extent_key: Optional[tuple] = None
        # Fiber-number texts and dashed boxes, kept so the ones outside the
        # visible limits can be skipped: they dominate the redraw cost, and a
        # redraw happens on every pan/zoom step.
        # ファイバー番号テキストと破線枠。表示範囲外のものを描画から外すために
        # 保持する。これらは再描画コストの大半を占め、パン/ズームのたびに
        # 再描画が走るため。
        self._overview_labels: List[object] = []
        self._overview_boxes:  List[object] = []

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

        # -- Isolated-fiber-only checkbox --
        # Default is off, so the fiber count stays comparable with earlier
        # versions. When on, only fibers that touch no other fiber anywhere
        # along their path are listed. A fiber cut where it crosses another one
        # has a truncated length rather than a short one, and a fibril
        # reconnected across a crossing has a length that depends on the
        # connector's judgment; excluding both leaves only fibers whose full
        # length is measured directly.
        # ── 孤立ファイバーのみ表示 ──
        # 既定 OFF（従来版とファイバー本数を比較可能に保つ）。ON のとき、経路上の
        # どこでも他のファイバーに接していないファイバーのみを一覧する。交差部で
        # 切断されたファイバーの長さは「短い」のではなく「切り詰められている」。
        # また交差を越えて再結合されたフィブリルの長さは連結器の判断に依存する。
        # 両者を除外することで、全長を直接計測できたファイバーだけが残る。
        self.isolated_only_var    = tk.BooleanVar(value=False)

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

        # -- Profile element checkboxes --
        # ── プロファイル描画要素チェックボックス ──
        self.show_kink_var   = tk.BooleanVar(value=True)
        self.show_medmax_var = tk.BooleanVar(value=True)

        # -- Enlarged-image element checkboxes --
        # ── 拡大像描画要素チェックボックス ──
        # Kept separate from the profile toggles above: the enlarged image shows
        # where a kink sits in 2D, the profile shows where it sits along the
        # fiber length, so the two views are toggled independently. They live on
        # the App, not on the detail window, so the choice survives closing and
        # reopening that window.
        # 上のプロファイル用とは別変数にする。拡大像は「2次元のどこにキンクが
        # あるか」、プロファイルは「全長のどこにあるか」を示すもので用途が違う。
        # 個別表示ウインドウは閉じると作り直されるため、状態を保持できるよう
        # App 側に置く。
        self.show_fiber_kink_var  = tk.BooleanVar(value=True)
        self.show_fiber_track_var = tk.BooleanVar(value=True)
        # A margin around the crop lets neighboring fibers into the frame, so
        # the tracked extent is outlined to keep the measured object
        # unambiguous, including in exported figures.
        # 余白を付けると隣接ファイバーが枠内に入るため、追跡した範囲を明示して
        # 出力図でも計測対象を取り違えないようにする。
        self.show_fiber_bbox_var  = tk.BooleanVar(value=True)

        # Fiber numbers and boxes on the AFM overview. At full zoom-out on a
        # dense image they overlap into noise and cost most of the redraw time,
        # so they can be switched off.
        # AFM 全体像のファイバー番号と枠。密な画像を全体表示すると番号が重なって
        # 読めないうえ、再描画時間の大半を占めるため OFF にできるようにする。
        self.show_overview_labels_var = tk.BooleanVar(value=True)

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
            "「孤立ファイバーのみ」とは排他で、一方を ON にすると他方は OFF になる。\n"
            "切り替えると現在のデータセットを再解析する。"
        ))
        ttk.Button(
            bar, text=_("連結設定…"),
            command=self._open_connect_settings,
        ).pack(side="left", padx=(0, 4))

        # -- Isolated fibers only: pure view filter, no reanalysis --
        # Placed next to the connection controls because the two answer the same
        # problem in opposite ways: connection reconstructs a fiber through a
        # crossing, this filter declines to trust any fiber that reaches one.
        # ── 孤立ファイバーのみ ── 再解析を伴わない表示フィルター。
        # 同じ問題に正反対の方針で答える機能なので連結操作の隣に配置する。連結は
        # 交差を越えてファイバーを再構築し、本フィルターは交差に達したファイバー
        # を信頼しない。
        chk_isolated = ttk.Checkbutton(
            bar, text=_("孤立ファイバーのみ"),
            variable=self.isolated_only_var,
            command=self._on_isolated_only_toggle,
        )
        chk_isolated.pack(side="left", padx=(2, 2))
        ToolTip(chk_isolated, _(
            "ON時: 他のファイバーと交差・接触していないファイバーだけを一覧・表示・"
            "CSV 出力の対象にする。\n"
            "交差部で切断されたファイバーは全長が不明なため、長さ統計から除外される。\n"
            "「ファイバー連結」とは排他で、一方を ON にすると他方は OFF になる。"
            "連結は交差を越えてファイバーをつなぐため、孤立ファイバーが"
            "ネットワークに取り込まれ、孤立と判定されなくなる。\n"
            "再解析は行わず、表示の絞り込みのみを切り替える。"
        ))

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

        # Pack the view-control row before the canvas frame: the canvas expands,
        # so anything packed after it would be squeezed out of the pane.
        # 表示操作行はキャンバスより先にパックする。キャンバスは expand する
        # ため、後からパックすると領域を確保できない。
        self._afm_tb_row = ttk.Frame(afm_outer)
        self._afm_tb_row.pack(side="bottom", fill="x", padx=2, pady=(0, 2))

        self._afm_frame = ttk.Frame(afm_outer)
        self._afm_frame.pack(fill="both", expand=True, padx=2, pady=2)

    def _build_afm_view_controls(self) -> None:
        """
        Build the AFM overview view row: pan/zoom toolbar and view buttons.
        AFM 全体像の表示操作行（Pan/Zoom ツールバーと表示ボタン）を構築する。

        Notes
        -----
        Called after ``_init_figures`` because the toolbar needs the canvas.
        ツールバーはキャンバスを必要とするため、``_init_figures`` の後に呼ぶ。
        """
        row = self._afm_tb_row

        # Pack the custom controls (side="right") BEFORE the toolbar so the
        # toolbar's growable coordinate readout can never squeeze them.
        # ツールバーの座標表示はホバー時に横へ伸びるため、独自コントロールを
        # 先に右側へ確保して押し潰されないようにする。
        ttk.Button(row, text=_("リセット"),
                   command=self._reset_overview_view).pack(side="right", padx=(8, 0))
        btn_zoom_sel = ttk.Button(row, text=_("選択へズーム"),
                                  command=self._zoom_to_selected)
        btn_zoom_sel.pack(side="right", padx=(8, 0))
        ToolTip(btn_zoom_sel, _(
            "選択中のファイバーが画面いっぱいになるまで拡大します。\n"
            "表示範囲外のファイバーを選んだ場合は自動で表示範囲へ入りますが、\n"
            "拡大率は変わりません。"
        ))
        chk_labels = ttk.Checkbutton(
            row, text=_("番号・枠"),
            variable=self.show_overview_labels_var,
            command=self._on_overview_labels_toggle,
        )
        chk_labels.pack(side="right", padx=(8, 0))
        ToolTip(chk_labels, _(
            "各ファイバーの番号と破線枠の表示を切り替えます。\n"
            "OFF にすると全体像の再描画が目に見えて速くなるため、\n"
            "拡大・移動の操作が重いときに有効です。\n"
            "選択中ファイバーの黄色い枠は常に表示されます。"
        ))

        # Place the toolbar last (side="left", no fill/expand) so it takes only
        # its own width and leaves the rest of the row to the controls above.
        # ツールバーは最後に左寄せで配置し、自分の幅だけ占有して残りを上の
        # コントロールへ渡す。
        toolbar_frame, _toolbar = build_pan_zoom_toolbar(
            row, self._afm_canvas, clam_bg=self._clam_bg)
        toolbar_frame.pack(side="left")

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

        # The pan/zoom toolbar needs the canvas, so build its row now.
        # Pan/Zoom ツールバーはキャンバスを必要とするため、ここで行を構築する。
        self._build_afm_view_controls()

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
        # Drop the pan/zoom view state with the dataset: the next dataset gets
        # its own full view, and stale limits must not be restored onto it.
        # パン/ズームの状態もデータセットと一緒に破棄する。次のデータセットは
        # 自身の全体表示から始まり、古い軸範囲を復元してはならない。
        self._afm_home_limits = None
        self._afm_extent_key  = None
        self._overview_labels = []
        self._overview_boxes  = []
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
                self.ui_queue.put(("file_loaded", (stem, image, fibers, stats)))
            except Exception:
                self.ui_queue.put(("file_error", (stem, traceback.format_exc())))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_file_loaded(self, stem: str, image, fibers: List[Fiber], stats: List[tuple]) -> None:
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
        # Start every dataset at full view. Datasets in one folder usually share
        # a scan size and pixel count, so the extent signature would match and
        # the previous dataset's zoom would silently carry over onto a different
        # image.
        # データセットは必ず全体表示から始める。同一フォルダのデータセットは
        # スキャンサイズも画素数も揃っていることが多く、extent 識別子が一致して
        # 前のデータセットのズームが別の画像へそのまま持ち越されてしまう。
        self._afm_extent_key = None

        # -- Auto-update vmin/vmax only when auto mode is enabled --
        # The skeleton is passed as the fiber mask so the upper bound is a
        # percentile of the fibers themselves rather than of the whole image,
        # which a contamination spike would otherwise dominate.
        # スケルトンをファイバーマスクとして渡し、上端を画像全体ではなく
        # ファイバー自身のパーセンタイルで決める（全体だとコンタミの
        # スパイクに支配される）。
        if self.auto_vrange_var.get() and image.calibrated_image is not None:
            self._apply_auto_vrange(
                image.calibrated_image, mask=image.skeleton_image, log=True,
            )

        self._log(_("読み込み完了: {name}  ファイバー数: {count}").format(
            name=os.path.basename(stem), count=len(fibers)
        ))
        # Read back through the accessor so a checked isolated-fiber filter
        # survives a file switch, as the height filter already does below.
        # アクセサ経由で読み直し、孤立ファイバーフィルターがファイル切替後も
        # 維持されるようにする（下の高さフィルターと同じ扱い）。
        self._populate_fiber_table(self._display_fibers())
        # Dispatch by display mode so the fiber view survives a file switch.
        # 表示モードで分岐し、ファイル切替後も色分け表示を維持する。
        self._rebuild_overview_bg()

        # Auto-select the first fiber after file selection, unlike folder selection.
        # 先頭ファイバーを自動選択（ファイル選択時は内部選択を行う、フォルダ選択時とは別）。
        children = self.fiber_tree.get_children()
        if children:
            self.fiber_tree.selection_set(children[0])
            self.fiber_tree.focus(children[0])
            # Programmatic re-selection, so keep the current pan/zoom view.
            # プログラムによる選び直しのため、現在のパン/ズームを維持する。
            self._on_fiber_select(follow_view=False)

        # If a new file is selected while the height filter is on, apply it automatically.
        # 高さフィルター ON のまま新ファイルに切り替わった場合、自動で適用する。
        if self.filter_enabled_var.get():
            self._apply_filter()

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
        # The cache is indexed by position in current_fibers, so any filter that
        # drops rows invalidates that mapping.
        # フィルターなし かつ キャッシュが有効な場合はインデックスで直接参照する。
        # キャッシュは current_fibers 内の位置で引くため、行を除外するフィルター
        # が有効ならその対応は無効になる。
        use_cache = (
            (not self._filter_active)
            and (not self.isolated_only_var.get())
            and len(self._fiber_stats) == len(fibers)
        )
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

    def _on_fiber_select(self, _event=None, *, follow_view: bool = True) -> None:
        """
        Update overview highlighting and detail windows after fiber selection.
        ファイバー選択後に全体像のハイライトと個別表示を更新する。

        Parameters
        ----------
        follow_view
            Whether a zoomed-in overview may pan to the selected fiber. Callers
            that re-select row 0 after repopulating the table pass ``False``.
            ズーム中の全体像が選択ファイバーへパンしてよいか。テーブル再構築後に
            先頭行を選び直す呼び出しは ``False`` を渡す。

        Notes
        -----
        Repopulating the fiber table (a file load, or the isolated-fiber
        filter) re-selects the first row programmatically. That is not the user
        choosing a fiber, so panning there would teleport a zoomed-in view to
        fiber 0 on every filter toggle.
        ファイバーテーブルの再構築（ファイル読み込みや孤立ファイバーフィルター）
        はプログラム側で先頭行を選び直す。これはユーザーがファイバーを選んだ
        わけではないため、ここでパンするとフィルター切替のたびにズーム中の視野が
        ファイバー 0 へ飛ばされてしまう。
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

        # A user selection is the one event that may move the view: while
        # zoomed in, a highlight outside the visible limits would leave the
        # screen unchanged and read as a dead control. Both calls schedule the
        # same idle draw.
        # 視野を動かしてよいのはユーザーによる選択だけである。ズーム中に表示
        # 範囲外へハイライトを置いても画面は変わらず、操作が効いていないように
        # 見える。2 つの呼び出しは同じアイドル描画にまとめられる。
        if follow_view:
            self._ensure_fiber_visible(fiber)
            self._afm_canvas.draw_idle()

        # Keep the non-modal detail window synchronized if it is open.
        # 個別表示が開いていれば追従させる（非モーダル）。
        self._update_detail_window(fiber)

    def _display_fibers(self) -> List[Fiber]:
        """
        Return the fiber list every view, selection, and export must use.
        一覧・選択・エクスポートが共通で使うファイバーリストを返す。

        Single accessor for the displayed population, so the fiber table, the
        overview, the detail window, and the CSV export can never disagree
        about which fibers are in scope. Table row ids are positions in this
        list, so all callers must read it rather than the raw fiber lists.
        表示対象母集団への唯一のアクセサ。一覧テーブル・全体像・個別表示・CSV
        出力の対象がずれないようにする。テーブルの行 ID はこのリスト内の位置な
        ので、呼び出し側は生のリストではなく必ずこれを参照すること。

        The height filter is applied first because it rebuilds fibers; the
        isolation test then runs on the fibers as they are actually measured
        and exported.
        高さフィルターはファイバーを再構築するため先に適用し、孤立判定は実際に
        計測・出力される状態のファイバーに対して行う。
        """
        fibers = self._filtered_fibers if self._filter_active else self.current_fibers
        if self.isolated_only_var.get() and self.current_image is not None:
            flags = isolated_fiber_flags(self.current_image, fibers)
            fibers = [f for f, keep in zip(fibers, flags) if keep]
        return fibers

    def _current_fiber(self) -> Optional[Fiber]:
        """
        Return the currently selected fiber, or ``None`` if no fiber is selected.
        現在選択中の Fiber を返し、未選択なら ``None`` を返す。
        """
        if self._sel_idx is None:
            return None
        fibers = self._display_fibers()
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

        # ax.clear() above discarded the previous artists; collect the new ones
        # so _cull_overview_labels can hide those outside the visible limits.
        # 上の ax.clear() で以前の artist は破棄済み。表示範囲外を
        # _cull_overview_labels で隠せるよう、新しい artist を集める。
        self._overview_labels = []
        self._overview_boxes  = []

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
            box = plt.Rectangle(
                (x_p, y_p), h_p, w_p,
                linewidth=1.0, linestyle="--", edgecolor="white", facecolor="none", alpha=0.6,
            )
            ax.add_patch(box)
            # clip_on keeps a zoomed-in view from painting the numbers of
            # off-screen fibers over the figure margins; patches clip already.
            # clip_on はズーム時に画面外ファイバーの番号が図の余白へはみ出して
            # 描かれるのを防ぐ。パッチ側は既定でクリップされる。
            label = ax.text(x_p + h_p / 2, y_p + w_p / 2, str(disp_i),
                            color="white", fontsize=7, ha="center", va="center",
                            fontweight="bold", clip_on=True)
            self._overview_boxes.append(box)
            self._overview_labels.append(label)

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
        Rebuild the overview background while preserving the pan/zoom view.
        パン/ズームの表示範囲を保ったまま全体像の背景を再構築する。

        Notes
        -----
        Ten call sites invalidate the background cache (vmin/vmax, scale, unit,
        filters, connection, display mode), and each one redraws through here.
        Without restoring the limits, every one of those would snap a zoomed-in
        view back to the whole image, which is exactly when the user is
        comparing settings on one region.
        背景キャッシュを無効化する呼び出しは 10 箇所（vmin/vmax・スケール・単位・
        各フィルター・連結・表示モード）あり、いずれもここを通って再描画する。
        軸範囲を復元しないと、そのすべてでズームが全体表示へ戻ってしまう。
        設定を変えながら 1 箇所を見比べている最中こそ、その操作が起きる。

        The view is restored only while the data extent is unchanged. Switching
        the tick unit (µm/nm) or the scale rescales the axes, so the previous
        limits would frame a different physical region; those reset to the full
        view instead.
        復元するのはデータ extent が変わらない間だけである。軸目盛単位（µm/nm）
        やスケールを変えると軸が張り替わり、以前の軸範囲は別の物理領域を指す。
        その場合は全体表示に戻す。
        """
        if self.current_image is None:
            return
        prev_key    = self._afm_extent_key
        prev_limits = None
        # Read the live axes, not `_overview_bg_drawn`: every caller clears that
        # flag *before* redrawing, so keying off it would always miss the view
        # that is still on screen.
        # 参照するのは実際の軸であって `_overview_bg_drawn` ではない。呼び出し側は
        # 再描画の前にこのフラグを落とすため、これを条件にすると画面に出ている
        # 表示範囲を必ず取り逃がす。
        if self._afm_home_limits is not None:
            prev_limits = (self._afm_ax.get_xlim(), self._afm_ax.get_ylim())

        self._rebuild_overview_artists()

        ax = self._afm_ax
        # Capture the full view before restoring, so the reset button and the
        # pan clamp always refer to the whole image.
        # 復元前に全体表示を控える。リセットとパンのクランプが常に画像全体を
        # 基準にするため。
        self._afm_home_limits = (ax.get_xlim(), ax.get_ylim())
        new_key = self._overview_extent_key()
        if prev_limits is not None and prev_key is not None and prev_key == new_key:
            ax.set_xlim(*prev_limits[0])
            ax.set_ylim(*prev_limits[1])
        self._afm_extent_key = new_key

        # ax.clear() replaces the axes callback registry, so reconnect after
        # every rebuild. Nothing accumulates: the old registry is discarded.
        # ax.clear() は軸のコールバック登録簿を作り直すため、再構築のたびに
        # 接続し直す。古い登録簿は破棄されるので多重登録にはならない。
        ax.callbacks.connect("xlim_changed", self._on_overview_lims_changed)
        ax.callbacks.connect("ylim_changed", self._on_overview_lims_changed)
        self._cull_overview_labels()

    def _overview_extent_key(self) -> Optional[tuple]:
        """
        Return a signature of the overview's current data extent.
        全体像の現在のデータ extent を表す識別子を返す。

        Notes
        -----
        Two background draws share a signature exactly when their axes span the
        same physical region, which is the condition for carrying a zoomed view
        across a rebuild.
        2 回の背景描画の識別子が一致するのは、軸が同じ物理領域を張るときだけで
        あり、それがズーム状態を再構築後に持ち越せる条件である。
        """
        if self.current_image is None:
            return None
        x_scale, y_scale, unit_label = self._get_extent_scale_xy_and_unit()
        h_px, w_px = self.current_image.calibrated_image.shape[:2]
        return (round(float(x_scale), 9), round(float(y_scale), 9),
                int(w_px), int(h_px), unit_label)

    def _on_overview_lims_changed(self, _ax=None) -> None:
        """
        Re-cull the overview labels after a pan, zoom, or reset.
        パン・ズーム・リセット後に全体像のラベルを絞り直す。
        """
        self._cull_overview_labels()

    def _cull_overview_labels(self) -> None:
        """
        Draw only the fiber numbers and boxes inside the visible limits.
        表示範囲内にあるファイバー番号と枠だけを描画対象にする。

        Notes
        -----
        The numbers dominate the overview redraw: on a 136-fiber scan they cost
        about 410 ms of a 940 ms redraw, and a redraw runs on every pan or zoom
        step. Restricting them to the visible region cuts a zoomed-in redraw to
        roughly 350 ms, and the display toggle removes them entirely.
        番号の描画が全体像の再描画コストの大半を占める。136 本の画像では 940 ms
        の再描画のうち約 410 ms がこれで、パン/ズームのたびに再描画が走る。表示
        範囲内に限定すると拡大時の再描画は約 350 ms まで下がり、表示トグルを
        OFF にすれば描画自体がなくなる。

        The selected fiber's highlight patch is not in these lists, so it stays
        visible in every case.
        選択ファイバーの黄色いハイライトはこれらのリストに含まれないため、
        どの場合でも表示され続ける。
        """
        show = self.show_overview_labels_var.get()
        ax = self._afm_ax
        x0, x1 = sorted(ax.get_xlim())
        y0, y1 = sorted(ax.get_ylim())
        for label in self._overview_labels:
            if not show:
                label.set_visible(False)
                continue
            lx, ly = label.get_position()
            label.set_visible(x0 <= lx <= x1 and y0 <= ly <= y1)
        for box in self._overview_boxes:
            if not show:
                box.set_visible(False)
                continue
            bx, by = box.get_xy()
            bw, bh = box.get_width(), box.get_height()
            # Keep a partially visible box: it is clipped to the axes anyway.
            # 一部だけ見える枠は残す（軸でクリップされるため）。
            box.set_visible(not (bx > x1 or bx + bw < x0 or by > y1 or by + bh < y0))

    def _on_overview_labels_toggle(self) -> None:
        """
        Apply the fiber number and box display toggle.
        ファイバー番号・枠の表示トグルを反映する。
        """
        self._cull_overview_labels()
        self._afm_canvas.draw_idle()

    def _fiber_view_bbox(self, fiber: Fiber) -> Optional[tuple]:
        """
        Return one fiber's bounding box in the overview's display units.
        全体像の表示単位に変換したファイバー外接矩形を返す。

        Returns
        -------
        tuple or None
            ``(x0, x1, y0, y1)`` with ``x0 < x1`` and ``y0 < y1``, or ``None``
            when no dataset is loaded.
            ``x0 < x1``、``y0 < y1`` の ``(x0, x1, y0, y1)``。データ未ロード時は
            ``None``。
        """
        if self.current_image is None:
            return None
        x_scale, y_scale, _unit = self._get_extent_scale_xy_and_unit()
        h_px, w_px = self.current_image.calibrated_image.shape[:2]
        x_spp = x_scale / w_px
        y_spp = y_scale / h_px
        # f.data is OpenCV stats (x, y, width, height, area); `h` is the X
        # extent and `w` the Y extent, as elsewhere in this file.
        x, y, h, w, _unused = fiber.data
        return (x * x_spp, (x + h) * x_spp, y * y_spp, (y + w) * y_spp)

    def _apply_overview_view(self, cx: float, cy: float,
                             half_x: float, half_y: float) -> None:
        """
        Center the overview on a point, clamped to the full image.
        全体像を指定点に中心合わせする（画像全体の範囲でクランプする）。

        Parameters
        ----------
        cx, cy
            Target center in display units.
            表示単位での中心座標。
        half_x, half_y
            Half-spans of the requested view in display units.
            表示単位での表示範囲の半幅・半高。

        Notes
        -----
        Clamping keeps the view inside the image so panning to a fiber near the
        border does not scroll empty space into the frame. The Y axis is
        inverted by ``imshow``'s extent, so its orientation is read from the
        current limits rather than assumed.
        クランプにより表示範囲が画像内に収まり、端のファイバーへ移動しても
        余白が入り込まない。Y 軸は ``imshow`` の extent により反転しているため、
        向きは仮定せず現在の軸範囲から読み取る。
        """
        if self._afm_home_limits is None:
            return
        ax = self._afm_ax
        hx0, hx1 = sorted(self._afm_home_limits[0])
        hy0, hy1 = sorted(self._afm_home_limits[1])
        half_x = min(half_x, (hx1 - hx0) / 2)
        half_y = min(half_y, (hy1 - hy0) / 2)
        cx = min(max(cx, hx0 + half_x), hx1 - half_x)
        cy = min(max(cy, hy0 + half_y), hy1 - half_y)

        y_inverted = ax.get_ylim()[0] > ax.get_ylim()[1]
        ax.set_xlim(cx - half_x, cx + half_x)
        if y_inverted:
            ax.set_ylim(cy + half_y, cy - half_y)
        else:
            ax.set_ylim(cy - half_y, cy + half_y)

    def _ensure_fiber_visible(self, fiber: Fiber) -> None:
        """
        Pan the overview to the selected fiber only when it is off-screen.
        選択ファイバーが表示範囲外のときだけ全体像をパンする。

        Notes
        -----
        Selecting a fiber replaces only the highlight patch, so while zoomed in
        a selection outside the view would change nothing on screen and read as
        a broken control. The zoom level is kept: this moves the view, it does
        not reframe it.
        ファイバー選択はハイライトを差し替えるだけのため、ズーム中に表示範囲外の
        ファイバーを選ぶと画面上は何も起きず、操作が壊れているように見える。
        拡大率は保つ。ここで行うのは表示位置の移動であって、拡大のやり直しでは
        ない。
        """
        bbox = self._fiber_view_bbox(fiber)
        if bbox is None or self._afm_home_limits is None:
            return
        fx0, fx1, fy0, fy1 = bbox
        ax = self._afm_ax
        vx0, vx1 = sorted(ax.get_xlim())
        vy0, vy1 = sorted(ax.get_ylim())
        if fx0 >= vx0 and fx1 <= vx1 and fy0 >= vy0 and fy1 <= vy1:
            return
        self._apply_overview_view(
            (fx0 + fx1) / 2, (fy0 + fy1) / 2,
            (vx1 - vx0) / 2, (vy1 - vy0) / 2,
        )

    def _zoom_to_selected(self) -> None:
        """
        Zoom the overview to the selected fiber.
        全体像を選択中のファイバーまで拡大する。

        Notes
        -----
        The requested span keeps the current view's aspect ratio, because the
        axes hold ``aspect="equal"``: framing a long thin fiber by its bounding
        box alone would shrink the axes box to that shape.
        要求する表示範囲は現在の表示アスペクト比を保つ。軸は ``aspect="equal"``
        のため、細長いファイバーを外接矩形そのままで囲むと軸の箱がその形まで
        つぶれてしまう。
        """
        fiber = self._current_fiber()
        if fiber is None or not self._overview_bg_drawn:
            messagebox.showinfo(_("情報"), _("ファイバーを選択してください。"))
            return
        bbox = self._fiber_view_bbox(fiber)
        if bbox is None or self._afm_home_limits is None:
            return
        fx0, fx1, fy0, fy1 = bbox
        ax = self._afm_ax
        vx0, vx1 = sorted(ax.get_xlim())
        vy0, vy1 = sorted(ax.get_ylim())
        view_ratio = (vx1 - vx0) / (vy1 - vy0) if vy1 > vy0 else 1.0

        # 30% margin so the fiber is not flush with the panel edge.
        # 端に密着しないよう 30% の余裕を持たせる。
        half_x = max((fx1 - fx0) / 2, 1e-9) * 1.3
        half_y = max((fy1 - fy0) / 2, 1e-9) * 1.3
        if half_x / half_y < view_ratio:
            half_x = half_y * view_ratio
        else:
            half_y = half_x / view_ratio
        self._apply_overview_view((fx0 + fx1) / 2, (fy0 + fy1) / 2, half_x, half_y)
        self._afm_canvas.draw_idle()

    def _reset_overview_view(self) -> None:
        """
        Reset the overview to the full image without redrawing the background.
        背景を再描画せずに全体像の表示範囲を画像全体へ戻す。
        """
        if self._afm_home_limits is None or not self._overview_bg_drawn:
            return
        self._afm_ax.set_xlim(*self._afm_home_limits[0])
        self._afm_ax.set_ylim(*self._afm_home_limits[1])
        self._afm_canvas.draw_idle()

    def _rebuild_overview_artists(self) -> None:
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

        isolated_only = self.isolated_only_var.get()
        if not self._filter_active and not isolated_only:
            self._draw_overview_background()
            return

        # Filter-active path (height filter, isolated-fiber filter, or both).
        # フィルター有効時の経路（高さ・孤立ファイバー・両方のいずれか）。
        filtered = self._display_fibers()
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
        # Plot title text stays fixed English per the UI-string policy.
        parts = []
        if self._filter_active:
            parts.append("filter: {count} segments".format(count=len(filtered)))
        if isolated_only:
            parts.append("isolated fibers only")
        self._draw_overview_background(
            labeled_fibers=list(enumerate(filtered)),
            title_suffix="  [{parts}]".format(parts=", ".join(parts)),
        )
        ax = self._afm_ax
        # Scatter the surviving skeleton pixels of each extracted segment. The
        # track arrays are bbox-local (xtrack = global_x - x), so add the bbox
        # origin before scaling to the physical tick-display unit.
        # 抽出された各区間の残存スケルトン画素を散布表示する。track 配列は BBox
        # ローカル座標（xtrack = グローバルx - x）なので、物理表示単位へスケール
        # する前に BBox 原点を加える。
        # The magenta scatter marks pixels the height filter extracted. The
        # isolated-fiber filter selects whole fibers instead of pixels, so on
        # its own it leaves the boxes and numbers without this overlay.
        # マゼンタ散布は高さフィルターが抽出した画素を示す。孤立ファイバー
        # フィルターは画素ではなくファイバー単位で選ぶため、単独使用時はこの
        # 重ね描きを行わず枠と番号のみとする。
        if not self._filter_active:
            return
        for f in filtered:
            x, y, _h, _w, _unused = f.data
            # The 0.5 places each marker at the pixel center: imshow spreads
            # w columns over the extent, so column c covers [c, c+1) * x_spp.
            # 0.5 はマーカーを画素中心へ置くための補正。imshow は w 列を extent
            # 全体へ広げるため、列 c は [c, c+1) * x_spp を占める。
            ax.scatter(
                (f.xtrack + x + 0.5) * x_spp,
                (f.ytrack + y + 0.5) * y_spp,
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

        # This mode draws no fiber numbers or boxes, so nothing is left to cull.
        # 本モードは番号・枠を描かないため、カリング対象は空にする。
        self._overview_labels = []
        self._overview_boxes  = []

        # Color each fiber the same way in both filtered and unfiltered states.
        # フィルター有無にかかわらず同じ方式で各ファイバーを配色する。
        fibers = self._display_fibers()
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
                # +0.5 centers each marker in its pixel (see the height overview).
                # +0.5 で各マーカーを画素中心に置く（高さ表示側と同じ補正）。
                ax.scatter(
                    (f.xtrack + x + 0.5) * x_spp,
                    (f.ytrack + y + 0.5) * y_spp,
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

        # Panning to the selection belongs to _on_fiber_select, not here: this
        # method also runs for vmin/vmax, filter, and mode changes, and moving
        # the view on those would yank a zoomed-in comparison off its region.
        # 選択位置へのパンは _on_fiber_select の仕事であり、ここではない。本
        # メソッドは vmin/vmax・フィルター・モード変更でも走るため、ここで視野を
        # 動かすと、拡大して見比べている領域から引き剥がしてしまう。
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
        self._populate_fiber_table(self._display_fibers())

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

    def _on_isolated_only_toggle(self) -> None:
        """
        Handle isolated-fiber-only checkbox changes.
        「孤立ファイバーのみ」チェックボックスの変更を処理する。

        This is a selection over the fibers already measured, so it needs no
        worker thread and no reanalysis: the table, overview, and export all
        read `_display_fibers`, and redrawing is enough. The one exception is
        switching off fiber connection, which does re-run the analysis.
        既に計測済みのファイバーに対する絞り込みなので、ワーカースレッドも再解析
        も不要。一覧・全体像・出力はいずれも `_display_fibers` を参照するため、
        再描画のみでよい。唯一の例外はファイバー連結を OFF にする場合で、この
        ときは解析が再実行される。
        """
        if self.isolated_only_var.get() and self.connect_enabled_var.get():
            # Mutually exclusive: connection joins fibers across crossings, so
            # an isolated fiber gets absorbed into the network and stops being
            # isolated. Measuring isolated fibers means not reconnecting first.
            # 排他。連結は交差を越えてファイバーをつなぐため、孤立ファイバーが
            # ネットワークへ取り込まれ孤立でなくなる。孤立ファイバーを計測する
            # とは、先に再結合しないということである。
            self.connect_enabled_var.set(False)
            self._log(_(
                "「孤立ファイバーのみ」を ON にしたため、"
                "「ファイバー連結」を OFF にしました。"
            ))
            # Re-analysis repopulates the table and overview through
            # _display_fibers, so this handler has nothing further to do.
            # 再解析が _display_fibers 経由で一覧と全体像を再構築するため、
            # 本ハンドラでこれ以上行う処理はない。
            self._on_connect_toggle()
            return

        if self.current_image is None:
            # Keep only the checkbox state until a dataset is selected.
            # データ未選択ならチェック状態だけ保持する（後で適用される）。
            return

        shown = self._display_fibers()
        # Row ids are positions in the displayed list, so a stale selection can
        # point past its end; clear it and let the table re-select.
        # 行 ID は表示リスト内の位置なので、古い選択は末尾を超えることがある。
        # いったん解除し、テーブル側で選び直させる。
        self._sel_idx = None
        self._populate_fiber_table(shown)
        self._overview_bg_drawn = False
        self._rebuild_overview_bg()
        self._afm_canvas.draw_idle()

        children = self.fiber_tree.get_children()
        if children:
            self.fiber_tree.selection_set(children[0])
            self.fiber_tree.focus(children[0])
            # Programmatic re-selection, so keep the current pan/zoom view.
            # プログラムによる選び直しのため、現在のパン/ズームを維持する。
            self._on_fiber_select(follow_view=False)

        if self.isolated_only_var.get():
            total = len(
                self._filtered_fibers if self._filter_active else self.current_fibers
            )
            self._log(_(
                "孤立ファイバーのみ表示: {count} / {total} 件"
                "（他のファイバーと交差・接触していないもの）"
            ).format(count=len(shown), total=total))
            # In a dense network almost every fiber reaches a crossing, so a
            # small count is the expected outcome, not a detection failure.
            # 密なネットワーク像ではほぼ全ファイバーが交差に達するため、残る本数
            # が少ないのは想定どおりの結果であり、検出失敗ではない。
            if total and len(shown) * 4 < total:
                self._log(_(
                    "注意: 交差に達したファイバーを全て除外したため、"
                    "残った本数が少なくなっています。"
                ))
        else:
            self._log(_("孤立ファイバーのみ表示を解除しました。"))

    def _reset_filter(self) -> None:
        """
        Clear the height filter and restore the full fiber table.
        高さフィルターを解除し、全ファイバーの一覧に戻す。
        """
        self._filter_active   = False
        self._filtered_fibers = []
        if self.current_image is not None:
            self._populate_fiber_table(self._display_fibers())
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
        if self.connect_enabled_var.get() and self.isolated_only_var.get():
            # Mutually exclusive; see _on_isolated_only_toggle for why.
            # 排他。理由は _on_isolated_only_toggle を参照。
            self.isolated_only_var.set(False)
            self._log(_(
                "「ファイバー連結」を ON にしたため、"
                "「孤立ファイバーのみ」を OFF にしました。"
            ))

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
        self._apply_auto_vrange(
            self.current_image.calibrated_image,
            mask=self.current_image.skeleton_image,
            log=True,
        )
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

        fibers = self._display_fibers()
        if not fibers:
            messagebox.showinfo(_("情報"), _("エクスポートするファイバーがありません。"))
            return

        name = self.current_image.name
        def _write_csv(path):
            # Columns and formatting are owned by lib.measure. A complete,
            # unfiltered export is byte-identical to `cli.py measure`; an
            # active height filter intentionally writes only retained portions,
            # and the isolated-fiber filter only fibers touching no other.
            # Either way the rows are renumbered from the exported list, so the
            # `index` column matches the fiber table.
            # 列と書式は lib.measure が管理する。全件・フィルターなしなら
            # `cli.py measure` とバイト単位で一致し、高さフィルター有効時は
            # 意図どおり残った部分だけを、孤立ファイバーフィルター有効時は
            # 他に接していないファイバーだけを書き出す。いずれの場合も出力
            # リストで採番し直すため、`index` 列は一覧テーブルと一致する。
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
            stem, image, fibers, stats = payload
            self.is_running = False
            self._hide_progress()
            self._set_ui_enabled(True)
            self._on_file_loaded(stem, image, fibers, stats)

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

        # Display-only margin around the tracked bounding box (see
        # DEFAULT_FIBER_PAD_PX). Setting it to 0 restores the tight crop.
        # 追跡した外接矩形の周囲に付ける表示専用の余白（DEFAULT_FIBER_PAD_PX
        # 参照）。0 にすると従来どおり外接矩形ぴったりの切り出しになる。
        self._fiber_pad:  int   = int(DEFAULT_FIBER_PAD_PX)

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
        self._fiber_pad_var       = tk.StringVar(value=self._app._fmt_num(self._fiber_pad))
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
        Build the enlarged-image settings rows (size, fonts, display, save).
        拡大像の設定行（サイズ・フォント・表示要素・画像保存ボタン）を構築する。
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
        # Margin around the tracked bounding box; see DEFAULT_FIBER_PAD_PX.
        # 追跡した外接矩形の周囲余白。DEFAULT_FIBER_PAD_PX 参照。
        ttk.Label(f_row1, text=_("余白") + " (px)").pack(side="left")
        self.ent_fiber_pad = ttk.Entry(f_row1, width=4, textvariable=self._fiber_pad_var)
        self.ent_fiber_pad.pack(side="left", padx=(2, 8))
        self._app._register_unconfirmed_entry(
            self.ent_fiber_pad,
            lambda: self._app._fmt_num(self._fiber_pad),
            self._commit_fiber_settings,
            registry=self._unconfirmed_entries,
        )
        ToolTip(self.ent_fiber_pad, _(
            "追跡範囲の周囲を何画素分まで表示に含めるかを指定します。\n"
            "端点で終わったのか交差で切れたのかを周囲ごと確認できます。\n"
            "表示専用の設定で、長さ・高さなどの計測値には影響しません。\n"
            "0 を指定すると追跡範囲ぴったりの切り出しに戻ります。"
        ))
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

        # -- Enlarged-image display settings, row 2: display elements and save --
        # Row 2 mirrors the profile column's checkbox row so each column's save
        # button exports exactly what that column currently shows.
        # 行2 はプロファイル側の表示要素行と同じ並びにする。各カラムの保存
        # ボタンが、そのカラムで見えているものをそのまま出力するようにする。
        f_row2 = ttk.Frame(parent)
        f_row2.pack(side="top", fill="x", padx=2, pady=(0, 2))
        ttk.Label(f_row2, text=_("表示：")).pack(side="left", padx=(2, 4))
        ttk.Checkbutton(
            f_row2, text=_("キンク"),
            variable=self._app.show_fiber_kink_var,
            command=self._redraw_fiber_image,
        ).pack(side="left", padx=(0, 4))
        ttk.Checkbutton(
            f_row2, text=_("中心線"),
            variable=self._app.show_fiber_track_var,
            command=self._redraw_fiber_image,
        ).pack(side="left", padx=(0, 4))
        chk_bbox = ttk.Checkbutton(
            f_row2, text=_("追跡範囲"),
            variable=self._app.show_fiber_bbox_var,
            command=self._redraw_fiber_image,
        )
        chk_bbox.pack(side="left", padx=(0, 4))
        ToolTip(chk_bbox, _(
            "計測対象のファイバーを囲む破線枠を表示します。\n"
            "余白に隣接ファイバーが写り込んでも、どれが計測対象かを取り違えずに済みます。"
        ))
        ttk.Button(f_row2, text=_("画像を保存"),
                   command=self._save_fiber_image).pack(side="left", padx=(0, 4))

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

        # This holder has no scrollbar, so the wheel is the only way to reach a
        # figure taller than the pane. Scope it to the enlarged-image side so it
        # does not fight the profile pane sharing this window.
        # このホルダにはスクロールバーが無いため、ペインより縦長の Figure に
        # 届く手段はホイールだけである。同一ウィンドウのプロファイル側と競合
        # しないよう、拡大像側に範囲を限定する。
        bind_mousewheel_scroll(self._fiber_holder, scope=parent)

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

        # Same reasoning as the enlarged-image holder: no scrollbar here either,
        # and the scope keeps the wheel on the profile side of the window.
        bind_mousewheel_scroll(self._prof_holder, scope=parent)

    # -- Commit callbacks local to the detail window ---------------------------

    def _commit_fiber_settings(self) -> bool:
        """
        Commit enlarged-image size and font settings together.
        拡大像のサイズとフォント設定をまとめて確定する。
        """
        try:
            new_w     = max(200, int(self._fiber_w_var.get().strip()))
            new_h     = max(150, int(self._fiber_h_var.get().strip()))
            new_pad   = int(self._fiber_pad_var.get().strip())
            new_lblfs = float(self._fiber_label_fs_var.get().strip())
            new_tkfs  = float(self._fiber_tick_fs_var.get().strip())
            new_cbfs  = float(self._fiber_cbar_fs_var.get().strip())
        except ValueError:
            messagebox.showerror(_("エラー"), _("拡大像の設定値が不正です。"))
            return False
        if not all(1 <= v <= 60 for v in (new_lblfs, new_tkfs, new_cbfs)):
            messagebox.showerror(_("エラー"), _("フォントサイズは 1〜60 の範囲で入力してください。"))
            return False
        if not 0 <= new_pad <= MAX_FIBER_PAD_PX:
            messagebox.showerror(
                _("エラー"),
                _("余白は 0〜{max} px の範囲で入力してください。").format(
                    max=MAX_FIBER_PAD_PX),
            )
            return False
        self._fiber_w        = new_w
        self._fiber_h        = new_h
        self._fiber_pad      = new_pad
        self._fiber_label_fs = new_lblfs
        self._fiber_tick_fs  = new_tkfs
        self._fiber_cbar_fs  = new_cbfs
        rewrite_entries((
            (self.ent_fiber_w,        self._fiber_w),
            (self.ent_fiber_h,        self._fiber_h),
            (self.ent_fiber_pad,      self._fiber_pad),
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
        units from the main app; figure size, local font sizes, and the margin
        around the tracked bounding box are adjusted here.
        本ウインドウはメインアプリの ``vmin``、``vmax``、``scale_um``、軸目盛単位
        を継承し、ここでは Figure サイズ・ローカルフォントサイズ・追跡範囲周囲の
        余白を調整する。
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

        # Re-crop the same calibrated image with a margin so the fiber ends are
        # not flush with the frame and the surroundings (a real end point vs. a
        # crossing with a neighbor) stay visible. This is display only: the
        # cached Fiber.fiber_image and the bounding-box-relative xtrack/ytrack
        # that lib/ measures from are left untouched, so overlays are shifted by
        # the crop origin instead.
        # 同じ補正画像を余白付きで切り直し、ファイバー端が枠に密着せず周囲の
        # 状況（本当の端点か、隣接ファイバーとの交差か）を確認できるようにする。
        # これは表示専用で、キャッシュ済みの Fiber.fiber_image と lib/ が計測に
        # 使う外接矩形基準の xtrack/ytrack は変更しない。そのぶん重ね描き側を
        # 切り出し原点だけずらす。
        bbox_x, bbox_y, bbox_w, bbox_h = (int(v) for v in fiber.data[:4])
        if app.current_image is not None and self._fiber_pad > 0:
            img, off_x, off_y = crop_with_margin(
                app.current_image.calibrated_image,
                (bbox_x, bbox_y, bbox_w, bbox_h),
                self._fiber_pad,
            )
        else:
            # No dataset loaded, or no margin requested: the cached crop is
            # already exactly the bounding box.
            # データ未ロード、または余白なし指定：キャッシュ済み切り出しが
            # そのまま外接矩形に一致する。
            img, off_x, off_y = fiber.fiber_image, 0, 0
        h_px_img, w_px_img = img.shape[:2]
        extent = [0, w_px_img * x_spp, h_px_img * y_spp, 0]

        im = ax.imshow(img, cmap="afmhot", vmin=vmin, vmax=vmax,
                       extent=extent, aspect="equal")

        # Outline the tracked bounding box so the measured fiber stays
        # identifiable once the margin lets neighboring fibers into the frame.
        # Same dashed white style as the overview boxes.
        # 余白によって隣接ファイバーが枠内に入っても計測対象を識別できるよう、
        # 追跡した外接矩形を明示する。全体像の枠と同じ白破線スタイル。
        if app.show_fiber_bbox_var.get():
            ax.add_patch(plt.Rectangle(
                (off_x * x_spp, off_y * y_spp), bbox_w * x_spp, bbox_h * y_spp,
                linewidth=0.8, linestyle="--", edgecolor="white",
                facecolor="none", alpha=0.6, zorder=3,
            ))

        # Add a colorbar with the same height as the heatmap.
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="4%", pad=0.05)
        self._fiber_cbar = self._fiber_fig.colorbar(im, cax=cax)
        # Control colorbar ticks and label with the same fs_cbar value.
        # カラーバーは目盛とラベルを同じ fs_cbar で制御（GUI01 / GUI02 流儀）。
        self._fiber_cbar.ax.tick_params(labelsize=fs_cbar)
        self._fiber_cbar.set_label("Height (nm)", fontsize=fs_cbar)

        # Fiber track line. The 0.5 puts each track point at its pixel center
        # so the line sits on the ridge instead of half a pixel up and left.
        # 0.5 は各追跡点を画素中心へ置く補正。これを入れないと線が稜線から
        # 左上へ半画素ずれる。
        if app.show_fiber_track_var.get() and len(fiber.xtrack) > 0:
            ax.plot((fiber.xtrack + off_x + 0.5) * x_spp,
                    (fiber.ytrack + off_y + 0.5) * y_spp,
                    color="lime", lw=1.0, alpha=0.75, zorder=4)

        # Kink points, centered in their pixels like the track line above so
        # the markers stay on it.
        # キンク点。上のトラック線と同じ画素中心補正を掛け、線上に載るようにする。
        if app.show_fiber_kink_var.get() and len(fiber.kink_indices) > 0:
            kx = (fiber.xtrack[fiber.kink_indices] + off_x + 0.5) * x_spp
            ky = (fiber.ytrack[fiber.kink_indices] + off_y + 0.5) * y_spp
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
