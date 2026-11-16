# -*- coding: utf-8 -*-
"""
Tests that the background calibrator's trim is the one the pixel size assumes.
背景補正器の切り落としが、画素サイズの前提と一致することのテスト。

Every background method stores ``original[1:, 1:]``: the first row and column
of the analyzed image are dropped. The recorded scan size spans the image
before that trim, so `bundle_schema.pixel_size_nm` divides it by the stored
count plus one, and the pipeline's absorbed-fraction check compares the stored
image with ``raw[1:, 1:]``. Nothing else ties these to the calibrator, so a
background method that trimmed differently would leave every measured length
and the readers' pixel sizes silently off. These tests fail first, which is
the signal to make the pixel size follow the bundle's format (see
`bundle_schema.pixel_size_nm`).
どの背景補正方法も ``original[1:, 1:]`` を保存し、解析画像の先頭の 1 行 1 列を
落とす。記録される走査範囲はこの切り落としの前の画像の寸法なので、
`bundle_schema.pixel_size_nm` はそれを保存画素数に 1 を足した数で割り、
パイプラインの吸収割合の検査は保存画像を ``raw[1:, 1:]`` と比べる。これらを
補正器と結び付けるものは他に無く、切り落とし方の違う背景補正方法は、すべての
計測長と読む側の画素サイズを黙ってずらす。本テストはその前に失敗し、画素サイズを
バンドルの形式に従わせる作業が要ることを知らせる（`bundle_schema.pixel_size_nm`
参照）。
"""

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Test / project libraries =====
import pytest

from lib.bg_calibrator import BG_METHOD_NAMES
from lib.bundle_schema import pixel_size_nm
from lib.pipeline import ProcParams, build_stages
from lib.processed_image import ProcessedImage

ROWS, COLS = 64, 96


def _calibrate(method: str):
    """
    Run one background method on a small noisy scan with one fiber on a tilt.
    傾きの上に繊維 1 本を載せたノイズのある小さな走査に、背景補正を 1 つ適用する。

    Returns the raw scan and the calibrated image.
    生の走査と補正済み画像を返す。
    """
    rng = np.random.default_rng(0)
    raw = rng.normal(0.0, 0.05, (ROWS, COLS)) + np.linspace(0.0, 1.0, COLS)[None, :]
    raw[ROWS // 2 - 1:ROWS // 2 + 2, 10:COLS - 10] += 2.0
    bg = build_stages(ProcParams(bg_method=method)).bg_calibrator
    image = ProcessedImage(original_AFM=raw, name="trim")
    bg(image)
    return raw, np.asarray(image.calibrated_image, dtype=float)


@pytest.mark.parametrize("method", BG_METHOD_NAMES)
def test_one_row_and_column_are_dropped_as_the_pixel_size_assumes(method):
    raw, cal = _calibrate(method)
    assert (ROWS - cal.shape[0], COLS - cal.shape[1]) == (1, 1)
    # The recorded scan size spans the raw image, so one stored pixel is the
    # scan size over the raw count, which is what pixel_size_nm returns.
    # 記録される走査範囲は生の画像に渡るため、保存画素 1 つは走査範囲を生の画素数で
    # 割った大きさであり、pixel_size_nm はそれを返す。
    assert pixel_size_nm(1.0, cal.shape[1]) == pytest.approx(1000.0 / COLS)
    assert pixel_size_nm(1.0, cal.shape[0]) == pytest.approx(1000.0 / ROWS)


@pytest.mark.parametrize("method", BG_METHOD_NAMES)
def test_the_first_row_and_column_are_the_ones_dropped(method):
    raw, cal = _calibrate(method)
    # The subtracted background is smooth, so the difference between
    # neighbouring pixels keeps the scan's own noise; it matches the raw scan
    # only at the offset the trim actually used.
    # 差し引く背景は滑らかなので、隣の画素との差には走査自身のノイズが残る。
    # それが生の走査と一致するのは、実際に切り落とした位置だけである。
    def noise(a):
        return np.diff(a, axis=1).ravel()

    leading = np.corrcoef(noise(cal), noise(raw[1:, 1:]))[0, 1]
    trailing = np.corrcoef(noise(cal), noise(raw[:-1, :-1]))[0, 1]
    assert leading > 0.9
    assert leading > trailing + 0.5
