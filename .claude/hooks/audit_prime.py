#!/usr/bin/env python3
"""Hand the AI coding agent the exhaustive-review procedure the moment it is
asked to find every problem, before it starts choosing where to look.

すべての問題点を洗い出すよう頼まれた時点で、どこを調べるかを選び始める前に、
網羅的な調査の手順を AI コーディングエージェントに渡す。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code. `.claude/settings.json` attaches it to the
`UserPromptSubmit` event; whatever it prints to stdout is added to the agent's
context for that turn.

このファイルは AFM 解析ソフトウェアの一部ではなく、本体から import されることも
ない。Claude Code の設定である。`.claude/settings.json` で `UserPromptSubmit`
イベントに登録してあり、標準出力に書いた内容がそのターンのエージェントの
コンテキストに加わる。

Why it exists
-------------
Asked to list the academic problems of the processing, the agent reviewed the
places it judged suspicious, delegated topics it chose to subagents, and
reported what came back. Nothing recorded what it had not examined: one
subagent's whole stage never reported and the report nearly went out without
it, and each repeat of the question surfaced problems the previous review had
not looked for. The procedure in `NOTE` makes the code, not the reviewer,
decide what is examined (`scripts/audit_ledger.py`), and
`audit_guard.py` refuses a report that does not state its coverage.

処理の学術的な問題点を挙げるよう頼まれたエージェントは、自分が怪しいと判断した
箇所を調べ、自分で選んだ話題をサブエージェントに割り振り、返ってきたものを
報告した。調べていない箇所の記録は無かった。あるサブエージェントの担当段階は
結果が返らず、報告はそれを欠いたまま出るところだった。同じ質問を繰り返すたびに、
前回が探していなかった問題が出てきた。`NOTE` の手順は、何を調べるかを調査者
ではなくコードに決めさせ（`scripts/audit_ledger.py`）、`audit_guard.py` は
調査範囲を書かない報告を止める。

Deliberately loose
------------------
`TOPIC_RE` matches broadly. A spurious match costs a paragraph of context; a
missed one costs another review that silently skips part of the software.

`TOPIC_RE` は広めに一致させる。空振りの代償はコンテキストが一段落増えるだけで、
取りこぼしの代償は、ソフトウェアの一部を黙って飛ばした調査がもう一度出ることで
ある。

Failure behaviour
-----------------
Fails open: any error exits 0 with no output.
異常時は必ず通す。エラーが起きても何も出力せず終了コード 0 で抜ける。
"""
import json
import re
import sys

TOPIC_RE = re.compile(
    r"洗い出|網羅|漏れなく|もれなく|総点検|点検|監査|棚卸"
    r"|問題点|問題が(ある|あれば|無い|ない)|欠陥|不具合|誤り|間違い|バグ"
    r"|レビュー|見落とし|検出漏れ"
    r"|exhaustive|audit|review|every (problem|issue|bug)|all (problems|issues|bugs)",
    re.IGNORECASE,
)

NOTE = (
    "[exhaustive-review] If this prompt asks you to find, list or check problems "
    "(or to confirm there are none), the review must be exhaustive, not a search "
    "of the places you judge suspicious. Follow this procedure (AGENTS.md, "
    "Editing Rules, exhaustive reviews):\n"
    "1. Fix the scope from the request before reading anything. 'The software' "
    "or 'the processing' means lib/, guis/, cli.py and Main.py with --outputs. "
    "Anything you leave out goes in --exclude PATH::REASON and is named in the "
    "report.\n"
    "2. Build the item list from the code: `.venv/Scripts/python.exe "
    "scripts/audit_ledger.py init NAME PATHS... --outputs --question \"...\"`. "
    "Tell the user the item count and an honest time estimate, then start.\n"
    "3. Examine every item. Take work from `audit_ledger.py todo NAME` (give "
    "subagents item ids, never topics). Mark each with `mark` and evidence a "
    "reader can open (path.py:123, or a script and its output under .tmp/). "
    "Mark UI-only code `na` with that reason, do not skip it. For each output "
    "item, check how it is computed, what it is invariant to, how it scales, "
    "what a between-group comparison of it concludes when only an irrelevant "
    "factor differs, and whether the documentation states what it is.\n"
    "4. A subagent's 'problem' is marked only after you have read the code or "
    "rerun the number yourself; a refuted one is marked ok with the refutation.\n"
    "5. Report from `audit_ledger.py report NAME` and include its coverage line "
    "('調査範囲: ...') verbatim. While items are unchecked, never write that the "
    "list is complete or that there are no problems. Close with `close` (or "
    "`close --incomplete REASON`).\n"
    "audit_guard.py blocks the end of a turn whose reply lacks the current "
    "coverage line while an audit is open."
)


def main() -> int:
    # Decode UTF-8 explicitly: a piped stdin on Windows decodes with cp932
    # otherwise and the Japanese terms never match.
    # UTF-8 として明示的に復号する。Windows のパイプ入力は cp932 で復号され、
    # 日本語の語が一致しなくなるため。
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return 0
    if TOPIC_RE.search(str(payload.get("prompt", ""))):
        sys.stdout.write(NOTE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
