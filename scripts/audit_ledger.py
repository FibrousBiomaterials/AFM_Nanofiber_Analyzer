#!/usr/bin/env python3
"""
Keep the ledger of an exhaustive review: every item in scope, and what was found for each.
網羅的な調査の台帳を管理する。調査範囲の全項目と、各項目で何が分かったかを記録する。

Why it exists
-------------
Asked to list every problem in the processing, an agent reviewed the places it
judged suspicious and reported what it found there. Nothing recorded which
parts it had not looked at, so the report read as complete while whole stages
were never examined, and every later review found problems the previous one
had not looked for. This script takes the choice of what to look at away from
the reviewer: the items come from the code, and a report states how many of
them were examined.
処理の問題点をすべて挙げるよう求められたエージェントは、自分が怪しいと判断した
箇所を調べ、そこで見つけたものを報告した。どこを調べていないかの記録が無かった
ため、段階ごと調べていないのに報告は完全に見え、次の調査のたびに前回が探して
いなかった問題が出てきた。このスクリプトは何を調べるかの選択を調査者から取り
上げる。項目はコードから作り、報告には何件を調べたかを書く。

Items
-----
- ``.py`` files: each top-level function, each method, each module-level and
  class-level assignment (constants, dataclass fields such as the
  ``ProcParams`` fields), and the remaining module-level statements as one
  ``<module>`` item. Nested functions belong to the item that contains them.
- ``.md`` files: each section, by heading.
- With ``--outputs``: every value a user can cite — GUI03 quantity per
  aggregation unit (and per frame mode for contour length), GUI03 between-group
  tests, GUI03 plot types, GUI04 fiber-table columns, fiber CSV columns, and
  ``.b2z`` bundle keys.

- ``.py`` ファイル: トップレベル関数、メソッド、モジュールとクラスの代入（定数、
  ``ProcParams`` のフィールドのようなデータクラスのフィールド）を 1 項目ずつ。残りの
  モジュールレベルの文はまとめて ``<module>`` の 1 項目にする。入れ子の関数は外側の
  項目に含める。
- ``.md`` ファイル: 見出しごとの節。
- ``--outputs`` を付けると、利用者が引用できる値をすべて加える。GUI03 の計測量と
  集計単位の組（輪郭長は枠の扱いごと）、GUI03 の群間検定、GUI03 の図の種類、GUI04
  のファイバー一覧の列、ファイバー CSV の列、``.b2z`` バンドルのキー。

Statuses
--------
``unchecked`` (initial), ``ok``, ``problem``, ``na`` (not applicable, with the
reason). ``ok`` and ``problem`` need evidence naming a location
(``path.py:123``) or a script under ``.tmp/``; ``problem`` also needs the
finding. An item whose code changed after it was marked reads as unchecked
again (``stale``).
``unchecked``（初期値）、``ok``、``problem``、``na``（対象外。理由が必要）。
``ok`` と ``problem`` には場所（``path.py:123``）か ``.tmp/`` 下のスクリプトを
示す根拠が要り、``problem`` には指摘内容も要る。記録後にコードが変わった項目は
未確認に戻る（``stale``）。

Usage
-----
``.venv/Scripts/python.exe scripts/audit_ledger.py init NAME PATH... [--outputs] [--exclude PATH::REASON] [--question TEXT]``
``... todo NAME [--file PATH] [--limit N]``
``... mark NAME ITEM_ID... --status ok|problem|na --evidence TEXT [--finding TEXT]``
``... mark NAME --json FILE`` (a list of ``{id, status, evidence, finding}``)
``... status NAME``
``... report NAME``
``... close NAME [--incomplete REASON]``

Ledgers live in ``.tmp/audit_ledgers/NAME/ledger.json``. ``.tmp/audit_ledgers/ACTIVE`` names
the open audit, which ``.claude/hooks/audit_guard.py`` reads.
台帳は ``.tmp/audit_ledgers/NAME/ledger.json`` に置く。``.tmp/audit_ledgers/ACTIVE`` は開いている
調査の名前を持ち、``.claude/hooks/audit_guard.py`` がそれを読む。
"""

from __future__ import annotations

# ===== Standard library =====
import argparse
import ast
import hashlib
import io
import json
import re
import sys
import textwrap
import time
import tokenize
from pathlib import Path
from typing import Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / ".tmp" / "audit_ledgers"
ACTIVE = AUDIT_DIR / "ACTIVE"

STATUSES = ("ok", "problem", "na")
# Evidence for ok/problem must point at something a reader can open.
# ok / problem の根拠は、読み手が開いて確かめられるものを指していなければならない。
LOCATION_RE = re.compile(r"[\w./\\-]+\.(py|md|json|txt|csv):\d+|\.tmp[/\\]\S+")


# ----------------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------------

def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _code_digest(lines: List[str], node: ast.AST) -> str:
    """
    Digest a definition's code tokens, so a comment or a blank line does not reset it.
    定義のコードのトークンからダイジェストを作る。コメントや空行では未確認に戻らない。
    """
    # Tokens rather than ast.dump: the hook that recounts the ledger may run on
    # another Python, and ast.dump's output differs between versions.
    # ast.dump ではなくトークンを使う。台帳を数え直すフックは別の Python で動く
    # ことがあり、ast.dump の出力は版によって異なるため。
    # Whole lines are sliced instead of ast.get_source_segment, which splits the
    # whole file again on every call.
    # ast.get_source_segment は呼ぶたびにファイル全体を分割し直すので、行単位で切り出す。
    segment = "".join(lines[node.lineno - 1:node.end_lineno])
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
    try:
        toks = [t.string for t in tokenize.generate_tokens(io.StringIO(textwrap.dedent(segment)).readline)
                if t.type not in skip]
    except (tokenize.TokenError, IndentationError):
        toks = [segment]
    return _digest(" ".join(toks))


def _python_items(path: Path) -> Iterator[Dict]:
    rel = _rel(path)
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    rest: List[ast.stmt] = []

    def item(symbol: str, node: ast.AST, kind: str) -> Dict:
        return {"id": f"{rel}::{symbol}", "kind": kind, "file": rel,
                "lines": f"{node.lineno}-{node.end_lineno}",
                "digest": _code_digest(lines, node)}

    def targets(node: ast.stmt) -> List[str]:
        if isinstance(node, ast.Assign):
            return [t.id for t in node.targets if isinstance(t, ast.Name)]
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return [node.target.id]
        return []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield item(node.name, node, "function")
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item(f"{node.name}.{sub.name}", sub, "method")
                else:
                    for name in targets(sub):
                        yield item(f"{node.name}.{name}", sub, "class constant")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
              and isinstance(node.value.value, str)):
            continue  # docstring
        elif targets(node):
            for name in targets(node):
                yield item(name, node, "constant")
        else:
            rest.append(node)
    if rest:
        yield {"id": f"{rel}::<module>", "kind": "module code", "file": rel,
               "lines": ",".join(f"{n.lineno}-{n.end_lineno}" for n in rest),
               "digest": _digest("".join(_code_digest(lines, n) for n in rest))}


def _markdown_items(path: Path) -> Iterator[Dict]:
    rel = _rel(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"#{1,6} ", ln)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        title = lines[s].lstrip("#").strip() if lines[s].startswith("#") else "<preamble>"
        yield {"id": f"{rel}::{s + 1}:{title}", "kind": "section", "file": rel,
               "lines": f"{s + 1}-{e}", "digest": _digest("\n".join(lines[s:e]))}


def _output_items() -> Iterator[Dict]:
    """
    List the values a user can cite, read from the code that produces them.
    利用者が引用できる値を、それを作るコードから読み取って列挙する。
    """
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib

    g3 = importlib.import_module("guis.GUI03_Fiber_Morphology_Statistics")
    from lib import bundle_schema, measure
    import check_gui04_docs

    def out(name: str, kind: str) -> Dict:
        return {"id": f"output::{name}", "kind": kind, "file": "", "lines": "", "digest": ""}

    for param in g3.PARAM_ORDER:
        # Frame modes change contour length's samples and weights, so each is
        # its own output, for the summary and for the test alike.
        # 枠の扱いは輪郭長の標本と重みを変えるので、要約でも検定でも別の出力とする。
        frames = [f"/{f}" for f in g3.FRAME_MODES] if param == g3.PARAM_LENGTH else [""]
        for unit in g3.PARAM_SPECS[param]["units"]:
            for frame in frames:
                yield out(f"GUI03/{param}/{unit}{frame}", "GUI03 summary")
                if unit in g3.TESTABLE_UNITS:
                    yield out(f"GUI03/test/{param}/{unit}{frame}", "GUI03 group test")
    for plot in g3.PLOT_TYPES:
        yield out(f"GUI03/plot/{plot}", "GUI03 figure")
    columns = check_gui04_docs.table_columns()
    if not columns:
        raise SystemExit("could not read GUI04's fiber-table columns; fix "
                         "check_gui04_docs.table_columns before auditing outputs")
    for col in columns:
        yield out(f"GUI04/{col}", "GUI04 column")
    for col in measure.FIBER_CSV_COLUMNS:
        yield out(f"CSV/{col}", "fiber CSV column")
    for key in list(bundle_schema.REQUIRED_BUNDLE_KEYS) + list(bundle_schema.OPTIONAL_BUNDLE_KEYS):
        yield out(f"bundle/{key}", "bundle key")


def inventory(paths: List[str], outputs: bool) -> List[Dict]:
    """
    Build the item list for the given files and folders.
    指定したファイルとフォルダから項目一覧を作る。
    """
    files: List[Path] = []
    for p in paths:
        path = (ROOT / p).resolve()
        if path.is_dir():
            files += sorted(f for f in path.rglob("*")
                            if f.suffix in (".py", ".md") and "__pycache__" not in f.parts)
        elif path.is_file():
            files.append(path)
        else:
            raise SystemExit(f"no such path: {p}")
    items: List[Dict] = []
    for f in files:
        items += list(_python_items(f) if f.suffix == ".py" else _markdown_items(f))
    if outputs:
        items += list(_output_items())
    seen = set()
    for it in items:
        if it["id"] in seen:
            # A name assigned twice at module level is one item.
            # モジュールで 2 回代入された名前は 1 項目にまとめる。
            it["id"] += f"@{it['lines']}"
        seen.add(it["id"])
        it.update(status="unchecked", evidence="", finding="", marked_digest="")
    return items


# ----------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------

def ledger_path(name: str) -> Path:
    return AUDIT_DIR / name / "ledger.json"


def load(name: str) -> Dict:
    p = ledger_path(name)
    if not p.exists():
        raise SystemExit(f"no ledger named {name!r}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(name: str, ledger: Dict) -> None:
    p = ledger_path(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def current_digests(ledger: Dict) -> Dict[str, str]:
    """
    Recompute every code item's digest, so an item changed after marking reads as unchecked.
    コード項目のダイジェストを計算し直す。記録後に変わった項目を未確認として扱うため。
    """
    files = sorted({it["file"] for it in ledger["items"] if it["file"]})
    now: Dict[str, str] = {}
    for f in files:
        path = ROOT / f
        if not path.exists():
            continue
        found = _python_items(path) if path.suffix == ".py" else _markdown_items(path)
        for it in found:
            now[it["id"]] = it["digest"]
    return now


def effective_status(item: Dict, now: Dict[str, str]) -> str:
    if item["status"] == "unchecked":
        return "unchecked"
    if item["file"] and item["status"] != "na" and now.get(item["id"]) != item["marked_digest"]:
        return "stale"
    return item["status"]


def counts(ledger: Dict) -> Dict[str, int]:
    now = current_digests(ledger)
    c = {"total": len(ledger["items"]), "ok": 0, "problem": 0, "na": 0, "unchecked": 0, "stale": 0}
    for it in ledger["items"]:
        c[effective_status(it, now)] += 1
    return c


def coverage_line(ledger: Dict, c: Optional[Dict[str, int]] = None) -> str:
    """
    The one line every report of this audit must carry, built from the ledger as it is now.
    この調査の報告に必ず載せる 1 行。現時点の台帳から作る。
    """
    c = c or counts(ledger)
    done = c["ok"] + c["problem"] + c["na"]
    left = c["unchecked"] + c["stale"]
    return (f"調査範囲: 対象 {c['total']} 件中 確認済み {done} 件"
            f"（問題あり {c['problem']}、問題なし {c['ok']}、対象外 {c['na']}）、"
            f"未確認 {left} 件")


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def cmd_init(a: argparse.Namespace) -> None:
    if ledger_path(a.name).exists() and not a.force:
        raise SystemExit(f"ledger {a.name!r} exists; pass --force to rebuild it")
    excluded = []
    for e in a.exclude or []:
        path, _, reason = e.partition("::")
        if not reason.strip():
            raise SystemExit(f"--exclude needs PATH::REASON, got {e!r}")
        excluded.append({"path": path, "reason": reason.strip()})
    ledger = {"name": a.name, "question": a.question or "", "scope": a.paths,
              "outputs": a.outputs, "excluded": excluded, "closed": False,
              "created": time.strftime("%Y-%m-%d %H:%M"), "items": inventory(a.paths, a.outputs)}
    ledger_path(a.name).parent.mkdir(parents=True, exist_ok=True)
    save(a.name, ledger)
    ACTIVE.write_text(a.name, encoding="utf-8")
    by_kind: Dict[str, int] = {}
    for it in ledger["items"]:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    print(f"{len(ledger['items'])} items: " + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    for e in excluded:
        print(f"excluded: {e['path']} ({e['reason']})")
    print(coverage_line(ledger))


def cmd_todo(a: argparse.Namespace) -> None:
    ledger = load(a.name)
    now = current_digests(ledger)
    shown = 0
    for it in ledger["items"]:
        st = effective_status(it, now)
        if st not in ("unchecked", "stale"):
            continue
        if a.file and it["file"] != a.file.replace("\\", "/"):
            continue
        print(f"{it['id']}\t{it['kind']}\t{it['lines']}\t{st}")
        shown += 1
        if a.limit and shown >= a.limit:
            break


def _apply(ledger: Dict, now: Dict[str, str], ids: List[str], status: str,
           evidence: str, finding: str) -> None:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    if not evidence.strip():
        raise SystemExit("evidence is required")
    if status in ("ok", "problem") and not LOCATION_RE.search(evidence):
        raise SystemExit("evidence for ok/problem must name a location (path.py:123) "
                         "or a script/output under .tmp/: " + evidence[:120])
    if status == "problem" and not finding.strip():
        raise SystemExit("a problem needs --finding")
    index = {it["id"]: it for it in ledger["items"]}
    missing = [i for i in ids if i not in index]
    if missing:
        raise SystemExit("unknown item ids: " + ", ".join(missing[:10]))
    for i in ids:
        it = index[i]
        it.update(status=status, evidence=evidence, finding=finding,
                  marked_digest=now.get(i, ""), marked=time.strftime("%Y-%m-%d %H:%M"))


def cmd_mark(a: argparse.Namespace) -> None:
    ledger = load(a.name)
    now = current_digests(ledger)
    if a.json:
        entries = json.loads(Path(a.json).read_text(encoding="utf-8"))
        for e in entries:
            _apply(ledger, now, [e["id"]], e["status"], e.get("evidence", ""), e.get("finding", ""))
    else:
        if not a.ids or not a.status:
            raise SystemExit("give item ids and --status, or --json FILE")
        _apply(ledger, now, a.ids, a.status, a.evidence or "", a.finding or "")
    save(a.name, ledger)
    print(coverage_line(ledger))


def cmd_status(a: argparse.Namespace) -> None:
    ledger = load(a.name)
    now = current_digests(ledger)
    per_file: Dict[str, List[int]] = {}
    for it in ledger["items"]:
        key = it["file"] or "outputs"
        row = per_file.setdefault(key, [0, 0])
        row[0] += 1
        if effective_status(it, now) not in ("unchecked", "stale"):
            row[1] += 1
    for f, (total, done) in sorted(per_file.items()):
        if done < total:
            print(f"  {f}: {done}/{total}")
    for e in ledger["excluded"]:
        print(f"excluded: {e['path']} ({e['reason']})")
    print(coverage_line(ledger))


def cmd_report(a: argparse.Namespace) -> None:
    ledger = load(a.name)
    now = current_digests(ledger)
    for it in ledger["items"]:
        if effective_status(it, now) == "problem":
            print(f"- {it['id']}: {it['finding']}\n    根拠: {it['evidence']}")
    for e in ledger["excluded"]:
        print(f"範囲外: {e['path']}（{e['reason']}）")
    print(coverage_line(ledger))


def cmd_close(a: argparse.Namespace) -> None:
    ledger = load(a.name)
    c = counts(ledger)
    left = c["unchecked"] + c["stale"]
    if left and not a.incomplete:
        raise SystemExit(f"{left} items are unchecked; finish them or close with "
                         "--incomplete REASON, and say so in the report")
    ledger["closed"] = True
    ledger["incomplete_reason"] = a.incomplete or ""
    save(a.name, ledger)
    print(coverage_line(ledger))
    if a.incomplete:
        print(f"未完了のまま終了: {a.incomplete}")


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("name")
    p.add_argument("paths", nargs="+")
    p.add_argument("--outputs", action="store_true")
    p.add_argument("--exclude", action="append")
    p.add_argument("--question")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("todo")
    p.add_argument("name")
    p.add_argument("--file")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("mark")
    p.add_argument("name")
    p.add_argument("ids", nargs="*")
    p.add_argument("--status")
    p.add_argument("--evidence")
    p.add_argument("--finding")
    p.add_argument("--json")
    for n in ("status", "report"):
        sub.add_parser(n).add_argument("name")
    p = sub.add_parser("close")
    p.add_argument("name")
    p.add_argument("--incomplete")
    a = ap.parse_args(argv)
    {"init": cmd_init, "todo": cmd_todo, "mark": cmd_mark, "status": cmd_status,
     "report": cmd_report, "close": cmd_close}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
