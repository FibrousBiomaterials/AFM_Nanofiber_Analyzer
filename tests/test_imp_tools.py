# -*- coding: utf-8 -*-
"""
Tests for lib/imp_tools.py skeleton morphology helpers.
lib/imp_tools.py の骨格モルフォロジー補助関数のテスト。

The cases here pin down behavior at the image border, which is where the
neighborhood arithmetic stops being symmetric. `remove_bp` cuts the skeleton
at every branch point so `tracking` sees paths with exactly two endpoints; a
junction it fails to cut costs the whole connected component, because
`FiberTrackingImage` skips a component `tracking` rejects rather than
measuring part of it.
ここでの検証対象は画像の境界における挙動であり、近傍の添字計算が対称でなくなる
のはこの場所である。`remove_bp` は全ての分岐点で骨格を切断し、`tracking` が端点
ちょうど 2 つの経路を見られるようにする。切断し損ねた分岐は連結成分を丸ごと
失わせる。`FiberTrackingImage` は `tracking` が拒否した成分を、一部だけ計測する
のではなくスキップするためである。
"""

import numpy as np
import pytest

from lib import imp_tools


def _t_junction(row: int, col: int, size: int = 12) -> np.ndarray:
    """
    Return a skeleton with one T junction at ``(row, col)``.
    ``(row, col)`` に T 字分岐を 1 つ持つ骨格を返す。
    """
    skel = np.zeros((size, size), dtype=np.uint8)
    skel[row, 1:size - 2] = 1
    skel[row + 1:row + 9, col] = 1
    return skel


@pytest.mark.parametrize("row, col", [(0, 5), (3, 5)])
def test_remove_bp_cuts_a_junction_on_the_first_scan_line(row, col):
    """A branch point is removed on the first row exactly as it is inside."""
    skel = _t_junction(row, col)
    branch = imp_tools.branchedPoints(skel)
    assert branch[row, col] == 1

    cleaned = imp_tools.remove_bp(skel, min_area=0)
    assert cleaned[row, col] == 0
    # The junction is cut, so the three arms become separate components.
    # 分岐が切断され、3 本の腕がそれぞれ独立した連結成分になる。
    assert not imp_tools.branchedPoints(cleaned).any()


def test_remove_bp_clamps_the_border_window_instead_of_wrapping():
    """At the border the window is trimmed, not moved to the opposite edge."""
    skel = _t_junction(0, 5)
    cleaned = imp_tools.remove_bp(skel, min_area=0)

    # The whole in-image part of the 3x3 neighborhood is cleared.
    # 3x3 近傍のうち画像内に収まる部分がすべて消えている。
    assert not cleaned[0:2, 4:7].any()
    # The opposite edge is untouched: a negative slice start would have
    # reached the last rows and columns instead of the intended neighborhood.
    # 反対側の端は手つかずである。スライス開始が負のままだと、意図した近傍では
    # なく末尾の行・列へ届いてしまう。
    assert np.array_equal(cleaned[-2:, :], skel[-2:, :])
    assert np.array_equal(cleaned[:, -2:], skel[:, -2:])
