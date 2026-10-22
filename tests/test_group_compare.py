# -*- coding: utf-8 -*-
"""
Tests for lib/group_compare.py.
lib/group_compare.py のテスト。

The effect size is checked against its brute-force definition and the Holm
correction against a worked textbook example, so both stay verifiable without
trusting the implementation they are testing.
効果量はブルートフォースの定義と、Holm 補正は教科書の計算例と突き合わせて検証
する。いずれも被検対象の実装を信頼せずに確認できるようにするためである。
"""

import numpy as np
import pytest

from lib.group_compare import (
    MAGNITUDE_LARGE,
    PairComparison,
    cliffs_delta,
    compare_groups,
    delta_magnitude,
    holm_adjusted,
)


def _brute_force_delta(a, b):
    """Cliff's delta straight from its definition, ties included."""
    a = np.asarray(a, dtype=float)[:, None]
    b = np.asarray(b, dtype=float)[None, :]
    return (np.sum(a > b) - np.sum(a < b)) / (a.size * b.size)


def test_cliffs_delta_matches_its_definition():
    """The rank-derived value equals the pairwise count, ties and all."""
    rng = np.random.default_rng(0)
    # Small integer range so ties are common, which is where the U-statistic
    # shortcut could diverge from the definition if the half-credit for ties
    # were handled wrongly.
    # 同順位が多く出るよう整数の範囲を狭くする。同順位への 0.5 の扱いを誤ると
    # U 統計量による近道が定義から外れるのは、まさにこの状況である。
    a = rng.integers(0, 6, 200).astype(float)
    b = rng.integers(0, 6, 170).astype(float)
    assert cliffs_delta(a, b) == pytest.approx(_brute_force_delta(a, b))


def test_cliffs_delta_bounds():
    """Identical samples give zero and disjoint ones give the extremes."""
    sample = np.array([1.0, 2.0, 3.0, 4.0])
    assert cliffs_delta(sample, sample) == pytest.approx(0.0)
    assert cliffs_delta(np.array([10.0, 11.0]), np.array([1.0, 2.0])) == 1.0
    assert cliffs_delta(np.array([1.0, 2.0]), np.array([10.0, 11.0])) == -1.0


def test_cliffs_delta_of_an_empty_sample_is_undefined():
    """An empty sample yields NaN rather than a made-up zero."""
    assert np.isnan(cliffs_delta(np.array([]), np.array([1.0])))


def test_holm_matches_a_worked_example():
    """Holm on (0.01, 0.04, 0.03) gives (0.03, 0.06, 0.06)."""
    assert holm_adjusted([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_is_monotone_and_capped():
    """Adjusted values never decrease with the raw order and never exceed 1."""
    adjusted = holm_adjusted([0.2, 0.3, 0.4, 0.5])
    assert all(p <= 1.0 for p in adjusted)
    assert adjusted == sorted(adjusted)


def test_holm_passes_nan_through():
    """A comparison that could not be tested stays untested after correction."""
    adjusted = holm_adjusted([0.01, float("nan")])
    assert adjusted[0] == pytest.approx(0.01)
    assert np.isnan(adjusted[1])


def test_compare_groups_pairs_every_combination():
    """Three groups produce the three unordered pairs, in formation order."""
    rng = np.random.default_rng(1)
    groups = [(name, rng.normal(0, 1, 40)) for name in ("A", "B", "C")]
    results = compare_groups(groups)
    assert [(r.group_a, r.group_b) for r in results] == [
        ("A", "B"), ("A", "C"), ("B", "C"),
    ]
    assert all(isinstance(r, PairComparison) for r in results)


def test_compare_groups_needs_two_groups():
    """A single group has nothing to compare against."""
    assert compare_groups([("A", np.array([1.0, 2.0, 3.0]))]) == []


def test_compare_groups_separates_a_shifted_group():
    """A clearly shifted group is both significant and a large effect."""
    rng = np.random.default_rng(2)
    results = compare_groups([
        ("low", rng.normal(0.0, 1.0, 80)),
        ("high", rng.normal(3.0, 1.0, 80)),
    ])
    assert len(results) == 1
    result = results[0]
    assert result.mannwhitney_p_adjusted < 0.001
    assert result.ks_p_adjusted < 0.001
    assert result.magnitude == MAGNITUDE_LARGE
    # "low" is stochastically below "high", so delta is negative.
    # "low" は "high" より確率的に下側にあるため、delta は負になる。
    assert result.cliffs_delta < -0.9


def test_compare_groups_reports_untestable_pairs_without_numbers():
    """
    A pair too small to test keeps its row but carries no statistics.
    検定するには小さすぎるペアも行は残るが、統計量は持たない。

    Dropping the row would hide a group from the comparison table; filling it
    in would present numbers that the sample size cannot support -- Cliff's
    delta is defined for one observation against one, where it always reads
    plus or minus one.
    行を落とすとそのグループが比較表から消える。埋めれば標本数が支えられない
    数値を提示することになる。Cliff's delta は 1 観測対 1 観測でも定義され、
    その場合は必ず ±1 になるためである。
    """
    results = compare_groups([
        ("tiny", np.array([1.0])),
        ("big", np.arange(20.0)),
    ])
    assert len(results) == 1
    result = results[0]
    assert result.n_a == 1
    assert np.isnan(result.mannwhitney_p)
    assert np.isnan(result.ks_p)
    assert np.isnan(result.cliffs_delta)
    assert result.magnitude == ""
    assert np.isnan(result.min_attainable_p)


@pytest.mark.parametrize("n_a, n_b", [(3, 3), (3, 4), (4, 4), (3, 5)])
def test_min_attainable_p_matches_the_exact_rank_count(n_a, n_b):
    """
    At small sizes the floor is two arrangements out of all of them.
    小さい標本数では、下限は全並びのうちの 2 通りである。

    The exact two-sided Mann-Whitney test puts each completely separated
    arrangement in its own tail, so its smallest p-value is 2 / C(n_a + n_b,
    n_a), computed here without scipy.
    厳密な両側 Mann-Whitney 検定では、完全に分離した並びがそれぞれの裾に
    1 通りずつあるため、最小の p 値は 2 / C(n_a + n_b, n_a) となる。ここでは
    scipy を使わずに計算する。
    """
    from math import comb

    results = compare_groups([
        ("A", np.arange(float(n_a))),
        ("B", np.arange(float(n_a), float(n_a + n_b))),
    ])
    assert results[0].min_attainable_p == pytest.approx(2.0 / comb(n_a + n_b, n_a))


def test_min_attainable_p_bounds_every_untied_sample():
    """
    No untied pair of these sizes gets below the reported floor.
    この標本数の同値を含まないペアは、報告された下限を下回らない。
    """
    rng = np.random.default_rng(3)
    for _ in range(200):
        values = rng.permutation(7)
        result = compare_groups([("A", values[:3] * 1.0),
                                 ("B", values[3:] * 1.0)])[0]
        floor = result.min_attainable_p
        assert result.mannwhitney_p >= floor - 1e-12
        assert result.ks_p >= floor - 1e-12


def test_delta_magnitude_labels():
    """Magnitude labels follow the documented thresholds and sign-independence."""
    assert delta_magnitude(0.10) == "negligible"
    assert delta_magnitude(-0.10) == "negligible"
    assert delta_magnitude(0.20) == "small"
    assert delta_magnitude(0.40) == "medium"
    assert delta_magnitude(-0.90) == MAGNITUDE_LARGE
    assert delta_magnitude(float("nan")) == ""
