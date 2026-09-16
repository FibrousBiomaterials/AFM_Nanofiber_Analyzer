# -*- coding: utf-8 -*-
"""
Fiber centerline placed on the height image: the half-maximum midpoint line.
高さ画像上に置く繊維の中心線（半値中点線）。

The skeleton decides which pixels form one fiber, in which order, and where a
fiber is cut at a crossing; this module decides where the fiber's line runs.
Each skeleton point is moved, along the normal of a smoothed copy of the track,
to the midpoint between the two points where the height cross-section falls to
half its maximum. The result has exactly one point per skeleton point, so an
index into the line is an index into the skeleton track. It is the line a
fiber is drawn along and measured along: length, curvature, straightness, kink
detection and the height profile all read it.
スケルトンは、どの画素が 1 本の繊維をなし、どの順に並び、交差でどこを切るかを
決める。本モジュールは、繊維の線がどこを通るかを決める。各スケルトン点を、
トラックの平滑化コピーの法線方向に、高さ断面が最大値の半分まで下がる 2 点の
中点へ移す。結果はスケルトン点ごとにちょうど 1 点を持つため、線のインデックスは
スケルトントラックのインデックスでもある。これが繊維を描画し計測する線であり、
長さ・曲率・直線度・キンク判定・高さプロファイルはすべてこの線を読む。

Notes
-----
Why not the skeleton itself. The skeleton is the medial axis of a thresholded
mask, so it runs midway between two mask boundaries rather than along the
fiber: where a neighbour, a junction skirt or background roughness widens the
mask on one side, the axis follows it, and the 8-connected pixel chain adds a
staircase on top. Below a Y junction on the bundled higher-plant TOC scan the
skeleton swung around a straight fiber and produced a 118 degree "kink" there.
On 60 synthetic scans with a known centerline (2 nm pixels, apparent width
8 px; corners, zigzags, corner pairs, arcs, meanders, crossings and
junctions) the median distance to the true centerline was 0.11 px for this
line against 0.29 px for the skeleton, and the 95th percentile 0.35 px
against 0.90 px.
なぜスケルトンそのものではないか。スケルトンはしきい値マスクの medial axis で
あり、繊維に沿うのではなく 2 本のマスク境界の中間を通る。近傍物・分岐部の裾・
背景の凹凸がマスクを片側に広げると軸はそれに従い、さらに 8 連結の画素鎖が
階段を上乗せする。同梱の高等植物 TOC スキャンの Y 字の下では、スケルトンが
まっすぐな繊維のまわりで振れ、そこに 118 度の「キンク」を生んだ。中心線が既知の
合成スキャン 60 枚（画素 2 nm、見かけ幅 8 px。コーナー・ジグザグ・コーナーの
2 連・円弧・蛇行・交差・分岐）では、真の中心線までの距離の中央値はこの線で
0.11 px、スケルトンで 0.29 px、95 パーセンタイルはそれぞれ 0.35 px と 0.90 px
であった。

Why the half-maximum midpoint and not the crest. The crest -- the highest
point of each cross-section -- is the estimator a twisted fiber displaces
most: a fibril with an anisotropic cross-section turns its tallest edge to
alternating sides as it twists, so the crest swings from one side of the axis
to the other. On synthetic twisted ribbons (rectangular sections of 4x2 to
16x3 nm on a straight axis) the crest left the axis 1.2-1.8 times as far as
the half-maximum midpoint (RMS). Lower levels sit closer to the axis still,
but on a thin, low fiber a quarter-height midpoint was pulled up to 3.8 nm
off by background bumps that the half-maximum level stays above. The
half-maximum is also the definition of the apparent width
(`measure_apparent_width`) every length in this module is scaled by.
なぜ頂点ではなく半値中点か。頂点（各断面の最高点）は、ねじれた繊維で最も大きく
ずれる推定量である。断面が異方性のフィブリルはねじれに伴って最も高い縁を交互の
側に向けるため、頂点は軸の片側から反対側へ振れる。合成のねじれリボン（直線軸上の
4×2〜16×3 nm の長方形断面）では、頂点は半値中点の 1.2〜1.8 倍（RMS）軸から
離れた。それより低いレベルはさらに軸に近いが、細く低い繊維では 1/4 高さの中点が
背景の凹凸に最大 3.8 nm 引かれた。半値のレベルはその凹凸より上にある。半値は、
本モジュールのすべての長さの尺度となる見かけ幅（`measure_apparent_width`）の
定義でもある。

With a blunt probe the displacement of a twisted fiber is in the image itself,
and every estimator moves with it; no line read from the height can recover
the axis there.
探針が太い場合、ねじれた繊維のずれは画像そのものに入っており、どの推定量も
一緒に動く。高さから読む線では、そこで軸を取り戻すことはできない。

This module depends only on NumPy, because `lib.fiber_connector`,
`lib.fiber_tracking_image` and `lib.kink_detector` all import it.
本モジュールの依存は NumPy のみとする。`lib.fiber_connector`・
`lib.fiber_tracking_image`・`lib.kink_detector` がいずれも import するため。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import Optional, Tuple, Union

# ===== Numerical / scientific libraries =====
import numpy as np
from numpy.typing import NDArray

# Which line a fiber is drawn and measured along: the values of
# `Fiber.centerline` and `FiberTrackingImage.centerline`. A bundle of format 1.0
# was analyzed on the skeleton track and keeps it until it is re-analyzed, so
# the stored kinks and the line they sit on never come from two different
# definitions (see `bundle_schema.centerline_from_meta`).
# 繊維を描画し計測する線の種類。`Fiber.centerline` と
# `FiberTrackingImage.centerline` の値。形式 1.0 のバンドルはスケルトントラック上で
# 解析されているため、再解析されるまでそれを使い続ける。こうすることで、保存済みの
# キンクとそれが載る線が異なる定義から来ることはない
# （`bundle_schema.centerline_from_meta` 参照）。
SKELETON_TRACK = "skeleton"
HALF_MAX_CENTERLINE = "half_max"

# Lateral half-range searched when measuring the apparent width, and the step
# the height profile is sampled at, both in pixels.
# 見かけ幅の測定時に探索する横方向の片側範囲と、高さプロファイルのサンプリング
# 間隔。いずれも画素単位。
_WIDTH_SEARCH_PX = 12.0
_WIDTH_STEP_PX = 0.25

# Half-window of track points the local tangent is taken over while measuring
# the width, so the sampled profile is perpendicular to the fiber rather than
# to one staircase step of the skeleton.
# 幅の測定中に局所接線を取るトラック点の片側窓幅。サンプリングするプロファイル
# がスケルトンの階段 1 段ではなく繊維に対して垂直になるようにする。
_WIDTH_TANGENT_HALF = 3

# Fallback apparent width, in pixels, when the height profile gives no usable
# half-maximum run (a flat or saturated neighbourhood). The bundled scans
# measure 7.5 to 10 px across, so this is their middle rather than an invented
# number. It is a pixel count, so a fiber placed with it is not scaled by its
# own width the way every other fiber is; `place_centerline` reports the
# substitution (`CenterlineResult.width_measured`) so the fiber can be flagged
# rather than measured as if its width were known.
# 高さプロファイルから使える半値区間が得られない場合（平坦または飽和した近傍）の
# 見かけ幅の代替値（画素）。同梱スキャンの実測幅は 7.5〜10 px であり、この値は
# 恣意的な数ではなくその中央にあたる。画素数なので、この値で線を置いた繊維は他の
# 繊維のように自身の幅で尺度付けされていない。`place_centerline` はその代用を
# 報告し（`CenterlineResult.width_measured`）、幅が既知であるかのように計測する
# のではなく、繊維に印を付けられるようにする。
FALLBACK_WIDTH_PX = 8.0

# Half-window, in apparent widths, on either side of a line point within which
# the crest height is read where the cross-section could not be resolved. A
# resolved section reports the maximum it climbed to; an interpolated point has
# no section of its own, so the height nearest its line is the best available.
# 断面を決められなかった点で頂点高さを読む、線の点の両側の片側窓幅（見かけ幅
# 単位）。決められた断面は登り着いた最大値を報告する。補間された点は自身の断面を
# 持たないため、その線に最も近い高さが得られる最善である。
_CREST_WINDOW_WIDTHS = 0.25

# Smoothing scale of the frame, in apparent widths: a smoothed copy of the
# track that supplies only the direction each point may move in and the base
# its lateral offset is measured from. No point is ever moved to the smoothed
# position itself, which is what rounded a real corner in the first prototype.
# A quarter width keeps two features one width apart from being averaged into
# one. The probe broadens every fiber to about a width, so that is roughly the
# closest two bends can be told apart at all; see `_OFFSET_SMOOTH_WIDTHS` for
# what half a width did.
# 枠の平滑化尺度（見かけ幅単位）。枠はトラックの平滑化コピーで、各点が動ける
# 方向と横方向オフセットの基準だけを与える。点そのものを平滑化位置へ動かすことは
# 決してない。最初の試作ではそれが本物のコーナーを丸めていた。1/4 幅にするのは、
# 1 幅離れた 2 つの特徴を 1 つに平均しないためである。探針はどの繊維も約 1 幅に
# 広げるため、2 つの折れを見分けられるのはおおよそその間隔までである。半幅で何が
# 起きたかは `_OFFSET_SMOOTH_WIDTHS` を参照。
_FRAME_SIGMA_WIDTHS = 0.25

# How far the section's maximum may lie from the frame, how far from that
# maximum each half-maximum crossing is searched for, and the widest
# cross-section still taken as one fiber, all in apparent widths. The width
# limit applies to the full width at half maximum, not to each half: AFM
# profiles are often asymmetric, one flank falling more slowly than the other,
# and requiring each half to stay within 0.75 widths marked most of one arm of a
# clean 114 degree corner on the tunicate scan unreliable, although that arm is
# a single fiber whose sections measured 1.0-1.3 widths across. Two fibers
# lying side by side below a junction are wider than 1.5 widths and are marked
# unreliable rather than split down the middle the way a medial axis splits
# them.
# 断面の最大値が枠からどこまで離れてよいか、その最大値から各半値交点をどこまで
# 探すか、および 1 本の繊維とみなす最大の断面幅（いずれも見かけ幅単位）。幅の
# 上限は各半分ではなく半値全幅に課す。AFM の断面はしばしば非対称で片側の斜面が
# ゆっくり下がり、各半分を 0.75 幅以内に要求すると、tunicate スキャンの明瞭な
# 114 度コーナーの片腕の大半が信頼できないとされた。その腕は 1 本の繊維で、断面は
# 1.0〜1.3 幅であった。分岐の下で並んで走る 2 本の繊維は 1.5 幅より広く、medial
# axis のように真ん中で分けられるのではなく、信頼できない区間として扱われる。
_CREST_REACH_WIDTHS = 0.75
_HALF_MAX_REACH_WIDTHS = 1.5
_MAX_SECTION_WIDTHS = 1.5

# Correlation length, in apparent widths, of the first-order penalty that joins
# the per-point offsets into one lateral offset along the track. With this and
# the frame at half a width, the line rounded corners that lie close together:
# on synthetic scans with known corners (2 nm pixels, W = 8 px), two
# same-sense 60 degree corners a few widths apart were judged as one bend by
# the kink rule in 2 of 16 cases, and the median distance from a corner vertex
# to the line was 1.10-1.51 px; at a quarter width no pair was merged and the
# distance fell to 0.77-1.21 px, while the median distance to the true
# centerline stayed at 0.11 px.
# 各点のオフセットを、トラックに沿った 1 本の横方向オフセットにつなぐ一次罰則の
# 相関長（見かけ幅単位）。これと枠を半幅にすると、線は近接したコーナーを丸めた。
# コーナー位置が既知の合成スキャン（画素 2 nm、W = 8 px）では、数幅離れた同じ
# 向きの 60 度コーナー 2 つを、キンク規則が 16 例中 2 例で 1 つの折れと判定し、
# コーナー頂点から線までの距離の中央値は 1.10〜1.51 px であった。1/4 幅では
# まとめられた組は無く、距離は 0.77〜1.21 px に下がった。真の中心線までの距離の
# 中央値は 0.11 px のままであった。
_OFFSET_SMOOTH_WIDTHS = 0.25

# Radius around a branch point, in apparent widths, inside which the height
# belongs to more than one fiber and cannot locate this one.
# 分岐点のまわりで、高さが複数の繊維に属し、この繊維の位置を決められない範囲の
# 半径（見かけ幅単位）。
_JUNCTION_WIDTHS = 1.0

# A cross-section whose amplitude falls below this fraction of the track's
# typical amplitude is a gap or a dim excursion, not this fiber.
# 振幅がトラックの典型的な振幅のこの割合を下回る断面は、この繊維ではなく、途切れ
# や暗い逸脱である。
_MIN_CREST_AMPLITUDE_FRAC = 0.25


def _bilinear(image: NDArray, y: NDArray, x: NDArray) -> NDArray:
    """
    Sample an image at fractional coordinates by bilinear interpolation.
    小数座標の画像値を双線形補間で取得する。

    Coordinates outside the image are clipped onto its edge.
    画像外の座標は画像の縁へクリップする。
    """
    rows, cols = image.shape
    y = np.clip(y, 0.0, rows - 1.001)
    x = np.clip(x, 0.0, cols - 1.001)
    y0 = np.floor(y).astype(np.intp)
    x0 = np.floor(x).astype(np.intp)
    fy = y - y0
    fx = x - x0
    return (image[y0, x0] * (1.0 - fy) * (1.0 - fx)
            + image[y0 + 1, x0] * fy * (1.0 - fx)
            + image[y0, x0 + 1] * (1.0 - fy) * fx
            + image[y0 + 1, x0 + 1] * fy * fx)


def sample_height(height: NDArray, x: NDArray, y: NDArray) -> NDArray:
    """
    Read a height image along a line with fractional coordinates.
    小数座標を持つ線に沿って高さ画像を読む。

    Parameters
    ----------
    height
        Height image indexed ``height[y, x]``.
        ``height[y, x]`` で添字付けする高さ画像。
    x, y
        Line coordinates in image pixels (x = column, y = row).
        画像画素座標での線の座標（x = 列、y = 行）。

    Returns
    -------
    ndarray
        Bilinearly interpolated heights, one per line point.
        線の点ごとに 1 つの、双線形補間した高さ。
    """
    return _bilinear(np.asarray(height, dtype=np.float64),
                     np.asarray(y, dtype=np.float64),
                     np.asarray(x, dtype=np.float64))


def polyline_distance(
    xtrack: NDArray,
    ytrack: NDArray,
    pixel_step_size: Union[int, float],
    y_pixel_step_size: Optional[Union[int, float]] = None,
) -> NDArray:
    """
    Cumulative Euclidean length along a polyline with per-axis pixel sizes.
    軸別ピクセルサイズで測った、折れ線に沿った累積ユークリッド長。

    Parameters
    ----------
    xtrack, ytrack
        Ordered line coordinates in pixels.
        順序付きの線の座標（画素）。
    pixel_step_size
        Physical size of one pixel along X (columns).
        X（列）方向の 1 画素の物理サイズ。
    y_pixel_step_size
        Physical size of one pixel along Y (rows); ``None`` reuses X.
        Y（行）方向の 1 画素の物理サイズ。``None`` なら X の値を使う。

    Returns
    -------
    ndarray
        Distance from the first point, starting at 0.
        先頭点からの距離。0 から始まる。

    Notes
    -----
    The chain-code weights of `imp_tools.convert_track_to_distance` correct
    the length of an 8-connected pixel chain, whose steps are orthogonal or
    diagonal only. A sub-pixel line has no such steps, so its length is the
    plain Euclidean sum.
    `imp_tools.convert_track_to_distance` のチェーンコード重みは、直交か斜めの
    ステップしか持たない 8 連結画素鎖の長さを補正するものである。小数座標の線には
    そうしたステップが無いため、長さは単純なユークリッド和である。
    """
    x = np.asarray(xtrack, dtype=np.float64)
    y = np.asarray(ytrack, dtype=np.float64)
    x_step = float(pixel_step_size)
    y_step = x_step if y_pixel_step_size is None else float(y_pixel_step_size)
    out = np.zeros(x.size, dtype=np.float64)
    if x.size > 1:
        steps = np.hypot(np.diff(x) * x_step, np.diff(y) * y_step)
        out[1:] = np.cumsum(steps)
    return out


def _unit_tangents(x: NDArray, y: NDArray, half: int) -> Tuple[NDArray, NDArray]:
    """
    Unit tangent at each track point from a centered finite difference.
    中心差分により各トラック点の単位接線を求める。
    """
    n = x.size
    i = np.arange(n)
    a = np.clip(i - half, 0, n - 1)
    b = np.clip(i + half, 0, n - 1)
    tx = x[b] - x[a]
    ty = y[b] - y[a]
    norm = np.hypot(tx, ty)
    norm[norm == 0.0] = 1.0
    return tx / norm, ty / norm


def measure_apparent_width(
    height: NDArray,
    xtrack: NDArray,
    ytrack: NDArray,
    return_measured: bool = False,
) -> Union[float, Tuple[float, bool]]:
    """
    Apparent full width at half maximum of the fiber under a track, in pixels.
    トラック下の繊維の見かけ半値全幅（画素）。

    Parameters
    ----------
    height
        Background-corrected height image the track was traced on.
        トラックを追跡した背景補正済み高さ画像。
    xtrack, ytrack
        Ordered track coordinates in image pixels.
        画像座標系での順序付きトラック座標。
    return_measured
        Also return whether the width was read from the profiles, or is the
        `FALLBACK_WIDTH_PX` substituted when too few sections gave a usable
        half-maximum run.
        幅がプロファイルから読めたか、使える半値区間を持つ断面が少なすぎて
        `FALLBACK_WIDTH_PX` を代用したかも返す。

    Returns
    -------
    float or tuple
        Median apparent width in pixels, never below 2; with
        `return_measured`, ``(width, measured)``.
        見かけ幅の中央値（画素）。2 を下回ることはない。`return_measured` を
        指定すると ``(width, measured)``。

    Notes
    -----
    The width is read from the **height** image, not from the binarized mask,
    even though the skeleton came from the mask. A mask boundary is a threshold
    contour, so its position moves with the fiber's own height, with the
    background residual and with neighbouring objects. The half-maximum level
    is taken per profile against that profile's own 10th percentile, so a
    fiber sitting on a residual background slope is still measured against its
    local base.
    幅は二値化マスクではなく **高さ** 画像から読む。スケルトンはマスク由来だが、
    マスク境界はしきい値等高線であり、その位置は繊維自身の高さ・背景残差・近傍物体
    によって動く。半値の基準はプロファイルごとにそのプロファイル自身の
    10 パーセンタイルへ取るため、背景の残留傾斜の上に載った繊維でも局所的な基準に
    対して測られる。

    The median over the track is used rather than a per-point width. A width
    is a property of the fiber, and a per-point value would make every length
    derived from it fluctuate along one fiber.
    点ごとの幅ではなくトラック全体の中央値を使う。幅は繊維の性質であり、点ごとの
    値ではそこから導く長さがすべて 1 本の繊維の中で揺らいでしまう。
    """
    x = np.asarray(xtrack, dtype=np.float64)
    y = np.asarray(ytrack, dtype=np.float64)
    if x.size < 2 or height is None:
        return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX

    tx, ty = _unit_tangents(x, y, _WIDTH_TANGENT_HALF)
    nx, ny = -ty, tx
    offsets = np.arange(-_WIDTH_SEARCH_PX, _WIDTH_SEARCH_PX + 1e-9, _WIDTH_STEP_PX)
    profiles = _bilinear(
        np.asarray(height, dtype=np.float64),
        y[:, None] + ny[:, None] * offsets[None, :],
        x[:, None] + nx[:, None] * offsets[None, :],
    )

    peak = profiles.max(axis=1)
    base = np.percentile(profiles, 10.0, axis=1)
    level = base + 0.5 * (peak - base)
    above = profiles >= level[:, None]

    # Walk outward from the track point until the profile drops below the half
    # maximum, so a second fiber further along the normal cannot widen the run.
    # トラック点から外側へ歩き、プロファイルが半値を下回った時点で止める。
    # これにより法線上のさらに先にある別の繊維が幅を広げることはない。
    centre = offsets.size // 2
    widths = np.empty(x.size, dtype=np.float64)
    usable = np.zeros(x.size, dtype=bool)
    for i in range(x.size):
        lo = centre
        while lo > 0 and above[i, lo - 1]:
            lo -= 1
        hi = centre
        while hi < offsets.size - 1 and above[i, hi + 1]:
            hi += 1
        widths[i] = offsets[hi] - offsets[lo]
        # A run that reaches the end of the search range never came back down
        # to half maximum, so it reports the search range rather than a width
        # and is excluded instead of averaged in.
        # 探索範囲の端まで届いた区間は半値まで下がらなかったということであり、
        # 返すのは幅ではなく探索範囲そのものなので、平均に混ぜず除外する。
        usable[i] = lo > 0 and hi < offsets.size - 1

    if usable.sum() < max(1, x.size // 2):
        return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
    width = float(np.median(widths[usable]))
    if not np.isfinite(width) or width < 2.0:
        return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
    return (width, True) if return_measured else width


def _smooth_extrapolated(values: NDArray, sigma: float) -> NDArray:
    """
    Gaussian-smooth a 1D sequence, padding each end by linear extrapolation.
    両端を線形外挿で延長して、1 次元列をガウス平滑化する。

    Padding by linear extrapolation reproduces a straight end exactly.
    Repeating the end value instead pulls the ends inward along the track,
    which shortened fragments under two widths by up to 35 % in a prototype.
    線形外挿による延長は直線の端を厳密に再現する。端の値を繰り返すと端がトラック
    に沿って内側へ引き込まれ、試作では 2 幅未満の断片が最大 35 % 短くなった。
    """
    v = np.asarray(values, dtype=np.float64)
    if sigma <= 0.0 or v.size < 3:
        return v.copy()
    radius = max(1, int(np.ceil(3.0 * sigma)))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    span = min(v.size - 1, radius)
    head_slope = (v[span] - v[0]) / span
    tail_slope = (v[-1] - v[-1 - span]) / span
    head = v[0] - head_slope * np.arange(radius, 0, -1)
    tail = v[-1] + tail_slope * np.arange(1, radius + 1)
    return np.convolve(np.concatenate([head, v, tail]), kernel, mode="valid")


def _solve_tridiagonal(
    sub: NDArray, main: NDArray, sup: NDArray, rhs: NDArray,
) -> NDArray:
    """
    Solve a tridiagonal linear system by the Thomas algorithm.
    三重対角連立一次方程式をトーマス法で解く。

    Written out rather than taken from SciPy so that this module needs nothing
    beyond NumPy.
    本モジュールが NumPy 以外を必要としないよう、SciPy から取らずに書き下す。
    """
    n = main.size
    if n == 1:
        return rhs / main
    c = np.empty(n - 1)
    d = np.empty(n)
    c[0] = sup[0] / main[0]
    d[0] = rhs[0] / main[0]
    for i in range(1, n):
        denom = main[i] - sub[i - 1] * c[i - 1]
        if i < n - 1:
            c[i] = sup[i] / denom
        d[i] = (rhs[i] - sub[i - 1] * d[i - 1]) / denom
    out = np.empty(n)
    out[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        out[i] = d[i] - c[i] * out[i + 1]
    return out


def _whittaker_first_order(
    target: NDArray, weight: NDArray, lam: float,
) -> NDArray:
    """
    Weighted first-order penalized least squares (Whittaker smoother).
    重み付き一次罰則付き最小二乗（Whittaker 平滑化）。

    Minimizes ``sum(w (z - t)^2) + lam * sum(diff(z)^2)``. A first-order
    penalty interpolates linearly across a gap and extrapolates a constant
    beyond the last weighted point, so an unreliable track end keeps the offset
    of the reliable part next to it instead of drifting.
    ``sum(w (z - t)^2) + lam * sum(diff(z)^2)`` を最小化する。一次罰則は欠落区間を
    線形に補間し、最後の重み付き点より先は定数で外挿する。そのため信頼できない
    トラック端は、隣接する信頼できる部分のオフセットを保ち、漂流しない。
    """
    n = target.size
    if n == 1:
        return target.astype(np.float64).copy()
    main = weight + 1e-6 + lam * np.concatenate([[1.0], np.full(n - 2, 2.0), [1.0]])
    off = np.full(n - 1, -lam)
    return _solve_tridiagonal(off, main, off, weight * target)


def refine_centerline(
    height: NDArray,
    xtrack: NDArray,
    ytrack: NDArray,
    width_px: float,
    branch_points: Optional[NDArray] = None,
) -> Tuple[NDArray, NDArray, NDArray]:
    """
    Move each skeleton point to the half-maximum midpoint of its cross-section.
    各スケルトン点を、その断面の半値中点へ移す。

    Parameters
    ----------
    height
        Background-corrected height image the track was traced on.
        トラックを追跡した背景補正済み高さ画像。
    xtrack, ytrack
        Ordered skeleton track in image pixels.
        画像座標系での順序付きスケルトントラック。
    width_px
        Apparent fiber width (`measure_apparent_width`); every length the
        refinement uses is a multiple of it.
        見かけ繊維幅（`measure_apparent_width`）。精密化が使う長さはすべてその
        倍数である。
    branch_points
        Branch-point mask in the frame of `height`, or ``None``.
        `height` と同じ座標系の分岐点マスク。無ければ ``None``。

    Returns
    -------
    tuple of ndarray
        ``(x, y, reliable)``: one line point per input point, in the same
        order. ``reliable`` marks the points whose position was measured on
        this fiber's own cross-section; the others were interpolated.
        ``(x, y, reliable)``。入力点ごとに 1 点を同じ順で返す。``reliable`` は
        この繊維自身の断面で位置を測った点を示し、それ以外は補間された点である。

    Notes
    -----
    Each point moves only along the normal of a smoothed copy of the track.
    Confining the motion to the normal is what keeps the result stable: a
    point cannot slide along the curve or fold back, which is how a prototype
    that let points move freely ran a 59 px fragment at a crossing out to
    536 px. Before the half-maximum crossings are read, the section is climbed
    uphill from the frame to the nearest local maximum, not to the brightest
    point in reach, so a brighter neighbour cannot capture the track; before
    that rule, two real tracks were pulled 0.6-0.7 widths off their own fiber.
    The maximum only anchors the search -- the position reported is the
    midpoint of the two crossings, which is read off the steep flanks where
    noise moves a crossing least, not off the flat top.
    各点はトラックの平滑化コピーの法線方向にだけ動く。運動を法線に限ることが結果を
    安定させる。点は曲線に沿って滑ることも折り返すこともできない。点を自由に動かした
    試作では、交差部の 59 px の断片が 536 px まで伸びた。半値交点を読む前に、断面を
    枠から坂に沿って最寄りの極大へ上る。射程内で最も明るい点へではない。これにより、
    より明るい隣の繊維にトラックを奪われない。この規則の前は、実トラック 2 本が自分の
    繊維から 0.6〜0.7 幅引き離されていた。極大は探索の足場にすぎず、返す位置は
    2 つの交点の中点である。これはノイズが交点を最も動かさない急な斜面から読むもので
    あり、平らな頂部から読むのではない。

    A point is marked unreliable, and its offset interpolated from the
    reliable points around it instead of measured, wherever the cross-section
    cannot locate this one fiber: within one width of a branch point, where
    the section is wider than 1.5 widths (two fibers side by side), where the
    maximum found does not belong to the section the track lies on, and where
    the section is too faint. The offsets are joined along the track by a
    first-order penalty, so a gap is bridged linearly and an unreliable end
    keeps the offset of the reliable part next to it.
    断面がこの 1 本の繊維の位置を決められない点——分岐点から 1 幅以内、断面幅が
    1.5 幅を超える点（2 本が並んでいる）、見つけた極大がトラックの載る断面のもの
    でない点、断面が弱すぎる点——は信頼できないと印を付け、そのオフセットは測らずに
    周囲の信頼できる点から補間する。オフセットは一次罰則でトラックに沿ってつなぐ
    ため、欠落区間は線形に橋渡しされ、信頼できない端は隣の信頼できる部分の
    オフセットを保つ。
    """
    lx, ly, reliable, _crest = _refine(height, xtrack, ytrack, width_px, branch_points)
    return lx, ly, reliable


def _refine(
    height: Optional[NDArray],
    xtrack: NDArray,
    ytrack: NDArray,
    width_px: float,
    branch_points: Optional[NDArray],
) -> Tuple[NDArray, NDArray, NDArray, NDArray]:
    """
    Place the line and read the crest height at each of its points.
    線を置き、その各点で頂点高さを読む。

    Returns ``(x, y, reliable, crest)``: the three values of
    `refine_centerline` and, per point, the **crest height** -- the maximum of
    the cross-section the point was resolved on, or, where the section could
    not locate this fiber and the point was interpolated, the maximum within
    `_CREST_WINDOW_WIDTHS` of the line point along its normal. The crest is
    what a fiber's height means: the line itself sits at the half-maximum
    midpoint, which on an asymmetric section is beside the top rather than on
    it, so a height read at the line by interpolation is biased low.
    ``(x, y, reliable, crest)`` を返す。`refine_centerline` の 3 つの値と、点ごとの
    **頂点高さ**である。頂点高さは、その点を決めた断面の最大値、または断面がこの
    繊維の位置を決められず点が補間された場合は、線の点から法線に沿って
    `_CREST_WINDOW_WIDTHS` 以内の最大値である。繊維の高さが意味するのは頂点高さで
    ある。線そのものは半値中点にあり、非対称な断面では頂部の上ではなく脇に来る
    ため、線の位置で補間して読んだ高さは低く偏る。
    """
    x = np.asarray(xtrack, dtype=np.float64)
    y = np.asarray(ytrack, dtype=np.float64)
    n = x.size
    if n < 3 or height is None:
        crest = (np.full(n, np.nan) if height is None
                 else sample_height(height, x, y))
        return x.copy(), y.copy(), np.zeros(n, dtype=bool), crest
    img = np.asarray(height, dtype=np.float64)
    width = float(width_px)
    mean_step = max(float(np.hypot(np.diff(x), np.diff(y)).mean()), 1e-9)

    sigma = _FRAME_SIGMA_WIDTHS * width / mean_step
    fx = _smooth_extrapolated(x, sigma)
    fy = _smooth_extrapolated(y, sigma)
    tx = np.gradient(fx)
    ty = np.gradient(fy)
    norm = np.hypot(tx, ty)
    norm[norm == 0.0] = 1.0
    nx, ny = -ty / norm, tx / norm

    reach = _CREST_REACH_WIDTHS * width
    half_reach = _HALF_MAX_REACH_WIDTHS * width
    s = np.arange(-(reach + half_reach), reach + half_reach + 1e-9, _WIDTH_STEP_PX)
    ns = s.size
    prof = _bilinear(img, fy[:, None] + ny[:, None] * s[None, :],
                     fx[:, None] + nx[:, None] * s[None, :])
    rows = np.arange(n)
    col = np.arange(ns)[None, :]

    # Climb uphill from the frame point to the nearest local maximum.
    # 枠の点から坂を上り、最寄りの極大へ達する。
    c = int(np.argmin(np.abs(s)))
    dif = np.diff(prof, axis=1)
    k = np.full(n, c)
    go_right = dif[:, c] > 0
    go_left = ~go_right & (dif[:, c - 1] < 0)
    stop_right = dif[:, c:] <= 0
    right_end = np.where(stop_right.any(1), stop_right.argmax(1), stop_right.shape[1]) + c
    k = np.where(go_right, np.minimum(right_end, ns - 1), k)
    stop_left = dif[:, :c][:, ::-1] >= 0
    left_steps = np.where(stop_left.any(1), stop_left.argmax(1), c)
    k = np.where(go_left, c - left_steps, k)
    peak = prof[rows, k]
    within_reach = np.abs(s[k]) < reach - 0.5 * _WIDTH_STEP_PX

    # Half-maximum crossings on either side of the maximum.
    # 極大の両側の半値交点。
    window = np.abs(s[None, :] - s[k][:, None]) <= half_reach
    left = window & (col < k[:, None])
    right = window & (col > k[:, None])
    left_min = np.where(left, prof, np.inf).min(1)
    right_min = np.where(right, prof, np.inf).min(1)
    left_min = np.where(np.isfinite(left_min), left_min, peak)
    right_min = np.where(np.isfinite(right_min), right_min, peak)
    base = np.minimum(left_min, right_min)
    amplitude = peak - base
    level = base + 0.5 * amplitude
    below = prof < level[:, None]
    li = np.where(left & below, col, -1).max(1)
    ri = np.where(right & below, col, ns).min(1)
    resolved = within_reach & (li >= 0) & (ri < ns) & (amplitude > 0)

    offset = s[k].astype(np.float64)
    r = np.nonzero(resolved)[0]
    if r.size:
        jl = li[r]
        pl0 = prof[r, jl]
        pl1 = prof[r, jl + 1]
        xl = s[jl] + (level[r] - pl0) / np.where(pl1 != pl0, pl1 - pl0, 1.0) * _WIDTH_STEP_PX
        jr = ri[r]
        pr0 = prof[r, jr - 1]
        pr1 = prof[r, jr]
        xr = s[jr - 1] + (pr0 - level[r]) / np.where(pr0 != pr1, pr0 - pr1, 1.0) * _WIDTH_STEP_PX
        offset[r] = 0.5 * (xl + xr)
        # The section must be the one the track lies on: the frame point has
        # to sit inside its half-maximum run.
        # 断面はトラックが載るものでなければならない。枠の点がその半値区間の
        # 内側にある必要がある。
        owns = (xl <= 0.0) & (xr >= 0.0)
        narrow = (xr - xl) <= _MAX_SECTION_WIDTHS * width
        resolved[r[~(owns & narrow)]] = False

    typical = float(np.median(amplitude[resolved])) if resolved.any() else float(np.median(amplitude))
    weight = (resolved & (amplitude >= _MIN_CREST_AMPLITUDE_FRAC * typical)).astype(np.float64)

    if branch_points is not None:
        mask = np.asarray(branch_points)
        radius = _JUNCTION_WIDTHS * width
        x0 = max(int(np.floor(x.min() - radius)), 0)
        x1 = min(int(np.ceil(x.max() + radius)) + 1, mask.shape[1])
        y0 = max(int(np.floor(y.min() - radius)), 0)
        y1 = min(int(np.ceil(y.max() + radius)) + 1, mask.shape[0])
        by, bx = np.nonzero(mask[y0:y1, x0:x1])
        if bx.size:
            d2 = ((x[:, None] - (bx + x0)[None, :]) ** 2
                  + (y[:, None] - (by + y0)[None, :]) ** 2).min(1)
            weight[d2 < radius * radius] = 0.0

    lam = (_OFFSET_SMOOTH_WIDTHS * width / mean_step) ** 2
    lateral = np.clip(_whittaker_first_order(offset, weight, lam), -reach, reach)
    reliable = weight > 0.0

    # Crest height: the maximum of the section a reliable point was resolved
    # on; for an interpolated point, the maximum within a quarter width of the
    # line point. The sampled span always covers that window, because the
    # lateral offset is clipped to the crest reach inside it.
    # 頂点高さ。信頼できる点はそれを決めた断面の最大値、補間された点は線の点から
    # 1/4 幅以内の最大値。横方向オフセットはこの範囲内の頂点到達距離にクリップ
    # されるため、サンプリング範囲は常にその窓を覆う。
    near = np.abs(s[None, :] - lateral[:, None]) <= _CREST_WINDOW_WIDTHS * width
    crest_near = np.where(near, prof, -np.inf).max(1)
    line_x = fx + nx * lateral
    line_y = fy + ny * lateral
    # The profile is sampled every quarter pixel, so the height at the line
    # point itself can exceed the sampled maximum by a sliver; taking the
    # larger keeps "never below the height at the line" exact.
    # プロファイルは 1/4 画素ごとの標本なので、線の点そのものの高さが標本の
    # 最大値をわずかに上回ることがある。大きい方を取り、「線の位置の高さを
    # 下回らない」を厳密に保つ。
    at_line = _bilinear(img, line_y, line_x)
    crest_near = np.where(np.isfinite(crest_near), crest_near, at_line)
    crest = np.maximum(np.where(reliable, peak, crest_near), at_line)
    return line_x, line_y, reliable, crest.astype(np.float64)


@dataclass(frozen=True)
class CenterlineResult:
    """
    The line placed on one traced skeleton track, with what placing it found.
    追跡済みスケルトントラック 1 本の上に置いた線と、置く過程でわかったこと。

    Attributes
    ----------
    x, y
        Line coordinates in image pixels, one per track point, in track order.
        画像座標系での線の座標。トラック点ごとに 1 点、トラック順。
    width_px
        Apparent width W in pixels the line was placed with, which the kink
        rule of `lib.kink_detector` scales every length by.
        線を置くのに使った見かけ幅 W（画素）。`lib.kink_detector` のキンク規則は
        すべての長さをこれで尺度付けする。
    width_measured
        Whether `width_px` was read from the fiber's own cross-sections.
        ``False`` means `FALLBACK_WIDTH_PX` was substituted, so the fiber's
        rule lengths are a pixel count rather than multiples of its width.
        `width_px` が繊維自身の断面から読めたかどうか。``False`` は
        `FALLBACK_WIDTH_PX` を代用したことを意味し、その繊維の規則の長さは幅の
        倍数ではなく画素数になっている。
    reliable
        Per point, whether the position was measured on this fiber's own
        cross-section (``True``) or interpolated from the reliable points
        around it. An interpolated run is straight, so no kink and no
        curvature can be found on it; the fraction of reliable points is how
        much of the fiber was actually located.
        点ごとに、位置をこの繊維自身の断面で測ったか（``True``）、周囲の信頼
        できる点から補間したか。補間区間は直線なので、そこにキンクも曲率も見つ
        からない。信頼できる点の割合が、繊維のどれだけを実際に位置決めできたかを
        表す。
    crest
        Crest height per point in the units of the height image: the maximum
        of the resolved cross-section, or the maximum within a quarter width
        of an interpolated point. This is the fiber's height; the line itself
        sits at the half-maximum midpoint, beside the top on an asymmetric
        section.
        点ごとの頂点高さ（高さ画像の単位）。決められた断面の最大値、または補間
        された点から 1/4 幅以内の最大値。これが繊維の高さである。線そのものは
        半値中点にあり、非対称な断面では頂部の脇に来る。
    """

    x: NDArray
    y: NDArray
    width_px: float
    width_measured: bool
    reliable: NDArray
    crest: NDArray


def place_centerline(
    height: Optional[NDArray],
    xtrack: NDArray,
    ytrack: NDArray,
    branch_points: Optional[NDArray] = None,
) -> CenterlineResult:
    """
    Place the half-maximum centerline of one traced skeleton track.
    追跡済みスケルトントラック 1 本の半値中点線を置く。

    Parameters
    ----------
    height
        Background-corrected height image in the frame of the track.
        ``None`` returns the track itself as floats, with the fallback width,
        no reliable point and no crest.
        トラックと同じ座標系の背景補正済み高さ画像。``None`` ならトラック自体を
        浮動小数で返し、幅は代替値、信頼できる点は無し、頂点高さも無しとする。
    xtrack, ytrack
        Ordered skeleton track in image pixels.
        画像座標系での順序付きスケルトントラック。
    branch_points
        Branch-point mask in the same frame, or ``None``.
        同じ座標系の分岐点マスク。無ければ ``None``。

    Returns
    -------
    CenterlineResult
        The line, the width it was placed with and whether that width was
        measured, the per-point reliability and the crest heights.
        線、置くのに使った幅とそれが測定値かどうか、点ごとの信頼性、頂点高さ。

    Notes
    -----
    GUI01's kink detection and the fiber tracer that rebuilds fibers when a
    bundle is opened both call this, so the kinks stored in a bundle and the
    line they are drawn on come from one computation on the same inputs.
    `half_max_centerline` is the same computation returning only the line.
    GUI01 のキンク判定と、バンドルを開いたときに繊維を組み立て直す追跡処理の
    両方がこれを呼ぶ。そのため、バンドルに保存されたキンクと、それを描く線は、
    同じ入力に対する 1 つの計算から来る。`half_max_centerline` は同じ計算で線だけ
    を返すものである。
    """
    x = np.asarray(xtrack, dtype=np.float64)
    y = np.asarray(ytrack, dtype=np.float64)
    if height is None:
        return CenterlineResult(
            x.copy(), y.copy(), FALLBACK_WIDTH_PX, False,
            np.zeros(x.size, dtype=bool), np.full(x.size, np.nan),
        )
    width, measured = measure_apparent_width(height, x, y, return_measured=True)
    lx, ly, reliable, crest = _refine(height, x, y, width, branch_points)
    return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)


def half_max_centerline(
    height: Optional[NDArray],
    xtrack: NDArray,
    ytrack: NDArray,
    branch_points: Optional[NDArray] = None,
    return_width: bool = False,
) -> Union[Tuple[NDArray, NDArray], Tuple[NDArray, NDArray, float]]:
    """
    Return the half-maximum centerline of one traced skeleton track.
    追跡済みスケルトントラック 1 本の半値中点線を返す。

    Parameters
    ----------
    height
        Background-corrected height image in the frame of the track.
        ``None`` returns the track itself as floats.
        トラックと同じ座標系の背景補正済み高さ画像。``None`` ならトラック自体を
        浮動小数で返す。
    xtrack, ytrack
        Ordered skeleton track in image pixels.
        画像座標系での順序付きスケルトントラック。
    branch_points
        Branch-point mask in the same frame, or ``None``.
        同じ座標系の分岐点マスク。無ければ ``None``。
    return_width
        Also return the apparent width the line was placed with, which the
        kink rule of `lib.kink_detector` scales every length by.
        線を置くのに使った見かけ幅も返す。`lib.kink_detector` のキンク規則は
        すべての長さをこれで尺度付けする。

    Returns
    -------
    tuple
        ``(x, y)`` line coordinates, one per track point, in track order; with
        `return_width`, the apparent width in pixels follows as a third
        element.
        トラック点ごとに 1 点の、トラック順の線座標 ``(x, y)``。`return_width`
        を指定すると、3 番目の要素として見かけ幅（画素）が続く。

    Notes
    -----
    The line-only form of `place_centerline`, which also reports the width's
    provenance, the per-point reliability and the crest heights.
    `place_centerline` の線だけを返す形。`place_centerline` は幅の出所、点ごとの
    信頼性、頂点高さも報告する。
    """
    placed = place_centerline(height, xtrack, ytrack, branch_points)
    if return_width:
        return placed.x, placed.y, placed.width_px
    return placed.x, placed.y
