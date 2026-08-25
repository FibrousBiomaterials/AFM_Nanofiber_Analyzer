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
    Height map with one broad ridge and one faint narrow ridge.
    太い尾根 1 本と細く淡い尾根 1 本を持つ高さマップ。

    The broad ridge clears `area_min` on its own; the faint one is the kind of
    structure the amplitude path drops, so it is the candidate for recovery.
    太い尾根は単独で `area_min` を満たす。淡い尾根は振幅経路が落とす種類の
    構造で、回収の候補になる。
    """
    rng = np.random.default_rng(0)
    img = rng.normal(0.0, 0.05, size=(200, 200))
    rows = np.arange(200)
    # Broad, tall diagonal ridge.
    for offset in range(-3, 4):
        img[rows, np.clip(rows + offset, 0, 199)] += 6.0
    # Faint, narrow horizontal ridge well away from the broad one.
    img[160:162, 20:180] += 2.2
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
    """The faint ridge is exactly the structure recovery exists to pick up."""
    arr = _two_fiber_image()
    off, _ = _segment(arr, recovery=False, nm_per_px=10.0)
    on, _ = _segment(arr, recovery=True, nm_per_px=10.0)
    faint = np.zeros_like(off)
    faint[160:162, 20:180] = True
    assert off[faint].sum() < faint.sum() * 0.5, "fixture no longer misses the faint ridge"
    assert on[faint].sum() > off[faint].sum(), "recovery did not pick up the faint ridge"


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
