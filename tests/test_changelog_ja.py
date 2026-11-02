# -*- coding: utf-8 -*-
"""
Keep `CHANGELOG.ja.md` a translation of `CHANGELOG.md`.
`CHANGELOG.ja.md` が `CHANGELOG.md` の訳であり続けることのテスト。

`scripts/check_changelog_ja.py` is the check; this file carries it into CI, where
the pre-commit hook cannot be skipped, and pins what it detects. The rule lives
in `AGENTS.md` section 8.11.
検査本体は `scripts/check_changelog_ja.py` で、このファイルはそれを省略できない CI へ
持ち込み、何を検出するかを固定する。規則は `AGENTS.md` 8.11 節にある。

After translating an English change, read the pair and record it:
英語の変更を訳したら、読み合わせて記録する:

    .venv\\Scripts\\python.exe scripts\\check_changelog_ja.py --update
"""

import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_changelog_ja as cj  # noqa: E402
import release as rel  # noqa: E402

EN = """# Changelog

Intro paragraph.

## [Unreleased]

### Fixed

- First entry with `code`, 12 px and **bold
  text**.
- Second entry "連結を解除".

  Its second paragraph:
  - a nested item.

## [1.0.0] - 2026-01-01

Initial release.

### Added

- Third entry.

[Unreleased]: https://example.org/repo/compare/v1.0.0...HEAD
[1.0.0]: https://example.org/repo/releases/tag/v1.0.0
"""

JA = """# 変更履歴

導入の段落。

## [Unreleased]

### 修正

- `code` と 12 px と **太字
  の文** を持つ最初の項目。
- 「連結を解除」を持つ 2 番目の項目。

  その 2 段落目:
  - 入れ子の項目。

## [1.0.0] - 2026-01-01

最初のリリース。

### 追加

- 3 番目の項目。

[Unreleased]: https://example.org/repo/compare/v1.0.0...HEAD
[1.0.0]: https://example.org/repo/releases/tag/v1.0.0
"""


def _recorded(en=EN, ja=JA):
    """The pairs of a state that was read and recorded."""
    return {e.fingerprint: j.fingerprint for e, j in zip(cj.parse(en)[1], cj.parse(ja)[1])}


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def test_the_real_pair_follows_the_english():
    """A change to `CHANGELOG.md` fails here until the translation follows it."""
    problems = cj.find_problems(cj.read_worktree(cj.CHANGELOG_EN),
                                cj.read_worktree(cj.CHANGELOG_JA),
                                cj.load_manifest(cj.read_worktree))
    assert not problems, "\n".join(problems)


def test_entries_are_items_and_paragraphs():
    headings, entries, links = cj.parse(EN)
    assert headings == ["# Changelog", "## [Unreleased]", "### Fixed",
                        "## [1.0.0] - 2026-01-01", "### Added"]
    assert [e.normalized.split(" ")[0] for e in entries] == [
        "Intro", "-", "-", "Initial", "-"]
    assert "a nested item" in entries[2].text, "indented text belongs to its item"
    assert entries[1].section == "[Unreleased] / Fixed"
    assert len(links) == 2


def test_a_recorded_state_is_clean():
    assert cj.find_problems(EN, JA, _recorded()) == []


def test_rewrapping_does_not_count_as_a_change():
    rewrapped = EN.replace("**bold\n  text**", "**bold text**")
    assert cj.find_problems(rewrapped, JA, _recorded()) == []


def test_an_entry_added_to_one_file_is_found():
    added = EN.replace("- Third entry.", "- Third entry.\n- Fourth entry.")
    problems = cj.find_problems(added, JA, _recorded())
    assert len(problems) == 1 and "2 entries in English and 1 in Japanese" in problems[0]


def test_an_english_edit_without_a_translation_is_found_and_not_recorded():
    edited = EN.replace("Third entry.", "Third entry, reworded.")
    recorded = _recorded()
    problems = cj.find_problems(edited, JA, recorded)
    assert len(problems) == 1 and "translation did not" in problems[0]
    text, refused = cj.update(edited, JA, recorded)
    assert text is None and "translation did not" in refused[0]


def test_an_english_only_edit_is_recorded_when_said_so():
    edited = EN.replace("Third entry.", "Third entry, reworded.")
    text, problems = cj.update(edited, JA, _recorded(), english_only=True)
    assert problems == [] and text is not None


def test_an_edit_to_both_needs_recording_and_is_accepted():
    en = EN.replace("Third entry.", "Third entry, reworded.")
    ja = JA.replace("3 番目の項目。", "3 番目の項目（書き直し）。")
    recorded = _recorded()
    assert "not read against" in cj.find_problems(en, ja, recorded)[0]
    text, problems = cj.update(en, ja, recorded)
    assert problems == [] and text is not None
    assert cj.find_problems(en, ja, _recorded(en, ja)) == []


@pytest.mark.parametrize("old, new, expected", [
    ("12 px", "13 px", "number 12 missing"),
    ("`code`", "`other`", "inline code differs"),
    ("**太字\n  の文**", "太字の文", "bold markers differ"),
    ("「連結を解除」", "「解除」", "Japanese label"),
    ("\n\n  その 2 段落目:", "\n  その 2 段落目:", "paragraphs differ"),
    ("  - 入れ子の項目。", "  入れ子の項目。", "nested list items differ"),
])
def test_mechanical_differences_are_found(old, new, expected):
    assert old in JA
    problems = cj.find_problems(EN, JA.replace(old, new), _recorded())
    assert any(expected in p for p in problems), problems


def test_a_heading_outside_the_table_is_reported():
    problems = cj.structure_problems(EN.replace("### Added", "### Notes"), JA)
    assert any("no translation in SECTION_JA" in p for p in problems)


def test_a_wrong_heading_translation_is_reported():
    problems = cj.structure_problems(EN, JA.replace("### 追加", "### 新機能"))
    assert any("headings differ" in p for p in problems)


def test_link_definitions_must_be_identical():
    problems = cj.structure_problems(EN, JA.replace("compare/v1.0.0", "compare/v0.9.0"))
    assert any("link definitions" in p for p in problems)


def test_a_release_keeps_the_pair_recorded():
    """`release.py prepare` runs the tests, so rolling both must leave them clean."""
    en = rel.roll_changelog(EN, "1.1.0", "2026-02-02", "1.0.0")
    ja = rel.roll_changelog(JA, "1.1.0", "2026-02-02", "1.0.0", cj.CHANGELOG_JA)
    assert cj.structure_problems(en, ja) == []
    recorded = _recorded()
    for entry_en, entry_ja in zip(cj.parse(en)[1], cj.parse(ja)[1]):
        assert recorded[entry_en.fingerprint] == entry_ja.fingerprint


def test_a_commit_before_the_translation_exists_is_not_blocked(monkeypatch):
    monkeypatch.setattr(cj, "read_staged", lambda rel_path: None)
    monkeypatch.setattr(cj, "_in_head", lambda rel_path: False)
    assert cj.main(["--staged"]) == 0


def test_removing_a_committed_translation_is_blocked(monkeypatch):
    monkeypatch.setattr(cj, "read_staged",
                        lambda rel_path: EN if rel_path == cj.CHANGELOG_EN else None)
    monkeypatch.setattr(cj, "_in_head", lambda rel_path: True)
    assert cj.main(["--staged"]) == 1
