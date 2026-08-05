#!/usr/bin/env python3
"""Scanner that blocks result-changing commits without a CHANGELOG.md entry.
数値結果が変わる変更を CHANGELOG.md への追記なしにコミットするのを止める安全装置。

Invoked by ``.githooks/pre-commit`` (enable it once per clone with
``git config core.hooksPath .githooks``). The check is deliberately narrow:
it fires only when ``tests/strict_regression_golden.json`` is part of the
change. That file records the hashes the pipeline is expected to produce, so
a change to it means the numbers this software reports have moved. Such a
change breaks reproducibility of earlier results even when no API breaks, so
RELEASING.md requires it to be visible in the changelog rather than only in
the commit log.

A commit is blocked when the goldens changed and either

- ``CHANGELOG.md`` is not part of the same change, or
- ``CHANGELOG.md`` changed but no line was added inside its
  ``## [Unreleased]`` section (e.g. only an older release section was edited).

Manual scans without committing:
    python scripts/check_changelog.py --staged
    python scripts/check_changelog.py --range origin/main..HEAD

Exit codes: 0 = clean, 1 = findings (the commit is blocked), 2 = usage or git
error (also blocked; the check fails closed).
"""

from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys

# Strict-regression goldens: the recorded hashes are this project's definition
# of "the numbers the pipeline produces", so a change here is the one reliable,
# low-false-positive signal that analysis results moved. Editing an analysis
# module without touching this file leaves every golden intact, which means the
# results did not change.
# 厳密回帰テストの golden 値。記録されたハッシュが「パイプラインが出す数値」
# そのものなので、このファイルの変更が「結果が変わった」ことの確実なシグナル
# になる(解析モジュールを触っても golden が動かなければ結果は変わっていない)。
GOLDEN_PATH = "tests/strict_regression_golden.json"
CHANGELOG_PATH = "CHANGELOG.md"

# Keep a Changelog structure: "## [Unreleased]" opens the section that collects
# not-yet-released changes; the next "## " heading closes it.
_UNRELEASED_RE = re.compile(r"^##\s+\[Unreleased\]", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##\s")

# Unified-diff hunk header; group 1 is the first line number on the new side.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@functools.lru_cache(maxsize=1)
def _repo_root() -> str:
    """Return the repository root as an absolute path.
    リポジトリのルートを絶対パスで返す。

    Notes
    -----
    Every other git call runs with ``-C <root>`` so the pathspecs and the
    constants above stay repository-relative no matter where the check is
    invoked from.
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"not inside a git repository: {detail}")
    return proc.stdout.decode("utf-8", "replace").strip()


def _git(*args: str) -> str:
    """Run a git command at the repository root and return its stdout as text.
    リポジトリのルートで git コマンドを実行し、標準出力をテキストとして返す。

    Raises
    ------
    RuntimeError
        If git exits non-zero.
    """
    proc = subprocess.run(["git", "-C", _repo_root(), *args], capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.decode("utf-8", "replace")


def _changed_files(diff_args: list[str]) -> set[str]:
    """Collect repository-relative paths touched by a diff.
    差分が触れたファイルのパス(リポジトリ相対)を集める。

    Parameters
    ----------
    diff_args
        Extra arguments for ``git diff`` (``--cached`` or a revision range).

    Notes
    -----
    ``-z`` avoids ``core.quotepath`` escaping, so non-ASCII paths compare
    correctly. Deletions are excluded: removing the goldens is not a
    result-changing fix.
    """
    out = _git("diff", "--name-only", "--diff-filter=ACMR", "-z", *diff_args)
    return {path for path in out.split("\0") if path}


def _unreleased_span(text: str) -> tuple[int, int] | None:
    """Return the 1-based line range of the ``[Unreleased]`` section body.
    ``[Unreleased]`` セクション本文の行範囲(1 始まり)を返す。

    Returns
    -------
    Inclusive ``(first, last)`` line numbers, or None when the file has no
    ``## [Unreleased]`` heading.
    """
    lines = text.splitlines()
    start: int | None = None
    for lineno, line in enumerate(lines, start=1):
        if start is None:
            if _UNRELEASED_RE.match(line):
                start = lineno + 1
            continue
        if _SECTION_RE.match(line):
            return (start, lineno - 1)
    if start is None:
        return None
    return (start, len(lines))


def _added_line_numbers(diff_args: list[str], path: str) -> set[int]:
    """Collect new-side line numbers of lines added to one file.
    1 つのファイルに追加された行の、新側での行番号を集める。

    Notes
    -----
    ``--unified=0`` removes context lines, so the new-side counter only has to
    advance on added lines; removed lines do not consume a new-side number.
    """
    diff = _git("diff", "--no-color", "--unified=0", *diff_args, "--", path)
    added: set[int] = set()
    lineno = 0
    for line in diff.splitlines():
        hunk = _HUNK_RE.match(line)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            added.add(lineno)
            lineno += 1
    return added


def _report(reason: str, action: str, bypass: str) -> None:
    """Print the block message explaining why and how to resolve it.
    ブロック理由と解決方法を標準エラーに出力する。
    """
    print(
        f"changelog check: BLOCKED ({action}).\n"
        f"  {reason}\n\n"
        f"  {GOLDEN_PATH} is part of this change, so the numbers this software\n"
        "  produces differ from the previous release. Users reproducing earlier\n"
        "  results must be able to see that from the changelog alone.\n\n"
        "  How to resolve:\n"
        f'  - Add one line under "## [Unreleased]" in {CHANGELOG_PATH} (normally\n'
        '    under "### Fixed") and state explicitly that results change from\n'
        "    this version; see RELEASING.md.\n"
        f"  - Include {CHANGELOG_PATH} in the same change.\n"
        "  - If the goldens moved only because test data was added or renamed\n"
        f"    and the analysis itself is unchanged: {bypass}\n",
        file=sys.stderr,
    )


def _check(
    diff_args: list[str],
    changelog_rev: str,
    label: str,
    action: str,
    bypass: str,
) -> int:
    """Run the check over one diff and report the outcome.
    1 つの差分について検査し、結果を報告する。
    """
    changed = _changed_files(diff_args)
    if GOLDEN_PATH not in changed:
        print(
            f"changelog check: OK ({label}; {GOLDEN_PATH} unchanged).",
            file=sys.stderr,
        )
        return 0

    if CHANGELOG_PATH not in changed:
        _report(
            f"The regression goldens changed but {CHANGELOG_PATH} did not.",
            action=action,
            bypass=bypass,
        )
        return 1

    span = _unreleased_span(_git("show", f"{changelog_rev}:{CHANGELOG_PATH}"))
    if span is None:
        raise RuntimeError(
            f"{CHANGELOG_PATH} has no '## [Unreleased]' heading; cannot verify "
            "the entry."
        )
    added = _added_line_numbers(diff_args, CHANGELOG_PATH)
    if not any(span[0] <= lineno <= span[1] for lineno in added):
        _report(
            f"{CHANGELOG_PATH} changed, but nothing was added under "
            "'## [Unreleased]'.",
            action=action,
            bypass=bypass,
        )
        return 1

    print(
        f"changelog check: OK ({label}; goldens changed and {CHANGELOG_PATH} "
        "records it).",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point; selects staged mode (the hook) or manual range mode.
    エントリポイント。ステージ済み差分(フック)か手動レンジを選択する。
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--staged",
        action="store_true",
        help="check the staged diff ('git diff --cached'); used by pre-commit",
    )
    parser.add_argument(
        "--range",
        dest="rev_range",
        default="",
        help="check 'git diff RANGE' (e.g. origin/main..HEAD) instead",
    )
    args = parser.parse_args(argv)

    # Report through UTF-8 regardless of the console code page, matching
    # scripts/check_sensitive.py.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.staged:
            # ":CHANGELOG.md" reads the staged blob, which is what this commit
            # will contain — not the possibly dirtier working-tree file.
            # ":CHANGELOG.md" はステージ済みの内容を読む。作業ツリーの未ステージ
            # 変更ではなく、実際にコミットされる内容で判定するため。
            return _check(
                diff_args=["--cached"],
                changelog_rev="",
                label="staged changes",
                action="commit",
                bypass="git commit --no-verify",
            )
        if args.rev_range:
            end = args.rev_range.split("..")[-1] or "HEAD"
            return _check(
                diff_args=[args.rev_range],
                changelog_rev=end,
                label=f"range {args.rev_range}",
                action="range check",
                bypass="skip this check",
            )
        parser.print_help(sys.stderr)
        print(
            "\nchangelog check: choose --staged or --range "
            "(e.g. --range origin/main..HEAD).",
            file=sys.stderr,
        )
        return 2
    except RuntimeError as exc:
        # Fail closed: an internal error also blocks the commit.
        # フェイルクローズ方針: 内部エラー時もコミットを中止する。
        print(f"changelog check: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
