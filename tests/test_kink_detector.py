# -*- coding: utf-8 -*-
"""
Tests for the excess-turning kink rule of `lib.kink_detector` on analytic lines.
`lib.kink_detector` の超過回転キンク規則を、解析的な線の上で検証するテスト。

The rule is given lines whose geometry is known exactly -- straight arms,
corners of known turn, arcs of known radius -- so each test states the correct
answer rather than a recorded output. Placing the line on a rendered height
image before it is judged is covered by `test_centerline.py`.
規則には形が厳密にわかっている線（まっすぐな腕、回転角の既知なコーナー、半径の
既知な円弧）を与えるため、各テストは記録された出力ではなく正しい答えを述べる。
線を描画した高さ画像の上に置いてから判定する経路は `test_centerline.py` が扱う。
"""

import numpy as np
import pytest

from lib.kink_detector import KinkDetector

# Apparent width in pixels, as on the synthetic scans (2 nm pixels, 4 nm fiber,
# 15 nm probe), and the line's point spacing: one point per skeleton pixel.
# 見かけ幅（画素）。合成スキャン（画素 2 nm、繊維 4 nm、探針 15 nm）と同じ。
# 線の点間隔はスケルトン画素ごとに 1 点。
W = 8.0
STEP = 1.0


def _walk(parts, heading_deg=17.0, step=STEP):
    """
    Build a line from ``("L", length_px)``, ``("T", turn_deg)`` and ``("A", radius_px, turn_deg)`` parts.
    ``("L", 長さ)``・``("T", 回転角)``・``("A", 半径, 回転角)`` の部品から線を作る。

    Returns the points and, for each ``"T"``, the index of its vertex.
    点列と、``"T"`` ごとの頂点インデックスを返す。
    """
    pts = [np.zeros(2)]
    heading = np.radians(heading_deg)
    corners = []
    for part in parts:
        if part[0] == "L":
            n = max(1, int(round(part[1] / step)))
            d = np.array([np.cos(heading), np.sin(heading)]) * (part[1] / n)
            for _ in range(n):
                pts.append(pts[-1] + d)
        elif part[0] == "T":
            corners.append(len(pts) - 1)
            heading += np.radians(part[1])
        else:
            radius, turn = part[1], np.radians(part[2])
            n = max(1, int(round(radius * abs(turn) / step)))
            dt = turn / n
            ds = radius * abs(turn) / n
            for _ in range(n):
                heading += dt / 2
                pts.append(pts[-1] + ds * np.array([np.cos(heading), np.sin(heading)]))
                heading += dt / 2
    p = np.array(pts)
    return p[:, 0], p[:, 1], corners


def _judge(x, y, width=W, detector=None):
    return (detector or KinkDetector()).kinks_on_line(x, y, width)


def test_a_straight_line_has_no_bend():
    """A straight line reports neither a kink nor a bend left unjudged."""
    x, y, _ = _walk([("L", 120)])
    kinks, angles, unjudged = _judge(x, y)
    assert kinks.size == 0 and angles.size == 0 and unjudged.size == 0


def test_an_isolated_corner_is_one_kink_at_its_turn():
    """
    A 60 degree turn between long straight arms is one kink, at the vertex, of interior angle 120 degrees.
    長いまっすぐな腕の間の 60 度の回転は、頂点で内角 120 度のキンク 1 つである。
    """
    x, y, corners = _walk([("L", 60), ("T", 60), ("L", 60)])
    kinks, angles, unjudged = _judge(x, y)
    assert kinks.size == 1 and unjudged.size == 0
    assert np.hypot(x[kinks[0]] - x[corners[0]], y[kinks[0]] - y[corners[0]]) < 0.5 * W
    assert np.degrees(angles[0]) == pytest.approx(120.0, abs=3.0)


def test_a_turn_below_the_threshold_is_not_a_kink():
    """A 20 degree turn is below the default 30 degrees and is not reported."""
    x, y, _ = _walk([("L", 60), ("T", 20), ("L", 60)])
    kinks, _, unjudged = _judge(x, y)
    assert kinks.size == 0 and unjudged.size == 0


@pytest.mark.parametrize("radius_widths", [3.0, 5.0, 10.0])
def test_a_smooth_arc_is_not_a_kink(radius_widths):
    """
    A 120 degree arc of radius 3 W or more between straight arms has no kink.
    まっすぐな腕の間にある、半径 3 W 以上で 120 度の円弧にはキンクが無い。

    The total turn is four times the threshold, so a rule that summed turning
    without comparing it with the curvature beside it would report the arc.
    全回転はしきい値の 4 倍あるため、回転を脇の曲率と比べずに合計する規則なら
    この円弧を報告してしまう。
    """
    x, y, _ = _walk([("L", 40), ("A", radius_widths * W, 120), ("L", 40)])
    kinks, _, _ = _judge(x, y)
    assert kinks.size == 0


@pytest.mark.parametrize("spacing_widths", [1.5, 2.0, 3.0])
@pytest.mark.parametrize("second_turn", [60, -60], ids=["same-sense", "jog"])
def test_two_close_corners_are_two_kinks(spacing_widths, second_turn):
    """
    Two 60 degree corners 1.5-3 W apart are two kinks, in the same sense or as a jog.
    1.5〜3 W 離れた 60 度のコーナー 2 つは、同じ向きでも段差でもキンク 2 つである。

    The approved visual reference counts a jog -- two opposite bends about a
    width apart -- as two kinks, and a merged pair would hide a real defect.
    承認された目視基準は、段差（約 1 幅離れた逆向きの折れ 2 つ）をキンク 2 つと
    数える。1 つにまとめると本物の欠陥を隠すことになる。
    """
    x, y, corners = _walk([("L", 60), ("T", 60), ("L", spacing_widths * W),
                           ("T", second_turn), ("L", 60)])
    kinks, _, _ = _judge(x, y)
    assert kinks.size == 2
    for k, c in zip(kinks, corners):
        assert np.hypot(x[k] - x[c], y[k] - y[c]) < 0.5 * W


def test_a_bend_next_to_an_end_is_returned_as_not_judged():
    """
    A 60 degree corner 1 W from an end is not a kink but is returned as not judged.
    端から 1 W の 60 度のコーナーはキンクではなく、判定しなかった折れとして返る。

    It must not simply vanish: a viewer has to be able to tell "not judged"
    from "measured and below the threshold".
    単に消えてはならない。利用者が「判定しなかった」と「測ってしきい値未満だった」
    を見分けられなければならないためである。
    """
    x, y, corners = _walk([("L", 80), ("T", 60), ("L", 1.0 * W)])
    kinks, _, unjudged = _judge(x, y)
    assert kinks.size == 0
    assert unjudged.size == 1
    assert np.hypot(x[unjudged[0]] - x[corners[0]], y[unjudged[0]] - y[corners[0]]) < 0.5 * W


def test_a_bend_two_widths_from_an_end_is_judged():
    """The same corner 2 W from the end is judged and reported as a kink."""
    x, y, _ = _walk([("L", 80), ("T", 60), ("L", 2.0 * W)])
    kinks, _, unjudged = _judge(x, y)
    assert kinks.size == 1 and unjudged.size == 0


def test_the_threshold_follows_the_interior_angle_setting():
    """
    A 45 degree turn is a kink at the default 150 degrees and not at 130 degrees.
    45 度の回転は、既定の 150 度ではキンクで、130 度ではキンクではない。
    """
    x, y, _ = _walk([("L", 60), ("T", 45), ("L", 60)])
    kinks, angles, _ = _judge(x, y)
    assert kinks.size == 1
    assert np.degrees(angles[0]) == pytest.approx(135.0, abs=3.0)
    strict = KinkDetector(threshold_angle_from_decomposed_indices=np.radians(130.0))
    assert _judge(x, y, detector=strict)[0].size == 0


def test_the_rule_is_scaled_by_the_width():
    """
    Doubling the geometry and the width leaves the verdict and the angle unchanged.
    形と幅を 2 倍にしても、判定と角度は変わらない。

    Every length the rule uses is a multiple of the width, so a scan of the
    same fibers at another pixel size must give the same kinks.
    規則の長さはすべて幅の倍数であるため、同じ繊維を別の画素サイズで走査しても
    同じキンクが得られなければならない。
    """
    parts = [("L", 50), ("T", 50), ("L", 1.5 * W), ("T", -70), ("L", 50)]
    x1, y1, _ = _walk(parts)
    x2, y2, _ = _walk([(p[0], p[1] * 2.0) if p[0] == "L" else p for p in parts], step=2.0)
    k1, a1, _ = _judge(x1, y1, W)
    k2, a2, _ = _judge(x2 * 1.0, y2 * 1.0, 2.0 * W)
    assert k1.size == k2.size == 2
    np.testing.assert_allclose(np.degrees(a1), np.degrees(a2), atol=2.0)


def test_a_hairpin_is_one_kink_with_a_valid_interior_angle():
    """
    A U-turn narrower than the window is one kink whose angle stays inside (0, pi).
    窓より狭い U ターンはキンク 1 つで、その角度は (0, pi) の内側に収まる。

    The line turns by about 180 degrees within the window, so ``pi`` minus
    the excess would reach zero; the bundle contract requires a strictly
    positive interior angle.
    線は窓の中で約 180 度回るため、``pi`` から超過回転を引くと 0 に達する。
    バンドル契約は正の内角を要求する。
    """
    x, y, _ = _walk([("L", 60), ("T", 90), ("L", 4), ("T", 90), ("L", 60)])
    kinks, angles, _ = _judge(x, y)
    assert kinks.size == 1
    assert 0.0 < angles[0] < np.radians(30.0)


def test_degenerate_lines_give_nothing():
    """Lines too short for the window, or with repeated points only, report nothing."""
    for x, y in ((np.array([0.0, 1.0]), np.array([0.0, 0.0])),
                 (np.zeros(5), np.zeros(5)),
                 _walk([("L", 6)])[:2]):
        kinks, angles, unjudged = _judge(x, y)
        assert kinks.size == 0 and angles.size == 0 and unjudged.size == 0


def test_the_angle_is_read_from_the_arms_not_from_the_excess():
    """
    Sharp corners read their true interior angle from the arms beside them.
    鋭いコーナーは、その脇の腕から真の内角を読む。

    Pi minus the excess turning read low on sharp corners because the window
    spans the rounded apex; the arms beyond it do not.
    pi から超過回転を引いた値は、窓が丸められた頂点を跨ぐため鋭いコーナーで
    低く読んだ。その外側の腕は跨がない。
    """
    for turn in (40.0, 60.0, 90.0, 120.0):
        x, y, _ = _walk([("L", 60), ("T", turn), ("L", 60)])
        judged = KinkDetector().judge_line(x, y, W)
        assert judged.kink_indices.size == 1
        assert np.degrees(judged.kink_angles[0]) == pytest.approx(180.0 - turn, abs=1.5)
        # The excess is what the rule tested and is stored beside the angle.
        # 超過回転は規則が検定した量で、角度の隣に保存される。
        assert judged.kink_excess.shape == (1,)
        assert np.degrees(judged.kink_excess[0]) >= 30.0


def test_a_jog_reads_each_corner_from_its_own_arms():
    """
    The arm of one corner stops at the next bend, so a jog's two angles are
    each corner's own.
    腕は次の折れで止まるため、段差の 2 つの角度はそれぞれのコーナー自身のもの。
    """
    x, y, _ = _walk([("L", 60), ("T", 50), ("L", 1.5 * W), ("T", -70), ("L", 60)])
    judged = KinkDetector().judge_line(x, y, W)
    assert judged.kink_indices.size == 2
    np.testing.assert_allclose(np.degrees(judged.kink_angles), [130.0, 110.0], atol=4.0)


def test_the_noise_floor_is_the_lines_own_and_only_raises_the_bar():
    """
    With the noise test on, a clean corner is still a kink, the floor of a
    clean line is near zero, and a noisy line's floor is larger.
    ノイズ検定を有効にしても、きれいなコーナーはキンクのままで、きれいな線の床は
    ほぼ 0、ノイズの多い線の床はより大きい。
    """
    x, y, _ = _walk([("L", 120), ("T", 60), ("L", 120)])
    clean = KinkDetector(noise_sigmas=3.0).judge_line(x, y, W)
    assert clean.kink_indices.size == 1
    assert np.isfinite(clean.noise_excess) and np.degrees(clean.noise_excess) < 2.0

    rng = np.random.default_rng(3)
    xn = x + rng.normal(0.0, 0.6, x.size)
    yn = y + rng.normal(0.0, 0.6, y.size)
    noisy = KinkDetector(noise_sigmas=3.0).judge_line(xn, yn, W)
    assert np.isfinite(noisy.noise_excess) and noisy.noise_excess > clean.noise_excess
    # Turning the test off can only add kinks, never remove one.
    # 検定を無効にしてもキンクが増えることはあれ、減ることはない。
    off = KinkDetector(noise_sigmas=0.0).judge_line(xn, yn, W)
    assert set(noisy.kink_indices.tolist()) <= set(off.kink_indices.tolist())


def test_a_short_line_gets_no_noise_floor():
    """A line with too few windows is judged by the angle threshold alone."""
    x, y, _ = _walk([("L", 20), ("T", 60), ("L", 20)])
    judged = KinkDetector(noise_sigmas=3.0).judge_line(x, y, W)
    assert not np.isfinite(judged.noise_excess)
    assert judged.kink_indices.size == 1
