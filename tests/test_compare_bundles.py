# -*- coding: utf-8 -*-
"""
Tests for the comparisons of `scripts/compare_bundles.py`.
`scripts/compare_bundles.py` の比較処理のテスト。
"""

import dataclasses
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))
import compare_bundles as cb  # noqa: E402


def test_identical_arrays_report_nothing():
    a = {"kp": np.array([[1, 2], [3, 4]]), "ka": np.array([2.5, np.nan])}
    assert cb.compare_arrays(a, {k: v.copy() for k, v in a.items()}) == []


def test_each_kind_of_array_difference_is_named():
    old = {"kp": np.zeros((2, 3), int), "ka": np.array([1.0, 2.0]),
           "bp": np.zeros(4, np.uint8), "up": np.zeros((2, 0))}
    new = {"kp": np.zeros((2, 2), int), "ka": np.array([1.0, 2.5]),
           "bp": np.zeros(4, bool), "ke": np.zeros(0)}
    out = cb.compare_arrays(old, new)
    assert "kp: shape (2, 3) -> (2, 2)" in out
    assert "ka: 1 of 2 values differ" in out
    assert "bp: dtype uint8 -> bool" in out
    assert "up: only in the old bundle" in out
    assert "ke: only in the new bundle" in out


def test_a_parameter_added_since_counts_only_when_not_default():
    old = {"bg_method": "trendfill"}
    assert cb.compare_params(old, {"bg_method": "trendfill",
                                   "centerline_method": "half_max_025w"}) == []
    out = cb.compare_params(old, {"bg_method": "tophat", "centerline_method": "crest"})
    assert "bg_method: 'trendfill' -> 'tophat'" in out
    assert any(o.startswith("centerline_method: not recorded") for o in out)


@dataclasses.dataclass
class _Stat:
    length_nm: float
    kink_angles: tuple


def test_fiber_statistics_compare_nan_and_sequences():
    old = [_Stat(float("nan"), (1.0, 2.0)), _Stat(3.0, ())]
    assert cb.compare_stats(old, [_Stat(float("nan"), (1.0, 2.0)), _Stat(3.0, ())]) == []
    out = cb.compare_stats(old, [_Stat(1.0, (1.0, 2.0)), _Stat(3.0, (0.5,))])
    assert any(o.startswith("fiber 0 length_nm") for o in out)
    assert any(o.startswith("fiber 1 kink_angles") for o in out)
    assert cb.compare_stats(old, old[:1]) == ["fiber count 2 -> 1"]
