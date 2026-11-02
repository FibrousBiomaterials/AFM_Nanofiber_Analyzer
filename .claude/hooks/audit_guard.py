#!/usr/bin/env python3
"""Stop the AI coding agent from ending a turn of an open exhaustive review
without stating how much of the scope it has examined.

網羅的な調査が開いている間、調査範囲のどれだけを調べたかを書かずに AI コーディ
ングエージェントがターンを終えることを止める。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code. `.claude/settings.json` attaches it to the
`Stop` event, which fires when the agent is about to hand control back; it
prints `{"decision": "block", "reason": ...}` to refuse that.

このファイルは AFM 解析ソフトウェアの一部ではなく、本体から import されることも
ない。Claude Code の設定である。`.claude/settings.json` で `Stop` イベントに登録
してある。`Stop` はエージェントが操作を返そうとする直前に発生し、このファイルが
`{"decision": "block", "reason": ...}` を出力するとそれを拒む。

Why it exists
-------------
A review report that lists findings reads as complete whether it examined all
of the software or a tenth of it. `scripts/audit_ledger.py` records which items
were examined; this guard makes every reply of an open audit carry the
ledger's current coverage line, so the reader always sees how much is still
unexamined, and refuses a claim of completeness ("すべて洗い出した", "問題は
ありません") while items remain.

発見事項を並べた報告は、ソフトウェア全体を調べたものでも 1 割しか調べていない
ものでも、同じように完全に見える。`scripts/audit_ledger.py` はどの項目を調べたか
を記録する。このガードは、開いている調査のすべての応答に台帳の現在の調査範囲の
行を載せさせ、何が未確認かを読み手が常に見られるようにする。未確認の項目が残る
間は、完全だという主張（「すべて洗い出した」「問題はありません」）も止める。

How it decides
--------------
1. `.tmp/audit_ledgers/ACTIVE` names the open ledger; empty or missing means no audit.
2. The reply text of the current turn (everything the agent wrote after the
   last human message) must contain the ledger's coverage line exactly as
   `audit_ledger.coverage_line` builds it now, so a stale count fails too.
3. While items are unchecked, `COMPLETE_RE` must not match the reply.
4. Once the ledger is closed and a reply has carried its line, `ACTIVE` is
   emptied and the guard goes quiet.

1. `.tmp/audit_ledgers/ACTIVE` が開いている台帳の名前を持つ。空か無ければ調査は無い。
2. 現在のターンの応答（最後のユーザー発言より後にエージェントが書いた文）は、
   `audit_ledger.coverage_line` が今作る調査範囲の行をそのまま含まなければなら
   ない。古い件数のままでも通らない。
3. 未確認の項目がある間は、応答が `COMPLETE_RE` に一致してはならない。
4. 台帳を閉じ、その行を載せた応答が出たら `ACTIVE` を空にし、以後は何もしない。

Failure behaviour
-----------------
Fails open on any unexpected condition, and `stop_hook_active` suppresses a
second consecutive block so it cannot loop.
想定外の状態では必ず通す。`stop_hook_active` が立っていれば二度続けてブロック
しないので、止まり続けることはない。
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / ".tmp" / "audit_ledgers" / "ACTIVE"

COMPLETE_RE = re.compile(
    r"網羅(しました|的に調べ(まし)?た)|(すべて|全て|全部)(を)?洗い出(しました|した)"
    r"|漏れなく(調べ|洗い出)(ました|た)|これで(全部|すべて|全て)です|以上が(すべて|全て)"
    r"|問題は(ありません|ない|無い)(と|。|$)"
)


def _turn_text(rows):
    """Concatenate the agent's text after the last human message.

    最後のユーザー発言より後にエージェントが書いた文をつなげて返す。
    """
    last_human = -1
    for i, row in enumerate(rows):
        if row.get("type") != "user":
            continue
        content = (row.get("message") or {}).get("content")
        if isinstance(content, str) or (isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "text" for b in content)):
            last_human = i
    parts = []
    for row in rows[last_human + 1:]:
        if row.get("type") != "assistant":
            continue
        for b in (row.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text", "")))
    return "\n".join(parts)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        return 0
    if not ACTIVE.exists():
        return 0
    name = ACTIVE.read_text(encoding="utf-8").strip()
    if not name:
        return 0

    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_ledger

    ledger = audit_ledger.load(name)
    c = audit_ledger.counts(ledger)
    line = audit_ledger.coverage_line(ledger, c)
    left = c["unchecked"] + c["stale"]

    text = str(payload.get("last_assistant_message") or "")
    path = payload.get("transcript_path")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(ln) for ln in fh if ln.strip()]
        text = _turn_text(rows) + "\n" + text

    problems = []
    if line not in text:
        problems.append(
            "The reply does not carry the audit's current coverage line. Run "
            f"`.venv/Scripts/python.exe scripts/audit_ledger.py status {name}` and "
            f"include this line verbatim:\n  {line}")
    if left and COMPLETE_RE.search(text):
        problems.append(
            f"{left} items are still unchecked, but the reply claims completeness "
            f"(\"{COMPLETE_RE.search(text).group(0)}\"). Say what was examined and "
            "what was not, instead.")
    if problems:
        reason = (f"AUDIT-GUARD: exhaustive review {name!r} is open "
                  "(scripts/audit_ledger.py).\n" + "\n".join(problems))
        json.dump({"decision": "block", "reason": reason}, sys.stdout)
    elif ledger.get("closed"):
        ACTIVE.write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        # Fail open - a guard must never wedge the session (SystemExit from
        # audit_ledger.load included).
        # 異常時は必ず通す。audit_ledger.load の SystemExit も含む。
        sys.exit(0)
