# -*- coding: utf-8 -*-
"""
Every sentence of the JOSS manuscript records what supports it.
JOSS 原稿のすべての文が、それを裏付ける根拠を記録している。

The rules are those of `scripts/check_paper_claims.py`; this test runs them in
CI, where the pre-commit hook cannot be skipped around.
規則は `scripts/check_paper_claims.py` のものであり、本テストは pre-commit
フックを迂回できない CI でそれを実行する。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _checker():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "check_paper_claims", PROJECT_ROOT / "scripts" / "check_paper_claims.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _checker()


def test_every_sentence_of_the_paper_has_a_valid_record(checker):
    """
    Each sentence has one record, and every verified source still holds.
    各文に記録が 1 つあり、確認済みの根拠がすべて今も成り立つ。
    """
    problems = checker.check(checker.doc_excerpts.read_worktree)
    assert not problems, "\n".join(problems[:40])


PAPER = """---
title: x
---

# Summary

The tool reads files. It measures height (\\autoref{fig:a}).

- Item one, for code.

![A caption.\\label{fig:a}](figures/a.png)
"""


def _files(checker, claims, paper=PAPER, extra=None):
    for c in claims:
        c.setdefault("ja", "訳。")
    record = {"title_ja": "題", "headings_ja": {"Summary": "概要"}, "claims": claims}
    files = {
        checker.PAPER: paper,
        checker.BIB: "@article{Key2020,\n  title = {t}\n}\n",
        checker.CLAIMS: json.dumps(record),
        "lib/mod.py": "VALUE = 3\n\ndef func():\n    return VALUE\n",
        "docs/d.md": "The bundled scans are\nthree scans.\n",
    }
    try:
        files[checker.PAPER_JA] = checker.render_ja(paper, record)
    except KeyError:
        pass
    files.update(extra or {})
    return lambda rel: files.get(rel)


def _all_unverified(checker, paper=PAPER):
    return [{"sentence": s, "status": "unverified", "note": "n", "ja": "訳。"}
            for s in checker.paper_sentences(paper)]


def test_sentences_skip_front_matter_and_headings_and_keep_captions(checker):
    """
    Front matter and headings carry no claim; captions and list items do.
    フロントマターと見出しは主張を含まず、キャプションと箇条書きは含む。
    """
    assert checker.paper_sentences(PAPER) == [
        "The tool reads files.",
        "It measures height (\\autoref{fig:a}).",
        "Item one, for code.",
        "A caption.",
    ]


def test_a_decimal_or_an_asterisk_does_not_end_a_sentence(checker):
    text = "Models 4.8, 5 and A* search are used. Next one."
    assert checker.paper_sentences(text) == [
        "Models 4.8, 5 and A* search are used.", "Next one."]


def test_a_sentence_without_a_record_is_reported(checker):
    claims = _all_unverified(checker)[1:]
    problems = checker.check(_files(checker, claims))
    assert any("no record for" in p for p in problems)


def test_a_record_whose_sentence_left_the_paper_is_reported(checker):
    claims = _all_unverified(checker) + [
        {"sentence": "Gone.", "status": "unverified", "note": "n"}]
    problems = checker.check(_files(checker, claims))
    assert any("not in paper.md" in p for p in problems)


@pytest.mark.parametrize("source, fragment", [
    ({"kind": "doc", "path": "docs/d.md", "quote": "four scans"}, "quote not found"),
    ({"kind": "code", "path": "lib/mod.py", "symbol": "missing"}, "symbol 'missing'"),
    ({"kind": "code", "path": "lib/mod.py", "quote": "VALUE = 4"}, "quote not found"),
    ({"kind": "external", "ref": "Nobody2000", "locator": "p", "quote": "q"}, "neither a URL"),
    ({"kind": "external", "ref": "Key2020", "locator": "p", "quote": ""}, "without quote"),
    ({"kind": "author", "reason": ""}, "without reason"),
    ({"kind": "figure", "path": "figures/none.png", "observed": "x"}, "not found"),
])
def test_a_source_that_does_not_hold_is_reported(checker, source, fragment):
    claims = _all_unverified(checker)
    claims[0] = {"sentence": claims[0]["sentence"], "status": "verified", "sources": [source]}
    problems = checker.check(_files(checker, claims))
    assert any(fragment in p for p in problems), problems


def test_sources_that_hold_pass(checker):
    claims = _all_unverified(checker)
    claims[0] = {"sentence": claims[0]["sentence"], "status": "verified", "sources": [
        {"kind": "doc", "path": "docs/d.md", "quote": "bundled scans are three scans"},
        {"kind": "code", "path": "lib/mod.py", "symbol": "func", "quote": "return VALUE"},
        {"kind": "external", "ref": "Key2020", "locator": "p. 1", "quote": "q"},
        {"kind": "external", "ref": "https://example.org", "locator": "README", "quote": "q"},
        {"kind": "author", "reason": "confirmed by the corresponding author"},
    ]}
    assert checker.check(_files(checker, claims)) == []


def test_verified_needs_a_source_and_unverified_needs_a_note(checker):
    claims = _all_unverified(checker)
    claims[0] = {"sentence": claims[0]["sentence"], "status": "verified", "sources": []}
    claims[1] = {"sentence": claims[1]["sentence"], "status": "unverified", "note": ""}
    problems = checker.check(_files(checker, claims))
    assert any("verified without a source" in p for p in problems)
    assert any("unverified without a note" in p for p in problems)


def test_blocks_keep_paragraphs_list_items_and_figures_apart(checker):
    text = PAPER + "\nIntro:\n\n- First item.\n  Continued.\n- Second item.\n\nAfter.\n"
    kinds = [b[0] for b in checker.paper_blocks(text)]
    assert kinds == ["heading", "para", "item", "figure", "para", "item", "item", "para"]
    assert checker.paper_blocks(text)[5][1] == ["First item.", "Continued."]


@pytest.mark.parametrize("ja, fragment", [
    ("引用がない。", "citations differ"),
    ("[@Key2020] 値は 3 nm。", "inline code differs"),
    ("[@Key2020] `x` の値は 4 nm。", "number 3 missing"),
    ("[@Key2020] `x` の値は 3 nm、5 回。", "number 5 not in the English"),
])
def test_translation_differences_are_reported(checker, ja, fragment):
    en = "The value of `x` is 3 nm [@Key2020]."
    assert any(fragment in p for p in checker.translation_problems(en, ja))


def test_spelled_out_numbers_may_become_digits(checker):
    en = "Three scans of `x` were read [@Key2020]."
    assert checker.translation_problems(en, "[@Key2020] `x` の 3 つのスキャンを読んだ。") == []


def _translated(checker, paper=PAPER):
    record = {
        "title_ja": "題",
        "headings_ja": {"Summary": "概要"},
        "claims": [{"sentence": s, "status": "unverified", "note": "n", "ja": "訳" + "あいうえお"[i] + "。"}
                   for i, s in enumerate(checker.paper_sentences(paper))],
    }
    return record


def test_missing_translation_and_stale_japanese_paper_are_reported(checker):
    record = _translated(checker)
    record["claims"][0]["ja"] = ""
    files = {checker.PAPER: PAPER, checker.BIB: "", checker.CLAIMS: json.dumps(record)}
    problems = checker.check(lambda rel: files.get(rel))
    assert any("no Japanese translation" in p for p in problems)

    record = _translated(checker)
    files[checker.CLAIMS] = json.dumps(record)
    files[checker.PAPER_JA] = "edited by hand\n"
    problems = checker.check(lambda rel: files.get(rel))
    assert any("does not match" in p for p in problems)

    files[checker.PAPER_JA] = checker.render_ja(PAPER, record)
    assert checker.check(lambda rel: files.get(rel)) == []


def test_rendered_japanese_follows_the_english_structure(checker):
    text = checker.render_ja(PAPER, _translated(checker))
    assert 'title: "題"' in text
    assert "# 概要" in text
    assert "訳あ。訳い。" in text
    assert "- 訳う。" in text
    assert "![訳え。\\label{fig:a}](figures/a.png)" in text


def test_unverified_sentences_may_only_shrink(checker):
    """
    A commit may remove or verify an unverified sentence but never add one.
    コミットは未確認の文を削除・確認できるが、追加はできない。
    """
    before = [{"sentence": "A.", "status": "unverified"},
              {"sentence": "B.", "status": "verified"}]
    assert checker.unverified_additions(before, [{"sentence": "B.", "status": "verified"}]) == []
    assert checker.unverified_additions(
        before, [{"sentence": "A.", "status": "unverified"},
                 {"sentence": "B.", "status": "unverified"}]) == ["B."]
    assert checker.unverified_additions(
        before, [{"sentence": "C.", "status": "unverified"}]) == ["C."]
    assert checker.unverified_additions(None, before) == []
