# -*- coding: utf-8 -*-
"""
Keep `docs/gui04_measurements.md` honest about the code it quotes.
`docs/gui04_measurements.md` の記述を、引用しているコードと一致させ続けるテスト。

The document explains GUI04's centerline and every number GUI04 displays,
quoting the source. The checks live in `scripts/check_gui04_docs.py`, which the
pre-commit hook and the Claude Code hook also run; this file carries them into
CI, where they cannot be skipped, and verifies that each check actually fails
on the kind of drift it exists to catch.
この文書は GUI04 の中心線と GUI04 が表示する各数値を、ソースを引用しながら説明
する。検査本体は `scripts/check_gui04_docs.py` にあり、pre-commit フックと
Claude Code フックも同じものを実行する。本ファイルはそれを省略できない CI へ
持ち込み、各検査が捕捉すべき種類のずれで実際に失敗することも確かめる。

After rereading the affected sections of both language versions, refresh the
fingerprints with:
両言語版の該当節を読み直したうえで、指紋を次で更新する:

    .venv\\Scripts\\python.exe scripts\\check_gui04_docs.py --update
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_gui04_docs as docs  # noqa: E402


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
    quote every watched symbol, and explain every fiber-table column.
    両言語版が存在し、互いに一致し、コードを正確に引用し、全監視シンボルを
    引用し、ファイバー一覧の全列を説明している。
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
        + "\nReread the sections of docs/gui04_measurements.md and its .ja.md "
        "pair that quote these symbols, update them, then run:\n"
        "    .venv\\Scripts\\python.exe scripts\\check_gui04_docs.py --update"
    )


def test_every_watched_symbol_resolves():
    """Every entry of `WATCHED_SYMBOLS` names a definition that exists."""
    missing = [k for k, v in docs.current_digests().items() if v is None]
    assert not missing, missing


def test_fiber_table_columns_are_read_from_the_source():
    """
    The column reader sees GUI04's real headings, so the coverage check is
    not vacuous.
    列の読み取りが GUI04 の実際の見出しを返し、網羅検査が空振りしない。
    """
    columns = docs.table_columns()
    assert "length (nm)" in columns
    assert "curvature (rad/µm)" in columns
    assert len(columns) >= 10


def test_behavioral_change_breaks_the_fingerprint():
    """A changed computation in a watched symbol is detected."""
    reader = _overlay({"lib/measure.py": lambda t: t.replace(
        "HEIGHT_UPPER_PERCENTILE = 90.0", "HEIGHT_UPPER_PERCENTILE = 95.0")})
    problems = docs.check_fingerprints(reader)
    assert any("HEIGHT_UPPER_PERCENTILE" in p for p in problems), problems


def test_comment_only_change_keeps_the_fingerprint():
    """Editing only comments and docstrings does not demand a review."""
    def edit(text):
        return text.replace(
            "# Median and maximum guide lines follow the main-window checkbox",
            "# The median and maximum guide lines follow the checkbox",
        ).replace(
            "Redraw the height profile using main-window display toggles.",
            "Redraw the height profile from the display toggles.",
        )
    reader = _overlay({"guis/GUI04_Tracking_fiber.py": edit})
    assert edit(docs.read_worktree("guis/GUI04_Tracking_fiber.py")) != \
        docs.read_worktree("guis/GUI04_Tracking_fiber.py")
    assert not docs.check_fingerprints(reader)


def test_stale_excerpt_is_detected():
    """An excerpt that no longer matches its symbol is reported."""
    reader = _overlay({"lib/fiber_connector.py": lambda t: t.replace(
        "MANUAL_RANGE_FACTOR = 2.0", "MANUAL_RANGE_FACTOR = 3.0")})
    problems = docs.check_documents(reader)
    assert any("MANUAL_RANGE_FACTOR" in p and "no longer matches" in p
               for p in problems), problems


def test_undocumented_table_column_is_detected():
    """A new fiber-table column without an explanation is reported."""
    reader = _overlay({"guis/GUI04_Tracking_fiber.py": lambda t: t.replace(
        '"unjudged", "W (nm)", "reliable")',
        '"unjudged", "W (nm)", "reliable", "new column")')})
    problems = docs.check_documents(reader)
    assert any("`new column`" in p for p in problems), problems


def test_column_listed_only_in_the_overview_is_not_explained():
    """
    Naming a column in the overview table without a subsection of its own
    still fails, in the language version that lacks the subsection.
    概要表に列名があっても専用の小節が無ければ、その言語版で失敗する。
    """
    add_column = {"guis/GUI04_Tracking_fiber.py": lambda t: t.replace(
        '"unjudged", "W (nm)", "reliable")',
        '"unjudged", "W (nm)", "reliable", "new column")')}
    row = "| `reliable` |"
    overview = {
        path: (lambda t: t.replace(row, "| `new column` | x | x |\n" + row, 1))
        for path in ("docs/gui04_measurements.md",
                     "docs/gui04_measurements.ja.md")
    }
    problems = docs.check_documents(_overlay({**add_column, **overview}))
    assert any("`new column`" in p for p in problems), problems

    section = {"docs/gui04_measurements.md": lambda t: t.replace(
        "## 4. The fiber detail window",
        "### 3.12 `new column`\n\nExplained.\n\n## 4. The fiber detail window")}
    problems = docs.check_documents(_overlay({**add_column, **section}))
    assert any("gui04_measurements.ja.md" in p and "`new column`" in p
               for p in problems), problems
    assert not any("gui04_measurements.md:" in p and "`new column`" in p
                   for p in problems), problems


def test_unreadable_table_fails_closed():
    """A fiber table the checker can no longer read is a failure."""
    reader = _overlay({"guis/GUI04_Tracking_fiber.py": lambda t: t.replace(
        'cols = ("#", "length (nm)"', 'columns = ("#", "length (nm)"')})
    problems = docs.check_documents(reader)
    assert any("cannot read the fiber-table columns" in p
               for p in problems), problems


def test_bare_line_is_refused_in_both_languages():
    """
    Prose that says a bare 「線」 / "line" is reported; compounds meaning
    neither sequence, and code, are not.
    単独の「線」/ "line" は報告し、どちらの座標列も指さない複合語とコードは
    報告しない。
    """
    ja = ("中心線に沿って測る。\n直線と破線と `line_reliable`。\n"
          "線の端から測る。\n```python\nline = 1  # 線\n```\n")
    assert [n for n, _ in docs.bare_line_mentions(ja, japanese=True)] == [3]
    en = ("Measured along the centerline.\nA straight line and guide lines.\n"
          "Measured from the line end.\n```python\nline = 1\n```\n")
    assert [n for n, _ in docs.bare_line_mentions(en, japanese=False)] == [3]

    reader = _overlay({"docs/gui04_measurements.ja.md": lambda t: t.replace(
        "中心線の各点 $i$ について、", "線の各点 $i$ について、")})
    problems = docs.check_documents(reader)
    assert any("gui04_measurements.ja.md" in p and "線の各点" in p
               for p in problems), problems


def test_diverging_language_versions_are_detected():
    """An excerpt edited in one language version only is reported."""
    reader = _overlay({"docs/gui04_measurements.ja.md": lambda t: t.replace(
        "MANUAL_RANGE_FACTOR = 2.0\n", "MANUAL_RANGE_FACTOR = 2.0\nextra = 1\n", 1)})
    problems = docs.check_documents(reader)
    assert any("quote different code" in p for p in problems), problems


def test_excerpt_of_unwatched_symbol_is_refused():
    """Quoting a symbol that is not fingerprinted is refused."""
    block = (
        "\n```python\n# source: lib/measure.py::fiber_kink_angle\n"
        "if not stat.kink_angles_deg:\n    return float(\"nan\")\n```\n"
    )
    reader = _overlay({"docs/gui04_measurements.md": lambda t: t + block})
    problems = docs.check_documents(reader)
    assert any("not in WATCHED_SYMBOLS" in p for p in problems), problems


def test_excerpt_matching_honours_gaps_and_order():
    """`...` separates runs that must appear in order, each contiguously."""
    source = "a = 1\n# note\nb = 2\n\nc = 3\nd = 4\n"
    assert docs.excerpt_problem(["a = 1", "b = 2"], source) is None
    assert docs.excerpt_problem(["a = 1", "...", "d = 4"], source) is None
    assert docs.excerpt_problem(["a = 1", "c = 3"], source) is not None
    assert docs.excerpt_problem(["d = 4", "...", "a = 1"], source) is not None
