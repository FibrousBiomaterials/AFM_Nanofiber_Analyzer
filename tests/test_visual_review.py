"""
Tests that every change to the GUI01 analysis stages carries a visual review.
GUI01 の解析段階への変更に、目視の確認が付いていることを検査する。

The working tree's analysis code must be covered by ``tests/visual_review.json``
(AGENTS.md §8.18); the remaining tests pin the rule that decides coverage.
作業ツリーの解析コードは ``tests/visual_review.json`` に覆われていなければならない
（AGENTS.md §8.18）。残りのテストは、覆われているかを決める規則を固定する。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_visual_review as cvr  # noqa: E402


def _reader(files):
    """Return a reader of the given texts, falling back to the working tree."""
    return lambda path: files[path] if path in files else cvr.read_worktree(path)


def test_working_tree_is_covered():
    assert cvr.problems(cvr.read_worktree) == []


def test_a_comment_keeps_the_fingerprint():
    path = cvr.VISUAL_MODULES[0]
    edited = cvr.read_worktree(path) + "\n# A comment changes nothing computed.\n"
    assert cvr.fingerprint(_reader({path: edited})) == cvr.fingerprint(cvr.read_worktree)


def test_a_code_change_moves_the_fingerprint():
    path = cvr.VISUAL_MODULES[0]
    edited = cvr.read_worktree(path) + "\n\ndef _added_for_the_test():\n    return 1\n"
    assert cvr.fingerprint(_reader({path: edited})) != cvr.fingerprint(cvr.read_worktree)


def test_only_an_approval_with_a_name_covers():
    reviews = [
        {"fingerprint": "a", "status": "approved", "approved_by": ""},
        {"fingerprint": "b", "status": "pending"},
        {"fingerprint": "c", "status": "approved", "approved_by": "reviewer"},
        {"fingerprint": "d", "status": "identical"},
    ]
    assert cvr.covering(reviews, "a") is None
    assert cvr.covering(reviews, "b") is None
    assert cvr.covering(reviews, "c") is not None
    assert cvr.covering(reviews, "d") is not None


def test_an_unreviewed_change_is_reported():
    path = cvr.VISUAL_MODULES[0]
    edited = cvr.read_worktree(path) + "\n\ndef _added_for_the_test():\n    return 1\n"
    assert cvr.problems(_reader({path: edited}))
    assert cvr.problems(_reader({path: edited}), base=_reader({path: edited})) == []
