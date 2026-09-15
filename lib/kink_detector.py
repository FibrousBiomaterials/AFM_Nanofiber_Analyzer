"""
Detect kinks on the line of each fiber traced from an AFM skeleton image.
AFM の骨格画像から追跡した各繊維の線の上でキンクを検出する。

A kink is a bend concentrated within about one apparent fiber width W, where
the fiber's heading turns by more than its own smooth curvature there accounts
for. It is judged on the fiber's half-maximum centerline (`lib.centerline`),
the same line the fiber is later drawn and measured along, so a bend the
skeleton makes only because the mask is asymmetric about the fiber is not
reported. Every length the rule uses is a multiple of W, so the rule means the
same thing at any scan size.
キンクとは、見かけの繊維幅 W 1 本分程度の範囲に集中した折れで、繊維の向きが、
その場所での繊維自身の滑らかな曲率では説明できないほど回る点である。判定は繊維の
半値中点線（`lib.centerline`）上で行う。これは後で繊維を描画・計測するのと同じ線で
あり、マスクが繊維に対して非対称なためだけにスケルトンが作る折れは報告されない。
規則が使う長さはすべて W の倍数であり、どの走査サイズでも同じ意味を持つ。

Bundles of format 1.0 were judged by an earlier rule, which decomposed the
skeleton track into a polyline and tested the angle at each vertex. It is kept
as `KinkDetector.kinks_and_decomposed_from_track` only so that a fibril
reconnected in such a bundle is judged by the rule that produced the rest of
its image (see `bundle_schema.centerline_from_meta`).
形式 1.0 のバンドルは以前の規則で判定されている。スケルトントラックを折れ線に
分解し、各頂点の角度を検定する規則である。これを
`KinkDetector.kinks_and_decomposed_from_track` として残すのは、そのような
バンドルで再結合したフィブリルを、画像の他の部分を生んだのと同じ規則で判定する
ためだけである（`bundle_schema.centerline_from_meta` 参照）。
"""

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np
from numpy.typing import NDArray

from . import imp_tools
from .centerline import _smooth_extrapolated, half_max_centerline
from .processed_image import ProcessedImage

logger = logging.getLogger(__name__)

# ----- The excess-turning rule ------------------------------------------------
# Every length below is a multiple of the fiber's apparent width W
# (`centerline.measure_apparent_width`, the full width at half maximum of its
# height cross-section). W is also the resolution of the image: the probe
# broadens every fiber to about W, so a bend occupies about W of the line
# however sharply the fiber itself turned, and two bends much closer than W
# cannot be told apart.
# 以下の長さはすべて繊維の見かけ幅 W（`centerline.measure_apparent_width`、
# 高さ断面の半値全幅）の倍数である。W は画像の分解能でもある。探針はどの繊維も
# 約 W に広げるため、繊維自体がどれほど鋭く曲がっても折れは線の上で約 W を占め、
# W よりずっと近い 2 つの折れは見分けられない。
#
# The values follow from W being the resolution; they were checked, not
# fitted, against a visual reference marked by eye on the height images of the
# bundled scans. Changing any one of them to the alternative named in its
# comment moved the clear reference kinks found from 60 of 64 to between 59
# and 62, and the false detections from 60 to between 45 and 81.
# 値は W が分解能であることから決まるもので、同梱スキャンの高さ画像に目視で印を
# 付けた基準に対して確認はしたが、合わせ込んではいない。どれか 1 つをコメントに
# 挙げた代替値に変えても、見つかる明瞭な基準キンクは 64 件中 60 件から 59〜62 件の
# 間で動くだけで、誤検出は 60 件から 45〜81 件の間で動いた。

# Half-length c of the window a bend's turning is summed over. The probe
# spreads a corner's turning over about one W of line, so +-0.75 W holds it
# whole with a margin for where its centre is estimated. Alternatives 0.6 and
# 0.9 W.
# 折れの回転を合計する窓の片側長 c。探針はコーナーの回転を線の上で約 1 W に
# 広げるため、±0.75 W なら中心推定の誤差を見込んでもそれを丸ごと含む。代替値は
# 0.6 W と 0.9 W。
_CORE_WIDTHS = 0.75

# Length f of the flank beyond each side of that window, on which the fiber's
# own turning rate is read. The rate of the less-curved flank, times the
# window length, is subtracted from the window's turning: an arc turns at the
# same rate inside the window and on both flanks and so leaves nothing, while
# a corner between two straight arms keeps all of its turning. The smaller
# flank is used because a corner where a curve ends has one curved flank and
# one straight one. Alternatives 0.75 and 1.5 W.
# 窓の両外側で、繊維自身の回転率を読む脇の長さ f。曲がりの小さい側の脇の回転率に
# 窓の長さを掛けたものを窓の回転から差し引く。円弧は窓の中でも両脇でも同じ率で
# 回るため何も残らず、2 本のまっすぐな腕に挟まれたコーナーは回転をすべて残す。
# 小さい側を使うのは、曲線の終わりにあるコーナーでは脇の一方が曲がり、もう一方が
# まっすぐだからである。代替値は 0.75 W と 1.5 W。
_FLANK_WIDTHS = 1.0

# Gaussian sigma the heading is smoothed with before it is differentiated.
# Wiggles of the line shorter than a quarter width are not the fiber's shape
# (see `centerline._FRAME_SIGMA_WIDTHS`). Alternatives 0.15 and 0.35 W.
# 微分する前に向きを平滑化するガウスの sigma。1/4 幅より短い線の揺れは繊維の形
# ではない（`centerline._FRAME_SIGMA_WIDTHS` 参照）。代替値は 0.15 W と 0.35 W。
_HEADING_SIGMA_WIDTHS = 0.25

# A bend whose centre lies closer than this to an end of the line is not
# judged. One of its arms is then shorter than the visual reference required
# before it called a bend clear, and many track ends are not fiber ends but
# cuts at a crossing (46-68 % lie within 3 px of a branch point on the bundled
# scans), where the line bends with the junction's skirt. Such bends are
# returned separately so they can be shown as not judged, rather than hidden.
# Alternatives 1.0 W, which raised the false detections from 60 to 75 without
# finding another clear kink, and 2.0 W, which lowered them to 47 but no
# longer judged synthetic corners 1.5-2 W from an end.
# 線の端からこれより近くに中心がある折れは判定しない。そのとき片方の腕は、目視
# 基準が折れを明瞭と呼ぶのに要した長さに満たない。またトラック端の多くは繊維の
# 終端ではなく交差での切断であり（同梱スキャンでは 46〜68 % が分岐点から 3 px
# 以内）、そこでは線が分岐部の裾とともに曲がる。こうした折れは隠さず、判定しな
# かったものとして示せるよう別に返す。代替値は 1.0 W（明瞭なキンクを 1 件も
# 増やさずに誤検出を 60 件から 75 件に増やした）と 2.0 W（誤検出を 47 件に減らした
# が、端から 1.5〜2 W の合成コーナーを判定しなくなった）。
_END_WIDTHS = 1.5

# Two bends closer than this are one bend, and the stronger is kept.
# Alternatives 0.5 and 1.0 W.
# これより近い 2 つの折れは 1 つの折れとし、強い方を残す。代替値は 0.5 W と 1.0 W。
_SUPPRESS_WIDTHS = 0.75

# Arc-length step, in pixels, the heading is resampled at: a sampling step far
# below every length above, not a scale of the rule.
# 向きを再サンプリングする弧長の間隔（画素）。上のどの長さよりもずっと短い
# サンプリング間隔であり、規則の尺度ではない。
_HEADING_STEP_PX = 0.5

# A curvature maximum is a candidate only where it reaches this fraction of the
# mean curvature a bend exactly at the threshold has across the window.
# 曲率の極大は、しきい値ちょうどの折れが窓全体で持つ平均曲率のこの割合に達した
# ときだけ候補とする。
_CURVATURE_FLOOR_FRAC = 0.5

# The bundle stores interior angles strictly inside (0, pi). A fold of 180
# degrees or more, where the line doubles back within the window, is stored
# as this small angle rather than as zero or a negative one.
# バンドルは内角を開区間 (0, pi) で保存する。窓の中で線が折り返す 180 度以上の
# 折れは、0 や負の角度ではなくこの小さな角度で保存する。
_MIN_INTERIOR_ANGLE = 1e-6


def _heading_profile(
    x: NDArray, y: NDArray, width: float,
) -> Optional[Tuple[NDArray, NDArray, float, NDArray, NDArray]]:
    """
    Heading of a line, resampled at a fixed arc-length step and smoothed.
    一定の弧長間隔で再サンプリングし、平滑化した線の向き。

    Returns ``(orig, s, length, sm, heading)``: the indices of the line points
    kept after dropping repeated points, their arc lengths, the total length,
    the arc lengths the heading is sampled at, and the smoothed, unwrapped
    heading in radians. ``None`` when the line has no length to sample.
    ``(orig, s, length, sm, heading)`` を返す。重複点を除いた後に残る線の点の
    インデックス、その弧長、全長、向きをサンプリングした弧長、平滑化してアンラップ
    した向き（ラジアン）である。サンプリングする長さが無ければ ``None``。

    The heading is padded by linear extrapolation before smoothing
    (`centerline._smooth_extrapolated`), so a straight end does not read as
    turning toward its last sample.
    向きは平滑化の前に線形外挿で延長する（`centerline._smooth_extrapolated`）。
    これにより、まっすぐな端が最後のサンプルへ向かって回っていると読まれない。
    """
    seg = np.hypot(np.diff(x), np.diff(y))
    keep = np.concatenate([[True], seg > 1e-9])
    orig = np.nonzero(keep)[0]
    x, y = x[keep], y[keep]
    if x.size < 2:
        return None
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    length = float(s[-1])
    su = np.arange(0.0, length + 1e-9, _HEADING_STEP_PX)
    if su.size < 2:
        return None
    xu = np.interp(su, s, x)
    yu = np.interp(su, s, y)
    theta = np.unwrap(np.arctan2(np.diff(yu), np.diff(xu)))
    sm = su[:-1] + 0.5 * _HEADING_STEP_PX
    heading = _smooth_extrapolated(
        theta, _HEADING_SIGMA_WIDTHS * width / _HEADING_STEP_PX,
    )
    return orig, s, length, sm, heading


class KinkDetector:
    """
    Detect kinks on the half-maximum centerline of each traced skeleton component.
    追跡した各スケルトン成分の半値中点線上でキンクを検出するクラス。

    Attributes
    ----------
    threshold_distance
        Perpendicular tolerance (px) of the polyline decomposition the rule of
        bundle format 1.0 measured angles on. Read only by
        `kinks_and_decomposed_from_track`; the current rule does not use it.
        バンドル形式 1.0 の規則が角度を測った折れ線分解の垂直許容量 (px)。
        `kinks_and_decomposed_from_track` だけが読み、現行の規則は使わない。
    threshold_angle_from_decomposed_indices
        Interior-angle threshold (radian). A bend is a kink when the fiber's
        heading turns, beyond its own curvature there, by at least ``pi``
        minus this. The name is historical; both rules read it.
        内角しきい値（ラジアン）。繊維の向きが、その場所での繊維自身の曲率を
        超えて ``pi`` からこれを引いた角度以上回る折れをキンクとする。名前は歴史的
        なもので、両方の規則が読む。
    threshold_angle_corner
        Angle threshold (radian) for corner detection utility.
        コーナー検出補助で使う角度しきい値（ラジアン）。
    k
        Point offset used when computing local corner angles.
        局所角度を計算する際の前後点オフセット。
    """
    def __init__(self,
                 threshold_distance: float = 3,
                 threshold_angle_from_decomposed_indices: float = 5 * np.pi / 6,
                 threshold_angle_corner: float = 5 * np.pi / 6,
                 k: int = 10) -> None:
        """
        Initialize detector thresholds and angle settings.
        検出に使うしきい値と角度設定を初期化する。

        Parameters
        ----------
        threshold_distance
            Minimum farthest distance to split a segment in the polyline rule
            of bundle format 1.0.
            バンドル形式 1.0 の折れ線規則で区間分割を行う最遠距離の最小値。
        threshold_angle_from_decomposed_indices
            Interior-angle threshold (radian) for kink classification; the
            default, 150 degrees, makes a kink a turn of at least 30 degrees.
            kink 判定に使う内角しきい値（ラジアン）。既定の 150 度では、30 度以上の
            回転をキンクとする。
        threshold_angle_corner
            Angle threshold (radian) for corner detection.
            コーナー検出に使う角度しきい値（ラジアン）。
        k
            Index distance for local angle calculation.
            局所角度計算で使うインデックス間隔。
        """
        self.threshold_distance = threshold_distance
        self.threshold_angle_from_decomposed_indices = threshold_angle_from_decomposed_indices
        # Set angle threshold for corner detection helper.
        self.threshold_angle_corner = threshold_angle_corner
        # Set point offset used by corner-angle computation.
        self.k = k

    def __call__(self, image: ProcessedImage) -> None:
        """
        Run kink detection and store results into the ProcessedImage object.
        kink 検出を実行し、結果を ProcessedImage オブジェクトへ保存する。

        Parameters
        ----------
        image
            Input image object containing a skeleton image and result fields.
            骨格画像と結果保存先フィールドを持つ入力画像オブジェクト。

        Returns
        -------
        None
            Results are written to attributes of `image`.
            結果は `image` の属性に書き込まれる。

        Raises
        ------
        ValueError
            If `image.skeleton_image` is None, i.e. skeletonization has not
            been run on this image yet, or if `image.calibrated_image` is
            None, which the centerline is placed on.
        Exception
            Re-raises any exception unchanged after logging its traceback.

        Notes
        -----
        Reads `image.skeleton_image`, `image.calibrated_image` and `image.bp`
        (the latter recomputed from the skeleton when absent); writes
        `image.kink_indices_by_label`, `image.kink_angles_by_label`,
        `image.unjudged_indices_by_label`, `image.decomposed_indices_by_label`
        (empty), `image.all_kink_coordinates`, `image.all_kink_angles`,
        `image.unjudged_point_coordinates`, and
        `image.decomposed_point_coordinates` (empty).
        """
        # Fail loudly at the stage boundary instead of deep inside imp_tools.
        if image.skeleton_image is None:
            raise ValueError(
                "KinkDetector requires image.skeleton_image; "
                "run Skeletonizer on the image first."
            )
        if image.calibrated_image is None:
            raise ValueError(
                "KinkDetector requires image.calibrated_image to place each "
                "fiber's centerline; run BGCalibrator on the image first."
            )
        try:
            # Remove branch points and L-corners for cleaner line tracking.
            no_bp_skel = imp_tools.remove_bp(image.skeleton_image)
            no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
            # Split skeleton into connected components (labels).
            nLabels, label_image, data, center = cv2.connectedComponentsWithStats(no_Lcorner_skel)
            # Branch points mark where the height belongs to more than one
            # fiber, so the centerline is not measured next to them.
            # 分岐点は高さが複数の繊維に属する場所を示すため、中心線はそのそばで
            # 位置を測らない。
            branch_points = getattr(image, "bp", None)
            if branch_points is None:
                branch_points = imp_tools.branchedPoints(image.skeleton_image)

            # Flat arrays the pipeline writes into the bundle.
            # パイプラインがバンドルへ書く平坦な配列。
            all_kink_coordinate_x: List[int] = []
            all_kink_coordinate_y: List[int] = []
            all_kink_angles: List[float] = []
            unjudged_point_x: List[int] = []
            unjudged_point_y: List[int] = []
            for label in range(1, nLabels):
                x, y, w, h, area = data[label]
                sub_label = label_image[y:y+h, x:x+w]
                target_image = (sub_label == label).astype(np.uint8)
                try:
                    _xtrack_local, _ytrack_local = imp_tools.tracking(target_image)
                except ValueError as exc:
                    if "tracking requires exactly 2 endpoints" not in str(exc):
                        raise
                    logger.info(
                        "Skipping untraceable skeleton component %s: %s",
                        label, exc,
                    )
                    continue
                # Tracking returns bounding-box-local coordinates, so restore image coordinates.
                # tracking 結果は BBox ローカル座標なので元画像座標に戻す。
                _xtrack = _xtrack_local + x
                _ytrack = _ytrack_local + y
                # Judge bends on the fiber's centerline rather than on the
                # skeleton pixels. The line has one point per skeleton pixel,
                # so the indices found on it are stored at skeleton
                # coordinates below, where a reader's feature lookup expects
                # them.
                # 折れはスケルトン画素ではなく繊維の中心線上で判定する。線は
                # スケルトン画素ごとに 1 点なので、線上で得たインデックスは下で
                # スケルトン座標として保存され、読み取り側の特徴点照合と一致する。
                line_x, line_y, width = half_max_centerline(
                    image.calibrated_image, _xtrack, _ytrack, branch_points,
                    return_width=True,
                )
                kink_indices, kink_angles, unjudged_indices = self.kinks_on_line(
                    line_x, line_y, width,
                )

                # Store per-label arrays for fiber-instance generation.
                image.kink_indices_by_label[label]       = kink_indices
                image.kink_angles_by_label[label]        = kink_angles
                image.unjudged_indices_by_label[label]   = unjudged_indices
                image.decomposed_indices_by_label[label] = np.zeros(0, dtype=np.intp)

                all_kink_coordinate_x.extend(_xtrack[kink_indices])
                all_kink_coordinate_y.extend(_ytrack[kink_indices])
                all_kink_angles.extend(list(kink_angles))
                unjudged_point_x.extend(_xtrack[unjudged_indices])
                unjudged_point_y.extend(_ytrack[unjudged_indices])

            image.all_kink_coordinates = (np.array(all_kink_coordinate_x), np.array(all_kink_coordinate_y))
            image.all_kink_angles = np.array(all_kink_angles)
            image.unjudged_point_coordinates = (np.array(unjudged_point_x), np.array(unjudged_point_y))
            # Nothing is decomposed any more; the bundle's `dp` key is kept
            # empty so every bundle carries the same required keys.
            # もう何も分解しない。どのバンドルも同じ必須キーを持つよう、バンドルの
            # `dp` キーは空のまま残す。
            image.decomposed_point_coordinates = (
                np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
            )

        except Exception:
            # Log the full traceback before re-raising the original exception
            # unchanged (bare `raise` preserves the exception and its chain).
            logger.exception("Kink detection failed")
            raise

    def kinks_on_line(
        self,
        xline: NDArray,
        yline: NDArray,
        width_px: float,
    ) -> Tuple[NDArray, NDArray, NDArray]:
        """
        Judge the kinks on one fiber's line by the excess-turning rule.
        1 本の繊維の線上のキンクを超過回転規則で判定する。

        Public so a caller can judge a line the bundle does not contain -- a
        reconnected fibril, a height-band sub-fiber -- by the rule `__call__`
        applied to every traced component.
        公開しているのは、バンドルに含まれない線（再結合フィブリル、高さ帯の
        サブファイバー）を、`__call__` が追跡した全成分に適用したのと同じ規則で
        判定できるようにするためである。

        Parameters
        ----------
        xline
            X coordinates of the ordered line in pixels: a fiber's
            half-maximum centerline (`centerline.half_max_centerline`).
            画素単位の順序付きの線の x 座標。繊維の半値中点線
            （`centerline.half_max_centerline`）。
        yline
            Y coordinates of the same line.
            同じ線の y 座標。
        width_px
            The fiber's apparent width W in pixels, which every length of the
            rule is a multiple of.
            繊維の見かけ幅 W（画素）。規則の長さはすべてその倍数である。

        Returns
        -------
        tuple of ndarray
            ``(kink_indices, kink_angles, unjudged_indices)``, indices into
            the line in line order. ``kink_angles`` are interior angles in
            radians, ``pi`` minus the excess turning defined in the Notes.
            ``unjudged_indices`` are the bends that reached the threshold
            within 1.5 W of an end of the line, where the rule does not judge.
            ``(kink_indices, kink_angles, unjudged_indices)``。いずれも線の点を
            指すインデックスで、線の順に並ぶ。``kink_angles`` はラジアンの内角で、
            ``pi`` から Notes で定義する超過回転を引いた値。``unjudged_indices``
            は線の端から 1.5 W 以内でしきい値に達した、規則が判定しない折れ。

        Notes
        -----
        The heading of the line is resampled every 0.5 px of arc length and
        smoothed over W/4. At a position p, the turning within the window
        ``[p - c, p + c]`` (c = 0.75 W) is compared with the fiber's own
        turning rate on the flank of length W just outside it on each side.
        The background rate is the smaller of the two flank rates in the
        sense of the window's turning, or zero when either flank turns the
        other way, and the **excess turning** is the window's turning minus
        ``2c`` times that rate. A bend is a kink when its excess is at least
        ``pi`` minus the interior-angle threshold: 30 degrees at the default
        150.
        線の向きを弧長 0.5 px ごとに再サンプリングし、W/4 で平滑化する。位置 p で、
        窓 ``[p - c, p + c]``（c = 0.75 W）内の回転を、そのすぐ外側の両脇（長さ
        W）での繊維自身の回転率と比べる。背景の回転率は、窓の回転と同じ向きで測った
        両脇の率の小さい方とし、どちらかの脇が逆向きに回るなら 0 とする。
        **超過回転**は窓の回転から ``2c`` × その率を引いたものである。超過回転が
        ``pi`` から内角しきい値を引いた角度（既定の 150 度では 30 度）以上の折れを
        キンクとする。

        The window turning alone is not the test because it reports curvature
        as well as kinks: an arc of radius 3 W already turns 29 degrees over
        1.5 W. The flanks are what separate the two. An arc turns at the same
        rate inside the window and beside it, so its excess is near zero,
        while a corner between straight arms keeps all of its turning. On
        synthetic arcs and meanders (2 nm pixels, W = 8 px) the rule
        reported 12 bends where the polyline rule it replaces reported 31.
        窓の回転だけを検定にしないのは、それがキンクだけでなく曲率も報告するため
        である。半径 3 W の円弧は 1.5 W で既に 29 度回る。両者を分けるのが脇である。
        円弧は窓の中でも脇でも同じ率で回るため超過はほぼ 0 になり、まっすぐな腕に
        挟まれたコーナーは回転をすべて残す。合成の円弧と蛇行（画素 2 nm、W = 8 px）
        では、この規則が報告した折れは 12 件で、置き換えた折れ線規則は 31 件で
        あった。

        Candidate positions are the maxima of the curvature, and, where no
        such maximum passes within 0.75 W, the maxima of the window turning
        itself: a corner whose curvature peak noise splits in two, or whose
        turning runs straight into a curve, has no single curvature maximum
        at its centre, and on the bundled scans two visible corners were
        missed without this second kind of candidate. Candidates closer than
        0.75 W are one bend, and the one with the larger excess is kept.
        候補位置は曲率の極大とし、0.75 W 以内にそうした極大が通過していない場所
        では、窓の回転そのものの極大も加える。ノイズで曲率のピークが 2 つに割れた
        コーナーや、回転がそのまま曲線へ続くコーナーは、中心に曲率の極大を 1 つも
        持たないためである。同梱スキャンでは、この 2 種目の候補が無いと、目に見える
        コーナーを 2 件見落とした。0.75 W より近い候補は 1 つの折れとし、超過回転の
        大きい方を残す。

        A bend whose centre lies within 1.5 W of an end is returned in
        ``unjudged_indices`` instead of being judged (see `_END_WIDTHS`), and
        nothing is measured where the window does not fit on the line.
        端から 1.5 W 以内に中心がある折れは、判定せずに ``unjudged_indices`` で
        返す（`_END_WIDTHS` 参照）。窓が線に収まらない位置では何も測らない。

        The value reported is the excess, not the whole turning, because it is
        the part of the bend the fiber's curvature does not account for; on a
        corner set in a curve it is smaller than the total turning there.
        報告する値は回転全体ではなく超過回転である。それが、繊維の曲率では説明
        できない部分だからである。曲線の中にあるコーナーでは、その場所の回転全体
        より小さくなる。
        """
        empty = np.zeros(0, dtype=np.intp)
        nothing = (empty, np.zeros(0, dtype=np.float64), empty)
        x = np.asarray(xline, dtype=np.float64)
        y = np.asarray(yline, dtype=np.float64)
        if x.size < 3:
            return nothing
        width = float(width_px)
        c = _CORE_WIDTHS * width
        f = _FLANK_WIDTHS * width
        profile = _heading_profile(x, y, width)
        if profile is None:
            return nothing
        orig, s, length, sm, heading = profile
        if length < 2.0 * c + _HEADING_STEP_PX or sm.size < 3:
            return nothing

        turn_threshold = max(np.pi - float(self.threshold_angle_from_decomposed_indices), 0.0)
        curvature = np.abs(np.gradient(heading, _HEADING_STEP_PX))
        curvature_floor = _CURVATURE_FLOOR_FRAC * turn_threshold / (2.0 * c)
        radius = _SUPPRESS_WIDTHS * width

        def heading_at(q: float) -> float:
            return float(np.interp(q, sm, heading))

        def excess_at(p: float) -> Optional[float]:
            # Excess turning at p, or None where the window does not fit or
            # the bend stays below the threshold.
            # p での超過回転。窓が収まらないか、折れがしきい値に届かなければ None。
            if p < c or p > length - c:
                return None
            core = heading_at(p + c) - heading_at(p - c)
            if abs(core) < turn_threshold:
                return None
            sense = np.sign(core)
            # A flank cut short by the end of the line is still divided by the
            # full flank length, so its rate reads low there. Only a bend
            # within 0.25 W of the not-judged zone is affected, by at most a
            # quarter of its background.
            # 線の端で短くなった脇も脇の全長で割るため、そこでは率が低く読まれる。
            # 影響を受けるのは判定しない範囲から 0.25 W 以内の折れだけで、その
            # 背景が最大 1/4 小さくなる。
            left = (heading_at(p - c) - heading_at(max(sm[0], p - c - f))) / f
            right = (heading_at(min(sm[-1], p + c + f)) - heading_at(p + c)) / f
            background = max(0.0, min(sense * left, sense * right))
            excess = abs(core) - 2.0 * c * background
            return float(excess) if excess >= turn_threshold else None

        # Fine candidates: curvature maxima.
        # 細かい候補：曲率の極大。
        fine: List[Tuple[float, float]] = []
        for i in range(1, curvature.size - 1):
            if (curvature[i] >= curvature[i - 1] and curvature[i] > curvature[i + 1]
                    and curvature[i] >= curvature_floor):
                excess = excess_at(float(sm[i]))
                if excess is not None:
                    fine.append((excess, float(sm[i])))

        # Coarse candidates: maxima of the window turning, only where no fine
        # candidate passed nearby.
        # 粗い候補：窓の回転の極大。近くに通過した細かい候補が無い場所だけ。
        coarse: List[Tuple[float, float]] = []
        grid = sm[(sm >= c) & (sm <= length - c)]
        if grid.size >= 3:
            window_turn = np.abs(np.interp(grid + c, sm, heading)
                                 - np.interp(grid - c, sm, heading))
            for i in range(1, grid.size - 1):
                if (window_turn[i] >= window_turn[i - 1]
                        and window_turn[i] > window_turn[i + 1]
                        and window_turn[i] >= turn_threshold):
                    p = float(grid[i])
                    excess = excess_at(p)
                    if excess is not None and all(abs(p - q) > radius for _, q in fine):
                        coarse.append((excess, p))

        # Strongest first; a candidate within `radius` of a kept one is the
        # same bend. The sort is stable, so equal strengths keep fine before
        # coarse.
        # 強い順に処理し、残した候補から `radius` 以内の候補は同じ折れとする。
        # 安定ソートなので、強さが同じなら細かい候補が粗い候補より先に来る。
        kept: List[Tuple[float, float]] = []
        for excess, p in sorted(fine + coarse, key=lambda t: -t[0]):
            if all(abs(p - q) > radius for _, q in kept):
                kept.append((excess, p))

        margin = _END_WIDTHS * width
        kinks: List[Tuple[int, float]] = []
        unjudged: List[int] = []
        taken = set()
        for excess, p in kept:
            index = int(orig[int(np.argmin(np.abs(s - p)))])
            # Two bends can only share a line point where the points are
            # spaced wider than the suppression radius; the stronger, seen
            # first, keeps it.
            # 2 つの折れが同じ線の点を共有するのは、点の間隔が抑制半径より広い
            # 場所だけである。先に来る強い方がその点を取る。
            if index in taken:
                continue
            taken.add(index)
            if margin <= p <= length - margin:
                kinks.append((index, excess))
            else:
                unjudged.append(index)
        kinks.sort()
        kink_indices = np.array([k for k, _ in kinks], dtype=np.intp)
        kink_angles = np.clip(
            np.pi - np.array([e for _, e in kinks], dtype=np.float64),
            _MIN_INTERIOR_ANGLE, np.pi - _MIN_INTERIOR_ANGLE,
        )
        return kink_indices, kink_angles, np.array(sorted(unjudged), dtype=np.intp)

    def kinks_and_decomposed_from_track(
        self,
        xtrack: NDArray,
        ytrack: NDArray,
    ) -> tuple[NDArray, NDArray, NDArray]:
        """
        Judge a skeleton track by the polyline rule of bundle format 1.0.
        バンドル形式 1.0 の折れ線規則でスケルトントラックを判定する。

        Kept only for bundles written before format 1.1, which were judged by
        this rule on the skeleton track. A fibril reconnected or cut by the
        height filter in such a bundle is judged here, so one image never
        carries kinks from two rules; `kinks_on_line` judges everything else.
        The detector's own thresholds (`threshold_distance`,
        `threshold_angle_from_decomposed_indices`) are used.
        形式 1.1 より前に書かれ、スケルトントラック上でこの規則により判定された
        バンドルのためだけに残す。そのようなバンドルで再結合したフィブリルや高さ
        フィルターで切り出したものはここで判定し、1 枚の画像に 2 つの規則のキンクが
        混在しないようにする。それ以外はすべて `kinks_on_line` が判定する。検出器
        自身のしきい値（`threshold_distance`、
        `threshold_angle_from_decomposed_indices`）を使う。

        Parameters
        ----------
        xtrack
            X coordinates of the ordered skeleton track.
            順序付きのスケルトントラックの x 座標列。
        ytrack
            Y coordinates of the same track.
            同じトラックの y 座標列。

        Returns
        -------
        tuple of ndarray
            ``(kink_indices, kink_angles, decomposed_indices)``. Kink angles are
            interior angles in radians; all indices point into the track arrays.
            ``(kink_indices, kink_angles, decomposed_indices)``。kink 角度は
            ラジアンの内角で、各インデックスはトラック配列に対応する。
        """
        decomposed_indices = self._binary_decompose_simple(
            xtrack, ytrack, self.threshold_distance,
        )
        kink_indices, kink_angles = self._detect_kink_from_decomposed_indices(
            xtrack, ytrack, decomposed_indices,
            self.threshold_angle_from_decomposed_indices,
        )
        return kink_indices, kink_angles, decomposed_indices

    def _binary_decompose_simple(
        self,
        skel_coor_x: NDArray,
        skel_coor_y: NDArray,
        threshold_distance: float,
    ) -> NDArray:
        """
        Decompose a skeleton track into piecewise-linear representative indices.
        骨格トラックを折れ線近似の代表インデックスへ分解する。

        This follows the Douglas-Peucker idea: start from endpoints and insert
        the farthest inner point while its perpendicular distance meets or
        exceeds the threshold.
        Douglas-Peucker 法に近い考え方で、始点と終点から開始し、垂直距離が
        しきい値以上の最遠内部点を追加して分割を続ける。

        Parameters
        ----------
        skel_coor_x
            X coordinates of tracked skeleton points.
            追跡された骨格点の x 座標列。
        skel_coor_y
            Y coordinates of tracked skeleton points.
            追跡された骨格点の y 座標列。
        threshold_distance
            Minimum perpendicular distance required to insert a split point.
            分割点を追加するために必要な最小垂直距離。

        Returns
        -------
        decomposed_indices
            Representative point indices for the piecewise-linear track.
            折れ線近似トラックの代表点インデックス。
        """

        # Convert coordinates once to avoid repeated dtype casting inside the loop.
        cx = np.asarray(skel_coor_x, dtype=np.float64)
        cy = np.asarray(skel_coor_y, dtype=np.float64)
        n_pts = cx.size

        # Degenerate cases: fewer than 2 points cannot form a segment.
        if n_pts < 2:
            return np.arange(n_pts, dtype=np.int64)

        decomposed_indices = [0, n_pts - 1]
        updated = True
        while updated:
            updated = False
            for n, (i, j) in enumerate(zip(decomposed_indices[:-1], decomposed_indices[1:])):
                # No inner points between i and j, nothing to split.
                if j - i < 2:
                    continue

                # Inline point-to-line distance without helper calls.
                ax = cx[i]; ay = cy[i]
                bx = cx[j]; by = cy[j]
                abx = bx - ax
                aby = by - ay
                length_ab = (abx * abx + aby * aby) ** 0.5

                # Degenerate segment (i == j in coordinate sense) cannot define a line.
                if length_ab == 0.0:
                    continue

                xs = cx[i + 1:j]
                ys = cy[i + 1:j]
                # 2D cross product magnitude divided by |AB|: perpendicular distance.
                dist = np.abs(abx * (ys - ay) - aby * (xs - ax)) / length_ab

                # Find the farthest inner point; single pass via argmax.
                k = int(dist.argmax())
                farthest_distance = dist[k]

                # If all inner points are on the line, no split is needed.
                if farthest_distance == 0:
                    continue

                elif farthest_distance >= threshold_distance:
                    # Insert a split point when the farthest distance meets the threshold.
                    added_indices = [k + i + 1]
                    decomposed_indices = decomposed_indices[:n + 1] + added_indices + decomposed_indices[n + 1:]
                    updated = True
                    # Restart scan because segment layout changed after insertion.
                    break

        decomposed_indices.sort()
        return np.array(decomposed_indices)


    def _detect_kink_from_decomposed_indices(
        self,
        skel_coor_x: NDArray,
        skel_coor_y: NDArray,
        decomposed_indices: NDArray,
        threshold_angle: float,
    ) -> tuple[NDArray, NDArray]:
        """
        Detect kink indices by evaluating angles at decomposition midpoints.
        分解点列の中間点角度を評価して kink インデックスを抽出する。

        Parameters
        ----------
        skel_coor_x
            X coordinates of tracked skeleton points.
            追跡された骨格点の x 座標列。
        skel_coor_y
            Y coordinates of tracked skeleton points.
            追跡された骨格点の y 座標列。
        decomposed_indices
            Key indices obtained from decomposition.
            分解処理で得られた代表点インデックス。
        threshold_angle
            Angle threshold in radians for kink classification.
            kink 判定に使う角度しきい値（ラジアン）。

        Returns
        -------
        kink_result
            `(kink_indices, kink_angles)` filtered by threshold.
            しきい値で抽出した `(kink_indices, kink_angles)`。

        Notes
        -----
        A candidate is also required to be larger than its own uncertainty.
        The decomposition localizes a vertex only to within
        `threshold_distance` of the true path, so a vertex displaced by that
        much across an arm of length ``A`` tilts the arm by about
        ``threshold_distance / A`` radians, and the two arms together move the
        interior angle by about ``2 * threshold_distance / A``. What the
        threshold tests is not the angle but its distance below a straight
        line, ``pi - angle``, so a candidate is kept only where

            ``pi - angle > 2 * threshold_distance / min(arm_prev, arm_next)``

        that is, where the bend being reported is at least as large as the
        error bar on measuring it.
        候補には、その値が自身の不確かさを上回ることも要求する。分解は頂点を
        真の経路から `threshold_distance` の精度でしか局在化しないため、その量
        だけずれた頂点は長さ ``A`` の腕を約 ``threshold_distance / A`` ラジアン
        傾け、両腕あわせて内角を約 ``2 * threshold_distance / A`` 動かす。
        しきい値が検定しているのは角度そのものではなく、直線からの不足
        ``pi - angle`` であるから、候補は

            ``pi - angle > 2 * threshold_distance / min(arm_prev, arm_next)``

        を満たすものだけを残す。つまり、報告しようとしている折れが、それを測る
        誤差棒と同じかそれ以上の大きさを持つ場合に限る。

        This replaces a fixed minimum arm length, and it behaves better for the
        reason the fixed rule was wrong: how much support an angle needs is not
        a constant, it depends on how sharp the angle is. A 120 degree bend is
        60 degrees clear of straight and survives on a short arm; a 149 degree
        bend is 31 degrees clear and needs three times as much before it can be
        told from the vertex jitter. The rule is also free of any length scale
        — `threshold_distance` and the arm are both in pixels and cancel — so
        it means the same thing at any scan size, which a pixel count does not.
        これは固定の最小腕長を置き換えるもので、固定規則が誤っていたのと同じ
        理由でより良く振る舞う。角度が必要とする支持量は定数ではなく、角度の
        鋭さに依存する。120 度の折れは直線から 60 度離れているので短い腕でも
        残るが、149 度の折れは 31 度しか離れておらず、頂点の揺らぎと区別する
        には 3 倍の腕を要する。また `threshold_distance` と腕はどちらも画素
        単位で相殺するため長さスケールを含まず、画素数指定と違ってどの走査
        サイズでも同じ意味を持つ。

        The terminal arms are what this mainly removes. A track endpoint is a
        decomposition vertex by construction, so a terminal arm can be as
        short as one pixel, and after `imp_tools.remove_bp` most endpoints are
        not fiber ends at all but cuts at a crossing, where the mask is at its
        least symmetric about the ridge. Measured on the three bundled scans,
        46 to 68 % of track ends lie within 3 px of a branch point.
        主に除かれるのは末端の腕である。トラックの端点は構成上必ず分解頂点に
        なるため末端の腕は 1 画素まで短くなり得るうえ、`imp_tools.remove_bp`
        の後では端点の多くが繊維の終端ではなく交差での切断であり、そこはマスク
        が稜線に対して最も非対称になる場所である。同梱の実スキャン 3 種で実測
        すると、トラック端の 46〜68 % が分岐点から 3 px 以内にある。
        """
        # Compute angles at decomposition midpoints and keep sharp bends.
        kink_indices = []
        kink_angles = []
        if len(decomposed_indices) <= 2:
            # No middle point means no angle can be formed.
            return np.array(kink_indices, dtype=np.intp), np.array(kink_angles)

        di = decomposed_indices
        mid_idx = di[1:-1]
        prev_idx = di[:-2]
        next_idx = di[2:]
        cx = np.asarray(skel_coor_x)
        cy = np.asarray(skel_coor_y)
        # Vectorize angle computation at each midpoint.
        v1x = cx[prev_idx] - cx[mid_idx]
        v1y = cy[prev_idx] - cy[mid_idx]
        v2x = cx[next_idx] - cx[mid_idx]
        v2y = cy[next_idx] - cy[mid_idx]
        dot = v1x * v2x + v1y * v2y
        norm1 = np.sqrt(v1x ** 2 + v1y ** 2)
        norm2 = np.sqrt(v2x ** 2 + v2y ** 2)
        angles = np.arccos(dot / (norm1 * norm2))
        mask = angles <= threshold_angle

        # Significance rule: see Notes. The bend must exceed the angular error
        # the decomposition's vertex tolerance puts on measuring it. norm1 and
        # norm2 are already the arm lengths in pixels, so no length scale
        # enters and none has to be supplied.
        # 有意性ルール（Notes 参照）。折れは、分解の頂点許容がその測定に与える
        # 角度誤差を上回らなければならない。norm1 と norm2 は既に画素単位の腕長
        # なので、長さスケールは入らず、与える必要もない。
        arm = np.minimum(norm1, norm2)
        with np.errstate(divide="ignore", invalid="ignore"):
            angular_error = np.where(arm > 0.0,
                                     2.0 * self.threshold_distance / arm,
                                     np.inf)
        mask &= (np.pi - angles) > angular_error
        return mid_idx[mask], angles[mask]
