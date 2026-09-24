# -*- coding: utf-8 -*-
"""
Tests for the file edits of `scripts/release.py`.
`scripts/release.py` のファイル編集のテスト。

The edits are applied to the repository's real files in memory, so a change
in the shape of any of them (a reworded CITATION line, a second BibTeX entry)
fails here rather than in the middle of a release.
編集はリポジトリの実ファイルにメモリ上で適用する。どれかの形が変わった場合
（CITATION の行の書き換え、BibTeX 項目の追加など）は、リリースの途中ではなく
ここで失敗する。
"""

import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_versions as cv  # noqa: E402
import release as rel  # noqa: E402


def _real(paths):
    # Read raw bytes, as the script does, so a CRLF working copy is what is
    # tested; text mode would hide the line endings the patterns must handle.
    out = {}
    for path in paths:
        with open(os.path.join(ROOT, path), "rb") as f:
            out[path] = f.read().decode("utf-8")
    return out


CHANGELOG = """# Changelog

## [Unreleased]

### Added

- A new line.

## [2.0.1] - 2026-09-17

- Old.

[Unreleased]: https://example.org/repo/compare/v2.0.1...HEAD
[2.0.1]: https://example.org/repo/compare/v2.0.0...v2.0.1
"""


def test_a_release_rolls_the_changelog_and_its_links():
    out = rel.roll_changelog(CHANGELOG, "2.1.0", "2026-10-01", "2.0.1")
    assert "## [Unreleased]\n\n## [2.1.0] - 2026-10-01\n\n### Added\n\n- A new line." in out
    assert cv.unreleased_section(out).strip() == ""
    assert "[Unreleased]: https://example.org/repo/compare/v2.1.0...HEAD\n" \
           "[2.1.0]: https://example.org/repo/compare/v2.0.1...v2.1.0\n" \
           "[2.0.1]:" in out


def test_a_first_release_links_to_its_tag():
    out = rel.roll_changelog(CHANGELOG, "2.1.0", "2026-10-01", None)
    assert "[2.1.0]: https://example.org/repo/releases/tag/v2.1.0" in out


def test_an_empty_unreleased_section_is_refused():
    empty = CHANGELOG.replace("### Added\n\n- A new line.\n", "")
    with pytest.raises(rel.ReleaseError, match="empty"):
        rel.roll_changelog(empty, "2.1.0", "2026-10-01", "2.0.1")


def test_a_version_that_already_has_a_section_is_refused():
    with pytest.raises(rel.ReleaseError, match="already"):
        rel.roll_changelog(CHANGELOG, "2.0.1", "2026-10-01", "2.0.1")


def test_only_this_softwares_bibtex_entry_is_edited():
    readme = ("@article{other,\n  year = {2020},\n  version = {9}\n}\n\n"
              "@software{afm_nanofiber_analyzer,\n  year      = {2026},\n"
              "  version   = {2.0.1},\n}\n")
    out = rel.set_readme_bibtex(readme, "2.1.0", "2027")
    assert "year = {2020},\n  version = {9}" in out
    assert "year      = {2027}" in out and "version   = {2.1.0}" in out


def test_the_real_files_take_a_release():
    """Every file a release edits has exactly the shape the edits expect."""
    files = _real(rel.RELEASE_FILES)
    if not cv.unreleased_section(files[rel.CHANGELOG]).strip():
        files[rel.CHANGELOG] = files[rel.CHANGELOG].replace(
            "## [Unreleased]", "## [Unreleased]\n\n- test entry", 1)
    last = "2.0.1"
    out = rel.release_edits(files, "9.8.7", "2031-02-03", last)
    assert cv.pyproject_version(out[rel.PYPROJECT]) == "9.8.7"
    assert cv.module_constant(out[rel.INIT], "__version__") == "9.8.7"
    assert re.search(r'^version:\s*"9\.8\.7"', out[rel.CITATION], re.MULTILINE)
    assert re.search(r'^date-released:\s*"2031-02-03"', out[rel.CITATION], re.MULTILINE)
    for readme in rel.READMES:
        assert "version   = {9.8.7}" in out[readme]
        assert "year      = {2031}" in out[readme]
    assert "## [9.8.7] - 2031-02-03" in out[rel.CHANGELOG]
    # The result passes the version check as a release commit.
    after = {**_real(cv.WATCHED), **{k: v for k, v in out.items() if k in cv.WATCHED}}
    assert cv.find_problems(_real(cv.WATCHED), after, last) == []


def test_the_real_files_take_a_development_start():
    out = rel.dev_edits(_real(rel.DEV_FILES), "9.9.0.dev0")
    assert cv.pyproject_version(out[rel.PYPROJECT]) == "9.9.0.dev0"
    assert cv.module_constant(out[rel.INIT], "__version__") == "9.9.0.dev0"


# ----- Suggesting the next version -----

PIPE_OLD = "class ProcParams:\n    a: int = 1\n    b: int = 2\n"
SCHEMA_OLD = 'BUNDLE_FORMAT_VERSION = "1.1"\nSUPPORTED_BUNDLE_VERSIONS = ("1.0", "1.1")\n'
CLI_OLD = ('def build(sub):\n    p = sub.add_parser("process")\n'
           '    p.add_argument("inputs")\n    p.add_argument("--rows")\n')


def _state(pipe=PIPE_OLD, schema=SCHEMA_OLD, cli=CLI_OLD, lib="def f():\n    pass\n",
           py='requires-python = ">=3.11"\n', changelog="## [Unreleased]\n\n- fix\n"):
    return {cv.PIPELINE: pipe, cv.SCHEMA: schema, rel.CLI: cli, "lib/mod.py": lib,
            rel.PYPROJECT: py, rel.CHANGELOG: changelog}


def _level(after, added=(), goldens=False):
    return rel.suggest_level(_state(), after, list(added), goldens)


def test_a_fix_only_release_is_patch():
    level, reasons = _level(_state())
    assert level == rel.PATCH and reasons == []


def test_additions_are_minor():
    after = _state(pipe=PIPE_OLD + "    c: int = 3\n",
                   schema=SCHEMA_OLD.replace('"1.1"\n', '"1.2"\n').replace('"1.1")', '"1.1", "1.2")'),
                   cli=CLI_OLD + '    p.add_argument("--centerline")\n')
    level, reasons = _level(after, added=["guis/GUI05_New.py"])
    assert level == rel.MINOR
    text = " ".join(r for _, r in reasons)
    for needle in ("field(s) added: c", "1.1 -> 1.2", "process --centerline", "GUI05_New.py"):
        assert needle in text


def test_breaking_changes_are_major():
    for after, needle in [
        (_state(pipe="class ProcParams:\n    a: int = 1\n"), "removed or renamed: b"),
        (_state(schema='BUNDLE_FORMAT_VERSION = "1.1"\nSUPPORTED_BUNDLE_VERSIONS = ("1.1",)\n'),
         "no longer readable: 1.0"),
        (_state(lib="def g():\n    pass\n"), "removed from lib/mod.py: f"),
        (_state(cli=CLI_OLD.replace('    p.add_argument("--rows")\n', "")), "process --rows"),
        (_state(py='requires-python = ">=3.12"\n'), "3.11 -> 3.12"),
    ]:
        level, reasons = _level(after)
        assert level == rel.MAJOR, needle
        assert any(needle in r for _, r in reasons), needle


def test_notes_do_not_raise_the_level():
    level, reasons = _level(_state(changelog="## [Unreleased]\n\n### Removed\n\n- x\n"), goldens=True)
    assert level == rel.PATCH
    assert [lvl for lvl, _ in reasons] == ["NOTE", "NOTE"]


def test_private_names_and_positionals_are_not_api():
    assert rel.public_names("def _x():\n    pass\nY = 1\n_Z = 2\n") == {"Y"}
    assert rel.cli_options(CLI_OLD) == {"process", "process --rows"}


def test_next_version_steps():
    assert rel.next_version("2.0.1", rel.PATCH) == "2.0.2"
    assert rel.next_version("2.0.1", rel.MINOR) == "2.1.0"
    assert rel.next_version("2.0.1", rel.MAJOR) == "3.0.0"


# ----- Deprecated aliases and their removal -----

def test_a_marker_is_due_at_its_version_and_not_before():
    files = {"lib/m.py": 'A = {"OLD": ("NEW", "3.0.0")}  # remove-in: 3.0.0\n'}
    assert rel.due_removals(files, "2.1.0") == []
    assert rel.due_removals(files, "3.0.0") == ['lib/m.py:1: A = {"OLD": ("NEW", "3.0.0")}  # remove-in: 3.0.0']
    assert len(rel.due_removals(files, "3.1.0")) == 1


def test_an_alias_keeps_the_name_public():
    before = "X = 1\n"
    after = 'Y = 1\n_DEPRECATED_ALIASES = {"X": ("Y", "3.0.0")}\n'
    assert "X" in rel.public_names(after)
    assert rel.public_names(before) - rel.public_names(after) == set()


def test_the_repository_markers_are_not_due_before_3_0_0():
    """Only the 3.0.0 removal is pending; a 2.x release must not be blocked."""
    import subprocess
    root = os.path.abspath(ROOT)
    paths = subprocess.run(["git", "-C", root, "ls-files", "*.py"],
                           capture_output=True, text=True).stdout.split()
    files = {p: open(os.path.join(root, p), encoding="utf-8", errors="replace").read()
             for p in paths if os.path.exists(os.path.join(root, p))}
    assert rel.due_removals(files, "2.9.9") == []
    assert any("HALF_MAX_CENTERLINE" in d for d in rel.due_removals(files, "3.0.0"))
