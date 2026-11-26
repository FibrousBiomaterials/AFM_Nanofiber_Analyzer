"""
GUI plugin showing one analyzed ``.b2z`` bundle as layers and correcting its results by hand.
解析済みの ``.b2z`` バンドル 1 つをレイヤーとして表示し、解析結果を手で修正する GUI プラグイン。

Input: one ``.b2z`` bundle written by GUI01, chosen through a file dialog or
named on the command line. The raw height image is taken from the bundle's
``original`` key or, without one, from the input file the bundle records when
that file sits in the bundle's folder (`afm_nanofiber_analyzer.bundle_edit`).
入力は GUI01 が書き出した ``.b2z`` バンドル 1 つ。ファイルダイアログで選ぶか、
コマンドラインで指定する。生の高さ画像は、バンドルの ``original`` キーから取る。
無ければ、バンドルが記録する入力ファイルがバンドルのフォルダにある場合に、それを
読む（`afm_nanofiber_analyzer.bundle_edit`）。

Output: an edited bundle and its ``_param.json``, written through a save
dialog ("名前を付けて保存…", Ctrl+Shift+S); the default name is the opened
bundle's stem followed by ``_edited``.
The edited bundle has the keys of a GUI01 bundle and records in its metadata
that a person changed it (`bundle_schema.MANUAL_EDIT_KEY`), together with the
points that set the angle of each kink given one by hand
(`bundle_schema.KINK_ARMS_KEY`). It also stores the ridge mask
(`bundle_schema.FIBER_MASK_KEY`) when that mask is known to belong to the
bundle (`bundle_edit.BundleEditor.save`). The bundle GUI01 wrote is never
overwritten. An edited bundle that is open, including one just saved, can be
saved over with "上書き保存" (Ctrl+S) once something has changed, after a
confirmation. While a bundle GUI01 wrote is being edited, Ctrl+S opens the
save dialog instead.
出力は、編集したバンドルとその ``_param.json`` で、保存ダイアログ（「名前を付けて
保存…」、Ctrl+Shift+S）から書き出す。
既定の名前は、開いたバンドルの stem に ``_edited`` を付けたもの。編集したバンドルは
GUI01 のバンドルと同じキーを持ち、人が変更したことをメタデータに記録する
（`bundle_schema.MANUAL_EDIT_KEY`）。手で角度を決めたキンクについては、その角度を
決める点も記録する（`bundle_schema.KINK_ARMS_KEY`）。リッジマスクも、そのバンドルの
ものだと分かっているときに保存する（`bundle_schema.FIBER_MASK_KEY`、
`bundle_edit.BundleEditor.save`）。GUI01 が書いたバンドルには上書きしない。
開いている編集済みのバンドル（保存した直後のものを含む）には、何かを変更したあと、
確認のうえ「上書き保存」（Ctrl+S）で上書きできる。GUI01 が書いたバンドルを編集して
いる間の Ctrl+S は、代わりに保存ダイアログを開く。

The image pane draws the results of every analysis stage over one another: the
raw height image, the fiber mask the background stage excluded from its fill
(the "ridge mask"), the background-corrected image, the binarized image, the
skeleton, the line each fiber is measured along, and the kinks with the bends
that were not judged. A bundle GUI01 wrote does not store the ridge mask; it is
obtained by repeating the background stage on the raw image with the recorded
settings (with the stored mask, when an edited bundle has one), and the log
says when the repeated stage no longer gives the stored heights, because the
mask shown is then not the one the analysis used.
画像ペインは、解析の各段の結果を重ねて描く。生の高さ画像、背景補正が穴埋めから
除外した繊維マスク（「リッジマスク」）、背景補正画像、二値化画像、細線化画像、
各繊維を計測する線、キンクと判定しなかった折れである。GUI01 が書いたバンドルは
リッジマスクを保存しないため、記録された設定で生の画像に背景補正をやり直して得る
（編集したバンドルがマスクを保存していれば、そのマスクを使ってやり直す）。やり直した
補正が保存済みの高さを再現しない場合は、ログがそれを伝える。そのとき表示している
マスクは、解析が使ったものではないためである。

The layer pane lists the layers from the topmost down. Each can be hidden,
given an opacity, and dragged to another place in the stack. A layer whose
data cannot be obtained (no raw image, a background method without a mask) is
left out of the list. Clicking the name of the kink layer, the skeleton, the
binarized image or the ridge mask makes it the layer the tools above the image
act on (`LAYER_TOOLS`).
レイヤーペインは、レイヤーを上から順に並べる。レイヤーごとに、非表示にする、
不透明度を変える、ドラッグして重ね順を変える、ができる。データを得られない
レイヤー（生の画像が無い、マスクを使わない背景補正の方式）は一覧に入れない。
キンク・細線化画像・二値化画像・リッジマスクのいずれかのレイヤーの名前を
クリックすると、画像の上のツールがそのレイヤーに働く（`LAYER_TOOLS`）。

The ridge mask and the binarized image are corrected with a pencil and an
eraser, and the skeleton with the eraser alone, so that its lines stay one
pixel wide (`bundle_edit.PAINTABLE`). Each stage can be run again on the
results as they stand: detecting the ridge mask, the background stage (with
the current ridge mask, for the methods that use one), binarization,
skeletonization and kink detection. The settings of the background stage and
of binarization are changed in a dialog. A change to one result, or to the
settings of its stage, marks the results computed from it as stale in the
layer pane until their stages are run again (`bundle_edit.DOWNSTREAM`), and a
saved bundle records which were stale. Stages run in a worker thread.
リッジマスクと二値化画像は鉛筆と消しゴムで修正し、細線化画像は消しゴムだけで
修正する。線の太さを 1 画素に保つためである（`bundle_edit.PAINTABLE`）。解析の
各段は、現在の結果を入力にして再実行できる。リッジマスクの検出、背景補正
（マスクを使う方式では現在のリッジマスクを使う）、二値化、細線化、キンク検出である。
背景補正と二値化の設定はダイアログで変更する。ある結果、またはその段の設定を
変えると、そこから計算される結果には、その段を再実行するまでレイヤーペインで
「古い」の印が付く（`bundle_edit.DOWNSTREAM`）。保存したバンドルには、どれが
古かったかが記録される。段の実行はワーカースレッドで行う。

Kinks are added, removed and moved by hand, always on a skeleton pixel of a
traced fiber, where a bundle stores them. The angle of a kink is set by two
points on its fiber, one on either side, drawn in red when the kink is chosen
with the kink-editing tool and dragged along the skeleton: they are the ends
of the kink's two arms, each of which starts a set distance from the kink, and
the angle is the one between the arms (`bundle_edit.KinkEditor`). A kink the
bundle stores keeps the angle the kink rule gave it until one of its two
points is moved. Only a bundle of the current format can be edited; an older
one is shown.
キンクは手で足す・消す・動かすことができ、置く場所は常に、追跡した繊維の
スケルトン画素の上である。バンドルがキンクを保存するのもそこである。キンクの角度は、
その繊維の上で両側に 1 つずつ置く 2 つの点で決める。2 つの点は、キンク編集の
ツールでキンクを選ぶと赤で描かれ、スケルトンに沿ってドラッグできる。2 つの点は
キンクの 2 本の腕の端であり、各腕はキンクから決まった距離だけ離れた位置で始まる。
角度は 2 本の腕のなす角である（`bundle_edit.KinkEditor`）。バンドルが保存する
キンクは、2 つの点のどちらかを動かすまで、キンク規則が与えた角度を保つ。編集
できるのは現在の形式のバンドルだけで、古い形式のバンドルは表示だけする。
"""

# ===== Plugin metadata =====
# Main.py parses this dictionary with ast.literal_eval() for the launcher.
# Main.py は ast.literal_eval() でこの辞書を読み取り、ランチャー画面に表示する。
# Values must remain string literals because literal_eval cannot parse gettext calls.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Bundle Editor",
    "description": (
        "Image Preprocessor で解析した .b2z バンドルを 1 つ読み込み、解析の各段階の"
        "結果をレイヤーとして重ねて表示します。\n"
        "レイヤーは、元データ、背景補正に使ったリッジマスク、背景補正画像、二値化画像、"
        "細線化画像、中心線、キンクです。レイヤーごとに表示・非表示と不透明度を"
        "切り替えられ、ドラッグで重ね順を変えられます。\n"
        "リッジマスクと二値化画像は鉛筆と消しゴムで、細線化画像は消しゴムで修正できます。"
        "キンクは、繊維の細線化画素の上で、手で追加・消去・移動できます。キンクの角度は、"
        "キンクの両側に置く 2 つの端点をドラッグして決められます。\n"
        "リッジマスクの検出・背景補正・二値化・細線化・キンク検出は、現在のレイヤーを"
        "入力にして再実行できます。背景補正と二値化は設定を変更できます。元になる"
        "レイヤーが変わったあと計算し直していないレイヤーには「古い」の印が付きます。\n"
        "編集した結果は別名のバンドルとして保存し、手で編集したことを記録します。"
        "編集済みのバンドルを開いているときは、上書き保存もできます。"
        "解析で書き出したバンドルには上書きしません。\n"
        "元データは、バンドルに含まれていなければ、バンドルと同じフォルダにある"
        "元ファイルから読み込みます。リッジマスクは、元データと記録された解析条件から"
        "計算し直して表示します。"
    )
}

# ===== Standard library =====
import os
import queue
import sys
import threading
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import LineCollection
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure

# ===== Project libraries =====
from afm_nanofiber_analyzer.blosc2_io import BUNDLE_EXT
from afm_nanofiber_analyzer.bundle_edit import (
    ARM_AFTER, ARM_BEFORE, MARK_KINK, MASK_BG_METHODS, PAINTABLE,
    RAW_FROM_BUNDLE, RAW_MISSING_CHANGED, RAW_MISSING_NOT_FOUND,
    RAW_MISSING_NOT_RECORDED, RAW_MISSING_SHAPE, RAW_MISSING_UNREADABLE, RESULTS,
    STAGE_BACKGROUND, STAGE_BINARIZE, STAGE_KINKS, STAGE_MASK, STAGE_RESULT,
    STAGE_SKELETONIZE, BundleEditor, EditSession, KinkEditor, edited_path_for,
    fiber_line, load_edit_session,
)
from afm_nanofiber_analyzer.bundle_schema import BUNDLE_FORMAT_VERSION, MANUAL_EDIT_KEY
from afm_nanofiber_analyzer.pipeline import ProcParams
from afm_nanofiber_analyzer.plugin_launch import call_when_shown
from afm_nanofiber_analyzer.translator import _
from afm_nanofiber_analyzer.ui_tools import (
    LogMixin, ToolTip, apply_window_size, build_pan_zoom_toolbar,
    compute_auto_vrange, create_scrolled_text, drain_ui_queue,
    save_text_widget_log, setup_matplotlib_style, setup_ttk_theme,
)

# ===== Internal state keys =====
# Layer identifiers and kinds. Fixed English keys, not user-visible text.
# レイヤーの識別子と種類。固定の英語キーで、表示文字列ではない。
LAYER_RAW = "raw"
LAYER_CALIBRATED = "calibrated"
LAYER_FIBER_MASK = "fiber_mask"
LAYER_BINARIZED = "binarized"
LAYER_SKELETON = "skeletonized"
LAYER_CENTERLINE = "centerline"
LAYER_KINKS = "kinks"

KIND_HEIGHT = "height"
KIND_MASK = "mask"
KIND_LINES = "lines"
KIND_POINTS = "points"

# What a left click on the image does. Fixed English keys, not user-visible text.
# 画像の上での左クリックの働き。固定の英語キーで、表示文字列ではない。
TOOL_NONE = "none"
TOOL_PENCIL = "pencil"
TOOL_ERASER = "eraser"
TOOL_ADD_KINK = "add_kink"
TOOL_ERASE_KINK = "erase_kink"
TOOL_MOVE_KINK = "move_kink"
TOOL_EDIT_KINK = "edit_kink"

# Layers the tools can change, and the tools each allows. The keys of the mask
# layers and of the kink layer are the result names of `bundle_edit`. A mask
# takes the eraser, and the pencil too where `bundle_edit.PAINTABLE` lets its
# pixels be set.
# ツールで変更できるレイヤーと、それぞれで使えるツール。マスクのレイヤーとキンクの
# レイヤーのキーは、`bundle_edit` の結果の名前と同じである。マスクには消しゴムが使え、
# `bundle_edit.PAINTABLE` が画素を立てることを許すものには鉛筆も使える。
LAYER_TOOLS = {
    LAYER_KINKS: (TOOL_ADD_KINK, TOOL_ERASE_KINK, TOOL_MOVE_KINK, TOOL_EDIT_KINK),
    **{name: ((TOOL_PENCIL, TOOL_ERASER) if settable else (TOOL_ERASER,))
       for name, settable in PAINTABLE.items()},
}
EDITABLE_LAYERS = tuple(LAYER_TOOLS)

# Brush diameter the pencil and the eraser start with, and its range, in
# image pixels.
# 鉛筆と消しゴムのブラシの直径の初期値と、その範囲（画像の画素）。
DEFAULT_BRUSH_PX = 5
BRUSH_RANGE_PX = (1, 99)

# Delay after the last change of the skeleton before its fibers are traced
# again, so a series of eraser strokes is followed by one tracing.
# スケルトンの最後の変更から、繊維を追跡し直すまでの待ち時間。消しゴムを続けて
# 使ったとき、追跡を 1 回で済ませるためのもの。
RETRACE_DELAY_MS = 600

# The stack a bundle opens with, topmost first: key, kind, color, shown,
# opacity. A height image is drawn in grey, so every overlay color stays
# readable on it; a mask is drawn in its color where it is set and left
# transparent elsewhere, so it never hides the layers below.
# バンドルを開いたときの重なり（上から順）。キー、種類、色、表示するか、不透明度。
# 高さ画像は灰色で描くので、重ねる色はどれもその上で読める。マスクは、立っている
# 画素をその色で描き、それ以外は透明にするので、下のレイヤーを隠さない。
DEFAULT_STACK = (
    (LAYER_KINKS, KIND_POINTS, "#FFE600", True, 1.0),
    (LAYER_CENTERLINE, KIND_LINES, "#3D7BFF", True, 1.0),
    (LAYER_SKELETON, KIND_MASK, "#EE66FF", True, 1.0),
    (LAYER_BINARIZED, KIND_MASK, "#44DD66", False, 0.45),
    (LAYER_FIBER_MASK, KIND_MASK, "#33BBEE", False, 0.45),
    (LAYER_CALIBRATED, KIND_HEIGHT, "#808080", True, 1.0),
    (LAYER_RAW, KIND_HEIGHT, "#808080", False, 1.0),
)

# ===== Display constants =====
FIGURE_FACE_COLOR = "#303030"
CENTERLINE_WIDTH_PT = 1.2
KINK_MARKER_PT = 6.0
SELECTED_ROW_COLOR = "#cfe6ff"
# Text color of the mark on a layer that was not computed again after what
# it is computed from changed.
# 計算の元になるものが変わってから計算し直していないレイヤーに付ける印の文字色。
STALE_COLOR = "#b45f06"
# The two arm ends of the chosen kink and the lines from the kink to them.
# 選んだキンクの 2 つの腕の端と、キンクからそこまでの線。
ARM_COLOR = "#FF2020"
ARM_END_MARKER_PT = 7.0
ARM_LINE_WIDTH_PT = 1.6
# One wheel notch scales the view by this factor about the pointer.
# ホイール 1 目盛りで、ポインタの位置を中心に表示をこの倍率だけ拡大・縮小する。
WHEEL_ZOOM_FACTOR = 1.25
# Delay before a requested redraw runs, so a dragged opacity slider redraws
# once per pause instead of once per pixel moved.
# 再描画の要求から実行までの待ち時間。不透明度のスライダーをドラッグしたとき、
# 動かした画素ごとではなく、止まるたびに 1 回だけ描き直すためのもの。
RENDER_DELAY_MS = 15
LAYER_PANE_WIDTH = 250
# How far from the pointer, in screen pixels, a click still reaches a fiber
# pixel or a mark, and the least that distance is in image pixels, so a click
# still reaches the pixel under it when the image is drawn very large.
# クリックが繊維の画素や印に届く、ポインタからの距離（画面のピクセル）と、その距離の
# 画像の画素での下限。画像を非常に大きく描いたときも、クリックがその下の画素に
# 届くようにするためのもの。
PICK_RADIUS_SCREEN_PX = 10.0
PICK_RADIUS_MIN_IMAGE_PX = 1.5


@dataclass
class Layer:
    """
    One layer of the stack and how it is drawn.
    重なりの中の 1 枚のレイヤーと、その描き方。

    Attributes
    ----------
    key
        One of the ``LAYER_*`` keys.
        ``LAYER_*`` キーのいずれか。
    kind
        One of the ``KIND_*`` keys.
        ``KIND_*`` キーのいずれか。
    color
        RGB in 0..1 a mask, the lines or the points are drawn in.
        マスク・線・点を描く色（0〜1 の RGB）。
    visible
        Whether the layer is drawn.
        レイヤーを描くかどうか。
    opacity
        Opacity from 0 (transparent) to 1 (opaque).
        不透明度。0（透明）から 1（不透明）。
    data
        What is drawn: a grey image in 0..1 for a height layer, a boolean
        array for a mask, a list of ``(N, 2)`` vertex arrays for lines, and a
        ``{"kinks": (x, y), "unjudged": (x, y)}`` dictionary for points.
        描く内容。高さのレイヤーは 0〜1 の灰色画像、マスクは真偽値の配列、線は
        ``(N, 2)`` の頂点配列のリスト、点は
        ``{"kinks": (x, y), "unjudged": (x, y)}`` の辞書。
    """

    key: str
    kind: str
    color: Tuple[float, float, float]
    visible: bool
    opacity: float
    data: Any = None

    @property
    def is_raster(self) -> bool:
        """
        Whether the layer is an image composited with its raster neighbours.
        隣り合う画像のレイヤーと合成して描く画像かどうか。
        """
        return self.kind in (KIND_HEIGHT, KIND_MASK)


def layer_label(key: str) -> str:
    """
    Return the translated name of a layer.
    レイヤーの翻訳済みの名前を返す。
    """
    labels = {
        LAYER_RAW: _("元データ"),
        LAYER_CALIBRATED: _("背景補正画像"),
        LAYER_FIBER_MASK: _("リッジマスク"),
        LAYER_BINARIZED: _("二値化画像"),
        LAYER_SKELETON: _("細線化画像"),
        LAYER_CENTERLINE: _("中心線"),
        LAYER_KINKS: _("キンク"),
    }
    return labels.get(key, key)


def height_to_grey(image: np.ndarray, mask: Optional[np.ndarray] = None) -> np.ndarray:
    """
    Scale a height image to grey levels over its automatic display range.
    高さ画像を、自動で決めた表示範囲にわたる灰色の濃淡へ変換する。

    Parameters
    ----------
    image
        Heights in nanometers.
        高さ（nm）。
    mask
        Skeleton of the same shape, which `ui_tools.compute_auto_vrange` reads
        the upper bound of the range from.
        同じ形状のスケルトン。`ui_tools.compute_auto_vrange` が範囲の上限を読む。

    Returns
    -------
    numpy.ndarray
        ``float32`` levels in 0..1; a non-finite height becomes 0.
        0〜1 の ``float32`` の濃淡。有限でない高さは 0 になる。
    """
    heights = np.asarray(image, dtype=np.float64)
    vmin, vmax = compute_auto_vrange(heights, mask)
    span = float(vmax) - float(vmin)
    if not np.isfinite(span) or span <= 0:
        span = 1.0
    grey = (heights - float(vmin)) / span
    return np.clip(np.nan_to_num(grey, nan=0.0, posinf=1.0, neginf=0.0),
                   0.0, 1.0).astype(np.float32)


def composite_rasters(
    rasters: Sequence[Layer], shape: Tuple[int, int],
    region: Optional[Tuple[int, int, int, int]] = None,
) -> np.ndarray:
    """
    Composite image layers into one RGBA image.
    画像のレイヤーを 1 枚の RGBA 画像へ合成する。

    Parameters
    ----------
    rasters
        Height and mask layers from the lowest up; each is drawn over the
        result so far with its `Layer.opacity`.
        高さとマスクのレイヤー。下から順。それぞれを、そこまでの結果の上へ
        `Layer.opacity` で重ねる。
    shape
        ``(rows, columns)`` of every layer.
        すべてのレイヤーの ``(行数, 列数)``。
    region
        ``(row_start, row_stop, column_start, column_stop)`` to composite
        only that part of the layers; the result then has the region's shape.
        A brush stroke changes a few pixels, and compositing them alone keeps
        painting from lagging behind the pointer.
        レイヤーのその部分だけを合成する場合の
        ``(row_start, row_stop, column_start, column_stop)``。結果の形状は、その
        領域の形状になる。ブラシのストロークが変えるのは数画素なので、そこだけを
        合成すれば、塗る操作がポインタに遅れない。

    Returns
    -------
    numpy.ndarray
        ``uint8`` array of shape ``(rows, columns, 4)`` with straight (not
        premultiplied) alpha. A pixel no layer covers is fully transparent,
        so whatever is drawn below the image shows through it.
        形状 ``(行数, 列数, 4)`` の ``uint8`` 配列。アルファは乗算済みではない。
        どのレイヤーも覆わない画素は完全に透明で、画像の下に描いたものが透ける。
    """
    window: Tuple[slice, slice] = (slice(None), slice(None))
    rows, columns = int(shape[0]), int(shape[1])
    if region is not None:
        window = (slice(region[0], region[1]), slice(region[2], region[3]))
        rows, columns = region[1] - region[0], region[3] - region[2]
    # Accumulated with premultiplied color, which makes "over" a plain blend.
    # `covered` is False until a layer covers every pixel; from then on the
    # result is opaque everywhere and its alpha need not be tracked.
    # 色は乗算済みで累積する。こうすると「上に重ねる」が単純な混合になる。
    # `covered` は、あるレイヤーが全画素を覆うまで False。それ以降は結果がどこも
    # 不透明なので、アルファを追う必要が無い。
    #
    # The three color planes are kept as separate 2D arrays: an operation
    # broadcast over a trailing axis of length 3 runs several times slower
    # than the same operation on three contiguous planes.
    # 3 つの色の面は、別々の 2 次元配列として持つ。長さ 3 の末尾の軸へ
    # ブロードキャストする演算は、連続した 3 枚の面に対する同じ演算より数倍遅い。
    planes = [np.zeros((rows, columns), dtype=np.float32) for _ in range(3)]
    out_alpha = np.zeros((rows, columns), dtype=np.float32)
    covered = False
    for layer in rasters:
        alpha = float(min(max(layer.opacity, 0.0), 1.0))
        if alpha <= 0.0 or layer.data is None:
            continue
        if layer.kind == KIND_HEIGHT:
            grey = np.asarray(layer.data[window], dtype=np.float32)
            if alpha >= 1.0:
                for plane in planes:
                    plane[...] = grey
                covered = True
                continue
            scaled = grey * np.float32(alpha)
            for plane in planes:
                plane *= np.float32(1.0 - alpha)
                plane += scaled
            if not covered:
                out_alpha *= np.float32(1.0 - alpha)
                out_alpha += np.float32(alpha)
        else:
            weight = np.asarray(layer.data[window], dtype=np.float32) * np.float32(alpha)
            keep = np.float32(1.0) - weight
            for plane, channel in zip(planes, layer.color):
                plane *= keep
                plane += weight * np.float32(channel)
            if not covered:
                out_alpha *= keep
                out_alpha += weight
    rgba = np.empty((rows, columns, 4), dtype=np.uint8)
    if covered:
        rgba[..., 3] = 255
    else:
        for plane in planes:
            np.divide(plane, out_alpha, out=plane, where=out_alpha > 0.0)
        rgba[..., 3] = np.clip(out_alpha * 255.0 + 0.5, 0.0, 255.0)
    for index, plane in enumerate(planes):
        plane *= 255.0
        plane += 0.5
        np.clip(plane, 0.0, 255.0, out=plane)
        rgba[..., index] = plane
    return rgba


def _columns(pixels: Sequence[Tuple[int, int]]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Split ``(x, y)`` pixels into an x array and a y array.
    ``(x, y)`` の画素の並びを、x の配列と y の配列に分ける。
    """
    array = np.array(pixels, dtype=np.int64).reshape(-1, 2)
    return array[:, 0], array[:, 1]


def kink_layer_data(
    editor: KinkEditor,
    moving_from: Optional[Tuple[int, int]] = None,
    moving_to: Optional[Tuple[int, int]] = None,
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Return what the kink layer draws for the marks of an editor.
    エディタの印について、キンクのレイヤーが描く内容を返す。

    Parameters
    ----------
    editor
        The kinks being edited.
        編集中のキンク。
    moving_from, moving_to
        While a kink is dragged, its pixel and the pixel under the pointer;
        the kink is drawn at the latter.
        キンクをドラッグしている間の、その画素とポインタの下の画素。キンクは後者に
        描く。

    Returns
    -------
    dict
        ``{"kinks": (x, y), "unjudged": (x, y)}`` as `Layer.data` holds it.
        `Layer.data` が持つ形の ``{"kinks": (x, y), "unjudged": (x, y)}``。
    """
    kinks = editor.kink_pixels()
    if moving_from is not None and moving_to is not None:
        kinks = [moving_to if pixel == moving_from else pixel for pixel in kinks]
    return {"kinks": _columns(kinks), "unjudged": _columns(editor.unjudged_pixels())}


def build_layers(session: EditSession) -> List[Layer]:
    """
    Build the layer stack of an opened bundle, topmost first.
    開いたバンドルのレイヤーの重なりを作る（上から順）。

    Parameters
    ----------
    session
        The opened bundle.
        開いたバンドル。

    Returns
    -------
    list of Layer
        `DEFAULT_STACK` without the layers the session has no data for: the
        raw image and the ridge mask when no raw image was found, the ridge
        mask alone for a background method that uses none.
        `DEFAULT_STACK` から、セッションにデータの無いレイヤーを除いたもの。生の
        画像が見つからなければ生の画像とリッジマスクを、マスクを使わない背景補正の
        方式ではリッジマスクだけを除く。
    """
    arrays = session.arrays
    skeleton = np.asarray(arrays["skeletonized"]).astype(bool)
    kinks = np.asarray(arrays["kp"])
    unjudged = np.asarray(arrays.get("up", np.zeros((2, 0), dtype=np.int64)))
    data: Dict[str, Any] = {
        LAYER_CALIBRATED: height_to_grey(arrays["calibrated"], skeleton),
        LAYER_BINARIZED: np.asarray(arrays["binarized"]).astype(bool),
        LAYER_SKELETON: skeleton,
        LAYER_CENTERLINE: [
            np.column_stack([x, y]) for x, y in session.centerlines if len(x) >= 2
        ],
        LAYER_KINKS: {
            "kinks": (kinks[0], kinks[1]),
            "unjudged": (unjudged[0], unjudged[1]),
        },
    }
    if session.raw_aligned is not None:
        data[LAYER_RAW] = height_to_grey(session.raw_aligned, skeleton)
    if session.fiber_mask is not None:
        data[LAYER_FIBER_MASK] = np.asarray(session.fiber_mask).astype(bool)
    return [
        Layer(key, kind, to_rgb(color), visible, opacity, data[key])
        for key, kind, color, visible, opacity in DEFAULT_STACK
        if key in data
    ]


def drop_slot(row_centers: Sequence[float], y: float) -> int:
    """
    Return the gap between layer rows a pointer height falls into.
    ポインタの高さが、レイヤーの行のどのすき間に当たるかを返す。

    Parameters
    ----------
    row_centers
        Vertical center of each row, top row first.
        各行の縦方向の中心。上の行から順。
    y
        Pointer height in the same coordinates.
        同じ座標でのポインタの高さ。

    Returns
    -------
    int
        Number of rows whose center lies above `y`: 0 is the gap above the
        first row, ``len(row_centers)`` the gap below the last.
        中心が `y` より上にある行の数。0 は最初の行の上のすき間、
        ``len(row_centers)`` は最後の行の下のすき間。
    """
    return sum(1 for center in row_centers if center < y)


def session_messages(session: EditSession) -> Tuple[List[str], List[str]]:
    """
    Describe what an opened bundle provides and what it lacks.
    開いたバンドルが何を持ち、何を持たないかを文章にする。

    Parameters
    ----------
    session
        The opened bundle.
        開いたバンドル。

    Returns
    -------
    tuple of list
        ``(notes, warnings)``: lines for the log, and lines the user has to
        see before reading the layers — a missing raw image, settings that
        cannot be used, a ridge mask that is not the analysis's own.
        ``(notes, warnings)``。ログに書く行と、レイヤーを読む前に利用者が見る
        べき行（生の画像が無い、設定が使えない、リッジマスクが解析時のものでない）。
    """
    notes: List[str] = []
    warnings: List[str] = []
    if not session.editable:
        notes.append(_(
            "このバンドルは形式 {version} のため、表示だけできます。編集して保存する"
            "には、Image Preprocessor で解析し直した形式 {current} のバンドルを"
            "開いてください。"
        ).format(version=session.format_version or "?", current=BUNDLE_FORMAT_VERSION))
    edits = session.meta.get(MANUAL_EDIT_KEY) or []
    if edits:
        notes.append(_(
            "このバンドルは手で編集されたものです（保存 {n} 回）。"
        ).format(n=len(edits)))

    raw = session.raw
    if raw.height is not None:
        if raw.source == RAW_FROM_BUNDLE:
            notes.append(_("元データ: バンドル内の {key}").format(key="original"))
        else:
            notes.append(_("元データ: {name}（バンドルと同じフォルダ）").format(
                name=raw.detail))
    else:
        reasons = {
            RAW_MISSING_NOT_RECORDED: _(
                "バンドルに元データのファイル名が記録されていません。"),
            RAW_MISSING_NOT_FOUND: _(
                "元データ {name} が、バンドルと同じフォルダにありません。"),
            RAW_MISSING_CHANGED: _(
                "バンドルと同じフォルダの {name} は、解析時の元データと内容が異なります。"),
            RAW_MISSING_UNREADABLE: _("元データを読み込めませんでした: {name}"),
            RAW_MISSING_SHAPE: _(
                "元データ {name} の大きさが、バンドルの画像と合いません。"),
        }
        reason = reasons.get(raw.problem or "", "").format(name=raw.detail)
        # An edited bundle stores its ridge mask, which is then shown without
        # the raw image.
        # 編集したバンドルはリッジマスクを保存しており、その場合は生の画像が
        # 無くても表示できる。
        consequence = (
            _("元データとリッジマスクは表示できません。")
            if session.fiber_mask is None else
            _("元データは表示できず、背景補正の再実行もできません。"))
        warnings.append(reason + "\n" + consequence)
        return notes, warnings

    if session.params is None:
        warnings.append(_(
            "バンドルの解析条件を使えないため、リッジマスクは表示できません: {reason}"
        ).format(reason=session.params_problem))
        return notes, warnings

    method = session.params.bg_method
    background = session.background
    stale_when_saved = set((edits[-1].get("stale_layers") or ()) if edits else ())
    if background is not None and not background.reproduces:
        if LAYER_CALIBRATED in stale_when_saved:
            # Saved with its heights marked stale: they are known not to
            # follow from the mask and the settings the bundle stores.
            # 高さが古いと記録して保存されたバンドルである。その高さが、バンドルの
            # 保存するマスクと設定から導かれたものでないことは、分かっている。
            notes.append(_(
                "背景補正画像は、保存時に「古い」と記録されています。保存されている"
                "リッジマスクと設定から計算し直したものではありません。"))
        elif background.max_difference_nm is None:
            warnings.append(_(
                "記録された解析条件で背景補正をやり直しましたが、保存されている"
                "背景補正画像と大きさが一致しません。"))
        elif method in MASK_BG_METHODS:
            warnings.append(_(
                "記録された解析条件で背景補正をやり直しましたが、保存されている"
                "背景補正画像と一致しません（最大の差 {difference} {unit}）。"
                "表示するリッジマスクは、解析時のものと異なる可能性があります。"
            ).format(difference=f"{background.max_difference_nm:.3g}", unit="nm"))
        else:
            warnings.append(_(
                "記録された解析条件で背景補正をやり直しましたが、保存されている"
                "背景補正画像と一致しません（最大の差 {difference} {unit}）。"
            ).format(difference=f"{background.max_difference_nm:.3g}", unit="nm"))
    if method not in MASK_BG_METHODS:
        notes.append(_(
            "背景補正の方式が {method} のため、リッジマスクはありません。"
        ).format(method=method))
    return notes, warnings


def stage_label(stage: str) -> str:
    """
    Return the translated name of a stage that can be run again.
    再実行できる段の、翻訳済みの名前を返す。
    """
    labels = {
        STAGE_MASK: _("リッジマスクの検出"),
        STAGE_BACKGROUND: _("背景補正"),
        STAGE_BINARIZE: _("二値化"),
        STAGE_SKELETONIZE: _("細線化"),
        STAGE_KINKS: _("キンク検出"),
    }
    return labels.get(stage, stage)


def stage_fields(stage: str) -> List[Tuple[str, str, Tuple[str, ...]]]:
    """
    Return the settings a stage's dialog offers.
    ある段の設定ダイアログに並べる設定を返す。

    Parameters
    ----------
    stage
        `STAGE_BACKGROUND` or `STAGE_BINARIZE`.
        `STAGE_BACKGROUND` または `STAGE_BINARIZE`。

    Returns
    -------
    list of tuple
        ``(field, description, choices)`` per setting: the `ProcParams` field
        name, its translated description, and the values to choose from for a
        field that takes one of a few (empty otherwise).
        設定ごとの ``(field, description, choices)``。`ProcParams` のフィールド名、
        翻訳済みの説明、いくつかの値から 1 つを取るフィールドの選択肢（そうで
        なければ空）。

    Notes
    -----
    The descriptions are the ones GUI01's settings dialog shows for the same
    fields, word for word, so both windows explain a setting alike and the
    translations are shared. They are built when called, so they follow the
    language in use.
    説明は、GUI01 の設定ダイアログが同じフィールドに表示するものと一字一句同じに
    してある。2 つのウィンドウが同じ設定を同じように説明し、翻訳も共有するためで
    ある。呼び出し時に作るので、使用中の言語に従う。
    """
    if stage == STAGE_BACKGROUND:
        return [
            ("bg_method", _("背景補正の方式"), ("trendfill", "tophat", "spline1d")),
            ("tophat_se_size",
             _("[tophat時のみ] 構造要素直径") + " (px)。"
             + _("最大ファイバー幅の2〜3倍。奇数(偶数は+1)"), ()),
            ("spline1d_axis",
             _("[spline1d時のみ] 補間の向き。'x'=各行を横に補間し、画像の行が走査ラインのときは走査ラインごとの上下のずれ(横縞)も除去。'y'=各列を縦に補間し、横縞は除去しない"),
             ("x", "y")),
            ("spline1d_degree",
             _("[spline1d時のみ] 行/列スプライン order。実用範囲1〜3 (2=旧pandas互換)。点数不足の行は線形に自動フォールバック"), ()),
            ("threshold_factor",
             _("[trendfill, spline1d時] 背景範囲（中心±sigma*係数）を決める係数"), ()),
            ("fiber_detect_factor",
             _("[trendfill, spline1d時] [1,0,-1]の急変を繊維として除外する距離しきい値") + " (px)", ()),
            ("noise_detect_factor",
             _("[trendfill, spline1d時] [1,-1]の急変が一定以上離れている場合に構造とみなすしきい値") + " (px)", ()),
            ("savgol_window",
             _("[trendfill, tophat, spline1d時] Savitzky-Golayフィルタの窓幅（平滑化範囲）。spline1d ではライン端に保持する水準の平均本数も兼ねる") + " (px)", ()),
            ("savgol_polyorder",
             _("[trendfill, tophat, spline1d時] Savitzky-Golayフィルタの多項式次数"), ()),
            ("apply_median", _("中央値フィルタを最後にかける（点ノイズに強い）"), ()),
            ("mask_dilation",
             _("[trendfill, spline1d時] 繊維マスクを膨張させる画素数（0でdilationなし）"), ()),
            ("min_mask_component_area",
             _("[trendfill, spline1d時] dilation前にマスクから除外する連結成分の最小面積") + " (px^2)。"
             + _("1でフィルタ無効"), ()),
        ]
    return [
        ("wsize_localbin", _("局所しきい値の計算に使う窓サイズ") + " (px)", ()),
        ("global_threshold", _("全体一律の2値化しきい値") + " (nm)", ()),
        ("area_min", _("小さい連結成分を消す面積しきい値") + " (px^2)", ()),
        ("area_min_connecting", _("つながり成分を除くときの面積しきい値") + " (px^2)", ()),
        ("apply_no_connecting", _("つながり除去を実行するかどうか"), ()),
        ("h_length", _("線分検出で線分とみなす最小長さ") + " (px)", ()),
        ("h_sratio", _("線っぽさ") + " (s_ratio) " + _("のしきい値"), ()),
        ("low_threshold", _("高さが低い成分を消すしきい値") + " (nm)", ()),
        ("ridge_recovery",
         _("しきい値で拾えなかった繊維をリッジフィルタで検出して追加する。"
           "1画像あたり数秒〜30秒遅くなる"), ()),
        ("ridge_min_length_nm",
         _("[ridge_recovery時] 追加するセグメントの最小長") + " (nm)", ()),
        ("ridge_min_width_nm",
         _("[ridge_recovery時] リッジフィルタが探索する繊維半幅の下限") + " (nm)", ()),
        ("ridge_max_width_nm",
         _("[ridge_recovery時] リッジフィルタが探索する繊維半幅の上限") + " (nm)", ()),
    ]


class App(tk.Tk, LogMixin):
    """
    Window showing one bundle as a stack of layers and editing its results.
    1 つのバンドルをレイヤーの重なりとして表示し、その結果を編集するウィンドウ。

    Attributes
    ----------
    session
        The opened bundle, or ``None`` before one is opened.
        開いたバンドル。開く前は ``None``。
    layers
        The layer stack, topmost first.
        レイヤーの重なり（上から順）。
    state
        Everything of the bundle that can be changed, with its undo history,
        or ``None`` when the bundle cannot be edited.
        バンドルのうち変更できるものすべてと、その元に戻す履歴。バンドルを編集
        できないときは ``None``。
    editor
        The kinks of `state`, or ``None`` when the bundle cannot be edited.
        `state` のキンク。バンドルを編集できないときは ``None``。
    active_layer
        Key of the layer the tools act on, or ``None``.
        ツールが働くレイヤーのキー。無ければ ``None``。
    ui_queue
        Messages from the loading thread to the Tk main loop.
        読み込みスレッドから Tk メインループへのメッセージ。
    """

    def __init__(self) -> None:
        """
        Build the window.
        ウィンドウを作成する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])
        setup_matplotlib_style(font_size=12)
        self._clam_bg = setup_ttk_theme(self)
        apply_window_size(self, 1280, 860)

        self.session: Optional[EditSession] = None
        self.layers: List[Layer] = []
        self.state: Optional[BundleEditor] = None
        self.editor: Optional[KinkEditor] = None
        self.active_layer: Optional[str] = None
        # Set while a stage runs in the worker thread; nothing may change the
        # state meanwhile, so every editing control is switched off.
        # 段がワーカースレッドで動いている間だけ立てる。その間は状態を変更しては
        # ならないので、編集の操作はすべて無効にする。
        self._busy = False
        # Set while the fibers are traced again in a worker thread; painting
        # goes on meanwhile, on copies the worker does not read.
        # 繊維をワーカースレッドで追跡し直している間だけ立てる。その間も、ワーカーが
        # 読まない複製の上で、塗る操作は続けられる。
        self._retracing = False
        self._retrace_after: Optional[str] = None
        # The heights the grey levels of the corrected image were computed
        # from, and those levels.
        # 補正画像の灰色の濃淡を計算した元の高さと、その濃淡。
        self._grey_source: Optional[np.ndarray] = None
        self._grey: Optional[np.ndarray] = None
        # The image artists as last drawn, each with the layers composited
        # into it and its RGBA array, so a brush stroke can redraw the few
        # pixels it changed.
        # 最後に描いた画像の描画要素。それぞれ、合成したレイヤーと RGBA 配列を伴う。
        # ブラシのストロークが、変えた数画素だけを描き直せるようにする。
        self._raster_groups: List[Tuple[Any, List[Layer], np.ndarray]] = []
        # The pointer position a brush stroke last painted to.
        # ブラシのストロークが最後に塗った、ポインタの位置。
        self._stroke_at: Optional[Tuple[float, float]] = None
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        # Raised for every bundle opened, so a bundle still loading when the
        # next one is chosen is dropped when it arrives.
        # バンドルを開くたびに上げる。次のバンドルを選んだ時点でまだ読み込み中
        # だったバンドルは、届いても捨てる。
        self._generation = 0
        self._loading = False
        self._last_dir: Optional[str] = None
        self._shape: Tuple[int, int] = (0, 0)
        self._artists: List[Any] = []
        # The two artists of the kink layer as last drawn (unjudged, kinks),
        # so an edit can move the marks without compositing the images again.
        # 最後に描いたキンクのレイヤーの 2 つの描画要素（判定しなかった折れ、キンク）。
        # 編集のたびに画像を合成し直さず、印だけを動かせるようにする。
        self._kink_artists: Optional[Tuple[Any, Any]] = None
        self._rows: Dict[str, "LayerRow"] = {}
        # Ids of the scheduled redraw and poll, cancelled when the window closes.
        # 予約済みの再描画とポーリングの id。ウィンドウを閉じるときに取り消す。
        self._render_job: Optional[str] = None
        self._poll_job: Optional[str] = None
        # The layer row being dragged and the gap it would be dropped into.
        # ドラッグ中のレイヤーの行と、離したときに入るすき間。
        self._drag_key: Optional[str] = None
        self._drag_slot: Optional[int] = None
        # A view drag in progress: pointer position, the inverse transform and
        # the axis limits at the press.
        # 表示を動かすドラッグの途中の状態。押した時点のポインタ位置、逆変換、軸の範囲。
        self._pan: Optional[tuple] = None
        # A kink being dragged: its pixel and the fiber pixel under the pointer.
        # ドラッグ中のキンク。その画素と、ポインタの下の繊維の画素。
        self._move_source: Optional[Tuple[int, int]] = None
        self._move_target: Optional[Tuple[int, int]] = None
        # The kink chosen with the kink-editing tool, whose arm ends are drawn.
        # キンク編集のツールで選んだキンク。その腕の端を描く。
        self._selected_kink: Optional[Tuple[int, int]] = None
        # An arm end being dragged: which end, and the pixel under the pointer.
        # ドラッグ中の腕の端。どちらの端かと、ポインタの下の画素。
        self._arm_drag: Optional[Tuple[int, Tuple[int, int]]] = None
        self._arm_drag_from: Optional[Tuple[int, int]] = None
        self._arm_artists: List[Any] = []

        self._build_widgets()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-z>", lambda _event: self.on_undo())
        self.bind("<Control-y>", lambda _event: self.on_redo())
        # Ctrl+S saves over an edited bundle and asks for a name otherwise, as
        # Save does for a document that has never been saved. Caps Lock swaps
        # the case Tk reports ("S" for Ctrl+S, "s" for Ctrl+Shift+S), so both
        # cases are bound; a binding naming Shift is the more specific one and
        # is chosen whenever Shift is held.
        # Ctrl+S は、編集済みのバンドルには上書き保存し、それ以外では名前を尋ねる。
        # 一度も保存していない文書に対する一般的な「上書き保存」と同じ動きである。
        # Caps Lock が有効だと Tk が報告する大文字・小文字が入れ替わる（Ctrl+S が
        # "S"、Ctrl+Shift+S が "s"）ため、両方に割り当てる。Shift を名指しした
        # 割り当てのほうが限定的なので、Shift を押している間はそちらが選ばれる。
        self.bind("<Control-s>", lambda _event: self.on_save_shortcut())
        self.bind("<Control-S>", lambda _event: self.on_save_shortcut())
        self.bind("<Control-Shift-S>", lambda _event: self.on_save_as_shortcut())
        self.bind("<Control-Shift-s>", lambda _event: self.on_save_as_shortcut())
        self._update_controls()
        self._log(_("バンドルを開いてください。"))

    # ----- Widgets -----

    def _build_widgets(self) -> None:
        """
        Build the top row, the image pane, the layer pane and the log.
        上段の操作欄、画像ペイン、レイヤーペイン、ログを作る。
        """
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))
        self.open_button = ttk.Button(
            top, text=_("バンドルを開く…"), command=self.on_open)
        self.open_button.pack(side=tk.LEFT)
        self.name_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.name_var).pack(side=tk.LEFT, padx=(10, 0))
        self.save_button = ttk.Button(
            top, text=_("名前を付けて保存…"), command=self.on_save)
        self.save_button.pack(side=tk.RIGHT)
        ToolTip(self.save_button, _(
            "編集した結果を、名前を付けてバンドルとして保存します（Ctrl+Shift+S）。\n"
            "保存したバンドルには、手で編集したことが記録されます。\n"
            "解析で書き出したバンドルには上書きしません。"
        ))
        self.overwrite_button = ttk.Button(
            top, text=_("上書き保存"), command=self.on_overwrite)
        self.overwrite_button.pack(side=tk.RIGHT, padx=(0, 4))
        ToolTip(self.overwrite_button, _(
            "開いている編集済みのバンドルに、編集を上書きして保存します（Ctrl+S）。\n"
            "解析で書き出したバンドルを開いているとき、または保存していない編集が"
            "無いときは押せません。解析で書き出したバンドルを編集しているときの"
            "Ctrl+S は「名前を付けて保存…」を開きます。"
        ))
        self.editor_name_var = tk.StringVar(value="")
        self.editor_entry = ttk.Entry(top, textvariable=self.editor_name_var, width=14)
        self.editor_entry.pack(side=tk.RIGHT, padx=(4, 8))
        ToolTip(self.editor_entry, _(
            "保存するバンドルに、編集した人の名前として記録します。\n"
            "空欄なら記録しません。"
        ))
        ttk.Label(top, text=_("編集者（任意）")).pack(side=tk.RIGHT)

        frm_log = ttk.LabelFrame(self, text=_("ログ"))
        frm_log.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(2, 8))
        frm_log_buttons = ttk.Frame(frm_log)
        frm_log_buttons.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(frm_log_buttons, text=_("ログを保存"),
                   command=self.on_save_log).pack(side=tk.LEFT)
        log_body = ttk.Frame(frm_log)
        log_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.log_text, _log_sb = create_scrolled_text(
            log_body, height=5, wrap=tk.WORD, state="disabled",
        )

        body = ttk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=4)

        frm_layers = ttk.LabelFrame(body, text=_("レイヤー"), width=LAYER_PANE_WIDTH)
        frm_layers.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        frm_layers.pack_propagate(False)
        self.layer_rows_frame = ttk.Frame(frm_layers)
        self.layer_rows_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)
        # Shows where a dragged row would be dropped.
        # ドラッグ中の行を離したときに入る位置を示す線。
        self._drop_line = tk.Frame(self.layer_rows_frame, height=2, bg="#1a73e8")
        ttk.Label(
            frm_layers, wraplength=LAYER_PANE_WIDTH - 24, justify=tk.LEFT,
            text=_(
                "名前をクリックすると、編集するレイヤーを選べます"
                "（編集できるのは、キンク・細線化画像・二値化画像・リッジマスクです）。"
                "ドラッグすると重ね順が変わります。"
                "「古い」と付いたレイヤーは、元になるレイヤーが変わったあと"
                "計算し直していません。"),
        ).pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=6)

        frm_image = ttk.Frame(body)
        frm_image.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tool_row = ttk.Frame(frm_image)
        tool_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        ttk.Label(tool_row, text=_("ツール")).pack(side=tk.LEFT, padx=(0, 6))
        self.tool_var = tk.StringVar(value=TOOL_NONE)
        self.tool_buttons: Dict[str, ttk.Radiobutton] = {}
        tools = (
            (TOOL_NONE, _("表示のみ"),
             _("画像をクリックしても、何も変更しません。")),
            (TOOL_PENCIL, _("鉛筆"), _(
                "ドラッグした画素を、選んだマスクに加えます。\n"
                "リッジマスクと二値化画像で使えます。細線化画像には使えません"
                "（線の太さを 1 画素に保つためです）。")),
            (TOOL_ERASER, _("消しゴム"), _(
                "ドラッグした画素を、選んだマスクから除きます。\n"
                "リッジマスク・二値化画像・細線化画像で使えます。")),
            (TOOL_ADD_KINK, _("キンク追加"), _(
                "繊維の上をクリックすると、最も近い細線化画素にキンクを置きます。\n"
                "角度を決める 2 つの端点は、キンクの両側に自動で置かれます。\n"
                "端点は「キンクの編集」で動かせます。")),
            (TOOL_ERASE_KINK, _("キンク消去"), _(
                "キンク、または判定しなかった折れ（中抜きの印）をクリックすると消します。")),
            (TOOL_MOVE_KINK, _("キンク移動"), _(
                "キンクをドラッグすると、繊維の細線化画素の上を動かせます。\n"
                "動かしたキンクの端点は、自動で置き直されます。")),
            (TOOL_EDIT_KINK, _("キンクの編集"), _(
                "キンクをクリックすると、その角度を決める 2 つの端点が赤で表示されます。\n"
                "端点をドラッグすると、繊維の細線化画素の上を動かせます。\n"
                "角度は、赤い 2 本の線（腕）のなす角です。各腕は、キンクから見かけ幅の"
                "半分だけ離れた点から端点までで、中心線の点で測ります。\n"
                "解析が見つけたキンクは、端点を動かすまで解析の角度を保ちます"
                "（そのとき端点は破線で表示されます）。")),
        )
        for key, text, tip in tools:
            button = ttk.Radiobutton(
                tool_row, text=text, value=key, variable=self.tool_var,
                command=self._on_tool_chosen)
            button.pack(side=tk.LEFT, padx=(0, 6))
            ToolTip(button, tip)
            self.tool_buttons[key] = button
        self.undo_button = ttk.Button(
            tool_row, text=_("元に戻す"), command=self.on_undo)
        self.undo_button.pack(side=tk.LEFT, padx=(12, 2))
        self.redo_button = ttk.Button(
            tool_row, text=_("やり直す"), command=self.on_redo)
        self.redo_button.pack(side=tk.LEFT)

        # The brush and the stages on a second row: with the tools they do
        # not fit one row in the longer translations.
        # ブラシと段の再実行は 2 行目に置く。ツールと合わせると、長い翻訳では 1 行に
        # 収まらないためである。
        stage_row = ttk.Frame(frm_image)
        stage_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        ttk.Label(stage_row, text=_("ブラシの太さ") + " (px)").pack(side=tk.LEFT)
        self.brush_var = tk.StringVar(value=str(DEFAULT_BRUSH_PX))
        self.brush_spin = ttk.Spinbox(
            stage_row, from_=BRUSH_RANGE_PX[0], to=BRUSH_RANGE_PX[1], width=4,
            textvariable=self.brush_var)
        self.brush_spin.pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(stage_row, text=_("再実行")).pack(side=tk.LEFT, padx=(0, 6))
        self.stage_buttons: Dict[str, ttk.Button] = {}
        self.settings_buttons: Dict[str, ttk.Button] = {}
        stage_tips = {
            STAGE_MASK: _(
                "現在の設定で、元データからリッジマスクを検出し直します。\n"
                "手で直したリッジマスクは、検出結果で置き換わります。"),
            STAGE_BACKGROUND: _(
                "現在のリッジマスクと設定で、元データから背景補正をやり直します。\n"
                "方式が tophat のときは、マスクを使わずに実行します。"),
            STAGE_BINARIZE: _("現在の背景補正画像と設定から、二値化をやり直します。"),
            STAGE_SKELETONIZE: _("現在の二値化画像から、細線化をやり直します。"),
            STAGE_KINKS: _(
                "現在の細線化画像と背景補正画像から、キンクを検出し直します。\n"
                "手で置いたキンクは、検出結果で置き換わります。"),
        }
        for stage in (STAGE_MASK, STAGE_BACKGROUND, STAGE_BINARIZE,
                      STAGE_SKELETONIZE, STAGE_KINKS):
            button = ttk.Button(
                stage_row, text=stage_label(stage),
                command=lambda chosen=stage: self.on_run_stage(chosen))
            button.pack(side=tk.LEFT, padx=(0, 2))
            ToolTip(button, stage_tips[stage])
            self.stage_buttons[stage] = button
            if stage in (STAGE_BACKGROUND, STAGE_BINARIZE):
                # A negative width is a minimum: the button stays narrow for a
                # short label and grows for a longer translation.
                settings = ttk.Button(
                    stage_row, text=_("設定…"), width=-6,
                    command=lambda chosen=stage: self.on_stage_settings(chosen))
                settings.pack(side=tk.LEFT, padx=(0, 8))
                ToolTip(settings, _("{stage} の設定を変更します。").format(
                    stage=stage_label(stage)))
                self.settings_buttons[stage] = settings
        # On a row of its own: the tools already fill the row above in the
        # longer translations.
        # 専用の行に置く。上の行は、長い翻訳ではツールだけで埋まるためである。
        self.status_var = tk.StringVar(value="")
        ttk.Label(frm_image, textvariable=self.status_var, anchor=tk.W).pack(
            side=tk.TOP, fill=tk.X, pady=(0, 2))

        view_row = ttk.Frame(frm_image)
        view_row.pack(side=tk.TOP, fill=tk.X)

        self.fig = Figure(figsize=(7, 7), dpi=100, facecolor=FIGURE_FACE_COLOR)
        self.ax = self.fig.add_axes((0.0, 0.0, 1.0, 1.0))
        self.ax.set_axis_off()
        self.ax.format_coord = self._format_coord
        self.canvas = FigureCanvasTkAgg(self.fig, master=frm_image)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

        # The caller's own button is packed before the toolbar frame, whose
        # coordinate readout grows while the pointer is over the image.
        # 独自のボタンは、ツールバーのフレームより先に置く。ツールバーの座標表示は、
        # ポインタが画像の上にある間に横へ伸びるためである。
        self.fit_button = ttk.Button(
            view_row, text=_("全体を表示"), command=self.on_fit_view)
        self.fit_button.pack(side=tk.RIGHT)
        ToolTip(self.fit_button, _(
            "画像全体が見える表示に戻します。\n"
            "拡大・縮小はマウスホイール、またはツールバーの Zoom で行えます。\n"
            "右ボタンまたは中ボタンのドラッグで、表示を動かせます。"
        ))
        toolbar_frame, self._toolbar = build_pan_zoom_toolbar(
            view_row, self.canvas, clam_bg=self._clam_bg)
        toolbar_frame.pack(side=tk.LEFT)

    def _format_coord(self, x: float, y: float) -> str:
        """
        Format the pointer position as the pixel under it and its height.
        ポインタの位置を、その下の画素とその高さとして文字列にする。

        The height is the background-corrected one the bundle stores, which
        every measurement reads, whichever layers are shown.
        高さは、バンドルが保存する背景補正後の値である。表示しているレイヤーに
        よらず、すべての計測が読む値を示す。
        """
        column, row = int(round(x)), int(round(y))
        text = f"x={column}, y={row}"
        if self.session is not None:
            heights = self.session.arrays["calibrated"]
            if 0 <= row < heights.shape[0] and 0 <= column < heights.shape[1]:
                text += f", z={float(heights[row, column]):.2f} nm"
        return text

    def _update_controls(self) -> None:
        """
        Enable the controls that apply to the current state.
        現在の状態で使える操作だけを有効にする。
        """
        def state(enabled: bool) -> str:
            return tk.NORMAL if enabled else tk.DISABLED

        current = self.state
        free = current is not None and not self._busy and not self._loading
        self.open_button.configure(state=state(not self._loading and not self._busy))
        self.fit_button.configure(state=state(self.session is not None))
        allowed = LAYER_TOOLS.get(self.active_layer or "", ()) if free else ()
        for key, button in self.tool_buttons.items():
            usable = key in allowed or (key == TOOL_NONE and bool(allowed))
            button.configure(state=state(usable))
        if self.tool_var.get() not in allowed:
            self.tool_var.set(TOOL_NONE)
        painting = any(tool in allowed for tool in (TOOL_PENCIL, TOOL_ERASER))
        self.brush_spin.configure(state=state(painting))
        self.undo_button.configure(state=state(free and current.can_undo))
        self.redo_button.configure(state=state(free and current.can_redo))
        for stage, button in self.stage_buttons.items():
            button.configure(state=state(free and current.can_run(stage)))
        for button in self.settings_buttons.values():
            button.configure(state=state(free))
        self.save_button.configure(state=state(self._can_save_as()))
        self.overwrite_button.configure(state=state(self._can_overwrite()))
        self.editor_entry.configure(state=state(current is not None))

    # ----- Opening a bundle -----

    def _discard_allowed(self) -> bool:
        """
        Ask before unsaved edits are thrown away; ``True`` when they may be.
        保存していない編集を捨てる前に確認する。捨ててよければ ``True``。
        """
        if self.state is None or not self.state.modified:
            return True
        return bool(messagebox.askyesno(
            _("確認"), _("保存していない編集があります。破棄しますか？"),
            parent=self))

    def on_open(self) -> None:
        """
        Ask for a bundle and open it.
        バンドルを選ばせて開く。
        """
        if not self._discard_allowed():
            return
        path = filedialog.askopenfilename(
            parent=self, title=_(".b2z バンドルを選択"),
            initialdir=self._last_dir,
            filetypes=[("b2z bundle", "*" + BUNDLE_EXT), ("All files", "*.*")])
        if path:
            self.open_bundle(path)

    def open_bundle(self, path: str) -> None:
        """
        Open a bundle in a worker thread and show it when it is read.
        バンドルをワーカースレッドで開き、読み終えたら表示する。

        Parameters
        ----------
        path
            Path to a ``.b2z`` bundle.
            ``.b2z`` バンドルのパス。
        """
        self._last_dir = os.path.dirname(os.path.abspath(path))
        self._generation += 1
        self._loading = True
        self._log(_("読み込み中: {name}").format(name=os.path.basename(path)))
        self._update_controls()
        threading.Thread(
            target=self._load_job, args=(self._generation, path), daemon=True,
        ).start()
        if self._poll_job is None:
            self._poll_job = self.after(50, self._poll_ui_queue)

    def _load_job(self, generation: int, path: str) -> None:
        """
        Read a bundle and prepare its layers; runs in the worker thread.
        バンドルを読み、レイヤーを用意する。ワーカースレッドで動く。

        It never touches Tk widgets; every result goes through `ui_queue`.
        Tk のウィジェットには触れない。結果はすべて `ui_queue` を通す。
        """
        try:
            session = load_edit_session(
                path, on_step=lambda key: self.ui_queue.put(("step", (generation, key))))
            layers = build_layers(session)
            state = BundleEditor(session) if session.editable else None
        except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
            self.ui_queue.put(
                ("failed", (generation, path, f"{type(exc).__name__}: {exc}")))
        else:
            self.ui_queue.put(("loaded", (generation, session, layers, state)))

    def _stage_job(self, generation: int, stage: str) -> None:
        """
        Run a stage on the current state; runs in the worker thread.
        現在の状態に対して段を実行する。ワーカースレッドで動く。

        It only reads the state (`BundleEditor.compute`); the result is taken
        over in the main thread.
        状態を読むだけである（`BundleEditor.compute`）。結果はメインスレッドで
        取り込む。
        """
        try:
            computed = self.state.compute(stage)
        except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
            self.ui_queue.put(
                ("stage_failed", (generation, stage, f"{type(exc).__name__}: {exc}")))
        else:
            self.ui_queue.put(("stage_done", (generation, stage, computed)))

    def _poll_ui_queue(self) -> None:
        """
        Apply queued worker results and keep polling while a bundle loads.
        キューのワーカー結果を反映し、バンドルの読み込み中はポーリングを続ける。
        """
        self._poll_job = None
        steps = {
            "read": _("バンドルを読み込んでいます…"),
            "raw": _("元データを探しています…"),
            "background": _("背景補正をやり直しています…"),
            "centerline": _("中心線を求めています…"),
        }

        def on_step(payload) -> None:
            generation, key = payload
            if generation == self._generation:
                self.status_var.set(steps.get(key, ""))

        def on_loaded(payload) -> None:
            generation, session, layers, state = payload
            if generation != self._generation:
                return
            self._loading = False
            self._show_session(session, layers, state)

        def on_stage_done(payload) -> None:
            generation, stage, computed = payload
            if generation != self._generation or self.state is None:
                return
            self._busy = False
            self.state.apply(stage, computed)
            self._log(_("{stage} を再実行しました。").format(stage=stage_label(stage)))
            self._after_state_change()

        def on_retraced(payload) -> None:
            generation, revision, fibers = payload
            if generation != self._generation or self.state is None:
                return
            self._retracing = False
            # Fibers of a skeleton that has changed since are dropped; the
            # change scheduled another tracing.
            # その後に変わったスケルトンの繊維は捨てる。その変更が、次の追跡を
            # 予約している。
            if revision != self.state.skeleton_revision:
                self._schedule_retrace()
                return
            self.state.set_fibers(fibers)
            off_track = len(self.state.kinks.off_track)
            if off_track:
                self._log(_(
                    "{n} 個のキンクは、追跡した繊維の画素の上にありません。"
                    "これらは消去だけできます。"
                ).format(n=off_track))
            self._after_state_change()

        def on_retrace_failed(payload) -> None:
            generation, reason = payload
            if generation != self._generation:
                return
            self._retracing = False
            self.status_var.set("")
            self._log(_("繊維を追跡できませんでした: {reason}").format(reason=reason))

        def on_stage_failed(payload) -> None:
            generation, stage, reason = payload
            if generation != self._generation:
                return
            self._busy = False
            self.status_var.set("")
            self._log(_("{stage} を実行できませんでした: {reason}").format(
                stage=stage_label(stage), reason=reason))
            messagebox.showerror(
                _("実行エラー"),
                _("{stage} を実行できませんでした:\n{e}").format(
                    stage=stage_label(stage), e=reason),
                parent=self)
            self._update_controls()

        def on_failed(payload) -> None:
            generation, path, reason = payload
            if generation != self._generation:
                return
            self._loading = False
            self.status_var.set("")
            self._log(_("{name}: 読み込めませんでした ({reason})").format(
                name=os.path.basename(path), reason=reason))
            messagebox.showerror(
                _("読み込みエラー"),
                _("バンドルを読み込めませんでした:\n{e}").format(e=reason),
                parent=self)

        drain_ui_queue(self.ui_queue, {
            "step": on_step, "loaded": on_loaded, "failed": on_failed,
            "stage_done": on_stage_done, "stage_failed": on_stage_failed,
            "retraced": on_retraced, "retrace_failed": on_retrace_failed,
        })
        self._update_controls()
        if self._loading or self._busy or self._retracing:
            self._poll_job = self.after(50, self._poll_ui_queue)

    def _start_job(self, target, *args) -> None:
        """
        Run a job in a worker thread and poll for its result.
        ジョブをワーカースレッドで実行し、その結果をポーリングする。

        Editing is switched off until the result is taken over, because the
        job reads the state the whole time it runs.
        結果を取り込むまで、編集は無効にする。ジョブは、動いている間ずっと状態を
        読むためである。
        """
        self._busy = True
        self._update_controls()
        threading.Thread(
            target=target, args=(self._generation, *args), daemon=True).start()
        if self._poll_job is None:
            self._poll_job = self.after(50, self._poll_ui_queue)

    def _show_session(self, session: EditSession, layers: List[Layer],
                      state: Optional[BundleEditor]) -> None:
        """
        Show an opened bundle and report what it lacks.
        開いたバンドルを表示し、欠けているものを伝える。
        """
        self.session = session
        self.layers = layers
        self.state = state
        editor = self.editor = None if state is None else state.kinks
        self._busy = False
        if self._retrace_after is not None:
            self.after_cancel(self._retrace_after)
            self._retrace_after = None
        self.active_layer = None
        self.tool_var.set(TOOL_NONE)
        self._move_source = self._move_target = None
        self._selected_kink = None
        self._arm_drag = None
        self._pan = None
        self._shape = tuple(np.asarray(session.arrays["calibrated"]).shape)
        name = os.path.basename(session.bundle_path)
        self.name_var.set(name)
        self.status_var.set("")

        rows, columns = self._shape
        self.ax.set_aspect(session.pixel_aspect)
        self.ax.set_autoscale_on(False)
        self.on_fit_view()
        self._grey_source = None
        self._bind_layers()
        self._rebuild_layer_rows()
        self._render()

        kinks = np.asarray(session.arrays["kp"]).shape[1]
        self._log(_(
            "読み込み完了: {name}（{columns} × {rows} 画素、繊維 {n_fibers} 本、"
            "キンク {n_kinks} 個）"
        ).format(name=name, columns=columns, rows=rows,
                 n_fibers=len(session.fibers), n_kinks=kinks))
        notes, warnings = session_messages(session)
        for line in notes:
            self._log(line)
        if editor is not None and editor.off_track:
            self._log(_(
                "{n} 個のキンクは、追跡した繊維の画素の上にありません。"
                "これらは消去だけできます。"
            ).format(n=len(editor.off_track)))
        for line in warnings:
            self._log(line.replace("\n", " "))
        self._update_controls()
        if warnings:
            messagebox.showwarning(
                _("警告"), "\n\n".join(warnings), parent=self)

    # ----- Following the state -----

    def _bind_layers(self) -> bool:
        """
        Point the layers at the state's results as they stand.
        レイヤーを、現在の状態の結果に結び付ける。

        Returns
        -------
        bool
            Whether a layer was added or removed: the ridge mask layer exists
            only while there is a mask.
            レイヤーが増減したかどうか。リッジマスクのレイヤーは、マスクがある間
            だけ存在する。

        Notes
        -----
        The mask layers hold the state's own arrays, which a brush stroke
        changes in place, so a stroke needs no rebinding. A stage that is run
        again, and an undo of it, replace the arrays, and are followed by
        this.
        マスクのレイヤーは状態の配列そのものを持つ。ブラシのストロークはそれを直接
        書き換えるので、ストロークのあとに結び直す必要は無い。段の再実行とその
        取り消しは配列を置き換えるので、そのあとにこれを呼ぶ。
        """
        state = self.state
        if state is None:
            return False
        changed = False
        mask_layer = self._layer(LAYER_FIBER_MASK)
        if state.fiber_mask is None and mask_layer is not None:
            self.layers.remove(mask_layer)
            changed = True
        elif state.fiber_mask is not None and mask_layer is None:
            spec = next(spec for spec in DEFAULT_STACK if spec[0] == LAYER_FIBER_MASK)
            keys = [layer.key for layer in self.layers]
            position = keys.index(LAYER_CALIBRATED) if LAYER_CALIBRATED in keys else len(keys)
            self.layers.insert(position, Layer(
                spec[0], spec[1], to_rgb(spec[2]), True, spec[4]))
            changed = True
        if self._grey_source is not state.calibrated:
            # The grey levels follow the heights; recomputed only when the
            # background stage replaced them.
            # 灰色の濃淡は高さから決まる。背景補正の段が高さを置き換えたときだけ
            # 計算し直す。
            self._grey_source = state.calibrated
            self._grey = height_to_grey(state.calibrated, state.skeleton)
        data = {
            LAYER_CALIBRATED: self._grey,
            LAYER_FIBER_MASK: state.fiber_mask,
            LAYER_BINARIZED: state.binarized,
            LAYER_SKELETON: state.skeleton,
            LAYER_CENTERLINE: [
                np.column_stack(fiber_line(fiber)) for fiber in state.fibers
                if len(fiber.xtrack) >= 2
            ],
            LAYER_KINKS: kink_layer_data(
                state.kinks, self._move_source, self._move_target),
        }
        for layer in self.layers:
            if layer.key in data:
                layer.data = data[layer.key]
        return changed

    def _refresh_rows(self) -> None:
        """
        Show on each layer row whether it is chosen and whether it is stale.
        各レイヤーの行に、選ばれているかどうかと、古いかどうかを表示する。
        """
        state = self.state
        stale = set() if state is None else set(state.stale)
        if state is not None and state.tracks_stale:
            stale.add(LAYER_CENTERLINE)
        for key, row in self._rows.items():
            row.set_selected(key == self.active_layer)
            row.set_stale(key in stale)

    def _after_state_change(self) -> None:
        """
        Redraw everything after a change that replaced results of the state.
        状態の結果を置き換えた変更のあと、すべてを描き直す。
        """
        self.status_var.set("")
        if self._bind_layers():
            self._rebuild_layer_rows()
        if self._layer(self.active_layer or "") is None:
            self.active_layer = None
        if (self._selected_kink is not None and self.editor is not None
                and self.editor.kink_values(self._selected_kink) is None):
            self._selected_kink = None
        self._refresh_rows()
        self._render()
        self._update_controls()
        self._schedule_retrace()

    def _schedule_retrace(self) -> None:
        """
        Trace the fibers again shortly, when the skeleton has changed.
        スケルトンが変わっていれば、少し後に繊維を追跡し直す。

        The fibers follow from the skeleton, so the centerline layer and the
        pixels a kink can be put on are out of date until they are traced
        again. The delay lets a series of eraser strokes be followed by one
        tracing.
        繊維はスケルトンから決まるので、追跡し直すまで、中心線のレイヤーと、キンクを
        置ける画素は古いままである。待ち時間を置くことで、消しゴムを続けて使ったとき
        追跡を 1 回で済ませる。
        """
        if self._retrace_after is not None:
            self.after_cancel(self._retrace_after)
            self._retrace_after = None
        if self.state is not None and self.state.tracks_stale:
            self._retrace_after = self.after(RETRACE_DELAY_MS, self._start_retrace)

    def _start_retrace(self) -> None:
        """
        Start tracing the fibers of the skeleton as it stands.
        現在のスケルトンの繊維の追跡を始める。

        The arrays to trace are copied here, in the main thread, and the
        worker reads only the copies, so painting can go on meanwhile. The
        result is taken over only if the skeleton has not changed since.
        追跡する配列は、ここ、メインスレッドで複製し、ワーカーはその複製だけを読む。
        その間も塗る操作を続けられる。結果は、その後スケルトンが変わっていない場合に
        だけ取り込む。
        """
        self._retrace_after = None
        state = self.state
        if state is None or not state.tracks_stale:
            return
        if self._busy or self._retracing or self._stroke_at is not None:
            self._retrace_after = self.after(RETRACE_DELAY_MS, self._start_retrace)
            return
        self._retracing = True
        self.status_var.set(_("繊維を追跡し直しています…"))
        arrays = state.current_arrays()
        revision = state.skeleton_revision
        generation = self._generation

        def job() -> None:
            try:
                fibers = state.compute_fibers(arrays)
            except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
                self.ui_queue.put(
                    ("retrace_failed", (generation, f"{type(exc).__name__}: {exc}")))
            else:
                self.ui_queue.put(("retraced", (generation, revision, fibers)))

        threading.Thread(target=job, daemon=True).start()
        if self._poll_job is None:
            self._poll_job = self.after(50, self._poll_ui_queue)

    # ----- Image pane -----

    def on_fit_view(self) -> None:
        """
        Show the whole image.
        画像全体を表示する。
        """
        rows, columns = self._shape
        if rows <= 0 or columns <= 0:
            return
        # Pixel centers sit at integer coordinates, so the image spans from
        # -0.5 to the size less 0.5; row 0 is drawn at the top.
        # 画素の中心は整数の座標にあるので、画像は -0.5 から大きさ - 0.5 までを
        # 占める。行 0 が上に来る。
        self.ax.set_xlim(-0.5, columns - 0.5)
        self.ax.set_ylim(rows - 0.5, -0.5)
        self.canvas.draw_idle()

    def _on_scroll(self, event) -> None:
        """
        Zoom the view about the pointer on a wheel turn.
        ホイールを回したとき、ポインタの位置を中心に表示を拡大・縮小する。
        """
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        scale = 1.0 / WHEEL_ZOOM_FACTOR if event.button == "up" else WHEEL_ZOOM_FACTOR
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(event.xdata + (x0 - event.xdata) * scale,
                         event.xdata + (x1 - event.xdata) * scale)
        self.ax.set_ylim(event.ydata + (y0 - event.ydata) * scale,
                         event.ydata + (y1 - event.ydata) * scale)
        self.canvas.draw_idle()

    def _schedule_render(self) -> None:
        """
        Redraw the layers shortly, once for any number of requests.
        少し後にレイヤーを描き直す。要求が何度あっても 1 回だけ描く。
        """
        if self._render_job is None:
            self._render_job = self.after(RENDER_DELAY_MS, self._render)

    def _render(self) -> None:
        """
        Draw the visible layers in stack order.
        表示するレイヤーを、重なりの順に描く。

        Neighbouring image layers are composited into one image; a line or
        point layer between two of them splits the run, so it is drawn above
        the images below it and under the images above it.
        隣り合う画像のレイヤーは 1 枚の画像に合成する。その間に線や点のレイヤーが
        あれば、そこで合成を区切る。こうして線や点は、下の画像の上、上の画像の下に
        描かれる。
        """
        self._render_job = None
        for artist in self._artists:
            artist.remove()
        self._artists = []
        self._kink_artists = None
        self._raster_groups = []
        if self.session is None:
            self.canvas.draw_idle()
            return

        zorder = 1
        run: List[Layer] = []

        def flush() -> None:
            nonlocal zorder
            if not run:
                return
            rgba = composite_rasters(run, self._shape)
            image = self.ax.imshow(
                rgba, interpolation="nearest",
                aspect=self.session.pixel_aspect, zorder=zorder)
            # The toolbar would otherwise append the composited color under
            # the pointer to the coordinate readout.
            # こうしないと、ツールバーが座標表示の後ろに、ポインタの下の合成後の
            # 色を付け足してしまう。
            image.mouseover = False
            self._artists.append(image)
            self._raster_groups.append((image, list(run), rgba))
            zorder += 1
            run.clear()

        for layer in reversed(self.layers):
            if not layer.visible or layer.opacity <= 0.0:
                continue
            if layer.is_raster:
                run.append(layer)
                continue
            flush()
            if layer.kind == KIND_LINES:
                lines = LineCollection(
                    layer.data, colors=[layer.color],
                    linewidths=CENTERLINE_WIDTH_PT, alpha=layer.opacity,
                    zorder=zorder)
                self.ax.add_collection(lines, autolim=False)
                self._artists.append(lines)
            else:
                kink_x, kink_y = layer.data["kinks"]
                unjudged_x, unjudged_y = layer.data["unjudged"]
                # A kink is a filled marker; a bend that was not judged is a
                # hollow one in the same color.
                # キンクは塗りつぶした印、判定しなかった折れは同じ色の中抜きの印。
                unjudged_artist, = self.ax.plot(
                    unjudged_x, unjudged_y, linestyle="none", marker="o",
                    markersize=KINK_MARKER_PT, markerfacecolor="none",
                    markeredgecolor=layer.color, markeredgewidth=1.4,
                    alpha=layer.opacity, zorder=zorder)
                kink_artist, = self.ax.plot(
                    kink_x, kink_y, linestyle="none", marker="o",
                    markersize=KINK_MARKER_PT, markerfacecolor=layer.color,
                    markeredgecolor="black", markeredgewidth=0.8,
                    alpha=layer.opacity, zorder=zorder)
                self._artists.extend([unjudged_artist, kink_artist])
                self._kink_artists = (unjudged_artist, kink_artist)
            zorder += 1
        flush()
        self._draw_arms()

    def _repaint_region(self, key: str, region: Tuple[int, int, int, int]) -> None:
        """
        Redraw the part of the image a brush stroke changed on one layer.
        ブラシのストロークが 1 枚のレイヤーで変えた、画像の一部を描き直す。

        Parameters
        ----------
        key
            Key of the painted layer.
            塗ったレイヤーのキー。
        region
            ``(row_start, row_stop, column_start, column_stop)`` the stroke
            changed.
            ストロークが変えた
            ``(row_start, row_stop, column_start, column_stop)``。

        Notes
        -----
        Only that region of the image the layer is composited into is
        composited again, which is what lets the brush keep up with the
        pointer on a large scan. A layer that is not drawn changes nothing on
        screen.
        そのレイヤーを合成している画像の、その領域だけを合成し直す。大きな走査でも
        ブラシがポインタに遅れないのは、このためである。描いていないレイヤーは、
        画面を何も変えない。
        """
        for image, layers, rgba in self._raster_groups:
            if any(layer.key == key for layer in layers):
                rgba[region[0]:region[1], region[2]:region[3]] = composite_rasters(
                    layers, self._shape, region)
                image.set_data(rgba)
                self.canvas.draw_idle()
                return

    def _draw_arms(self) -> None:
        """
        Draw the arm ends of the chosen kink, above every layer.
        選んだキンクの腕の端を、すべてのレイヤーの上に描く。

        The two lines are the two arms: each runs between the points of the
        fiber's line it is read at, from its start beside the kink to its end,
        so what is drawn is what is measured, and the stretch next to the kink
        that no arm covers stays visible as the gap between them. Ends a
        person has not placed are drawn dashed and hollow: they are where a
        drag would start, not what the kink's angle was read with.
        2 本の線は 2 本の腕である。それぞれ、キンクのそばの始点から端まで、腕を読む
        繊維の線の点どうしを結ぶ。描いたものが、測ったものである。どちらの腕も
        覆わないキンクのすぐ隣の区間は、2 本の間のすき間として見える。人がまだ置いて
        いない端は、破線と中抜きで描く。それはドラッグの出発点であり、キンクの角度を
        読んだ位置ではない。
        """
        for artist in self._arm_artists:
            artist.remove()
        self._arm_artists = []
        shown = self._shown_arms()
        if shown is not None:
            _angle, points, by_hand = shown
            # First end, start of the first arm, a break, start of the second
            # arm, second end: one artist drawing both arms.
            # 1 つ目の端、1 本目の腕の始点、切れ目、2 本目の腕の始点、2 つ目の端。
            # 1 つの描画要素で両方の腕を描く。
            xs = [points[0][0], points[1][0], np.nan, points[2][0], points[3][0]]
            ys = [points[0][1], points[1][1], np.nan, points[2][1], points[3][1]]
            line, = self.ax.plot(
                xs, ys, color=ARM_COLOR, linewidth=ARM_LINE_WIDTH_PT,
                linestyle="-" if by_hand else "--", zorder=1000)
            ends, = self.ax.plot(
                [xs[0], xs[4]], [ys[0], ys[4]], linestyle="none", marker="o",
                markersize=ARM_END_MARKER_PT,
                markerfacecolor=ARM_COLOR if by_hand else "none",
                markeredgecolor="white" if by_hand else ARM_COLOR,
                markeredgewidth=1.0 if by_hand else 1.6, zorder=1001)
            ring, = self.ax.plot(
                [self._selected_kink[0]], [self._selected_kink[1]],
                linestyle="none", marker="o", markersize=KINK_MARKER_PT + 7.0,
                markerfacecolor="none", markeredgecolor=ARM_COLOR,
                markeredgewidth=1.4, zorder=1001)
            self._arm_artists = [line, ends, ring]
        self.canvas.draw_idle()

    def _shown_arms(self) -> Optional[Tuple[float, List[Tuple[float, float]], bool]]:
        """
        Return what `_draw_arms` draws for the chosen kink, or ``None``.
        選んだキンクについて `_draw_arms` が描く内容を返す。無ければ ``None``。

        Returns
        -------
        tuple or None
            ``(angle, points, by_hand)``: the angle between the arms in
            radians, the four line points the arms run between (first end,
            start of the first arm, start of the second arm, second end), and
            whether the ends were placed by a person or are being dragged.
            ``None`` unless the kink-editing tool is chosen, a kink is chosen
            and the kink layer is shown.
            ``(angle, points, by_hand)``。腕の間の角度（ラジアン）、腕が結ぶ線の
            4 点（1 つ目の端、1 本目の腕の始点、2 本目の腕の始点、2 つ目の端）、端が
            人の置いたものか、ドラッグ中かどうか。キンク編集のツールが選ばれ、
            キンクが選ばれ、キンクのレイヤーが表示されている場合以外は ``None``。
        """
        layer = self._layer(LAYER_KINKS)
        if (self.editor is None or self._selected_kink is None
                or self.tool_var.get() != TOOL_EDIT_KINK
                or layer is None or not layer.visible or layer.opacity <= 0.0):
            return None
        ends = self.editor.arm_ends(self._selected_kink)
        if ends is None:
            return None
        first, second, by_hand = ends
        if self._arm_drag is not None:
            side, target = self._arm_drag
            first, second = (target, second) if side == ARM_BEFORE else (first, target)
            by_hand = True
        measured = self.editor.measure_arms(self._selected_kink, first, second)
        if measured is None:
            return None
        return measured[0], measured[1], by_hand

    def _show_selected_kink(self) -> None:
        """
        Draw the chosen kink's arms and state its angle.
        選んだキンクの腕を描き、その角度を表示する。
        """
        self._draw_arms()
        pixel = self._selected_kink
        if pixel is None or self.editor is None:
            return
        values = self.editor.kink_values(pixel)
        if values is None:
            return
        if self._arm_drag is not None:
            shown = self._shown_arms()
            if shown is not None:
                self.status_var.set(_("内角 {angle} {unit}").format(
                    angle=f"{np.degrees(shown[0]):.1f}", unit="deg"))
        elif self.editor.angle_is_set_by_hand(pixel):
            self.status_var.set(_(
                "x={x}, y={y}、内角 {angle} {unit}（端点で決めた角度）"
            ).format(x=pixel[0], y=pixel[1],
                     angle=f"{np.degrees(values[0]):.1f}", unit="deg"))
        elif self.editor.arm_ends(pixel) is None:
            self.status_var.set(_(
                "x={x}, y={y}、内角 {angle} {unit}（解析の角度。"
                "このキンクには端点を置けません）"
            ).format(x=pixel[0], y=pixel[1],
                     angle=f"{np.degrees(values[0]):.1f}", unit="deg"))
        else:
            self.status_var.set(_(
                "x={x}, y={y}、内角 {angle} {unit}（解析の角度。"
                "破線の端点を動かすと、端点で決めた角度に置き換わります）"
            ).format(x=pixel[0], y=pixel[1],
                     angle=f"{np.degrees(values[0]):.1f}", unit="deg"))

    # ----- Pointer on the image -----

    def _toolbar_idle(self) -> bool:
        """
        Whether the toolbar's own Pan or Zoom is switched off.
        ツールバー自身の Pan・Zoom が切れているかどうか。

        While one of them is on, it owns the left drag, and a click must not
        edit as well.
        どちらかが入っている間は、左ドラッグはそれが使う。クリックで編集まで
        行ってはならない。
        """
        return getattr(getattr(self._toolbar, "mode", None), "name", "NONE") == "NONE"

    def _pick_radius(self) -> float:
        """
        Distance in image pixels within which a click reaches a pixel or a mark.
        クリックが画素や印に届く距離（画像の画素単位）。
        """
        inverse = self.ax.transData.inverted()
        left = inverse.transform((0.0, 0.0))
        right = inverse.transform((PICK_RADIUS_SCREEN_PX, 0.0))
        return max(abs(float(right[0] - left[0])), PICK_RADIUS_MIN_IMAGE_PX)

    def _kinks_editable_now(self) -> bool:
        """
        Whether a click may change the kinks, saying why not when it may not.
        クリックでキンクを変更できるかどうか。できないときは理由を表示する。
        """
        if self.editor is None or self.active_layer != LAYER_KINKS:
            return False
        layer = self._layer(LAYER_KINKS)
        if layer is None or not layer.visible or layer.opacity <= 0.0:
            self.status_var.set(_("キンクのレイヤーが非表示です。表示してから編集してください。"))
            return False
        if self.state is not None and self.state.tracks_stale:
            # A kink sits on a fiber pixel, and the fibers of the changed
            # skeleton are not traced yet.
            # キンクは繊維の画素の上に置く。変更したスケルトンの繊維は、まだ追跡
            # されていない。
            self.status_var.set(_(
                "細線化画像が変わったので、繊維を追跡し直しています。少し待ってください。"))
            return False
        return True

    def _brush_diameter(self) -> float:
        """
        Return the brush diameter entered, within its range, in image pixels.
        入力されたブラシの直径を、範囲内に収めて返す（画像の画素）。
        """
        try:
            diameter = float(self.brush_var.get())
        except ValueError:
            diameter = float(DEFAULT_BRUSH_PX)
        return float(min(max(diameter, BRUSH_RANGE_PX[0]), BRUSH_RANGE_PX[1]))

    def _begin_paint(self, tool: str, x: float, y: float) -> None:
        """
        Start a brush stroke on the chosen mask layer.
        選んだマスクのレイヤーで、ブラシのストロークを始める。
        """
        key = self.active_layer
        layer = self._layer(key or "")
        if layer is None or tool not in LAYER_TOOLS.get(key or "", ()):
            return
        if not layer.visible or layer.opacity <= 0.0:
            self.status_var.set(_(
                "{layer} が非表示です。表示してから編集してください。"
            ).format(layer=layer_label(key)))
            return
        self.status_var.set("")
        self.state.begin_stroke(key, tool == TOOL_PENCIL)
        self._stroke_at = (x, y)
        self._paint_to(x, y)

    def _paint_to(self, x: float, y: float) -> None:
        """
        Paint from where the stroke last was to a pointer position.
        ストロークが最後にあった位置から、ポインタの位置まで塗る。
        """
        x0, y0 = self._stroke_at
        region = self.state.paint(x0, y0, x, y, self._brush_diameter())
        self._stroke_at = (x, y)
        if region is not None:
            self._repaint_region(self.active_layer, region)

    def _on_press(self, event) -> None:
        """
        Start a view drag, or apply the chosen tool where the pointer is.
        表示を動かすドラッグを始める、または選んだツールをポインタの位置で使う。
        """
        if (event.inaxes is not self.ax or self.session is None
                or event.xdata is None or event.ydata is None
                or not self._toolbar_idle()):
            return
        if event.button in (2, 3):
            self._pan = (event.x, event.y, self.ax.transData.inverted(),
                         self.ax.get_xlim(), self.ax.get_ylim())
            return
        tool = self.tool_var.get()
        if event.button != 1 or tool == TOOL_NONE or self.state is None or self._busy:
            return
        if tool in (TOOL_PENCIL, TOOL_ERASER):
            self._begin_paint(tool, event.xdata, event.ydata)
            return
        if not self._kinks_editable_now():
            return
        if tool == TOOL_ADD_KINK:
            self.add_kink_at(event.xdata, event.ydata)
        elif tool == TOOL_ERASE_KINK:
            self.erase_mark_at(event.xdata, event.ydata)
        elif tool == TOOL_MOVE_KINK:
            found = self.editor.nearest_mark(
                event.xdata, event.ydata, self._pick_radius(), kinks_only=True)
            if found is None:
                self.status_var.set(_("動かすキンクの上で押してください。"))
            else:
                self._move_source = self._move_target = found[1]
        elif tool == TOOL_EDIT_KINK:
            side = self._arm_end_at(event.xdata, event.ydata)
            if side is not None:
                ends = self.editor.arm_ends(self._selected_kink)
                self._arm_drag = (side, ends[side])
                self._arm_drag_from = ends[side]
                return
            found = self.editor.nearest_mark(
                event.xdata, event.ydata, self._pick_radius(), kinks_only=True)
            self._selected_kink = None if found is None else found[1]
            if found is None:
                self.status_var.set(_("角度を決めるキンクをクリックしてください。"))
            self._show_selected_kink()

    def _arm_end_at(self, x: float, y: float) -> Optional[int]:
        """
        Return which drawn arm end of the chosen kink a position is on.
        ある位置が、選んだキンクの描かれた腕の端のどちらの上にあるかを返す。

        Returns
        -------
        int or None
            `ARM_BEFORE` or `ARM_AFTER`, or ``None`` when the position is on
            neither, or no arms are drawn.
            `ARM_BEFORE` または `ARM_AFTER`。どちらの上にも無い、または腕を描いて
            いなければ ``None``。
        """
        shown = self._shown_arms()
        if shown is None:
            return None
        points = shown[1]
        aspect = self.session.pixel_aspect
        distances = [
            float(np.hypot(points[i][0] - x, (points[i][1] - y) * aspect))
            for i in (0, 3)
        ]
        side = ARM_BEFORE if distances[0] <= distances[1] else ARM_AFTER
        return side if distances[side] <= self._pick_radius() else None

    def _on_motion(self, event) -> None:
        """
        Follow the pointer during a drag of the view, a kink or an arm end.
        表示・キンク・腕の端のいずれかのドラッグの間、ポインタを追う。
        """
        if self._pan is not None:
            x0, y0, inverse, xlim, ylim = self._pan
            start = inverse.transform((x0, y0))
            now = inverse.transform((event.x, event.y))
            dx, dy = float(now[0] - start[0]), float(now[1] - start[1])
            self.ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
            self.ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
            self.canvas.draw_idle()
            return
        if self.editor is None or event.inaxes is not self.ax or event.xdata is None:
            return
        if self._stroke_at is not None:
            self._paint_to(event.xdata, event.ydata)
            return
        if self._arm_drag is not None and self._selected_kink is not None:
            side, target = self._arm_drag
            pixel = self.editor.nearest_arm_pixel(
                self._selected_kink, side, event.xdata, event.ydata)
            if pixel is not None and pixel != target:
                self._arm_drag = (side, pixel)
                self._show_selected_kink()
            return
        if self._move_source is None:
            return
        pixel = self.editor.nearest_track_pixel(
            event.xdata, event.ydata, self._pick_radius())
        if pixel is not None and pixel != self._move_target:
            self._move_target = pixel
            self._sync_kinks()

    def _on_release(self, _event) -> None:
        """
        End a view drag, or drop a dragged kink or arm end where it was shown.
        表示を動かすドラッグを終える。または、ドラッグ中のキンクや腕の端を、最後に
        示した位置に置く。
        """
        if self._pan is not None:
            self._pan = None
            return
        if self.editor is None:
            return
        if self._stroke_at is not None:
            key = self.active_layer
            setting = self.tool_var.get() == TOOL_PENCIL
            self._stroke_at = None
            if self.state.end_stroke():
                message = (_("{layer} に画素を加えました。") if setting
                           else _("{layer} から画素を除きました。"))
                self._log(message.format(layer=layer_label(key)))
                self._refresh_rows()
                self._update_controls()
                self._schedule_retrace()
            return
        if self._arm_drag is not None:
            side, target = self._arm_drag
            self._arm_drag = None
            pixel = self._selected_kink
            # A press released where it began moves nothing: a kink keeps the
            # angle it has until one of its ends is actually moved.
            # 押した位置で離した場合は何も動かさない。キンクは、端のどちらかが実際に
            # 動くまで、いまの角度を保つ。
            if (pixel is not None and target != self._arm_drag_from
                    and self.state.set_arm(pixel, side, target)):
                self._log(_("キンクの角度を設定: {detail}").format(
                    detail=self._describe_kink(pixel)))
            self._after_edit()
            return
        if self._move_source is None:
            return
        source, target = self._move_source, self._move_target
        self._move_source = self._move_target = None
        if target is not None and target != source:
            if self.state.move_kink(source, target):
                self._log(_("キンクを移動: x={x}, y={y} → {detail}").format(
                    x=source[0], y=source[1], detail=self._describe_kink(target)))
                self.status_var.set("")
            else:
                self.status_var.set(_("そこへはキンクを動かせません。"))
        self._after_edit()

    # ----- Editing kinks -----

    def _describe_kink(self, pixel: Tuple[int, int]) -> str:
        """
        Describe a kink by its pixel, its interior angle and its arm ends.
        キンクを、その画素・内角・腕の端で文章にする。
        """
        angle, _excess = self.editor.kink_values(pixel)
        text = _("x={x}, y={y}、内角 {angle} {unit}").format(
            x=pixel[0], y=pixel[1], angle=f"{np.degrees(angle):.1f}", unit="deg")
        ends = self.editor.arm_ends(pixel)
        if ends is not None and ends[2]:
            text += _("、端点 ({x1}, {y1}) と ({x2}, {y2})").format(
                x1=ends[0][0], y1=ends[0][1], x2=ends[1][0], y2=ends[1][1])
        return text

    def _sync_kinks(self) -> None:
        """
        Draw the kink layer from the editor's current marks.
        エディタの現在の印から、キンクのレイヤーを描く。
        """
        layer = self._layer(LAYER_KINKS)
        if layer is None or self.editor is None:
            return
        layer.data = kink_layer_data(self.editor, self._move_source, self._move_target)
        if self._kink_artists is None or self._render_job is not None:
            self._schedule_render()
            return
        unjudged_artist, kink_artist = self._kink_artists
        unjudged_artist.set_data(*layer.data["unjudged"])
        kink_artist.set_data(*layer.data["kinks"])
        self._draw_arms()

    def _after_edit(self) -> None:
        """
        Redraw the kinks and update the controls after a change.
        変更のあと、キンクを描き直し、操作欄を更新する。
        """
        # A change can remove the chosen kink (an erase, a move, an undo).
        # 変更によって、選んでいたキンクが無くなることがある（消去・移動・元に戻す）。
        if (self._selected_kink is not None and self.editor is not None
                and self.editor.kink_values(self._selected_kink) is None):
            self._selected_kink = None
        self._sync_kinks()
        if self._selected_kink is not None and self.tool_var.get() == TOOL_EDIT_KINK:
            self._show_selected_kink()
        self._refresh_rows()
        self._update_controls()

    def add_kink_at(self, x: float, y: float) -> bool:
        """
        Put a kink on the fiber pixel nearest an image position.
        画像上の位置に最も近い繊維の画素に、キンクを置く。

        Parameters
        ----------
        x, y
            Position in image pixels.
            画像の画素単位の位置。

        Returns
        -------
        bool
            Whether a kink was added.
            キンクを追加したかどうか。
        """
        if self.editor is None:
            return False
        pixel = self.editor.nearest_track_pixel(x, y, self._pick_radius())
        if pixel is None:
            self.status_var.set(_("繊維（細線化画像の線）の上をクリックしてください。"))
            return False
        if not self.state.add_kink(pixel):
            self.status_var.set(_("そこにはキンクを置けません。"))
            return False
        self.status_var.set("")
        self._log(_("キンクを追加: {detail}").format(detail=self._describe_kink(pixel)))
        self._after_edit()
        return True

    def erase_mark_at(self, x: float, y: float) -> bool:
        """
        Remove the kink, or the bend that was not judged, nearest a position.
        ある位置に最も近いキンク、または判定しなかった折れを除く。

        Parameters
        ----------
        x, y
            Position in image pixels.
            画像の画素単位の位置。

        Returns
        -------
        bool
            Whether a mark was removed.
            印を除いたかどうか。
        """
        if self.editor is None:
            return False
        found = self.editor.nearest_mark(x, y, self._pick_radius())
        if found is None:
            self.status_var.set(_("消す印の上をクリックしてください。"))
            return False
        kind, pixel = found
        if not self.state.remove_mark(pixel):
            return False
        self.status_var.set("")
        message = (_("キンクを消去: x={x}, y={y}") if kind == MARK_KINK
                   else _("判定しなかった折れを消去: x={x}, y={y}"))
        self._log(message.format(x=pixel[0], y=pixel[1]))
        self._after_edit()
        return True

    def on_undo(self) -> None:
        """
        Take back the last change to the kinks.
        キンクへの直前の変更を取り消す。
        """
        if self.state is not None and not self._busy and self.state.undo():
            self._log(_("元に戻しました。"))
            self._after_state_change()

    def on_redo(self) -> None:
        """
        Apply the last undone change again.
        直前に取り消した変更をやり直す。
        """
        if self.state is not None and not self._busy and self.state.redo():
            self._log(_("やり直しました。"))
            self._after_state_change()

    # ----- Running stages again -----

    def on_run_stage(self, stage: str) -> None:
        """
        Run a stage again on the results as they stand.
        現在の結果に対して、段を再実行する。

        Parameters
        ----------
        stage
            One of `bundle_edit.STAGE_RESULT`.
            `bundle_edit.STAGE_RESULT` のいずれか。

        Notes
        -----
        The stage runs in a worker thread and its result is taken over when
        it arrives. Where the result it replaces was changed by hand, the
        user is asked first, because those changes are then lost (an undo
        brings them back).
        段はワーカースレッドで動き、結果は届いたときに取り込む。置き換える結果が
        手で変更されている場合は、先に確認する。その変更が失われるためである
        （元に戻せば復元できる）。
        """
        state = self.state
        if state is None or self._busy or not state.can_run(stage):
            return
        result = STAGE_RESULT[stage]
        if result in state.edited and not messagebox.askyesno(
                _("確認"),
                _("手で変更した {layer} は、{stage} の結果で置き換わります。続けますか？"
                  ).format(layer=layer_label(result), stage=stage_label(stage)),
                parent=self):
            return
        self.status_var.set(_("{stage} を実行しています…").format(
            stage=stage_label(stage)))
        self._start_job(self._stage_job, stage)

    def on_stage_settings(self, stage: str) -> None:
        """
        Open the settings dialog of a stage.
        ある段の設定ダイアログを開く。
        """
        if self.state is not None and not self._busy:
            ParamsDialog(self, stage, self.state.params)

    def apply_stage_settings(self, stage: str, params: ProcParams) -> Optional[str]:
        """
        Take over settings a dialog returned for a stage.
        ダイアログが返した、ある段の設定を取り込む。

        Parameters
        ----------
        stage
            The stage the settings belong to.
            設定が属する段。
        params
            The settings with the dialog's values.
            ダイアログの値を入れた設定。

        Returns
        -------
        str or None
            Why the settings were refused, or ``None`` when they were taken.
            設定を受け付けなかった理由。受け付けた場合は ``None``。
        """
        if self.state is None:
            return None
        try:
            self.state.set_params(params, stage)
        except ValueError as exc:
            return str(exc)
        self._log(_("{stage} の設定を変更しました。").format(stage=stage_label(stage)))
        self._refresh_rows()
        self._update_controls()
        return None

    def _on_tool_chosen(self) -> None:
        """
        Switch the toolbar's Pan or Zoom off when an editing tool is chosen.
        編集のツールを選んだとき、ツールバーの Pan・Zoom を切る。

        Both would otherwise claim the left button.
        そうしないと、どちらも左ボタンを使おうとする。
        """
        self.status_var.set("")
        self._arm_drag = None
        # The arm ends are drawn only while the kink-editing tool is chosen.
        # 腕の端を描くのは、キンク編集のツールを選んでいる間だけである。
        self._show_selected_kink()
        if self.tool_var.get() == TOOL_NONE:
            return
        mode = getattr(getattr(self._toolbar, "mode", None), "name", "NONE")
        if mode == "PAN":
            self._toolbar.pan()
        elif mode == "ZOOM":
            self._toolbar.zoom()

    # ----- Saving -----

    def _can_overwrite(self) -> bool:
        """
        Whether the edits may be saved over the opened bundle.
        編集を、開いているバンドルに上書き保存してよいかどうか。

        Only an edited bundle (one with a `MANUAL_EDIT_KEY` record) is saved
        over, never the bundle the analysis wrote, and only when something
        differs from what was last opened or saved. A bundle saved under
        another name is opened afterwards (`save_to`), so after a first save
        the edited bundle is the opened one.
        上書きするのは編集済みのバンドル（`MANUAL_EDIT_KEY` の記録を持つもの）だけで、
        解析が書いたバンドルには上書きしない。最後に開いた、または保存した状態から
        違いがあるときに限る。別名で保存したバンドルは保存後に開く（`save_to`）ため、
        一度保存すれば、開いているのはその編集済みのバンドルである。
        """
        current = self.state
        return (current is not None and self.session is not None
                and not self._busy and not self._loading and current.modified
                and bool(self.session.meta.get(MANUAL_EDIT_KEY)))

    def _can_save_as(self) -> bool:
        """
        Whether the edits may be saved under a name, as the save button allows.
        「名前を付けて保存…」のボタンと同じく、編集を名前を付けて保存してよいかどうか。
        """
        current = self.state
        return (current is not None and not self._busy and not self._loading
                and current.modified)

    def on_save_shortcut(self) -> None:
        """
        Handle Ctrl+S: save over an edited bundle, otherwise ask for a name.
        Ctrl+S を処理する。編集済みのバンドルには上書き保存し、それ以外は名前を尋ねる。

        An edited bundle that has changed is saved over after a confirmation
        (`on_overwrite`). A bundle the analysis wrote is never saved over, so
        its edits are saved under a name (`on_save`), as Save does for a
        document that has never been saved. Nothing happens while nothing has
        changed.
        変更のある編集済みのバンドルは、確認のうえ上書き保存する（`on_overwrite`）。
        解析が書いたバンドルには上書きしないため、その編集は名前を付けて保存する
        （`on_save`）。一度も保存していない文書に対する一般的な「上書き保存」と同じ
        動きである。変更が無いときは何もしない。
        """
        if self._can_overwrite():
            self.on_overwrite()
        elif self._can_save_as():
            self.on_save()

    def on_save_as_shortcut(self) -> None:
        """
        Handle Ctrl+Shift+S: save the edits under a name when the button allows it.
        Ctrl+Shift+S を処理する。ボタンが押せるときに、編集を名前を付けて保存する。
        """
        if self._can_save_as():
            self.on_save()

    def on_overwrite(self) -> None:
        """
        Save the edits over the opened edited bundle, after asking.
        確認のうえ、開いている編集済みのバンドルに編集を上書き保存する。
        """
        if not self._can_overwrite():
            return
        path = self.session.bundle_path
        if not messagebox.askyesno(
                _("確認"),
                _("{name} に上書き保存しますか？").format(name=os.path.basename(path)),
                parent=self):
            return
        self.save_to(path)

    def on_save(self) -> None:
        """
        Ask where to save the edited bundle and save it.
        編集したバンドルの保存先を尋ねて、保存する。
        """
        if self.editor is None or self.session is None:
            return
        default = edited_path_for(self.session.bundle_path, self.session.meta)
        path = filedialog.asksaveasfilename(
            parent=self, title=_("編集したバンドルの保存先"),
            initialdir=os.path.dirname(os.path.abspath(default)),
            initialfile=os.path.basename(default),
            defaultextension=BUNDLE_EXT,
            filetypes=[("b2z bundle", "*" + BUNDLE_EXT), ("All files", "*.*")])
        if path:
            self.save_to(path)

    def save_to(self, path: str) -> bool:
        """
        Save the edited bundle and open the saved file.
        編集したバンドルを保存し、保存したファイルを開く。

        Parameters
        ----------
        path
            Where to write the edited bundle.
            編集したバンドルの書き込み先。

        Returns
        -------
        bool
            Whether the bundle was saved.
            バンドルを保存できたかどうか。

        Notes
        -----
        The saved file is opened afterwards, so what is on screen is what is
        on disk, and a further save adds to that file's own record.
        保存のあと、保存したファイルを開く。画面にあるものがディスクにあるものと
        同じになり、次の保存は、そのファイル自身の記録に足される。
        """
        state = self.state
        if state is None or self.session is None or self._busy:
            return False
        source = os.path.abspath(self.session.bundle_path)
        if (os.path.abspath(path) == source
                and not self.session.meta.get(MANUAL_EDIT_KEY)):
            messagebox.showerror(
                _("保存エラー"),
                _("解析で書き出したバンドルには上書きできません。"
                  "別の名前で保存してください。"),
                parent=self)
            return False
        if state.stale:
            # Saved as they are, with the record naming them: the choice of
            # which stage to run again stays with the user.
            # そのまま保存し、記録にその名前を書く。どの段を再実行するかは、
            # 利用者が決める。
            names = "、".join(
                layer_label(name) for name in RESULTS if name in state.stale)
            if not messagebox.askyesno(
                    _("確認"),
                    _("次のレイヤーは、元になるレイヤーや設定が変わったあと、計算し直して"
                      "いません:\n{layers}\n\nこのまま保存しますか？（保存するバンドルには、"
                      "これらが古いことが記録されます）").format(layers=names),
                    parent=self):
                return False
        self.status_var.set(_("保存しています…"))
        self.update_idletasks()
        try:
            param_path = state.save(path, editor_name=self.editor_name_var.get())
        except Exception as exc:  # noqa: BLE001 - shown to the user as the reason
            self.status_var.set("")
            reason = f"{type(exc).__name__}: {exc}"
            self._log(_("保存できませんでした: {reason}").format(reason=reason))
            messagebox.showerror(
                _("保存エラー"),
                _("バンドルを保存できませんでした:\n{e}").format(e=reason),
                parent=self)
            return False
        self._log(_("保存: {path}").format(path=path))
        self._log(_("保存: {path}").format(path=param_path))
        self.open_bundle(path)
        return True

    # ----- Layer pane -----

    def _layer(self, key: str) -> Optional[Layer]:
        """
        Return the layer with a key, or ``None``.
        キーに対応するレイヤーを返す。無ければ ``None``。
        """
        for layer in self.layers:
            if layer.key == key:
                return layer
        return None

    def _rebuild_layer_rows(self) -> None:
        """
        Create one row per layer, topmost layer first.
        レイヤーごとに 1 行を作る。上のレイヤーから順。
        """
        for row in self._rows.values():
            row.destroy()
        self._rows = {}
        for layer in self.layers:
            self._rows[layer.key] = LayerRow(self.layer_rows_frame, self, layer)
        self._pack_layer_rows()
        self._refresh_rows()

    def _pack_layer_rows(self) -> None:
        """
        Place the rows in the order of the layer stack.
        行を、レイヤーの重なりの順に並べる。

        A row already on screen is moved within the packing order, never
        forgotten and packed again: a row that is unmapped and mapped within
        one pass of the event loop can come back with the widgets inside it
        still unmapped, which shows as a row with no name and no check box.
        すでに表示されている行は、パックの順番の中で動かす。いったん外して置き直す
        ことはしない。イベントループの 1 回の処理の中で非表示にして再表示した行は、
        中のウィジェットが非表示のまま戻ることがあり、名前もチェックボックスも無い
        行として見えてしまう。
        """
        previous: Optional[LayerRow] = None
        for layer in self.layers:
            row = self._rows[layer.key]
            options: Dict[str, Any] = {"side": tk.TOP, "fill": tk.X, "pady": (0, 4)}
            if previous is not None:
                options["after"] = previous
            else:
                packed = self.layer_rows_frame.pack_slaves()
                if packed and packed[0] is not row:
                    options["before"] = packed[0]
            row.pack_configure(**options)
            previous = row

    def select_layer(self, key: str) -> None:
        """
        Make a layer the one the tools act on.
        あるレイヤーを、ツールが働くレイヤーにする。

        Parameters
        ----------
        key
            Key of the layer. A layer outside `EDITABLE_LAYERS` is not
            selected, and neither is any layer of a bundle that cannot be
            edited.
            レイヤーのキー。`EDITABLE_LAYERS` に無いレイヤーは選ばれない。編集
            できないバンドルでは、どのレイヤーも選ばれない。
        """
        if key not in EDITABLE_LAYERS:
            self.status_var.set(_("このレイヤーは編集できません。"))
            return
        if self.state is None:
            self.status_var.set(_("このバンドルは表示だけできます。"))
            return
        self.active_layer = key
        self.status_var.set("")
        self._refresh_rows()
        self._update_controls()
        # The arm ends are drawn only for the kink layer's own tool.
        # 腕の端を描くのは、キンクのレイヤーのツールを使っている間だけである。
        self._draw_arms()

    def set_layer_visible(self, key: str, visible: bool) -> None:
        """
        Show or hide a layer.
        レイヤーを表示または非表示にする。
        """
        layer = self._layer(key)
        if layer is not None and layer.visible != bool(visible):
            layer.visible = bool(visible)
            self.status_var.set("")
            self._schedule_render()

    def set_layer_opacity(self, key: str, opacity: float) -> None:
        """
        Set a layer's opacity, from 0 to 1.
        レイヤーの不透明度（0〜1）を設定する。
        """
        layer = self._layer(key)
        if layer is None:
            return
        opacity = float(min(max(opacity, 0.0), 1.0))
        if layer.opacity != opacity:
            layer.opacity = opacity
            self._schedule_render()

    def move_layer(self, key: str, slot: int) -> bool:
        """
        Move a layer into a gap of the stack.
        レイヤーを、重なりのすき間へ移す。

        Parameters
        ----------
        key
            Key of the layer to move.
            移すレイヤーのキー。
        slot
            Gap to move it into, counted from the top before the move: 0 is
            above the topmost layer, ``len(layers)`` below the lowest.
            移す先のすき間。移す前の上からの番号で、0 は最も上のレイヤーの上、
            ``len(layers)`` は最も下のレイヤーの下。

        Returns
        -------
        bool
            Whether the layer changed its place.
            レイヤーの位置が変わったかどうか。
        """
        keys = [layer.key for layer in self.layers]
        if key not in keys:
            return False
        index = keys.index(key)
        slot = min(max(int(slot), 0), len(keys))
        # The gaps on either side of the row leave it where it is.
        # 行のすぐ上とすぐ下のすき間は、行を動かさない。
        if slot in (index, index + 1):
            return False
        layer = self.layers.pop(index)
        self.layers.insert(slot if slot < index else slot - 1, layer)
        self._pack_layer_rows()
        self._schedule_render()
        return True

    def begin_row_drag(self, key: str) -> None:
        """
        Start dragging a layer row.
        レイヤーの行のドラッグを始める。
        """
        self._drag_key = key
        self._drag_slot = None

    def drag_row_to(self, y_root: int) -> None:
        """
        Show where the dragged row would be dropped for a pointer height.
        ポインタの高さに対して、ドラッグ中の行を離したときに入る位置を示す。

        Parameters
        ----------
        y_root
            Pointer height in screen coordinates.
            画面座標でのポインタの高さ。
        """
        if self._drag_key is None:
            return
        rows = [self._rows[layer.key] for layer in self.layers]
        centers = [row.winfo_rooty() + row.winfo_height() / 2.0 for row in rows]
        slot = drop_slot(centers, y_root)
        self._drag_slot = slot
        frame_top = self.layer_rows_frame.winfo_rooty()
        if slot < len(rows):
            line_y = rows[slot].winfo_rooty() - frame_top - 2
        else:
            line_y = rows[-1].winfo_rooty() + rows[-1].winfo_height() - frame_top
        self._drop_line.place(x=0, y=max(line_y, 0), relwidth=1.0)
        self._drop_line.lift()

    def end_row_drag(self) -> None:
        """
        Drop the dragged row, or select its layer when it was only clicked.
        ドラッグ中の行を置く。クリックしただけなら、そのレイヤーを選ぶ。

        A press released without the row changing its place is a click on the
        layer, which selects it.
        行の位置が変わらないまま離した押下は、レイヤーへのクリックであり、その
        レイヤーを選ぶ。
        """
        key, slot = self._drag_key, self._drag_slot
        self._drag_key = None
        self._drag_slot = None
        self._drop_line.place_forget()
        if key is None:
            return
        if slot is None or not self.move_layer(key, slot):
            self.select_layer(key)

    # ----- Log and shutdown -----

    def on_save_log(self) -> None:
        """
        Save the log text through a file dialog.
        ログ本文をファイルダイアログ経由で保存する。
        """
        save_text_widget_log(
            self, self.log_text,
            initial_dir=self._last_dir,
            initialfile="bundle_editor_log.txt",
            empty_warning=True,
            log_cb=self._log,
        )

    def on_close(self) -> None:
        """
        Close the window, asking first when edits are not saved.
        ウィンドウを閉じる。保存していない編集があれば、先に確認する。
        """
        if self._discard_allowed():
            self.destroy()

    def destroy(self) -> None:
        """
        Cancel the scheduled work and destroy the window.
        予約済みの処理を取り消して、ウィンドウを破棄する。
        """
        # A redraw or a poll still scheduled would run against the destroyed
        # window and report an unknown command.
        # 予約されたままの再描画やポーリングは、破棄されたウィンドウに対して
        # 実行され、不明なコマンドとして報告されてしまう。
        self._generation += 1
        for name in ("_render_job", "_poll_job", "_retrace_after"):
            job = getattr(self, name, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        super().destroy()


class LayerRow(ttk.Frame):
    """
    One row of the layer pane: handle, visibility, name and opacity.
    レイヤーペインの 1 行。つまみ、表示の切り替え、名前、不透明度。

    The handle, the color swatch and the name take a press: dragged, it moves
    the layer in the stack; released in place, it selects the layer. The check
    box and the slider do neither, so using them never reorders or selects.
    つまみ・色見本・名前は押下を受ける。ドラッグすればレイヤーを重なりの中で動かし、
    その場で離せばレイヤーを選ぶ。チェックボックスとスライダーはどちらもしないので、
    それらを使ってもレイヤーの順や選択は変わらない。
    """

    def __init__(self, parent: tk.Misc, app: App, layer: Layer) -> None:
        """
        Build the row for one layer.
        1 枚のレイヤーの行を作る。

        Parameters
        ----------
        parent
            Frame holding the rows.
            行を並べるフレーム。
        app
            Window the row reports changes to.
            変更を伝える先のウィンドウ。
        layer
            Layer the row shows.
            行が表示するレイヤー。
        """
        super().__init__(parent)
        self._app = app
        self._key = layer.key
        self.visible_var = tk.BooleanVar(value=layer.visible)
        self.opacity_var = tk.DoubleVar(value=layer.opacity)
        self.percent_var = tk.StringVar(value=self._percent(layer.opacity))

        head = ttk.Frame(self)
        head.pack(side=tk.TOP, fill=tk.X)
        handle = ttk.Label(head, text="≡", cursor="sb_v_double_arrow")
        handle.pack(side=tk.LEFT, padx=(0, 2))
        ttk.Checkbutton(
            head, variable=self.visible_var, command=self._on_visible,
        ).pack(side=tk.LEFT)
        red, green, blue = (int(round(channel * 255)) for channel in layer.color)
        swatch = tk.Frame(head, width=12, height=12,
                          bg=f"#{red:02x}{green:02x}{blue:02x}")
        swatch.pack(side=tk.LEFT, padx=(2, 4))
        self.name_label = ttk.Label(head, text=layer_label(layer.key))
        self.name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # Always in place and empty unless the layer is stale: showing and
        # hiding a widget of a row is what `App._pack_layer_rows` avoids.
        # 常に置いておき、レイヤーが古くない間は空にする。行のウィジェットを表示・
        # 非表示で切り替えることは、`App._pack_layer_rows` が避けている操作である。
        self.stale_var = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.stale_var, foreground=STALE_COLOR).pack(
            side=tk.RIGHT)

        tail = ttk.Frame(self)
        tail.pack(side=tk.TOP, fill=tk.X, padx=(18, 0))
        ttk.Label(tail, textvariable=self.percent_var, width=5, anchor=tk.E).pack(
            side=tk.RIGHT)
        self.scale = ttk.Scale(
            tail, from_=0.0, to=1.0, variable=self.opacity_var,
            command=self._on_opacity)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for widget in (handle, swatch, self.name_label):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_motion)
            widget.bind("<ButtonRelease-1>", self._on_release)
        ToolTip(handle, _("ドラッグすると、レイヤーの重ね順を変えられます。"))

    @staticmethod
    def _percent(opacity: float) -> str:
        """
        Format an opacity as a whole percentage.
        不透明度を整数の百分率の文字列にする。
        """
        return f"{int(round(float(opacity) * 100))}%"

    def set_selected(self, selected: bool) -> None:
        """
        Mark the row as the layer the tools act on, or clear the mark.
        この行を、ツールが働くレイヤーとして示す。または、その表示を消す。
        """
        self.name_label.configure(background=SELECTED_ROW_COLOR if selected else "")

    def set_stale(self, stale: bool) -> None:
        """
        Mark the layer as not computed again since its source changed, or not.
        レイヤーを、元になるものが変わってから計算し直していないものとして示す。
        または、その表示を消す。
        """
        self.stale_var.set(_("古い") if stale else "")

    def _on_visible(self) -> None:
        """
        Pass the check box's state to the window.
        チェックボックスの状態をウィンドウへ伝える。
        """
        self._app.set_layer_visible(self._key, self.visible_var.get())

    def _on_opacity(self, _value: str) -> None:
        """
        Pass the slider's value to the window.
        スライダーの値をウィンドウへ伝える。
        """
        opacity = float(self.opacity_var.get())
        self.percent_var.set(self._percent(opacity))
        self._app.set_layer_opacity(self._key, opacity)

    def _on_press(self, _event) -> None:
        """
        Start a press on this row.
        この行への押下を始める。
        """
        self._app.begin_row_drag(self._key)

    def _on_motion(self, event) -> None:
        """
        Follow the pointer while this row is dragged.
        この行のドラッグ中、ポインタを追う。
        """
        self._app.drag_row_to(event.y_root)

    def _on_release(self, _event) -> None:
        """
        Drop this row where the pointer is, or select its layer.
        ポインタの位置にこの行を入れる。または、そのレイヤーを選ぶ。
        """
        self._app.end_row_drag()


class ParamsDialog(tk.Toplevel):
    """
    Modal dialog for the analysis settings of one stage.
    1 つの段の解析設定を編集するモーダルダイアログ。

    Each row shows a `ProcParams` field by its name, the value to edit, and the
    description `stage_fields` gives. Accepting hands the settings to
    `App.apply_stage_settings`, which checks them; settings that are refused
    leave the dialog open with the reason shown.
    各行は、`ProcParams` のフィールドの名前、編集する値、`stage_fields` が与える説明を
    表示する。確定すると、設定を `App.apply_stage_settings` に渡し、そこで検査する。
    受け付けられなかった設定では、理由を表示してダイアログを開いたままにする。
    """

    def __init__(self, app: App, stage: str, params: ProcParams) -> None:
        """
        Build the dialog for one stage.
        1 つの段のダイアログを作る。

        Parameters
        ----------
        app
            Window that takes the settings over.
            設定を取り込むウィンドウ。
        stage
            `STAGE_BACKGROUND` or `STAGE_BINARIZE`.
            `STAGE_BACKGROUND` または `STAGE_BINARIZE`。
        params
            The settings as they stand.
            現在の設定。
        """
        super().__init__(app)
        self.title(_("{stage} の設定").format(stage=stage_label(stage)))
        self.transient(app)
        self._app = app
        self._stage = stage
        self._params = params
        self._vars: Dict[str, tk.Variable] = {}

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        for row, (field, description, choices) in enumerate(stage_fields(stage)):
            value = getattr(params, field)
            # The field name is the key `_param.json` stores; it is shown as
            # it is, not translated.
            # フィールド名は `_param.json` に保存されるキーである。翻訳せず、
            # そのまま表示する。
            ttk.Label(body, text=field).grid(
                row=row, column=0, sticky=tk.W, padx=(0, 8), pady=3)
            if isinstance(value, bool):
                variable: tk.Variable = tk.BooleanVar(value=value)
                widget: tk.Widget = ttk.Checkbutton(body, variable=variable)
            elif choices:
                variable = tk.StringVar(value=str(value))
                widget = ttk.Combobox(
                    body, textvariable=variable, values=list(choices),
                    state="readonly", width=12)
            else:
                variable = tk.StringVar(value=str(value))
                widget = ttk.Entry(body, textvariable=variable, width=14)
            widget.grid(row=row, column=1, sticky=tk.W, pady=3)
            ttk.Label(
                body, text=description, wraplength=520, justify=tk.LEFT,
                foreground="#555",
            ).grid(row=row, column=2, sticky=tk.W, padx=(10, 0), pady=3)
            self._vars[field] = variable

        buttons = ttk.Frame(self, padding=(10, 0, 10, 10))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text=_("キャンセル"), command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text=_("OK"), command=self.on_accept).pack(
            side=tk.RIGHT, padx=(0, 6))
        self.update_idletasks()
        self.geometry("+{0}+{1}".format(app.winfo_rootx() + 60, app.winfo_rooty() + 90))
        self.grab_set()

    def values(self) -> Dict[str, Any]:
        """
        Read the entered values as the types of their fields.
        入力された値を、それぞれのフィールドの型で読む。

        Raises
        ------
        ValueError
            If a number cannot be read; the message names the field.
        """
        values: Dict[str, Any] = {}
        for field, variable in self._vars.items():
            current = getattr(self._params, field)
            entered = variable.get()
            if isinstance(current, bool):
                values[field] = bool(entered)
                continue
            text = str(entered).strip()
            try:
                if isinstance(current, int):
                    values[field] = int(text)
                elif isinstance(current, float):
                    values[field] = float(text)
                else:
                    values[field] = text
            except ValueError:
                raise ValueError(_("{field} の値を読み取れません: {value}").format(
                    field=field, value=text)) from None
        return values

    def on_accept(self) -> None:
        """
        Hand the entered settings to the window and close when they are taken.
        入力された設定をウィンドウに渡し、受け付けられたら閉じる。
        """
        try:
            params = replace(self._params, **self.values())
        except ValueError as exc:
            messagebox.showerror(_("入力エラー"), str(exc), parent=self)
            return
        problem = self._app.apply_stage_settings(self._stage, params)
        if problem:
            messagebox.showerror(_("入力エラー"), problem, parent=self)
            return
        self.destroy()


def main() -> None:
    """
    Start the bundle editor, opening the bundle named on the command line.
    Bundle Editor を起動し、コマンドラインで指定されたバンドルを開く。

    The first argument is a bundle file (`afm_nanofiber_analyzer.plugin_launch`);
    without one the window opens empty.
    最初の引数はバンドルファイル（`afm_nanofiber_analyzer.plugin_launch`）。引数が
    無ければ空のウィンドウで開く。
    """
    app = App()
    if len(sys.argv) > 1:
        # Open once the window is on screen: opening can raise a warning
        # dialog, which needs the window behind it.
        # ウィンドウの表示後に開く。開くときに警告のダイアログが出ることがあり、
        # その背後にウィンドウが要るためである。
        call_when_shown(app, app.open_bundle, sys.argv[1])
    app.mainloop()


# Run the GUI only when this module is executed directly.
if __name__ == "__main__":
    main()
