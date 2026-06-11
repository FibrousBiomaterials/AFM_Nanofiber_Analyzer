"""
Detect kink points from AFM skeletonized fiber images.
AFM の骨格化繊維画像から kink 点を検出する。

This module provides a detector class that decomposes tracked skeleton points
into piecewise linear segments and identifies sharp bends by angle thresholding.
このモジュールは、追跡された骨格点列を折れ線として分解し、
角度しきい値により鋭い折れ曲がりを抽出する検出クラスを提供する。
"""

from collections.abc import Iterable
import traceback

import cv2
import numpy as np
from numpy.typing import NDArray

from . import imp_tools
from .processed_image import ProcessedImage


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
            Re-raises any exception after printing traceback.

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
                _xtrack_local, _ytrack_local = imp_tools.tracking(target_image)
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

        except Exception as e:
            # Print full traceback before re-raising the original exception.
            print(traceback.format_exc())
            raise e

    @staticmethod
    def _calc_line_to_points_dist(a, b, x, y) -> NDArray:
        """
        Compute perpendicular distance from line AB to one or many points.
        直線 AB から1点または複数点までの垂直距離を計算する。

        Parameters
        ----------
        a
            First point defining the reference line.
            基準直線を定義する第1点。
        b
            Second point defining the reference line.
            基準直線を定義する第2点。
        x
            X coordinate(s) of query point(s).
            距離を求める点の x 座標（単数または複数）。
        y
            Y coordinate(s) of query point(s).
            距離を求める点の y 座標（単数または複数）。

        Returns
        -------
        NDArray
            Perpendicular distance array.
            垂直距離の配列。

        Raises
        ------
        ValueError
            If x and y are iterables with different lengths.
        """
        # Compute point-to-line distance(s) using 2D cross product.
        A = np.array(a, dtype=float)
        B = np.array(b, dtype=float)
        AB = B - A
        length_AB = np.linalg.norm(AB)

        # Handle scalar inputs as a single point distance.
        if not isinstance(x, Iterable) and not isinstance(y, Iterable):
            AC = np.array([x, y], dtype=float) - A
            return np.array([abs(np.cross(AB, AC)) / length_AB])

        # Validate paired iterable inputs have matching lengths.
        if isinstance(x, Iterable) and isinstance(y, Iterable) and len(x) != len(y):
            raise ValueError('The length of x and y must be the same.')

        # Use vectorized computation to avoid Python loops.
        xs = np.asarray(x, dtype=float)
        ys = np.asarray(y, dtype=float)
        # Compute 2D cross product magnitude with line vector AB.
        cross = AB[0] * (ys - A[1]) - AB[1] * (xs - A[0])
        return np.abs(cross) / length_AB

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
        return mid_idx[mask], angles[mask]
