#!/usr/bin/env python3
"""Keep the AI coding agent from starting work when the user only asked a
question: the question is answered first, and nothing the user did not ask for
happens in that turn.

ユーザーが質問しただけのときに、AI コーディングエージェントが勝手に作業を始め
ないようにする。まず質問に答えさせ、頼まれていない作業はそのターンで行わせない。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code, the AI coding agent used on this repository.
`.claude/settings.json` attaches this one file to two events:

- `UserPromptSubmit` (a message was just sent): classify the message, record
  the result for this session, and tell the agent what the turn is for.
- `PreToolUse` (the agent is about to call a tool): in a question-only turn,
  deny every tool except read-only lookups.

このファイルは AFM 解析ソフトウェアの一部ではない。本体から import されることも
ない。本リポジトリで使う AI コーディングエージェント Claude Code の設定である。
`.claude/settings.json` でこの 1 ファイルを 2 つのイベントに登録してある。

- `UserPromptSubmit` (メッセージが送られた直後): メッセージを分類し、結果を
  セッションごとに記録し、このターンで何をすべきかをエージェントに伝える。
- `PreToolUse` (エージェントがツールを呼ぶ直前): 質問だけのターンでは、読み取り
  専用の参照以外のツールをすべて拒否する。

Why it exists
-------------
The user asked questions ("isn't this over-fitted?", "why not replace the
skeleton?") and the agent answered only after many tool calls of probes,
renders and prototypes. The answer came late, and the tokens went on work
nobody had asked for. The rule: when the user asks a question, answer it
first; start work only when asked.

ユーザーが質問した (「過剰適応では？」「なぜ置き換えない？」) のに、エージェント
はプローブの実行、画像の描画、試作を何度も繰り返してから答えていた。回答は遅れ、
トークンは誰も頼んでいない作業に使われた。ルールは「質問されたらまず答える。
作業は頼まれてから始める」。

How a message is classified
---------------------------
- answer-only: a question (`QUESTION_RE`) with no explicit request for work
  (`WORK_RE`). Every tool outside `ALLOWED_TOOLS` is denied until the next
  message, except edits to the agent's own memory files.
- answer-first: a question plus an explicit request (「直して」「作成しろ」).
  Nothing is denied; the agent is told to answer before any tool call.
- anything else: no output, nothing denied.

- 回答のみ: 質問 (`QUESTION_RE`) があり、作業の明示的な依頼 (`WORK_RE`) が無い。
  次のメッセージまで `ALLOWED_TOOLS` 以外のツールを拒否する。エージェント自身の
  メモリファイルの編集だけは例外。
- 回答が先: 質問に加えて明示的な依頼 (「直して」「作成しろ」) がある。何も拒否
  しないが、ツールを呼ぶ前に回答するよう伝える。
- それ以外: 何も出力せず、何も拒否しない。

Ambiguity resolves toward answer-only. A Japanese te-form is both a request
(「直して」) and a plain conjunction (「解析して表示したが」), so it counts as a
request only at the end of a sentence or before ください/くれ/ほしい. Reading a
request as a question costs one confirmation; reading a question as a request
is the very failure this hook exists to stop.

曖昧なときは「回答のみ」に倒す。日本語のて形は依頼 (「直して」) にも単なる接続
(「解析して表示したが」) にもなるため、文末か ください/くれ/ほしい の前にあると
きだけ依頼とみなす。依頼を質問と読み違えても確認が 1 回増えるだけだが、質問を
依頼と読み違えるのは、まさにこのフックが防ぐべき失敗である。

Failure behaviour
-----------------
Fails open: any error exits 0 with no output, so a broken hook never denies a
tool. The per-session state lives in `.tmp/hook_state/` (git-ignored) and is
rewritten on every message.

異常時は必ず通す (フェイルオープン)。エラー時は何も出力せず終了コード 0 で抜け
るので、壊れたフックがツールを拒否することはない。セッションごとの状態は
`.tmp/hook_state/` (git 管理外) に置き、メッセージのたびに書き直す。

Testing and disabling
---------------------
Pipe a payload into it: `{"hook_event_name": "UserPromptSubmit",
"session_id": "t", "prompt": "..."}`, then `{"hook_event_name": "PreToolUse",
"session_id": "t", "tool_name": "Bash", "tool_input": {}}` and see whether a
deny decision is printed. To turn it off, delete its two entries from
`.claude/settings.json`.

手元で試すには上の JSON を順に標準入力へ流し、拒否の判定が出るかを見ればよい。
無効にするには `.claude/settings.json` から 2 つのエントリを消す。
"""
import json
import os
import re
import sys
import time

# Code, inline code and URLs can carry a "?" that is not a question.
# コード・インラインコード・URL の "?" は質問ではないので除いてから判定する。
_STRIP_RE = re.compile(r"```.*?```|`[^`\n]*`|https?://\S+", re.S)

QUESTION_RE = re.compile(
    r"[?？]"
    r"|なぜ|何故|なんで|どうして|どういうこと|どう思う|理由は"
    r"|教えて|説明して|説明しろ|ですか|ますか"
)

# A te-form is a request only at the end of a sentence or before a request
# auxiliary; elsewhere it joins clauses (「解析して表示したが」).
# て形は文末か依頼の補助語の前にあるときだけ依頼とみなす。それ以外は接続である。
_TE = r"(?=ください|下さい|くれ|ほしい|欲しい|もらえ|もらい|いただけ|頂け|[。．.!！\n]|\s*$)"
_END = r"(?=[。．.!！\n]|\s*$)"
_SURU = (
    r"(?:実装|作成|修正|追加|削除|変更|着手|実行|更新|反映|適用|コミット|プッシュ"
    r"|検証|確認|調査|試作|解析|再解析|描画|置換|導入|統合|復元|整理|テスト)"
)
WORK_RE = re.compile(
    _SURU + r"(?:して" + _TE + r"|しろ|せよ|を(?:お願い|頼む|進めて|始めて))"
    r"|(?:直|戻|消|回|試)(?:して" + _TE + r"|せ" + _END + r")"
    r"|(?:作|や)(?:って" + _TE + r"|れ" + _END + r")"
    r"|書(?:いて" + _TE + r"|け" + _END + r")"
    r"|(?:入れ|進め|続け|始め|置き換え|調べ|走らせ|止め|まとめ|見せ)(?:て" + _TE + r"|ろ)"
    r"|お願い|頼む|よろしく"
    r"|\b(?:go ahead|proceed|do it"
    r"|please (?:fix|add|change|update|run|implement|create|write|make))\b",
    re.IGNORECASE,
)

# Read-only lookups a short, accurate answer may genuinely need.
# 正確に短く答えるために本当に必要になり得る、読み取り専用の参照。
ALLOWED_TOOLS = {"Read", "Grep", "Glob", "AskUserQuestion", "ToolSearch", "ListAgents", "TaskOutput"}
MEMORY_EDIT_TOOLS = {"Edit", "Write"}

# A state file older than this is ignored, so a hook that failed to rewrite it
# on a later message cannot keep denying tools.
# これより古い状態ファイルは無視する。後のメッセージで書き直しに失敗しても、
# 拒否が続かないようにするため。
STATE_TTL_S = 6 * 3600
PRUNE_AFTER_S = 3 * 24 * 3600

NOTE_ANSWER_ONLY = (
    "[question-first] The user's message is a question and asks for no work. "
    "Answer it now, in text, from what you already know. Do not start work this "
    "turn: no edits, no commands, no probes, no subagents. Read, Grep and Glob "
    "are allowed only for a short lookup the answer genuinely needs; every other "
    "tool is denied until the user's next message. If a proper answer needs "
    "analysis you have not run, say so plainly instead of running it, and ask "
    "whether to proceed."
)
NOTE_ANSWER_FIRST = (
    "[question-first] The user's message asks a question and also requests "
    "work. Answer the question first, in text, before any tool call; then do "
    "only the work that was requested."
)
DENY_REASON = (
    "[question-first] {tool} denied: this turn answers a question and the user "
    "asked for no work. Answer in text now. If the answer needs work, describe "
    "it in one or two lines and ask whether to proceed. Allowed this turn: "
    "Read, Grep, Glob, AskUserQuestion, and edits to memory files."
)


def classify(prompt: str) -> str:
    """Return ``"answer_only"``, ``"answer_first"`` or ``"none"`` for a message.

    メッセージを ``"answer_only"``、``"answer_first"``、``"none"`` のいずれかに分類する。
    """
    text = _STRIP_RE.sub(" ", prompt or "")
    if not QUESTION_RE.search(text):
        return "none"
    return "answer_first" if WORK_RE.search(text) else "answer_only"


def _state_path(payload: dict) -> str:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:80]
    return os.path.join(root, ".tmp", "hook_state", f"question_first_{sid}.json")


def _prune(folder: str) -> None:
    now = time.time()
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.startswith("question_first_") and now - os.path.getmtime(path) > PRUNE_AFTER_S:
            os.remove(path)


def _is_memory_file(path: str) -> bool:
    p = str(path).replace("\\", "/").lower()
    return "/.claude/projects/" in p and "/memory/" in p


def on_prompt(payload: dict) -> None:
    mode = classify(str(payload.get("prompt", "")))
    path = _state_path(payload)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _prune(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"mode": mode, "time": time.time()}, fh)
    except OSError:
        # A stale answer-only state must not outlive a message it failed to
        # describe.
        # 書き直せなかった古い「回答のみ」の状態を残さない。
        try:
            os.remove(path)
        except OSError:
            pass
    if mode == "answer_only":
        sys.stdout.write(NOTE_ANSWER_ONLY)
    elif mode == "answer_first":
        sys.stdout.write(NOTE_ANSWER_FIRST)


def on_tool(payload: dict) -> None:
    try:
        with open(_state_path(payload), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return
    if state.get("mode") != "answer_only":
        return
    if time.time() - float(state.get("time", 0)) > STATE_TTL_S:
        return
    tool = str(payload.get("tool_name", ""))
    if tool in ALLOWED_TOOLS:
        return
    args = payload.get("tool_input") or {}
    if tool in MEMORY_EDIT_TOOLS and _is_memory_file(args.get("file_path", "")):
        return
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON.format(tool=tool),
    }}, sys.stdout)


def main() -> int:
    # Read bytes and decode UTF-8 explicitly: on Windows a piped stdin
    # otherwise decodes with the locale code page (cp932) and garbles Japanese.
    # バイト列で読み UTF-8 として明示的に復号する。Windows ではパイプの標準入力が
    # ロケールのコードページ (cp932) で復号され、日本語が化けるため。
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    event = payload.get("hook_event_name")
    if event == "PreToolUse" or (event is None and "tool_name" in payload):
        on_tool(payload)
    elif event == "UserPromptSubmit" or (event is None and "prompt" in payload):
        on_prompt(payload)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail open - a guard must never wedge the session.
        # 異常時は必ず通す。ガードがセッションを止めてしまっては本末転倒。
        sys.exit(0)
