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
from skimage.filters import (
    apply_hysteresis_threshold, frangi, threshold_local, threshold_otsu,
    threshold_triangle,
)
from skimage.morphology import (
    binary_dilation, binary_erosion, closing, skeletonize,
)
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
        ridge_recovery: bool = False,
        ridge_min_length_nm: float = 100.0,
        ridge_min_width_nm: float = 3.0,
        ridge_max_width_nm: float = 20.0,
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
        ridge_recovery
            Whether to add fibers that thresholding missed entirely, found by
            a multi-scale ridge filter. Off by default: enabling it changes
            the analysis output.
            しきい値処理が完全に取りこぼした繊維を、マルチスケールのリッジ
            フィルタで検出して追加するか。既定は無効。有効にすると解析結果が
            変わる。
        ridge_min_length_nm
            Shortest recovered segment kept, as a physical length. Below about
            100 nm the candidates stop being distinguishable from particle
            skirts and tip artifacts by eye.
            回収するセグメントの最小長（物理量）。100 nm を下回るあたりから、
            候補を粒子の裾や探針アーティファクトと目視で区別できなくなる。
        ridge_min_width_nm, ridge_max_width_nm
            Fiber half-width range searched by the ridge filter, as physical
            lengths. Converted to pixel scales per image, so the same setting
            means the same physical structure at any scan resolution.
            リッジフィルタが探索する繊維半幅の範囲（物理量）。画像ごとに画素
            スケールへ換算するため、同じ設定値が走査解像度によらず同じ物理
            構造を意味する。
        """

        self.global_threshold = global_threshold
        self.wsize_localbin = wsize_localbin
        self.area_min = area_min
        self.area_min_connecting = area_min_connecting
        self.apply_no_connecting = apply_no_connecting
        self.low_threshold = low_threshold
        self.h_length = h_length
        self.h_sratio = h_sratio
        self.ridge_recovery = ridge_recovery
        self.ridge_min_length_nm = ridge_min_length_nm
        self.ridge_min_width_nm = ridge_min_width_nm
        self.ridge_max_width_nm = ridge_max_width_nm

        self.n_label = None
        self.no_linear = None

        # Keep intermediate masks available for tests and diagnostic inspection.
        self.binary_image: Optional[np.ndarray]
        self.no_small_binary_image: Optional[np.ndarray]
        self.no_linear_binary_image: Optional[np.ndarray]
        self.no_connecting_binary_image: Optional[np.ndarray]
        self.no_low_binary_image: Optional[np.ndarray]
        self.ridge_recovered_image: Optional[np.ndarray]

        self.max_height_list: list = []
        self.h_sratio_list: list = []

    def __call__(
        self, image: "ProcessedImage", nm_per_px: Optional[float] = None,
    ) -> None:
        """
        Segment a calibrated AFM image and store the binary mask on it.
        補正済み AFM 画像を分割し、二値マスクを画像オブジェクトに格納する。

        Parameters
        ----------
        image
            Processed image object with a `calibrated_image` height map.
            `calibrated_image` 高さマップを持つ処理済み画像オブジェクト。
        nm_per_px
            Pixel size in nanometres, required only by ridge recovery. When
            omitted the recovery step is skipped, because its length and width
            settings are physical and cannot be converted without it.
            画素サイズ (nm)。リッジ回収でのみ必要。省略時は回収段を行わない。
            回収段の長さ・幅設定は物理量であり、これなしでは換算できないため。

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
            self.binary_image, image.calibrated_image, nm_per_px
        )

    def apply_component_filters(
        self,
        mask: np.ndarray,
        height_image: np.ndarray,
        nm_per_px: Optional[float] = None,
    ) -> np.ndarray:
        """
        Apply the post-thresholding component filters to an external mask.
        外部から与えた二値マスクに、しきい値後の成分フィルタ群を適用する。

        Runs the same small-area, linearity, weak-connection, and maximum-height
        filters -- plus ridge recovery and the final morphological closing --
        that `__call__` applies after `_binaryzation`, but starting from ``mask``
        instead of this Segmenter's own thresholding output. This lets a mask
        produced elsewhere -- such as a machine-learning binarization model's
        prediction -- be carried through the exact same pipeline stage, so it can
        be compared against the stored ``binarized`` result at the same stage
        rather than as a raw prediction.
        `__call__` が `_binaryzation` の後に適用するのと同じ成分フィルタ（微小面積・
        線形性・弱接続・最大高さ）、リッジ回収、最終のモルフォロジー closing を、
        この Segmenter 自身のしきい値出力ではなく ``mask`` を起点に適用する。これに
        より、別途生成したマスク（例：機械学習の二値化モデルの予測）を全く同じ
        パイプライン段まで通し、保存済み ``binarized`` 結果と同じ段で比較できる。

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
        nm_per_px
            Pixel size in nanometres, required only by ridge recovery. Omitting
            it skips that step, so a caller comparing against a stored
            ``binarized`` mask must pass the same value `__call__` was given.
            画素サイズ (nm)。リッジ回収でのみ必要。省略すると回収段を行わないため、
            保存済み ``binarized`` マスクと比較する呼び出し側は `__call__` に渡した
            値と同じものを渡すこと。

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

        # Ridge recovery runs before the closing so a recovered segment that
        # ends next to a kept component is bridged into it rather than left as
        # a separate short fiber.
        # リッジ回収は closing の前に行う。既存成分の隣で終わる回収セグメントが
        # 独立した短繊維として残らず、closing で橋渡しされるようにするため。
        self.ridge_recovered_image = self._recover_missed_ridges(
            height_image, self.no_low_binary_image, nm_per_px,
        )
        recovered_union = self.no_low_binary_image | self.ridge_recovered_image

        return closing(recovered_union).astype(bool)

    def _recover_missed_ridges(
        self,
        calibrated_image: np.ndarray,
        binary_image: np.ndarray,
        nm_per_px: Optional[float],
    ) -> np.ndarray:
        """
        Find fibers the thresholding pipeline missed entirely.
        しきい値処理が完全に取りこぼした繊維を検出する。

        Parameters
        ----------
        calibrated_image
            Background-corrected height map the ridge filter runs on.
            リッジフィルタを適用する背景補正済み高さマップ。
        binary_image
            Mask accepted so far; only material outside it can be recovered.
            ここまでに採用されたマスク。この外側の実体だけが回収対象となる。
        nm_per_px
            Pixel size in nanometres, or None to skip recovery.
            画素サイズ (nm)。None なら回収を行わない。

        Returns
        -------
        np.ndarray
            Boolean mask of recovered segments; all False when disabled.
            回収したセグメントの真偽マスク。無効時は全て False。

        Notes
        -----
        The candidate mask is subtracted from `binary_image` *before* the
        connected-component pass, not after. Taking whole candidate components
        that merely fail to touch the existing mask discards a long fiber the
        moment it brushes the detected network anywhere, and long fibers touch
        it most often — measured on one 10 um scan, 56 candidate components
        held at least 100 nm of fiber outside the mask, one of them 1476 nm,
        and all were dropped by that rule.
        候補マスクは連結成分処理の *前* に `binary_image` を差し引く。既存
        マスクに一切触れない成分だけを採る方式では、長い繊維が検出済みの網目
        にどこか一点でも接した瞬間に丸ごと捨てられ、しかも長い繊維ほど接触
        しやすい。ある 10 um 走査での実測では、マスク外に 100 nm 以上の実体を
        持つ候補成分が 56 個あり（最大 1476 nm）、その全てが捨てられていた。

        Hysteresis on the ridge response works where the same scheme on raw
        amplitude does not: the response falls to near zero between fibers, so
        the region grows to a boundary instead of percolating across the image.
        リッジ応答に対するヒステリシスは、生の振幅に対する同じ方式と違って
        機能する。応答は繊維間でほぼ 0 まで落ちるため、領域は画像全体へ
        浸透せず境界で止まる。
        """
        empty = np.zeros_like(binary_image, dtype=bool)
        if not self.ridge_recovery or not nm_per_px or nm_per_px <= 0:
            return empty

        # Physical half-widths become pixel scales here, so one setting means
        # the same structure whatever the scan resolution.
        lo = max(0.6, self.ridge_min_width_nm / nm_per_px)
        hi = max(lo * 1.5, self.ridge_max_width_nm / nm_per_px)
        sigmas = np.geomspace(lo, hi, 5)
        response = np.nan_to_num(
            frangi(calibrated_image, sigmas=sigmas, black_ridges=False)
        )
        if not np.any(response > 0):
            return empty
        try:
            high = threshold_otsu(response)
            low = threshold_triangle(response)
        except ValueError:
            # Degenerate response histogram; nothing dependable to recover.
            return empty
        if not low < high:
            low = high * 0.3
        candidate = apply_hysteresis_threshold(response, low, high)

        outside = candidate & ~binary_image.astype(bool)
        if not outside.any():
            return empty
        n_labels, labels = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
        keep = [
            label for label in range(1, n_labels)
            if skeletonize(labels == label).sum() * nm_per_px >= self.ridge_min_length_nm
        ]
        if not keep:
            return empty
        return np.isin(labels, keep)

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
