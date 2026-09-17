#!/usr/bin/env python3
"""Keep `docs/gui04_measurements.md` in step with the code it quotes.
`docs/gui04_measurements.md` を、引用しているコードと一致させ続ける検査。

The document explains how GUI04 places a fiber's centerline and computes every
number its fiber table and detail window show, quoting the source. Quoted code
rots faster than prose, so this script turns each way the page can go stale
into a failure:
この文書は、GUI04 が繊維の中心線を置き、ファイバー一覧と詳細ウィンドウに表示する
各数値を計算する方法を、ソースを引用しながら説明する。引用したコードは散文より
速く陳腐化するため、本スクリプトは文書が古くなる経路をそれぞれ失敗に変える。

1. Every code excerpt names its source (``# source: <path>::<symbol>``) and
   must still appear, line for line, in that symbol.
   各コード片は出典（``# source: <path>::<symbol>``）を名乗り、そのシンボル内に
   行単位で今も存在しなければならない。
2. Every symbol in `WATCHED_SYMBOLS` is fingerprinted with comments and
   docstrings removed. A change to what one of them computes fails until the
   document has been reviewed and `tests/gui04_doc_manifest.json` refreshed.
   `WATCHED_SYMBOLS` の各シンボルを、コメントと docstring を除いて指紋化する。
   計算内容が変わると、文書を見直して `tests/gui04_doc_manifest.json` を更新
   するまで失敗する。
3. Every column of GUI04's fiber table is explained, so a new column cannot
   ship without an explanation.
   GUI04 のファイバー一覧の全列が説明されている。説明の無い列は出荷できない。
4. The English and Japanese versions share one heading skeleton and quote the
   same code.
   英語版と日本語版が同じ見出し構造を持ち、同じコードを引用している。

It is run in three places: `.githooks/pre-commit` (``--staged``, against the
index), `tests/test_gui04_docs.py` in CI, and the Claude Code hook
`.claude/hooks/doc_code_reminder.py`, which uses `drifted_symbols` to tell an
agent the moment it edits a documented symbol. Only the standard library is
imported, because the hooks run outside the project environment.
実行箇所は 3 つ。`.githooks/pre-commit`（``--staged``、インデックスに対して）、
CI の `tests/test_gui04_docs.py`、および Claude Code フック
`.claude/hooks/doc_code_reminder.py`（`drifted_symbols` を使い、エージェントが
解説対象のシンボルを編集した時点で知らせる）。フックはプロジェクト環境の外で
動くため、標準ライブラリしか import しない。

Usage:
    python scripts/check_gui04_docs.py            # check the working tree
    python scripts/check_gui04_docs.py --staged   # check the index (pre-commit)
    python scripts/check_gui04_docs.py --update   # refresh the fingerprints

Exit codes: 0 = clean, 1 = findings, 2 = usage or git error (fails closed).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# The shared excerpt contract lives beside this script. Put its directory on the
# path explicitly, because the Claude Code hook loads this file by path, where
# the script's own directory is not searched.
# 共通の引用規約はこのスクリプトの隣にある。Claude Code フックはこのファイルを
# パス指定で読み込み、その場合スクリプト自身のディレクトリは検索されないため、
# 明示的にパスへ加える。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from doc_excerpts import (  # noqa: E402
    ROOT,
    Reader,
    _SOURCE_HEADER,  # noqa: F401  (read by .claude/hooks/doc_code_reminder.py)
    _find_node,
    check_pair_excerpts,
    excerpt_problem,  # noqa: F401  (re-exported for tests)
    excerpts,  # noqa: F401  (re-exported for tests)
    fenced_blocks,  # noqa: F401  (re-exported for tests)
    headings,
    read_staged,
    read_worktree,
    split_symbol,
    symbol_digest,
    symbol_source,  # noqa: F401  (re-exported for tests)
)

DOC_EN = "docs/gui04_measurements.md"
DOC_JA = "docs/gui04_measurements.ja.md"
MANIFEST = "tests/gui04_doc_manifest.json"

# The symbols the document quotes and explains. A symbol is fingerprinted, not
# its whole module: GUI04 alone is several thousand lines, and a module-level
# fingerprint would demand a document review for every unrelated UI edit.
# Adding an excerpt of a new symbol means adding it here; the check refuses an
# excerpt of a symbol that is not watched, so quoted code is always guarded.
# 文書が引用・解説するシンボル。モジュール全体ではなくシンボル単位で指紋化する。
# GUI04 だけで数千行あり、モジュール単位の指紋では無関係な UI 編集のたびに文書の
# 見直しを要求してしまうためである。新しいシンボルを引用するときはここへ追加する。
# 監視外のシンボルの引用は検査が拒否するため、引用したコードは常に守られる。
WATCHED_SYMBOLS: Tuple[str, ...] = (
    "lib/measure.py::measure_bundle",
    "lib/fiber_tracking_image.py::_build_fiber",
    "lib/fiber.py::Fiber.length",
    "lib/centerline.py::_WIDTH_SEARCH_PX",
    "lib/centerline.py::_WIDTH_STEP_PX",
    "lib/centerline.py::_WIDTH_TANGENT_HALF",
    "lib/centerline.py::FALLBACK_WIDTH_PX",
    "lib/centerline.py::_FRAME_SIGMA_WIDTHS",
    "lib/centerline.py::_CREST_REACH_WIDTHS",
    "lib/centerline.py::_HALF_MAX_REACH_WIDTHS",
    "lib/centerline.py::_MAX_SECTION_WIDTHS",
    "lib/centerline.py::_OFFSET_SMOOTH_WIDTHS",
    "lib/centerline.py::_JUNCTION_WIDTHS",
    "lib/centerline.py::_MIN_CREST_AMPLITUDE_FRAC",
    "lib/centerline.py::_CREST_WINDOW_WIDTHS",
    "lib/centerline.py::place_centerline",
    "lib/centerline.py::measure_apparent_width",
    "lib/centerline.py::_refine",
    "lib/centerline.py::_whittaker_first_order",
    "lib/centerline.py::polyline_distance",
    "lib/measure.py::CUT_END_EXCLUSION_WIDTHS",
    "lib/measure.py::MIN_HEIGHT_SAMPLES",
    "lib/measure.py::HEIGHT_UPPER_PERCENTILE",
    "lib/measure.py::DEFAULT_CURVATURE_WINDOW_NM",
    "lib/measure.py::compute_fiber_stats",
    "lib/measure.py::height_sample_mask",
    "lib/measure.py::fiber_straightness",
    "lib/measure.py::fiber_curvature_profile",
    "lib/measure.py::fiber_mean_curvature",
    "lib/measure.py::fiber_kink_density",
    "lib/kink_detector.py::END_MARGIN_WIDTHS",
    "guis/GUI04_Tracking_fiber.py::App._build_fiber_table",
    "guis/GUI04_Tracking_fiber.py::_table_values",
    "guis/GUI04_Tracking_fiber.py::App._populate_fiber_table",
    "guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_fiber_image",
    "guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_profile",
    "lib/fiber_connector.py::ConnectParams",
    "lib/fiber_connector.py::MANUAL_RANGE_FACTOR",
    "lib/fiber_connector.py::_manual_reach",
    "lib/fiber_connector.py::connection_candidates",
    "lib/fiber_connector.py::_fragment_end_geometry",
    "lib/fiber_connector.py::angle_between_three_points",
    "lib/fiber_connector.py::_fragment_median_heights",
    "lib/fiber_connector.py::_candidates_for",
    "lib/fiber_connector.py::_build_chain_fiber",
    "lib/fiber_connector.py::_rebuild_connected_fiber",
    "lib/fiber_connector.py::filter_fibers_by_height",
)

# Where the fiber table's column tuple is built, and the names its headings
# concatenate. The headings are read from the source rather than imported,
# because GUI04 imports tkinter at module level.
# ファイバー一覧の列タプルを組み立てる場所と、見出しが連結する名前。GUI04 は
# モジュールレベルで tkinter を import するため、見出しは import せずソースから読む。
TABLE_SYMBOL = "guis/GUI04_Tracking_fiber.py::App._build_fiber_table"
TABLE_VARIABLE = "cols"
TABLE_NAMES = {"UNIT_MICROMETER": "µm"}

# Number of the document section that explains the fiber table. Every column
# needs a subsection of its own there, whose heading names the column in
# backticks; a mention in the overview table alone does not count, because a
# name in a table explains nothing about how the value is computed.
# ファイバー一覧を解説する文書の節番号。各列はその中に、列名をバッククォートで
# 示す見出しを持つ自分の小節を必要とする。概要表での言及だけでは数えない。表に
# 名前があっても、値の計算方法は何も説明されないためである。
TABLE_SECTION = "3"

# The document distinguishes two coordinate sequences along a fiber, the
# centerline and the skeleton track, and must always say which one it means.
# A bare "line" / 「線」 is ambiguous between them, so it is refused outside
# code. The allowances below are compounds that mean neither sequence
# (a straight line, a guide line in a plot, a line of source code), removed
# before the search.
# 文書は繊維に沿った 2 つの座標列（中心線とスケルトントラック）を区別し、どちらを
# 指すのかを常に明示しなければならない。単独の "line" /「線」はどちらとも読める
# ため、コード外では拒否する。以下の許可語は、どちらの座標列も指さない複合語
# （直線、プロットの補助線、ソースコードの行など）で、検索の前に取り除く。
BARE_LINE_EN = re.compile(r"\blines?\b", re.IGNORECASE)
ALLOWED_LINE_EN = re.compile(
    r"straight line|line for line|a line holding|comment lines|blank\s+lines"
    r"|guide lines|cyan lines",
    re.IGNORECASE,
)
BARE_LINE_JA = re.compile("線")
ALLOWED_LINE_JA = re.compile(
    "中心線|半値中点線|直線|曲線|破線|実線|補助線|縦線|折れ線|等高線|法線|接線"
    "|線形|細線化|稜線"
)


# ----------------------------------------------------------------------------
# Fingerprints
# ----------------------------------------------------------------------------

def current_digests(reader: Reader = read_worktree,
                    symbols: Sequence[str] = WATCHED_SYMBOLS) -> Dict[str, Optional[str]]:
    """Fingerprint the given symbols as `reader` sees the sources."""
    cache: Dict[str, Optional[str]] = {}
    out: Dict[str, Optional[str]] = {}
    for key in symbols:
        path, name = split_symbol(key)
        if path not in cache:
            cache[path] = reader(path)
        source = cache[path]
        out[key] = None if source is None else symbol_digest(source, name)
    return out


def recorded_digests(reader: Reader = read_worktree) -> Dict[str, str]:
    """Return the fingerprints recorded in the manifest (empty if absent)."""
    text = reader(MANIFEST)
    if text is None:
        return {}
    return json.loads(text).get("symbols", {})


def drifted_symbols(path: str, reader: Reader = read_worktree) -> List[str]:
    """
    Return the watched symbols of one file whose code no longer matches.
    1 ファイル内の監視シンボルのうち、記録と一致しなくなったものを返す。

    Used by the Claude Code hook right after an edit to `path`.
    `path` の編集直後に Claude Code フックが使う。
    """
    keys = [k for k in WATCHED_SYMBOLS if split_symbol(k)[0] == path]
    if not keys:
        return []
    recorded = recorded_digests(reader)
    now = current_digests(reader, keys)
    return [k for k in keys if recorded.get(k) != now[k]]


def watched_paths() -> List[str]:
    """Return the source files that hold at least one watched symbol."""
    return sorted({split_symbol(k)[0] for k in WATCHED_SYMBOLS})


# ----------------------------------------------------------------------------
# Document parsing
# ----------------------------------------------------------------------------

def table_section_headings(text: str) -> List[str]:
    """
    Return the subsection headings inside the fiber-table section.
    ファイバー一覧の節に含まれる小節の見出しを返す。

    The section starts at the level-2 heading numbered `TABLE_SECTION` and
    ends at the next level-2 heading.
    節は番号 `TABLE_SECTION` の第 2 レベル見出しで始まり、次の第 2 レベル
    見出しで終わる。
    """
    found: List[str] = []
    inside = False
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            inside = line[3:].lstrip().startswith(f"{TABLE_SECTION}.")
        elif inside and line.startswith("### "):
            found.append(line[4:])
    return found


def bare_line_mentions(text: str, japanese: bool) -> List[Tuple[int, str]]:
    """
    Return the prose lines that say "line" without saying which one.
    どちらの座標列かを示さずに「線」と書いている本文の行を返す。

    Fenced code blocks and inline code spans are ignored, and the compounds in
    `ALLOWED_LINE_EN` / `ALLOWED_LINE_JA` are removed before the search.
    フェンス付きコードブロックとインラインコードは無視し、許可語は検索前に除く。
    """
    bare = BARE_LINE_JA if japanese else BARE_LINE_EN
    allowed = ALLOWED_LINE_JA if japanese else ALLOWED_LINE_EN
    found: List[Tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        prose = allowed.sub("", re.sub(r"`[^`]*`", "", line))
        if bare.search(prose):
            found.append((number, line.strip()))
    return found


def table_columns(reader: Reader = read_worktree) -> List[str]:
    """
    Return the headings of GUI04's fiber table as the source builds them.
    GUI04 のファイバー一覧の見出しを、ソースが組み立てるとおりに返す。
    """
    path, name = split_symbol(TABLE_SYMBOL)
    source = reader(path)
    if source is None:
        return []
    node = _find_node(ast.parse(source), name)
    if node is None:
        return []

    def value(expr: ast.AST) -> str:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name) and expr.id in TABLE_NAMES:
            return TABLE_NAMES[expr.id]
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            return value(expr.left) + value(expr.right)
        raise ValueError(f"unsupported column expression: {ast.dump(expr)}")

    for sub in ast.walk(node):
        if (isinstance(sub, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == TABLE_VARIABLE
                        for t in sub.targets)
                and isinstance(sub.value, ast.Tuple)):
            return [value(e) for e in sub.value.elts]
    return []


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

def check_documents(reader: Reader = read_worktree) -> List[str]:
    """
    Return every problem with the documents themselves.
    文書自体の問題をすべて返す。

    Covers presence, the shared structure of the pair, the excerpts, the
    coverage of every watched symbol, and every table column.
    存在、対の構造一致、引用、全監視シンボルの網羅、全列の説明を扱う。
    """
    problems: List[str] = []
    docs = {rel: reader(rel) for rel in (DOC_EN, DOC_JA)}
    for rel, text in docs.items():
        if text is None:
            problems.append(f"{rel} is missing")
    if any(text is None for text in docs.values()):
        return problems
    en, ja = docs[DOC_EN], docs[DOC_JA]

    # An empty column list would make the coverage check pass vacuously, so a
    # table this script can no longer read is a failure, not a pass.
    # 列の一覧が空だと網羅の検査が空振りで通ってしまうため、読み取れなくなった
    # 表は合格ではなく失敗として扱う。
    columns = table_columns(reader)
    if not columns:
        problems.append(
            f"cannot read the fiber-table columns from {TABLE_SYMBOL} "
            f"(variable `{TABLE_VARIABLE}`); update TABLE_SYMBOL / "
            "TABLE_VARIABLE in scripts/check_gui04_docs.py"
        )

    if headings(en) != headings(ja):
        problems.append(
            f"{DOC_EN} and {DOC_JA} have diverged in structure; add the "
            "corresponding section to the other file"
        )
    excerpt_problems, quoted = check_pair_excerpts(
        docs, reader, allowed=WATCHED_SYMBOLS,
        allowed_label="WATCHED_SYMBOLS (scripts/check_gui04_docs.py)",
    )
    problems.extend(excerpt_problems)

    for rel, text in docs.items():
        for key in WATCHED_SYMBOLS:
            if key not in quoted[rel]:
                problems.append(f"{rel}: watched symbol {key} is never quoted")

        word = "「線」" if rel == DOC_JA else '"line"'
        for number, line in bare_line_mentions(text, japanese=(rel == DOC_JA)):
            problems.append(
                f"{rel}:{number}: says {word} "
                "without saying whether it is the centerline or the skeleton "
                f"track: {line}"
            )

        subsections = table_section_headings(text)
        for column in columns:
            if not any(f"`{column}`" in h for h in subsections):
                problems.append(
                    f"{rel}: fiber-table column `{column}` is not explained "
                    f"(no subsection of section {TABLE_SECTION} names it in "
                    "its heading)"
                )
    return problems


def check_fingerprints(reader: Reader = read_worktree) -> List[str]:
    """Return one problem per watched symbol whose code changed or vanished."""
    recorded = recorded_digests(reader)
    problems = []
    for key, digest in current_digests(reader).items():
        if digest is None:
            problems.append(f"{key} no longer exists")
        elif recorded.get(key) != digest:
            problems.append(f"{key} changed since the document was reviewed")
    stale = sorted(set(recorded) - set(WATCHED_SYMBOLS))
    for key in stale:
        problems.append(f"{MANIFEST} records {key}, which is no longer watched")
    return problems


def _staged_names() -> set:
    """Return the repository-relative paths in the staged diff."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "-z"],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git diff --cached failed: {detail}")
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def update_manifest() -> None:
    """Rewrite the fingerprint manifest from the working tree."""
    digests = current_digests(read_worktree)
    missing = [k for k, v in digests.items() if v is None]
    if missing:
        raise SystemExit("cannot fingerprint missing symbols: " + ", ".join(missing))
    payload = {
        "_comment": (
            "SHA-256 of each symbol docs/gui04_measurements.md explains, with "
            "comments and docstrings removed. Refresh with "
            "`python scripts/check_gui04_docs.py --update` only after "
            "rereading the affected sections of both language versions."
        ),
        "symbols": digests,
    }
    (ROOT / MANIFEST).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"updated {MANIFEST}")


_HOW_TO_FIX = (
    "\n"
    "docs/gui04_measurements.md (and its .ja.md pair) explains the code above\n"
    "to the people who cite GUI04's numbers. Reread the sections that quote the\n"
    "changed symbols, update both language versions (including the quoted\n"
    "excerpts), then refresh the fingerprints:\n"
    "\n"
    "    .venv\\Scripts\\python.exe scripts\\check_gui04_docs.py --update\n"
)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point: check the working tree, check the index, or update."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true",
                       help="check the staged snapshot; used by pre-commit")
    group.add_argument("--update", action="store_true",
                       help="refresh tests/gui04_doc_manifest.json")
    args = parser.parse_args(argv)

    if args.update:
        update_manifest()
        return 0

    reader = read_staged if args.staged else read_worktree
    try:
        problems = check_fingerprints(reader) + check_documents(reader)
        if args.staged:
            staged = _staged_names()
            # Refreshing the fingerprints is the claim that the document was
            # reread, so it has to come with the document.
            # 指紋の更新は「文書を読み直した」という主張なので、文書の変更を伴う
            # 必要がある。
            if MANIFEST in staged and not staged & {DOC_EN, DOC_JA}:
                problems.append(
                    f"{MANIFEST} is refreshed but neither {DOC_EN} nor "
                    f"{DOC_JA} is part of the commit"
                )
    except (RuntimeError, SyntaxError, ValueError) as exc:
        print(f"gui04-doc check: {exc}", file=sys.stderr)
        return 2

    if not problems:
        return 0
    label = "staged snapshot" if args.staged else "working tree"
    print(f"gui04-doc check ({label}):", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(_HOW_TO_FIX, file=sys.stderr)
    if args.staged:
        print(
            "If the change genuinely cannot affect the explanation (a pure\n"
            "refactor), refresh the fingerprints and commit with --no-verify;\n"
            "the CI test still checks every excerpt against the code.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
