# -*- coding: utf-8 -*-
"""
Tests for pipeline-stage precondition checks.
パイプラインステージの事前条件チェックのテスト。

Each stage of the GUI01 preprocessing pipeline reads attributes that earlier
stages must have written into the shared `ProcessedImage`. These tests verify
that running a stage out of order fails immediately at the stage boundary
with a self-explanatory ValueError, instead of surfacing as an unrelated
NoneType error deep inside cv2/scipy/skimage.
GUI01 前処理パイプラインの各ステージは、前段が共有 `ProcessedImage` に
書き込んだ属性を読む。本テストは、誤った順序でステージを実行したとき、
cv2/scipy/skimage の深部で無関係な NoneType エラーになる代わりに、
ステージ境界で自己説明的な ValueError として即座に失敗することを検証する。
"""

import numpy as np
import pytest

from lib.bg_calibrator_shimadzu import BG_Calibrator_shimadzu
from lib.kink_detector import KinkDetector
from lib.processed_image import ProcessedImage
from lib.segmenter import Segmenter
from lib.skeletonizer import Skeletonizer


def _fresh_image() -> ProcessedImage:
    """Return a ProcessedImage on which no pipeline stage has run yet."""
    return ProcessedImage(original_AFM=np.zeros((16, 16)), name="precond")


def test_bg_calibrator_rejects_missing_original():
    """BG calibration fails clearly when the raw height image is absent."""
    image = ProcessedImage(original_AFM=None, name="precond")
    with pytest.raises(ValueError, match="original_image"):
        BG_Calibrator_shimadzu()(image)


def test_segmenter_rejects_uncalibrated_image():
    """Segmenter names the missing input and the stage to run first."""
    with pytest.raises(ValueError, match="calibrated_image"):
        Segmenter()(_fresh_image())


def test_skeletonizer_rejects_unsegmented_image():
    """Skeletonizer fails clearly when binarization has not run."""
    with pytest.raises(ValueError, match="binarized_image"):
        Skeletonizer()(_fresh_image())


def test_skeletonizer_rejects_missing_calibrated_image():
    """Skeletonizer also requires the calibrated heights for branch pruning."""
    image = _fresh_image()
    image.binarized_image = np.zeros((16, 16), dtype=bool)
    image.calibrated_image = None
    with pytest.raises(ValueError, match="calibrated_image"):
        Skeletonizer()(image)


def test_kink_detector_rejects_unskeletonized_image():
    """KinkDetector fails clearly when skeletonization has not run."""
    with pytest.raises(ValueError, match="skeleton_image"):
        KinkDetector()(_fresh_image())
