# -*- coding: utf-8 -*-
"""
Tests for lib/stripe_noise.py.
lib/stripe_noise.py のテスト。

Unit tests use handmade images so the injected glitch is known exactly and the
flagged lines can be compared against it. Two integration tests run the metric
over bundled real scans: one that must screen as clean, and one carrying a
single feedback event that must be reported without condemning the rest of the
scan. Those are the two ways the screening becomes useless in practice —
crying wolf on good data, or answering with an unusable field either way.
単体テストは手作り画像を使い、注入したグリッチが厳密に既知であることを利用して
検出された走査線と突き合わせる。統合テストは同梱の実測走査 2 枚に対して指標を
実行する。清浄と判定されるべきものと、フィードバック擾乱が 1 箇所ありながら
走査の残りを巻き添えにしてはならないものである。この 2 つが、検査機能が実用に
耐えなくなる 2 通りの壊れ方にあたる。良好なデータで狼少年になるか、どちらに
転んでも使えない視野しか返さないか、である。
"""

import numpy as np
import pytest

from lib.afm_io import load_afm_image
from lib.stripe_noise import (
    DEFAULT_GUARD_LINES,
    DEFAULT_STEP_THRESHOLD_NM,
    evaluate_scan_lines,
    propose_clean_ranges,
)
from tests.conftest import HIGHER_PLANT_DATA, REAL_DATA


def _flat_scan(n_lines=100, n_cols=64, noise=0.2, seed=0):
    """
    Build a healthy scan: a flat substrate with small per-pixel noise.
    健全な走査を作る。平坦な基板に小さな画素ノイズを乗せたもの。
    """
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, noise, size=(n_lines, n_cols))


def test_clean_scan_flags_nothing():
    q = evaluate_scan_lines(_flat_scan())
    assert q.bad_lines.sum() == 0
    assert q.bad_fraction == 0.0
    assert q.flagged_steps == 0
    assert propose_clean_ranges(q) == [(0, 100)]


def test_displaced_lines_are_flagged_with_guard():
    img = _flat_scan()
    # Displace lines 50-54 by 40 nm: this is what a lost feedback loop does.
    # 走査線 50〜54 を 40 nm 変位させる。フィードバック喪失時に起きる現象。
    img[50:55] += 40.0
    q = evaluate_scan_lines(img)

    # Both boundaries of the displaced block exceed the threshold.
    assert q.flagged_steps == 2
    assert q.worst_step_nm == pytest.approx(40.0, abs=1.0)
    # The displaced lines themselves are always flagged.
    assert q.bad_lines[50:55].all()
    # The guard reaches DEFAULT_GUARD_LINES beyond each boundary line.
    assert q.bad_lines[50 - DEFAULT_GUARD_LINES]
    assert q.bad_lines[54 + DEFAULT_GUARD_LINES]
    # Far from the glitch the scan is left alone.
    assert not q.bad_lines[:40].any()
    assert not q.bad_lines[70:].any()


def test_clean_ranges_split_around_a_glitch():
    img = _flat_scan()
    img[50:55] += 40.0
    q = evaluate_scan_lines(img)
    ranges = propose_clean_ranges(q)

    assert len(ranges) == 2
    (a0, a1), (b0, b1) = ranges
    # Returned in image order, half-open, and covering only good lines.
    assert a0 == 0 and b1 == 100
    assert a1 < b0
    assert not q.bad_lines[a0:a1].any()
    assert not q.bad_lines[b0:b1].any()


def test_min_lines_drops_short_runs():
    img = _flat_scan()
    # Two glitches close together leave a short island of good lines between.
    # 近接した 2 つのグリッチの間に、短い良好区間の島が残る。
    img[40:45] += 40.0
    img[70:75] += 40.0
    q = evaluate_scan_lines(img)

    all_ranges = propose_clean_ranges(q)
    long_only = propose_clean_ranges(q, min_lines=25)
    assert len(all_ranges) == 3
    assert len(long_only) < len(all_ranges)
    assert all(b - a >= 25 for (a, b) in long_only)


def test_material_density_does_not_look_like_a_glitch():
    """
    A line crossing many fibers must not be flagged; the median ignores them.
    多数の繊維を横切る走査線を誤検出しないこと。中央値はそれらを無視する。
    """
    img = _flat_scan(noise=0.05)
    # 30% of the pixels on these lines sit 10 nm high, as a dense fiber mat
    # would leave them. Their mean rises by ~3 nm, above the 3 nm threshold,
    # but their median does not move.
    # これらの走査線の 30% の画素を 10 nm 高くする。密な繊維マットが残す状態に
    # 相当し、平均は約 3 nm 上がってしきい値 3 nm を超えるが、中央値は動かない。
    img[60:65, :19] += 10.0
    q = evaluate_scan_lines(img)
    assert q.bad_lines.sum() == 0


def test_threshold_and_guard_are_honoured():
    img = _flat_scan()
    img[50:55] += 5.0

    # Below the threshold the same displacement is ignored.
    assert evaluate_scan_lines(img, threshold_nm=8.0).bad_lines.sum() == 0
    # Above it, a zero guard marks only the boundary lines themselves.
    tight = evaluate_scan_lines(img, threshold_nm=1.0, guard_lines=0)
    assert tight.bad_lines[49] and tight.bad_lines[50]
    assert not tight.bad_lines[45]

    q = evaluate_scan_lines(img, threshold_nm=1.0)
    assert q.threshold_nm == 1.0
    assert q.guard_lines == DEFAULT_GUARD_LINES


def test_single_line_and_shape_guard():
    q = evaluate_scan_lines(np.zeros((1, 16)))
    assert q.step_nm.size == 0
    assert q.bad_lines.tolist() == [False]
    assert q.bad_fraction == 0.0
    assert q.worst_step_nm == 0.0

    with pytest.raises(ValueError):
        evaluate_scan_lines(np.zeros((4, 4, 4)))


def test_scattered_invalid_pixels_do_not_remove_lines():
    """
    A few invalid pixels must not silently drop scan lines from the analysis.
    少数の無効画素が走査線を黙って解析対象から外さないこと。
    """
    img = _flat_scan()
    img[30, ::7] = np.nan
    q = evaluate_scan_lines(img)
    assert q.bad_lines.sum() == 0


def test_fully_invalid_line_is_flagged_without_faking_a_step():
    """
    A line with no valid pixel is unanalyzable, but must not fake a step.
    有効画素の無い走査線は解析不能だが、偽の段差を作ってはならない。
    """
    img = _flat_scan() + 25.0
    img[30, :] = np.nan
    q = evaluate_scan_lines(img)

    assert q.bad_lines[30]
    # Its neighbors are intact: the gap did not read as two 25 nm steps.
    assert q.flagged_steps == 0
    assert not q.bad_lines[:30].any()
    assert not q.bad_lines[31:].any()


@pytest.mark.slow
def test_healthy_real_scan_is_not_flagged():
    """
    The bundled tunicate scan is a good measurement and must screen as clean.
    同梱のホヤ走査は良好な測定であり、清浄と判定されなければならない。
    """
    img = load_afm_image(str(REAL_DATA))
    q = evaluate_scan_lines(img)
    assert q.flagged_steps == 0
    assert q.bad_fraction == 0.0
    # The whole scan stays available as one analyzable block.
    assert propose_clean_ranges(q, min_lines=32) == [(0, img.shape[0])]


@pytest.mark.slow
def test_isolated_glitch_leaves_most_of_the_scan_usable():
    """
    One glitch must be reported without condemning the rest of the scan.
    グリッチ 1 箇所を報告しつつ、走査の残りまで巻き添えにしないこと。

    The bundled 2 um scan carries a single feedback event. The screening is
    only useful if it distinguishes that from a scan whose glitches make the
    field unusable, so this pins the shape of the answer, not just a flag.
    同梱の 2 um 走査にはフィードバック擾乱が 1 箇所ある。視野が使い物にならない
    ほどグリッチだらけの走査と区別できて初めて検査の意味があるため、真偽値では
    なく回答の形を固定する。
    """
    img = load_afm_image(str(HIGHER_PLANT_DATA))
    q = evaluate_scan_lines(img)

    assert q.worst_step_nm > DEFAULT_STEP_THRESHOLD_NM
    # Localized: a small minority of lines, not a third of the scan.
    assert 0.0 < q.bad_fraction < 0.05
    # What survives is one large block, not a set of thin strips.
    ranges = propose_clean_ranges(q, min_lines=32)
    longest = max(stop - start for start, stop in ranges)
    assert longest > 0.75 * img.shape[0]
