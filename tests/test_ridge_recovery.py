# -*- coding: utf-8 -*-
"""
Tests for the optional ridge-recovery step in `lib.segmenter`.
`lib.segmenter` の任意リッジ回収段のテスト。

Recovery adds fibers that thresholding missed entirely. It is off by default
because enabling it changes analysis output, so the tests pin both the
default-off behaviour and the structural guarantee that recovery only ever
adds: a recovered mask must be a superset of the mask without it, never a
different segmentation.
回収段は、しきい値処理が完全に取りこぼした繊維を追加する。有効化すると解析
結果が変わるため既定は無効であり、本テストは既定無効の挙動と、「回収は追加
しかしない」という構造的保証（回収後のマスクは回収なしのマスクの上位集合で
あり、別物の分割にはならない）を固定する。
"""

import numpy as np
import pytest

from lib.pipeline import ProcParams, validate_params
from lib.processed_image import ProcessedImage
from lib.segmenter import Segmenter


def _two_fiber_image() -> np.ndarray:
    """
    Height map with one broad ridge and one short narrow ridge.
    太い尾根 1 本と短く細い尾根 1 本を持つ高さマップ。

    The broad ridge clears `area_min` on its own; the short one, 2 by 40 px,
    binarizes to fewer pixels than `area_min` (100 in `_segment`), so the
    amplitude path drops it, while at 10 nm per pixel it is long enough for
    recovery's length test, so it is the candidate for recovery.
    太い尾根は単独で `area_min` を満たす。短い尾根は 2 × 40 px で、二値化すると
    `area_min`（`_segment` では 100）より画素が少ないので振幅経路が落とすが、
    画素 10 nm では回収の長さの判定を通るので、回収の候補になる。
    """
    rng = np.random.default_rng(0)
    img = rng.normal(0.0, 0.05, size=(200, 200))
    rows = np.arange(200)
    # Broad, tall diagonal ridge.
    for offset in range(-3, 4):
        img[rows, np.clip(rows + offset, 0, 199)] += 6.0
    # Short, narrow horizontal ridge well away from the broad one.
    img[160:162, 20:60] += 2.2
    return img


def _segment(image_array, *, recovery, nm_per_px):
    seg = Segmenter(
        area_min=100, area_min_connecting=3, apply_no_connecting=False,
        low_threshold=1.0, global_threshold=0.3, wsize_localbin=17,
        h_length=20, h_sratio=0.5, ridge_recovery=recovery,
        ridge_min_length_nm=100.0,
    )
    img = ProcessedImage(original_AFM=image_array, name="ridge")
    img.calibrated_image = image_array
    seg(img, nm_per_px=nm_per_px)
    return np.asarray(img.binarized_image, dtype=bool), seg


def test_recovery_off_by_default():
    """A default ProcParams must not enable recovery."""
    assert ProcParams().ridge_recovery is False


def test_disabled_recovery_leaves_mask_untouched():
    """With recovery off, the mask must match a run that never had the feature."""
    arr = _two_fiber_image()
    off, seg = _segment(arr, recovery=False, nm_per_px=10.0)
    assert not seg.ridge_recovered_image.any()
    # The recovered mask is empty, so the union step cannot have changed anything.
    assert np.array_equal(off, _segment(arr, recovery=False, nm_per_px=None)[0])


def test_recovery_needs_a_pixel_size():
    """
    Without nm_per_px the physical settings cannot be converted, so recovery
    must skip rather than guess a pixel size.
    nm_per_px が無ければ物理設定を換算できないため、画素サイズを推測せず
    回収を飛ばさなければならない。
    """
    arr = _two_fiber_image()
    off, _ = _segment(arr, recovery=False, nm_per_px=None)
    on_without_scale, seg = _segment(arr, recovery=True, nm_per_px=None)
    assert not seg.ridge_recovered_image.any()
    assert np.array_equal(off, on_without_scale)


def test_recovery_only_adds():
    """
    Recovery must be additive: every pixel kept without it stays kept.
    回収は追加のみでなければならない。回収なしで残った画素は全て残る。
    """
    arr = _two_fiber_image()
    off, _ = _segment(arr, recovery=False, nm_per_px=10.0)
    on, seg = _segment(arr, recovery=True, nm_per_px=10.0)
    assert np.all(on[off]), "recovery removed pixels that were previously kept"
    # Whatever it added must lie outside the pre-recovery mask by construction.
    assert not (seg.ridge_recovered_image & seg.no_low_binary_image).any()


def test_recovery_finds_the_faint_ridge():
    """The short ridge is exactly the structure recovery exists to pick up."""
    arr = _two_fiber_image()
    off, _ = _segment(arr, recovery=False, nm_per_px=10.0)
    on, _ = _segment(arr, recovery=True, nm_per_px=10.0)
    faint = np.zeros_like(off)
    faint[160:162, 20:60] = True
    assert off[faint].sum() < faint.sum() * 0.5, "fixture no longer misses the short ridge"
    assert on[faint].sum() > off[faint].sum(), "recovery did not pick up the short ridge"


@pytest.mark.parametrize("field, value", [
    ("ridge_recovery", "yes"),
    ("ridge_min_length_nm", 0.0),
    ("ridge_min_width_nm", -1.0),
    ("ridge_max_width_nm", 1.0),   # not greater than ridge_min_width_nm (3.0)
])
def test_validate_params_rejects_bad_ridge_settings(field, value):
    """`validate_params` collects problems rather than raising, so check the report."""
    problems = validate_params(ProcParams(**{field: value}))
    assert any(field in message for message in problems), problems


def test_validate_params_accepts_the_defaults():
    assert validate_params(ProcParams()) == []


def _scene_on_grid(y_nm_per_px, x_nm_per_px=2.0, size_nm=400.0):
    """
    One physical scene sampled on a grid of the given pixel sizes.
    1 つの実空間の場面を、指定した画素サイズの格子で標本化する。

    A long faint ridge runs along X; a 150 nm one runs along Y, which the
    100 nm length test keeps only when its length is measured physically.
    長く淡い尾根が X に沿って走り、150 nm の尾根が Y に沿って走る。後者は、長さを
    実寸で測ったときにだけ 100 nm の長さの判定を通る。
    """
    rows, cols = int(size_nm / y_nm_per_px), int(size_nm / x_nm_per_px)
    yy, xx = np.mgrid[0:rows, 0:cols]
    y, x = yy * y_nm_per_px, xx * x_nm_per_px
    sigma = 6.0
    along_x = np.exp(-((y - 100) ** 2) / (2 * sigma ** 2)) * ((x > 40) & (x < 360))
    along_y = np.exp(-((x - 200) ** 2) / (2 * sigma ** 2)) * ((y > 200) & (y < 350))
    noise = np.random.default_rng(0).normal(0.0, 0.05, along_x.shape)
    short_zone = (y > 190) & (y < 360) & (np.abs(x - 200) < 20)
    return 1.5 * (along_x + along_y) + noise, short_zone


def test_recovery_measures_non_square_pixels_physically():
    """
    On pixels twice as tall as wide, a ridge along Y is judged by its real length.
    幅の 2 倍の高さの画素でも、Y に沿う尾根は実際の長さで判定されること。

    Taken as square, the 150 nm ridge counts as 75 nm and is dropped.
    正方画素とみなすと、150 nm の尾根は 75 nm と数えられて落とされる。
    """
    seg = Segmenter(ridge_recovery=True, ridge_min_length_nm=100.0)
    square, square_zone = _scene_on_grid(2.0)
    tall, tall_zone = _scene_on_grid(4.0)
    on_square = seg._recover_missed_ridges(square, np.zeros(square.shape, bool), 2.0)
    on_tall = seg._recover_missed_ridges(tall, np.zeros(tall.shape, bool), 2.0, 2.0)
    as_square = seg._recover_missed_ridges(tall, np.zeros(tall.shape, bool), 2.0, 1.0)

    square_area = (on_square & square_zone).sum() * 2.0 * 2.0
    tall_area = (on_tall & tall_zone).sum() * 2.0 * 4.0
    assert square_area > 0
    assert tall_area == pytest.approx(square_area, rel=0.2)
    assert not (as_square & tall_zone).any()


def test_recovery_on_square_pixels_ignores_the_resampling():
    """
    An aspect of 1 leaves the square-pixel computation exactly as it was.
    縦横比 1 では、正方画素の計算がそのまま変わらないこと。
    """
    arr = _two_fiber_image()
    seg = Segmenter(ridge_recovery=True, ridge_min_length_nm=100.0)
    base = seg._recover_missed_ridges(arr, np.zeros(arr.shape, bool), 10.0)
    explicit = seg._recover_missed_ridges(arr, np.zeros(arr.shape, bool), 10.0, 1.0)
    assert np.array_equal(base, explicit)
