"""
Detect kink points from AFM skeletonized fiber images.
AFM の骨格化繊維画像から kink 点を検出する。

This module provides a detector class that decomposes tracked skeleton points
into piecewise linear segments and identifies sharp bends by angle thresholding.
このモジュールは、追跡された骨格点列を折れ線として分解し、
角度しきい値により鋭い折れ曲がりを抽出する検出クラスを提供する。
"""

import logging

import cv2
import numpy as np
from numpy.typing import NDArray

from . import imp_tools
from .processed_image import ProcessedImage

logger = logging.getLogger(__name__)


class KinkDetector:
    """
    Detect kink points from skeletonized fiber lines.
    骨格化された繊維線から kink 点を検出するクラス。

    Attributes
    ----------
    threshold_distance
        Distance threshold for inserting decomposition points.
        分解点を追加するための距離しきい値。
    threshold_angle_from_decomposed_indices
        Angle threshold (radian) used to classify kink points.
        kink 点判定に使う角度しきい値（ラジアン）。
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
            Minimum farthest distance to split a segment.
            区間分割を行う最遠距離の最小値。
        threshold_angle_from_decomposed_indices
            Angle threshold (radian) for kink classification.
            kink 判定に使う角度しきい値（ラジアン）。
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
            been run on this image yet.
        Exception
            Re-raises any exception unchanged after logging its traceback.

        Notes
        -----
        Reads `image.skeleton_image`; writes `image.kink_indices_by_label`,
        `image.kink_angles_by_label`, `image.decomposed_indices_by_label`,
        `image.all_kink_coordinates`, `image.all_kink_angles`, and
        `image.decomposed_point_coordinates`.
        """
        # Fail loudly at the stage boundary instead of deep inside imp_tools.
        if image.skeleton_image is None:
            raise ValueError(
                "KinkDetector requires image.skeleton_image; "
                "run Skeletonizer on the image first."
            )
        try:
            # Remove branch points and L-corners for cleaner line tracking.
            no_bp_skel = imp_tools.remove_bp(image.skeleton_image)
            no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
            # Split skeleton into connected components (labels).
            nLabels, label_image, data, center = cv2.connectedComponentsWithStats(no_Lcorner_skel)

            # Prepare flat arrays for backward-compatible output fields.
            all_kink_coordinate_x = []
            all_kink_coordinate_y = []
            all_kink_angles = []
            decomposed_point_x = []
            decomposed_point_y = []
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
                # Decompose the track into representative piecewise-linear points.
                decomposed_indices = self._binary_decompose_simple(_xtrack, _ytrack, self.threshold_distance)
                # Detect kink points by angle threshold on decomposed points.
                kink_indices, kink_angles = self._detect_kink_from_decomposed_indices(_xtrack, _ytrack, decomposed_indices, self.threshold_angle_from_decomposed_indices)

                # Store per-label arrays for fiber-instance generation.
                image.kink_indices_by_label[label]       = kink_indices
                image.kink_angles_by_label[label]        = kink_angles
                image.decomposed_indices_by_label[label] = decomposed_indices

                # Store flattened arrays for legacy GUI output compatibility.
                # GUI01 saving code still expects these backward-compatible flat arrays.
                all_kink_coordinate_x.extend(_xtrack[kink_indices])
                all_kink_coordinate_y.extend(_ytrack[kink_indices])
                all_kink_angles.extend(list(kink_angles))
                decomposed_point_x.extend(_xtrack[decomposed_indices])
                decomposed_point_y.extend(_ytrack[decomposed_indices])

            image.all_kink_coordinates = (np.array(all_kink_coordinate_x), np.array(all_kink_coordinate_y))
            image.all_kink_angles = np.array(all_kink_angles)
            image.decomposed_point_coordinates = (np.array(decomposed_point_x), np.array(decomposed_point_y))

        except Exception:
            # Log the full traceback before re-raising the original exception
            # unchanged (bare `raise` preserves the exception and its chain).
            logger.exception("Kink detection failed")
            raise

    def kinks_and_decomposed_from_track(
        self,
        xtrack: NDArray,
        ytrack: NDArray,
    ) -> tuple[NDArray, NDArray, NDArray]:
        """
        Detect kink and decomposition indices for a single ordered track.
        順序付き 1 本のトラックから kink・分解点インデックスを検出する。

        Public wrapper over the piecewise-linear decomposition and angle-based
        kink detection so callers can recompute features on a reconstructed
        track (for example a fiber assembled from several fragments) without
        reaching into the private helpers. The detector's own thresholds
        (`threshold_distance`, `threshold_angle_from_decomposed_indices`) are
        used, so the result matches the per-label detection in `__call__`.
        折れ線分解と角度ベースの kink 検出の公開ラッパー。再構築したトラック
        （複数断片から連結したファイバーなど）に対して、private ヘルパーへ直接
        触れずに特徴点を再計算できるようにする。検出器自身のしきい値
        （`threshold_distance`、`threshold_angle_from_decomposed_indices`）を
        使うため、`__call__` のラベル単位検出と結果が一致する。

        Parameters
        ----------
        xtrack
            X coordinates of the ordered skeleton track.
            順序付き骨格トラックの x 座標列。
        ytrack
            Y coordinates of the ordered skeleton track.
            順序付き骨格トラックの y 座標列。

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
