#!/usr/bin/env python3
"""Stop the AI coding agent from finishing a turn in which it concluded what
the analysis detected without ever looking at a rendered image.

画像を一度も見ないまま「何が検出できたか」を結論づけた応答で、AI コーディング
エージェントが作業を終えられないようにする。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code, the AI coding agent used on this repository.
`.claude/settings.json` attaches it to the `Stop` event, which fires when the
agent is about to finish its turn and hand control back. Claude Code runs this
file as a subprocess, passes a JSON payload on stdin (including the path to
the session transcript), and reads the decision it prints to stdout.

このファイルは AFM 解析ソフトウェアの一部ではない。本体から import されることも
ない。本リポジトリで使う AI コーディングエージェント Claude Code の設定である。

`.claude/settings.json` で `Stop` イベントに登録してある。`Stop` は、エージェント
が 1 回の応答 (ターン) を終えて操作をユーザーに返そうとする直前に発生する。
Claude Code はこのファイルを別プロセスで実行し、標準入力から JSON を渡す。JSON
にはセッションの記録 (トランスクリプト) のパスが入っている。判定結果は標準出力
に書き、Claude Code がそれを読む。

Why it exists
-------------
`AGENTS.md` §8.12 requires that any claim about what the analysis detected or
missed -- and any recommended detection parameter -- be checked against the
rendered images before it is written. Statistics alone are not evidence: a
metric counting recovered targets always improves as a threshold loosens, and
no pipeline stage is ground truth. That rule was broken twice by concluding
from numbers alone, and both conclusions were wrong. The failure was never
disagreement with the rule; it was not noticing that the rule applied. So this
file checks mechanically instead of relying on the agent to remember.

`AGENTS.md` §8.12 は、何が検出できて何を見落としたかを述べるとき、また検出
パラメータの推奨値を出すときは、書く前に必ず画像を描画して確かめよと定めて
いる。

数値だけでは根拠にならない。検出できた数だけを数える指標は、閾値を緩めれば必ず
良くなる。パイプラインの途中の出力も、どれ一つとして正解ではない。

このルールは過去に 2 回破られ、いずれも結論が誤っていた。原因はルールに納得して
いなかったからではなく、いままさにルールが効く場面だと気づかなかったことにある。
そのため、エージェントが覚えていることを当てにせず、機械的に確かめる。

How it decides
--------------
It reads the transcript named in the payload and examines the last few human
turns (`HUMAN_TURN_WINDOW`):

1. A Bash command matching `ANALYSIS_RE` means detection numbers were computed.
2. A `Read` of an image file means the pictures were actually looked at.
3. If 1 happened and 2 has not happened since, the turn is blocked.

Commands matching `TOOLING_RE` are ignored, because maintaining this hook
means handling its own vocabulary.

JSON で渡されたトランスクリプトを読み、直近数回のユーザー発言以降
(`HUMAN_TURN_WINDOW`) を対象に、次の順で判定する。

1. `ANALYSIS_RE` に一致する Bash コマンドがあれば、検出に関する数値を計算した
   とみなす。
2. 画像ファイルの `Read` があれば、実際に画像を見たとみなす。
3. 1 があり、その後に 2 がなければブロックする。

`TOOLING_RE` に一致するコマンドは数えない。このフック自体を直す作業では、
ガードが探している単語を自分で打ち込むことになり、自分に反応してしまうため。

What happens when it blocks
---------------------------
It prints `{"decision": "block", ...}` and exits 0. Claude Code then refuses to
end the turn and feeds `REASON` back to the agent, which must render and view
the images -- or state explicitly that the turn makes no detection claim --
before it can finish. `stop_hook_active` suppresses a second consecutive block,
so this cannot loop.

`{"decision": "block", ...}` を出力し、終了コード 0 で終わる。すると Claude Code
はターンの終了を認めず、`REASON` の文面をエージェントに突き返す。エージェントは
画像を描画して確かめるか、「このターンは検出について何も主張していない」と明言
するまで終われない。`stop_hook_active` が立っているときはブロックしないので、
止まり続けることはない。

Failure behaviour
-----------------
Fails open. Every unexpected condition -- unreadable payload, missing
transcript, any exception -- exits 0 without blocking. A guard that wedges the
session is worse than one that occasionally misses.

異常時は必ず通す (フェイルオープン)。JSON が読めない、トランスクリプトが無い、
例外が出た — どの場合もブロックせず終了コード 0 で抜ける。たまに見逃すガード
より、セッションを止めてしまうガードのほうが害が大きいからである。

Testing and disabling
---------------------
Run it directly to try it: pipe
`{"stop_hook_active": false, "transcript_path": "<file>.jsonl"}` into it and
see whether a block decision is printed. To turn it off, delete its entry from
`.claude/settings.json`.

手元で試すには、`{"stop_hook_active": false, "transcript_path": "<file>.jsonl"}`
を標準入力に流し、ブロック判定が出るか見ればよい。無効にするには
`.claude/settings.json` から該当エントリを消す。

See also
--------
`detection_claim_prime.py` -- the preventive counterpart that injects the same
rule at the start of a turn instead of blocking at the end.
`run_hook.sh` -- the launcher that picks a Python interpreter for both hooks.

`detection_claim_prime.py` — 終わりで止めるのではなく、ターンの始めに同じルール
を渡しておく予防側。
`run_hook.sh` — 両方のフックを起動し、使える Python を選ぶスクリプト。
"""
import json
import os
import re
import sys

# Bash commands that mean "detection analysis was computed this turn".
# 検出解析を実行したと判断する Bash コマンドのパターン。
ANALYSIS_RE = re.compile(
    r"load_bundle|measure_bundle|load_tracking_image|fibers_in_image"
    r"|FiberTrackingImage|connect_fiber_fragments"
    r"|Segmenter|BGCalibrator|Skeletonizer|KinkDetector"
    r"|connectedComponents|threshold_local|skeletoniz|binariz"
    r"|\.b2z|process_file|cli\.py\s+(measure|process|heights|bgquality|bgcompare)",
    re.IGNORECASE,
)

IMAGE_RE = re.compile(r"\.(png|jpe?g|bmp|gif|webp|tiff?)\s*$", re.IGNORECASE)

# Commands that maintain this agent tooling rather than run the pipeline.
# Editing or testing the guard means handling its own vocabulary - the REASON
# text, ANALYSIS_RE itself, and payloads like {"prompt": "binarize ..."} - so
# without this exclusion the guard reliably fires on the turn that touches it.
# Nothing under .claude/ analyses AFM data, so the whole directory is exempt.
# Backslashes are normalised to "/" before matching, hence none in the pattern.
# 解析を走らせるのではなく、このフック自体を保守するコマンド。ガードを直したり
# テストしたりすると、REASON の文面や ANALYSIS_RE そのもの、
# {"prompt": "binarize ..."} のようなテスト用データを書くことになる。つまり
# ガードが探している単語を自分で打ち込むわけで、除外しないと自分に反応する。
# .claude/ の下に AFM データを解析するものは無いので、ディレクトリごと対象外に
# する。照合前にバックスラッシュを "/" に直すため、パターン側には要らない。
TOOLING_RE = re.compile(r"\.claude/")

# How many recent human turns the guard looks back over. See the comment in
# main() for why this is neither 1 (the current turn) nor the whole session.
# 何回分のユーザー発言まで遡って調べるか。1 (今のターンだけ) でもセッション全体
# でもない理由は main() 内のコメントを参照。
HUMAN_TURN_WINDOW = 3

REASON = (
    "STOP-HOOK: detection analysis ran this turn, but no rendered image was "
    "viewed.\n"
    "\n"
    "You computed statistics about what the pipeline detected (bundles, "
    "segmentation stages, fiber tracking) and did not Read a single image. "
    "Claims about what was detected or missed, and recommendations for "
    "detection parameters (global_threshold, area_min, h_length, "
    "low_threshold, min_area, ...), are NOT verified by numbers:\n"
    "  - a metric counting recovered targets improves monotonically as the "
    "threshold loosens unless it carries a false-positive term;\n"
    "  - no pipeline stage (BG mask, binarized mask, skeleton) is ground "
    "truth - the calibrated height image is;\n"
    "  - an aggregate over a population whose composition changed is "
    "meaningless.\n"
    "\n"
    "Before concluding: render the calibrated height image beside the stage "
    "outputs for the SAME crop, and/or overlay captured-vs-missed on the "
    "height image, save a PNG under .tmp/, and Read it. Then state the "
    "conclusion.\n"
    "\n"
    "If this turn genuinely makes no claim about detection results, say so "
    "explicitly in one sentence and finish."
)


def _blocks(msg):
    """Yield content blocks of a transcript message, tolerating shapes.

    トランスクリプトのメッセージから中身のブロックを取り出す。想定外の形が来て
    も例外にせず読み飛ばす。
    """
    content = (msg or {}).get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                yield block


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    # Never block twice in a row: prevents a stop/continue loop.
    # 二度続けてブロックしない。stop と continue が往復する無限ループを防ぐ。
    if payload.get("stop_hook_active"):
        return 0

    path = payload.get("transcript_path")
    if not path or not os.path.exists(path):
        return 0

    try:
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    except Exception:
        return 0

    # Window: the last HUMAN_TURN_WINDOW human turns, not the current turn and
    # not the whole session.
    # 調べる範囲は直近 HUMAN_TURN_WINDOW 回のユーザー発言以降。今のターンだけ
    # でもセッション全体でもない。
    #
    # Per-turn is too narrow - analysis is routinely launched in one turn (often
    # backgrounded) and concluded on in a later one after a task notification.
    # Replayed against the transcript where the wrong recommendation was
    # actually made, a per-turn window did not fire.
    # ターン単位では狭すぎる。解析はあるターンで (多くはバックグラウンドで)
    # 動かし、完了通知を受けた次のターンで結論を書くことが多い。実際に誤った
    # 推奨をしたときのトランスクリプトで試すと、ターン単位では発火しなかった。
    #
    # Whole-session is too wide - a single false positive (an analysis marker
    # appearing inside a heredoc that merely *writes* a file) sets the marker
    # permanently, and the guard then blocks every subsequent turn until an
    # image happens to be read. That was observed in practice.
    # セッション全体では広すぎる。誤検知が一度でも起きると (ファイルを書くだけ
    # の heredoc に解析用の単語が入っていた場合など) フラグが立ちっぱなしになり、
    # たまたま画像を読むまで以後のターンが全部ブロックされる。実際にそうなった。
    #
    # A few human turns is the compromise: long enough to span launch-then-
    # conclude, short enough that a false positive expires on its own.
    # 数ターンという幅が折衷案。解析の開始から結論までをまたげる長さがあり、
    # 誤検知が自然に流れて消える程度には短い。
    human_turns = []
    for i, row in enumerate(rows):
        if row.get("type") != "user":
            continue
        blocks = list(_blocks(row.get("message")))
        if any(b.get("type") == "text" for b in blocks):
            human_turns.append(i)
    start = human_turns[-HUMAN_TURN_WINDOW] if len(human_turns) >= HUMAN_TURN_WINDOW else 0

    # Within the window, the condition that matters is "numbers computed,
    # pictures not looked at since".
    # この範囲の中で見るのは「数値は出したが、その後に画像を見ていない」という
    # 状態だけ。
    last_analysis = -1
    last_image = -1
    for i, row in enumerate(rows[start:], start):
        if row.get("type") != "assistant":
            continue
        for block in _blocks(row.get("message")):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            args = block.get("input") or {}
            if name == "Read":
                if IMAGE_RE.search(str(args.get("file_path", ""))):
                    last_image = i
            elif name == "Bash":
                cmd = str(args.get("command", "")).replace("\\", "/")
                if not TOOLING_RE.search(cmd) and ANALYSIS_RE.search(cmd):
                    last_analysis = i

    if last_analysis >= 0 and last_image < last_analysis:
        json.dump({"decision": "block", "reason": REASON}, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail open - a guard must never wedge the session.
        # 異常時は必ず通す。ガードがセッションを止めてしまっては本末転倒。
        sys.exit(0)
