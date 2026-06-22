"""
Container for processed AFM image data and derived fiber metadata.
処理済み AFM 画像データと派生した繊維メタデータを保持するコンテナ。

This module stores the intermediate images and analysis outputs produced by
the preprocessing pipeline stages. It is a passive data container; Fiber
objects are built from this data by
`lib.fiber_tracking_image.FiberTrackingImage`.
このモジュールは前処理パイプライン各段階が生成する中間画像と解析結果を
保持する。受動的なデータコンテナであり、Fiber オブジェクトの構築は
`lib.fiber_tracking_image.FiberTrackingImage` が本データから行う。
"""

from typing import Optional

import numpy as np


class ProcessedImage:
    """
    Store processed AFM image data and derived fiber metadata.
    処理済み AFM 画像データと派生した繊維メタデータを保持する。

    Attributes
    ----------
    name
        Identifier or file name for this image.
        この画像の識別名またはファイル名。
    original_image
        Original 2D AFM image array.
        元の 2 次元 AFM 画像配列。
    size_per_pixel
        Physical size represented by one pixel (nm/px); None when the scan
        scale is unknown.
        1 ピクセルが表す実空間サイズ (nm/px)。スキャンスケール未知の場合は None。
    calibrated_image
        Background-corrected AFM height image set by the calibrator.
        キャリブレーション処理で設定される背景補正済み AFM 高さ画像。
    binarized_image
        Binary fiber mask set by the segmenter.
        セグメンテーション処理で設定される繊維の二値マスク。
    skeleton_image
        Skeletonized fiber image set by the skeletonizer.
        スケルトン化処理で設定される繊維の骨格画像。
    nLabels
        Number of connected-component labels generated from the skeleton.
        骨格画像から生成される連結成分ラベル数。
    data
        Connected-component statistics indexed by label.
        ラベルで参照する連結成分の統計情報。
    label_image
        Label image for connected components in the skeleton.
        骨格画像内の連結成分ラベル画像。
    bp
        Branch-point mask on the skeleton.
        骨格上の分岐点マスク。
    ep
        Endpoint mask on the skeleton.
        骨格上の終端点マスク。
    kink_indices_by_label
        Kink indices keyed by connected-component label.
        連結成分ラベルごとのキンク位置インデックス。
    kink_angles_by_label
        Kink angles keyed by connected-component label.
        連結成分ラベルごとのキンク角度。
    decomposed_indices_by_label
        Decomposition-point indices keyed by connected-component label.
        連結成分ラベルごとの分解点インデックス。
    """

    def __init__(
        self,
        original_AFM: np.ndarray,
        name: str,
        size_per_pixel: Optional[float] = None,
    ) -> None:
        """
        Initialize a container for AFM image processing results.
        AFM 画像処理結果を保持するコンテナを初期化する。

        Parameters
        ----------
        original_AFM
            Original 2D AFM image array.
            元の 2 次元 AFM 画像配列。
        name
            Identifier or file name for this image.
            この画像の識別名またはファイル名。
        size_per_pixel
            Physical size represented by one pixel (nm/px). None means the
            scan scale is unknown; the preprocessing stages never read this
            field, and leaving it None makes an accidental length computation
            fail loudly instead of silently assuming a default scan size.
            1 ピクセルが表す実空間サイズ (nm/px)。None はスキャンスケール
            未知を意味する。前処理ステージはこのフィールドを参照しないため、
            None のままなら誤って長さ計算に使われた際に、既定スキャンサイズを
            黙って仮定せず明示的に失敗する。
        """
        self.name: str = name
        self.original_image: np.ndarray = original_AFM
        self.size_per_pixel: Optional[float] = size_per_pixel

        # Store images produced by later pipeline stages.
        # 後続のパイプライン段階で生成される画像を保持する。
        self.calibrated_image: Optional[np.ndarray] = None
        self.binarized_image: Optional[np.ndarray] = None
        self.skeleton_image: Optional[np.ndarray] = None

        # Connected component outputs generated from skeleton image.
        # 骨格画像から生成される連結成分情報。
        self.nLabels: Optional[int] = None
        self.data: Optional[tuple] = None
        self.label_image: Optional[np.ndarray] = None

        # Branch points and endpoints on the skeleton.
        # 骨格上の分岐点と終端点。
        self.bp = None
        self.ep = None

        # Keep kink/decomposition indices by connected-component label.
        # キンク・分解点をラベルごとの辞書で保持する。
        # Mapping format: label(int) -> ndarray index array for xtrack/ytrack.
        # { label(int): ndarray of indices into that label's xtrack/ytrack }
        self.kink_indices_by_label: dict[int, np.ndarray] = {}
        self.kink_angles_by_label:  dict[int, np.ndarray] = {}
        self.decomposed_indices_by_label: dict[int, np.ndarray] = {}
