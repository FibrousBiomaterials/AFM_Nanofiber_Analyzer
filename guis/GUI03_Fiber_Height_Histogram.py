"""
Interactive morphology histogram GUI for AFM nanofiber analysis.
AFM ナノファイバー解析用の形態パラメータヒストグラム GUI。

Loads ``.b2z`` bundles produced by the image preprocessor and compares the
distribution of one morphological quantity — height, contour length, kink
angle, or kink density — across user-defined groups.
画像前処理 GUI が出力した ``.b2z`` バンドルを読み込み、形態パラメータ
（高さ・輪郭長・キンク角・キンク密度）のいずれか 1 つの分布を、ユーザー定義
グループ間で比較する。

The aggregation unit selects what counts as one sample: a skeleton pixel, a
fiber, one kink, or a whole image. This matters for reporting because pooled
skeleton pixels are not independent observations — a long fiber contributes
more pixels than a short one, and neighboring pixels of one fiber repeat the
same object — so group comparisons should also be inspected per fiber or per
image.
集計単位は「1 標本」を何と数えるかを選ぶ（骨格画素・ファイバー 1 本・キンク
1 点・画像 1 枚）。骨格画素をまとめた分布は独立観測ではなく（長いファイバー
ほど多くの画素を出し、同一ファイバーの隣接画素は同じ対象の繰り返しになる）、
群間比較ではファイバー単位・画像単位でも確認する必要があるため、報告上この
区別が重要になる。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Main.py がこのファイルを読み込む際、AST（構文解析）でこの辞書を取得してランチャー画面に表示する。
# Values must remain plain string literals because they are passed to literal_eval.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Fiber Height Histogram",
    "description": (
        "AFMで撮影したナノファイバーの形態パラメータのヒストグラムをGUIで作成するプログラムです。\n"
        "入力データには、Image Preprocessor が出力する .b2z バンドルファイルが必要です。\n"
        "計測量は height（高さ）、contour length（輪郭長）、kink angle（キンク角）、kink density（キンク密度）から選べます。高さはバンドル内の calibrated（BG補正済み画像）と skeletonized（細線化画像）から収集し、輪郭長・キンク量はファイバー追跡結果から算出します。\n"
        "集計単位（骨格画素・ファイバー・キンク・画像）を切り替えられるため、画素をまとめた分布だけでなく、ファイバー単位・画像単位の分布としても比較できます。\n"
        "複数のデータ群（グループ）を登録すると、グループごとに別々のヒストグラムを作成し、縦並び・重ね表示で比較表示できます。中央値・四分位範囲・平均・標準偏差・最頻値と、標本数の内訳を併記します。"
    )
}

# ===== Standard library =====
import os
import re
import csv
import uuid
import queue
import threading
import traceback
from datetime import datetime

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== GUI libraries =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import colorchooser

# ===== Plotting libraries =====
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ===== Project libraries =====
from lib.blosc2_io import BUNDLE_EXT
from lib.group_compare import compare_groups
from lib.measure import (
    DEFAULT_CURVATURE_WINDOW_NM,
    collect_fiber_curvature, collect_fiber_stats, collect_fiber_stats_from_csv,
    collect_skeleton_height_profiles, fiber_kink_angle, fiber_kink_density,
    skeleton_height_values,
)
from lib.translator import _
from lib.ui_tools import (
    apply_window_size, setup_matplotlib_style, save_figure_with_dialog,
    setup_ttk_theme,
    save_text_widget_log, create_scrolled_text, create_scrolled_treeview,
    drain_ui_queue, save_csv_with_dialog, bind_mousewheel_scroll,
    UNIT_MICROMETER, ToolTip,
    UnconfirmedEntryMixin, LogMixin,
)


# ===== Measured quantities and aggregation units =====
# These are internal state keys and plot text, so they stay fixed English and
# are never wrapped with _(): they name axes, CSV columns, and exported labels.
# これらは内部状態キー兼プロット表記のため、固定英語のままとし _() を付けない。
# 軸ラベル・CSV 列・出力ラベルに使われる。
PARAM_HEIGHT = "height"
PARAM_LENGTH = "contour length"
PARAM_KINK_ANGLE = "kink angle"
PARAM_KINK_DENSITY = "kink density"
PARAM_STRAIGHTNESS = "straightness"
PARAM_CURVATURE = "curvature"

UNIT_PIXEL = "pixel"
UNIT_LENGTH = "length"
UNIT_KINK = "kink"
UNIT_FIBER = "fiber"
UNIT_IMAGE = "image"

# Input types. Bundles carry the images, so they support every aggregation
# unit and can have manual exclusions applied from their sidecars. A folder of
# GUI04 fiber CSVs carries only per-fiber rows, but those rows are the fibers a
# person looked at and accepted in the fiber tracker, which is the only way to
# curate a dense network where nearly every fiber touches a crossing.
# 入力タイプ。バンドルは画像を含むため全ての集計単位に対応し、サイドカーからの
# 手動除外も適用できる。GUI04 のファイバー CSV のフォルダはファイバー単位の行
# しか持たないが、その行はファイバートラッカーで人が見て採用したファイバーで
# あり、ほぼ全てのファイバーが交差に接する密なネットワークをキュレーションする
# 唯一の手段である。
INPUT_BUNDLE = "bundle"
INPUT_FIBER_CSV = "fiber csv"

INPUT_ORDER = (INPUT_BUNDLE, INPUT_FIBER_CSV)

# Suffix each input type is discovered by inside a registered folder.
# 登録フォルダ内で各入力タイプを検出するための接尾辞。
INPUT_SUFFIXES = {
    INPUT_BUNDLE: BUNDLE_EXT,
    INPUT_FIBER_CSV: "_fibers.csv",
}

# Aggregation units that need the bundle's images and tracks, so they are not
# offered when the input is a per-fiber CSV.
# バンドルの画像とトラックを必要とする集計単位。入力がファイバー単位の CSV の
# ときは提供しない。
BUNDLE_ONLY_UNITS = (UNIT_PIXEL, UNIT_LENGTH)

# Quantities that need something only a bundle carries. Curvature is measured
# by walking the traced track, which a per-fiber CSV does not store.
# バンドルにしか無い情報を必要とする計測量。曲率は追跡トラックをたどって測る
# 必要があるが、ファイバー単位の CSV にはトラックが保存されていない。
BUNDLE_ONLY_PARAMS = (PARAM_CURVATURE,)

# Plot types. The histogram shows the shape of one distribution, the ECDF
# compares several without depending on a bin width, and the box summarises
# each group's median and quartiles side by side.
# プロットの種類。ヒストグラムは 1 つの分布の形を示し、ECDF はビン幅に依存せず
# 複数を比較でき、箱ひげは各群の中央値と四分位数を並べて要約する。
PLOT_HISTOGRAM = "histogram"
PLOT_ECDF = "ECDF"
PLOT_BOX = "box"

PLOT_TYPES = (PLOT_HISTOGRAM, PLOT_ECDF, PLOT_BOX)

# Aggregation units whose samples support a between-group test. The others are
# excluded on principle rather than for convenience: skeleton pixels and
# length-weighted points are not independent observations of a specimen, and
# several kinks come from one fiber, so a p-value over them measures how
# finely the images were sampled instead of whether the specimens differ.
# 群間検定を適用できる集計単位。他を外すのは便宜ではなく原理による。骨格画素と
# 長さ重み付けの点は試料の独立観測ではなく、複数のキンクは 1 本のファイバーから
# 来る。それらに対する p 値は、試料が異なるかどうかではなく、画像をどれだけ
# 細かくサンプリングしたかを測ってしまう。
TESTABLE_UNITS = (UNIT_FIBER, UNIT_IMAGE)

# Inverse micrometer in two spellings, because no single one renders in both
# places it is needed. "1/µm" written straight after a number reads as part of
# the number ("3.40 1/µm"), so figures use the exponent form; but the plain
# Unicode superscript minus (U+207B) is missing from Arial, which this
# project's Matplotlib style asks for first, and renders as a blank box.
# Matplotlib mathtext draws the exponent correctly by taking that one glyph
# from its own math font, so figures use the mathtext form and everything
# outside Matplotlib — Tk labels, CSV headers — uses the plain form.
# µm の逆数を 2 通りで持つ。両方の用途で成立する表記が 1 つも無いため。"1/µm" は
# 数値の直後だと数値の一部に見える（"3.40 1/µm"）ので図では指数表記を使いたいが、
# 素の Unicode 上付きマイナス (U+207B) は本プロジェクトの Matplotlib スタイルが
# 最優先に指定する Arial に存在せず、空の箱として描画される。Matplotlib の
# mathtext はこのグリフだけを自前の数式フォントから取って正しく描くため、図では
# mathtext 形式を、Matplotlib 外（Tk ラベル・CSV ヘッダ）では素の形式を使う。
UNIT_PER_MICROMETER = "1/" + UNIT_MICROMETER
UNIT_PER_MICROMETER_PLOT = r"$\mathregular{\mu m^{-1}}$"

# Plural nouns used when reporting the sample size of each aggregation unit.
# The length unit measures a contour length rather than counting objects, so
# its "count" is reported in micrometers.
# 各集計単位の標本量を表示するときに使う複数形の名詞。length 単位は個数では
# なく輪郭長を測るため、その「数」は µm で報告する。
UNIT_NOUNS = {
    UNIT_PIXEL: "px",
    UNIT_LENGTH: UNIT_MICROMETER + " of contour",
    UNIT_KINK: "kinks",
    UNIT_FIBER: "fibers",
    UNIT_IMAGE: "images",
}

# Aggregation units whose sample size is a physical length, not a count.
# They are formatted with a decimal and a unit instead of a thousands-grouped
# integer.
# 標本量が個数ではなく物理長になる集計単位。3 桁区切りの整数ではなく、小数と
# 単位を付けて整形する。
LENGTH_WEIGHTED_UNITS = (UNIT_LENGTH,)

# Below this many samples a histogram shows no distribution shape, so the run
# says so instead of letting a two-bar plot pass for one. It is a readability
# threshold for the figure, not a statistical rule; the summary statistics are
# reported at any sample size.
# これ未満の標本数ではヒストグラムが分布の形を示さないため、2 本の棒を分布として
# 通してしまう前にその旨を伝える。図の可読性のしきい値であって統計的な規則では
# なく、要約統計量は標本数によらず報告する。
MIN_SAMPLES_FOR_SHAPE = 8

# Per-quantity display metadata and default histogram range.
# The first entry of "units" is the default aggregation unit. "value_unit" is
# the plain-text unit for Tk labels and CSV headers; "value_unit_plot" is the
# spelling Matplotlib draws and defaults to "value_unit" when the two agree.
# The ranges are starting points for typical nanocellulose scans, not physical
# limits: fibril heights are a few nm, contour lengths hundreds of nm to a few
# µm, and kink angles are interior angles so they approach 180 deg for a
# straight contour.
# 計測量ごとの表示メタデータと既定ヒストグラム範囲。
# "units" の先頭要素が既定の集計単位。"value_unit" は Tk ラベルと CSV ヘッダ用の
# 素の単位表記、"value_unit_plot" は Matplotlib が描画する表記で、両者が一致する
# 場合は "value_unit" が既定値になる。範囲は典型的なナノセルロース試料向けの
# 初期値であって物理的な上限下限ではない（フィブリル高さは数 nm、輪郭長は
# 数百 nm〜数 µm、キンク角は内角なので直線的な輪郭ほど 180 度に近づく）。
PARAM_SPECS = {
    PARAM_HEIGHT: {
        "slug": "height",
        "value_unit": "nm",
        "axis_label": "height (nm)",
        "units": (UNIT_PIXEL, UNIT_LENGTH, UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 10.0, 0.2),
    },
    PARAM_LENGTH: {
        "slug": "contour_length",
        "value_unit": "nm",
        "axis_label": "contour length (nm)",
        "units": (UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 3000.0, 100.0),
    },
    PARAM_KINK_ANGLE: {
        "slug": "kink_angle",
        "value_unit": "degree",
        "axis_label": "kink angle (degree)",
        "units": (UNIT_KINK, UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 180.0, 5.0),
    },
    PARAM_STRAIGHTNESS: {
        "slug": "straightness",
        "value_unit": "-",
        # Dimensionless, so the label carries no unit; spelling the definition
        # out here overflowed the axes on a box plot, and it belongs in the
        # documentation rather than on every figure.
        # 無次元量のためラベルに単位は付けない。定義を書き下すと箱ひげの軸から
        # はみ出したうえ、その説明は毎回の図ではなくドキュメントに属する。
        "axis_label": "straightness",
        "units": (UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 1.02, 0.02),
    },
    PARAM_CURVATURE: {
        "slug": "curvature",
        "value_unit": "rad/" + UNIT_MICROMETER,
        "axis_label": "curvature (rad/" + UNIT_MICROMETER + ")",
        "units": (UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 20.0, 0.5),
    },
    PARAM_KINK_DENSITY: {
        "slug": "kink_density",
        "value_unit": UNIT_PER_MICROMETER,
        "value_unit_plot": UNIT_PER_MICROMETER_PLOT,
        "axis_label": "kink density (" + UNIT_PER_MICROMETER_PLOT + ")",
        "units": (UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 20.0, 0.5),
    },
}

# Fill in the Matplotlib spelling for every quantity whose unit needs no
# special drawing, so lookups never have to test for the key.
# 特別な描画を要しない計測量については Matplotlib 用の表記を埋めておき、参照側が
# キーの有無を判定しなくて済むようにする。
for _spec in PARAM_SPECS.values():
    _spec.setdefault("value_unit_plot", _spec["value_unit"])

# Order shown in the quantity selector.
# 計測量セレクタに表示する順序。
PARAM_ORDER = (
    PARAM_HEIGHT, PARAM_LENGTH, PARAM_STRAIGHTNESS, PARAM_CURVATURE,
    PARAM_KINK_ANGLE, PARAM_KINK_DENSITY,
)


def _fiber_value(stat, param: str):
    """
    Return the per-fiber value of one measured quantity, or None if undefined.
    1 本のファイバーにおける計測量の値を返す。定義できない場合は None。

    Parameters
    ----------
    stat
        Per-fiber statistics row from `lib.measure.compute_fiber_stats`.
        `lib.measure.compute_fiber_stats` が返すファイバー単位の統計行。
    param
        Measured-quantity key from `PARAM_SPECS`.
        `PARAM_SPECS` の計測量キー。

    Returns
    -------
    float or None
        Fiber-level value, or None when the fiber carries no such value.
        ファイバー単位の値。その値を持たないファイバーでは None。

    Notes
    -----
    A fiber represents its height and kink angle by the median of the values
    sampled along it, so one fiber contributes exactly one sample regardless
    of how long it is. Kink density is kinks per micrometer of contour, which
    is the length-normalized form used to compare fibers of different length;
    a fiber with no detected kink is a valid zero, not a missing value.
    ファイバーの高さとキンク角は、そのファイバー上でサンプリングした値の
    中央値で代表させる。これにより、長さにかかわらず 1 本が 1 標本になる。
    キンク密度は輪郭長 1 µm あたりのキンク数で、長さの異なるファイバーを
    比較するための長さ正規化形である。キンクが検出されなかったファイバーは
    欠測ではなく 0 という有効な値として扱う。
    """
    if param == PARAM_HEIGHT:
        return float(stat.height_median_nm)
    if param == PARAM_LENGTH:
        return float(stat.length_nm)
    # Both come from lib.measure so the value GUI04 shows beside a fiber is
    # the value histogrammed here; an undefined one contributes nothing.
    # どちらも lib.measure から得る。GUI04 がファイバーの横に表示する値と、ここで
    # ヒストグラム化する値を一致させるため。未定義の値は寄与しない。
    if param == PARAM_KINK_ANGLE:
        value = fiber_kink_angle(stat)
        return None if not np.isfinite(value) else value
    if param == PARAM_KINK_DENSITY:
        value = fiber_kink_density(stat)
        return None if not np.isfinite(value) else value
    if param == PARAM_STRAIGHTNESS:
        # A CSV written before straightness existed leaves the field
        # undefined, and those fibers contribute nothing rather than a zero.
        # straightness が存在する前に書かれた CSV ではこの項目が未定義であり、
        # そうしたファイバーは 0 ではなく「寄与なし」として扱う。
        value = float(stat.straightness)
        return None if not np.isfinite(value) else value
    return None


def _fiber_samples(stat, param: str, unit: str) -> list:
    """
    Return the samples one fiber contributes for a quantity and unit.
    ある計測量・集計単位において 1 本のファイバーが出す標本を返す。

    Parameters
    ----------
    stat
        Per-fiber statistics row from `lib.measure.compute_fiber_stats`.
        `lib.measure.compute_fiber_stats` が返すファイバー単位の統計行。
    param
        Measured-quantity key from `PARAM_SPECS`.
        `PARAM_SPECS` の計測量キー。
    unit
        Aggregation-unit key; ``UNIT_KINK`` yields every kink of the fiber.
        集計単位キー。``UNIT_KINK`` ではファイバー内の全キンクを返す。

    Returns
    -------
    list of float
        Zero or more samples, in track order for kink-level samples.
        0 個以上の標本。キンク単位では追跡順に並ぶ。
    """
    if unit == UNIT_KINK:
        return [float(a) for a in stat.kink_angles_deg]
    value = _fiber_value(stat, param)
    return [] if value is None else [value]


def _summary_stats(values: np.ndarray, weights=None) -> dict:
    """
    Return mean, standard deviation, and quartiles of a sample.
    標本の平均・標準偏差・四分位数を返す。

    Parameters
    ----------
    values
        Sample values in the unit of the measured quantity.
        計測量の単位で表した標本値。
    weights
        Per-value weights, or None for an unweighted sample. Used by the
        length-weighted aggregation, where a weight is the contour length in
        nanometers that its value represents.
        値ごとの重み。重みなしの標本では None。長さ重み付け集計で使い、その
        場合の重みは各値が代表する輪郭長 (nm)。

    Returns
    -------
    dict
        Keys ``mean``, ``std``, ``q1``, ``median``, ``q3``.
        キーは ``mean``, ``std``, ``q1``, ``median``, ``q3``。

    Notes
    -----
    The unweighted branch calls NumPy directly rather than passing weights of
    one to the weighted branch. The two quantile definitions do not agree
    exactly, so routing every sample through the weighted path would silently
    move the numbers of the existing unweighted modes.
    重みなしの分岐では、1 の重みを weighted 側へ渡すのではなく NumPy を直接
    呼ぶ。両者の分位数の定義は厳密には一致しないため、すべてを weighted 経路に
    通すと既存の重みなしモードの数値が黙って変わってしまう。
    """
    if weights is None:
        q1, median, q3 = (
            float(v) for v in np.percentile(values, [25.0, 50.0, 75.0])
        )
        return {
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "q1": q1, "median": median, "q3": q3,
        }

    total = float(weights.sum())
    mean = float(np.sum(values * weights) / total)
    variance = float(np.sum(weights * (values - mean) ** 2) / total)
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights)
    # Position each value at the midpoint of the weight interval it occupies,
    # the standard weighted-percentile convention.
    # 各値をそれが占める重み区間の中点に配置する。重み付きパーセンタイルの
    # 標準的な定義。
    positions = (cumulative - 0.5 * sorted_weights) / total
    q1, median, q3 = (
        float(v) for v in np.interp([0.25, 0.5, 0.75], positions, sorted_values)
    )
    return {
        "mean": mean,
        "std": float(np.sqrt(variance)),
        "q1": q1, "median": median, "q3": q3,
    }


def _format_sample_size(value: float, unit: str) -> str:
    """
    Format a sample size for the aggregation unit that produced it.
    集計単位に応じて標本量を整形する。

    Parameters
    ----------
    value
        Sample size: a count for counted units, a contour length in
        nanometers for length-weighted units.
        標本量。個数を数える単位では件数、長さ重み付けの単位では輪郭長 (nm)。
    unit
        Aggregation-unit key.
        集計単位キー。

    Returns
    -------
    str
        Grouped integer for counts, or a micrometer value for lengths.
        個数は 3 桁区切りの整数、長さは µm 表記。
    """
    if unit in LENGTH_WEIGHTED_UNITS:
        return "{0:,.1f}".format(value / 1000.0)
    return "{0:,}".format(int(value))


def _blank_if_nan(value: float, fmt: str = "{0:.6g}") -> str:
    """
    Format a number for CSV, leaving an undefined one as an empty cell.
    CSV 用に数値を整形し、未定義の値は空セルにする。

    Parameters
    ----------
    value
        Number to format; NaN means the quantity was not computed.
        整形する数値。NaN は計算されなかったことを意味する。
    fmt
        Format string applied to a finite value.
        有限値に適用する書式文字列。

    Returns
    -------
    str
        Formatted number, or an empty string. An empty cell reads as missing
        in every spreadsheet and analysis tool, whereas "nan" or 0 would be
        taken for a measured value.
        整形済みの数値、または空文字列。空セルはどの表計算・解析ツールでも欠測
        として読まれるが、"nan" や 0 は計測値と取り違えられる。
    """
    return "" if not np.isfinite(value) else fmt.format(value)


def _sample_size_csv_value(value: float, unit: str):
    """
    Return a sample size as a bare number for CSV output.
    CSV 出力用に、標本量を桁区切りなしの数値として返す。

    Parameters
    ----------
    value
        Sample size in the same terms as `_format_sample_size` takes.
        `_format_sample_size` と同じ意味の標本量。
    unit
        Aggregation-unit key.
        集計単位キー。

    Returns
    -------
    int or str
        Plain integer count, or a micrometer value without thousands
        separators, which a spreadsheet or a script would otherwise read as
        text rather than as a number.
        素の整数の件数、または 3 桁区切りを含まない µm 値。区切りが入ると
        表計算やスクリプトが数値ではなく文字列として読んでしまう。
    """
    if unit in LENGTH_WEIGHTED_UNITS:
        return "{0:.4f}".format(value / 1000.0)
    return int(value)


def _default_color_palette():
    """
    Return the default group-color palette.
    グループ色のデフォルトパレットを返す。

    Combines Matplotlib categorical palettes and removes duplicate RGB tuples.
    Matplotlib のカテゴリカル配色を結合し、重複する RGB タプルを除く。
    """
    base = list(plt.get_cmap("tab10").colors) + list(plt.get_cmap("tab20").colors)
    out = []
    seen = set()
    for c in base:
        key = tuple(round(v, 4) for v in c)
        if key not in seen:
            seen.add(key)
            out.append(matplotlib.colors.to_hex(c))
    return out


def _color_for_index(idx: int) -> str:
    """
    Return a stable display color for a group index.
    グループ番号に対応する安定した表示色を返す。

    Indices beyond the categorical palette are sampled in HSV space so later
    groups still receive distinguishable colors.
    カテゴリカル配色を超えた番号では HSV 空間を等間隔にサンプリングし、
    後続グループにも識別しやすい色を割り当てる。
    """
    palette = _default_color_palette()
    if idx < len(palette):
        return palette[idx]
    # Cycle through 12 HSV hues after the fixed palette to keep colors readable.
    # 固定パレットを超えた後は 12 個の HSV 色相を循環させ、視認性を保つ。
    h = ((idx - len(palette)) % 12) / 12.0
    rgb = matplotlib.colors.hsv_to_rgb([h, 0.7, 0.9])
    return matplotlib.colors.to_hex(rgb)


def _sanitize_filename(name: str) -> str:
    """
    Return a filesystem-safe stem for CSV exports.
    CSV 出力に使える安全なファイル名 stem を返す。
    """
    s = re.sub(r'[\\/:\*\?"<>\|]', "_", name)
    s = s.strip().strip(".")
    return s if s else "group"


class Group:
    """
    Store one user-defined group of input folders.
    ユーザーが定義した入力フォルダ群を保持するクラス。

    Attributes
    ----------
    id
        Stable internal identifier used as the Treeview item ID.
        Treeview のアイテム ID として使う安定した内部識別子。
    name
        User-editable group name shown in the GUI and exported files.
        GUI と出力ファイルに表示されるユーザー編集可能なグループ名。
    color
        Histogram display color as a Matplotlib/Tk-compatible hex string.
        Matplotlib と Tk で扱える hex 文字列形式のヒストグラム表示色。
    folder_paths
        Registered folder paths for this group; duplicates are not allowed
        within the same group.
        このグループに登録されたフォルダパス。同一グループ内の重複は許可しない。
    folder_pairinfo
        Per-folder scan results containing candidate bundle counts and
        discovery warnings. Bundle contents are validated during loading.
        候補バンドル数と探索時の警告を保持するフォルダ単位のスキャン結果。
        バンドル内容は読み込み時に検証する。
    """

    def __init__(self, name: str, color: str) -> None:
        self.id = uuid.uuid4().hex
        self.name = name
        self.color = color
        self.folder_paths = []
        self.folder_pairinfo = {}

    def total_pairs(self) -> int:
        """
        Return the total candidate bundle count for this group.
        このグループが持つ候補バンドル総数を返す。
        """
        return sum(self.folder_pairinfo.get(p, {}).get("pairs", 0) for p in self.folder_paths)

    def total_missing(self) -> int:
        """
        Return the total warning or missing-item count for this group.
        このグループが持つ警告または欠損メッセージの総数を返す。
        """
        return sum(len(self.folder_pairinfo.get(p, {}).get("missing", [])) for p in self.folder_paths)


class App(tk.Tk, UnconfirmedEntryMixin, LogMixin):
    """
    Main window for grouped AFM nanofiber morphology histograms.
    AFM ナノファイバーの形態パラメータヒストグラムをグループ別に作成する
    メインウィンドウ。

    Attributes
    ----------
    groups
        Registered groups; order controls plotting order.
        登録済みグループ。順序は描画順序を決める。
    ui_queue
        Queue used to pass worker-thread results back to Tk's main thread.
        ワーカースレッドの結果を Tk メインスレッドへ渡すキュー。
    param
        Committed measured-quantity key from `PARAM_SPECS`.
        確定済みの計測量キー（`PARAM_SPECS`）。
    unit
        Committed aggregation-unit key deciding what one sample counts as.
        確定済みの集計単位キー。1 標本を何と数えるかを決める。
    min_h
        Lower histogram edge, in the unit of the selected quantity.
        ヒストグラム下限値（選択中の計測量の単位）。
    max_h
        Upper histogram edge, in the unit of the selected quantity.
        ヒストグラム上限値（選択中の計測量の単位）。
    step
        Histogram bin width, in the unit of the selected quantity.
        ヒストグラムのビン幅（選択中の計測量の単位）。
    fig_w
        Figure width in inches.
        Figure の横幅 (inch)。
    fig_h
        Figure height in inches; stacked mode treats this as per-subplot height.
        Figure の縦幅 (inch)。縦並び表示では 1 サブプロット分の高さとして扱う。
    """

    # Input bundles come from GUI01 and contain both calibrated and skeletonized arrays.
    # 入力は GUI01_Image_Preprocessor が出力する .b2z バンドル形式で、
    # calibrated / skeletonized が同一ファイルに含まれる。
    BUNDLE_SUFFIX = BUNDLE_EXT

    # Internal display-mode keys stay untranslated; UI labels go through gettext.
    # 表示モードの内部キーは翻訳せず、UI 表示のみ _() 経由で行う。
    MODE_STACK = "stack"
    MODE_OVERLAY = "overlay"

    def __init__(self) -> None:
        """
        Initialize the histogram window, state, controls, and default group.
        ヒストグラムウィンドウ、状態、コントロール、既定グループを初期化する。
        """
        super().__init__()
        self.title(PLUGIN_INFO["name"])

        setup_matplotlib_style(font_size=15)

        self._clam_bg = setup_ttk_theme(self)

        apply_window_size(self, 1450, 850, min_w=1100, min_h=700)

        self.groups = []
        self._last_results = None
        self._last_edges = None
        self._last_param = None
        self._last_unit = None
        self._last_comparisons = []
        self._has_result = False

        self.ui_queue = queue.Queue()
        self.is_running = False

        # The measured quantity and the aggregation unit drive both the worker
        # and every axis/heading label, so they are held as committed state
        # rather than read from the widgets at draw time.
        # 計測量と集計単位はワーカーと全ての軸・見出しラベルの両方を決めるため、
        # 描画時にウィジェットから読むのではなく確定済み状態として保持する。
        self.param = PARAM_HEIGHT
        self.unit = PARAM_SPECS[PARAM_HEIGHT]["units"][0]

        # Input type and whether a bundle's manual exclusions are honored.
        # Applying them is the default: a sidecar exists only because someone
        # curated that dataset, and ignoring it would silently analyze objects
        # they had already rejected.
        # 入力タイプと、バンドルの手動除外を尊重するかどうか。適用を既定とする。
        # サイドカーは誰かがそのデータセットをキュレーションしたときにのみ存在
        # するため、無視すると既に棄却された対象を黙って解析することになる。
        self.input_mode = INPUT_BUNDLE

        # Arc length the curvature estimator turns over. Committed like the
        # histogram range so an unconfirmed edit cannot reach a run.
        # 曲率推定が回転角を測る弧長。ヒストグラム範囲と同様に確定値として保持し、
        # 未確定の編集が実行へ届かないようにする。
        self.curvature_window = DEFAULT_CURVATURE_WINDOW_NM

        # Keep committed values separate from Entry text so edits can be confirmed with Enter.
        # Entry の textvariable とは別に確定済みの値を保持し、Enter 確定で反映する。
        self.min_h, self.max_h, self.step = PARAM_SPECS[PARAM_HEIGHT]["default_range"]

        # In stacked mode, fig_h is interpreted as the height of one subplot.
        # 縦並び時は fig_h を 1 サブプロット分の高さとして扱い、後で N 倍する。
        self.fig_w = 6.0
        self.fig_h = 3.0
        self.label_fs = 15.0
        self.tick_fs  = 15.0
        self.ann_fs   = 15.0
        self.group_name_fs = 15.0

        self._init_unconfirmed_registry()

        self._build_ui()

        g = self._add_group_internal(self._next_default_name())
        # Select the initial group on startup so folder controls are immediately usable,
        # matching the behavior of on_add_group.
        # 起動時に初期グループを選択状態にし、フォルダ操作を即利用可能にする（on_add_group と挙動を揃える）。
        self.tree.selection_set(g.id)
        self.tree.focus(g.id)

        self._log_initial_message()

    def _build_ui(self) -> None:
        """
        Build the histogram controls, tree view, plot canvas, and log area.
        ヒストグラム操作部、Treeview、描画キャンバス、ログ領域を構築する。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=3)

        # Build each pane top-to-bottom; creation order is preserved.
        self._build_left_pane(left)
        self._build_right_pane(right)

        self._update_summary()

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        """
        Build the left pane: group/folder tree, result table, and log area.
        左ペイン（グループ/フォルダツリー・結果表・ログ領域）を構築する。
        """
        self._build_group_panel(parent)
        self._build_result_panel(parent)
        self._build_comparison_panel(parent)
        self._build_log_panel(parent)

    def _build_group_panel(self, parent: ttk.Frame) -> None:
        """
        Build the group/folder controls, tree view, and summary label.
        グループ/フォルダ操作部・ツリー・サマリラベルを構築する。
        """
        frm_group = ttk.Frame(parent)
        frm_group.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        grp_btn_row = ttk.Frame(frm_group)
        grp_btn_row.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.btn_add_group = ttk.Button(grp_btn_row, text=_("グループ追加"), command=self.on_add_group)
        self.btn_add_group.pack(side=tk.LEFT)

        self.btn_remove_group = ttk.Button(grp_btn_row, text=_("グループ削除"), command=self.on_remove_group)
        self.btn_remove_group.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_move_up = ttk.Button(grp_btn_row, text=_("↑"), width=3, command=lambda: self.on_move_group(-1))
        self.btn_move_up.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_move_down = ttk.Button(grp_btn_row, text=_("↓"), width=3, command=lambda: self.on_move_group(+1))
        self.btn_move_down.pack(side=tk.LEFT, padx=(2, 0))

        self.btn_add_folder = ttk.Button(grp_btn_row, text=_("フォルダ追加"), command=self.on_add_folder)
        self.btn_add_folder.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_remove_folder = ttk.Button(grp_btn_row, text=_("フォルダ削除"), command=self.on_remove_folder)
        self.btn_remove_folder.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_clear_all = ttk.Button(grp_btn_row, text=_("全クリア"), command=self.on_clear_all)
        self.btn_clear_all.pack(side=tk.LEFT, padx=(6, 0))

        tree_row = ttk.Frame(frm_group)
        tree_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 4))

        self.tree, _tree_sb = create_scrolled_treeview(
            tree_row,
            columns=("pairs",),
            show="tree headings",
            selectmode="browse",
            height=10,
            headings={
                "#0": _("グループ／フォルダ"),
                "pairs": _("有効バンドル数"),
            },
            column_options={
                "#0": {"width": 320, "stretch": True},
                "pairs": {"width": 120, "stretch": False, "anchor": "e"},
            },
            scrollbar_side=tk.LEFT,
        )

        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        # Bind Button-2 as well because macOS may report secondary-click that way.
        # macOS では右クリックが Button-2 として扱われる場合があるため両方バインドする。
        self.tree.bind("<Button-2>", self._on_tree_right_click)

        self.summary_var = tk.StringVar(
            value=_("グループ数: {g} / 有効バンドル総数: {p} / 欠損: {m}").format(g=0, p=0, m=0)
        )
        ttk.Label(frm_group, textvariable=self.summary_var).pack(anchor="w", padx=6, pady=(0, 6))

    def _build_result_panel(self, parent: ttk.Frame) -> None:
        """
        Build the per-group statistics result table and its save button.
        グループ別統計結果テーブルと保存ボタンを構築する。
        """
        frm_res = ttk.Frame(parent)
        frm_res.pack(fill=tk.BOTH, expand=False, padx=4, pady=4)

        res_btn_row = ttk.Frame(frm_res)
        res_btn_row.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.btn_save_stats = ttk.Button(
            res_btn_row, text=_("統計値を保存"),
            command=self.on_save_stats, state=tk.DISABLED,
        )
        self.btn_save_stats.pack(side=tk.LEFT)

        # One caption carries the quantity, its unit, and the sample unit, so
        # the value columns do not each have to repeat the unit. Repeating it
        # widened the table enough to push the paned-window sash and shrink
        # the plot area.
        # 計測量・単位・集計単位はこのキャプションにまとめ、各数値列で単位を
        # 繰り返さない。列ごとに単位を入れると表が広がり、ペインの仕切りが
        # 動いてプロット領域が狭くなってしまう。
        self.result_caption_var = tk.StringVar()
        ttk.Label(res_btn_row, textvariable=self.result_caption_var).pack(
            side=tk.LEFT, padx=(10, 0)
        )
        self._update_result_caption()

        # The tree lives in its own row so a horizontal scrollbar can sit
        # under it: the statistics row is wider than the left pane, and a
        # Treeview clips overflowing columns without any scroll affordance.
        # ツリーは専用の行に置き、その下に横スクロールバーを配置する。統計行は
        # 左ペインより横に長く、Treeview は溢れた列をスクロール手段なしに
        # 切り落としてしまうため。
        res_tree_row = ttk.Frame(frm_res)
        res_tree_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        self.result_tree, _res_sb = create_scrolled_treeview(
            res_tree_row,
            columns=("group", "median", "iqr", "mean", "std", "mode",
                     "n", "nfib", "nimg"),
            show="headings",
            height=5,
            headings=self._result_headings(self.param),
            # Widths hold the formatted values, not a unit-bearing heading:
            # the Treeview's requested width is the sum of these, and it
            # pushes the paned-window sash, so every column widened here is
            # width taken from the plot.
            # 列幅は単位付き見出しではなく整形後の値に合わせる。Treeview の要求
            # 幅はこれらの合計で、ペインの仕切りを押すため、ここで広げた分だけ
            # プロット領域が狭くなる。
            column_options={
                "group":  {"width": 100, "anchor": "w", "stretch": True},
                "median": {"width": 72, "anchor": "e", "stretch": False},
                "iqr":    {"width": 116, "anchor": "e", "stretch": False},
                "mean":   {"width": 72, "anchor": "e", "stretch": False},
                "std":    {"width": 68, "anchor": "e", "stretch": False},
                "mode":   {"width": 68, "anchor": "e", "stretch": False},
                "n":      {"width": 66, "anchor": "e", "stretch": False},
                "nfib":   {"width": 62, "anchor": "e", "stretch": False},
                "nimg":   {"width": 66, "anchor": "e", "stretch": False},
            },
            tree_pack_kwargs={
                "side": tk.LEFT, "fill": tk.BOTH, "expand": True,
            },
            scrollbar_side=tk.LEFT,
            scrollbar_pack_kwargs={"side": tk.LEFT, "fill": tk.Y},
        )

        res_hsb = ttk.Scrollbar(
            frm_res, orient=tk.HORIZONTAL, command=self.result_tree.xview,
        )
        self.result_tree.configure(xscrollcommand=res_hsb.set)
        res_hsb.pack(fill=tk.X, padx=6, pady=(0, 6))

    @staticmethod
    def _result_headings(param: str) -> dict:
        """
        Return the result-table column headings.
        結果テーブルの列見出しを返す。

        Parameters
        ----------
        param
            Measured-quantity key from `PARAM_SPECS`, reserved for headings
            that need to vary by quantity.
            `PARAM_SPECS` の計測量キー。計測量ごとに変える見出し用に受け取る。

        Returns
        -------
        dict
            Column-id to heading text mapping; headings are fixed English
            because they label exported scientific quantities. The value unit
            is not repeated per column — the caption above the table carries
            it once.
            列 ID から見出し文字列への対応。見出しは出力される科学的量の
            ラベルであるため固定英語とする。値の単位は列ごとに繰り返さず、
            表の上のキャプションで 1 回だけ示す。
        """
        return {
            "group": "Group",
            "median": "median",
            "iqr": "IQR",
            "mean": "mean",
            "std": "std",
            "mode": "mode",
            "n": "N",
            "nfib": "N fibers",
            "nimg": "N images",
        }

    def _update_result_caption(self, param: str = None, unit: str = None) -> None:
        """
        Refresh the caption naming the quantity, its unit, and the sample unit.
        計測量・単位・集計単位を示すキャプションを更新する。

        Parameters
        ----------
        param
            Quantity the table currently shows; defaults to the selection.
            表が現在示している計測量。省略時は選択中の値。
        unit
            Aggregation unit the table currently shows; defaults to the
            selection.
            表が現在示している集計単位。省略時は選択中の値。
        """
        param = self.param if param is None else param
        unit = self.unit if unit is None else unit
        self.result_caption_var.set(
            _("{param} ({value_unit}) / {sample} 単位").format(
                param=param,
                value_unit=PARAM_SPECS[param]["value_unit"],
                sample=unit,
            )
        )

    def _build_comparison_panel(self, parent: ttk.Frame) -> None:
        """
        Build the between-group comparison table.
        群間比較テーブルを構築する。

        Notes
        -----
        The statistics table above describes each group on its own, which
        leaves the reader to judge from two medians whether a difference
        exceeds the spread. This table answers that directly: a test of
        whether the groups are distinguishable, and an effect size saying how
        far apart they are independently of how many fibers were measured.
        上の統計量テーブルは各群を単独で記述するため、差がばらつきを超えている
        かどうかの判断は 2 つの中央値から読み手に委ねられる。この表はそれに直接
        答える。群が区別できるかの検定と、計測したファイバー本数に依存せず隔たり
        の大きさを示す効果量である。
        """
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=False, padx=4, pady=(0, 4))

        header = ttk.Frame(frm)
        header.pack(fill=tk.X, padx=6, pady=(0, 2))
        self.btn_save_comparison = ttk.Button(
            header, text=_("比較を保存"),
            command=self.on_save_comparison, state=tk.DISABLED,
        )
        self.btn_save_comparison.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(header, text=_("群間比較")).pack(side=tk.LEFT)
        self.comparison_note_var = tk.StringVar()
        ttk.Label(header, textvariable=self.comparison_note_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        tree_row = ttk.Frame(frm)
        tree_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 0))
        # Headings name statistical quantities that also go into the exported
        # CSV, so they stay fixed English like every other reported label.
        # 見出しは出力 CSV にも入る統計量の名称であるため、他の報告ラベルと同様に
        # 固定英語とする。
        self.comparison_tree, _sb = create_scrolled_treeview(
            tree_row,
            columns=("pair", "n", "u", "ks", "delta", "magnitude"),
            show="headings",
            height=4,
            headings={
                "pair": "Pair",
                "n": "N",
                "u": "Mann-Whitney p",
                "ks": "KS p",
                "delta": "Cliff's delta",
                "magnitude": "effect",
            },
            column_options={
                "pair": {"width": 140, "anchor": "w", "stretch": True},
                "n": {"width": 76, "anchor": "e", "stretch": False},
                "u": {"width": 108, "anchor": "e", "stretch": False},
                "ks": {"width": 90, "anchor": "e", "stretch": False},
                "delta": {"width": 92, "anchor": "e", "stretch": False},
                "magnitude": {"width": 80, "anchor": "w", "stretch": False},
            },
            tree_pack_kwargs={"side": tk.LEFT, "fill": tk.BOTH, "expand": True},
            scrollbar_side=tk.LEFT,
            scrollbar_pack_kwargs={"side": tk.LEFT, "fill": tk.Y},
        )

        hsb = ttk.Scrollbar(
            frm, orient=tk.HORIZONTAL, command=self.comparison_tree.xview,
        )
        self.comparison_tree.configure(xscrollcommand=hsb.set)
        hsb.pack(fill=tk.X, padx=6, pady=(0, 4))

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        """
        Build the log area and its save button.
        ログ領域とログ保存ボタンを構築する。
        """
        frm_log = ttk.Frame(parent)
        frm_log.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # The save-log button also labels the log area, avoiding a redundant heading.
        # ボタンのテキスト「ログを保存」自体が領域の説明を兼ねるため、別途ラベルは設けない。
        log_btn_row = ttk.Frame(frm_log)
        log_btn_row.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.btn_save_log = ttk.Button(log_btn_row, text=_("ログを保存"), command=self.on_save_log)
        self.btn_save_log.pack(side=tk.LEFT)
        self.btn_clear_log = ttk.Button(log_btn_row, text=_("ログをクリア"), command=self._clear_log)
        self.btn_clear_log.pack(side=tk.LEFT, padx=(4, 0))

        log_body = ttk.Frame(frm_log)
        log_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        self.log_text, _log_sb = create_scrolled_text(
            log_body,
            height=8,
            wrap=tk.WORD,
            state="disabled",
            scrollbar_side=tk.LEFT,
            text_side=tk.LEFT,
        )

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        """
        Build the right pane: action bar, histogram controls, plot options,
        and the scrollable plot canvas.
        右ペイン（操作バー・ヒストグラム設定・図オプション・スクロール可能な
        描画キャンバス）を構築する。
        """
        frm_plot = ttk.Frame(parent)
        frm_plot.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._build_action_bar(frm_plot)
        self._build_histogram_controls(frm_plot)
        self._build_plot_options(frm_plot)
        self._build_plot_canvas(frm_plot)

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        """
        Build the run / save-figure / save-CSV action bar.
        ヒストグラム作成・画像保存・数値保存の操作バーを構築する。
        """
        actionbar = ttk.Frame(parent)
        actionbar.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.btn_run = ttk.Button(actionbar, text=_("ヒストグラム作成"), command=self.on_run)
        self.btn_run.pack(side=tk.LEFT)

        self.btn_save_fig = ttk.Button(actionbar, text=_("画像を保存"), command=self.on_save_fig, state=tk.DISABLED)
        self.btn_save_fig.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_save_csv = ttk.Button(actionbar, text=_("数値を保存"), command=self.on_save_csv, state=tk.DISABLED)
        self.btn_save_csv.pack(side=tk.LEFT, padx=(6, 0))

    def _build_quantity_controls(self, parent: ttk.Frame) -> None:
        """
        Build the measured-quantity and aggregation-unit selectors.
        計測量セレクタと集計単位セレクタを構築する。

        Notes
        -----
        Both selectors invalidate cached results instead of redrawing them,
        because a cached histogram belongs to the quantity and unit it was
        computed with; redrawing it under a new axis label would present the
        old numbers as if they were the new quantity.
        どちらのセレクタもキャッシュ済み結果を再描画せず破棄する。キャッシュは
        計算時の計測量・集計単位に紐づいており、新しい軸ラベルで再描画すると
        古い数値を別の量として提示してしまうため。
        """
        inputbar = ttk.Frame(parent)
        inputbar.pack(fill=tk.X, padx=6, pady=(6, 0))

        ttk.Label(inputbar, text=_("入力")).pack(side=tk.LEFT)
        self.input_var = tk.StringVar(value=self.input_mode)
        self.cmb_input = ttk.Combobox(
            inputbar, textvariable=self.input_var,
            values=list(INPUT_ORDER), width=11, state="readonly",
        )
        self.cmb_input.pack(side=tk.LEFT, padx=(4, 12))
        self.cmb_input.bind("<<ComboboxSelected>>", lambda _e: self._on_input_change())
        ToolTip(self.cmb_input, _(
            "{bundle} は GUI01 が出力した .b2z を直接読み、全ての集計単位が使えます。"
            "{csv} は Fiber Tracker が出力した {suffix} を読み、そこに残っている"
            "ファイバーだけを集計します。密なネットワークでは自動フィルターで"
            "ゴミを落とせないため、Fiber Tracker で全体像を見ながら除外し、その"
            "結果を集計するのがこの経路の目的です。{csv} はファイバー単位の値しか"
            "持たないため、{pixel} と {length} 集計は使えません。"
        ).format(
            bundle=INPUT_BUNDLE, csv=INPUT_FIBER_CSV,
            suffix=INPUT_SUFFIXES[INPUT_FIBER_CSV],
            pixel=UNIT_PIXEL, length=UNIT_LENGTH,
        ))

        self.apply_exclusions_var = tk.BooleanVar(value=True)
        self.chk_exclusions = ttk.Checkbutton(
            inputbar, text=_("除外を適用"),
            variable=self.apply_exclusions_var,
            command=self._on_exclusions_toggle,
        )
        self.chk_exclusions.pack(side=tk.LEFT)
        ToolTip(self.chk_exclusions, _(
            "バンドル横の {suffix} に記録された手動除外を適用します。Fiber Tracker "
            "で除外したファイバーが集計から外れ、何本外れたかはログに出ます。"
            "OFF にすると、追跡された全てのファイバーを集計します。"
        ).format(suffix="_excluded.json"))

        parambar = ttk.Frame(parent)
        parambar.pack(fill=tk.X, padx=6, pady=(4, 0))

        # Quantity and unit keys are fixed English identifiers that also appear
        # on axes and in exports, so they are shown verbatim; only the field
        # labels and the hint text are localized. This matches the existing
        # y-axis selector, which shows "density"/"percent" untranslated.
        # 計測量・集計単位のキーは軸や出力にも現れる固定英語識別子のため、その
        # まま表示し、ラベルとヒント文のみ翻訳対象とする。"density"/"percent"
        # をそのまま表示する既存の縦軸セレクタと同じ方針。
        ttk.Label(parambar, text=_("計測量")).pack(side=tk.LEFT)
        self.param_var = tk.StringVar(value=self.param)
        self.cmb_param = ttk.Combobox(
            parambar, textvariable=self.param_var,
            values=self._available_params(), width=17, state="readonly",
        )
        self.cmb_param.pack(side=tk.LEFT, padx=(4, 12))
        self.cmb_param.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())
        ToolTip(self.cmb_param, _(
            "比較する形態パラメータを選びます。{height} はバンドルの補正済み画像と"
            "細線化画像から直接収集します。{length} / {angle} / {density} は"
            "ファイバー追跡の結果から算出するため、バンドルに走査範囲が記録されている"
            "必要があります。"
        ).format(
            height=PARAM_HEIGHT, length=PARAM_LENGTH,
            angle=PARAM_KINK_ANGLE, density=PARAM_KINK_DENSITY,
        ))

        ttk.Label(parambar, text=_("集計単位")).pack(side=tk.LEFT)
        self.unit_var = tk.StringVar(value=self.unit)
        self.cmb_unit = ttk.Combobox(
            parambar, textvariable=self.unit_var,
            values=self._available_units(self.param),
            width=8, state="readonly",
        )
        self.cmb_unit.pack(side=tk.LEFT, padx=(4, 8))
        self.cmb_unit.bind("<<ComboboxSelected>>", lambda _e: self._on_unit_change())
        ToolTip(self.cmb_unit, _(
            "1 標本の数え方を選びます。{pixel} は骨格画素 1 点、{kink} はキンク 1 点、"
            "{fiber} はファイバー 1 本（高さとキンク角はファイバー内の中央値）、"
            "{image} は画像 1 枚（その画像のファイバー値の中央値）です。"
            "{pixel} でまとめた分布は独立観測ではなく、長いファイバーほど重みが"
            "大きくなるため、群間比較では {fiber} または {image} でも確認してください。"
            "{length} は骨格画素を輪郭長で重み付けします。画素を等しく数えると、"
            "斜めの骨格ステップが約 1.41 倍長いことと、走査範囲の異なる画像で"
            "ピクセルサイズが変わることの 2 つの偏りが入ります。{length} は両方を"
            "取り除き、「観測した輪郭長のうちの割合」を表す走査条件に依らない分布に"
            "します。"
        ).format(
            pixel=UNIT_PIXEL, length=UNIT_LENGTH, kink=UNIT_KINK,
            fiber=UNIT_FIBER, image=UNIT_IMAGE,
        ))

        ttk.Label(parambar, text=_("曲率窓") + " (nm)").pack(side=tk.LEFT)
        self.curvature_window_var = tk.StringVar(
            value=self._fmt_num(self.curvature_window)
        )
        self.ent_curvature_window = ttk.Entry(
            parambar, textvariable=self.curvature_window_var, width=6,
        )
        self.ent_curvature_window.pack(side=tk.LEFT, padx=(4, 8))
        self._register_unconfirmed_entry(
            self.ent_curvature_window,
            lambda: self._fmt_num(self.curvature_window),
            self._commit_curvature_window,
        )
        ToolTip(self.ent_curvature_window, _(
            "{curvature} が回転角を測る弧長です。骨格のステップは直交か斜めしか"
            "無いため画素スケールでは方向が量子化され、窓が小さすぎると真の曲率に"
            "関係なく一定のノイズ値が返ります（既知半径の円弧に対し 20 nm では"
            "常に 19.4 rad/{um} でした）。大きくすると滑らかになりますが、窓より"
            "短いファイバーは測定対象から外れます。"
        ).format(curvature=PARAM_CURVATURE, um=UNIT_MICROMETER))

        self.sample_hint_var = tk.StringVar()
        ttk.Label(parambar, textvariable=self.sample_hint_var).pack(side=tk.LEFT)
        self._update_sample_hint()

    def _available_params(self) -> list:
        """
        Return the quantities the current input type can produce.
        現在の入力タイプで算出できる計測量を返す。

        Returns
        -------
        list of str
            Quantity keys in `PARAM_ORDER`.
            `PARAM_ORDER` の順に並んだ計測量キー。
        """
        if self.input_mode == INPUT_BUNDLE:
            return list(PARAM_ORDER)
        return [p for p in PARAM_ORDER if p not in BUNDLE_ONLY_PARAMS]

    def _available_units(self, param: str) -> list:
        """
        Return the aggregation units the current input type can produce.
        現在の入力タイプで算出できる集計単位を返す。

        Parameters
        ----------
        param
            Measured-quantity key from `PARAM_SPECS`.
            `PARAM_SPECS` の計測量キー。

        Returns
        -------
        list of str
            Unit keys, in the quantity's declared order.
            計測量の宣言順に並んだ集計単位キー。
        """
        units = list(PARAM_SPECS[param]["units"])
        if self.input_mode != INPUT_BUNDLE:
            units = [u for u in units if u not in BUNDLE_ONLY_UNITS]
        return units

    def _on_input_change(self) -> None:
        """
        Apply an input-type change to the unit list and cached results.
        入力タイプの変更を集計単位一覧とキャッシュ済み結果へ反映する。
        """
        mode = self.input_var.get()
        if mode not in INPUT_SUFFIXES:
            self.input_var.set(self.input_mode)
            return
        if mode == self.input_mode:
            return

        self.input_mode = mode

        params = self._available_params()
        self.cmb_param.configure(values=params)
        if self.param not in params:
            self.param = params[0]
            self.param_var.set(self.param)
            self._apply_default_range(self.param)
            for col, text in self._result_headings(self.param).items():
                self.result_tree.heading(col, text=text)

        units = self._available_units(self.param)
        self.cmb_unit.configure(values=units)
        if self.unit not in units:
            self.unit = units[0]
            self.unit_var.set(self.unit)
            self._update_sample_hint()
            self._update_result_caption()

        # Exclusions live beside a bundle; a fiber CSV already has them baked
        # in, because GUI04 exported only the fibers it was displaying.
        # 除外はバンドルの横にある。ファイバー CSV には既に適用済みで、GUI04 が
        # 表示中のファイバーだけを出力しているため。
        self.chk_exclusions.configure(
            state=tk.NORMAL if mode == INPUT_BUNDLE else tk.DISABLED
        )

        self._rescan_all()
        self._reset_result_state()
        self._log(_("入力を {mode} に変更しました（{suffix} を探索します）。").format(
            mode=mode, suffix=INPUT_SUFFIXES[mode],
        ))

    def _on_exclusions_toggle(self) -> None:
        """
        Invalidate cached results when the exclusion setting changes.
        除外設定の変更時にキャッシュ済み結果を破棄する。
        """
        self._reset_result_state()

    def _update_sample_hint(self) -> None:
        """
        Refresh the label describing what one sample is.
        1 標本が何を指すかを説明するラベルを更新する。
        """
        hints = {
            UNIT_PIXEL: _("1 標本 = 骨格画素 1 点"),
            UNIT_LENGTH: _("1 標本 = 骨格画素 1 点（輪郭長で重み付け）"),
            UNIT_KINK: _("1 標本 = キンク 1 点"),
            UNIT_FIBER: _("1 標本 = ファイバー 1 本"),
            UNIT_IMAGE: _("1 標本 = 画像 1 枚"),
        }
        self.sample_hint_var.set(hints.get(self.unit, ""))

    def _apply_default_range(self, param: str) -> None:
        """
        Load one quantity's default histogram range into the range entries.
        指定した計測量の既定ヒストグラム範囲を範囲入力欄へ読み込む。

        Notes
        -----
        Quantities differ by orders of magnitude (nanometers of height versus
        nanometers of contour length versus degrees), so a range carried over
        from the previous quantity would usually produce an empty histogram.
        計測量ごとに桁が大きく異なる（高さの nm、輪郭長の nm、角度の度）ため、
        前の計測量の範囲をそのまま引き継ぐと、たいてい空のヒストグラムになる。
        """
        self.min_h, self.max_h, self.step = PARAM_SPECS[param]["default_range"]
        self.min_var.set(self._fmt_num(self.min_h))
        self.max_var.set(self._fmt_num(self.max_h))
        self.step_var.set(self._fmt_num(self.step))
        # Writing the StringVars does not fire the Entry key handlers, so the
        # confirmed/unconfirmed styles are refreshed explicitly.
        # StringVar への代入では Entry のキーハンドラが走らないため、確定/未確定
        # スタイルを明示的に再評価する。
        self._refresh_all_entry_states()

    def _commit_curvature_window(self) -> bool:
        """
        Validate and commit the curvature window.
        曲率窓を検証して確定する。

        Returns
        -------
        bool
            True when the value is committed; False when validation fails.
            確定できた場合は True、不正値の場合は False。
        """
        def _check(v):
            if v["curvature_window"] <= 0.0:
                return _("曲率窓は正の値にしてください。")
            return None

        def _on_success():
            # The window changes what is measured, not how it is drawn, so
            # cached results no longer describe the current setting.
            # 窓は描き方ではなく計測内容を変えるため、キャッシュ済み結果は現在の
            # 設定を記述しなくなる。
            self._reset_result_state()

        return self._commit_float_fields(
            [(self.ent_curvature_window, "curvature_window", "curvature window")],
            validator=_check,
            on_success=_on_success,
        )

    def _on_param_change(self) -> None:
        """
        Apply a measured-quantity change to units, range, headings, and state.
        計測量の変更を集計単位・範囲・見出し・状態へ反映する。
        """
        param = self.param_var.get()
        if param not in self._available_params():
            self.param_var.set(self.param)
            return
        if param == self.param:
            return

        self.param = param

        units = self._available_units(param)
        self.cmb_unit.configure(values=units)
        if self.unit not in units:
            self.unit = units[0]
            self.unit_var.set(self.unit)

        self._apply_default_range(param)
        for col, text in self._result_headings(param).items():
            self.result_tree.heading(col, text=text)
        self._update_sample_hint()
        self._update_result_caption()
        self._reset_result_state()

        self._log(
            _("計測量を {param} に変更しました。ヒストグラム範囲を既定値"
              "（min={min}, max={max}, step={step}）に戻しました。").format(
                param=param,
                min=self._fmt_num(self.min_h),
                max=self._fmt_num(self.max_h),
                step=self._fmt_num(self.step),
            )
        )

    def _on_unit_change(self) -> None:
        """
        Apply an aggregation-unit change and invalidate cached results.
        集計単位の変更を反映し、キャッシュ済み結果を破棄する。
        """
        unit = self.unit_var.get()
        if unit not in self._available_units(self.param):
            self.unit_var.set(self.unit)
            return
        if unit == self.unit:
            return

        self.unit = unit
        self._update_sample_hint()
        self._update_result_caption()
        self._reset_result_state()

    def _build_histogram_controls(self, parent: ttk.Frame) -> None:
        """
        Build the quantity, unit, histogram range, and view-option controls.
        計測量・集計単位・ヒストグラム範囲・表示オプションの操作部を構築する。
        """
        self._build_quantity_controls(parent)

        topbar = ttk.Frame(parent)
        topbar.pack(fill=tk.X, padx=6, pady=(2, 4))

        # Histogram range changes are committed with Enter and trigger recalculation.
        # ヒストグラム範囲変更は Enter で確定し、再計算を発生させる。
        self.min_var = tk.StringVar(value=self._fmt_num(self.min_h))
        self.max_var = tk.StringVar(value=self._fmt_num(self.max_h))
        self.step_var = tk.StringVar(value=self._fmt_num(self.step))

        ttk.Label(topbar, text=_("min")).pack(side=tk.LEFT)
        self.ent_min = ttk.Entry(topbar, textvariable=self.min_var, width=6)
        self.ent_min.pack(side=tk.LEFT, padx=(4, 8))
        self._register_unconfirmed_entry(
            self.ent_min,
            lambda: self._fmt_num(self.min_h),
            self._commit_histogram_params,
        )

        ttk.Label(topbar, text=_("max")).pack(side=tk.LEFT)
        self.ent_max = ttk.Entry(topbar, textvariable=self.max_var, width=6)
        self.ent_max.pack(side=tk.LEFT, padx=(4, 8))
        self._register_unconfirmed_entry(
            self.ent_max,
            lambda: self._fmt_num(self.max_h),
            self._commit_histogram_params,
        )

        ttk.Label(topbar, text=_("step")).pack(side=tk.LEFT)
        self.ent_step = ttk.Entry(topbar, textvariable=self.step_var, width=6)
        self.ent_step.pack(side=tk.LEFT, padx=(4, 12))
        self._register_unconfirmed_entry(
            self.ent_step,
            lambda: self._fmt_num(self.step),
            self._commit_histogram_params,
        )

        # View-only options reuse cached results and redraw immediately.
        # 表示専用オプションはキャッシュ済み結果を使い、選択時に即時再描画する。
        self.yaxis_mode_var = tk.StringVar(value="density")
        ttk.Label(topbar, text=_("Y")).pack(side=tk.LEFT)
        self.yaxis_mode = ttk.Combobox(
            topbar, textvariable=self.yaxis_mode_var,
            values=[_("非表示"), "density", "percent"], width=8, state="readonly"
        )
        self.yaxis_mode.pack(side=tk.LEFT, padx=(4, 12))
        self.yaxis_mode.bind("<<ComboboxSelected>>", lambda _e: self._on_view_option_change())

        self.display_mode_var = tk.StringVar(value=self.MODE_STACK)
        ttk.Label(topbar, text=_("表示")).pack(side=tk.LEFT)
        self._rb_stack = ttk.Radiobutton(
            topbar, text=_("縦並び"),
            variable=self.display_mode_var, value=self.MODE_STACK,
            command=self._on_view_option_change,
        )
        self._rb_stack.pack(side=tk.LEFT, padx=(4, 0))
        self._rb_overlay = ttk.Radiobutton(
            topbar, text=_("重ね表示"),
            variable=self.display_mode_var, value=self.MODE_OVERLAY,
            command=self._on_view_option_change,
        )
        self._rb_overlay.pack(side=tk.LEFT, padx=(4, 12))

        self.show_height_text_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            topbar, text=_("統計値表示"),
            variable=self.show_height_text_var,
            command=self._on_view_option_change,
        ).pack(side=tk.LEFT, padx=(0, 12))

    def _build_plot_options(self, parent: ttk.Frame) -> None:
        """
        Build the figure-size and font-size option controls.
        図サイズ・フォントサイズのオプション操作部を構築する。
        """
        optbar = ttk.Frame(parent)
        optbar.pack(fill=tk.X, padx=6, pady=(0, 6))

        self.fig_w_var = tk.StringVar(value=self._fmt_num(self.fig_w))
        self.fig_h_var = tk.StringVar(value=self._fmt_num(self.fig_h))
        self.group_name_fs_var = tk.StringVar(value=self._fmt_num(self.group_name_fs))
        self.label_fs_var = tk.StringVar(value=self._fmt_num(self.label_fs))
        self.tick_fs_var = tk.StringVar(value=self._fmt_num(self.tick_fs))
        self.ann_fs_var = tk.StringVar(value=self._fmt_num(self.ann_fs))

        self.plot_type_var = tk.StringVar(value=PLOT_HISTOGRAM)
        ttk.Label(optbar, text=_("図")).pack(side=tk.LEFT)
        self.cmb_plot_type = ttk.Combobox(
            optbar, textvariable=self.plot_type_var,
            values=list(PLOT_TYPES), width=10, state="readonly",
        )
        self.cmb_plot_type.pack(side=tk.LEFT, padx=(4, 12))
        self.cmb_plot_type.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_plot_type_change()
        )
        ToolTip(self.cmb_plot_type, _(
            "{histogram} は 1 群の分布の形を示します。{ecdf} は累積分布を重ねて"
            "描くため、ビン幅に依存せずに群を比較できます。{box} は各群の中央値と"
            "四分位数を並べて要約します。{ecdf} と {box} は常に重ね／並置表示に"
            "なるため、縦並び・重ね表示の選択は使われません。"
        ).format(histogram=PLOT_HISTOGRAM, ecdf=PLOT_ECDF, box=PLOT_BOX))

        ttk.Label(optbar, text=_("横長")).pack(side=tk.LEFT)
        self.ent_fig_w = ttk.Entry(optbar, textvariable=self.fig_w_var, width=4)
        self.ent_fig_w.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_fig_w,
            lambda: self._fmt_num(self.fig_w),
            self._commit_plot_params,
        )

        # Stacked mode treats this height as per subplot; other modes use it as figure height.
        # 縦並び時は 1 サブプロット分、重ね表示や単一グループでは Figure 全体の高さとして扱う。
        ttk.Label(optbar, text=_("縦長")).pack(side=tk.LEFT)
        self.ent_fig_h = ttk.Entry(optbar, textvariable=self.fig_h_var, width=4)
        self.ent_fig_h.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_fig_h,
            lambda: self._fmt_num(self.fig_h),
            self._commit_plot_params,
        )

        ttk.Label(optbar, text=_("フォントサイズ：グループ名")).pack(side=tk.LEFT)
        self.ent_group_name_fs = ttk.Entry(optbar, textvariable=self.group_name_fs_var, width=4)
        self.ent_group_name_fs.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_group_name_fs,
            lambda: self._fmt_num(self.group_name_fs),
            self._commit_plot_params,
        )

        ttk.Label(optbar, text=_("軸ラベル")).pack(side=tk.LEFT)
        self.ent_label_fs = ttk.Entry(optbar, textvariable=self.label_fs_var, width=4)
        self.ent_label_fs.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_label_fs,
            lambda: self._fmt_num(self.label_fs),
            self._commit_plot_params,
        )

        ttk.Label(optbar, text=_("軸目盛")).pack(side=tk.LEFT)
        self.ent_tick_fs = ttk.Entry(optbar, textvariable=self.tick_fs_var, width=4)
        self.ent_tick_fs.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_tick_fs,
            lambda: self._fmt_num(self.tick_fs),
            self._commit_plot_params,
        )

        ttk.Label(optbar, text=_("統計値")).pack(side=tk.LEFT)
        self.ent_ann_fs = ttk.Entry(optbar, textvariable=self.ann_fs_var, width=4)
        self.ent_ann_fs.pack(side=tk.LEFT, padx=(4, 0))
        self._register_unconfirmed_entry(
            self.ent_ann_fs,
            lambda: self._fmt_num(self.ann_fs),
            self._commit_plot_params,
        )

    def _build_plot_canvas(self, parent: ttk.Frame) -> None:
        """
        Build the scrollable plot canvas hosting the histogram figure.
        ヒストグラム Figure を載せるスクロール可能な描画キャンバスを構築する。
        """
        # Add scrollbars because stacked plots can become taller than the window.
        # グループ数が多くなると Figure 縦長が巨大化するため、Canvas にスクロールバーを付けて
        # ウィンドウサイズを超えても全体を見られるようにする。
        canvas_holder = ttk.Frame(parent)
        canvas_holder.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        self._scroll_canvas = tk.Canvas(canvas_holder, highlightthickness=0)
        sb_v = ttk.Scrollbar(canvas_holder, orient=tk.VERTICAL, command=self._scroll_canvas.yview)
        sb_h = ttk.Scrollbar(canvas_holder, orient=tk.HORIZONTAL, command=self._scroll_canvas.xview)
        self._scroll_canvas.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        sb_v.pack(side=tk.RIGHT, fill=tk.Y)
        sb_h.pack(side=tk.BOTTOM, fill=tk.X)
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner_frame = ttk.Frame(self._scroll_canvas)
        self._scroll_canvas.create_window(
            (0, 0), window=self._inner_frame, anchor="nw"
        )

        self._inner_frame.bind("<Configure>", self._on_inner_configure)

        self.fig = plt.Figure(figsize=(6, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel(PARAM_SPECS[self.param]["axis_label"])
        self.ax.set_yticks([])

        self.canvas = FigureCanvasTkAgg(self.fig, master=self._inner_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Scope the wheel to this panel: the window's other areas (log, file
        # table) scroll themselves and must not drive the plot canvas.
        bind_mousewheel_scroll(self._scroll_canvas, scope=canvas_holder)

    def _on_inner_configure(self, event) -> None:
        """
        Update the scrollable plot region after inner-frame resizing.
        内側フレームのサイズ変更後にスクロール可能な描画領域を更新する。
        """
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _log_initial_message(self) -> None:
        """
        Write the initial usage guidance to the log area.
        初期の操作案内をログ領域へ出力する。
        """
        msg = (
            _("使い方:\n")
            + _("  1)「グループ追加」でデータ群を作成（自動で 1 個作成済み）\n")
            + _("  2) Treeview でグループを選び「フォルダ追加」で .b2z バンドルを含むフォルダを登録\n")
            + _("  3) 計測量と集計単位、条件と表示モード（縦並び/重ね表示）を設定して「ヒストグラム作成」\n")
            + _("  4) 必要に応じて「画像を保存」「数値を保存（グループ別CSV）」\n")
            + "\n"
            + _("ヒント:\n")
            + _("  - グループをダブルクリックで名前変更／右クリックで色変更\n")
            + _("  - 縦軸モード: 非表示=目盛なし / {density}=割合(0–1) / {percent}=パーセント\n").format(
                density="density", percent="percent"
            )
            + _("  - グループ間でデータ数が大きく異なるときは {density} または {percent} を推奨\n").format(
                density="density", percent="percent"
            )
            + _("  - {pixel} 集計は骨格画素をまとめた分布で、長いファイバーほど重みが大きく、"
                "同一ファイバーの隣接画素も独立ではありません。群間比較の根拠には "
                "{fiber} または {image} 集計での N も併せて確認してください。\n").format(
                pixel=UNIT_PIXEL, fiber=UNIT_FIBER, image=UNIT_IMAGE
            )
            + _("  - {height} 以外の計測量はファイバー追跡を行うため、バンドルに走査範囲が"
                "記録されている必要があり、処理時間も長くなります。\n").format(height=PARAM_HEIGHT)
            + _("  - mode はヒストグラムのビン幅に依存します。step を変えると値が変わるため、"
                "報告には median と IQR を併記してください。\n")
        )
        self._log(msg)

    # _log is inherited from ui_tools.LogMixin.
    def _default_save_dir(self) -> str:
        """
        Return the first registered input folder for save dialogs.
        保存ダイアログ用に、最初に登録された入力フォルダを返す。
        """
        for group in self.groups:
            for folder in group.folder_paths:
                if folder:
                    return folder
        return os.getcwd()

    def _next_default_name(self) -> str:
        # Continue from the largest existing "Group N"; renamed groups do not participate.
        # 現存する "Group N" 形式の最大値 + 1 を採用し、リネーム済みグループは対象外にする。
        # Default group names stay language-independent so exported data and figures are
        # consistent across UI languages.
        # デフォルトのグループ名は言語非依存とし、出力データ・図の表記を UI 言語に依存させない。
        prefix = "Group "
        max_n = 0
        for g in self.groups:
            name = g.name
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix):]
            try:
                n = int(rest)
            except ValueError:
                continue
            if n > max_n:
                max_n = n
        return "Group {n}".format(n=max_n + 1)

    # Unconfirmed Entry behavior is shared with GUI01/GUI02 through UnconfirmedEntryMixin.
    # 未確定 Entry の挙動は GUI01 / GUI02 と共通で、UnconfirmedEntryMixin に集約する。

    def _commit_histogram_params(self) -> bool:
        """
        Validate and commit min, max, and step histogram parameters.
        ヒストグラムの min / max / step を検証して確定する。

        Returns
        -------
        bool
            True when all values are committed; False when validation fails.
            すべての値を確定できた場合は True、不正値がある場合は False。

        Notes
        -----
        These parameters trigger a full recalculation when results already exist.
        既存の結果がある場合、これらのパラメータ変更は再計算を発生させる。
        """
        def _check(v):
            if v["step"] <= 0:
                return _("step は正の値にしてください。")
            if v["max_h"] <= v["min_h"]:
                return _("max height は min height より大きくしてください。")
            return None

        def _on_success():
            if self._has_result and not self.is_running:
                self.on_run()

        return self._commit_float_fields(
            [
                (self.ent_min,  "min_h", "min height"),
                (self.ent_max,  "max_h", "max height"),
                (self.ent_step, "step",  "step"),
            ],
            validator=_check,
            on_success=_on_success,
        )

    def _commit_plot_params(self) -> bool:
        """
        Validate and commit figure-size and font-size parameters.
        Figure サイズとフォントサイズのパラメータを検証して確定する。

        Returns
        -------
        bool
            True when all values are committed; False when validation fails.
            すべての値を確定できた場合は True、不正値がある場合は False。

        Notes
        -----
        These display-only parameters redraw the existing results without
        recomputing histogram counts.
        表示専用パラメータのため、既存結果の再描画のみを行いヒストグラム数は再計算しない。
        """
        def _check(v):
            if v["fig_w"] <= 0 or v["fig_h"] <= 0:
                return _("ヒストグラムの横/縦の長さは正の値にしてください。")
            if (v["group_name_fs"] <= 0 or v["label_fs"] <= 0
                    or v["tick_fs"] <= 0 or v["ann_fs"] <= 0):
                return _("フォントサイズは正の値にしてください。")
            return None

        def _on_success():
            if self._has_result:
                self._redraw_from_last_results()

        return self._commit_float_fields(
            [
                (self.ent_fig_w,         "fig_w",         "fig_w"),
                (self.ent_fig_h,         "fig_h",         "fig_h"),
                (self.ent_group_name_fs, "group_name_fs", "group_name_fs"),
                (self.ent_label_fs,      "label_fs",      "label_fs"),
                (self.ent_tick_fs,       "tick_fs",       "tick_fs"),
                (self.ent_ann_fs,        "ann_fs",        "ann_fs"),
            ],
            validator=_check,
            on_success=_on_success,
        )

    def _on_plot_type_change(self) -> None:
        """
        Redraw for a new plot type and grey out controls it does not use.
        新しい図の種類で再描画し、その図が使わない操作部を無効化する。

        Notes
        -----
        The ECDF and box plots put every group on one axes by construction, so
        the stacked/overlaid choice has nothing to act on; disabling it says
        that before the user changes it and sees nothing happen.
        ECDF と箱ひげは構造上すべての群を 1 つの軸に描くため、縦並び／重ね表示の
        選択には作用する対象が無い。無効化することで、変更しても何も起きないと
        気づく前にそれを伝える。
        """
        stacking_used = self.plot_type_var.get() == PLOT_HISTOGRAM
        state = tk.NORMAL if stacking_used else tk.DISABLED
        for widget in (self._rb_stack, self._rb_overlay):
            widget.configure(state=state)
        self._on_view_option_change()

    def _on_view_option_change(self) -> None:
        """
        Apply lightweight view-option changes immediately.
        軽量な表示オプション変更を即時反映する。

        Reuses the latest results and redraws only the figure.
        """
        if not self._has_result:
            return
        self._redraw_from_last_results()

    def _redraw_from_last_results(self) -> None:
        """
        Redraw the figure from cached results and current display parameters.
        キャッシュ済み結果と現在の表示パラメータから Figure を再描画する。
        """
        if self._last_results is None or self._last_edges is None:
            return
        self._draw_figure(
            results=self._last_results,
            edges=self._last_edges,
            param=self._last_param,
            unit=self._last_unit,
            plot_type=self.plot_type_var.get(),
            yaxis_mode=self.yaxis_mode_var.get(),
            display_mode=self.display_mode_var.get(),
            show_height_text=bool(self.show_height_text_var.get()),
            fig_w=self.fig_w,
            fig_h=self.fig_h,
            label_fs=self.label_fs,
            tick_fs=self.tick_fs,
            ann_fs=self.ann_fs,
            group_name_fs=self.group_name_fs,
        )

    def _add_group_internal(self, name: str, color: str = None) -> Group:
        """
        Create a group, add it to state, and insert its tree row.
        グループを作成して内部状態へ追加し、Treeview 行を挿入する。
        """
        if color is None:
            color = _color_for_index(len(self.groups))
        g = Group(name=name, color=color)
        self.groups.append(g)
        self._insert_group_in_tree(g)
        self._update_summary()
        return g

    def _group_label(self, g: Group) -> str:
        """
        Return the display label for a group row.
        グループ行に表示するラベルを返す。
        """
        return f"● {g.name}"

    def _folder_label(self, folder: str, info: dict) -> str:
        """
        Return the display label for a registered folder row.
        登録フォルダ行に表示するラベルを返す。
        """
        pairs = info.get("pairs", 0)
        return f"{folder}  ({_('pairs')}={pairs})"

    def _insert_group_in_tree(self, g: Group) -> None:
        """
        Insert a group row into the Treeview.
        Treeview にグループ行を挿入する。
        """
        # Use group.id as the iid so selection can be mapped back to the Group object.
        # iid に group.id を使うと、選択された行から Group を逆引きしやすい。
        tag = f"grp_{g.id}"
        self.tree.tag_configure(tag, foreground=g.color)
        self.tree.insert(
            "", tk.END, iid=g.id,
            text=self._group_label(g),
            values=(g.total_pairs(),),
            open=True,
            tags=(tag,),
        )

    def _refresh_group_row(self, g: Group) -> None:
        """
        Refresh a group row after its name, color, or count changes.
        名前、色、件数の変更後にグループ行を更新する。
        """
        tag = f"grp_{g.id}"
        self.tree.tag_configure(tag, foreground=g.color)
        self.tree.item(g.id, text=self._group_label(g), values=(g.total_pairs(),), tags=(tag,))

    def _refresh_folder_row(self, g: Group, folder: str) -> None:
        """
        Refresh a folder row after its scan result changes.
        スキャン結果の変更後にフォルダ行を更新する。
        """
        info = g.folder_pairinfo.get(folder, {})
        iid = self._folder_iid(g, folder)
        self.tree.item(iid, text=self._folder_label(folder, info), values=(info.get("pairs", 0),))

    def _folder_iid(self, g: Group, folder: str) -> str:
        """
        Return the stable Treeview item ID for a folder row.
        フォルダ行に使う安定した Treeview アイテム ID を返す。
        """
        return f"{g.id}::{folder}"

    def _find_group_by_iid(self, iid: str) -> tuple:
        """
        Resolve a Treeview item ID to its group and optional folder.
        Treeview アイテム ID からグループと任意のフォルダを解決する。
        """
        for g in self.groups:
            if g.id == iid:
                return g, None
            for folder in g.folder_paths:
                if self._folder_iid(g, folder) == iid:
                    return g, folder
        return None, None

    def _selected_group(self) -> tuple:
        """
        Return the currently selected group and optional folder.
        現在選択されているグループと任意のフォルダを返す。
        """
        sel = self.tree.selection()
        if not sel:
            return None, None
        return self._find_group_by_iid(sel[0])

    def _update_summary(self) -> None:
        """
        Update the group and bundle count summary label.
        グループ数とバンドル数の概要ラベルを更新する。
        """
        total_pairs = sum(g.total_pairs() for g in self.groups)
        total_missing = sum(g.total_missing() for g in self.groups)
        self.summary_var.set(
            _("グループ数: {g} / 有効バンドル総数: {p} / 欠損: {m}").format(
                g=len(self.groups), p=total_pairs, m=total_missing
            )
        )

    def _find_pairs(self, folder: str) -> tuple:
        """
        Return candidate bundle path pairs and warning messages for a folder.
        フォルダ内の候補バンドルパスペアと警告メッセージを返す。

        Parameters
        ----------
        folder
            Folder scanned for ``.b2z`` analysis bundles.
            ``.b2z`` 解析バンドルを探索するフォルダ。

        Returns
        -------
        tuple
            Candidate pair list and warning list. Each pair is
            ``(bundle_path, bundle_path)``.
            候補ペアリストと警告リスト。各ペアは ``(bundle_path, bundle_path)``。

        Notes
        -----
        Each ``.b2z`` candidate is passed downstream, where the required
        calibrated and skeletonized keys are loaded and validated. The same
        path is stored twice to satisfy code that expects separate ``cal_path``
        and ``skl_path`` variables.
        ``.b2z`` バンドルには calibrated / skeletonized が同一ファイル内に含まれる。
        必須キーの読み込みと検証は下流処理で行う。別々の ``cal_path`` /
        ``skl_path`` 変数を期待するコードに合わせ、同じパスを 2 回格納する。
        """
        try:
            files = os.listdir(folder)
        except Exception as e:
            return [], [_("[アクセス不可] {err}").format(err=e)]

        suffix = INPUT_SUFFIXES[self.input_mode]
        bundle_files = [f for f in files if f.endswith(suffix)]
        if not bundle_files:
            return [], [_("入力なし（*{ext} が見つかりません）").format(ext=suffix)]

        pairs = []
        missing = []
        for bf in bundle_files:
            bundle_path = os.path.join(folder, bf)
            pairs.append((bundle_path, bundle_path))

        return pairs, missing

    def _scan_folder(self, folder: str) -> dict:
        """
        Scan one folder and summarize candidate bundle counts and warnings.
        1 つのフォルダをスキャンし、候補バンドル数と警告を要約する。
        """
        pairs, missing = self._find_pairs(folder)
        return {"pairs": len(pairs), "missing": missing}

    def _rescan_all(self) -> None:
        """
        Rescan all registered folders and refresh the tree summary.
        登録済みフォルダをすべて再スキャンし、Treeview と概要を更新する。
        """
        for g in self.groups:
            g.folder_pairinfo.clear()
            for folder in g.folder_paths:
                g.folder_pairinfo[folder] = self._scan_folder(folder)
                self._refresh_folder_row(g, folder)
            self._refresh_group_row(g)
        self._update_summary()

    def on_add_group(self) -> None:
        """
        Add a new empty histogram group and select it in the tree.
        空のヒストグラムグループを追加し、Treeview 上で選択する。
        """
        name = self._next_default_name()
        g = self._add_group_internal(name)
        # Select the new group so the next folder-add action targets it.
        # 追加直後に選択しておくと、そのまま「フォルダ追加」できる。
        self.tree.selection_set(g.id)
        self.tree.see(g.id)
        self._log(_("グループ追加: {name}").format(name=g.name))

    def on_remove_group(self) -> None:
        """
        Remove the selected group after confirming data-loss cases.
        選択中のグループを、登録フォルダが失われる場合は確認してから削除する。
        """
        g, _folder = self._selected_group()
        if g is None:
            messagebox.showwarning(_("未選択"), _("削除するグループを選択してください。"))
            return
        # Skip confirmation for empty groups because no folder registrations are lost.
        # 空グループでは失われるフォルダ登録がないため確認を省略する。
        if g.folder_paths:
            if not messagebox.askyesno(
                _("確認"),
                _("グループ「{name}」を削除しますか？\n所属フォルダの登録もすべて解除されます。").format(name=g.name),
            ):
                return
        self.tree.delete(g.id)
        self.groups.remove(g)
        self._update_summary()
        self._log(_("グループ削除: {name}").format(name=g.name))

    def on_move_group(self, delta: int) -> None:
        """
        Move the selected group up or down in plotting order.
        選択中のグループを描画順序の中で上下に移動する。
        """
        g, _folder = self._selected_group()
        if g is None:
            messagebox.showwarning(_("未選択"), _("並び替えるグループを選択してください。"))
            return
        idx = self.groups.index(g)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self.groups):
            return
        self.groups[idx], self.groups[new_idx] = self.groups[new_idx], self.groups[idx]
        self.tree.move(g.id, "", new_idx)

    def on_clear_all(self) -> None:
        """
        Remove all groups and reset any existing histogram result state.
        全グループを削除し、既存のヒストグラム結果状態をリセットする。
        """
        if not self.groups:
            return
        # Skip confirmation when all groups are empty.
        # 全グループが空で失うフォルダ登録がない場合は確認を省略する。
        has_any_folder = any(g.folder_paths for g in self.groups)
        if has_any_folder:
            if not messagebox.askyesno(_("確認"), _("すべてのグループとフォルダ登録を削除しますか？")):
                return
        for iid in list(self.tree.get_children("")):
            self.tree.delete(iid)
        self.groups.clear()
        self._update_summary()
        self._reset_result_state()
        self._log(_("全クリアしました。"))

    def on_add_folder(self) -> None:
        """
        Add an input folder to the selected group and scan bundle availability.
        選択中グループへ入力フォルダを追加し、利用可能なバンドルをスキャンする。
        """
        g, _folder = self._selected_group()
        if g is None:
            messagebox.showwarning(
                _("未選択"),
                _("フォルダを追加する先のグループを Treeview で選択してください。"),
            )
            return

        folder = filedialog.askdirectory(title=_("解析対象フォルダを選択"))
        if not folder:
            return
        folder = os.path.normpath(folder)

        if folder in g.folder_paths:
            messagebox.showinfo(_("重複"), _("このフォルダは同じグループに既に登録されています。"))
            return

        # Allow cross-group duplicates because intentional comparisons may reuse a folder.
        # 意図的な比較の可能性があるため、別グループとの重複は許容して警告ログだけ出す。
        for other in self.groups:
            if other is not g and folder in other.folder_paths:
                self._log(
                    _("注意: 「{f}」は別グループ「{n}」にも登録されています。").format(
                        f=folder, n=other.name
                    )
                )
                break

        g.folder_paths.append(folder)
        info = self._scan_folder(folder)
        g.folder_pairinfo[folder] = info

        iid = self._folder_iid(g, folder)
        self.tree.insert(
            g.id, tk.END, iid=iid,
            text=self._folder_label(folder, info),
            values=(info.get("pairs", 0),),
        )
        self._refresh_group_row(g)
        self._update_summary()

        self._log(_("[{name}] 追加: {path}").format(name=g.name, path=folder))
        self._log(_("有効ペア数: {n}").format(n=info["pairs"]))
        if info["missing"]:
            self._log(_("欠損/注意:"))
            for m in info["missing"]:
                self._log(f"  - {m}")

    def on_remove_folder(self) -> None:
        """
        Remove the selected folder registration from its group.
        選択中のフォルダ登録を所属グループから削除する。
        """
        g, folder = self._selected_group()
        if g is None or folder is None:
            messagebox.showwarning(_("未選択"), _("削除するフォルダ行を選択してください。"))
            return
        iid = self._folder_iid(g, folder)
        self.tree.delete(iid)
        if folder in g.folder_paths:
            g.folder_paths.remove(folder)
        g.folder_pairinfo.pop(folder, None)
        self._refresh_group_row(g)
        self._update_summary()
        self._log(_("[{name}] フォルダ削除: {path}").format(name=g.name, path=folder))

    def _on_tree_double_click(self, event) -> None:
        """
        Rename a group when its Treeview row is double-clicked.
        Treeview のグループ行がダブルクリックされたときに名前変更を行う。
        """
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        g, folder = self._find_group_by_iid(iid)
        if g is None or folder is not None:
            return
        self._rename_group(g)

    def _on_tree_right_click(self, event) -> None:
        """
        Open the context menu for the group or folder row under the pointer.
        ポインタ下のグループ行またはフォルダ行のコンテキストメニューを開く。
        """
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        g, folder = self._find_group_by_iid(iid)
        if g is None:
            return
        # Select the row under the pointer before opening its context menu.
        # コンテキストメニューを開く前に、ポインタ下の行を選択状態にする。
        self.tree.selection_set(iid)

        if folder is None:
            menu = self._build_group_context_menu(g)
        else:
            menu = self._build_folder_context_menu(g, folder)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _build_group_context_menu(self, g: Group) -> tk.Menu:
        """
        Build the group context menu for rename, color, and delete actions.
        名前変更、色変更、削除操作用のグループコンテキストメニューを構築する。
        """
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=_("名前を変更"), command=lambda: self._rename_group(g))
        menu.add_command(label=_("色を変更"), command=lambda: self._change_color(g))
        menu.add_separator()
        menu.add_command(label=_("グループ削除"), command=self.on_remove_group)
        return menu

    def _build_folder_context_menu(self, g: Group, folder: str) -> tk.Menu:
        """
        Build the folder context menu for group-name and clipboard actions.
        フォルダ名のグループ名反映・クリップボードコピー用メニューを構築する。
        """
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=_("フォルダ名をグループ名にする"),
            command=lambda: self._set_group_name_from_folder(g, folder),
        )
        menu.add_command(
            label=_("フォルダ名をコピーする"),
            command=lambda: self._copy_folder_name(folder),
        )
        return menu

    def _set_group_name_from_folder(self, g: Group, folder: str) -> None:
        """
        Rename the group to the selected folder's basename.
        選択したフォルダのベース名をグループ名に設定する。
        """
        new_name = os.path.basename(folder) or folder
        # Duplicate names are allowed because group color/order can still distinguish them.
        # グループ色や順序で識別できるため、同名は警告ログのみで許容する。
        if any(other is not g and other.name == new_name for other in self.groups):
            self._log(_("注意: 同名のグループ「{n}」が既に存在します。").format(n=new_name))
        g.name = new_name
        self._refresh_group_row(g)
        self._log(_("グループ名変更: {name}").format(name=new_name))

    def _copy_folder_name(self, folder: str) -> None:
        """
        Copy the selected folder's basename to the clipboard.
        選択したフォルダのベース名をクリップボードにコピーする。
        """
        name = os.path.basename(folder) or folder
        self.clipboard_clear()
        self.clipboard_append(name)
        self._log(_("フォルダ名をコピーしました: {name}").format(name=name))

    def _rename_group(self, g: Group) -> None:
        """
        Prompt for and apply a new group name.
        新しいグループ名を入力させ、反映する。
        """
        new_name = simpledialog.askstring(
            _("グループ名変更"),
            _("新しいグループ名を入力してください:"),
            initialvalue=g.name,
            parent=self,
        )
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        # Duplicate names are allowed because group color/order can still distinguish them.
        # グループ色や順序で識別できるため、同名は警告ログのみで許容する。
        if any(other is not g and other.name == new_name for other in self.groups):
            self._log(_("注意: 同名のグループ「{n}」が既に存在します。").format(n=new_name))
        g.name = new_name
        self._refresh_group_row(g)
        self._log(_("グループ名変更: {name}").format(name=new_name))

    def _change_color(self, g: Group) -> None:
        """
        Prompt for and apply a new group display color.
        新しいグループ表示色を選択させ、反映する。
        """
        rgb, hex_str = colorchooser.askcolor(color=g.color, title=_("グループ色を選択"), parent=self)
        if hex_str is None:
            return
        g.color = hex_str
        self._refresh_group_row(g)
        self._log(_("[{name}] 色を変更: {c}").format(name=g.name, c=hex_str))

    def on_run(self) -> None:
        """
        Validate settings and start histogram extraction in a worker thread.
        設定値を検証し、ワーカースレッドでヒストグラム抽出を開始する。
        """
        if self.is_running:
            return

        # Commit pending Entry values first; the commit callback may rerun this method.
        # 未確定 Entry を先に確定する。確定コールバックがこのメソッドを再実行する場合がある。
        had_unconfirmed = any(
            (e.get() != getter()) for (e, getter, _cb) in self._unconfirmed_entries
        )
        if had_unconfirmed:
            self._commit_all_unconfirmed(self._unconfirmed_entries)

        if not self.groups:
            messagebox.showwarning(_("入力不足"), _("グループが登録されていません。"))
            return
        non_empty_groups = [g for g in self.groups if g.folder_paths]
        if not non_empty_groups:
            messagebox.showwarning(
                _("入力不足"),
                _("どのグループにもフォルダが登録されていません。"),
            )
            return

        min_h = self.min_h
        max_h = self.max_h
        step = self.step
        fig_w = self.fig_w
        fig_h = self.fig_h
        label_fs = self.label_fs
        tick_fs = self.tick_fs
        ann_fs = self.ann_fs
        group_name_fs = self.group_name_fs

        # Validate committed values defensively in case a future code path bypasses Entry checks.
        # 将来 Entry 検証を迂回する経路が増えても壊れないよう、確定済み値も検証する。
        if step <= 0 or max_h <= min_h:
            messagebox.showerror(
                _("設定エラー"),
                _("ヒストグラム範囲が不正です（min < max かつ step > 0）。"),
            )
            return
        if fig_w <= 0 or fig_h <= 0 or label_fs <= 0 or tick_fs <= 0 or ann_fs <= 0 or group_name_fs <= 0:
            messagebox.showerror(
                _("設定エラー"),
                _("サイズ/フォントサイズは正の値にしてください。"),
            )
            return

        # Raw counts can mislead comparisons when group sizes differ.
        # グループ間でデータ数が異なる場合、生カウント比較は誤解を招きやすい。
        if self.yaxis_mode_var.get() == _("非表示") and len(non_empty_groups) >= 2:
            self._log(
                _("注意: グループ間でデータ数が異なる場合、生カウント比較は誤解を招く可能性があります。{density} または {percent} を推奨します。").format(
                    density="density", percent="percent"
                )
            )

        # Rescan immediately before analysis so folder contents reflect the current disk state.
        # 解析直前に再スキャンし、現在のディスク状態を反映する。
        self._rescan_all()
        total_pairs = sum(g.total_pairs() for g in self.groups)
        if total_pairs <= 0:
            messagebox.showerror(
                _("有効ペアなし"),
                _("有効な calibrated/skeletonized バンドルが見つかりません。ログを確認してください。"),
            )
            return

        self._set_running(True)

        # Pass lightweight dictionaries to the worker instead of mutable Group objects.
        # 変更され得る Group オブジェクトではなく、軽量な辞書をワーカーへ渡す。
        groups_payload = []
        for g in self.groups:
            if not g.folder_paths:
                continue
            groups_payload.append({
                "id": g.id,
                "name": g.name,
                "color": g.color,
                "folders": list(g.folder_paths),
            })

        self.ui_queue = queue.Queue()
        args = {
            "groups": groups_payload,
            "param": self.param,
            "unit": self.unit,
            "input_mode": self.input_mode,
            "apply_exclusions": bool(self.apply_exclusions_var.get()),
            "curvature_window": self.curvature_window,
            "plot_type": self.plot_type_var.get(),
            "min_h": min_h,
            "max_h": max_h,
            "step": step,
            "yaxis_mode": self.yaxis_mode_var.get(),
            "display_mode": self.display_mode_var.get(),
            "show_height_text": bool(self.show_height_text_var.get()),
            "fig_w": fig_w,
            "fig_h": fig_h,
            "label_fs": label_fs,
            "tick_fs": tick_fs,
            "ann_fs": ann_fs,
            "group_name_fs": group_name_fs,
        }

        threading.Thread(target=self._worker_run, args=(args,), daemon=True).start()
        self.after(60, self._poll_ui_queue)

    def _set_running(self, running: bool) -> None:
        """
        Enable or disable controls while a worker thread is active.
        ワーカースレッド実行中に操作部の有効/無効を切り替える。
        """
        self.is_running = running
        state = tk.DISABLED if running else tk.NORMAL
        for b in (
            self.btn_add_group, self.btn_remove_group,
            self.btn_move_up, self.btn_move_down, self.btn_clear_all,
            self.btn_add_folder, self.btn_remove_folder,
            self.btn_run,
        ):
            b.configure(state=state)

        # The selectors decide what the running worker is computing, so they
        # stay locked until it finishes; "readonly" is their enabled state.
        # セレクタは実行中のワーカーが何を計算するかを決めるため、完了まで
        # 操作を止める。有効時の状態は "readonly"。
        combo_state = tk.DISABLED if running else "readonly"
        for c in (self.cmb_param, self.cmb_unit, self.cmb_input):
            c.configure(state=combo_state)
        self.chk_exclusions.configure(
            state=tk.DISABLED
            if (running or self.input_mode != INPUT_BUNDLE)
            else tk.NORMAL
        )

    def _poll_ui_queue(self) -> None:
        """
        Drain worker messages and continue polling while analysis is running.
        ワーカーメッセージを処理し、解析中はポーリングを継続する。
        """
        def _on_done(payload):
            self._set_running(False)
            self._handle_done(payload)
            return False

        def _on_fatal(payload):
            self._set_running(False)
            messagebox.showerror(
                _("致命的エラー"),
                payload.get("text", _("不明なエラー")),
            )
            trace = payload.get("trace", "")
            if trace:
                self._log(trace)
            return False

        should_continue = drain_ui_queue(self.ui_queue, {
            "log": self._log,
            "done": _on_done,
            "fatal": _on_fatal,
        })
        if not should_continue:
            return
    
        if self.is_running:
            self.after(50, self._poll_ui_queue)

    def _collect_bundle_values(self, bundle_paths, param: str, unit: str,
                               input_mode: str = INPUT_BUNDLE,
                               apply_exclusions: bool = False,
                               curvature_window: float =
                               DEFAULT_CURVATURE_WINDOW_NM) -> tuple:
        """
        Collect one folder's samples for a quantity and aggregation unit.
        1 フォルダ分の標本を、計測量と集計単位に従って収集する。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles to read, all from one registered folder.
            読み込む ``.b2z`` バンドル。すべて同一の登録フォルダに属する。
        param
            Measured-quantity key from `PARAM_SPECS`.
            `PARAM_SPECS` の計測量キー。
        unit
            Aggregation-unit key deciding what one sample counts as.
            1 標本を何と数えるかを決める集計単位キー。

        Returns
        -------
        tuple
            ``(values, weights, n_fibers, n_images, load_errors)``. `weights`
            is None for every counted unit and holds the contour length in
            nanometers that each value represents under ``UNIT_LENGTH``.
            `n_fibers` counts the fibers that contributed at least one sample
            and is 0 in the skeleton-pixel path, where fibers are not
            individuated. `load_errors` holds ``(bundle_path, message)`` pairs.
            ``(値リスト, 重み, ファイバー数, 画像数, 読込エラー)``。`weights` は
            個数で数える単位では None、``UNIT_LENGTH`` では各値が代表する
            輪郭長 (nm)。`n_fibers` は 1 標本以上を出したファイバーの数で、
            ファイバーを個体として扱わない骨格画素経路では 0。`load_errors` は
            ``(バンドルパス, メッセージ)``。

        Notes
        -----
        Only the height/pixel combination avoids fiber tracing, which is why
        it is the one combination that works on bundles without a recorded
        scan size: everything else needs a physical pixel size to convert
        track steps into nanometers.
        ファイバー追跡を回避できるのは height/pixel の組み合わせだけであり、
        走査範囲が未記録のバンドルでも動くのはこの経路に限られる。他の経路は
        追跡ステップを nm へ変換するために物理ピクセルサイズを必要とする。
        """
        if input_mode == INPUT_FIBER_CSV:
            # The rows are already the curated population: GUI04 exports what
            # `_display_fibers` was showing, so filters, fiber connection, and
            # manual exclusions are baked in and nothing is re-applied here.
            # 行は既にキュレーション済みの母集団である。GUI04 は
            # `_display_fibers` が表示していたものを出力するため、フィルター・
            # ファイバー連結・手動除外は反映済みで、ここで再適用はしない。
            per_file, load_errors = collect_fiber_stats_from_csv(bundle_paths)
            return self._values_from_fiber_stats(per_file, param, unit) + (load_errors,)

        if param == PARAM_HEIGHT and unit == UNIT_PIXEL:
            heights, load_errors = skeleton_height_values(bundle_paths)
            failed = {path for path, _msg in load_errors}
            n_images = sum(1 for path in bundle_paths if path not in failed)
            return heights.tolist(), None, 0, n_images, load_errors

        if param == PARAM_HEIGHT and unit == UNIT_LENGTH:
            # Length weighting walks the traced fibers rather than the skeleton
            # mask, because the weight of a point is the contour length it
            # represents and only the ordered track gives the step lengths.
            # 長さ重み付けでは骨格マスクではなく追跡済みファイバーをたどる。点の
            # 重みはその点が代表する輪郭長であり、ステップ長は順序付けられた
            # トラックからしか得られないため。
            profiles, load_errors = collect_skeleton_height_profiles(
                bundle_paths, apply_exclusions=apply_exclusions,
            )
            values = []
            weights = []
            n_images = 0
            for _path, heights, point_weights in profiles:
                if heights.size == 0:
                    continue
                n_images += 1
                values.extend(heights.tolist())
                weights.extend(point_weights.tolist())
            # Fibers are traced here but not counted individually: the profiles
            # arrive concatenated, which is what the weighted statistics need.
            # ここではファイバーを追跡するが個体としては数えない。プロファイルは
            # 連結された形で届き、重み付き統計に必要なのはその形だからである。
            return values, weights, 0, n_images, load_errors

        if param == PARAM_CURVATURE:
            per_fiber, load_errors = collect_fiber_curvature(
                bundle_paths,
                apply_exclusions=apply_exclusions,
                curvature_window_nm=curvature_window,
            )
            self._log_curvature_caveats(per_fiber, curvature_window)
            return self._curvature_values(per_fiber, unit) + (load_errors,)

        per_bundle, load_errors = collect_fiber_stats(
            bundle_paths, apply_exclusions=apply_exclusions,
        )
        return self._values_from_fiber_stats(per_bundle, param, unit) + (load_errors,)

    def _log_curvature_caveats(self, per_fiber, curvature_window: float) -> None:
        """
        Report how many fibers the curvature window excluded.
        曲率窓が測定対象から外したファイバーの本数を報告する。

        Parameters
        ----------
        per_fiber
            ``(bundle_path, curvature)`` pairs.
            ``(バンドルパス, 曲率)`` の列。
        curvature_window
            Arc length the curvature estimator used.
            曲率推定が使った弧長。

        Notes
        -----
        The note exists because the number on screen can be read as a property
        of the specimen when it is partly a property of the measurement:
        raising the window drops every fiber shorter than it, changing which
        fibers the median describes.
        この注記が存在するのは、画面上の数値が試料の性質として読まれ得るが実際
        には一部が計測の性質であるためである。窓を大きくすると、それより短い
        ファイバーが全て落ち、中央値が記述する対象そのものが変わる。
        """
        if not per_fiber:
            return

        total = sum(int(c.size) for _p, c in per_fiber)
        measurable = sum(int(np.isfinite(c).sum()) for _p, c in per_fiber)
        if measurable < total:
            self.ui_queue.put(("log", _(
                "曲率窓 {w} nm より短いファイバー {n} 本 / {total} 本は測定"
                "対象外です。窓を広げるとさらに減ります。"
            ).format(
                w=self._fmt_num(curvature_window),
                n=total - measurable, total=total,
            )))

    @staticmethod
    def _curvature_values(per_fiber, unit: str) -> tuple:
        """
        Turn per-fiber curvature into samples at the requested unit.
        ファイバーごとの曲率を、要求された集計単位の標本へ変換する。

        Parameters
        ----------
        per_fiber
            ``(bundle_path, curvature)`` pairs from
            `lib.measure.collect_fiber_curvature`.
            `lib.measure.collect_fiber_curvature` が返す
            ``(バンドルパス, 曲率)`` の列。
        unit
            Aggregation-unit key.
            集計単位キー。

        Returns
        -------
        tuple
            ``(values, weights, n_fibers, n_images)``; `weights` is always
            None because the quantity counts objects.
            ``(値, 重み, ファイバー数, 画像数)``。個数を数える量であるため
            `weights` は常に None。
        """
        values = []
        n_fibers = 0
        n_images = 0
        for _path, curvature in per_fiber:
            measurable = curvature[np.isfinite(curvature)]
            if measurable.size == 0:
                continue
            n_fibers += int(measurable.size)
            n_images += 1
            if unit == UNIT_IMAGE:
                values.append(float(np.median(measurable)))
            else:
                values.extend(measurable.tolist())

        return values, None, n_fibers, n_images

    @staticmethod
    def _values_from_fiber_stats(per_source, param: str, unit: str) -> tuple:
        """
        Turn per-source fiber statistics into samples for one quantity/unit.
        ソースごとのファイバー統計を、計測量と集計単位に応じた標本へ変換する。

        Parameters
        ----------
        per_source
            ``(source_path, stats)`` pairs, one per bundle or per CSV file.
            ``(ソースパス, 統計値リスト)`` のペア。バンドルまたは CSV 1 件ごと。
        param
            Measured-quantity key from `PARAM_SPECS`.
            `PARAM_SPECS` の計測量キー。
        unit
            Aggregation-unit key.
            集計単位キー。

        Returns
        -------
        tuple
            ``(values, weights, n_fibers, n_images)``; `weights` is always
            None because these units count objects rather than length.
            ``(値リスト, 重み, ファイバー数, 画像数)``。これらの単位は長さでは
            なく個数を数えるため、`weights` は常に None。

        Notes
        -----
        Shared by the bundle and CSV paths so a curated CSV and the bundle it
        came from aggregate identically. That is what makes the two inputs
        comparable rather than merely similar.
        バンドル経路と CSV 経路で共有し、キュレーション済み CSV とその元となった
        バンドルが同一に集計されるようにする。これにより 2 つの入力が「似ている」
        ではなく「比較可能」になる。
        """
        values = []
        n_fibers = 0
        n_images = 0
        for _path, stats in per_source:
            source_values = []
            for stat in stats:
                samples = _fiber_samples(stat, param, unit)
                if not samples:
                    continue
                n_fibers += 1
                source_values.extend(samples)

            if not source_values:
                continue
            n_images += 1
            if unit == UNIT_IMAGE:
                # One sample per image, so a scan with many fibers does not
                # outweigh a sparse scan of the same specimen.
                # 1 画像 1 標本とし、ファイバーの多い画像が同じ試料の疎な画像を
                # 押しのけないようにする。
                values.append(float(np.median(source_values)))
            else:
                values.extend(source_values)

        return values, None, n_fibers, n_images

    def _worker_run(self, args: dict) -> None:
        """
        Compute histogram data in a background thread.
        バックグラウンドスレッドでヒストグラム用データを計算する。

        Tk widgets must only be touched on the main thread, so this worker
        returns log and result messages through ``self.ui_queue``.
        Tk ウィジェットはメインスレッドでのみ操作する必要があるため、
        このワーカーは ``self.ui_queue`` 経由でログと結果を返す。
        """
        groups = args["groups"]
        min_h = args["min_h"]
        max_h = args["max_h"]
        step = args["step"]
        param = args["param"]
        unit = args["unit"]
        input_mode = args["input_mode"]
        # Exclusions live beside a bundle; a fiber CSV already has them applied.
        # 除外はバンドル横にある。ファイバー CSV には既に適用済み。
        apply_exclusions = (
            args["apply_exclusions"] and input_mode == INPUT_BUNDLE
        )
        curvature_window = args["curvature_window"]

        # Skeleton pixels are read straight from the bundle arrays, so that
        # one combination needs no fiber tracing and no scan size. Every other
        # combination measures fibers and therefore cannot count "N fibers"
        # in the pixel case, where fibers are never individuated.
        # 骨格画素はバンドル配列から直接読むため、この組み合わせだけはファイバー
        # 追跡も走査範囲も不要である。他の組み合わせはファイバーを計測する。
        # 画素モードではファイバーを個体として切り出さないため、"N fibers" は
        # 数えられない。
        pixel_mode = (
            input_mode == INPUT_BUNDLE
            and param == PARAM_HEIGHT and unit == UNIT_PIXEL
        )
        # The length unit traces fibers but concatenates their profiles, so it
        # counts no individual fibers either.
        # length 単位はファイバーを追跡するがプロファイルを連結するため、こちらも
        # 個々のファイバーは数えない。
        counts_fibers = not (pixel_mode or (
            input_mode == INPUT_BUNDLE and unit == UNIT_LENGTH
        ))
        weighted = unit in LENGTH_WEIGHTED_UNITS

        results = []
        errors = []

        for grp in groups:
            grp_name = grp["name"]
            grp_values = []
            grp_weights = [] if weighted else None
            grp_fibers = 0 if counts_fibers else None
            grp_images = 0

            for folder in grp["folders"]:
                folder_name = os.path.basename(folder)
                pairs, missing_local = self._find_pairs(folder)
                for m in missing_local:
                    errors.append(
                        _("[{grp}/{folder}] {msg}").format(grp=grp_name, folder=folder_name, msg=m)
                    )

                if not pairs:
                    errors.append(
                        _("[{grp}/{folder}] 有効ペアがありません").format(grp=grp_name, folder=folder_name)
                    )
                    continue

                # Loading and measurement are delegated to lib.measure, the
                # same code path as `cli.py heights` / `cli.py measure`.
                # Per-bundle errors come back as fixed English strings and are
                # wrapped in translated group/folder context here.
                # 読み込みと計測は `cli.py heights` / `cli.py measure` と同一経路の
                # lib.measure へ委譲する。バンドルごとのエラーは固定英語文字列で
                # 返り、ここで翻訳済みのグループ/フォルダ文脈を付けて表示する。
                bundle_paths = [cal_path for cal_path, _skl_path in pairs]
                if not pixel_mode:
                    # Fiber tracing is far slower than reading skeleton pixels,
                    # so report progress instead of leaving the log silent.
                    # ファイバー追跡は骨格画素の読み出しよりはるかに遅いため、
                    # ログを無音にせず進捗を報告する。
                    self.ui_queue.put(("log", _(
                        "[{grp}/{folder}] {n} バンドルを計測中..."
                    ).format(grp=grp_name, folder=folder_name, n=len(bundle_paths))))


                try:
                    (values, weights, n_fibers, n_images,
                     load_errors) = self._collect_bundle_values(
                        bundle_paths, param, unit,
                        input_mode=input_mode,
                        apply_exclusions=apply_exclusions,
                        curvature_window=curvature_window,
                    )
                except Exception as e:
                    errors.append(
                        _("[{grp}/{folder}] {param} の抽出に失敗: {err}").format(
                            grp=grp_name, folder=folder_name, param=param, err=e
                        )
                    )
                    continue

                for failed_path, msg in load_errors:
                    suffix = INPUT_SUFFIXES[input_mode]
                    base = os.path.basename(failed_path)[:-len(suffix)]
                    errors.append(
                        _("[{grp}/{folder}] 読込失敗: {base} ({err})").format(
                            grp=grp_name, folder=folder_name, base=base, err=msg
                        )
                    )

                grp_values.extend(values)
                if grp_weights is not None:
                    grp_weights.extend(weights)
                grp_images += n_images
                if grp_fibers is not None:
                    grp_fibers += n_fibers

            if len(grp_values) == 0:
                errors.append(
                    _("[{grp}] データ 0 件のためスキップしました").format(grp=grp_name)
                )
                continue

            arr = np.asarray(grp_values, dtype=float)
            wts = None if grp_weights is None else np.asarray(grp_weights, dtype=float)
            # Quartiles accompany mean/std because fiber morphology
            # distributions are right-skewed; a median with its interquartile
            # range describes them without assuming symmetry.
            # 平均・標準偏差に加えて四分位数も求める。ファイバー形態の分布は
            # 右に裾を引くため、対称性を仮定しない中央値と四分位範囲での
            # 記述が必要になる。
            stats = _summary_stats(arr, wts)
            results.append({
                "id": grp["id"],
                "name": grp_name,
                "color": grp["color"],
                "values": arr,
                "weights": wts,
                "mean": stats["mean"],
                "std": stats["std"],
                "median": stats["median"],
                "q1": stats["q1"],
                "q3": stats["q3"],
                # The reported sample size is the total weight, which is a
                # count when the weights are implicit ones and a contour
                # length in nanometers under length weighting.
                # 報告する標本量は重みの合計。重みが暗黙の 1 なら件数、長さ
                # 重み付けなら輪郭長 (nm) になる。
                "n_samples": float(arr.size) if wts is None else float(wts.sum()),
                # The raw point count drives the "too few samples to read the
                # shape" notice, which is about the histogram, not the weight.
                # 「形状が読めるほど標本が無い」通知は生の点数で判断する。これは
                # 重みではなくヒストグラムについての話であるため。
                "n_raw": int(arr.size),
                "n_fibers": grp_fibers,
                "n_images": grp_images,
            })

        if not results:
            self.ui_queue.put(("fatal", {
                "text": _("どのグループからも {param} のデータを得られませんでした。"
                          "ログを確認してください。").format(param=param),
                "trace": "",
            }))
            return

        try:
            edges = np.arange(min_h, max_h, step)
        except Exception:
            self.ui_queue.put(("fatal", {
                "text": _("ヒストグラム範囲の準備に失敗しました。"),
                "trace": traceback.format_exc(),
            }))
            # Stop here: without `edges` the loop below raises UnboundLocalError
            # deep in this worker thread, where the traceback only reaches stderr
            # and is invisible in a windowed or frozen build. The range entries only
            # enforce min < max and step > 0, so a wide range with a fine step
            # (min=0, max=1e12, step=1e-6) still reaches this handler through
            # np.arange's MemoryError.
            # ここで処理を止める。`edges` が無いまま下のループへ進むとこのワーカー
            # スレッド内で UnboundLocalError となり、そのトレースバックは stderr にしか
            # 出ないためウィンドウアプリや凍結ビルドでは誰にも見えない。範囲入力が
            # 保証するのは min < max と step > 0 だけなので、広い範囲に細かい step
            # を与えると（min=0, max=1e12, step=1e-6）np.arange の MemoryError で
            # 実際にこのハンドラへ到達する。
            return

        for r in results:
            # Length weighting enters the histogram here as bin weights, so the
            # bars show contour length per bin instead of a point count and
            # agree with the weighted statistics above.
            # 長さ重み付けはビンの重みとしてここでヒストグラムに入る。棒はビン
            # ごとの点数ではなく輪郭長を表し、上の重み付き統計と一致する。
            counts, _edges = np.histogram(
                r["values"], bins=edges, weights=r["weights"], density=False,
            )
            total = float(counts.sum())
            r["counts"] = counts
            r["total"] = total
            if total > 0:
                k = int(np.argmax(counts))
                r["mode"] = float((edges[k] + edges[k + 1]) / 2.0)
            else:
                r["mode"] = float("nan")

            # Summary statistics describe the whole sample, while the bars show
            # only the selected range. Silently dropping out-of-range samples
            # from the figure would misrepresent the distribution, so report the
            # excluded share rather than leaving the difference invisible. A
            # share rather than a count because the sample size is a length,
            # not a count, under length weighting.
            # 要約統計量は全標本を、棒グラフは選択範囲のみを表す。範囲外の標本を
            # 黙って図から落とすと分布を誤って伝えるため、除外された割合を示す。
            # 件数ではなく割合にするのは、長さ重み付けでは標本量が件数ではなく
            # 長さになるため。
            outside = r["n_samples"] - total
            if outside > 0 and r["n_samples"] > 0:
                errors.append(
                    _("[{grp}] 標本の {pct}% がヒストグラム範囲外です"
                      "（統計値は範囲外を含む全標本から計算しています）").format(
                        grp=r["name"],
                        pct="{0:.1f}".format(100.0 * outside / r["n_samples"]),
                    )
                )

            # A histogram over a handful of samples shows no distribution
            # shape, which is the normal situation for the image unit: a group
            # holds as many samples as it holds scans. The table's median and
            # IQR remain meaningful there, so point at them instead of letting
            # a two-bar plot be read as a distribution.
            # 標本が数個しかないヒストグラムは分布の形を示さない。これは image
            # 単位では通常の状況で、グループの標本数は走査枚数そのものになる。
            # その場合もテーブルの中央値と四分位範囲は意味を持つため、2 本の棒を
            # 分布として読まれる前にそちらを参照するよう促す。
            if r["n_raw"] < MIN_SAMPLES_FOR_SHAPE:
                errors.append(
                    _("[{grp}] 標本が {n} 個しかないため、ヒストグラムの形状は"
                      "解釈できません。テーブルの median と IQR を参照してください。").format(
                        grp=r["name"], n=r["n_raw"]
                    )
                )

        # Between-group tests run here, on the samples as they were collected,
        # so the comparison always describes the same population the table and
        # the figure do.
        # 群間検定は収集した標本に対してここで実行する。比較が常に、テーブルと図が
        # 示すのと同じ母集団を記述するようにするためである。
        comparisons = []
        comparison_note = ""
        if len(results) < 2:
            comparison_note = _("比較には 2 群以上が必要です。")
        elif unit not in TESTABLE_UNITS:
            comparison_note = _(
                "{unit} 集計の標本は独立観測ではないため検定しません。"
                "{fiber} または {image} 集計に切り替えてください。"
            ).format(unit=unit, fiber=UNIT_FIBER, image=UNIT_IMAGE)
        else:
            try:
                comparisons = compare_groups(
                    [(r["name"], r["values"]) for r in results]
                )
            except Exception as e:
                comparison_note = _("群間比較に失敗しました: {err}").format(err=e)

        self.ui_queue.put(("done", {
            "results": results,
            "edges": edges,
            "param": param,
            "unit": unit,
            "comparisons": comparisons,
            "comparison_note": comparison_note,
            "plot_type": args["plot_type"],
            "yaxis_mode": args["yaxis_mode"],
            "display_mode": args["display_mode"],
            "show_height_text": args["show_height_text"],
            "fig_w": args["fig_w"],
            "fig_h": args["fig_h"],
            "label_fs": args["label_fs"],
            "tick_fs": args["tick_fs"],
            "ann_fs": args["ann_fs"],
            "group_name_fs": args["group_name_fs"],
            "errors": errors,
        }))

    def _handle_done(self, payload: dict) -> None:
        """
        Apply completed histogram results to tables, figures, and cached state.
        完了したヒストグラム結果を表、図、キャッシュ状態へ反映する。
        """
        results = payload["results"]
        edges = payload["edges"]
        param = payload["param"]
        unit = payload["unit"]
        plot_type = payload["plot_type"]
        yaxis_mode = payload["yaxis_mode"]
        display_mode = payload["display_mode"]
        show_height_text = payload["show_height_text"]
        fig_w = payload["fig_w"]
        fig_h = payload["fig_h"]
        label_fs = payload["label_fs"]
        tick_fs = payload["tick_fs"]
        ann_fs = payload["ann_fs"]
        group_name_fs = payload["group_name_fs"]
        errors = payload["errors"]

        for col, text in self._result_headings(param).items():
            self.result_tree.heading(col, text=text)
        self._update_result_caption(param, unit)
        self._last_comparisons = payload["comparisons"]
        self._populate_comparison_table(
            payload["comparisons"], payload["comparison_note"],
        )

        for iid in self.result_tree.get_children(""):
            self.result_tree.delete(iid)
        for r in results:
            mode_str = f"{r['mode']:.3f}" if not np.isnan(r["mode"]) else "-"
            self.result_tree.insert(
                "", tk.END,
                values=(
                    r["name"],
                    f"{r['median']:.3f}",
                    f"{r['q1']:.3f}–{r['q3']:.3f}",
                    f"{r['mean']:.3f}",
                    f"{r['std']:.3f}",
                    mode_str,
                    _format_sample_size(r["n_samples"], unit),
                    "-" if r["n_fibers"] is None else f"{r['n_fibers']:,}",
                    f"{r['n_images']:,}",
                ),
            )

        self._draw_figure(
            results=results,
            edges=edges,
            param=param,
            unit=unit,
            plot_type=plot_type,
            yaxis_mode=yaxis_mode,
            display_mode=display_mode,
            show_height_text=show_height_text,
            fig_w=fig_w,
            fig_h=fig_h,
            label_fs=label_fs,
            tick_fs=tick_fs,
            ann_fs=ann_fs,
            group_name_fs=group_name_fs,
        )

        # Cache results so display-only options can redraw without recomputing counts.
        # The quantity and unit are cached with them because a later redraw must
        # label the figure with what was measured, not with the current selector
        # value, which the user may already have changed.
        # 表示専用オプションでヒストグラム数を再計算せず再描画できるよう、結果を保持する。
        # 計測量と集計単位も併せて保持する。再描画時のラベルは、既に変更されている
        # かもしれない現在のセレクタ値ではなく、実際に計測した内容でなければならない。
        self._last_results = results
        self._last_edges = edges
        self._last_param = param
        self._last_unit = unit
        self._has_result = True
        self.btn_save_fig.configure(state=tk.NORMAL)
        self.btn_save_csv.configure(state=tk.NORMAL)
        self.btn_save_stats.configure(state=tk.NORMAL)

        # Non-fatal notices go to the log only. The run produced a result, and
        # the log panel is always on screen, so a modal dialog would add a
        # dismissal to every run without telling the user anything the log does
        # not already show. Most of these notices are routine — samples outside
        # the plotted range, a group too small for a histogram shape — and a
        # dialog that appears every time stops being read. A run that produces
        # nothing still raises the fatal dialog from _poll_ui_queue.
        # 非致命的な通知はログのみに出す。実行自体は結果を出しており、ログ欄は
        # 常に画面上にあるため、モーダルダイアログはログ以上の情報を与えないまま
        # 毎回クリックを強いるだけになる。これらの通知の大半は日常的なもので
        # （描画範囲外の標本、ヒストグラムの形が読めない小さなグループ）、毎回
        # 出るダイアログは読まれなくなる。結果が 1 つも出ない実行では、
        # _poll_ui_queue が従来どおり致命的エラーのダイアログを出す。
        if errors:
            self._log(_("=== エラー/注意（処理は継続しました） ==="))
            for e in errors:
                self._log(f"- {e}")
        else:
            self._log(_("完了"))

    @staticmethod
    def _format_p(value: float) -> str:
        """
        Format a p-value for the comparison table.
        比較テーブル用に p 値を整形する。

        Parameters
        ----------
        value
            Raw or adjusted p-value; NaN means the pair was not tested.
            生または補正後の p 値。NaN は未検定を意味する。

        Returns
        -------
        str
            Fixed decimals down to 0.001 and scientific notation below, so a
            very small p stays legible instead of collapsing to "0.000".
            0.001 までは固定小数、それ未満は指数表記。非常に小さい p 値が
            "0.000" に潰れず読めるようにする。
        """
        if not np.isfinite(value):
            return "-"
        if value < 0.001:
            return "{0:.1e}".format(value)
        return "{0:.3f}".format(value)

    def _populate_comparison_table(self, comparisons, note: str) -> None:
        """
        Fill the between-group comparison table and its note.
        群間比較テーブルと注記を埋める。

        Parameters
        ----------
        comparisons
            `lib.group_compare.PairComparison` rows, possibly empty.
            `lib.group_compare.PairComparison` の行。空の場合もある。
        note
            Explanation shown when no comparison was run.
            比較を実行しなかった場合に表示する説明。

        Notes
        -----
        The adjusted p-values are the ones shown, with the raw value beside
        them, because every pair of k groups is tested at once and reading the
        raw values alone would find a difference among four groups about a
        quarter of the time with none present.
        表示するのは補正後の p 値で、生の値は併記する。k 群のすべてのペアを同時に
        検定しており、生の値だけを見ると、差が無くても 4 群では約 1/4 の確率で
        どこかに差が見つかってしまうためである。
        """
        for iid in self.comparison_tree.get_children(""):
            self.comparison_tree.delete(iid)

        self.btn_save_comparison.configure(
            state=tk.NORMAL if comparisons else tk.DISABLED
        )
        if not comparisons:
            self.comparison_note_var.set(note)
            return

        self.comparison_note_var.set(
            _("p 値は Holm 補正後（括弧内は補正前）") if len(comparisons) > 1
            else _("p 値（2 群のため補正不要）")
        )
        for c in comparisons:
            if len(comparisons) > 1:
                u_text = "{adj} ({raw})".format(
                    adj=self._format_p(c.mannwhitney_p_adjusted),
                    raw=self._format_p(c.mannwhitney_p),
                )
                ks_text = "{adj} ({raw})".format(
                    adj=self._format_p(c.ks_p_adjusted),
                    raw=self._format_p(c.ks_p),
                )
            else:
                u_text = self._format_p(c.mannwhitney_p)
                ks_text = self._format_p(c.ks_p)

            self.comparison_tree.insert("", tk.END, values=(
                "{a} vs {b}".format(a=c.group_a, b=c.group_b),
                "{a:,} / {b:,}".format(a=c.n_a, b=c.n_b),
                u_text,
                ks_text,
                "-" if not np.isfinite(c.cliffs_delta) else "{0:+.3f}".format(
                    c.cliffs_delta
                ),
                c.magnitude or "-",
            ))

    def _finish_figure(self) -> None:
        """
        Lay out the figure and resize the scrollable canvas around it.
        Figure のレイアウトを整え、スクロール可能なキャンバスを合わせて調整する。
        """
        try:
            self.fig.tight_layout()
        except Exception:
            # Keep the GUI responsive even if Matplotlib cannot fit the layout.
            # レイアウトに失敗しても GUI をクラッシュさせない。
            pass

        self.canvas.get_tk_widget().configure(
            width=int(self.fig.get_size_inches()[0] * self.fig.get_dpi()),
            height=int(self.fig.get_size_inches()[1] * self.fig.get_dpi()),
        )
        self.canvas.draw()
        self._inner_frame.update_idletasks()
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _draw_ecdf(self, *, results, param, fig_w, fig_h,
                   label_fs, tick_fs, group_name_fs) -> None:
        """
        Draw one overlaid empirical cumulative distribution per group.
        群ごとの経験累積分布を 1 つの軸へ重ねて描画する。

        Notes
        -----
        The ECDF uses every sample at its own value, so unlike the histogram it
        has no bin width to choose and cannot be made to show or hide a
        difference by changing one. Overlaid curves also make the separation
        between two groups readable directly as the horizontal gap, which is
        what the effect size in the comparison table quantifies.
        ECDF は各標本をその値のまま使うため、ヒストグラムと違いビン幅の選択が
        なく、ビン幅を変えて差を見せたり隠したりすることができない。曲線を重ねる
        と 2 群の隔たりが水平方向の差として直接読み取れる。これは比較テーブルの
        効果量が数値化しているものでもある。
        """
        self.fig.clf()
        self.fig.set_size_inches(fig_w, fig_h, forward=True)
        ax = self.fig.add_subplot(111)
        spec = PARAM_SPECS[param]

        for r in results:
            values = np.asarray(r["values"], dtype=float)
            if values.size == 0:
                continue
            order = np.argsort(values)
            sorted_values = values[order]
            if r["weights"] is None:
                weights = np.ones(sorted_values.shape, dtype=float)
            else:
                weights = np.asarray(r["weights"], dtype=float)[order]
            # Weighted cumulative fraction, so the length unit's curve is the
            # fraction of observed contour length below each value rather than
            # the fraction of sampled points.
            # 重み付き累積割合。length 単位の曲線が、サンプル点の割合ではなく、
            # 各値以下にある観測輪郭長の割合を表すようにする。
            cumulative = np.cumsum(weights) / float(weights.sum())
            ax.step(
                sorted_values, cumulative, where="post",
                color=r["color"], label=r["name"], linewidth=1.6,
            )

        ax.set_xlabel(spec["axis_label"], fontsize=label_fs)
        ax.set_ylabel("cumulative fraction", fontsize=label_fs)
        ax.set_ylim(0.0, 1.02)
        ax.tick_params(axis="both", labelsize=tick_fs)
        if len(results) >= 2:
            ax.legend(fontsize=group_name_fs, loc="lower right")
        self._finish_figure()

    def _draw_box(self, *, results, param, fig_w, fig_h,
                  label_fs, tick_fs, group_name_fs) -> None:
        """
        Draw one box per group from the statistics the table reports.
        テーブルが報告する統計量から、群ごとに 1 つの箱を描画する。

        Notes
        -----
        The boxes are drawn from precomputed quartiles rather than by handing
        Matplotlib the raw samples, so the box and the statistics table can
        never disagree -- and so the length unit's boxes use its weighted
        quartiles, which Matplotlib's own boxplot has no way to compute.
        箱は生の標本を Matplotlib に渡すのではなく、あらかじめ計算した四分位数
        から描く。これにより箱と統計量テーブルが食い違うことがなく、また length
        単位では重み付き四分位数を使える。Matplotlib の boxplot 自身にはこれを
        計算する手段が無い。
        """
        self.fig.clf()
        self.fig.set_size_inches(fig_w, fig_h, forward=True)
        ax = self.fig.add_subplot(111)
        spec = PARAM_SPECS[param]

        stats = []
        for r in results:
            values = np.asarray(r["values"], dtype=float)
            iqr = r["q3"] - r["q1"]
            # Tukey fences: the whiskers reach the furthest sample still within
            # 1.5 IQR of the box, which is a property of the values present and
            # so is read from the samples rather than from the weights.
            # Tukey のフェンス。ひげは箱から 1.5 IQR 以内にある最も遠い標本まで
            # 伸びる。これは存在する値の性質であるため、重みではなく標本から読む。
            low_fence = r["q1"] - 1.5 * iqr
            high_fence = r["q3"] + 1.5 * iqr
            inside = values[(values >= low_fence) & (values <= high_fence)]
            stats.append({
                "label": r["name"],
                "med": r["median"],
                "q1": r["q1"],
                "q3": r["q3"],
                "whislo": float(inside.min()) if inside.size else r["q1"],
                "whishi": float(inside.max()) if inside.size else r["q3"],
                "fliers": [],
            })

        artists = ax.bxp(stats, showfliers=False, patch_artist=True)
        for patch, r in zip(artists["boxes"], results):
            patch.set_facecolor(r["color"])
            patch.set_alpha(0.55)
            patch.set_edgecolor(r["color"])
        for median in artists["medians"]:
            median.set_color("black")

        ax.set_ylabel(spec["axis_label"], fontsize=label_fs)
        ax.tick_params(axis="y", labelsize=tick_fs)
        ax.tick_params(axis="x", labelsize=group_name_fs)
        self._finish_figure()

    def _draw_figure(self, *, results, edges, param, unit, plot_type,
                     yaxis_mode, display_mode,
                     show_height_text, fig_w, fig_h,
                     label_fs, tick_fs, ann_fs, group_name_fs):
        """
        Draw the latest group results as the selected plot type.
        最新のグループ別結果を、選択された種類の図として描画する。
        """
        if plot_type == PLOT_ECDF:
            self._draw_ecdf(
                results=results, param=param, fig_w=fig_w, fig_h=fig_h,
                label_fs=label_fs, tick_fs=tick_fs, group_name_fs=group_name_fs,
            )
            return
        if plot_type == PLOT_BOX:
            self._draw_box(
                results=results, param=param, fig_w=fig_w, fig_h=fig_h,
                label_fs=label_fs, tick_fs=tick_fs, group_name_fs=group_name_fs,
            )
            return

        self.fig.clf()
        widths = np.diff(edges)
        spec = PARAM_SPECS[param]
        # Figure text uses the Matplotlib spelling of the unit; see
        # UNIT_PER_MICROMETER for why the two spellings exist.
        # 図中のテキストは Matplotlib 用の単位表記を使う。2 つの表記がある理由は
        # UNIT_PER_MICROMETER を参照。
        value_unit = spec["value_unit_plot"]
        sample_noun = UNIT_NOUNS.get(unit, unit)

        def compute_y_and_label(counts, total):
            """
            Convert raw bin counts into the selected y-axis representation.
            生のビンカウントを選択中の y 軸表現へ変換する。
            """
            total_for_div = total if total > 0 else 1
            if yaxis_mode == _("非表示"):
                return counts.astype(float), ""
            elif yaxis_mode == "density":
                return counts / total_for_div, "density"
            else:
                return (counts / total_for_div) * 100.0, "Frequency (%)"

        def annotate_height_stats(ax, r):
            """
            Draw the summary-statistics annotation box for one group.
            1 グループ分の要約統計量の注釈ボックスを描画する。

            Notes
            -----
            The annotation is fixed English because it is figure text that
            ends up in publications. It reports the median with its
            interquartile range alongside mean ± SD, and states the sample
            size in units of what was actually counted, so a reader can tell
            a distribution over skeleton pixels from one over fibers.
            この注釈は論文図に載る図中テキストのため固定英語とする。平均 ± 標準
            偏差に加えて中央値と四分位範囲を示し、標本数は実際に数えた単位で
            表記する。これにより、骨格画素の分布とファイバーの分布を読者が
            区別できる。
            """
            lines = [
                "{p} = {m} ± {s} {u}".format(
                    p=param, m=f"{r['mean']:.2f}", s=f"{r['std']:.2f}", u=value_unit,
                ),
                "median = {md} {u} (IQR {q1}–{q3})".format(
                    md=f"{r['median']:.2f}", u=value_unit,
                    q1=f"{r['q1']:.2f}", q3=f"{r['q3']:.2f}",
                ),
                "mode = {mo} {u}".format(
                    mo=f"{r['mode']:.2f}" if not np.isnan(r["mode"]) else "-",
                    u=value_unit,
                ),
            ]
            n_parts = ["{n} {noun}".format(
                n=_format_sample_size(r["n_samples"], unit), noun=sample_noun,
            )]
            if r["n_fibers"] is not None and unit != UNIT_FIBER:
                n_parts.append("{n:,} fibers".format(n=r["n_fibers"]))
            if unit != UNIT_IMAGE:
                n_parts.append("{n:,} images".format(n=r["n_images"]))
            lines.append("N = " + ", ".join(n_parts))

            # Anchored to the right edge so the box grows leftwards. Left
            # anchoring clipped the longer lines this annotation now carries
            # (a median with its IQR is far wider than a bare mean), and
            # clipped text loses the number entirely, whereas overlapping a
            # bar still reads.
            # 右端を基準にし、ボックスが左へ伸びるようにする。左端基準では、
            # 中央値と四分位範囲を含む長い行が切れてしまう。切れると数値自体が
            # 失われるのに対し、棒と重なるだけなら判読できる。
            ax.text(
                0.98, 0.95, "\n".join(lines),
                transform=ax.transAxes, ha="right", va="top",
                fontsize=ann_fs,
            )

        n = len(results)

        if display_mode == self.MODE_OVERLAY or n == 1:
            # A single group uses the overlay path because stacked and overlay views are equivalent.
            # 単一グループでは縦並びと重ね表示が同等なため、重ね表示経路に統一する。
            self.fig.set_size_inches(fig_w, fig_h, forward=True)
            ax = self.fig.add_subplot(111)

            for r in results:
                y, ylabel = compute_y_and_label(r["counts"], r["total"])
                alpha = 1.0 if n == 1 else 0.5
                ax.bar(
                    edges[:-1], y, width=widths, align="edge",
                    color=r["color"], alpha=alpha,
                    label=r["name"], edgecolor="none",
                )

            if yaxis_mode == _("非表示"):
                ax.set_yticks([])
            else:
                ax.set_ylabel(ylabel, fontsize=label_fs)

            ax.set_xlabel(spec["axis_label"], fontsize=label_fs)
            ax.tick_params(axis="both", labelsize=tick_fs)

            if n >= 2:
                ax.legend(fontsize=group_name_fs, loc="upper right")

            if show_height_text and n == 1:
                annotate_height_stats(ax, results[0])

        else:
            # In stacked mode, fig_h is the height per subplot, so the figure scales with n.
            # 縦並び時は fig_h を 1 サブプロット分として解釈し、Figure 全体を n 倍する。
            self.fig.set_size_inches(fig_w, fig_h * n, forward=True)
            axes = self.fig.subplots(nrows=n, ncols=1, sharex=True)
            if n == 1:
                axes = [axes]

            for ax, r in zip(axes, results):
                y, ylabel = compute_y_and_label(r["counts"], r["total"])
                ax.bar(
                    edges[:-1], y, width=widths, align="edge",
                    color=r["color"], edgecolor="none",
                )
                ax.set_title(r["name"], loc="left", fontsize=group_name_fs, color=r["color"])

                if yaxis_mode == _("非表示"):
                    ax.set_yticks([])
                else:
                    ax.set_ylabel(ylabel, fontsize=label_fs)

                ax.tick_params(axis="both", labelsize=tick_fs)

                if show_height_text:
                    annotate_height_stats(ax, r)

            axes[-1].set_xlabel(spec["axis_label"], fontsize=label_fs)

        try:
            self.fig.tight_layout()
        except Exception:
            # Keep the GUI responsive even if Matplotlib cannot fit many subplots cleanly.
            # サブプロットが多く配置に失敗しても、GUI をクラッシュさせない。
            pass

        self.canvas.get_tk_widget().configure(
            width=int(self.fig.get_size_inches()[0] * self.fig.get_dpi()),
            height=int(self.fig.get_size_inches()[1] * self.fig.get_dpi()),
        )
        self.canvas.draw()
        self._inner_frame.update_idletasks()
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _reset_result_state(self) -> None:
        """
        Clear cached histogram results and disable result export controls.
        キャッシュ済みヒストグラム結果を消去し、結果出力操作を無効化する。
        """
        for iid in self.result_tree.get_children(""):
            self.result_tree.delete(iid)

        for iid in self.comparison_tree.get_children(""):
            self.comparison_tree.delete(iid)
        self.comparison_note_var.set("")
        self._last_comparisons = []
        self.btn_save_comparison.configure(state=tk.DISABLED)

        self.btn_save_fig.configure(state=tk.DISABLED)
        self.btn_save_csv.configure(state=tk.DISABLED)
        self.btn_save_stats.configure(state=tk.DISABLED)
        self._last_results = None
        self._last_edges = None
        self._last_param = None
        self._last_unit = None
        self._has_result = False

        self.fig.clf()
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel(PARAM_SPECS[self.param]["axis_label"])
        self.ax.set_yticks([])
        self.canvas.draw()

    def on_save_fig(self) -> None:
        """
        Save the currently displayed histogram figure through a dialog.
        現在表示中のヒストグラム図をダイアログ経由で保存する。
        """
        if not self._has_result:
            messagebox.showwarning(_("未作成"), _("先にヒストグラムを作成してください。"))
            return
        save_figure_with_dialog(
            self, self.fig,
            initial_name="histogram.png",
            initial_dir=self._default_save_dir(),
            title=_("画像を保存"),
            log_cb=self._log,
        )

    def on_save_csv(self) -> None:
        """
        Export the raw sampled values of each group as CSV files.
        各グループのサンプリング済みの値を CSV ファイルとして出力する。
        """
        if not self._has_result or not self._last_results:
            messagebox.showwarning(_("未作成"), _("先にヒストグラムを作成してください。"))
            return

        out_dir = filedialog.askdirectory(
            title=_("CSV 保存先フォルダを選択"),
            initialdir=self._default_save_dir(),
        )
        if not out_dir:
            return

        # The quantity and unit go in the file name because the rows carry a
        # bare number: without them, exported files of different quantities
        # are indistinguishable once they leave this window.
        # 行は数値のみを持つため、計測量と集計単位はファイル名に入れる。これが
        # 無いと、このウィンドウを離れた時点で別々の計測量の出力を区別できない。
        stem_suffix = "{slug}_{unit}".format(
            slug=PARAM_SPECS[self._last_param]["slug"], unit=self._last_unit,
        )

        used_names = set()
        saved_paths = []
        try:
            for r in self._last_results:
                base_name = _sanitize_filename(r["name"])
                # Add suffixes only when duplicate group names would collide on disk.
                # 同名グループでファイル名が衝突する場合のみ通番を付与する。
                candidate = f"{base_name}_{stem_suffix}"
                suffix_idx = 2
                while candidate in used_names:
                    candidate = f"{base_name}_{stem_suffix}_{suffix_idx}"
                    suffix_idx += 1
                used_names.add(candidate)

                path = os.path.join(out_dir, candidate + ".csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if r["weights"] is None:
                        # Preserve the raw-data CSV contract: one sampled value per row.
                        # 生データ CSV の契約として、1 行 1 標本値で保存する。
                        for v in r["values"]:
                            w.writerow([float(v)])
                    else:
                        # A length-weighted sample needs its weights exported
                        # too. Without them the file recomputes an unweighted
                        # distribution and silently disagrees with the figure
                        # and the statistics it came from.
                        # 長さ重み付けの標本は重みも併せて出力する必要がある。重み
                        # が無いと、そのファイルからは重みなしの分布が再計算され、
                        # 元の図や統計値と黙って食い違ってしまう。
                        w.writerow(["value_nm", "weight_nm"])
                        for v, wt in zip(r["values"], r["weights"]):
                            w.writerow([float(v), float(wt)])
                saved_paths.append(path)

            self._log(
                _("{n} 個のCSVを保存しました → {dir}").format(n=len(saved_paths), dir=out_dir)
            )
            for p in saved_paths:
                self._log(f"  - {p}")
        except Exception as e:
            messagebox.showerror(_("保存失敗"), _("CSVの保存に失敗しました:\n{e}").format(e=e))

    def on_save_comparison(self) -> None:
        """
        Export the between-group comparison as a CSV file.
        群間比較を CSV ファイルとして出力する。

        Notes
        -----
        Both the raw and the Holm-adjusted p-values are written. The adjusted
        one is what a conclusion rests on, but the raw value is what another
        correction could be recomputed from, so dropping it would make the
        exported table impossible to re-analyze.
        生の p 値と Holm 補正後の p 値をどちらも書き出す。結論の根拠になるのは
        補正後の値だが、別の補正法を計算し直せるのは生の値からである。落とすと
        出力した表を再解析できなくなる。
        """
        if not self._last_comparisons:
            messagebox.showwarning(_("未作成"), _("先に群間比較を実行してください。"))
            return

        default_name = "group_comparison_{ts}.csv".format(
            ts=datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        def _write(path):
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                # Fixed English headers, like every other exported table.
                # 他の出力表と同様、ヘッダは固定英語とする。
                w.writerow([
                    "quantity", "sample unit",
                    "group A", "group B", "N A", "N B",
                    "Mann-Whitney p", "Mann-Whitney p (Holm)",
                    "KS p", "KS p (Holm)",
                    "Cliff's delta", "effect",
                ])
                for c in self._last_comparisons:
                    w.writerow([
                        self._last_param, self._last_unit,
                        c.group_a, c.group_b, c.n_a, c.n_b,
                        _blank_if_nan(c.mannwhitney_p),
                        _blank_if_nan(c.mannwhitney_p_adjusted),
                        _blank_if_nan(c.ks_p),
                        _blank_if_nan(c.ks_p_adjusted),
                        _blank_if_nan(c.cliffs_delta, "{0:.4f}"),
                        c.magnitude,
                    ])

        save_csv_with_dialog(
            self,
            _write,
            initial_dir=self._default_save_dir(),
            initial_name=default_name,
            title=_("比較を保存"),
            log_cb=self._log,
            success_message=_("群間比較を保存しました → {path}"),
            error_title=_("保存失敗"),
        )

    def on_save_log(self) -> None:
        """
        Save the analysis log text through a file dialog.
        解析ログ本文をファイルダイアログ経由で保存する。
        """
        default_name = "histogram_log_{ts}.txt".format(
            ts=datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        save_text_widget_log(
            self,
            self.log_text,
            initial_dir=self._default_save_dir(),
            initialfile=default_name,
            empty_warning=True,
            log_cb=self._log,
        )

    def on_save_stats(self) -> None:
        """
        Export summary statistics for the latest histogram results.
        最新のヒストグラム結果に対する要約統計量を出力する。
        """
        if not self._has_result or not self._last_results:
            messagebox.showwarning(_("未作成"), _("先にヒストグラムを作成してください。"))
            return

        default_name = "histogram_stats_{ts}.csv".format(
            ts=datetime.now().strftime("%Y%m%d_%H%M%S")
        )

        value_unit = PARAM_SPECS[self._last_param]["value_unit"]

        def _write_stats(path):
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([
                    # Keep the data-column header language-independent for exported CSV.
                    # 出力 CSV のデータ列ヘッダは言語非依存にする。
                    "Group",
                    "quantity",
                    "sample unit",
                    "median ({0})".format(value_unit),
                    "Q1 ({0})".format(value_unit),
                    "Q3 ({0})".format(value_unit),
                    "mean ({0})".format(value_unit),
                    "std ({0})".format(value_unit),
                    "mode ({0})".format(value_unit),
                    # N samples is the whole sample the statistics describe;
                    # N in range is what the drawn bars contain. Both are
                    # counts for the counted units and a contour length in
                    # micrometers under length weighting, which is what the
                    # "sample unit" column identifies.
                    # N samples は統計量の母体となる全標本量、N in range は
                    # 描画された棒に含まれる標本量。どちらも個数で数える単位では
                    # 件数、長さ重み付けでは輪郭長 (µm) であり、その区別は
                    # "sample unit" 列が示す。
                    "N samples",
                    "N in range",
                    "N fibers",
                    "N images",
                ])
                for r in self._last_results:
                    mode_val = "" if np.isnan(r["mode"]) else f"{r['mode']:.3f}"
                    w.writerow([
                        r["name"],
                        self._last_param,
                        self._last_unit,
                        f"{r['median']:.3f}",
                        f"{r['q1']:.3f}",
                        f"{r['q3']:.3f}",
                        f"{r['mean']:.3f}",
                        f"{r['std']:.3f}",
                        mode_val,
                        _sample_size_csv_value(r["n_samples"], self._last_unit),
                        _sample_size_csv_value(r["total"], self._last_unit),
                        "" if r["n_fibers"] is None else int(r["n_fibers"]),
                        int(r["n_images"]),
                    ])

        save_csv_with_dialog(
            self,
            _write_stats,
            initial_dir=self._default_save_dir(),
            initial_name=default_name,
            title=_("統計値を保存"),
            log_cb=self._log,
            success_message=_("統計値を保存しました → {path}"),
            error_title=_("保存失敗"),
        )

def main() -> None:
    """
    Launch the fiber height histogram GUI.
    繊維高さヒストグラム GUI を起動する。
    """
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
