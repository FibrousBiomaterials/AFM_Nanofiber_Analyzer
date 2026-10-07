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


# Key of the module-level statements that define no name (``if`` blocks,
# expression statements, ``try``), fingerprinted together.
# 名前を定義しないモジュール直下の文（``if``・式文・``try``）をまとめて指紋化する
# ときのキー。
MODULE_STATEMENTS = "<module statements>"


def _node_digest(lines: List[str], node: ast.AST, skip: set) -> str:
    """Fingerprint one node's lines, less comments, docstrings and blank lines."""
    start, end = _span(node)
    kept = [
        lines[number - 1].rstrip()
        for number in range(start, end + 1)
        if number not in skip and lines[number - 1].strip()
    ]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def _bound_names(stmt: ast.stmt) -> List[str]:
    """Names a module- or class-level assignment binds, in order."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    names: List[str] = []
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
    return names


def _is_type_checking_block(node: ast.AST) -> bool:
    """
    Whether a statement is an ``if TYPE_CHECKING:`` block with no ``else``.
    文が ``else`` を持たない ``if TYPE_CHECKING:`` ブロックかどうか。

    Its body never runs, so what it imports exists only for annotations.
    その本体は実行されないため、そこで import するものは注釈のためにしか存在しない。
    """
    if not isinstance(node, ast.If) or node.orelse:
        return False
    test = node.test
    return ((isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"))


def _runtime_names(node: ast.AST) -> set:
    """
    Every bare name and attribute a node mentions outside annotations.
    注釈の外でノードが言及する、すべての名前と属性名。

    Argument and return annotations, and ``if TYPE_CHECKING:`` blocks, are
    skipped: a name mentioned only there takes no part in the computation, so
    adding the import that provides it cannot change what the code computes.
    引数と戻り値の注釈、および ``if TYPE_CHECKING:`` ブロックは飛ばす。そこでしか
    言及されない名前は計算に関与しないため、それを提供する import を加えても
    コードの計算は変わらない。
    """
    found: set = set()
    stack = [node]
    while stack:
        sub = stack.pop()
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
        if _is_type_checking_block(sub):
            continue
        for field, value in ast.iter_fields(sub):
            if (field == "annotation" and isinstance(sub, ast.arg)) or (
                    field == "returns"
                    and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))):
                continue
            if isinstance(value, ast.AST):
                stack.append(value)
            elif isinstance(value, list):
                stack.extend(v for v in value if isinstance(v, ast.AST))
    return found


def _char_offset(line: str, byte_col: int) -> int:
    """Convert an `ast` column (UTF-8 bytes) into a character index of `line`."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _signatures_without_annotations(source: str, tree: ast.Module,
                                    lines: List[str]) -> List[str]:
    """
    Return `lines` with each function signature reduced to an annotation-free form.
    各関数シグネチャを注釈なしの形に縮めた `lines` を返す。

    Argument and return annotations are removed, and so is the whitespace of
    the signature and a trailing comma before its closing parenthesis, because
    adding an annotation typically rewraps the signature and respaces its
    defaults (``x=3`` becomes ``x: int = 3``). The reduced signature replaces
    the ``def`` line and the signature's continuation lines become blank, so
    every other line keeps its number. Decorators and the body are untouched.
    引数と戻り値の注釈を除き、シグネチャ内の空白と閉じ括弧直前の末尾カンマも
    除く。注釈を付けるとシグネチャの折り返しや既定値まわりの空白（``x=3`` が
    ``x: int = 3`` になる）も変わるのが普通だからである。縮めたシグネチャで
    ``def`` 行を置き換え、続きの行は空にするので、他の行の行番号は変わらない。
    デコレータと本体には触れない。

    Notes
    -----
    Annotations take no part in what this project computes: nothing reads
    them at run time (no ``functools.singledispatch``, no
    ``typing.get_type_hints``). Annotations of assignments are kept, because a
    dataclass field exists only through its annotation.
    このプロジェクトの計算に注釈は関与しない。実行時に注釈を読むもの
    （``functools.singledispatch``、``typing.get_type_hints``）は使っていない。
    代入の注釈は残す。dataclass のフィールドは注釈によってのみ存在するためである。
    """
    original = source.splitlines()
    out = list(lines)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first, last = node.lineno, node.body[0].lineno - 1
        if last < first:
            # A one-line definition (``def f(): pass``) has no header of its own.
            # 1 行の定義（``def f(): pass``）には独立したヘッダ行が無い。
            continue
        starts = []
        pos = 0
        for number in range(first, last + 1):
            starts.append(pos)
            pos += len(out[number - 1]) + 1
        header = "\n".join(out[number - 1] for number in range(first, last + 1))

        def offset(lineno: int, byte_col: int) -> int:
            return (starts[lineno - first]
                    + _char_offset(original[lineno - 1], byte_col))

        spans = []
        args = node.args
        for arg in (args.posonlyargs + args.args + args.kwonlyargs
                    + [a for a in (args.vararg, args.kwarg) if a is not None]):
            if arg.annotation is not None:
                name_end = arg.col_offset + len(arg.arg.encode("utf-8"))
                spans.append((offset(arg.lineno, name_end),
                              offset(arg.annotation.end_lineno,
                                     arg.annotation.end_col_offset)))
        if node.returns is not None:
            end = offset(node.returns.end_lineno, node.returns.end_col_offset)
            arrow = header.rfind("->", 0, offset(node.returns.lineno,
                                                 node.returns.col_offset))
            if arrow >= 0:
                spans.append((arrow, end))
        for start, end in sorted(spans, reverse=True):
            header = header[:start] + header[end:]
        header = re.sub(r"\s+", "", header)
        close = header.rfind(")")
        if close > 0 and header[close - 1] == ",":
            header = header[:close - 1] + header[close:]
        out[first - 1] = header
        for number in range(first + 1, last + 1):
            out[number - 1] = ""
    return out


def code_symbol_digests(source: str) -> Dict[str, str]:
    """
    Fingerprint every definition of a module separately.
    モジュールの各定義を個別に指紋化する。

    Keys are top-level functions and constants (``name``), class methods and
    constants (``Class.name``), a class's remaining body (``Class.<body>``),
    imported names (``import:name``), and `MODULE_STATEMENTS`. Comments,
    docstrings and blank lines are ignored, as in `symbol_digest`; unlike it,
    so are function annotations (`_signatures_without_annotations`) and
    ``if TYPE_CHECKING:`` blocks.
    キーは、トップレベルの関数と定数（``name``）、クラスのメソッドと定数
    （``Class.name``）、クラス本体の残り（``Class.<body>``）、import した名前
    （``import:name``）、および `MODULE_STATEMENTS` である。`symbol_digest` と
    同じくコメント・docstring・空行は無視し、それと違って関数の注釈
    （`_signatures_without_annotations`）と ``if TYPE_CHECKING:`` ブロックも無視する。

    Notes
    -----
    Per-definition fingerprints are what let `computation_changes` tell a
    change to the existing computation from an addition nothing uses: a single
    module fingerprint moves for both, which blocked comment-free but
    behaviour-preserving edits such as a deprecated alias. Annotations are left
    out for the same reason: correcting a type hint cannot change a number.
    定義ごとの指紋によって、`computation_changes` は既存の計算への変更と、何も
    使わない追加とを見分けられる。モジュール全体の指紋では両方で動いてしまい、
    非推奨の別名のように挙動を変えない編集まで止めていた。注釈を除くのも同じ
    理由で、型ヒントを直しても数値は変わらないためである。
    """
    tree = ast.parse(source)
    lines = _signatures_without_annotations(source, tree, _code_lines(source))
    skip = _docstring_lines(tree)
    body = tree.body
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        skip.update(range(body[0].lineno, body[0].end_lineno + 1))
        body = body[1:]

    out: Dict[str, str] = {}
    loose: List[str] = []

    def put(key: str, digest: str) -> None:
        # A name defined twice keeps both definitions, in order.
        # 2 回定義された名前は、両方の定義を順に保つ。
        n, k = 1, key
        while k in out:
            n += 1
            k = f"{key}#{n}"
        out[k] = digest

    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            put(stmt.name, _node_digest(lines, stmt, skip))
        elif isinstance(stmt, ast.ClassDef):
            rest: List[str] = []
            for member in stmt.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    put(f"{stmt.name}.{member.name}", _node_digest(lines, member, skip))
                elif isinstance(member, (ast.Assign, ast.AnnAssign)):
                    for name in _bound_names(member):
                        put(f"{stmt.name}.{name}", _node_digest(lines, member, skip))
                else:
                    rest.append(_node_digest(lines, member, skip))
            # The class line itself (bases, decorators) and anything left in
            # its body belong to the class.
            # クラス行（基底クラス・デコレータ）と本体の残りはクラスに属する。
            header = [lines[n - 1].rstrip() for n in range(_span(stmt)[0], stmt.body[0].lineno)
                      if n not in skip and lines[n - 1].strip()]
            put(f"{stmt.name}.<body>", hashlib.sha256(
                "\n".join(header + rest).encode("utf-8")).hexdigest())
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for name in _bound_names(stmt):
                put(name, _node_digest(lines, stmt, skip))
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            module = "." * getattr(stmt, "level", 0) + (getattr(stmt, "module", None) or "")
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".")[0]
                spec = f"{module}:{alias.name}" if isinstance(stmt, ast.ImportFrom) else alias.name
                put(f"import:{bound}",
                    hashlib.sha256(spec.encode("utf-8")).hexdigest())
        elif _is_type_checking_block(stmt):
            continue
        else:
            loose.append(_node_digest(lines, stmt, skip))
    out[MODULE_STATEMENTS] = hashlib.sha256("\n".join(loose).encode("utf-8")).hexdigest()
    return out


def _referenced_names(source: str, keys: Iterable[str]) -> set:
    """Every bare name and attribute the given definitions mention outside annotations."""
    tree = ast.parse(source)
    wanted = set(keys)
    found: set = set()

    def visit(node: ast.AST) -> None:
        found.update(_runtime_names(node))

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name in wanted:
                visit(stmt)
        elif isinstance(stmt, ast.ClassDef):
            for member in stmt.body:
                names = ([member.name] if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                         else _bound_names(member) if isinstance(member, (ast.Assign, ast.AnnAssign))
                         else [])
                if (any(f"{stmt.name}.{n}" in wanted for n in names)
                        or (not names and f"{stmt.name}.<body>" in wanted)):
                    visit(member)
            if f"{stmt.name}.<body>" in wanted:
                for base in stmt.bases + stmt.decorator_list:
                    visit(base)
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if any(n in wanted for n in _bound_names(stmt)):
                visit(stmt)
        elif not isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if MODULE_STATEMENTS in wanted:
                visit(stmt)
    return found


def computation_changes(
    recorded: Dict[str, str],
    source: str,
    external: Optional[set] = None,
) -> List[str]:
    """
    Describe what in `source` can change the computation `recorded` fingerprinted.
    `recorded` が指紋化した計算を変えうる `source` 内の変更を記述する。

    Parameters
    ----------
    recorded
        `code_symbol_digests` of the reviewed version of the module.
        確認済みの版のモジュールの `code_symbol_digests`。
    source
        The module's current source.
        モジュールの現在のソース。
    external
        Names the rest of the project code mentions (`names_used_in` over the
        files `is_project_code` accepts, less this module). A new public
        definition that other code calls is part of the analysis even though
        nothing in its own module uses it, as a detector method called by the
        fiber connector is. ``None`` skips this test.
        プロジェクトコードの残りが言及する名前（`is_project_code` が認める
        ファイルからこのモジュールを除いたものに対する `names_used_in`）。
        他のコードが呼ぶ新しい公開定義は、自モジュールで誰も使わなくても解析の
        一部である（繊維コネクタが呼ぶ検出器のメソッドなど）。``None`` なら
        この判定を行わない。

    Returns
    -------
    list of str
        One line per definition that was changed or removed, and per new
        definition that code already present refers to by name; empty when
        the change cannot alter what the reviewed code computes.
        変更・削除された定義ごと、および既存のコードが名前で参照する新しい定義
        ごとに 1 行。確認済みのコードの計算を変えられない変更なら空。

    Notes
    -----
    A new definition that no existing definition names, and that (with
    `external`) no other project code names, cannot change what the analysis
    computes, so it is not reported: a deprecated alias, a helper only new code
    in the module will call, a new constant. Once existing code
    starts using it, that code's own fingerprint moves and the change is
    reported. A new top-level name that existing code already mentions is
    reported even when that code is unchanged, because it shadows whatever
    the name resolved to before (a builtin, or an imported name).
    既存のどの定義も名指さず、（`external` を与えた場合）他のプロジェクトコードも
    名指さない新しい定義は、解析の計算を変えられないため報告しない（非推奨の別名、
    モジュール内の新しいコードだけが呼ぶ補助関数、新しい定数）。
    既存のコードがそれを使い始めれば、そのコード自身の指紋が動いて報告される。
    既存のコードが既に言及している名前を新たにトップレベルに定義した場合は、
    そのコードが無変更でも報告する。その名前が以前指していたもの（組み込み関数や
    import した名前）を覆い隠すためである。

    Function annotations and ``if TYPE_CHECKING:`` blocks are not part of the
    fingerprint (`code_symbol_digests`), and a name mentioned only in them does
    not count as used, so adding or correcting a type hint, with the import it
    needs, is not reported. Removing an import is still reported, because the
    recorded fingerprint cannot tell what the name was used for.
    関数の注釈と ``if TYPE_CHECKING:`` ブロックは指紋に含めず
    （`code_symbol_digests`）、そこでしか言及されない名前は使われたとみなさない。
    そのため、型ヒントの追加や修正は、それに必要な import を含めて報告しない。
    import の削除は引き続き報告する。記録された指紋からは、その名前が何に
    使われていたかが分からないためである。
    """
    current = code_symbol_digests(source)
    out = [f"changed {key}" for key in recorded
           if key in current and current[key] != recorded[key]]
    out += [f"removed {key}" for key in recorded if key not in current]
    added = [key for key in current if key not in recorded]
    if added:
        existing = [key for key in current if key in recorded]
        used = _referenced_names(source, existing)
        for key in added:
            name = key.split(":", 1)[-1].split("#")[0]
            # A new class is keyed by its body; existing code names the class.
            # 新しいクラスは本体のキーで記録され、既存のコードはクラス名で参照する。
            simple = (name[:-len(".<body>")] if name.endswith(".<body>")
                      else name.split(".")[-1])
            if simple in used:
                out.append(f"added {key}, which existing code refers to")
            elif external is not None and not simple.startswith("_") and simple in external:
                out.append(f"added {key}, which other project code refers to")
    return out


# Project code outside a module that can put a new definition of it to use.
# Tests and scripts are left out: they exercise the analysis, they are not it.
# あるモジュールの新しい定義を使いうる、そのモジュール以外のプロジェクトコード。
# テストとスクリプトは除く。解析を試すものであって、解析そのものではない。
PROJECT_CODE_PREFIXES = ("lib/", "guis/")
PROJECT_CODE_FILES = ("cli.py", "Main.py")


def is_project_code(rel: str) -> bool:
    """Whether a repository path is analysis or GUI code (see `PROJECT_CODE_PREFIXES`)."""
    return rel.endswith(".py") and (rel.startswith(PROJECT_CODE_PREFIXES)
                                    or rel in PROJECT_CODE_FILES)


def project_code_paths(root: Path = ROOT) -> List[str]:
    """
    Repository-relative paths of the project code in the working tree.
    作業ツリー内のプロジェクトコードのリポジトリ相対パス。

    Walks only `PROJECT_CODE_PREFIXES` and `PROJECT_CODE_FILES`, so a virtual
    environment or scratch directory under the root is never read.
    `PROJECT_CODE_PREFIXES` と `PROJECT_CODE_FILES` だけをたどるため、ルート下の
    仮想環境や作業用ディレクトリは読まない。
    """
    root = Path(root)
    out = [name for name in PROJECT_CODE_FILES if (root / name).is_file()]
    for prefix in PROJECT_CODE_PREFIXES:
        base = root / prefix
        if base.is_dir():
            out += [p.relative_to(root).as_posix() for p in base.rglob("*.py")]
    return sorted(out)


def names_used_in(sources: Iterable[str]) -> set:
    """
    Every bare name and attribute mentioned in the given sources outside annotations.
    与えたソースで注釈の外に言及される、すべての名前と属性名。

    Unparsable sources are skipped: a syntax error is reported by the tests,
    and a reminder must not fail because of it. Annotations are skipped as in
    `_runtime_names`.
    構文解析できないソースは飛ばす。構文エラーはテストが報告し、通知がそれで
    失敗してはならない。注釈は `_runtime_names` と同じく飛ばす。
    """
    found: set = set()
    for source in sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        found.update(_runtime_names(tree))
    return found


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
