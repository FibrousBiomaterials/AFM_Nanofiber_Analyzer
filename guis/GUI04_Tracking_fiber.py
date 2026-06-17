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
from lib.blosc2_io import bundle_has_keys, BUNDLE_EXT
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
# The key list is owned by lib.measure so the CLI and this GUI stay in sync.
# キー一覧は lib.measure が管理し、CLI と本 GUI の整合を保つ。
REQUIRED_BUNDLE_KEYS = TRACKING_BUNDLE_KEYS

DEFAULT_HEIGHT_YLIM:           float = 20.0
# The full image size is entered in micrometers and converted to nanometers internally.
# 画像全体のサイズはユーザー入力では µm 単位、内部計算では nm 単位で扱う。
# Match GUI01: entry values stay in micrometers, while tick labels can switch units.
# GUI01 と仕様を揃え、入力欄の単位は µm 固定で、軸目盛単位の表示だけ µm/nm を切り替える。
DEFAULT_IMAGE_SIZE_UM:         float = 2.0               # 画像全体のサイズ (µm)
# Fiber analysis is always parallelized with ThreadPoolExecutor.
# ファイバー解析は常に ThreadPoolExecutor で並列化する。


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

        # -- Profile element checkboxes --
        # ── プロファイル描画要素チェックボックス ──
        self.show_kink_var   = tk.BooleanVar(value=True)
        self.show_medmax_var = tk.BooleanVar(value=True)

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
        self.ent_scale_um = ttk.Entry(bar, width=7, textvariable=self.scale_um_var)
        self.ent_scale_um.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_scale_um,
            lambda: self._fmt_num(self.scale_um),
            self._commit_scale_um,
        )
        ToolTip(
            self.ent_scale_um,
            _("AFM 画像の一辺の実寸") + " (µm)。\n"
            + _("ファイバー解析の長さ・座標換算に使われる重要な値。") + "\n"
            + _("変更すると現在のファイルが再解析される。"),
        )
        # Optional Y (height) size for rectangular scans. "X" is the left
        # entry, "Y" the right; an empty Y means a square scan (Y = X).
        # 矩形スキャン用の任意の Y（高さ）サイズ。左が X、右が Y で、Y 空欄は
        # 正方スキャン（Y = X）を意味する。
        ttk.Label(bar, text="×").pack(side="left", padx=(0, 1))
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
            afm_header1, text=_("個別表示を開く"),
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

        # Use committed internal scale, not unconfirmed Entry text.
        # スケールは内部状態（確定済み値）を参照する。
            # While the Entry is unconfirmed, the committed value remains active until Enter.
        # 入力欄が未確定（青色）の間は古い内部値が使われ、Enter 確定後に反映される。
        scale_um = self.scale_um
        # measure_bundle takes micrometers. Derive the worker value from
        # _get_scale_nm() to keep its non-positive-input fallback semantics.
        # measure_bundle は µm 単位を受け取る。非正値入力時のフォールバック挙動を
        # 維持するため、ワーカーへ渡す値は _get_scale_nm() から導出する。
        worker_scale_um = self._get_scale_nm() / 1000.0
        # None lets measure_bundle reuse the X scale for Y (square scan).
        # None なら measure_bundle が Y に X スケールを流用する（正方スキャン）。
        worker_scale_y_um = self.scale_y_um

        self._log(
            (_("読み込み中: {name}  スケール={scale}") + " µm ...").format(
                name=os.path.basename(stem), scale=self._fmt_num(scale_um)
            )
        )
        self._set_ui_enabled(False)
        self._show_progress(_("ファイル読み込み中..."), 0)

        def _worker(stem=stem, scale_um=worker_scale_um,
                    scale_y_um=worker_scale_y_um):
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

        # -- Auto-update vmin/vmax only when auto mode is enabled --
        if self.auto_vrange_var.get() and image.calibrated_image is not None:
            self._apply_auto_vrange(image.calibrated_image, log=True)

        self._log(_("読み込み完了: {name}  ファイバー数: {count}").format(
            name=os.path.basename(stem), count=len(fibers)
        ))
        self._populate_fiber_table(fibers)
        self._draw_overview_background()

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

        Without a filter, every fiber is shown with a white box and original
        index. With the height filter on, the extracted skeleton pixels are
        scattered in magenta over the AFM image, matching the pixel-level
        ``specific_height_fibers`` extraction: a fiber contributes only the
        sub-segments whose calibrated height lies in the selected range.
        フィルターなしでは全ファイバーを白枠と元番号で表示する。高さフィルター
        ON では、抽出されたスケルトン画素をマゼンタで AFM 像上に散布表示し、
        画素単位の ``specific_height_fibers`` 抽出（補正高さが範囲内の区間のみ
        残る）に一致させる。
        """
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

        self._draw_overview_background(
            labeled_fibers=[],
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

    def _show_progress(self, label: str = "", value: int = 0) -> None:
        """
        Keep the progress-bar API as a no-op because progress is shown in the log.
        進捗はログに表示するため、プログレスバー API は no-op として残す。
        """
        pass

    def _hide_progress(self) -> None:
        """
        Keep the progress-hide API as a no-op because progress is shown in the log.
        進捗はログに表示するため、プログレス非表示 API は no-op として残す。
        """
        pass

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

        def _worker():
            """
            Extract specific-height fiber segments off the Tk main thread.
            Tk メインスレッド外で特定高さのファイバー区間を画素単位で抽出する。
            """
            try:
                # Pixel-level extraction: keep only skeleton pixels whose
                # calibrated height is within [lo, hi] and rebuild fibers from
                # them. Delegates to FiberTrackingImage.specific_height_fibers
                # so the GUI matches the reference height-filter behavior, which
                # isolates the portions at a target height (e.g. dents) rather
                # than selecting whole fibers by a summary statistic.
                # 画素単位抽出。補正高さが [lo, hi] のスケルトン画素のみを残して
                # 再構築する。specific_height_fibers に委譲し、要約統計で
                # ファイバーを丸ごと選ぶのではなく特定高さの箇所（凹みなど）を
                # 切り出す、本来の高さフィルター仕様に一致させる。
                result = image.specific_height_fibers(lo, hi)
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
            self._draw_overview_background()
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
            # Columns and formatting are owned by lib.measure, so this export
            # stays byte-identical to the `cli.py measure` output.
            # 列と書式は lib.measure が管理しており、このエクスポートは
            # `cli.py measure` の出力とバイト単位で一致する。
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
            pct = int(done / total * 100) if total > 0 else 0
            self._show_progress(
                _("ファイバー解析中... {done}/{total} ({pct}%)").format(
                    done=done, total=total, pct=pct
                ),
                pct,
            )
            # Also show a compact text progress bar in the log.
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            replace_log_tail(self.log_text, f"  [{bar}] {done}/{total} ({pct}%)")

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
        # Row 1: profile width, height, label/tick/legend fonts, and Y-axis maximum.
        # 行1: プロファイル表示設定: 幅 / 高さ / 軸ラベルfs / 軸目盛fs / 凡例fs / y軸最大値。
        # Font-size and Y-axis entries sit to the right of the height entry after the layout change.
        # 各フォントサイズ入力欄（軸ラベル/軸目盛/凡例）および y軸最大値(nm) は高さ入力欄の右側に並べる（仕様変更）。
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
        # Place Y-axis maximum to the right of legend font size after the layout change.
        # y軸最大値(nm) は凡例 fs の右に配置（仕様変更）。
        # Synchronize _ylim and _ylim_var with _fmt_num to avoid a false
        # unconfirmed state during initial drawing.
        # 内部状態 self._ylim と表示用 StringVar self._ylim_var を _fmt_num で同期させて、
        # 初期描画時に「未確定」状態（青色）になるバグを回避する。
        ttk.Label(p_row1, text=_("y軸最大値") + " (nm)").pack(side="left", padx=(0, 2))
        self.ent_ylim = ttk.Entry(p_row1, width=5, textvariable=self._ylim_var)
        self.ent_ylim.pack(side="left", padx=(0, 8))
        self._app._register_unconfirmed_entry(
            self.ent_ylim,
            lambda: self._app._fmt_num(self._ylim),
            self._commit_ylim,
            registry=self._unconfirmed_entries,
        )

        # Row 2: tick direction, grid mode, legend location, and displayed elements.
        # 行2: 目盛りの向き / グリッド表示 / 表示要素。
        # Row 2 collects profile display controls; image saving stays in row 1.
        # 行2にはプロファイル表示操作をまとめ、画像保存は行1に残す。
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
        # Display-element label and checkboxes.
        # 表示要素ラベル＋チェックボックス。
        ttk.Label(p_row2, text=_("表示：")).pack(side="left", padx=(2, 4))
        ttk.Checkbutton(
            p_row2, text=_("キンク"),
            variable=self._app.show_kink_var,
            command=self._redraw_profile,
        ).pack(side="left", padx=(0, 4))
        ttk.Checkbutton(
            p_row2, text=_("中央値/最大値"),
            variable=self._app.show_medmax_var,
            command=self._redraw_profile,
        ).pack(side="left", padx=(0, 4))

        # Row 3: Save Image button, separated from row 2.
        # 行3: 画像保存ボタン（行2から分離）。
        p_row3 = ttk.Frame(parent)
        p_row3.pack(side="top", fill="x", padx=2, pady=(0, 2))
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
