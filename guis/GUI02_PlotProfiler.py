"""
GUI plugin for extracting AFM height profiles.
AFM 高さプロファイルを抽出する GUI プラグイン。

The plugin loads two-dimensional AFM arrays from bundles, NumPy files,
text/CSV exports, or native Gwyddion files; it lets the user mark two or more
points on the heatmap and computes concatenated profiles along the selected
segments using `skimage.measure.profile_line`.
バンドル、NumPy ファイル、テキスト/CSV エクスポート、または Gwyddion
ネイティブファイルから 2 次元 AFM 配列を読み込み、ヒートマップ上で 2 点以上を
指定して `skimage.measure.profile_line` により各線分のプロファイルを連結計算する。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain string literals because literal_eval cannot parse gettext calls.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Plot Profiler",
    "description": (
        "AFMの高さプロファイルをGUIで取得します。\n"
        "高さプロファイルは skimage.measure の profile_line を用いて計算します。\n"
        "Image_Preprocessor でバックグラウンド補正済みの二次元データ配列を読み込めます。\n"
        "対応形式: .b2z バンドル（calibratedキーを自動抽出）/ .npy / csv / txt / Gwyddion .gwy。\n"
        "高さプロファイルのグラフはレイアウトを調整したうえで画像として出力することも可能です。"
    )
}

# ===== Standard library =====
import os

# ===== Numerical / scientific libraries =====
import numpy as np
from skimage.measure import profile_line

# ===== GUI libraries =====
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg, NavigationToolbar2Tk)
# FigureCanvasTkAgg embeds matplotlib figures in tkinter windows.
# NavigationToolbar2Tk provides the matplotlib pan/zoom toolbar inside tkinter.
from mpl_toolkits.axes_grid1 import make_axes_locatable

# ===== Project libraries =====
# These modules provide project-level data loading, plotting defaults, and UI helpers.
# これらのモジュールは本プロジェクト共通の読み込み、描画既定値、UI 補助機能を提供する。
from lib.blosc2_io import load_blosc2, load_bundle, BUNDLE_EXT
from lib.afm_io import load_afm_text, read_scan_size
from lib.gwy_io import GWY_EXT, list_gwy_channels, load_gwy_image, select_default_channel
from lib.measure import read_scan_size_from_bundle
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, ToolTip, setup_matplotlib_style,
    save_figure_with_dialog, PLOT_FS_DEFAULTS, setup_ttk_theme,
    UNIT_MICROMETER, extent_scale_and_unit, save_csv_with_dialog,
    rewrite_entries, mark_entry_state,
    UnconfirmedEntryMixin, localized_combobox_width,
    DEFAULT_VMIN, DEFAULT_VMAX,
)

# ===== Constants =====
# Default scan size used as the initial scale value (µm).
# 初期スケール値として用いる既定スキャンサイズ (µm)。GUI01 / GUI04 と揃える。
DEFAULT_IMAGE_SIZE_UM = 2.0


class ModalWindow(UnconfirmedEntryMixin):
    """
    Modal profile-figure editor opened from the main profiler window.
    メイン画面から開く高さプロファイル図のモーダル編集ウィンドウ。

    Attributes
    ----------
    parent
        Main `App` window that owns the profile data and controls.
        プロファイルデータと操作部を保持するメイン `App` ウィンドウ。
    modal_window
        Tkinter top-level window used for the modal editor, or None before it opens.
        モーダル編集に使う Tkinter のトップレベルウィンドウ。表示前は None。
    canvasW
        Requested profile-figure canvas width in screen pixels.
        プロファイル図キャンバスの指定幅 (画面ピクセル)。
    canvasH
        Requested profile-figure canvas height in screen pixels.
        プロファイル図キャンバスの指定高さ (画面ピクセル)。
    fontsizelabel
        Axis-label font size used in the designed profile figure.
        調整済みプロファイル図で使う軸ラベルのフォントサイズ。
    fontsizeticks
        Tick-label font size used in the designed profile figure.
        調整済みプロファイル図で使う目盛ラベルのフォントサイズ。
    """

    def __init__(self, parent) -> None:
        """
        Initialize the modal editor wrapper.
        モーダル編集ウィンドウのラッパーを初期化する。

        Parameters
        ----------
        parent
            Main `App` window that owns the profile data and controls.
            プロファイルデータと操作部を保持するメイン `App` ウィンドウ。
        """
        self.parent = parent
        self.modal_window = None

    def open(self) -> None:
        """
        Open the modal editor window.
        モーダル編集ウィンドウを開く。
        """
        # Disable the parent controls while the modal editor is active.
        self.disable_widgets()

        # Track whether a figure has already been drawn.
        self.flag = False

        # Create an independent Toplevel window.
        self.modal_window = tk.Toplevel(self.parent)
        self.modal_window.title(_("Designed graph"))
        apply_window_size(self.modal_window, 820, 640, min_w=720, min_h=520)

        # Match the parent clam theme background for visual consistency.
        # メインウィンドウと同じ clam テーマ背景色に揃える。
        try:
            clam_bg = getattr(self.parent, "_clam_bg", None)
            if clam_bg:
                self.modal_window.configure(bg=clam_bg)
        except tk.TclError:
            pass

        # Reset figure-layout parameters each time the modal window opens.
        self.canvasW = 600
        self.canvasH = 500
        self.fontsizelabel = 13
        self.fontsizeticks = 13

        # Root layout: fixed-height control row above an expandable canvas area.
        control_frame = ttk.Frame(self.modal_window, padding=(8, 8))
        control_frame.pack(side="top", fill="x")

        # Canvas area takes the remaining vertical space.
        self.canvas_frame = ttk.Frame(self.modal_window)
        self.canvas_frame.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))

        self._build_modal_controls(control_frame)

        # Draw once immediately after the window opens.
        self.draw_graph()

        # grab_set() gives this window modal control over UI events.
        self.modal_window.grab_set()

        # Route the window-manager close button through the cleanup path.
        self.modal_window.protocol("WM_DELETE_WINDOW", self.close)

    def _build_modal_controls(self, control_frame: ttk.Frame) -> None:
        """
        Build the modal editor's control row (size, font, tick, grid, save).
        モーダル編集の操作行（サイズ・フォント・目盛り・グリッド・保存）を構築する。
        """
        # Numeric entries use Enter-to-commit; comboboxes redraw immediately.
        # 数値 Entry は Enter 確定、Combobox は選択時に即時再描画する。
        # Keep the modal registry separate from the main App registry.
        # モーダル専用の未確定 Entry 登録簿を使い、App 側とは混ぜない。
        self._init_unconfirmed_registry()

        col = 0
        ttk.Label(control_frame, text=_("幅")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        self.entrycs1 = ttk.Entry(control_frame, width=5)
        self.entrycs1.insert(0, self.canvasW)
        self.entrycs1.grid(row=0, column=col, padx=(0, 8))
        self._register_unconfirmed_entry(
            self.entrycs1,
            lambda: self._fmt_num(self.canvasW),
            self._commit_entries,
        )
        col += 1

        ttk.Label(control_frame, text=_("高さ")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        self.entrycs2 = ttk.Entry(control_frame, width=5)
        self.entrycs2.insert(0, self.canvasH)
        self.entrycs2.grid(row=0, column=col, padx=(0, 8))
        self._register_unconfirmed_entry(
            self.entrycs2,
            lambda: self._fmt_num(self.canvasH),
            self._commit_entries,
        )
        col += 1

        ttk.Label(control_frame, text=_("軸ラベルサイズ")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        self.entryfs1 = ttk.Entry(control_frame, width=5)
        self.entryfs1.insert(0, self.fontsizelabel)
        self.entryfs1.grid(row=0, column=col, padx=(0, 8))
        self._register_unconfirmed_entry(
            self.entryfs1,
            lambda: self._fmt_num(self.fontsizelabel),
            self._commit_entries,
        )
        col += 1

        ttk.Label(control_frame, text=_("目盛りサイズ")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        self.entryfs2 = ttk.Entry(control_frame, width=5)
        self.entryfs2.insert(0, self.fontsizeticks)
        self.entryfs2.grid(row=0, column=col, padx=(0, 8))
        self._register_unconfirmed_entry(
            self.entryfs2,
            lambda: self._fmt_num(self.fontsizeticks),
            self._commit_entries,
        )
        col += 1

        ttk.Label(control_frame, text=_("目盛りの向き")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        # Read-only comboboxes restrict users to supported plotting options.
        optiondirect = [_("外向き"), _("内向き"), _("両方")]
        self.drbox = ttk.Combobox(
            control_frame, values=optiondirect, state="readonly",
            width=localized_combobox_width(optiondirect, min_width=6, max_width=14),
        )
        self.drbox.set(optiondirect[0])
        self.drbox.grid(row=0, column=col, padx=(0, 8))
        # Redraw immediately when the selection changes.
        self.drbox.bind("<<ComboboxSelected>>", lambda _e: self._on_combobox_change())
        col += 1

        ttk.Label(control_frame, text=_("グリッド")).grid(row=0, column=col, padx=(0, 2))
        col += 1
        optiongrid = [_("無し"), _("x軸"), _("y軸"), _("両方")]
        self.gridbox = ttk.Combobox(
            control_frame, values=optiongrid, state="readonly",
            width=localized_combobox_width(optiongrid, min_width=4, max_width=12),
        )
        self.gridbox.set(optiongrid[0])
        self.gridbox.grid(row=0, column=col, padx=(0, 8))
        # Redraw immediately when the selection changes.
        self.gridbox.bind("<<ComboboxSelected>>", lambda _e: self._on_combobox_change())
        col += 1

        # Keep the save button outside draw_graph() so redraws cannot briefly remove it.
        # 保存ボタンは draw_graph() の外に置き、再描画中に押下不能にならないようにする。
        self.save_fig_button = ttk.Button(
            control_frame, text=_("画像を保存"), command=self.save_figure)
        self.save_fig_button.grid(row=0, column=col, padx=(8, 0))

    def close(self) -> None:
        """
        Close the modal editor and re-enable the parent controls.
        モーダル編集ウィンドウを閉じ、親ウィンドウの操作を再有効化する。
        """
        if self.modal_window:
            self.modal_window.destroy()

        # Re-enable parent controls after modal teardown.
        self.enable_widgets()

    def _commit_entries(self) -> bool:
        """
        Commit the four numeric layout entries and redraw the profile figure.
        4 つの数値 Entry を内部状態へ反映し、プロファイル図を再描画する。

        Returns
        -------
        bool
            True if all values were committed; False if conversion failed.
            全値を確定できた場合は True、数値変換に失敗した場合は False。
        """
        return self._commit_float_fields(
            [
                (self.entrycs1, "canvasW",       "canvasW"),
                (self.entrycs2, "canvasH",       "canvasH"),
                (self.entryfs1, "fontsizelabel", "fontsizelabel"),
                (self.entryfs2, "fontsizeticks", "fontsizeticks"),
            ],
            on_success=self.draw_graph,
            parent=self.modal_window,
        )

    def _on_combobox_change(self) -> None:
        """
        Redraw after a tick-direction or grid combobox change.
        目盛り方向またはグリッドの Combobox 変更後に再描画する。

        Notes
        -----
        The redraw uses committed numeric state, so incomplete Entry edits are
        not accidentally committed when a combobox is changed.
        再描画は確定済みの数値状態だけを使うため、Combobox 操作で編集中の
        Entry 値が予期せず確定されることはない。
        """
        self.draw_graph()

    def draw_graph(self) -> None:
        """
        Draw the modal profile figure from committed layout settings.
        確定済みレイアウト設定からモーダル側のプロファイル図を描画する。
        """
        # Draw from committed numeric state; validation is handled by _commit_entries.
        # 数値検証は _commit_entries が担うため、ここでは確定済み内部状態を前提に描画する。

        # On redraw, destroy the previous canvas but keep the save button in control_frame.
        # 再描画時は前回キャンバスだけを破棄し、保存ボタンは control_frame 側に残す。
        if self.flag:
            self.image_widget.destroy()
            self.ax.cla()
            # Close the previous figure to avoid accumulating matplotlib objects.
            try:
                plt.close(self.fig)
            except Exception:
                pass

        # Convert the requested pixel size to inches using a 100-dpi convention.
        fig_w_in = max(self.canvasW / 100.0, 1.0)
        fig_h_in = max(self.canvasH / 100.0, 1.0)
        self.fig, self.ax = plt.subplots(1, 1, figsize=(fig_w_in, fig_h_in))

        # Embed the matplotlib Figure in the modal canvas frame.
        self.canvas = FigureCanvasTkAgg(self.fig, self.canvas_frame)
        self.image_widget = self.canvas.get_tk_widget()
        # Center the user-sized canvas instead of stretching it to fill the frame.
        self.canvas_frame.rowconfigure(0, weight=1)
        self.canvas_frame.rowconfigure(1, weight=0)
        self.canvas_frame.columnconfigure(0, weight=1)
        # Keep the canvas at the user-requested size and center it without stretching.
        # キャンバスはユーザー指定の幅・高さを尊重しつつ、
        # Center the canvas without stretching it across the whole grid cell.
        # 中央寄せで配置する（sticky="" で領域いっぱいに広げない）
        self.image_widget.configure(width=int(self.canvasW), height=int(self.canvasH))
        self.image_widget.grid(row=0, column=0, sticky="")

        # The save button is persistent in control_frame and is not recreated here.

        # Convert localized combobox labels to matplotlib tick-direction values.
        dr = self.drbox.get()
        if dr == _("外向き"):
            self.direction = 'out'
        elif dr == _("内向き"):
            self.direction = 'in'
        elif dr == _("両方"):
            self.direction = 'inout'

        # Convert localized grid labels to matplotlib grid options.
        gr = self.gridbox.get()
        if gr == _("無し"):
            grv = False
            graxis = 'both'
        elif gr == _("x軸"):
            grv = True
            graxis = 'x'
        elif gr == _("y軸"):
            grv = True
            graxis = 'y'
        elif gr == _("両方"):
            grv = True
            graxis = 'both'

        # profilex is stored in micrometers; convert only for nanometer display.
        # profilex は µm 固定で保持し、nm 表示時だけ 1000 倍する。
        scale_disp, unit_label = self.parent._get_extent_scale_and_unit()
        y = self.parent.profiley
        x = (
            self.parent.profilex * 1000.0
            if unit_label == "nm"
            else self.parent.profilex
        )
        self.ax.plot(x, y, color='black', lw=1)
        self.ax.set_xlabel("Length ({})".format(unit_label), fontsize=self.fontsizelabel)
        self.ax.set_ylabel("Height (nm)", fontsize=self.fontsizelabel)
        self.ax.tick_params(direction=self.direction, labelsize=self.fontsizeticks)
        self.ax.grid(visible=grv, which='major', axis=graxis)

        # Increase margins for larger fonts so labels are not clipped.
        base_fontsize = 10
        label_ratio = self.fontsizelabel / base_fontsize
        ticks_ratio = self.fontsizeticks / base_fontsize
        # Cap margins so the plot area does not collapse for large font sizes.
        left   = min(0.12 * label_ratio + 0.05 * ticks_ratio, 0.30)
        bottom = min(0.10 * label_ratio + 0.04 * ticks_ratio, 0.25)
        self.fig.subplots_adjust(left=left, bottom=bottom, right=0.97, top=0.97)
        self.canvas.draw()

        self.flag = True

    def save_figure(self) -> None:
        """
        Save the current designed profile figure.
        現在の調整済みプロファイル図を画像ファイルとして保存する。
        """
        if not self.flag:
            return
        try:
            base = os.path.splitext(self.parent.filename)[0] + "_profile.png"
            initial_dir = self.parent._default_save_dir()
        except AttributeError:
            base = "profile.png"
            initial_dir = os.getcwd()
        save_figure_with_dialog(
            self.modal_window, self.fig,
            initial_name=base,
            initial_dir=initial_dir,
            title=_("プロファイル画像を保存"),
        )
            
    def _walk_widgets(self, root) -> list:
        """
        Recursively yield widgets under `root`.
        `root` 配下のウィジェットを再帰的に列挙する。
        """
        for child in root.winfo_children():
            yield child
            yield from self._walk_widgets(child)

    def disable_widgets(self) -> None:
        """
        Disable controls in the parent window while the modal editor is open.
        モーダル編集ウィンドウ表示中に親ウィンドウの操作部を無効化する。
        """
        for widget in self._walk_widgets(self.parent.labelFrame):
            # ttk widgets use state(); classic tk widgets use config(state=...).
            if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
                try:
                    widget.state(['disabled'])
                except tk.TclError:
                    pass
            elif isinstance(widget, (tk.Button, tk.Entry, tk.Text)):
                try:
                    widget.config(state='disabled')
                except tk.TclError:
                    pass
            elif isinstance(widget, ttk.Label):
                try:
                    widget.state(['disabled'])
                except tk.TclError:
                    pass
            elif isinstance(widget, tk.Label):
                try:
                    widget.config(fg='gray')
                except tk.TclError:
                    pass
    
    def enable_widgets(self) -> None:
        """
        Re-enable controls in the parent window after the modal editor closes.
        モーダル編集ウィンドウ終了後に親ウィンドウの操作部を再有効化する。
        """
        for widget in self._walk_widgets(self.parent.labelFrame):
            if isinstance(widget, ttk.Combobox):
                try:
                    widget.state(['!disabled', 'readonly'])
                except tk.TclError:
                    pass
            elif isinstance(widget, (ttk.Button, ttk.Entry, ttk.Checkbutton, ttk.Label)):
                try:
                    widget.state(['!disabled'])
                except tk.TclError:
                    pass
            elif isinstance(widget, (tk.Button, tk.Entry, tk.Text)):
                try:
                    widget.config(state='normal')
                except tk.TclError:
                    pass
            elif isinstance(widget, tk.Label):
                try:
                    widget.config(fg='black')
                except tk.TclError:
                    pass

class App(tk.Tk, UnconfirmedEntryMixin):
    """
    Main window for loading AFM images and extracting height profiles.
    AFM 画像を読み込み、高さプロファイルを抽出するメインウィンドウ。

    Attributes
    ----------
    scale_um
        Physical scan size in micrometers used to map display coordinates to pixels.
        表示座標をピクセルへ変換するための物理スキャンサイズ (µm)。
    unit
        Current length-display unit shown on the heatmap and profile axes.
        ヒートマップとプロファイル軸に表示する現在の長さ単位。
    vmin
        Lower heatmap color-limit value in nanometers.
        ヒートマップ色範囲の下限値 (nm)。
    vmax
        Upper heatmap color-limit value in nanometers.
        ヒートマップ色範囲の上限値 (nm)。
    linewidth
        Sampling width in pixels passed to `skimage.measure.profile_line`.
        `skimage.measure.profile_line` に渡すサンプリング線幅 (px)。
    reduce_func
        Aggregation function used when the sampling line covers multiple pixels.
        サンプリング線が複数ピクセルを含む場合に使う集計関数。
    xlist
        Marked point x-coordinates stored internally in micrometers.
        内部的に µm 単位で保持する打点 x 座標。
    ylist
        Marked point y-coordinates stored internally in micrometers.
        内部的に µm 単位で保持する打点 y 座標。
    profilex
        Concatenated profile-distance axis stored internally in micrometers.
        内部的に µm 単位で保持する連結済みプロファイル距離軸。
    profiley
        Concatenated AFM height profile stored in nanometers.
        nm 単位で保持する連結済み AFM 高さプロファイル。
    """

    def __init__(self) -> None:
        """
        Initialize the main profiler window and persistent plotting state.
        メインプロファイラーウィンドウと永続的な描画状態を初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])
        setup_matplotlib_style(font_size=12)

        self._clam_bg = setup_ttk_theme(self)

        apply_window_size(self, 1280, 720, min_w=1100, min_h=580)
        self.resizable(True, True)

        # Track whether the heatmap and profile canvases currently contain data.
        self.flag1 = False
        self.flag2 = False

        # Input is always in µm. The radio button only switches the displayed
        # axis-tick unit (µm/nm) without changing this stored value.
        # 入力欄は µm 固定。ラジオボタンは軸目盛の表示単位 (µm/nm) を切り替えるだけで、
        # ここに保持する値そのものは変化させない（GUI01 / GUI04 と同仕様）。
        # scale_um is the X (width) size; scale_y_um is the optional Y (height)
        # size for rectangular scans. None means "same as X" (square scan).
        # scale_um は X（幅）サイズ、scale_y_um は矩形スキャン用の任意の Y（高さ）
        # サイズ。None は「X と同値」（正方スキャン）を意味する。
        self.scale_um = DEFAULT_IMAGE_SIZE_UM
        self.scale_y_um = None
        self.unit = UNIT_MICROMETER
        # Heatmap height range is stored in nanometers and shared with GUI01/GUI04 defaults.
        # ヒートマップ高さ範囲は nm で保持し、GUI01 / GUI04 と共通の既定値を使う。
        self.vmin = float(DEFAULT_VMIN)
        self.vmax = float(DEFAULT_VMAX)
        self.linewidth = 3
        self.reduce_func = np.max

        # Auto vmin/vmax follows each loaded image so users can inspect varied files quickly.
        # 自動 vmin/vmax は画像ごとの範囲に追随し、多様な画像を切替確認しやすくする。
        self.auto_vrange_var = tk.BooleanVar(value=True)

        # Use shared project plotting defaults for consistent GUI output.
        self.fs_title = PLOT_FS_DEFAULTS["title_fs"]
        self.fs_label = PLOT_FS_DEFAULTS["label_fs"]
        self.fs_tick  = PLOT_FS_DEFAULTS["tick_fs"]
        self.fs_cbar  = PLOT_FS_DEFAULTS["cbar_fs"]

        # Store mpl_connect ID so file_select() can disconnect stale click handlers.
        self._click_cid = None

        # Create the modal editor wrapper; it opens lazily.
        self.modal = ModalWindow(self)

        # Registry for Entry fields whose text may differ from committed state.
        # Entry 表示文字列と確定済み内部値の差分を管理する登録簿。
        self._init_unconfirmed_registry()

        # Root container for all visible content.
        self.labelFrame = ttk.Frame(self)
        self.labelFrame.pack(fill="both", expand=True, padx=4, pady=4)

        # Only the content row expands vertically.
        self.labelFrame.rowconfigure(0, weight=0)
        self.labelFrame.rowconfigure(1, weight=0)
        self.labelFrame.rowconfigure(2, weight=0)
        self.labelFrame.rowconfigure(3, weight=1)
        self.labelFrame.columnconfigure(0, weight=1)

        # Build each UI region top-to-bottom; creation order is preserved.
        self._build_file_row()
        self._build_param_row()
        self._build_action_row()
        self._build_content_area()

    def _build_file_row(self) -> None:
        """
        Build the file-selection row (Row 0).
        ファイル選択行（Row 0）を構築する。
        """
        # Row 0: file selection.
        file_row = ttk.Frame(self.labelFrame)
        file_row.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

        load_button = ttk.Button(
            file_row, text=_("参照"), command=self.load_image)
        load_button.grid(row=0, column=0, padx=(0, 8))

        # Placeholder text is replaced with the selected filename after loading.
        self.label2 = ttk.Label(
            file_row, text=_('←このボタンを押してファイルを選んで下さい'),
        )
        self.label2.grid(row=0, column=1, sticky="w")
        self.showfilename = None
        file_row.columnconfigure(1, weight=1)

        # Channel selector for multi-channel Gwyddion .gwy inputs. Hidden until a
        # .gwy with more than one channel is loaded; the topography channel is
        # auto-selected, and changing this dropdown reloads another channel.
        # 複数チャンネルの Gwyddion .gwy 入力用チャンネル選択。チャンネルが複数
        # ある .gwy を読むまで非表示。地形チャンネルを自動選択し、このドロップ
        # ダウンを変更すると別チャンネルを読み込む。
        self.gwy_channel_label = ttk.Label(file_row, text=_("チャンネル"))
        self.gwy_channel_box = ttk.Combobox(file_row, state="readonly", width=22)
        self.gwy_channel_box.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_gwy_channel_change()
        )
        self.gwy_channel_label.grid(row=0, column=2, padx=(8, 2))
        self.gwy_channel_box.grid(row=0, column=3, padx=(0, 4))
        self.gwy_channel_label.grid_remove()
        self.gwy_channel_box.grid_remove()
        # Channels of the current .gwy and the chosen id (None = text / auto).
        # 現在の .gwy のチャンネルと選択中の id（None = テキスト / 自動）。
        self._gwy_channels = []
        self._gwy_channel_id = None

    def _build_param_row(self) -> None:
        """
        Build the parameter row (Row 1): scale, height range, line width,
        aggregation method, and font sizes.
        パラメータ行（Row 1）: スケール・高さ範囲・線幅・計算方法・
        フォントサイズを構築する。
        """
        # Numeric Entry values are committed only by Enter; unit radios apply immediately.
        # 数値 Entry は Enter でのみ確定し、単位ラジオは選択時に即時反映する。
        param_row = ttk.Frame(self.labelFrame)
        param_row.grid(row=1, column=0, sticky="ew", padx=6, pady=2)

        # Physical-size input stays in micrometers; radios only change displayed tick units.
        # 実寸入力は µm 固定で、ラジオは軸目盛の表示単位だけを切り替える。
        c = 0
        ttk.Label(param_row, text=_("スケール") + " (µm)").grid(row=0, column=c, padx=(0, 4))
        c += 1
        self.entryas = ttk.Entry(param_row, width=6)
        self.entryas.insert(0, self._fmt_num(self.scale_um))
        self.entryas.grid(row=0, column=c, padx=(0, 4))
        self._register_unconfirmed_entry(
            self.entryas,
            lambda: self._fmt_num(self.scale_um),
            self.validate_input1,
        )
        ToolTip(self.entryas, _("AFM 画像の X（幅）方向の実寸") + " (µm)。")
        c += 1
        # Optional Y (height) size for rectangular scans. "X" is the left
        # entry, "Y" the right; an empty Y means a square scan (Y = X).
        # 矩形スキャン用の任意の Y（高さ）サイズ。左が X、右が Y で、Y 空欄は
        # 正方スキャン（Y = X）を意味する。
        ttk.Label(param_row, text="×").grid(row=0, column=c, padx=(0, 2))
        c += 1
        self.entry_scale_y = ttk.Entry(param_row, width=6)
        self.entry_scale_y.grid(row=0, column=c, padx=(0, 4))
        self._register_unconfirmed_entry(
            self.entry_scale_y,
            lambda: "" if self.scale_y_um is None
            else self._fmt_num(self.scale_y_um),
            self.validate_scale_y,
        )
        ToolTip(
            self.entry_scale_y,
            _("AFM 画像の Y（高さ）方向の実寸") + " (µm)。\n"
            + _("空欄なら X（幅）と同じ（正方スキャン）。"),
        )
        c += 1
        # Use the shared U+00B5 micrometer symbol constant for label consistency.
        # µm 表記は UNIT_MICROMETER (U+00B5) に統一する。
        self.unit_var = tk.StringVar(value=self.unit)
        ttk.Radiobutton(
            param_row, text=UNIT_MICROMETER, value=UNIT_MICROMETER,
            variable=self.unit_var, command=self.unit_selected,
        ).grid(row=0, column=c, padx=(0, 2))
        c += 1
        ttk.Radiobutton(
            param_row, text="nm", value="nm",
            variable=self.unit_var, command=self.unit_selected,
        ).grid(row=0, column=c, padx=(0, 12))
        c += 1

        # Height-range controls. Auto mode recalculates vmin/vmax from the current image.
        # 高さ範囲の自動モードでは、現在画像から vmin/vmax を再計算する。
        self.chk_auto_vrange = ttk.Checkbutton(
            param_row, text=_("自動"),
            variable=self.auto_vrange_var,
            command=self._on_auto_vrange_toggle,
        )
        self.chk_auto_vrange.grid(row=0, column=c, padx=(0, 4))
        ToolTip(self.chk_auto_vrange, _(
            "ON時: 画像ごとに vmin/vmax を自動計算。\n"
            "  vmin = 画像最小値 を切り下げ\n"
            "  vmax = 画像最大値 + 1 を切り上げ\n"
            "OFF時: 入力欄の vmin / vmax を固定使用。"
        ))
        c += 1

        ttk.Label(param_row, text="vmin").grid(row=0, column=c, padx=(0, 4))
        c += 1
        self.ent_vmin = ttk.Entry(param_row, width=5)
        self.ent_vmin.insert(0, self._fmt_num(self.vmin))
        self.ent_vmin.grid(row=0, column=c, padx=(0, 2))
        self._register_unconfirmed_entry(
            self.ent_vmin,
            lambda: self._fmt_num(self.vmin),
            self._commit_vrange,
        )
        c += 1
        ttk.Label(param_row, text="vmax").grid(row=0, column=c, padx=(0, 2))
        c += 1
        self.ent_vmax = ttk.Entry(param_row, width=5)
        self.ent_vmax.insert(0, self._fmt_num(self.vmax))
        self.ent_vmax.grid(row=0, column=c, padx=(0, 12))
        self._register_unconfirmed_entry(
            self.ent_vmax,
            lambda: self._fmt_num(self.vmax),
            self._commit_vrange,
        )
        c += 1

        # Put the tooltip on the label; the Entry is mainly keyboard-operated.
        lw_label = ttk.Label(param_row, text=_("線幅（ピクセル）:"))
        lw_label.grid(row=0, column=c, padx=(0, 4))
        ToolTip(lw_label, _(
            "高さプロファイルを取得する線分の垂直方向の幅（ピクセル数）。\n"
            "1 にすると線分の真上のみ、3 以上にすると周囲数ピクセルも含めて\n"
            "下の「計算方法」で集計した値が高さとして使われます。\n"
            "ナノファイバーの場合、3〜5 程度に設定するとノイズの影響を抑えられます。"
        ))
        c += 1
        self.entrylw = ttk.Entry(param_row, width=4)
        self.entrylw.insert(0, self.linewidth)
        self.entrylw.grid(row=0, column=c, padx=(0, 12))
        self._register_unconfirmed_entry(
            self.entrylw,
            lambda: self._fmt_num(self.linewidth),
            self.input_lw,
        )
        c += 1

        # Aggregation method for profile_line when line width covers multiple pixels.
        # 線幅が複数ピクセルを含む場合の profile_line 集計方法。
        rf_label = ttk.Label(param_row, text=_("計算方法"))
        rf_label.grid(row=0, column=c, padx=(0, 4))
        ToolTip(rf_label, _(
            "上の「線幅」が 2 以上のとき、線分垂直方向の複数ピクセルから\n"
            "1 つの高さ値を決める集計方法。\n"
            "「最大」: 最も高い値を採用（ファイバー本体の高さを拾いやすい）\n"
            "「最小」: 最も低い値を採用（背景レベルの確認に有用）\n"
            "「平均」: 平均値を採用（ノイズを平滑化したいとき）"
        ))
        c += 1
        optionrf = [_("最大"), _("最小"), _("平均")]
        self.rfbox = ttk.Combobox(
            param_row, values=optionrf, state="readonly",
            width=localized_combobox_width(optionrf, min_width=4, max_width=12),
        )
        self.rfbox.set(optionrf[0])
        self.rfbox.bind("<<ComboboxSelected>>", self.rf_selected)
        self.rfbox.grid(row=0, column=c, padx=(0, 12))
        c += 1

        # Heatmap font-size controls use shared defaults and Enter-to-commit behavior.
        # ヒートマップのフォントサイズは共通既定値を使い、Enter で確定する。
        ttk.Label(param_row, text=_("フォントサイズ：タイトル")).grid(
            row=0, column=c, padx=(0, 2))
        c += 1
        self.entry_fs_title = ttk.Entry(param_row, width=4)
        self.entry_fs_title.insert(0, self.fs_title)
        self.entry_fs_title.grid(row=0, column=c, padx=(0, 6))
        self._register_unconfirmed_entry(
            self.entry_fs_title,
            lambda: self._fmt_num(self.fs_title),
            self.validate_font_sizes,
        )
        c += 1

        ttk.Label(param_row, text=_("軸ラベル")).grid(row=0, column=c, padx=(0, 2))
        c += 1
        self.entry_fs_label = ttk.Entry(param_row, width=4)
        self.entry_fs_label.insert(0, self.fs_label)
        self.entry_fs_label.grid(row=0, column=c, padx=(0, 6))
        self._register_unconfirmed_entry(
            self.entry_fs_label,
            lambda: self._fmt_num(self.fs_label),
            self.validate_font_sizes,
        )
        c += 1

        ttk.Label(param_row, text=_("軸目盛")).grid(row=0, column=c, padx=(0, 2))
        c += 1
        self.entry_fs_tick = ttk.Entry(param_row, width=4)
        self.entry_fs_tick.insert(0, self.fs_tick)
        self.entry_fs_tick.grid(row=0, column=c, padx=(0, 6))
        self._register_unconfirmed_entry(
            self.entry_fs_tick,
            lambda: self._fmt_num(self.fs_tick),
            self.validate_font_sizes,
        )
        c += 1

        ttk.Label(param_row, text=_("カラーバー")).grid(row=0, column=c, padx=(0, 2))
        c += 1
        self.entry_fs_cbar = ttk.Entry(param_row, width=4)
        self.entry_fs_cbar.insert(0, self.fs_cbar)
        self.entry_fs_cbar.grid(row=0, column=c, padx=(0, 0))
        self._register_unconfirmed_entry(
            self.entry_fs_cbar,
            lambda: self._fmt_num(self.fs_cbar),
            self.validate_font_sizes,
        )
        c += 1

    def _build_action_row(self) -> None:
        """
        Build the point-cancel action row (Row 2).
        打点取り消し操作行（Row 2）を構築する。
        """
        # Row 2: point-cancel actions and operation guide.
        action_row = ttk.Frame(self.labelFrame)
        action_row.grid(row=2, column=0, sticky="ew", padx=6, pady=2)

        # Remove the most recently marked point.
        buttoncl = ttk.Button(
            action_row, text=_("一点取り消し"), command=self.cancel_plot)
        buttoncl.grid(row=0, column=0, padx=(0, 6))

        # Remove all marked points.
        buttoncl2 = ttk.Button(
            action_row, text=_("全点取り消し"), command=self.clear_all_points)
        buttoncl2.grid(row=0, column=1, padx=(0, 16))

        # Reserve guide-label space; text is filled after a file is loaded.
        self.guide_label = ttk.Label(action_row, text="", anchor="w")
        self.guide_label.grid(row=0, column=2, sticky="w")
        action_row.columnconfigure(2, weight=1)

    def _build_content_area(self) -> None:
        """
        Build the content area (Row 3): heatmap panel, separator, profile panel.
        コンテンツ領域（Row 3）: ヒートマップ・セパレータ・プロファイルを構築する。
        """
        # Row 3: content area with heatmap panel, separator, and profile panel.
        content_row = ttk.Frame(self.labelFrame)
        content_row.grid(row=3, column=0, sticky="nsew", padx=6, pady=(2, 6))
        # Left and right panels expand equally; the center separator stays fixed.
        content_row.columnconfigure(0, weight=1, uniform="panels")
        content_row.columnconfigure(1, weight=0)  # Separator
        content_row.columnconfigure(2, weight=1, uniform="panels")
        content_row.rowconfigure(0, weight=1)

        # -- Center separator: visually separates heatmap and profile workflows. --
        # Grid placement is order-independent, so the separator is created here.
        ttk.Separator(content_row, orient="vertical").grid(
            row=0, column=1, sticky="ns", padx=4,
        )

        self._build_heatmap_panel(content_row)
        self._build_profile_panel(content_row)

    def _build_heatmap_panel(self, content_row) -> None:
        """
        Build the left heatmap panel with its toolbar and action buttons.
        左側のヒートマップパネル（ツールバー・操作ボタン付き）を構築する。
        """
        # -- Left panel: heatmap --
        self.heatmap_panel = ttk.Frame(content_row)
        self.heatmap_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        # Canvas above, toolbar and buttons below.
        self.heatmap_panel.rowconfigure(0, weight=1)
        self.heatmap_panel.rowconfigure(1, weight=0)
        self.heatmap_panel.columnconfigure(0, weight=1)

        # Create the heatmap figure; figure inches are independent of screen pixels.
        self.fig, self.ax = plt.subplots(figsize=(5, 4.5))
        self.canvas = FigureCanvasTkAgg(self.fig, self.heatmap_panel)
        # Let the heatmap canvas expand with the panel.
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        # Toolbar plus reset and image-save buttons, kept on a single row.
        heatmap_tb_row = ttk.Frame(self.heatmap_panel)
        heatmap_tb_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # Pack the custom reset/save buttons (side="right") BEFORE the toolbar so the
        # toolbar's growable coordinate readout can never squeeze them on hover.
        # ツールバーの座標表示はホバー時に横へ伸びるため、独自ボタンを先に右側へ確保し、
        # 押し潰されないようにする。
        # Custom reset button redraws the heatmap with the current view settings.
        buttonhome = ttk.Button(
            heatmap_tb_row, text=_("リセット"), command=self.home)
        buttonhome.pack(side="right", padx=(8, 0))

        # Custom image-save button exports the current heatmap figure.
        button_save_img = ttk.Button(
            heatmap_tb_row, text=_("画像を保存"), command=self.save_heatmap_image)
        button_save_img.pack(side="right", padx=(8, 0))

        # NavigationToolbar2Tk uses pack internally, so isolate it in a dedicated frame.
        toolbar_frame = ttk.Frame(heatmap_tb_row)
        toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        toolbar.update()
        # NavigationToolbar2Tk is a fixed figure-width frame (pack_propagate(False)), so it
        # spreads Pan/Zoom and the right-aligned coordinate readout across the whole figure
        # width. Re-enable propagation so the toolbar shrinks to just Pan/Zoom, removing that
        # dead space and leaving room for the custom buttons on the same row.
        # ツールバーは図幅で固定（pack_propagate(False)）のため、Pan/Zoom と右寄せの座標表示が
        # 図幅いっぱいに引き離される。伝播を戻して Pan/Zoom 幅まで縮め、その空白をなくして
        # 同じ行に独自ボタンを収める。
        toolbar.pack_propagate(True)

        # NavigationToolbar2Tk uses classic tk widgets, so manually match the clam background.
        # NavigationToolbar2Tk は ttk テーマ外のため、clam 背景色へ手動で揃える。
        try:
            toolbar.configure(bg=self._clam_bg)
        except tk.TclError:
            pass
        for child in toolbar.winfo_children():
            try:
                child.configure(bg=self._clam_bg)
            except tk.TclError:
                # Skip widgets that do not expose a classic tk bg option.
                pass

        # Keep only Pan/Zoom from the matplotlib toolbar; custom buttons handle reset/save.
        # matplotlib ツールバーは Pan/Zoom だけ残し、リセット/保存は独自ボタンで扱う。
        _KEEP_BUTTON_TEXTS = {"Pan", "Zoom"}
        for child in list(toolbar.winfo_children()):
            # Both tk.Button and ttk.Button expose a text option.
            try:
                txt = child.cget("text")
            except tk.TclError:
                continue
            # Hide unwanted toolbar buttons instead of destroying them: matplotlib
            # keeps references to Back/Forward in NavigationToolbar2Tk._buttons and
            # configures their state from set_history_buttons() during Pan/Zoom.
            # Destroying the widgets makes that call raise TclError, so only unmap them.
            # 不要なボタンは破棄せず非表示にする。matplotlib は Back/Forward を
            # NavigationToolbar2Tk._buttons に保持し、Pan/Zoom 操作時に
            # set_history_buttons() でその state を設定する。破棄するとこの呼び出しが
            # TclError になるため、レイアウトから外すだけにとどめる。
            if isinstance(child, (tk.Button, ttk.Button)) and txt not in _KEEP_BUTTON_TEXTS:
                child.pack_forget()

        # Place the toolbar last (side="left", no fill/expand) so it occupies only its own
        # width and leaves the rest of the row for the custom buttons packed above.
        # ツールバーは最後に左寄せ（fill/expand なし）で配置し、自分の幅だけ占有して
        # 残りを上で確保した独自ボタンへ渡す。
        toolbar_frame.pack(side="left")

        self.canvas.draw()

    def _build_profile_panel(self, content_row) -> None:
        """
        Build the right profile panel and lazy-canvas placeholders.
        右側のプロファイルパネルと遅延生成キャンバスのプレースホルダを構築する。
        """
        # -- Right panel: height profile --
        self.profile_panel = ttk.Frame(content_row)
        self.profile_panel.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self.profile_panel.rowconfigure(0, weight=1)
        self.profile_panel.rowconfigure(1, weight=0)
        self.profile_panel.columnconfigure(0, weight=1)

        # The profile canvas is created lazily by make_profile(); show a guide initially.
        # プロファイル描画用キャンバスは make_profile() で遅延作成し、初期状態では操作ガイドを表示する。
        self.profile_canvas_container = ttk.Frame(self.profile_panel)
        self.profile_canvas_container.grid(row=0, column=0, sticky="nsew")
        self.profile_canvas_container.rowconfigure(0, weight=1)
        self.profile_canvas_container.columnconfigure(0, weight=1)

        # Placeholder shown while no profile is drawn.
        self.profile_placeholder = ttk.Label(
            self.profile_canvas_container,
            text=_("左クリックでパン、右クリックで打点。\n"
                   "最低2点で高さプロファイルが表示されます。"),
            anchor="center",
            justify="center",
            foreground="gray",
        )
        self.profile_placeholder.grid(row=0, column=0, sticky="nsew")

        # Button row for profile export/layout actions, initially empty.
        self.profile_button_row = ttk.Frame(self.profile_panel)
        self.profile_button_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        # Buttons are created by make_profile() and hidden by hide_profile_canvas().
        self.buttonsavecsv = None
        self.button_save_profile_img = None
        self.open_button = None
        # Matplotlib objects for the profile panel, set by make_profile().
        self.image_widget2 = None
        self.canvas2 = None
        self.fig2 = None
        self.ax2 = None

    # ---------- Callbacks and logic ----------
    # Unconfirmed-entry behavior is implemented by ui_tools.UnconfirmedEntryMixin.
    # 未確定 Entry の共通処理は ui_tools.UnconfirmedEntryMixin に集約している。

    def validate_font_sizes(self) -> bool:
        """
        Validate and commit heatmap/profile font-size entries together.
        ヒートマップ・プロファイル用フォントサイズをまとめて検証・確定する。

        Returns
        -------
        bool
            True if all font sizes were committed; False if validation failed.
            全フォントサイズを確定できた場合は True、不正値なら False。
        """
        keys = ("fs_title", "fs_label", "fs_tick", "fs_cbar")

        def _on_success():
            if self.flag1:
                # Font size only — reuse the cached image array.
                # フォントサイズの変更だけなのでキャッシュ済み画像を再利用する。
                self.image_showing(reload=False)
                self.line_redraw()
            # Profile axes also use fs_label/fs_tick, so redraw if visible.
            if self.flag2:
                self.make_profile()

        return self._commit_float_fields(
            [
                (self.entry_fs_title, "fs_title", "title"),
                (self.entry_fs_label, "fs_label", "label"),
                (self.entry_fs_tick,  "fs_tick",  "tick"),
                (self.entry_fs_cbar,  "fs_cbar",  "cbar"),
            ],
            # Limit values that would not error in matplotlib but would break layout.
            validator=lambda v: None if all(1 <= v[k] <= 60 for k in keys)
            else _("フォントサイズは 1〜60 の範囲で入力してください"),
            on_success=_on_success,
        )

    def validate_input1(self) -> bool:
        """
        Validate and commit the physical image scale in micrometers.
        画像実寸スケール (µm) を検証・確定する。

        Returns
        -------
        bool
            True if the scale was committed; False if validation failed.
            スケール値を確定できた場合は True、不正値なら False。
        """
        # Capture the effective per-axis scales before the commit so stored
        # points can be rescaled by each axis's own ratio (Y follows X when
        # the Y entry is empty, so changing X then rescales Y as well).
        # コミット前に軸別の実効スケールを控え、各軸の比率で打点を再変換する
        # （Y 欄が空なら Y は X に従うので、X 変更時は Y も再変換される）。
        old_x, old_y = self._scale_xy_um()

        def _on_success():
            if self.flag1:
                # Scale value only changes the axis extent, not the pixel data
                # itself — keep using the cached image array.
                # スケール値の変更は軸の extent を変えるだけで画素データ自体は変わらない。
                # キャッシュ済み画像を使い回す。
                self.image_showing(reload=False)
                new_x, new_y = self._scale_xy_um()
                self._rescale_points(old_x, new_x, old_y, new_y)

        return self._commit_float_fields(
            [(self.entryas, "scale_um", "scale_um")],
            validator=lambda v: None if v["scale_um"] > 0
            else _("スケール") + " (µm) " + _("は正の数を入力してください"),
            on_success=_on_success,
        )

    def validate_scale_y(self) -> bool:
        """
        Validate and commit the optional Y (height) scale in micrometers.
        任意の Y（高さ）スケール (µm) の入力欄を検証・確定する。

        An empty field commits ``None`` (Y follows X, square scan); a non-empty
        field must be positive. Stored points are rescaled along Y by the
        change in the effective Y scale.
        空欄は ``None`` を確定し（Y は X に従う＝正方スキャン）、非空欄は正の数で
        あること。実効 Y スケールの変化分だけ打点を Y 方向に再変換する。
        """
        old_x, old_y = self._scale_xy_um()
        raw = self.entry_scale_y.get().strip()
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
        rewrite_entries(((self.entry_scale_y, committed),))
        mark_entry_state(self.entry_scale_y, committed)
        if self.flag1:
            self.image_showing(reload=False)
            new_x, new_y = self._scale_xy_um()
            self._rescale_points(old_x, new_x, old_y, new_y)
        return True

    def _scale_xy_um(self) -> tuple:
        """
        Return the (X, Y) scan size in micrometers; Y falls back to X when unset.
        走査範囲 (X, Y) を µm で返す。Y 未設定時は X にフォールバックする。
        """
        y = self.scale_y_um if self.scale_y_um is not None else self.scale_um
        return self.scale_um, y

    def _rescale_points(self, old_x: float, new_x: float,
                        old_y: float, new_y: float) -> None:
        """
        Rescale stored micrometer points when the physical scale changes.
        実寸スケール変更時に、µm 単位で保持した打点を再変換する。

        Points are kept at the same pixel location, so each axis is scaled by
        its own new/old ratio.
        打点は同じ画素位置に保つため、各軸を自身の new/old 比で拡縮する。
        """
        if not self.xlist:
            return
        self.xlist = (np.array(self.xlist) * new_x / old_x).tolist()
        self.ylist = (np.array(self.ylist) * new_y / old_y).tolist()
        self.line_redraw()
        if self.flag2:
            self.make_profile()

    def _get_extent_scale_xy_and_unit(self) -> tuple:
        """
        Return per-axis extent scales and the shared unit label.
        軸別の extent スケールと共通の単位ラベルを返す。

        X uses the width scale and Y the height scale, so rectangular scans draw
        with the correct physical aspect. Nanometer display multiplies by 1000.
        X は幅スケール、Y は高さスケールを使い、矩形スキャンを正しい物理アスペクト
        で描画する。nm 表示では 1000 倍する。
        """
        x_um, y_um = self._scale_xy_um()
        unit = self.unit_var.get()
        x_scale, unit_label = extent_scale_and_unit(x_um, unit)
        y_scale, _unit_label = extent_scale_and_unit(y_um, unit)
        return x_scale, y_scale, unit_label

    def _default_save_dir(self) -> str:
        """
        Return the directory of the loaded input file for save dialogs.
        保存ダイアログ用に、読み込んだ入力ファイルのフォルダを返す。
        """
        path = getattr(self, "path", "")
        if path:
            return os.path.dirname(path) or os.getcwd()
        return os.getcwd()

    def home(self) -> None:
        """
        Reset the heatmap view without reloading image data.
        画像データを再読込せずにヒートマップ表示をリセットする。
        """
        if self.flag1:
            # Zoom reset only — no need to re-read the file.
            # ズームを元に戻すだけなのでファイル再読込は不要。
            self.image_showing(reload=False)
            self.line_redraw()
            
    def save_heatmap_image(self) -> None:
        """
        Save the current heatmap figure as an image file.
        現在のヒートマップ図を画像ファイルとして保存する。
        """
        if not self.flag1:
            messagebox.showinfo(_("情報"), _("先にファイルを読み込んでください。"))
            return
        save_figure_with_dialog(
            self, self.fig,
            initial_name=os.path.splitext(self.filename)[0] + ".png",
            initial_dir=self._default_save_dir(),
            title=_("ヒートマップを保存"),
        )

    def save_profile_image(self) -> None:
        """
        Save the current profile figure as an image file.
        現在のプロファイル図を画像ファイルとして保存する。
        """
        if not self.flag2:
            messagebox.showinfo(_("情報"), _("先に高さプロファイルを描画してください。"))
            return
        try:
            base = os.path.splitext(self.filename)[0] + "_profile.png"
        except AttributeError:
            base = "profile.png"
        save_figure_with_dialog(
            self, self.fig2,
            initial_name=base,
            initial_dir=self._default_save_dir(),
            title=_("プロファイル画像を保存"),
        )

    def unit_selected(self) -> None:
        """
        Apply the selected length display unit to heatmap and profile axes.
        選択された長さ表示単位をヒートマップとプロファイル軸に反映する。
        """
        self.unit = self.unit_var.get()
        if self.flag1:
            # Unit switch updates axis ticks/labels only; cached image is reused.
            # 単位切替は軸目盛とラベルだけを更新する。キャッシュ済み画像をそのまま使う。
            self.image_showing(reload=False)
            self.line_redraw()
        if self.flag2:
            self.make_profile()

    def _get_extent_scale_and_unit(self) -> tuple:
        """
        Return display-side scale and unit label for axis ticks.
        軸目盛表示用のスケール値と単位ラベルを返す。
        """
        return extent_scale_and_unit(self.scale_um, self.unit_var.get())

    def _commit_vrange(self) -> bool:
        """
        Validate and commit heatmap vmin/vmax entries together.
        ヒートマップの vmin/vmax 入力欄をまとめて検証・確定する。
        """
        def _on_success():
            if self.flag1:
                # Only vmin/vmax change — reuse the cached image data.
                # vmin/vmax の変更だけなのでキャッシュ済み画像を再利用する。
                self.image_showing(reload=False)
                self.line_redraw()

        return self._commit_float_fields(
            [
                (self.ent_vmin, "vmin", "vmin"),
                (self.ent_vmax, "vmax", "vmax"),
            ],
            validator=lambda v: None if v["vmax"] >= v["vmin"]
            else _("左側に最小値を入力してください"),
            on_success=_on_success,
        )

    def _on_auto_vrange_toggle(self) -> None:
        """
        Recompute vmin/vmax when auto range is enabled.
        自動レンジが有効化されたときに vmin/vmax を再計算する。
        """
        if not self.auto_vrange_var.get():
            return
        # Nothing to recompute until an image has been loaded.
        if not self.flag1 or getattr(self, "img", None) is None:
            return
        self._apply_auto_vrange(self.img, log=False)
        # Redraw using cached image data with updated vmin/vmax.
        self.image_showing(reload=False)
        self.line_redraw()

    def input_lw(self) -> bool:
        """
        Validate and commit the profile sampling line width.
        プロファイル取得線幅を検証・確定する。

        Returns
        -------
        bool
            True if the line width was committed; False if validation failed.
            線幅を確定できた場合は True、不正値なら False。
        """
        def _on_success():
            if self.flag2:
                self.make_profile()

        return self._commit_float_fields(
            [(self.entrylw, "linewidth", "linewidth", int)],
            on_success=_on_success,
        )

    def rf_selected(self, event) -> None:
        """
        Update the profile aggregation function from the combobox selection.
        Combobox の選択からプロファイル集計関数を更新する。

        Parameters
        ----------
        event
            Tkinter combobox selection event. The value is read from `self.rfbox`.
            Tkinter の Combobox 選択イベント。値は `self.rfbox` から読み取る。
        """
        rf = self.rfbox.get()
        if rf == _("最大"):
            self.reduce_func = np.max
        elif rf == _("最小"):
            self.reduce_func = np.min
        elif rf == _("平均"):
            self.reduce_func = np.mean
        if self.flag2:
            self.make_profile()

    def load_array_file(self, path) -> np.ndarray | None:
        """
        Load a 2D AFM height array from bundle, NumPy, text, CSV, or .gwy input.
        バンドル、NumPy、テキスト、CSV、.gwy 入力から 2D AFM 高さ配列を読み込む。

        Parameters
        ----------
        path
            File path selected by the user.
            ユーザーが選択したファイルパス。

        Returns
        -------
        ndarray or None
            Loaded 2D height array, or None after showing an error dialog.
            読み込んだ 2D 高さ配列。失敗時はエラーダイアログ表示後に None。
        """
        data = None
        err_detail = ""

        try:
            if path.endswith(BUNDLE_EXT):
                # For GUI01 .b2z bundles, use the background-corrected calibrated image.
                # GUI01 の .b2z バンドルでは、BG 補正済みの calibrated 画像を使う。
                bundle = load_bundle(path, keys=["calibrated"])
                data = bundle["calibrated"]
            elif path.endswith(".npy"):
                # Try standard NumPy first, then Blosc2-compressed arrays.
                try:
                    data = np.load(path, allow_pickle=True)
                except Exception:
                    data = load_blosc2(path)
            elif path.lower().endswith(GWY_EXT):
                # Gwyddion native .gwy: load the channel chosen via the channel
                # dropdown (self._gwy_channel_id), defaulting to the
                # auto-selected topography channel when unset.
                # Gwyddion ネイティブ .gwy：チャンネルドロップダウンで選んだ
                # チャンネル（self._gwy_channel_id）を読み込む。未設定時は自動
                # 選択された地形チャンネルを既定とする。
                data = load_gwy_image(path, channel=self._gwy_channel_id).data
            else:
                # Text / CSV — delegate to the AFM text loader, which auto-detects
                # the header layout (Shimadzu multi-column, Bruker single-column),
                # column count, and file encoding.
                # テキスト / CSV は AFM テキストローダに委譲する。ヘッダ構成
                # （島津多列形式 / Bruker 1 列形式）・列数・エンコーディングを
                # 自動判定する。
                data = load_afm_text(path)
        except Exception as e:
            err_detail = str(e)

        if data is None:
            messagebox.showerror(
                _("エラー"),
                _("ファイルを読み込めませんでした。\n"
                  "サポートしていない形式か、ファイルが壊れている可能性があります。\n"
                  "詳細: {0}").format(err_detail or _("不明なエラー")),
            )
            return None

        # Pixel-to-physical conversion uses per-axis pixel counts, so both
        # non-square pixel arrays and rectangular scans are supported; only a
        # non-2D array is rejected.
        # 画素→物理変換は軸別の画素数を用いるため、非正方形の画素配列と矩形
        # スキャンの双方に対応する。拒否するのは 2 次元でない配列のみ。
        if data.ndim != 2:
            messagebox.showerror(
                _("エラー"),
                _("2 次元配列ではありません (shape={0})。").format(data.shape),
            )
            return None

        # Pixel-grid extents: image_h rows (Y), image_w columns (X).
        # 画素格子の大きさ：image_h 行（Y）、image_w 列（X）。
        self.image_h, self.image_w = data.shape[:2]
        return data

    def _apply_loaded_scan_size(self, path: str) -> bool:
        """
        Default the scale to a file's recorded or header scan size, if any.
        ファイルの記録走査範囲またはヘッダ走査範囲があればスケールを既定化する。

        For `.b2z` bundles the values come from the recorded
        ``spatial_calibration``; text/CSV inputs use instrument-header values,
        and native `.gwy` inputs use the default channel extents. Both axes are
        applied: a distinct Y size keeps a rectangular scan, an equal one
        leaves the Y entry empty (square scan). Inputs without a known scan
        size (e.g. `.npy`) keep the current scale.
        `.b2z` は記録された ``spatial_calibration``、テキスト/CSV は装置ヘッダ、
        ネイティブ `.gwy` は既定チャンネルの範囲から取得する。両軸を適用し、
        Y が異なれば矩形スキャン、等しければ Y 欄は空（正方スキャン）とする。
        走査範囲が不明な入力（`.npy` 等）は現在のスケールを保持する。

        Returns
        -------
        bool
            True when a scan size was found and applied to the scale entry.
            走査範囲が見つかりスケール入力欄へ適用された場合に True。
        """
        size_um = None
        size_y_um = None
        try:
            if path.endswith(BUNDLE_EXT):
                recorded = read_scan_size_from_bundle(path)
                if recorded is not None:
                    size_um, size_y_um = recorded
            elif not path.endswith(".npy"):
                header = read_scan_size(path)
                if header is not None:
                    size_um, size_y_um = header.x_um, header.y_um
        except Exception:
            # A metadata/header read failure must not block loading the image.
            # メタデータ/ヘッダ読み取り失敗で画像読み込みを妨げない。
            size_um = None
            size_y_um = None
        if size_um is None or size_um <= 0:
            return False
        self.scale_um = size_um
        # A distinct Y size keeps a rectangular scan; an equal one leaves the
        # Y entry empty (square scan).
        # Y が異なれば矩形スキャン、等しければ Y 欄は空（正方スキャン）とする。
        if size_y_um is not None and size_y_um > 0 and abs(size_y_um - size_um) > 1e-9:
            self.scale_y_um = size_y_um
        else:
            self.scale_y_um = None
        # Mirror the committed values into the entries and clear the unconfirmed
        # styling so the fields read as confirmed.
        # 確定値を入力欄へ反映し、未確定スタイルを解除して確定表示にする。
        self.entryas.delete(0, "end")
        self.entryas.insert(0, self._fmt_num(self.scale_um))
        self.entry_scale_y.delete(0, "end")
        if self.scale_y_um is not None:
            self.entry_scale_y.insert(0, self._fmt_num(self.scale_y_um))
        try:
            self._refresh_all_entry_states()
        except Exception:
            pass
        return True

    def _setup_gwy_channel_selector(self, path: str) -> None:
        """
        Prepare the channel dropdown for a newly selected input file.
        新しく選択された入力ファイル向けにチャンネルドロップダウンを準備する。

        Resets to auto-selection for every file. For a Gwyddion ``.gwy`` with
        more than one channel, the dropdown is populated and shown with the
        auto-selected topography channel preselected; for single-channel ``.gwy``
        and all other formats it is hidden, since there is nothing to choose.
        ファイルごとに自動選択へリセットする。チャンネルが複数ある Gwyddion
        ``.gwy`` ではドロップダウンを生成・表示し、自動選択された地形チャンネルを
        初期選択にする。単一チャンネルの ``.gwy`` やその他の形式では選ぶ対象が
        無いため非表示にする。
        """
        # New file: start from auto-selection (topography), regardless of format.
        # 新しいファイル：形式によらず自動選択（地形）から始める。
        self._gwy_channels = []
        self._gwy_channel_id = None

        if not path.lower().endswith(GWY_EXT):
            self.gwy_channel_label.grid_remove()
            self.gwy_channel_box.grid_remove()
            return

        try:
            channels = list_gwy_channels(path)
        except Exception:
            # A channel-listing failure must not block loading; load_array_file
            # surfaces the real error when it tries to read the image.
            # チャンネル列挙の失敗で読み込みを止めない。実際のエラーは
            # load_array_file が画像読込時に表示する。
            channels = []

        self._gwy_channels = channels
        if len(channels) <= 1:
            self.gwy_channel_label.grid_remove()
            self.gwy_channel_box.grid_remove()
            return

        default = select_default_channel(channels)
        self._gwy_channel_id = default.channel_id
        self.gwy_channel_box.configure(
            values=[c.display_label for c in channels]
        )
        self.gwy_channel_box.current(channels.index(default))
        self.gwy_channel_label.grid()
        self.gwy_channel_box.grid()

    def _on_gwy_channel_change(self) -> None:
        """
        Reload the image with the channel chosen in the dropdown.
        ドロップダウンで選んだチャンネルで画像を再読み込みする。
        """
        index = self.gwy_channel_box.current()
        if index < 0 or index >= len(self._gwy_channels):
            return
        self._gwy_channel_id = self._gwy_channels[index].channel_id
        # Reload from disk with the new channel; the scan size is shared across
        # channels, so the current scale stays valid.
        # 新しいチャンネルでディスクから再読み込みする。走査範囲はチャンネル間で
        # 共通のため、現在のスケールはそのまま有効。
        self.image_showing(reload=True)

    def load_image(self) -> None:
        """
        Open a file dialog and load the selected AFM data file.
        ファイル選択ダイアログを開き、選択された AFM データファイルを読み込む。
        """
        # Initial directory is intentionally omitted so Tk/OS can reuse the
        # process-local file-dialog location. This matches GUI01 / GUI03 / GUI04.
        # 初期ディレクトリは敢えて指定しない。``initialdir`` を渡さないと
        # Tk/OS がプロセス内で直前に開いたダイアログのディレクトリを記憶して
        # 再オープン時にそこを開く。GUI01 / GUI03 / GUI04 と同じ挙動。
        # File-type filter: keep "all files" as the last (most permissive) entry
        # so users can still open arbitrarily named exports. Specific entries
        # mirror the formats accepted by load_array_file.
        # 拡張子フィルタ: load_array_file が受け付ける形式を明示しつつ、最後に「すべて」を
        # 残して任意のエクスポートも開けるようにする。
        filetype = [
            (_("AFMデータ"), ("*" + BUNDLE_EXT, "*.npy", "*.csv", "*.txt", "*" + GWY_EXT)),
            (_("バンドル"),   "*" + BUNDLE_EXT),
            (_(".npy"),       "*.npy"),
            (_("テキスト/CSV"), ("*.csv", "*.txt")),
            (_("Gwyddion"),   "*" + GWY_EXT),
            (_("すべて"),     "*"),
        ]

        path = filedialog.askopenfilename(filetypes=filetype)
        if not path:
            return
        # Guard against rare cases where the dialog returns a non-existent path.
        # ダイアログが稀に存在しないパスを返すケースに備える。
        if not os.path.isfile(path):
            messagebox.showerror(
                _("エラー"),
                _("ファイルが見つかりません: {0}").format(path),
            )
            return
        self.path = path
        self.file_select(self.path)

    def image_showing(self, reload: bool = False) -> None:
        """
        Draw or update the heatmap canvas.
        ヒートマップキャンバスを描画または更新する。

        Parameters
        ----------
        reload
            If True, reload the image from disk; otherwise reuse cached image data.
            True の場合はディスクから再読込し、False の場合はキャッシュ画像を再利用する。

        Notes
        -----
        The first render creates the AxesImage and colorbar. Later updates reuse
        them and adjust properties such as extent, clim, labels, and font sizes.
        初回描画で AxesImage とカラーバーを作成し、以降は extent、clim、
        ラベル、フォントサイズなどの属性更新だけで再描画する。
        """
        self.filename = os.path.basename(self.path)

        if reload or getattr(self, "img", None) is None:
            # Load (or reload) the file from disk. load_array_file returns None and
            # shows an error dialog if anything fails.
            # ディスクから読み込み（または再読み込み）する。load_array_file は失敗時に
            # None を返し、エラーダイアログ自体は load_array_file 側で表示済み。
            img = self.load_array_file(self.path)
            if img is None:
                # Keep the existing display if loading fails.
                return
            self.img = img

            # Auto vmin/vmax is recomputed only after a successful file load.
            # 自動 vmin/vmax はファイル読込成功時だけ再計算する。
            if self.auto_vrange_var.get():
                self._apply_auto_vrange(self.img, log=False)
        # else: keep using the cached self.img — no disk I/O.
        # else 節: キャッシュ済み self.img をそのまま使う（ディスク I/O なし）。

        # Axis extent uses the display-side scale (µm or nm×1000) selected via
        # the unit radio; the stored value self.scale_um (µm) is unchanged.
        # 軸の extent は単位ラジオに応じた表示用スケール (µm or nm×1000) を使う。
        # 保持値 self.scale_um (µm) はラジオで変化しない。
        x_disp, y_disp, unit_label = self._get_extent_scale_xy_and_unit()
        extent = [0, x_disp, 0, y_disp]

        if not self.flag1 or getattr(self, "aximg", None) is None:
            # First render creates the image artist and colorbar.
            self.ax.cla()
            # afmhot is retained as the AFM-oriented heatmap colormap.
            # afmhot は AFM 画像向けのヒートマップとして維持する。
            self.aximg = self.ax.imshow(
                self.img, interpolation=None, cmap="afmhot",
                extent=extent, vmin=self.vmin, vmax=self.vmax,
            )
            self.ax.set_title(self.filename, fontsize=self.fs_title)

            # The intended length-valued .gwy channels and all other supported
            # height inputs are normalized to nm, so the colorbar label is
            # fixed. An explicitly selected non-length .gwy channel retains
            # native values and is outside this height-profile convention.
            # 通常対象とする長さ単位の .gwy チャンネルと他の高さ入力は nm へ正規化
            # するため、カラーバーラベルは固定する。長さ以外の .gwy チャンネルを
            # 明示選択した場合は元単位のままで、高さプロファイル規約の対象外となる。
            # unit_var controls only the horizontal scale (µm/nm).
            # unit_var は横方向スケール (µm/nm) だけを切り替える。
            divider = make_axes_locatable(self.ax)
            self.cax = divider.append_axes("right", size="5%", pad=0.1)
            self.cbar = self.fig.colorbar(
                self.aximg, cax=self.cax, label="Height (nm)",
            )
            self.cbar.ax.yaxis.label.set_fontsize(self.fs_cbar)
            self.cbar.ax.tick_params(labelsize=self.fs_cbar)

            self.ax.set_xlabel("({})".format(unit_label), fontsize=self.fs_label)
            self.ax.set_ylabel("({})".format(unit_label), fontsize=self.fs_label)
            self.ax.tick_params(labelsize=self.fs_tick)

            # Run tight_layout only once to establish initial label spacing.
            plt.tight_layout()
        else:
            # Later redraws reuse AxesImage and remove only point/line overlays.
            for line in list(self.ax.lines):
                line.remove()

            # Replace pixel data only on reload; display-only changes avoid set_data().
            # reload 時だけ画素データを入れ替え、表示設定変更では set_data() を避ける。
            if reload:
                self.aximg.set_data(self.img)
            self.aximg.set_extent(extent)
            self.aximg.set_clim(self.vmin, self.vmax)
            # Explicit limits keep future set_xlim/set_ylim changes from desynchronizing extent.
            self.ax.set_xlim(extent[0], extent[1])
            self.ax.set_ylim(extent[2], extent[3])

            # Update text and colorbar font sizes without recreating artists.
            self.ax.set_title(self.filename, fontsize=self.fs_title)
            self.ax.set_xlabel("({})".format(unit_label), fontsize=self.fs_label)
            self.ax.set_ylabel("({})".format(unit_label), fontsize=self.fs_label)
            self.ax.tick_params(labelsize=self.fs_tick)
            self.cbar.ax.yaxis.label.set_fontsize(self.fs_cbar)
            self.cbar.ax.tick_params(labelsize=self.fs_cbar)

        self.canvas.draw_idle()
        # Only mark "heatmap drawn" after a successful render. The early
        # return for img is None above prevents flag1 from being set on failure.
        # 描画に成功した場合のみ flag1 を立てる。読み込み失敗時は上の early return
        # により、flag1 は前回の状態のまま維持される。
        self.flag1 = True

    def file_select(self, path) -> None:
        """
        Handle a selected file path and refresh the heatmap workflow.
        選択されたファイルパスを処理し、ヒートマップ操作を更新する。

        Parameters
        ----------
        path
            File path selected by the user.
            ユーザーが選択したファイルパス。
        """
        # Clear any existing profile so it cannot be mixed with a newly loaded file.
        if self.flag2:
            self.hide_profile_canvas()
        # Start each file with a blank point list.
        self.xlist = []
        self.ylist = []

        # Replace the initial prompt with the selected file path.
        if self.label2 is not None:
            try:
                self.label2.destroy()
            except Exception:
                pass
            self.label2 = None
        if self.showfilename is not None:
            try:
                self.showfilename.destroy()
            except Exception:
                pass
        # file_row is local to __init__, so recover the row frame from grid_slaves.
        # file_row は __init__ のローカル変数なので、grid_slaves から行フレームを取得する。
        slaves = self.labelFrame.grid_slaves(row=0, column=0)
        if slaves:
            file_row_widget = slaves[0]
            self.showfilename = ttk.Label(
                file_row_widget,
                text=_("ファイルパス：{}").format(path),
            )
            self.showfilename.grid(row=0, column=1, sticky="w")

        # If the file can be loaded, show it and enable profile picking.
        if path and os.path.isfile(path):
            # Prepare the .gwy channel dropdown (shown only for multi-channel
            # .gwy) before loading, so the first draw uses the chosen channel.
            # .gwy のチャンネルドロップダウン（複数チャンネルの .gwy でのみ表示）を
            # 読み込み前に準備し、初回描画で選択チャンネルを使うようにする。
            self._setup_gwy_channel_selector(path)

            # Default the scale to this file's recorded/header scan size so
            # profile distances are reproducible; the user can still override.
            # Done before the first draw so the axis extent uses the new scale.
            # プロファイル距離を再現可能にするため、スケールをこのファイルの記録/
            # ヘッダ走査範囲で既定化する（ユーザーは上書き可能）。初回描画前に
            # 行い、軸 extent に新スケールを反映する。
            self._apply_loaded_scan_size(path)

            # New file selected — force a fresh load.
            # 新しいファイルが選ばれたので必ずディスクから読み込む。
            self.image_showing(reload=True)

            # Update the operation guide after a valid file is selected.
            self.guide_label.config(
                text=_("ヒートマップ上を右クリックで打点して下さい。各点を結ぶ線分の高さプロファイルが計算されます。"),
            )

            # Disconnect stale handlers so each click is processed exactly once.
            if self._click_cid is not None:
                try:
                    self.fig.canvas.mpl_disconnect(self._click_cid)
                except Exception:
                    pass
            self._click_cid = self.fig.canvas.mpl_connect(
                "button_press_event", self.click1)

    def click1(self, event) -> None:
        """
        Add a right-clicked point on the heatmap and update the profile.
        ヒートマップ上の右クリック点を追加し、プロファイルを更新する。

        Parameters
        ----------
        event
            Matplotlib mouse event whose `xdata` and `ydata` are display-unit coordinates.
            `xdata` と `ydata` が表示単位座標を表す Matplotlib マウスイベント。
        """
        # Ignore clicks outside the image axes.
        if event.xdata and event.ydata:
            # Use right-click so point picking does not conflict with pan/zoom interactions.
            if event.button == 3:
                # event.xdata / event.ydata are in the heatmap's display unit
                # (µm or nm) because they correspond to the imshow extent. We
                # store the points in µm internally so profile_between_points can apply the
                # fixed scale_um→pixel conversion regardless of the radio state.
                # event.xdata / event.ydata は imshow の extent に対応した
                # 「表示単位」座標 (µm or nm) として返ってくる。内部表現は µm 固定
                # にしておけば、ラジオ切替に関係なく profile_between_points が
                # scale_um→ピクセル変換をそのまま使える。
                x_disp, y_disp = (event.xdata, event.ydata)
                unit_now = self.unit_var.get()
                if unit_now == "nm":
                    x_val, y_val = (x_disp / 1000.0, y_disp / 1000.0)
                else:
                    x_val, y_val = (x_disp, y_disp)
                if self.xlist == []:
                    # First point: draw only a blue marker in display coordinates.
                    self.ax.plot(x_disp, y_disp, marker='.', color='b')
                    self.canvas.draw()
                else:
                    # Later points: connect to the previous point and mark the new endpoint.
                    # 2 点目以降は前点と破線で結び、新しい終点を赤で示す。
                    prev_disp_x = (
                        self.xlist[-1] * 1000.0 if unit_now == "nm" else self.xlist[-1]
                    )
                    prev_disp_y = (
                        self.ylist[-1] * 1000.0 if unit_now == "nm" else self.ylist[-1]
                    )
                    linelistx = [x_disp, prev_disp_x]
                    linelisty = [y_disp, prev_disp_y]
                    self.ax.plot(
                        linelistx, linelisty, "--", linewidth=2.0, color='b', alpha=0.5,
                    )
                    self.ax.plot(x_disp, y_disp, marker='.', color='r')
                    self.canvas.draw()
                # Store normalized micrometer coordinates.
                self.xlist.append(x_val)
                self.ylist.append(y_val)
                if len(self.xlist) > 1:
                    self.make_profile()

    def line_redraw(self) -> None:
        """
        Redraw stored points and connecting lines on the heatmap.
        ヒートマップ上に保持済み打点と接続線を再描画する。
        """
        if not self.flag1:
            return
        if self.xlist == []:
            return
        # Convert stored µm coordinates to the current display unit.
        # 保持している µm 座標を現在の表示単位に変換する。
        if self.unit_var.get() == "nm":
            xs = [v * 1000.0 for v in self.xlist]
            ys = [v * 1000.0 for v in self.ylist]
        else:
            xs = list(self.xlist)
            ys = list(self.ylist)

        if len(xs) == 1:
            self.ax.plot(xs[0], ys[0], marker='.', color='b')
            self.canvas.draw()
        elif len(xs) == 2:
            self.ax.plot(xs[0], ys[0], marker='.', color='b')
            self.ax.plot(
                [xs[0], xs[1]], [ys[0], ys[1]],
                "--", linewidth=2.0, color='b', alpha=0.5,
            )
            self.ax.plot(xs[1], ys[1], marker='.', color='r')
            self.canvas.draw()
        else:  # len(xs) > 2
            self.ax.plot(xs[0], ys[0], marker='.', color='b')
            for i in range(len(xs) - 1):
                self.ax.plot(
                    [xs[i], xs[i + 1]], [ys[i], ys[i + 1]],
                    "--", linewidth=2.0, color='b', alpha=0.5,
                )
                self.ax.plot(xs[i + 1], ys[i + 1], marker='.', color='r')
            self.canvas.draw()

    def cancel_plot(self) -> None:
        """
        Remove the most recently marked point.
        最後に追加した打点を 1 点だけ削除する。
        """
        if not hasattr(self, 'xlist') or self.xlist == []:
            messagebox.showerror(_("エラー"), _("打点されていません"))
        elif len(self.xlist) == 1:
            self.xlist = []
            self.ylist = []
            # Removing a point doesn't touch the image array — reuse cache.
            # 打点を消すだけなので画像配列は無関係。キャッシュ済みデータを使う。
            self.image_showing(reload=False)
        elif len(self.xlist) > 1:
            del self.xlist[-1]
            del self.ylist[-1]
            self.image_showing(reload=False)
            self.line_redraw()
            if self.flag2:
                if len(self.xlist) > 1:
                    self.make_profile()
                else:
                    self.hide_profile_canvas()

        if not self.flag1:
            messagebox.showerror(_("エラー"), _("画像を開いてください"))

    def clear_all_points(self) -> None:
        """
        Remove all marked points and any displayed profile.
        すべての打点と表示中のプロファイルを削除する。
        """
        if self.flag2:
            self.hide_profile_canvas()
        if self.flag1:
            if not hasattr(self, 'xlist') or self.xlist == []:
                messagebox.showerror(_("エラー"), _("打点されていません"))
            else:
                self.xlist = []
                self.ylist = []
                # Clearing all points doesn't touch the image array.
                # 全打点クリアでも画像配列は無関係。
                self.image_showing(reload=False)
        else:
            messagebox.showerror(_("エラー"), _("画像を開いてください"))

    def profile_between_points(self, x1, x2, y1, y2) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute a height profile between two points stored in micrometers.
        µm 単位で保持された 2 点間の高さプロファイルを計算する。

        Parameters
        ----------
        x1
            Start-point x-coordinate in micrometers.
            始点の x 座標 (µm)。
        x2
            End-point x-coordinate in micrometers.
            終点の x 座標 (µm)。
        y1
            Start-point y-coordinate in micrometers.
            始点の y 座標 (µm)。
        y2
            End-point y-coordinate in micrometers.
            終点の y 座標 (µm)。

        Returns
        -------
        tuple of ndarray
            Distance axis in micrometers and sampled height values in nanometers.
            µm 単位の距離軸と nm 単位のサンプリング済み高さ値。
        """

        # Convert micrometer coordinates to ndarray pixel coordinates per axis
        # (X from the width scale, Y from the height scale), so rectangular
        # scans map correctly. imshow uses a lower-left displayed origin while
        # ndarray indexing uses upper-left rows, so y is flipped.
        # µm 座標を軸別に画素座標へ変換する（X は幅スケール、Y は高さスケール）。
        # これで矩形スキャンも正しく対応づく。imshow は表示上は左下原点、ndarray は
        # 左上原点なので y 方向を反転する。
        x_um, y_um = self._scale_xy_um()
        # Columns map X via image_w, rows map Y via image_h, so non-square pixel
        # grids convert correctly.
        # 列は image_w で X、行は image_h で Y に対応づけ、非正方形の画素格子も
        # 正しく変換する。
        tx1 = x1 * self.image_w / x_um
        tx2 = x2 * self.image_w / x_um
        ty1 = self.image_h - y1 * self.image_h / y_um
        ty2 = self.image_h - y2 * self.image_h / y_um
        # profile_line expects coordinates as (row, col) = (y, x).
        start = np.array([ty1, tx1])
        end = np.array([ty2, tx2])
        profile = profile_line(
            self.img, start, end, mode='nearest',
            linewidth=self.linewidth, reduce_func=self.reduce_func,
        )
        # The points are already stored in micrometers per axis, so their plain
        # Euclidean separation is the true physical segment length.
        # 打点は軸別に µm で保持済みなので、そのユークリッド距離が物理的な
        # 区間長そのものになる。
        d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
        profilex = np.linspace(0, d, len(profile))
        return profilex, profile

    def make_profile(self) -> None:
        """
        Concatenate segment profiles and draw the profile graph.
        区間ごとのプロファイルを連結し、プロファイルグラフを描画する。
        """
        error = False

        # Draw the latest endpoint in the current display unit.
        if len(self.xlist) >= 2:
            if self.unit_var.get() == "nm":
                last_disp_x = self.xlist[-1] * 1000.0
                last_disp_y = self.ylist[-1] * 1000.0
            else:
                last_disp_x = self.xlist[-1]
                last_disp_y = self.ylist[-1]
            self.ax.plot(last_disp_x, last_disp_y, marker='.', color='r')
            self.canvas.draw()

        if len(self.xlist) == 2:
            # Two points produce one profile segment.
            x1 = self.xlist[0]
            x2 = self.xlist[1]
            y1 = self.ylist[0]
            y2 = self.ylist[1]
            self.profilex, self.profiley = self.profile_between_points(x1, x2, y1, y2)
            dotlist = None
        elif len(self.xlist) > 2:
            # Concatenate profiles across all adjacent point pairs.
            profilexlist = []
            profileylist = []
            dotlist = []
            for i in range(len(self.xlist) - 1):
                x1 = self.xlist[i]
                x2 = self.xlist[i + 1]
                y1 = self.ylist[i]
                y2 = self.ylist[i + 1]

                # Compute the i-th segment profile.
                addprofilex, addprofiley = self.profile_between_points(x1, x2, y1, y2)

                if i == 0:
                    # Keep the first segment unchanged.
                    profilexlist.extend(addprofilex)
                    profileylist.extend(addprofiley)
                    dotlist.append(addprofilex.shape[0])
                else:
                    # Skip the duplicated first point of later segments and offset distance.
                    # 後続区間は前区間の終点と始点が重複するため、2 点目以降だけ追加する。
                    addprofilex = addprofilex + profilexlist[-1]
                    profilexlist.extend(addprofilex[1:])
                    profileylist.extend(addprofiley[1:])
                    adddot = dotlist[-1] + addprofilex.shape[0] - 1
                    dotlist.append(adddot)

            self.profilex = np.array(profilexlist)
            self.profiley = np.array(profileylist)
        else:
            error = True
            messagebox.showerror(_("エラー"), _("線を引いてください"))
            dotlist = None

        if error:
            return

        # Create Figure/Canvas/buttons only once; later calls reuse them.
        if self.fig2 is None:
            self.fig2, self.ax2 = plt.subplots(1, 1, figsize=(5, 4.5))
            self.canvas2 = FigureCanvasTkAgg(self.fig2, self.profile_canvas_container)
            self.image_widget2 = self.canvas2.get_tk_widget()
            self.image_widget2.grid(row=0, column=0, sticky="nsew")
            # subplots_adjust is computed below from current font sizes.

            # Create CSV, image-save, and layout-editor buttons.
            self.buttonsavecsv = ttk.Button(
                self.profile_button_row, text=_("csvで保存"),
                command=self.save_csv)
            self.buttonsavecsv.pack(side="left", padx=(0, 8))

            # Place image-save between CSV export and layout adjustment.
            self.button_save_profile_img = ttk.Button(
                self.profile_button_row, text=_("画像を保存"),
                command=self.save_profile_image)
            self.button_save_profile_img.pack(side="left", padx=(0, 8))

            # Open the modal layout-adjustment window.
            self.open_button = ttk.Button(
                self.profile_button_row, text=_("レイアウト調整してグラフ作成"),
                command=self.modal.open)
            self.open_button.pack(side="left")
        else:
            # Later redraws reuse the same Figure and clear only the Axes contents.
            self.ax2.cla()

        # Hide placeholder without losing its grid placement.
        if self.profile_placeholder is not None:
            try:
                self.profile_placeholder.grid_remove()
            except tk.TclError:
                pass
        # Re-show the canvas if hide_profile_canvas previously hid it.
        try:
            self.image_widget2.grid()
        except tk.TclError:
            pass

        # Compute the display-side horizontal axis values. profilex is stored
        # in µm; in nm mode multiply by 1000 so the plotted x-axis matches the
        # unit shown by the radio. profiley (height in nm) is unaffected.
        # 表示用の横軸値を計算する。profilex は µm 単位で保管しており、nm 表示時のみ
        # 1000 倍して描画する。profiley (nm 単位の高さ) は変換不要。
        scale_disp, unit_label = self._get_extent_scale_and_unit()
        display_x = (
            self.profilex * 1000.0 if unit_label == "nm" else self.profilex
        )

        # Draw the full concatenated profile.
        self.ax2.plot(display_x, self.profiley, color='dimgrey', lw=2)

        if dotlist is not None and len(self.xlist) > 2:
            # Mark intermediate segment boundaries.
            for i in range(len(dotlist)):
                d = dotlist[i] - 1
                self.ax2.plot(
                    display_x[d], self.profiley[d], marker='.', color='r',
                )

        # Highlight start and end points.
        self.ax2.plot(
            display_x[0], self.profiley[0], marker='.', color='b',
        )
        self.ax2.plot(
            display_x[-1], self.profiley[-1], marker='.', color='r',
        )
        # Apply the shared label/tick font sizes used by the heatmap.
        self.ax2.set_xlabel("Length ({})".format(unit_label), fontsize=self.fs_label)
        self.ax2.set_ylabel("Height (nm)", fontsize=self.fs_label)
        self.ax2.tick_params(labelsize=self.fs_tick)

        # Adjust margins from font sizes, with caps to preserve plot area.
        left   = min(0.12 * (self.fs_label / 10) + 0.05 * (self.fs_tick / 10), 0.30)
        bottom = min(0.10 * (self.fs_label / 10) + 0.04 * (self.fs_tick / 10), 0.25)
        self.fig2.subplots_adjust(left=left, bottom=bottom, right=0.97, top=0.97)
        self.canvas2.draw()

        # Re-show buttons if hide_profile_canvas hid them.
        for btn in (self.buttonsavecsv, self.button_save_profile_img, self.open_button):
            if btn is not None and not btn.winfo_ismapped():
                btn.pack(side="left", padx=(0, 8))

        self.flag2 = True

    def hide_profile_canvas(self) -> None:
        """
        Hide the profile graph while keeping reusable Figure/Canvas objects.
        再利用可能な Figure/Canvas を保持したままプロファイルグラフを隠す。
        """
        if self.ax2 is not None:
            try:
                self.ax2.cla()
            except Exception:
                pass
            if self.canvas2 is not None:
                try:
                    self.canvas2.draw()
                except Exception:
                    pass
        # Hide canvas and buttons without destroying them.
        if self.image_widget2 is not None:
            try:
                self.image_widget2.grid_remove()
            except tk.TclError:
                pass
        for btn in (self.buttonsavecsv, self.button_save_profile_img, self.open_button):
            if btn is not None:
                try:
                    btn.pack_forget()
                except tk.TclError:
                    pass
        # Restore the placeholder.
        if self.profile_placeholder is not None:
            try:
                self.profile_placeholder.grid()
            except tk.TclError:
                pass
        self.flag2 = False

    def save_csv(self) -> None:
        """
        Export the current height profile to CSV.
        現在の高さプロファイルを CSV に出力する。
        """
        # Local import: pandas is used only for this CSV export and costs
        # about 1 s to import, so it is kept out of GUI startup.
        import pandas as pd

        filename = os.path.splitext(os.path.basename(self.path))[0]
        def _write_csv(path):
            # CSV is exported with the displayed unit so the file contents match
            # what the user sees on screen. Height stays in nm (AFM convention).
            # CSV の横軸は画面表示と同じ単位で出力する。高さは AFM の慣例どおり nm 固定。
            _scale_disp, unit_label = self._get_extent_scale_and_unit()
            x_out = (
                self.profilex * 1000.0 if unit_label == "nm" else self.profilex
            )
            df = pd.DataFrame({
                "Length ({})".format(unit_label): x_out,
                "Height (nm)":                    self.profiley,
            })
            # Write a header row so downstream tools can identify the displayed units.
            # 表示単位を下流ツールで判別できるよう、ヘッダー行を書き出す。
            df.to_csv(path, index=False, encoding="utf_8")

        save_csv_with_dialog(
            self,
            _write_csv,
            initial_dir=os.path.dirname(self.path),
            initial_name=str(filename) + "_profile.csv",
            title=_("保存先を選んで下さい"),
        )


def main() -> None:
    """
    Start the plot-profiler GUI.
    Plot Profiler GUI を起動する。
    """
    app = App()
    app.mainloop()


# Run the GUI only when this module is executed directly.
if __name__ == "__main__":
    main()
