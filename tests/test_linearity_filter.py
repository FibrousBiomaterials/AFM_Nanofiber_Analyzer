# -*- coding: utf-8 -*-
"""
Tests for the linearity filter, `Segmenter._remove_nonlinear_objects`.
直線性フィルタ `Segmenter._remove_nonlinear_objects` のテスト。

The filter keeps a component whose outline follows straight lines at least
`h_length` long. These tests pin that the verdict does not depend on how a
shape lies on the pixel grid: a straight rod is kept at every angle, including
along the rows and columns, and a shape too short or too round is removed at
every angle.
フィルタは、輪郭が `h_length` 以上の直線に沿う成分を残す。本テストは、判定が
形の格子への置かれ方によらないことを固定する。まっすぐな棒は行や列に沿う向きを
含めどの角度でも残り、短すぎる形や丸い形はどの角度でも除かれる。
"""

import numpy as np
import pytest

from lib.segmenter import Segmenter, _max_extent_px

H_LENGTH = 20
H_SRATIO = 0.5
ANGLES = range(0, 91, 5)


def _rod(length: float, width: float, angle_deg: float, offset=(0.0, 0.0)) -> np.ndarray:
    """
    Mask of a rod with round ends (a stadium) of the given length and width.
    指定した長さと幅の、両端が丸い棒（スタジアム形）のマスク。
    """
    n = int(length + width + 12)
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    cx, cy = n / 2 + offset[0], n / 2 + offset[1]
    ux, uy = np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))
    px, py = xx - cx, yy - cy
    t = np.clip(px * ux + py * uy, -(length - width) / 2, (length - width) / 2)
    return np.hypot(px - t * ux, py - t * uy) <= width / 2


def _kept(mask: np.ndarray) -> bool:
    seg = Segmenter()
    out = seg._remove_nonlinear_objects(mask.copy(), H_LENGTH, H_SRATIO)
    return bool(out.any())


@pytest.mark.parametrize("width", [3, 5, 7, 9])
def test_long_straight_rod_is_kept_at_every_angle(width):
    """A rod twice h_length long is kept whether or not it lies along an axis."""
    rng = np.random.default_rng(width)
    for angle in ANGLES:
        offset = tuple(rng.uniform(-0.5, 0.5, 2))
        assert _kept(_rod(2 * H_LENGTH, width, angle, offset)), angle


@pytest.mark.parametrize("axis", [0, 1])
def test_band_along_rows_or_columns_is_kept(axis):
    """Both long borders of an axis-parallel band lie on its box; they still count."""
    band = np.zeros((20, 80), dtype=bool)
    band[8:12, 10:70] = True
    assert _kept(band if axis == 0 else band.T)


def test_short_rod_is_removed_at_every_angle():
    """A rod shorter than h_length cannot hold a line of that length."""
    for angle in ANGLES:
        assert not _kept(_rod(H_LENGTH - 4, 5, angle)), angle


def test_round_blob_is_removed():
    """A disc has no straight outline, however large its extent."""
    yy, xx = np.mgrid[0:40, 0:40]
    disc = np.hypot(xx - 19.5, yy - 19.5) <= 13
    assert _max_extent_px(disc) >= H_LENGTH
    assert not _kept(disc)


def test_max_extent_follows_the_shape_not_the_grid():
    """A pixel run measures about its length along a row and along a diagonal."""
    row = np.zeros((5, 30), dtype=bool)
    row[2, 5:25] = True
    diagonal = np.eye(20, dtype=bool)
    assert _max_extent_px(row) == pytest.approx(np.hypot(20, 1))
    assert _max_extent_px(diagonal) == pytest.approx(20 * np.sqrt(2))
