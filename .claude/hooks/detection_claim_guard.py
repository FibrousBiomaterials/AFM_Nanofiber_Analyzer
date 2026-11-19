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

1. A Bash or PowerShell command that runs Python with `ANALYSIS_RE` in it, or
   in a `.py` file it runs, means detection numbers were computed
   (`runs_analysis`). A command that only mentions those words (`ls`, `git`,
   `grep`) computes nothing and does not count, nor does a pytest run, which
   reports pass or fail rather than detection numbers, a tool run on a file
   (`python -m ruff check FILE`), or a repository checking script
   (`CHECKER_RE`). In a `.py` file only the code is searched: words inside its
   strings and comments do not count (`_code_only`).
2. A `Read` of an image file means the pictures were actually looked at.
3. If 1 happened and 2 has not happened since, the turn is blocked, once per
   analysis command: the next turns in the window are not blocked again for
   the same command.

Commands matching `TOOLING_RE` are ignored, because maintaining this hook
means handling its own vocabulary.

JSON で渡されたトランスクリプトを読み、直近数回のユーザー発言以降
(`HUMAN_TURN_WINDOW`) を対象に、次の順で判定する。

1. Python を実行し、コマンドそのもの、または実行する `.py` ファイルに
   `ANALYSIS_RE` を含む Bash・PowerShell のコマンドがあれば、検出に関する数値を
   計算したとみなす（`runs_analysis`）。その語に触れるだけのコマンド（`ls`・
   `git`・`grep`）は何も計算しておらず、数えない。pytest の実行も、検出の数値
   ではなく合否を出すだけなので数えない。ファイルに対するツールの実行
   （`python -m ruff check FILE`）と、リポジトリの検査スクリプト（`CHECKER_RE`）
   も数えない。`.py` ファイルではコードだけを探し、文字列とコメントの中の語は
   数えない（`_code_only`）。
2. 画像ファイルの `Read` があれば、実際に画像を見たとみなす。
3. 1 があり、その後に 2 がなければブロックする。止めるのは解析コマンド 1 つに
   つき 1 回で、窓の中の以後のターンを同じコマンドで再び止めることはしない。

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

# A command counts only when it runs Python: a mention of `.b2z` or
# `measure_bundle` in `ls`, `git` or `grep` computes nothing, and counting such
# mentions blocked turns that made no claim at all.
# Python を実行するコマンドだけを数える。`ls`・`git`・`grep` の中で `.b2z` や
# `measure_bundle` に触れても何も計算しておらず、そうした言及を数えると、何も
# 主張していないターンまで止めていた。
PYTHON_RE = re.compile(r"(?:^|[\s/\\])(?:python[\d.]*|py)(?:\.exe)?(?=\s|$)", re.IGNORECASE)

# Repository scripts that check documents, rules or records and name the
# analysis symbols only as text to compare (`check_gui04_docs.WATCHED_SYMBOLS`,
# the audit ledger's item list); running one computes no detection number.
# 文書・規則・記録を検査するリポジトリのスクリプト。解析のシンボルは比べる文字列
# として名指すだけで（`check_gui04_docs.WATCHED_SYMBOLS`、監査台帳の項目一覧）、
# 実行しても検出の数値は出さない。
CHECKER_RE = re.compile(r"(?:^|/)scripts/(?:check_\w+|audit_ledger|doc_excerpts|trash)\.py$")

# A pytest run checks the code against assertions and reports pass or fail; it
# gives the agent no detection numbers to conclude from. Its test files name
# the analysis on every page, so a run of one GUI test read as an analysis
# run. The segments of a command that run pytest are dropped before the check.
# pytest の実行はコードをアサーションと照らして合否を出すだけで、エージェントが
# 結論を引き出す検出の数値は出さない。テストファイルはどこにでも解析の語を含む
# ため、GUI のテストを 1 件走らせただけで解析の実行と数えられていた。コマンドの
# うち pytest を実行する区切りは、判定の前に取り除く。
PYTEST_RE = re.compile(r"(?:-m\s+pytest|(?:^|[\s/\\])pytest(?:\.exe)?)(?=\s|$)", re.IGNORECASE)
SEGMENT_RE = re.compile(r"&&|\|\||;|\n")

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


def runs_analysis(cmd: str, root: str) -> bool:
    """Whether a command runs Python on the analysis.

    コマンドが解析に対して Python を実行するかどうか。

    The analysis terms are looked for in the command itself (an inline script
    or a heredoc) and in every ``.py`` file it names that exists, since a
    script run from a file shows none of them on its command line.
    解析の語は、コマンドそのもの（インラインのスクリプトや heredoc）と、コマンドが
    名指す既存の ``.py`` ファイルの中で探す。ファイルから実行するスクリプトは、
    コマンド行にはその語を一つも見せないためである。

    Segments that run pytest are left out first (`PYTEST_RE`). A ``.py`` file
    is read only when it is the script Python runs -- the first argument after
    the interpreter -- because a tool run as ``python -m ruff check FILE`` only
    reads the file it names, and that file of the GUI names the analysis
    throughout. ``python -m MODULE`` runs a tool, not the analysis, unless the
    module is a file of this repository.
    最初に pytest を実行する区切りを除く（`PYTEST_RE`）。``.py`` ファイルの中を
    見るのは、それが Python の実行するスクリプト、すなわちインタプリタの直後の
    引数であるときだけにする。``python -m ruff check FILE`` のようなツールは名指す
    ファイルを読むだけで、GUI のファイルはどこにでも解析の語を含むためである。
    ``python -m MODULE`` はツールの実行であり、解析ではない。ただしそのモジュールが
    このリポジトリのファイルなら、その中を見る。
    """
    cmd = "\n".join(seg for seg in SEGMENT_RE.split(cmd) if not PYTEST_RE.search(seg))
    if TOOLING_RE.search(cmd) or not PYTHON_RE.search(cmd):
        return False
    for seg in SEGMENT_RE.split(cmd):
        match = PYTHON_RE.search(seg)
        if not match:
            continue
        args = seg[match.end():].split()
        # Interpreter options such as -I or -u come before what is run.
        # -I や -u のようなインタプリタのオプションは、実行対象の前に来る。
        while args and args[0].startswith("-") and args[0] not in ("-", "-c", "-m"):
            args.pop(0)
        if not args or args[0] in ("-", "-c") or args[0].startswith("<"):
            # An inline script or a heredoc: the analysis is in the command.
            # インラインのスクリプトか heredoc。解析の語はコマンドの中にある。
            if ANALYSIS_RE.search(cmd):
                return True
            continue
        if args[0] == "-m":
            if len(args) < 2:
                continue
            name = args[1].replace(".", "/") + ".py"
        else:
            name = args[0].strip("\"'")
        if not name.endswith(".py") or CHECKER_RE.search(name):
            continue
        path = name if os.path.isabs(name) else os.path.join(root, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                if ANALYSIS_RE.search(_code_only(fh.read())):
                    return True
        except OSError:
            continue
    return False


def _code_only(source: str) -> str:
    """Return a script's code with its strings and comments removed.

    スクリプトから文字列とコメントを除いたコードを返す。

    A script that writes findings or replacement text names the analysis in its
    strings without calling it, and an audit script that only marked a ledger
    read as an analysis run. A call such as ``measure.measure_bundle(...)`` is
    code and stays. A file that does not tokenize is returned whole, so a
    broken script still counts.
    所見や置き換え文字列を書くスクリプトは、解析を呼ばずに文字列の中で名指す。
    台帳に記録するだけの監査用スクリプトが、解析の実行と読まれていた。
    ``measure.measure_bundle(...)`` のような呼び出しはコードなので残る。字句解析
    できないファイルは丸ごと返し、壊れたスクリプトも数える。
    """
    import io
    import tokenize

    dropped = {tokenize.STRING, tokenize.COMMENT}
    # Python 3.12 splits f-strings into parts; their text is string too.
    # Python 3.12 は f 文字列を部分に分ける。その文字も文字列である。
    dropped |= {getattr(tokenize, n) for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")
                if hasattr(tokenize, n)}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return source
    return " ".join(t.string for t in tokens if t.type not in dropped)


def _state_path(payload: dict, root: str) -> str:
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:80]
    return os.path.join(root, ".tmp", "hook_state", f"detection_claim_guard_{sid}.json")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."

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
            elif name in ("Bash", "PowerShell"):
                cmd = str(args.get("command", "")).replace("\\", "/")
                if runs_analysis(cmd, root):
                    last_analysis = i

    if last_analysis < 0 or last_image >= last_analysis:
        return 0
    # Block once per analysis command: the agent has answered it (rendered an
    # image or said it claims nothing), and asking again at the end of every
    # later turn in the window repeated the same sentence each time.
    # 解析コマンド 1 つにつき 1 回だけ止める。エージェントはもう答えて（画像を
    # 描いたか、何も主張していないと述べて）おり、窓の中の以後のターンの終わりで
    # 毎回問い直すと、同じ一文を毎回繰り返させていた。
    state = _state_path(payload, root)
    try:
        with open(state, encoding="utf-8") as fh:
            if json.load(fh).get("blocked_at") == last_analysis:
                return 0
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(state), exist_ok=True)
        with open(state, "w", encoding="utf-8") as fh:
            json.dump({"blocked_at": last_analysis}, fh)
    except OSError:
        pass
    json.dump({"decision": "block", "reason": REASON}, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Fail open - a guard must never wedge the session.
        # 異常時は必ず通す。ガードがセッションを止めてしまっては本末転倒。
        sys.exit(0)
