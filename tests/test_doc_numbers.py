# -*- coding: utf-8 -*-
"""
Every number in the algorithm documents cites a source that still holds.
アルゴリズム解説文書のすべての数値が、今も成り立つ出典を示している。

The rules are those of `scripts/check_doc_numbers.py`; this test runs them in
CI, where the pre-commit hook cannot be skipped around.
規則は `scripts/check_doc_numbers.py` のものであり、本テストは pre-commit フックを
迂回できない CI でそれを実行する。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _checker():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "check_doc_numbers", PROJECT_ROOT / "scripts" / "check_doc_numbers.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _checker()


def test_every_number_in_the_algorithm_documents_has_a_valid_source(checker):
    """
    No number lacks a marker, and every marker matches what it cites.
    印の無い数値が無く、すべての印が引用先と一致する。
    """
    problems = checker.check(checker.doc_excerpts.read_worktree)
    assert not problems, "\n".join(problems[:40])


def _reader(files):
    return lambda rel: files.get(rel)


def _with(checker, en: str, ja: str, measurements: str = "", pending: str = ""):
    files = {checker.DOCS[0]: en, checker.DOCS[1]: ja}
    if measurements:
        files[checker.MEASUREMENTS] = measurements
    if pending:
        files[checker.PENDING] = pending
    return checker.check(_reader(files))


def test_an_unmarked_number_is_refused(checker):
    """A new number with no marker fails, in either language."""
    problems = _with(checker, "The rule found 60 kinks.\n", "60 件見つけた。\n")
    assert sum("has no source marker" in p for p in problems) == 2


def test_a_measured_number_must_equal_its_recording(checker):
    """``m:`` compares at the written precision and catches a wrong value."""
    data = ('{"snapshots": {}, "experiments": {"e": {"snapshot": "x", '
            '"values": {"a": 0.1149, "r": [56, 62]}}}}')
    good = "0.11<!--m:e.a--> and 56–62<!--m:e.r-->\n"
    assert _with(checker, good, good, data) == []
    bad = "0.12<!--m:e.a--> and 56–61<!--m:e.r-->\n"
    problems = _with(checker, bad, bad, data)
    assert sum("does not match" in p for p in problems) == 4


def test_a_code_constant_is_read_from_the_code(checker):
    """``c:`` resolves a dataclass field default and a transform of it."""
    ok = ("3<!--c:lib/pipeline.py::ProcParams.mask_dilation--> "
          "30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->\n")
    files = {checker.DOCS[0]: ok, checker.DOCS[1]: ok}

    def read(rel):
        if rel in files:
            return files[rel]
        if rel in (checker.PENDING, checker.MEASUREMENTS):
            return None
        return checker.doc_excerpts.read_worktree(rel)

    assert checker.check(read) == []
    wrong = "4<!--c:lib/pipeline.py::ProcParams.mask_dilation-->\n"
    files = {checker.DOCS[0]: wrong, checker.DOCS[1]: wrong}
    assert sum("does not match" in p for p in checker.check(read)) == 2


def test_the_two_languages_cite_the_same_sources(checker):
    """A source cited in one language only is reported."""
    problems = _with(checker, "4<!--x:2 + 2-->\n", "4<!--x:1 + 3-->\n")
    assert any("cite different sources" in p for p in problems)


def test_exempt_positions_are_not_numbers(checker):
    """Code, math, headings, section references and versions are not checked."""
    text = ("# Heading 4\n"
            "1. Item `x = 5` in §4.2 of 1.0.0, see $W/4$ and [a](b3.md).\n"
            "```\n7\n```\n$$\n8\n$$\n"
            "A note <!-- TODO(review): 9 on one line --> and\n"
            "<!-- TODO(review): a note over\ntwo lines with 10 -->\n")
    assert _with(checker, text, text) == []
