# -*- coding: utf-8 -*-
"""
Synthetic AFM scans whose fiber centerline is known analytically.
繊維中心線が解析的に既知の合成 AFM 画像を生成する。

The bundled real scans can show that a detected kink is absent from the height
ridge, but they cannot measure a false-positive *rate*, because nobody knows
how many kinks a real fiber truly has. The scans built here have a centerline
that is an analytic curve, so the number of true kinks is known by
construction: zero for the smooth families (`straight`, `arc`, `sine`) and
exactly one for `kinked`. That makes a false-positive count per unit contour
length measurable, and it lets a detection threshold be chosen against a known
answer instead of against a real image whose answer is unknown.
同梱の実測スキャンでは「検出されたキンクが高さ稜線に無い」ことは示せるが、
偽陽性「率」は測れない。実際の繊維が本当は何点折れているか誰も知らないため
である。ここで作る画像は中心線が解析曲線なので、真のキンク数が構成上わかる
（平滑族 `straight` / `arc` / `sine` はゼロ、`kinked` はちょうど 1 点）。
これにより単位輪郭長あたりの偽陽性数が測定可能になり、答えのわからない実画像
ではなく既知の答えに対してしきい値を決められる。

Notes
-----
Height formation follows the standard AFM forward model: the ideal fiber
surface is dilated by the probe apex (Villarrubia), not blurred. The
distinction is what makes these scans able to reproduce the defect they exist
to measure. A Gaussian blur is symmetric about the ridge, so the binarized
mask of a blurred fiber is symmetric about the ridge too, and a medial axis
computed from it cannot be displaced. Dilation by a finite tip is not
symmetric on a curved fiber — the apex reaches further into the outside of a
bend than into the inside — so the mask acquires exactly the asymmetry that
displaces a thinning-based centerline in a real scan.
高さの生成は AFM の標準的な順モデルに従い、理想繊維表面を探針先端で dilation
する（Villarrubia）。ぼかしでは代用できない。ガウスぼかしは稜線に対して対称
なので、ぼかした繊維の二値化マスクも稜線に対して対称になり、そこから求めた
medial axis は原理的にずれ得ない。有限半径の探針による dilation は曲がった
繊維上で対称ではなく——先端は曲がりの内側より外側へ深く入り込む——実スキャンで
細線化中心線をずらしているのと同じ非対称性がマスクに生じる。

Coordinates follow the project convention: ``image[y, x]``, with centerline
positions in pixel units where the centre of pixel ``(row i, column j)`` is
``(j + 0.5, i + 0.5)``. A detected track therefore has to be compared at
``xtrack + 0.5``, the same half-pixel shift GUI04 applies when it draws one.
座標はプロジェクトの慣例に従う（``image[y, x]``、中心線は画素単位で、画素
``(行 i, 列 j)`` の中心が ``(j + 0.5, i + 0.5)``）。したがって検出トラックとの
比較は ``xtrack + 0.5`` で行う。GUI04 が描画時に掛けるのと同じ半画素補正である。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

# Centerline sampling step in pixels. A quarter pixel keeps the ground truth
# itself free of the staircase that integer-endpoint line drawing would add.
# 中心線のサンプリング間隔（画素）。1/4 画素にすることで、整数端点の直線描画が
# 真値そのものに階段状の量子化を持ち込むのを避ける。
CENTERLINE_STEP_PX: float = 0.25

@dataclass(frozen=True)
class Centerline:
    """
    One analytic fiber centerline with its true kink positions.
    真のキンク位置を伴う解析的な繊維中心線 1 本。

    Attributes
    ----------
    x, y
        Densely sampled centerline in pixel coordinates.
        画素座標で密にサンプリングした中心線。
    kink_indices
        Indices into `x` / `y` where the curve has a tangent discontinuity.
        Empty for every smooth family.
        接線が不連続になる点の `x` / `y` 上のインデックス。平滑族では空。
    kink_angles_deg
        Interior angle at each entry of `kink_indices`.
        `kink_indices` の各点における内角（度）。
    kind
        Family name: ``"straight"``, ``"arc"``, ``"sine"`` or ``"kinked"``.
        族の名前。``"straight"`` / ``"arc"`` / ``"sine"`` / ``"kinked"``。
    curvature_radius_nm
        Smallest radius of curvature along the curve; ``inf`` where the curve
        is piecewise straight. This is the physical scale a detector has to
        distinguish from a kink.
        曲線上で最小の曲率半径。区分的に直線なら ``inf``。検出器がキンクと
        区別しなければならない物理スケールそのものである。
    """

    x: NDArray[np.float64]
    y: NDArray[np.float64]
    kink_indices: NDArray[np.int64]
    kink_angles_deg: NDArray[np.float64]
    kind: str
    curvature_radius_nm: float


@dataclass(frozen=True)
class SyntheticScan:
    """
    A rendered height image together with the ground truth that produced it.
    描画した高さ画像と、その生成に用いた真値の組。

    Attributes
    ----------
    image
        Height image in nanometers, indexed ``[y, x]``.
        ナノメートル単位の高さ画像。添字は ``[y, x]``。
    nm_per_px
        Pixel size; the pixel grid is square by construction.
        画素サイズ。構成上、画素格子は正方形である。
    centerlines
        Ground-truth centerlines drawn into the image.
        画像に描いた真値の中心線。
    fiber_diameters_nm
        Diameter of each modelled cylinder, i.e. its true apparent height at
        full thickness. One entry per centerline, so a crossing can be built
        from fibers of unequal height.
        モデル化した各円柱の直径。すなわち最大太さでの真の見かけ高さ。中心線
        ごとに 1 要素あるため、高さの異なる繊維どうしの交差も構成できる。
    taper_nm, taper_end_ratio
        Length over which each fiber thins toward its two ends, and the
        fraction of full diameter it retains at the very end.
        各繊維が両端に向かって細くなる長さと、末端で保持する直径の割合。
    tip_radius_nm
        Probe apex radius used for the dilation; ``0`` means an ideal probe.
        dilation に用いた探針先端半径。``0`` は理想探針を意味する。
    noise_nm, line_noise_nm, tilt_nm
        Pixel noise, per-scan-line offset noise, and background tilt applied
        after dilation.
        dilation 後に加えた画素ノイズ、走査線ごとのオフセットノイズ、背景傾斜。
    roughness_nm, roughness_corr_nm, roughness_hurst
        Standard deviation, outer scale, and roughness exponent of the
        spatially correlated background, as injected before the pipeline runs.
        The background stage removes part of it, so these are not what a
        calibrated image shows: the bundled real scans carry 0.15 to 0.46 nm
        of background deviation after calibration, still correlated at 18 nm
        and beyond, against 0.05 nm and no correlation for pixel noise alone.
        空間相関を持つ背景の標準偏差・外側スケール・粗さ指数。いずれもパイプ
        ライン実行前に注入する値である。背景段がその一部を除去するため、較正済み
        画像に現れる値とは異なる。同梱の実スキャンは較正後で背景標準偏差
        0.15〜0.46 nm を持ち、18 nm 以遠まで相関が残る。画素ノイズのみでは
        0.05 nm・無相関である。
    seed
        Seed of the generator that produced the noise.
        ノイズ生成に用いた乱数シード。
    """

    image: NDArray[np.float64]
    nm_per_px: float
    centerlines: Tuple[Centerline, ...]
    fiber_diameters_nm: Tuple[float, ...]
    taper_nm: float
    taper_end_ratio: float
    tip_radius_nm: float
    noise_nm: float
    line_noise_nm: float
    tilt_nm: float
    roughness_nm: float
    roughness_corr_nm: float
    roughness_hurst: float
    seed: int

    @property
    def scan_size_um(self) -> Tuple[float, float]:
        """
        Physical scan size ``(x_um, y_um)`` for `pipeline.process_file`.
        `pipeline.process_file` に渡す走査範囲 ``(x_um, y_um)``。
        """
        h, w = self.image.shape[:2]
        return (w * self.nm_per_px / 1000.0, h * self.nm_per_px / 1000.0)

    @property
    def true_kinks_xy(self) -> Tuple[NDArray[np.float64], NDArray[np.float64]]:
        """
        Pixel coordinates of every true kink across all centerlines.
        全中心線にわたる真のキンクの画素座標。
        """
        xs, ys = [], []
        for line in self.centerlines:
            xs.append(line.x[line.kink_indices])
            ys.append(line.y[line.kink_indices])
        if not xs:
            return np.empty(0), np.empty(0)
        return np.concatenate(xs), np.concatenate(ys)

    @property
    def true_length_nm(self) -> float:
        """
        Total contour length of the ground-truth centerlines.
        真値中心線の総輪郭長（nm）。
        """
        total = 0.0
        for line in self.centerlines:
            steps = np.hypot(np.diff(line.x), np.diff(line.y))
            total += float(steps.sum()) * self.nm_per_px
        return total


# ===== Centerline families =====


def _place(
    u_nm: NDArray,
    v_nm: NDArray,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    angle_deg: float,
    center_px: Optional[Tuple[float, float]],
) -> Tuple[NDArray, NDArray]:
    """
    Rotate a curve given in its own frame and place it in the image.
    曲線を自身の座標系で回転し、画像内に配置する。

    Rotating by a non-axis-aligned angle is deliberate: the skeleton of an
    axis-aligned line is exact, so an axis-aligned test would understate the
    digitisation noise that every obliquely running real fiber carries.
    軸に平行でない角度で回転させるのは意図的である。軸平行な線のスケルトンは
    厳密に一致するため、軸平行なテストは斜めに走る実際の繊維が必ず持つ量子化
    ノイズを過小評価してしまう。
    """
    ang = np.radians(angle_deg)
    ca, sa = np.cos(ang), np.sin(ang)
    xs = (u_nm * ca - v_nm * sa) / nm_per_px
    ys = (u_nm * sa + v_nm * ca) / nm_per_px
    h, w = shape
    cx, cy = (w / 2.0, h / 2.0) if center_px is None else center_px
    return xs + cx, ys + cy


def _arange_symmetric(length_nm: float, step_nm: float) -> NDArray:
    """
    Sample a curve parameter symmetrically about zero.
    曲線パラメータを 0 を中心に対称にサンプリングする。
    """
    n = int(round(length_nm / step_nm))
    return (np.arange(n + 1) - n / 2.0) * step_nm


def straight_centerline(
    length_nm: float,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    angle_deg: float = 23.0,
    center_px: Optional[Tuple[float, float]] = None,
) -> Centerline:
    """
    A straight fiber: the zero-curvature, zero-kink baseline.
    直線繊維。曲率ゼロ・キンクゼロの基準条件。

    Every kink reported on this family is a false positive with no ambiguity
    at all, so it isolates the detector's pure noise floor from the separate
    question of whether curvature should count as a kink.
    この族で報告されたキンクは一切の曖昧さなく偽陽性なので、「曲率をキンクと
    数えるべきか」という別の問題から切り離して検出器の純粋なノイズ床を測れる。
    """
    step = CENTERLINE_STEP_PX * nm_per_px
    u = _arange_symmetric(length_nm, step)
    x, y = _place(u, np.zeros_like(u), shape=shape, nm_per_px=nm_per_px,
                  angle_deg=angle_deg, center_px=center_px)
    return Centerline(x, y, np.empty(0, np.int64), np.empty(0), "straight", float("inf"))


def arc_centerline(
    length_nm: float,
    radius_nm: float,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    angle_deg: float = 23.0,
    center_px: Optional[Tuple[float, float]] = None,
) -> Centerline:
    """
    A circular arc: constant curvature, no kink anywhere.
    円弧。曲率一定で、どこにもキンクは無い。

    This is the family that separates "kink" from "curvature". A detector that
    reports a kink here is reporting a bend spread over the whole fiber, which
    is a curvature measurement, not a defect.
    「キンク」と「曲率」を分離するための族である。ここでキンクを報告する検出器
    は、繊維全体に分布した曲がりを報告しているのであって、それは曲率の測定で
    あり欠陥の検出ではない。
    """
    if radius_nm <= 0:
        raise ValueError("radius_nm must be positive")
    step = CENTERLINE_STEP_PX * nm_per_px
    s = _arange_symmetric(length_nm, step)
    t = s / radius_nm
    u = radius_nm * np.sin(t)
    v = radius_nm * (1.0 - np.cos(t))
    x, y = _place(u, v, shape=shape, nm_per_px=nm_per_px,
                  angle_deg=angle_deg, center_px=center_px)
    return Centerline(x, y, np.empty(0, np.int64), np.empty(0), "arc", float(radius_nm))


def sine_centerline(
    length_nm: float,
    amplitude_nm: float,
    wavelength_nm: float,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    angle_deg: float = 23.0,
    center_px: Optional[Tuple[float, float]] = None,
) -> Centerline:
    """
    A sinusoidal meander: curvature that varies in sign and magnitude.
    正弦波状の蛇行。曲率の符号と大きさが変化する。

    An arc turns the same way everywhere, so a detector could pass it by
    ignoring slow turns wholesale. A meander reverses, as a dispersed fibril
    does, and its curvature extrema are where a scale-blind detector plants a
    vertex.
    円弧はどこでも同じ向きに曲がるので、緩い曲がりを一律に無視するだけの検出器
    でも通過してしまう。蛇行は向きが反転する——分散したフィブリルの挙動である
    ——ため、スケールを持たない検出器はその曲率極大に頂点を立てる。

    Notes
    -----
    The parameter is sampled uniformly in `u`, not in arc length, so points are
    slightly denser where the curve is steep. That is harmless for a distance
    field and for a nearest-point ground truth, and it is stated here so a
    caller does not read `x` / `y` as arc-length parameterized.
    パラメータは弧長ではなく `u` について等間隔にサンプリングするため、傾きが
    急な場所ほど点がわずかに密になる。距離場と最近傍による真値には無害だが、
    `x` / `y` を弧長パラメータと誤読しないよう明記しておく。
    """
    step = CENTERLINE_STEP_PX * nm_per_px
    u = _arange_symmetric(length_nm, step)
    k = 2.0 * np.pi / wavelength_nm
    v = amplitude_nm * np.sin(k * u)
    x, y = _place(u, v, shape=shape, nm_per_px=nm_per_px,
                  angle_deg=angle_deg, center_px=center_px)
    r_min = float("inf") if amplitude_nm == 0 else 1.0 / (amplitude_nm * k * k)
    return Centerline(x, y, np.empty(0, np.int64), np.empty(0), "sine", r_min)


def kinked_centerline(
    length_nm: float,
    interior_angle_deg: float,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    angle_deg: float = 23.0,
    center_px: Optional[Tuple[float, float]] = None,
) -> Centerline:
    """
    Two straight arms meeting at one apex of known interior angle.
    既知の内角を持つ頂点 1 点で交わる 2 本の直線腕。

    The positive control. Recall measured here and the false-positive density
    measured on the smooth families are the two halves of one threshold
    decision; a recall figure quoted without the other half is the
    recovery-only metric that always improves as a threshold loosens.
    陽性対照。ここで測る再現率と平滑族で測る偽陽性密度は、1 つのしきい値決定の
    表裏である。片方だけを引用した再現率は、しきい値を緩めれば常に改善する
    「回収率のみの指標」にすぎない。
    """
    if not 0.0 < interior_angle_deg < 180.0:
        raise ValueError("interior_angle_deg must lie strictly between 0 and 180")
    step = CENTERLINE_STEP_PX * nm_per_px
    half = length_nm / 2.0
    theta = np.radians(interior_angle_deg)
    d1 = np.array([-np.sin(theta / 2.0), np.cos(theta / 2.0)])
    d2 = np.array([np.sin(theta / 2.0), np.cos(theta / 2.0)])
    s = np.arange(step, half + 1e-9, step)
    u = np.concatenate([(s * d1[0])[::-1], [0.0], s * d2[0]])
    v = np.concatenate([(s * d1[1])[::-1], [0.0], s * d2[1]])
    x, y = _place(u, v, shape=shape, nm_per_px=nm_per_px,
                  angle_deg=angle_deg, center_px=center_px)
    return Centerline(
        x, y,
        np.array([len(s)], np.int64),
        np.array([float(interior_angle_deg)]),
        "kinked",
        float("inf"),
    )


# ===== Forward model =====


def _distance_to_line(
    line: Centerline, radii: NDArray, qx: NDArray, qy: NDArray
) -> Tuple[NDArray[np.float64], NDArray[np.float64]]:
    """
    Distance from each query point to a centerline polyline, and the radius there.
    各問い合わせ点から中心線の折れ線までの距離と、そこでの半径。

    Parameters
    ----------
    line
        Centerline whose samples are joined into a polyline.
        サンプルを結んで折れ線とする中心線。
    radii
        Fiber radius at each sample of `line`, in nanometers.
        `line` の各サンプルにおける繊維半径（nm）。
    qx, qy
        Query points in pixel coordinates.
        画素座標の問い合わせ点。

    Returns
    -------
    tuple of ndarray
        Distance in pixels to the nearest point of the polyline, and the
        radius interpolated linearly at that point.
        折れ線上の最近点までの距離（画素）と、その点で線形補間した半径。

    Notes
    -----
    The distance to the nearest *sample* would be up to half a sample step too
    long between two samples, which on a fiber narrower than a pixel is a
    visible fraction of its radius. The nearest sample only selects the two
    segments next to it; the distance is taken to those segments.
    最近傍 *サンプル* までの距離は、2 サンプルの間でサンプル間隔の半分まで長く
    なり、画素より細い繊維ではその半径に対して無視できない。最近傍サンプルは
    隣接する 2 つの線分を選ぶためだけに使い、距離はその線分まで測る。
    """
    x = np.asarray(line.x, dtype=np.float64)
    y = np.asarray(line.y, dtype=np.float64)
    n = x.size
    _d, k = cKDTree(np.column_stack([x, y])).query(np.column_stack([qx, qy]))
    if n == 1:
        return np.hypot(qx - x[0], qy - y[0]), np.full(qx.shape, float(radii[0]))
    best_d = np.full(qx.shape, np.inf)
    best_r = np.zeros(qx.shape)
    for offset in (-1, 0):
        i0 = np.clip(k + offset, 0, n - 2)
        i1 = i0 + 1
        vx, vy = x[i1] - x[i0], y[i1] - y[i0]
        t = np.clip(((qx - x[i0]) * vx + (qy - y[i0]) * vy)
                    / np.maximum(vx * vx + vy * vy, 1e-12), 0.0, 1.0)
        d = np.hypot(qx - x[i0] - t * vx, qy - y[i0] - t * vy)
        better = d < best_d
        best_d = np.where(better, d, best_d)
        best_r = np.where(better, radii[i0] + t * (radii[i1] - radii[i0]), best_r)
    return best_d, best_r


def _tip_reach_nm(tip_radius_nm: float, max_height_nm: float) -> float:
    """
    Lateral reach beyond which a spherical apex cannot touch a surface.
    それより外側では球状の先端が表面に触れ得ない横方向の到達距離。

    Notes
    -----
    An offset ``rho`` from the apex lowers the sphere by
    ``R - sqrt(R^2 - rho^2)``; once that exceeds the tallest feature, the
    substrate under the apex is reached first. A feature at least ``R`` tall
    can meet the sphere anywhere up to its equator, so the reach is then ``R``.
    先端からのずれ ``rho`` で球は ``R - sqrt(R^2 - rho^2)`` 下がる。それが最大の
    高さを超えると、先端直下の基板に先に触れる。高さが ``R`` 以上の形状は球の
    赤道まで触れ得るので、そのとき到達距離は ``R`` である。
    """
    r = float(tip_radius_nm)
    h = float(max_height_nm)
    if h >= r:
        return r
    return float(np.sqrt(2.0 * r * h - h * h))


def dilate_analytic(
    surface_at,
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    tip_radius_nm: float,
    max_height_nm: float,
    near: Optional[NDArray[np.bool_]] = None,
) -> NDArray[np.float64]:
    """
    Image of an analytic surface scanned by a spherical apex, sampled at pixel centres.
    解析的な表面を球状の先端で走査した画像を、画素中心で標本化して返す。

    Parameters
    ----------
    surface_at
        Callable ``(x, y) -> height`` giving the ideal surface in nanometers at
        any point in pixel coordinates (pixel ``(i, j)`` centred at
        ``(j + 0.5, i + 0.5)``); zero on the bare substrate.
        画素座標の任意の点で理想表面の高さ（nm）を返す呼び出し可能オブジェクト
        ``(x, y) -> 高さ``（画素 ``(i, j)`` の中心は ``(j + 0.5, i + 0.5)``）。
        基板上では 0。
    shape
        Image shape ``(rows, columns)``.
        画像の形 ``(行, 列)``。
    nm_per_px
        Pixel size in nanometers.
        画素サイズ（nm）。
    tip_radius_nm
        Apex radius; ``0`` samples the surface itself.
        先端半径。``0`` なら表面そのものを標本化する。
    max_height_nm
        Upper bound on the surface height, which bounds how far from a pixel
        centre the apex can touch.
        表面の高さの上限。先端が画素中心からどこまで離れて触れ得るかを決める。
    near
        Pixels that may lie within reach of the surface; the rest are
        substrate and read 0. ``None`` evaluates every pixel.
        表面に届き得る画素。それ以外は基板で 0 になる。``None`` なら全画素を
        評価する。

    Returns
    -------
    ndarray
        Height image in nanometers.
        ナノメートル単位の高さ画像。

    Notes
    -----
    A scan samples the dilated surface at its pixel positions; it does not
    dilate a pixel-sampled surface. The two differ for any feature that is not
    smooth on the pixel scale: a fiber narrower than a pixel is mostly lost
    between pixel centres before a pixel-grid dilation can widen it, which
    leaves a crest that rises and falls along the fiber with the pixel phase.
    Here the apex height at each pixel centre is the maximum over offsets
    ``q`` of ``surface(p + q) - (R - sqrt(R^2 - |q|^2))``, searched on a grid
    and refined twice around the best offset, each time ten times finer, so
    the result is set by the surface and the probe, not by the pixel grid.
    The refinement assumes a single maximum per pixel, which holds where the
    surface is concave on its support, as a cylinder or a convex ribbon
    section is.
    走査は膨張した表面をその画素位置で標本化するのであって、画素で標本化した
    表面を膨張させるのではない。両者は画素スケールで滑らかでない形状について
    異なる。画素より細い繊維は、画素格子上の膨張で広がる前に画素中心の間で
    ほとんど失われ、繊維に沿って画素の位相とともに上下する稜線が残る。ここでは
    各画素中心での先端の高さを、ずれ ``q`` についての
    ``surface(p + q) - (R - sqrt(R^2 - |q|^2))`` の最大値とし、格子上で探して
    から最良のずれの周りで 2 回、そのたびに 10 倍細かく絞り込む。したがって
    結果は画素格子ではなく表面と探針で決まる。絞り込みは画素ごとに最大値が
    1 つであることを仮定しており、円柱や凸なリボン断面のように表面がその台の
    上で凹であれば成り立つ。
    """
    h, w = shape
    gy, gx = np.mgrid[0:h, 0:w]
    if near is None:
        near = np.ones(shape, dtype=bool)
    qx = gx[near] + 0.5
    qy = gy[near] + 0.5
    image = np.zeros(shape, np.float64)
    r = float(tip_radius_nm)
    if r <= 0:
        image[near] = surface_at(qx, qy)
        return image
    reach = _tip_reach_nm(r, max_height_nm)

    def apex(ox, oy):
        # Apex height for offsets (ox, oy) in nm; offsets beyond the reach lose.
        # ずれ (ox, oy)（nm）での先端の高さ。到達距離の外のずれは選ばれない。
        rho2 = ox * ox + oy * oy
        drop = r - np.sqrt(np.maximum(r * r - rho2, 0.0))
        value = surface_at(qx + ox / nm_per_px, qy + oy / nm_per_px) - drop
        return np.where(rho2 <= reach * reach, value, -np.inf)

    step = max(0.25, reach / 20.0)
    n = int(np.ceil(reach / step))
    best = np.full(qx.shape, -np.inf)
    bx = np.zeros(qx.shape)
    by = np.zeros(qx.shape)
    offsets = [(ox, oy) for oy in np.arange(-n, n + 1) * step
               for ox in np.arange(-n, n + 1) * step if ox * ox + oy * oy <= reach * reach]
    for ox, oy in offsets:
        value = apex(np.full(qx.shape, ox), np.full(qx.shape, oy))
        better = value > best
        best = np.where(better, value, best)
        bx = np.where(better, ox, bx)
        by = np.where(better, oy, by)
    for _level in range(2):
        span, step = 2.0 * step, step / 10.0
        grid = np.arange(-int(round(span / step)), int(round(span / step)) + 1) * step
        cx, cy = bx.copy(), by.copy()
        for dy in grid:
            for dx in grid:
                value = apex(cx + dx, cy + dy)
                better = value > best
                best = np.where(better, value, best)
                bx = np.where(better, cx + dx, bx)
                by = np.where(better, cy + dy, by)
    image[near] = np.maximum(best, 0.0)
    return image


def _per_sample_radii(
    centerlines: Sequence[Centerline],
    diameters_nm: NDArray,
    nm_per_px: float,
    taper_nm: float,
    taper_end_ratio: float,
) -> NDArray[np.float64]:
    """
    Radius at every centerline sample, thinned toward each fiber's ends.
    各中心線サンプルにおける半径。繊維の両端に向かって細くする。

    Notes
    -----
    A real fibril does not stop at full thickness: it thins over its last tens
    of nanometers, and after tip dilation that thin end becomes a low, broad
    foot. Segmentation admits the foot, thinning follows the foot's medial
    axis instead of the ridge, and a false kink appears at the end. A model
    with a square-ended cylinder cannot produce that failure, so a negative
    control built from square-ended cylinders would certify a detector that
    still fails on real ends.
    実際のフィブリルは最大太さのまま終わらない。末端数十 nm にわたって細くなり、
    探針 dilation を経るとその細い末端は低く広い裾になる。セグメンテーションは
    その裾を取り込み、細線化は稜線ではなく裾の medial axis を辿り、末端に偽の
    キンクが現れる。角で終わる円柱のモデルではこの故障を作れないため、そうした
    モデルで組んだ負例対照は、実際の末端では失敗する検出器を合格させてしまう。
    """
    out: list = []
    for line, diameter in zip(centerlines, diameters_nm):
        steps = np.hypot(np.diff(line.x), np.diff(line.y)) * nm_per_px
        s = np.concatenate([[0.0], np.cumsum(steps)])
        if taper_nm > 0:
            frac = np.clip(np.minimum(s, s[-1] - s) / taper_nm, 0.0, 1.0)
            scale = taper_end_ratio + (1.0 - taper_end_ratio) * frac
        else:
            scale = np.ones_like(s)
        out.append(0.5 * float(diameter) * scale)
    return np.concatenate(out)


def self_affine_field(
    shape: Tuple[int, int],
    nm_per_px: float,
    outer_scale_nm: float,
    hurst: float,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """
    Unit-variance background roughness with a power-law spectrum.
    べき乗則スペクトルを持つ、分散 1 の背景粗さ。

    Parameters
    ----------
    shape
        Field shape ``(rows, columns)``.
        場の形 ``(行, 列)``。
    nm_per_px
        Pixel size, so the outer scale can be given in nanometers.
        画素サイズ。外側スケールを nm で与えられるようにするため。
    outer_scale_nm
        Length beyond which the spectrum flattens, bounding the power at
        large scales.
        これを超えるとスペクトルが平坦になる長さ。大スケール側の power を有界に
        する。
    hurst
        Roughness exponent; larger values give a smoother surface.
        粗さ指数。大きいほど滑らかな面になる。
    rng
        Generator supplying the white field.
        白色場を供給する乱数生成器。

    Returns
    -------
    ndarray
        Field of unit standard deviation, to be scaled by the caller.
        標準偏差 1 の場。呼び出し側で振幅を掛ける。

    Notes
    -----
    A single-scale field — white noise through one Gaussian filter — is the
    obvious model and the wrong one. Its autocorrelation swings negative about
    one correlation length out, and once the pipeline's background stage
    subtracts a smoothed copy the negative lobe deepens, which no real scan
    shows: a real background decays slowly and stays positive out to several
    fiber widths because its power is spread over many scales. Matching that
    matters because the mask boundary is set by the background near the fiber,
    and a background that reverses sign at 30 nm pushes the two sides of a
    fiber the same way instead of opposite ways.
    単一スケールの場——白色ノイズにガウス平滑を 1 回——は自明なモデルだが誤りで
    ある。その自己相関は相関長の 1 倍付近で負に振れ、パイプラインの背景段が平滑
    コピーを差し引くと負の谷はさらに深くなる。実スキャンにこれは現れない。実際
    の背景は power が多数のスケールに分布しているため、繊維幅の数倍まで緩やかに
    減衰して正のままである。マスク境界は繊維近傍の背景で決まるため、30 nm で符号
    が反転する背景は繊維の両側を逆向きではなく同じ向きに押してしまう。ここを
    合わせることには意味がある。
    """
    h, w = shape
    ky = np.fft.fftfreq(h, d=nm_per_px)[:, None]
    kx = np.fft.fftfreq(w, d=nm_per_px)[None, :]
    k2 = ky ** 2 + kx ** 2
    k0 = 1.0 / max(outer_scale_nm, nm_per_px)
    # Self-affine surface: PSD proportional to k^(-2(1+H)) above the outer
    # scale, flattened below it so the variance stays finite.
    # 自己アフィン面。外側スケールより上では PSD が k^(-2(1+H)) に比例し、
    # それより下では平坦にして分散を有限に保つ。
    psd = (k2 + k0 * k0) ** (-(1.0 + hurst))
    spectrum = np.fft.fft2(rng.normal(0.0, 1.0, (h, w))) * np.sqrt(psd)
    field = np.real(np.fft.ifft2(spectrum))
    field -= field.mean()
    return field / max(float(field.std()), 1e-12)


def render_scan(
    centerlines: Sequence[Centerline],
    *,
    shape: Tuple[int, int],
    nm_per_px: float,
    fiber_diameter_nm: float | Sequence[float] = 3.0,
    taper_nm: float = 0.0,
    taper_end_ratio: float = 0.2,
    tip_radius_nm: float = 10.0,
    noise_nm: float = 0.05,
    line_noise_nm: float = 0.0,
    tilt_nm: float = 1.0,
    roughness_nm: float = 0.0,
    roughness_corr_nm: float = 60.0,
    roughness_hurst: float = 0.5,
    seed: int = 0,
) -> SyntheticScan:
    """
    Render centerlines into an AFM-like height image.
    中心線を AFM 風の高さ画像に描画する。

    Parameters
    ----------
    centerlines
        Ground-truth curves to draw. Two overlapping curves produce a
        crossing, which is where the pipeline cuts the skeleton at a branch
        point; a single curve isolates the detector from that.
        描画する真値曲線。2 本を重ねると交差ができ、そこでパイプラインは分岐点
        でスケルトンを切断する。1 本ならその影響から切り離せる。
    shape
        Image shape ``(rows, columns)``.
        画像の形 ``(行, 列)``。
    nm_per_px
        Pixel size in nanometers.
        画素サイズ（nm）。
    fiber_diameter_nm
        Diameter of the modelled cylinder lying on the substrate; the ideal
        apparent height equals this value. A sequence gives one diameter per
        centerline, so a crossing can pair a tall fiber with a short one — the
        case where the merged mask is asymmetric about both ridges.
        基板上に横たわる円柱の直径。理想的な見かけ高さはこの値に等しい。列を
        渡すと中心線ごとに直径を指定でき、高い繊維と低い繊維の交差——融合した
        マスクがどちらの稜線に対しても非対称になる場合——を構成できる。
    taper_nm
        Length over which each fiber thins toward its ends; ``0`` leaves a
        square-ended cylinder.
        各繊維が末端に向かって細くなる長さ。``0`` なら角で終わる円柱になる。
    taper_end_ratio
        Fraction of the full diameter retained at the very end of a fiber.
        繊維の末端で保持する直径の割合。
    tip_radius_nm
        Probe apex radius; ``0`` renders with an ideal (infinitely sharp)
        probe, the control that isolates tip broadening from everything else.
        探針先端半径。``0`` は理想（無限に鋭い）探針での描画で、探針拡がりだけ
        を他から切り分ける対照条件になる。
    noise_nm
        Standard deviation of independent per-pixel noise.
        画素ごとに独立なノイズの標準偏差。
    line_noise_nm
        Standard deviation of a per-scan-line height offset. This is the slow
        instrumental artifact a real scan carries and an independent per-pixel
        model does not reproduce.
        走査線ごとの高さオフセットの標準偏差。実スキャンが持つ低周波の装置
        アーティファクトで、画素独立モデルでは再現できない。
    tilt_nm
        Peak-to-peak tilt of the background plane, so background calibration
        has something to remove.
        背景平面の傾斜（全幅）。背景補正が除去すべき対象を持つようにする。
    roughness_nm
        Standard deviation of spatially correlated background roughness:
        substrate texture plus the residual of an imperfect background
        subtraction. Independent per-pixel noise cannot stand in for it. Noise
        that is uncorrelated between neighbouring pixels averages out inside
        the segmenter's window, so it moves a mask boundary hardly at all;
        roughness correlated over a fiber width or two displaces the whole
        boundary to one side, which is what pulls a medial axis off the ridge.
        空間相関を持つ背景粗さの標準偏差。基板のテクスチャと、不完全な背景差し
        引きの残差である。画素独立ノイズでは代用できない。隣接画素間で無相関な
        ノイズはセグメンタの窓の中で平均されてしまい、マスク境界をほとんど動か
        さないが、繊維幅の 1〜2 倍にわたって相関した粗さは境界全体を片側へずら
        し、これが medial axis を稜線から引き離す。
    roughness_corr_nm
        Outer scale of that roughness: the length beyond which its spectrum
        flattens.
        その粗さの外側スケール。これを超えるとスペクトルが平坦になる長さ。
    roughness_hurst
        Roughness exponent of the self-affine background; larger is smoother.
        自己アフィン背景の粗さ指数。大きいほど滑らか。
    seed
        Seed for the noise generator.
        ノイズ生成の乱数シード。

    Returns
    -------
    SyntheticScan
        Image plus the ground truth needed to score a detection against it.
        画像と、検出結果を採点するために必要な真値。

    Raises
    ------
    ValueError
        If `centerlines` is empty.

    Notes
    -----
    The tip-dilated surface is evaluated at each pixel centre, as a scan
    samples it (see `dilate_analytic`). For a cylinder the dilation has a
    closed form, so no search over probe offsets is needed. Dilating a
    pixel-sampled cylinder instead loses most of a fiber narrower than a pixel
    between the pixel centres and leaves a crest that rises and falls with the
    pixel phase, which a detector would then be scored against.
    探針で膨張した表面を、走査が標本化するのと同じく各画素中心で評価する
    （`dilate_analytic` 参照）。円柱では膨張に閉じた式があるため、探針のずれに
    ついての探索は要らない。画素で標本化した円柱を膨張させると、画素より細い
    繊維の大半が画素中心の間で失われ、画素の位相とともに上下する稜線が残り、
    検出器はそれに対して採点されてしまう。
    """
    if not centerlines:
        raise ValueError("at least one centerline is required")
    h, w = shape
    diameters = np.broadcast_to(
        np.atleast_1d(np.asarray(fiber_diameter_nm, dtype=float)),
        (len(centerlines),),
    )
    gy, gx = np.mgrid[0:h, 0:w]
    qx = gx.ravel() + 0.5
    qy = gy.ravel() + 0.5
    tip = float(tip_radius_nm)
    image = np.zeros((h, w), np.float64)
    for line, diameter in zip(centerlines, diameters):
        radii = _per_sample_radii([line], np.array([diameter]), nm_per_px,
                                  taper_nm, taper_end_ratio)
        dist_px, r = _distance_to_line(line, radii, qx, qy)
        d_nm = (dist_px * nm_per_px).reshape(h, w)
        r = r.reshape(h, w)
        # A cylinder of radius r lies on the substrate with its axis at height
        # r, so its ridge stands at the diameter. A sphere of radius R touching
        # it has its centre r + R from the axis, so the apex at lateral
        # distance d stands at r + sqrt((r + R)^2 - d^2) - R, until the apex
        # meets the substrate; R = 0 gives the bare cylinder. The radius comes
        # from the nearest point of the centerline, so it can thin along a
        # tapering fiber and differ between two crossing ones.
        # 半径 r の円柱は軸を高さ r にして基板上に横たわるので、稜線は直径の
        # 高さにある。これに触れる半径 R の球の中心は軸から r + R 離れるので、
        # 横方向の距離 d での先端の高さは、先端が基板に触れるまで
        # r + sqrt((r + R)^2 - d^2) - R である。R = 0 なら円柱そのもの。半径は
        # 中心線上の最近点から取るので、先細りする繊維に沿って細くしたり、
        # 交差する 2 本で変えたりできる。
        surface = r + np.sqrt(np.maximum((r + tip) ** 2 - d_nm ** 2, 0.0)) - tip
        surface[d_nm >= r + tip] = 0.0
        # Scanning the union of the fibers gives the higher of their images.
        # 繊維の和集合を走査すると、それぞれの像の高い方になる。
        image = np.maximum(image, np.maximum(surface, 0.0))

    rng = np.random.default_rng(seed)
    if tilt_nm:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        image = image + tilt_nm * (0.66 * xx / max(w - 1, 1) + 0.34 * yy / max(h - 1, 1))
    if roughness_nm > 0:
        field = self_affine_field(shape, nm_per_px, roughness_corr_nm,
                                  roughness_hurst, rng)
        image = image + field * roughness_nm
    if line_noise_nm:
        image = image + rng.normal(0.0, line_noise_nm, (h, 1))
    if noise_nm:
        image = image + rng.normal(0.0, noise_nm, (h, w))

    return SyntheticScan(
        image=image,
        nm_per_px=float(nm_per_px),
        centerlines=tuple(centerlines),
        fiber_diameters_nm=tuple(float(d) for d in diameters),
        taper_nm=float(taper_nm),
        taper_end_ratio=float(taper_end_ratio),
        tip_radius_nm=float(tip_radius_nm),
        noise_nm=float(noise_nm),
        line_noise_nm=float(line_noise_nm),
        tilt_nm=float(tilt_nm),
        roughness_nm=float(roughness_nm),
        roughness_corr_nm=float(roughness_corr_nm),
        roughness_hurst=float(roughness_hurst),
        seed=int(seed),
    )


def write_afm_text(scan: SyntheticScan, path: str) -> str:
    """
    Write a scan as a headerless CSV the project's text reader accepts.
    走査画像を、本プロジェクトのテキストリーダが受け付けるヘッダ無し CSV として
    書き出す。

    Notes
    -----
    No instrument header is written, so `afm_io.read_scan_size` finds no scan
    size and the caller must pass `scan_size_um` to `pipeline.process_file`.
    That is deliberate: a fabricated Shimadzu header would make the file look
    like an instrument export it is not.
    装置ヘッダは書かないため `afm_io.read_scan_size` は走査範囲を見つけられず、
    呼び出し側が `pipeline.process_file` に `scan_size_um` を渡す必要がある。
    これは意図的で、偽の島津ヘッダを書けば装置エクスポートでないファイルを
    そう見せかけてしまう。
    """
    np.savetxt(path, scan.image, delimiter=",", fmt="%.4f")
    return path
