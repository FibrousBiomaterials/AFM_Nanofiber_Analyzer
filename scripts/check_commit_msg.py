#!/usr/bin/env python3
"""Scanner that blocks commit messages carrying leaked shell quoting markers.
シェルの引用記号が紛れ込んだコミットメッセージを止める安全装置。

Invoked by ``.githooks/commit-msg`` (enable it once per clone with
``git config core.hooksPath .githooks``).

The failure this catches is a quoting mismatch between shells rather than a
typo. A multi-line message passed with ``git commit -m`` needs a here-string
in PowerShell (``@'`` … ``'@``) and a here-document in POSIX ``sh``
(``<<'EOF'`` … ``EOF``), and the two are not interchangeable: running the
PowerShell form under ``sh`` leaves the delimiters in the message, so the
commit lands with ``@`` as its subject line and the real subject pushed down
to line 2. Nothing fails loudly — the commit succeeds and the damage is only
visible in ``git log``, after which only a history rewrite can fix it.

The fix the message points to is to stop hand-quoting multi-line messages
altogether and pass them as a file with ``git commit -F``, which behaves
identically in both shells.

Manual scan without committing:
    python scripts/check_commit_msg.py <path-to-message-file>

Exit codes: 0 = clean, 1 = findings (the commit is blocked), 2 = usage or read
error (also blocked; the check fails closed).
"""

from __future__ import annotations

import sys

# Lines that are a quoting delimiter and nothing else. A real commit message
# never consists of one of these on its own line, so an exact match is both
# the reliable signal and the one that cannot fire on prose that merely
# mentions a marker.
# 引用の区切り記号だけからなる行。本物のコミットメッセージがこれらだけの行を
# 持つことはないため、完全一致が確実なシグナルであり、記号に言及しているだけの
# 本文で誤検出することもない。
#
# "@" alone is the PowerShell here-string opener as `sh` leaves it: `sh` eats
# the quote in `@'` as the start of a quoted string and keeps the `@`.
# 単独の "@" は、PowerShell の here-string 開始記号を `sh` が処理した残骸である。
# `sh` は `@'` の引用符を文字列の開始として解釈し、"@" だけを残す。
QUOTING_MARKERS = frozenset({
    "@", "@'", "'@", '@"', '"@',            # PowerShell here-string
    "EOF", "'EOF'", '"EOF"', "<<EOF", "<<'EOF'",   # POSIX here-document
    "EOM", "PATCH", "'", '"',
})

# Git appends everything after this line to the message file as a diff for the
# author to read; it is stripped before the message is stored.
# git はこの行以降を、書き手が読むための差分としてメッセージファイルへ付ける。
# 実際に保存されるメッセージからは取り除かれる。
SCISSORS = "# ------------------------ >8 ------------------------"


def message_lines(text: str) -> list[str]:
    """
    Return the lines git will keep, dropping comments and the scissors block.
    git が実際に残す行を返す。コメント行と scissors 以降は取り除く。
    """
    lines = []
    for line in text.splitlines():
        if line.rstrip() == SCISSORS:
            break
        if line.startswith("#"):
            continue
        lines.append(line)
    return lines


def findings(lines: list[str]) -> list[str]:
    """
    Report every problem found in the message body.
    メッセージ本文で見つかった問題をすべて報告する。

    Notes
    -----
    The empty subject line is checked as well as the markers themselves: a
    leaked opener takes line 1, so the subject that ``git log --oneline`` and
    every UI show is the delimiter rather than the summary the author wrote.
    区切り記号そのものに加えて、件名行が空であることも検査する。開始記号が
    1 行目を占めると、``git log --oneline`` や各種 UI が表示する件名が、書き手
    の書いた要約ではなく区切り記号になってしまうためである。
    """
    problems = []
    for number, line in enumerate(lines, start=1):
        if line.strip() in QUOTING_MARKERS:
            problems.append(
                f"line {number}: {line.strip()!r} is a shell quoting delimiter, "
                "not message text"
            )
    if lines and not lines[0].strip() and any(ln.strip() for ln in lines[1:]):
        problems.append("line 1: the subject line is empty; the summary starts lower")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "commit-msg check: usage: check_commit_msg.py <path-to-message-file>",
            file=sys.stderr,
        )
        return 2

    try:
        with open(argv[1], encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        # Fail closed: an unreadable message file also blocks the commit.
        # フェイルクローズ方針: メッセージファイルを読めない場合もコミットを中止する。
        print(f"commit-msg check: error: {exc}", file=sys.stderr)
        return 2

    problems = findings(message_lines(text))
    if not problems:
        print("commit-msg check: OK (no shell quoting markers).")
        return 0

    print("commit-msg check: shell quoting leaked into the message.", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    print(
        "\nWrite the message to a file and pass it with -F, which quotes\n"
        "identically in PowerShell and sh:\n"
        "    git commit -F .tmp/commit_msg.txt\n"
        "Do not reach for --no-verify: the commit would land with the\n"
        "delimiter as its subject line, and only a history rewrite fixes that.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
