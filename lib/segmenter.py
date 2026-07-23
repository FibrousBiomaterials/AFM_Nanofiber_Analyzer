"""
Segment AFM height images into binary nanofiber masks.
AFM 高さ画像を二値化されたナノファイバーマスクへ分割するモジュール。

Combines global and local thresholding with component filtering based on area,
linearity, connectivity, and maximum height.
大域・局所しきい値処理に、面積・線形性・接続性・最大高さに基づく成分除去を組み合わせる。
"""

from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np
from scipy.ndimage import maximum as ndi_maximum
from skimage.feature import canny
from skimage.filters import threshold_local
from skimage.morphology import binary_dilation, binary_erosion, closing
from skimage.transform import hough_line, hough_line_peaks

if TYPE_CHECKING:
    from .processed_image import ProcessedImage

# Tiny denominator offset guarding the straightness-ratio division against an
# empty edge map (zero-sum denominator).
# 直線性比の除算で、エッジマップが空（分母の総和が 0）になる場合のゼロ除算を
# 防ぐための微小オフセット。
_DENOM_EPS = 1e-21


class Segmenter:
    """
    Create binary nanofiber masks from calibrated AFM height images.
    補正済み AFM 高さ画像から二値化ナノファイバーマスクを作成するクラス。

    Attributes
    ----------
    global_threshold
        Global height threshold used before local thresholding.
        局所しきい値処理の前に用いる大域高さしきい値。
    wsize_localbin
        Window size used by local thresholding.
        局所しきい値処理で使用するウィンドウサイズ。
    area_min
        Minimum component area retained after the first connected-component pass.
        最初の連結成分処理後に保持する最小成分面積。
    area_min_connecting
        Minimum area retained after erosion separates weakly connected fragments.
        収縮で弱く接続した断片を分離した後に保持する最小面積。
    apply_no_connecting
        Whether to remove weakly connected fragments after linearity filtering.
        線形性フィルタ後に弱く接続した断片を除去するかどうか。
    low_threshold
        Minimum maximum height required to retain a labeled component.
        ラベル成分を保持するために必要な最大高さの最小値。
    h_length
        Minimum Hough accumulator vote threshold used as a line-length proxy.
        直線長の代理指標として使う Hough アキュムレータの最小投票数。
    h_sratio
        Minimum linearity score required to retain small components.
        小さい成分を保持するために必要な最小線形性スコア。
    """

    def __init__(
        self,
        area_min: int = 200,
        area_min_connecting: int = 200,
        apply_no_connecting: bool = True,
        low_threshold: float = 1.5,
        global_threshold: float = 0.3,
        wsize_localbin: int = 17,
        h_length: int = 12,
        h_sratio: float = 0.3,
    ) -> None:
        """
        Initialize segmentation thresholds and filtering options.
        セグメンテーションのしきい値とフィルタリング設定を初期化する。

        Parameters
        ----------
        area_min
            Minimum area retained during the first component filtering step.
            最初の成分フィルタリングで保持する最小面積。
        area_min_connecting
            Minimum area retained after erosion separates weak connections.
            収縮で弱い接続を分離した後に保持する最小面積。
        apply_no_connecting
            Whether to remove weakly connected fragments.
            弱く接続した断片を除去するかどうか。
        low_threshold
            Minimum maximum height required for a component to remain.
            成分を保持するために必要な最大高さの最小値。
        global_threshold
            Global threshold applied before local thresholding.
            局所しきい値処理の前に適用する大域しきい値。
        wsize_localbin
            Window size used by local thresholding.
            局所しきい値処理で使用するウィンドウサイズ。
        h_length
            Hough peak threshold used as a proxy for minimum line length.
            最小直線長の代理指標として使う Hough ピークしきい値。
        h_sratio
            Minimum Hough-line score required to retain small components.
            小さい成分を保持するために必要な最小 Hough 直線スコア。
        """

        self.global_threshold = global_threshold
        self.wsize_localbin = wsize_localbin
        self.area_min = area_min
        self.area_min_connecting = area_min_connecting
        self.apply_no_connecting = apply_no_connecting
        self.low_threshold = low_threshold
        self.h_length = h_length
        self.h_sratio = h_sratio

        self.n_label = None
        self.no_linear = None

        # Keep intermediate masks available for tests and diagnostic inspection.
        self.binary_image: Optional[np.ndarray]
        self.no_small_binary_image: Optional[np.ndarray]
        self.no_linear_binary_image: Optional[np.ndarray]
        self.no_connecting_binary_image: Optional[np.ndarray]
        self.no_low_binary_image: Optional[np.ndarray]

        self.max_height_list: list = []
        self.h_sratio_list: list = []

    def __call__(self, image: "ProcessedImage") -> None:
        """
        Segment a calibrated AFM image and store the binary mask on it.
        補正済み AFM 画像を分割し、二値マスクを画像オブジェクトに格納する。

        Parameters
        ----------
        image
            Processed image object with a `calibrated_image` height map.
            `calibrated_image` 高さマップを持つ処理済み画像オブジェクト。

        Raises
        ------
        ValueError
            If `image.calibrated_image` is None, i.e. background calibration
            has not been run on this image yet.

        Notes
        -----
        Reads `image.calibrated_image`; writes `image.binarized_image`.

        The pipeline combines global and local threshold masks, removes small
        components, filters nonlinear components with a Hough-line score,
        optionally removes weakly connected fragments, and finally removes
        components whose maximum height is below `low_threshold`.
        この処理では大域・局所しきい値マスクを組み合わせ、小さい成分を除去し、
        Hough 直線スコアで非線形成分を除外し、必要に応じて弱く接続した断片を除去し、
        最後に最大高さが `low_threshold` 未満の成分を除去する。

        """
        # Fail loudly at the stage boundary instead of deep inside cv2/scipy.
        if image.calibrated_image is None:
            raise ValueError(
                "Segmenter requires image.calibrated_image; "
                "run BGCalibrator on the image first."
            )

        self.binary_image = self._binaryzation(
            image.calibrated_image, self.global_threshold, self.wsize_localbin
        )

        # Run the post-thresholding component filters and final closing. Shared
        # with `apply_component_filters` so an externally produced mask (e.g. an
        # ML binarization prediction) is carried through the identical stage.
        image.binarized_image = self.apply_component_filters(
            self.binary_image, image.calibrated_image
        )

    def apply_component_filters(
        self, mask: np.ndarray, height_image: np.ndarray
    ) -> np.ndarray:
        """
        Apply the post-thresholding component filters to an external mask.
        外部から与えた二値マスクに、しきい値後の成分フィルタ群を適用する。

        Runs the same small-area, linearity, weak-connection, and maximum-height
        filters (and the final morphological closing) that `__call__` applies
        after `_binaryzation`, but starting from ``mask`` instead of this
        Segmenter's own thresholding output. This lets a mask produced elsewhere
        -- such as a machine-learning binarization model's prediction -- be
        carried through the exact same pipeline stage, so it can be compared
        against the stored ``binarized`` result at the same stage rather than as
        a raw prediction.
        `__call__` が `_binaryzation` の後に適用するのと同じ成分フィルタ（微小面積・
        線形性・弱接続・最大高さ）と最終のモルフォロジー closing を、この Segmenter
        自身のしきい値出力ではなく ``mask`` を起点に適用する。これにより、別途生成
        したマスク（例：機械学習の二値化モデルの予測）を全く同じパイプライン段まで
        通し、保存済み ``binarized`` 結果と同じ段で比較できる。

        Parameters
        ----------
        mask
            Binary fiber mask to filter; nonzero marks fiber.
            フィルタ対象の二値繊維マスク。非ゼロが繊維。
        height_image
            Calibrated height map used by the low-height filter to measure each
            component's maximum height; must match ``mask`` in shape.
            低高さフィルタが各成分の最大高さを測るための補正済み高さマップ。
            ``mask`` と同形状であること。

        Returns
        -------
        ndarray
            Boolean mask after all component filters and the final closing.
            全成分フィルタと最終 closing を適用した後の真偽マスク。
        """
        binary = np.asarray(mask).astype(bool)

        self.no_small_binary_image = self._remove_small_fragments(binary, self.area_min)

        self.no_linear_binary_image = self._remove_nonlinear_objects(
            self.no_small_binary_image, self.h_length, self.h_sratio
        )
        if self.apply_no_connecting:
            self.no_connecting_binary_image = self._remove_connecting_fragments(
                self.no_linear_binary_image
            )
        else:
            self.no_connecting_binary_image = self.no_linear_binary_image

        self.no_low_binary_image = self.remove_low_component(
            height_image, self.no_connecting_binary_image
        )

        return closing(self.no_low_binary_image).astype(bool)

    @staticmethod
    def _binaryzation(
        image: np.ndarray,
        global_threshold: float,
        wsize_localbin: int,
    ) -> np.ndarray:
        """
        Combine global and local threshold masks.
        大域しきい値マスクと局所しきい値マスクを組み合わせる。
        """
        binary_global = image > global_threshold
        local_threshold = threshold_local(image, wsize_localbin)
        binary_local = image > local_threshold
        binary_final = binary_global & binary_local
        return binary_final

    @staticmethod
    def _remove_small_fragments(binary_image: np.ndarray, area_min: int) -> np.ndarray:
        """
        Remove connected components whose area is below the first threshold.
        最初の面積しきい値を下回る連結成分を除去する。
        """
        out_binary_image = binary_image.copy()
        n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
            np.uint8(out_binary_image), 8
        )
        areas = stats[:, cv2.CC_STAT_AREA]
        small_labels = np.where(areas <= area_min)[0]
        mask_remove = np.isin(label_image, small_labels)
        out_binary_image[mask_remove] = 0
        out_binary_image = cv2.medianBlur(out_binary_image.astype(np.float32), ksize=3)
        return out_binary_image.astype(bool)

    def _remove_nonlinear_objects(
        self,
        binary_image: np.ndarray,
        h_length: int,
        h_sratio: float,
        linegap: int = 1,
    ) -> np.ndarray:
        """
        Remove small components whose Hough-line score is below the threshold.
        Hough 直線スコアがしきい値を下回る小さい成分を除去する。
        """
        out_binary_image = binary_image.copy()
        n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
            np.uint8(out_binary_image), 8
        )
        for i in range(1, n_labels):
            left, top, width, height, area = stats[i]
            # Large components are retained without the linearity test.
            if area >= 1000:
                continue
            # Components shorter than the Hough threshold cannot form a retained line.
            if max(width, height) < self.h_length:
                out_binary_image[label_image == i] = 0
                continue
            target = out_binary_image[
                top : top + height, left : left + width
            ]
            target_edge = canny(target, sigma=0, low_threshold=0, high_threshold=1)
            # Use Hough accumulator votes as a proxy for detected line length.
            # Hough アキュムレータの投票数を、検出された直線長の代理指標として使う。
            h, theta, d = hough_line(target_edge)
            accums, _, _ = hough_line_peaks(
                h, theta, d,
                min_distance=max(1, linegap),
                min_angle=1,
                threshold=h_length,
            )
            if len(accums) > 0:
                total_length = float(np.sum(accums))
            else:
                total_length = 0.0
            # Offset the denominator so an empty edge map cannot divide by zero.
            # NumPy only warns (does not raise) on a zero denominator, so this
            # offset is the actual guard.
            # エッジマップが空でもゼロ除算にならないよう分母をオフセットする。
            # NumPy はゼロ除算でも例外を送出せず警告のみのため、このオフセットが
            # 実際の保護になる。
            s_ratio = total_length / (np.sum(target_edge) + _DENOM_EPS)
            self.h_sratio_list.append(s_ratio)

            if s_ratio < h_sratio and np.sum(target) < 1000:
                out_binary_image[label_image == i] = 0

        return out_binary_image

    def _remove_connecting_fragments(self, binary_image: np.ndarray) -> np.ndarray:
        """
        Remove small fragments after erosion separates weak connections.
        収縮で弱い接続を分離した後、小さい断片を除去する。
        """
        out_binary_image = binary_image.copy()
        out_binary_image = binary_erosion(out_binary_image)
        n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
            np.uint8(out_binary_image), 8
        )
        for i in range(n_labels - 1):
            *_, area = stats[i]
            if area <= self.area_min_connecting:
                out_binary_image[label_image == i] = 0
        out_binary_image = binary_dilation(out_binary_image)
        out_binary_image = closing(out_binary_image).astype(bool)
        return out_binary_image

    def remove_low_component(
        self,
        height_image: np.ndarray,
        binary_image: np.ndarray,
    ) -> np.ndarray:
        """
        Remove components whose maximum height is below `low_threshold`.
        最大高さが `low_threshold` 未満の成分を除去する。

        Parameters
        ----------
        height_image
            Calibrated AFM height map used to measure each component maximum.
            各成分の最大値を測定するための補正済み AFM 高さマップ。
        binary_image
            Binary component mask to filter.
            フィルタリング対象の二値成分マスク。

        Returns
        -------
        ndarray
            Binary mask with low-height components removed.
            高さの低い成分を除去した二値マスク。
        """
        out_binary_image = binary_image.copy()
        n_labels, label_image, data, centers = cv2.connectedComponentsWithStats(
            np.uint8(out_binary_image), 8
        )
        if n_labels <= 1:
            return out_binary_image
    
        labels = np.arange(1, n_labels)
        max_heights = ndi_maximum(height_image, labels=label_image, index=labels)
        low_labels = labels[np.asarray(max_heights) < self.low_threshold]
        if low_labels.size > 0:
            out_binary_image[np.isin(label_image, low_labels)] = 0
        return out_binary_image
