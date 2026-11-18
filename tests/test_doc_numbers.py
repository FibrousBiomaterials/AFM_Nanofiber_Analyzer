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

import copy
import importlib.util
import json
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
    # Only the first pair is under test; the other documents are present and empty.
    files = {doc: "" for doc in checker.DOCS}
    files.update({checker.DOCS[0]: en, checker.DOCS[1]: ja})
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
    # Only the first pair is under test; the other documents are present and empty.
    others = {doc: "" for doc in checker.DOCS[2:]}
    files = {checker.DOCS[0]: ok, checker.DOCS[1]: ok, **others}

    def read(rel):
        if rel in files:
            return files[rel]
        if rel in (checker.PENDING, checker.MEASUREMENTS):
            return None
        return checker.doc_excerpts.read_worktree(rel)

    assert checker.check(read) == []
    wrong = "4<!--c:lib/pipeline.py::ProcParams.mask_dilation-->\n"
    files = {checker.DOCS[0]: wrong, checker.DOCS[1]: wrong, **others}
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


def _measure_docs():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "measure_docs", PROJECT_ROOT / "scripts" / "measure_docs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_golden_digest_ignores_layout_and_follows_the_values(checker):
    """
    One golden gives one digest however it is laid out; another value moves it.
    同じゴールデンは体裁によらず同じダイジェストになり、値が違えば変わる。
    """
    def digest(*texts):
        return checker.golden_digest(_reader(dict(zip(checker.GOLDENS, texts))))

    assert digest('{"a": 1, "b": [2.5, 3]}', "{}") \
        == digest('{\r\n  "b": [2.5, 3],\r\n  "a": 1\r\n}\r\n', "{}")
    assert digest('{"a": 1}', "{}") != digest('{"a": 2}', "{}")
    assert digest('{"a": 1}', "{}") != digest('{"a": 1}', '{"c": 0}')
    # A golden that is absent is not the same as an empty one.
    assert digest("{}", "{}") != checker.golden_digest(_reader({checker.GOLDENS[0]: "{}"}))


def test_a_recording_is_stale_only_when_code_and_goldens_both_moved(checker):
    """
    Changed code alone, or moved goldens alone, leaves a recording valid.
    コードだけが変わっても、ゴールデンだけが動いても、記録は有効なままである。

    A change that reaches the same result another way changes the code and
    not the goldens, and measuring again would cost every experiment's run
    time. A recording with no golden digest is judged by its code alone.
    同じ結果に別の方法で到達する変更は、コードを変えるがゴールデンは変えない。
    測り直せば全実験の実行時間がかかる。ゴールデンのダイジェストを持たない記録は、
    コードだけで判定する。
    """
    rel = "lib/fiber.py"
    current = checker.doc_excerpts.code_symbol_digests(
        checker.doc_excerpts.read_worktree(rel))
    symbol = sorted(current)[0]
    other_code = copy.deepcopy(current)
    other_code[symbol] = "another digest"
    goldens = dict(zip(checker.GOLDENS, ('{"a": 1}', '{"b": 2}')))

    def read(path):
        return goldens[path] if path in goldens else checker.doc_excerpts.read_worktree(path)

    recorded_goldens = checker.golden_digest(read)

    def stale(code, golden_field):
        entry = {"snapshot": "s", "values": {}, **golden_field}
        measurements = {"snapshots": {"s": {rel: code}}, "experiments": {"e": entry}}
        return checker.stale_experiments(measurements, {"e"}, read)

    assert stale(other_code, {"goldens": recorded_goldens}) == {}
    assert stale(current, {"goldens": "the goldens of another day"}) == {}
    assert stale(other_code, {"goldens": "the goldens of another day"}) \
        == {"e": [f"{rel}: changed {symbol}"]}
    assert stale(other_code, {}) == {"e": [f"{rel}: changed {symbol}"]}
    assert stale(current, {}) == {}


def test_a_measurement_records_the_goldens_it_was_made_beside(tmp_path, monkeypatch, checker):
    """
    ``record`` writes the digest of the goldens beside an experiment's values.
    ``record`` は、実験の値とともにゴールデンのダイジェストを書く。
    """
    measure_docs = _measure_docs()
    path = tmp_path / "doc_measurements.json"
    monkeypatch.setattr(measure_docs, "MEASUREMENTS", path)
    monkeypatch.setitem(measure_docs.EXPERIMENTS, "quick",
                        dict(func=lambda: {"a": 1}, roots=[], description="d"))
    measure_docs.record(["quick"])
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["experiments"]["quick"]
    assert entry["values"] == {"a": 1}
    assert entry["goldens"] == checker.golden_digest(checker.doc_excerpts.read_worktree)
    assert data["_comment"] == measure_docs.RECORD_COMMENT
