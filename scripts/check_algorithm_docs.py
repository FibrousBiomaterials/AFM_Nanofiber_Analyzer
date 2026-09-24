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

A commit is blocked when it changes what one of the algorithm modules computes
and neither language version of the document is part of the same change, and,
in ``--staged`` mode, when a code excerpt quoted by either document no longer
matches the staged code (`scripts/doc_excerpts.py`). "Changes what it
computes" is decided definition by definition
(`doc_excerpts.computation_changes`): comments, docstrings, and new
definitions that no existing code uses do not count, so a deprecated alias or
a comment fix commits without touching the document and without
``--no-verify``, which would skip every other check as well.
アルゴリズムモジュールの計算を変えたのに文書のどちらの言語版も同じ変更に含まれない
場合、および ``--staged`` モードでは、どちらかの文書が引用したコード片が
ステージ済みのコードと一致しない場合に、コミットを中止する。「計算を変えた」は
定義ごとに判定する（`doc_excerpts.computation_changes`）。コメント・docstring・
既存のコードが使わない新しい定義は数えないため、非推奨の別名やコメントの修正は、
文書に触れず、他の検査まで飛ばしてしまう ``--no-verify`` も使わずにコミットできる。

This hook is the early warning, not the enforcement. It is opt-in per clone and
can be bypassed, so ``tests/test_algorithm_docs.py`` carries the same rule into
CI, where it cannot be skipped: it fingerprints each definition of the same
modules with comments and docstrings removed and fails, by the same rule, until
the fingerprints are refreshed.
このフックは早期警告であって強制ではない。クローンごとの opt-in であり迂回も
できるため、同じ規則を ``tests/test_algorithm_docs.py`` が CI へ持ち込む。そちら
は省略できず、同じモジュールの各定義をコメントと docstring を除いて指紋化し、
同じ規則で、指紋が更新されるまで失敗する。

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
from pathlib import Path

# The excerpt contract shared with the GUI04 document lives beside this script.
# GUI04 文書と共有する引用規約は、このスクリプトの隣にある。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from doc_excerpts import (  # noqa: E402
    check_pair_excerpts,
    code_symbol_digests,
    computation_changes,
    is_project_code,
    names_used_in,
    read_staged,
)

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
    "lib/centerline.py",
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


def _report(changes: dict[str, list[str]], label: str) -> None:
    """Print the finding and how to resolve it."""
    print(
        f"algorithm-doc check: {label} change what "
        + ", ".join(sorted(changes))
        + " computes, but neither docs/algorithms.md nor docs/algorithms.ja.md.",
        file=sys.stderr,
    )
    for path in sorted(changes):
        for line in changes[path][:8]:
            print(f"  - {path}: {line}", file=sys.stderr)
        if len(changes[path]) > 8:
            print(f"  - {path}: ... {len(changes[path]) - 8} more", file=sys.stderr)
    print(
        "\n"
        "docs/algorithms.md explains these stages to the people who cite the\n"
        "numbers this software produces. Update the affected sections of both\n"
        "language versions and refresh the fingerprints:\n"
        "\n"
        "    .venv\\Scripts\\python.exe tests\\test_algorithm_docs.py --update\n"
        "\n"
        "Comments, docstrings, and definitions no existing code uses (a new\n"
        "helper, constant, or deprecated alias) are not counted, so a change\n"
        "listed above is one to what the reviewed code runs.",
        file=sys.stderr,
    )


def _module_changes(before: str | None, after: str | None,
                    external: set | None = None) -> list[str]:
    """What in `after` can change the computation of `before` (both sources)."""
    if before is None and after is None:
        return []
    if before is None:
        return ["module added"]
    if after is None:
        return ["module removed"]
    return computation_changes(code_symbol_digests(before), after, external)


def _external_names(rev: str, module: str) -> set:
    """Names the project code other than `module` mentions at `rev` ("" = index)."""
    if rev == "":
        listing = _git("ls-files", "--", "*.py")
    else:
        listing = _git("ls-tree", "-r", "--name-only", rev)
    paths = [p for p in listing.split() if is_project_code(p) and p != module]
    return names_used_in(text for text in (_read_rev(rev, p) for p in paths) if text)


def _read_rev(rev: str, path: str) -> str | None:
    """Read `path` at `rev` ("" = the index), or None when it is absent there."""
    proc = subprocess.run(["git", "-C", _repo_root(), "show", f"{rev}:{path}"],
                          capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def _check(diff_args: list[str], label: str, before_rev: str, after_rev: str) -> int:
    """Return 1 when the change alters a stage's computation without a doc update.
    段の計算を変える変更が文書の更新を伴わないとき 1 を返す。

    A module that was touched is compared definition by definition
    (`doc_excerpts.computation_changes`), so comments, docstrings, and additions
    no existing code uses do not require the document to change.
    触れたモジュールは定義ごとに比較する（`doc_excerpts.computation_changes`）。
    コメント・docstring・既存のコードが使わない追加では、文書の変更を求めない。
    """
    changed = _changed_files(diff_args)
    touched = sorted(path for path in ALGORITHM_PATHS if path in changed)
    if not touched or any(doc in changed for doc in DOC_PATHS):
        return 0
    changes = {}
    for path in touched:
        found = _module_changes(_read_rev(before_rev, path), _read_rev(after_rev, path),
                                _external_names(after_rev, path))
        if found:
            changes[path] = found
    if not changes:
        print(f"algorithm-doc check: OK ({label}; "
              + ", ".join(touched)
              + " touched without changing what they compute).", file=sys.stderr)
        return 0
    _report(changes, label)
    return 1


def _check_staged_excerpts() -> int:
    """
    Return 1 when a quoted excerpt no longer matches the staged code.
    引用したコード片がステージ済みのコードと一致しなくなっていれば 1 を返す。

    The documents quote the code they explain (``# source:`` blocks). Unlike
    the path check above, this one cannot be satisfied by touching a document:
    the quoted lines themselves must still be what the software runs.
    文書は説明対象のコードを引用している（``# source:`` ブロック）。上のパス検査と
    違い、文書に触れるだけでは通らない。引用した行そのものが、ソフトウェアの実行
    内容と一致していなければならない。
    """
    docs = {rel: read_staged(rel) for rel in DOC_PATHS}
    missing = [rel for rel, text in docs.items() if text is None]
    if missing:
        print(f"algorithm-doc check: {', '.join(missing)} not in the index",
              file=sys.stderr)
        return 1
    problems, _quoted = check_pair_excerpts(docs, read_staged)
    if not problems:
        return 0
    print("algorithm-doc check (staged snapshot): quoted code is out of date:",
          file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\nUpdate the excerpts and the explanation around them in both\n"
        "docs/algorithms.md and docs/algorithms.ja.md.",
        file=sys.stderr,
    )
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
            return max(_check(["--cached"], "staged changes", "HEAD", ""),
                       _check_staged_excerpts())
        if args.rev_range:
            start, _, end = args.rev_range.partition("..")
            return _check([args.rev_range], f"changes in {args.rev_range}",
                          start, end or "HEAD")
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
