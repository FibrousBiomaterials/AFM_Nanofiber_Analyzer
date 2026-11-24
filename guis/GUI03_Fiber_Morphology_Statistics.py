"""
Interactive fiber morphology statistics GUI for AFM nanofiber analysis.
AFM ナノファイバー解析用の形態パラメータ統計 GUI。

Loads ``.b2z`` bundles produced by the image preprocessor and summarizes the
distribution of one morphological quantity — height, contour length,
straightness, curvature, or kink density — for one group or across
user-defined groups. Bundles are registered file by file, each in a group; a
group stands for one specimen, and its bundles are aggregated together. A
bundle is moved to another group by dragging its row, and the calibrated height
image of the selected bundle is shown beside the list.
画像前処理 GUI が出力した ``.b2z`` バンドルを読み込み、形態パラメータ（高さ・
輪郭長・直線度・曲率・キンク密度）のいずれか 1 つの分布を、1 つの
グループについて、またはユーザー定義グループ間で要約する。バンドルはファイル
単位でグループに登録する。グループは 1 つの試料を表し、そのバンドルをまとめて
集計する。バンドルは行をドラッグして別のグループへ移せ、選択中のバンドルの補正済み
高さ像を一覧の隣に表示する。

The aggregation unit selects what counts as one sample: a skeleton pixel, a
fiber, or a whole image. This matters for reporting because pooled
skeleton pixels are not independent observations — a long fiber contributes
more pixels than a short one, and neighboring pixels of one fiber repeat the
same object — so group comparisons should also be inspected per fiber or per
image. Fibers of one image share that scan as well, so a comparison that
allows for the difference between places on a specimen is made per image.
集計単位は「1 標本」を何と数えるかを選ぶ（骨格画素・ファイバー 1 本・画像
1 枚）。骨格画素をまとめた分布は独立観測ではなく（長いファイバーほど
多くの画素を出し、同一ファイバーの隣接画素は同じ対象の繰り返しになる）、群間比較
ではファイバー単位・画像単位でも確認する必要があるため、報告上この区別が重要に
なる。同じ画像のファイバーもその走査を共有するため、試料上の場所ごとの違いを
踏まえた比較は画像単位で行う。

The summary statistics and the between-group comparison are shown in a window
of their own, opened from the main window. Nothing is written automatically.
Through file dialogs the user saves the histogram figure, the sampled values of
each group (one CSV per group), the summary statistics (CSV), the between-group
comparison (CSV), and the log.
要約統計量と群間比較は、メインウィンドウから開く別のウィンドウに表示する。自動では
何も書き出さない。ファイルダイアログから、ヒストグラム図、各グループの標本値
（グループごとに 1 つの CSV）、要約統計量 (CSV)、群間比較 (CSV)、ログを保存する。
"""

# ===== Plugin metadata =====
# Main.py reads this dictionary with AST parsing for the launcher screen.
# Main.py がこのファイルを読み込む際、AST（構文解析）でこの辞書を取得してランチャー画面に表示する。
# Values must remain plain string literals because they are passed to literal_eval.
# 値は literal_eval 対象のため文字列リテラルのまま（gettext の _() は付けない）。
PLUGIN_INFO = {
    "name": "Fiber Morphology Statistics",
    "description": (
        "AFMで撮影したナノファイバーの形態パラメータの分布と統計量をGUIで求めるプログラムです。\n"
        "入力データには、Image Preprocessor が出力する .b2z バンドルファイルを使います。ファイルをグループごとに登録し、選択中のファイルの背景補正済みの高さ像を確認できます。\n"
        "計測量は height（高さ）、contour length（輪郭長）、straightness（直線度）、curvature（曲率）、kink density（キンク密度）から選べ、骨格画素単位の高さ以外はファイバー追跡結果から算出します。\n"
        "集計単位（骨格画素・ファイバー・画像）を切り替えられるため、画素をまとめた分布だけでなく、ファイバー単位・画像単位の分布としても確認できます。\n"
        "図はヒストグラム・ECDF・箱ひげ図から選べ、中央値・四分位範囲・平均・標準偏差・最頻値と、標本数の内訳を併記します。複数のデータ群（グループ）を登録すると、縦並び・重ね表示で比較でき、ファイバー単位・画像単位では群間検定の結果も表示します。"
    )
}

# ===== Standard library =====
import os
import re
import sys
import csv
import uuid
import queue
import threading
import traceback
from datetime import datetime
from types import SimpleNamespace

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
from afm_nanofiber_analyzer.blosc2_io import BUNDLE_EXT, bundle_array_shape, load_bundle, load_bundle_meta
from afm_nanofiber_analyzer.bundle_schema import (
    APPARENT_WIDTH_KEY, SOURCE_REGION_KEY, centerline_from_meta,
    kink_params_from_meta, pixel_size_nm, scan_size_um_from_meta,
)
from afm_nanofiber_analyzer.centerline import (
    DEFAULT_CENTERLINE_METHOD, SKELETON_PIXEL_LINE, SKELETON_TRACK,
)
from afm_nanofiber_analyzer.connect_selection import (
    CONNECT_SUFFIX, connect_path_for, load_connect_plan,
)
from afm_nanofiber_analyzer.group_compare import compare_groups
from afm_nanofiber_analyzer.measure import (
    DEFAULT_CURVATURE_WINDOW_NM,
    collect_fiber_curvature, collect_fiber_stats,
    fiber_judged_length_um,
    fiber_real_end_count, kaplan_meier_length_weights, length_floor_nm,
    skeleton_height_values,
)
from afm_nanofiber_analyzer.plugin_launch import read_path_arguments
from afm_nanofiber_analyzer.translator import _
from afm_nanofiber_analyzer.ui_tools import (
    apply_window_size, setup_matplotlib_style, save_figure_with_dialog,
    setup_ttk_theme,
    save_text_widget_log, create_scrolled_text, create_scrolled_treeview,
    drain_ui_queue, save_csv_with_dialog, bind_mousewheel_scroll,
    compute_auto_vrange, read_height_image, UNIT_MICROMETER, ToolTip,
    UnconfirmedEntryMixin, LogMixin,
)


# ===== Measured quantities and aggregation units =====
# These are internal state keys and plot text, so they stay fixed English and
# are never wrapped with _(): they name axes, CSV columns, and exported labels.
# これらは内部状態キー兼プロット表記のため、固定英語のままとし _() を付けない。
# 軸ラベル・CSV 列・出力ラベルに使われる。
PARAM_HEIGHT = "height"
PARAM_LENGTH = "contour length"
PARAM_KINK_DENSITY = "kink density"
PARAM_STRAIGHTNESS = "straightness"
PARAM_CURVATURE = "curvature"

UNIT_PIXEL = "pixel"
UNIT_FIBER = "fiber"
UNIT_IMAGE = "image"

# Name of a scan-line-range analysis, as `afm_nanofiber_analyzer.pipeline.row_range_suffix` writes
# it after the input's stem (the bundle extension removed). Parsed here rather
# than imported because a reader must not import the pipeline.
# `afm_nanofiber_analyzer.pipeline.row_range_suffix` が入力のステムの後ろに書く、走査線範囲の解析の
# 名前（バンドルの拡張子は除く）。読み取り側はパイプラインを import しては
# ならないため、ここで解析する。
_ROW_RANGE_NAME = re.compile(r"^(?P<stem>.+)_r(?P<start>\d+)-(?P<stop>\d+)$")

# Pointer travel, in pixels, from which a press on a file row is a drag
# rather than a click, and the band at the top and bottom of the list in
# which a drag scrolls it.
# ファイル行での押下を、クリックではなくドラッグとみなすポインタの移動量（px）と、
# ドラッグ中に一覧をスクロールさせる上下端の帯の幅。
DRAG_THRESHOLD_PX = 6
DRAG_SCROLL_BAND_PX = 18

# Tag marking the group row a dragged file would be dropped into, and its
# background color.
# ドラッグ中のファイルを落とす先のグループ行に付けるタグと、その背景色。
DROP_TARGET_TAG = "drop_target"
DROP_TARGET_COLOR = "#cfe2f3"

# Colormap of the bundle preview, the one GUI02 and GUI04 draw height images
# with, and how many previews stay in memory so stepping back through the
# list does not read the files again.
# バンドルのプレビューのカラーマップ（GUI02・GUI04 が高さ像の描画に使うもの）と、
# 一覧を戻るときにファイルを読み直さずに済むよう、メモリに残すプレビューの数。
PREVIEW_COLORMAP = "afmhot"
PREVIEW_CACHE_SIZE = 8
# Delay, in milliseconds, between a selection change and the read of its
# bundle, so moving through the list with the arrow keys reads only the row
# the selection rests on.
# 選択の変化からバンドルを読むまでの待ち時間（ミリ秒）。矢印キーで一覧を移動した
# とき、選択が止まった行だけを読むようにする。
PREVIEW_DELAY_MS = 150

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
# excluded on principle rather than for convenience: skeleton pixels are not
# independent observations of a specimen, and several kinks come from one
# fiber, so a p-value over them measures how finely the images were sampled
# instead of whether the specimens differ.
# 群間検定を適用できる集計単位。他を外すのは便宜ではなく原理による。骨格画素は
# 試料の独立観測ではなく、複数のキンクは 1 本のファイバーから来る。それらに
# 対する p 値は、試料が異なるかどうかではなく、画像をどれだけ細かくサンプリング
# したかを測ってしまう。
# The two testable units differ in what they treat as independent: the fiber
# unit counts the fibers of one image as independent, which the image unit
# does not, and the comparison note says so for the fiber unit
# (`_comparison_caveat`).
# 検定できる 2 単位は何を独立とみなすかが違う。fiber 単位は同じ画像のファイバーを
# 独立と数え、image 単位は数えない。fiber 単位では比較の注記がその旨を述べる
# （`_comparison_caveat`）。
TESTABLE_UNITS = (UNIT_FIBER, UNIT_IMAGE)

# How the standard deviation was computed, named in the results table heading
# and the summary CSV. An unweighted sample divides by n - 1, the sample
# standard deviation papers report; a weighted one divides by the total
# weight, because what n - 1 corrects for depends on what the weights mean.
# 標準偏差の計算法。結果テーブルの見出しと要約 CSV に示す。重みなしの標本は
# 論文で報告される標本標準偏差として n - 1 で割る。重み付きの標本は重みの合計で
# 割る。n - 1 が何を補正するかが重みの意味によって変わるためである。
STD_SAMPLE = "sample (n-1)"
STD_WEIGHTED = "weighted (population)"
STD_HEADINGS = {STD_SAMPLE: "SD (n-1)", STD_WEIGHTED: "weighted SD"}

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
# 各集計単位の標本量を表示するときに使う複数形の名詞。
UNIT_NOUNS = {
    UNIT_PIXEL: "px",
    UNIT_FIBER: "fibers",
    UNIT_IMAGE: "images",
}

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
# limits: fibril heights are a few nm and contour lengths hundreds of nm to a
# few µm.
# 計測量ごとの表示メタデータと既定ヒストグラム範囲。
# "units" の先頭要素が既定の集計単位。"value_unit" は Tk ラベルと CSV ヘッダ用の
# 素の単位表記、"value_unit_plot" は Matplotlib が描画する表記で、両者が一致する
# 場合は "value_unit" が既定値になる。範囲は典型的なナノセルロース試料向けの
# 初期値であって物理的な上限下限ではない（フィブリル高さは数 nm、輪郭長は
# 数百 nm〜数 µm）。
PARAM_SPECS = {
    PARAM_HEIGHT: {
        "slug": "height",
        "value_unit": "nm",
        "axis_label": "height (nm)",
        "units": (UNIT_PIXEL, UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 10.0, 0.2),
    },
    PARAM_LENGTH: {
        "slug": "contour_length",
        "value_unit": "nm",
        "axis_label": "contour length (nm)",
        "units": (UNIT_FIBER, UNIT_IMAGE),
        "default_range": (0.0, 3000.0, 100.0),
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
        # Per image only: one fiber's density takes the values 0, 1/L, 2/L...
        # of its judged length L, so a per-fiber distribution is shaped by the
        # fragment lengths rather than by the fibers. The rate a specimen has
        # is pooled kinks over pooled judged length, with the image as the
        # replicate (`_kink_totals`).
        # 画像単位のみ。1 本の密度は判定長 L に対して 0、1/L、2/L… の値しか
        # 取らないため、ファイバーごとの分布の形は繊維ではなく断片の長さで決まる。
        # 試料が持つ率は、まとめたキンク数をまとめた判定長で割ったもので、画像を
        # 反復の単位とする（`_kink_totals`）。
        "units": (UNIT_IMAGE,),
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
    PARAM_KINK_DENSITY,
)

# How contour length treats fibers that reach the image frame. A fiber cut by
# the frame is measured short, while its height, curvature and kinks are still
# valid measurements of the part inside, so this applies to length only.
# Excluding them removes the truncated lengths but, since a long fiber is more
# likely to reach the frame, under-represents long fibers; the
# Miles-Lantuejoul weight (`FiberStats.frame_weight`) corrects that. Fibers
# cut at a crossing are lower bounds too, which only the Kaplan-Meier estimate
# (`afm_nanofiber_analyzer.measure.kaplan_meier_length_weights`) takes into account: it uses every
# fiber with an end of its own, treating one cut at the other end as known to
# be at least as long as measured. Internal state keys shown verbatim, like the
# quantity and unit keys.
# 画像の枠に達したファイバーを輪郭長でどう扱うか。枠で切れたファイバーの長さは
# 短く測られるが、高さ・曲率・キンクは枠内の部分の測定として有効なままなので、
# これは長さにだけ適用する。除外すれば切り詰められた長さは消えるが、長いファイ
# バーほど枠に達しやすいため長いファイバーが過小になる。Miles-Lantuejoul 重み
# （`FiberStats.frame_weight`）がそれを補正する。交差で切れたファイバーの長さも
# 下限値であり、それを扱うのは Kaplan-Meier 推定
# （`afm_nanofiber_analyzer.measure.kaplan_meier_length_weights`）だけである。自身の端を持つ全ファイバー
# を使い、もう一方の端が切れたものは、計測した長さ以上であることが分かっている
# ものとして扱う。計測量・集計単位のキーと同じく、そのまま表示する内部状態キー。
FRAME_INCLUDE = "include"
FRAME_EXCLUDE = "exclude"
FRAME_MILES_LANTUEJOUL = "Miles-Lantuejoul"
FRAME_KAPLAN_MEIER = "Kaplan-Meier"

FRAME_MODES = (FRAME_INCLUDE, FRAME_EXCLUDE, FRAME_MILES_LANTUEJOUL,
               FRAME_KAPLAN_MEIER)
# The modes whose samples carry a weight in `FiberStats.frame_weight`.
# 標本が `FiberStats.frame_weight` に重みを持つ扱い。
WEIGHTED_FRAME_MODES = (FRAME_MILES_LANTUEJOUL, FRAME_KAPLAN_MEIER)

# Resamples behind the interval reported beside a Kaplan-Meier quartile
# (`_kaplan_meier_interval`), and the fixed seed that makes the interval the
# same on every run of the same data.
# Kaplan-Meier の四分位数の脇に出す区間（`_kaplan_meier_interval`）の
# リサンプリング回数と、同じデータでは毎回同じ区間になるようにする固定の種。
KM_RESAMPLES = 200
KM_RESAMPLE_SEED = 20261104
# The three quantiles a summary reports, with the result keys they go under.
# 要約が報告する 3 つの分位点と、それを入れる結果のキー。
QUARTILE_KEYS = ((0.25, "q1"), (0.5, "median"), (0.75, "q3"))
# The kink threshold of a bundle that records none: the detector default
# (`pipeline.ProcParams.kinkangle_deg`), which is what such a run used. Written
# out because importing `afm_nanofiber_analyzer.pipeline` loads the analysis stages.
# しきい値を記録していないバンドルのキンクしきい値。そのような実行が使った検出器の
# 既定値（`pipeline.ProcParams.kinkangle_deg`）である。`afm_nanofiber_analyzer.pipeline` を読み込むと
# 解析段まで読み込まれるため、値を書き出している。
UNRECORDED_KINK_ANGLE_DEG = 150.0


def _apply_frame_mode(per_source, frame_mode: str) -> tuple:
    """
    Drop the fibers that reach the frame, as the frame mode asks.
    枠の扱いの指定に従い、枠に達したファイバーを外す。

    Parameters
    ----------
    per_source
        ``(source_path, stats)`` pairs, one per bundle.
        ``(ソースパス, 統計値リスト)`` のペア。バンドル 1 件ごと。
    frame_mode
        One of `FRAME_MODES`.
        `FRAME_MODES` のいずれか。

    Returns
    -------
    tuple
        ``(kept, report)``. `kept` has the same shape as `per_source`, less
        the fibers that reach the frame and less every source that does not
        record the frame test; under `FRAME_INCLUDE` it is `per_source` itself.
        `report` is a dict with ``total`` and ``frame`` (fibers judged, and
        those that reach the frame), ``lower_bound`` (fibers judged not to
        reach it that have a cut end) and ``unrecorded`` (the sources without
        the test). `FRAME_INCLUDE` counts the same fibers and removes none, so
        the share of lengths the frame cut can be reported.
        ``(kept, report)``。`kept` は `per_source` と同じ形で、枠に達した
        ファイバーと、枠の判定を記録していないソースを除いたもの。
        `FRAME_INCLUDE` では `per_source` そのもの。`report` は ``total``・
        ``frame``（判定した本数と枠に達した本数）、``lower_bound``（枠に達して
        いないと判定され、切断端を持つ本数）、``unrecorded``（判定の無いソース）を
        持つ dict。`FRAME_INCLUDE` は同じ本数を数えるが何も外さない。枠で切れた
        長さの割合を報告できるようにするためである。

    Notes
    -----
    A source whose fibers carry no frame test (`FiberStats.touches_frame` is
    ``None``) is left out whole rather than kept unfiltered: mixing fibers
    that were judged with fibers that could not be would bias the
    distribution in a direction nobody can state. A fiber with a cut end is
    kept: its length is a lower bound too, but that is a property of the
    segmentation, which the frame correction does not model, and the report
    says how many there are.
    ファイバーが枠の判定を持たないソース（`FiberStats.touches_frame` が
    ``None``）は、絞り込まずに残すのではなく丸ごと外す。判定できたファイバーと
    できなかったファイバーを混ぜると、向きを誰も言えない偏りが分布に入るためである。
    切断端を持つファイバーは残す。その長さも下限値だが、それはセグメンテーションの
    性質であり枠の補正はそれを扱わない。本数は報告に出す。
    """
    if frame_mode == FRAME_KAPLAN_MEIER:
        return _apply_kaplan_meier(per_source)
    kept = []
    report = {"total": 0, "frame": 0, "lower_bound": 0, "unrecorded": []}
    for path, stats in per_source:
        if any(s.touches_frame is None for s in stats):
            report["unrecorded"].append(path)
            continue
        survivors = [s for s in stats if not s.touches_frame]
        report["total"] += len(stats)
        report["frame"] += len(stats) - len(survivors)
        report["lower_bound"] += sum(1 for s in survivors if s.cut_end_count)
        kept.append((path, survivors))
    return (per_source if frame_mode == FRAME_INCLUDE else kept), report


def _scan_size_spread_note(sizes_by_group: dict, frame_mode: str) -> str:
    """
    Word the warning that bundles compared without a frame correction differ in scan size.
    枠の補正なしで比べるバンドルの走査範囲が違うときの警告文を作る。

    Parameters
    ----------
    sizes_by_group
        Group name mapped to the ``(x_um, y_um)`` scan size of each of its
        bundles that records one.
        グループ名から、走査範囲を記録した各バンドルの ``(x_um, y_um)`` への対応。
    frame_mode
        `FRAME_INCLUDE` or `FRAME_EXCLUDE`, which selects how the shift is
        worded.
        `FRAME_INCLUDE` または `FRAME_EXCLUDE`。偏りの説明の文面を選ぶ。

    Returns
    -------
    str
        The warning, or an empty string when every recorded size agrees within
        one percent on both axes.
        警告文。記録されたすべての走査範囲が両軸で 1 % 以内に一致すれば空文字列。

    Notes
    -----
    Keeping the fibers the frame cut measures them short, and leaving them out
    favours short fibers. Either way the amount is set by how long the fibers
    are against the scan, so a difference between scan sizes enters the length
    distributions. The spread is taken over every bundle of the run, so the
    warning says that such bundles were compared, and the sizes are listed per
    group so the reader can see how they are distributed. The comparison is
    still made; the user is told.
    枠で切れたファイバーを残せば短く測られ、外せば短いファイバーが有利になる。
    どちらでも大きさは走査範囲に対する繊維の長さで決まるため、走査範囲の違いが長さの
    分布に入り込む。ばらつきは実行内の全バンドルで取るので、警告が示すのはそうした
    バンドルを比べたことである。
    走査範囲はグループごとに挙げ、どう分かれているかを読み手が見られるようにする。
    比較はそのまま行い、ユーザーに知らせる。
    """
    sizes = [size for group in sizes_by_group.values() for size in group]
    if len(sizes) < 2:
        return ""
    # A spread under one percent, such as the rounding of a scan size written
    # in an instrument header, does not raise the warning.
    # 装置ヘッダに書かれた走査範囲の丸めのような 1 % 未満の違いでは警告しない。
    if all(max(axis) <= min(axis) * 1.01 for axis in zip(*sizes)):
        return ""
    groups = "; ".join(
        "{name}: {sizes}".format(
            name=name,
            sizes=", ".join(
                "{0:.3g}×{1:.3g}".format(*size) for size in sorted(set(group))
            ),
        )
        for name, group in sizes_by_group.items() if group
    )
    if frame_mode == FRAME_INCLUDE:
        return _(
            "注意: {mode} で比較したバンドルの走査範囲 ({um}) が異なります（{groups}）。"
            "枠で切れたファイバーは短く測られ、分布は短い側に偏ります。その大きさは走査範囲に"
            "対する繊維の長さで変わります。そのため走査範囲の違うバンドルの間の長さの差には、"
            "撮像条件の違いも含まれます。{ml} を使うと、この偏りは小さくなります。"
        ).format(mode=frame_mode, um=UNIT_MICROMETER, groups=groups,
                 ml=FRAME_MILES_LANTUEJOUL)
    return _(
        "注意: {exclude} で比較したバンドルの走査範囲 ({um}) が異なります（{groups}）。"
        "枠に達したファイバーを外すと分布は短い側に偏り、その大きさは走査範囲に対する"
        "繊維の長さで変わります。そのため走査範囲の違うバンドルの間の長さの差には、"
        "撮像条件の違いも含まれます。{ml} を使うと、この偏りは小さくなります。"
    ).format(exclude=frame_mode, um=UNIT_MICROMETER, groups=groups,
             ml=FRAME_MILES_LANTUEJOUL)


def _kink_condition_report(conditions_by_group: dict) -> list:
    """
    Say how the bundles compared for kinks differ in what the count depends on.
    キンクを比べるバンドルが、キンク数の依存する条件でどう違うかを述べる。

    Parameters
    ----------
    conditions_by_group
        Group name mapped to the `App._bundle_kink_conditions` entry of each of
        its bundles.
        グループ名から、各バンドルの `App._bundle_kink_conditions` の項目への対応。

    Returns
    -------
    list of str
        The warnings to log; empty when nothing differs.
        ログに出す警告の列。何も違わなければ空。

    Notes
    -----
    A different threshold is a different definition of a kink; a different
    pixel size or format, or noise above the limit `pipeline.noise_warnings`
    applies, changes how the same definition reads a scan. Each is reported and
    the test still runs; what the difference means for the comparison is the
    user's to judge. A difference in noise below that limit, or in apparent
    width, has no measured limit to warn at, so those values are shown instead.
    しきい値が違えばキンクの定義が違い、サンプリング間隔（nm/px）や形式の違い、
    `pipeline.noise_warnings` の限度を超えるノイズは、同じ定義が画像をどう読むかを
    変える。どれも報告し、検定は実行する。その違いが比較にとって何を意味するかは
    ユーザーが判断する。その限度より小さいノイズの差や見かけの幅の差には、警告する
    限度の測定値が無いため、値を示すにとどめる。
    """
    conditions = [c for group in conditions_by_group.values() for c in group]
    warnings = []
    thresholds = sorted({c["threshold"] for c in conditions})
    if len(thresholds) > 1:
        warnings.append(_(
            "注意: 比較したバンドルのキンクのしきい値が {values} 度と異なります。キンクの"
            "定義が違うため、群の差にはしきい値の違いも含まれます。そろえるには、Image "
            "Preprocessor で同じしきい値（{param}）で解析し直してください。"
        ).format(values=", ".join(f"{v:g}" for v in thresholds),
                 param="kinkangle_deg"))
    sizes = [c["pixel_nm"] for c in conditions if c["pixel_nm"] is not None]
    # A spread under one percent, such as the rounding of a scan size written
    # in an instrument header, does not raise the warning.
    # 装置ヘッダに書かれた走査範囲の丸めのような 1 % 未満の違いでは警告しない。
    if sizes and max(sizes) > min(sizes) * 1.01:
        warnings.append(_(
            "注意: 比較したバンドルのサンプリング間隔（nm/px）が {low}〜{high} nm/px と異なります。"
            "キンクの検出は見かけの幅・サンプリング間隔（nm/px）・ノイズで変わるため"
            "（docs/validation.md §4.4、§4.8）、群の差には撮像条件の違いも含まれます。"
        ).format(low=f"{min(sizes):.2f}", high=f"{max(sizes):.2f}"))
    versions = sorted({c["version"] for c in conditions if c["version"]})
    if len(versions) > 1:
        warnings.append(_(
            "注意: 比較したバンドルの形式が {versions} と混在しています。形式によって"
            "見かけの幅やキンクの探し方の定義が違うため、同じ版で解析し直すことを"
            "勧めます。"
        ).format(versions=", ".join(versions)))
    # Local import: see `App._bundle_height_and_noise`.
    # 局所インポート。`App._bundle_height_and_noise` を参照。
    from afm_nanofiber_analyzer.pipeline import MIN_FIBER_SNR

    ratios = [c["height_nm"] / c["noise_nm"] for c in conditions
              if c.get("height_nm") is not None and c.get("noise_nm")]
    low = [ratio for ratio in ratios if ratio < MIN_FIBER_SNR]
    if low:
        warnings.append(_(
            "注意: 比較したバンドルのうち {n}/{total} 個は、繊維の高さが画素ノイズの "
            "{limit:g} 倍未満です（最小 {ratio:.1f} 倍）。ノイズが大きいと太い繊維の幅が"
            "短く読まれ、キンクを判定する尺度が変わります（docs/validation.md §4.16、"
            "§4.17）。"
        ).format(n=len(low), total=len(ratios), limit=MIN_FIBER_SNR,
                 ratio=min(low)))
    return warnings


def _centerline_note(lines) -> str:
    """
    Word the warning that the compared bundles were analyzed on different centerlines.
    比べるバンドルが異なる中心線で解析されたときの警告文を作る。

    Parameters
    ----------
    lines
        Centerline names found among the compared bundles.
        比べるバンドルにあった中心線の名前。

    Returns
    -------
    str
        The warning, or an empty string when there is one line or none.
        警告文。線が 1 種類以下なら空文字列。

    Notes
    -----
    Every length, height, curvature and kink is measured along the centerline,
    so a difference between groups on different lines may be the lines alone,
    and a p-value cannot tell that from a difference between the specimens.
    The test still runs; the user is told.
    長さ・高さ・曲率・キンクはすべて中心線に沿って測るため、線の違う群の差は線の違い
    だけによるかもしれず、p 値はそれを試料の差と区別できない。検定は実行し、
    ユーザーに知らせる。
    """
    names = sorted(lines)
    if len(names) < 2:
        return ""
    return _(
        "注意: 比較したバンドルの中心線が {lines} と異なります。長さ・高さ・曲率・"
        "キンクはすべて中心線に沿って測るため、群の差には中心線の違いも含まれます。"
        "同じ中心線で解析し直すと、この違いは無くなります。"
    ).format(lines=", ".join(names))


def _median_width_nm(conditions: list):
    """
    Return the median apparent width of some bundles, in nanometers.
    いくつかのバンドルの見かけの幅の中央値 (nm) を返す。

    Parameters
    ----------
    conditions
        `App._bundle_kink_conditions` entries.
        `App._bundle_kink_conditions` の項目。

    Returns
    -------
    float or None
        Median over the bundles that record a width and a pixel size, or
        ``None`` when none does.
        幅とサンプリング間隔（nm/px）を記録したバンドルにわたる中央値。無ければ ``None``。

    Notes
    -----
    The kink rule measures every length in apparent widths, so this is the scale
    a group's kinks were judged at, and it includes probe broadening.
    キンクの規則はすべての長さを見かけの幅で測るため、これがそのグループのキンクを
    判定した尺度であり、探針による広がりを含む。
    """
    widths = [c["width_px"] * c["pixel_nm"] for c in conditions
              if c["width_px"] is not None and c["pixel_nm"] is not None]
    return float(np.median(widths)) if widths else None


def _apply_kaplan_meier(per_source) -> tuple:
    """
    Weight the fibers seen whole by the Kaplan-Meier length distribution.
    全長を見たファイバーを、Kaplan-Meier の長さ分布で重み付けする。

    Parameters
    ----------
    per_source
        ``(source_path, stats)`` pairs, one per bundle, all estimated
        together.
        ``(ソースパス, 統計値リスト)`` のペア。バンドル 1 件ごとで、すべて
        まとめて推定する。

    Returns
    -------
    tuple
        ``(kept, report)``. `kept` holds, per source, the fibers with both
        ends their own, each with its weight in `frame_weight`; a fiber cut at
        one end enters the estimate as censored and carries no weight itself.
        `report` has ``kaplan_meier`` (True), ``total``, ``complete``,
        ``censored``, ``no_own_end``, ``unassigned`` (the share of fibers the
        estimate places beyond the longest one seen whole), ``beyond`` (that
        many fibers), ``longest_nm``, ``unrecorded``, and ``lengths_nm`` and
        ``own_ends``, the length and own-end count of every fiber the estimate
        read, which `_kaplan_meier_interval` resamples.
        ``(kept, report)``。`kept` はソースごとに、両端とも自身の端である
        ファイバーを、重みを `frame_weight` に入れて持つ。片端が切れたファイバーは
        打ち切りとして推定に入り、自身は重みを持たない。`report` は
        ``kaplan_meier``（True）・``total``・``complete``・``censored``・
        ``no_own_end``・``unassigned``（全長を見たうち最長のものより長い側に推定が
        置く本数の割合）・``beyond``（その本数）・``longest_nm``・``unrecorded``、
        および推定が読んだ全ファイバーの長さと自身の端の数である ``lengths_nm`` と
        ``own_ends`` を持つ。後の 2 つは `_kaplan_meier_interval` がリサンプリング
        する。

    Notes
    -----
    A source with a fiber whose own ends cannot be counted
    (`fiber_real_end_count` returns ``None``) is left out whole, for the reason
    `_apply_frame_mode` gives.
    自身の端の数を数えられないファイバー（`fiber_real_end_count` が ``None`` を
    返す）を含むソースは、`_apply_frame_mode` に書いた理由により丸ごと外す。
    """
    import dataclasses

    report = {"kaplan_meier": True, "total": 0, "complete": 0, "censored": 0,
              "no_own_end": 0, "unassigned": 0.0, "beyond": 0.0,
              "longest_nm": float("nan"), "unrecorded": []}
    recorded = []
    for path, stats in per_source:
        own = [fiber_real_end_count(s) for s in stats]
        if any(o is None for o in own):
            report["unrecorded"].append(path)
            continue
        recorded.append((path, stats, own))
    lengths = [s.length_nm for _p, stats, _o in recorded for s in stats]
    own = [o for _p, _s, owns in recorded for o in owns]
    weights, rest = kaplan_meier_length_weights(lengths, own)
    kept = []
    at = 0
    for path, stats, owns in recorded:
        survivors = []
        for s, o in zip(stats, owns):
            if o == 2 and weights[at] > 0.0:
                survivors.append(dataclasses.replace(s, frame_weight=float(weights[at])))
            at += 1
        kept.append((path, survivors))
    report["total"] = len(own)
    report["complete"] = sum(1 for o in own if o == 2)
    report["censored"] = sum(1 for o in own if o == 1)
    report["no_own_end"] = sum(1 for o in own if o == 0)
    report["unassigned"] = rest if sum(own) else 0.0
    report["beyond"] = rest * sum(own) / 2.0
    whole = [ln for ln, o in zip(lengths, own) if o == 2]
    if whole:
        report["longest_nm"] = float(max(whole))
    report["lengths_nm"] = np.asarray(lengths, dtype=float)
    report["own_ends"] = np.asarray(own, dtype=int)
    return kept, report


def _fiber_value(stat, param: str):
    """
    Return the per-fiber value of one measured quantity, or None if undefined.
    1 本のファイバーにおける計測量の値を返す。定義できない場合は None。

    Parameters
    ----------
    stat
        Per-fiber statistics row from `afm_nanofiber_analyzer.measure.compute_fiber_stats`.
        `afm_nanofiber_analyzer.measure.compute_fiber_stats` が返すファイバー単位の統計行。
    param
        Measured-quantity key from `PARAM_SPECS`.
        `PARAM_SPECS` の計測量キー。

    Returns
    -------
    float or None
        Fiber-level value, or None when the fiber carries no such value. Kink
        density has no fiber-level value here, because it is compared per image
        only (`_kink_totals`).
        ファイバー単位の値。その値を持たないファイバーでは None。キンク密度は画像
        単位でだけ比べるため（`_kink_totals`）、ここではファイバー単位の値を持たない。

    Notes
    -----
    A fiber represents its height by the median of the values sampled along
    it, so one fiber contributes exactly one sample regardless of how long it
    is.
    ファイバーの高さは、そのファイバー上でサンプリングした値の中央値で代表させる。
    これにより、長さにかかわらず 1 本が 1 標本になる。
    """
    if param == PARAM_HEIGHT:
        # NaN when every sample of the fiber read a crossing
        # (`height_sample_mask`); such a fiber has no height of its own.
        # 繊維の全標本が交差を読んだとき NaN になる（`height_sample_mask`）。
        # そのような繊維には自身の高さが無い。
        value = float(stat.height_median_nm)
        return None if not np.isfinite(value) else value
    if param == PARAM_LENGTH:
        return float(stat.length_nm)
    if param == PARAM_STRAIGHTNESS:
        # A fiber whose straightness is undefined (NaN) contributes nothing
        # rather than a zero.
        # straightness が未定義（NaN）のファイバーは、0 ではなく「寄与なし」として
        # 扱う。
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
        Per-fiber statistics row from `afm_nanofiber_analyzer.measure.compute_fiber_stats`.
        `afm_nanofiber_analyzer.measure.compute_fiber_stats` が返すファイバー単位の統計行。
    param
        Measured-quantity key from `PARAM_SPECS`.
        `PARAM_SPECS` の計測量キー。
    unit
        Aggregation-unit key; every unit takes the fiber's one value.
        集計単位キー。どの単位でもファイバーの 1 つの値を使う。

    Returns
    -------
    list of float
        No sample or one.
        標本 0 個または 1 個。
    """
    value = _fiber_value(stat, param)
    return [] if value is None else [value]


def _kaplan_meier_bounds(values: np.ndarray, weights: np.ndarray,
                         estimates) -> dict:
    """
    Return the bounds of each quartile of a Kaplan-Meier length estimate.
    Kaplan-Meier の長さ推定について、各四分位数の範囲を返す。

    Parameters
    ----------
    values
        Lengths of the fibers seen whole, over every estimate pooled.
        まとめる全推定の、全長を見たファイバーの長さ。
    weights
        Their Kaplan-Meier weights, in fibers.
        それらの Kaplan-Meier 重み（本数）。
    estimates
        ``(longest_nm, beyond)`` per estimate pooled: the longest fiber that
        estimate saw whole (NaN when it saw none) and the fibers it places
        beyond it. A run makes one estimate per group, so it passes one entry.
        まとめる推定ごとの ``(longest_nm, beyond)``。その推定が全長を見た最長の
        ファイバー（1 本も無ければ NaN）と、それより長い側に置く本数。実行では
        グループごとに 1 回推定するため、項目は 1 つになる。

    Returns
    -------
    dict
        ``{key: (lower, upper)}`` for each key of `QUARTILE_KEYS`; ``upper`` is
        infinite when the quantile can lie anywhere beyond ``lower``.
        `QUARTILE_KEYS` の各キーについて ``{key: (lower, upper)}``。分位点が
        ``lower`` より先のどこにでもありうるときは ``upper`` が無限大。

    Notes
    -----
    An estimate stops at the longest fiber it saw whole, and the fibers it
    places beyond lie somewhere above that length. Placing every estimate's
    share at infinity gives the largest each quantile can be, and placing it
    just above that estimate's own longest fiber the smallest; an estimate
    that saw no fiber whole gives no such length and is placed just above
    zero. With one estimate the two agree wherever it reaches the quantile,
    and otherwise the quantile is known only to exceed the longest fiber seen
    whole.
    推定は、全長を見た最長のファイバーで止まり、それより長い側に置くファイバーは、
    その長さより先のどこかにある。全推定の分を無限遠に置くと各分位点は最も大きく、
    各推定自身の最長のファイバーのすぐ先に置くと最も小さくなる。1 本も全長を
    見なかった推定にはその長さが無く、0 のすぐ先に置く。推定が 1 つなら、推定が
    分位点に届く範囲で両者は一致し、届かなければ分位点は全長を見た最長の
    ファイバーより長いことしか分からない。
    """
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    shares = sorted((float(longest) if np.isfinite(longest) else 0.0, float(beyond))
                    for longest, beyond in estimates if beyond > 0.0)
    assigned = float(weights.sum())
    total = assigned + sum(b for _l, b in shares)
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    upper_positions = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total

    # The lower bound: each estimate's share sits just above its own longest
    # fiber, so every length above that moves up by the share.
    # 下限。各推定の分を自身の最長のファイバーのすぐ先に置くため、それより
    # 長い各長さは、その分だけ上へずれる。
    positions = []
    lengths = []
    for value, position in zip(sorted_values, upper_positions):
        below = sum(b for longest, b in shares if longest < value)
        positions.append(position + below / total)
        lengths.append(value)
    placed = 0.0
    for longest, beyond in shares:
        start = float(sorted_weights[sorted_values <= longest].sum()) + placed
        positions.extend([start / total, (start + beyond) / total])
        lengths.extend([longest, longest])
        placed += beyond
    knots = np.lexsort((lengths, positions))
    positions = np.asarray(positions, dtype=float)[knots]
    lengths = np.maximum.accumulate(np.asarray(lengths, dtype=float)[knots])

    bounds = {}
    for q, key in QUARTILE_KEYS:
        if sorted_values.size == 0:
            bounds[key] = (0.0, float("inf"))
            continue
        upper = (float(np.interp(q, upper_positions, sorted_values))
                 if q <= assigned / total else float("inf"))
        lower = float(np.interp(q, positions, lengths))
        bounds[key] = (min(lower, upper), upper)
    return bounds


def _kaplan_meier_summary(values: np.ndarray, weights: np.ndarray,
                          estimates) -> dict:
    """
    Return the statistics a Kaplan-Meier length estimate can give.
    Kaplan-Meier による長さの推定が与えられる統計値を返す。

    Parameters
    ----------
    values
        Lengths of the fibers seen whole.
        全長を見たファイバーの長さ。
    weights
        Their Kaplan-Meier weights, in fibers.
        それらの Kaplan-Meier 重み（本数）。
    estimates
        ``(longest_nm, beyond)`` per estimate, as in `_kaplan_meier_bounds`.
        推定ごとの ``(longest_nm, beyond)``。`_kaplan_meier_bounds` と同じ。

    Returns
    -------
    dict
        The keys of `_summary_stats` and ``bounds``. With nothing beyond, the
        weighted statistics of `_summary_stats` and no bounds; otherwise a
        quartile is reported only where its bounds (`_kaplan_meier_bounds`,
        kept under ``bounds``) agree and is NaN elsewhere, and the mean and the
        standard deviation are NaN, because they depend on the part of the
        distribution that was not estimated.
        `_summary_stats` のキーと ``bounds``。推定できない部分が無ければ
        `_summary_stats` の重み付き統計値で、範囲は持たない。あれば、四分位数は
        その範囲（`_kaplan_meier_bounds`。``bounds`` に入れる）の上下が一致する
        場合だけ報告し、それ以外は NaN とする。平均・標準偏差も NaN とする。
        推定していない部分の分布に依存するためである。

    Notes
    -----
    The quartiles are taken against every fiber the estimate stands for, the
    part beyond included, so a median is reported only where the estimate
    reaches half the fibers; statistics packages report such a median as
    missing in the same way.
    四分位数は、推定できない部分を含め、推定が表す全ファイバーに対して取る。
    そのため中央値は、推定が半数のファイバーに届く場合にだけ報告する。統計
    パッケージもそのような中央値を同じように欠測として返す。
    """
    if sum(b for _l, b in estimates) <= 0.0:
        return dict(_summary_stats(values, weights), bounds={})
    bounds = _kaplan_meier_bounds(values, weights, estimates)
    stats = {"mean": float("nan"), "std": float("nan"),
             "std_definition": STD_WEIGHTED, "bounds": bounds}
    for _q, key in QUARTILE_KEYS:
        lower, upper = bounds[key]
        stats[key] = (upper if np.isfinite(upper)
                      and upper - lower <= 1e-9 * max(1.0, abs(upper))
                      else float("nan"))
    return stats


def _kaplan_meier_interval(samples, resamples: int = KM_RESAMPLES,
                           seed: int = KM_RESAMPLE_SEED) -> dict:
    """
    Return a resampling interval for each quartile of a Kaplan-Meier length estimate.
    Kaplan-Meier の長さ推定の各四分位数について、リサンプリング区間を返す。

    Parameters
    ----------
    samples
        ``(lengths_nm, own_ends)`` arrays per estimate pooled: every fiber
        the estimate read (`_apply_kaplan_meier`'s report). A run makes one
        estimate per group, so it passes one entry.
        まとめる推定ごとの ``(lengths_nm, own_ends)`` 配列。その推定が読んだ
        全ファイバー（`_apply_kaplan_meier` の report）。実行ではグループごとに
        1 回推定するため、項目は 1 つになる。
    resamples
        Number of resamples.
        リサンプリング回数。
    seed
        Seed of the random resampling, so the same data give the same interval.
        ランダムなリサンプリングの種。同じデータには同じ区間を与える。

    Returns
    -------
    dict
        ``{key: (lower, upper)}`` for each key of `QUARTILE_KEYS`: the 2.5th
        percentile of the quartile's lower bound and the 97.5th percentile of
        its upper bound over the resamples, ``upper`` infinite when more than
        2.5 % of the resamples leave the quartile without an upper bound.
        Empty when no estimate has a fiber.
        `QUARTILE_KEYS` の各キーについて ``{key: (lower, upper)}``。リサンプリング
        にわたる、四分位数の下限の 2.5 パーセンタイルと上限の 97.5 パーセンタイル。
        2.5 % を超えるリサンプルで上限が定まらなければ ``upper`` は無限大。
        どの推定にもファイバーが無ければ空。

    Notes
    -----
    The bounds of `_kaplan_meier_bounds` cover only where an estimate's
    unplaced share might lie; the fibers measured are themselves a sample. The
    fibers of each estimate are drawn again with replacement, the estimate and
    its bounds are recomputed, and the interval spans the bounds' spread. Each
    estimate is resampled on its own, so it keeps its own fibers and its own
    longest fiber seen whole.
    `_kaplan_meier_bounds` の範囲が扱うのは、推定の置けなかった分がどこに
    ありうるかだけであり、計測したファイバー自体も標本である。各推定の
    ファイバーを復元抽出し直して推定とその範囲を計算し直し、区間はその範囲の
    ばらつきにわたる。推定ごとに別々にリサンプリングするため、各推定は自身の
    ファイバーと、全長を見た自身の最長のファイバーを保つ。
    """
    samples = [(np.asarray(lengths, dtype=float), np.asarray(own, dtype=int))
               for lengths, own in samples if len(lengths)]
    if not samples:
        return {}
    rng = np.random.default_rng(seed)
    lowers = {key: [] for _q, key in QUARTILE_KEYS}
    uppers = {key: [] for _q, key in QUARTILE_KEYS}
    for _resample in range(resamples):
        values, weights, estimates = [], [], []
        for lengths, own in samples:
            pick = rng.integers(0, lengths.size, lengths.size)
            drawn, drawn_own = lengths[pick], own[pick]
            fiber_weights, rest = kaplan_meier_length_weights(drawn, drawn_own)
            keep = (drawn_own == 2) & (fiber_weights > 0.0)
            values.append(drawn[keep])
            weights.append(fiber_weights[keep])
            whole = drawn[drawn_own == 2]
            estimates.append((float(whole.max()) if whole.size else float("nan"),
                              rest * float(drawn_own.sum()) / 2.0))
        values = np.concatenate(values)
        weights = np.concatenate(weights)
        bounds = (_kaplan_meier_bounds(values, weights, estimates) if values.size
                  else {key: (0.0, float("inf")) for _q, key in QUARTILE_KEYS})
        for _q, key in QUARTILE_KEYS:
            lowers[key].append(bounds[key][0])
            uppers[key].append(bounds[key][1])
    return {key: (float(np.percentile(lowers[key], 2.5)),
                  float(np.percentile(uppers[key], 97.5, method="higher")))
            for _q, key in QUARTILE_KEYS}


def _range_csv_values(ranges: dict) -> list:
    """
    Return the CSV cells of the quartile ranges: lower and upper per key of `QUARTILE_KEYS`.
    四分位数の範囲の CSV セルを返す。`QUARTILE_KEYS` のキーごとに下限と上限。

    A key without a range gives two blank cells, and an upper end that is not
    bounded reads ``inf``.
    範囲の無いキーは空欄 2 つになり、定まらない上限は ``inf`` と書く。
    """
    cells = []
    for _q, key in QUARTILE_KEYS:
        if key not in ranges:
            cells.extend(["", ""])
            continue
        lower, upper = ranges[key]
        cells.append("{0:.3f}".format(lower))
        cells.append("{0:.3f}".format(upper) if np.isfinite(upper) else "inf")
    return cells


def _range_text(bounds, fmt: str) -> str:
    """
    Format a ``(lower, upper)`` range, open-ended when ``upper`` is infinite.
    ``(lower, upper)`` の範囲を書式化する。``upper`` が無限大なら上を開く。
    """
    lower, upper = bounds
    if not np.isfinite(upper):
        return "> " + fmt.format(lower)
    return "[" + fmt.format(lower) + ", " + fmt.format(upper) + "]"


def _quantile_text(r: dict, key: str, fmt: str) -> str:
    """
    Format a quartile of a result, or the range a Kaplan-Meier estimate leaves it in.
    結果の四分位数を書式化する。Kaplan-Meier 推定で値が定まらなければ、その範囲を書く。

    A quartile the estimate leaves undetermined reads ``[lower, upper]``, or
    ``> lower`` when it can lie anywhere beyond `lower`
    (`_kaplan_meier_bounds`).
    推定で値が定まらない四分位数は ``[lower, upper]``、`lower` より先のどこにでも
    ありうるときは ``> lower`` と書く（`_kaplan_meier_bounds`）。
    """
    value = r[key]
    if np.isfinite(value):
        return fmt.format(value)
    bounds = r.get("quantile_bounds", {}).get(key)
    if bounds is not None:
        return _range_text(bounds, fmt)
    return "-"


def _histogram_edges(min_h: float, max_h: float, step: float) -> np.ndarray:
    """
    Return equal bins of width `step` from `min_h` that reach `max_h`.
    `min_h` から幅 `step` の等幅ビンを `max_h` まで並べて返す。

    Notes
    -----
    An arange to `max_h` stops one step short of it, which would leave the
    last bin of the entered range out of the figure and count its samples as
    outside it. When the range is not a whole number of steps, the last bin
    ends past `max_h` instead of short of it.
    `max_h` までの arange は 1 step 手前で止まるため、入力範囲の最後のビンが図から
    欠け、その標本が範囲外と数えられてしまう。範囲が step で割り切れないときは、
    最後のビンを `max_h` の手前ではなく先で終える。
    """
    n_bins = int(np.ceil((max_h - min_h) / step - 1e-9))
    edges = min_h + step * np.arange(n_bins + 1)
    if np.isclose(edges[-1], max_h, rtol=0.0,
                  atol=1e-9 * max(abs(max_h), step)):
        edges[-1] = max_h
    return edges


def _bin_results(results: list, edges: np.ndarray, counted_by_fiber: bool) -> list:
    """
    Count each group's samples into `edges` and note the share outside them.
    各グループの標本を `edges` のビンに数え、範囲外の割合を注記する。

    Parameters
    ----------
    results
        Per-group results holding ``values``, ``weights``, ``weight_total``
        and ``km_beyond``; ``counts``, ``total``, ``n_in_range``, ``mode`` and
        ``norm_total`` are written into each.
        ``values``・``weights``・``weight_total``・``km_beyond`` を持つグループ
        ごとの結果。各結果に ``counts``・``total``・``n_in_range``・``mode``・
        ``norm_total`` を書き込む。
    edges
        Bin edges (`_histogram_edges`).
        ビンの境界（`_histogram_edges`）。
    counted_by_fiber
        Whether the weights do not stand for sample counts (the frame
        weights), so the samples in range are counted apart from the bar
        totals.
        重みが標本の量を表さないか（枠の重み）。そのとき範囲内の標本数を棒の
        合計とは別に数える。

    Returns
    -------
    list of str
        One notice per group with samples outside the bins.
        ビンの外に標本があるグループごとの通知。

    Notes
    -----
    Only the bins depend on the histogram range and step; the samples and the
    summary statistics do not, so a new range re-bins the samples already
    collected instead of measuring the bundles again.
    ヒストグラムの範囲と step に依存するのはビンだけで、標本と要約統計量は依存
    しない。そのため範囲を変えたときは、バンドルを計測し直さず、集めた標本を
    ビンに数え直す。
    """
    notes = []
    for r in results:
        # Weights enter the histogram here as bin weights, so the bars
        # agree with the weighted statistics.
        # 重みはビンの重みとしてここでヒストグラムに入る。棒は重み付き統計と一致する。
        counts, _edges = np.histogram(
            r["values"], bins=edges, weights=r["weights"], density=False,
        )
        total = float(counts.sum())
        r["counts"] = counts
        r["total"] = total
        # How many samples the drawn range holds. Under the
        # Miles-Lantuejoul weight the bars sum weights, so the count is
        # taken separately to stay comparable with the reported fibers.
        # 描画範囲に入る標本の量。Miles-Lantuejoul 重みでは棒が重みを合計
        # するため、報告する本数と比べられるよう件数を別に数える。
        r["n_in_range"] = (
            float(np.histogram(r["values"], bins=edges)[0].sum())
            if counted_by_fiber else total
        )
        if total > 0:
            k = int(np.argmax(counts))
            r["mode"] = float((edges[k] + edges[k + 1]) / 2.0)
        else:
            r["mode"] = float("nan")
        # Under Kaplan-Meier the bars are fractions of every fiber the
        # estimate stands for, so they sum to less than one by the part it
        # could not place, and the tallest bar is not the mode of a
        # distribution whose tail is unknown.
        # Kaplan-Meier では棒を、推定が表す全ファイバーに対する割合とする。
        # そのため棒の合計は、置けなかった部分だけ 1 に届かない。また裾の
        # 分からない分布では、最も高い棒は最頻値ではない。
        r["norm_total"] = total
        if r.get("km_beyond", 0.0) > 0.0:
            r["norm_total"] = r["weight_total"] + r["km_beyond"]
            r["mode"] = float("nan")

        # Summary statistics describe the whole sample, while the bars show
        # only the selected range. Silently dropping out-of-range samples
        # from the figure would misrepresent the distribution, so report the
        # excluded share rather than leaving the difference invisible. A
        # share of the total weight rather than a count, because under a
        # weight the bars sum weights, not samples.
        # 要約統計量は全標本を、棒グラフは選択範囲のみを表す。範囲外の標本を
        # 黙って図から落とすと分布を誤って伝えるため、除外された割合を示す。
        # 件数ではなく重みの合計に対する割合にするのは、重みがあると棒が標本の
        # 数ではなく重みを合計するため。
        outside = r["weight_total"] - total
        # Fractional weights sum in a different order in the bins than in
        # the total, so a relative tolerance keeps rounding from reporting
        # "0.0% outside".
        # 小数の重みはビンと合計で加算順が異なるため、相対許容誤差を設け、
        # 丸め誤差で「0.0% が範囲外」と報告しないようにする。
        if outside > 1e-9 * r["weight_total"] and r["weight_total"] > 0:
            notes.append(
                _("[{grp}] 標本の {pct}% がヒストグラム範囲外です"
                  "（統計値は範囲外を含む全標本から計算しています）").format(
                    grp=r["name"],
                    pct="{0:.1f}".format(100.0 * outside / r["weight_total"]),
                )
            )
    return notes


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
        Miles-Lantuejoul frame correction of contour lengths, where it is the
        dimensionless `FiberStats.frame_weight`.
        値ごとの重み。重みなしの標本では None。輪郭長の Miles-Lantuejoul 枠補正で
        使い、その場合は無次元の `FiberStats.frame_weight`。

    Returns
    -------
    dict
        Keys ``mean``, ``std``, ``q1``, ``median``, ``q3``, and
        ``std_definition`` (`STD_SAMPLE` or `STD_WEIGHTED`). ``std`` is NaN
        for an unweighted sample of one value.
        キーは ``mean``, ``std``, ``q1``, ``median``, ``q3`` と
        ``std_definition``（`STD_SAMPLE` または `STD_WEIGHTED`）。重みなしで
        値が 1 個の標本では ``std`` は NaN。

    Notes
    -----
    The unweighted branch calls NumPy directly rather than passing weights of
    one to the weighted branch. The two quantile definitions do not agree
    exactly, so routing every sample through the weighted path would silently
    move the numbers of the existing unweighted modes.
    重みなしの分岐では、1 の重みを weighted 側へ渡すのではなく NumPy を直接
    呼ぶ。両者の分位数の定義は厳密には一致しないため、すべてを weighted 経路に
    通すと既存の重みなしモードの数値が黙って変わってしまう。

    The unweighted standard deviation divides by n - 1, the sample standard
    deviation; dividing by n reads low by a factor of sqrt((n - 1) / n),
    which matters most for the image unit, where a group holds only a few
    samples. One value has no spread to estimate, so it is NaN rather than 0.
    重みなしの標準偏差は n - 1 で割る標本標準偏差である。n で割ると
    sqrt((n - 1) / n) 倍だけ小さく出る。これは群が少数の標本しか持たない画像単位で
    最も効く。値が 1 個ではばらつきを推定できないため、0 ではなく NaN とする。
    """
    if weights is None:
        q1, median, q3 = (
            float(v) for v in np.percentile(values, [25.0, 50.0, 75.0])
        )
        return {
            "mean": float(np.mean(values)),
            "std": (float(np.std(values, ddof=1)) if np.size(values) > 1
                    else float("nan")),
            "q1": q1, "median": median, "q3": q3,
            "std_definition": STD_SAMPLE,
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
        "std_definition": STD_WEIGHTED,
    }


def _kink_totals(stats) -> tuple:
    """
    Return the kink count and judged length pooled over a set of fibers.
    ファイバーの集合についてまとめたキンク数と判定長を返す。

    Parameters
    ----------
    stats
        Per-fiber statistics rows.
        ファイバー単位の統計行。

    Returns
    -------
    tuple
        ``(kinks, judged_um, n_fibers)``: the kinks on the fibers that had a
        judged length, the sum of those lengths in micrometers
        (`afm_nanofiber_analyzer.measure.fiber_judged_length_um`), and how many fibers they are.
        ``(キンク数, 判定長 µm, ファイバー数)``。判定長を持つファイバー上の
        キンク数、その長さの合計（`afm_nanofiber_analyzer.measure.fiber_judged_length_um`）、
        その本数。

    Notes
    -----
    The image unit divides the pooled count by the pooled length instead of
    taking the median of per-fiber densities. When more than half
    of an image's fibers carry no kink, the median of their densities is 0
    whatever the kinked fibers do, so a per-image median would compare zeros
    with zeros; a short fragment's density also swings with one kink more or
    less. The pooled ratio is kinks per micrometer of judged contour over the
    whole image, which every fiber enters in proportion to the length it was
    judged over.
    画像単位では、ファイバーごとの密度の中央値ではなく、まとめた
    キンク数をまとめた長さで割る。画像のファイバーの半数以上がキンクを持たない
    とき、その密度の中央値はキンクを持つファイバーがどうであれ 0 になるため、
    画像ごとの中央値では 0 と 0 を比べることになる。また短い断片の密度はキンクが
    1 個増減するだけで大きく振れる。まとめた比は画像全体での判定した輪郭 1 µm
    あたりのキンク数であり、各ファイバーは判定された長さに比例して寄与する。
    """
    kinks = 0
    judged_um = 0.0
    n_fibers = 0
    for stat in stats:
        length_um = fiber_judged_length_um(stat)
        if not np.isfinite(length_um):
            continue
        kinks += int(stat.kink_count)
        judged_um += length_um
        n_fibers += 1
    return kinks, judged_um, n_fibers


def _comparison_caveat(unit: str) -> str:
    """
    Return what a between-group test at this unit treats as independent.
    この集計単位での群間検定が何を独立とみなしているかを返す。

    Parameters
    ----------
    unit
        Aggregation unit the samples were tested at.
        検定した標本の集計単位。

    Returns
    -------
    str
        Translated caveat for the fiber unit; an empty string for the image
        unit, whose samples are the images themselves.
        fiber 単位では翻訳済みの注意書き。image 単位では空文字列（標本が画像
        そのものであるため）。

    Notes
    -----
    Fibers of one image share one scan: one place on the specimen, one tip
    and one background calibration. A test that counts them as independent
    assumes they resemble each other no more than fibers of different images
    do, and its significance grows with the number of fibers rather than the
    number of images. The image unit takes one value per image instead, so
    the difference between places on a specimen enters the comparison.
    同じ画像のファイバーは 1 回の走査を共有する。試料上の 1 つの場所、1 つの探針、
    1 回の背景補正である。それらを独立と数える検定は、別の画像のファイバーどうしと
    同程度にしか似ていないと仮定しており、その有意性は画像の枚数ではなくファイバーの
    本数とともに増す。image 単位は画像ごとに 1 つの値を取るため、試料上の場所ごとの
    違いが比較に入る。
    """
    if unit == UNIT_FIBER:
        return _(
            "{fiber} 集計は、同じ画像のファイバーを独立な標本として検定しています。"
            "p 値はファイバー本数とともに小さくなります。場所ごとの違いを踏まえて"
            "比べるには、{image} 集計で検定してください。"
        ).format(fiber=UNIT_FIBER, image=UNIT_IMAGE)
    return ""


def _primary_test_note() -> str:
    """
    Say which of the two tests a conclusion rests on.
    2 つの検定のどちらを結論の根拠とするかを述べる。

    Returns
    -------
    str
        The note shown under the comparison table.
        比較表の下に出す注記。

    Notes
    -----
    Both tests are run on every pair, so reading whichever came out smaller
    tests each pair twice and the correction across pairs would not cover it.
    Naming one test as primary keeps the correction meaningful. The quantities
    are run one at a time, so no correction across them can be computed here,
    which is why the note says so rather than leaving it to the documentation.
    どのペアも両方の検定にかけるため、小さく出た方を読むと各ペアを 2 回検定したことに
    なり、ペアにまたがる補正ではそれを扱えない。主検定を 1 つ定めることで補正が意味を
    保つ。計測量は 1 つずつ実行するので、量にまたがる補正はここでは計算できない。
    そのため文書に任せず、注記で述べる。
    """
    return _(
        "結論は Mann-Whitney の p 値で述べてください。KS は分布の形の違いを見る参考値"
        "です。補正はこの計測量のペアだけにかかるため、複数の計測量を検定して述べるときは"
        "別に補正が必要です。"
    )


def _frame_bias_note(param: str, frame_mode: str) -> str:
    """
    Say that an uncorrected length comparison also holds a difference in frame bias.
    補正なしの長さの比較には枠の偏りの差も含まれることを述べる。

    Parameters
    ----------
    param
        Measured-quantity key the comparison was run for.
        比較を実行した計測量キー。
    frame_mode
        Frame mode the lengths were aggregated under.
        長さを集計した枠の扱い。

    Returns
    -------
    str
        The note, or an empty string for any other quantity or mode.
        注記。それ以外の計測量や扱いでは空文字列。

    Notes
    -----
    The frame shortens long fibers more, so even at one scan size two groups
    are biased by different amounts when their fibers differ in length, which is
    the very difference under test. The test still runs, because refusing it
    would leave the default setting with no comparison of lengths.
    枠は長いファイバーほど大きく短縮する。したがって走査範囲が同じでも、繊維の長さが
    違う 2 群の偏りの大きさは違い、それはまさに検定している差である。検定は実行する。
    止めると既定の設定で長さを比較できなくなるためである。
    """
    if param != PARAM_LENGTH or frame_mode not in (FRAME_INCLUDE, FRAME_EXCLUDE):
        return ""
    return _(
        "{mode} の長さは枠の影響で短い側に偏り、長いファイバーの群ほど大きく短縮されます。"
        "この p 値と効果量には、その偏りの差も含まれます。補正して検定するには、枠の扱いを "
        "{ml} に、集計単位を {image} にしてください。"
    ).format(mode=frame_mode, ml=FRAME_MILES_LANTUEJOUL, image=UNIT_IMAGE)


# The level a reader conventionally reads a p-value against. Nothing is
# decided by it; it only selects the pairs `_attainable_p_note` names.
# p 値を読む際に慣例的に使われる水準。これで何かを判定することはなく、
# `_attainable_p_note` が挙げるペアを選ぶためだけに使う。
CONVENTIONAL_ALPHA = 0.05


def _attainable_p_note(comparisons) -> str:
    """
    Name the pairs too small to reach the conventional significance level.
    慣例の有意水準に届き得ないほど小さいペアを挙げる。

    Parameters
    ----------
    comparisons
        `afm_nanofiber_analyzer.group_compare.PairComparison` rows.
        `afm_nanofiber_analyzer.group_compare.PairComparison` の行。

    Returns
    -------
    str
        Translated note naming each such pair with its smallest attainable
        p-value; an empty string when every tested pair can reach the level.
        該当する各ペアを、到達しうる最小の p 値とともに挙げる翻訳済みの注記。
        検定した全ペアが水準に届きうるなら空文字列。

    Notes
    -----
    With three images against three, two groups that do not overlap at all
    still give p = 0.10, so a "not significant" there is a statement about
    the sample size, not about the specimens. The Holm correction only raises
    a p-value, so a pair named here cannot reach the level after it either.
    3 画像対 3 画像では、まったく重ならない 2 群でも p = 0.10 となる。
    そこでの「有意差なし」は試料についてではなく標本数についての言明である。
    Holm 補正は p 値を上げるだけなので、ここで挙げたペアは補正後も水準に届かない。
    """
    limited = [
        c for c in comparisons
        if np.isfinite(c.min_attainable_p)
        and c.min_attainable_p >= CONVENTIONAL_ALPHA
    ]
    if not limited:
        return ""
    pairs = ", ".join(
        "{a} vs {b}: {p:.3g}".format(a=c.group_a, b=c.group_b,
                                     p=c.min_attainable_p)
        for c in limited
    )
    return _(
        "次のペアは、同じ値が無ければ 2 群が完全に分かれても p 値が {alpha} "
        "未満になりません（値はこの標本数で到達しうる最小の p 値）: {pairs}。"
        "これらのペアの「有意差なし」は、差が無いことを示しません。"
    ).format(alpha=CONVENTIONAL_ALPHA, pairs=pairs)


def _format_sample_size(value: float, unit: str) -> str:
    """
    Format a sample size for display.
    表示用に標本量を整形する。

    Parameters
    ----------
    value
        Sample size, a count of samples.
        標本量（標本の件数）。
    unit
        Aggregation-unit key; every unit counts its samples.
        集計単位キー。どの単位も標本を件数で数える。

    Returns
    -------
    str
        Integer with thousands separators.
        3 桁区切りの整数。
    """
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
        Aggregation-unit key; every unit counts its samples.
        集計単位キー。どの単位も標本を件数で数える。

    Returns
    -------
    int
        Plain integer count without thousands separators, which a
        spreadsheet or a script would otherwise read as text rather than as a
        number.
        3 桁区切りを含まない素の整数の件数。区切りが入ると表計算やスクリプトが
        数値ではなく文字列として読んでしまう。
    """
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


def _file_key(path: str) -> str:
    """
    Return the key that identifies one bundle file among the registered ones.
    登録したバンドルファイルの中で 1 つのファイルを識別するキーを返す。

    A path handed over by another GUI and one picked in a dialog may differ in
    separators or letter case, so paths are compared after normalization.
    他の GUI から渡されたパスとダイアログで選んだパスは、区切り文字や大文字小文字が
    異なりうるため、正規化してから比べる。
    """
    return os.path.normcase(os.path.abspath(path))


class Group:
    """
    Store one user-defined group of bundle files, which stands for one specimen.
    ユーザーが定義したバンドルファイルの群を保持するクラス。1 つの試料を表す。

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
    files
        Registered ``.b2z`` bundle paths of this group, in the order they were
        added; a file is not registered twice in the same group.
        このグループに登録された ``.b2z`` バンドルのパス。追加した順に並ぶ。
        同じファイルを同一グループへ二重には登録しない。
    """

    def __init__(self, name: str, color: str) -> None:
        self.id = uuid.uuid4().hex
        self.name = name
        self.color = color
        self.files = []

    def holds(self, path: str) -> bool:
        """
        Return whether a bundle file is already registered in this group.
        バンドルファイルがこのグループに登録済みかを返す。
        """
        key = _file_key(path)
        return any(_file_key(p) == key for p in self.files)


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

        # A press on a file row that may become a drag to another group
        # (`_on_tree_press`); None between presses.
        # 別グループへのドラッグになりうる、ファイル行での押下
        # （`_on_tree_press`）。押下の外では None。
        self._drag = None
        self._drop_target_iid = None
        # Folder the file dialog opens in: the folder of the files added last.
        # ファイルダイアログが開くフォルダ。最後に追加したファイルのフォルダ。
        self._last_dir = None

        # Bundle preview: the reads go through a queue of their own, because
        # `ui_queue` is replaced by every run and drained only while one runs.
        # `_preview_request` numbers the reads so a result that arrives after
        # the selection has moved on is dropped.
        # バンドルのプレビュー。読み込みは専用のキューを通す。`ui_queue` は実行の
        # たびに作り直され、実行中しか処理されないためである。`_preview_request` は
        # 読み込みに番号を付け、選択が移った後に届いた結果を捨てられるようにする。
        self._preview_queue = queue.Queue()
        self._preview_request = 0
        self._preview_reads = 0
        self._preview_after_id = None
        self._preview_poll_id = None
        self._preview_cache = {}
        self._preview_path = None

        # Text shown beside the run button and in the statistics window once
        # the groups changed after the run the result came from.
        # 結果を出した実行の後でグループが変わったとき、実行ボタンの横と統計
        # ウィンドウに出す文。
        self.stale_var = tk.StringVar()

        # The measured quantity and the aggregation unit drive both the worker
        # and every axis/heading label, so they are held as committed state
        # rather than read from the widgets at draw time.
        # 計測量と集計単位はワーカーと全ての軸・見出しラベルの両方を決めるため、
        # 描画時にウィジェットから読むのではなく確定済み状態として保持する。
        self.param = PARAM_HEIGHT
        self.unit = PARAM_SPECS[PARAM_HEIGHT]["units"][0]

        # Arc length the curvature estimator turns over. Committed like the
        # histogram range so an unconfirmed edit cannot reach a run.
        # 曲率推定が回転角を測る弧長。ヒストグラム範囲と同様に確定値として保持し、
        # 未確定の編集が実行へ届かないようにする。
        self.curvature_window = DEFAULT_CURVATURE_WINDOW_NM

        # How contour length treats fibers reaching the image frame. Including
        # them is the default because it is what every earlier run did.
        # 輪郭長で画像の枠に達したファイバーをどう扱うか。以前のすべての実行と
        # 同じ結果になるよう、含めることを既定とする。
        self.frame_mode = FRAME_INCLUDE

        # Bundle metadata read during a comparison run (`_bundle_meta`); None
        # between runs.
        # 比較の実行中に読んだバンドルのメタデータ（`_bundle_meta`）。実行の外では None。
        self._meta_cache: dict | None = None
        # Each bundle's traced fibers, kept between runs so changing the
        # quantity, the unit or the frame mode does not trace every bundle
        # again; an entry is reused only while the bundle, its sidecars and the
        # measurement settings are unchanged (`afm_nanofiber_analyzer.measure._measure_curated`).
        # Read and written only by the worker thread.
        # 各バンドルの追跡結果。実行の間で保持し、計測量・集計単位・枠の扱いを
        # 変えても全バンドルを追跡し直さないようにする。項目を使い回すのは、
        # バンドル、そのサイドカー、計測の設定が変わっていない間だけである
        # （`afm_nanofiber_analyzer.measure._measure_curated`）。ワーカースレッドだけが読み書きする。
        self._measure_cache: dict = {}

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
        # Select the initial group on startup so file controls are immediately usable,
        # matching the behavior of on_add_group.
        # 起動時に初期グループを選択状態にし、ファイル操作を即利用可能にする（on_add_group と挙動を揃える）。
        self.tree.selection_set(g.id)
        self.tree.focus(g.id)

        self._log_initial_message()

    def _build_ui(self) -> None:
        """
        Build the histogram controls, tree view, plot canvas, and log area.
        ヒストグラム操作部、Treeview、描画キャンバス、ログ領域を構築する。

        The statistics window is built here as well and stays hidden until
        its button is pressed.
        統計ウィンドウもここで構築し、ボタンが押されるまで隠しておく。
        """
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(outer)
        right = ttk.Frame(outer)
        outer.add(left, weight=1)
        outer.add(right, weight=3)

        self._build_statistics_window()
        # Build each pane top-to-bottom; creation order is preserved.
        self._build_left_pane(left)
        self._build_right_pane(right)

        self._update_summary()

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        """
        Build the left pane: group/file tree, bundle preview, and log area.
        左ペイン（グループ/ファイルツリー・バンドルのプレビュー・ログ領域）を構築する。

        Notes
        -----
        The three share the pane's height through draggable sashes, so the
        preview can be enlarged when an image has to be inspected closely.
        3 つはドラッグできる仕切りでペインの高さを分け合う。画像を詳しく確かめたい
        ときにプレビューを広げられるようにするためである。
        """
        panes = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        panes.pack(fill=tk.BOTH, expand=True)
        frm_group = ttk.Frame(panes)
        frm_preview = ttk.Frame(panes)
        frm_log = ttk.Frame(panes)
        panes.add(frm_group, weight=2)
        panes.add(frm_preview, weight=3)
        panes.add(frm_log, weight=1)
        self._build_group_panel(frm_group)
        self._build_preview_panel(frm_preview)
        self._build_log_panel(frm_log)

    def _build_group_panel(self, parent: ttk.Frame) -> None:
        """
        Build the group/file controls, tree view, and summary label.
        グループ/ファイル操作部・ツリー・サマリラベルを構築する。
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

        self.btn_add_files = ttk.Button(grp_btn_row, text=_("ファイル追加"), command=self.on_add_files)
        self.btn_add_files.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_add_files, _(
            "選択中のグループに .b2z バンドルを追加します。ダイアログでは複数の"
            "ファイルを選べ、Ctrl+A でフォルダ内の全ファイルを選べます。"))

        self.btn_remove_files = ttk.Button(grp_btn_row, text=_("ファイル削除"), command=self.on_remove_files)
        self.btn_remove_files.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_clear_all = ttk.Button(grp_btn_row, text=_("全クリア"), command=self.on_clear_all)
        self.btn_clear_all.pack(side=tk.LEFT, padx=(6, 0))

        tree_row = ttk.Frame(frm_group)
        tree_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 4))

        # Several file rows can be selected at once, so they are removed or
        # moved to another group together.
        # 複数のファイル行を同時に選べる。まとめて削除したり、別のグループへ移したり
        # できるようにするためである。
        self.tree, _tree_sb = create_scrolled_treeview(
            tree_row,
            columns=("count",),
            show="tree headings",
            selectmode="extended",
            height=10,
            headings={
                "#0": _("グループ／ファイル"),
                "count": _("ファイル数"),
            },
            column_options={
                "#0": {"width": 320, "stretch": True},
                "count": {"width": 90, "stretch": False, "anchor": "e"},
            },
            scrollbar_side=tk.LEFT,
        )
        self.tree.tag_configure(DROP_TARGET_TAG, background=DROP_TARGET_COLOR)

        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        # Bind Button-2 as well because macOS may report secondary-click that way.
        # macOS では右クリックが Button-2 として扱われる場合があるため両方バインドする。
        self.tree.bind("<Button-2>", self._on_tree_right_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        # Dragging file rows onto another group moves them there.
        # ファイル行を別のグループへドラッグすると、そこへ移る。
        self.tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.tree.bind("<B1-Motion>", self._on_tree_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release)

        self.summary_var = tk.StringVar(
            value=_("グループ数: {g} / ファイル総数: {p}").format(g=0, p=0)
        )
        ttk.Label(frm_group, textvariable=self.summary_var).pack(anchor="w", padx=6, pady=(0, 6))

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        """
        Build the pane showing the calibrated image of the selected bundle.
        選択中のバンドルの補正済み高さ像を表示するペインを構築する。

        Notes
        -----
        The image is what the registered file holds, so a scan that should not
        be aggregated — a disturbed one, or one filed under the wrong group —
        can be recognized before it is measured.
        画像は登録したファイルが持つものである。集計に入れるべきでない走査（乱れた
        もの、別のグループに入れるべきもの）を、計測の前に見分けられるようにする。
        """
        frm = ttk.Frame(parent)
        frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # A width of one character keeps a long file name from widening the
        # pane; the label fills the pane and shows as much as fits.
        # 幅を 1 文字にして、長いファイル名でペインが広がらないようにする。ラベルは
        # ペインの幅いっぱいに広がり、収まる分だけ表示する。
        self.preview_caption_var = tk.StringVar()
        ttk.Label(frm, textvariable=self.preview_caption_var,
                  anchor="w", width=1).pack(fill=tk.X, padx=6, pady=(2, 2))

        # A small figure, so the canvas asks for little room and the pane's
        # sash decides how large the image is drawn.
        # Figure は小さくしておく。キャンバスの要求サイズを小さくし、画像の大きさを
        # ペインの仕切りで決められるようにするためである。
        self.preview_fig = plt.Figure(figsize=(3.2, 2.6), dpi=100)
        self.preview_canvas = FigureCanvasTkAgg(self.preview_fig, master=frm)
        self.preview_canvas.get_tk_widget().pack(
            fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self._clear_preview(_("ファイル行を選ぶと、その画像を表示します。"))

    def _build_statistics_window(self) -> None:
        """
        Build the hidden window holding the statistics and comparison tables.
        統計値の表と群間比較の表を載せるウィンドウを、隠した状態で構築する。

        Notes
        -----
        The tables are built once and filled by every run, whether the window
        is shown or not, so opening it shows the latest result and a run made
        while it is open refreshes it.
        表は 1 度だけ作り、ウィンドウが表示されているかどうかにかかわらず、実行の
        たびに埋める。そのため開けば最新の結果が見え、開いたまま実行すれば内容が
        更新される。
        """
        self.stats_window = StatisticsWindow(self)
        self._build_result_panel(self.stats_window.body)
        self._build_comparison_panel(self.stats_window.body)

    def on_show_statistics(self) -> None:
        """
        Show the statistics window, in front of the other windows.
        統計ウィンドウを、他のウィンドウの手前に表示する。
        """
        self.stats_window.show()

    def _build_result_panel(self, parent: ttk.Frame) -> None:
        """
        Build the per-group statistics result table and its save button.
        グループ別統計結果テーブルと保存ボタンを構築する。
        """
        frm_res = ttk.Frame(parent)
        frm_res.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        res_btn_row = ttk.Frame(frm_res)
        res_btn_row.pack(fill=tk.X, padx=6, pady=(6, 2))

        self.btn_save_stats = ttk.Button(
            res_btn_row, text=_("統計値を保存"),
            command=self.on_save_stats, state=tk.DISABLED,
        )
        self.btn_save_stats.pack(side=tk.LEFT)

        # One caption carries the quantity, its unit, and the sample unit, so
        # the value columns do not each have to repeat the unit.
        # 計測量・単位・集計単位はこのキャプションにまとめ、各数値列で単位を
        # 繰り返さない。
        self.result_caption_var = tk.StringVar()
        ttk.Label(res_btn_row, textvariable=self.result_caption_var).pack(
            side=tk.LEFT, padx=(10, 0)
        )
        self._update_result_caption()
        # Says that the groups changed after the run the tables came from.
        # 表を出した実行の後でグループが変わったことを示す。
        ttk.Label(res_btn_row, textvariable=self.stale_var,
                  foreground="#b00020").pack(side=tk.LEFT, padx=(12, 0))

        # The tree lives in its own row so a horizontal scrollbar can sit
        # under it: a Treeview clips columns that overflow a narrowed window
        # without any scroll affordance.
        # ツリーは専用の行に置き、その下に横スクロールバーを配置する。Treeview は、
        # 狭めたウィンドウから溢れた列をスクロール手段なしに切り落としてしまうため。
        res_tree_row = ttk.Frame(frm_res)
        res_tree_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        self.result_tree, _res_sb = create_scrolled_treeview(
            res_tree_row,
            columns=("group", "median", "iqr", "mean", "std", "mode",
                     "n", "nfib", "nimg", "width"),
            show="headings",
            height=5,
            headings=self._result_headings(self.param),
            # Widths hold the formatted values, not a unit-bearing heading; the
            # group name takes whatever room the window has left.
            # 列幅は単位付き見出しではなく整形後の値に合わせる。グループ名の列が、
            # ウィンドウの残りの幅を使う。
            column_options={
                "group":  {"width": 100, "anchor": "w", "stretch": True},
                "median": {"width": 72, "anchor": "e", "stretch": False},
                "iqr":    {"width": 116, "anchor": "e", "stretch": False},
                "mean":   {"width": 72, "anchor": "e", "stretch": False},
                "std":    {"width": 84, "anchor": "e", "stretch": False},
                "mode":   {"width": 68, "anchor": "e", "stretch": False},
                "n":      {"width": 66, "anchor": "e", "stretch": False},
                "nfib":   {"width": 62, "anchor": "e", "stretch": False},
                "nimg":   {"width": 66, "anchor": "e", "stretch": False},
                "width":  {"width": 56, "anchor": "e", "stretch": False},
            },
            tree_pack_kwargs={
                "side": tk.LEFT, "fill": tk.BOTH, "expand": True,
            },
            scrollbar_side=tk.LEFT,
            scrollbar_pack_kwargs={"side": tk.LEFT, "fill": tk.Y},
        )
        self._show_width_column(False)

        res_hsb = ttk.Scrollbar(
            frm_res, orient=tk.HORIZONTAL, command=self.result_tree.xview,
        )
        self.result_tree.configure(xscrollcommand=res_hsb.set)
        res_hsb.pack(fill=tk.X, padx=6, pady=(0, 6))

    @staticmethod
    def _result_headings(param: str, std_definition: str = STD_SAMPLE) -> dict:
        """
        Return the result-table column headings.
        結果テーブルの列見出しを返す。

        Parameters
        ----------
        param
            Measured-quantity key from `PARAM_SPECS`, reserved for headings
            that need to vary by quantity.
            `PARAM_SPECS` の計測量キー。計測量ごとに変える見出し用に受け取る。
        std_definition
            `STD_SAMPLE` or `STD_WEIGHTED`, naming how the standard deviation
            column was computed.
            `STD_SAMPLE` または `STD_WEIGHTED`。標準偏差の列の計算法を示す。

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
            "std": STD_HEADINGS[std_definition],
            "mode": "mode",
            "n": "N",
            "nfib": "N fibers",
            "nimg": "N images",
            "width": "W (nm)",
        }

    def _show_width_column(self, show: bool) -> None:
        """
        Show or hide the apparent-width column of the result table.
        結果テーブルの見かけの幅の列を表示または非表示にする。

        Parameters
        ----------
        show
            Whether the table lists the column.
            テーブルにこの列を出すかどうか。
        """
        columns = self.result_tree["columns"]
        self.result_tree.configure(
            displaycolumns=columns if show else columns[:-1])
        # The other columns give up the room the width column takes, because the
        # table does not grow and a column past its edge reads as absent.
        # 他の列が幅の列の分を譲る。テーブルは広がらず、端からはみ出した列は無いように
        # 見えるためである。
        self.result_tree.column("group", width=64 if show else 100)
        self.result_tree.column("n", width=46 if show else 66)

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
        frm.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

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
                "ks": "KS p (reference)",
                "delta": "Cliff's delta",
                "magnitude": "effect",
            },
            column_options={
                "pair": {"width": 140, "anchor": "w", "stretch": True},
                "n": {"width": 76, "anchor": "e", "stretch": False},
                "u": {"width": 108, "anchor": "e", "stretch": False},
                "ks": {"width": 112, "anchor": "e", "stretch": False},
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

        # Below the table rather than beside the note, because the caveat is a
        # paragraph and the header row would otherwise widen the whole window;
        # it wraps to the panel width and is packed only while it has text.
        # 注意書きは段落なので、注記の横ではなく表の下に置く。見出し行に置くと
        # ウィンドウ全体が横に広がるためである。パネル幅で折り返し、文があるときだけ
        # 配置する。
        # A scrollbar, because several notes can apply at once and together
        # they are longer than the field.
        # スクロールバーを付ける。複数の注記が同時に当てはまることがあり、合わせると
        # 欄より長くなるためである。
        self.comparison_caveat_row = ttk.Frame(frm)
        self.comparison_caveat_text = tk.Text(
            self.comparison_caveat_row, height=6, wrap=tk.WORD, state=tk.DISABLED,
            relief=tk.FLAT, font="TkDefaultFont",
            background=ttk.Style().lookup("TFrame", "background"),
        )
        caveat_sb = ttk.Scrollbar(
            self.comparison_caveat_row, orient=tk.VERTICAL,
            command=self.comparison_caveat_text.yview,
        )
        self.comparison_caveat_text.configure(yscrollcommand=caveat_sb.set)
        self.comparison_caveat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        caveat_sb.pack(side=tk.LEFT, fill=tk.Y)

    def _set_comparison_caveat(self, text: str) -> None:
        """
        Show or hide the caveat under the comparison table.
        比較テーブル下の注意書きを表示または非表示にする。

        Parameters
        ----------
        text
            Caveat to show; an empty string hides the field.
            表示する注意書き。空文字列なら欄を隠す。
        """
        self.comparison_caveat_text.configure(state=tk.NORMAL)
        self.comparison_caveat_text.delete("1.0", tk.END)
        self.comparison_caveat_text.insert("1.0", text)
        self.comparison_caveat_text.configure(state=tk.DISABLED)
        if text:
            self.comparison_caveat_row.pack(
                fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        else:
            self.comparison_caveat_row.pack_forget()

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
        Build the right pane.
        右ペインを構築する。

        It holds the action bar, histogram controls, plot options, and the
        scrollable plot canvas.
        操作バー・ヒストグラム設定・図オプション・スクロール可能な描画キャンバスを
        並べる。
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

        self.btn_stats = ttk.Button(
            actionbar, text=_("統計処理"),
            command=self.on_show_statistics, state=tk.DISABLED,
        )
        self.btn_stats.pack(side=tk.LEFT, padx=(6, 0))
        ToolTip(self.btn_stats, _(
            "グループごとの統計値と群間比較の結果を、別のウィンドウに表示します。"
            "統計値と比較の保存もそのウィンドウで行います。開いたままヒストグラムを"
            "作成し直すと、内容が更新されます。"))

        # Says that the groups changed after the run the figure came from.
        # 図を出した実行の後でグループが変わったことを示す。
        ttk.Label(actionbar, textvariable=self.stale_var,
                  foreground="#b00020").pack(side=tk.LEFT, padx=(12, 0))

    def _build_quantity_controls(self, parent: ttk.Frame) -> None:
        """
        Build the selectors that choose what is plotted.
        描画する内容を選ぶセレクタを構築する。

        They choose the measured quantity, the aggregation unit, and the plot
        type.
        計測量・集計単位・図の種類を選ぶ。

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
        # The first row holds the selectors that define what is computed; the
        # curation switches and per-quantity settings go on the second row so
        # both rows fit the default window width in every UI language.
        # 1 段目には何を計算するかを決めるセレクタを置き、キュレーションの切替と
        # 計測量ごとの設定は 2 段目に置く。どの UI 言語でも既定のウィンドウ幅に
        # 両方の段が収まるようにするため。
        inputbar = ttk.Frame(parent)
        inputbar.pack(fill=tk.X, padx=6, pady=(6, 0))
        parambar = ttk.Frame(parent)
        parambar.pack(fill=tk.X, padx=6, pady=(4, 0))

        # Applying a bundle's manual exclusions is the default: a sidecar
        # exists only because someone curated that dataset, and ignoring it
        # would silently analyze objects they had already rejected.
        # バンドルの手動除外は適用を既定とする。サイドカーは誰かがそのデータセットを
        # キュレーションしたときにのみ存在するため、無視すると既に棄却された対象を
        # 黙って解析することになる。
        self.apply_exclusions_var = tk.BooleanVar(value=True)
        self.chk_exclusions = ttk.Checkbutton(
            parambar, text=_("除外を適用"),
            variable=self.apply_exclusions_var,
            command=self._on_curation_toggle,
        )
        self.chk_exclusions.pack(side=tk.LEFT)
        ToolTip(self.chk_exclusions, _(
            "バンドル横の {suffix} に記録された手動除外を適用します。Fiber Tracker "
            "で除外したファイバーが集計から外れ、何本外れたかはログに出ます。"
            "OFF にすると、追跡された全てのファイバーを集計します。"
        ).format(suffix="_excluded.json"))

        self.apply_connection_var = tk.BooleanVar(value=True)
        self.chk_connection = ttk.Checkbutton(
            parambar, text=_("連結を適用"),
            variable=self.apply_connection_var,
            command=self._on_curation_toggle,
        )
        self.chk_connection.pack(side=tk.LEFT, padx=(8, 0))
        ToolTip(self.chk_connection, _(
            "バンドル横の {suffix} に記録された連結結果を適用します。Fiber Tracker "
            "で連結して保存したバンドルは、そこで見ていたのと同じ 1 本の"
            "フィブリルとして集計されます。自動連結と手動連結は区別されません。"
            "記録されているのはどの断片が繋がっているかであり、探索はここでは"
            "実行されないため、集計対象は画面で確認したものと一致します。"
            "ファイルの無いバンドルは骨格断片のまま集計されるため、適用できた"
            "枚数はログに出ます。"
        ).format(suffix=CONNECT_SUFFIX))

        # Quantity and unit keys are fixed English identifiers that also appear
        # on axes and in exports, so they are shown verbatim; only the field
        # labels and the hint text are localized. This matches the existing
        # y-axis selector, which shows "density"/"percent" untranslated.
        # 計測量・集計単位のキーは軸や出力にも現れる固定英語識別子のため、その
        # まま表示し、ラベルとヒント文のみ翻訳対象とする。"density"/"percent"
        # をそのまま表示する既存の縦軸セレクタと同じ方針。
        ttk.Label(inputbar, text=_("計測量")).pack(side=tk.LEFT)
        self.param_var = tk.StringVar(value=self.param)
        self.cmb_param = ttk.Combobox(
            inputbar, textvariable=self.param_var,
            values=self._available_params(), width=17, state="readonly",
        )
        self.cmb_param.pack(side=tk.LEFT, padx=(4, 12))
        self.cmb_param.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())
        ToolTip(self.cmb_param, _(
            "比較する形態パラメータを選びます。{height} の {pixel} 集計以外は"
            "ファイバー追跡の結果から算出します。{height} の {pixel} 集計は骨格画素の"
            "高さをそのまま集めるため走査範囲が未記録のバンドルでも計測できますが、"
            "それ以外はバンドルに走査範囲が記録されている必要があります。"
        ).format(height=PARAM_HEIGHT, pixel=UNIT_PIXEL))

        ttk.Label(inputbar, text=_("集計単位")).pack(side=tk.LEFT)
        self.unit_var = tk.StringVar(value=self.unit)
        self.cmb_unit = ttk.Combobox(
            inputbar, textvariable=self.unit_var,
            values=self._available_units(self.param),
            width=8, state="readonly",
        )
        self.cmb_unit.pack(side=tk.LEFT, padx=(4, 8))
        self.cmb_unit.bind("<<ComboboxSelected>>", lambda _e: self._on_unit_change())
        ToolTip(self.cmb_unit, _(
            "1 標本の数え方を選びます。{pixel} は骨格画素 1 点、"
            "{fiber} はファイバー 1 本（高さはファイバー内の中央値）、"
            "{image} は画像 1 枚です。{image} は含まれるファイバー値の中央値で、"
            "キンク密度は総キンク数を判定した長さの合計で割った値です。キンク密度は"
            "{image} でだけ集計します。1 本ごとの密度は判定した長さ L に対して 0、"
            "1/L、2/L… の値しか取らず、分布の形が断片の長さで決まるためです。"
            "{pixel} でまとめた分布は独立観測ではなく、長いファイバーほど重みが"
            "大きくなるため、群間比較では {fiber}・{image} でも確認してください。"
            "{fiber} は同じ画像のファイバーを独立と数えるため、場所ごとの違いを"
            "踏まえて比べるときは {image} を使います。"
            "{pixel} はサンプリング間隔（nm/px）の小さい画像ほど標本が多くなるため、サンプリング間隔（nm/px）の"
            "異なる画像を同じグループに混ぜるとログに注意を出します。"
        ).format(
            pixel=UNIT_PIXEL, fiber=UNIT_FIBER, image=UNIT_IMAGE,
        ))

        self.plot_type_var = tk.StringVar(value=PLOT_HISTOGRAM)
        ttk.Label(inputbar, text=_("図")).pack(side=tk.LEFT)
        self.cmb_plot_type = ttk.Combobox(
            inputbar, textvariable=self.plot_type_var,
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

        ttk.Label(parambar, text=_("曲率窓") + " (nm)").pack(side=tk.LEFT, padx=(16, 0))
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
            "{curvature} が回転角を測る弧長です。スケルトンの画素をそのままたどる線"
            "（{skeleton}、{pixels}）では一歩が直交か斜めに限られるため、窓が小さいと"
            "方向の量子化が値に表れます。大きくすると滑らかになりますが、窓より"
            "短いファイバーは測定対象から外れます。"
        ).format(curvature=PARAM_CURVATURE, skeleton=SKELETON_TRACK,
                 pixels=SKELETON_PIXEL_LINE))

        ttk.Label(parambar, text=_("枠のファイバー")).pack(side=tk.LEFT)
        self.frame_mode_var = tk.StringVar(value=self.frame_mode)
        self.cmb_frame_mode = ttk.Combobox(
            parambar, textvariable=self.frame_mode_var,
            values=list(FRAME_MODES), width=16, state="readonly",
        )
        self.cmb_frame_mode.pack(side=tk.LEFT, padx=(4, 8))
        self.cmb_frame_mode.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_frame_mode_change()
        )
        ToolTip(self.cmb_frame_mode, _(
            "{length} だけに効く設定です。画像の枠に達したファイバーは走査範囲の外へ"
            "続いているため、長さが短く測られます。{include} はそのまま集計し、"
            "枠に達した割合をグループごとに図とログに出します。"
            "{exclude} は長さの集計から外します。ただし長いファイバーほど枠に"
            "達しやすいため、外すだけでは長いファイバーが過小になります。どちらの偏りも"
            "走査範囲で変わるため、比べるバンドルの走査範囲が違うとログで警告します。{ml} は"
            "外したうえで、残った各ファイバーを枠内に収まる確率の逆数で重み付けし"
            "（Miles-Lantuejoul 補正）、その偏りを小さくします。走査範囲に近い長さは"
            "枠に収まる向きが少ないか無いため、差が残ります。交差で切れた断片は"
            "補正されず、その本数はログに出ます。{km} は、枠と交差のどちらで切れた"
            "長さも扱います。自身の端を 2 つ持つファイバーを全長の観測、1 つだけ持つ"
            "ファイバーを「計測した長さ以上」の観測として、ファイバーの長さの分布を"
            "推定します（Kaplan-Meier 推定）。{km} は {fiber} 集計でだけ使えます。"
            "全長を見たうち最長のファイバーより長い側は推定できず、その割合は図と"
            "ログに出ます。推定はグループごとに行います。そこに落ちる中央値や四分位数は、"
            "数値の代わりに「> 全長を見た最長のファイバーの長さ」と書きます。"
            "ファイバーをリサンプリングした 95 % 区間はログと統計値の "
            "CSV に出ます。平均・標準偏差・最頻値は空欄にします。{fiber} 集計の重み付きの標本"
            "には群間検定を行いません。{ml} の {image} 集計は、各画像の重み付き中央値を"
            "検定します。高さ・曲率・キンクは枠内の部分の"
            "測定として有効なため、この設定の影響を受けません。"
        ).format(
            length=PARAM_LENGTH, include=FRAME_INCLUDE,
            exclude=FRAME_EXCLUDE, ml=FRAME_MILES_LANTUEJOUL,
            km=FRAME_KAPLAN_MEIER, fiber=UNIT_FIBER,
            image=UNIT_IMAGE,
        ))
        self._update_frame_mode_state()

    def _available_params(self) -> list:
        """
        Return the quantities the quantity selector offers.
        計測量セレクタに出す計測量を返す。

        Returns
        -------
        list of str
            Quantity keys in `PARAM_ORDER`.
            `PARAM_ORDER` の順に並んだ計測量キー。
        """
        return list(PARAM_ORDER)

    def _available_units(self, param: str) -> list:
        """
        Return the aggregation units a quantity can be aggregated at.
        ある計測量を集計できる集計単位を返す。

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
        return list(PARAM_SPECS[param]["units"])

    def _on_curation_toggle(self) -> None:
        """
        Invalidate cached results when a curation setting changes.
        キュレーション設定の変更時にキャッシュ済み結果を破棄する。

        Notes
        -----
        Exclusion and connection both change which objects are measured, not
        how a fixed set is displayed, so a cached result computed under the
        previous setting describes a different population.
        除外と連結はいずれも「固定された集合の見せ方」ではなく「何を計測対象と
        するか」を変える。そのため、変更前の設定で計算されたキャッシュ結果は別の
        母集団を記述している。
        """
        self._reset_result_state()

    def _update_frame_mode_state(self) -> None:
        """
        Enable the frame-mode selector only where it has an effect.
        枠の扱いのセレクタを、効果がある場合だけ有効にする。

        Notes
        -----
        It applies to contour length only, so it is disabled for every other
        quantity and while a run is in progress; the selected mode is kept so
        switching back to length restores it.
        輪郭長にだけ適用されるため、他の計測量と実行中は無効にする。選択中の
        扱いは保持し、長さに戻したときに復元する。
        """
        enabled = self.param == PARAM_LENGTH and not self.is_running
        self.cmb_frame_mode.configure(
            state="readonly" if enabled else tk.DISABLED
        )

    def _on_frame_mode_change(self) -> None:
        """
        Apply a frame-mode change and invalidate cached results.
        枠の扱いの変更を反映し、キャッシュ済み結果を破棄する。
        """
        mode = self.frame_mode_var.get()
        if mode not in FRAME_MODES:
            self.frame_mode_var.set(self.frame_mode)
            return
        if mode == self.frame_mode:
            return
        self.frame_mode = mode
        # The mode changes which fibers are measured and how they count, so a
        # cached result describes a different population.
        # この扱いはどのファイバーをどう数えるかを変えるため、キャッシュ済み
        # 結果は別の母集団を記述している。
        self._reset_result_state()

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
        self._update_result_caption()
        self._update_frame_mode_state()
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

        # Matplotlib figure sizes are in inches; the unit is fixed English.
        # Matplotlib の図サイズはインチ単位。単位表記は固定英語とする。
        ttk.Label(optbar, text=_("図の幅") + " (in)").pack(side=tk.LEFT)
        self.ent_fig_w = ttk.Entry(optbar, textvariable=self.fig_w_var, width=4)
        self.ent_fig_w.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_fig_w,
            lambda: self._fmt_num(self.fig_w),
            self._commit_plot_params,
        )

        # Stacked mode treats this height as per subplot; other modes use it as figure height.
        # 縦並び時は 1 サブプロット分、重ね表示や単一グループでは Figure 全体の高さとして扱う。
        ttk.Label(optbar, text=_("図の高さ") + " (in)").pack(side=tk.LEFT)
        self.ent_fig_h = ttk.Entry(optbar, textvariable=self.fig_h_var, width=4)
        self.ent_fig_h.pack(side=tk.LEFT, padx=(4, 10))
        self._register_unconfirmed_entry(
            self.ent_fig_h,
            lambda: self._fmt_num(self.fig_h),
            self._commit_plot_params,
        )
        ToolTip(self.ent_fig_h, _(
            "{histogram} を縦並びで表示するときは 1 グループ分の高さで、図全体の"
            "高さはグループ数倍になります。それ以外では図全体の高さです。"
        ).format(histogram=PLOT_HISTOGRAM))

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
            + _("  2) Treeview でグループを選び「ファイル追加」で .b2z バンドルを登録（複数選択可）\n")
            + _("  3) 計測量と集計単位、条件と表示モード（縦並び/重ね表示）を設定して「ヒストグラム作成」\n")
            + _("  4) 統計値と群間比較は「統計処理」で表示。必要に応じて「画像を保存」「数値を保存（グループ別CSV）」\n")
            + "\n"
            + _("ヒント:\n")
            + _("  - グループをダブルクリックで名前変更／右クリックで色変更\n")
            + _("  - ファイル行を選ぶと画像を表示。別のグループへドラッグすると移動\n")
            + _("  - 縦軸モード: 非表示=目盛なし / {density}=割合(0–1) / {percent}=パーセント\n").format(
                density="density", percent="percent"
            )
            + _("  - グループ間でデータ数が大きく異なるときは {density} または {percent} を推奨\n").format(
                density="density", percent="percent"
            )
            + _("  - {pixel} 集計は骨格画素をまとめた分布で、長いファイバーほど重みが大きく、"
                "同一ファイバーの隣接画素も独立ではありません。群間比較の根拠には "
                "{fiber}・{image} 集計での N も併せて確認してください。\n").format(
                pixel=UNIT_PIXEL, fiber=UNIT_FIBER, image=UNIT_IMAGE,
            )
            + _("  - {height} の {pixel} 集計以外はファイバー追跡を行うため処理時間が"
                "かかり、バンドルに走査範囲が記録されている必要があります。\n").format(
                height=PARAM_HEIGHT, pixel=UNIT_PIXEL)
            + _("  - mode はヒストグラムのビン幅に依存します。step を変えると値が変わるため、"
                "報告には median と IQR を併記してください。\n")
        )
        self._log(msg)

    # _log is inherited from ui_tools.LogMixin.
    def _default_save_dir(self) -> str:
        """
        Return the folder of the first registered bundle for save dialogs.
        保存ダイアログ用に、最初に登録されたバンドルのあるフォルダを返す。
        """
        for group in self.groups:
            for path in group.files:
                return os.path.dirname(path)
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
        When results already exist, the collected samples are re-binned and
        redrawn (`_rebin_last_results`); the bundles are not measured again.
        既存の結果がある場合は、集めた標本をビンに数え直して再描画する
        （`_rebin_last_results`）。バンドルは計測し直さない。
        """
        def _check(v):
            if v["step"] <= 0:
                return _("step は正の値にしてください。")
            if v["max_h"] <= v["min_h"]:
                return _("max height は min height より大きくしてください。")
            return None

        def _on_success():
            if self._has_result and not self.is_running:
                self._rebin_last_results()

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

    def _file_label(self, path: str) -> str:
        """
        Return the display label for a registered file row: the file name.
        登録ファイル行に表示するラベル（ファイル名）を返す。
        """
        return os.path.basename(path)

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
            values=(len(g.files),),
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
        self.tree.item(g.id, text=self._group_label(g), values=(len(g.files),), tags=(tag,))

    def _file_iid(self, g: Group, path: str) -> str:
        """
        Return the Treeview item ID of a file row: its group's id and its path.
        ファイル行の Treeview アイテム ID（所属グループの id とパス）を返す。
        """
        return f"{g.id}::{path}"

    def _find_group_by_iid(self, iid: str) -> tuple:
        """
        Resolve a Treeview item ID to its group and, for a file row, its path.
        Treeview アイテム ID から、グループと、ファイル行であればそのパスを解決する。

        Returns
        -------
        tuple
            ``(group, path)``; `path` is None for a group row, and both are
            None for an ID that names no row.
            ``(group, path)``。グループ行では `path` は None。どの行も指さない ID
            では両方 None。
        """
        # A group id is a hex string, so the first "::" ends it whatever the
        # path holds.
        # グループの id は 16 進文字列なので、パスの内容にかかわらず最初の "::" が
        # その終わりになる。
        group_id, sep, path = iid.partition("::")
        for g in self.groups:
            if g.id != group_id:
                continue
            if not sep:
                return g, None
            return (g, path) if path in g.files else (None, None)
        return None, None

    def _selected_group(self) -> tuple:
        """
        Return the group the selection points at, and its file when one row is meant.
        選択が指すグループと、行が 1 つに定まる場合はそのファイルを返す。

        Returns
        -------
        tuple
            ``(group, path)`` of the focused row when it is selected, otherwise
            of the first selected row; ``(None, None)`` without a selection.
            フォーカスのある行が選択されていればその ``(group, path)``、そうで
            なければ選択の先頭の行のもの。選択が無ければ ``(None, None)``。
        """
        sel = self.tree.selection()
        if not sel:
            return None, None
        focus = self.tree.focus()
        return self._find_group_by_iid(focus if focus in sel else sel[0])

    def _selected_file_rows(self) -> list:
        """
        Return the selected file rows as ``(iid, group, path)``, in tree order.
        選択中のファイル行を ``(iid, group, path)`` で、ツリーの並び順に返す。
        """
        selected = set(self.tree.selection())
        rows = []
        for g in self.groups:
            for path in g.files:
                iid = self._file_iid(g, path)
                if iid in selected:
                    rows.append((iid, g, path))
        return rows

    def _update_summary(self) -> None:
        """
        Update the group and file count summary label.
        グループ数とファイル数の概要ラベルを更新する。
        """
        self.summary_var.set(
            _("グループ数: {g} / ファイル総数: {p}").format(
                g=len(self.groups), p=sum(len(g.files) for g in self.groups),
            )
        )

    def _mark_results_stale(self) -> None:
        """
        Say that the groups changed after the run the shown result came from.
        表示中の結果を出した実行の後で、グループが変わったことを示す。

        Notes
        -----
        The figure and the tables are kept, because they still describe the
        run they came from; the note tells the reader that the list beside
        them no longer does. It is cleared by the next run.
        図と表は残す。それらは出した実行の内容を今も表しているためである。注記は、
        隣の一覧がもうその実行の内容ではないことを読み手に伝える。次の実行で消える。
        """
        if self._has_result:
            self.stale_var.set(
                _("一覧が変わりました。ヒストグラムを作成し直してください。"))

    @staticmethod
    def _overlapping_inputs(paths) -> tuple:
        """
        Return the bundles of one group that analyzed the same scan lines of one input file.
        1 つのグループのうち、1 つの入力ファイルの同じ走査線を解析したバンドルの組を返す。

        Parameters
        ----------
        paths
            Every bundle of the group.
            グループの全バンドル。

        Returns
        -------
        tuple
            ``(pairs, by_name)``: the overlapping ``(path, path)`` pairs, and how
            many bundles could be traced to their input file only by their name.
            ``(pairs, by_name)``。重なる ``(path, path)`` の組と、入力ファイルを
            名前でしか突き止められなかったバンドルの数。

        Notes
        -----
        GUI01 keeps a whole-image bundle when the scan is later analyzed as
        scan-line ranges, so both can be registered in one group, as can a copy
        of a bundle under another name; pooling them counts every fiber of the
        overlap twice. Two bundles overlap when they come from the same input
        file and their scan-line ranges intersect. The input file is the
        bundle's recorded ``input_sha256`` when both record one, and otherwise
        the name less its ``_r<start>-<stop>`` suffix; the range is the
        bundle's ``source_region``, and its absence means the whole image. A
        bundle that cannot be read is left out, because its measurement reports
        it.
        GUI01 は、走査を後から走査線範囲で解析しても画像全体のバンドルを残すため、
        両方が 1 つのグループに登録されうる。バンドルを別名でコピーした場合も同じ
        である。まとめると重なった部分の繊維をすべて二度数える。2 つのバンドルは、
        同じ入力ファイルに由来し、走査線の範囲が交わるときに重なるとする。入力
        ファイルは、両方が記録していればバンドルの ``input_sha256``、そうでなければ
        ``_r<start>-<stop>`` を除いた名前で見る。範囲はバンドルの ``source_region``
        で見て、無ければ画像全体とする。読めないバンドルは、その計測が報告するため
        外す。
        """
        entries = []
        for path in paths:
            name = os.path.basename(path)
            if name.endswith(BUNDLE_EXT):
                name = name[:-len(BUNDLE_EXT)]
            match = _ROW_RANGE_NAME.match(name)
            source = match.group("stem") if match else name
            try:
                meta = load_bundle_meta(path)
            except Exception:
                continue
            sha = meta.get("input_sha256") or None
            region = meta.get(SOURCE_REGION_KEY)
            try:
                rows = (int(region["row_start"]), int(region["row_stop"]))
            except (TypeError, KeyError, ValueError):
                rows = None
            entries.append((path, sha, source, rows))

        pairs = []
        for i, (path_a, sha_a, source_a, rows_a) in enumerate(entries):
            for path_b, sha_b, source_b, rows_b in entries[i + 1:]:
                same_input = (sha_a == sha_b) if (sha_a and sha_b) else (
                    source_a == source_b)
                if not same_input:
                    continue
                if (rows_a is None or rows_b is None
                        or (rows_a[0] < rows_b[1] and rows_b[0] < rows_a[1])):
                    pairs.append((path_a, path_b))
        by_name = sum(1 for _p, sha, _s, _r in entries if not sha)
        return pairs, by_name

    def on_add_group(self) -> None:
        """
        Add a new empty histogram group and select it in the tree.
        空のヒストグラムグループを追加し、Treeview 上で選択する。
        """
        name = self._next_default_name()
        g = self._add_group_internal(name)
        # Select the new group so the next file-add action targets it.
        # 追加直後に選択しておくと、そのまま「ファイル追加」できる。
        self.tree.selection_set(g.id)
        self.tree.focus(g.id)
        self.tree.see(g.id)
        self._log(_("グループ追加: {name}").format(name=g.name))

    def on_remove_group(self) -> None:
        """
        Remove the selected group after confirming data-loss cases.
        選択中のグループを、登録ファイルが失われる場合は確認してから削除する。
        """
        g, _path = self._selected_group()
        if g is None:
            messagebox.showwarning(_("未選択"), _("削除するグループを選択してください。"))
            return
        # Skip confirmation for empty groups because no file registrations are lost.
        # 空グループでは失われるファイル登録がないため確認を省略する。
        had_files = bool(g.files)
        if had_files:
            if not messagebox.askyesno(
                _("確認"),
                _("グループ「{name}」を削除しますか？\n所属ファイルの登録もすべて解除されます。").format(name=g.name),
            ):
                return
        self.tree.delete(g.id)
        self.groups.remove(g)
        self._update_summary()
        if had_files:
            self._mark_results_stale()
        self._log(_("グループ削除: {name}").format(name=g.name))

    def on_move_group(self, delta: int) -> None:
        """
        Move the selected group up or down in plotting order.
        選択中のグループを描画順序の中で上下に移動する。

        Parameters
        ----------
        delta
            Positions to move by: negative moves up, positive moves down. A
            move past either end does nothing.
            移動する位置の数。負なら上へ、正なら下へ。端を越える移動では何もしない。
        """
        g, _path = self._selected_group()
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
        # 全グループが空で失うファイル登録がない場合は確認を省略する。
        has_any_file = any(g.files for g in self.groups)
        if has_any_file:
            if not messagebox.askyesno(_("確認"), _("すべてのグループとファイル登録を削除しますか？")):
                return
        for iid in list(self.tree.get_children("")):
            self.tree.delete(iid)
        self.groups.clear()
        self._update_summary()
        self._reset_result_state()
        self._log(_("全クリアしました。"))

    def on_add_files(self) -> None:
        """
        Add bundle files chosen in a dialog to the selected group.
        ダイアログで選んだバンドルファイルを、選択中のグループへ追加する。
        """
        g, _path = self._selected_group()
        if g is None:
            messagebox.showwarning(
                _("未選択"),
                _("ファイルを追加する先のグループを Treeview で選択してください。"),
            )
            return

        paths = filedialog.askopenfilenames(
            parent=self, title=_(".b2z バンドルを選択"),
            initialdir=self._last_dir,
            filetypes=[("b2z bundle", "*" + BUNDLE_EXT)],
        )
        if not paths:
            return
        self._last_dir = os.path.dirname(paths[0])
        self.add_files(g, list(paths))

    def add_files(self, g: Group, paths) -> None:
        """
        Register bundle files in a group.
        バンドルファイルをグループへ登録する。

        Parameters
        ----------
        g
            Group the files join.
            ファイルを登録するグループ。
        paths
            Paths chosen in the dialog, or handed over by GUI01's
            "このフォルダをGUI03で解析" or GUI05's "GUI03で開く".
            ダイアログで選んだパス、または GUI01 の「このフォルダをGUI03で解析」や
            GUI05 の「GUI03で開く」から渡されたパス。

        Notes
        -----
        A path that is not an existing ``.b2z`` file, and a file the group
        already holds, are left out and named in the log; the rest are added,
        so one wrong path among many does not refuse the others. The same file
        may be registered in another group, because a comparison may reuse it
        on purpose; the log says so.
        存在する ``.b2z`` ファイルではないパスと、グループが既に持つファイルは
        追加せず、ログに挙げる。残りは追加する。多数のうち 1 つのパスが誤っていても、
        他を拒まないためである。同じファイルを別のグループに登録することはできる。
        比較で意図的に使い回すことがあるためで、その旨をログに出す。
        """
        added = []
        for raw in paths:
            path = os.path.normpath(os.path.abspath(raw))
            if not (path.lower().endswith(BUNDLE_EXT) and os.path.isfile(path)):
                self._log(_("[{name}] 追加しません（{ext} ファイルではないか、見つかりません）: {path}").format(
                    name=g.name, ext=BUNDLE_EXT, path=path))
                continue
            if g.holds(path):
                self._log(_("[{name}] 追加しません（同じグループに登録済み）: {path}").format(
                    name=g.name, path=path))
                continue
            for other in self.groups:
                if other is not g and other.holds(path):
                    self._log(
                        _("注意: 「{f}」は別グループ「{n}」にも登録されています。").format(
                            f=path, n=other.name
                        )
                    )
                    break
            g.files.append(path)
            self.tree.insert(
                g.id, tk.END, iid=self._file_iid(g, path),
                text=self._file_label(path), values=("",),
            )
            added.append(path)

        if not added:
            return
        self._refresh_group_row(g)
        self._update_summary()
        self._mark_results_stale()
        self._log(_("[{name}] {n} 個のファイルを追加しました:").format(
            name=g.name, n=len(added)))
        for path in added:
            self._log(f"  - {path}")

    def on_remove_files(self) -> None:
        """
        Remove the selected file registrations from their groups.
        選択中のファイル登録を、所属グループから削除する。
        """
        rows = self._selected_file_rows()
        if not rows:
            messagebox.showwarning(_("未選択"), _("削除するファイル行を選択してください。"))
            return
        for iid, g, path in rows:
            self.tree.delete(iid)
            g.files.remove(path)
            self._log(_("[{name}] ファイル削除: {path}").format(name=g.name, path=path))
        for g in {id(g): g for _iid, g, _path in rows}.values():
            self._refresh_group_row(g)
        self._update_summary()
        self._mark_results_stale()

    def move_files(self, rows, target: Group) -> None:
        """
        Move registered files to another group.
        登録したファイルを別のグループへ移す。

        Parameters
        ----------
        rows
            ``(iid, group, path)`` of the file rows to move
            (`_selected_file_rows`).
            移すファイル行の ``(iid, group, path)``（`_selected_file_rows`）。
        target
            Group the files join.
            ファイルを移す先のグループ。

        Notes
        -----
        A file already in `target` stays where it is, and the log says so:
        moving it would register one bundle twice in a group, which a run
        refuses (`_overlapping_inputs`). Every move is logged, so a drop made
        by mistake can be seen and undone.
        `target` に既にあるファイルは動かさず、その旨をログに出す。移すと 1 つの
        バンドルがグループに二重に登録され、実行がそれを拒むためである
        （`_overlapping_inputs`）。誤って落とした移動を見つけて戻せるよう、移動は
        すべてログに出す。
        """
        moved = []
        sources = {}
        for iid, g, path in rows:
            if g is target:
                continue
            if target.holds(path):
                self._log(_("[{src}] → [{dst}] 移しません（移動先に登録済み）: {name}").format(
                    src=g.name, dst=target.name, name=os.path.basename(path)))
                continue
            self.tree.delete(iid)
            g.files.remove(path)
            target.files.append(path)
            new_iid = self._file_iid(target, path)
            self.tree.insert(
                target.id, tk.END, iid=new_iid,
                text=self._file_label(path), values=("",),
            )
            moved.append(new_iid)
            sources[id(g)] = g
            self._log(_("[{src}] → [{dst}] 移動: {name}").format(
                src=g.name, dst=target.name, name=os.path.basename(path)))
        if not moved:
            return
        for g in sources.values():
            self._refresh_group_row(g)
        self._refresh_group_row(target)
        self.tree.item(target.id, open=True)
        self._update_summary()
        self._mark_results_stale()
        # Keep the moved rows selected, so they can be seen where they landed
        # and moved again.
        # 移した行を選択したままにする。どこへ入ったかが見え、続けて動かせる。
        self.tree.selection_set(moved)
        self.tree.focus(moved[-1])
        self.tree.see(moved[-1])

    def _on_tree_double_click(self, event):
        """
        Rename a group when its Treeview row is double-clicked.
        Treeview のグループ行がダブルクリックされたときに名前変更を行う。

        Notes
        -----
        Tk delivers the second press of two quick presses on one spot to this
        binding and not to the press binding. On a file row that press can be
        the start of a drag — a row is clicked to select it and pressed again
        at once to drag it — so it is handed to `_on_tree_press`.
        Tk は、同じ場所での素早い 2 回の押下のうち 2 回目を、押下のバインドではなく
        このバインドに渡す。ファイル行では、その押下がドラッグの始まりでありうる
        （行をクリックして選び、すぐに押し直してドラッグする）ため、
        `_on_tree_press` に渡す。
        """
        iid = self.tree.identify_row(event.y)
        if not iid:
            return None
        g, path = self._find_group_by_iid(iid)
        if g is None:
            return None
        if path is not None:
            return self._on_tree_press(event)
        self._rename_group(g)
        return None

    def _on_tree_right_click(self, event) -> None:
        """
        Open the context menu for the group or file row under the pointer.
        ポインタ下のグループ行またはファイル行のコンテキストメニューを開く。
        """
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        g, path = self._find_group_by_iid(iid)
        if g is None:
            return
        # A right-click inside a selection of several rows keeps it, so the
        # menu acts on all of them; anywhere else it selects the row under
        # the pointer.
        # 複数行の選択の中での右クリックは選択を保ち、メニューがその全行に作用する。
        # それ以外では、ポインタ下の行を選択する。
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
            self.tree.focus(iid)

        if path is None:
            menu = self._build_group_context_menu(g)
        else:
            menu = self._build_file_context_menu(g, path)
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

    def _build_file_context_menu(self, g: Group, path: str) -> tk.Menu:
        """
        Build the file context menu: move, remove, group-name and clipboard actions.
        ファイル行のメニュー（移動・削除・グループ名への反映・クリップボードコピー）を
        構築する。

        Notes
        -----
        "Move to group" does what dragging the selected rows does, for a list
        long enough that the group to move to is out of view.
        「グループへ移動」は、選択した行のドラッグと同じことをする。一覧が長く、
        移動先のグループが見えていないときのためである。
        """
        state = tk.DISABLED if self.is_running else tk.NORMAL
        menu = tk.Menu(self, tearoff=0)
        move_menu = tk.Menu(menu, tearoff=0)
        for other in self.groups:
            if other is g:
                continue
            move_menu.add_command(
                label=other.name,
                command=lambda target=other: self.move_files(
                    self._selected_file_rows(), target),
            )
        menu.add_cascade(
            label=_("グループへ移動"), menu=move_menu,
            state=state if len(self.groups) > 1 else tk.DISABLED,
        )
        menu.add_command(label=_("ファイル削除"), command=self.on_remove_files,
                         state=state)
        menu.add_separator()
        menu.add_command(
            label=_("フォルダ名をグループ名にする"),
            command=lambda: self._set_group_name_from_folder(g, path),
        )
        menu.add_command(
            label=_("ファイル名をコピーする"),
            command=lambda: self._copy_file_name(path),
        )
        return menu

    def _set_group_name_from_folder(self, g: Group, path: str) -> None:
        """
        Rename the group to the name of the folder that holds a file.
        ファイルのあるフォルダの名前をグループ名に設定する。
        """
        folder = os.path.dirname(path)
        new_name = os.path.basename(folder) or folder
        # Duplicate names are allowed because group color/order can still distinguish them.
        # グループ色や順序で識別できるため、同名は警告ログのみで許容する。
        if any(other is not g and other.name == new_name for other in self.groups):
            self._log(_("注意: 同名のグループ「{n}」が既に存在します。").format(n=new_name))
        g.name = new_name
        self._refresh_group_row(g)
        self._log(_("グループ名変更: {name}").format(name=new_name))

    def _copy_file_name(self, path: str) -> None:
        """
        Copy a file's name to the clipboard.
        ファイル名をクリップボードにコピーする。
        """
        name = os.path.basename(path)
        self.clipboard_clear()
        self.clipboard_append(name)
        self._log(_("ファイル名をコピーしました: {name}").format(name=name))

    # ----- Dragging file rows to another group -----

    def _on_tree_press(self, event):
        """
        Note a press on a file row, which may become a drag to another group.
        ファイル行での押下を記録する。別グループへのドラッグになりうる。

        Notes
        -----
        A plain press on a row of a selection of several rows is kept from the
        Treeview's own binding, which would reduce the selection to that row
        at once and leave only one row to drag. The selection is reduced on
        release instead, when the press turns out to have been a click
        (`_on_tree_release`). A press with Shift or Ctrl held edits the
        selection and never starts a drag.
        複数行の選択の中の行での修飾キーなしの押下は、Treeview 自身のバインドに
        渡さない。渡すと選択が直ちにその 1 行になり、ドラッグできるのが 1 行だけに
        なるためである。押下がクリックだったと分かったときに、離した時点で選択を
        その行にする（`_on_tree_release`）。Shift か Ctrl を押した押下は選択を
        編集するもので、ドラッグは始めない。
        """
        self._drag = None
        if self.is_running or event.state & 0x0005:
            return None
        if self.tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return None
        iid = self.tree.identify_row(event.y)
        if not iid:
            return None
        g, path = self._find_group_by_iid(iid)
        if path is None:
            return None
        selected = [row[0] for row in self._selected_file_rows()]
        keeps_selection = iid in selected and len(self.tree.selection()) > 1
        self._drag = {
            "x": event.x, "y": event.y, "active": False,
            "iids": selected if keeps_selection else [iid],
            "click_iid": iid if keeps_selection else None,
        }
        if keeps_selection:
            self.tree.focus_set()
            self.tree.focus(iid)
            return "break"
        return None

    def _on_tree_motion(self, event):
        """
        Follow a drag of file rows and mark the group they would be dropped into.
        ファイル行のドラッグを追い、落とす先のグループに印を付ける。
        """
        drag = self._drag
        if drag is None:
            return None
        if not drag["active"]:
            moved = abs(event.x - drag["x"]) + abs(event.y - drag["y"])
            if moved < DRAG_THRESHOLD_PX:
                return "break"
            drag["active"] = True
            self.tree.configure(cursor="hand2")
        # Near the top or bottom edge the list scrolls, so a group that is out
        # of view can be reached.
        # 上下の端の近くでは一覧をスクロールし、見えていないグループに届くようにする。
        if event.y < DRAG_SCROLL_BAND_PX:
            self.tree.yview_scroll(-1, "units")
        elif event.y > self.tree.winfo_height() - DRAG_SCROLL_BAND_PX:
            self.tree.yview_scroll(1, "units")
        self._set_drop_target(self._drop_group_at(event.y, drag["iids"]))
        return "break"

    def _on_tree_release(self, event):
        """
        Drop dragged file rows into the group under the pointer.
        ドラッグしたファイル行を、ポインタ下のグループへ落とす。
        """
        drag = self._drag
        self._drag = None
        if drag is None:
            return None
        if not drag["active"]:
            if drag["click_iid"] is not None:
                self.tree.selection_set(drag["click_iid"])
            return None
        self.tree.configure(cursor="")
        self._set_drop_target(None)
        target = self._drop_group_at(event.y, drag["iids"])
        if target is not None:
            rows = [(iid,) + self._find_group_by_iid(iid) for iid in drag["iids"]]
            self.move_files([row for row in rows if row[1] is not None], target)
        return "break"

    def _drop_group_at(self, y: int, iids) -> "Group | None":
        """
        Return the group a drop at a height in the tree would move rows into.
        ツリー内のある高さで落としたとき、行の移動先になるグループを返す。

        Parameters
        ----------
        y
            Pointer height inside the Treeview, in pixels.
            Treeview 内でのポインタの高さ（px）。
        iids
            Item IDs of the dragged file rows.
            ドラッグ中のファイル行のアイテム ID。

        Returns
        -------
        Group or None
            The group whose row, or one of whose file rows, is at `y`; ``None``
            away from every row, and when every dragged row is already in that
            group, so nothing would move.
            `y` にグループ行かそのファイル行があるグループ。どの行からも外れて
            いるとき、およびドラッグ中の全行が既にそのグループにあって何も動かない
            ときは ``None``。
        """
        iid = self.tree.identify_row(y)
        if not iid:
            return None
        group, _path = self._find_group_by_iid(iid)
        if group is None:
            return None
        if all(self._find_group_by_iid(i)[0] is group for i in iids):
            return None
        return group

    def _set_drop_target(self, group) -> None:
        """
        Mark one group row as the drop target, and unmark the previous one.
        1 つのグループ行に落とす先の印を付け、前の印を外す。
        """
        iid = None if group is None else group.id
        if iid == self._drop_target_iid:
            return
        previous = self._drop_target_iid
        self._drop_target_iid = iid
        for item, marked in ((previous, False), (iid, True)):
            if item is None or not self.tree.exists(item):
                continue
            tags = [t for t in self.tree.item(item, "tags") if t != DROP_TARGET_TAG]
            if marked:
                tags.append(DROP_TARGET_TAG)
            self.tree.item(item, tags=tags)

    # ----- Preview of the selected bundle -----

    def _on_tree_select(self, _event=None) -> None:
        """
        Show the image of the file row the selection rests on.
        選択が指しているファイル行の画像を表示する。

        Notes
        -----
        With several rows selected, the row shown is the focused one — the row
        clicked last — when it is a selected file row, otherwise the last
        selected file row. A group row has no image, so the pane is cleared.
        複数行を選択しているときは、フォーカスのある行（最後にクリックした行）が
        選択中のファイル行ならその行を、そうでなければ選択中の最後のファイル行を
        表示する。グループ行には画像が無いので、ペインを空にする。
        """
        rows = self._selected_file_rows()
        focus = self.tree.focus()
        path = None
        for iid, _g, row_path in rows:
            if iid == focus:
                path = row_path
        if path is None and rows:
            path = rows[-1][2]
        self._request_preview(path)

    def _request_preview(self, path) -> None:
        """
        Schedule the preview of a bundle, or clear the pane for ``None``.
        バンドルのプレビューを予約する。``None`` ならペインを空にする。

        Notes
        -----
        The read starts after `PREVIEW_DELAY_MS` without a further request, in
        a worker thread, so stepping through the list neither reads every row
        passed nor blocks the window.
        読み込みは、次の要求が無いまま `PREVIEW_DELAY_MS` が過ぎてから、ワーカー
        スレッドで始める。一覧を順に移動しても、通過した行をすべて読むことはなく、
        ウィンドウも止まらない。
        """
        if path == self._preview_path:
            return
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None
        self._preview_path = path
        self._preview_request += 1
        if path is None:
            self._clear_preview(_("ファイル行を選ぶと、その画像を表示します。"))
            return
        self._preview_after_id = self.after(
            PREVIEW_DELAY_MS, self._start_preview_read, self._preview_request, path)

    def _start_preview_read(self, request: int, path: str) -> None:
        """
        Read a bundle's preview in a worker thread, or take it from the cache.
        バンドルのプレビューをワーカースレッドで読む。キャッシュにあればそれを使う。
        """
        self._preview_after_id = None
        if request != self._preview_request:
            return
        try:
            key = (_file_key(path), os.path.getmtime(path))
        except OSError:
            key = None
        if key is not None and key in self._preview_cache:
            self._show_preview(path, self._preview_cache[key])
            return
        self.preview_caption_var.set(
            _("読み込み中: {name}").format(name=os.path.basename(path)))
        self._preview_reads += 1
        threading.Thread(
            target=self._preview_worker, args=(request, path, key), daemon=True,
        ).start()
        if self._preview_poll_id is None:
            self._preview_poll_id = self.after(40, self._poll_preview_queue)

    def _preview_worker(self, request: int, path: str, key) -> None:
        """
        Read one bundle's preview and queue it for the main thread.
        1 つのバンドルのプレビューを読み、メインスレッド向けのキューに積む。

        Notes
        -----
        The image is the stored ``calibrated`` array, drawn over the color
        range `compute_auto_vrange` gives, which is how GUI05 colors the same
        bundle. The extent comes from the recorded scan size through
        `bundle_schema.pixel_size_nm`; a bundle without one is drawn with
        square pixels and no physical size.
        画像は保存された ``calibrated`` 配列で、`compute_auto_vrange` が与える
        色範囲で描く。GUI05 が同じバンドルに色を付ける方法と同じである。範囲は、
        記録された走査範囲から `bundle_schema.pixel_size_nm` で求める。記録の無い
        バンドルは正方形の画素で描き、物理サイズは示さない。
        """
        try:
            image, mask = read_height_image(path)
            vmin, vmax = (float(v) for v in compute_auto_vrange(image, mask))
            try:
                scan = scan_size_um_from_meta(load_bundle_meta(path))
            except Exception:
                scan = None
            rows, cols = image.shape
            extent = None
            if scan is not None:
                extent = (pixel_size_nm(scan[0], cols) * cols / 1000.0,
                          pixel_size_nm(scan[1], rows) * rows / 1000.0)
            data = {"image": image.astype(np.float32), "vrange": (vmin, vmax),
                    "extent_um": extent, "shape": (rows, cols)}
            self._preview_queue.put((request, path, key, data, None))
        except Exception as exc:  # noqa: BLE001 - shown in the pane and the log
            self._preview_queue.put(
                (request, path, key, None, f"{type(exc).__name__}: {exc}"))

    def _poll_preview_queue(self) -> None:
        """
        Show the previews the worker threads have read; poll while a read is running.
        ワーカースレッドが読んだプレビューを表示する。読み込み中のものがある間は続ける。
        """
        self._preview_poll_id = None
        while True:
            try:
                request, path, key, data, error = self._preview_queue.get_nowait()
            except queue.Empty:
                break
            self._preview_reads -= 1
            if data is not None and key is not None:
                self._preview_cache[key] = data
                while len(self._preview_cache) > PREVIEW_CACHE_SIZE:
                    self._preview_cache.pop(next(iter(self._preview_cache)))
            # A read that finished after the selection moved on is kept in the
            # cache but not drawn.
            # 選択が移った後に終わった読み込みは、キャッシュには残すが描かない。
            if request != self._preview_request:
                continue
            if error is not None:
                self._clear_preview(_("画像を読めません: {name}").format(
                    name=os.path.basename(path)))
                self._log(_("画像を読めません: {path} ({err})").format(
                    path=path, err=error))
            else:
                self._show_preview(path, data)
        if self._preview_reads > 0:
            self._preview_poll_id = self.after(40, self._poll_preview_queue)

    def _show_preview(self, path: str, data: dict) -> None:
        """
        Draw a bundle's calibrated image and caption in the preview pane.
        バンドルの補正済み高さ像と見出しをプレビューペインに描く。
        """
        rows, cols = data["shape"]
        extent = data["extent_um"]
        vmin, vmax = data["vrange"]
        self.preview_fig.clf()
        ax = self.preview_fig.add_subplot(111)
        if extent is None:
            im = ax.imshow(data["image"], cmap=PREVIEW_COLORMAP,
                           vmin=vmin, vmax=vmax, aspect="equal")
            size_text = "{c} × {r} px".format(c=cols, r=rows)
        else:
            im = ax.imshow(data["image"], cmap=PREVIEW_COLORMAP,
                           vmin=vmin, vmax=vmax, aspect="equal",
                           extent=(0.0, extent[0], extent[1], 0.0))
            size_text = "{x:.3g} × {y:.3g} {um}, {c} × {r} px".format(
                x=extent[0], y=extent[1], um=UNIT_MICROMETER, c=cols, r=rows)
        ax.set_xticks([])
        ax.set_yticks([])
        colorbar = self.preview_fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        colorbar.set_label("height (nm)", fontsize=9)
        colorbar.ax.tick_params(labelsize=8)
        self.preview_fig.subplots_adjust(left=0.02, right=0.86, top=0.98, bottom=0.02)
        self.preview_canvas.draw_idle()
        self.preview_caption_var.set("{folder}/{name}  ({size})".format(
            folder=os.path.basename(os.path.dirname(path)),
            name=os.path.basename(path), size=size_text))

    def _clear_preview(self, caption: str) -> None:
        """
        Empty the preview pane and show a caption in its place.
        プレビューペインを空にし、代わりに見出しを表示する。
        """
        self.preview_fig.clf()
        self.preview_canvas.draw_idle()
        self.preview_caption_var.set(caption)

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
        non_empty_groups = [g for g in self.groups if g.files]
        if not non_empty_groups:
            messagebox.showwarning(
                _("入力不足"),
                _("どのグループにもファイルが登録されていません。"),
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

        # A registered file can have been moved or deleted since it was added,
        # so the disk is checked immediately before analysis. The worker names
        # each missing file; a run with none left is refused here.
        # 登録したファイルは、追加した後で移動や削除をされていることがあるため、
        # 解析直前にディスクを確かめる。見つからないファイルはワーカーが 1 つずつ
        # 挙げる。1 つも残らない実行はここで断る。
        if not any(os.path.isfile(p) for g in non_empty_groups for p in g.files):
            messagebox.showerror(
                _("入力なし"),
                _("登録したファイルが 1 つも見つかりません。"),
            )
            return

        self._set_running(True)

        # Pass lightweight dictionaries to the worker instead of mutable Group objects.
        # 変更され得る Group オブジェクトではなく、軽量な辞書をワーカーへ渡す。
        groups_payload = []
        for g in self.groups:
            if not g.files:
                continue
            groups_payload.append({
                "id": g.id,
                "name": g.name,
                "color": g.color,
                "files": list(g.files),
            })

        self.ui_queue = queue.Queue()
        args = {
            "groups": groups_payload,
            "param": self.param,
            "unit": self.unit,
            "apply_exclusions": bool(self.apply_exclusions_var.get()),
            "apply_connection": bool(self.apply_connection_var.get()),
            "curvature_window": self.curvature_window,
            "frame_mode": self.frame_mode,
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
            self.btn_add_files, self.btn_remove_files,
            self.btn_run,
        ):
            b.configure(state=state)

        # The selectors decide what the running worker is computing, so they
        # stay locked until it finishes; "readonly" is their enabled state.
        # セレクタは実行中のワーカーが何を計算するかを決めるため、完了まで
        # 操作を止める。有効時の状態は "readonly"。
        combo_state = tk.DISABLED if running else "readonly"
        for c in (self.cmb_param, self.cmb_unit):
            c.configure(state=combo_state)
        self._update_frame_mode_state()
        for chk in (self.chk_exclusions, self.chk_connection):
            chk.configure(state=state)

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
                               apply_exclusions: bool = False,
                               curvature_window: float =
                               DEFAULT_CURVATURE_WINDOW_NM,
                               apply_connection: bool = False,
                               frame_mode: str = FRAME_INCLUDE,
                               frame_report=None,
                               curation_report=None,
                               group_name: str = "") -> tuple:
        """
        Collect one group's samples for a quantity and aggregation unit.
        1 グループ分の標本を、計測量と集計単位に従って収集する。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles to read, all registered in one group.
            読み込む ``.b2z`` バンドル。すべて同一のグループに登録されている。
        param
            Measured-quantity key from `PARAM_SPECS`.
            `PARAM_SPECS` の計測量キー。
        unit
            Aggregation-unit key deciding what one sample counts as.
            1 標本を何と数えるかを決める集計単位キー。
        apply_exclusions
            Honor each bundle's manual-exclusion sidecar.
            各バンドルの手動除外サイドカーを適用する。
        curvature_window
            Arc length in nanometers over which curvature is estimated; used
            only for the curvature quantity.
            曲率を推定する弧長 (nm)。曲率の計測量でのみ使う。
        apply_connection
            Honor each bundle's fiber-connection sidecar.
            各バンドルのファイバー連結サイドカーを適用する。
        frame_mode
            One of `FRAME_MODES`; applied only to `PARAM_LENGTH`.
            `FRAME_MODES` のいずれか。`PARAM_LENGTH` にだけ適用する。
        frame_report
            Dict filled with the `_apply_frame_mode` report for contour length,
            so the caller can log it with the group name.
            輪郭長について `_apply_frame_mode` の報告で埋める dict。呼び出し側が
            グループ名を付けてログに出せるようにするため。
        curation_report
            List passed to the `afm_nanofiber_analyzer.measure` collector as its
            ``curation_report``, so the caller can log how many fibers the
            manual exclusions removed.
            `afm_nanofiber_analyzer.measure` のコレクタへ ``curation_report`` として渡すリスト。
            手動除外で何本外れたかを呼び出し側がログに出せるようにするため。
        group_name
            Name the curvature-window note is prefixed with, as every other
            per-group log line is.
            曲率窓の注記の先頭に付けるグループ名。ほかのグループごとのログ行と同じ。

        Returns
        -------
        tuple
            ``(values, weights, n_fibers, n_images, load_errors)``. `weights`
            is None unless the unit weights its samples (Miles-Lantuejoul,
            judged length). `n_fibers` counts the fibers that contributed at
            least one sample and is 0 in the skeleton-pixel path, where fibers
            are not individuated. `load_errors` holds ``(bundle_path,
            message)`` pairs.
            ``(値リスト, 重み, ファイバー数, 画像数, 読込エラー)``。`weights` は
            標本を重み付けする単位（Miles-Lantuejoul、判定長）以外では None。
            `n_fibers` は 1 標本以上を出したファイバーの数で、ファイバーを個体と
            して扱わない骨格画素経路では 0。`load_errors` は
            ``(バンドルパス, メッセージ)``。

        Notes
        -----
        The height/pixel combination reads the skeleton pixels without
        tracing (`skeleton_height_values`), so it is the only one that works
        on a bundle without a recorded scan size. Every other path traces
        fibers and needs a physical pixel size to turn track steps into
        nanometers.
        height/pixel の組み合わせは追跡せずにスケルトン画素を読む
        （`skeleton_height_values`）。そのため走査範囲が未記録のバンドルでも動く
        唯一の組み合わせである。
        ほかの経路はすべてファイバーを追跡し、追跡ステップを nm へ変換するために
        サンプリング間隔（nm/px）を必要とする。
        """
        if param == PARAM_HEIGHT and unit == UNIT_PIXEL:
            heights, load_errors = skeleton_height_values(
                bundle_paths,
                apply_exclusions=apply_exclusions,
                apply_connection=apply_connection,
                curation_report=curation_report,
            )
            failed = {path for path, _msg in load_errors}
            n_images = sum(1 for path in bundle_paths if path not in failed)
            return heights.tolist(), None, 0, n_images, load_errors

        if param == PARAM_CURVATURE:
            per_fiber, load_errors = collect_fiber_curvature(
                bundle_paths,
                apply_exclusions=apply_exclusions,
                curvature_window_nm=curvature_window,
                apply_connection=apply_connection,
                curation_report=curation_report,
                cache=self._measure_cache,
            )
            self._log_curvature_caveats(per_fiber, curvature_window, group_name)
            return self._curvature_values(per_fiber, unit) + (load_errors,)

        per_bundle, load_errors = collect_fiber_stats(
            bundle_paths,
            apply_exclusions=apply_exclusions,
            apply_connection=apply_connection,
            curation_report=curation_report,
            cache=self._measure_cache,
        )
        return self._values_from_fiber_stats(
            self._frame_filtered(per_bundle, param, frame_mode, frame_report),
            param, unit,
            frame_weighted=self._frame_weighted(param, frame_mode),
        ) + (load_errors,)

    @staticmethod
    def _frame_weighted(param: str, frame_mode: str) -> bool:
        """
        Return whether samples carry a frame weight (Miles-Lantuejoul or Kaplan-Meier).
        標本が枠の重み（Miles-Lantuejoul または Kaplan-Meier）を持つかを返す。
        """
        return param == PARAM_LENGTH and frame_mode in WEIGHTED_FRAME_MODES

    @staticmethod
    def _frame_filtered(per_source, param: str, frame_mode: str,
                        frame_report) -> list:
        """
        Apply the frame mode to contour length and pass anything else through.
        輪郭長には枠の扱いを適用し、それ以外はそのまま通す。

        Returns
        -------
        list
            ``(source_path, stats)`` pairs in the shape of `per_source`.
            `per_source` と同じ形の ``(ソースパス, 統計値リスト)`` の列。
        """
        if param != PARAM_LENGTH:
            return per_source
        kept, report = _apply_frame_mode(per_source, frame_mode)
        if report is not None and frame_report is not None:
            frame_report.update(report)
        return kept

    def _count_connected_bundles(self, bundle_paths) -> int:
        """
        Count the bundles whose sidecar records at least one connected fibril.
        連結されたフィブリルを 1 本以上記録しているサイドカーを持つバンドル数を
        数える。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        int
            Bundles that will be measured as whole fibrils rather than as
            skeleton fragments.
            骨格断片ではなく 1 本のフィブリルとして計測されるバンドル数。

        Notes
        -----
        An unreadable sidecar is passed over here rather than reported,
        because the collector reads the same file and turns the failure into a
        per-bundle load error, which is where the user sees it once.
        読めないサイドカーはここでは報告せず読み飛ばす。コレクタが同じファイルを
        読み、失敗をバンドル単位の読込エラーに変換するため、ユーザーはそちらで
        一度だけ目にすることになる。
        """
        count = 0
        for path in bundle_paths:
            try:
                plan = load_connect_plan(connect_path_for(path))
            except Exception:
                continue
            if plan is not None and plan.chains:
                count += 1
        return count

    def _count_bundles_by_line(self, bundle_paths) -> dict:
        """
        Count the bundles by the line they are measured along.
        計測に使う線ごとにバンドル数を数える。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        dict
            Bundle count per line (`bundle_schema.centerline_from_meta`):
            `centerline.SKELETON_TRACK` for a bundle analyzed before format
            1.1, otherwise the line chosen for the analysis.
            線ごとのバンドル数（`bundle_schema.centerline_from_meta`）。形式 1.1
            より前に解析したバンドルは `centerline.SKELETON_TRACK`、それ以外は
            解析に選んだ線。

        Notes
        -----
        Only the metadata is read. An unreadable bundle is passed over here,
        because the collector reports it once as a per-bundle load error.
        メタデータだけを読む。読めないバンドルはここでは読み飛ばす。コレクタが
        バンドル単位の読込エラーとして一度だけ報告するためである。
        """
        counts: dict = {}
        for path in bundle_paths:
            try:
                line = centerline_from_meta(self._bundle_meta(path))
            except Exception:
                continue
            counts[line] = counts.get(line, 0) + 1
        return counts

    def _bundle_meta(self, path: str) -> dict:
        """
        Read a bundle's metadata, at most once in a comparison run.
        バンドルのメタデータを読む。1 回の比較実行の中では高々 1 度しか読まない。

        Parameters
        ----------
        path
            ``.b2z`` bundle of the run.
            実行内の ``.b2z`` バンドル。

        Returns
        -------
        dict
            The bundle's vlmeta (`blosc2_io.load_bundle_meta`).
            バンドルの vlmeta（`blosc2_io.load_bundle_meta`）。

        Notes
        -----
        Several helpers inspect the same bundles before they are measured, and
        each read opens the bundle file, so `_worker_run` keeps what was read
        until the run ends. A read that fails is not kept: every helper still
        sees it fail and passes the bundle over, as it did when reading the
        file itself. Outside a run the metadata is read directly.
        複数の補助関数が計測前に同じバンドルを調べ、読むたびにバンドルファイルを
        開くため、`_worker_run` は読んだ内容を実行の終わりまで保持する。読み取りに
        失敗した結果は保持しない。各補助関数は自分でファイルを読んでいたときと
        同じく失敗を受け取り、そのバンドルを読み飛ばす。実行の外では直接読む。
        """
        cache = getattr(self, "_meta_cache", None)
        if cache is None:
            return load_bundle_meta(path)
        if path not in cache:
            cache[path] = load_bundle_meta(path)
        return cache[path]

    def _bundle_pixel_sizes(self, bundle_paths) -> list:
        """
        Read the X pixel size each bundle is measured with, in nanometers.
        各バンドルを計測する X のサンプリング間隔（nm/px）を読む。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        list of float
            One pixel size per bundle with a recorded scan size
            (`bundle_schema.pixel_size_nm`); a bundle without one, or one that
            cannot be read, is passed over, because the collector reports it.
            走査範囲を記録したバンドルごとのサンプリング間隔（nm/px）
            （`bundle_schema.pixel_size_nm`）。記録の無いバンドルや読めない
            バンドルは読み飛ばす。コレクタがそれを報告するためである。
        """
        sizes = []
        for path in bundle_paths:
            try:
                scan = scan_size_um_from_meta(self._bundle_meta(path))
                if scan is None:
                    continue
                width = bundle_array_shape(path, "calibrated")[1]
                sizes.append(pixel_size_nm(scan[0], width))
            except Exception:
                continue
        return sizes

    def _bundle_scan_sizes(self, bundle_paths) -> list:
        """
        Read the scan size recorded in each bundle.
        各バンドルに記録された走査範囲を読む。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        list of tuple
            ``(x_um, y_um)`` per bundle with a recorded scan size; a bundle
            without one, or one that cannot be read, is passed over, because
            the collector reports it.
            走査範囲を記録したバンドルごとの ``(x_um, y_um)``。記録の無いバンドルや
            読めないバンドルは読み飛ばす。コレクタがそれを報告するためである。
        """
        sizes = []
        for path in bundle_paths:
            try:
                scan = scan_size_um_from_meta(self._bundle_meta(path))
            except Exception:
                continue
            if scan is not None:
                sizes.append(tuple(float(v) for v in scan))
        return sizes

    def _bundle_kink_conditions(self, bundle_paths) -> list:
        """
        Read what a kink count depends on from each bundle.
        キンク数が依存する条件を各バンドルから読む。

        Parameters
        ----------
        bundle_paths
            ``.b2z`` bundles about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        list of dict
            One entry per readable bundle: ``threshold`` (degrees),
            ``version``, ``pixel_nm`` and ``width_px``, the last two ``None``
            when not recorded. A bundle that cannot be read is passed over,
            because the collector reports it.
            読めたバンドルごとに 1 項目。``threshold``（度）、
            ``version``、``pixel_nm``、``width_px``。最後の 2 つは記録が無ければ
            ``None``。読めないバンドルは読み飛ばす。コレクタがそれを報告するため
            である。
        """
        conditions = []
        for path in bundle_paths:
            try:
                meta = self._bundle_meta(path)
                angle, _decompose = kink_params_from_meta(meta)
            except Exception:
                continue
            sizes = self._bundle_pixel_sizes([path])
            width = (meta.get(APPARENT_WIDTH_KEY) or {}).get("median_px")
            height_nm, noise_nm = App._bundle_height_and_noise(path)
            conditions.append({
                "threshold": round(UNRECORDED_KINK_ANGLE_DEG if angle is None
                                   else float(angle), 6),
                "version": str(meta.get("version") or ""),
                "pixel_nm": sizes[0] if sizes else None,
                "width_px": None if width is None else float(width),
                "height_nm": height_nm,
                "noise_nm": noise_nm,
            })
        return conditions

    @staticmethod
    def _bundle_height_and_noise(path: str) -> tuple:
        """
        Read a bundle's typical fiber height and pixel noise from its stored arrays.
        保存された配列から、バンドルの典型的な繊維の高さと画素ノイズを読む。

        Parameters
        ----------
        path
            ``.b2z`` bundle about to be measured.
            これから計測する ``.b2z`` バンドル。

        Returns
        -------
        tuple
            ``(height_nm, noise_nm)`` as `pipeline.fiber_snr` reads them, or
            ``(None, None)`` when they cannot be read.
            `pipeline.fiber_snr` が読む ``(height_nm, noise_nm)``。読めなければ
            ``(None, None)``。

        Notes
        -----
        This measures the stored record and runs no analysis stage. The import
        is local because `afm_nanofiber_analyzer.pipeline` brings the stage modules with it, which
        a run that compares no kinks has no need to load.
        保存された記録を測るだけで、解析段は実行しない。局所インポートなのは、
        `afm_nanofiber_analyzer.pipeline` が解析段のモジュールを伴って読み込まれ、キンクを比べない実行には
        不要なためである。
        """
        from afm_nanofiber_analyzer.pipeline import fiber_snr

        try:
            arrays = load_bundle(
                path, keys=["calibrated", "binarized", "skeletonized"])
            read = fiber_snr(SimpleNamespace(
                calibrated_image=arrays["calibrated"],
                binarized_image=arrays["binarized"],
                skeleton_image=arrays["skeletonized"],
            ))
        except Exception:
            return None, None
        return (None, None) if read is None else read

    def _log_pixel_size_spread(self, pixel_sizes: list) -> None:
        """
        Warn when the bundles measured for curvature differ in pixel size.
        曲率を計測したバンドルのサンプリング間隔（nm/px）が違うときに警告する。

        Parameters
        ----------
        pixel_sizes
            X pixel size of every bundle measured, in nanometers.
            計測した全バンドルの X のサンプリング間隔（nm/px）。

        Notes
        -----
        Curvature is averaged unsigned, so the jitter of the centerline adds
        to it even on a straight fiber, and how much it adds depends on the
        pixel size and the image noise. Bundles imaged at different pixel
        sizes then differ partly because of how they were imaged. The spread is
        taken over every bundle of the run, whichever group it belongs to, so
        the warning says that such bundles were compared, not that the groups
        differ in pixel size. The comparison is still made; the user is told.
        曲率は符号なしで平均するため、まっすぐな繊維でも中心線の揺れが上乗せされ、
        その量はサンプリング間隔（nm/px）と画像のノイズで変わる。そのため、異なるサンプリング間隔（nm/px）で撮像
        したバンドルどうしは、撮像条件の違いによっても差が出る。ばらつきはグループを
        問わず実行内の全バンドルで取るので、警告が示すのはそうしたバンドルを比べた
        ことであり、グループ間でサンプリング間隔（nm/px）が違うことではない。比較はそのまま行い、
        ユーザーに知らせる。
        """
        if len(pixel_sizes) < 2:
            return
        low, high = min(pixel_sizes), max(pixel_sizes)
        # A spread under one percent, such as the rounding of a scan size
        # written in an instrument header, does not raise the warning.
        # 装置ヘッダに書かれた走査範囲の丸めのような 1 % 未満の違いでは警告しない。
        if high <= low * 1.01:
            return
        self.ui_queue.put(("log", _(
            "注意: 比較したバンドルのサンプリング間隔（nm/px）が {low}〜{high} nm/px と異なります。"
            "曲率は中心線の揺れにより、まっすぐな繊維でも 0 より大きく出ます。"
            "その上乗せはサンプリング間隔（nm/px）とノイズで変わるため、サンプリング間隔（nm/px）の違うバンドルの間の"
            "曲率の差には、撮像条件の違いも含まれます。"
        ).format(low=f"{low:.2f}", high=f"{high:.2f}")))

    def _log_group_pixel_size_spread(self, grp_name: str, pixel_sizes: list) -> None:
        """
        Warn when one group pools skeleton pixels of different pixel sizes.
        1 グループがサンプリング間隔（nm/px）の異なるスケルトン画素をまとめるときに警告する。

        Parameters
        ----------
        grp_name
            Group the bundles belong to.
            バンドルが属するグループ。
        pixel_sizes
            X pixel size of each bundle of the group, in nanometers.
            グループの各バンドルの X のサンプリング間隔（nm/px）。

        Notes
        -----
        The pixel unit counts every skeleton pixel once, so a fiber imaged at a
        finer pixel size yields more samples per unit length and weighs more
        in the group's pooled distribution. Nothing is corrected; the user is
        told and decides whether the pooling is acceptable.
        pixel 単位はスケルトン画素を 1 点ずつ数えるため、小さいサンプリング間隔（nm/px）で撮像した
        繊維ほど長さあたりの標本が多く、グループのまとめた分布での重みが大きくなる。
        補正はせず、ユーザーに知らせて、まとめてよいかを判断してもらう。
        """
        if len(pixel_sizes) < 2:
            return
        low, high = min(pixel_sizes), max(pixel_sizes)
        # The same one-percent tolerance as `_log_pixel_size_spread`.
        # `_log_pixel_size_spread` と同じ 1 % の許容幅。
        if high <= low * 1.01:
            return
        self.ui_queue.put(("log", _(
            "[{grp}] 注意: このグループのバンドルのサンプリング間隔（nm/px）が {low}〜{high} nm/px と"
            "異なります。{pixel} 集計では画素 1 点を 1 標本と数えるため、画素の細かい"
            "画像ほど繊維の長さあたりの標本が多く、分布への寄与が大きくなります。"
        ).format(grp=grp_name, low=f"{low:.2f}", high=f"{high:.2f}",
                 pixel=UNIT_PIXEL)))

    def _warn_group_length_floors(self, grp_name: str, bundle_paths) -> None:
        """
        Warn when the bundles of one group keep different shortest fiber lengths.
        1 つのグループのバンドルが残す最短の繊維長が違うときに警告する。

        Parameters
        ----------
        grp_name
            Group name the warning is prefixed with.
            警告の先頭に付けるグループ名。
        bundle_paths
            The group's ``.b2z`` bundles.
            そのグループの ``.b2z`` バンドル。

        Notes
        -----
        The floor of a coarse scan is longer than that of a fine one
        (`length_floor_nm`), so a group that pools both holds fibers between
        the two floors from the fine scans only, and its distribution mixes
        populations cut at different lengths. The group is not cut to one
        floor: that would discard the short fibers the fine scans do record.
        Groups are not compared for it, because each specimen may be imaged
        at the resolution its fibers need.
        粗い走査の下限は細かい走査より長い（`length_floor_nm`）ため、両方をまとめた
        グループでは、2 つの下限の間の長さの繊維が細かい走査からだけ現れ、分布は
        異なる長さで切れた母集団の混ざり物になる。グループを 1 つの下限で切ることは
        しない。細かい走査が実際に記録している短い繊維を捨てることになるためである。
        グループどうしは比べない。試料ごとに、その繊維に合ったサンプリング間隔（nm/px）で撮ることが
        あるためである。
        """
        floors = []
        for path in bundle_paths:
            try:
                floor = length_floor_nm(path)
            except Exception:
                # An unreadable bundle is reported when it is measured.
                # 読めないバンドルは計測の段階で報告される。
                continue
            if floor is not None:
                floors.append(floor)
        if not floors:
            return
        low, high = min(floors), max(floors)
        # A spread under one percent, such as the rounding of a scan size
        # written in an instrument header, is not a difference.
        # 装置ヘッダに書かれた走査範囲の丸めのような 1 % 未満の違いは、違いとしない。
        if high <= low * 1.01:
            return
        self.ui_queue.put(("log", _(
            "[{grp}] 注意: このグループのバンドルが残す最短の繊維長が {low:.0f}〜{high:.0f} nm と"
            "異なります。サンプリング間隔（nm/px）が大きい走査ほど短い繊維が写らないため、"
            "このグループの分布には撮像条件の違いが混ざります。"
        ).format(grp=grp_name, low=low, high=high)))

    def _log_curvature_caveats(self, per_fiber, curvature_window: float,
                               group_name: str) -> None:
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
        group_name
            Group the fibers belong to. The window is one length for every
            group, so a group of shorter fibers loses a larger share of them,
            and the count has to say which group it is.
            ファイバーが属するグループ。窓はどのグループにも同じ長さなので、短い
            ファイバーの多いグループほど多くの割合を失う。そのため本数にはどの
            グループのものかを付ける。

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
                "[{grp}] 曲率窓 {w} nm より短いファイバー {n} 本 / {total} 本は"
                "測定対象外です。窓を広げるとさらに減ります。"
            ).format(
                grp=group_name, w=self._fmt_num(curvature_window),
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
            `afm_nanofiber_analyzer.measure.collect_fiber_curvature`.
            `afm_nanofiber_analyzer.measure.collect_fiber_curvature` が返す
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
    def _values_from_fiber_stats(per_source, param: str, unit: str,
                                 frame_weighted: bool = False) -> tuple:
        """
        Turn per-source fiber statistics into samples for one quantity/unit.
        ソースごとのファイバー統計を、計測量と集計単位に応じた標本へ変換する。

        Parameters
        ----------
        per_source
            ``(source_path, stats)`` pairs, one per bundle.
            ``(ソースパス, 統計値リスト)`` のペア。バンドル 1 件ごと。
        param
            Measured-quantity key from `PARAM_SPECS`.
            `PARAM_SPECS` の計測量キー。
        unit
            Aggregation-unit key.
            集計単位キー。
        frame_weighted
            Weight each fiber by `FiberStats.frame_weight` (the
            Miles-Lantuejoul frame correction). The caller has already removed
            the fibers that reach the frame, which carry no weight.
            各ファイバーを `FiberStats.frame_weight`（Miles-Lantuejoul の枠補正）
            で重み付けする。重みを持たない、枠に達したファイバーは呼び出し側が
            除いてある。

        Returns
        -------
        tuple
            ``(values, weights, n_fibers, n_images)``. `weights` is None except
            for `frame_weighted` fiber samples; the image unit takes a weighted
            median instead and stays unweighted.
            ``(値リスト, 重み, ファイバー数, 画像数)``。`weights` は
            `frame_weighted` のファイバー単位標本以外では None。image 単位では
            代わりに重み付き中央値を取り、重みなしのままにする。

        Notes
        -----
        An image value pools the image's fibers: the median of every fiber
        value it holds, and the pooled kinks over the pooled judged length for
        kink density (`_kink_totals`).
        画像の値は、その画像のファイバーをまとめて求める。すなわち全ファイバー値の
        中央値、キンク密度ではまとめたキンク数をまとめた判定長で割った値
        （`_kink_totals`）である。
        """
        def pooled(source_values, source_weights) -> float:
            if frame_weighted:
                return _summary_stats(
                    np.asarray(source_values, dtype=float),
                    np.asarray(source_weights, dtype=float),
                )["median"]
            return float(np.median(source_values))

        values = []
        weights = [] if frame_weighted and unit != UNIT_IMAGE else None
        n_fibers = 0
        n_images = 0
        for _path, stats in per_source:
            if param == PARAM_KINK_DENSITY and unit == UNIT_IMAGE:
                kinks, judged_um, used = _kink_totals(stats)
                if used == 0:
                    continue
                n_fibers += used
                n_images += 1
                values.append(kinks / judged_um)
                continue

            source_values = []
            source_weights = []
            for stat in stats:
                samples = _fiber_samples(stat, param, unit)
                if not samples:
                    continue
                n_fibers += 1
                source_values.extend(samples)
                if frame_weighted:
                    source_weights.extend([stat.frame_weight] * len(samples))

            if not source_values:
                continue
            n_images += 1
            if unit == UNIT_IMAGE:
                # One sample per image, so a scan with many fibers does not
                # outweigh a sparse scan of the same specimen.
                # 1 画像 1 標本とし、ファイバーの多い画像が同じ試料の疎な画像を
                # 押しのけないようにする。
                values.append(pooled(source_values, source_weights))
            else:
                values.extend(source_values)
                if weights is not None:
                    weights.extend(source_weights)
        return values, weights, n_fibers, n_images

    def _worker_run(self, args: dict) -> None:
        """
        Run one comparison in a background thread, reading each bundle's metadata once.
        バックグラウンドスレッドで 1 回の比較を実行する。各バンドルのメタデータは 1 度だけ読む。

        Parameters
        ----------
        args
            Settings of the run, as `on_run` collects them.
            `on_run` が集めた実行の設定。

        Notes
        -----
        The metadata read during the run is kept until it ends
        (`_bundle_meta`) and dropped afterwards, so the next run reads bundles
        that were analyzed again in the meantime.
        実行中に読んだメタデータは実行の終わりまで保持し（`_bundle_meta`）、その後は
        捨てる。その間に再解析されたバンドルは、次の実行で読み直される。
        """
        self._meta_cache = {}
        try:
            self._run_comparison(args)
        finally:
            self._meta_cache = None

    def _run_comparison(self, args: dict) -> None:
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
        apply_exclusions = args["apply_exclusions"]
        apply_connection = args["apply_connection"]
        curvature_window = args["curvature_window"]
        # The frame mode applies to contour length only; for any other
        # quantity the run is exactly what it was before the mode existed.
        # 枠の扱いは輪郭長にだけ適用する。他の計測量では、この設定が存在する
        # 前とまったく同じ実行になる。
        frame_mode = (
            args.get("frame_mode", FRAME_INCLUDE)
            if param == PARAM_LENGTH else FRAME_INCLUDE
        )
        frame_weighted = self._frame_weighted(param, frame_mode)
        # A Kaplan-Meier estimate describes fibers; the median of one image
        # can itself lie beyond what was seen whole, so it is offered for the
        # fiber unit only.
        # Kaplan-Meier 推定はファイバーを記述する。画像の中央値それ自体が全長を
        # 見た範囲より長い側にありうるため、fiber 単位でだけ使える。
        if frame_mode == FRAME_KAPLAN_MEIER and unit != UNIT_FIBER:
            self.ui_queue.put(("fatal", {
                "text": _("{km} は {fiber} 集計でだけ使えます。集計単位を {fiber} に"
                          "するか、枠の扱いを変えてください。").format(
                              km=FRAME_KAPLAN_MEIER, fiber=UNIT_FIBER),
                "trace": "",
            }))
            return

        # The pixel combination pools skeleton pixels without individuating
        # fibers, so it cannot count "N fibers"; it is also the only
        # combination that runs on a bundle with no recorded scan size,
        # because heights do not depend on the pixel size.
        # 画素の組み合わせはスケルトン画素を個体に分けずまとめるため "N fibers" を
        # 数えられない。また、高さがサンプリング間隔（nm/px）に依存しないことから、走査範囲が
        # 未記録のバンドルでも動く唯一の組み合わせでもある。
        pixel_mode = param == PARAM_HEIGHT and unit == UNIT_PIXEL
        counts_fibers = not pixel_mode
        weighted = frame_weighted and unit == UNIT_FIBER
        # The frame weights do not measure the sample, so the sample size
        # reported is the number of fibers measured.
        # 枠の重みは標本の量を表さないため、報告する標本量は計測したファイバーの
        # 本数とする。
        counted_by_fiber = frame_weighted

        results = []
        errors = []
        # X pixel size of every bundle measured for curvature, to warn when the
        # compared bundles differ in it (`_log_pixel_size_spread`).
        # 曲率を計測した全バンドルの X のサンプリング間隔（nm/px）。比較するバンドルで違うときに
        # 警告するために集める（`_log_pixel_size_spread`）。
        curvature_pixel_sizes: list = []
        # Scan size of every bundle whose lengths carry no frame correction, per
        # group, to warn when the compared bundles differ in it
        # (`_scan_size_spread_note`).
        # 長さに枠の補正をかけない全バンドルの走査範囲をグループごとに集める。比較する
        # バンドルで違うときに警告するため（`_scan_size_spread_note`）。
        uncorrected_lengths = (
            param == PARAM_LENGTH
            and frame_mode in (FRAME_INCLUDE, FRAME_EXCLUDE)
        )
        frame_scan_sizes: dict = {}
        # What each group's kink counts depend on (`_kink_condition_report`).
        # 各グループのキンク数が依存する条件（`_kink_condition_report`）。
        kink_quantity = param == PARAM_KINK_DENSITY
        kink_conditions: dict = {}
        # Centerline of every bundle measured (`_centerline_note`).
        # 計測した全バンドルの中心線（`_centerline_note`）。
        analyzed_lines: set = set()

        # A registered file can have been moved or deleted since it was added.
        # Each group is measured on the files that are on the disk now, and
        # every missing one is named in the notices of the run.
        # 登録したファイルは、追加した後で移動や削除をされていることがある。各
        # グループは今ディスクにあるファイルで計測し、見つからないファイルは実行の
        # 注意としてすべて挙げる。
        group_files = {}
        for grp in groups:
            present = []
            for path in grp["files"]:
                if os.path.isfile(path):
                    present.append(path)
                else:
                    errors.append(_("[{grp}] ファイルが見つかりません: {path}").format(
                        grp=grp["name"], path=path))
            group_files[grp["id"]] = present

        # Two analyses of the same scan lines pooled into one group count every
        # fiber of the overlap twice, so such a group is refused before anything
        # is measured (`_overlapping_inputs`).
        # 同じ走査線の解析を 2 つ 1 つのグループにまとめると、重なった部分の繊維を
        # すべて二度数える。そのため、何かを計測する前にそのグループを拒否する
        # （`_overlapping_inputs`）。
        for grp in groups:
            overlaps, by_name = self._overlapping_inputs(group_files[grp["id"]])
            if overlaps:
                shown = overlaps[:10]
                listed = "\n".join(
                    "{a} / {b}".format(
                        a=os.path.join(os.path.basename(os.path.dirname(a)),
                                       os.path.basename(a)),
                        b=os.path.join(os.path.basename(os.path.dirname(b)),
                                       os.path.basename(b)),
                    )
                    for a, b in shown
                )
                if len(overlaps) > len(shown):
                    listed += "\n" + _("ほか {n} 組").format(
                        n=len(overlaps) - len(shown))
                self.ui_queue.put(("fatal", {
                    "text": _(
                        "グループ「{grp}」に、同じ入力ファイルの同じ走査線を解析した"
                        "結果が複数あります。重なった部分の繊維を二度数えるため、"
                        "集計しません。次の各組のどちらかをグループから外してください。"
                        "\n{pairs}"
                    ).format(grp=grp["name"], pairs=listed),
                    "trace": "",
                }))
                return
            if by_name:
                self.ui_queue.put(("log", _(
                    "[{grp}] {n} 件の入力には元の入力ファイルの記録が無いため、同じ"
                    "走査線の解析が重なっていないかはファイル名だけで確かめました。"
                ).format(grp=grp["name"], n=by_name)))

        all_bundles = [path for grp in groups for path in group_files[grp["id"]]]
        # Measurements of bundles no longer registered are dropped, so the kept
        # fibers stay bounded by what is compared.
        # 登録から外れたバンドルの計測は捨て、保持する量を比べる対象に限る。
        registered = {os.path.abspath(path) for path in all_bundles}
        for key in [k for k in self._measure_cache if k[0] not in registered]:
            del self._measure_cache[key]
        for grp in groups:
            grp_name = grp["name"]
            # Every bundle of the group is measured together, so the
            # Kaplan-Meier estimate is made once over the whole group.
            # グループの全バンドルをまとめて計測する。そのため Kaplan-Meier 推定は
            # グループ全体で 1 回になる。
            bundle_paths = group_files[grp["id"]]
            if not bundle_paths:
                errors.append(
                    _("[{grp}] 計測できるファイルがありません").format(grp=grp_name)
                )
                continue
            # Skeleton-pixel heights measure no fiber length, so the shortest
            # length a bundle keeps does not matter to them.
            # スケルトン画素の高さはファイバーの長さを測らないため、バンドルが残す
            # 最短の長さは関係しない。
            if not pixel_mode:
                self._warn_group_length_floors(grp_name, bundle_paths)

            # Loading and measurement are delegated to afm_nanofiber_analyzer.measure, the same
            # code path as `cli.py heights` / `cli.py measure`. Per-bundle
            # errors come back as fixed English strings and are wrapped in
            # translated group context here.
            # 読み込みと計測は `cli.py heights` / `cli.py measure` と同一経路の
            # afm_nanofiber_analyzer.measure へ委譲する。バンドルごとのエラーは固定英語文字列で返り、
            # ここで翻訳済みのグループ文脈を付けて表示する。
            # Every path but the skeleton-pixel heights traces fibers, which
            # is too slow to leave the log silent while it runs.
            # スケルトン画素の高さ以外の経路はすべてファイバー追跡を行い、実行中に
            # ログを無音にしてよいほど速くはない。
            self.ui_queue.put(("log", _(
                "[{grp}] {n} バンドルを計測中..."
            ).format(grp=grp_name, n=len(bundle_paths))))

            # Say how many bundles actually carry a saved connection. A bundle
            # without the sidecar is measured as fragments, and the difference
            # is otherwise invisible in the result.
            # 実際に保存済みの連結を持つバンドルが何個あるかを報告する。サイドカーの
            # 無いバンドルは骨格断片として計測されるが、その差は結果からは見えない
            # ためである。
            if apply_connection:
                n_conn = self._count_connected_bundles(bundle_paths)
                msg = _("[{grp}] 連結を適用: {n}/{total} バンドル")
                if n_conn < len(bundle_paths):
                    msg += _("（残りは骨格断片のまま集計）")
                self.ui_queue.put(("log", msg.format(
                    grp=grp_name, n=n_conn, total=len(bundle_paths),
                )))

            # Say how many bundles were analyzed before format 1.1. They are
            # measured along the skeleton track rather than the centerline, on
            # a skeleton traced as stored that can still hold the loops and
            # spurs the current analysis removes, and a group mixing them with
            # current bundles is otherwise invisible in the result.
            # 形式 1.1 より前に解析したバンドルが何個あるかを報告する。それらは
            # 中心線ではなくスケルトントラックに沿って、保存されたとおりに追跡した
            # スケルトンで計測され、そのスケルトンには現在の解析が取り除く小ループや
            # 短い枝が残っていることがある。現在のバンドルと混ざったグループは結果
            # からは見分けがつかないためである。
            by_line = self._count_bundles_by_line(bundle_paths)
            analyzed_lines.update(by_line)
            n_old = by_line.get(SKELETON_TRACK, 0)
            if n_old:
                self.ui_queue.put(("log", _(
                    "[{grp}] {n}/{total} バンドルは旧版（形式 1.0）で"
                    "解析されています。保存されたスケルトンをそのまま追跡して"
                    "スケルトンに沿って計測するため、現在の解析が取り除く小ループや"
                    "行き止まりの短い枝でファイバーが分断されていることがあります。"
                    "GUI01 で再解析してください"
                ).format(
                    grp=grp_name, n=n_old, total=len(bundle_paths),
                )))
            # Name the lines whenever one is not the default: every length,
            # height and kink depends on the line, so groups analyzed on
            # different lines differ for that reason alone.
            # 既定以外の線が 1 つでもあれば線の名前を示す。長さ・高さ・キンクは
            # すべて線に依存するため、別の線で解析した群どうしはそれだけで違いが出る。
            chosen = {k: v for k, v in by_line.items() if k != SKELETON_TRACK}
            if set(chosen) - {DEFAULT_CENTERLINE_METHOD}:
                self.ui_queue.put(("log", _(
                    "[{grp}] 中心線: {lines}"
                ).format(
                    grp=grp_name,
                    lines=", ".join(
                        f"{k} {v}/{len(bundle_paths)}"
                        for k, v in sorted(chosen.items())),
                )))

            if param == PARAM_CURVATURE:
                curvature_pixel_sizes.extend(
                    self._bundle_pixel_sizes(bundle_paths))

            if pixel_mode:
                self._log_group_pixel_size_spread(
                    grp_name, self._bundle_pixel_sizes(bundle_paths))

            if uncorrected_lengths:
                frame_scan_sizes[grp_name] = self._bundle_scan_sizes(bundle_paths)

            if kink_quantity:
                kink_conditions[grp_name] = self._bundle_kink_conditions(
                    bundle_paths)

            frame_report = {}
            curation_report: list = []
            try:
                (grp_values, grp_weights, n_fibers, grp_images,
                 load_errors) = self._collect_bundle_values(
                    bundle_paths, param, unit,
                    apply_exclusions=apply_exclusions,
                    apply_connection=apply_connection,
                    curvature_window=curvature_window,
                    frame_mode=frame_mode,
                    frame_report=frame_report,
                    curation_report=curation_report,
                    group_name=grp_name,
                )
            except Exception as e:
                errors.append(
                    _("[{grp}] {param} の抽出に失敗: {err}").format(
                        grp=grp_name, param=param, err=e
                    )
                )
                continue
            if not weighted:
                grp_weights = None
            grp_fibers = n_fibers if counts_fibers else None

            # Say how many traced fibers the manual exclusions removed. The
            # collectors return only what survived, so a population reduced by
            # hand is otherwise indistinguishable from one the analysis
            # produced.
            # 手動除外で追跡済みファイバーが何本外れたかを示す。コレクタは残った
            # ものしか返さないため、これが無いと手で減らした母集団が解析の出力と
            # 見分けられない。
            if apply_exclusions and curation_report:
                traced = sum(row[1] for row in curation_report)
                kept = sum(row[2] for row in curation_report)
                # Skeleton-pixel heights trace nothing: their counts are the
                # pieces of skeleton left once the branch points are cleared.
                # スケルトン画素の高さは何も追跡しない。その件数は、分岐点を
                # 消した後に残るスケルトンの断片の数である。
                if pixel_mode:
                    msg = _(
                        "[{grp}] 手動除外を適用: スケルトンの断片 {total} 個の"
                        "うち {n} 個を除外しました"
                    )
                else:
                    msg = _(
                        "[{grp}] 手動除外を適用: 追跡した {total} 本の"
                        "うち {n} 本を除外しました"
                    )
                self.ui_queue.put(("log", msg.format(
                    grp=grp_name, total=traced, n=traced - kept,
                )))

            # Say what the frame mode removed, and how many of the lengths
            # that remain are still lower bounds because a crossing cut them:
            # the frame correction does not model those. Under Kaplan-Meier,
            # say instead which fibers the estimate used and how much of the
            # distribution it could not place.
            # Kaplan-Meier では代わりに、推定がどのファイバーを使い、分布の
            # どれだけを置けなかったかを示す。
            # 枠の扱いが何を外したか、また残った長さのうち交差で切れて依然
            # 下限値であるものが何本あるかを示す。枠の補正はそれらを扱わない。
            # The group's Kaplan-Meier estimate: the fibers it places beyond
            # the longest fiber seen whole and that length
            # (`_kaplan_meier_bounds`), and every fiber it read
            # (`_kaplan_meier_interval`).
            # グループの Kaplan-Meier 推定。全長を見た最長のファイバーより長い側に
            # 置く本数とその長さ（`_kaplan_meier_bounds`）、および推定が読んだ
            # 全ファイバー（`_kaplan_meier_interval`）。
            grp_km_beyond = 0.0
            grp_km_longest = float("nan")
            grp_km_estimates = []
            grp_km_samples = []
            # Under `FRAME_INCLUDE`: fibers judged, those that reach the frame,
            # and those with an end cut elsewhere.
            # `FRAME_INCLUDE` のとき、判定した本数、枠に達した本数、それ以外で切れた
            # 端を持つ本数。
            grp_frame_total = 0
            grp_frame_touching = 0
            grp_frame_cut = 0
            if frame_report.get("kaplan_meier"):
                grp_km_beyond = frame_report["beyond"]
                grp_km_longest = frame_report["longest_nm"]
                grp_km_estimates.append(
                    (frame_report["longest_nm"], frame_report["beyond"]))
                grp_km_samples.append(
                    (frame_report["lengths_nm"], frame_report["own_ends"]))
            if frame_report and frame_mode == FRAME_INCLUDE:
                grp_frame_total = frame_report["total"]
                grp_frame_touching = frame_report["frame"]
                grp_frame_cut = frame_report["lower_bound"]
                for skipped in frame_report["unrecorded"]:
                    self.ui_queue.put(("log", _(
                        "[{grp}] {name}: 枠の判定が記録されていないため、"
                        "枠に達した本数に数えていません"
                    ).format(
                        grp=grp_name, name=os.path.basename(skipped),
                    )))
            elif frame_report:
                for skipped in frame_report["unrecorded"]:
                    self.ui_queue.put(("log", _(
                        "[{grp}] {name}: 枠の判定が記録されていない"
                        "ため、長さの集計から外しました"
                    ).format(
                        grp=grp_name, name=os.path.basename(skipped),
                    )))
                if frame_report.get("kaplan_meier"):
                    self.ui_queue.put(("log", _(
                        "[{grp}] 長さ ({km}): {total} 本のうち、両端とも"
                        "自身の端である {whole} 本で分布を推定し、片端が切れた {cut} 本を"
                        "打ち切りとして使いました。両端とも切れているか枠にかかる {none} 本は"
                        "使っていません。全長を見たうち最長のファイバー ({longest:.0f} nm) より"
                        "長い側にある {share:.0%} は、推定できません"
                    ).format(
                        grp=grp_name, km=FRAME_KAPLAN_MEIER,
                        total=frame_report["total"],
                        whole=frame_report["complete"],
                        cut=frame_report["censored"],
                        none=frame_report["no_own_end"],
                        longest=frame_report["longest_nm"],
                        share=frame_report["unassigned"],
                    )))
                else:
                    self.ui_queue.put(("log", _(
                        "[{grp}] 長さ: 枠に達したファイバー {n}/{total} 本を"
                        "除外しました。残りのうち {k} 本は交差などで切れた端を持ち、"
                        "長さは下限値です"
                    ).format(
                        grp=grp_name,
                        n=frame_report["frame"], total=frame_report["total"],
                        k=frame_report["lower_bound"],
                    )))

            for failed_path, msg in load_errors:
                base = os.path.basename(failed_path)
                if base.endswith(BUNDLE_EXT):
                    base = base[:-len(BUNDLE_EXT)]
                errors.append(
                    _("[{grp}] 読込失敗: {base} ({err})").format(
                        grp=grp_name, base=base, err=msg
                    )
                )

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
            kaplan_meier = frame_mode == FRAME_KAPLAN_MEIER and wts is not None
            stats = (_kaplan_meier_summary(arr, wts, grp_km_estimates) if kaplan_meier
                     else _summary_stats(arr, wts))
            km_interval = (_kaplan_meier_interval(grp_km_samples) if kaplan_meier
                           else {})
            if km_interval:
                # The quartiles' 95 % resampling interval, which covers the
                # sampling of the fibers as well as where the estimate's
                # unplaced share lies.
                # 四分位数の 95 % リサンプリング区間。推定の置けなかった分の位置に
                # 加えて、ファイバーの標本抽出によるばらつきも含む。
                self.ui_queue.put(("log", _(
                    "[{grp}] 長さ ({km}): ファイバーを {n} 回"
                    "リサンプリングした 95 % 区間は、第 1 四分位数 {q1}、中央値 {md}、"
                    "第 3 四分位数 {q3} nm です"
                ).format(
                    grp=grp_name, km=FRAME_KAPLAN_MEIER, n=KM_RESAMPLES,
                    q1=_range_text(km_interval["q1"], "{0:.1f}"),
                    md=_range_text(km_interval["median"], "{0:.1f}"),
                    q3=_range_text(km_interval["q3"], "{0:.1f}"),
                )))
            results.append({
                "id": grp["id"],
                "name": grp_name,
                "color": grp["color"],
                "values": arr,
                "weights": wts,
                "mean": stats["mean"],
                "std": stats["std"],
                "std_definition": stats["std_definition"],
                "median": stats["median"],
                "q1": stats["q1"],
                "q3": stats["q3"],
                # Under Kaplan-Meier, the range a quartile lies in when the
                # estimate's unplaced share leaves it undetermined
                # (`_kaplan_meier_bounds`), and the 95 % resampling interval
                # (`_kaplan_meier_interval`).
                # Kaplan-Meier で、推定の置けなかった分によって値が定まらない
                # 四分位数の範囲（`_kaplan_meier_bounds`）と、95 % リサンプリング
                # 区間（`_kaplan_meier_interval`）。
                "quantile_bounds": stats.get("bounds", {}),
                "km_interval": km_interval,
                # The reported sample size is the number of samples measured.
                # No weight measures it: the total of the Miles-Lantuejoul
                # weight is an estimated fiber count, not what was observed.
                # 報告する標本量は計測した標本の数。重みはこれを表さない。
                # Miles-Lantuejoul 重みの合計は観測した本数ではなく推定本数であるため。
                "n_samples": float(arr.size),
                # Total weight, which is what the histogram bars sum to and so
                # what the out-of-range share is taken against.
                # 重みの合計。ヒストグラムの棒の総和であり、範囲外の割合はこれに
                # 対して取る。
                "weight_total": (
                    float(arr.size) if wts is None else float(wts.sum())
                ),
                "frame_mode": frame_mode,
                # What the Kaplan-Meier estimate could not place: the fibers
                # beyond the longest one seen whole, and that length.
                # Kaplan-Meier 推定が置けなかったもの。全長を見た最長のファイバー
                # より長い側の本数と、その長さ。
                "km_beyond": grp_km_beyond if kaplan_meier else 0.0,
                "km_longest_nm": grp_km_longest,
                # Share of the fibers aggregated under `FRAME_INCLUDE` whose
                # length the frame cut, which is what the mode leaves in.
                # `FRAME_INCLUDE` で集計したファイバーのうち、枠で長さが切れたものの
                # 割合。このモードが分布に残すものである。
                "frame_share": (
                    grp_frame_touching / grp_frame_total if grp_frame_total
                    else None
                ),
                # The scale the group's kinks were judged at, shown beside the
                # kink statistics so a difference in it can be seen.
                # そのグループのキンクを判定した尺度。差が見えるよう、キンクの統計値の
                # 隣に示す。
                "width_nm": _median_width_nm(kink_conditions.get(grp_name, [])),
                # The raw point count drives the "too few samples to read the
                # shape" notice, which is about the histogram, not the weight.
                # 「形状が読めるほど標本が無い」通知は生の点数で判断する。これは
                # 重みではなくヒストグラムについての話であるため。
                "n_raw": int(arr.size),
                "n_fibers": grp_fibers,
                "n_images": grp_images,
                # Kish's effective sample size of the Miles-Lantuejoul weights:
                # the weights are unbounded, so a few fibers whose box nearly
                # fills the frame can carry most of the weighted sample.
                # Miles-Lantuejoul 重みの Kish の有効標本数。重みには上限が無く、
                # 外接矩形が枠をほぼ埋める少数のファイバーが重み付き標本の大半を
                # 担いうるためである。
                "n_effective": (
                    float(wts.sum() ** 2 / np.sum(wts ** 2))
                    if frame_weighted and wts is not None and wts.size else None
                ),
                "max_weight_share": (
                    float(wts.max() / wts.sum())
                    if frame_weighted and wts is not None and wts.size else None
                ),
            })
            if results[-1]["n_effective"] is not None:
                self.ui_queue.put(("log", _(
                    "[{g}] {mode} 重みの有効標本数は {neff:.1f} 本（計測した {n} 本）で、"
                    "最大の重みを持つ 1 本が重みの合計の {share:.0%} を占めます。"
                ).format(g=grp_name, mode=frame_mode, neff=results[-1]["n_effective"],
                         n=int(arr.size), share=results[-1]["max_weight_share"])))
            if results[-1]["frame_share"] is not None:
                self.ui_queue.put(("log", _(
                    "[{g}] 長さ: {total} 本のうち {n} 本 ({share:.0%}) が枠に達し、"
                    "ほかに {k} 本が交差などで切れた端を持ちます。どちらの長さも下限値です。"
                ).format(g=grp_name, total=grp_frame_total, n=grp_frame_touching,
                         share=results[-1]["frame_share"], k=grp_frame_cut)))

        self._log_pixel_size_spread(curvature_pixel_sizes)
        for text in _kink_condition_report(kink_conditions):
            self.ui_queue.put(("log", text))
        centerline_note = _centerline_note(analyzed_lines)
        if centerline_note:
            self.ui_queue.put(("log", centerline_note))
        for r in results:
            if r["width_nm"] is not None:
                self.ui_queue.put(("log", _(
                    "[{g}] キンクを判定した尺度: 見かけの幅の中央値 {w:.1f} nm"
                ).format(g=r["name"], w=r["width_nm"])))
            noises = [c["noise_nm"] for c in kink_conditions.get(r["name"], [])
                      if c.get("noise_nm") is not None]
            if noises:
                self.ui_queue.put(("log", _(
                    "[{g}] 背景の画素ノイズの中央値: {n:.3f} nm"
                ).format(g=r["name"], n=float(np.median(noises)))))
        scan_size_note = _scan_size_spread_note(frame_scan_sizes, frame_mode)
        if scan_size_note:
            self.ui_queue.put(("log", scan_size_note))

        if not results:
            self.ui_queue.put(("fatal", {
                "text": _("どのグループからも {param} のデータを得られませんでした。"
                          "ログを確認してください。").format(param=param),
                "trace": "",
            }))
            return

        try:
            edges = _histogram_edges(min_h, max_h, step)
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

        errors.extend(_bin_results(results, edges, counted_by_fiber))
        for r in results:
            # Kept for re-binning when only the histogram range changes
            # (`App._rebin_last_results`).
            # ヒストグラムの範囲だけが変わったときにビンを数え直すために保持する
            # （`App._rebin_last_results`）。
            r["counted_by_fiber"] = counted_by_fiber

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
                "{fiber} か {image} の集計に切り替えてください。"
            ).format(unit=unit, fiber=UNIT_FIBER, image=UNIT_IMAGE)
        elif frame_weighted and unit == UNIT_FIBER:
            # Mann-Whitney U and KS take no weights, and a weighted
            # Mann-Whitney has no standard form, so a corrected fiber sample is
            # described but not tested. An image sample is that scan's
            # weighted median, one unweighted value, so the image unit is
            # tested with the correction in place. The note does not point at
            # `exclude`, which can be tested only by dropping the correction
            # for the bias it introduces.
            # Mann-Whitney U と KS は重みを受け付けず、重み付き Mann-Whitney
            # には標準的な形が無い。そのため補正したファイバー標本は記述するが検定
            # しない。画像の標本はその画像の重み付き中央値という重みのない 1 値
            # なので、image 単位は補正したまま検定する。注記で `exclude` を案内
            # しないのは、それが生む偏りの補正を捨てることになるためである。
            if frame_mode == FRAME_KAPLAN_MEIER:
                comparison_note = _(
                    "{km} の標本は重み付きのため検定しません。枠で切れた長さを"
                    "補正して検定するには、枠の扱いを {ml} に、集計単位を {image} に"
                    "してください。{ml} は交差で切れた長さを補正しません。"
                ).format(km=FRAME_KAPLAN_MEIER, ml=FRAME_MILES_LANTUEJOUL,
                         image=UNIT_IMAGE)
            else:
                comparison_note = _(
                    "{fiber} 集計の {ml} 補正の標本は重み付きのため検定しません。"
                    "補正したまま検定するには {image} の集計に切り替えて"
                    "ください。各画像の重み付き中央値を検定します。"
                ).format(fiber=UNIT_FIBER, ml=FRAME_MILES_LANTUEJOUL,
                         image=UNIT_IMAGE)
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

        # Every group of one run shares the weighting, so the first names the
        # standard deviation the whole column holds.
        # 1 回の実行の全グループは重み付けを共有するため、先頭の結果が列全体の
        # 標準偏差の定義を表す。
        std_definition = (
            results[0].get("std_definition", STD_SAMPLE) if results
            else STD_SAMPLE
        )
        for col, text in self._result_headings(param, std_definition).items():
            self.result_tree.heading(col, text=text)
        self._update_result_caption(param, unit)
        self._last_comparisons = payload["comparisons"]
        self._populate_comparison_table(
            payload["comparisons"], payload["comparison_note"], unit,
            frame_note=_frame_bias_note(
                param, payload["results"][0].get("frame_mode", FRAME_INCLUDE)),
        )

        self._fill_result_table(results, unit)

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
        self.stale_var.set("")
        self.btn_save_fig.configure(state=tk.NORMAL)
        self.btn_save_csv.configure(state=tk.NORMAL)
        self.btn_save_stats.configure(state=tk.NORMAL)
        self.btn_stats.configure(state=tk.NORMAL)

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

    def _rebin_last_results(self) -> None:
        """
        Re-bin the collected samples at the current histogram range and redraw.
        集めた標本を現在のヒストグラム範囲でビンに数え直し、再描画する。

        Notes
        -----
        The range and step set only the bins, the mode and the share outside
        the range (`_bin_results`); the samples, the summary statistics and
        the between-group tests do not depend on them, so the bundles are not
        measured again.
        範囲と step が決めるのは、ビン・最頻値・範囲外の割合だけである
        （`_bin_results`）。標本・要約統計量・群間検定はこれらに依存しないため、
        バンドルを計測し直さない。
        """
        if not self._last_results:
            return
        try:
            edges = _histogram_edges(self.min_h, self.max_h, self.step)
        except Exception:
            # The entries enforce only min < max and step > 0, so a wide range
            # with a fine step can still run out of memory here.
            # 入力が保証するのは min < max と step > 0 だけなので、広い範囲に
            # 細かい step を与えるとここでメモリ不足になりうる。
            messagebox.showerror(_("エラー"), _("ヒストグラム範囲の準備に失敗しました。"))
            return
        results = self._last_results
        notes = _bin_results(
            results, edges, bool(results[0].get("counted_by_fiber", False)))
        self._last_edges = edges
        self._fill_result_table(results, self._last_unit)
        self._redraw_from_last_results()
        for note in notes:
            self._log(f"- {note}")

    def _fill_result_table(self, results: list, unit: str) -> None:
        """
        Fill the per-group result table from the results of one run.
        1 回の実行の結果から、グループごとの結果表を埋める。
        """
        for iid in self.result_tree.get_children(""):
            self.result_tree.delete(iid)
        for r in results:
            mode_str = f"{r['mode']:.3f}" if not np.isnan(r["mode"]) else "-"
            self.result_tree.insert(
                "", tk.END,
                values=(
                    r["name"],
                    _quantile_text(r, "median", "{0:.3f}"),
                    # A quartile given as a range reads poorly joined by a dash.
                    # 範囲で示した四分位数はダッシュでつなぐと読みにくい。
                    _quantile_text(r, "q1", "{0:.3f}")
                    + ("–" if np.isfinite(r["q1"]) and np.isfinite(r["q3"]) else " to ")
                    + _quantile_text(r, "q3", "{0:.3f}"),
                    _blank_if_nan(r["mean"], "{0:.3f}") or "-",
                    _blank_if_nan(r["std"], "{0:.3f}") or "-",
                    mode_str,
                    _format_sample_size(r["n_samples"], unit),
                    "-" if r["n_fibers"] is None else f"{r['n_fibers']:,}",
                    f"{r['n_images']:,}",
                    "-" if r.get("width_nm") is None else f"{r['width_nm']:.1f}",
                ),
            )
        # The width column takes room from the plot, so it shows only beside
        # the kink quantities it explains.
        # 幅の列はプロットの領域を削るため、説明する相手であるキンクの量のときだけ出す。
        self._show_width_column(any(r.get("width_nm") is not None for r in results))

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

    def _populate_comparison_table(self, comparisons, note: str,
                                   unit: str = None,
                                   frame_note: str = "") -> None:
        """
        Fill the between-group comparison table and its note.
        群間比較テーブルと注記を埋める。

        Parameters
        ----------
        comparisons
            `afm_nanofiber_analyzer.group_compare.PairComparison` rows, possibly empty.
            `afm_nanofiber_analyzer.group_compare.PairComparison` の行。空の場合もある。
        note
            Explanation shown when no comparison was run.
            比較を実行しなかった場合に表示する説明。
        unit
            Aggregation unit the samples were tested at, which selects the
            caveat under the table (`_comparison_caveat`).
            検定した標本の集計単位。表の下の注意書きを選ぶ（`_comparison_caveat`）。
        frame_note
            What the frame mode leaves in the comparison (`_frame_bias_note`),
            shown under the table when a test ran.
            枠の扱いが比較に残すもの（`_frame_bias_note`）。検定したとき表の下に出す。

        Notes
        -----
        The adjusted p-values are the ones shown, with the raw value beside
        them, because every pair of k groups is tested at once, and testing
        each pair at 0.05 on its own finds a difference somewhere more often
        than 5% of the time when there is none.
        表示するのは補正後の p 値で、生の値は併記する。k 群のすべてのペアを同時に
        検定しており、各ペアを単独に 0.05 で検定すると、差が無くてもどこかに差が
        見つかる確率は 5% を超えるためである。
        """
        for iid in self.comparison_tree.get_children(""):
            self.comparison_tree.delete(iid)

        self.btn_save_comparison.configure(
            state=tk.NORMAL if comparisons else tk.DISABLED
        )
        if not comparisons:
            # These notes say how to reach a test, which is longer than the
            # one-line header can show, so they go in the field under the table.
            # これらの注記は検定に至る方法を述べており、1 行の見出しには収まらない
            # ため、表の下の欄に出す。
            self.comparison_note_var.set("")
            self._set_comparison_caveat(note)
            return

        self.comparison_note_var.set(
            _("主検定 Mann-Whitney は Holm 補正後（括弧内は補正前）。KS は補正なしの参考値")
            if len(comparisons) > 1
            else _("主検定は Mann-Whitney（2 群のため補正不要）。KS は参考値")
        )
        self._set_comparison_caveat("\n".join(
            text for text in (_primary_test_note(),
                              frame_note,
                              _comparison_caveat(unit),
                              _attainable_p_note(comparisons))
            if text
        ))
        for c in comparisons:
            if len(comparisons) > 1:
                u_text = "{adj} ({raw})".format(
                    adj=self._format_p(c.mannwhitney_p_adjusted),
                    raw=self._format_p(c.mannwhitney_p),
                )
            else:
                u_text = self._format_p(c.mannwhitney_p)
            # Uncorrected: the correction covers the primary test, and a value
            # labelled as a reference is not what a conclusion rests on.
            # 補正しない。補正の対象は主検定であり、参考値と表示した値は結論の根拠に
            # ならない。
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
            # Under Kaplan-Meier the curve stops short of one by the part of
            # the distribution beyond the longest fiber seen whole.
            # Kaplan-Meier では、全長を見た最長のファイバーより長い側の分だけ、
            # 曲線は 1 に届かずに終わる。
            cumulative = np.cumsum(weights) / (
                float(weights.sum()) + r.get("km_beyond", 0.0))
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
        positions = []
        # A Kaplan-Meier box whose quartiles the estimate leaves undetermined
        # cannot be drawn, so its place says where they lie instead.
        # 推定で四分位数が定まらない Kaplan-Meier の箱は描けないため、その位置に
        # 四分位数のある範囲を書く。
        unplaced = []
        for k, r in enumerate(results, start=1):
            if not all(np.isfinite(r[q]) for q in ("q1", "median", "q3")):
                unplaced.append((k, r))
                continue
            positions.append(k)
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

        if stats:
            drawn = [results[k - 1] for k in positions]
            artists = ax.bxp(stats, positions=positions, showfliers=False,
                             patch_artist=True)
            for patch, r in zip(artists["boxes"], drawn):
                patch.set_facecolor(r["color"])
                patch.set_alpha(0.55)
                patch.set_edgecolor(r["color"])
            for median in artists["medians"]:
                median.set_color("black")
        for k, r in unplaced:
            lines = ["box not estimated"] + [
                "{0} {1}".format(label, _quantile_text(r, key, "{0:.0f}"))
                for label, key in (("Q1", "q1"), ("median", "median"), ("Q3", "q3"))
                if not np.isfinite(r[key])
            ]
            ax.text(k, 0.5, "\n".join(lines), transform=ax.get_xaxis_transform(),
                    ha="center", va="center", fontsize=tick_fs, color=r["color"])
        ax.set_xticks(range(1, len(results) + 1))
        ax.set_xticklabels([r["name"] for r in results])
        ax.set_xlim(0.5, len(results) + 0.5)

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
            # A group of one sample has no standard deviation, so its mean is
            # written alone rather than as "± nan".
            # 標本 1 個の群には標準偏差が無いため、"± nan" ではなく平均だけを書く。
            # Under Kaplan-Meier with part of the distribution unplaced the
            # mean is not defined, so the line says so instead of a number.
            # Kaplan-Meier で分布の一部を置けなかったときは平均が定まらないため、
            # 数値の代わりにそう書く。
            if not np.isfinite(r["mean"]):
                mean_line = "{p}: mean not estimated".format(p=param)
            elif np.isfinite(r["std"]):
                mean_line = "{p} = {m} ± {s} {u}".format(
                    p=param, m=f"{r['mean']:.2f}", s=f"{r['std']:.2f}",
                    u=value_unit,
                )
            else:
                mean_line = "{p} = {m} {u}".format(
                    p=param, m=f"{r['mean']:.2f}", u=value_unit,
                )
            lines = [
                mean_line,
                "median {eq}{md} {u} (IQR {q1} to {q3})".format(
                    eq="= " if np.isfinite(r["median"]) else "",
                    md=_quantile_text(r, "median", "{0:.2f}"), u=value_unit,
                    q1=_quantile_text(r, "q1", "{0:.2f}"),
                    q3=_quantile_text(r, "q3", "{0:.2f}"),
                ) if not (np.isfinite(r["q1"]) and np.isfinite(r["q3"]))
                else "median = {md} {u} (IQR {q1}–{q3})".format(
                    md=_quantile_text(r, "median", "{0:.2f}"), u=value_unit,
                    q1=_quantile_text(r, "q1", "{0:.2f}"),
                    q3=_quantile_text(r, "q3", "{0:.2f}"),
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
            # A published length distribution has to say whether fibers cut
            # by the frame were in it, because that changes the numbers.
            # 論文に載る長さ分布は、枠で切れたファイバーを含むかを明示しなければ
            # ならない。それによって数値が変わるためである。
            frame_mode = r.get("frame_mode", FRAME_INCLUDE)
            if r.get("frame_share") is not None:
                lines.append("{0:.0%} of fibers reach the frame".format(
                    r["frame_share"]))
            if frame_mode == FRAME_EXCLUDE:
                lines.append("frame-touching fibers excluded")
            elif frame_mode == FRAME_MILES_LANTUEJOUL:
                # Two lines: as one, it is wider than the axes and is clipped.
                # 2 行にする。1 行では軸より広く、切れてしまう。
                lines.append("frame-touching fibers excluded")
                lines.append("Miles-Lantuejoul weighted")
                if r.get("n_effective") is not None:
                    lines.append("effective N = {0:.1f}".format(r["n_effective"]))
            elif frame_mode == FRAME_KAPLAN_MEIER:
                lines.append("Kaplan-Meier estimate")
                lines.append("(cut lengths censored)")
                if r.get("n_effective") is not None:
                    lines.append("effective N = {0:.1f}".format(r["n_effective"]))
                if r.get("km_beyond", 0.0) > 0.0:
                    share = r["km_beyond"] / (r["weight_total"] + r["km_beyond"])
                    # The share lies beyond the longest fiber the group saw
                    # whole; a group that saw none has no such length to name.
                    # この分は、グループが全長を見た最長のファイバーより先にある。
                    # 全長を見たファイバーが無いグループには、書ける長さが無い。
                    longest = r.get("km_longest_nm", float("nan"))
                    if np.isfinite(longest):
                        lines.append("{0:.0%} beyond {1:.0f} {2}".format(
                            share, longest, value_unit))
                        lines.append("not estimated")
                    else:
                        lines.append("{0:.0%} not estimated".format(share))

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
                y, ylabel = compute_y_and_label(r["counts"], r.get("norm_total", r["total"]))
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
                y, ylabel = compute_y_and_label(r["counts"], r.get("norm_total", r["total"]))
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
        self._set_comparison_caveat("")
        self._last_comparisons = []
        self.btn_save_comparison.configure(state=tk.DISABLED)

        self.btn_save_fig.configure(state=tk.DISABLED)
        self.btn_save_csv.configure(state=tk.DISABLED)
        self.btn_save_stats.configure(state=tk.DISABLED)
        self.btn_stats.configure(state=tk.DISABLED)
        self._last_results = None
        self._last_edges = None
        self._last_param = None
        self._last_unit = None
        self._has_result = False
        self.stale_var.set("")

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
                        # A weighted sample needs its weights exported too.
                        # Without them the file recomputes an unweighted
                        # distribution and silently disagrees with the figure
                        # and the statistics it came from.
                        # 重み付きの標本は重みも併せて出力する必要がある。重み
                        # が無いと、そのファイルからは重みなしの分布が再計算され、
                        # 元の図や統計値と黙って食い違ってしまう。
                        # The Miles-Lantuejoul and Kaplan-Meier weights are
                        # dimensionless.
                        # Miles-Lantuejoul 重みと Kaplan-Meier 重みは無次元である。
                        frame_weighted = (r.get("frame_mode")
                                          in WEIGHTED_FRAME_MODES)
                        value_column = (
                            "value_per_um" if self._last_param == PARAM_KINK_DENSITY
                            else "value_nm")
                        w.writerow([value_column,
                                    "weight" if frame_weighted else "weight_nm"])
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
        Mann-Whitney one is what a conclusion rests on, but the raw value is
        what another correction could be recomputed from, so dropping it would
        make the exported table impossible to re-analyze. The KS columns are
        kept for the same reason, although the window shows KS as a reference.
        生の p 値と Holm 補正後の p 値をどちらも書き出す。結論の根拠になるのは
        Mann-Whitney の補正後の値だが、別の補正法を計算し直せるのは生の値からである。
        落とすと出力した表を再解析できなくなる。KS の列も同じ理由で残す。画面では KS を
        参考値として示す。
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

        # The button is in the statistics window, so the dialog opens over it.
        # ボタンは統計ウィンドウにあるので、ダイアログはその上に開く。
        save_csv_with_dialog(
            self.stats_window,
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
                    # counts of what the "sample unit" column names.
                    # N samples は統計量の母体となる全標本量、N in range は
                    # 描画された棒に含まれる標本量。どちらも "sample unit" 列が
                    # 示すものの件数である。
                    "N samples",
                    "N in range",
                    "N fibers",
                    "N images",
                    # How contour length treated fibers reaching the frame;
                    # blank for the other quantities, which it never affects.
                    # 輪郭長で枠に達したファイバーをどう扱ったか。影響しない他の
                    # 計測量では空欄。
                    "frame-touching fibers",
                    # Whether std divides by n - 1 or by the total weight
                    # (`_summary_stats`), appended so earlier columns keep
                    # their positions.
                    # std を n - 1 で割ったか重みの合計で割ったか
                    # （`_summary_stats`）。既存の列位置を保つため末尾に足す。
                    "std definition",
                    # Under Kaplan-Meier, the percentage of fibers the estimate
                    # places beyond the longest fiber seen whole; a statistic
                    # that falls there is blank.
                    # Kaplan-Meier で、推定が全長を見た最長のファイバーより長い
                    # 側に置くファイバーの割合。そこに落ちる統計値は空欄になる。
                    "not estimated (%)",
                    # Under `include`, the percentage of fibers the frame cut.
                    # `include` で、枠で切れたファイバーの割合。
                    "reaching frame (%)",
                    # Under the kink quantities, the scale the kinks were judged at.
                    # キンクの量で、キンクを判定した尺度。
                    "median W (nm)",
                    # Under Kaplan-Meier, the range each quartile lies in when
                    # it is not determined (`_kaplan_meier_bounds`), and its
                    # 95 % resampling interval (`_kaplan_meier_interval`); an
                    # upper end that is not bounded reads "inf".
                    # Kaplan-Meier で、値が定まらない四分位数のある範囲
                    # （`_kaplan_meier_bounds`）と、その 95 % リサンプリング区間
                    # （`_kaplan_meier_interval`）。上が定まらなければ "inf"。
                    "Q1 lower bound", "Q1 upper bound",
                    "median lower bound", "median upper bound",
                    "Q3 lower bound", "Q3 upper bound",
                    "Q1 95% interval lower", "Q1 95% interval upper",
                    "median 95% interval lower", "median 95% interval upper",
                    "Q3 95% interval lower", "Q3 95% interval upper",
                ])
                for r in self._last_results:
                    mode_val = "" if np.isnan(r["mode"]) else f"{r['mode']:.3f}"
                    w.writerow([
                        r["name"],
                        self._last_param,
                        self._last_unit,
                        _blank_if_nan(r["median"], "{0:.3f}"),
                        _blank_if_nan(r["q1"], "{0:.3f}"),
                        _blank_if_nan(r["q3"], "{0:.3f}"),
                        _blank_if_nan(r["mean"], "{0:.3f}"),
                        _blank_if_nan(r["std"], "{0:.3f}"),
                        mode_val,
                        _sample_size_csv_value(r["n_samples"], self._last_unit),
                        _sample_size_csv_value(
                            r.get("n_in_range", r["total"]), self._last_unit),
                        "" if r["n_fibers"] is None else int(r["n_fibers"]),
                        int(r["n_images"]),
                        (r.get("frame_mode", FRAME_INCLUDE)
                         if self._last_param == PARAM_LENGTH else ""),
                        r.get("std_definition", STD_SAMPLE),
                        ("{0:.1f}".format(100.0 * r["km_beyond"] / (
                            r["weight_total"] + r["km_beyond"]))
                         if r.get("km_beyond", 0.0) > 0.0 else ""),
                        ("{0:.1f}".format(100.0 * r["frame_share"])
                         if r.get("frame_share") is not None else ""),
                        ("{0:.3f}".format(r["width_nm"])
                         if r.get("width_nm") is not None else ""),
                        *_range_csv_values(r.get("quantile_bounds", {})),
                        *_range_csv_values(r.get("km_interval", {})),
                    ])

        # The button is in the statistics window, so the dialog opens over it.
        # ボタンは統計ウィンドウにあるので、ダイアログはその上に開く。
        save_csv_with_dialog(
            self.stats_window,
            _write_stats,
            initial_dir=self._default_save_dir(),
            initial_name=default_name,
            title=_("統計値を保存"),
            log_cb=self._log,
            success_message=_("統計値を保存しました → {path}"),
            error_title=_("保存失敗"),
        )


class StatisticsWindow(tk.Toplevel):
    """
    Window holding the statistics table and the between-group comparison.
    統計値の表と群間比較を載せるウィンドウ。

    Attributes
    ----------
    body
        Frame the main window builds the two tables into.
        メインウィンドウが 2 つの表を構築する先のフレーム。

    Notes
    -----
    The window is created hidden and is hidden again, not destroyed, when it is
    closed, so the tables keep the latest result and reopening shows it. It is
    not tied to the main window's position, so it can sit beside the figure or
    on another monitor.
    ウィンドウは隠した状態で作り、閉じたときも破棄せずに隠す。そのため表は最新の
    結果を保ち、開き直せばそれが表示される。メインウィンドウの位置には結び付けない
    ので、図の横や別のモニターに置ける。
    """

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.withdraw()
        self.title(_("統計処理"))
        apply_window_size(self, 860, 520, min_w=560, min_h=360)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.body = ttk.Frame(self)
        self.body.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def show(self) -> None:
        """
        Show the window in front of the others and give it the focus.
        ウィンドウを他のウィンドウの手前に表示し、フォーカスを与える。
        """
        self.deiconify()
        self.lift()
        self.focus_set()


def main() -> None:
    """
    Launch the fiber morphology statistics GUI with any bundles named on the command line.
    繊維形態統計 GUI を起動し、コマンドラインで指定されたバンドルがあれば登録する。

    GUI01's "このフォルダをGUI03で解析" and GUI05's "GUI03で開く" hand their
    bundles over through a list file, and paths given as plain arguments are
    read the same way (`afm_nanofiber_analyzer.plugin_launch.read_path_arguments`). The bundles
    join the group the window starts with; without any the window opens with
    that group empty.
    GUI01 の「このフォルダをGUI03で解析」と GUI05 の「GUI03で開く」は、バンドルを
    一覧ファイルで渡す。パスをそのまま引数に書いた場合も同じ方法で読む
    （`afm_nanofiber_analyzer.plugin_launch.read_path_arguments`）。バンドルは起動時のグループに登録
    される。1 つも無ければ、そのグループが空のままウインドウが開く。
    """
    app = App()
    paths = read_path_arguments(sys.argv[1:])
    if paths:
        app.add_files(app.groups[0], paths)
    app.mainloop()


if __name__ == "__main__":
    main()
