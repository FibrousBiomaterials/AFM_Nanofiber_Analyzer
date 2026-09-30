#!/usr/bin/env python3
"""Check that every number in the algorithm documents says where it comes from.
アルゴリズム解説文書のすべての数値が、出典を示していることを確認する。

`docs/algorithms.md` and `docs/algorithms.ja.md` state results: how often a
rule found the marked kinks, how far a centerline lies from the true one, how
large a background residual was. A number with no source cannot be checked, and
one measured on code that has since changed reads as authoritative while it is
wrong. Every number in the prose therefore carries a hidden source marker
directly after it, and this script checks each one:
`docs/algorithms.md` と `docs/algorithms.ja.md` は結果を述べる。規則が印の付いた
キンクをどれだけ見つけたか、中心線が真の中心線からどれだけ離れているか、背景の
残差がどれだけあったか。出典の無い数値は確かめられず、その後に変わったコードで
測った数値は、誤っていても信頼できるものとして読まれる。そこで本文のすべての数値の
直後に、表示されない出典の印を付け、本スクリプトがそれぞれを照合する。

``0.23<!--m:experiment.key-->``
    Measured. The value recorded under that key in `MEASUREMENTS`, written by
    ``scripts/measure_docs.py``. The recording stores the fingerprints of the
    analysis code it ran on; a change to what that code computes makes every
    value of the recording stale until it is measured again.
    実測値。``scripts/measure_docs.py`` が `MEASUREMENTS` に書いたその項目の値。
    記録は実行したときの解析コードの指紋を持ち、そのコードの計算が変わると、
    測り直すまでその記録の値はすべて古いものとして扱われる。
``3<!--c:lib/pipeline.py::ProcParams.mask_dilation-->``
    A constant or default in the code: a module constant (``path::NAME``), a
    class attribute or dataclass field (``path::Class.name``), or a parameter
    default (``path::func(param)``, ``path::Class.method(param)``). A trailing
    ``|expr`` transforms the value, with ``v`` standing for it
    (``|180 - v``).
    コードの定数・既定値。モジュール定数（``path::NAME``）、クラス属性・
    dataclass フィールド（``path::Class.name``）、引数の既定値
    （``path::func(param)``、``path::Class.method(param)``）。末尾の ``|式`` は値を
    変換する。``v`` がその値を表す（``|180 - v``）。
``23<!--x:12 * 2000 / 1024-->``
    Arithmetic on the numbers the sentence states, evaluated here.
    文が述べる数値からの計算。ここで評価する。
``1989<!--n:citation-->``
    Not a result: a citation, a label, a count in a definition, a value an
    example is built with. The reason is required and stays visible in review.
    結果ではない数値。文献、ラベル、定義の中の個数、例を作る値など。理由は必須で、
    レビューで見える。

A number is compared at the precision it is written with, so ``0.11`` matches
0.1149 and ``23`` matches 23.44. A range written ``a–b`` (or ``a〜b``) with one
marker after it matches a two-element value. Numbers inside fenced code, inline
code, math, headings, section references (``§4.2``), link targets, version
strings (``1.0.0``) and ordered-list markers are not checked.
数値は書かれた精度で比較する。``0.11`` は 0.1149 に、``23`` は 23.44 に一致する。
``a–b``（または ``a〜b``）と書いた範囲の直後に印が 1 つあれば、2 要素の値と
照合する。フェンス付きコード・インラインコード・数式・見出し・節番号
（``§4.2``）・リンク先・バージョン文字列（``1.0.0``）・番号付きリストの番号は
照合しない。

Numbers written before this check existed and not yet verified are listed in
`PENDING` by the line that holds them. The list may only shrink: a line that is
edited no longer matches its entry, so its numbers must be marked, and the
staged check refuses a commit that adds an entry.
本チェックの導入前に書かれ、まだ検証していない数値は、それを含む行によって
`PENDING` に記録されている。一覧は減る方向にしか変えられない。編集した行は
項目と一致しなくなるため、その数値には印が要る。また、項目を追加するコミットは
ステージ済みの検査が拒否する。

Only the standard library is imported, because the git hooks run outside the
project environment.
git フックはプロジェクト環境の外で動くため、標準ライブラリしか import しない。

Usage
-----
``python scripts/check_doc_numbers.py``            check the working tree
``python scripts/check_doc_numbers.py --staged``   check the staged snapshot
``python scripts/check_doc_numbers.py --list-unmarked``
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doc_excerpts  # noqa: E402

DOCS = ("docs/algorithms.md", "docs/algorithms.ja.md")
MEASUREMENTS = "tests/doc_measurements.json"
PENDING = "tests/doc_numbers_pending.json"

_MARKER = re.compile(r"<!--([mcxn]):(.*?)-->")
_NUMBER = r"[+\-−±]?\d+(?:\.\d+)?"
# A number, optionally a range, not glued to a preceding word or number.
# 数値（範囲でもよい）。直前の語や数値にくっついていないもの。
_TOKEN = re.compile(
    r"(?<![\w.§/−+\-])(" + _NUMBER + r")(?:\s*[–〜~]\s*(" + _NUMBER + r"))?(?![\w.]*\d)"
)
_VERSION = re.compile(r"(?<![\w.])\d+\.\d+\.\d+(?![\w.])")
_SECTION = re.compile(r"§\s*\d+(?:\.\d+)*")
_LIST_MARKER = re.compile(r"^(\s*(?:>\s*)?)\d+\.(?=\s)")
_INLINE_CODE = re.compile(r"`[^`]*`")
_INLINE_MATH = re.compile(r"\$[^$]+\$")
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# A written fraction such as 1/4: a definition ("a quarter"), not a result.
# 1/4 のような分数。定義（「4 分の 1」）であって結果ではない。
_FRACTION = re.compile(r"(?<![\w.])\d+/\d+(?![\w.])")


@dataclass
class Found:
    """One number in a document, with the marker that follows it, if any."""
    doc: str
    line_no: int
    line: str
    text: str
    low: float
    high: Optional[float]
    kind: Optional[str]
    ref: Optional[str]


def _to_float(text: str) -> float:
    return float(text.replace("−", "-").replace("±", ""))


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _blank(match: "re.Match") -> str:
    return " " * len(match.group(0))


def prose_mask(line: str) -> str:
    """
    The line with everything that is not a checkable number blanked out.
    照合対象の数値以外を空白で潰した行。

    Column positions are kept, so a marker is matched to the number right
    before it.
    列位置を保つため、印をその直前の数値と対応付けられる。
    """
    masked = _MARKER.sub(lambda m: "\0" * len(m.group(0)), line)
    for pattern in (_INLINE_CODE, _INLINE_MATH, _LINK_TARGET, _VERSION, _SECTION, _FRACTION):
        masked = pattern.sub(_blank, masked)
    return _LIST_MARKER.sub(
        lambda m: m.group(1) + " " * (len(m.group(0)) - len(m.group(1))), masked)


def scan(doc: str, text: str) -> List[Found]:
    """
    Every checkable number of a document, in order, with its marker.
    文書の照合対象の数値を、印とともに順に返す。
    """
    found: List[Found] = []
    fence = False
    display_math = False
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if stripped.startswith("$$"):
            # A display-math block opens and closes on "$$" lines; a line that
            # holds both delimiters is a one-line block.
            # 表示数式は "$$" の行で開閉する。両方を含む行は 1 行の数式である。
            if not (len(stripped) > 2 and stripped.endswith("$$")):
                display_math = not display_math
            continue
        if display_math or stripped.startswith("#"):
            continue
        markers: Dict[int, Tuple[str, str]] = {}
        for m in _MARKER.finditer(line):
            markers[m.start()] = (m.group(1), m.group(2).strip())
        masked = prose_mask(line)
        for tok in _TOKEN.finditer(masked):
            end = tok.end()
            kind = ref = None
            if end in markers:
                kind, ref = markers[end]
            low = _to_float(tok.group(1))
            high = _to_float(tok.group(2)) if tok.group(2) else None
            found.append(Found(doc, line_no, line, tok.group(0), low, high, kind, ref))
    return found


# ----------------------------------------------------------------------------
# Resolving markers
# ----------------------------------------------------------------------------

_SAFE_NAMES = {name: getattr(math, name) for name in (
    "pi", "e", "sqrt", "log", "log10", "exp", "sin", "cos", "tan", "atan",
    "asin", "acos", "degrees", "radians", "hypot", "floor", "ceil")}
_SAFE_NAMES.update(abs=abs, min=min, max=max, round=round)


def safe_eval(expr: str, extra: Optional[Dict[str, float]] = None) -> float:
    """Evaluate arithmetic on numbers, `math` functions and `extra` names only."""
    tree = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
               ast.Load, ast.Call, ast.operator, ast.unaryop, ast.Attribute,
               ast.List, ast.Tuple)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError(f"not arithmetic: {expr!r}")
        if isinstance(node, ast.Attribute) and not (
                isinstance(node.value, ast.Name) and node.value.id in ("np", "math")):
            raise ValueError(f"attribute not allowed: {expr!r}")
    names = dict(_SAFE_NAMES)
    names["np"] = names["math"] = math
    names.update(extra or {})
    value = eval(compile(tree, "<marker>", "eval"), {"__builtins__": {}}, names)
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    return float(value)


def _module_bindings(tree: ast.Module) -> Dict[str, ast.AST]:
    out: Dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value:
            out[stmt.target.id] = stmt.value
    return out


def _imported_from(tree: ast.Module, rel: str, name: str) -> Optional[str]:
    """The repository path a ``from .x import name`` of module `rel` points at."""
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and any(a.name == name for a in stmt.names):
            if stmt.level == 1 and stmt.module:
                return str(Path(rel).parent / (stmt.module.replace(".", "/") + ".py")).replace("\\", "/")
            if stmt.module and stmt.module.startswith("lib."):
                return stmt.module.replace(".", "/") + ".py"
    return None


def _evaluate(node: ast.AST, rel: str, tree: ast.Module, read: Callable[[str], Optional[str]],
              depth: int = 0) -> float:
    if depth > 5:
        raise ValueError("constant resolves too deep")
    names: Dict[str, float] = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id not in _SAFE_NAMES and sub.id not in ("np", "math"):
            names[sub.id] = constant_value(f"{rel}::{sub.id}", read, depth + 1, tree=tree)
    return safe_eval(ast.unparse(node), names)


def constant_value(spec: str, read: Callable[[str], Optional[str]], depth: int = 0,
                   tree: Optional[ast.Module] = None) -> float:
    """
    The numeric value a ``c:`` marker names.
    ``c:`` の印が指す数値。
    """
    rel, _, name = spec.partition("::")
    source = read(rel)
    if source is None:
        raise ValueError(f"{rel} not found")
    own = ast.parse(source)
    if name.startswith("len(") and name.endswith(")"):
        # The number of elements of a module-level tuple or list literal.
        # モジュール直下のタプル・リストリテラルの要素数。
        target = _module_bindings(own).get(name[4:-1])
        if not isinstance(target, (ast.Tuple, ast.List)):
            raise ValueError(f"{name[4:-1]} is not a tuple or list literal in {rel}")
        return float(len(target.elts))
    param = None
    if name.endswith(")") and "(" in name:
        name, _, param = name[:-1].partition("(")
    parts = name.split(".")
    if param is not None:
        scope: Sequence[ast.stmt] = own.body
        func = None
        for part in parts:
            func = next((s for s in scope if isinstance(s, (ast.FunctionDef, ast.ClassDef))
                         and s.name == part), None)
            if func is None:
                raise ValueError(f"{name} not found in {rel}")
            scope = func.body
        if not isinstance(func, ast.FunctionDef):
            raise ValueError(f"{name} is not a function")
        args = func.args
        positional = args.posonlyargs + args.args
        defaults = dict(zip([a.arg for a in positional[len(positional) - len(args.defaults):]],
                            args.defaults))
        defaults.update({a.arg: d for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None})
        if param not in defaults:
            raise ValueError(f"{name}({param}) has no default")
        return _evaluate(defaults[param], rel, own, read, depth)
    if len(parts) == 1:
        bindings = _module_bindings(own)
        if parts[0] in bindings:
            return _evaluate(bindings[parts[0]], rel, own, read, depth)
        target = _imported_from(own, rel, parts[0])
        if target:
            return constant_value(f"{target}::{parts[0]}", read, depth + 1)
        raise ValueError(f"{name} not found in {rel}")
    cls = next((s for s in own.body if isinstance(s, ast.ClassDef) and s.name == parts[0]), None)
    if cls is None:
        raise ValueError(f"class {parts[0]} not found in {rel}")
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                and stmt.target.id == parts[1] and stmt.value is not None:
            return _evaluate(stmt.value, rel, own, read, depth)
        if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == parts[1] for t in stmt.targets):
            return _evaluate(stmt.value, rel, own, read, depth)
    raise ValueError(f"{name} not found in {rel}")


def _lookup(values: dict, key: str):
    """A recorded value, or one element of it when the key ends in ``[i]``."""
    index = None
    m = re.match(r"^(.*)\[(\d+)\]$", key)
    if m:
        key, index = m.group(1), int(m.group(2))
    if key not in values:
        raise KeyError(key)
    value = values[key]
    if index is not None:
        if not isinstance(value, list) or index >= len(value):
            raise KeyError(f"{key}[{index}]")
        value = value[index]
    return value


def _matches(written_low: str, written_high: Optional[str], value) -> bool:
    def close(text: str, v: float) -> bool:
        d = _decimals(text.lstrip("+-−±"))
        return round(float(v), d) == round(_to_float(text), d) or \
            abs(float(v) - _to_float(text)) <= 0.5 * 10 ** (-d) + 1e-12
    if written_high is None:
        return not isinstance(value, list) and close(written_low, value)
    return isinstance(value, list) and len(value) == 2 \
        and close(written_low, value[0]) and close(written_high, value[1])


# ----------------------------------------------------------------------------
# Measurements and their staleness
# ----------------------------------------------------------------------------

def load_measurements(read: Callable[[str], Optional[str]]) -> dict:
    text = read(MEASUREMENTS)
    return json.loads(text) if text else {"snapshots": {}, "experiments": {}}


def stale_experiments(measurements: dict, used: set,
                      read: Callable[[str], Optional[str]]) -> Dict[str, List[str]]:
    """
    Experiments whose recorded analysis code has since changed what it computes.
    記録した解析コードの計算がその後変わった実験。
    """
    out: Dict[str, List[str]] = {}
    snapshots = measurements.get("snapshots", {})
    paths = doc_excerpts.project_code_paths(ROOT)
    for name in sorted(used):
        exp = measurements["experiments"].get(name)
        if exp is None or exp.get("historical"):
            continue
        recorded = snapshots.get(exp.get("snapshot", ""), {})
        problems: List[str] = []
        for rel, digests in sorted(recorded.items()):
            source = read(rel)
            if source is None:
                problems.append(f"{rel} removed")
                continue
            others = [read(p) or "" for p in paths if p != rel]
            changes = doc_excerpts.computation_changes(digests, source,
                                                       doc_excerpts.names_used_in(others))
            problems += [f"{rel}: {c}" for c in changes[:3]]
        if problems:
            out[name] = problems
    return out


# ----------------------------------------------------------------------------
# The check
# ----------------------------------------------------------------------------

def pending_key(line: str) -> str:
    """
    A line as the pending list records it: stripped, with its markers removed.
    検証待ち一覧が記録する形の行。前後の空白と印を除いたもの。

    Marking some of a line's numbers keeps it on the list for the rest; editing
    its words does not, so every number of an edited line must be marked.
    行の一部の数値に印を付けても、残りの数値については一覧に残る。語句を編集すると
    残らないため、編集した行の数値にはすべて印が要る。
    """
    return _MARKER.sub("", line).strip()


def _pending(read: Callable[[str], Optional[str]]) -> Dict[str, set]:
    text = read(PENDING)
    if not text:
        return {}
    data = json.loads(text)
    return {doc: set(lines) for doc, lines in data.get("lines", {}).items()}


def check(read: Callable[[str], Optional[str]], list_unmarked: bool = False) -> List[str]:
    """
    Every problem with the numbers of the algorithm documents.
    アルゴリズム解説文書の数値のすべての問題。
    """
    problems: List[str] = []
    measurements = load_measurements(read)
    experiments = measurements.get("experiments", {})
    pending = _pending(read)
    used_experiments: set = set()
    per_doc_markers: Dict[str, List[Tuple[str, str]]] = {}
    pending_seen: Dict[str, set] = {doc: set() for doc in pending}
    for doc in DOCS:
        text = read(doc)
        if text is None:
            problems.append(f"{doc}: missing")
            continue
        markers: List[Tuple[str, str]] = []
        for f in scan(doc, text):
            where = f"{doc}:{f.line_no}: {f.text!r}"
            low_text = re.match(_NUMBER, f.text).group(0)
            high_match = re.search(r"[–〜~]\s*(" + _NUMBER + r")$", f.text)
            high_text = high_match.group(1) if high_match else None
            if f.kind is None:
                if pending_key(f.line) in pending.get(doc, set()):
                    pending_seen.setdefault(doc, set()).add(pending_key(f.line))
                    continue
                problems.append(f"{where} has no source marker "
                                "(m:, c:, x: or n:; see scripts/check_doc_numbers.py)")
                continue
            if f.kind != "n":
                markers.append((f.kind, f.ref))
            try:
                if f.kind == "n":
                    if not f.ref:
                        problems.append(f"{where}: n: needs a reason")
                    continue
                if f.kind == "c":
                    spec, _, transform = f.ref.partition("|")
                    value = constant_value(spec.strip(), read)
                    if transform.strip():
                        value = safe_eval(transform, {"v": value})
                elif f.kind == "x":
                    value = safe_eval(f.ref)
                else:
                    name, _, key = f.ref.partition(".")
                    used_experiments.add(name)
                    if name not in experiments:
                        problems.append(f"{where}: no recorded experiment {name!r}")
                        continue
                    value = _lookup(experiments[name]["values"], key)
                if not _matches(low_text, high_text, value):
                    problems.append(f"{where} does not match its source "
                                    f"{f.kind}:{f.ref} = {value!r}")
            except (ValueError, KeyError, SyntaxError, NameError, TypeError,
                    ZeroDivisionError) as exc:
                problems.append(f"{where}: cannot resolve {f.kind}:{f.ref} ({exc})")
        per_doc_markers[doc] = markers
    if len(per_doc_markers) == 2:
        en, ja = (sorted(per_doc_markers[d]) for d in DOCS)
        if en != ja:
            only_en = sorted(set(en) - set(ja))[:8]
            only_ja = sorted(set(ja) - set(en))[:8]
            problems.append("the English and Japanese documents cite different sources: "
                            f"only in English {only_en}, only in Japanese {only_ja}")
    for name, why in stale_experiments(measurements, used_experiments, read).items():
        problems.append(f"measurement {name!r} is stale ({'; '.join(why[:3])}); re-run "
                        f"`.venv\\Scripts\\python.exe scripts/measure_docs.py --only {name}` "
                        "and update the documents to the new values")
    for doc, lines in pending.items():
        for line in sorted(lines - pending_seen.get(doc, set())):
            problems.append(f"{PENDING}: entry no longer needed in {doc} "
                            f"(remove it): {line[:80]!r}")
    if list_unmarked:
        for doc in DOCS:
            for f in scan(doc, read(doc) or ""):
                if f.kind is None:
                    print(f"{doc}:{f.line_no}: {f.text}  | {f.line.strip()[:100]}")
    return problems


def pending_additions() -> List[str]:
    """Entries the staged pending list has that HEAD's does not."""
    staged = doc_excerpts.read_staged(PENDING)
    proc = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{PENDING}"],
                          capture_output=True)
    if staged is None:
        return []
    now = json.loads(staged).get("lines", {})
    before = json.loads(proc.stdout.decode("utf-8")).get("lines", {}) if proc.returncode == 0 else None
    if before is None:
        return []
    added = []
    for doc, lines in now.items():
        added += [f"{doc}: {line[:80]!r}" for line in set(lines) - set(before.get(doc, []))]
    return added


def _unmarked_lines(read: Callable[[str], Optional[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for doc in DOCS:
        lines = {pending_key(f.line) for f in scan(doc, read(doc) or "") if f.kind is None}
        out[doc] = sorted(lines)
    return out


def _write_pending(lines: Dict[str, List[str]]) -> None:
    payload = {
        "_comment": (
            "Lines of docs/algorithms*.md whose numbers were written before "
            "scripts/check_doc_numbers.py existed and are not yet verified. This list "
            "may only shrink: mark a line's numbers (m:, c:, x:, n:) and run "
            "`python scripts/check_doc_numbers.py --prune-pending`. The staged check "
            "refuses a commit that adds an entry."
        ),
        "lines": {doc: sorted(v) for doc, v in lines.items() if v},
    }
    (ROOT / PENDING).write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                                encoding="utf-8")


def init_pending() -> int:
    """Record every currently unmarked line once, when the check is introduced."""
    if (ROOT / PENDING).is_file():
        print(f"{PENDING} exists; it may only shrink (use --prune-pending)", file=sys.stderr)
        return 1
    _write_pending(_unmarked_lines(doc_excerpts.read_worktree))
    return 0


def prune_pending() -> int:
    """Drop entries whose line no longer carries an unmarked number. Never adds."""
    current = _pending(doc_excerpts.read_worktree)
    still = _unmarked_lines(doc_excerpts.read_worktree)
    kept = {doc: [line for line in still.get(doc, []) if line in current.get(doc, set())]
            for doc in DOCS}
    removed = sum(len(v) for v in current.values()) - sum(len(v) for v in kept.values())
    _write_pending(kept)
    print(f"removed {removed} entries; {sum(len(v) for v in kept.values())} remain")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--staged", action="store_true",
                        help="check the staged snapshot (pre-commit)")
    parser.add_argument("--list-unmarked", action="store_true",
                        help="print every number without a marker, pending or not")
    parser.add_argument("--init-pending", action="store_true",
                        help="create the pending list from the current documents (once)")
    parser.add_argument("--prune-pending", action="store_true",
                        help="remove pending entries that no longer apply; never adds")
    args = parser.parse_args(argv)
    if args.init_pending:
        return init_pending()
    if args.prune_pending:
        return prune_pending()
    read = doc_excerpts.read_staged if args.staged else doc_excerpts.read_worktree
    problems = check(read, list_unmarked=args.list_unmarked)
    if args.staged:
        problems += [f"{PENDING} may only shrink; this commit adds {entry}"
                     for entry in pending_additions()]
    for p in problems:
        print(f"doc-numbers: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
