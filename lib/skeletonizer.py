"""
Skeleton pruning and cleanup for segmented AFM nanofiber images.
セグメント化された AFM ナノファイバー画像のスケルトン枝刈りと後処理を行う。

The module thins a binary nanofiber mask, removes short low-height branches,
and labels the remaining skeleton segments for downstream fiber analysis.
二値化されたナノファイバーマスクを細線化し、低い高さの短い枝を除去して、
後段の繊維解析に使うスケルトン成分へラベル付けする。
"""

import traceback

import cv2
import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import maximum_filter
from skimage.morphology import skeletonize, thin

from .processed_image import ProcessedImage


# ---------------------------------------------------------------------------
# Fast cv2-based replacements for imp_tools.endPoints / imp_tools.branchedPoints
#
# imp_tools uses mahotas.morph.hitmiss which is ~6x slower than cv2.MORPH_HITMISS
# on the same patterns. Kernel value mapping: mahotas 0→-1(bg), 1→1(fg), 2→0(dc).
# Patterns and rotation order replicate imp_tools.py exactly so outputs are identical.
# ---------------------------------------------------------------------------

def _mh_to_cv2_kernel(arr: np.ndarray) -> np.ndarray:
    """
    Convert a mahotas hit-miss kernel to the OpenCV kernel convention.
    mahotas の hit-miss カーネルを OpenCV のカーネル表現へ変換する。
    """
    return np.where(arr == 2, 0, np.where(arr == 0, -1, 1)).astype(np.int8)


def _build_ep_patterns() -> list[np.ndarray]:
    """
    Build endpoint hit-miss kernels compatible with OpenCV.
    OpenCV で利用できる端点検出用 hit-miss カーネルを構築する。
    """
    ep1 = np.array([[0, 0, 0], [0, 1, 0], [2, 1, 2]])
    ep2 = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 1]])
    ep_single = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
    pats = []
    for k in range(4):
        for p in [ep1, ep2]:
            pats.append(_mh_to_cv2_kernel(np.rot90(p, k=k)))
    pats.append(_mh_to_cv2_kernel(ep_single))
    return pats


def _build_bp_patterns() -> list[np.ndarray]:
    """
    Build branch-point hit-miss kernels compatible with OpenCV.
    OpenCV で利用できる分岐点検出用 hit-miss カーネルを構築する。
    """
    vh_xbranch      = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    diagonal_xbranch = np.array([[1, 0, 1], [0, 1, 0], [1, 0, 1]])
    vh_ybranch      = np.array([[1, 0, 1], [0, 1, 0], [2, 1, 2]])
    diagonal_ybranch = np.array([[0, 1, 2], [1, 1, 2], [2, 2, 1]])
    vh_tbranch      = np.array([[0, 0, 0], [1, 1, 1], [0, 1, 0]])
    diagonal_tbranch = np.array([[1, 0, 1], [0, 1, 0], [1, 0, 0]])
    square_branch   = np.array([[2, 2, 2], [1, 1, 2], [1, 1, 2]])
    pats = []
    for k in range(4):
        for p in [vh_ybranch, diagonal_ybranch, vh_tbranch, diagonal_tbranch]:
            pats.append(_mh_to_cv2_kernel(np.rot90(p, k=k)))
    for p in [vh_xbranch, diagonal_xbranch, square_branch]:
        pats.append(_mh_to_cv2_kernel(p))
    return pats


# Precompute pattern lists once at module import time
_EP_PATTERNS_CV2 = _build_ep_patterns()
_BP_PATTERNS_CV2 = _build_bp_patterns()


def _fast_end_points(skel: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """
    Return endpoints using a cv2-based replacement for imp_tools.endPoints.
    imp_tools.endPoints と同じ出力を cv2 ベースの代替処理で返す。
    """
    padded = np.pad(skel, pad_width=1, mode='constant', constant_values=0)
    hits = np.zeros_like(padded, dtype=np.uint8)
    for p in _EP_PATTERNS_CV2:
        hits |= cv2.morphologyEx(padded, cv2.MORPH_HITMISS, p)
    return np.ascontiguousarray(np.where(hits > 0, 1, 0).astype(np.uint8)[1:-1, 1:-1])


def _fast_branched_points(skel: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """
    Return branch points using a cv2-based replacement for imp_tools.branchedPoints.
    imp_tools.branchedPoints と同じ出力を cv2 ベースの代替処理で返す。
    """
    padded = np.pad(skel, pad_width=1, mode='constant', constant_values=0)
    hits = np.zeros_like(padded, dtype=np.uint8)
    for p in _BP_PATTERNS_CV2:
        hits |= cv2.morphologyEx(padded, cv2.MORPH_HITMISS, p)
    return np.ascontiguousarray(np.where(hits > 0, 1, 0).astype(np.uint8)[1:-1, 1:-1])


class Skeletonizer:
    """
    Extract and clean skeleton traces from a segmented AFM nanofiber mask.
    セグメント化された AFM ナノファイバーマスクからスケルトントレースを抽出・整形する。

    Attributes
    ----------
    bp_height
        Height threshold used to classify low branch points in the calibrated image.
        較正済み画像で低い分岐点を分類するための高さしきい値。
    branch_length
        Search radius in pixels used to connect nearby endpoints to low branch points.
        近傍端点を低い分岐点へ接続して追跡する探索半径 (px)。
    min_area
        Minimum connected-component area retained in the final skeleton.
        最終スケルトンに残す連結成分の最小面積。
    image_size
        Width and height of the square working image.
        正方形の作業画像の幅および高さ。
    """

    def __init__(
        self,
        bp_height: float = 5,
        branch_length: int = 8,
        min_area: int = 10,
    ) -> None:
        """
        Initialize skeleton pruning parameters.
        スケルトン枝刈り用のパラメータを初期化する。

        Parameters
        ----------
        bp_height
            Height threshold used to classify branch points as low or high.
            分岐点を低い点または高い点として分類する高さしきい値。
        branch_length
            Search radius in pixels for short branch tracking.
            短い枝を追跡するための探索半径 (px)。
        min_area
            Minimum connected-component area retained after cleanup.
            後処理後に保持する連結成分の最小面積。
        """
        self.bp_height = bp_height
        self.branch_length = branch_length
        self.min_area = min_area
        self.image_size = None
        self._coor_low_bps = None
        self._coor_high_bps = None
        self._coor_close_eps = None
        self._branches_image = None

        self._init_skeleton_image = None
        self._nobranch_image = None
        self._nobranch_skeleton_image = None
        self._nosmall_skeleton_image = None

    def __call__(self, image: ProcessedImage) -> None:
        """
        Add a branch-pruned skeleton and connected-component data to an image.
        画像へ枝除去済みスケルトンと連結成分データを追加する。

        Parameters
        ----------
        image
            Processed image produced by background calibration and segmentation.
            背景補正とセグメンテーション後に得られた ProcessedImage インスタンス。

        Returns
        -------
        None
            The input instance is updated in place.
            入力インスタンスをインプレースで更新する。

        Raises
        ------
        ValueError
            If `image.binarized_image` or `image.calibrated_image` is None,
            i.e. segmentation or background calibration has not been run yet.

        Notes
        -----
        Reads `image.binarized_image` and `image.calibrated_image`; writes
        `image.skeleton_image`, `image.label_image`, `image.nLabels`,
        `image.data`, `image.ep`, and `image.bp`.

        The workflow first thins the binary mask, removes short branches derived
        from low-height branch points, and then removes tiny or ring-shaped
        connected components.
        まず二値マスクを細線化し、低い高さの分岐点から伸びる短い枝を除去した後、
        微小成分やリング状成分を除去する。
        """
        # Fail loudly at the stage boundary instead of deep inside skimage/cv2.
        if image.binarized_image is None:
            raise ValueError(
                "Skeletonizer requires image.binarized_image; "
                "run Segmenter on the image first."
            )
        if image.calibrated_image is None:
            raise ValueError(
                "Skeletonizer requires image.calibrated_image; "
                "run BGCalibrator on the image first."
            )

        init_skeleton_image = thin(image.binarized_image).astype(np.uint8)
        self.image_size = image.binarized_image.shape[0]
        self._init_skeleton_image = init_skeleton_image
        self.set_low_bp_coor(image.calibrated_image, init_skeleton_image, self.bp_height)
        self.get_close_eps()
        nobranch_image = self.prune_branches(image.calibrated_image, init_skeleton_image)
        self._nobranch_image = nobranch_image
        nobranch_skeleton_image = skeletonize(nobranch_image).astype(np.uint8)
        self._nobranch_skeleton_image = nobranch_skeleton_image
        nosmall_skeleton_image = self.remove_small_and_ring(nobranch_skeleton_image)
        self._nosmall_skeleton_image = nosmall_skeleton_image

        # Store connected-component data on the ProcessedImage instance.
        nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(
            nosmall_skeleton_image
        )
        image.skeleton_image = nosmall_skeleton_image
        image.label_image = label_Images
        image.nLabels = nLabels
        image.data = data

        image.ep = _fast_end_points(nosmall_skeleton_image)
        image.bp = _fast_branched_points(nosmall_skeleton_image)


    def prune_branches(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
    ) -> NDArray[np.uint8]:
        """
        Remove tracked short branches from the initial skeleton.
        初期スケルトンから追跡された短い枝を除去する。

        Parameters
        ----------
        calibrated_image
            Height-calibrated image used to classify branch-point height.
            分岐点の高さ分類に使う較正済み高さ画像。
        init_skeleton_image
            Initial skeleton image before branch pruning.
            枝刈り前の初期スケルトン画像。

        Returns
        -------
        numpy.ndarray
            Skeleton image with tracked branch pixels removed.
            追跡された枝画素を除去したスケルトン画像。
        """
        branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
        return init_skeleton_image - branches_image

    def calc_branches_image(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
    ) -> NDArray[np.uint8]:
        """
        Create a mask of branch pixels selected for pruning.
        枝刈り対象として選ばれた枝画素のマスクを作成する。

        Parameters
        ----------
        calibrated_image
            Height-calibrated image used to classify branch-point height.
            分岐点の高さ分類に使う較正済み高さ画像。
        init_skeleton_image
            Initial skeleton image before branch pruning.
            枝刈り前の初期スケルトン画像。

        Returns
        -------
        numpy.ndarray
            Binary image whose nonzero pixels mark branches to remove.
            非ゼロ画素が除去対象の枝を表す二値画像。
        """
        branches_image = np.zeros((self.image_size, self.image_size), dtype=np.uint8)
        coor_branch = self.track_branches()
        if coor_branch[0].size != 0:
            branches_image[coor_branch] = 1
        return branches_image

    def set_low_bp_coor(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
        bp_height: float,
    ) -> None:
        """
        Split skeleton branch points into low-height and high-height coordinates.
        スケルトン分岐点を低い高さと高い高さの座標に分ける。

        Parameters
        ----------
        calibrated_image
            Height-calibrated AFM image.
            高さ較正済みの AFM 画像。
        init_skeleton_image
            Skeleton image whose branch points are classified.
            分岐点を分類する対象のスケルトン画像。
        bp_height
            Height threshold separating low and high branch points.
            低い分岐点と高い分岐点を分ける高さしきい値。

        Returns
        -------
        None
            Coordinates are stored on the instance.
            座標はインスタンスに保存される。
        """
        all_bps = _fast_branched_points(init_skeleton_image)
        low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
        high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
        self._coor_low_bps = low_bp_coor
        self._coor_high_bps = high_bp_coor

    def get_close_eps(self) -> None:
        """
        Find endpoints close to low-height branch points.
        低い高さの分岐点に近い端点を検出する。

        Returns
        -------
        None
            Endpoint coordinates are stored on the instance.
            端点座標はインスタンスに保存される。

        Notes
        -----
        The dilation radius is controlled by `branch_length`, so only endpoints
        that can plausibly be short branches are considered for pruning.
        膨張半径は `branch_length` で制御されるため、短い枝とみなせる端点のみが
        枝刈り候補になる。
        """
        all_eps_image = _fast_end_points(self._init_skeleton_image)
        _low_bps_image = np.zeros((self.image_size, self.image_size), dtype=np.uint8)
        _low_bps_image[self._coor_low_bps] = 1

        k = self.branch_length
        dilated_low_bps = maximum_filter(
            _low_bps_image.astype(float), size=2 * k, mode='constant', cval=0, origin=0
        )
        close_eps = all_eps_image & (dilated_low_bps > 0).astype(np.uint8)
        self._coor_close_eps = np.where(close_eps)

    def track_branches(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Track branch pixels from nearby endpoints toward low-height branch points.
        近傍端点から低い高さの分岐点に向かって枝画素を追跡する。

        Returns
        -------
        tuple of numpy.ndarray
            Row and column coordinates of branch pixels selected for pruning.
            枝刈り対象として選ばれた枝画素の行・列座標。

        Notes
        -----
        Tracking stops when it reaches a low branch point, encounters a high
        branch point, leaves the local branch window, or exhausts the configured
        branch length.
        低い分岐点に到達した場合、高い分岐点に接した場合、局所探索窓から外れる場合、
        または設定された枝長を使い切った場合に追跡を停止する。
        """
        branches_coor_x = []
        branches_coor_y = []
        image_for_tracking = self._init_skeleton_image.copy()

        image_low_bps = np.zeros((self.image_size, self.image_size), dtype=bool)
        image_low_bps[self._coor_low_bps] = True  # Mark low branch points in the boolean mask.

        image_high_bps = np.zeros((self.image_size, self.image_size), dtype=bool)
        image_high_bps[self._coor_high_bps] = True
        # Start tracking from endpoints and stop when a low branch point is reached.
        # ep からトラック開始。low_bp にぶつかったら終了。
        starts_x, starts_y = self._coor_close_eps
        for step_num, (start_x, start_y) in enumerate(zip(starts_x, starts_y)):
            bl = self.branch_length
            if (start_x < bl or start_x + bl > self.image_size or
                    start_y < bl or start_y + bl > self.image_size):
                continue
        
            tracking_area = image_for_tracking[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
            image_for_low_bp_detection = image_low_bps[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
            image_for_high_bp_detection = image_high_bps[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
        
            x, y = bl, bl
            xtrack = [x + start_x - bl]
            ytrack = [y + start_y - bl]
        
            for i in range(bl):
                tracking_area[x, y] = 0
                window = tracking_area[x - 1 : x + 2, y - 1 : y + 2]
        
                if (window == 0).all():
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                elif image_for_low_bp_detection[x - 1 : x + 2, y - 1 : y + 2].any():
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                elif image_for_high_bp_detection[x - 1 : x + 2, y - 1 : y + 2].any():
                    break
        
                direction_rows, direction_cols = np.where(window != 0)
                if len(direction_rows) == 0:
                    break
                x += int(direction_rows[0]) - 1
                y += int(direction_cols[0]) - 1
                xtrack.append(x + start_x - bl)
                ytrack.append(y + start_y - bl)

        branches_coor_x = np.asarray(branches_coor_x)
        branches_coor_y = np.asarray(branches_coor_y)
        return branches_coor_x, branches_coor_y

    def remove_small_and_ring(self, skeleton_image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """
        Remove tiny skeleton components and closed components without endpoints.
        微小なスケルトン成分と端点を持たない閉じた成分を除去する。

        Parameters
        ----------
        skeleton_image
            Skeleton image after branch pruning.
            枝刈り後のスケルトン画像。

        Returns
        -------
        numpy.ndarray
            Skeleton image with small components and endpoint-free rings removed.
            微小成分と端点を持たないリング状成分を除去したスケルトン画像。
        """
        returned_image = np.copy(skeleton_image)
        nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(returned_image)
        ep = _fast_end_points(returned_image)
        ring_frac_label = np.setdiff1d(np.arange(1, nLabels), label_Images[ep > 0])
        # Vectorize: collect all labels to remove, then apply a single boolean mask
        areas = np.array([data[i][4] for i in range(1, nLabels)])
        small_labels = np.nonzero(areas < self.min_area)[0] + 1  # +1: labels are 1-indexed
        remove_labels = np.union1d(small_labels, ring_frac_label)
        if remove_labels.size > 0:
            returned_image[np.isin(label_Images, remove_labels)] = 0
        return returned_image
