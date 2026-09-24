#!/usr/bin/env python3
"""Scanner that blocks commits whose version bookkeeping is missing.
バージョン関係の書き込み漏れがあるコミットを止める安全装置。

Invoked by ``.githooks/pre-commit`` (enable it once per clone with
``git config core.hooksPath .githooks``). Three rules, each a bookkeeping step
RELEASING.md and AGENTS.md §8.2 require and that is easy to forget:

1. **Package version.** ``pyproject.toml`` and ``lib/__init__.py`` must carry
   the same version, and it must be later than the newest release tag
   reachable from HEAD. The version is written into every bundle as
   ``software_version``, so code left under a released number records its
   bundles as made by that release (RELEASING.md, "リリース間の開発版表記").
   Right after a release this means the next commit must set ``X.Y.Z.devN``.
2. **Bundle format.** When ``BUNDLE_FORMAT_VERSION`` in
   ``lib/bundle_schema.py`` changes, the new version must be listed in
   ``SUPPORTED_BUNDLE_VERSIONS``, named in the ``## [Unreleased]`` section of
   ``CHANGELOG.md``, and named in both README files; and the package version
   must be at least a MINOR step above the last release, because an older
   release cannot read the new bundles (RELEASING.md, MAJOR / MINOR table).
3. **ProcParams fields.** Removing or renaming a ``ProcParams`` field breaks
   every ``_param.json`` that carries it (AGENTS.md §8.1), which RELEASING.md
   classifies as MAJOR, so it requires a MAJOR step above the last release.

Rules 2 and 3 compare the file before and after the change; rule 1 reads only
the result. What the check cannot do is decide the version number or write
the changelog prose: it only refuses a commit that is missing them.

Manual scans without committing:
    python scripts/check_versions.py --staged
    python scripts/check_versions.py --range v2.0.1..HEAD

Exit codes: 0 = clean, 1 = findings (the commit is blocked), 2 = usage or git
error (also blocked; the check fails closed).
"""

from __future__ import annotations

import argparse
import ast
import functools
import re
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

PYPROJECT = "pyproject.toml"
INIT = "lib/__init__.py"
SCHEMA = "lib/bundle_schema.py"
PIPELINE = "lib/pipeline.py"
CHANGELOG = "CHANGELOG.md"
READMES = ("README.md", "README.ja.md")
WATCHED = (PYPROJECT, INIT, SCHEMA, PIPELINE, CHANGELOG) + READMES

# The version forms this project uses: a release "X.Y.Z" and a development
# version "X.Y.Z.devN" (PEP 440), which sorts before its release.
# 本プロジェクトが使う版の形式。リリース "X.Y.Z" と開発版 "X.Y.Z.devN"
# （PEP 440）で、開発版は対応するリリースより前に並ぶ。
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$")
_TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")
_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_UNRELEASED_RE = re.compile(r"^##\s+\[Unreleased\]", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##\s")

Version = Tuple[int, int, int, float]


# ----------------------------------------------------------------------------
# Pure rules (no git), unit-tested in tests/test_check_versions.py
# ----------------------------------------------------------------------------

def parse_version(text: str) -> Optional[Version]:
    """Parse "X.Y.Z" or "X.Y.Z.devN" into a sortable key, or None.
    "X.Y.Z" または "X.Y.Z.devN" を並べ替え可能なキーに変換する。無効なら None。
    """
    m = _VERSION_RE.match(text.strip())
    if not m:
        return None
    dev = float("inf") if m.group(4) is None else float(m.group(4))
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), dev


def pyproject_version(text: str) -> Optional[str]:
    """Return ``[project] version`` of a pyproject.toml, or None.
    pyproject.toml の ``version`` を返す。見つからなければ None。
    """
    m = _PYPROJECT_VERSION_RE.search(text)
    return m.group(1) if m else None


def module_constant(source: str, name: str):
    """Return the literal value assigned to a module-level name, or None.
    モジュール直下で名前に代入されたリテラル値を返す。無ければ None。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                try:
                    return ast.literal_eval(node.value)
                except ValueError:
                    return None
    return None


def dataclass_fields(source: str, class_name: str) -> Optional[List[str]]:
    """Return the annotated field names of a class, in order, or None.
    クラスの注釈付きフィールド名を順に返す。クラスが無ければ None。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                stmt.target.id for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    return None


def unreleased_section(changelog: str) -> str:
    """Return the body of the ``## [Unreleased]`` section ("" if absent).
    ``## [Unreleased]`` セクションの本文を返す（無ければ ""）。
    """
    out: List[str] = []
    inside = False
    for line in changelog.splitlines():
        if inside:
            if _SECTION_RE.match(line):
                break
            out.append(line)
        elif _UNRELEASED_RE.match(line):
            inside = True
    return "\n".join(out)


def _mentions(text: str, version: str) -> bool:
    """Whether `version` appears as a whole token (1.2 does not match 1.21)."""
    return re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d])", text) is not None


def find_problems(
    before: Dict[str, Optional[str]],
    after: Dict[str, Optional[str]],
    last_release: Optional[str],
) -> List[str]:
    """Apply the three rules to the watched files before and after a change.
    変更前後の監視ファイルに 3 つの規則を適用する。

    Parameters
    ----------
    before, after
        File path to text (None when the file does not exist on that side),
        for the paths in `WATCHED`.
        `WATCHED` の各パスからテキストへの辞書（その側に無ければ None）。
    last_release
        Newest release tag reachable from the result, as "X.Y.Z", or None when
        there is none.
        結果から到達できる最新のリリースタグ（"X.Y.Z"）。無ければ None。

    Returns
    -------
    list of str
        One message per finding; empty when the change is clean.
        検出ごとに 1 つのメッセージ。問題が無ければ空。
    """
    problems: List[str] = []
    released = parse_version(last_release) if last_release else None

    # --- Rule 1: package version --------------------------------------------
    py_ver = pyproject_version(after.get(PYPROJECT) or "")
    init_ver = module_constant(after.get(INIT) or "", "__version__")
    if py_ver is None or not isinstance(init_ver, str):
        problems.append(
            f"cannot read the version from {PYPROJECT} ({py_ver!r}) "
            f"or {INIT} ({init_ver!r})."
        )
        return problems
    if py_ver != init_ver:
        problems.append(
            f"{PYPROJECT} says {py_ver} but {INIT} says {init_ver}; they must "
            "be the same version (RELEASING.md step 1-2)."
        )
    version = parse_version(py_ver)
    if version is None:
        problems.append(
            f"version {py_ver!r} is neither X.Y.Z nor X.Y.Z.devN."
        )
        return problems
    if released is not None and version <= released:
        problems.append(
            f"version {py_ver} is not later than the last release v{last_release}. "
            "Code after a release must carry the next development version, "
            f"e.g. {released[0]}.{released[1]}.{released[2] + 1}.dev0 or "
            f"{released[0]}.{released[1] + 1}.0.dev0, because __version__ is "
            "written into every bundle as software_version (RELEASING.md "
            "step 13)."
        )

    # --- Rule 2: bundle format ----------------------------------------------
    old_fmt = module_constant(before.get(SCHEMA) or "", "BUNDLE_FORMAT_VERSION")
    new_fmt = module_constant(after.get(SCHEMA) or "", "BUNDLE_FORMAT_VERSION")
    if isinstance(new_fmt, str) and old_fmt is not None and new_fmt != old_fmt:
        supported = module_constant(after.get(SCHEMA) or "", "SUPPORTED_BUNDLE_VERSIONS")
        if not (isinstance(supported, (tuple, list)) and new_fmt in supported):
            problems.append(
                f"BUNDLE_FORMAT_VERSION became {new_fmt!r} but "
                f"SUPPORTED_BUNDLE_VERSIONS does not list it."
            )
        if not _mentions(unreleased_section(after.get(CHANGELOG) or ""), new_fmt):
            problems.append(
                f"BUNDLE_FORMAT_VERSION became {new_fmt!r} but the "
                f"'## [Unreleased]' section of {CHANGELOG} does not name {new_fmt}."
            )
        for readme in READMES:
            if not _mentions(after.get(readme) or "", new_fmt):
                problems.append(
                    f"BUNDLE_FORMAT_VERSION became {new_fmt!r} but {readme} "
                    f"does not name {new_fmt} (the vlmeta 'version' row)."
                )
        if released is not None and version[:2] <= released[:2]:
            problems.append(
                f"BUNDLE_FORMAT_VERSION became {new_fmt!r}, which v{last_release} "
                f"cannot read, so the next release must be at least MINOR: "
                f"set the version to {released[0]}.{released[1] + 1}.0.dev0 or "
                f"later (currently {py_ver})."
            )

    # --- Rule 3: ProcParams fields --------------------------------------------
    old_fields = dataclass_fields(before.get(PIPELINE) or "", "ProcParams")
    new_fields = dataclass_fields(after.get(PIPELINE) or "", "ProcParams")
    if old_fields is not None and new_fields is not None:
        gone = [name for name in old_fields if name not in new_fields]
        if gone and (released is None or version[0] <= released[0]):
            problems.append(
                "ProcParams lost field(s) " + ", ".join(gone) + ". Field names are "
                "frozen because _param.json stores them (AGENTS.md §8.1); a "
                "rename or removal is a MAJOR change, so it needs version "
                f"{(released[0] + 1) if released else 'N+1'}.0.0.dev0 or later "
                f"(currently {py_ver}). Add an alias instead if the old files "
                "must keep loading."
            )
    return problems


# ----------------------------------------------------------------------------
# Git plumbing
# ----------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _repo_root() -> str:
    """Return the repository root as an absolute path.
    リポジトリのルートを絶対パスで返す。
    """
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"not inside a git repository: {detail}")
    return proc.stdout.decode("utf-8", "replace").strip()


def _git(*args: str, allow_fail: bool = False) -> Optional[str]:
    """Run git at the repository root; None on failure when `allow_fail`.
    リポジトリのルートで git を実行する。`allow_fail` なら失敗時に None。
    """
    proc = subprocess.run(["git", "-C", _repo_root(), *args], capture_output=True)
    if proc.returncode != 0:
        if allow_fail:
            return None
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.decode("utf-8", "replace")


def _read(rev: str, path: str) -> Optional[str]:
    """Read `path` at `rev` ("" = the index), or None when it does not exist."""
    return _git("show", f"{rev}:{path}", allow_fail=True)


def _last_release(rev: str, skip_own: bool = False) -> Optional[str]:
    """Return the newest "vX.Y.Z" tag reachable from `rev`, as "X.Y.Z".
    `rev` から到達できる最新の "vX.Y.Z" タグを "X.Y.Z" で返す。

    `skip_own` leaves out tags on `rev` itself. A range that ends at a release
    commit is checked against the release before it, because that commit only
    received its own tag after it was made. The staged check must not skip
    them: there `rev` is HEAD, the commit before the one being made, and a
    tagged HEAD is exactly the release the new commit has to be later than.
    `skip_own` は `rev` 自身のタグを除く。リリースコミットで終わる範囲は、その
    前のリリースと比べる。そのコミットは作成後に自身のタグを受け取ったためで
    ある。ステージ済みの検査では除いてはならない。そこでの `rev` は作成中の
    コミットの 1 つ前の HEAD であり、タグ付きの HEAD こそ新しいコミットが上回る
    べきリリースだからである。
    """
    if not rev:
        return None
    out = _git("tag", "--merged", rev, "--list", "v*") or ""
    own = (set((_git("tag", "--points-at", rev, allow_fail=True) or "").split())
           if skip_own else set())
    best: Optional[str] = None
    for tag in out.split():
        if tag in own:
            continue
        m = _TAG_RE.match(tag)
        if m and (best is None or parse_version(m.group(1)) > parse_version(best)):
            best = m.group(1)
    return best


def _run(before_rev: Optional[str], after_rev: str, tag_rev: str, label: str,
         skip_own: bool = False) -> int:
    """Check one change and report; returns the exit code."""
    before = {p: (_read(before_rev, p) if before_rev else None) for p in WATCHED}
    after = {p: _read(after_rev, p) for p in WATCHED}
    last = _last_release(tag_rev, skip_own=skip_own)
    problems = find_problems(before, after, last)
    if not problems:
        print(f"version check: OK ({label}; last release "
              f"{'v' + last if last else 'none'}).", file=sys.stderr)
        return 0
    print(f"version check: BLOCKED ({label}).", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\n  Fix the files named above and stage them. This check only refuses a\n"
        "  change that is missing its bookkeeping; choosing the version number\n"
        "  and writing the changelog entry stay with you (RELEASING.md).",
        file=sys.stderr,
    )
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point; selects staged mode (the hook) or manual range mode.
    エントリポイント。ステージ済み差分（フック）か手動レンジを選択する。
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", action="store_true",
                        help="check the index against HEAD; used by pre-commit")
    parser.add_argument("--range", dest="rev_range", default="",
                        help="check 'A..B' instead (e.g. v2.0.1..HEAD)")
    args = parser.parse_args(argv)

    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.staged:
            # The index is what the commit will contain; HEAD is what it
            # changes. A first commit has no HEAD, so nothing is compared.
            # インデックスがコミットされる内容、HEAD が変更前の内容である。
            head = "HEAD" if _git("rev-parse", "--verify", "HEAD", allow_fail=True) else None
            return _run(head, "", "HEAD" if head else "", "staged changes")
        if args.rev_range and ".." in args.rev_range:
            start, end = args.rev_range.split("..", 1)
            end = end or "HEAD"
            return _run(start, end, end, f"range {args.rev_range}", skip_own=True)
        parser.print_help(sys.stderr)
        print("\nversion check: choose --staged or --range A..B.", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        # Fail closed: an internal error also blocks the commit.
        # フェイルクローズ方針: 内部エラー時もコミットを中止する。
        print(f"version check: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
