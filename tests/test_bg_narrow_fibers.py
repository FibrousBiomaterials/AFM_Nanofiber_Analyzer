# -*- coding: utf-8 -*-
"""
Tests that the trendfill fiber mask covers narrow fibers in every direction.
trendfill の繊維マスクが細い繊維をどの向きでも覆うことのテスト。

A fiber narrower than `noise_detect_factor` pixels that runs along a scan axis
is crossed at right angles by every scan line of the other axis, so pattern 2
of `BGCalibrator._extract_fiber` sees only a short span on each line. These
tests pin that such a fiber is still masked, at any position of its crest on
the pixel grid, and that its height is not subtracted with the background,
while an isolated short mark is still rejected.
`noise_detect_factor` 画素より細く走査軸に沿って走る繊維は、もう一方の軸のどの
走査線にも直角に横切られるため、`BGCalibrator._extract_fiber` のパターン2は
各線で短い長さしか見ない。本テストは、頂部が画素格子のどこにあってもそうした
繊維がマスクされ、その高さが背景と一緒に差し引かれないこと、そして孤立した
短い印は引き続き退けられることを固定する。
"""

import math

import numpy as np
import pytest

from lib.pipeline import ProcParams, build_stages
from lib.processed_image import ProcessedImage

N = 200
NM_PER_PX = 5.0
DIAMETER_NM = 8.0
TIP_RADIUS_NM = 15.0


def _scan(angle_deg: float, phase_px: float):
    """
    One straight fiber of known height, point-sampled from a tip-dilated cylinder.
    探針で膨張させた円柱から点標本化した、高さが既知の直線繊維 1 本。

    Returns the raw scan, the fiber alone, and a mask of the pixels on its axis.
    生の走査、繊維だけの画像、軸上の画素のマスクを返す。
    """
    r = DIAMETER_NM / 2.0
    yy, xx = np.mgrid[0:N, 0:N].astype(float) + 0.5
    t = math.radians(angle_deg)
    cx = N / 2.0 - phase_px * math.sin(t)
    cy = N / 2.0 + phase_px * math.cos(t)
    d = (-(xx - cx) * math.sin(t) + (yy - cy) * math.cos(t)) * NM_PER_PX
    s = (xx - cx) * math.cos(t) + (yy - cy) * math.sin(t)
    fiber = np.maximum(
        r + np.sqrt(np.maximum((r + TIP_RADIUS_NM) ** 2 - d ** 2, 0.0)) - TIP_RADIUS_NM, 0.0
    ) * (np.abs(s) < 70)
    axis = (np.abs(d) < 0.71 * NM_PER_PX) & (np.abs(s) < 55)
    rng = np.random.default_rng(0)
    raw = fiber + rng.normal(0.0, 0.05, (N, N)) + np.linspace(0.0, 1.0, N)[None, :]
    return raw, fiber, axis


@pytest.mark.parametrize("angle_deg", [0.0, 3.0, 45.0, 90.0])
@pytest.mark.parametrize("phase_px", [0.0, 0.25, 0.5])
def test_narrow_fiber_is_masked_and_keeps_its_height(angle_deg, phase_px):
    raw, fiber, axis = _scan(angle_deg, phase_px)
    bg = build_stages(ProcParams()).bg_calibrator
    image = ProcessedImage(original_AFM=raw, name="narrow")
    bg(image)
    # The calibrated arrays drop the first row and column (`_bg_generate`).
    rows, cols = np.nonzero(axis[1:, 1:])
    masked = np.isnan(bg.bg_only)[rows, cols]
    assert masked.mean() > 0.95
    truth = fiber[1:, 1:][rows, cols]
    kept = np.median(image.calibrated_image[rows, cols] / truth)
    assert kept > 0.95


def test_isolated_short_mark_is_rejected_and_lined_up_marks_are_kept():
    bg = build_stages(ProcParams()).bg_calibrator
    limit = int(bg.noise_detect_factor)
    fill = np.zeros((40, 60))
    short = np.zeros((40, 60), dtype=bool)
    # An isolated mark a few pixels long, as a noise step leaves.
    short[5, 3:7] = True
    # Short marks on consecutive lines, as a narrow fiber crossed at right
    # angles leaves along its length.
    short[20:40, 30:33] = True
    keep = bg._lined_up_marks(fill, short)
    assert not keep[5, 3:7].any()
    assert keep[20:40, 30:33].all()
    assert 20 > limit
