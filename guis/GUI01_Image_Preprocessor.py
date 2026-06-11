# -*- coding: utf-8 -*-
"""
GUI plugin for preprocessing AFM nanofiber images.
AFM ナノファイバー画像の前処理を行う GUI プラグイン。

The plugin runs background calibration, segmentation, skeletonization, and
kink-related feature extraction, then saves the analysis outputs as a single
Blosc2 TreeStore bundle per input file.
バックグラウンド補正、二値化、細線化、キンク関連特徴抽出を実行し、
入力ファイルごとに解析結果を 1 つの Blosc2 TreeStore バンドルへ保存する。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain plain string literals; do not wrap them with gettext _().
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Image Preprocessor",
    "description": (
        "AFMで撮影したナノファイバー画像に対して、以下の前処理を順に実行します。\n"
        "・バックグラウンド補正（lib/bg_calibrator_shimadzu.py）\n"
        "・二値化（lib/segmenter.py）\n"
        "・細線化（lib/skeletonizer.py）\n"
        "・EP（端点）、BP（分岐点）、DP（分解点）、KP（キンク点）、KA（キンク角）の抽出（lib/kink_detector.py）\n"
        "処理結果は1解析ファイルにつき1つの .b2z バンドル（blosc2 TreeStore）に統合保存されます。\n"
        "解析パラメータは同名の _param.json としても併せて出力されます。\n"
        "解析は別スレッド、UI更新はQueue経由です。\n"
        "\n"
        "Image Preprocessor では背景補正方式を 4 種類から選べます:\n"
        "  - 'inpaint'     : 勾配リッジ検出 + NS inpaint\n"
        "  - 'tophat'      : 形態学的 opening (マスク不要、高速、一様性◎)\n"
        "  - 'spline1d'    : 行/列ごとの 1D B-スプライン補間 (端の線形外挿つき)。\n"
        "  - 'spline2d'    : 大局的に滑らかな背景向けの 2D B-スプラインフィット\n"
    )
}

# ===== Standard library =====
import os
import sys
import json
import time
import traceback
import threading
import queue
import subprocess
from dataclasses import dataclass, asdict, fields
from typing import Optional, Dict, Any, List, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")   # Embed matplotlib figures in tkinter windows.
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ===== Project libraries =====
# These modules implement the AFM image-processing pipeline used by this GUI.
# これらのモジュールが GUI から呼び出す AFM 画像処理本体である。
from lib.bg_calibrator_shimadzu import BG_Calibrator_shimadzu
from lib.processed_image import ProcessedImage
from lib.kink_detector import KinkDetector
from lib.segmenter import Segmenter
from lib.skeletonizer import Skeletonizer
from lib.blosc2_io import save_bundle, load_bundle, bundle_has_keys, BUNDLE_EXT
from lib.afm_io import load_afm_text
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, ToolTip, setup_matplotlib_style,
    save_figure_with_dialog, PLOT_FS_DEFAULTS, setup_ttk_theme,
    save_text_widget_log,
    create_scrolled_text, create_scrolled_treeview, drain_ui_queue,
    UnconfirmedEntryMixin, LogMixin,
)

# ===== Internal status keys; do not translate these identifiers. =====
# Keep internal state in fixed English keys and translate only for display.
# 内部状態は固定の英語キーで管理し、表示時のみ _() を通して翻訳する。
STATUS_PENDING  = "pending"    # Not analyzed.
STATUS_RUNNING  = "running"    # Analysis in progress.
STATUS_ANALYZED = "analyzed"   # Analysis complete.


def status_label(status: str) -> str:
    """
    Convert an internal status key to a translated display label.
    内部ステータスキーを翻訳済みの表示ラベルへ変換する。

    Parameters
    ----------
    status
        Internal status key stored in `FileItem.status`.
        `FileItem.status` に保存される内部ステータスキー。

    Returns
    -------
    str
        Translated label for the Treeview, or the input value if unknown.
        Treeview 用の翻訳済みラベル。不明な値は入力値をそのまま返す。
    """
    return {
        STATUS_PENDING:  _("未解析"),
        STATUS_RUNNING:  _("解析中"),
        STATUS_ANALYZED: _("解析済み"),
    }.get(status, status)


# ===== Settings =====
@dataclass
class ProcParams:
    """
    Processing parameters shared by the preprocessing pipeline.
    前処理パイプラインで共有する解析パラメータ。

    Attributes
    ----------
    bg_method
        Background-estimation method.
        背景推定方式。
    tophat_se_size
        Diameter of the structuring element in pixels for `tophat`.
        `tophat` 用の構造要素直径 (px)。
    spline1d_axis
        Direction used by the one-dimensional spline background model.
        1D スプライン背景モデルで補間する方向。
    spline1d_degree
        Spline degree used by `spline1d`.
        `spline1d` で用いるスプライン次数。
    spline2d_degree
        Spline degree used by `spline2d`.
        `spline2d` で用いるスプライン次数。
    spline2d_subsample
        Pixel subsampling factor for the `spline2d` fit.
        `spline2d` フィット用の画素サブサンプル係数。
    spline2d_smoothing
        Smoothing factor for `spline2d`; kept out of the GUI by default.
        `spline2d` の平滑化係数。既定では GUI に露出しない。
    threshold_factor
        Sigma multiplier used to define the background range.
        背景範囲を定める sigma 係数。
    fiber_detect_factor
        Threshold for excluding abrupt height changes as fibers.
        急峻な高さ変化を繊維として除外するしきい値。
    noise_detect_factor
        Threshold for distinguishing structural changes from noise.
        構造変化とノイズを区別するしきい値。
    savgol_window
        Window length for the Savitzky-Golay smoothing filter.
        Savitzky-Golay 平滑化フィルタの窓幅。
    savgol_polyorder
        Polynomial order for the Savitzky-Golay filter.
        Savitzky-Golay フィルタの多項式次数。
    apply_median
        Whether to apply a final median filter.
        最後に中央値フィルタを適用するか。
    mask_dilation
        Pixel radius used to dilate the fiber mask.
        繊維マスクを膨張させる画素数。
    min_mask_component_area
        Minimum connected-component area retained in the mask.
        マスク内に保持する連結成分の最小面積。
    wsize_localbin
        Window size for local thresholding.
        局所しきい値計算のウィンドウサイズ。
    global_threshold
        Global binarization threshold.
        全体一律の二値化しきい値。
    area_min
        Minimum component area retained after binarization.
        二値化後に保持する連結成分の最小面積。
    area_min_connecting
        Area threshold used by the disconnected-component cleanup.
        つながり除去で用いる面積しきい値。
    apply_no_connecting
        Whether to run disconnected-component cleanup.
        つながり除去を実行するか。
    h_length
        Minimum line length for Hough-based line detection.
        Hough 変換で線分とみなす最小長。
    h_sratio
        Line-likeness threshold.
        線らしさを示す s_ratio のしきい値。
    low_threshold
        Height threshold in nanometers for removing low components.
        低い成分を除去する高さしきい値 (nm)。
    bp_height
        Height threshold for branch-point filtering.
        分岐点を判定する高さしきい値。
    branch_length
        Maximum branch length traced during skeleton cleanup.
        スケルトン整理時に枝として追跡する最大長。
    min_area
        Minimum area retained after skeletonization.
        細線化後に保持する最小面積。
    kinkangle_deg
        Bend-angle threshold in degrees for kink detection.
        キンク検出に用いる折れ角しきい値 (度)。

    Notes
    -----
    Physical image size is intentionally excluded. It is display metadata, not
    an analysis parameter, and folders may contain images with different scan
    sizes.
    画像の実寸は意図的に除外している。実寸は解析結果に影響しない表示用
    メタ情報であり、同一フォルダ内に異なるスキャンサイズの画像が混在する
    可能性があるため。
    """

    # BG_Calibrator_shimadzu parameters.
    bg_method: str = "inpaint"             # Background method: inpaint, tophat, spline1d, or spline2d.
    tophat_se_size: int = 25               # Structuring-element diameter for tophat, in pixels.
    spline1d_axis: str = "x"               # Axis used for the one-dimensional spline interpolation.
    spline1d_degree: int = 2               # Spline degree for spline1d; practical range is 1 to 3.
    spline2d_degree: int = 2               # Spline degree for spline2d; practical range is 1 to 3.
    spline2d_subsample: int = 4            # Pixel subsampling factor per axis for spline2d.
    spline2d_smoothing: Optional[float] = None  # Hidden advanced spline2d smoothing value; None keeps SciPy's default and avoids unstable near-interpolation fits.
    threshold_factor: float = 2.0          # Sigma multiplier for the background range.
    fiber_detect_factor: float = 10.0      # Threshold for treating abrupt height changes as fibers.
    noise_detect_factor: float = 10.0      # Threshold for separating structural change from noise.
    savgol_window: int = 31                # Savitzky-Golay smoothing window for inpaint, tophat, and spline1d.
    savgol_polyorder: int = 1              # Savitzky-Golay polynomial order for inpaint, tophat, and spline1d.
    apply_median: bool = False             # Whether to apply the final median filter.
    mask_dilation: int = 3                 # Fiber-mask dilation radius in pixels; 0 disables dilation.
    min_mask_component_area: int = 10      # Minimum mask component area retained before dilation; 1 disables filtering.

    # Segmenter parameters.
    wsize_localbin: int = 17               # Window size for local thresholding.
    global_threshold: float = 0.3         # Global binarization threshold.
    area_min: int = 100                    # Minimum component area retained, in px^2.
    area_min_connecting: int = 3           # Area threshold for disconnected-component cleanup.
    apply_no_connecting: bool = False      # Whether to run disconnected-component cleanup.
    h_length: int = 20                     # Minimum Hough line length.
    h_sratio: float = 0.5                  # Line-likeness threshold.
    low_threshold: float = 1.8             # Low-height removal threshold, in nanometers.

    # Skeletonizer parameters.
    bp_height: float = 10.0               # Height threshold for branch-point filtering.
    branch_length: int = 12               # Maximum branch length traced during skeleton cleanup, in pixels.
    min_area: int = 10                    # Minimum area retained after skeletonization.

    # Kink-detection parameters.
    kinkangle_deg: float = 150.0          # Bends at or below this angle are detected as kinks.

# Settings filename stored next to this GUI script.
SETTINGS_FILENAME = "afmpp_settings.json"

# Key used inside the settings file for UI state that is *not* an analysis parameter.
# Analysis parameters live at the top level (see load_or_create_startup_params);
# UI-only state is namespaced under this key so it never participates in the
# ProcParams missing/obsolete-key reconciliation.
# 解析パラメータはトップレベルに置かれる。UI のみの状態はこのキー配下に
# 名前空間を分けて保存し、ProcParams の欠損/不要キー判定に巻き込まれないようにする。
UI_SETTINGS_KEY = "_ui"

# Default UI state used when the settings file is absent or lacks the _ui section.
# 設定ファイルが無い、または _ui セクションが無い場合に使う UI 状態の既定値。
UI_DEFAULTS = {
    # When True, the background-corrected analysis also stores the raw original
    # AFM height image inside the .b2z bundle under the "original" key.
    # True のとき、解析時に元の AFM 高さ画像を "original" キーとして .b2z に同梱する。
    "save_original": False,
}


def load_ui_settings() -> Dict[str, Any]:
    """
    Load UI-only settings from the settings file, falling back to defaults.
    設定ファイルから UI 専用設定を読み込み、無ければ既定値にフォールバックする。

    Notes
    -----
    Read failures and missing sections are non-fatal: the function returns a
    copy of `UI_DEFAULTS` so a corrupt or partial file never blocks startup.
    読み込み失敗やセクション欠損は致命的ではなく、`UI_DEFAULTS` のコピーを返す。
    """
    ui = dict(UI_DEFAULTS)
    path = _settings_path()
    if not os.path.isfile(path):
        return ui
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        section = d.get(UI_SETTINGS_KEY, {})
        if isinstance(section, dict):
            # Only adopt known keys; unknown keys are ignored for forward safety.
            for k in UI_DEFAULTS:
                if k in section:
                    ui[k] = section[k]
    except Exception:
        # Any failure falls back to defaults; the analysis-parameter loader
        # reports its own errors separately.
        pass
    return ui


def save_ui_settings(ui: Dict[str, Any]) -> None:
    """
    Persist UI-only settings into the `_ui` section without touching parameters.
    パラメータ部に触れず、UI 専用設定を `_ui` セクションへ保存する。

    Notes
    -----
    The existing top-level ProcParams keys are preserved by reading the file
    first and rewriting only the `_ui` section.
    既存のトップレベル ProcParams キーは、ファイルを読んでから `_ui` セクション
    のみ書き換えることで保持する。
    """
    path = _settings_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                d = {}
        else:
            d = {}
        d[UI_SETTINGS_KEY] = {k: ui.get(k, UI_DEFAULTS[k]) for k in UI_DEFAULTS}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        # Saving UI state is best-effort and must not interrupt the workflow.
        pass


def _settings_path() -> str:
    """
    Return the absolute path to the startup settings file.
    起動時設定ファイルの絶対パスを返す。
    """
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, SETTINGS_FILENAME)


def load_or_create_startup_params() -> Tuple[ProcParams, List[str]]:
    """
    Load startup settings, creating defaults when the file is missing.
    起動時設定を読み込み、ファイルが無い場合は既定値で作成する。

    Returns
    -------
    tuple
        Loaded parameters and log messages to show after the GUI is built.
        読み込んだパラメータと、GUI 構築後に表示するログメッセージ。

    Notes
    -----
    Corrupted settings files are not overwritten or deleted automatically; the
    application falls back to `ProcParams` defaults and reports the error.
    破損した設定ファイルは自動で上書き・削除せず、`ProcParams` の既定値に
    フォールバックしてエラーを報告する。
    """
    logs: List[str] = []
    default_params = ProcParams()
    path = _settings_path()

    if not os.path.isfile(path):
        # Create a missing settings file from defaults.
        try:
            with open(path, "w", encoding="utf-8") as f:
                # Preserve Japanese strings in JSON for maintainers editing settings by hand.
                # 手編集する日本語保守者向けに、日本語文字列を JSON 内でそのまま保存する。
                json.dump(asdict(default_params), f, ensure_ascii=False, indent=2)
            logs.append(_("起動時設定ファイルを作成しました: %s") % path)
        except Exception as e:
            logs.append(_("起動時設定ファイルの作成に失敗しました（デフォルトで起動します）: %s") % e)
        return default_params, logs

    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)

        # Fill missing keys from ProcParams defaults so old settings files keep working
        # when new fields are added.
        # 旧設定ファイルに新規フィールドが無いだけで全設定が失われないよう、
        # 欠損キーは ProcParams の既定値で補完する。
        defaults_dict = asdict(default_params)
        missing = [k for k in defaults_dict if k not in d]
        if missing:
            logs.append(_("起動時設定ファイルに不足キーがありました（デフォルトで補完）: %s")
                        % ", ".join(missing))
            merged = {k: d.get(k, defaults_dict[k]) for k in defaults_dict}
        else:
            merged = {k: d[k] for k in defaults_dict}

        # Ignore keys outside the current ProcParams schema, but log them for users.
        # 現在の ProcParams スキーマに含まれないキーは無視しつつ、ユーザーへの
        # 案内としてログに残す。
        obsolete = [k for k in d if k not in defaults_dict]
        if obsolete:
            logs.append(_("起動時設定ファイルに使われていないキーがありました（無視）: %s")
                        % ", ".join(obsolete))

        # Reuse the same key layout as the per-analysis parameter JSON.
        return ProcParams(**merged), logs

    except Exception as e:
        logs.append(_("起動時設定ファイルの読み込みに失敗しました（デフォルトにフォールバック）: %s") % e)
        return default_params, logs


@dataclass
class FileItem:
    """
    Track one input text file and its analysis state.
    1 つの入力テキストファイルと解析状態を保持する。

    Attributes
    ----------
    txt_path
        Absolute path to the input `.txt` file.
        入力 `.txt` ファイルの絶対パス。
    status
        Internal analysis status key.
        解析状態を表す内部キー。
    proc_time_s
        Processing time formatted for display.
        表示用に整形した処理時間。
    missing_reason
        Reason why an expected analysis output is missing.
        期待される解析出力が欠損している理由。
    """

    txt_path: str
    status: str = STATUS_PENDING
    proc_time_s: str = ""
    missing_reason: str = ""

    @property
    def stem(self) -> str:
        """
        Return the full path without the extension.
        拡張子を除いたフルパスを返す。
        """
        return os.path.splitext(self.txt_path)[0]

    @property
    def basename_stem(self) -> str:
        """
        Return the filename without directory or extension.
        フォルダと拡張子を除いたファイル名を返す。
        """
        return os.path.splitext(os.path.basename(self.txt_path))[0]


# Bundle keys required to treat a file as analyzed.
# One .b2z bundle is written per analyzed file; all keys below must exist.
# 1 解析ファイルにつき 1 つの .b2z バンドルが生成され、下記キーが揃っていれば解析済みと判定する。
#   /calibrated   : Background-corrected image.
#   /binarized    : Binarized image.
#   /skeletonized : Skeletonized image.
#   /bp           : Branch-point mask.
#   /ep           : End-point mask.
#   /kp           : Kink coordinates, shape (2, N), [0]=x, [1]=y.
#   /dp           : Decomposed points used for kink detection, shape (2, N).
#   /ka           : Kink angles in radians, shape (N,).
REQUIRED_BUNDLE_KEYS = [
    "calibrated", "binarized", "skeletonized",
    "bp", "ep",
    "kp", "dp", "ka",
]

# Optional keys must not affect the analyzed/not-analyzed decision for backward compatibility.
# 後方互換のため、任意キーは解析済み判定に使わない。
OPTIONAL_BUNDLE_KEYS = ["original"]


def bundle_path_for(stem: str) -> str:
    """
    Return the bundle path for an extensionless input path.
    拡張子を除いた入力パスに対応するバンドルパスを返す。
    """
    return stem + BUNDLE_EXT


def existing_min_set(stem: str) -> Tuple[bool, List[str]]:
    """
    Check whether all required bundle keys exist for an input stem.
    入力 stem に対応するバンドルへ必須キーが揃っているか確認する。
    """
    return bundle_has_keys(bundle_path_for(stem), REQUIRED_BUNDLE_KEYS)


def open_folder_in_os(path: str) -> None:
    """
    Open a folder with the platform's file manager.
    OS 標準のファイルマネージャーでフォルダを開く。
    """
    if not path:
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass   # Folder display is optional; ignore file-manager failures.


# ===== Main GUI =====
class App(tk.Tk, UnconfirmedEntryMixin, LogMixin):
    """
    Main window for batch preprocessing AFM nanofiber images.
    AFM ナノファイバー画像を一括前処理するメインウィンドウ。

    Attributes
    ----------
    folder_path
        Selected input folder that also receives output bundles.
        入力フォルダであり、出力バンドルの保存先でもあるフォルダ。
    items
        Files shown in the batch-processing table.
        一括処理テーブルに表示するファイル一覧。
    params_active
        Parameter snapshot used by the running analysis.
        実行中の解析で使用するパラメータのスナップショット。
    params_pending
        Editable parameters staged until the next analysis starts.
        次回解析開始まで保留される編集可能なパラメータ。
    """

    def __init__(self) -> None:
        """
        Initialize application state, widgets, preview canvas, and queue polling.
        アプリ状態、ウィジェット、プレビューキャンバス、キュー監視を初期化する。
        """
        super().__init__()
        setup_matplotlib_style(font_size=12)
        self.title(PLUGIN_INFO["name"])
        apply_window_size(self, 1450, 850, min_w=1100, min_h=700)

        self._clam_bg = setup_ttk_theme(self)

        # ===== Application state =====
        self.folder_path: str = ""
        self.items: List[FileItem] = []
        self.item_by_iid: Dict[str, FileItem] = {}
        self.iid_by_path: Dict[str, str] = {}

        # Load startup settings before building widgets so controls reflect persisted values.
        p, startup_logs = load_or_create_startup_params()

        self.params_active = p
        self.params_pending = ProcParams(**asdict(p))
        # Settings edits are copied to params_active only when the next analysis starts.

        # ===== UI control flags =====
        self.is_running = False
        self.stop_event = threading.Event()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        # Worker threads must not touch tkinter widgets directly; use this queue.

        # ===== Progress tracking =====
        self._total_tasks = 0
        self._done_tasks = 0

        # Default to preserving existing analysis outputs unless the user opts in to overwrite.
        # 既存解析結果は既定で保持し、ユーザーが明示した場合のみ上書きする。
        self.overwrite_existing_var = tk.BooleanVar(value=False)

        # When checked, the raw original AFM height image is bundled into the .b2z
        # under the "original" key. Persisted in the settings file's _ui section so
        # the choice survives restarts; defaults to OFF on first launch.
        # チェック時、元の AFM 高さ画像を "original" キーとして .b2z に同梱する。
        # 設定ファイルの _ui セクションに保存して再起動後も維持する。初回起動は OFF。
        self._ui_settings = load_ui_settings()
        self.save_original_var = tk.BooleanVar(value=bool(self._ui_settings.get("save_original", False)))
        # Worker-thread snapshot of save_original; set at each run start (_start_processing).
        # ワーカー用のスナップショット。解析開始ごとに _start_processing で設定する。
        self._save_original_active: bool = bool(self.save_original_var.get())

        # ===== Preview display settings =====
        # Entry text is staged separately from committed internal values.
        self.vmin: float = -0.5
        self.vmax: float = 5.0
        self.vmin_var = tk.StringVar(value=self._fmt_num(self.vmin))
        self.vmax_var = tk.StringVar(value=self._fmt_num(self.vmax))

        # Physical image size is display metadata, not an analysis parameter.
        self.scale_um: float = 2.0
        self.scale_um_var = tk.StringVar(value=self._fmt_num(self.scale_um))

        # Scale display is applied immediately to all preview panels.
        self.show_scale_var = tk.BooleanVar(value=False)

        # The input value stays in micrometers; only the display unit changes.
        self.unit_var = tk.StringVar(value="µm")

        # Font sizes remain editable even when the related display element is hidden.
        self.fs_title:  int = PLOT_FS_DEFAULTS["title_fs"]
        self.fs_legend: int = PLOT_FS_DEFAULTS["legend_fs"]
        self.fs_label:  int = PLOT_FS_DEFAULTS["label_fs"]
        self.fs_tick:   int = PLOT_FS_DEFAULTS["tick_fs"]
        self.title_fs_var  = tk.StringVar(value=self._fmt_num(self.fs_title))
        self.legend_fs_var = tk.StringVar(value=self._fmt_num(self.fs_legend))
        self.label_fs_var  = tk.StringVar(value=self._fmt_num(self.fs_label))
        self.tick_fs_var   = tk.StringVar(value=self._fmt_num(self.fs_tick))

        # Title display is applied immediately.
        self.show_title_var = tk.BooleanVar(value=True)

        # Overlay option for the skeletonized preview panel.
        self.overlay_mode_var = tk.StringVar(value=_("非表示"))
        self.preview_mode_var = tk.StringVar(value="original")

        # ===== Preview data cache =====
        # Reload bundles only when the selected file or bundle mtime changes.
        self._current_item: Optional[FileItem] = None
        self._current_data: Optional[Dict[str, np.ndarray]] = None
        self._current_mtime: float = 0.0

        # ===== Registry for unconfirmed entries in the main window =====
        # SingleViewDialog owns a separate registry selected by the registry argument.
        self._init_unconfirmed_registry()

        # ===== Build UI widgets =====
        self._build_top_bar()
        self._build_main_panes()

        # Show startup-setting messages after the log widget exists.
        for m in startup_logs:
            self._log(m)

        self._build_preview_area()
        self._bind_events()

        # constrained_layout avoids repeated tight_layout() calls during redraw.
        self.preview_fig = plt.Figure(figsize=(7.0, 6.2), dpi=100, constrained_layout=True)
        self.preview_axes = self.preview_fig.subplots(2, 2)
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, master=self.right_frame)
        self.preview_canvas.get_tk_widget().pack(fill="both", expand=True)

        self._preview_clear_axes()

        # Poll worker messages frequently enough to keep the UI responsive.
        self.after(50, self._poll_ui_queue)

        # Initialize button states before any folder is selected.
        self._update_controls_state()

    # ---------- UI construction ----------
    def _build_top_bar(self) -> None:
        """
        Build the top toolbar for folder selection and analysis actions.
        フォルダ選択と解析操作用の上部ツールバーを構築する。
        """
        # Build the top toolbar in functional groups separated by ttk.Separator.
        #   1. Input: [Folder]
        #   2. Run: [Overwrite analyzed] [Analyze all] [Analyze] [Stop]
        #   3. Other: [Settings] [Open output]
        # Surface-specific actions stay near the log and preview areas they operate on.
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=8, pady=6)

        # --- Group 1: input selection ---
        self.btn_select_folder = ttk.Button(top, text=_("フォルダ選択"), command=self.on_select_folder)
        self.btn_select_folder.pack(side="left", padx=4)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)

        # --- Group 2: analysis controls ---
        # Checked means existing analysis outputs will be overwritten.
        self.chk_skip = ttk.Checkbutton(top, text=_("解析済みを上書き"), variable=self.overwrite_existing_var,
                                        command=self._on_toggle_skip_checkbox)
        self.chk_skip.pack(side="left", padx=8)

        self.btn_run_all = ttk.Button(top, text=_("全て解析"), command=self.on_run_all)
        self.btn_run_all.pack(side="left", padx=4)

        self.btn_run_sel = ttk.Button(top, text=_("解析"), command=self.on_run_selected)
        self.btn_run_sel.pack(side="left", padx=4)

        self.btn_stop = ttk.Button(top, text=_("停止"), command=self.on_stop)
        self.btn_stop.pack(side="left", padx=4)

        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=2)

        # --- Group 3: other actions ---
        self.btn_settings = ttk.Button(top, text=_("設定"), command=self.on_open_settings)
        self.btn_settings.pack(side="left", padx=4)

        self.btn_open_out = ttk.Button(top, text=_("出力先を開く"), command=self.on_open_output_folder)
        self.btn_open_out.pack(side="left", padx=4)

    def _build_main_panes(self) -> None:
        """
        Build the file-list, log, progress, and preview pane layout.
        ファイル一覧、ログ、進捗、プレビュー領域のペイン配置を構築する。
        """
        # Build a resizable split layout: file list/log on the left, preview on the right.
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=6)

        self.left_frame = ttk.Frame(paned)
        self.right_frame = ttk.Frame(paned)
        paned.add(self.left_frame, weight=2)
        paned.add(self.right_frame, weight=3)

        # Left pane: file list.
        list_frame = ttk.Frame(self.left_frame)
        list_frame.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Label(list_frame, text=_("ファイル一覧")).pack(side="top", anchor="w", padx=2, pady=(0, 2))

        # Inner frame keeps the Treeview and its scrollbar aligned.
        list_inner = ttk.Frame(list_frame)
        list_inner.pack(fill="both", expand=True)

        columns = ("name", "status", "time")
        self.tree, _tree_vsb = create_scrolled_treeview(
            list_inner,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=14,
            headings={
                "name": _("ファイル名"),
                "status": _("状態"),
                "time": _("処理時間") + " (s)",
            },
            column_options={
                "name": {"width": 260, "anchor": "w"},
                "status": {"width": 90, "anchor": "center"},
                "time": {"width": 90, "anchor": "center"},
            },
        )

        # Left pane: log display.
        log_frame = ttk.Frame(self.left_frame)
        log_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # Keep the log-save action attached to the log area instead of the global toolbar.
        log_header = ttk.Frame(log_frame)
        log_header.pack(side="top", fill="x", padx=2, pady=(0, 2))
        self.btn_save_log = ttk.Button(log_header, text=_("ログを保存"), command=self.on_save_log)
        self.btn_save_log.pack(side="left")

        # Inner container for the log text widget and scrollbar.
        log_inner = ttk.Frame(log_frame)
        log_inner.pack(fill="both", expand=True)

        self.log_text, _log_vsb = create_scrolled_text(
            log_inner, height=10, wrap="word", state="disabled",
        )

        # Progress area: percentage bar, completed count, and current step details.
        prog_frame = ttk.Frame(self.left_frame)
        prog_frame.pack(fill="x", padx=4, pady=(0, 4))

        self.progress_count_var = tk.StringVar(value=_("-/- 完了"))
        ttk.Label(prog_frame, textvariable=self.progress_count_var).pack(side="left", padx=(4, 10))

        self.progressbar = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self.progressbar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.progress_detail_var = tk.StringVar(value=_("-"))
        ttk.Label(prog_frame, textvariable=self.progress_detail_var).pack(side="left", padx=(0, 4))

    def _build_preview_area(self) -> None:
        """
        Build preview controls for scale, contrast, overlays, and export.
        スケール、コントラスト、重ね表示、書き出し用のプレビュー操作部を構築する。
        """
        # Build the preview controls in three compact rows.
        # Entry-based numeric controls use Enter-to-commit so partial edits do not
        # immediately redraw figures with invalid or unintended values.

        # -- Row 1: scale display, physical scale, axis unit, vmin/vmax --
        ctrl1 = ttk.Frame(self.right_frame)
        ctrl1.pack(side="top", fill="x", padx=4, pady=(4, 2))

        # Scale display toggle applies immediately.
        ttk.Checkbutton(
            ctrl1, text=_("スケール表示"), variable=self.show_scale_var,
            command=self.on_redraw_preview,
        ).pack(side="left", padx=(2, 4))

        # Physical scale in micrometers, committed with Enter.
        ttk.Label(ctrl1, text=_("スケール") + " (µm)").pack(side="left", padx=(8, 2))
        self.ent_scale_um = ttk.Entry(ctrl1, width=7, textvariable=self.scale_um_var)
        self.ent_scale_um.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_scale_um,
            lambda: self._fmt_num(self.scale_um),
            self.validate_scale_um,
        )
        ToolTip(
            self.ent_scale_um,
            _("AFM 画像の一辺の実寸") + " (µm)。\n"
            + _("解析結果には影響せず、スケール表示時の軸目盛のみに使われる。") + "\n"
            + _("同一フォルダ内で画像ごとにスキャンサイズが異なる場合は、") + "\n"
            + _("ファイルを選び直してから値を変更してください。"),
        )

        # Axis tick unit, applied immediately.
        ttk.Label(ctrl1, text=_("軸目盛単位")).pack(side="left", padx=(10, 2))
        ttk.Radiobutton(
            ctrl1, text="µm", value="µm",
            variable=self.unit_var, command=self.on_redraw_preview,
        ).pack(side="left", padx=(0, 2))
        ttk.Radiobutton(
            ctrl1, text="nm", value="nm",
            variable=self.unit_var, command=self.on_redraw_preview,
        ).pack(side="left", padx=(0, 2))

        # vmin/vmax for calibrated-image contrast.
        ttk.Label(ctrl1, text=_("vmin")).pack(side="left", padx=(14, 2))
        self.ent_vmin = ttk.Entry(ctrl1, width=7, textvariable=self.vmin_var)
        self.ent_vmin.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_vmin,
            lambda: self._fmt_num(self.vmin),
            self.validate_vrange,
        )

        ttk.Label(ctrl1, text=_("vmax")).pack(side="left", padx=(6, 2))
        self.ent_vmax = ttk.Entry(ctrl1, width=7, textvariable=self.vmax_var)
        self.ent_vmax.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_vmax,
            lambda: self._fmt_num(self.vmax),
            self.validate_vrange,
        )

        # -- Row 2: title toggle and font sizes --
        ctrl2 = ttk.Frame(self.right_frame)
        ctrl2.pack(side="top", fill="x", padx=4, pady=(0, 2))

        # Title display toggle applies immediately.
        ttk.Checkbutton(
            ctrl2, text=_("タイトル表示"), variable=self.show_title_var,
            command=self.on_redraw_preview,
        ).pack(side="left", padx=(2, 4))

        ttk.Label(ctrl2, text=_("フォントサイズ：タイトル")).pack(side="left", padx=(8, 2))
        self.ent_title_fs = ttk.Entry(ctrl2, width=5, textvariable=self.title_fs_var)
        self.ent_title_fs.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_title_fs,
            lambda: self._fmt_num(self.fs_title),
            self.validate_main_font_sizes,
        )

        ttk.Label(ctrl2, text=_("軸ラベル")).pack(side="left", padx=(10, 2))
        self.ent_label_fs = ttk.Entry(ctrl2, width=5, textvariable=self.label_fs_var)
        self.ent_label_fs.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_label_fs,
            lambda: self._fmt_num(self.fs_label),
            self.validate_main_font_sizes,
        )

        ttk.Label(ctrl2, text=_("軸目盛")).pack(side="left", padx=(10, 2))
        self.ent_tick_fs = ttk.Entry(ctrl2, width=5, textvariable=self.tick_fs_var)
        self.ent_tick_fs.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_tick_fs,
            lambda: self._fmt_num(self.fs_tick),
            self.validate_main_font_sizes,
        )

        ttk.Label(ctrl2, text=_("凡例")).pack(side="left", padx=(10, 2))
        self.ent_legend_fs = ttk.Entry(ctrl2, width=5, textvariable=self.legend_fs_var)
        self.ent_legend_fs.pack(side="left", padx=2)
        self._register_unconfirmed_entry(
            self.ent_legend_fs,
            lambda: self._fmt_num(self.fs_legend),
            self.validate_main_font_sizes,
        )

        # -- Row 3: overlay, image export, and single-view dialog --
        ctrl3 = ttk.Frame(self.right_frame)
        ctrl3.pack(side="top", fill="x", padx=4, pady=(0, 4))

        # Overlay selector for the skeletonized panel.
        lbl_overlay = ttk.Label(ctrl3, text=_("重ね表示"))
        lbl_overlay.pack(side="left", padx=(2, 2))
        self.cmb_overlay = ttk.Combobox(
            ctrl3, width=10, textvariable=self.overlay_mode_var,
            values=[_("非表示"), "EP", "BP", "KP", "DP"],
            state="readonly"
        )
        self.cmb_overlay.pack(side="left", padx=2)
        self.cmb_overlay.bind("<<ComboboxSelected>>", lambda e: self.on_redraw_preview())

        # Explain abbreviated feature names in the tooltip.
        overlay_help = (
            _("Skeletonized 画像に重ねる特徴点の種類を選択します。") + "\n"
            "  " + _("非表示") + "           : " + _("重ね表示しません") + "\n"
            "  EP (End Point)     : " + _("ファイバーの端点（青）")          + "\n"
            "  BP (Branch Point)  : " + _("ファイバーの分岐点（赤）")        + "\n"
            "  KP (Kink Point)    : " + _("ファイバーのキンク点（シアン）")  + "\n"
            "  DP (Decomposed Point) : " + _("ファイバーの分解点（オレンジ）")
        )
        ToolTip(lbl_overlay, overlay_help)

        # Export the full right-pane preview figure.
        self.btn_export_preview = ttk.Button(
            ctrl3, text=_("画像を保存"), command=self.on_export_preview)
        self.btn_export_preview.pack(side="left", padx=(16, 4))

        self.btn_open_single = ttk.Button(
            ctrl3, text=_("個別表示"), command=self.on_open_single_view)
        self.btn_open_single.pack(side="left", padx=4)

    # ---------- Unconfirmed-entry mechanism, shared with GUI02 ----------
    # Entries are marked as unconfirmed when text differs from committed state,
    # then all unconfirmed values in the same registry are committed together on Enter.
    # Shared behavior lives in ui_tools.UnconfirmedEntryMixin.

    def validate_vrange(self):
        """
        Validate and commit the main preview vmin/vmax fields together.
        メインプレビューの vmin/vmax 入力欄をまとめて検証・確定する。

        Returns
        -------
        bool
            True if both values were committed; False if validation failed.
            両方の値を確定できた場合は True、不正値なら False。
        """
        return self._commit_float_fields(
            [
                (self.ent_vmin, "vmin", "vmin"),
                (self.ent_vmax, "vmax", "vmax"),
            ],
            validator=lambda v: None if v["vmax"] >= v["vmin"]
            else _("vmin は vmax 以下にしてください"),
            on_success=self.on_redraw_preview,
        )

    def validate_main_font_sizes(self):
        """
        Validate and commit the main preview font-size fields together.
        メインプレビューのフォントサイズ入力欄をまとめて検証・確定する。

        Returns
        -------
        bool
            True if all font sizes were committed; False if validation failed.
            全フォントサイズを確定できた場合は True、不正値なら False。
        """
        keys = ("fs_title", "fs_legend", "fs_label", "fs_tick")
        return self._commit_float_fields(
            [
                (self.ent_title_fs,  "fs_title",  "title"),
                (self.ent_legend_fs, "fs_legend", "legend"),
                (self.ent_label_fs,  "fs_label",  "label"),
                (self.ent_tick_fs,   "fs_tick",   "tick"),
            ],
            validator=lambda v: None if all(1 <= v[k] <= 60 for k in keys)
            else _("フォントサイズは 1〜60 の範囲で入力してください"),
            on_success=self.on_redraw_preview,
        )

    def validate_scale_um(self):
        """
        Validate and commit the physical image scale in micrometers.
        画像実寸スケール (µm) の入力欄を検証・確定する。

        Returns
        -------
        bool
            True if the positive scale value was committed; False otherwise.
            正のスケール値を確定できた場合は True、それ以外は False。
        """
        return self._commit_float_fields(
            [(self.ent_scale_um, "scale_um", "scale_um")],
            validator=lambda v: None if v["scale_um"] > 0
            else _("スケール") + " (µm) " + _("は正の数を入力してください"),
            on_success=self.on_redraw_preview,
        )

    def _bind_events(self) -> None:
        """
        Bind GUI events that update controls and preview state.
        操作部とプレビュー状態を更新する GUI イベントを結び付ける。
        """
        # Refresh preview state when the selected Treeview row changes.
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_tree_select())

    # ---------- Log ----------
    # _log and _log_exception come from ui_tools.LogMixin.
    # log_text is created in _build_main_panes.

    # ---------- Output Location ----------
    def _default_save_dir(self) -> str:
        """
        Return the default directory for save dialogs.
        保存ダイアログの既定フォルダを返す。
        """
        # Use the selected input folder as the default save location.
        return self.folder_path or os.getcwd()

    def has_output_dir(self) -> bool:
        """
        Return whether this GUI has an output folder available.
        この GUI で出力先フォルダが利用可能かを返す。
        """
        # A selected input folder is also the output location for this GUI.
        return bool(self.folder_path)

    # ---------- File List Updates ----------
    def _clear_tree(self) -> None:
        """
        Clear the file table and its path lookup dictionaries.
        ファイル表とパス検索用辞書を消去する。
        """
        # Keep Treeview rows and lookup dictionaries in sync.
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.item_by_iid.clear()
        self.iid_by_path.clear()

    def _insert_item(self, item: FileItem) -> None:
        """
        Insert one file item into the Treeview and lookup dictionaries.
        1 件のファイル項目を Treeview と検索用辞書へ挿入する。
        """
        # Store both lookup directions because later queue messages carry only iid.
        iid = self.tree.insert("", "end", values=(os.path.basename(item.txt_path), status_label(item.status), item.proc_time_s))
        self.item_by_iid[iid] = item
        self.iid_by_path[item.txt_path] = iid

    def _refresh_tree_row(self, iid: str) -> None:
        """
        Refresh one Treeview row from its FileItem state.
        FileItem の状態から Treeview の 1 行を更新する。
        """
        # Re-render one row from the authoritative FileItem state.
        it = self.item_by_iid.get(iid)
        if not it:
            return
        self.tree.item(iid, values=(os.path.basename(it.txt_path), status_label(it.status), it.proc_time_s))

    def _find_iid_for_item(self, item: FileItem) -> Optional[str]:
        """
        Return the Treeview row id for a file item.
        ファイル項目に対応する Treeview 行 ID を返す。
        """
        # Return the Treeview row id for a FileItem, if it is still listed.
        return self.iid_by_path.get(item.txt_path)

    # ---------- UI State ----------
    def _update_controls_state(self) -> None:
        """
        Enable or disable controls according to the current run state.
        現在の実行状態に応じて操作部を有効化または無効化する。
        """
        # Disable controls that would mutate selection or settings during analysis.
        def _set(widgets, state):
            """
            Apply one ttk state change to a group of widgets.
            複数ウィジェットへ 1 つの ttk 状態変更を適用する。
            """
            # ttk state strings use "!disabled" to remove the disabled state.
            for w in widgets:
                try:
                    w.state([state])
                except Exception:
                    pass

        running = self.is_running
        _set([self.btn_select_folder, self.chk_skip, self.btn_run_all, self.btn_settings],
             "disabled" if running else "!disabled")
        _set([self.btn_stop], "!disabled" if running else "disabled")

        # Single-file analysis is available only when at least one row is selected.
        if running:
            _set([self.btn_run_sel], "disabled")
        else:
            has_sel = bool(self.tree.selection())
            _set([self.btn_run_sel], "!disabled" if has_sel else "disabled")

    def _on_tree_select(self) -> None:
        """
        Handle file-table selection changes.
        ファイル表の選択変更を処理する。
        """
        self._update_controls_state()
        self.on_redraw_preview()

    def _on_toggle_skip_checkbox(self) -> None:
        """
        Log the current overwrite policy after the checkbox changes.
        チェックボックス変更後の上書き方針をログへ記録する。
        """
        # Log the overwrite policy because the checkbox wording can be read two ways.
        if self.overwrite_existing_var.get():
            self._log(_("既存ファイル: 上書きON（解析開始前に上書き対象数をログ表示）"))
        else:
            self._log(_("既存ファイル: スキップ（再計算・上書きしない）"))

    # ---------- Folder Selection ----------
    def on_select_folder(self) -> None:
        """
        Ask for an input folder and populate the batch file list.
        入力フォルダを選択し、一括処理用ファイル一覧を作成する。
        """
        folder = filedialog.askdirectory(title=_("入力フォルダを選択（.txtを含む）"))
        if not folder:
            return

        self.folder_path = folder
        self._log(_("フォルダ選択: %s") % folder)

        try:
            # Sort input files for deterministic batch order and log output.
            files = sorted([f for f in os.listdir(folder) if f.lower().endswith(".txt")])
        except Exception as e:
            self._log(_("フォルダ読み込み失敗: %s") % e)
            return

        self.items = []
        self._clear_tree()
        # Switching folders invalidates preview data even before a new row is selected.
        self._invalidate_current_data()

        # Detect existing outputs only when a folder is selected.
        for fn in files:
            full = os.path.join(folder, fn)
            item = FileItem(txt_path=full)
            ok, missing = existing_min_set(item.stem)
            if ok:
                # The minimal bundle key set is enough to skip recalculation.
                item.status = STATUS_ANALYZED
            else:
                item.status = STATUS_PENDING
                if missing:
                    item.missing_reason = _("欠損: ") + ", ".join(missing)
                    self._log(_("%s: 未解析（%s）") % (fn, item.missing_reason))
            self.items.append(item)
            self._insert_item(item)

        if not self.items:
            self._log(_("対象 .txt がありません。"))
        self._update_controls_state()
        self.on_redraw_preview()

    # ---------- Analysis ----------
    def _check_folder_selected(self) -> bool:
        """
        Return whether an input folder has been selected, warning if needed.
        入力フォルダが選択済みかを返し、必要なら警告を表示する。
        """
        if not self.folder_path:
            messagebox.showwarning(_("注意"), _("先にフォルダを選択してください。"))
            return False
        return True

    def on_run_all(self) -> None:
        """
        Start analysis for all listed files.
        一覧内の全ファイルの解析を開始する。
        """
        if not self._check_folder_selected():
            return
        targets = list(self.items)
        self._start_processing(targets)

    def on_run_selected(self) -> None:
        """
        Start analysis for the selected table rows.
        ファイル表で選択された行の解析を開始する。
        """
        if not self._check_folder_selected():
            return
        sel_iids = list(self.tree.selection())
        if not sel_iids:
            return
        targets = [self.item_by_iid[iid] for iid in sel_iids if iid in self.item_by_iid]
        self._start_processing(targets)

    def on_stop(self) -> None:
        """
        Request a safe stop between files in the worker thread.
        ワーカースレッドにファイル間での安全な停止を要求する。
        """
        # The worker checks stop_event between files so partial outputs are avoided.
        if not self.is_running:
            return
        self._log(_("停止要求を受け付けました（安全に中断します）"))
        self.progress_detail_var.set(_("停止要求を送信しました…"))
        self.stop_event.set()

    def _start_processing(self, targets: List[FileItem]) -> None:
        """
        Freeze settings and launch the worker thread for selected targets.
        設定を固定し、選択された対象ファイル用のワーカースレッドを起動する。
        """
        if self.is_running:
            return
        if not targets:
            return

        if not self.has_output_dir():
            messagebox.showerror(_("エラー"), _("フォルダが選択されていません。"))
            return

        # Freeze pending settings at run start so dialog edits cannot affect the worker.
        self.params_active = ProcParams(**asdict(self.params_pending))

        # Snapshot the save-original flag at run start; worker threads must not read
        # tkinter variables directly, and the user could toggle it mid-batch.
        # 解析開始時に元データ保存フラグをスナップショットする。ワーカーは tkinter
        # 変数を直接参照せず、また実行中のトグル変更の影響も受けないようにする。
        self._save_original_active = bool(self.save_original_var.get())

        # Count overwrites before starting because users expect an explicit warning.
        overwrite = self.overwrite_existing_var.get()
        if overwrite:
            n_over = 0
            for it in targets:
                ok, _missing = existing_min_set(it.stem)
                if ok:
                    n_over += 1
            self._log(_("上書き対象ファイル数: %d") % n_over)

        # Progressbar stores a percentage; completed count is tracked separately.
        self._total_tasks = len(targets)
        self._done_tasks = 0
        self.progressbar["maximum"] = 100
        self.progressbar["value"] = 0
        self.progress_count_var.set(_("{0}/{1} 完了").format(0, self._total_tasks))
        self.progress_detail_var.set(_("-"))

        self.is_running = True
        self.stop_event.clear()
        self._update_controls_state()

        # daemon=True lets the process exit cleanly if the main window is closed.
        th = threading.Thread(target=self._worker_process, args=(targets, overwrite), daemon=True)
        th.start()

    def _worker_process(self, targets: List[FileItem], overwrite: bool) -> None:
        """
        Process a batch of files on a background thread.
        バックグラウンドスレッドでファイル群を処理する。
        """
        # Worker threads must report all UI changes through self.ui_queue.
        try:
            # Reuse processing objects across the batch after parameters are frozen.
            p = self.params_active
            bg_calibrator = BG_Calibrator_shimadzu(
                bg_method=p.bg_method,
                tophat_se_size=p.tophat_se_size,
                spline1d_axis=p.spline1d_axis,
                spline1d_degree=p.spline1d_degree,
                spline2d_degree=p.spline2d_degree,
                spline2d_subsample=p.spline2d_subsample,
                spline2d_smoothing=p.spline2d_smoothing,
                threshold_factor=p.threshold_factor,
                fiber_detect_factor=p.fiber_detect_factor,
                noise_detect_factor=p.noise_detect_factor,
                savgol_window=p.savgol_window,
                savgol_polyorder=p.savgol_polyorder,
                apply_median=p.apply_median,
                mask_dilation=p.mask_dilation,
                min_mask_component_area=p.min_mask_component_area,
            )
            segmenter = Segmenter(
                wsize_localbin=p.wsize_localbin,
                global_threshold=p.global_threshold,
                area_min=p.area_min,
                area_min_connecting=p.area_min_connecting,
                apply_no_connecting=p.apply_no_connecting,
                h_length=p.h_length,
                h_sratio=p.h_sratio,
                low_threshold=p.low_threshold,
            )
            skeletonizer = Skeletonizer(
                bp_height=p.bp_height,
                branch_length=p.branch_length,
                min_area=p.min_area,
            )
            kink_detector = KinkDetector(
                # KinkDetector expects radians, while the GUI exposes degrees.
                threshold_angle_from_decomposed_indices=p.kinkangle_deg * np.pi / 180.0
            )

            for it in targets:
                if self.stop_event.is_set():
                    self.ui_queue.put(("log", _("停止しました。")))
                    break

                fname = os.path.basename(it.txt_path)
                iid = self._find_iid_for_item(it)
                if iid:
                    self.ui_queue.put(("status", (iid, STATUS_RUNNING, "")))

                # Re-check existing outputs at run time without changing folder-scan state.
                ok, _missing = existing_min_set(it.stem)
                if ok and not overwrite:
                    self.ui_queue.put(("log", _("%s: 既存データのためスキップ") % fname))
                    if iid:
                        self.ui_queue.put(("status", (iid, STATUS_ANALYZED, it.proc_time_s)))
                    self.ui_queue.put(("progress", 1))
                    self.ui_queue.put(("progress_detail", (fname, _("完了"))))
                    continue

                self._process_single_item(
                    it, fname, iid, bg_calibrator, segmenter, skeletonizer, kink_detector
                )

        finally:
            # Always unblock the main UI controls, even after an exception or stop.
            self.ui_queue.put(("done", None))

    def _process_single_item(
        self,
        it: FileItem,
        fname: str,
        iid: Optional[str],
        bg_calibrator: BG_Calibrator_shimadzu,
        segmenter: Segmenter,
        skeletonizer: Skeletonizer,
        kink_detector: KinkDetector,
    ) -> None:
        """
        Run the preprocessing pipeline and save outputs for one file.
        1 ファイルに対して前処理パイプラインを実行し、出力を保存する。
        """
        # Run the full preprocessing pipeline for one input file.
        t0 = time.time()
        try:
            # Each stage reports a translated progress label through the UI queue.
            self.ui_queue.put(("progress_detail", (fname, _("読み込み"))))
            height_data = load_afm_text(it.txt_path)
            image = ProcessedImage(original_AFM=height_data, name=it.basename_stem)

            self.ui_queue.put(("progress_detail", (fname, _("BG補正"))))
            bg_calibrator(image)

            self.ui_queue.put(("progress_detail", (fname, _("二値化/成分処理"))))
            segmenter(image)

            self.ui_queue.put(("progress_detail", (fname, _("細線化"))))
            skeletonizer(image)

            self.ui_queue.put(("progress_detail", (fname, _("kink検出"))))
            kink_detector(image)

            # Save all derived analysis outputs into one .b2z bundle.
            # 下流 GUI が 1 ファイルから必要な配列をまとめて読み込めるようにする。
            self.ui_queue.put(("progress_detail", (fname, _("保存"))))

            # Store point coordinate pairs as shape (2, N) arrays for GUI04.
            kp_x, kp_y = image.all_kink_coordinates
            dp_x, dp_y = image.decomposed_point_coordinates

            arrays = {
                "calibrated":   image.calibrated_image,
                "binarized":    image.binarized_image,
                "skeletonized": image.skeleton_image,
                "bp":           image.bp,                        # Branch-point mask.
                "ep":           image.ep,                        # End-point mask.
                "kp":           np.stack([kp_x, kp_y]),          # Kink coordinates, shape (2, N).
                "dp":           np.stack([dp_x, dp_y]),          # Decomposed-point coordinates, shape (2, N).
                "ka":           image.all_kink_angles,           # Kink angles in radians.
            }

            # Optionally bundle the raw original AFM height image. When included,
            # the .b2z is self-contained (no dependency on the source .txt) and can
            # serve as a fast-loading input for downstream machine-learning GUIs.
            # 任意で元の AFM 高さ画像を同梱する。同梱すると .b2z は .txt に依存せず
            # 自己完結し、下流の機械学習用 GUI の高速読み込み入力としても使える。
            if self._save_original_active:
                arrays["original"] = height_data

            params_dict = asdict(self.params_active)
            vlmeta = {
                "params":  params_dict,                  # Analysis parameters for reproducibility.
                "version": "1.0",
            }

            save_bundle(bundle_path_for(it.stem), arrays, vlmeta=vlmeta)

            # Keep analysis parameters as sidecar JSON because it is easy to inspect by hand.
            param_path = it.stem + "_param.json"
            with open(param_path, "w", encoding="utf-8") as f:
                json.dump(params_dict, f, ensure_ascii=False, indent=2)

            self.ui_queue.put(("progress_detail", (fname, _("完了"))))

        except Exception as e:
            # A failed file returns to pending while the rest of the batch continues.
            tb = traceback.format_exc()
            self.ui_queue.put(("log", _("解析失敗: %s\n%s\n%s") % (fname, e, tb)))
            if iid:
                self.ui_queue.put(("status", (iid, STATUS_PENDING, "")))
            self.ui_queue.put(("progress", 1))
            self.ui_queue.put(("progress_detail", (fname, _("失敗"))))
            return

        # Report timing only after all outputs and sidecar metadata are written.
        dt = time.time() - t0
        dt_s = f"{dt:.2f}"
        self.ui_queue.put(("log", _("解析完了: %s (%ss)") % (fname, dt_s)))
        if iid:
            self.ui_queue.put(("status", (iid, STATUS_ANALYZED, dt_s)))
        self.ui_queue.put(("progress", 1))

    # ---------- Queue Polling ----------
    def _poll_ui_queue(self) -> None:
        """
        Poll worker-thread messages and apply UI updates on the main thread.
        ワーカースレッドからのメッセージを監視し、メインスレッドで UI 更新を行う。
        """
        def _on_status(payload):
            iid, status, t = payload
            it = self.item_by_iid.get(iid)
            if it:
                it.status = status
                it.proc_time_s = t
                self._refresh_tree_row(iid)

        def _on_progress(payload):
            self._done_tasks += int(payload)
            pct = 0.0
            if self._total_tasks > 0:
                pct = (self._done_tasks / self._total_tasks) * 100.0
            self.progressbar["value"] = pct
            self.progress_count_var.set(
                _("{0}/{1} 完了").format(self._done_tasks, self._total_tasks)
            )

        def _on_done(_payload):
            # Re-analysis may have changed the selected bundle, so reload preview data.
            self.is_running = False
            self.stop_event.clear()
            self._update_controls_state()
            self._invalidate_current_data()
            self.on_redraw_preview()

        drain_ui_queue(self.ui_queue, {
            "log": lambda payload: self._log(str(payload)),
            "status": _on_status,
            "progress": _on_progress,
            "progress_detail": lambda payload: self.progress_detail_var.set(
                _("{0} / {1}").format(payload[0], payload[1])
            ),
            "done": _on_done,
        })
        # Keep polling frequently enough that the progress display feels live.
        self.after(50, self._poll_ui_queue)

    # ---------- Preview (2x2) ----------
    def _reset_axes(self) -> None:
        """
        Clear all preview axes without deciding their visibility.
        表示状態を決めずに全プレビュー軸を消去する。
        """
        # Only clear axes here; callers decide whether axes should be visible.
        # Applying axis("off") here would prevent axes from returning when the
        # scale display is enabled later.
        # ここで axis("off") を適用すると、後でスケール表示を有効化したときに
        # 軸枠が復帰できないため、表示状態の判断は呼び出し側へ分離している。
        for ax in self.preview_axes.ravel():
            ax.clear()

    def _preview_clear_axes(self) -> None:
        """
        Clear and hide all preview axes.
        全プレビュー軸を消去して非表示にする。
        """
        self._reset_axes()
        for ax in self.preview_axes.ravel():
            ax.axis("off")
        self.preview_fig.suptitle("")
        # constrained_layout handles spacing; draw_idle avoids blocking the UI loop.
        self.preview_canvas.draw_idle()

    def _get_selected_item_for_preview(self) -> Optional[FileItem]:
        """
        Return the first selected item used by the preview renderer.
        プレビュー描画に使う最初の選択項目を返す。
        """
        sel = self.tree.selection()
        if not sel:
            return None
        # Preview uses the first selected row when the Treeview has multi-selection.
        iid = sel[0]
        return self.item_by_iid.get(iid)

    def _bundle_mtime_safe(self, it: FileItem) -> float:
        """
        Return the output bundle modification time, or zero if missing.
        出力バンドルの更新時刻を返し、存在しない場合は 0 を返す。
        """
        # Bundle mtime is used to detect re-analysis without opening the TreeStore.
        try:
            return os.path.getmtime(bundle_path_for(it.stem))
        except OSError:
            return 0.0

    def _load_processed_for_preview(
        self, it: FileItem,
    ) -> Optional[Dict[str, np.ndarray]]:
        """
        Load original and processed arrays for preview rendering.
        プレビュー描画用に元画像と処理済み配列を読み込む。
        """
        # Load the preview data synchronously; redraws reuse this cache.
        #
        # The original image source depends on the bundle: if the .b2z was saved
        # with "元データを保存" ON it contains an "original" key, which is read
        # directly (faster than re-parsing the source .txt, notably for large or
        # slow-to-parse text formats). Otherwise fall back to load_afm_text.
        # 元画像の取得元はバンドル依存。「元データを保存」ON で保存された .b2z は
        # "original" キーを含むのでそこから直接読む（.txt 再パースより速く、特に
        # 大きい/解析の重いテキスト形式で効く）。無ければ load_afm_text に戻す。
        if it.status != STATUS_ANALYZED:
            return None

        try:
            bundle_path = bundle_path_for(it.stem)

            # Required keys mirror _process_single_item; missing keys surface as KeyError.
            data = load_bundle(bundle_path)

            if "original" in data:
                ori = data["original"]
            else:
                ori = load_afm_text(it.txt_path)

            # Return every key used by the preview renderer and single-view dialog.
            return {
                "original":     ori,
                "calibrated":   data["calibrated"],
                "binarized":    data["binarized"],
                "skeletonized": data["skeletonized"],
                "bp":           data["bp"],
                "ep":           data["ep"],
                "kp":           data["kp"],   # shape: (2, N) → [0]=kink_x, [1]=kink_y
                "dp":           data["dp"],   # shape: (2, N) → [0]=dp_x,   [1]=dp_y
                "ka":           data["ka"],   # shape: (N,), kink angles in radians.
            }
        except Exception as e:
            self._log_exception(_("プレビュー読み込み失敗"), e)
            return None

    def _invalidate_current_data(self) -> None:
        """
        Clear the cached preview bundle data.
        キャッシュされたプレビューバンドルデータを消去する。
        """
        # Drop cached preview data after selection changes or bundle rewrites.
        self._current_item = None
        self._current_data = None
        self._current_mtime = 0.0

    def _ensure_current_data(self, it: FileItem) -> Optional[Dict[str, np.ndarray]]:
        """
        Return cached preview data, reloading when the selected bundle changes.
        選択バンドルが変わった場合は再読込し、キャッシュ済みプレビューデータを返す。
        """
        # Reuse preview data unless the selected item or bundle mtime changed.
        mtime = self._bundle_mtime_safe(it)
        if (
            self._current_item is it
            and self._current_data is not None
            and self._current_mtime == mtime
        ):
            return self._current_data
        data = self._load_processed_for_preview(it)
        if data is None:
            self._invalidate_current_data()
            return None
        self._current_item = it
        self._current_data = data
        self._current_mtime = mtime
        return data

    def on_redraw_preview(self) -> None:
        """
        Redraw the main 2x2 preview for the selected file.
        選択ファイルのメイン 2x2 プレビューを再描画する。
        """
        # Redraw synchronously; controls such as vmin/vmax reuse cached data.
        it = self._get_selected_item_for_preview()
        if not it:
            self._invalidate_current_data()
            self._preview_clear_axes()
            return
        data = self._ensure_current_data(it)
        if data is None:
            self._preview_clear_axes()
            return
        self._render_preview(it, data)

    def _render_preview(
        self, it: FileItem, data: Optional[Dict[str, np.ndarray]]
    ) -> None:
        """
        Render cached arrays into the main 2x2 preview figure.
        キャッシュ済み配列をメイン 2x2 プレビュー図へ描画する。
        """
        # Render cached data only; heavy I/O should be finished before this call.
        if not data:
            self._preview_clear_axes()
            return

        # Use committed values while Entry text may still be unconfirmed.
        vmin = self.vmin
        vmax = self.vmax

        tfs = self.fs_title
        lfs = self.fs_legend
        lblfs = self.fs_label
        tkfs = self.fs_tick
        show_title = self.show_title_var.get()

        show_scale = self.show_scale_var.get()
        unit = self.unit_var.get()
        if unit == "nm":
            scale = self.scale_um * 1000.0
            unit_label = "nm"
        else:
            scale = self.scale_um
            unit_label = "µm"

        # extent converts imshow from pixel coordinates to the selected physical scale.
        extent = [0, scale, 0, scale] if show_scale else None

        self._reset_axes()

        sub_titles = (
            "Original",     # [0][0]
            "Calibrated",   # [0][1]
            "Binarized",    # [1][0]
            "Skeletonized", # [1][1]
        )

        # Panels share the same rendering loop to keep scale and title behavior aligned.
        panels = (
            (self.preview_axes[0][0], data["original"],     "afmhot", {}),
            (self.preview_axes[0][1], data["calibrated"],   "afmhot", {"vmin": vmin, "vmax": vmax}),
            (self.preview_axes[1][0], data["binarized"],    "gray",   {}),
            (self.preview_axes[1][1], data["skeletonized"], "gray",   {}),
        )

        for i, (ax, img, cmap, extra) in enumerate(panels):
            ax.imshow(img, cmap=cmap, extent=extent, **extra)
            if show_scale:
                ax.set_xlabel("({0})".format(unit_label), fontsize=lblfs)
                ax.set_ylabel("({0})".format(unit_label), fontsize=lblfs)
                ax.tick_params(labelsize=tkfs)
            else:
                ax.axis("off")
            if show_title:
                ax.set_title(sub_titles[i], fontsize=tfs)

        # Feature overlays are drawn on the skeletonized panel and share its scaling.
        sk_img = data["skeletonized"]
        if show_scale:
            h, w = sk_img.shape[:2]
            sx = scale / max(w - 1, 1)
            sy = scale / max(h - 1, 1)
        else:
            sx, sy = 1.0, 1.0

        overlay = self.overlay_mode_var.get()
        ax_sk = self.preview_axes[1][1]

        if overlay == "EP":
            ep = data["ep"].astype(bool)
            end_y, end_x = np.where(ep)
            ax_sk.scatter(end_x * sx, end_y * sy, c="blue", s=10, label="EP")
        elif overlay == "BP":
            bp = data["bp"].astype(bool)
            br_y, br_x = np.where(bp)
            ax_sk.scatter(br_x * sx, br_y * sy, c="red", s=10, label="BP")
        elif overlay == "KP":
            kp = data["kp"]   # shape: (2, N_kink)
            if kp.shape[1] > 0:
                ax_sk.scatter(kp[0] * sx, kp[1] * sy, c="cyan", s=15, label="KP")
        elif overlay == "DP":
            dp = data["dp"]   # shape: (2, N_dp)
            if dp.shape[1] > 0:
                ax_sk.scatter(dp[0] * sx, dp[1] * sy, c="orange", s=8, label="DP")

        # Show a legend only when an overlay is visible.
        if overlay in ("EP", "BP", "KP", "DP"):
            ax_sk.legend(
                loc="center left", bbox_to_anchor=(1.02, 0.5),
                borderaxespad=0.0, fontsize=lfs,
            )

        # Let constrained_layout place the suptitle without a manual y offset.
        if show_title:
            self.preview_fig.suptitle(it.basename_stem, fontsize=tfs)
        else:
            self.preview_fig.suptitle("")
        self.preview_canvas.draw_idle()

    def _require_analyzed_item(self) -> Optional[FileItem]:
        """
        Return the selected analyzed item, or notify the user and return None.
        選択された解析済み項目を返し、無ければユーザーへ通知して None を返す。
        """
        # Centralize the guard used by export and single-view actions.
        it = self._get_selected_item_for_preview()
        if not it or it.status != STATUS_ANALYZED:
            messagebox.showinfo(_("情報"), _("解析済みファイルを選択してください。"))
            return None
        return it

    # ---------- Export Preview ----------
    def on_export_preview(self) -> None:
        """
        Save the current main preview figure through a file dialog.
        現在のメインプレビュー図をファイルダイアログ経由で保存する。
        """
        it = self._require_analyzed_item()
        if not it:
            return
        save_figure_with_dialog(
            self, self.preview_fig,
            initial_name=f"{it.basename_stem}.png",
            initial_dir=self._default_save_dir(),
            title=_("プレビュー画像を保存"),
            log_cb=self._log,
        )

    # ---------- Open Output Folder ----------
    def on_open_output_folder(self) -> None:
        """
        Open the selected input/output folder in the OS file manager.
        選択中の入出力フォルダを OS のファイルマネージャーで開く。
        """
        if not self.folder_path:
            messagebox.showinfo(_("情報"), _("フォルダが選択されていません。"))
            return
        open_folder_in_os(self.folder_path)

    # ---------- Save Log ----------
    def on_save_log(self) -> None:
        """
        Save the contents of the log text widget.
        ログテキストウィジェットの内容を保存する。
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

    # ---------- Settings Dialog ----------
    def on_open_settings(self) -> None:
        """
        Open the modal settings dialog for pending parameters.
        保留中パラメータを編集するモーダル設定ダイアログを開く。
        """
        # Settings are staged in params_pending until the next analysis starts.
        SettingsDialog(self, self.params_pending)

    # ---------- Single-View Dialog ----------
    def on_open_single_view(self) -> None:
        """
        Open a single-file preview dialog for the selected analyzed file.
        選択された解析済みファイルの個別プレビューダイアログを開く。
        """
        it = self._require_analyzed_item()
        if not it:
            return
        SingleViewDialog(self, it)


# ===== Settings dialog =====
class SettingsDialog(tk.Toplevel):
    """
    Modal dialog for editing preprocessing parameters.
    前処理パラメータを編集するモーダルダイアログ。

    Attributes
    ----------
    parent
        Main application window that receives logs and pending parameters.
        ログ出力と保留パラメータを管理するメインアプリケーションウィンドウ。
    params_ref
        Mutable parameter object edited by this dialog.
        本ダイアログで編集する可変パラメータオブジェクト。
    vars
        tkinter variables keyed by processing-parameter name.
        解析パラメータ名をキーにした tkinter 変数。
    """

    def __init__(self, parent: App, params: ProcParams) -> None:
        """
        Initialize the modal settings dialog and populate controls.
        モーダル設定ダイアログを初期化し、操作部に値を反映する。
        """
        super().__init__(parent)
        self.parent = parent
        self.params_ref = params   # Reference to params_pending edited by this dialog.

        self.title(_("設定"))
        apply_window_size(self, 860, 720, min_w=700, min_h=600)

        # Match the parent clam theme background for a consistent dialog surface.
        try:
            clam_bg = getattr(parent, "_clam_bg", None)
            if clam_bg:
                self.configure(bg=clam_bg)
        except tk.TclError:
            pass

        self.grab_set()          # Modal: block parent-window interaction while open.

        self.vars: Dict[str, tk.Variable] = {}
        # save_original is UI state (not a ProcParams analysis parameter), so it is
        # kept in its own variable and persisted to the settings file's _ui section.
        # Initialized from the parent's current choice.
        # save_original は ProcParams（解析パラメータ）ではなく UI 状態なので、
        # 専用変数で持ち、設定ファイルの _ui セクションへ保存する。初期値は親の現在値。
        self.save_original_var = tk.BooleanVar(value=bool(parent.save_original_var.get()))
        self._build_ui()
        self._populate_from_refs()
        self._on_bg_method_changed()

    def _build_ui(self) -> None:
        """
        Build the scrollable parameter editor and action buttons.
        スクロール可能なパラメータ編集部と操作ボタンを構築する。
        """
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Use a Canvas-backed frame so the parameter list can scroll.
        # tk.Canvas is a non-ttk widget whose default background is white, which
        # would otherwise show as a white seam around the ttk content and as white
        # space when the dialog is widened. Match the clam background and remove the
        # focus highlight border so the canvas blends with the surrounding frames.
        # tk.Canvas は非 ttk で既定背景が白く、ttk 内容の周囲に白い筋として、また
        # 横拡大時に白い余白として見えてしまう。clam 背景に合わせ、フォーカス枠も
        # 消して周囲のフレームと馴染ませる。
        canvas_bg = getattr(self.parent, "_clam_bg", None)
        canvas_kwargs = {"highlightthickness": 0, "bd": 0}
        if canvas_bg:
            canvas_kwargs["bg"] = canvas_bg
        canvas = tk.Canvas(container, **canvas_kwargs)
        vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)

        self.inner.bind(
            "<Configure>",
            # Recompute the scrollable region whenever child widgets resize.
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        inner_window = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)

        # Stretch the inner window to the canvas width so widening the dialog does
        # not expose blank canvas on the right; the content tracks the canvas size.
        # Canvas 幅に内部ウィンドウを追従させ、横拡大時に右側へ空の Canvas が
        # 露出しないようにする。
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(inner_window, width=e.width),
        )

        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Parameters staged here apply only to the next analysis run.
        plf = ttk.LabelFrame(self.inner, text=_("解析条件（次回解析時にのみ反映）"))
        plf.pack(fill="both", expand=True, padx=6, pady=6)

        # Keep row widgets so bg_method can dim unused parameters.
        # {key: {"label": Label, "input": Entry/Combobox/Checkbutton, "desc": Label}}
        self._param_rows: Dict[str, Dict[str, tk.Widget]] = {}

        def add_field(parent_lf: ttk.LabelFrame, key: str, label: str, desc: str, width: int = 12) -> None:
            """
            Add a text-entry parameter row.
            テキスト入力用のパラメータ行を追加する。
            """
            frm = ttk.Frame(parent_lf)
            frm.pack(fill="x", pady=3)
            lbl = ttk.Label(frm, text=label, width=26)
            lbl.pack(side="left")
            v = tk.StringVar()
            self.vars[key] = v
            ent = ttk.Entry(frm, textvariable=v, width=width)
            ent.pack(side="left", padx=6)
            dsc = ttk.Label(frm, text=desc, foreground="#444", justify="left")
            dsc.pack(side="left", padx=8, fill="x", expand=True)
            self._param_rows[key] = {"label": lbl, "input": ent, "desc": dsc}

        def add_bool(parent_lf: ttk.LabelFrame, key: str, label: str, desc: str) -> None:
            """
            Add a boolean checkbox parameter row.
            真偽値チェックボックス用のパラメータ行を追加する。
            """
            frm = ttk.Frame(parent_lf)
            frm.pack(fill="x", pady=3)
            lbl = ttk.Label(frm, text=label, width=26)
            lbl.pack(side="left")
            v = tk.BooleanVar()
            self.vars[key] = v
            chk = ttk.Checkbutton(frm, variable=v)
            chk.pack(side="left", padx=6)
            dsc = ttk.Label(frm, text=desc, foreground="#444", justify="left")
            dsc.pack(side="left", padx=8, fill="x", expand=True)
            self._param_rows[key] = {"label": lbl, "input": chk, "desc": dsc}

        def add_choice(parent_lf: ttk.LabelFrame, key: str, label: str,
                       choices: list, desc: str, width: int = 12,
                       command=None) -> None:
            """
            Add a readonly choice parameter row.
            読み取り専用選択肢のパラメータ行を追加する。
            """
            # Store choice values as strings, then cast in _apply_vars_to_refs.
            frm = ttk.Frame(parent_lf)
            frm.pack(fill="x", pady=3)
            lbl = ttk.Label(frm, text=label, width=26)
            lbl.pack(side="left")
            v = tk.StringVar()
            self.vars[key] = v
            cb = ttk.Combobox(frm, textvariable=v, values=choices,
                              width=width, state="readonly")
            cb.pack(side="left", padx=6)
            if command is not None:
                cb.bind("<<ComboboxSelected>>", lambda e: command())
            dsc = ttk.Label(frm, text=desc, foreground="#444", justify="left")
            dsc.pack(side="left", padx=8, fill="x", expand=True)
            self._param_rows[key] = {"label": lbl, "input": cb, "desc": dsc}

        # ---- BG_Calibrator_shimadzu ----
        # Scan size is display metadata, not an analysis parameter; GUI01,
        # GUI02, and GUI04 handle it as view state.
        # 画像の実寸は解析結果に影響せず、表示時にユーザーが都度設定する。
        lf_bg = ttk.LabelFrame(plf, text=_("BG_Calibrator_shimadzu"))
        lf_bg.pack(fill="x", padx=6, pady=6)
        # Dim parameters that do not apply to the selected background method.
        #   inpaint     : gradient-ridge detection followed by Navier-Stokes inpainting.
        #   inpaint     : 勾配リッジ検出 + NS inpaint
        #   tophat      : morphological opening; no mask, fast, and spatially uniform.
        #   tophat      : 形態学的opening (マスク不要、高速、一様性◎)
        #   spline1d    : row/column 1D B-spline with linear edge extrapolation.
        #   spline1d    : 行/列ごとの 1D B-スプライン + 端の線形外挿
        #   spline2d    : 2D B-spline fit for globally smooth backgrounds.
        #   spline2d    : 大局的に滑らかな背景向けの 2D B-スプラインフィット
        add_choice(lf_bg, "bg_method", _("bg_method"),
                   ["inpaint", "tophat", "spline1d", "spline2d"],
                   _("背景推定方式（下の説明参照）。選択に応じて使うパラメータのみ有効化されます"),
                   command=self._on_bg_method_changed)

        # Method descriptions are keyed by bg_method and displayed in menu order.
        self._bg_method_descs = {
            "inpaint":  _("inpaint : 勾配リッジ検出 + Navier-Stokes inpaint。勾配で繊維マスクを作り背景を補間。汎用だがリッジ検出パラメータの調整が必要"),
            "tophat":   _("tophat : 形態学的opening。tophat_se_size より細い明るい構造を前景として除去。マスク不要・高速・一様性に優れる"),
            "spline1d": _("spline1d : 行/列ごとの1D B-スプライン補間（オリジナル方式）。ライン間オフセット（縞）ノイズに有効。spline1d_axis で縞の向きを選択"),
            "spline2d": _("spline2d : 2D B-スプラインフィット。背景を行毎でなく2D問題として一括で解く。大局的に滑らかな背景に向く"),
        }
        bg_desc_frame = ttk.Frame(lf_bg)
        bg_desc_frame.pack(fill="x", padx=6, pady=(0, 6))
        for _m in ["inpaint", "tophat", "spline1d", "spline2d"]:
            ttk.Label(bg_desc_frame, text=self._bg_method_descs[_m],
                      foreground="#555", justify="left").pack(anchor="w")

        # --- Parameters are ordered by method: inpaint, tophat, spline1d, spline2d. ---
        # tophat-specific.
        add_field(lf_bg, "tophat_se_size", "tophat_se_size",
                  _("[tophat時のみ] 構造要素直径") + " (px)。"
                  + _("最大ファイバー幅の2〜3倍。奇数(偶数は+1)"), 10)
        # spline1d-specific.
        add_choice(lf_bg, "spline1d_axis", "spline1d_axis",
                   ["y", "x"],
                   _("[spline1d時のみ] 除去する縞の向き。'y'=横縞(各走査ラインが上下にずれるノイズ)を除去/各列を縦に補間。'x'=縦縞を除去/各行を横に補間(良好な結果が多い)"))
        add_field(lf_bg, "spline1d_degree", "spline1d_degree",
                  _("[spline1d時のみ] 行/列スプライン order。実用範囲1〜3 (2=旧pandas互換)。点数不足の行は線形に自動フォールバック"), 10)
        # spline2d-specific.
        add_field(lf_bg, "spline2d_degree", "spline2d_degree",
                  _("[spline2d時のみ] スプライン次数。実用範囲1〜3 (1=双線形、2=旧pandas互換、3=双立方)。[1,5]"), 10)
        add_field(lf_bg, "spline2d_subsample", "spline2d_subsample",
                  _("[spline2d時のみ] フィット用画素サブサンプル係数。大きいほど高速、品質影響は微少。デフォルト4"), 10)
        # spline2d_smoothing is hidden because low smoothing can become ill-conditioned
        # and very slow; spline2d_subsample is the safer GUI-facing speed control.
        # spline2d パイプラインでは小さな s が悪条件・極端に低速な準補間に
        # なり得るため、GUI から外して ProcParams 既定の None に固定する。
        # Mask and threshold parameters shared by inpaint, spline1d, and spline2d.
        add_field(lf_bg, "threshold_factor", "threshold_factor", _("[inpaint, spline1d, spline2d時] 背景範囲（中心±sigma*係数）を決める係数"))
        add_field(lf_bg, "fiber_detect_factor", "fiber_detect_factor", _("[inpaint, spline1d, spline2d時] [1,0,-1]の急変を繊維として除外する距離しきい値"))
        add_field(lf_bg, "noise_detect_factor", "noise_detect_factor", _("[inpaint, spline1d, spline2d時] [1,-1]の急変が一定以上離れている場合に構造とみなすしきい値"))
        # Smoothing parameters shared by inpaint, tophat, and spline1d.
        add_field(lf_bg, "savgol_window", "savgol_window", _("[inpaint, tophat, spline1d時] Savitzky-Golayフィルタの窓幅（平滑化範囲）"), 10)
        add_field(lf_bg, "savgol_polyorder", "savgol_polyorder", _("[inpaint, tophat, spline1d時] Savitzky-Golayフィルタの多項式次数"), 10)
        # Post-processing shared by all methods.
        add_bool(lf_bg, "apply_median", "apply_median", _("中央値フィルタを最後にかける（点ノイズに強い）"))
        # Mask dilation parameters shared by inpaint, spline1d, and spline2d.
        add_field(lf_bg, "mask_dilation", "mask_dilation", _("[inpaint, spline1d, spline2d時] 繊維マスクを膨張させる画素数（0でdilationなし）"), 10)
        add_field(lf_bg, "min_mask_component_area", "min_mask_component_area",
                  _("[inpaint, spline1d, spline2d時] dilation前にマスクから除外する連結成分の最小面積") + " (px)。"
                  + _("1でフィルタ無効"), 10)

        # ---- Segmenter ----
        lf_seg = ttk.LabelFrame(plf, text=_("Segmenter"))
        lf_seg.pack(fill="x", padx=6, pady=6)
        add_field(lf_seg, "wsize_localbin", "wsize_localbin", _("局所しきい値の計算に使う窓サイズ"), 10)
        add_field(lf_seg, "global_threshold", "global_threshold", _("全体一律の2値化しきい値"))
        add_field(lf_seg, "area_min", "area_min", _("小さい連結成分を消す面積しきい値"), 10)
        add_field(lf_seg, "area_min_connecting", "area_min_connecting", _("つながり成分を除くときの面積しきい値"), 10)
        add_bool(lf_seg, "apply_no_connecting", "apply_no_connecting", _("つながり除去を実行するかどうか"))
        add_field(lf_seg, "h_length", "h_length", _("線分検出で線分とみなす最小長さ"), 10)
        add_field(lf_seg, "h_sratio", "h_sratio", _("線っぽさ") + " (s_ratio) " + _("のしきい値"))
        add_field(lf_seg, "low_threshold", "low_threshold", _("高さが低い成分を消すしきい値"))

        # ---- Skeletonizer ----
        lf_skl = ttk.LabelFrame(plf, text=_("Skeletonizer"))
        lf_skl.pack(fill="x", padx=6, pady=6)
        add_field(lf_skl, "bp_height", "bp_height", _("分岐点が低い高さか判定するしきい値"))
        add_field(lf_skl, "branch_length", "branch_length", _("枝とみなす短い線を追跡する最大長"), 10)
        add_field(lf_skl, "min_area", "min_area", _("小さすぎる線分（ノイズ）を削除する面積しきい値"), 10)

        # ---- Kinkdetector ----
        lf_kink = ttk.LabelFrame(plf, text=_("Kinkdetector"))
        lf_kink.pack(fill="x", padx=6, pady=6)
        add_field(lf_kink, "kinkangle_deg", "kinkangle_deg", _("折れ線近似の3点のなす角がこの値以下ならkink判定"))

        # ---- Save options ----
        # Placed outside the "解析条件" frame because save_original does not change
        # analysis results; it only controls whether the raw image is bundled.
        # save_original は解析結果を変えず元データ同梱の有無のみを制御するため、
        # 解析条件フレームの外に置く。
        lf_save = ttk.LabelFrame(self.inner, text=_("保存オプション"))
        lf_save.pack(fill="x", padx=6, pady=6)
        frm_so = ttk.Frame(lf_save)
        frm_so.pack(fill="x", pady=3)
        chk_so = ttk.Checkbutton(
            frm_so, text=_("解析時に元データを保存"),
            variable=self.save_original_var,
        )
        chk_so.pack(side="left", padx=6)
        ttk.Label(
            frm_so,
            text=_("ONのとき、背景補正前の元データも解析後の .b2z に original として同梱します（解析条件には含まれません）"),
            foreground="#444", justify="left",
        ).pack(side="left", padx=8, fill="x", expand=True)

        # JSON save/load uses the same schema as the per-analysis parameter sidecar.
        btns = ttk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=10, pady=10)
        ttk.Button(btns, text=_("OK"), command=self.on_ok).pack(side="right", padx=6)
        ttk.Button(btns, text=_("設定の保存"), command=self.on_save_settings).pack(side="right", padx=6)
        ttk.Button(btns, text=_("設定の読み込み"), command=self.on_load_settings).pack(side="right", padx=6)
        ttk.Button(btns, text=_("キャンセル"), command=self.on_cancel).pack(side="right")

        # Left-aligned defaults controls, separated from the right-aligned dialog actions.
        # 既定値操作は左寄せにし、右側のダイアログ操作と視覚的に分ける。
        ttk.Button(btns, text=_("現在値を既定値として保存"),
                   command=self.on_save_as_default).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text=_("初期値に戻す"),
                   command=self.on_reset_to_initial).pack(side="left", padx=6)


    # Parameter rows enabled for each bg_method; rows not listed are dimmed.
    _BG_PARAM_USAGE: Dict[str, set] = {
        "inpaint": {
            "threshold_factor", "fiber_detect_factor", "noise_detect_factor",
            "mask_dilation", "min_mask_component_area",
            "savgol_window", "savgol_polyorder",
        },
        "tophat": {
            "tophat_se_size",
            "savgol_window", "savgol_polyorder",
        },
        "spline1d": {
            "spline1d_axis", "spline1d_degree",
            "threshold_factor", "fiber_detect_factor", "noise_detect_factor",
            "mask_dilation", "min_mask_component_area",
            "savgol_window", "savgol_polyorder",
        },
        "spline2d": {
            "spline2d_degree", "spline2d_subsample",
            "threshold_factor", "fiber_detect_factor", "noise_detect_factor",
            "mask_dilation", "min_mask_component_area",
        },
    }
    # Method-independent post-processing stays enabled for every bg_method.
    _BG_ALWAYS_ON: set = {"apply_median"}

    def _set_row_enabled(self, key: str, enabled: bool) -> None:
        """
        Enable or disable one parameter row and its subdued text styling.
        1 パラメータ行の入力状態と淡色表示を切り替える。
        """
        row = self._param_rows.get(key)
        if not row:
            return
        inp = row["input"]
        if isinstance(inp, ttk.Combobox):
            inp.configure(state="readonly" if enabled else "disabled")
        else:
            inp.configure(state="normal" if enabled else "disabled")
        # Subdue labels as well as inputs so inactive rows are visually obvious.
        fg_lbl = "#000000" if enabled else "#999999"
        fg_desc = "#444444" if enabled else "#bbbbbb"
        try:
            row["label"].configure(foreground=fg_lbl)
            row["desc"].configure(foreground=fg_desc)
        except tk.TclError:
            pass

    def _on_bg_method_changed(self) -> None:
        """
        Dim parameter rows that are unused by the selected background method.
        選択中の背景推定方式で使わないパラメータ行をグレーアウトする。
        """
        method = self.vars["bg_method"].get()
        active = self._BG_PARAM_USAGE.get(method, set()) | self._BG_ALWAYS_ON
        managed = set().union(*self._BG_PARAM_USAGE.values()) | self._BG_ALWAYS_ON
        for key in managed:
            self._set_row_enabled(key, key in active)

    def _set_vars_from_dict(self, d: dict) -> None:
        """
        Copy dictionary values into matching tkinter variables.
        辞書の値を対応する tkinter 変数へ反映する。
        """
        for k, v in d.items():
            if k in self.vars:
                if isinstance(self.vars[k], tk.BooleanVar):
                    self.vars[k].set(bool(v))
                else:
                    self.vars[k].set(str(v))

    def _populate_from_refs(self) -> None:
        """
        Populate tkinter variables from the referenced parameters.
        参照中のパラメータから tkinter 変数へ値を反映する。
        """
        self._set_vars_from_dict(asdict(self.params_ref))

    def _apply_vars_to_refs(self) -> None:
        """
        Convert UI values and write them back to `params_ref`.
        UI 入力値を型変換し、`params_ref` へ反映する。
        """
        for f in fields(ProcParams):
            if f.name not in self.vars:
                continue
            raw = self.vars[f.name].get()
            if f.type is bool:
                setattr(self.params_ref, f.name, bool(raw))
            elif f.type is int:
                # Numeric entries are strings; float handles values like "12.0".
                setattr(self.params_ref, f.name, int(float(str(raw))))
            elif f.type is str:
                setattr(self.params_ref, f.name, str(raw))
            else:
                setattr(self.params_ref, f.name, float(str(raw)))

    def on_ok(self) -> None:
        """
        Commit dialog values to pending parameters and close the dialog.
        ダイアログの値を保留パラメータへ確定し、ダイアログを閉じる。
        """
        try:
            self._apply_vars_to_refs()
        except Exception as e:
            messagebox.showerror(_("エラー"), _("設定値の読み取りに失敗しました。\n%s") % e)
            return
        # Reflect the UI-only save_original choice back to the parent and persist it.
        # UI 専用の save_original 選択を親へ反映し、起動時設定へ保存する。
        on = bool(self.save_original_var.get())
        self.parent.save_original_var.set(on)
        self.parent._ui_settings["save_original"] = on
        save_ui_settings(self.parent._ui_settings)
        self.parent._log(_("設定を更新しました（次回解析時に反映）"))
        self.destroy()

    def on_cancel(self) -> None:
        """
        Close the dialog without committing staged edits.
        入力途中の編集を確定せずにダイアログを閉じる。
        """
        self.parent._log(_("設定変更をキャンセルしました"))
        self.destroy()

    def on_save_as_default(self) -> None:
        """
        Save current dialog values as startup defaults in afmpp_settings.json.
        現在のダイアログ値を起動時既定値として afmpp_settings.json へ保存する。

        Notes
        -----
        Analysis parameters are written at the top level; save_original is written
        to the _ui section. The existing _ui section is preserved otherwise.
        解析パラメータはトップレベル、save_original は _ui セクションへ書く。
        その他の _ui 内容は保持する。
        """
        if not messagebox.askyesno(
            _("確認"),
            _("現在のダイアログ値を起動時の既定値として保存します。\n"
              "起動時設定ファイルを上書きします。よろしいですか？"),
        ):
            return
        try:
            # Stage parameter values into params_ref, then serialize them.
            self._apply_vars_to_refs()
            params_dict = asdict(self.params_ref)
            on = bool(self.save_original_var.get())

            # Merge into the existing settings file: params at top level, UI under _ui.
            path = _settings_path()
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if not isinstance(existing, dict):
                    existing = {}
            else:
                existing = {}
            ui_section = existing.get(UI_SETTINGS_KEY, {})
            if not isinstance(ui_section, dict):
                ui_section = {}
            ui_section["save_original"] = on

            existing.update(params_dict)         # Overwrite ProcParams keys at top level.
            existing[UI_SETTINGS_KEY] = ui_section
            with open(path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)

            # Keep the running session consistent with what was just saved.
            self.parent._ui_settings["save_original"] = on
            self.parent.save_original_var.set(on)
            self.parent._log(_("現在値を既定値として保存しました: %s") % path)
        except Exception as e:
            messagebox.showerror(_("エラー"), _("既定値の保存に失敗しました。\n%s") % e)

    def on_reset_to_initial(self) -> None:
        """
        Reset dialog fields to the built-in initial values without writing files.
        ダイアログの値を組み込み初期値へ戻す。ファイルは書き換えない。

        Notes
        -----
        Parameters revert to ProcParams() defaults and save_original reverts to
        UI_DEFAULTS["save_original"] (OFF). The settings file is left untouched;
        use "現在値を既定値として保存" to persist.
        パラメータは ProcParams() 既定値、save_original は UI_DEFAULTS（OFF）へ戻す。
        設定ファイルは変更しない。永続化は「現在値を既定値として保存」で行う。
        """
        if not messagebox.askyesno(
            _("確認"),
            _("ダイアログの全パラメータと「元データを保存」を初期値に戻します。\n"
              "（この操作では設定ファイルは変更されません）\nよろしいですか？"),
        ):
            return
        # Reset only the on-screen variables; persistence is a separate explicit action.
        self._set_vars_from_dict(asdict(ProcParams()))
        self.save_original_var.set(bool(UI_DEFAULTS["save_original"]))
        self._on_bg_method_changed()
        self.parent._log(_("ダイアログを初期値に戻しました（未保存）"))

    def on_save_settings(self) -> None:
        """
        Save the current dialog parameters to a JSON file.
        現在のダイアログ上のパラメータを JSON ファイルへ保存する。
        """
        path = filedialog.asksaveasfilename(
            title=_("設定の保存（JSON）"),
            defaultextension=".json",
            initialdir=self.parent._default_save_dir(),
            initialfile="settings.json",
            filetypes=[(_("JSON"), "*.json")]
        )
        if not path:
            return
        try:
            self._apply_vars_to_refs()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.params_ref), f, ensure_ascii=False, indent=2)
            self.parent._log(_("設定を保存しました: %s") % path)
        except Exception as e:
            messagebox.showerror(_("エラー"), _("保存に失敗しました。\n%s") % e)

    def on_load_settings(self) -> None:
        """
        Load parameter values from a JSON file into the dialog.
        JSON ファイルからパラメータ値を読み込み、ダイアログへ反映する。
        """
        path = filedialog.askopenfilename(
            title=_("設定の読み込み（JSON）"),
            filetypes=[(_("JSON"), "*.json")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._set_vars_from_dict(d)
            self._on_bg_method_changed()
            self.parent._log(_("設定を読み込みました: %s") % path)
        except Exception as e:
            messagebox.showerror(_("エラー"), _("読み込みに失敗しました。\n%s") % e)
            
    def report_callback_exception(self, exc, val, tb):
        """
        Show and log tkinter callback exceptions raised by this dialog.
        本ダイアログの tkinter コールバック例外を表示し、ログへ記録する。
        """
        msg = "".join(traceback.format_exception(exc, val, tb))
        try:
            self._log(_("[Tkコールバック例外]\n") + msg)
        except Exception:
            pass
        messagebox.showerror(_("内部エラー"), str(val))


# ===== Single-file preview dialog =====
class SingleViewDialog(tk.Toplevel, UnconfirmedEntryMixin):
    """
    Display one analyzed file in a separate preview window.
    解析済みファイル 1 件を別ウィンドウで詳細表示する。

    Attributes
    ----------
    parent
        Main application window that owns the preview cache and shared settings.
        プレビューキャッシュと共通表示設定を保持するメインアプリケーションウィンドウ。
    item
        Analyzed file item displayed in this dialog.
        本ダイアログで表示する解析済みファイル項目。
    mode_var
        Display mode selected for the single image view.
        個別画像表示で選択される表示モード。
    vmin
        Lower contrast limit for calibrated images.
        補正済み画像の下限コントラスト値。
    vmax
        Upper contrast limit for calibrated images.
        補正済み画像の上限コントラスト値。

    Notes
    -----
    This dialog keeps its own vmin/vmax snapshot so multiple windows can be
    compared or exported with independent color ranges. That is useful for
    samples with different scan conditions or for figure-specific contrast
    adjustment.
    複数ウィンドウを独立した色域で比較・書き出しできるよう、本ダイアログは
    vmin/vmax のスナップショットを独自に保持する。スキャン条件の異なる試料や
    論文・発表 Figure 用のコントラスト調整で必要になるため。
    """
    def __init__(self, parent: App, item: FileItem) -> None:
        """
        Initialize the single-file preview dialog.
        個別ファイルプレビューダイアログを初期化する。
        """
        super().__init__(parent)
        self.parent = parent
        self.item = item

        self.title(_("個別表示: %s") % item.basename_stem)
        apply_window_size(self, 1100, 780, min_w=700, min_h=600)

        # Match the main window's clam background for visual consistency.
        try:
            clam_bg = getattr(parent, "_clam_bg", None)
            if clam_bg:
                self.configure(bg=clam_bg)
        except tk.TclError:
            pass

        # Open on calibrated data because it is the primary analysis result.
        self.mode_var = tk.StringVar(value="calibrated")
        # Start with the main preview's overlay and display settings.
        self.overlay_mode_var = tk.StringVar(value=parent.overlay_mode_var.get())
        self.show_scale_var = tk.BooleanVar(value=parent.show_scale_var.get())
        self.show_title_var = tk.BooleanVar(value=parent.show_title_var.get())

        # Font-size entries stage text separately from committed drawing values.
        self.fs_title:  float = float(parent.fs_title)
        self.fs_cbar:   float = float(PLOT_FS_DEFAULTS["cbar_fs"])
        self.fs_label:  float = float(parent.fs_label)
        self.fs_tick:   float = float(parent.fs_tick)
        self.fs_legend: float = float(parent.fs_legend)

        self.title_fs_var  = tk.StringVar(value=parent._fmt_num(self.fs_title))
        self.cbar_fs_var   = tk.StringVar(value=parent._fmt_num(self.fs_cbar))
        self.label_fs_var  = tk.StringVar(value=parent._fmt_num(self.fs_label))
        self.ext_fs_var    = tk.StringVar(value=parent._fmt_num(self.fs_tick))
        self.legend_fs_var = tk.StringVar(value=parent._fmt_num(self.fs_legend))

        # The unit selector starts from the main preview's current unit.
        self.unit_var = tk.StringVar(value=parent.unit_var.get())

        # Snapshot vmin/vmax so this dialog can be adjusted independently.
        self.vmin: float = float(parent.vmin)
        self.vmax: float = float(parent.vmax)
        self.vmin_var = tk.StringVar(value=parent._fmt_num(self.vmin))
        self.vmax_var = tk.StringVar(value=parent._fmt_num(self.vmax))

        # Use a separate unconfirmed-entry registry from the main window.
        self._init_unconfirmed_registry()

        self._build_ui()

        # constrained_layout keeps export and screen layout consistent.
        self.fig = plt.Figure(figsize=(7.5, 6.4), dpi=110, constrained_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.view_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self._cbar = None
        self._draw()

        self._update_epbp_state()
        self._update_vrange_state()

    def _build_ui(self) -> None:
        """
        Build controls and the frame that receives the matplotlib canvas.
        操作部と matplotlib キャンバスを配置するフレームを構築する。
        """
        # Controls are split into two compact rows above the figure.
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=8, pady=(6, 2))

        ttk.Label(top, text=_("表示")).pack(side="left", padx=(2, 2))
        self.cmb_mode = ttk.Combobox(
            top, width=14, textvariable=self.mode_var,
            values=["original", "calibrated", "binarized", "skeletonized"],
            state="readonly"
        )
        self.cmb_mode.pack(side="left", padx=2)
        self.cmb_mode.bind("<<ComboboxSelected>>", lambda e: self._on_mode_changed())

        # Overlay selection is used only for the skeletonized view.
        lbl_overlay = ttk.Label(top, text=_("重ね表示"))
        lbl_overlay.pack(side="left", padx=(10, 2))
        self.cmb_overlay = ttk.Combobox(
            top, width=10, textvariable=self.overlay_mode_var,
            values=[_("非表示"), "EP", "BP", "KP", "DP"],
            state="readonly"
        )
        self.cmb_overlay.pack(side="left", padx=2)
        self.cmb_overlay.bind("<<ComboboxSelected>>", lambda e: self._draw())

        # Explain abbreviated feature names in a tooltip.
        overlay_help = (
            _("Skeletonized 画像に重ねる特徴点の種類を選択します。") + "\n"
            "  " + _("非表示") + "           : " + _("重ね描きしません") + "\n"
            "  EP (End Point)     : " + _("ファイバーの端点（青）")          + "\n"
            "  BP (Branch Point)  : " + _("ファイバーの分岐点（赤）")        + "\n"
            "  KP (Kink Point)    : " + _("ファイバーのキンク点（シアン）")  + "\n"
            "  DP (Decomposed Point) : " + _("ファイバーの分解点（オレンジ）")
        )
        ToolTip(lbl_overlay, overlay_help)

        ttk.Checkbutton(top, text=_("スケール表示"), variable=self.show_scale_var, command=self._draw).pack(side="left", padx=10)

        # Use radiobuttons because there are only two axis-unit choices.
        ttk.Label(top, text=_("軸目盛単位")).pack(side="left", padx=(10, 2))
        ttk.Radiobutton(
            top, text="µm", value="µm",
            variable=self.unit_var, command=self._draw,
        ).pack(side="left", padx=(0, 2))
        ttk.Radiobutton(
            top, text="nm", value="nm",
            variable=self.unit_var, command=self._draw,
        ).pack(side="left", padx=(0, 2))

        # vmin/vmax is meaningful only for calibrated display mode.
        ttk.Label(top, text=_("vmin")).pack(side="left", padx=(14, 2))
        self.ent_vmin = ttk.Entry(top, width=7, textvariable=self.vmin_var)
        self.ent_vmin.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_vmin,
            lambda: self.parent._fmt_num(self.vmin),
            self.validate_dialog_vrange,
            registry=self._unconfirmed_entries,
        )
        ttk.Label(top, text=_("vmax")).pack(side="left", padx=(6, 2))
        self.ent_vmax = ttk.Entry(top, width=7, textvariable=self.vmax_var)
        self.ent_vmax.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_vmax,
            lambda: self.parent._fmt_num(self.vmax),
            self.validate_dialog_vrange,
            registry=self._unconfirmed_entries,
        )

        ttk.Button(top, text=_("画像を保存"), command=self._export).pack(side="left", padx=10)

        # Font-size entries share one Enter-to-commit registry.
        bottom = ttk.Frame(self)
        bottom.pack(side="top", fill="x", padx=8, pady=(0, 4))

        ttk.Checkbutton(bottom, text=_("タイトル表示"), variable=self.show_title_var, command=self._draw).pack(side="left", padx=(2, 4))

        ttk.Label(bottom, text=_("フォントサイズ：タイトル")).pack(side="left", padx=(2, 2))
        self.ent_title_fs = ttk.Entry(bottom, width=5, textvariable=self.title_fs_var)
        self.ent_title_fs.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_title_fs,
            lambda: self.parent._fmt_num(self.fs_title),
            self.validate_dialog_font_sizes,
            registry=self._unconfirmed_entries,
        )

        ttk.Label(bottom, text=_("カラーバー")).pack(side="left", padx=(10, 2))
        self.ent_cbar_fs = ttk.Entry(bottom, width=5, textvariable=self.cbar_fs_var)
        self.ent_cbar_fs.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_cbar_fs,
            lambda: self.parent._fmt_num(self.fs_cbar),
            self.validate_dialog_font_sizes,
            registry=self._unconfirmed_entries,
        )

        ttk.Label(bottom, text=_("軸ラベル")).pack(side="left", padx=(10, 2))
        self.ent_label_fs = ttk.Entry(bottom, width=5, textvariable=self.label_fs_var)
        self.ent_label_fs.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_label_fs,
            lambda: self.parent._fmt_num(self.fs_label),
            self.validate_dialog_font_sizes,
            registry=self._unconfirmed_entries,
        )

        ttk.Label(bottom, text=_("軸目盛")).pack(side="left", padx=(10, 2))
        self.ent_ext_fs = ttk.Entry(bottom, width=5, textvariable=self.ext_fs_var)
        self.ent_ext_fs.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_ext_fs,
            lambda: self.parent._fmt_num(self.fs_tick),
            self.validate_dialog_font_sizes,
            registry=self._unconfirmed_entries,
        )

        ttk.Label(bottom, text=_("凡例")).pack(side="left", padx=(10, 2))
        self.ent_legend_fs = ttk.Entry(bottom, width=5, textvariable=self.legend_fs_var)
        self.ent_legend_fs.pack(side="left", padx=2)
        self.parent._register_unconfirmed_entry(
            self.ent_legend_fs,
            lambda: self.parent._fmt_num(self.fs_legend),
            self.validate_dialog_font_sizes,
            registry=self._unconfirmed_entries,
        )

        # FigureCanvasTkAgg is attached here after _build_ui returns.
        self.view_frame = ttk.Frame(self)
        self.view_frame.pack(fill="both", expand=True, padx=8, pady=8)

    def validate_dialog_font_sizes(self):
        """
        Validate and commit all single-view font-size fields together.
        個別表示ダイアログのフォントサイズ入力欄をまとめて検証・確定する。

        Returns
        -------
        bool
            True if all font sizes were committed; False if validation failed.
            全フォントサイズを確定できた場合は True、不正値なら False。
        """
        keys = ("fs_title", "fs_cbar", "fs_label", "fs_tick", "fs_legend")
        return self._commit_float_fields(
            [
                (self.ent_title_fs,  "fs_title",  "title"),
                (self.ent_cbar_fs,   "fs_cbar",   "cbar"),
                (self.ent_label_fs,  "fs_label",  "label"),
                (self.ent_ext_fs,    "fs_tick",   "tick"),
                (self.ent_legend_fs, "fs_legend", "legend"),
            ],
            validator=lambda v: None if all(1 <= v[k] <= 60 for k in keys)
            else _("フォントサイズは 1〜60 の範囲で入力してください"),
            on_success=self._draw,
        )

    def validate_dialog_vrange(self):
        """
        Validate and commit the single-view vmin/vmax fields together.
        個別表示ダイアログの vmin/vmax 入力欄をまとめて検証・確定する。

        Returns
        -------
        bool
            True if both values were committed; False if validation failed.
            両方の値を確定できた場合は True、不正値なら False。

        Notes
        -----
        The dialog keeps these values independently from the main preview.
        本ダイアログはこれらの値をメインプレビューとは独立に保持する。
        """
        return self._commit_float_fields(
            [
                (self.ent_vmin, "vmin", "vmin"),
                (self.ent_vmax, "vmax", "vmax"),
            ],
            validator=lambda v: None if v["vmax"] >= v["vmin"]
            else _("vmin は vmax 以下にしてください"),
            on_success=self._draw,
        )
    def _on_mode_changed(self) -> None:
        """
        Refresh dependent controls and redraw after the display mode changes.
        表示モード変更後に関連操作部を更新し、再描画する。
        """
        # Mode changes can affect both overlay and contrast controls.
        self._update_epbp_state()
        self._update_vrange_state()
        self._draw()

    def _update_epbp_state(self) -> None:
        """
        Enable feature overlays only for skeletonized display mode.
        細線化画像表示モードでのみ特徴点重ね表示を有効にする。
        """
        # Feature overlays apply only to skeletonized images.
        if self.mode_var.get() == "skeletonized":
            self.cmb_overlay.configure(state="readonly")
        else:
            self.cmb_overlay.configure(state="disabled")

    def _update_vrange_state(self) -> None:
        """
        Enable contrast fields only when calibrated data is displayed.
        補正済みデータ表示時のみコントラスト入力欄を有効にする。
        """
        # Gray out vmin/vmax when they do not affect the selected mode.
        state = "normal" if self.mode_var.get() == "calibrated" else "disabled"
        self.ent_vmin.configure(state=state)
        self.ent_vmax.configure(state=state)

    def _load_data(self) -> Optional[Dict[str, np.ndarray]]:
        """
        Return processed arrays for this dialog, reusing parent cache when possible.
        可能な場合は親のキャッシュを再利用し、本ダイアログ用の処理済み配列を返す。
        """
        # Reuse the parent's preview cache when this dialog targets the same item.
        if (
            self.parent._current_item is self.item
            and self.parent._current_data is not None
        ):
            return self.parent._current_data
        return self.parent._ensure_current_data(self.item)

    def _draw(self) -> None:
        """
        Draw the selected image and optional feature overlay.
        選択画像と任意の特徴点重ね表示を描画する。
        """
        data = self._load_data()
        if not data:
            return

        mode = self.mode_var.get()   # "original" / "calibrated" / "binarized" / "skeletonized"
        img = data[mode]

        # Remove the previous colorbar so redraws do not accumulate axes.
        if self._cbar is not None:
            try:
                self._cbar.remove()
            except Exception:
                pass
            self._cbar = None

        self.ax.clear()

        # Use committed values while Entry text may still be unconfirmed.
        tfs   = self.fs_title
        cfs   = self.fs_cbar
        lblfs = self.fs_label
        tkfs  = self.fs_tick
        legfs = self.fs_legend

        # Axis extent and units.
        show_scale = self.show_scale_var.get()
        unit = self.unit_var.get()
        # Scan size is view metadata, so it comes from the main preview setting.
        actual_um = float(self.parent.scale_um)

        if unit == "nm":
            scale = actual_um * 1000.0
            unit_label = "nm"
        else:
            scale = actual_um
            unit_label = "µm"

        extent = None
        if show_scale:
            # extent converts imshow from pixel coordinates to physical scale.
            extent = [0, scale, 0, scale]
            self.ax.set_xlabel("({0})".format(unit_label))
            self.ax.set_ylabel("({0})".format(unit_label))
            self.ax.tick_params(labelsize=tkfs)
            self.ax.xaxis.label.set_size(lblfs)
            self.ax.yaxis.label.set_size(lblfs)
        else:
            self.ax.axis("off")

        # Calibrated mode uses this dialog's independent vmin/vmax.
        cmap = "gray" if mode in ("binarized", "skeletonized") else "afmhot"
        if mode == "calibrated":
            im = self.ax.imshow(
                img, cmap=cmap, extent=extent,
                vmin=self.vmin, vmax=self.vmax,
            )
        else:
            im = self.ax.imshow(img, cmap=cmap, extent=extent)

        # Overlay coordinates use the same pixel-to-physical scaling as imshow.
        if extent is not None:
            h, w = img.shape[:2]
            sx = (extent[1] - extent[0]) / max(w - 1, 1)
            sy = (extent[3] - extent[2]) / max(h - 1, 1)
        else:
            sx, sy = 1.0, 1.0

        # Draw one selected feature overlay on skeletonized images.
        overlay = self.overlay_mode_var.get()
        if mode == "skeletonized" and overlay in ("EP", "BP", "KP", "DP"):
            if overlay == "EP":
                ep = data["ep"].astype(bool)
                end_y, end_x = np.where(ep)
                self.ax.scatter(end_x * sx, end_y * sy, c="blue", s=10, label="EP")
            elif overlay == "BP":
                bp = data["bp"].astype(bool)
                br_y, br_x = np.where(bp)
                self.ax.scatter(br_x * sx, br_y * sy, c="red", s=10, label="BP")
            elif overlay == "KP":
                kp = data["kp"]   # shape: (2, N_kink)
                if kp.shape[1] > 0:
                    self.ax.scatter(kp[0] * sx, kp[1] * sy, c="cyan", s=15, label="KP")
            elif overlay == "DP":
                dp = data["dp"]   # shape: (2, N_dp)
                if dp.shape[1] > 0:
                    self.ax.scatter(dp[0] * sx, dp[1] * sy, c="orange", s=8, label="DP")

            # Show a legend only when an overlay is visible.
            self.ax.legend(
                loc="center left", bbox_to_anchor=(1.02, 0.5),
                borderaxespad=0.0, fontsize=legfs,
            )

        # Add a colorbar only for continuous-height images.
        if mode in ("original", "calibrated"):
            self._cbar = self.fig.colorbar(im, ax=self.ax, fraction=0.046, pad=0.04)
            self._cbar.ax.tick_params(labelsize=cfs)
            # Keep the historical colorbar unit label for compatibility.
            self._cbar.set_label("(µm)", fontsize=cfs)

        if self.show_title_var.get():
            self.ax.set_title(f"{self.item.basename_stem}_{mode}", fontsize=tfs)

        self.canvas.draw_idle()

    def _export(self) -> None:
        """
        Save the current single-view figure through a file dialog.
        現在の個別表示図をファイルダイアログ経由で保存する。
        """
        mode = self.mode_var.get()
        save_figure_with_dialog(
            self, self.fig,
            initial_name=f"{self.item.basename_stem}_{mode}.png",
            initial_dir=self.parent._default_save_dir(),
            title=_("個別表示画像を保存"),
            log_cb=self.parent._log,
        )


def main() -> None:
    """
    Start the image preprocessor GUI application.
    画像前処理 GUI アプリケーションを起動する。
    """
    app = App()
    app.mainloop()


# Run the GUI only when this module is executed as a script.
if __name__ == "__main__":
    main()
