# -*- coding: utf-8 -*-
"""
Keep `docs/gui03_statistics.md` honest about the code it quotes.
`docs/gui03_statistics.md` の記述を、引用しているコードと一致させ続けるテスト。

The document explains the statistics GUI03 computes, quoting the source. The
checks live in `scripts/check_gui03_docs.py`, which the pre-commit hook and the
Claude Code hook also run; this file carries them into CI, where they cannot be
skipped, and verifies that each check actually fails on the kind of drift it
exists to catch.
この文書は GUI03 が計算する統計を、ソースを引用しながら説明する。検査本体は
`scripts/check_gui03_docs.py` にあり、pre-commit フックと Claude Code フックも同じ
ものを実行する。本ファイルはそれを省略できない CI へ持ち込み、各検査が捕捉すべき
種類のずれで実際に失敗することも確かめる。

After rereading the affected sections of both language versions, refresh the
fingerprints with:
両言語版の該当節を読み直したうえで、指紋を次で更新する:

    .venv\\Scripts\\python.exe scripts\\check_gui03_docs.py --update
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_gui03_docs as docs  # noqa: E402

_COMPARE = "afm_nanofiber_analyzer/group_compare.py"


def _overlay(edits):
    """
    Return a reader that serves edited copies of some files.
    一部のファイルだけ編集済みの写しを返すリーダーを作る。

    `edits` maps a repository-relative path to a function that edits its text.
    `edits` はリポジトリ相対パスを、その本文を編集する関数へ対応付ける。
    """
    def reader(rel):
        text = docs.read_worktree(rel)
        if text is not None and rel in edits:
            text = edits[rel](text)
        return text

    return reader


def test_documents_are_consistent_with_the_code():
    """
    Both language versions exist, match each other, quote the code exactly,
    and quote every watched symbol.
    両言語版が存在し、互いに一致し、コードを正確に引用し、全監視シンボルを
    引用している。
    """
    problems = docs.check_documents()
    assert not problems, "\n".join(problems)


def test_watched_code_matches_the_reviewed_fingerprints():
    """
    No quoted symbol changed since the document was last reviewed.
    文書の最終確認以降、引用中のシンボルが変わっていない。
    """
    problems = docs.check_fingerprints()
    assert not problems, (
        "\n".join(problems)
        + "\nReread the sections of docs/gui03_statistics.md and its .ja.md "
        "pair that quote these symbols, update them, then run:\n"
        "    .venv\\Scripts\\python.exe scripts\\check_gui03_docs.py --update"
    )


def test_every_watched_symbol_resolves():
    """Every entry of `WATCHED_SYMBOLS` names a definition that exists."""
    missing = [k for k, v in docs.current_digests().items() if v is None]
    assert not missing, missing


def test_behavioral_change_breaks_the_fingerprint():
    """A changed computation in a watched symbol is detected."""
    reader = _overlay({_COMPARE: lambda t: t.replace(
        "MIN_SAMPLES_FOR_TEST = 3", "MIN_SAMPLES_FOR_TEST = 4")})
    problems = docs.check_fingerprints(reader)
    assert any("MIN_SAMPLES_FOR_TEST" in p for p in problems), problems


def test_comment_only_change_keeps_the_fingerprint():
    """Editing only comments and docstrings does not demand a review."""
    def edit(text):
        return text.replace(
            "# Correction spans the whole family of pairs, once per test.",
            "# The correction spans every pair, once per test.",
        ).replace(
            "Return Holm-corrected p-values for a family of comparisons.",
            "Return the Holm-corrected p-values of a family of comparisons.",
        )
    original = docs.read_worktree(_COMPARE)
    assert edit(original) != original
    assert not docs.check_fingerprints(_overlay({_COMPARE: edit}))


def test_stale_excerpt_is_detected():
    """An excerpt that no longer matches its symbol is reported."""
    reader = _overlay({_COMPARE: lambda t: t.replace(
        "_SAMPLED_SPLITS = 20_000", "_SAMPLED_SPLITS = 10_000")})
    problems = docs.check_documents(reader)
    assert any("_SAMPLED_SPLITS" in p and "no longer matches" in p
               for p in problems), problems


def test_diverging_language_versions_are_detected():
    """An excerpt edited in one language version only is reported."""
    reader = _overlay({"docs/gui03_statistics.ja.md": lambda t: t.replace(
        "CONVENTIONAL_ALPHA = 0.05\n", "CONVENTIONAL_ALPHA = 0.05\nextra = 1\n", 1)})
    problems = docs.check_documents(reader)
    assert any("quote different code" in p for p in problems), problems


def test_diverging_heading_structure_is_detected():
    """A section added to one language version only is reported."""
    reader = _overlay({"docs/gui03_statistics.md": lambda t: t.replace(
        "## References", "### 4.8 Extra\n\nText.\n\n## References")})
    problems = docs.check_documents(reader)
    assert any("diverged in structure" in p for p in problems), problems


def test_excerpt_of_unwatched_symbol_is_refused():
    """Quoting a symbol that is not fingerprinted is refused."""
    block = (
        "\n```python\n# source: afm_nanofiber_analyzer/group_compare.py::_SAMPLED_BATCH\n"
        "_SAMPLED_BATCH = 500\n```\n"
    )
    reader = _overlay({"docs/gui03_statistics.md": lambda t: t + block})
    problems = docs.check_documents(reader)
    assert any("not in WATCHED_SYMBOLS" in p for p in problems), problems


def test_watched_symbol_nobody_quotes_is_reported(monkeypatch):
    """A watched symbol that neither language version quotes is reported."""
    extra = f"{_COMPARE}::_SAMPLED_BATCH"
    monkeypatch.setattr(docs, "WATCHED_SYMBOLS", docs.WATCHED_SYMBOLS + (extra,))
    problems = docs.check_documents()
    assert any(extra in p and "never quoted" in p for p in problems), problems
