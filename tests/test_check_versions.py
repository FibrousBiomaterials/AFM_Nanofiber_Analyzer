# -*- coding: utf-8 -*-
"""
Tests for the version-bookkeeping rules of `scripts/check_versions.py`.
`scripts/check_versions.py` のバージョン記録規則のテスト。

The rules are pure functions of the files before and after a change, so they
are tested on hand-made texts rather than on a git history.
規則は変更前後のファイルだけの純粋関数なので、git 履歴ではなく手作りの
テキストで検査する。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))
import check_versions as cv  # noqa: E402


def _files(version="2.1.0.dev0", fmt="1.2", supported=("1.0", "1.1", "1.2"),
           unreleased="- Bundle format **1.2** records the line.",
           readme='| `version` | Bundle format version (currently `"1.2"`). |',
           fields=("bg_method", "kinkangle_deg", "centerline_method"),
           init_version=None):
    """Build the watched files of one repository state."""
    body = "\n".join(f"    {name}: str = 'x'" for name in fields)
    return {
        cv.PYPROJECT: f'[project]\nname = "x"\nversion = "{version}"\n',
        cv.INIT: f'__version__ = "{init_version or version}"\n',
        cv.SCHEMA: (f'BUNDLE_FORMAT_VERSION = "{fmt}"\n'
                    f"SUPPORTED_BUNDLE_VERSIONS = {tuple(supported)!r}\n"),
        cv.PIPELINE: f"class ProcParams:\n{body}\n",
        cv.CHANGELOG: (f"# Changelog\n\n## [Unreleased]\n\n{unreleased}\n\n"
                       "## [2.0.1] - 2026-09-17\n\n- Bundle format 1.1 fix.\n"),
        "README.md": readme,
        "README.ja.md": readme,
    }


BEFORE = _files(version="2.0.1", fmt="1.1", supported=("1.0", "1.1"),
                unreleased="", readme='`"1.1"`',
                fields=("bg_method", "kinkangle_deg"))


def test_a_complete_format_bump_passes():
    """Format, supported list, changelog, READMEs and a MINOR dev version: clean."""
    assert cv.find_problems(BEFORE, _files(), "2.0.1") == []


def test_code_left_under_the_released_number_is_refused():
    """The state found on 2026-09-24: new code still called 2.0.1."""
    after = _files(version="2.0.1")
    problems = cv.find_problems(BEFORE, after, "2.0.1")
    assert any("not later than the last release" in p for p in problems)


def test_the_two_version_files_must_agree():
    after = _files(version="2.1.0.dev0", init_version="2.1.0")
    assert any("must be the same version" in p for p in cv.find_problems(BEFORE, after, "2.0.1"))


@pytest.mark.parametrize("version", ["2.0.2.dev0", "2.0.2"])
def test_a_format_bump_needs_a_minor_step(version):
    """A PATCH step is not enough: the last release cannot read the bundles."""
    problems = cv.find_problems(BEFORE, _files(version=version), "2.0.1")
    assert any("at least MINOR" in p for p in problems)


@pytest.mark.parametrize("kwargs, needle", [
    ({"supported": ("1.0", "1.1")}, "SUPPORTED_BUNDLE_VERSIONS"),
    ({"unreleased": "- Something else."}, "[Unreleased]"),
    ({"readme": '`"1.1"`'}, "README.md"),
])
def test_a_format_bump_without_its_bookkeeping_is_refused(kwargs, needle):
    problems = cv.find_problems(BEFORE, _files(**kwargs), "2.0.1")
    assert any(needle in p for p in problems)


def test_the_format_named_only_in_an_old_release_section_does_not_count():
    """1.2 must be in [Unreleased], not merely somewhere in the changelog."""
    after = _files(unreleased="- Nothing about the format.")
    after[cv.CHANGELOG] += "\n## [1.9.0]\n\n- format 1.2\n"
    assert any("[Unreleased]" in p for p in cv.find_problems(BEFORE, after, "2.0.1"))


def test_a_version_token_is_matched_whole():
    assert cv._mentions("format 1.2 now", "1.2")
    assert not cv._mentions("format 1.21", "1.2")
    assert not cv._mentions("v11.2", "1.2")


def test_removing_a_procparams_field_needs_a_major_step():
    after = _files(fields=("bg_method", "centerline_method"))
    problems = cv.find_problems(BEFORE, after, "2.0.1")
    assert any("kinkangle_deg" in p and "MAJOR" in p for p in problems)
    after = _files(version="3.0.0.dev0", fields=("bg_method", "centerline_method"))
    assert not any("ProcParams" in p for p in cv.find_problems(BEFORE, after, "2.0.1"))


def test_adding_a_procparams_field_is_fine():
    assert not any("ProcParams" in p for p in cv.find_problems(BEFORE, _files(), "2.0.1"))


def test_the_release_commit_itself_passes():
    """Setting X.Y.Z for the release is later than the previous tag."""
    before = _files(version="2.1.0.dev0")
    after = _files(version="2.1.0")
    assert cv.find_problems(before, after, "2.0.1") == []


def test_no_release_tag_skips_the_ordering_rules():
    assert cv.find_problems(BEFORE, _files(version="0.1.0.dev0"), None) == []


def test_version_ordering_follows_pep440_for_the_forms_used_here():
    assert cv.parse_version("2.1.0.dev0") < cv.parse_version("2.1.0")
    assert cv.parse_version("2.0.1") < cv.parse_version("2.1.0.dev0")
    assert cv.parse_version("2.1.0.dev1") > cv.parse_version("2.1.0.dev0")
    assert cv.parse_version("2.1") is None
