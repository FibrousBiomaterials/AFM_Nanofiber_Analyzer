#!/usr/bin/env python3
"""Verify the code excerpts quoted in the explanatory documents.
解説文書に引用したコード片を、実際のコードと照合する共通処理。

`docs/algorithms.md` and `docs/gui04_measurements.md` (with their Japanese
pairs) explain the analysis by quoting the code that performs it. A quoted
excerpt rots the moment the code changes, so every excerpt names its source and
is checked against it:
`docs/algorithms.md` と `docs/gui04_measurements.md`（および日本語版）は、解析を
実行するコードを引用して説明する。引用したコード片はコードが変わった瞬間に古く
なるため、各コード片は出典を名乗り、その出典と照合される。

```text
# source: lib/kink_detector.py::KinkDetector.judge_line
```

The header names a file and a function, method (``Class.method``) or module
constant; several constants of one file may be listed, separated by commas. A
line holding only ``...`` marks omitted code. The source side is compared with
its docstrings and comments removed, and blank lines and indentation are ignored
on both sides, so a method body is quoted dedented and without its comments.
ヘッダはファイルと、関数・メソッド（``Class.method``）・モジュール定数を指す。
1 ファイルの複数の定数をカンマ区切りで並べてもよい。``...`` だけの行は省略を表す。
ソース側は docstring とコメントを除いてから照合し、空行と字下げは両側で無視するため、
メソッド本体は字下げを外し、コメントを省いて引用する。

`scripts/check_gui04_docs.py`, `scripts/check_algorithm_docs.py` and
`tests/test_algorithm_docs.py` all use this module, so the two document pairs
follow one excerpt contract. Only the standard library is imported, because the
git and Claude Code hooks run outside the project environment.
`scripts/check_gui04_docs.py`・`scripts/check_algorithm_docs.py`・
`tests/test_algorithm_docs.py` がすべてこのモジュールを使うため、2 組の文書は
同じ引用規約に従う。git フックと Claude Code フックはプロジェクト環境の外で動く
ため、標準ライブラリしか import しない。
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import subprocess
import tokenize
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]

Reader = Callable[[str], Optional[str]]

_SOURCE_HEADER = re.compile(r"^#\s*source:\s*(\S+?)::(.+?)\s*$")
_GAP = "..."


# ----------------------------------------------------------------------------
# Readers
# ----------------------------------------------------------------------------

def read_worktree(rel: str) -> Optional[str]:
    """Return a repository file from the working tree, or ``None`` if absent."""
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def read_staged(rel: str) -> Optional[str]:
    """Return a repository file as staged in the index, or ``None`` if absent.
    インデックスにステージされた内容を返す。無ければ ``None``。
    """
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f":{rel}"], capture_output=True
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8")


# ----------------------------------------------------------------------------
# Symbols and fingerprints
# ----------------------------------------------------------------------------

def split_symbol(key: str) -> Tuple[str, str]:
    """Split ``path::Qualified.name`` into its path and qualified name."""
    path, _, name = key.partition("::")
    return path, name


def _find_node(tree: ast.Module, qualname: str) -> Optional[ast.AST]:
    """
    Locate a top-level or class-level definition by its qualified name.
    修飾名から、トップレベルまたはクラス内の定義を探す。

    Functions, classes, properties and module constants (plain or annotated
    assignments) are recognised.
    関数・クラス・プロパティ・モジュール定数（通常代入・注釈付き代入）を扱う。
    """
    body: Sequence[ast.stmt] = tree.body
    node: Optional[ast.AST] = None
    for part in qualname.split("."):
        node = None
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and stmt.name == part:
                node = stmt
            elif isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == part for t in stmt.targets):
                node = stmt
            elif (isinstance(stmt, ast.AnnAssign)
                  and isinstance(stmt.target, ast.Name)
                  and stmt.target.id == part):
                node = stmt
            if node is not None:
                break
        if node is None:
            return None
        body = getattr(node, "body", [])
    return node


def _span(node: ast.AST) -> Tuple[int, int]:
    """Return the 1-based inclusive line span of a node, decorators included."""
    start = node.lineno
    for deco in getattr(node, "decorator_list", []):
        start = min(start, deco.lineno)
    return start, node.end_lineno


def _code_lines(source: str) -> List[str]:
    """
    Return the source lines with every comment truncated away.
    すべてのコメントを切り落としたソース行を返す。

    `tokenize` is used rather than a regular expression so a ``#`` inside a
    string literal is left alone.
    正規表現ではなく `tokenize` を使い、文字列リテラル内の ``#`` を残す。
    """
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            lines[row - 1] = lines[row - 1][:col]
    return lines


def _docstring_lines(node: ast.AST) -> set:
    """Return the line numbers of every docstring inside a node."""
    found: set = set()
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.ClassDef, ast.FunctionDef,
                                ast.AsyncFunctionDef)):
            continue
        body = sub.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            found.update(range(body[0].lineno, body[0].end_lineno + 1))
    return found


def symbol_source(source: str, qualname: str) -> Optional[str]:
    """Return the verbatim source of one symbol, or ``None`` if it is gone."""
    node = _find_node(ast.parse(source), qualname)
    if node is None:
        return None
    start, end = _span(node)
    return "\n".join(source.splitlines()[start - 1:end])


def symbol_code(source: str, qualname: str) -> Optional[str]:
    """
    Return one symbol's code with docstrings and comments removed.
    docstring とコメントを除いた 1 シンボルのコードを返す。

    This is what an excerpt is compared with, so an excerpt quotes code only:
    a docstring or a trailing comment inside the quoted region does not have to
    be reproduced, and cannot be.
    コード片はこれと照合するため、引用範囲内の docstring や行末コメントを
    再現する必要はない（再現しても一致しない）。
    """
    node = _find_node(ast.parse(source), qualname)
    if node is None:
        return None
    start, end = _span(node)
    lines = _code_lines(source)
    skip = _docstring_lines(node)
    return "\n".join(
        lines[number - 1].rstrip()
        for number in range(start, end + 1)
        if number not in skip
    )


def symbol_digest(source: str, qualname: str) -> Optional[str]:
    """
    Fingerprint one symbol, ignoring comments, docstrings and blank lines.
    コメント・docstring・空行を無視して 1 シンボルを指紋化する。

    Notes
    -----
    Line-based rather than `ast.dump`, whose node fields change between Python
    releases and would make the fingerprint differ across the CI matrix.
    `ast.dump` ではなく行単位で扱う。`ast.dump` はリリース間でノードフィールドが
    変わり、CI マトリクス間で指紋が食い違うためである。
    """
    tree = ast.parse(source)
    node = _find_node(tree, qualname)
    if node is None:
        return None
    start, end = _span(node)
    lines = _code_lines(source)
    skip = _docstring_lines(node)
    kept = [
        lines[number - 1].rstrip()
        for number in range(start, end + 1)
        if number not in skip and lines[number - 1].strip()
    ]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def module_digest(source: str) -> str:
    """
    Fingerprint a whole module, ignoring comments, docstrings and blank lines.
    コメント・docstring・空行を無視してモジュール全体を指紋化する。

    The same definition as `tests/test_algorithm_docs.py` records in
    `tests/algorithm_doc_manifest.json`, so the Claude Code hook can tell that
    an algorithm module changed without running the test suite.
    `tests/test_algorithm_docs.py` が `tests/algorithm_doc_manifest.json` に
    記録するものと同じ定義。Claude Code フックがテストを走らせずにアルゴリズム
    モジュールの変更を判定できるようにする。
    """
    lines = _code_lines(source)
    tree = ast.parse(source)
    skip = _docstring_lines(tree)
    body = tree.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        skip.update(range(body[0].lineno, body[0].end_lineno + 1))
    kept = [
        line.rstrip()
        for number, line in enumerate(lines, start=1)
        if number not in skip and line.strip()
    ]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Document parsing
# ----------------------------------------------------------------------------

def fenced_blocks(text: str) -> List[List[str]]:
    """Return the body lines of every fenced code block, in order."""
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def source_blocks(text: str) -> List[List[str]]:
    """Return the fenced blocks that start with a ``# source:`` header."""
    return [b for b in fenced_blocks(text)
            if b and _SOURCE_HEADER.match(b[0].strip())]


def excerpts(text: str) -> List[Tuple[List[str], List[str]]]:
    """
    Return ``(symbol keys, excerpt lines)`` for each block with a source header.
    出典ヘッダを持つ各ブロックについて ``(シンボルキー, 引用行)`` を返す。

    The header ``# source: lib/x.py::a, b`` may name several symbols of one
    file; the excerpt is then matched against their sources in that order.
    ヘッダ ``# source: lib/x.py::a, b`` は 1 ファイルの複数シンボルを指定でき、
    その場合は引用をそれらのソースを順に連結したものと照合する。
    """
    out = []
    for block in source_blocks(text):
        match = _SOURCE_HEADER.match(block[0].strip())
        path = match.group(1)
        names = [n.strip() for n in match.group(2).split(",") if n.strip()]
        out.append(([f"{path}::{n}" for n in names], block[1:]))
    return out


def headings(text: str) -> List[str]:
    """Return the ``#`` prefix of every heading outside fenced blocks."""
    levels: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#"):
            levels.append(line.split(" ", 1)[0])
    return levels


def _normalise(lines: Sequence[str]) -> List[str]:
    """Strip each line and drop blank and comment-only lines."""
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def excerpt_problem(excerpt: Sequence[str], source: str) -> Optional[str]:
    """
    Explain why an excerpt does not match its source, or return ``None``.
    引用がソースと一致しない理由を返す。一致すれば ``None``。

    A line holding only ``...`` marks omitted code. Each run between such
    markers must appear contiguously, and the runs in order, once blank and
    comment-only lines are ignored on both sides; indentation is ignored too,
    so a method body may be quoted dedented.
    ``...`` だけの行は省略を表す。空行とコメントだけの行を両側で無視したうえで、
    その間の各区間が連続して、かつ区間が順に現れなければならない。インデントも
    無視するため、メソッド本体を字下げを外して引用できる。
    """
    haystack = _normalise(source.splitlines())
    chunks: List[List[str]] = [[]]
    for line in excerpt:
        if line.strip() == _GAP:
            chunks.append([])
        else:
            chunks[-1].append(line)
    pos = 0
    for chunk in (_normalise(c) for c in chunks):
        if not chunk:
            continue
        found = -1
        for i in range(pos, len(haystack) - len(chunk) + 1):
            if haystack[i:i + len(chunk)] == chunk:
                found = i
                break
        if found < 0:
            return f"no longer matches the source, starting at: {chunk[0]!r}"
        pos = found + len(chunk)
    return None


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

def check_pair_excerpts(
    docs: Dict[str, str],
    reader: Reader = read_worktree,
    allowed: Optional[Iterable[str]] = None,
    allowed_label: str = "",
) -> Tuple[List[str], Dict[str, set]]:
    """
    Check the excerpts of a synchronized document pair.
    同期する文書の対について、引用したコード片を検査する。

    Parameters
    ----------
    docs
        ``{relative path: text}`` for the English and the Japanese document,
        in that order.
        英語版・日本語版の順の ``{相対パス: 本文}``。
    reader
        Reads the quoted source files (working tree or index).
        引用元のソースファイルを読む関数（作業ツリーまたはインデックス）。
    allowed
        Symbol keys an excerpt may name; ``None`` allows any symbol.
        コード片が指してよいシンボルキー。``None`` なら制限しない。
    allowed_label
        Where `allowed` is defined, for the error message.
        エラーメッセージに示す、`allowed` の定義場所。

    Returns
    -------
    tuple
        ``(problems, quoted)``: one message per problem, and the symbol keys
        each document quotes.
        ``(問題, 引用)``。問題ごとのメッセージと、各文書が引用するシンボルキー。
    """
    problems: List[str] = []
    rels = list(docs)
    blocks = [source_blocks(docs[rel]) for rel in rels]
    if len(blocks) == 2 and blocks[0] != blocks[1]:
        problems.append(
            f"{rels[0]} and {rels[1]} quote different code; the excerpts must "
            "be identical in both languages"
        )
    allowed_set = None if allowed is None else set(allowed)
    sources: Dict[str, Optional[str]] = {}
    quoted: Dict[str, set] = {}
    for rel in rels:
        quoted[rel] = set()
        for keys, lines in excerpts(docs[rel]):
            quoted[rel].update(keys)
            joined: List[str] = []
            for key in keys:
                path, name = split_symbol(key)
                if allowed_set is not None and key not in allowed_set:
                    problems.append(
                        f"{rel}: excerpt of {key}, which is not in "
                        f"{allowed_label or 'the allowed symbols'}"
                    )
                if path not in sources:
                    sources[path] = reader(path)
                src = sources[path]
                body = None if src is None else symbol_code(src, name)
                if body is None:
                    problems.append(f"{rel}: {key} no longer exists")
                    joined = []
                    break
                joined.append(body)
            if joined:
                issue = excerpt_problem(lines, "\n".join(joined))
                if issue:
                    problems.append(f"{rel}: excerpt of {', '.join(keys)} {issue}")
    return problems, quoted
