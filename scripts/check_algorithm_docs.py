#!/usr/bin/env python3
"""Scanner that blocks algorithm changes committed without a doc update.
アルゴリズムの変更を解説文書の更新なしにコミットするのを止める安全装置。

Invoked by ``.githooks/pre-commit`` (enable it once per clone with
``git config core.hooksPath .githooks``). ``docs/algorithms.md`` and its
Japanese counterpart explain what background calibration, binarization,
skeletonization, and kink detection do, so that the analysis is not a black
box to the people citing its output. That only holds while the explanation
tracks the code, and an explanation that has silently gone stale is worse than
none: it is read as authoritative.
``.githooks/pre-commit`` から呼ばれる(クローンごとに
``git config core.hooksPath .githooks`` で一度だけ有効化する)。
``docs/algorithms.md`` と日本語版は、背景補正・二値化・細線化・キンク検出の
内容を説明し、出力を引用する人にとって解析がブラックボックスにならないように
する。これはコードに追随している間だけ成り立つ。黙って陳腐化した説明は、説明が
無いことよりも悪い。権威あるものとして読まれてしまうからである。

A commit is blocked when one of the four algorithm modules changed and neither
language version of the document is part of the same change.

This hook is the early warning, not the enforcement. It is opt-in per clone and
can be bypassed, so ``tests/test_algorithm_docs.py`` carries the same rule into
CI, where it cannot be skipped: it fingerprints the same four modules with
comments and docstrings removed and fails until the fingerprint is refreshed.
このフックは早期警告であって強制ではない。クローンごとの opt-in であり迂回も
できるため、同じ規則を ``tests/test_algorithm_docs.py`` が CI へ持ち込む。そちら
は省略できず、同じ 4 モジュールをコメントと docstring を除いて指紋化し、指紋が
更新されるまで失敗する。

Manual scans without committing:
    python scripts/check_algorithm_docs.py --staged
    python scripts/check_algorithm_docs.py --range origin/main..HEAD

Exit codes: 0 = clean, 1 = findings (the commit is blocked), 2 = usage or git
error (also blocked; the check fails closed).
"""

from __future__ import annotations

import argparse
import functools
import subprocess
import sys

# The four preprocessing stages the document explains. Changing one of these is
# what makes the explanation potentially wrong. `lib/pipeline.py` is
# deliberately absent: it wires the stages together and owns `ProcParams`, but a
# new parameter there is already caught by the test suite's coverage check, and
# including it would fire the hook on every unrelated pipeline edit.
# 文書が説明する前処理 4 ステージ。説明が誤りになりうるのはここが変わるとき
# である。`lib/pipeline.py` は意図的に含めない。各段の結線と `ProcParams` を
# 担うが、そこへのパラメータ追加はテストスイートの網羅検査が既に捕捉するうえ、
# 含めると無関係なパイプライン編集のたびにフックが発火してしまう。
ALGORITHM_PATHS = (
    "lib/bg_calibrator.py",
    "lib/segmenter.py",
    "lib/skeletonizer.py",
    "lib/kink_detector.py",
)

DOC_PATHS = (
    "docs/algorithms.md",
    "docs/algorithms.ja.md",
)


@functools.lru_cache(maxsize=1)
def _repo_root() -> str:
    """Return the repository root as an absolute path.
    リポジトリのルートを絶対パスで返す。
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

    Notes
    -----
    ``-z`` avoids ``core.quotepath`` escaping, so non-ASCII paths compare
    correctly. Unlike the changelog check, deletions are included: removing an
    algorithm module is exactly the kind of change the document must follow.
    ``-z`` により ``core.quotepath`` のエスケープを避け、非 ASCII パスも正しく
    比較できる。CHANGELOG 検査と違い削除も対象に含める。アルゴリズムモジュール
    の削除こそ、文書が追随しなければならない変更だからである。
    """
    out = _git("diff", "--name-only", "-z", *diff_args)
    return {path for path in out.split("\0") if path}


def _report(changed_modules: list[str], label: str) -> None:
    """Print the finding and how to resolve it."""
    print(
        f"algorithm-doc check: {label} modify "
        + ", ".join(changed_modules)
        + " but neither docs/algorithms.md nor docs/algorithms.ja.md.",
        file=sys.stderr,
    )
    print(
        "\n"
        "docs/algorithms.md explains these stages to the people who cite the\n"
        "numbers this software produces. If the change alters what a stage\n"
        "computes, update the affected sections of both language versions and\n"
        "refresh the fingerprints:\n"
        "\n"
        "    .venv\\Scripts\\python.exe tests\\test_algorithm_docs.py --update\n"
        "\n"
        "If the change genuinely does not affect the explanation (a comment, a\n"
        "type hint, a refactor with identical behavior), commit with\n"
        "--no-verify. The CI test still fingerprints the code, so a behavioral\n"
        "change cannot slip past that way.",
        file=sys.stderr,
    )


def _check(diff_args: list[str], label: str) -> int:
    """Return 1 when the change needs a doc update it does not carry."""
    changed = _changed_files(diff_args)
    changed_modules = sorted(path for path in ALGORITHM_PATHS if path in changed)
    if not changed_modules:
        return 0
    if any(doc in changed for doc in DOC_PATHS):
        return 0
    _report(changed_modules, label)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point; selects staged mode (the hook) or manual range mode.
    エントリポイント。staged モード(フック用)と range モードを選択する。
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
        help="check a revision range, e.g. origin/main..HEAD",
    )
    args = parser.parse_args(argv)

    try:
        if args.staged:
            return _check(["--cached"], "staged changes")
        if args.rev_range:
            return _check([args.rev_range], f"changes in {args.rev_range}")
    except RuntimeError as exc:
        print(f"algorithm-doc check: {exc}", file=sys.stderr)
        return 2

    parser.print_usage(sys.stderr)
    print(
        "\nalgorithm-doc check: choose --staged or --range <rev-range>.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
