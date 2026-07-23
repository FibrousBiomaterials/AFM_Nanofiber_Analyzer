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
        "・バックグラウンド補正（lib/bg_calibrator.py）\n"
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
import csv
import json
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
# tksheet provides the Excel-like editable grid used for the file table
# (per-cell editing, read-only columns, clipboard paste from spreadsheets),
# which plain ttk.Treeview cannot offer (no per-cell widgets or styling).
# tksheet はファイル表に使う Excel 風の編集可能グリッド（セル単位編集・
# 読み取り専用列・表計算ソフトからの貼り付け）を提供する。ttk.Treeview は
# セル単位のウィジェットや装飾を持たないため、この仕様を実現できない。
from tksheet import Sheet

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")   # Embed matplotlib figures in tkinter windows.
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ===== Project libraries =====
# lib.pipeline drives the AFM preprocessing pipeline shared with the CLI;
# this GUI only adds batch policy (skip/overwrite/stop) and UI reporting.
# lib.pipeline が CLI と共通の前処理パイプラインを駆動する。本 GUI は
# バッチ方針（スキップ/上書き/停止）と UI 表示のみを担当する。
from lib.pipeline import (
    ProcParams, PipelineStages, STAGE_KEYS, build_stages, process_file,
    bundle_path_for, existing_min_set, merge_params_dict, validate_params,
)
from lib.blosc2_io import bundle_has_keys, load_bundle, load_bundle_meta
from lib.bundle_schema import (
    SCAN_SIZE_SOURCES, SPATIAL_CALIBRATION_KEY, scan_size_um_from_meta,
)
from lib.afm_io import load_afm_image, read_scan_size
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, ToolTip, setup_matplotlib_style,
    save_figure_with_dialog, PLOT_FS_DEFAULTS, setup_ttk_theme,
    save_text_widget_log,
    create_scrolled_text, drain_ui_queue,
    rewrite_entries, mark_entry_state,
    UnconfirmedEntryMixin, LogMixin,
)

# ===== Internal status keys; do not translate these identifiers. =====
# Keep internal state in fixed English keys and translate only for display.
# 内部状態は固定の英語キーで管理し、表示時のみ _() を通して翻訳する。
STATUS_PENDING  = "pending"    # Not analyzed.
STATUS_RUNNING  = "running"    # Analysis in progress.
STATUS_ANALYZED = "analyzed"   # Analysis complete.

# ===== File-table column layout =====
# Fixed column order of the tksheet file table; rows are append-only and the
# table is only cleared wholesale, so the row index doubles as the row id.
# tksheet ファイル表の固定列順。行は追記のみで表は全消去のみのため、
# 行インデックスがそのまま行 ID を兼ねる。
COL_NAME, COL_X, COL_Y, COL_STATUS, COL_TIME = range(5)
# Only the X/Y scan-size columns accept user edits; the rest are read-only.
# ユーザーが編集できるのは X/Y 走査範囲列のみで、残りは読み取り専用。
SCALE_COLS = (COL_X, COL_Y)
READONLY_COLS = (COL_NAME, COL_STATUS, COL_TIME)


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
        Translated label for the file table, or the input value if unknown.
        ファイル表用の翻訳済みラベル。不明な値は入力値をそのまま返す。
    """
    return {
        STATUS_PENDING:  _("未解析"),
        STATUS_RUNNING:  _("解析中"),
        STATUS_ANALYZED: _("解析済み"),
    }.get(status, status)


def stage_label(stage: str) -> str:
    """
    Convert a pipeline stage key from `lib.pipeline` to a translated label.
    `lib.pipeline` のステージキーを翻訳済みの表示ラベルへ変換する。

    Parameters
    ----------
    stage
        One of `lib.pipeline.STAGE_KEYS`.
        `lib.pipeline.STAGE_KEYS` のいずれかの値。

    Returns
    -------
    str
        Translated progress label, or the input value if unknown.
        翻訳済みの進捗ラベル。不明な値は入力値をそのまま返す。
    """
    return {
        "load":        _("読み込み"),
        "bg":          _("BG補正"),
        "binarize":    _("二値化/成分処理"),
        "skeletonize": _("細線化"),
        "kink":        _("kink検出"),
        "save":        _("保存"),
    }.get(stage, stage)


# ===== Settings =====
# `ProcParams` (the analysis-parameter schema) lives in lib/pipeline.py so the
# GUI and the CLI share one definition; this file keeps only UI-state settings.
# 解析パラメータスキーマ `ProcParams` は GUI と CLI で定義を共有するため
# lib/pipeline.py にあり、このファイルは UI 状態の設定のみを持つ。

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

        # Missing/unknown-key reconciliation is shared with the CLI through
        # lib.pipeline; this function only translates the reports for the UI.
        # 欠損・未知キーの整合処理は lib.pipeline 経由で CLI と共有し、
        # この関数は UI 向けの翻訳メッセージ化のみを行う。
        params, missing, obsolete = merge_params_dict(d)
        if missing:
            logs.append(_("起動時設定ファイルに不足キーがありました（デフォルトで補完）: %s")
                        % ", ".join(missing))
        if obsolete:
            logs.append(_("起動時設定ファイルに使われていないキーがありました（無視）: %s")
                        % ", ".join(obsolete))

        # Reuse the same key layout as the per-analysis parameter JSON.
        return params, logs

    except Exception as e:
        logs.append(_("起動時設定ファイルの読み込みに失敗しました（デフォルトにフォールバック）: %s") % e)
        return default_params, logs


@dataclass
class FileItem:
    """
    Track one input file and its analysis state.
    1 つの入力ファイルと解析状態を保持する。

    Attributes
    ----------
    txt_path
        Absolute path to the input file: a text/CSV export or a Gwyddion native
        `.gwy` file. The field name is retained for compatibility.
        入力ファイルの絶対パス。テキスト/CSV エクスポートまたは Gwyddion
        ネイティブ `.gwy` ファイル。フィールド名は互換性のため維持する。
    status
        Internal analysis status key.
        解析状態を表す内部キー。
    proc_time_s
        Processing time formatted for display.
        表示用に整形した処理時間。
    missing_reason
        Reason why an expected analysis output is missing.
        期待される解析出力が欠損している理由。
    scale_x_um, scale_y_um
        Per-file physical scan size in micrometers, stored in the bundle so
        length measurements are reproducible. ``None`` means the scan size is
        not yet known (no header value and no manual/manifest entry).
        ファイル単位の物理走査範囲 (µm)。長さ計測を再現可能にするためバンドルへ
        保存する。``None`` は走査範囲が未確定（ヘッダ値も手入力/マニフェスト値も
        無い）であることを表す。
    scale_source
        Provenance of the scan size: ``""`` (unset) or one of
        `SCAN_SIZE_SOURCES` (``input_header`` / ``manifest`` / ``manual``).
        走査範囲の出所。``""``（未設定）または `SCAN_SIZE_SOURCES`
        （``input_header`` / ``manifest`` / ``manual``）のいずれか。
    """

    txt_path: str
    status: str = STATUS_PENDING
    proc_time_s: str = ""
    missing_reason: str = ""
    scale_x_um: Optional[float] = None
    scale_y_um: Optional[float] = None
    scale_source: str = ""

    @property
    def has_scale(self) -> bool:
        """
        Return whether a positive per-axis scan size is set.
        軸ごとの正の走査範囲が設定されているかを返す。
        """
        return (
            self.scale_x_um is not None and self.scale_y_um is not None
            and self.scale_x_um > 0 and self.scale_y_um > 0
        )

    @property
    def scale_x_display(self) -> str:
        """
        Format the X (width) scan size for the file table.
        ファイル表向けに X（幅）走査範囲を整形する。

        An unset size shows an empty cell; in the spreadsheet-style table an
        empty editable cell reads as "fill me in".
        未設定時は空セルを表示する。表計算風の表では空の編集可能セルが
        「ここに入力する」ことを自然に伝える。
        """
        return "" if self.scale_x_um is None else f"{self.scale_x_um:g}"

    @property
    def scale_y_display(self) -> str:
        """
        Format the Y (height) scan size for the file table.
        ファイル表向けに Y（高さ）走査範囲を整形する。

        Notes
        -----
        An unset Y shows ``= X`` so first-time users read a blank Y as
        "Y follows X" (square scan); non-square scans (e.g. Shimadzu
        SizeX != SizeY) simply show different numbers in the two columns.
        Cell edit validation accepts ``= X`` (and an empty cell) as "unset".
        未設定の Y は ``= X`` と表示し、初見のユーザーが空の Y を「Y は X に
        従う」（正方スキャン）と読めるようにする。非正方走査（島津の
        SizeX != SizeY 等）は 2 列に異なる数値が表示されるだけである。セル編集
        の検証は ``= X``（および空セル）を「未設定」として受理する。
        """
        return "= X" if self.scale_y_um is None else f"{self.scale_y_um:g}"

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


# The .b2z bundle key contract (REQUIRED_BUNDLE_KEYS / OPTIONAL_BUNDLE_KEYS)
# and the analyzed-state check `existing_min_set` live in lib/pipeline.py.
# .b2z バンドルのキー契約（REQUIRED_BUNDLE_KEYS / OPTIONAL_BUNDLE_KEYS）と
# 解析済み判定 `existing_min_set` は lib/pipeline.py にある。


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
        # Row ids are the tksheet row indices (append-only table, see COL_*).
        # 行 ID は tksheet の行インデックス（追記のみの表。COL_* を参照）。
        self.item_by_iid: Dict[int, FileItem] = {}
        self.iid_by_path: Dict[str, int] = {}

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
        # scale_um is the X (width) size; scale_y_um is the optional Y (height)
        # size for rectangular scans. None means "same as X" (square scan).
        # scale_um は X（幅）サイズ、scale_y_um は矩形スキャン用の任意の Y（高さ）
        # サイズ。None は「X と同値」（正方スキャン）を意味する。
        self.scale_um: float = 2.0
        self.scale_um_var = tk.StringVar(value=self._fmt_num(self.scale_um))
        self.scale_y_um: Optional[float] = None
        self.scale_y_um_var = tk.StringVar(value="")

        # Guard for programmatic sheet writes: _refresh_tree_row and friends
        # set this so _on_sheet_modified only reacts to user-driven edits.
        # プログラムからのシート書き込み用ガード。_refresh_tree_row 等が設定し、
        # _on_sheet_modified がユーザー操作による編集にのみ反応するようにする。
        self._sheet_syncing = False
        # Row shown in the preview and the pending-idle-redraw flag; preview
        # reloads are deferred to idle time so cell editing stays responsive.
        # プレビュー表示中の行とアイドル再描画の保留フラグ。プレビュー再読込を
        # アイドル時へ遅延させ、セル編集の応答性を保つ。
        self._preview_row: Optional[int] = None
        self._preview_redraw_pending = False

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

        # ===== Preview data cache =====
        # Reload bundles only when the selected file or bundle mtime changes.
        self._current_item: Optional[FileItem] = None
        self._current_data: Optional[Dict[str, np.ndarray]] = None
        self._current_mtime: float = 0.0
        # Scan size recorded in the cached bundle's vlmeta (spatial_calibration),
        # or None when the bundle predates that metadata.
        # キャッシュ中バンドルの vlmeta（spatial_calibration）に記録された走査範囲。
        # メタデータ導入前のバンドルでは None。
        self._current_scan_size_um: Optional[Tuple[float, float]] = None

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
        list_header = ttk.Frame(list_frame)
        list_header.pack(side="top", fill="x", padx=2, pady=(0, 2))
        ttk.Label(list_header, text=_("ファイル一覧")).pack(side="left", anchor="w")
        # Discoverability hint: the X/Y scale cells are edited directly in the
        # spreadsheet-style table, and clipboard paste from Excel-like tools is
        # supported.
        # 発見性のヒント：X/Y スケールセルは表計算風の表で直接編集でき、Excel 等
        # からのクリップボード貼り付けにも対応する。
        ttk.Label(
            list_header,
            text=_("X / Y セルは直接入力・Excel から貼り付け可"),
            foreground="#8a8a8a",
        ).pack(side="left", padx=(8, 0))

        # Inner frame hosts the spreadsheet-style file table.
        list_inner = ttk.Frame(list_frame)
        list_inner.pack(fill="both", expand=True)

        # Excel-like file table (tksheet): X/Y scan-size cells are white and
        # editable in place; the other columns are gray and read-only. Editing
        # follows spreadsheet conventions (click + type, double-click, F2,
        # Ctrl+C/V/Z), so first-time users can reuse Excel habits, including
        # pasting X/Y columns copied from a spreadsheet.
        # Excel 風のファイル表（tksheet）。X/Y 走査範囲セルは白色でその場編集
        # でき、他の列は灰色の読み取り専用。編集は表計算ソフトの流儀
        # （クリック＋入力、ダブルクリック、F2、Ctrl+C/V/Z）に従うため、初見の
        # ユーザーも Excel の操作感をそのまま使える。表計算ソフトからコピーした
        # X/Y 列の貼り付けにも対応する。
        self.sheet = Sheet(
            list_inner,
            headers=[
                _("ファイル名"),
                # Axis names with units are fixed scientific labels (§6.2),
                # so the X/Y headings are not wrapped in _().
                # 軸名＋単位は固定の科学ラベル（§6.2）なので X/Y 見出しは
                # _() で包まない。
                "X (µm)",
                "Y (µm)",
                _("状態"),
                _("処理時間") + " (s)",
            ],
            show_row_index=False,
            height=300,
            # Committing an edit with Enter stays on the same cell instead of
            # jumping down, so editing one file's scale does not move focus to
            # the next file unexpectedly; the user picks the next cell to edit.
            # Enter による確定は下のセルへ飛ばずその場に留まる。あるファイルの
            # スケールを編集してもフォーカスが次のファイルへ勝手に移らず、次に
            # 編集するセルはユーザーが選ぶ。
            edit_cell_return="",
            # No blank scrollable strip after the last column; the file-name
            # column is then sized to the exact remaining table width by
            # _fit_name_column, so the columns always fill the table precisely.
            # The stretch column is the NAME column (Explorer-style), not the
            # last one: left-aligned names make its spare width read as normal,
            # whereas spare width in a trailing numeric column reads as a
            # blank margin.
            # 最終列の右にスクロール可能な空白帯を作らない。ファイル名列は
            # _fit_name_column がテーブルの残り幅ちょうどに合わせるため、列は
            # 常にテーブル幅を正確に埋める。伸ばす列は（エクスプローラ式に）
            # 最終列ではなくファイル名列とする。左寄せのファイル名では余り幅が
            # 自然に見えるのに対し、末尾の数値列の余り幅は空白の余白に見えて
            # しまうためである。
            empty_horizontal=0,
        )
        self.sheet.pack(fill="both", expand=True)
        # Selection, in-cell editing, clipboard, and right-click menu bindings.
        # "single_select" makes a plain click REPLACE the previous selection
        # (do not add "toggle_select": tksheet applies the last-listed mode, and
        # toggle mode accumulates selections so earlier clicks never deselect);
        # Ctrl+click / drag extend the selection for the batch actions.
        # "cut" is deliberately not enabled: cutting an X cell would clear a
        # required value, which validation rejects, so the command only confuses.
        # 選択・セル内編集・クリップボード・右クリックメニューのバインディング。
        # "single_select" により通常クリックは直前の選択を置き換える
        # （"toggle_select" を足さないこと：tksheet は後に書いたモードを採用し、
        # トグルモードは選択が蓄積して前のクリックが解除されなくなる）。
        # Ctrl＋クリックとドラッグが一括操作向けの複数選択を担う。
        # "cut" は意図的に無効：X セルの切り取りは必須値の消去となり検証で
        # 拒否されるため、コマンドがあっても混乱させるだけである。
        #
        # Manual column-width resizing is intentionally NOT enabled. The
        # numeric columns have fixed semantic widths and the file-name column
        # auto-fills the remaining table width (see _fit_name_column), so a
        # user drag has nothing useful to do and only fought the auto-fill
        # (dragging one separator appeared to move the other columns).
        # 手動の列幅リサイズは意図的に有効化しない。数値系の列は意味的に固定幅で、
        # ファイル名列がテーブルの残り幅を自動で埋める（_fit_name_column を参照）
        # ため、ユーザーのドラッグに有用な役割はなく、自動フィットと競合する
        # だけだった（ある境界をドラッグすると他の列が動いて見えた）。
        self.sheet.enable_bindings(
            "single_select", "row_select", "ctrl_select", "drag_select",
            "arrowkeys", "edit_cell", "copy", "paste", "delete", "undo",
            "right_click_popup_menu", "rc_select",
        )
        # Localize the tksheet right-click menu labels so they match the rest of
        # the (Japanese-primary) UI instead of tksheet's English defaults.
        # tksheet の右クリックメニューのラベルをローカライズし、tksheet の英語
        # 既定ではなく（日本語主体の）他の UI と揃える。
        self.sheet.set_options(
            edit_cell_label=_("セルを編集"),
            copy_label=_("コピー"),
            paste_label=_("貼り付け"),
            delete_label=_("削除"),
            undo_label=_("元に戻す"),
        )
        # A single left-click on an editable X/Y cell opens its editor right
        # away (same as the right-click "Edit cell" command), and the Delete
        # menu entry is pruned unless it applies (only a Y cell may be cleared).
        # 編集可能な X/Y セルはシングル左クリックで即座に編集欄を開く
        # （右クリックの「セルを編集」と同じ効果）。Delete メニュー項目は
        # 有効な場合（消去できるのは Y セルのみ）以外は取り除く。
        self.sheet.bind("<ButtonRelease-1>", self._on_sheet_click_release)
        self.sheet.bind("<3>", self._prune_rc_menu)
        # Fixed widths for all columns except the file name: the name column is
        # recomputed by _fit_name_column as the exact remainder of the table
        # width (its 300 px here is only the pre-layout fallback).
        # ファイル名以外は固定幅。ファイル名列は _fit_name_column がテーブル幅
        # の残りちょうどに再計算する（ここでの 300 px はレイアウト前の暫定値）。
        for col, width in (
            (COL_NAME, 300), (COL_X, 70), (COL_Y, 70),
            (COL_STATUS, 70), (COL_TIME, 100),
        ):
            self.sheet.column_width(col, width)
        # Keep the name column filling the table via a lightweight periodic
        # check instead of resize/redraw events. Every event-based trigger
        # tried here (Configure, debounced Configure, <<SheetRedrawn>>) raced
        # the window-maximize sizing: the fit fired while the canvas still
        # reported its old width and no later event re-ran it, leaving a wide
        # blank strip after the last column. Polling reads the *current* width
        # each tick, so it always converges within one interval of any size
        # change, regardless of event ordering. The check is idempotent (it
        # only resizes when the columns do not already fill the table), so it
        # costs a width comparison when nothing changed and never fights a
        # manual column drag.
        # リサイズ/再描画イベントではなく軽量な定期チェックでファイル名列を
        # テーブルに追従させる。ここで試したイベント方式（Configure、デバウンス
        # 付き Configure、<<SheetRedrawn>>）はいずれもウィンドウ最大化のサイズ
        # 確定と競合した。キャンバスがまだ旧幅を返している間にフィットが走り、
        # その後に再実行するイベントが来ないため、最終列の後に幅広の空白帯が
        # 残った。ポーリングは毎回*現在の*幅を読むので、イベント順序に関係なく
        # サイズ変化から 1 間隔以内に必ず収束する。チェックは冪等（列がすでに
        # テーブルを埋めていれば何もしない）なので、変化が無ければ幅比較のみで
        # 済み、手動の列ドラッグとも競合しない。
        self._fit_name_column()
        self.after(150, self._fit_name_loop)
        # Read-only columns are tinted gray so the editable white X/Y cells
        # stand out as input fields at rest, without hovering.
        # 読み取り専用列を灰色にし、編集可能な白い X/Y セルがホバーなしでも
        # 入力欄として浮き上がるようにする。
        self.sheet.readonly_columns(columns=list(READONLY_COLS), readonly=True)
        self.sheet.highlight_columns(
            columns=list(READONLY_COLS), bg="#efefef", fg="#444444",
        )
        # Every user-driven cell change (typing, paste, undo) passes through
        # validation first, then _on_sheet_modified syncs FileItem state.
        # ユーザー操作によるセル変更（入力・貼り付け・元に戻す）はまず検証を
        # 通り、その後 _on_sheet_modified が FileItem の状態と同期する。
        self.sheet.edit_validation(self._validate_sheet_edit)
        self.sheet.bind("<<SheetModified>>", self._on_sheet_modified)

        # Scale batch panel: assign the same scan size to the selected or all
        # files, or load per-file sizes from a CSV manifest. Per-file X/Y values
        # are edited in the table above; this panel only drives batch assignment
        # and, as a last resort, the preview fallback scale. Header/bundle values
        # are filled on load.
        # スケール一括パネル：同一の走査範囲を選択ファイルまたは全ファイルへ割り
        # 当てるか、CSV マニフェストからファイル単位のサイズを読み込む。ファイル
        # 単位の X/Y 値は上の表で編集する。本パネルは一括割り当てと、最終手段と
        # してのプレビューのフォールバックスケールのみを担う。ヘッダ/バンドル値は
        # 読み込み時に充填。
        # A borderless frame keeps the batch controls visually part of the file
        # table block; the apply buttons themselves explain what the entries do.
        # 枠なしフレームで一括操作をファイル表ブロックの一部として見せる。入力欄
        # の役割は適用ボタン自体が説明する。
        scale_frame = ttk.Frame(list_frame)
        scale_frame.pack(side="top", fill="x", padx=2, pady=(4, 0))

        scale_entry_row = ttk.Frame(scale_frame)
        scale_entry_row.pack(side="top", fill="x")
        # Axis names and the unit are fixed scientific labels (§6.2), so "X"/"Y"
        # and "µm" are not wrapped in _().
        # 軸名と単位は固定の科学ラベル（§6.2）なので "X"/"Y" と "µm" は _() で
        # 包まない。
        ttk.Label(scale_entry_row, text="X").pack(side="left")
        self.ent_scale_um = ttk.Entry(
            scale_entry_row, width=7, textvariable=self.scale_um_var,
        )
        self.ent_scale_um.pack(side="left", padx=(3, 2))
        ttk.Label(scale_entry_row, text="µm").pack(side="left", padx=(0, 12))
        self._register_unconfirmed_entry(
            self.ent_scale_um,
            lambda: self._fmt_num(self.scale_um),
            self.validate_scale_um,
        )
        ToolTip(
            self.ent_scale_um,
            _("AFM 画像の X（幅）方向の実寸") + " (µm)。\n"
            + _("プレビューの軸目盛と、ファイルへ適用したときの長さ計測の基準に使われる。"),
        )
        # Optional Y (height) size for rectangular scans; an empty Y means a
        # square scan (Y = X), reinforced by the "= X" ghost placeholder shown
        # while Y is blank.
        # 矩形スキャン用の任意の Y（高さ）サイズ。Y 空欄は正方スキャン（Y = X）
        # を意味し、Y が空のときに表示する "= X" ゴーストプレースホルダでも
        # それを補強する。
        ttk.Label(scale_entry_row, text="Y").pack(side="left")
        self.ent_scale_y_um = ttk.Entry(
            scale_entry_row, width=7, textvariable=self.scale_y_um_var,
        )
        self.ent_scale_y_um.pack(side="left", padx=(3, 2))
        ttk.Label(scale_entry_row, text="µm").pack(side="left")
        self._register_unconfirmed_entry(
            self.ent_scale_y_um,
            lambda: "" if self.scale_y_um is None
            else self._fmt_num(self.scale_y_um),
            self.validate_scale_y_um,
        )
        ToolTip(
            self.ent_scale_y_um,
            _("AFM 画像の Y（高さ）方向の実寸") + " (µm)。\n"
            + _("空欄なら X（幅）と同じ（正方スキャン）。"),
        )
        # Ghost placeholder overlaid on the empty Y field so first-time users
        # see that a blank Y means "Y = X" (square scan). It is a separate
        # Label placed on top of the Entry rather than inserted text, so
        # Entry.get() stays "" and the Enter-to-commit / validation machinery
        # keeps treating an untouched Y field as unset.
        # 空の Y 欄に重ねるゴーストプレースホルダ。空欄が「Y = X」（正方スキャン）
        # を意味することを初見のユーザーに伝える。入力テキストではなく Entry に
        # 重ねた別 Label なので Entry.get() は "" のままとなり、Enter 確定・検証
        # 機構は未入力の Y 欄を未設定として扱い続ける。
        field_bg = ttk.Style(self).lookup("TEntry", "fieldbackground") or "white"
        # Strip the Label border and internal padding so the ghost fits inside
        # the Entry field height and does not spill below it.
        # Label の枠と内側余白を除去し、ゴーストが Entry の高さに収まって
        # 下にはみ出さないようにする。
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

        # The apply / manifest buttons sit to the right of the X/Y entries on
        # the same row, so the whole batch control reads as one line.
        # 適用・マニフェスト読込ボタンは X/Y 入力欄の右・同じ行に置き、一括操作
        # 全体が 1 行として読めるようにする。
        self.btn_apply_scale_sel = ttk.Button(
            scale_entry_row, text=_("選択ファイルに適用"),
            command=lambda: self.on_apply_scale_to_rows(selected_only=True),
        )
        self.btn_apply_scale_sel.pack(side="left", padx=(12, 2))
        self.btn_apply_scale_all = ttk.Button(
            scale_entry_row, text=_("全ファイルに適用"),
            command=lambda: self.on_apply_scale_to_rows(selected_only=False),
        )
        self.btn_apply_scale_all.pack(side="left", padx=2)
        self.btn_load_manifest = ttk.Button(
            scale_entry_row, text=_("スケール表(CSV)読込"),
            command=self.on_load_scale_manifest,
        )
        self.btn_load_manifest.pack(side="left", padx=2)
        ToolTip(
            self.btn_apply_scale_sel,
            _("スケール入力欄の値を選択ファイルへ適用します。") + "\n"
            + _("ヘッダから取得できないファイルにスケールを与えるときに使います。"),
        )
        ToolTip(
            self.btn_load_manifest,
            _("ファイル名とスケールを対応付けた CSV を読み込みます。") + "\n"
            + _("列: filename, scale_um もしくは scale_x_um, scale_y_um。"),
        )

        # Left pane: log display.
        log_frame = ttk.Frame(self.left_frame)
        log_frame.pack(fill="both", expand=True, padx=4, pady=4)

        # Keep the log-save action attached to the log area instead of the global toolbar.
        log_header = ttk.Frame(log_frame)
        log_header.pack(side="top", fill="x", padx=2, pady=(0, 2))
        self.btn_save_log = ttk.Button(log_header, text=_("ログを保存"), command=self.on_save_log)
        self.btn_save_log.pack(side="left")
        self.btn_clear_log = ttk.Button(log_header, text=_("ログをクリア"), command=self._clear_log)
        self.btn_clear_log.pack(side="left", padx=(4, 0))

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

        # Green progress bar. The shared "clam" theme renders the bar from style
        # colors (unlike Windows native themes), so a custom style fill applies.
        # 緑色の進捗バー。共有テーマ "clam" はスタイル色でバーを描画するため
        # （Windows ネイティブテーマと異なり）塗り色の指定が反映される。
        ttk.Style(self).configure(
            "Green.Horizontal.TProgressbar", background="#28a745"
        )
        self.progressbar = ttk.Progressbar(
            prog_frame, mode="determinate", maximum=100,
            style="Green.Horizontal.TProgressbar",
        )
        self.progressbar.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.progress_detail_var = tk.StringVar(value=_("-"))
        ttk.Label(prog_frame, textvariable=self.progress_detail_var).pack(side="left", padx=(0, 4))

    @staticmethod
    def _parse_scale_y_text(text: str) -> Tuple[bool, Optional[float]]:
        """
        Parse a Y-cell string into (is_valid, value); ``None`` means "= X".
        Y セル文字列を (妥当か, 値) に解析する。``None`` は「= X」を意味する。

        An empty string and the literal ``= X`` display text (any spacing/case)
        are both accepted as "unset", so deleting the text and leaving the
        shown placeholder behave identically.
        空文字と表示文字列 ``= X``（空白・大文字小文字は不問）はどちらも
        「未設定」として受理する。文字を消しても、表示のままでも同じ挙動になる。
        """
        norm = text.replace(" ", "").lower()
        if norm in ("", "=x"):
            return True, None
        try:
            v = float(text)
        except ValueError:
            return False, None
        return (v > 0), (v if v > 0 else None)

    def _validate_sheet_edit(self, event) -> Optional[str]:
        """
        Validate one user cell edit (typing or paste) before it is applied.
        ユーザーのセル編集（入力・貼り付け）を適用前に 1 件ずつ検証する。

        Returns
        -------
        str or None
            The accepted text, or ``None`` to reject the edit and keep the
            previous cell value. Rejection rings the bell instead of raising a
            dialog so a paste with some bad cells is not interrupted per cell.
            受理するテキスト。``None`` は編集を拒否して元のセル値を保つ。拒否は
            ダイアログではなくベル音で知らせ、一部に不正セルを含む貼り付けが
            セルごとに中断されないようにする。
        """
        # The table is frozen while a batch run is using the file list.
        # 一括処理がファイル一覧を使用中は表を凍結する。
        if self.is_running:
            return None
        row, col = event.row, event.column
        if col not in SCALE_COLS or row not in self.item_by_iid:
            return None
        text = "" if event.value is None else str(event.value).strip()
        if col == COL_Y:
            ok, _v = self._parse_scale_y_text(text)
            if not ok:
                self.bell()
                return None
            return text
        # X requires a positive number; an empty X stays rejected because a
        # file with no width scale cannot be measured.
        # X は正の数が必須。幅スケールの無いファイルは計測できないため、空の X
        # は拒否のままとする。
        try:
            v = float(text)
        except ValueError:
            self.bell()
            return None
        if not v > 0:
            self.bell()
            return None
        return text

    def _on_sheet_click_release(self, _event=None) -> None:
        """
        Open the cell editor right after a single click on an X/Y cell.
        X/Y セルのシングルクリック直後にセル編集欄を開く。

        Bound to the sheet's Button-1 release hook. Mouse-only by design:
        arrow-key navigation must not auto-open editors, or the arrow keys
        would get captured by the editor and navigation would become
        impossible.
        シートの Button-1 リリースフックに束縛する。意図的にマウス限定とする：
        矢印キーでの移動時に編集欄が自動で開くと、矢印キーが編集欄に奪われて
        移動できなくなるためである。
        """
        # Defer the open past the events still queued for this click: tksheet
        # reuses a single editor widget, and when this click just closed a
        # previous editor, that widget's pending <FocusOut> would fire after
        # this handler and instantly close an editor opened synchronously here.
        # At idle time the stale <FocusOut> has been processed (harmlessly, the
        # old value was already committed) and the new editor stays open.
        # このクリック分でキューに残っているイベントの後まで開くのを遅らせる。
        # tksheet は編集ウィジェットを 1 個使い回すため、このクリックが直前の
        # 編集欄を閉じた場合、そのウィジェットに滞留した <FocusOut> が本
        # ハンドラの後に発火し、ここで同期的に開いた編集欄を即座に閉じてしまう。
        # アイドル時には滞留 <FocusOut> は処理済み（旧値は確定済みなので無害）
        # で、新しい編集欄は開いたままになる。
        self.after_idle(self._open_selected_scale_cell)

    def _open_selected_scale_cell(self) -> None:
        """
        Open the editor when a single editable X/Y cell is selected.
        編集可能な X/Y セルが単独選択されているときに編集欄を開く。
        """
        if self.is_running:
            return
        cur = self.sheet.get_currently_selected()
        # Selected.type_ is "cells" for cell selections ("rows"/"columns" for
        # header-driven ones).
        # Selected.type_ はセル選択で "cells"（見出し起点は "rows"/"columns"）。
        if not cur or cur.type_ != "cells" or cur.column not in SCALE_COLS:
            return
        # Only a plain single-cell click edits; a drag or Ctrl+click selection
        # is a batch-target selection, not an edit request.
        # 素のシングルセルクリックのみ編集に入る。ドラッグや Ctrl＋クリックの
        # 選択は一括操作の対象選択であり、編集要求ではない。
        if len(self.sheet.get_selected_cells()) != 1:
            return
        if cur.row not in self.item_by_iid:
            return
        self.sheet.open_cell()

    def _prune_rc_menu(self, _event=None) -> None:
        """
        Drop the Delete entry from the right-click menu unless it applies.
        右クリックメニューから、有効でない場合の Delete 項目を取り除く。

        tksheet builds the popup menu from the enabled bindings before this
        hook runs and pops it up afterwards, so entries can be removed here.
        Clearing a cell is only meaningful for Y cells (an empty Y means
        "= X"); X is required and read-only columns cannot be cleared, so the
        entry is shown only when every selected cell is in the Y column.
        tksheet は本フックの前に有効バインディングからポップアップメニューを
        構築し、後で表示するため、ここで項目を除去できる。セルの消去が意味を
        持つのは Y セルだけ（空の Y は「= X」を意味する）で、X は必須値、
        読み取り専用列は消去不能。そのため選択セルがすべて Y 列のときのみ
        項目を残す。
        """
        cells = self.sheet.get_selected_cells()
        if cells and all(c == COL_Y for (_r, c) in cells):
            return
        delete_label = self.sheet.ops.delete_label
        for menu in (
            self.sheet.MT.rc_popup_menu, self.sheet.MT.empty_rc_popup_menu,
        ):
            if menu is None:
                continue
            end = menu.index("end")
            if end is None:
                continue
            # Iterate backwards so deleting an entry does not shift the rest.
            # 項目の削除で残りの位置がずれないよう逆順に走査する。
            for i in range(end, -1, -1):
                try:
                    if menu.entrycget(i, "label") == delete_label:
                        menu.delete(i)
                except tk.TclError:
                    # Separators have no label option.
                    # セパレータは label オプションを持たない。
                    continue

    def _fit_name_loop(self) -> None:
        """
        Periodically keep the file-name column filling the table, then reschedule.
        ファイル名列がテーブルを埋め続けるよう定期実行し、再予約する。
        """
        self._fit_name_column()
        self.after(150, self._fit_name_loop)

    def _fit_name_column(self) -> None:
        """
        Size the file-name column to the exact remaining table width.
        ファイル名列をテーブルの残り幅ちょうどのサイズにする。

        The name column absorbs whatever width the fixed X/Y/status/time
        columns leave over, so the columns always fill the table exactly and
        the numeric columns stay compact against the right edge with no blank
        margin after them. Spare width inside the left-aligned name column
        reads naturally (Explorer-style). When the pane is too narrow, a
        160 px floor keeps names readable and the horizontal scrollbar takes
        over.
        固定幅の X/Y/状態/処理時間列が残した幅をファイル名列が吸収するため、
        列は常にテーブルを正確に埋め、数値系の列は右端まで詰めて並び、その後ろ
        に空白の余白が残らない。左寄せのファイル名列内の余り幅は（エクスプローラ
        式で）自然に見える。ペインが狭すぎる場合は下限 160 px でファイル名の
        可読性を保ち、水平スクロールバーに委ねる。
        """
        try:
            table_w = self.sheet.MT.winfo_width()
        except tk.TclError:
            return
        # Not yet mapped: a later tick fits it once the canvas has a real width.
        # 未マップ時：キャンバスが実幅を持った後の後続チェックでフィットする。
        if table_w <= 1:
            return
        widths = self.sheet.get_column_widths()
        if len(widths) != COL_TIME + 1:
            return
        others = sum(widths) - widths[COL_NAME]
        desired = max(int(table_w) - others, 160)
        # Idempotent: only resize when the columns do not already fill the table.
        # 冪等：列がまだテーブルを埋めていないときだけリサイズする。
        if desired != widths[COL_NAME]:
            # column_width() on a single int column updates col_positions but
            # (despite redraw=True) does NOT run the full redraw that recomputes
            # the canvas scrollregion, so the widened column would be drawn only
            # up to the stale scrollregion and leave a blank strip. refresh()
            # forces the full redraw so the new width is actually painted.
            # 単一の int 列に対する column_width() は col_positions を更新するが、
            # redraw=True でもキャンバスの scrollregion を再計算するフル再描画を
            # 実行しない。そのため広げた列は古い scrollregion までしか描画されず
            # 空白帯が残る。refresh() でフル再描画を強制し、新しい幅を実際に
            # 反映させる。
            self.sheet.column_width(COL_NAME, desired, redraw=False)
            self.sheet.refresh()

    def _on_sheet_modified(self, event=None) -> None:
        """
        Sync FileItem state after user-driven sheet changes (edit/paste/undo).
        ユーザー操作によるシート変更（編集・貼り付け・元に戻す）後に FileItem
        の状態を同期する。

        The changed cells' current text is the source of truth here, so undo
        and multi-cell paste flow through the same path as a single edit.
        ここでは変更セルの現在テキストを正とみなすため、元に戻す操作や複数セル
        貼り付けも単一編集と同じ経路で処理される。

        Notes
        -----
        tksheet calls this synchronously from inside its edit-commit sequence
        (``emit_event`` invokes bound callbacks directly, before the editor is
        hidden and the selection settles), so mutating the sheet here
        (``set_row_data`` / ``redraw``) or running the potentially slow preview
        reload would re-enter and corrupt that teardown — the symptom being a
        cell that stays "stuck" in edit mode. All side effects are therefore
        deferred to idle time, once tksheet has finished closing the editor.
        tksheet は編集確定シーケンスの内部からこれを同期的に呼ぶ（``emit_event``
        がエディタを隠し選択が確定する前に、束縛コールバックを直接実行する）。
        そのためここでシートを変更（``set_row_data`` / ``redraw``）したり、遅い
        可能性のあるプレビュー再読込を走らせると、後始末に再入して壊し、セルが
        編集モードから「抜けられない」症状になる。よって副作用はすべてアイドル
        時へ遅延し、tksheet がエディタを閉じ切った後に実行する。
        """
        if self._sheet_syncing:
            return
        # Collect the affected row set from the event; fall back to all rows.
        # イベントから影響行の集合を得る。取得できなければ全行を対象にする。
        try:
            cells = event["cells"]["table"]
            rows = sorted({r for (r, _c) in cells})
        except Exception:
            rows = sorted(self.item_by_iid.keys())
        self.after_idle(lambda: self._apply_sheet_edits(rows))

    def _apply_sheet_edits(self, rows: List[int]) -> None:
        """
        Sync the given rows from the sheet to FileItems, off the edit path.
        指定行をシートから FileItem へ同期する（編集フローの外で実行）。
        """
        if self.is_running:
            # A batch run owns the FileItems; revert any slipped-through change
            # (e.g. undo, which bypasses edit validation) back to item state.
            # 一括処理中は FileItem を処理側が所有する。検証を通らない変更
            # （例: 元に戻す）が紛れ込んだ場合は項目状態へ巻き戻す。
            for r in rows:
                self._refresh_tree_row(r)
            return
        changed = False
        for r in rows:
            changed = self._sync_row_from_sheet(r) or changed
        if changed:
            # Reflect new per-file scales in the preview axis ticks.
            # 新しいファイル単位スケールをプレビューの軸目盛へ反映する。
            self.on_redraw_preview()

    def _sync_row_from_sheet(self, row: int) -> bool:
        """
        Pull one row's X/Y cell text into its FileItem and re-render the row.
        1 行分の X/Y セルテキストを FileItem へ取り込み、行を再描画する。

        Returns
        -------
        bool
            True when a scan-size value actually changed.
            走査範囲の値が実際に変化した場合に True。
        """
        it = self.item_by_iid.get(row)
        if it is None:
            return False
        x_text = str(self.sheet.get_cell_data(row, COL_X) or "").strip()
        y_text = str(self.sheet.get_cell_data(row, COL_Y) or "").strip()
        changed = False
        try:
            x_val = float(x_text)
            if x_val > 0 and x_val != it.scale_x_um:
                it.scale_x_um = x_val
                changed = True
        except ValueError:
            # Unparsable X text (validation rejects it for user edits) keeps
            # the previous value; the re-render below restores the display.
            # 解析不能な X テキスト（ユーザー編集は検証で拒否済み）は前の値を
            # 保持し、下の再描画で表示を復元する。
            pass
        ok, y_val = self._parse_scale_y_text(y_text)
        if ok and y_val != it.scale_y_um:
            it.scale_y_um = y_val
            changed = True
        if changed:
            it.scale_source = "manual"
        # Always re-render so cell text returns to canonical display form
        # (e.g. "2.0" -> "2", blank Y -> "= X").
        # セルテキストを正規表示（例: "2.0"→"2"、空 Y→"= X"）へ戻すため
        # 常に再描画する。
        self._refresh_tree_row(row)
        return changed

    def _build_preview_area(self) -> None:
        """
        Build preview controls for scale, contrast, overlays, and export.
        スケール、コントラスト、重ね表示、書き出し用のプレビュー操作部を構築する。
        """
        # Build the preview controls in two compact rows.
        # Entry-based numeric controls use Enter-to-commit so partial edits do not
        # immediately redraw figures with invalid or unintended values.
        self._build_preview_scale_row()
        self._build_preview_font_row()

    def _build_preview_scale_row(self) -> None:
        """
        Build preview row 1: title/scale display, axis unit, vmin/vmax, overlay.
        プレビュー行1（タイトル/スケール表示・軸単位・vmin/vmax・重ね表示）を構築する。
        """
        # -- Row 1: title/scale display, axis unit, vmin/vmax, overlay --
        ctrl1 = ttk.Frame(self.right_frame)
        ctrl1.pack(side="top", fill="x", padx=4, pady=(4, 2))

        # Title display toggle applies immediately.
        ttk.Checkbutton(
            ctrl1, text=_("タイトル表示"), variable=self.show_title_var,
            command=self.on_redraw_preview,
        ).pack(side="left", padx=(2, 4))

        # Scale display toggle applies immediately.
        ttk.Checkbutton(
            ctrl1, text=_("スケール表示"), variable=self.show_scale_var,
            command=self.on_redraw_preview,
        ).pack(side="left", padx=(0, 4))

        # The physical-scale entry now lives in the file-list scale toolbar,
        # next to the buttons that apply it to rows (see _build_main_panes).
        # 実寸スケール入力欄はファイル一覧のスケールツールバーへ移動した
        # （適用ボタンの隣。_build_main_panes を参照）。

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

        # Overlay selector for the skeletonized panel.
        lbl_overlay = ttk.Label(ctrl1, text=_("重ね表示"))
        lbl_overlay.pack(side="left", padx=(14, 2))
        self.cmb_overlay = ttk.Combobox(
            ctrl1, width=10, textvariable=self.overlay_mode_var,
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

    def _build_preview_font_row(self) -> None:
        """
        Build preview row 2: title/label/tick/legend font sizes, image export, single-view.
        プレビュー行2（タイトル/軸ラベル/軸目盛/凡例のフォントサイズ・画像保存・個別表示）を構築する。
        """
        # -- Row 2: font sizes, image export, and single-view dialog --
        ctrl2 = ttk.Frame(self.right_frame)
        ctrl2.pack(side="top", fill="x", padx=4, pady=(0, 4))

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

        # Export the full right-pane preview figure.
        self.btn_export_preview = ttk.Button(
            ctrl2, text=_("画像を保存"), command=self.on_export_preview)
        self.btn_export_preview.pack(side="left", padx=(16, 4))

        self.btn_open_single = ttk.Button(
            ctrl2, text=_("個別表示"), command=self.on_open_single_view)
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

    def validate_scale_y_um(self) -> bool:
        """
        Validate and commit the optional Y (height) scale in micrometers.
        任意の Y（高さ）スケール (µm) の入力欄を検証・確定する。

        An empty field commits ``None``, meaning the Y size follows the X size
        (square scan); a non-empty field must be a positive number. This is
        kept separate from `validate_scale_um` because the shared
        `_commit_float_fields` helper cannot express the empty-means-default
        case.
        空欄は ``None`` を確定し、Y サイズが X サイズに従う（正方スキャン）こと
        を意味する。非空欄は正の数であること。空欄を既定値として扱う仕様は共有
        ヘルパー `_commit_float_fields` では表現できないため別実装とする。

        Returns
        -------
        bool
            True when the value (including empty) was committed; False on a
            non-numeric or non-positive entry.
            値（空欄含む）を確定できた場合は True、数値でない・非正の場合は False。
        """
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
                    _("スケール") + " (µm) " + _("は正の数を入力してください"),
                )
                return False
            self.scale_y_um = value
            committed = self._fmt_num(value)
        rewrite_entries(((self.ent_scale_y_um, committed),))
        mark_entry_state(self.ent_scale_y_um, committed)
        # Re-show the "= X" ghost when the field committed back to empty.
        # 空欄に確定した場合は "= X" ゴーストを再表示する。
        self._refresh_scale_y_placeholder()
        self.on_redraw_preview()
        return True

    def _scale_xy_um(self) -> Tuple[float, float]:
        """
        Return the toolbar-entry (X, Y) scale in micrometers.
        ツールバー入力欄の (X, Y) スケールを µm で返す。

        Y falls back to X when no separate Y size is set, so a single value
        keeps a square scan. This is the value assigned to files via the
        apply buttons; preview rendering resolves its display scale through
        `_preview_scale_xy_um` and uses this entry only as the last fallback.
        個別の Y サイズが未設定なら Y は X にフォールバックし、単一値で正方
        スキャンを保つ。これは「適用」ボタンでファイルに割り当てる値であり、
        プレビュー描画は `_preview_scale_xy_um` で表示スケールを解決し、
        本入力欄は最終フォールバックとしてのみ使う。
        """
        y = self.scale_y_um if self.scale_y_um is not None else self.scale_um
        return self.scale_um, y

    def _preview_scale_xy_um(self, it: FileItem) -> Tuple[float, float]:
        """
        Resolve the (X, Y) display scale in micrometers for one file's preview.
        ファイル 1 件のプレビュー表示に使う (X, Y) スケール (µm) を解決する。

        Parameters
        ----------
        it
            File whose preview is being rendered.
            プレビュー描画対象のファイル。

        Returns
        -------
        tuple of float
            Per-axis physical scan size in micrometers.
            軸ごとの物理走査範囲 (µm)。

        Notes
        -----
        Resolution order: (1) the scan size recorded in the analyzed ``.b2z``
        bundle — the value the analysis actually used, and the one GUI03/GUI04
        and the CLI read from the same bundle; (2) the per-file scale
        (header / manifest / manual), which covers bundles saved before
        ``spatial_calibration`` existed; (3) the toolbar entry as the last
        fallback for files with no scale information at all.
        解決順: (1) 解析済み ``.b2z`` に記録された走査範囲（解析が実際に使った
        値で、GUI03/GUI04 や CLI が同じバンドルから読む値と一致）、
        (2) ファイル単位スケール（ヘッダ/マニフェスト/手動。
        ``spatial_calibration`` 導入前のバンドルを補う）、(3) スケール情報が
        全く無いファイル向けの最終フォールバックとしてツールバー入力欄。
        """
        # The vlmeta scan size is cached alongside the preview arrays, so it
        # is only valid while `it` is the currently cached item.
        if self._current_item is it and self._current_scan_size_um is not None:
            return self._current_scan_size_um
        if it.has_scale:
            return it.scale_x_um, it.scale_y_um
        return self._scale_xy_um()

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

    def _bind_events(self) -> None:
        """
        Bind GUI events that update controls and preview state.
        操作部とプレビュー状態を更新する GUI イベントを結び付ける。
        """
        # Refresh preview state when the sheet selection changes.
        self.sheet.bind("<<SheetSelect>>", lambda e: self._on_sheet_select())

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
    @staticmethod
    def _row_values(item: FileItem) -> List[str]:
        """
        Build the file-table cell texts for one file item.
        1 件のファイル項目からファイル表のセルテキストを組み立てる。
        """
        return [
            os.path.basename(item.txt_path),
            item.scale_x_display, item.scale_y_display,
            status_label(item.status), str(item.proc_time_s),
        ]

    def _clear_tree(self) -> None:
        """
        Clear the file table and its path lookup dictionaries.
        ファイル表とパス検索用辞書を消去する。
        """
        # Keep sheet rows and lookup dictionaries in sync.
        self._sheet_syncing = True
        try:
            self.sheet.set_sheet_data([], reset_col_positions=False)
            self.sheet.deselect()
        finally:
            self._sheet_syncing = False
        self.item_by_iid.clear()
        self.iid_by_path.clear()
        self._preview_row = None

    def _insert_item(self, item: FileItem) -> None:
        """
        Insert one file item into the sheet and lookup dictionaries.
        1 件のファイル項目をシートと検索用辞書へ挿入する。
        """
        # Store both lookup directions because later queue messages carry only
        # the row id; rows are append-only so the index is stable.
        # 後続のキューメッセージは行 ID のみを運ぶため双方向の対応を保持する。
        # 行は追記のみなのでインデックスは安定している。
        row = len(self.item_by_iid)
        self._sheet_syncing = True
        try:
            # Default idx appends at the end; passing idx="end" makes tksheet
            # drop the cell values on a sheet whose data started empty.
            # 既定の idx は末尾へ追加する。idx="end" を渡すと、データが空で
            # 始まったシートでは tksheet がセル値を落としてしまう。
            self.sheet.insert_row(self._row_values(item))
        finally:
            self._sheet_syncing = False
        self.item_by_iid[row] = item
        self.iid_by_path[item.txt_path] = row

    def _refresh_tree_row(self, iid: int) -> None:
        """
        Refresh one file-table row from its FileItem state.
        FileItem の状態からファイル表の 1 行を更新する。
        """
        # Re-render one row from the authoritative FileItem state.
        it = self.item_by_iid.get(iid)
        if not it:
            return
        self._sheet_syncing = True
        try:
            self.sheet.set_row_data(iid, values=self._row_values(it))
            self.sheet.redraw()
        finally:
            self._sheet_syncing = False

    def _selected_rows(self) -> List[int]:
        """
        Return the selected file-table rows in ascending order.
        選択中のファイル表の行を昇順で返す。

        Selected cells count their rows too, so picking X/Y cells (not whole
        rows) still targets those files for the batch actions.
        選択セルもその行として数えるため、行全体でなく X/Y セルを選択した
        場合も一括操作の対象になる。
        """
        return sorted(self.sheet.get_selected_rows(get_cells_as_rows=True))

    def _find_iid_for_item(self, item: FileItem) -> Optional[int]:
        """
        Return the file-table row id for a file item.
        ファイル項目に対応するファイル表の行 ID を返す。
        """
        # Return the sheet row id for a FileItem, if it is still listed.
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
        _set([self.btn_select_folder, self.chk_skip, self.btn_run_all, self.btn_settings,
              self.btn_apply_scale_all, self.btn_load_manifest],
             "disabled" if running else "!disabled")
        _set([self.btn_stop], "!disabled" if running else "disabled")

        # Single-file analysis and apply-to-selected are available only when at
        # least one row is selected.
        if running:
            _set([self.btn_run_sel, self.btn_apply_scale_sel], "disabled")
        else:
            has_sel = bool(self.sheet.get_selected_rows(get_cells_as_rows=True))
            _set([self.btn_run_sel, self.btn_apply_scale_sel],
                 "!disabled" if has_sel else "disabled")

    def _on_sheet_select(self) -> None:
        """
        Handle file-table selection changes.
        ファイル表の選択変更を処理する。

        Only selecting a cell in the file-name column switches the preview;
        picking X/Y (or status/time) cells edits or selects without touching
        it, an empty selection (e.g. clicking past the last row) keeps the
        current preview instead of clearing it, and the reload is deferred to
        idle time so cell editing is never stalled behind the (potentially
        slow) preview load.
        プレビューを切り替えるのはファイル名列のセルを選択したときだけ。X/Y
        （や状態・処理時間）セルの選択は編集・選択のみでプレビューに触れず、
        空選択（最終行より下をクリック等）では消さずに現在のプレビューを保つ。
        再読込はアイドル時へ遅延し、セル編集が（遅い可能性のある）プレビュー
        読込に待たされないようにする。
        """
        self._update_controls_state()
        cur = self.sheet.get_currently_selected()
        row = cur.row if cur else None
        col = cur.column if cur else None
        # Only the file-name column drives the preview; everything else keeps
        # it as is, so scale editing never yanks the right pane around.
        # プレビューを動かすのはファイル名列のみ。それ以外では据え置き、
        # スケール編集で右ペインが振り回されないようにする。
        if (
            row is None or col != COL_NAME
            or row not in self.item_by_iid or row == self._preview_row
        ):
            return
        self._preview_row = row
        if not self._preview_redraw_pending:
            self._preview_redraw_pending = True
            self.after_idle(self._deferred_preview_redraw)

    def _deferred_preview_redraw(self) -> None:
        """
        Run the preview redraw scheduled by `_on_sheet_select`.
        `_on_sheet_select` が予約したプレビュー再描画を実行する。
        """
        self._preview_redraw_pending = False
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
        folder = filedialog.askdirectory(title=_("入力フォルダを選択（.txt / .gwy を含む）"))
        if not folder:
            return

        self.folder_path = folder
        self._log(_("フォルダ選択: %s") % folder)

        try:
            # Sort input files for deterministic batch order and log output.
            # Accept both text/CSV exports (.txt) and Gwyddion native files
            # (.gwy); the pipeline dispatches by extension.
            # テキスト/CSV エクスポート (.txt) と Gwyddion ネイティブ (.gwy) の
            # 双方を受け付ける。パイプラインが拡張子で振り分ける。
            files = sorted(
                f for f in os.listdir(folder)
                if f.lower().endswith((".txt", ".gwy"))
            )
        except Exception as e:
            self._log(_("フォルダ読み込み失敗: %s") % e)
            return

        self.items = []
        self._clear_tree()
        # Switching folders invalidates preview data even before a new row is selected.
        self._invalidate_current_data()

        # Detect existing outputs only when a folder is selected.
        n_from_bundle = 0
        n_from_header = 0
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
            # Auto-fill the scan size: analyzed files first restore the value
            # recorded in their .b2z bundle (what the previous run actually
            # used); otherwise fall back to the instrument header (Shimadzu
            # SizeX/SizeY). Files with neither stay unset and need a manual
            # or manifest value before processing.
            # 走査範囲の自動設定：解析済みファイルはまず .b2z バンドルの記録値
            # （前回実行が実際に使った値）を復元し、それ以外は装置ヘッダ（島津
            # SizeX/SizeY）から取得する。どちらも無いファイルは未設定のままで、
            # 処理前に手動またはマニフェストで値を与える必要がある。
            if (
                item.status == STATUS_ANALYZED
                and self._autofill_scale_from_bundle(item)
            ):
                n_from_bundle += 1
            elif self._autofill_scale_from_header(item):
                n_from_header += 1
            self.items.append(item)
            self._insert_item(item)

        if not self.items:
            self._log(_("対象ファイル（.txt / .gwy）がありません。"))
        else:
            n_unset = sum(1 for it in self.items if not it.has_scale)
            self._log(
                _("スケール: バンドル記録 %d 件 / ヘッダ取得 %d 件 / 未設定 %d 件")
                % (n_from_bundle, n_from_header, n_unset)
            )
            if n_unset:
                self._log(
                    _("スケール（画像の実寸 µm）が未設定のファイルがあります。"
                      "「適用」または「スケール表(CSV)読込」で設定してください。")
                )
        self._update_controls_state()
        self.on_redraw_preview()

    # ---------- Scale assignment ----------
    def _autofill_scale_from_header(self, item: FileItem) -> bool:
        """
        Set a file's scan size from its instrument header, if recorded.
        記録があればファイルの走査範囲を装置ヘッダから設定する。

        Returns
        -------
        bool
            True when a header scan size was found and applied.
            ヘッダの走査範囲が見つかり適用された場合に True。
        """
        try:
            size = read_scan_size(item.txt_path)
        except Exception:
            # A header read failure must not abort folder loading; the file
            # simply stays unset and can be filled manually.
            # ヘッダ読み取り失敗でフォルダ読み込みを中断しない。該当ファイルは
            # 未設定のままとし、手動で設定できる。
            size = None
        if size is None:
            return False
        item.scale_x_um = size.x_um
        item.scale_y_um = size.y_um
        item.scale_source = "input_header"
        return True

    def _autofill_scale_from_bundle(self, item: FileItem) -> bool:
        """
        Restore a file's scan size from its analyzed output bundle, if recorded.
        記録があれば解析済み出力バンドルからファイルの走査範囲を復元する。

        Returns
        -------
        bool
            True when a recorded scan size was found and applied.
            記録された走査範囲が見つかり適用された場合に True。

        Notes
        -----
        The bundle value is the scan size the previous analysis actually
        used, so it takes precedence over the input header for analyzed
        files: when the two differ, the user deliberately overrode the
        header value (manually or via a manifest) before the last run, and
        restoring that choice keeps a re-run reproducible. It also matches
        the preview scale resolution (`_preview_scale_xy_um`) and the value
        GUI03/GUI04 and the CLI read from the same bundle.
        バンドル値は前回の解析が実際に使った走査範囲であり、解析済みファイル
        では入力ヘッダより優先する。両者が食い違うのは前回実行前にユーザーが
        意図的に（手動またはマニフェストで）ヘッダ値を上書きした場合であり、
        その選択を復元することで再解析の再現性が保たれる。プレビューの
        スケール解決（`_preview_scale_xy_um`）や、GUI03/GUI04・CLI が同じ
        バンドルから読む値とも一致する。
        """
        meta = self._read_bundle_meta_safe(item)
        size = scan_size_um_from_meta(meta)
        if size is None:
            return False
        item.scale_x_um, item.scale_y_um = size
        # Restore the recorded provenance so a re-run writes the same source.
        # An unknown source value degrades to "" (unset) per the FileItem contract.
        # 記録された来歴を復元し、再解析時も同じ source が書き込まれるようにする。
        # 未知の source 値は FileItem の契約に従い ""（未設定）へ落とす。
        cal = meta.get(SPATIAL_CALIBRATION_KEY)
        source = cal.get("source") if isinstance(cal, dict) else None
        item.scale_source = source if source in SCAN_SIZE_SOURCES else ""
        return True

    def on_apply_scale_to_rows(self, selected_only: bool) -> None:
        """
        Apply the scale entry value to selected or all files (manual source).
        スケール入力欄の値を選択ファイルまたは全ファイルへ適用する（手動ソース）。
        """
        if self.is_running:
            return
        # Commit and validate both scale entries before applying them.
        # 適用前に両方のスケール入力欄を確定・検証する。
        if not self.validate_scale_um():
            return
        if not self.validate_scale_y_um():
            return
        if selected_only:
            iids = self._selected_rows()
            if not iids:
                messagebox.showinfo(_("注意"), _("適用するファイルを選択してください。"))
                return
        else:
            iids = sorted(self.item_by_iid.keys())
        # A blank Y entry applies a square scan (Y = X); otherwise X and Y differ.
        # Y 欄が空なら正方スキャン（Y = X）を適用し、そうでなければ X と Y は異なる。
        x_um, y_um = self._scale_xy_um()
        for iid in iids:
            it = self.item_by_iid.get(iid)
            if it is None:
                continue
            it.scale_x_um = x_um
            it.scale_y_um = y_um
            it.scale_source = "manual"
            self._refresh_tree_row(iid)
        if abs(x_um - y_um) < 1e-9:
            self._log(_("スケール %g µm を %d 件に適用しました。") % (x_um, len(iids)))
        else:
            self._log(
                _("スケール %g×%g µm を %d 件に適用しました。")
                % (x_um, y_um, len(iids))
            )

    def on_load_scale_manifest(self) -> None:
        """
        Load a CSV mapping file names to scan sizes and apply them by name.
        ファイル名と走査範囲を対応付けた CSV を読み込み、名前一致で適用する。

        Notes
        -----
        The CSV must have a header row with a ``filename`` column and either a
        single ``scale_um`` column or separate ``scale_x_um`` / ``scale_y_um``
        columns. File names match by base name, with or without extension.
        CSV はヘッダ行を持ち、``filename`` 列と、``scale_um`` 単一列または
        ``scale_x_um`` / ``scale_y_um`` の分割列のいずれかを含む必要がある。
        ファイル名は拡張子の有無を問わず基底名で一致させる。
        """
        if self.is_running:
            return
        path = filedialog.askopenfilename(
            title=_("スケール表(CSV)を選択"),
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            mapping = self._parse_scale_manifest(path)
        except Exception as e:
            messagebox.showerror(_("エラー"), _("スケール表の読み込みに失敗しました: %s") % e)
            return
        if not mapping:
            messagebox.showwarning(_("注意"), _("スケール表に有効な行がありませんでした。"))
            return

        # Match listed files by base name, accepting entries given with or
        # without the file extension.
        # 一覧のファイルを基底名で照合する。拡張子付き・無しのどちらの記載も許す。
        n_matched = 0
        for iid in sorted(self.item_by_iid.keys()):
            it = self.item_by_iid.get(iid)
            if it is None:
                continue
            base = os.path.basename(it.txt_path)
            stem = os.path.splitext(base)[0]
            entry = mapping.get(base) or mapping.get(stem)
            if entry is None:
                continue
            it.scale_x_um, it.scale_y_um = entry
            it.scale_source = "manifest"
            self._refresh_tree_row(iid)
            n_matched += 1
        n_unmatched = len(mapping) - n_matched
        self._log(
            _("スケール表を適用しました: 一致 %d 件 / 未一致 %d 件")
            % (n_matched, max(n_unmatched, 0))
        )

    @staticmethod
    def _parse_scale_manifest(path: str) -> Dict[str, Tuple[float, float]]:
        """
        Parse a scale-manifest CSV into a ``{name: (x_um, y_um)}`` mapping.
        スケールマニフェスト CSV を ``{名前: (x_um, y_um)}`` 辞書へ解析する。

        Raises
        ------
        ValueError
            If the required columns are missing.
            必須列が無い場合。
        """
        mapping: Dict[str, Tuple[float, float]] = {}
        # utf-8-sig also reads BOM-less UTF-8, matching Excel exports on
        # Japanese Windows.
        # utf-8-sig は BOM 無し UTF-8 も読め、日本語 Windows の Excel 出力に合う。
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
            if "filename" not in cols:
                raise ValueError("missing 'filename' column")
            has_single = "scale_um" in cols
            has_xy = "scale_x_um" in cols and "scale_y_um" in cols
            if not (has_single or has_xy):
                raise ValueError(
                    "missing scale columns ('scale_um' or "
                    "'scale_x_um'/'scale_y_um')"
                )
            for row in reader:
                name = (row.get("filename") or "").strip()
                if not name:
                    continue
                try:
                    if has_xy and (row.get("scale_x_um") or "").strip():
                        x = float(row["scale_x_um"])
                        y = float(row["scale_y_um"])
                    else:
                        x = y = float(row["scale_um"])
                except (TypeError, ValueError):
                    continue
                if x > 0 and y > 0:
                    mapping[name] = (x, y)
        return mapping

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
        sel_iids = self._selected_rows()
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

    def _scales_ready_for_run(self, targets: List[FileItem], overwrite: bool) -> bool:
        """
        Verify every file to be processed has a scan size set before a run.
        実行前に、処理対象の全ファイルへ走査範囲が設定済みかを確認する。

        Mixed per-file scales (including different X/Y sizes) are a supported
        workflow — set from each file's header or a CSV manifest — so they are
        not flagged; only files missing a scale block the run.
        ファイル単位での異なるスケール（X/Y 別を含む）は、ヘッダや CSV
        マニフェストから設定する正当なワークフローなので警告しない。実行を
        止めるのはスケール未設定のファイルがある場合のみ。

        Parameters
        ----------
        overwrite
            Whether existing outputs are reprocessed; when False, files with
            existing outputs are skipped and excluded from the scale check.
            既存出力を再処理するか。False のとき既存出力のあるファイルは
            スキップされ、スケール検査の対象から除外する。

        Returns
        -------
        bool
            True when processing may proceed; False to abort.
            処理を続行してよい場合は True、中止する場合は False。
        """
        # Only files that will actually be processed need a scale.
        # 実際に処理されるファイルのみスケールが必要。
        to_process = []
        for it in targets:
            ok, _missing = existing_min_set(it.stem)
            if ok and not overwrite:
                continue
            to_process.append(it)

        unset = [it for it in to_process if not it.has_scale]
        if unset:
            names = ", ".join(os.path.basename(it.txt_path) for it in unset[:10])
            if len(unset) > 10:
                names += f" (+{len(unset) - 10})"
            msg = _("スケール未設定のファイルがあります。先にスケールを設定してください:")
            self._log(msg + " " + names)
            messagebox.showerror(_("エラー"), msg + "\n\n" + names)
            return False

        return True

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

        # Reject invalid parameters before the worker starts, listing every
        # problem at once. Detail lines stay in fixed English because they
        # name serialized ProcParams fields.
        # ワーカー開始前に不正パラメータを拒否し、全問題を一括表示する。
        # 詳細行はシリアライズされる ProcParams フィールド名を含むため
        # 固定英語のままとする。
        problems = validate_params(self.params_active)
        if problems:
            detail = "\n".join(f"- {p}" for p in problems)
            self._log(_("解析パラメータが不正なため開始できません。") + "\n" + detail)
            messagebox.showerror(
                _("エラー"),
                _("解析パラメータが不正なため開始できません。") + "\n\n" + detail,
            )
            return

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

        # Validate the per-file scan size, but only for files that will actually
        # be processed (skipped existing outputs keep their stored scale).
        # ファイル単位の走査範囲を検証する。ただし実際に処理されるファイルのみ
        # 対象とする（スキップされる既存出力は保存済みスケールを保持する）。
        if not self._scales_ready_for_run(targets, overwrite):
            return

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
            # Stage construction is shared with the CLI through lib.pipeline.
            # パラメータ固定後、ステージをバッチ全体で再利用する。
            # ステージ構築は lib.pipeline 経由で CLI と共有する。
            stages = build_stages(self.params_active)

            for it in targets:
                if self.stop_event.is_set():
                    self.ui_queue.put(("log", _("停止しました。")))
                    break

                fname = os.path.basename(it.txt_path)
                # Row ids are ints and row 0 is falsy, so compare with None.
                # 行 ID は int で行 0 は偽値になるため None と比較する。
                iid = self._find_iid_for_item(it)
                if iid is not None:
                    self.ui_queue.put(("status", (iid, STATUS_RUNNING, "")))

                # Re-check existing outputs at run time without changing folder-scan state.
                ok, _missing = existing_min_set(it.stem)
                if ok and not overwrite:
                    self.ui_queue.put(("log", _("%s: 既存データのためスキップ") % fname))
                    if iid is not None:
                        self.ui_queue.put(("status", (iid, STATUS_ANALYZED, it.proc_time_s)))
                    self.ui_queue.put(("progress", 1))
                    self.ui_queue.put(("progress_detail", (fname, _("完了"))))
                    continue

                self._process_single_item(it, fname, iid, stages)

        finally:
            # Always unblock the main UI controls, even after an exception or stop.
            self.ui_queue.put(("done", None))

    def _process_single_item(
        self,
        it: FileItem,
        fname: str,
        iid: Optional[int],
        stages: PipelineStages,
    ) -> None:
        """
        Run the shared pipeline on one file and report progress to the UI.
        共有パイプラインを 1 ファイルに実行し、進捗を UI へ通知する。

        The pipeline itself (stage order, output bundle, sidecar JSON) lives in
        `lib.pipeline.process_file`; this method only maps stage keys to
        translated progress labels and converts the outcome into UI events.
        パイプライン本体（ステージ順序・バンドル出力・サイドカー JSON）は
        `lib.pipeline.process_file` にあり、このメソッドはステージキーの
        翻訳ラベル変換と結果の UI イベント化のみを行う。
        """
        # Each stage reports both its key (to advance the progress bar within a
        # single file) and a translated label (for the detail text).
        # 各ステージはキー（1 ファイル内でバーを進めるため）と翻訳ラベル
        # （詳細テキスト用）の両方を通知する。
        def report_stage(s: str) -> None:
            self.ui_queue.put(("stage", s))
            self.ui_queue.put(("progress_detail", (fname, stage_label(s))))

        try:
            # Pass the per-file scan size resolved on the main thread (header,
            # manifest, or manual) so the bundle records its spatial calibration.
            # メインスレッドで解決したファイル単位の走査範囲（ヘッダ/マニフェスト/
            # 手動）を渡し、バンドルへ空間較正を記録する。
            scan_size_um = None
            if it.has_scale:
                scan_size_um = (it.scale_x_um, it.scale_y_um)
            result = process_file(
                it.txt_path,
                self.params_active,
                stages=stages,
                save_original=self._save_original_active,
                on_stage=report_stage,
                scan_size_um=scan_size_um,
                scan_size_source=it.scale_source or "manual",
            )
            self.ui_queue.put(("progress_detail", (fname, _("完了"))))

        except Exception as e:
            # A failed file returns to pending while the rest of the batch continues.
            tb = traceback.format_exc()
            self.ui_queue.put(("log", _("解析失敗: %s\n%s\n%s") % (fname, e, tb)))
            if iid is not None:
                self.ui_queue.put(("status", (iid, STATUS_PENDING, "")))
            self.ui_queue.put(("progress", 1))
            self.ui_queue.put(("progress_detail", (fname, _("失敗"))))
            return

        # Report timing only after all outputs and sidecar metadata are written.
        dt_s = f"{result.elapsed_s:.2f}"
        self.ui_queue.put(("log", _("解析完了: %s (%ss)") % (fname, dt_s)))
        if iid is not None:
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

        def _on_stage(payload):
            # Advance the bar within the current file so it keeps moving even
            # for a single-file batch; full completion is handled by _on_progress.
            # 現在処理中のファイル内でバーを進め、1 ファイルのみのバッチでも
            # 動いて見えるようにする。完了時の更新は _on_progress が担当する。
            if self._total_tasks <= 0:
                return
            try:
                idx = STAGE_KEYS.index(payload)
            except ValueError:
                return
            frac = idx / len(STAGE_KEYS)
            pct = ((self._done_tasks + frac) / self._total_tasks) * 100.0
            self.progressbar["value"] = pct

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
            "stage": _on_stage,
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
        Return the item currently shown in the preview.
        現在プレビューに表示している項目を返す。
        """
        # `_preview_row` tracks the last file row deliberately chosen for the
        # preview (see _on_sheet_select); it is not cleared by an empty
        # selection, so the preview persists while the user edits X/Y cells.
        # `_preview_row` はプレビュー用に意図的に選ばれた最後のファイル行を
        # 保持する（_on_sheet_select を参照）。空選択では消えないため、X/Y セル
        # 編集中もプレビューは維持される。
        if self._preview_row is None:
            return None
        return self.item_by_iid.get(self._preview_row)

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
        # directly (faster than re-parsing the source file, notably for large or
        # slow-to-parse inputs). Otherwise fall back to load_afm_image.
        # 元画像の取得元はバンドル依存。「元データを保存」ON で保存された .b2z は
        # "original" キーを含むのでそこから直接読む（元ファイル再パースより速く、
        # 特に大きい/解析の重い入力で効く）。無ければ load_afm_image に戻す。
        if it.status != STATUS_ANALYZED:
            return None

        try:
            bundle_path = bundle_path_for(it.stem)

            # Load only the keys the preview renders instead of every key, so
            # an unexpected extra array in a bundle cannot balloon memory.
            # Required keys mirror _process_single_item; missing keys surface
            # as KeyError.
            # プレビューが描画するキーだけを読み込み、バンドル内の想定外の
            # 配列でメモリを浪費しないようにする。
            preview_keys = [
                "calibrated", "binarized", "skeletonized",
                "bp", "ep", "kp", "dp", "ka",
            ]
            has_original, _missing = bundle_has_keys(bundle_path, ["original"])
            if has_original:
                preview_keys.append("original")
            data = load_bundle(bundle_path, keys=preview_keys)

            if "original" in data:
                ori = data["original"]
            else:
                # Reload the raw height image when "original" was not bundled.
                # load_afm_image dispatches by extension so both text/CSV and
                # Gwyddion .gwy inputs (auto-selected channel) preview correctly.
                # "original" 未同梱時は生の高さ画像を読み直す。load_afm_image は
                # 拡張子で振り分けるため、テキスト/CSV と Gwyddion .gwy（自動選択
                # チャンネル）のいずれもプレビューできる。
                ori = load_afm_image(it.txt_path)

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

    def _read_bundle_meta_safe(self, it: FileItem) -> Dict:
        """
        Read a file's bundle vlmeta, or an empty dict when unavailable.
        ファイルのバンドル vlmeta を読み込み、読めない場合は空辞書を返す。
        """
        # A metadata read failure must not break folder scans or previews;
        # the scale simply falls back to the per-file or toolbar-entry value.
        # メタデータ読み込み失敗でフォルダ走査やプレビューを壊さない。スケールは
        # ファイル単位値または入力欄の値へフォールバックするだけにする。
        try:
            return load_bundle_meta(bundle_path_for(it.stem))
        except Exception:
            return {}

    def _load_bundle_scan_size(self, it: FileItem) -> Optional[Tuple[float, float]]:
        """
        Read the scan size recorded in a file's output bundle, if any.
        ファイルの出力バンドルに記録された走査範囲があれば読み込む。

        Returns
        -------
        tuple of float or None
            Per-axis scan size in micrometers, or ``None`` when the bundle
            does not record a spatial calibration or cannot be read.
            軸ごとの走査範囲 (µm)。空間較正が未記録、または読み込み不能な
            場合は ``None``。
        """
        return scan_size_um_from_meta(self._read_bundle_meta_safe(it))

    def _invalidate_current_data(self) -> None:
        """
        Clear the cached preview bundle data.
        キャッシュされたプレビューバンドルデータを消去する。
        """
        # Drop cached preview data after selection changes or bundle rewrites.
        self._current_item = None
        self._current_data = None
        self._current_mtime = 0.0
        self._current_scan_size_um = None

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
        # Refresh the recorded scan size together with the arrays so a
        # re-analyzed bundle updates the preview scale as well.
        # 再解析されたバンドルでプレビューのスケールも更新されるよう、
        # 記録走査範囲は配列と同時に読み直す。
        self._current_scan_size_um = self._load_bundle_scan_size(it)
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
        # Per-axis physical extent: X from the width scale, Y from the height
        # scale (equal for a square scan). The scale is resolved per file
        # (bundle record, then per-file value, then the toolbar entry).
        # 軸別の物理範囲：X は幅スケール、Y は高さスケール（正方スキャンでは
        # 等しい）。スケールはファイル単位で解決する（バンドル記録値 →
        # ファイル単位値 → ツールバー入力欄の順）。
        x_um, y_um = self._preview_scale_xy_um(it)
        if unit == "nm":
            x_scale, y_scale = x_um * 1000.0, y_um * 1000.0
            unit_label = "nm"
        else:
            x_scale, y_scale = x_um, y_um
            unit_label = "µm"

        # extent converts imshow from pixel coordinates to the selected physical scale.
        extent = [0, x_scale, 0, y_scale] if show_scale else None

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

        # Feature overlays are drawn on the skeletonized panel and share its
        # per-axis scaling (X from the width scale, Y from the height scale).
        # 特徴点の重ね表示は骨格パネルと同じ軸別スケール（X は幅、Y は高さ）を使う。
        sk_img = data["skeletonized"]
        if show_scale:
            h, w = sk_img.shape[:2]
            sx = x_scale / max(w - 1, 1)
            sy = y_scale / max(h - 1, 1)
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
        # Build top-to-bottom; the analysis-params frame is shared by the sections.
        plf = self._build_scroll_container()
        self._build_bg_section(plf)
        self._build_param_sections(plf)
        self._build_save_options()
        self._build_buttons()

    def _build_scroll_container(self) -> ttk.LabelFrame:
        """
        Build the scrollable canvas region and return the analysis-params frame.
        スクロール可能な canvas 領域を構築し、解析条件フレームを返す。
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
        return plf

    def _begin_param_row(self, parent_lf: ttk.LabelFrame, label: str):
        """
        Create the frame and left-aligned label shared by every parameter row.
        すべてのパラメータ行で共通のフレームと左寄せラベルを生成する。
        """
        frm = ttk.Frame(parent_lf)
        frm.pack(fill="x", pady=3)
        lbl = ttk.Label(frm, text=label, width=26)
        lbl.pack(side="left")
        return frm, lbl

    def _register_param_row(self, frm: ttk.Frame, key: str, lbl: ttk.Label,
                            input_widget: tk.Widget, desc: str) -> None:
        """
        Attach the trailing description label and register the row widgets.
        末尾の説明ラベルを付けて、行のウィジェットを登録する。
        """
        dsc = ttk.Label(frm, text=desc, foreground="#444", justify="left")
        dsc.pack(side="left", padx=8, fill="x", expand=True)
        self._param_rows[key] = {"label": lbl, "input": input_widget, "desc": dsc}

    def _add_field(self, parent_lf: ttk.LabelFrame, key: str, label: str,
                   desc: str, width: int = 12) -> None:
        """
        Add a text-entry parameter row.
        テキスト入力用のパラメータ行を追加する。
        """
        frm, lbl = self._begin_param_row(parent_lf, label)
        v = tk.StringVar()
        self.vars[key] = v
        ent = ttk.Entry(frm, textvariable=v, width=width)
        ent.pack(side="left", padx=6)
        self._register_param_row(frm, key, lbl, ent, desc)

    def _add_bool(self, parent_lf: ttk.LabelFrame, key: str, label: str,
                  desc: str) -> None:
        """
        Add a boolean checkbox parameter row.
        真偽値チェックボックス用のパラメータ行を追加する。
        """
        frm, lbl = self._begin_param_row(parent_lf, label)
        v = tk.BooleanVar()
        self.vars[key] = v
        chk = ttk.Checkbutton(frm, variable=v)
        chk.pack(side="left", padx=6)
        self._register_param_row(frm, key, lbl, chk, desc)

    def _add_choice(self, parent_lf: ttk.LabelFrame, key: str, label: str,
                    desc: str, choices: list, width: int = 12,
                    command=None) -> None:
        """
        Add a readonly choice parameter row.
        読み取り専用選択肢のパラメータ行を追加する。
        """
        # Store choice values as strings, then cast in _apply_vars_to_refs.
        frm, lbl = self._begin_param_row(parent_lf, label)
        v = tk.StringVar()
        self.vars[key] = v
        cb = ttk.Combobox(frm, textvariable=v, values=choices,
                          width=width, state="readonly")
        cb.pack(side="left", padx=6)
        if command is not None:
            cb.bind("<<ComboboxSelected>>", lambda e: command())
        self._register_param_row(frm, key, lbl, cb, desc)

    def _add_fields(self, parent_lf: ttk.LabelFrame, specs) -> None:
        """
        Add a sequence of parameter rows from declarative specs.
        宣言的な spec 列からパラメータ行をまとめて追加する。

        Notes
        -----
        Each spec is ``(kind, key, label, desc, opts)`` where ``kind`` is
        ``"field"``, ``"bool"``, or ``"choice"`` and ``opts`` is a dict of
        optional keyword arguments (``width`` / ``choices`` / ``command``).
        各 spec は ``(種別, キー, ラベル, 説明, オプション)``。種別は
        ``"field"`` / ``"bool"`` / ``"choice"`` で、オプション辞書に
        ``width`` / ``choices`` / ``command`` を渡す。
        Specs are built at call time so gettext follows the active language;
        do not lift them to a module/class constant.
        spec は呼び出し時に構築し gettext が現在の言語に追従するようにする。
        モジュール/クラス定数へ引き上げてはならない。
        """
        for kind, key, label, desc, opts in specs:
            if kind == "field":
                self._add_field(parent_lf, key, label, desc, **opts)
            elif kind == "bool":
                self._add_bool(parent_lf, key, label, desc, **opts)
            elif kind == "choice":
                self._add_choice(parent_lf, key, label, desc, **opts)
            else:
                raise ValueError(f"unknown parameter row kind: {kind!r}")

    def _build_bg_section(self, plf: ttk.LabelFrame) -> None:
        """
        Build the BGCalibrator parameter group with method-specific fields.
        BGCalibrator パラメータ群（方式別フィールド付き）を構築する。
        """
        # ---- BGCalibrator ----
        # Scan size is display metadata, not an analysis parameter; GUI01,
        # GUI02, and GUI04 handle it as view state.
        # 画像の実寸は解析結果に影響せず、表示時にユーザーが都度設定する。
        lf_bg = ttk.LabelFrame(plf, text=_("BGCalibrator"))
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
        self._add_choice(lf_bg, "bg_method", _("bg_method"),
                         _("背景推定方式（下の説明参照）。選択に応じて使うパラメータのみ有効化されます"),
                         choices=["inpaint", "tophat", "spline1d", "spline2d"],
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
        self._add_fields(lf_bg, [
            # tophat-specific.
            ("field", "tophat_se_size", "tophat_se_size",
             _("[tophat時のみ] 構造要素直径") + " (px)。"
             + _("最大ファイバー幅の2〜3倍。奇数(偶数は+1)"), {"width": 10}),
            # spline1d-specific.
            ("choice", "spline1d_axis", "spline1d_axis",
             _("[spline1d時のみ] 除去する縞の向き。'y'=横縞(各走査ラインが上下にずれるノイズ)を除去/各列を縦に補間。'x'=縦縞を除去/各行を横に補間(良好な結果が多い)"),
             {"choices": ["y", "x"]}),
            ("field", "spline1d_degree", "spline1d_degree",
             _("[spline1d時のみ] 行/列スプライン order。実用範囲1〜3 (2=旧pandas互換)。点数不足の行は線形に自動フォールバック"), {"width": 10}),
            # spline2d-specific.
            ("field", "spline2d_degree", "spline2d_degree",
             _("[spline2d時のみ] スプライン次数。実用範囲1〜3 (1=双線形、2=旧pandas互換、3=双立方)。[1,5]"), {"width": 10}),
            ("field", "spline2d_subsample", "spline2d_subsample",
             _("[spline2d時のみ] フィット用画素サブサンプル係数。大きいほど高速、品質影響は微少。デフォルト4"), {"width": 10}),
            # spline2d_smoothing is hidden because low smoothing can become ill-conditioned
            # and very slow; spline2d_subsample is the safer GUI-facing speed control.
            # spline2d パイプラインでは小さな s が悪条件・極端に低速な準補間に
            # なり得るため、GUI から外して ProcParams 既定の None に固定する。
            # Mask and threshold parameters shared by inpaint, spline1d, and spline2d.
            ("field", "threshold_factor", "threshold_factor",
             _("[inpaint, spline1d, spline2d時] 背景範囲（中心±sigma*係数）を決める係数"), {}),
            ("field", "fiber_detect_factor", "fiber_detect_factor",
             _("[inpaint, spline1d, spline2d時] [1,0,-1]の急変を繊維として除外する距離しきい値"), {}),
            ("field", "noise_detect_factor", "noise_detect_factor",
             _("[inpaint, spline1d, spline2d時] [1,-1]の急変が一定以上離れている場合に構造とみなすしきい値"), {}),
            # Smoothing parameters shared by inpaint, tophat, and spline1d.
            ("field", "savgol_window", "savgol_window",
             _("[inpaint, tophat, spline1d時] Savitzky-Golayフィルタの窓幅（平滑化範囲）"), {"width": 10}),
            ("field", "savgol_polyorder", "savgol_polyorder",
             _("[inpaint, tophat, spline1d時] Savitzky-Golayフィルタの多項式次数"), {"width": 10}),
            # Post-processing shared by all methods.
            ("bool", "apply_median", "apply_median",
             _("中央値フィルタを最後にかける（点ノイズに強い）"), {}),
            # Mask dilation parameters shared by inpaint, spline1d, and spline2d.
            ("field", "mask_dilation", "mask_dilation",
             _("[inpaint, spline1d, spline2d時] 繊維マスクを膨張させる画素数（0でdilationなし）"), {"width": 10}),
            ("field", "min_mask_component_area", "min_mask_component_area",
             _("[inpaint, spline1d, spline2d時] dilation前にマスクから除外する連結成分の最小面積") + " (px)。"
             + _("1でフィルタ無効"), {"width": 10}),
        ])

    def _build_param_sections(self, plf: ttk.LabelFrame) -> None:
        """
        Build the Segmenter, Skeletonizer, and Kinkdetector parameter groups.
        Segmenter・Skeletonizer・Kinkdetector のパラメータ群を構築する。
        """
        # Built at call time so gettext follows the active language (see _add_fields).
        sections = [
            (_("Segmenter"), [
                ("field", "wsize_localbin", "wsize_localbin", _("局所しきい値の計算に使う窓サイズ"), {"width": 10}),
                ("field", "global_threshold", "global_threshold", _("全体一律の2値化しきい値"), {}),
                ("field", "area_min", "area_min", _("小さい連結成分を消す面積しきい値"), {"width": 10}),
                ("field", "area_min_connecting", "area_min_connecting", _("つながり成分を除くときの面積しきい値"), {"width": 10}),
                ("bool", "apply_no_connecting", "apply_no_connecting", _("つながり除去を実行するかどうか"), {}),
                ("field", "h_length", "h_length", _("線分検出で線分とみなす最小長さ"), {"width": 10}),
                ("field", "h_sratio", "h_sratio", _("線っぽさ") + " (s_ratio) " + _("のしきい値"), {}),
                ("field", "low_threshold", "low_threshold", _("高さが低い成分を消すしきい値"), {}),
            ]),
            (_("Skeletonizer"), [
                ("field", "bp_height", "bp_height", _("分岐点が低い高さか判定するしきい値"), {}),
                ("field", "branch_length", "branch_length", _("枝とみなす短い線を追跡する最大長"), {"width": 10}),
                ("field", "min_area", "min_area", _("小さすぎる線分（ノイズ）を削除する面積しきい値"), {"width": 10}),
                ("field", "max_loop_area", "max_loop_area", _("骨格上の小ループ（マスクの穴由来の二重線）を1本に潰す最大囲み面積。0で無効"), {"width": 10}),
                ("field", "spur_length", "spur_length", _("高さに関係なく除去する行き止まりの短い枝の最大長。画素単位のため解像度に応じて調整。0で無効"), {"width": 10}),
            ]),
            (_("Kinkdetector"), [
                ("field", "kinkangle_deg", "kinkangle_deg", _("折れ線近似の3点のなす角がこの値以下ならkink判定"), {}),
            ]),
        ]
        for title, specs in sections:
            lf = ttk.LabelFrame(plf, text=title)
            lf.pack(fill="x", padx=6, pady=6)
            self._add_fields(lf, specs)

    def _build_save_options(self) -> None:
        """
        Build the save-options group (save_original is UI state, not analysis).
        保存オプション群を構築する（save_original は解析条件ではなく UI 状態）。
        """
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

    def _build_buttons(self) -> None:
        """
        Build the bottom action button row.
        下部の操作ボタン行を構築する。
        """
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
        self._build_display_controls()
        self._build_font_controls()

        # FigureCanvasTkAgg is attached here after _build_ui returns.
        self.view_frame = ttk.Frame(self)
        self.view_frame.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_display_controls(self) -> None:
        """
        Build the display-mode row: mode, title/scale, axis unit, vmin/vmax, overlay.
        表示モード行（表示種別・タイトル/スケール・軸単位・vmin/vmax・重ね表示）を構築する。
        """
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

        # Title/scale display toggles apply immediately.
        ttk.Checkbutton(top, text=_("タイトル表示"), variable=self.show_title_var, command=self._draw).pack(side="left", padx=(10, 4))
        ttk.Checkbutton(top, text=_("スケール表示"), variable=self.show_scale_var, command=self._draw).pack(side="left", padx=(0, 10))

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

        # Overlay selection is used only for the skeletonized view. A dedicated
        # style maps the disabled state to a gray foreground so that, when
        # _update_epbp_state disables the combobox for other modes, the grayed
        # text makes the not-selectable state easy to read at a glance.
        # 重ね表示は細線化ビューでのみ有効。専用スタイルで無効状態を灰色文字に
        # 対応付け、_update_epbp_state が他モードで無効化したときに選択不可で
        # あることをひと目で読み取れるようにする。
        lbl_overlay = ttk.Label(top, text=_("重ね表示"))
        lbl_overlay.pack(side="left", padx=(14, 2))
        self._overlay_style = "Overlay.TCombobox"
        ttk.Style(self).map(self._overlay_style, foreground=[("disabled", "#8a8a8a")])
        self.cmb_overlay = ttk.Combobox(
            top, width=10, textvariable=self.overlay_mode_var,
            values=[_("非表示"), "EP", "BP", "KP", "DP"],
            state="readonly", style=self._overlay_style,
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

    def _build_font_controls(self) -> None:
        """
        Build the font-size row: title/cbar/label/tick/legend sizes and image export.
        フォントサイズ行（タイトル/カラーバー/軸ラベル/軸目盛/凡例のサイズ・画像保存）を構築する。
        """
        # Font-size entries share one Enter-to-commit registry.
        bottom = ttk.Frame(self)
        bottom.pack(side="top", fill="x", padx=8, pady=(0, 4))

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

        ttk.Button(bottom, text=_("画像を保存"), command=self._export).pack(side="left", padx=(16, 4))

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
        # The scale is resolved per file through the parent, using the same
        # order as the main preview (bundle record, then per-file value, then
        # the toolbar entry). Per-axis: X from the width, Y from the height.
        # スケールは親経由でファイル単位に解決し、メインプレビューと同じ順
        # （バンドル記録値 → ファイル単位値 → ツールバー入力欄）を使う。
        # 軸別に、X は幅スケール、Y は高さスケールを使う。
        x_um, y_um = self.parent._preview_scale_xy_um(self.item)

        if unit == "nm":
            x_scale, y_scale = x_um * 1000.0, y_um * 1000.0
            unit_label = "nm"
        else:
            x_scale, y_scale = x_um, y_um
            unit_label = "µm"

        extent = None
        if show_scale:
            # extent converts imshow from pixel coordinates to physical scale.
            extent = [0, x_scale, 0, y_scale]
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
