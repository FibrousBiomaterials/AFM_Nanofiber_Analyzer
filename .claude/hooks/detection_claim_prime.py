#!/usr/bin/env python3
"""Warn the AI coding agent up front when a prompt is about detection results,
so the project's verification rule arrives before the answer is written.

検出結果に関する質問が来たとき、AI コーディングエージェントに先回りして注意を
渡す。回答が書かれてしまう前にプロジェクトの検証ルールを届けるのが狙い。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code, the AI coding agent used on this repository.
`.claude/settings.json` attaches it to the `UserPromptSubmit` event, which
fires the moment a message is sent and before the agent starts working. Claude
Code runs this file as a subprocess, passes the prompt as JSON on stdin, and
adds whatever it prints to stdout into the agent's context for that turn.

このファイルは AFM 解析ソフトウェアの一部ではない。本体から import されることも
ない。本リポジトリで使う AI コーディングエージェント Claude Code の設定である。

`.claude/settings.json` で `UserPromptSubmit` イベントに登録してある。
`UserPromptSubmit` は、ユーザーがメッセージを送った直後、エージェントが動き出す
前に発生する。Claude Code はこのファイルを別プロセスで実行し、標準入力から JSON
でプロンプトを渡す。標準出力に書いた内容は、そのターンのエージェントのコンテキス
トに追加される。

Why it exists
-------------
`AGENTS.md` §8.12 requires that any claim about what the analysis detected or
missed be checked against the rendered images before it is written.
`detection_claim_guard.py` enforces that at the end of a turn, but by then a
wrong answer has already been written and has to be retracted. This file is
the preventive half: when the prompt is on a detection or threshold topic
(`TOPIC_RE`), it injects `NOTE` so the rule is in context from the start.

`AGENTS.md` §8.12 は、何が検出できて何を見落としたかを述べる前に、画像を描画し
て確かめよと定めている。`detection_claim_guard.py` はこれをターンの終わりで
強制するが、その時点では誤った回答がもう書かれていて、撤回するしかない。

このファイルはその予防側である。プロンプトが検出や閾値の話題であれば
(`TOPIC_RE`)、`NOTE` を注入し、ターンの最初からルールをコンテキストに載せて
おく。

Deliberately loose in one direction
-----------------------------------
`TOPIC_RE` matches broadly, so it also fires on prompts that turn out not to
need the rule. That costs a few lines of context. Missing a prompt that did
need it costs a wrong published conclusion, so the match is kept loose on
purpose. Prompts that do not match produce no output at all.

空振りと取りこぼしのどちらを許すかは、意図的に片側へ倒してある。`TOPIC_RE` は
広めに書いてあるので、結果的にルールが要らなかったプロンプトでも発火する。
その代償はコンテキストが数行増えるだけである。逆に、本当に必要だったプロンプト
を取りこぼせば、誤った結論がそのまま世に出る。だから緩いままにしてある。
一致しなければ何も出力しない。

Failure behaviour
-----------------
Fails open: any error exits 0 with no output, so a broken hook can never stop a
prompt from being answered.

異常時は必ず通す (フェイルオープン)。エラーが起きても何も出力せず終了コード 0
で抜けるので、このフックが壊れて回答が止まることはない。

See also
--------
`detection_claim_guard.py` -- the Stop-side counterpart that blocks the turn if
the rule was ignored anyway.
`run_hook.sh` -- the launcher that picks a Python interpreter for both hooks.

`detection_claim_guard.py` — ルールが結局守られなかったとき、ターンの終わりで
止める Stop 側。
`run_hook.sh` — 両方のフックを起動し、使える Python を選ぶスクリプト。
"""
import json
import re
import sys

TOPIC_RE = re.compile(
    # Japanese
    r"二値化|閾値|しきい値|検出|マスク|ファイバー|繊維|骨格|スケルトン"
    r"|トラッキング|追跡|背景推定|セグメン|分割|漏れ|取りこぼ"
    # English / identifiers
    r"|binariz|threshold|detect|mask|fiber|fibre|skeleton|tracking|segment"
    r"|area_min|h_length|low_threshold|global_threshold|min_area|bg_method",
    re.IGNORECASE,
)

NOTE = (
    "[detection-claim guard] This prompt is on a detection/threshold topic. "
    "Before stating what the analysis detected or missed, or recommending any "
    "detection parameter value, render the relevant images and view them with "
    "Read. Statistics are not sufficient evidence here: a recovery-only metric "
    "always rewards a looser threshold, no pipeline stage is ground truth (the "
    "calibrated height image is), and an aggregate over a population whose "
    "composition changed is meaningless. Save PNGs under .tmp/ and Read them."
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = str(payload.get("prompt", ""))
    if TOPIC_RE.search(prompt):
        sys.stdout.write(NOTE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
