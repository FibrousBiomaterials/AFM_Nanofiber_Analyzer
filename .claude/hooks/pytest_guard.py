#!/usr/bin/env python3
"""Keep the AI coding agent from starting a test run that fills the screen
with windows, or loads every CPU core, before the user has agreed to it.

AI コーディングエージェントが、画面をウィンドウで埋めたり全 CPU コアを使ったり
するテスト実行を、ユーザーの同意なしに始めないようにする。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code, the AI coding agent used on this repository.
`.claude/settings.json` attaches this one file to two events:

- `UserPromptSubmit` (a message was just sent): when the message contains the
  approval words, record one approval for this session.
- `PreToolUse` (the agent is about to run a shell command): deny a command that
  starts a test run needing approval, unless an approval is on record; an
  approval is used up by the run it lets through.

このファイルは AFM 解析ソフトウェアの一部ではない。本体から import されることも
ない。本リポジトリで使う AI コーディングエージェント Claude Code の設定である。
`.claude/settings.json` でこの 1 ファイルを 2 つのイベントに登録してある。

- `UserPromptSubmit` (メッセージが送られた直後): メッセージに承認の言葉があれば、
  このセッションの承認を 1 回ぶん記録する。
- `PreToolUse` (エージェントがシェルコマンドを実行する直前): 承認が要るテスト
  実行を始めるコマンドを、承認の記録が無ければ拒否する。承認は、通した実行
  1 回で使い切る。

Why it exists
-------------
`pytest` with no arguments runs the whole suite in parallel workers
(`addopts = ["-n", "auto", ...]` in `pyproject.toml`), and its GUI tests open
real windows on the screen of whoever is working at the PC. On 2026-11-17 the
agent changed the shared `tk_app` fixture and ran the whole suite first, in
the background and unannounced. The run hung on one test, the user reported
GUI02 windows left open in large numbers and unresponsive, and the PC was
powered off 41 minutes later. A note telling the agent to be careful does not
stop a run; this hook does. The rule itself is AGENTS.md section 8.19.

引数なしの `pytest` は、全テストを並列ワーカーで走らせる (`pyproject.toml` の
`addopts = ["-n", "auto", ...]`)。GUI のテストは、その PC で作業している人の画面に
実際のウィンドウを開く。2026-11-17、エージェントは共通フィクスチャ `tk_app` を
変更し、最初の実行を全テストで、裏で、予告なしに行った。実行は 1 件のテストで
止まり、ユーザーは GUI02 のウィンドウが大量に開いたまま操作を受け付けなくなった
と報告し、41 分後に PC の電源を切った。「気をつける」という覚え書きでは実行は
止まらない。このフックは止める。規則そのものは AGENTS.md §8.19 にある。

What needs approval
-------------------
A `pytest` command needs approval when

- it names no test file, or names a folder (the whole suite, or a whole folder);
- it runs tests of a file that opens windows while the parallel workers are on
  (no `-n 0`); or
- it runs more than `MAX_SERIAL_GUI_TESTS` tests of files that open windows,
  even one at a time.

A file counts as opening windows when its text matches `WINDOW_RE` (Tk, the
`tk_app` fixture, a plugin launch). A file that cannot be read counts too.
`check.py --pin` and `scripts/release.py prepare` without `--skip-checks` start
the whole suite themselves and need the same approval. A command that only
lists or describes tests (`--collect-only`, `--version`, ...) never does.

`pytest` のコマンドは、次のとき承認が要る。

- テストファイルを指定していない、またはフォルダを指定している (全テスト、
  またはフォルダ全体)。
- ウィンドウを開くファイルのテストを、並列ワーカーを切らずに (`-n 0` なしで)
  走らせる。
- ウィンドウを開くファイルのテストを、1 つずつであっても
  `MAX_SERIAL_GUI_TESTS` 件より多く走らせる。

ファイルの本文が `WINDOW_RE` (Tk、`tk_app` フィクスチャ、プラグインの起動) に
一致すれば、ウィンドウを開くファイルとみなす。読めないファイルも同じ扱いにする。
`check.py --pin` と、`--skip-checks` なしの `scripts/release.py prepare` は全テストを
自分で起動するので、同じ承認が要る。テストを列挙・説明するだけのコマンド
(`--collect-only`、`--version` など) は対象外。

How approval is given
---------------------
The user sends a message containing `テスト実行を許可` (or "allow the test
run"). Text inside quotation marks or code is ignored, so quoting this hook's
own message approves nothing. One message approves one run, within
`APPROVAL_TTL_S`. The agent cannot approve: the record is written only from the
user's message.

ユーザーが `テスト実行を許可` (または "allow the test run") を含むメッセージを
送る。引用符やコードの中の文字は無視するので、このフックのメッセージを引用しても
承認にはならない。1 通のメッセージで 1 回の実行を、`APPROVAL_TTL_S` 以内に限って
承認する。エージェントは承認できない。記録はユーザーのメッセージからしか
書かれない。

Limits
------
The hook reads the command line only. It does not see a test run started from
inside another script or with `python -c`, it counts test functions rather than
parametrized cases, and it covers Claude Code only: other agents and a person
at a terminal follow AGENTS.md section 8.19 without it.

フックが読むのはコマンドラインだけである。別のスクリプトの中や `python -c` から
始まるテスト実行は見えない。数えるのはテスト関数で、パラメータ化された個々の
ケースではない。また Claude Code にしか効かない。他のエージェントや端末の前の
人は、フックなしで AGENTS.md §8.19 に従う。

Failure behaviour
-----------------
A payload that cannot be read exits 0 with no output, so a broken hook never
blocks an unrelated command. Once a command is recognised as a test run,
anything the hook cannot work out counts as needing approval.

読めないペイロードには何も出力せず終了コード 0 で抜けるので、壊れたフックが
無関係なコマンドを止めることはない。テスト実行だと分かったコマンドについては、
フックが判断できない点はすべて「承認が要る」に倒す。

Testing and disabling
---------------------
Pipe a payload into it: `{"hook_event_name": "PreToolUse", "session_id": "t",
"tool_name": "Bash", "tool_input": {"command": "pytest"}}` prints a deny
decision; after `{"hook_event_name": "UserPromptSubmit", "session_id": "t",
"prompt": "テスト実行を許可"}` the same command prints nothing, once. To turn it
off, delete its two entries from `.claude/settings.json`.

手元で試すには上の JSON を標準入力へ流す。1 つ目は拒否の判定を出し、2 つ目の
後は同じコマンドに 1 回だけ何も出さない。無効にするには `.claude/settings.json`
から 2 つのエントリを消す。
"""
import glob
import json
import os
import re
import shlex
import sys
import time

GUARDED_TOOLS = {"Bash", "PowerShell"}

# More window-opening tests than this need approval even one at a time.
# ウィンドウを開くテストがこれより多いと、1 つずつ走らせる場合でも承認が要る。
MAX_SERIAL_GUI_TESTS = 30

APPROVAL_TTL_S = 30 * 60
PRUNE_AFTER_S = 3 * 24 * 3600

# Quoted text and code are removed before looking for the approval words, so a
# message that quotes this hook's own instruction approves nothing.
# 承認の言葉を探す前に、引用とコードを取り除く。このフック自身の指示文を引用した
# メッセージが承認にならないようにするため。
_QUOTED_RE = re.compile(
    r"```.*?```|`[^`\n]*`|「[^」]*」|『[^』]*』|\"[^\"\n]*\"|“[^”\n]*”", re.S
)
APPROVE_RE = re.compile(
    r"テスト(?:の)?実行を許可(?!\s*(?:しない|しません|するな|できない|しては))"
    r"|(?<!not )(?<!n't )(?<!never )\ballow (?:the )?test run\b",
    re.IGNORECASE,
)

# Text that marks a test file as one that opens windows. tkinter counts only
# where it is imported: a docstring that mentions it opens nothing.
# テストファイルが「ウィンドウを開く」ものであることを示す文字列。tkinter は
# import している場合だけ数える。docstring で触れているだけでは何も開かない。
WINDOW_RE = re.compile(
    r"\btk_app\b|^\s*(?:import|from)\s+tkinter\b|\bTk\(|\bToplevel\(|\brequires_tk\b"
    r"|\.App\(|run-plugin|launch_plugin",
    re.M,
)

_SEPARATOR_RE = re.compile(r"&&|\|\||[;|\n]")
_PYTHON_RE = re.compile(r"(?:python[\d.]*|py|pypy[\d.]*)(?:\.exe)?", re.IGNORECASE)
_PYTEST_RE = re.compile(r"(?:pytest|py\.test)(?:\.exe)?", re.IGNORECASE)
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
_DURATION_RE = re.compile(r"[\d.]+[smhd]?")
_REDIRECT_ALONE_RE = re.compile(r"(?:\d*|&)>>?|<")
_REDIRECT_JOINED_RE = re.compile(r"(?:(?:\d*|&)>>?|<)\S+")
# Words that may stand before a command without being the command.
# コマンドの前に置かれるが、コマンドそのものではない語。
_WRAPPERS = {"timeout", "time", "nice", "env", "&", "uv", "run", "poetry", "winpty"}

# pytest options whose value is the next argument, so it is not read as a test.
# 値を次の引数に取る pytest のオプション。その値をテストの指定と読まないため。
_VALUE_OPTIONS = {
    "-m", "-p", "-c", "-o", "-W", "-r", "--deselect", "--ignore",
    "--ignore-glob", "--rootdir", "--basetemp", "--junitxml", "--junit-xml",
    "--maxfail", "--tb", "--durations", "--durations-min", "--dist",
    "--maxprocesses", "--capture", "--color", "--confcutdir", "--import-mode",
    "--log-level", "--log-cli-level", "--log-file", "--override-ini",
    "--max-worker-restart", "--timeout", "--cov", "--cov-report",
}
# Options with which pytest lists or describes tests instead of running them.
# テストを走らせず、列挙や説明だけを行うオプション。
_NO_RUN_FLAGS = {
    "--collect-only", "--co", "--version", "-V", "--help", "-h", "--fixtures",
    "--markers",
}

NOTE_APPROVED = (
    "[pytest-guard] The user's message approves one test run that needs "
    "approval (AGENTS.md section 8.19): the next such command in this session, "
    "within 30 minutes. Run what you described to the user, nothing wider."
)
DENY_REASON = (
    "[pytest-guard] {tool} denied: this command starts a test run that needs "
    "the user's approval first (AGENTS.md section 8.19).\n{reasons}\n"
    "Runs that pass without approval: named test files that open no window; "
    "and at most {limit} tests of window-opening files with `-n 0`, so one "
    "window is open at a time. If the wider run is really needed, tell the "
    "user what will run, that windows will open, and roughly how long it "
    "takes, and ask them to send the words テスト実行を許可. Do not reword the "
    "command to get past this check."
)


def _basename(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1]


def _tokens(segment: str, tool: str) -> list:
    # PowerShell paths use backslashes, which a POSIX split would swallow as
    # escapes.
    # PowerShell のパスはバックスラッシュ区切りで、POSIX の分割ではエスケープと
    # して消えてしまう。
    if tool == "PowerShell":
        segment = segment.replace("\\", "/")
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _at_command_position(tokens: list, index: int) -> bool:
    """Return whether only wrappers, assignments and options precede a token.

    その語の前に、ラッパー・代入・オプションしか無いかどうかを返す。
    """
    for tok in tokens[:index]:
        if tok in _WRAPPERS or tok.startswith("-"):
            continue
        if _ENV_ASSIGN_RE.fullmatch(tok) or _DURATION_RE.fullmatch(tok):
            continue
        return False
    return True


def _python_before(tokens: list, index: int) -> bool:
    return any(_PYTHON_RE.fullmatch(_basename(tok)) for tok in tokens[:index])


def _pytest_args(tokens: list):
    """Return the arguments of a pytest invocation in ``tokens``, or ``None``.

    ``tokens`` の中の pytest 呼び出しの引数を返す。呼び出しが無ければ ``None``。
    """
    for i, tok in enumerate(tokens):
        if tok == "-m" and i + 1 < len(tokens) and tokens[i + 1] == "pytest":
            if _python_before(tokens, i):
                return tokens[i + 2:]
        if tok == "-mpytest" and _python_before(tokens, i):
            return tokens[i + 1:]
        if _PYTEST_RE.fullmatch(_basename(tok)) and _at_command_position(tokens, i):
            return tokens[i + 1:]
    return None


def _script_args(tokens: list, script: str):
    """Return the arguments given to a project script run as a command.

    コマンドとして実行されるプロジェクトのスクリプトに渡された引数を返す。
    """
    for i, tok in enumerate(tokens):
        if _basename(tok) != script:
            continue
        if _python_before(tokens, i) or _at_command_position(tokens, i):
            return tokens[i + 1:]
    return None


def _parse_pytest_args(args: list) -> tuple:
    """Split pytest arguments into test targets, serial flag and ``-k`` text.

    pytest の引数を、テストの指定・直列かどうか・``-k`` の式に分ける。
    """
    targets, serial, k_expr = [], False, None
    i = 0
    while i < len(args):
        arg = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if arg == "&":
            i += 1
        elif _REDIRECT_ALONE_RE.fullmatch(arg):
            i += 2
        elif _REDIRECT_JOINED_RE.fullmatch(arg):
            i += 1
        elif arg in ("-n", "--numprocesses"):
            # The last one given wins, as in pytest.
            # pytest と同じく、最後に指定されたものが有効。
            serial = nxt == "0"
            i += 2
        elif arg.startswith("--numprocesses="):
            serial = arg.split("=", 1)[1] == "0"
            i += 1
        elif re.fullmatch(r"-n\S+", arg):
            serial = arg[2:] == "0"
            i += 1
        elif arg == "-k":
            k_expr = nxt
            i += 2
        elif arg.startswith("-k") and len(arg) > 2:
            k_expr = arg[2:].lstrip("=")
            i += 1
        elif arg in _VALUE_OPTIONS:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            targets.append(arg)
            i += 1
    return targets, serial, k_expr


def _count_tests(text: str, k_expr) -> int:
    """Count the test functions of a file that a plain ``-k`` word keeps.

    ファイル中のテスト関数のうち、単純な ``-k`` の語で残るものを数える。
    """
    names = re.findall(r"^\s*(?:async\s+)?def\s+(test_\w*)", text, re.M)
    if k_expr and re.fullmatch(r"[\w\[\].-]+", k_expr) and k_expr not in ("and", "or", "not"):
        # pytest matches -k without regard to case.
        # pytest の -k は大文字と小文字を区別しない。
        names = [name for name in names if k_expr.lower() in name.lower()]
    return len(names)


def _read(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def pytest_reasons(args: list, root: str) -> list:
    """Return why a pytest invocation needs approval; empty when it does not.

    pytest の呼び出しに承認が要る理由を返す。要らなければ空。
    """
    if any(arg in _NO_RUN_FLAGS for arg in args):
        return []
    targets, serial, k_expr = _parse_pytest_args(args)
    if not targets:
        return ["- It names no test file, so the whole suite runs."]
    reasons = []
    gui_tests = 0
    for target in targets:
        path_part, _, node = target.partition("::")
        full = path_part if os.path.isabs(path_part) else os.path.join(root, path_part)
        if any(ch in path_part for ch in "*?["):
            files = sorted(glob.glob(full))
            if not files:
                reasons.append(f"- `{path_part}` matches no file, so what runs is unknown.")
                continue
        else:
            files = [full]
        for file_path in files:
            if os.path.isdir(file_path):
                reasons.append(f"- `{path_part}` is a folder, so every test in it runs.")
                continue
            text = _read(file_path)
            if text is None:
                reasons.append(f"- `{path_part}` cannot be read, so what runs is unknown.")
                continue
            if not WINDOW_RE.search(text):
                continue
            if not serial:
                reasons.append(
                    f"- `{path_part}` opens windows and the parallel workers "
                    "are on (no `-n 0`)."
                )
                continue
            gui_tests += 1 if node else _count_tests(text, k_expr)
    if gui_tests > MAX_SERIAL_GUI_TESTS:
        reasons.append(
            f"- It runs about {gui_tests} tests of files that open windows; "
            f"more than {MAX_SERIAL_GUI_TESTS} need approval even one at a time."
        )
    return reasons


def command_reasons(command: str, tool: str, root: str) -> list:
    """Return why a shell command needs approval; empty when it does not.

    シェルコマンドに承認が要る理由を返す。要らなければ空。
    """
    reasons = []
    for segment in _SEPARATOR_RE.split(command or ""):
        tokens = _tokens(segment, tool)
        if not tokens:
            continue
        args = _pytest_args(tokens)
        if args is not None:
            try:
                reasons.extend(pytest_reasons(args, root))
            except Exception:
                reasons.append("- The test command could not be analysed.")
            continue
        args = _script_args(tokens, "check.py")
        if args is not None and "--pin" in args:
            reasons.append("- `check.py --pin` runs the whole suite.")
        args = _script_args(tokens, "release.py")
        if args is not None and "prepare" in args and "--skip-checks" not in args:
            reasons.append(
                "- `release.py prepare` runs the whole suite unless "
                "`--skip-checks` is given."
            )
    return reasons


def _root(payload: dict) -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "."


def _state_path(payload: dict) -> str:
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:80]
    return os.path.join(_root(payload), ".tmp", "hook_state", f"pytest_guard_{sid}.json")


def _prune(folder: str) -> None:
    now = time.time()
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.startswith("pytest_guard_") and now - os.path.getmtime(path) > PRUNE_AFTER_S:
            os.remove(path)


def on_prompt(payload: dict) -> None:
    text = _QUOTED_RE.sub(" ", str(payload.get("prompt", "")))
    if not APPROVE_RE.search(text):
        return
    path = _state_path(payload)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _prune(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"approved_at": time.time()}, fh)
    except OSError:
        return
    sys.stdout.write(NOTE_APPROVED)


def _take_approval(payload: dict) -> bool:
    """Use up this session's approval; return whether one was on record.

    このセッションの承認を使い切る。記録があったかどうかを返す。
    """
    path = _state_path(payload)
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return False
    try:
        os.remove(path)
    except OSError:
        # An approval that cannot be used up must not approve every later run.
        # 使い切れない承認が、以後の実行すべてを通してしまわないようにする。
        return False
    return time.time() - float(state.get("approved_at", 0)) <= APPROVAL_TTL_S


def on_tool(payload: dict) -> None:
    tool = str(payload.get("tool_name", ""))
    if tool not in GUARDED_TOOLS:
        return
    command = str((payload.get("tool_input") or {}).get("command", ""))
    reasons = command_reasons(command, tool, _root(payload))
    if not reasons or _take_approval(payload):
        return
    # json.dump escapes the Japanese approval words as ASCII, so the decision
    # reads the same whatever code page the console uses.
    # json.dump は日本語の承認の言葉を ASCII にエスケープするので、コンソールの
    # コードページによらず同じ内容で読める。
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON.format(
            tool=tool, reasons="\n".join(reasons), limit=MAX_SERIAL_GUI_TESTS),
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
        # A guard must never wedge the session over a payload it cannot read.
        # 読めないペイロードのせいで、ガードがセッションを止めてはならない。
        sys.exit(0)
