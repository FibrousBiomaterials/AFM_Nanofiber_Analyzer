"""
GUI plugin showing analyzed ``.b2z`` bundles as a gallery of thumbnails.
解析済みの ``.b2z`` バンドルをサムネイルの一覧として表示する GUI プラグイン。

Input: ``.b2z`` bundles written by GUI01. They are added a folder at a time
(the bundles directly inside it), as individually chosen files, or by dropping
files and folders onto the gallery. Only the ``calibrated`` height image is
drawn; ``skeletonized`` and the recorded scan size are read to set the
automatic color range and the physical aspect ratio, and a bundle without them
is still shown.
入力は GUI01 が書き出した ``.b2z`` バンドル。フォルダ単位（その直下のバンドル）、
ファイルを選んでの追加、一覧へのファイル・フォルダのドロップで追加する。描くのは
高さ像 ``calibrated`` だけで、``skeletonized`` と記録された走査範囲は色範囲の
自動設定と物理アスペクト比のために読む。これらが無いバンドルも表示する。

Output: the gallery as A4 sheets, written through a file dialog as PNG (one
file per page) or PDF (all pages in one file). Nothing is written
automatically, and no bundle is modified. The window has no print command; a
sheet is printed from the application that opens the exported file.
出力は A4 に割り付けた一覧シートで、ファイルダイアログから PNG（1 ページ 1
ファイル）または PDF（全ページを 1 ファイル）で保存する。自動で書き出すものは無く、
バンドルは変更しない。印刷の機能は持たず、出力したファイルを開いたアプリから
印刷する。

The gallery is drawn as the pages of that sheet: the page orientation, the
images per row and the rows per page chosen for the sheet lay out the screen
too, both from `SheetLayout`, so what is seen is what is saved. Bundles appear
in the order they were added and are rearranged by dragging.
一覧は、そのシートのページとして描く。シート用に選んだ用紙の向き・1 行の画像数・
1 ページの行数が画面の配置も決め、どちらも `SheetLayout` から求めるため、見えて
いるものがそのまま保存される。バンドルは追加した順に並び、ドラッグで並べ替える。

Each thumbnail is drawn under its file name with the physical aspect ratio of
its scan. A scale bar and a color bar under it state its size and the height
range its colors span, because thumbnails colored per image cannot be compared
by color; both are shown unless turned off. The selected bundles can be opened
in GUI02 or GUI04, each in a window of its own, or all together in one GUI03
window as one group (`afm_nanofiber_analyzer.plugin_launch`).
各サムネイルは、ファイル名の下に、走査の物理アスペクト比で描く。その下の
スケールバーとカラーバーが、大きさと色が表す高さの範囲を示す。画像ごとに色を
決めたサムネイルは、色では互いに比べられないため。どちらも、外さない限り表示する。
選択したバンドルは GUI02 または GUI04 で開ける。バンドルごとに別のウィンドウで
開く。GUI03 では、選択した全バンドルを 1 つのグループとして 1 つのウィンドウで
開く（`afm_nanofiber_analyzer.plugin_launch`）。

Dropping files needs the ``tkinterdnd2`` package; without it the window still
opens and the two buttons remain.
ファイルのドロップには ``tkinterdnd2`` パッケージが要る。無くてもウィンドウは
開き、2 つのボタンでの追加は使える。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain string literals because literal_eval cannot parse gettext calls.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Thumbnail Viewer",
    "description": (
        "Image Preprocessor で解析した複数の .b2z バンドルを読み込み、"
        "バックグラウンド補正済みの高さ像をサムネイルの一覧として表示します。\n"
        "フォルダ単位での追加、ファイルを選んでの追加、一覧への"
        "ドラッグ＆ドロップでの追加ができます。\n"
        "一覧は保存するシートのページとして表示され、サムネイルをドラッグして"
        "並べ替えられます。色の範囲は画像ごとに調節でき、各画像にスケールバーと"
        "カラーバーを付けられます。\n"
        "一覧は A4 に割り付けたシートとして PNG または PDF で保存できます。"
        "印刷は保存したファイルを開いたアプリから行ってください。"
    )
}

# ===== Standard library =====
import math
import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np
from PIL import Image, ImageTk

# ===== GUI libraries =====
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
from matplotlib import colormaps
from matplotlib.colors import Normalize

# ===== Project libraries =====
from afm_nanofiber_analyzer.blosc2_io import BUNDLE_EXT, load_bundle_meta
from afm_nanofiber_analyzer.bundle_schema import pixel_size_nm, scan_size_um_from_meta
from afm_nanofiber_analyzer.plugin_launch import call_when_shown, launch_plugin, path_list_arguments
from afm_nanofiber_analyzer.translator import _
from afm_nanofiber_analyzer.ui_tools import (
    DEFAULT_VMAX, DEFAULT_VMIN, FIGURE_SAVE_DPI, UNIT_MICROMETER, LogMixin,
    ToolTip, UnconfirmedEntryMixin, apply_window_size, bind_mousewheel_scroll,
    compute_auto_vrange, create_scrolled_text, drain_ui_queue,
    localized_combobox_width, read_height_image, rewrite_entries,
    save_text_widget_log, setup_matplotlib_style, setup_ttk_theme,
)

# ===== Plugins the selected bundles can be opened in =====
# Import paths handed to `afm_nanofiber_analyzer.plugin_launch.launch_plugin`, and the number of
# selected bundles from which opening them in GUI02 or GUI04 asks first: there
# each opens a window of its own, in a process of its own. GUI03 takes every
# selected bundle into one window.
# `afm_nanofiber_analyzer.plugin_launch.launch_plugin` に渡す import パスと、GUI02・GUI04 で開く前に
# 確認する選択数。この 2 つでは、バンドル 1 つごとに独立したプロセスのウィンドウが
# 1 つ開く。GUI03 は選択した全バンドルを 1 つのウィンドウで受け取る。
PROFILER_MODULE = "guis.GUI02_PlotProfiler"
STATISTICS_MODULE = "guis.GUI03_Fiber_Morphology_Statistics"
TRACKER_MODULE = "guis.GUI04_Tracking_fiber"
OPEN_CONFIRM_COUNT = 4

# ===== Internal state keys =====
SORT_NAME = "name"
SORT_MTIME = "mtime"

ORIENT_PORTRAIT = "portrait"
ORIENT_LANDSCAPE = "landscape"

# How large a sheet page is drawn on the screen: fitted to the gallery, or at
# a percentage of its paper size.
# シートのページを画面にどの大きさで描くか。一覧の枠に合わせるか、用紙の実寸に
# 対する百分率で描く。
ZOOM_FIT_WIDTH = "fit_width"
ZOOM_WHOLE_PAGE = "whole_page"
ZOOM_PERCENT = "percent"

# Keys of the three sheet font sizes the user can set.
# ユーザーが設定できる、シートの 3 つのフォントサイズのキー。
FONT_NAME = "name"
FONT_SCALE_BAR = "scale_bar"
FONT_COLORBAR = "colorbar"

# ===== Display constants =====
# The colormap the other GUIs draw height images with.
# 他の GUI が高さ像の描画に使うカラーマップ。
COLORMAP_NAME = "afmhot"

# Longest side of the height image kept in memory per bundle. A full
# `calibrated` array is several megabytes, so only this reduced copy is held
# and the sheet export reads the bundles again at full resolution.
# バンドルごとにメモリへ残す高さ像の長辺。`calibrated` 配列は 1 枚で数 MB あるため
# この縮小版だけを保持し、シート出力ではバンドルを元の解像度で読み直す。
PREVIEW_MAX_PX = 400

# Starting size of the window, in pixels; it opens wider when the two rows of
# controls need more (`App._fit_window_width`). The status text at the end of
# the second row is given a fixed width, in characters, that holds its longest
# message.
# ウィンドウの初期の大きさ（ピクセル）。操作欄の 2 行がこれより広い幅を必要と
# する場合は、その幅で開く（`App._fit_window_width`）。2 行目の端の状態表示は、
# 最も長い表示が入る固定の幅（文字数）にする。
DEFAULT_WINDOW_W = 1160
DEFAULT_WINDOW_H = 820
MIN_WINDOW_H = 560
STATUS_WIDTH_CHARS = 32

# Screen geometry of the page preview, in pixels.
# ページのプレビューの画面上の寸法（ピクセル）。
PAGE_MARGIN_PX = 14
PAGE_GAP_PX = 16

# Zoom choices offered beside the two fitted views, in percent of the paper
# size, and the limits and step of zooming with Ctrl and the mouse wheel.
# 枠に合わせる 2 つの表示と並べて選べる倍率（用紙の実寸に対する %）と、Ctrl+
# マウスホイールでの倍率変更の限界と刻み。
ZOOM_PRESETS = (25, 50, 75, 100, 125, 150, 200, 300)
ZOOM_MIN_PERCENT = 10.0
ZOOM_MAX_PERCENT = 400.0
ZOOM_WHEEL_FACTOR = 1.1

DRAG_THRESHOLD_PX = 8
DRAG_SCROLL_EDGE_PX = 24
DRAG_SCROLL_STEP_PX = 18

PAGE_BG = "#ffffff"
PAGE_OUTLINE = "#8c8c8c"
GALLERY_BG = "#d6d6d6"
TILE_SELECTED_BG = "#cfe6ff"
TILE_SELECTED_OUTLINE = "#2f6fb5"
DROP_MARK_COLOR = "#2f6fb5"
ERROR_ROW_BG = "#f1dede"
ERROR_TEXT = "#8a1f1f"

# ===== Sheet constants =====
MM_PER_INCH = 25.4
A4_SHORT_MM = 210.0
A4_LONG_MM = 297.0
SHEET_MARGIN_MM = 10.0
SHEET_FOOTER_MM = 5.0
SHEET_CELL_PAD_MM = 1.5
SHEET_BARS_GAP_MM = 0.8
SHEET_NAME_GAP_MM = 0.6
SHEET_NAME_PT = 6.5
SHEET_INFO_PT = 6.0
SHEET_FOOTER_PT = 7.0
# Range and step of the font sizes the user can set, in points on the sheet.
# ユーザーが設定できるフォントサイズの範囲と刻み（シート上のポイント）。
FONT_PT_MIN = 3.0
FONT_PT_MAX = 20.0
FONT_PT_STEP = 0.5
DEFAULT_FONT_PT = {
    FONT_NAME: SHEET_NAME_PT,
    FONT_SCALE_BAR: SHEET_INFO_PT,
    FONT_COLORBAR: SHEET_INFO_PT,
}
SHEET_LINE_SPACING = 1.3
SHEET_MAX_COLS = 8
SHEET_MAX_ROWS = 10
DEFAULT_SHEET_COLS = 4
DEFAULT_SHEET_ROWS = 5

# Height of the line a scale bar or a color bar takes under an image, and the
# sizes of the bars themselves, in millimeters.
# 画像の下でスケールバーまたはカラーバーが占める 1 行の高さと、バー自体の寸法 (mm)。
SHEET_BAR_LINE_MM = 3.5
SCALE_BAR_THICKNESS_MM = 0.45
SCALE_BAR_LABEL_GAP_MM = 1.0
COLORBAR_HEIGHT_MM = 1.5
COLORBAR_MAX_WIDTH_MM = 30.0
COLORBAR_WIDTH_FRACTION = 0.45
COLORBAR_LABEL_GAP_MM = 0.8

# A scale bar is the longest round length not above this share of the image
# width, so its label fits beside it under the image.
# スケールバーは、画像の幅のこの割合を超えない最長のきりのよい長さにする。
# ラベルが画像の下でバーの横に収まるようにするため。
SCALE_BAR_MAX_FRACTION = 0.3

# Fonts tried, after the project's figure fonts, for file names with Japanese
# or Chinese characters; Arial and Helvetica have no glyphs for them.
# 日本語・中国語を含むファイル名のために、プロジェクトの図用フォントの後に試す
# フォント。Arial や Helvetica はこれらの文字のグリフを持たない。
CJK_FONT_CANDIDATES = (
    "Yu Gothic", "Meiryo", "MS Gothic", "Hiragino Sans", "Noto Sans CJK JP",
    "Noto Sans JP", "IPAexGothic", "Microsoft YaHei", "SimHei", "PingFang SC",
    "Noto Sans CJK SC",
)

SHEET_FILETYPES = [("PNG", "*.png"), ("PDF", "*.pdf")]

# Marks "no drop position yet" during a drag; `None` already means "at the end".
# ドラッグ中の「まだ落とす位置が無い」を表す。`None` は「末尾」の意味で使うため。
_NO_DROP_TARGET = object()


@dataclass
class ThumbItem:
    """
    One bundle of the gallery and what was read from it.
    一覧の 1 バンドルと、そこから読み取った内容。

    Attributes
    ----------
    path
        Bundle file path as it was given.
        与えられたままのバンドルファイルパス。
    key
        `bundle_key` of the path, which identifies the bundle in the gallery.
        パスの `bundle_key`。一覧の中でバンドルを識別する。
    name
        File name without its folder.
        フォルダを除いたファイル名。
    order
        Position in the order the bundles were added.
        バンドルを追加した順での位置。
    mtime
        Modification time of the file, in seconds since the epoch.
        ファイルの更新日時（エポックからの秒）。
    shape
        ``(rows, cols)`` of the stored ``calibrated`` array.
        保存された ``calibrated`` 配列の ``(行数, 列数)``。
    scan_size_um
        Recorded scan size ``(x, y)`` in micrometers, or ``None``.
        記録された走査範囲 ``(x, y)`` (µm)。無ければ ``None``。
    auto_vrange
        ``(vmin, vmax)`` in nanometers from `compute_auto_vrange`.
        `compute_auto_vrange` による ``(vmin, vmax)`` (nm)。
    manual_vrange
        ``(vmin, vmax)`` in nanometers the user entered for this image, or
        ``None`` while the automatic range is used.
        この画像にユーザーが入力した ``(vmin, vmax)`` (nm)。自動範囲を使う間は
        ``None``。
    preview
        Height image in nanometers reduced to at most `PREVIEW_MAX_PX` on its
        longer side.
        長辺を `PREVIEW_MAX_PX` 以下へ縮小した高さ像 (nm)。
    error
        Why the bundle could not be read; empty when it was.
        バンドルを読めなかった理由。読めた場合は空。
    """

    path: str
    key: str
    name: str
    order: int
    mtime: float = 0.0
    shape: Optional[Tuple[int, int]] = None
    scan_size_um: Optional[Tuple[float, float]] = None
    auto_vrange: Optional[Tuple[float, float]] = None
    manual_vrange: Optional[Tuple[float, float]] = None
    preview: Optional[np.ndarray] = None
    error: str = ""

    @property
    def readable(self) -> bool:
        """
        Whether the bundle was read and has an image to draw.
        バンドルを読めて、描く画像があるかどうか。
        """
        return not self.error and self.shape is not None


@dataclass(frozen=True)
class SheetEntry:
    """
    One image of an exported sheet, fixed when the export starts.
    出力するシートの 1 画像。出力の開始時点の内容で固定する。

    Attributes
    ----------
    path
        Bundle to read the full-resolution image from.
        元の解像度の画像を読むバンドル。
    name
        File name printed above the image.
        画像の上に印字するファイル名。
    aspect
        Physical height over width of the image.
        画像の物理的な高さ÷幅。
    vrange
        ``(vmin, vmax)`` in nanometers the colors span.
        色が表す ``(vmin, vmax)`` (nm)。
    scale_bar
        ``(fraction, label)`` of the scale bar: its length as a share of the
        image width and its text, or ``None`` without a recorded scan size.
        スケールバーの ``(fraction, label)``。長さを画像の幅に対する割合で表した
        値と、その文字列。走査範囲の記録が無ければ ``None``。
    """

    path: str
    name: str
    aspect: float
    vrange: Tuple[float, float]
    scale_bar: Optional[Tuple[float, str]] = None


@dataclass(frozen=True)
class CellParts:
    """
    Where the parts of one sheet cell lie on its page.
    シートの 1 セルの各部分が、ページ上のどこにあるか。

    Every length is in millimeters from the bottom left corner of the page.
    長さはすべて、ページ左下を原点とする mm。

    Attributes
    ----------
    image
        ``(left, bottom, width, height)`` of the image.
        画像の ``(左, 下, 幅, 高さ)``。
    center_x
        Horizontal center of the cell.
        セルの水平方向の中心。
    text_width
        Width available to the file name and to the color bar.
        ファイル名とカラーバーに使える幅。
    scale_bar_y, colorbar_y
        Vertical center of the scale bar line and of the color bar line, or
        ``None`` when the layout does not show that bar.
        スケールバーの行とカラーバーの行の垂直方向の中心。その配置でバーを表示
        しない場合は ``None``。
    name_top
        Top of the file name line, above the image.
        画像の上にあるファイル名の行の上端。
    """

    image: Tuple[float, float, float, float]
    center_x: float
    text_width: float
    scale_bar_y: Optional[float]
    colorbar_y: Optional[float]
    name_top: float


@dataclass(frozen=True)
class SheetLayout:
    """
    Grid of an A4 sheet page; the screen and the saved sheet both use it.
    A4 シート 1 ページの格子。画面と保存するシートの両方がこれを使う。

    Attributes
    ----------
    n_cols, n_rows
        Images per row and rows per page.
        1 行あたりの画像数と 1 ページあたりの行数。
    landscape
        Whether the page is wider than tall.
        ページが横長かどうか。
    show_scale_bar, show_colorbar
        Whether a scale bar and a color bar are drawn under each image. Both
        are, unless turned off: they are what states the size of an image and
        the heights its colors stand for.
        各画像の下にスケールバーとカラーバーを描くかどうか。外さない限り、
        どちらも描く。画像の大きさと、色が表す高さを示すのはこの 2 つである。
    name_pt, scale_bar_pt, colorbar_pt
        Font size, in points on the sheet, of the file name and of the labels
        of the scale bar and of the color bar.
        ファイル名、スケールバーのラベル、カラーバーのラベルのフォントサイズ
        （シート上のポイント）。
    """

    n_cols: int
    n_rows: int
    landscape: bool = False
    show_scale_bar: bool = True
    show_colorbar: bool = True
    name_pt: float = SHEET_NAME_PT
    scale_bar_pt: float = SHEET_INFO_PT
    colorbar_pt: float = SHEET_INFO_PT

    @property
    def page_mm(self) -> Tuple[float, float]:
        """
        Page ``(width, height)`` in millimeters.
        ページの ``(幅, 高さ)`` (mm)。
        """
        if self.landscape:
            return A4_LONG_MM, A4_SHORT_MM
        return A4_SHORT_MM, A4_LONG_MM

    @property
    def per_page(self) -> int:
        """
        Number of images one page holds.
        1 ページに入る画像数。
        """
        return self.n_cols * self.n_rows

    def cell_box_mm(self, index: int) -> Tuple[float, float, float, float]:
        """
        Return the cell of the ``index``-th image of a page.
        ページ内 ``index`` 番目の画像のセルを返す。

        Parameters
        ----------
        index
            Position on the page, row by row from the top left.
            ページ内の位置。左上から行ごとに数える。

        Returns
        -------
        tuple
            ``(left, bottom, width, height)`` in millimeters from the bottom
            left corner of the page.
            ページ左下を原点とする ``(左, 下, 幅, 高さ)`` (mm)。
        """
        page_w, page_h = self.page_mm
        cell_w = (page_w - 2 * SHEET_MARGIN_MM) / self.n_cols
        cell_h = (page_h - 2 * SHEET_MARGIN_MM - SHEET_FOOTER_MM) / self.n_rows
        row, col = divmod(index, self.n_cols)
        left = SHEET_MARGIN_MM + col * cell_w
        bottom = page_h - SHEET_MARGIN_MM - (row + 1) * cell_h
        return left, bottom, cell_w, cell_h

    def cell_parts(self, index: int, aspect: float) -> CellParts:
        """
        Place the image, the bars and the text lines of one cell.
        1 セルの画像・バー・文字の行を配置する。

        Parameters
        ----------
        index
            Position on the page, as in `cell_box_mm`.
            ページ内の位置。`cell_box_mm` と同じ。
        aspect
            Physical height over width of the image.
            画像の物理的な高さ÷幅。

        Returns
        -------
        CellParts
            From the top down: the file name, the image centered in the space
            left for it, the scale bar line and the color bar line. The lines
            of one row of cells stay level whatever the shapes of its images,
            and each line is as tall as its font needs.
            上から順に、ファイル名、残りの領域の中央に置いた画像、スケールバーの
            行、カラーバーの行。同じ行のセルの各行は、画像の形にかかわらず同じ
            高さに並び、各行の高さはそのフォントに合わせる。
        """
        left, bottom, cell_w, cell_h = self.cell_box_mm(index)
        pt_to_mm = MM_PER_INCH / 72.0

        def line_mm(size_pt: float) -> float:
            return size_pt * SHEET_LINE_SPACING * pt_to_mm

        name_line = line_mm(self.name_pt)
        scale_line = (max(SHEET_BAR_LINE_MM, line_mm(self.scale_bar_pt))
                      if self.show_scale_bar else 0.0)
        color_line = (max(SHEET_BAR_LINE_MM, line_mm(self.colorbar_pt))
                      if self.show_colorbar else 0.0)

        name_top = bottom + cell_h - SHEET_CELL_PAD_MM
        area_top = name_top - name_line - SHEET_NAME_GAP_MM
        area_bottom = (bottom + SHEET_CELL_PAD_MM + color_line + scale_line
                       + SHEET_BARS_GAP_MM)
        area_w = cell_w - 2 * SHEET_CELL_PAD_MM
        # A page of many rows, or large fonts, leave little for the image; it
        # keeps a sliver rather than a height of zero or less.
        # 行数の多いページや大きなフォントでは、画像に残る高さがわずかになる。
        # 0 以下にはせず、細い帯を残す。
        area_h = max(area_top - area_bottom, 1.0)
        box_w, box_h = fit_box(aspect, area_w, area_h)
        center_x = left + cell_w / 2
        image = (center_x - box_w / 2, area_bottom + (area_h - box_h) / 2,
                 box_w, box_h)

        line_top = area_bottom - SHEET_BARS_GAP_MM
        scale_bar_y = colorbar_y = None
        if self.show_scale_bar:
            scale_bar_y = line_top - scale_line / 2
            line_top -= scale_line
        if self.show_colorbar:
            colorbar_y = line_top - color_line / 2
        return CellParts(image=image, center_x=center_x, text_width=area_w,
                         scale_bar_y=scale_bar_y, colorbar_y=colorbar_y,
                         name_top=name_top)


def bundle_key(path: str) -> str:
    """
    Return the key that identifies one bundle file in the gallery.
    一覧の中で 1 つのバンドルファイルを識別するキーを返す。

    A dropped path arrives with forward slashes and a dialog path may differ in
    letter case, so paths are compared after normalization.
    ドロップされたパスはスラッシュ区切りで届き、ダイアログのパスは大文字小文字が
    異なりうるため、正規化してから比べる。
    """
    return os.path.normcase(os.path.abspath(path))


def list_folder_bundles(folder: str) -> List[str]:
    """
    List the bundles directly inside a folder, in natural name order.
    フォルダ直下のバンドルを、自然な名前順で列挙する。

    Parameters
    ----------
    folder
        Folder to list; subfolders are not searched, as in GUI01 and GUI03.
        列挙するフォルダ。GUI01・GUI03 と同じくサブフォルダは探さない。

    Returns
    -------
    list of str
        Paths of the ``.b2z`` files.
        ``.b2z`` ファイルのパス。

    Raises
    ------
    OSError
        If the folder cannot be listed.
    """
    names = [
        name for name in os.listdir(folder)
        if name.lower().endswith(BUNDLE_EXT)
        and os.path.isfile(os.path.join(folder, name))
    ]
    return [os.path.join(folder, name) for name in sorted(names, key=natural_key)]


def expand_inputs(paths: Iterable[str]) -> Tuple[List[str], List[str]]:
    """
    Turn chosen or dropped files and folders into bundle paths.
    選択またはドロップされたファイルとフォルダを、バンドルのパスへ展開する。

    Parameters
    ----------
    paths
        Files and folders in any mixture, as one drop delivers them.
        ファイルとフォルダの混在。1 回のドロップはこの形で届く。

    Returns
    -------
    tuple
        ``(bundles, ignored)``: the bundle files found, and the given paths
        that are neither a bundle nor a readable folder.
        ``(bundles, ignored)``。見つかったバンドルファイルと、バンドルでも読める
        フォルダでもなかったパス。
    """
    bundles: List[str] = []
    ignored: List[str] = []
    for path in paths:
        if os.path.isdir(path):
            try:
                bundles.extend(list_folder_bundles(path))
            except OSError:
                ignored.append(path)
        elif path.lower().endswith(BUNDLE_EXT) and os.path.isfile(path):
            bundles.append(path)
        else:
            ignored.append(path)
    return bundles, ignored


def natural_key(name: str) -> list:
    """
    Return a sort key that orders embedded numbers by value.
    名前に含まれる数字を数値として並べるソートキーを返す。

    ``scan2`` then sorts before ``scan10``, which a plain string order reverses.
    The ``.b2z`` extension is left out, so ``scan.b2z`` sorts before
    ``scan2.b2z``.
    これにより ``scan2`` が ``scan10`` より前に並ぶ（文字列順では逆になる）。
    拡張子 ``.b2z`` は除いて比べるため、``scan.b2z`` は ``scan2.b2z`` より前に並ぶ。
    """
    stem = name[:-len(BUNDLE_EXT)] if name.lower().endswith(BUNDLE_EXT) else name
    return [int(token) if token.isdigit() else token
            for token in re.split(r"(\d+)", stem.lower())]


def image_extent_um(scan_size_um: Optional[Tuple[float, float]],
                    shape: Tuple[int, int]) -> Optional[Tuple[float, float]]:
    """
    Return the physical ``(x, y)`` extent of a stored image, in micrometers.
    保存された画像が占める物理範囲 ``(x, y)`` を µm で返す。

    Parameters
    ----------
    scan_size_um
        Recorded scan size ``(x, y)``, or ``None``.
        記録された走査範囲 ``(x, y)``。無ければ ``None``。
    shape
        ``(rows, cols)`` of the stored array.
        保存配列の ``(行数, 列数)``。

    Returns
    -------
    tuple of float or None
        Extent of the stored array, or ``None`` without a scan size.
        保存配列の範囲。走査範囲が無ければ ``None``。

    Notes
    -----
    The recorded scan size spans one pixel more per axis than the stored
    array, so the pixel size comes from `afm_nanofiber_analyzer.bundle_schema.pixel_size_nm`, as
    in GUI02.
    記録された走査範囲は保存配列より各軸 1 画素分広いため、GUI02 と同じく画素
    サイズは `afm_nanofiber_analyzer.bundle_schema.pixel_size_nm` で求める。
    """
    if scan_size_um is None:
        return None
    rows, cols = shape
    return (pixel_size_nm(scan_size_um[0], cols) * cols / 1000.0,
            pixel_size_nm(scan_size_um[1], rows) * rows / 1000.0)


def height_over_width(scan_size_um: Optional[Tuple[float, float]],
                      shape: Tuple[int, int]) -> float:
    """
    Return the physical height over width a stored image is drawn with.
    保存された画像を描くときの物理的な高さ÷幅を返す。

    Without a recorded scan size the pixels are taken as square.
    走査範囲の記録が無い場合は、画素を正方形とみなす。
    """
    rows, cols = shape
    extent = image_extent_um(scan_size_um, shape)
    if extent is None or extent[0] <= 0:
        return rows / cols
    return extent[1] / extent[0]


def fit_box(aspect: float, box_w: float, box_h: float) -> Tuple[float, float]:
    """
    Return the largest ``(width, height)`` of an aspect that fits a box.
    箱に収まる最大の ``(幅, 高さ)`` を、指定のアスペクト比で返す。

    Parameters
    ----------
    aspect
        Height over width of the image.
        画像の高さ÷幅。
    box_w, box_h
        Size of the box.
        箱の寸法。
    """
    if aspect * box_w <= box_h:
        return box_w, aspect * box_w
    return box_h / aspect, box_h


def scale_bar_for(width_um: float) -> Tuple[float, str]:
    """
    Choose the scale bar of an image from its physical width.
    画像の物理的な幅から、スケールバーを決める。

    Parameters
    ----------
    width_um
        Physical width of the image in micrometers.
        画像の物理的な幅 (µm)。

    Returns
    -------
    tuple
        ``(length_um, label)``: the longest of 1, 2 or 5 times a power of ten
        that is at most `SCALE_BAR_MAX_FRACTION` of the width, and its text in
        nanometers below one micrometer and in micrometers from there.
        ``(length_um, label)``。10 の累乗の 1・2・5 倍のうち、幅の
        `SCALE_BAR_MAX_FRACTION` 以下で最長のものと、その文字列。1 µm 未満は nm、
        それ以上は µm で表す。
    """
    target = width_um * SCALE_BAR_MAX_FRACTION
    power = 10.0 ** math.floor(math.log10(target))
    length = power
    for mantissa in (5.0, 2.0):
        # The tolerance keeps a bar that is exactly the allowed share.
        if mantissa * power <= target * (1 + 1e-9):
            length = mantissa * power
            break
    if length < 1.0:
        return length, "{0:g} nm".format(round(length * 1000.0, 6))
    return length, "{0:g} {1}".format(length, UNIT_MICROMETER)


def colorbar_width_mm(text_width: float) -> float:
    """
    Return the length of a cell's color bar strip, in millimeters.
    セルのカラーバーの帯の長さを mm で返す。

    The strip leaves room for the two numbers at its ends inside the cell.
    帯の両端に置く 2 つの数値が、セルの中に収まるだけの余地を残す。
    """
    return min(COLORBAR_MAX_WIDTH_MM, COLORBAR_WIDTH_FRACTION * text_width)


def resample_area(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """
    Resize a height image by averaging the pixels each output pixel covers.
    出力の 1 画素が覆う画素を平均して、高さ像の大きさを変える。

    Parameters
    ----------
    image
        2D height image.
        2D の高さ像。
    width, height
        Output size in pixels.
        出力の大きさ（ピクセル）。

    Returns
    -------
    ndarray
        ``float32`` array of shape ``(height, width)``.
        形状 ``(height, width)`` の ``float32`` 配列。

    Notes
    -----
    A fiber is a few pixels wide. Keeping every n-th pixel would drop it
    wherever it falls between the kept pixels; averaging keeps it, at a lower
    height.
    ファイバーの幅は数画素しかない。n 画素ごとに間引くと、残す画素の間に落ちた
    部分でファイバーが消える。平均なら、高さは下がるがファイバーは残る。
    """
    source = Image.fromarray(np.ascontiguousarray(image, dtype=np.float32))
    resized = source.resize((max(1, int(width)), max(1, int(height))),
                            resample=Image.Resampling.BOX)
    return np.asarray(resized, dtype=np.float32)


def resize_preview(preview: np.ndarray, width: int, height: int) -> np.ndarray:
    """
    Resize a stored preview for the screen.
    保持しているプレビューを、画面用の大きさにする。

    A preview drawn smaller is averaged like any reduction; one drawn larger
    than it was stored is interpolated smoothly, because blocks of repeated
    pixels would look like structure of the sample. The saved sheet does not
    use this: it reads the bundle again.
    小さく描くときは、他の縮小と同じく平均する。保持している大きさより大きく描く
    ときは、なめらかに補間する。同じ画素を並べたブロックは試料の構造に見えて
    しまうため。保存するシートはこれを使わず、バンドルを読み直す。
    """
    rows, cols = preview.shape
    if width <= cols and height <= rows:
        return resample_area(preview, width, height)
    source = Image.fromarray(np.ascontiguousarray(preview, dtype=np.float32))
    resized = source.resize((max(1, int(width)), max(1, int(height))),
                            resample=Image.Resampling.BICUBIC)
    return np.asarray(resized, dtype=np.float32)


def heights_to_rgb(image: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """
    Color a height image with the gallery colormap.
    高さ像を一覧のカラーマップで着色する。

    Parameters
    ----------
    image
        2D height image in nanometers.
        2D の高さ像 (nm)。
    vmin, vmax
        Heights drawn with the first and the last color; values outside are
        clipped to them.
        最初の色と最後の色で描く高さ。範囲外の値はその色に切り詰める。

    Returns
    -------
    ndarray
        ``uint8`` array of shape ``(rows, cols, 3)``.
        形状 ``(行数, 列数, 3)`` の ``uint8`` 配列。
    """
    norm = Normalize(vmin=vmin, vmax=vmax, clip=True)
    return colormaps[COLORMAP_NAME](norm(image), bytes=True)[..., :3]


def colorbar_rgb(width: int, height: int) -> np.ndarray:
    """
    Return the colormap as a horizontal strip, first color at the left.
    カラーマップを、最初の色を左端にした横長の帯として返す。

    Returns
    -------
    ndarray
        ``uint8`` array of shape ``(height, width, 3)``.
        形状 ``(height, width, 3)`` の ``uint8`` 配列。
    """
    ramp = np.linspace(0.0, 1.0, max(2, int(width)))
    colors = colormaps[COLORMAP_NAME](ramp, bytes=True)[:, :3]
    return np.ascontiguousarray(
        np.broadcast_to(colors, (max(1, int(height)),) + colors.shape))


def elide_middle(text: str, fits: Callable[[str], bool]) -> str:
    """
    Shorten a text from its middle until it fits.
    収まるまで、文字列を中央から省略する。

    The end of a file name is kept because it tells analyses of one scan
    apart (``_r10-200``, ``_converted``).
    ファイル名の末尾は残す。同じ走査の解析を区別する部分（``_r10-200``、
    ``_converted``）が末尾にあるため。

    Parameters
    ----------
    text
        Text to shorten.
        短くする文字列。
    fits
        Tells whether a candidate text fits.
        候補の文字列が収まるかを返す関数。
    """
    if fits(text):
        return text

    def shortened(keep: int) -> str:
        head = (keep + 1) // 2
        tail = keep - head
        return text[:head] + "…" + (text[len(text) - tail:] if tail else "")

    low, high = 0, len(text) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if fits(shortened(middle)):
            low = middle
        else:
            high = middle - 1
    return shortened(low)


def elide_end(text: str, fits: Callable[[str], bool]) -> str:
    """
    Shorten a text from its end until it fits.
    収まるまで、文字列を末尾から省略する。
    """
    if fits(text):
        return text
    low, high = 0, len(text) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if fits(text[:middle] + "…"):
            low = middle
        else:
            high = middle - 1
    return text[:low] + "…"


def insertion_point(boxes: Sequence[Tuple[str, float, float, float, float]],
                    x: float, y: float,
                    ) -> Optional[Tuple[Optional[str], Tuple[float, float, float]]]:
    """
    Find where a dragged tile would be put for a pointer position.
    ポインタの位置に対して、ドラッグ中のタイルを入れる場所を求める。

    Parameters
    ----------
    boxes
        ``(key, x0, y0, x1, y1)`` of the tiles in display order.
        表示順に並べたタイルの ``(key, x0, y0, x1, y1)``。
    x, y
        Pointer position in the coordinates of the boxes.
        ボックスと同じ座標系でのポインタの位置。

    Returns
    -------
    tuple or None
        ``(before_key, (line_x, line_y0, line_y1))``: the tile the dragged
        one goes in front of (``None`` for the end) and the vertical line that
        marks the gap. ``None`` when there is no tile.
        ``(before_key, (line_x, line_y0, line_y1))``。ドラッグ中のタイルを
        その手前へ入れるタイル（末尾なら ``None``）と、すき間を示す縦線。
        タイルが無ければ ``None``。

    Notes
    -----
    The nearest tile is taken by row first, so a pointer in the margin beside
    a row still aims at that row. Its left half means "before it" and its
    right half "after it".
    最も近いタイルは、まず行で選ぶ。行の横の余白にあるポインタも、その行を
    指すようにするため。タイルの左半分は「その前」、右半分は「その後」を表す。
    """
    if not boxes:
        return None

    def distance(box) -> Tuple[float, float]:
        _key, x0, y0, x1, y1 = box
        dy = 0.0 if y0 <= y <= y1 else min(abs(y - y0), abs(y - y1))
        dx = 0.0 if x0 <= x <= x1 else min(abs(x - x0), abs(x - x1))
        return dy, dx

    index = min(range(len(boxes)), key=lambda i: distance(boxes[i]))
    _key, x0, y0, x1, y1 = boxes[index]
    if x < (x0 + x1) / 2:
        return boxes[index][0], (x0, y0, y1)
    before = boxes[index + 1][0] if index + 1 < len(boxes) else None
    return before, (x1, y0, y1)


def load_thumb_item(path: str, order: int) -> ThumbItem:
    """
    Read one bundle into a gallery item; a failure becomes an error item.
    1 つのバンドルを一覧の項目として読む。失敗はエラー項目になる。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルパス。
    order
        Position in the order the bundles were added.
        バンドルを追加した順での位置。

    Returns
    -------
    ThumbItem
        The item, with `ThumbItem.error` set when the bundle could not be
        read, so one unreadable file never stops a folder from loading.
        項目。バンドルを読めなかった場合は `ThumbItem.error` を設定する。読めない
        ファイルが 1 つあっても、フォルダの読み込みは止まらない。
    """
    item = ThumbItem(path=path, key=bundle_key(path),
                     name=os.path.basename(path), order=order)
    try:
        item.mtime = os.path.getmtime(path)
    except OSError:
        item.mtime = 0.0
    try:
        image, mask = read_height_image(path)
        try:
            meta = load_bundle_meta(path)
        except Exception:
            # The scan size is optional; the image is still shown without it.
            # 走査範囲は任意の情報で、無くても画像は表示する。
            meta = {}
        rows, cols = image.shape
        item.shape = (rows, cols)
        item.scan_size_um = scan_size_um_from_meta(meta)
        item.auto_vrange = tuple(float(v) for v in compute_auto_vrange(image, mask))
        scale = min(1.0, PREVIEW_MAX_PX / max(rows, cols))
        item.preview = resample_area(image, round(cols * scale), round(rows * scale))
    except Exception as exc:  # noqa: BLE001 - one bundle never aborts the batch
        item.error = f"{type(exc).__name__}: {exc}"
    return item


def sheet_font_families() -> List[str]:
    """
    Return the font families the sheet text is drawn with, in fallback order.
    シートの文字を描くフォントファミリーを、代替の順に返す。

    Returns
    -------
    list of str
        The project's figure fonts followed by the installed fonts of
        `CJK_FONT_CANDIDATES`, so a file name with Japanese or Chinese
        characters is not printed as empty boxes.
        プロジェクトの図用フォントに、`CJK_FONT_CANDIDATES` のうちインストール
        済みのものを続けた一覧。日本語・中国語を含むファイル名が空の四角に
        ならないようにする。
    """
    # Imported here: only the sheet export needs the font list.
    from matplotlib import font_manager

    # A family counts only when it has an upright face of normal weight. A
    # family registered with another weight alone (a variable font) would be
    # substituted with a warning for every text drawn.
    # 標準の太さの正体を持つファミリーだけを数える。別の太さでしか登録されて
    # いないファミリー（可変フォント）は、文字を描くたびに警告付きで代用される。
    installed = {
        font.name for font in font_manager.fontManager.ttflist
        if font.style == "normal" and font.weight in (400, "normal", "regular")
    }
    wanted = list(matplotlib.rcParams["font.sans-serif"]) + list(CJK_FONT_CANDIDATES)
    return [name for name in wanted if name in installed] or ["sans-serif"]


def render_sheet_page(entries: Sequence[SheetEntry], layout: SheetLayout,
                      page_no: int, n_pages: int,
                      read_image: Callable[[str], np.ndarray]):
    """
    Draw one A4 page of the thumbnail sheet.
    サムネイルシートの A4 1 ページを描く。

    Parameters
    ----------
    entries
        Images of this page, at most `SheetLayout.per_page`.
        このページの画像。最大 `SheetLayout.per_page` 件。
    layout
        Page grid.
        ページの格子。
    page_no, n_pages
        Page number, from 1, and the page count, printed at the bottom right.
        1 から数えたページ番号とページ数。右下に印字する。
    read_image
        Returns the full-resolution height image of a bundle path.
        バンドルのパスから元の解像度の高さ像を返す関数。

    Returns
    -------
    tuple
        ``(figure, failed)``: the Matplotlib figure at the true page size, and
        the names of the entries whose image could not be read.
        ``(figure, failed)``。実寸のページ大の Matplotlib の図と、画像を読め
        なかった項目の名前。
    """
    # Imported here so opening the window does not load the figure machinery.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import Rectangle

    page_w, page_h = layout.page_mm
    fig = Figure(figsize=(page_w / MM_PER_INCH, page_h / MM_PER_INCH),
                 dpi=FIGURE_SAVE_DPI)
    renderer = FigureCanvasAgg(fig).get_renderer()
    families = sheet_font_families()
    pt_to_mm = MM_PER_INCH / 72.0
    failed: List[str] = []

    def width_pt(text: str, size: float) -> float:
        """Measure a text as it will be drawn, in points."""
        width_px, _height, _descent = renderer.get_text_width_height_descent(
            text, FontProperties(family=families, size=size), ismath=False)
        return width_px * 72.0 / fig.dpi

    def put_text(x_mm: float, y_mm: float, text: str, size: float,
                 ha: str = "center", va: str = "top") -> None:
        fig.text(x_mm / page_w, y_mm / page_h, text, ha=ha, va=va,
                 fontsize=size, fontfamily=families)

    for index, entry in enumerate(entries):
        parts = layout.cell_parts(index, entry.aspect)
        left, bottom, box_w, box_h = parts.image
        text_w_pt = parts.text_width / pt_to_mm
        ax = fig.add_axes([left / page_w, bottom / page_h,
                           box_w / page_w, box_h / page_h])
        ax.set_axis_off()
        try:
            image = read_image(entry.path)
        except Exception:  # noqa: BLE001 - reported per image, the page goes on
            failed.append(entry.name)
            ax.text(0.5, 0.5, "unreadable", ha="center", va="center",
                    fontsize=layout.name_pt, transform=ax.transAxes)
        else:
            # Reduce to the pixels the box has at the output resolution, by
            # averaging, so a PDF does not carry every bundle at full size.
            # 出力解像度で箱が持つ画素数まで平均で縮小する。PDF に全バンドルを
            # 元の大きさで埋め込まないため。
            rows, cols = image.shape
            target_w = min(cols, max(1, round(box_w / MM_PER_INCH * FIGURE_SAVE_DPI)))
            target_h = min(rows, max(1, round(box_h / MM_PER_INCH * FIGURE_SAVE_DPI)))
            if (target_h, target_w) != (rows, cols):
                image = resample_area(image, target_w, target_h)
            ax.imshow(image, cmap=COLORMAP_NAME, vmin=entry.vrange[0],
                      vmax=entry.vrange[1], aspect="auto",
                      interpolation="nearest")

        if parts.scale_bar_y is not None and entry.scale_bar is not None:
            fraction, label = entry.scale_bar
            length = fraction * box_w
            fig.add_artist(Rectangle(
                (left / page_w,
                 (parts.scale_bar_y - SCALE_BAR_THICKNESS_MM / 2) / page_h),
                length / page_w, SCALE_BAR_THICKNESS_MM / page_h,
                transform=fig.transFigure, facecolor="black", linewidth=0))
            put_text(left + length + SCALE_BAR_LABEL_GAP_MM, parts.scale_bar_y,
                     label, layout.scale_bar_pt, ha="left", va="center_baseline")
        if parts.colorbar_y is not None:
            strip_w = colorbar_width_mm(parts.text_width)
            strip_left = parts.center_x - strip_w / 2
            bar_ax = fig.add_axes([
                strip_left / page_w,
                (parts.colorbar_y - COLORBAR_HEIGHT_MM / 2) / page_h,
                strip_w / page_w, COLORBAR_HEIGHT_MM / page_h])
            bar_ax.set_axis_off()
            bar_ax.imshow(np.linspace(0.0, 1.0, 256)[np.newaxis, :],
                          cmap=COLORMAP_NAME, vmin=0.0, vmax=1.0, aspect="auto",
                          interpolation="nearest")
            put_text(strip_left - COLORBAR_LABEL_GAP_MM, parts.colorbar_y,
                     "{0:g}".format(entry.vrange[0]), layout.colorbar_pt,
                     ha="right", va="center_baseline")
            put_text(strip_left + strip_w + COLORBAR_LABEL_GAP_MM, parts.colorbar_y,
                     "{0:g} nm".format(entry.vrange[1]), layout.colorbar_pt,
                     ha="left", va="center_baseline")

        name = elide_middle(
            entry.name, lambda s: width_pt(s, layout.name_pt) <= text_w_pt)
        put_text(parts.center_x, parts.name_top, name, layout.name_pt)

    put_text(page_w - SHEET_MARGIN_MM, SHEET_MARGIN_MM, f"{page_no} / {n_pages}",
             SHEET_FOOTER_PT, ha="right", va="bottom")
    return fig, failed


def sheet_page_paths(path: str, n_pages: int) -> List[str]:
    """
    Return the files a sheet export writes for a chosen path.
    選ばれたパスに対して、シート出力が書き出すファイルを返す。

    Parameters
    ----------
    path
        Path chosen in the save dialog, ending in ``.png`` or ``.pdf``.
        保存ダイアログで選ばれたパス。``.png`` または ``.pdf`` で終わる。
    n_pages
        Number of sheet pages.
        シートのページ数。

    Returns
    -------
    list of str
        The path itself for a PDF or a single page; for a PNG of several
        pages, one ``<name>_pNN.png`` per page, because a PNG holds one image.
        PDF または 1 ページの場合はそのパス。複数ページの PNG では、PNG が
        1 画像しか持てないため、ページごとの ``<名前>_pNN.png``。
    """
    stem, ext = os.path.splitext(path)
    if ext.lower() == ".pdf" or n_pages <= 1:
        return [path]
    return [f"{stem}_p{page:02d}{ext}" for page in range(1, n_pages + 1)]


def write_sheet(entries: Sequence[SheetEntry], layout: SheetLayout, path: str,
                read_image: Callable[[str], np.ndarray],
                progress: Optional[Callable[[int, int], None]] = None,
                ) -> Tuple[List[str], List[str]]:
    """
    Write the thumbnail sheet of some images as PNG pages or one PDF.
    画像のサムネイルシートを、PNG のページ群または 1 つの PDF として書き出す。

    Parameters
    ----------
    entries
        Images in sheet order.
        シートに並べる順の画像。
    layout
        Page grid.
        ページの格子。
    path
        Output path ending in ``.png`` or ``.pdf``; see `sheet_page_paths`.
        ``.png`` または ``.pdf`` で終わる出力パス。`sheet_page_paths` を参照。
    read_image
        Returns the full-resolution height image of a bundle path.
        バンドルのパスから元の解像度の高さ像を返す関数。
    progress
        Called with ``(page, n_pages)`` after each page is written.
        各ページを書き終えるたびに ``(page, n_pages)`` で呼ばれる。

    Returns
    -------
    tuple
        ``(written, failed)``: the files written, and the names of the images
        that could not be read.
        ``(written, failed)``。書き出したファイルと、読めなかった画像の名前。
    """
    pages = [entries[start:start + layout.per_page]
             for start in range(0, len(entries), layout.per_page)]
    n_pages = len(pages)
    targets = sheet_page_paths(path, n_pages)
    failed: List[str] = []

    def draw(page_index: int):
        fig, page_failed = render_sheet_page(
            pages[page_index], layout, page_index + 1, n_pages, read_image)
        failed.extend(page_failed)
        return fig

    if os.path.splitext(path)[1].lower() == ".pdf":
        # Imported here: only a PDF export needs the PDF backend.
        from matplotlib.backends.backend_pdf import PdfPages

        with PdfPages(path) as pdf:
            for page_index in range(n_pages):
                pdf.savefig(draw(page_index), dpi=FIGURE_SAVE_DPI)
                if progress is not None:
                    progress(page_index + 1, n_pages)
    else:
        for page_index, target in enumerate(targets):
            draw(page_index).savefig(target, dpi=FIGURE_SAVE_DPI, format="png")
            if progress is not None:
                progress(page_index + 1, n_pages)
    return targets, failed


def open_in_default_app(path: str) -> None:
    """
    Open a file with the application the system associates with it.
    システムが関連付けているアプリでファイルを開く。

    Parameters
    ----------
    path
        File to open. A failure is ignored: the file was already saved and
        its path is in the log.
        開くファイル。失敗は無視する。ファイルは保存済みで、パスはログにある。
    """
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


class App(tk.Tk, UnconfirmedEntryMixin, LogMixin):
    """
    Gallery window of analyzed bundles, drawn as the pages of its A4 sheet.
    解析済みバンドルの一覧ウィンドウ。A4 シートのページとして描く。

    Attributes
    ----------
    items
        Loaded bundles in display order, which is the order of the sheet.
        読み込んだバンドル。表示の順で、それがシートの順になる。
    selected
        `ThumbItem.key` of the selected tiles.
        選択中のタイルの `ThumbItem.key`。
    ui_queue
        Messages from the worker thread to the Tk main loop.
        ワーカースレッドから Tk メインループへのメッセージ。
    dnd_enabled
        Whether files can be dropped onto the gallery.
        一覧へファイルをドロップできるかどうか。
    """

    def __init__(self) -> None:
        """
        Build the gallery window and start its worker thread.
        一覧ウィンドウを作成し、ワーカースレッドを開始する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])
        setup_matplotlib_style(font_size=12)
        setup_ttk_theme(self)
        # The window is sized after the widgets are built, by
        # `_fit_window_width`: its width depends on the translated controls.
        # ウィンドウの大きさは、ウィジェットを作った後に `_fit_window_width` で
        # 決める。幅が、翻訳後の操作欄に依存するため。

        self.items: List[ThumbItem] = []
        self.selected: set = set()
        self.dnd_enabled = False
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._jobs: "queue.Queue[Optional[Tuple[str, Any]]]" = queue.Queue()
        # Bundles in the gallery or waiting to be read, by `bundle_key`.
        # 一覧にある、または読み込み待ちのバンドル（`bundle_key` で保持）。
        self._known_keys: set = set()
        # Raised when the gallery is emptied, so bundles still waiting to be
        # read for the earlier contents are dropped instead of reappearing.
        # 一覧を空にするたびに上げる。空にする前の内容として読み込み待ちだった
        # バンドルが、後から現れないようにするため。
        self._generation = 0
        self._next_order = 0
        self._outstanding = 0
        self._polling = False
        self._load_total = 0
        self._load_done = 0
        self._load_failed = 0
        self._exporting = False
        self._anchor_key: Optional[str] = None
        self._photos: Dict[str, Tuple[tuple, Any]] = {}
        self._gradients: Dict[Tuple[int, int], Any] = {}
        self._fonts: Dict[int, tkfont.Font] = {}
        # Tiles under the pointer are found in these, filled by `_relayout`:
        # every selectable box, and the page cells alone in display order.
        # ポインタの下のタイルはこれらから探す。`_relayout` が埋める。選択できる
        # すべてのボックスと、表示順に並べたページのセルだけの一覧。
        self._tile_boxes: List[Tuple[str, float, float, float, float]] = []
        self._page_boxes: List[Tuple[str, float, float, float, float]] = []
        self._relayout_pending = False
        # Ids of the scheduled redraw and poll, cancelled when the window closes.
        # 予約済みの再描画とポーリングの id。ウィンドウを閉じるときに取り消す。
        self._relayout_job: Optional[str] = None
        self._poll_job: Optional[str] = None
        self._last_dir: Optional[str] = None
        self._ui_font = tkfont.nametofont("TkDefaultFont")
        # A press that may become a drag: (key, x, y, select on release).
        # ドラッグになりうる押下: (key, x, y, 離したときに選択するか)。
        self._press: Optional[Tuple[str, int, int, bool]] = None
        self._dragging = False
        self._drop_before: Any = _NO_DROP_TARGET
        # The committed text of the vmin and vmax entries; blank where the
        # selected images differ, or with no image selected.
        # vmin・vmax の入力欄の確定済みの文字列。選択した画像で値が異なる側と、
        # 画像を選択していないときは空。
        self._edit_texts: Tuple[str, str] = ("", "")
        self._init_unconfirmed_registry()

        self._orient_keys = [ORIENT_PORTRAIT, ORIENT_LANDSCAPE]
        # The page is fitted to the gallery, or drawn at `_zoom_percent` of
        # its paper size; `_page_scale` is the result, in screen pixels per
        # millimeter of the page, as last drawn.
        # ページは一覧の枠に合わせるか、用紙の実寸の `_zoom_percent` % で描く。
        # `_page_scale` はその結果で、最後に描いたときのページ 1 mm あたりの
        # 画面のピクセル数。
        self._zoom_mode = ZOOM_FIT_WIDTH
        self._zoom_percent = 100.0
        self._page_scale = 1.0
        self._font_dialog: Optional["FontSizeDialog"] = None

        self._build_widgets()
        self._fit_window_width()
        self._enable_file_drop()
        self._sync_range_entries()
        self._update_controls()
        self._relayout()

        threading.Thread(target=self._worker_loop, daemon=True).start()
        if self.dnd_enabled:
            self._log(_("フォルダやファイルを追加するか、一覧の枠へドロップしてください。"))
        else:
            self._log(_("フォルダまたはファイルを追加してください。"))

    # ----- Widgets -----

    def _build_widgets(self) -> None:
        """
        Create the toolbar, the gallery, the sheet controls, and the log.
        ツールバー、一覧、シート出力の操作欄、ログ欄を作成する。
        """
        # Two rows, grouped by what the controls act on. Row 1: what is on the
        # sheet, the shape of its pages, the zoom of the screen, and saving.
        # Row 2: how each image is shown.
        # 操作の対象ごとにまとめた 2 行。1 行目はシートに載せるもの、ページの形、
        # 画面の倍率、保存。2 行目は各画像の見せ方。
        frm_top = ttk.Frame(self)
        frm_top.pack(fill=tk.X, padx=8, pady=(8, 2))
        ttk.Button(frm_top, text=_("フォルダを追加"),
                   command=self.on_add_folder).pack(side=tk.LEFT)
        ttk.Button(frm_top, text=_("ファイルを追加"),
                   command=self.on_add_files).pack(side=tk.LEFT, padx=(6, 0))
        self.btn_remove = ttk.Button(frm_top, text=_("削除"),
                                     command=self.on_remove_selected)
        self.btn_remove.pack(side=tk.LEFT, padx=(12, 0))
        ToolTip(self.btn_remove, _(
            "選択したサムネイルを一覧から削除します（ファイルはそのまま残ります）。\n"
            "クリックで 1 つ選択、Ctrl+クリックで追加、Shift+クリックで範囲を選択します。"
        ))
        self.btn_clear = ttk.Button(frm_top, text=_("全て削除"),
                                    command=self.on_clear)
        self.btn_clear.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_clear, _(
            "すべてのサムネイルを一覧から削除します（ファイルはそのまま残ります）。"))
        # A menu, not a list that keeps showing a choice: sorting is done
        # once, and the order stays free to change by dragging afterwards.
        # 選択を表示し続ける一覧ではなく、メニューにする。並べ替えは 1 回だけ
        # 行い、その後も順序はドラッグで自由に変えられるため。
        self.btn_sort = ttk.Menubutton(frm_top, text=_("並べ替え"))
        self.sort_menu = tk.Menu(self.btn_sort, tearoff=False)
        self.sort_menu.add_command(label=_("名前順"),
                                   command=lambda: self.on_sort(SORT_NAME))
        self.sort_menu.add_command(label=_("更新日時順"),
                                   command=lambda: self.on_sort(SORT_MTIME))
        self.btn_sort.configure(menu=self.sort_menu)
        self.btn_sort.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_sort, _(
            "サムネイルは追加した順に並びます。ドラッグすると並べ替えられます"
            "（複数選択していれば、まとめて動かせます）。\n"
            "このメニューは、現在の一覧をその順に 1 回並べ直します。"
        ))

        self._separator(frm_top)
        ttk.Label(frm_top, text=_("用紙")).pack(side=tk.LEFT)
        self.cmb_orient = self._combobox(frm_top, [_("A4 縦"), _("A4 横")],
                                         self._on_view_changed)
        self.cmb_orient.pack(side=tk.LEFT, padx=(4, 10))
        lbl_cols = ttk.Label(frm_top, text=_("列数"))
        lbl_cols.pack(side=tk.LEFT)
        ToolTip(lbl_cols, _("1 ページの 1 行に並べる画像の数です。"))
        self.cols_var = tk.StringVar(value=str(DEFAULT_SHEET_COLS))
        ttk.Spinbox(frm_top, from_=1, to=SHEET_MAX_COLS, width=3, state="readonly",
                    textvariable=self.cols_var).pack(side=tk.LEFT, padx=(4, 10))
        lbl_rows = ttk.Label(frm_top, text=_("行数"))
        lbl_rows.pack(side=tk.LEFT)
        ToolTip(lbl_rows, _("1 ページに並べる行の数です。"))
        self.rows_var = tk.StringVar(value=str(DEFAULT_SHEET_ROWS))
        ttk.Spinbox(frm_top, from_=1, to=SHEET_MAX_ROWS, width=3, state="readonly",
                    textvariable=self.rows_var).pack(side=tk.LEFT, padx=(4, 0))

        self._separator(frm_top)
        lbl_zoom = ttk.Label(frm_top, text=_("表示"))
        lbl_zoom.pack(side=tk.LEFT)
        ToolTip(lbl_zoom, _(
            "ページを画面に描く大きさです。100% は用紙の実寸です。\n"
            "一覧の上で Ctrl を押しながらマウスホイールを回しても、倍率を変えられます。"
        ))
        self._zoom_labels = (
            [_("幅に合わせる"), _("ページ全体")]
            + ["{0}%".format(percent) for percent in ZOOM_PRESETS])
        self.cmb_zoom = self._combobox(frm_top, self._zoom_labels,
                                       self._on_zoom_chosen)
        self.cmb_zoom.pack(side=tk.LEFT, padx=(4, 0))

        self.btn_export = ttk.Button(frm_top, text=_("シートを保存"),
                                     command=self.on_export)
        self.btn_export.pack(side=tk.RIGHT)
        ToolTip(self.btn_export, _(
            "画面に見えているとおりのページを、A4 のシートとして保存します。\n"
            "PDF は全ページを 1 つのファイルに、PNG は 1 ページを 1 つのファイルに"
            "保存します（複数ページでは名前の末尾に _p01、_p02 … が付きます）。"
        ))
        self.open_after_var = tk.BooleanVar(value=True)
        chk_open = ttk.Checkbutton(frm_top, text=_("保存後に開く"),
                                   variable=self.open_after_var)
        chk_open.pack(side=tk.RIGHT, padx=(16, 10))
        ToolTip(chk_open, _(
            "保存したシートを既定のアプリで開きます。印刷はそのアプリから行います。\n"
            "PNG で複数ページになった場合は 1 ページ目を開きます。"
        ))

        frm_view = ttk.Frame(self)
        frm_view.pack(fill=tk.X, padx=8, pady=2)
        # Kept to measure the width the two rows need (`_fit_window_width`).
        # 2 行に必要な幅を測るために保持する（`_fit_window_width`）。
        self._control_rows = (frm_top, frm_view)
        # The two names carry the explanation; the entries themselves show the
        # shared "press Enter to commit" tooltip.
        # 説明は 2 つの名前に付ける。入力欄自体には、共通の「Enter キーで確定」の
        # ツールチップが出る。
        range_help = _(
            "色の範囲は画像ごとに自動で決まります。サムネイルを選択して vmin / vmax を"
            "入力し、Enter で確定すると、選択した画像の範囲が変わります。"
            "Ctrl+A ですべて選択できます。\n"
            "複数選択で値が揃っていない側は空欄になります。空欄のまま確定した側は、"
            "各画像の値のまま変わりません。"
        )
        lbl_vmin = ttk.Label(frm_view, text="vmin")
        lbl_vmin.pack(side=tk.LEFT)
        ToolTip(lbl_vmin, range_help)
        self.ent_vmin = ttk.Entry(frm_view, width=6)
        self.ent_vmin.pack(side=tk.LEFT, padx=(4, 6))
        self._register_unconfirmed_entry(
            self.ent_vmin, lambda: self._edit_texts[0], self._commit_vrange)
        lbl_vmax = ttk.Label(frm_view, text="vmax")
        lbl_vmax.pack(side=tk.LEFT)
        ToolTip(lbl_vmax, range_help)
        self.ent_vmax = ttk.Entry(frm_view, width=6)
        self.ent_vmax.pack(side=tk.LEFT, padx=(4, 2))
        self._register_unconfirmed_entry(
            self.ent_vmax, lambda: self._edit_texts[1], self._commit_vrange)
        ttk.Label(frm_view, text="nm").pack(side=tk.LEFT, padx=(0, 6))
        btn_auto = ttk.Button(frm_view, text=_("自動"), command=self.on_auto_range)
        btn_auto.pack(side=tk.LEFT)
        ToolTip(btn_auto, _(
            "選択した画像の色範囲を、自動で決めた範囲に戻します。"))

        self._separator(frm_view)
        # Both bars start shown: nothing else on a tile states its size or the
        # heights its colors stand for.
        # 2 つのバーは、表示した状態で始める。タイルの上で、大きさと色が表す
        # 高さを示すものは、ほかに無い。
        self.scale_bar_var = tk.BooleanVar(value=True)
        chk_scale = ttk.Checkbutton(frm_view, text=_("スケールバー"),
                                    variable=self.scale_bar_var)
        chk_scale.pack(side=tk.LEFT)
        ToolTip(chk_scale, _(
            "各画像の下、画像の左端に合わせてスケールバーを表示します。"
            "走査範囲の記録が無いバンドルには表示しません。"))
        self.colorbar_var = tk.BooleanVar(value=True)
        chk_colorbar = ttk.Checkbutton(frm_view, text=_("カラーバー"),
                                       variable=self.colorbar_var)
        chk_colorbar.pack(side=tk.LEFT, padx=(8, 0))
        ToolTip(chk_colorbar, _(
            "各画像の下に、その画像の色と高さの対応を示すカラーバーを表示します。"))
        self.font_vars: Dict[str, tk.StringVar] = {
            key: tk.StringVar(value="{0:.1f}".format(size))
            for key, size in DEFAULT_FONT_PT.items()
        }
        btn_fonts = ttk.Button(frm_view, text=_("フォントサイズ…"),
                               command=self.on_open_font_sizes)
        btn_fonts.pack(side=tk.LEFT, padx=(12, 0))
        ToolTip(btn_fonts, _(
            "ファイル名・スケールバー・カラーバーの文字の大きさを設定します。"
            "画面と保存するシートの両方に反映されます。"))

        self._separator(frm_view)
        btn_gui02 = ttk.Button(
            frm_view, text=_("GUI02で開く"),
            command=lambda: self.on_open_selected_in(PROFILER_MODULE, "GUI02"))
        btn_gui02.pack(side=tk.LEFT)
        ToolTip(btn_gui02, _(
            "選択した画像を Plot Profiler で開きます。1 つにつきウィンドウが 1 つ開きます。"))
        btn_gui03 = ttk.Button(
            frm_view, text=_("GUI03で開く"),
            command=self.on_open_selected_in_statistics)
        btn_gui03.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(btn_gui03, _(
            "選択した画像を Fiber Morphology Statistics で開きます。選択した全画像が "
            "1 つのグループに入った状態で、ウィンドウが 1 つ開きます。"))
        btn_gui04 = ttk.Button(
            frm_view, text=_("GUI04で開く"),
            command=lambda: self.on_open_selected_in(TRACKER_MODULE, "GUI04"))
        btn_gui04.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(btn_gui04, _(
            "選択した画像を Fiber Tracker で開きます。1 つにつきウィンドウが 1 つ開きます。"))
        # A trace follows every change of these settings, the spinbox arrows
        # and the mouse wheel alike, so the page preview never lags behind.
        # トレースはこれらの設定のどの変更にも追従する（スピンボックスの矢印でも
        # ホイールでも）。ページのプレビューが設定に遅れないようにするため。
        for variable in (self.cols_var, self.rows_var, self.scale_bar_var,
                         self.colorbar_var, *self.font_vars.values()):
            variable.trace_add("write", lambda *_a: self._schedule_relayout())

        # A fixed width, so the longest status text is already counted in the
        # width the row asks for and never pushes the controls about.
        # 幅を固定する。最も長い状態表示を行の必要幅に最初から含め、表示の
        # 変化で操作欄が動かないようにするため。
        self.status_var = tk.StringVar(value="")
        ttk.Label(frm_view, textvariable=self.status_var, anchor=tk.E,
                  width=STATUS_WIDTH_CHARS).pack(side=tk.RIGHT, padx=(16, 0))

        self.frm_gallery = ttk.Frame(self)
        self.frm_gallery.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.frm_gallery.rowconfigure(0, weight=1)
        self.frm_gallery.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.frm_gallery, bg=GALLERY_BG, takefocus=1,
                                highlightthickness=1,
                                highlightbackground=PAGE_OUTLINE)
        scroll_y = ttk.Scrollbar(self.frm_gallery, orient=tk.VERTICAL,
                                 command=self.canvas.yview)
        # A page zoomed wider than the gallery is reached with this one.
        # 一覧の枠より広く拡大したページは、こちらで見渡す。
        self._scroll_x = ttk.Scrollbar(self.frm_gallery, orient=tk.HORIZONTAL,
                                       command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=scroll_y.set,
                              xscrollcommand=self._scroll_x.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        self._scroll_x.grid(row=1, column=0, sticky="ew")
        self._scroll_x.grid_remove()
        self.canvas.bind("<Configure>", lambda _e: self._schedule_relayout())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Delete>", lambda _e: self.on_remove_selected())
        self.canvas.bind("<Control-a>", self._on_select_all)
        # X11 reports the wheel as buttons 4 and 5; the others as MouseWheel.
        # X11 はホイールをボタン 4・5 として、他は MouseWheel として届ける。
        for sequence in ("<Control-MouseWheel>", "<Control-Button-4>",
                         "<Control-Button-5>"):
            self.canvas.bind(sequence, self._on_zoom_wheel)
        for sequence in ("<Shift-MouseWheel>", "<Shift-Button-4>",
                         "<Shift-Button-5>"):
            self.canvas.bind(sequence, self._on_shift_wheel)
        bind_mousewheel_scroll(self.canvas, scope=self.frm_gallery)

        frm_log = ttk.LabelFrame(self, text=_("ログ"))
        frm_log.pack(fill=tk.BOTH, padx=8, pady=(2, 8))
        frm_log_buttons = ttk.Frame(frm_log)
        frm_log_buttons.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(frm_log_buttons, text=_("ログを保存"),
                   command=self.on_save_log).pack(side=tk.LEFT)
        log_body = ttk.Frame(frm_log)
        log_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.log_text, _log_sb = create_scrolled_text(
            log_body, height=4, wrap=tk.WORD, state="disabled",
        )

    @staticmethod
    def _separator(parent: tk.Misc) -> None:
        """
        Put a vertical line between two groups of controls in a row.
        行の中の 2 つの操作のまとまりの間に、縦線を置く。
        """
        ttk.Separator(parent, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=10, pady=2)

    def _fit_window_width(self) -> None:
        """
        Size the window so that both rows of controls are shown whole.
        操作欄の 2 行が切れずに表示されるよう、ウィンドウの大きさを決める。

        The rows are wider in some languages than in others, so the width is
        measured from the built rows instead of being a fixed number; it is
        both the least width the window takes and, when larger than the
        default, its starting width.
        行の幅は言語によって違うため、固定の数値ではなく、作成した行から幅を
        測る。その幅をウィンドウの最小幅とし、既定より大きい場合は初期の幅にも
        する。
        """
        self.update_idletasks()
        needed = max(row.winfo_reqwidth() for row in self._control_rows) + 2 * 8
        apply_window_size(self, max(DEFAULT_WINDOW_W, needed), DEFAULT_WINDOW_H,
                          min_w=needed, min_h=MIN_WINDOW_H)

    def _combobox(self, parent: tk.Misc, labels: List[str],
                  on_change: Optional[Callable[[], None]]) -> ttk.Combobox:
        """
        Create a read-only combobox whose choice is read by its index.
        選択を位置（インデックス）で読む、読み取り専用のコンボボックスを作る。

        The labels are translated, so the code never compares them; the
        selected index is mapped to a fixed key.
        ラベルは翻訳されるため、コードでは比べない。選択の位置を固定のキーへ
        対応付ける。
        """
        box = ttk.Combobox(parent, values=labels, state="readonly",
                           width=localized_combobox_width(labels, max_width=30))
        box.current(0)
        if on_change is not None:
            box.bind("<<ComboboxSelected>>", lambda _e: on_change())
        return box

    def _enable_file_drop(self) -> None:
        """
        Register the gallery as a drop target for files and folders.
        一覧を、ファイルとフォルダのドロップ先として登録する。

        Dropping is a convenience beside the two buttons, so any failure of
        the optional package only disables it.
        ドロップは 2 つのボタンに加えた補助の手段なので、任意パッケージ側で
        何が失敗しても、ドロップを無効にするだけに留める。
        """
        try:
            # Imported here so the window opens without the package.
            from tkinterdnd2 import DND_FILES, TkinterDnD

            TkinterDnD.require(self)
            # The canvas alone is registered: it has no child widgets, and the
            # tiles are canvas items, so every drop inside it arrives here.
            # 登録するのは canvas だけ。子ウィジェットは無く、タイルは canvas の
            # 項目なので、枠内へのドロップはすべてここへ届く。
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<Drop>>", self._on_drop)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            self.dnd_enabled = False
            self._log(_(
                "ドラッグ＆ドロップは使えません（{reason}）。"
                "「フォルダを追加」「ファイルを追加」は使えます。"
            ).format(reason=f"{type(exc).__name__}: {exc}"))
        else:
            self.dnd_enabled = True

    # ----- Current settings -----

    def _vrange_for(self, item: ThumbItem) -> Tuple[float, float]:
        """
        Return the color range an item is drawn with.
        項目を描く色範囲を返す。

        The range entered for the image, or its automatic range when none was
        entered.
        その画像に入力された範囲を使い、入力が無ければ自動範囲を使う。
        """
        if item.manual_vrange is not None:
            return item.manual_vrange
        if item.auto_vrange is not None:
            return item.auto_vrange
        return float(DEFAULT_VMIN), float(DEFAULT_VMAX)

    def selected_images(self) -> List[ThumbItem]:
        """
        Return the selected images that were read, in display order.
        選択中の画像のうち読めたものを、表示の順で返す。

        These are what the vmin/vmax entries, "Auto" and the three "open in"
        buttons act on.
        vmin/vmax の入力欄、「自動」、3 つの「…で開く」ボタンは、これらを対象に
        する。
        """
        return [item for item in self.items
                if item.readable and item.key in self.selected]

    def _scale_bar_of(self, item: ThumbItem) -> Optional[Tuple[float, str]]:
        """
        Return an item's scale bar as ``(share of the image width, label)``.
        項目のスケールバーを ``(画像の幅に対する割合, ラベル)`` で返す。

        ``None`` for a bundle that records no scan size: its pixels have no
        known length.
        走査範囲の記録が無いバンドルでは ``None``。画素の長さが分からないため。
        """
        extent = image_extent_um(item.scan_size_um, item.shape)
        if extent is None or extent[0] <= 0:
            return None
        length, label = scale_bar_for(extent[0])
        return length / extent[0], label

    def readable_items(self) -> List[ThumbItem]:
        """
        Return the items that have an image, in display and sheet order.
        画像を持つ項目を、表示とシートの順で返す。
        """
        return [item for item in self.items if item.readable]

    def _sheet_layout(self) -> SheetLayout:
        """
        Return the page grid chosen in the sheet controls.
        シートの操作欄で選ばれているページの格子を返す。
        """
        def count(variable: tk.StringVar, default: int, limit: int) -> int:
            try:
                return min(limit, max(1, int(variable.get())))
            except (ValueError, tk.TclError):
                return default

        def points(key: str) -> float:
            try:
                size = float(self.font_vars[key].get())
            except (ValueError, tk.TclError):
                return DEFAULT_FONT_PT[key]
            return min(FONT_PT_MAX, max(FONT_PT_MIN, size))

        return SheetLayout(
            n_cols=count(self.cols_var, DEFAULT_SHEET_COLS, SHEET_MAX_COLS),
            n_rows=count(self.rows_var, DEFAULT_SHEET_ROWS, SHEET_MAX_ROWS),
            landscape=self._orient_keys[self.cmb_orient.current()] == ORIENT_LANDSCAPE,
            show_scale_bar=bool(self.scale_bar_var.get()),
            show_colorbar=bool(self.colorbar_var.get()),
            name_pt=points(FONT_NAME),
            scale_bar_pt=points(FONT_SCALE_BAR),
            colorbar_pt=points(FONT_COLORBAR),
        )

    def _paper_scale(self) -> float:
        """
        Return the screen pixels per millimeter that show a page at 100 %.
        ページを 100 % で表示するときの、1 mm あたりの画面のピクセル数を返す。

        This is the paper's real size on a screen of the pixel density Tk
        reports.
        Tk が報告する画素密度の画面での、用紙の実寸に当たる。
        """
        return float(self.winfo_fpixels("1i")) / MM_PER_INCH

    # ----- Adding and removing -----

    def on_add_folder(self) -> None:
        """
        Ask for a folder and add the bundles directly inside it.
        フォルダを選ばせ、その直下のバンドルを追加する。
        """
        folder = filedialog.askdirectory(
            parent=self, title=_(".b2z バンドルを含むフォルダを選択"),
            initialdir=self._last_dir)
        if folder:
            self._last_dir = folder
            self.add_paths([folder])

    def on_add_files(self) -> None:
        """
        Ask for bundle files and add them.
        バンドルファイルを選ばせ、追加する。
        """
        paths = filedialog.askopenfilenames(
            parent=self, title=_(".b2z バンドルを選択"),
            initialdir=self._last_dir,
            filetypes=[("b2z bundle", "*" + BUNDLE_EXT), ("All files", "*.*")])
        if paths:
            self._last_dir = os.path.dirname(paths[0])
            self.add_paths(list(paths))

    def _on_drop(self, event) -> str:
        """
        Add the files and folders dropped onto the gallery.
        一覧へドロップされたファイルとフォルダを追加する。
        """
        # tkdnd delivers the paths as one Tcl list, with braces around a path
        # that contains spaces; splitlist undoes that quoting.
        # tkdnd はパスを 1 つの Tcl リストで渡し、空白を含むパスは波括弧で囲む。
        # splitlist がその括りを外す。
        self.add_paths(list(self.tk.splitlist(event.data)))
        return event.action

    def add_paths(self, paths: Sequence[str]) -> None:
        """
        Queue the bundles among some files and folders for loading.
        ファイルとフォルダの中のバンドルを、読み込み待ちに加える。

        Parameters
        ----------
        paths
            Files and folders in any mixture. A folder contributes the
            bundles directly inside it; a bundle already in the gallery is
            skipped. New bundles go to the end of the gallery, in the order
            given.
            ファイルとフォルダの混在。フォルダはその直下のバンドルを加える。
            既に一覧にあるバンドルは飛ばす。新しいバンドルは、与えられた順に
            一覧の末尾へ入る。
        """
        bundles, ignored = expand_inputs(paths)
        new_paths = []
        duplicates = 0
        for path in bundles:
            key = bundle_key(path)
            if key in self._known_keys:
                duplicates += 1
                continue
            self._known_keys.add(key)
            new_paths.append(path)

        self._log(_(
            "追加: {n_new} 件（既に一覧にあるため省略 {n_dup} 件、"
            ".b2z 以外のため無視 {n_ignored} 件）"
        ).format(n_new=len(new_paths), n_dup=duplicates, n_ignored=len(ignored)))
        for path in new_paths:
            self._load_total += 1
            self._submit(("load", (self._generation, self._next_order, path)))
            self._next_order += 1
        self._update_controls()

    def on_remove_selected(self) -> None:
        """
        Take the selected tiles out of the gallery; no file is deleted.
        選択中のタイルを一覧から外す。ファイルは削除しない。
        """
        if not self.selected:
            return
        removed = len(self.selected)
        self.items = [item for item in self.items if item.key not in self.selected]
        for key in self.selected:
            self._known_keys.discard(key)
            self._photos.pop(key, None)
        self._log(_("一覧から {n} 件を外しました。").format(n=removed))
        self._set_selection(set(), anchor=None)

    def on_clear(self) -> None:
        """
        Empty the gallery, including bundles still waiting to be read.
        読み込み待ちのバンドルも含めて、一覧を空にする。
        """
        self._generation += 1
        self.items = []
        self._known_keys = set()
        self._photos = {}
        self._load_total = self._load_done = self._load_failed = 0
        self._log(_("一覧を空にしました。"))
        self._set_selection(set(), anchor=None)

    def on_sort(self, mode: str) -> None:
        """
        Put the gallery into name or date order once.
        一覧を、名前順または更新日時順に 1 回並べ直す。

        Parameters
        ----------
        mode
            `SORT_NAME` (natural order of the file names) or `SORT_MTIME`
            (oldest file first). The order stays free afterwards: later
            bundles go to the end, and tiles can still be dragged.
            `SORT_NAME`（ファイル名の自然な順）または `SORT_MTIME`（古い
            ファイルが先）。その後も順序は固定されない。後から追加したバンドルは
            末尾へ入り、タイルは引き続きドラッグできる。
        """
        if mode == SORT_MTIME:
            self.items.sort(key=lambda it: (it.mtime, natural_key(it.name)))
            self._log(_("更新日時の古い順に並べ替えました。"))
        else:
            self.items.sort(key=lambda it: (natural_key(it.name), it.key))
            self._log(_("名前順に並べ替えました。"))
        self._relayout()

    def move_items(self, keys: Sequence[str], before_key: Optional[str]) -> None:
        """
        Move tiles in front of another tile, keeping their own order.
        タイルを、互いの順序を保ったまま、別のタイルの手前へ動かす。

        Parameters
        ----------
        keys
            `ThumbItem.key` of the tiles to move.
            動かすタイルの `ThumbItem.key`。
        before_key
            Key of the tile they go in front of, or ``None`` for the end.
            その手前へ入れるタイルのキー。末尾なら ``None``。
        """
        moving_keys = set(keys)
        if before_key in moving_keys:
            # The target is itself moving: aim at the next tile that stays.
            # 目標自体が動く側にある。動かない次のタイルを目標にする。
            order = [item.key for item in self.items]
            following = order[order.index(before_key) + 1:]
            before_key = next((k for k in following if k not in moving_keys), None)
        moving = [item for item in self.items if item.key in moving_keys]
        rest = [item for item in self.items if item.key not in moving_keys]
        index = next((i for i, item in enumerate(rest) if item.key == before_key),
                     len(rest))
        self.items = rest[:index] + moving + rest[index:]
        self._relayout()

    # ----- Worker thread -----

    def _submit(self, job: Tuple[str, Any]) -> None:
        """
        Hand a job to the worker thread and keep the UI queue polled.
        ジョブをワーカースレッドへ渡し、UI キューのポーリングを続ける。
        """
        self._outstanding += 1
        self._jobs.put(job)
        if not self._polling:
            self._polling = True
            self._poll_job = self.after(50, self._poll_ui_queue)

    def _worker_loop(self) -> None:
        """
        Run the queued jobs one at a time until the window is destroyed.
        ウィンドウが破棄されるまで、待ちジョブを 1 つずつ実行する。

        Runs in the worker thread; it never touches Tk widgets. Loading and
        exporting share this one thread, so a sheet is never written while
        bundles are still being read.
        ワーカースレッドで動き、Tk のウィジェットには触れない。読み込みと出力は
        この 1 本のスレッドを共有するため、バンドルの読み込み中にシートが
        書き出されることはない。
        """
        while True:
            job = self._jobs.get()
            if job is None:
                return
            kind, payload = job
            try:
                if kind == "load":
                    generation, order, path = payload
                    # Skip a bundle queued before the gallery was emptied.
                    # 一覧を空にする前に待ちへ入ったバンドルは読まない。
                    if generation == self._generation:
                        self.ui_queue.put(
                            ("item", (generation, load_thumb_item(path, order))))
                elif kind == "export":
                    self._export_job(*payload)
            except Exception as exc:  # noqa: BLE001 - reported, the thread lives on
                self.ui_queue.put(("failure", f"{type(exc).__name__}: {exc}"))
            finally:
                self.ui_queue.put(("job_done", kind))

    def _export_job(self, entries: List[SheetEntry], layout: SheetLayout,
                    path: str) -> None:
        """
        Write the sheet and report the result through the UI queue.
        シートを書き出し、結果を UI キューで通知する。
        """
        def read_image(bundle_path: str) -> np.ndarray:
            return read_height_image(bundle_path)[0]

        def progress(page: int, n_pages: int) -> None:
            self.ui_queue.put(("export_page", (page, n_pages)))

        try:
            written, failed = write_sheet(entries, layout, path, read_image,
                                          progress)
        except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
            self.ui_queue.put(("export_failed", f"{type(exc).__name__}: {exc}"))
        else:
            self.ui_queue.put(("export_done", (written, failed)))

    def _poll_ui_queue(self) -> None:
        """
        Apply queued worker results and keep polling while jobs remain.
        キューのワーカー結果を反映し、ジョブが残る間はポーリングを続ける。
        """
        def on_item(payload) -> None:
            generation, item = payload
            if generation != self._generation:
                return
            self._load_done += 1
            # Results arrive in the order the bundles were queued, so appending
            # puts each new bundle at the end of the gallery.
            # 結果はバンドルを待ちに入れた順に届くので、末尾へ足せば、新しい
            # バンドルは一覧の最後に入る。
            self.items.append(item)
            if item.error:
                self._load_failed += 1
                self._log(_("{name}: 読み込めませんでした ({reason})").format(
                    name=item.name, reason=item.error))
            self._schedule_relayout()

        def on_export_page(payload) -> None:
            page, n_pages = payload
            self.status_var.set(_("シートを保存中… {page} / {n_pages} ページ").format(
                page=page, n_pages=n_pages))

        def on_export_done(payload) -> None:
            written, failed = payload
            self._exporting = False
            for target in written:
                self._log(_("保存: {path}").format(path=target))
            if failed:
                self._log(_(
                    "{n} 件の画像は読み直せなかったため、シートでは空欄です: {names}"
                ).format(n=len(failed), names=", ".join(failed)))
            if self.open_after_var.get() and written:
                open_in_default_app(written[0])

        def on_export_failed(reason) -> None:
            self._exporting = False
            self._log(_("シートを保存できませんでした: {reason}").format(reason=reason))
            messagebox.showerror(
                _("保存エラー"), _("保存に失敗しました:\n{e}").format(e=reason),
                parent=self)

        def on_failure(reason) -> None:
            self._log(_("処理中にエラーが発生しました: {reason}").format(reason=reason))

        def on_job_done(_kind) -> None:
            self._outstanding -= 1

        drain_ui_queue(self.ui_queue, {
            "item": on_item,
            "export_page": on_export_page,
            "export_done": on_export_done,
            "export_failed": on_export_failed,
            "failure": on_failure,
            "job_done": on_job_done,
        })

        if self._outstanding > 0:
            self._update_controls()
            self._poll_job = self.after(50, self._poll_ui_queue)
            return
        self._polling = False
        self._poll_job = None
        if self._load_total:
            self._log(_("読み込み完了: {n_ok} 件（読み込めなかったもの {n_failed} 件）").format(
                n_ok=self._load_done - self._load_failed, n_failed=self._load_failed))
        self._load_total = self._load_done = self._load_failed = 0
        self._update_controls()

    def destroy(self) -> None:
        """
        Stop the worker thread and destroy the window.
        ワーカースレッドを止めて、ウィンドウを破棄する。
        """
        jobs = getattr(self, "_jobs", None)
        if jobs is not None:
            jobs.put(None)
        # A redraw or a poll still scheduled would run against the destroyed
        # window and report an unknown command.
        # 予約されたままの再描画やポーリングは、破棄されたウィンドウに対して
        # 実行され、不明なコマンドとして報告されてしまう。
        for name in ("_relayout_job", "_poll_job"):
            job = getattr(self, name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()

    # ----- Gallery drawing -----

    def _update_controls(self) -> None:
        """
        Set the buttons and the status text from the current state.
        現在の状態に合わせて、ボタンの有効・無効と状態表示を設定する。
        """
        busy = self._outstanding > 0
        readable = self.readable_items()
        has_images = bool(readable)
        self.btn_export.configure(
            state="normal" if has_images and not busy else "disabled")
        self.btn_remove.configure(state="normal" if self.selected else "disabled")
        self.btn_clear.configure(
            state="normal" if self.items or busy else "disabled")
        self.btn_sort.configure(
            state="normal" if len(readable) > 1 else "disabled")
        if self._exporting:
            return
        if self._load_total and busy:
            self.status_var.set(_("読み込み中… {done} / {total}").format(
                done=self._load_done, total=self._load_total))
        else:
            self.status_var.set(_("{n} 件（選択 {n_selected} 件）").format(
                n=len(self.items), n_selected=len(self.selected)))

    def _schedule_relayout(self) -> None:
        """
        Redraw the gallery once the event loop is idle.
        イベントループが空いたときに、一覧を 1 回だけ描き直す。

        Many bundles arrive in one poll, and a resize sends a burst of
        events; redrawing once per burst keeps the window responsive.
        1 回のポーリングで多数のバンドルが届き、リサイズではイベントが続けて
        届く。まとめて 1 回だけ描き直して、ウィンドウの応答を保つ。
        """
        if self._relayout_pending:
            return
        self._relayout_pending = True
        self._relayout_job = self.after_idle(self._relayout)

    def _font_for(self, size_pt: float, scale: float) -> tkfont.Font:
        """
        Return the screen font of a sheet text size at a page scale.
        シートの文字の大きさに対応する、ページ倍率での画面用フォントを返す。

        Parameters
        ----------
        size_pt
            Font size on the sheet, in points.
            シート上のフォントサイズ（ポイント）。
        scale
            Screen pixels per millimeter of the page.
            ページ 1 mm あたりの画面のピクセル数。
        """
        pixels = max(1, round(size_pt * MM_PER_INCH / 72.0 * scale))
        font = self._fonts.get(pixels)
        if font is None:
            # A negative Tk font size is a height in pixels.
            # Tk のフォントサイズは、負の値で高さをピクセル数で表す。
            font = tkfont.Font(root=self, family=self._ui_font.actual("family"),
                               size=-pixels)
            self._fonts[pixels] = font
        return font

    def _photo_for(self, item: ThumbItem, width: int, height: int):
        """
        Return the Tk image of an item at a size and its current color range.
        指定の大きさと現在の色範囲での、項目の Tk 画像を返す。
        """
        vrange = self._vrange_for(item)
        params = (width, height, vrange)
        cached = self._photos.get(item.key)
        if cached is not None and cached[0] == params:
            return cached[1]
        heights = resize_preview(item.preview, width, height)
        # `master` ties the image to this window's interpreter; the default
        # root may be another, already destroyed, window.
        # `master` で画像をこのウィンドウのインタプリタに結び付ける。既定の
        # ルートは、既に破棄された別のウィンドウでありうる。
        photo = ImageTk.PhotoImage(
            Image.fromarray(heights_to_rgb(heights, *vrange)), master=self)
        self._photos[item.key] = (params, photo)
        return photo

    def _gradient_photo(self, width: int, height: int):
        """
        Return the color bar strip as a Tk image, shared by tiles of one size.
        カラーバーの帯を Tk 画像で返す。同じ大きさのタイルで共有する。
        """
        photo = self._gradients.get((width, height))
        if photo is None:
            photo = ImageTk.PhotoImage(
                Image.fromarray(colorbar_rgb(width, height)), master=self)
            self._gradients[(width, height)] = photo
        return photo

    def _relayout(self) -> None:
        """
        Draw the gallery as the pages of the sheet, for the current settings.
        現在の設定で、一覧をシートのページとして描く。
        """
        self._relayout_pending = False
        self._relayout_job = None
        canvas = self.canvas
        canvas.delete("all")
        self._tile_boxes = []
        self._page_boxes = []
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        if not self.items:
            hint = (_("ここに .b2z ファイルまたはフォルダをドロップしてください。")
                    if self.dnd_enabled
                    else _("「フォルダを追加」または「ファイルを追加」で読み込んでください。"))
            canvas.create_text(width // 2, 60, text=hint, fill="#444444",
                               font=self._ui_font, width=max(width - 40, 100))
            canvas.configure(scrollregion=(0, 0, width, 1))
            self._update_controls()
            return

        layout = self._sheet_layout()
        page_w, page_h = layout.page_mm
        label_h = self._ui_font.metrics("linespace") + 4
        paper_scale = self._paper_scale()
        if self._zoom_mode == ZOOM_PERCENT:
            scale = paper_scale * self._zoom_percent / 100.0
        else:
            scale = (width - 2 * PAGE_MARGIN_PX) / page_w
            if self._zoom_mode == ZOOM_WHOLE_PAGE:
                scale = min(scale, (height - 2 * PAGE_MARGIN_PX - label_h) / page_h)
        scale = min(max(scale, paper_scale * ZOOM_MIN_PERCENT / 100.0),
                    paper_scale * ZOOM_MAX_PERCENT / 100.0)
        self._page_scale = scale
        page_px_w, page_px_h = page_w * scale, page_h * scale
        page_x = max(PAGE_MARGIN_PX, (width - page_px_w) / 2)
        # A page wider than the gallery extends the scrolled area sideways, and
        # only then is the horizontal scrollbar shown.
        # 一覧の枠より広いページは、スクロールする領域を横へ広げる。横の
        # スクロールバーは、そのときだけ表示する。
        total_w = max(width, page_px_w + 2 * PAGE_MARGIN_PX)
        if total_w > width:
            self._scroll_x.grid()
        else:
            self._scroll_x.grid_remove()

        readable = self.readable_items()
        pages = [readable[start:start + layout.per_page]
                 for start in range(0, len(readable), layout.per_page)]
        footer_font = self._font_for(SHEET_FOOTER_PT, scale)
        y = float(PAGE_MARGIN_PX)
        for page_index, page_items in enumerate(pages):
            canvas.create_text(
                page_x, y, anchor="nw", font=self._ui_font, fill="#333333",
                text=_("ページ {page} / {n_pages}").format(
                    page=page_index + 1, n_pages=len(pages)))
            y += label_h
            canvas.create_rectangle(page_x, y, page_x + page_px_w, y + page_px_h,
                                    fill=PAGE_BG, outline=PAGE_OUTLINE)
            for index, item in enumerate(page_items):
                self._draw_cell(item, layout, index, scale, page_x, y)
            canvas.create_text(page_x + (page_w - SHEET_MARGIN_MM) * scale,
                               y + (page_h - SHEET_MARGIN_MM) * scale,
                               anchor="se", font=footer_font,
                               text=f"{page_index + 1} / {len(pages)}")
            y += page_px_h + PAGE_GAP_PX

        y = self._draw_unreadable(y, width)
        canvas.configure(scrollregion=(0, 0, total_w, y))
        self._update_controls()

    def _draw_cell(self, item: ThumbItem, layout: SheetLayout, index: int,
                   scale: float, page_x: float, page_y: float) -> None:
        """
        Draw one image of a page with its name and its bars.
        ページの 1 画像を、名前とバーとともに描く。

        The positions come from `SheetLayout.cell_parts`, the same ones the
        saved sheet is drawn from, scaled to the screen.
        位置は `SheetLayout.cell_parts` から得る。保存するシートを描くのと同じ
        位置を、画面の倍率に合わせたもの。

        Parameters
        ----------
        item
            Readable item to draw.
            描く項目（読めたもの）。
        layout
            Page grid.
            ページの格子。
        index
            Position of the item on its page.
            ページ内での項目の位置。
        scale
            Screen pixels per millimeter of the page.
            ページ 1 mm あたりの画面のピクセル数。
        page_x, page_y
            Canvas position of the page's top left corner.
            ページ左上の canvas 上の位置。
        """
        canvas = self.canvas
        _page_w, page_h = layout.page_mm

        def to_x(mm: float) -> float:
            return page_x + mm * scale

        def to_y(mm: float) -> float:
            # Sheet lengths are measured up from the bottom of the page.
            # シートの長さは、ページの下端から上向きに測る。
            return page_y + (page_h - mm) * scale

        left, bottom, cell_w, cell_h = layout.cell_box_mm(index)
        box = (item.key, to_x(left), to_y(bottom + cell_h),
               to_x(left + cell_w), to_y(bottom))
        self._tile_boxes.append(box)
        self._page_boxes.append(box)
        if item.key in self.selected:
            canvas.create_rectangle(box[1] + 1, box[2] + 1, box[3] - 1, box[4] - 1,
                                    fill=TILE_SELECTED_BG,
                                    outline=TILE_SELECTED_OUTLINE, width=2)

        parts = layout.cell_parts(
            index, height_over_width(item.scan_size_um, item.shape))
        img_left, img_bottom, box_w, box_h = parts.image
        photo = self._photo_for(item, max(1, round(box_w * scale)),
                                max(1, round(box_h * scale)))
        canvas.create_image(to_x(img_left + box_w / 2),
                            to_y(img_bottom + box_h / 2), image=photo)

        vrange = self._vrange_for(item)
        scale_bar = self._scale_bar_of(item)
        if parts.scale_bar_y is not None and scale_bar is not None:
            fraction, label = scale_bar
            length = fraction * box_w
            canvas.create_line(
                to_x(img_left), to_y(parts.scale_bar_y),
                to_x(img_left + length), to_y(parts.scale_bar_y),
                fill="black", width=max(1, round(SCALE_BAR_THICKNESS_MM * scale)))
            canvas.create_text(
                to_x(img_left + length + SCALE_BAR_LABEL_GAP_MM),
                to_y(parts.scale_bar_y), anchor="w", text=label,
                font=self._font_for(layout.scale_bar_pt, scale))
        if parts.colorbar_y is not None:
            strip_w = colorbar_width_mm(parts.text_width)
            strip_left = parts.center_x - strip_w / 2
            gradient = self._gradient_photo(
                max(2, round(strip_w * scale)),
                max(2, round(COLORBAR_HEIGHT_MM * scale)))
            colorbar_font = self._font_for(layout.colorbar_pt, scale)
            canvas.create_image(to_x(parts.center_x), to_y(parts.colorbar_y),
                                image=gradient)
            canvas.create_text(
                to_x(strip_left - COLORBAR_LABEL_GAP_MM), to_y(parts.colorbar_y),
                anchor="e", font=colorbar_font, text="{0:g}".format(vrange[0]))
            canvas.create_text(
                to_x(strip_left + strip_w + COLORBAR_LABEL_GAP_MM),
                to_y(parts.colorbar_y), anchor="w", font=colorbar_font,
                text="{0:g} nm".format(vrange[1]))

        text_w = parts.text_width * scale
        name_font = self._font_for(layout.name_pt, scale)
        canvas.create_text(
            to_x(parts.center_x), to_y(parts.name_top), anchor="n", font=name_font,
            text=elide_middle(item.name, lambda s: name_font.measure(s) <= text_w))

    def _draw_unreadable(self, y: float, width: int) -> float:
        """
        List the bundles that could not be read, below the pages.
        読めなかったバンドルを、ページの下に一覧で示す。

        They are kept off the pages because they are not on the saved sheet;
        each is a row that can be selected and taken out of the gallery.
        保存するシートには載らないので、ページの外に置く。各行は選択して一覧から
        外せる。

        Parameters
        ----------
        y
            Canvas position below the last page.
            最後のページの下の canvas 上の位置。
        width
            Canvas width.
            canvas の幅。

        Returns
        -------
        float
            Canvas position below the list.
            一覧の下の canvas 上の位置。
        """
        unreadable = [item for item in self.items if not item.readable]
        if not unreadable:
            return y
        canvas = self.canvas
        line_h = self._ui_font.metrics("linespace")
        left, right = PAGE_MARGIN_PX, width - PAGE_MARGIN_PX
        canvas.create_text(left, y, anchor="nw", font=self._ui_font,
                           fill=ERROR_TEXT, text=_("読み込めなかったファイル"))
        y += line_h + 4

        def fits(text: str) -> bool:
            return self._ui_font.measure(text) <= right - left - 12

        for item in unreadable:
            chosen = item.key in self.selected
            self._tile_boxes.append((item.key, left, y, right, y + line_h + 6))
            canvas.create_rectangle(
                left, y, right, y + line_h + 6,
                fill=TILE_SELECTED_BG if chosen else ERROR_ROW_BG,
                outline=TILE_SELECTED_OUTLINE if chosen else "")
            canvas.create_text(
                left + 6, y + 3, anchor="nw", font=self._ui_font,
                text=elide_end("{0}: {1}".format(item.name, item.error), fits))
            y += line_h + 8
        return y + PAGE_MARGIN_PX

    # ----- Selection and dragging -----

    def _set_selection(self, keys: set, anchor: Optional[str]) -> None:
        """
        Replace the selection and refresh what depends on it.
        選択を置き換え、それに依存する表示を更新する。
        """
        self.selected = set(keys)
        self._anchor_key = anchor
        self._sync_range_entries()
        self._update_controls()
        self._relayout()

    def _key_at(self, x: float, y: float) -> Optional[str]:
        """
        Return the key of the tile under a canvas position, if any.
        canvas 上の位置にあるタイルのキーを返す（あれば）。
        """
        for key, x0, y0, x1, y1 in self._tile_boxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return key
        return None

    def _on_press(self, event) -> None:
        """
        Select tiles: click one, Ctrl+click to toggle, Shift+click a range.
        タイルを選択する。クリックで 1 つ、Ctrl+クリックで切り替え、Shift+
        クリックで範囲。

        A press on a tile that is already selected changes nothing yet, so the
        whole selection can be dragged; released without a drag it selects
        that tile alone.
        既に選択されているタイルの上での押下は、まだ何も変えない。選択全体を
        ドラッグできるようにするため。ドラッグせずに離すと、そのタイルだけを
        選択する。
        """
        self.canvas.focus_set()
        self._press = None
        key = self._key_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        ctrl = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        if key is None:
            if not (ctrl or shift):
                self._set_selection(set(), anchor=None)
            return
        if shift and self._anchor_key is not None:
            keys = [box[0] for box in self._tile_boxes]
            if self._anchor_key in keys:
                first, last = sorted((keys.index(self._anchor_key), keys.index(key)))
                chosen = set(keys[first:last + 1])
                self._set_selection((self.selected | chosen) if ctrl else chosen,
                                    anchor=self._anchor_key)
            return
        if ctrl:
            self._set_selection(self.selected ^ {key}, anchor=key)
            return
        if key in self.selected:
            self._press = (key, event.x, event.y, True)
            return
        self._set_selection({key}, anchor=key)
        self._press = (key, event.x, event.y, False)

    def _on_motion(self, event) -> None:
        """
        Drag the pressed tile, showing where it would be put.
        押したタイルをドラッグし、入る場所を示す。
        """
        if self._press is None:
            return
        key, press_x, press_y, _select_on_release = self._press
        if not self._dragging:
            if abs(event.x - press_x) + abs(event.y - press_y) < DRAG_THRESHOLD_PX:
                return
            # Only tiles on a page have an order to change.
            # 並び順を変えられるのは、ページ上のタイルだけ。
            if all(box[0] != key for box in self._page_boxes):
                return
            self._dragging = True
            self.canvas.configure(cursor="fleur")

        if event.y < DRAG_SCROLL_EDGE_PX:
            self._scroll_by(-DRAG_SCROLL_STEP_PX)
        elif event.y > self.canvas.winfo_height() - DRAG_SCROLL_EDGE_PX:
            self._scroll_by(DRAG_SCROLL_STEP_PX)

        self.canvas.delete("dropmark")
        point = insertion_point(self._page_boxes, self.canvas.canvasx(event.x),
                                self.canvas.canvasy(event.y))
        if point is None:
            self._drop_before = _NO_DROP_TARGET
            return
        self._drop_before, (line_x, line_y0, line_y1) = point
        self.canvas.create_line(line_x, line_y0, line_x, line_y1, width=4,
                                fill=DROP_MARK_COLOR, tags="dropmark")

    def _on_release(self, _event) -> None:
        """
        Finish a drag by moving the tiles, or a click by selecting the tile.
        ドラッグならタイルを動かして終え、クリックならタイルを選択して終える。
        """
        press, self._press = self._press, None
        if self._dragging:
            self._dragging = False
            self.canvas.configure(cursor="")
            self.canvas.delete("dropmark")
            target, self._drop_before = self._drop_before, _NO_DROP_TARGET
            if press is None or target is _NO_DROP_TARGET:
                return
            key = press[0]
            # A drag started on a selected tile carries the whole selection.
            # 選択中のタイルから始めたドラッグは、選択全体を運ぶ。
            moving = ([box[0] for box in self._page_boxes if box[0] in self.selected]
                      if key in self.selected else [key])
            self.move_items(moving, target)
            return
        if press is not None and press[3]:
            self._set_selection({press[0]}, anchor=press[0])

    def _scroll_by(self, pixels: float) -> None:
        """
        Scroll the gallery by a number of pixels.
        一覧を、指定のピクセル数だけスクロールする。
        """
        region = self.canvas.cget("scrollregion").split()
        total = float(region[3]) if len(region) == 4 else 0.0
        if total <= 0:
            return
        top = self.canvas.yview()[0] * total
        self.canvas.yview_moveto(max(0.0, (top + pixels) / total))

    def _on_select_all(self, _event=None) -> str:
        """
        Select every tile.
        すべてのタイルを選択する。
        """
        self._set_selection({item.key for item in self.items},
                            anchor=self._anchor_key)
        return "break"

    # ----- View settings -----

    def _on_view_changed(self) -> None:
        """
        Redraw after the page orientation changed.
        用紙の向きが変わった後に描き直す。
        """
        self._relayout()

    def _on_zoom_chosen(self) -> None:
        """
        Apply the zoom picked in the list: a fitted view or a percentage.
        一覧で選ばれた倍率（枠に合わせる表示、または百分率）を適用する。
        """
        index = self.cmb_zoom.current()
        if index == 0:
            self._zoom_mode = ZOOM_FIT_WIDTH
        elif index == 1:
            self._zoom_mode = ZOOM_WHOLE_PAGE
        elif index >= 2:
            self._zoom_mode = ZOOM_PERCENT
            self._zoom_percent = float(ZOOM_PRESETS[index - 2])
        self._relayout()

    def set_zoom_percent(self, percent: float) -> None:
        """
        Draw the pages at a percentage of the paper size.
        ページを、用紙の実寸に対する百分率で描く。

        Parameters
        ----------
        percent
            Zoom in percent, limited to `ZOOM_MIN_PERCENT` to
            `ZOOM_MAX_PERCENT`. The zoom list shows the value, whether or not
            it is one of its entries.
            倍率（%）。`ZOOM_MIN_PERCENT` から `ZOOM_MAX_PERCENT` の範囲に
            収める。倍率の一覧には、その項目に無い値でも、この値を表示する。
        """
        self._zoom_mode = ZOOM_PERCENT
        self._zoom_percent = min(ZOOM_MAX_PERCENT, max(ZOOM_MIN_PERCENT, percent))
        self.cmb_zoom.set("{0:.0f}%".format(self._zoom_percent))
        self._relayout()

    def _on_zoom_wheel(self, event) -> str:
        """
        Zoom the pages with Ctrl and the mouse wheel.
        Ctrl+マウスホイールで、ページの表示倍率を変える。

        The step starts from the size the pages have now, so it also leaves a
        fitted view smoothly.
        刻みは現在のページの大きさを起点にするので、枠に合わせた表示からも
        なめらかに移る。
        """
        # Wheel forward (up) zooms in: a positive delta, or button 4 on X11.
        # 前（上）へ回すと拡大。delta が正、または X11 のボタン 4。
        forward = getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0
        current = self._page_scale / self._paper_scale() * 100.0
        factor = ZOOM_WHEEL_FACTOR if forward else 1.0 / ZOOM_WHEEL_FACTOR
        self.set_zoom_percent(current * factor)
        # "break" keeps the window's wheel binding from scrolling as well.
        # "break" で、ウィンドウのホイール用バインドが併せてスクロールするのを
        # 止める。
        return "break"

    def _on_shift_wheel(self, event) -> str:
        """
        Scroll the gallery sideways with Shift and the mouse wheel.
        Shift+マウスホイールで、一覧を横にスクロールする。
        """
        forward = getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0
        first, last = self.canvas.xview()
        if not (first <= 0.0 and last >= 1.0):
            self.canvas.xview_scroll(-1 if forward else 1, "units")
        return "break"

    def on_open_font_sizes(self) -> None:
        """
        Show the window of the three font sizes, or bring it to the front.
        3 つのフォントサイズのウィンドウを表示する（既にあれば前面に出す）。
        """
        if self._font_dialog is not None and self._font_dialog.winfo_exists():
            self._font_dialog.lift()
            self._font_dialog.focus_set()
            return
        self._font_dialog = FontSizeDialog(self)

    def on_reset_font_sizes(self) -> None:
        """
        Return the three font sizes to their defaults.
        3 つのフォントサイズを既定値に戻す。
        """
        for key, size in DEFAULT_FONT_PT.items():
            self.font_vars[key].set("{0:.1f}".format(size))

    def _sync_range_entries(self) -> None:
        """
        Show in the vmin/vmax entries the range of the selected images.
        vmin/vmax の入力欄に、選択した画像の範囲を表示する。

        Each entry shows a value only when every selected image has that
        value; where they differ it is blank, so one image's value is never
        read as the value of all. With no image selected both are blank and
        disabled: there is nothing to show or to change.
        各入力欄は、選択した画像すべてが同じ値を持つときだけ、その値を表示する。
        値が異なる側は空欄にし、1 枚の値が全体の値に見えないようにする。画像を
        選択していなければ、表示する値も変える対象も無いので、両方を空にして
        無効にする。
        """
        targets = self.selected_images()
        ranges = [self._vrange_for(item) for item in targets]
        texts = []
        for bound in (0, 1):
            values = {vrange[bound] for vrange in ranges}
            texts.append(self._fmt_num(values.pop()) if len(values) == 1 else "")
        self._edit_texts = (texts[0], texts[1])

        entries = (self.ent_vmin, self.ent_vmax)
        for entry in entries:
            entry.configure(state="normal")
        rewrite_entries(zip(entries, self._edit_texts))
        self._refresh_all_entry_states()
        if not targets:
            for entry in entries:
                entry.configure(state="disabled")

    def _commit_vrange(self) -> bool:
        """
        Apply the entered vmin/vmax to the selected images.
        入力された vmin/vmax を、選択した画像に適用する。

        A blank entry leaves that bound of each image as it is, so one bound
        can be set for images whose other bounds differ. Nothing is applied
        when an entry is not a number, or when an image would be left with a
        vmax not above its vmin.
        空欄の側は、各画像のその値を変えない。これにより、もう一方の値が異なる
        画像に対しても、片方だけを揃えられる。数値でない入力があるとき、または
        vmax が vmin 以下になる画像があるときは、何も適用しない。

        Returns
        -------
        bool
            ``True`` when the entries were accepted, ``False`` when a value
            was refused and a dialog said why.
            入力を受け付けた場合は ``True``。値を拒否し、理由をダイアログで
            示した場合は ``False``。
        """
        targets = self.selected_images()
        if not targets:
            return True
        bounds: List[Optional[float]] = []
        for entry in (self.ent_vmin, self.ent_vmax):
            text = entry.get().strip()
            if not text:
                bounds.append(None)
                continue
            try:
                value = float(text)
            except ValueError:
                value = float("nan")
            if not math.isfinite(value):
                messagebox.showerror(_("エラー"), _("数値を入力してください"),
                                     parent=self)
                return False
            bounds.append(value)
        low, high = bounds

        new_ranges = []
        for item in targets:
            current = self._vrange_for(item)
            vrange = (current[0] if low is None else low,
                      current[1] if high is None else high)
            # A range of no width has no colors to spread.
            # 幅の無い範囲では、色を割り当てられない。
            if not vrange[1] > vrange[0]:
                messagebox.showerror(
                    _("エラー"),
                    _("vmax には vmin より大きい値を入力してください"),
                    parent=self)
                return False
            new_ranges.append(vrange)

        if low is not None or high is not None:
            for item, vrange in zip(targets, new_ranges):
                item.manual_vrange = vrange
            if low is not None and high is not None:
                self._log(_(
                    "{n} 件の画像の色範囲を {vmin} 〜 {vmax} nm に設定しました。"
                ).format(n=len(targets), vmin=self._fmt_num(low),
                         vmax=self._fmt_num(high)))
            else:
                self._log(_(
                    "{n} 件の画像の {bound} を {value} nm に設定しました。"
                ).format(n=len(targets),
                         bound="vmin" if low is not None else "vmax",
                         value=self._fmt_num(low if low is not None else high)))
        self._sync_range_entries()
        self._update_controls()
        self._relayout()
        return True

    def on_auto_range(self) -> None:
        """
        Return the selected images to their automatic color range.
        選択した画像を、自動の色範囲に戻す。

        The button stays enabled; with nothing to do it says why in the log
        instead of changing anything.
        ボタンは常に押せる。することが無い場合は、何も変えずに理由をログに出す。
        """
        targets = self.selected_images()
        if not targets:
            self._log(_("色範囲を自動に戻す画像を選択してください。"))
            return
        changed = [item for item in targets if item.manual_vrange is not None]
        if not changed:
            self._log(_("選択した画像は、既に自動の色範囲です。"))
            return
        for item in changed:
            item.manual_vrange = None
        self._log(_("{n} 件の画像の色範囲を自動に戻しました。").format(n=len(changed)))
        self._sync_range_entries()
        self._update_controls()
        self._relayout()

    def on_open_selected_in(self, module_import_path: str, gui_name: str) -> None:
        """
        Open each selected image in another GUI, one window per bundle.
        選択した各画像を別の GUI で開く。バンドル 1 つにつきウィンドウ 1 つ。

        Parameters
        ----------
        module_import_path
            `PROFILER_MODULE` or `TRACKER_MODULE`.
            `PROFILER_MODULE` または `TRACKER_MODULE`。
        gui_name
            Name of that GUI in the confirmation, ``"GUI02"`` or ``"GUI04"``.
            確認に表示するその GUI の名前（``"GUI02"`` または ``"GUI04"``）。

        Notes
        -----
        Each window is a process of its own that loads its libraries afresh,
        so from `OPEN_CONFIRM_COUNT` selected images on the user is asked
        first; a whole gallery left selected is otherwise opened at one click.
        各ウィンドウは独立したプロセスで、ライブラリを新たに読み込む。そのため、
        選択が `OPEN_CONFIRM_COUNT` 件以上のときは先に確認する。確認が無いと、
        全選択のままの一覧が 1 回のクリックですべて開いてしまう。
        """
        targets = self.selected_images()
        if not targets:
            self._log(_("開く画像を選択してください。"))
            return
        if len(targets) >= OPEN_CONFIRM_COUNT and not messagebox.askokcancel(
                _("確認"),
                _("選択した {n} 件を {gui} で開きます。ウィンドウが {n} 個開きます。").format(
                    n=len(targets), gui=gui_name),
                parent=self):
            return
        for item in targets:
            try:
                # The child starts in the application folder, so the bundle is
                # named by its full path.
                # 子プロセスはアプリのフォルダで起動するので、バンドルは絶対
                # パスで渡す。
                launch_plugin(module_import_path, [os.path.abspath(item.path)])
            except Exception as exc:  # noqa: BLE001 - reported, nothing is lost
                self._log_exception(_("起動に失敗しました"), exc)
                return
            self._log(_("{name} を新しいウインドウで開きます。").format(name=item.name))

    def on_open_selected_in_statistics(self) -> None:
        """
        Open every selected image in one GUI03 window, as one group.
        選択した全画像を、1 つのグループとして 1 つの GUI03 ウィンドウで開く。

        Notes
        -----
        GUI03 aggregates the bundles of a group together, so the selection is
        one hand-over rather than a window per bundle. The paths go through a
        list file (`path_list_arguments`), since a selection can hold more
        paths than a command line does. Like the other two buttons it acts on
        `selected_images`, which leaves out a bundle that could not be read.
        GUI03 はグループのバンドルをまとめて集計するため、選択はバンドルごとの
        ウィンドウではなく 1 回の受け渡しになる。パスは一覧ファイルで渡す
        （`path_list_arguments`）。選択はコマンドラインに入る数より多くのパスを
        持ちうるためである。他の 2 つのボタンと同じく `selected_images` を対象に
        するため、読めなかったバンドルは含まれない。
        """
        targets = self.selected_images()
        if not targets:
            self._log(_("開く画像を選択してください。"))
            return
        try:
            # The child starts in the application folder, so the bundles are
            # named by their full paths.
            # 子プロセスはアプリのフォルダで起動するので、バンドルは絶対パスで渡す。
            launch_plugin(STATISTICS_MODULE, path_list_arguments(
                [os.path.abspath(item.path) for item in targets]))
        except Exception as exc:  # noqa: BLE001 - reported, nothing is lost
            self._log_exception(_("起動に失敗しました"), exc)
            return
        self._log(_("{n} 件の画像を GUI03 の新しいウインドウで開きます。").format(
            n=len(targets)))

    @staticmethod
    def _fmt_num(v) -> str:
        """
        Format a committed range value without a trailing ``.0``.
        確定した範囲の値を、末尾の ``.0`` を付けずに整形する。
        """
        return f"{float(v):g}"

    # ----- Sheet export -----

    def sheet_entries(self) -> List[SheetEntry]:
        """
        Return the images of the sheet, in the order the pages show them.
        シートの画像を、ページが表示している順で返す。

        These are the readable bundles of the gallery; an unreadable one is
        listed below the pages on the screen and is not on the sheet.
        一覧のうち読めたバンドルがこれに当たる。読めなかったものは画面では
        ページの下に並び、シートには載らない。
        """
        return [
            SheetEntry(
                path=item.path, name=item.name,
                aspect=height_over_width(item.scan_size_um, item.shape),
                vrange=self._vrange_for(item),
                scale_bar=self._scale_bar_of(item))
            for item in self.readable_items()
        ]

    def on_export(self) -> None:
        """
        Ask where to save the sheet and write it in the worker thread.
        シートの保存先を選ばせ、ワーカースレッドで書き出す。
        """
        if self._outstanding > 0:
            return
        entries = self.sheet_entries()
        if not entries:
            messagebox.showinfo(
                _("シートを保存"), _("保存する画像がありません。"), parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title=_("シートを保存"), defaultextension=".png",
            initialdir=self._last_dir or os.getcwd(),
            initialfile="thumbnails", filetypes=SHEET_FILETYPES)
        if not path:
            return
        if os.path.splitext(path)[1].lower() not in (".png", ".pdf"):
            messagebox.showerror(
                _("保存エラー"),
                _("拡張子は .png または .pdf にしてください。"), parent=self)
            return

        layout = self._sheet_layout()
        n_pages = (len(entries) + layout.per_page - 1) // layout.per_page
        targets = sheet_page_paths(path, n_pages)
        # The save dialog confirmed only the name that was typed; the numbered
        # page files of a PNG export are confirmed here.
        # 保存ダイアログが確認したのは入力した名前だけ。PNG 出力で連番を付けた
        # ページのファイルは、ここで上書きを確認する。
        existing = [t for t in targets if t != path and os.path.exists(t)]
        if existing and not messagebox.askyesno(
                _("シートを保存"),
                _("次のファイルは既にあります。上書きしますか？\n{names}").format(
                    names="\n".join(os.path.basename(t) for t in existing)),
                parent=self):
            return

        self._last_dir = os.path.dirname(path)
        self._exporting = True
        self.status_var.set(_("シートを保存中… {page} / {n_pages} ページ").format(
            page=0, n_pages=n_pages))
        self._log(_("シートを保存します（画像 {n} 件、{n_pages} ページ）。").format(
            n=len(entries), n_pages=n_pages))
        self._submit(("export", (entries, layout, path)))
        self._update_controls()

    def on_save_log(self) -> None:
        """
        Save the log text through a file dialog.
        ログ本文をファイルダイアログ経由で保存する。
        """
        save_text_widget_log(
            self, self.log_text,
            initial_dir=self._last_dir,
            initialfile="thumbnail_viewer_log.txt",
            empty_warning=True,
            log_cb=self._log,
        )


class FontSizeDialog(tk.Toplevel):
    """
    Window setting the three font sizes of the sheet.
    シートの 3 つのフォントサイズを設定するウィンドウ。

    Each size is in points on the saved sheet and is applied at once, to the
    screen and to the sheet alike, through the variables of the main window.
    各サイズは保存するシート上のポイントで、メインウィンドウの変数を通じて、
    画面とシートの両方にすぐ反映される。
    """

    def __init__(self, app: "App") -> None:
        """
        Build the window beside its owner.
        持ち主のウィンドウのそばに、ウィンドウを作成する。

        Parameters
        ----------
        app
            Main window whose `App.font_vars` the spinboxes edit.
            スピンボックスが編集する `App.font_vars` を持つメインウィンドウ。
        """
        super().__init__(app)
        self.title(_("フォントサイズ"))
        self.transient(app)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        rows = [
            (_("ファイル名"), FONT_NAME),
            (_("スケールバー"), FONT_SCALE_BAR),
            (_("カラーバー"), FONT_COLORBAR),
        ]
        for index, (label, key) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w",
                                              pady=3)
            # Read-only: the arrows move in half points, so no entered text
            # needs checking.
            # 読み取り専用。矢印で 0.5 ポイントずつ動かすので、入力された
            # 文字列を検証する必要が無い。
            ttk.Spinbox(frame, from_=FONT_PT_MIN, to=FONT_PT_MAX,
                        increment=FONT_PT_STEP, format="%.1f", width=5,
                        state="readonly", textvariable=app.font_vars[key],
                        ).grid(row=index, column=1, padx=(12, 4), pady=3)
            ttk.Label(frame, text="pt").grid(row=index, column=2, sticky="w")
        note = ttk.Label(
            frame, wraplength=260, justify=tk.LEFT,
            text=_("大きさは保存するシート上のポイントです。セルの幅に収まらない"
                   "ファイル名は、中央を省略します。"))
        note.grid(row=len(rows), column=0, columnspan=3, sticky="w", pady=(8, 6))
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(rows) + 1, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text=_("既定に戻す"),
                   command=app.on_reset_font_sizes).pack(side=tk.LEFT)
        ttk.Button(buttons, text=_("閉じる"),
                   command=self.destroy).pack(side=tk.LEFT, padx=(6, 0))
        self.update_idletasks()
        # Placed over the owner's top left area, where its controls are.
        # 持ち主の左上（操作欄のあるあたり）に重ねて置く。
        self.geometry("+{0}+{1}".format(app.winfo_rootx() + 60,
                                        app.winfo_rooty() + 90))


def main() -> None:
    """
    Start the thumbnail viewer, adding the paths named on the command line.
    Thumbnail Viewer を起動し、コマンドラインで指定されたパスを追加する。

    Each argument is a bundle file or a folder of bundles
    (`afm_nanofiber_analyzer.plugin_launch`); without one the window opens empty.
    各引数はバンドルファイルまたはバンドルのフォルダ（`afm_nanofiber_analyzer.plugin_launch`）。
    引数が無ければ空のウィンドウで開く。
    """
    app = App()
    if len(sys.argv) > 1:
        # Load once the window is on screen, so the thumbnails appear in it
        # as they are read.
        # 読み込んだサムネイルが順に表示されるよう、ウィンドウの表示後に読み込む。
        call_when_shown(app, app.add_paths, sys.argv[1:])
    app.mainloop()


# Run the GUI only when this module is executed directly.
if __name__ == "__main__":
    main()
