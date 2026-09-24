#!/usr/bin/env python3
"""Write a release, or start the next development version, in one command.
リリース、または次の開発版の開始を 1 コマンドで書き込む。

Two subcommands carry out the file edits of RELEASING.md:

``prepare X.Y.Z``
    Checklist steps 1-6: set ``X.Y.Z`` in ``pyproject.toml`` and
    ``lib/__init__.py``; set ``version`` and ``date-released`` in
    ``CITATION.cff``; set ``version`` (and ``year``) in the BibTeX block of
    both READMEs; turn ``## [Unreleased]`` of ``CHANGELOG.md`` into
    ``## [X.Y.Z] - DATE`` under a new empty ``[Unreleased]`` and update the
    link references; then run ``pytest``, ``ruff check .`` and
    ``check.py --verify``. With ``--commit`` it also commits
    ("Release vX.Y.Z") and creates the tag ``vX.Y.Z`` (steps 7-8).
``start-dev X.Y.Z``
    Step 13: set ``X.Y.Z.dev0`` in ``pyproject.toml`` and ``lib/__init__.py``,
    leaving ``CITATION.cff`` and the READMEs at the released number. With
    ``--commit`` it commits ("Start X.Y.Z development").

Nothing is ever pushed: pushing ``main`` and the tag, publishing the GitHub
Release, and archiving on Zenodo stay manual, and the command prints what is
left. Choosing the number and writing the changelog prose also stay manual;
``prepare`` refuses an empty ``[Unreleased]`` section.

Usage:
    python scripts/release.py prepare 2.1.0 [--date 2026-10-01] [--commit] [--skip-checks]
    python scripts/release.py start-dev 2.2.0 [--commit]

Exit codes: 0 = done, 1 = a precondition or a check failed, 2 = usage error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_versions as cv  # noqa: E402

PYPROJECT = cv.PYPROJECT
INIT = cv.INIT
CITATION = "CITATION.cff"
CHANGELOG = cv.CHANGELOG
READMES = cv.READMES
RELEASE_FILES = (PYPROJECT, INIT, CITATION, CHANGELOG) + READMES
DEV_FILES = (PYPROJECT, INIT)
BIBTEX_KEY = "@software{afm_nanofiber_analyzer"


class ReleaseError(Exception):
    """A precondition failed or a file does not have the expected shape."""


# ----------------------------------------------------------------------------
# Pure text transforms, unit-tested in tests/test_release.py
# ----------------------------------------------------------------------------

def _sub_once(pattern: str, repl: str, text: str, what: str, flags: int = re.MULTILINE) -> str:
    """Replace exactly one match, or raise `ReleaseError` naming `what`."""
    new, count = re.subn(pattern, repl, text, flags=flags)
    if count != 1:
        raise ReleaseError(f"expected exactly one {what}, found {count}")
    return new


def set_pyproject_version(text: str, version: str) -> str:
    """Set ``[project] version`` in pyproject.toml.
    pyproject.toml の ``version`` を設定する。
    """
    return _sub_once(r'^(version\s*=\s*")[^"]*(")', rf"\g<1>{version}\g<2>",
                     text, f'version = "..." line in {PYPROJECT}')


def set_init_version(text: str, version: str) -> str:
    """Set ``__version__`` in lib/__init__.py.
    lib/__init__.py の ``__version__`` を設定する。
    """
    return _sub_once(r'^(__version__\s*=\s*")[^"]*(")', rf"\g<1>{version}\g<2>",
                     text, f"__version__ line in {INIT}")


def set_citation(text: str, version: str, date: str) -> str:
    """Set ``version`` and ``date-released`` in CITATION.cff, keeping comments.
    CITATION.cff の ``version`` と ``date-released`` を設定する（注記は保つ）。
    """
    text = _sub_once(r'^(version:\s*")[^"]*(")', rf"\g<1>{version}\g<2>",
                     text, f"version line in {CITATION}")
    return _sub_once(r'^(date-released:\s*")[^"]*(")', rf"\g<1>{date}\g<2>",
                     text, f"date-released line in {CITATION}")


def set_readme_bibtex(text: str, version: str, year: str, name: str = "README") -> str:
    """Set ``version`` and ``year`` inside this software's BibTeX entry only.
    このソフト自身の BibTeX 項目の中だけで ``version`` と ``year`` を設定する。

    The READMEs also cite papers with their own ``year`` fields, so the edit is
    confined to the ``@software{afm_nanofiber_analyzer`` block.
    README は論文も ``year`` 付きで引用しているため、編集はこのソフトの
    ``@software{afm_nanofiber_analyzer`` ブロック内に限る。
    """
    start = text.find(BIBTEX_KEY)
    if start < 0 or text.count(BIBTEX_KEY) != 1:
        raise ReleaseError(f"expected exactly one {BIBTEX_KEY} entry in {name}")
    end = text.find("\n}", start)
    if end < 0:
        raise ReleaseError(f"unterminated {BIBTEX_KEY} entry in {name}")
    block = text[start:end]
    block = _sub_once(r"(version\s*=\s*\{)[^}]*(\})", rf"\g<1>{version}\g<2>",
                      block, f"version field in the BibTeX entry of {name}")
    block = _sub_once(r"(year\s*=\s*\{)[^}]*(\})", rf"\g<1>{year}\g<2>",
                      block, f"year field in the BibTeX entry of {name}")
    return text[:start] + block + text[end:]


def roll_changelog(text: str, version: str, date: str, previous: Optional[str]) -> str:
    """Turn ``[Unreleased]`` into ``[version] - date`` and update the links.
    ``[Unreleased]`` を ``[version] - date`` に変え、リンク参照を更新する。

    Parameters
    ----------
    previous
        The release before this one, "X.Y.Z", or None for a first release.
        この前のリリース（"X.Y.Z"）。初回リリースなら None。

    Raises
    ------
    ReleaseError
        If the section is missing or empty, the version already has a
        section, or the ``[Unreleased]`` link reference is missing.
    """
    if not cv.unreleased_section(text).strip():
        raise ReleaseError(
            f"the '## [Unreleased]' section of {CHANGELOG} is empty; write what "
            "this release changes before releasing it")
    if re.search(rf"^##\s+\[{re.escape(version)}\]", text, re.MULTILINE):
        raise ReleaseError(f"{CHANGELOG} already has a section for {version}")
    text = _sub_once(r"^##\s+\[Unreleased\][^\n]*$",
                     f"## [Unreleased]\n\n## [{version}] - {date}",
                     text, f"'## [Unreleased]' heading in {CHANGELOG}",
                     flags=re.MULTILINE | re.IGNORECASE)
    m = re.search(r"^\[Unreleased\]:\s*(\S+?)/compare/\S+$", text, re.MULTILINE)
    if not m:
        raise ReleaseError(f"no '[Unreleased]: .../compare/...' link in {CHANGELOG}")
    base = m.group(1)
    target = (f"{base}/compare/v{previous}...v{version}" if previous
              else f"{base}/releases/tag/v{version}")
    return text[:m.start()] + (
        f"[Unreleased]: {base}/compare/v{version}...HEAD\n[{version}]: {target}"
    ) + text[m.end():]


def _lf(files: Dict[str, str]) -> Dict[str, str]:
    """Normalise CRLF to LF so the line-anchored patterns match.
    行頭・行末で照合するパターンが一致するよう、CRLF を LF にそろえる。

    The working copies on Windows are CRLF, and ``$`` does not match before
    ``\\r``; `_write_files` puts each file's own line endings back.
    Windows の作業コピーは CRLF で、``$`` は ``\\r`` の前で一致しない。
    `_write_files` が各ファイル自身の改行を戻す。
    """
    return {path: text.replace("\r\n", "\n") for path, text in files.items()}


def release_edits(files: Dict[str, str], version: str, date: str,
                  previous: Optional[str]) -> Dict[str, str]:
    """Return the edited text of every file a release changes.
    リリースで変わる各ファイルの編集後テキストを返す。
    """
    files = _lf(files)
    year = date[:4]
    out = {
        PYPROJECT: set_pyproject_version(files[PYPROJECT], version),
        INIT: set_init_version(files[INIT], version),
        CITATION: set_citation(files[CITATION], version, date),
        CHANGELOG: roll_changelog(files[CHANGELOG], version, date, previous),
    }
    for readme in READMES:
        out[readme] = set_readme_bibtex(files[readme], version, year, readme)
    return out


def dev_edits(files: Dict[str, str], version: str) -> Dict[str, str]:
    """Return the edited text of the two files a development start changes.
    開発版の開始で変わる 2 ファイルの編集後テキストを返す。
    """
    files = _lf(files)
    return {
        PYPROJECT: set_pyproject_version(files[PYPROJECT], version),
        INIT: set_init_version(files[INIT], version),
    }


# ----------------------------------------------------------------------------
# Suggesting the next version (pure), unit-tested in tests/test_release.py
# ----------------------------------------------------------------------------

MAJOR, MINOR, PATCH = "MAJOR", "MINOR", "PATCH"
_LEVELS = (PATCH, MINOR, MAJOR)
CLI = "cli.py"
_REQUIRES_PYTHON_RE = re.compile(r'^requires-python\s*=\s*">=\s*(\d+)\.(\d+)', re.MULTILINE)


_REMOVE_IN_RE = re.compile(r"#\s*remove-in:\s*(\d+\.\d+\.\d+)")


def due_removals(files: Dict[str, str], version: str) -> List[str]:
    """``path:line`` of every ``# remove-in: X.Y.Z`` marker due by `version`.
    `version` までに期限を迎える ``# remove-in: X.Y.Z`` 印の ``パス:行``。

    A deprecated alias is kept with such a marker; the release that reaches
    the marked version must delete it rather than carry it silently on.
    非推奨の別名はこの印付きで残す。印の版に達するリリースは、黙って持ち越さず
    に削除しなければならない。
    """
    target = cv.parse_version(version)
    out = []
    for path in sorted(files):
        for lineno, line in enumerate(files[path].splitlines(), 1):
            m = _REMOVE_IN_RE.search(line)
            if m and cv.parse_version(m.group(1)) <= target:
                out.append(f"{path}:{lineno}: {line.strip()}")
    return out


def public_names(source: str) -> set:
    """Top-level names a module defines without a leading underscore.
    モジュールがアンダースコア無しで定義するトップレベルの名前。

    Keys of a module-level ``_DEPRECATED_ALIASES`` dict count as defined:
    the module still resolves them (PEP 562 ``__getattr__``), so removing the
    assignment in favour of an alias is not an API removal.
    モジュール直下の ``_DEPRECATED_ALIASES`` 辞書のキーも定義済みとみなす。
    モジュールは引き続きそれを解決する（PEP 562 の ``__getattr__``）ため、
    代入を別名に置き換えても API の削除にはならない。
    """
    aliases = cv.module_constant(source, "_DEPRECATED_ALIASES")
    alias_names = set(aliases) if isinstance(aliases, dict) else set()
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return {n for n in names if not n.startswith("_")} | alias_names


def cli_options(source: str) -> set:
    """``"subcommand"`` and ``"subcommand --flag"`` entries of cli.py.
    cli.py の ``"サブコマンド"`` と ``"サブコマンド --フラグ"`` の一覧。

    A parser variable is tied to its subcommand by the assignment
    ``p = sub.add_parser("name", ...)``; flags added to it are recorded under
    that name. Positional arguments are not options and are left out.
    パーサ変数は ``p = sub.add_parser("name", ...)`` の代入でサブコマンドに
    結び付け、そこへ追加したフラグをその名前の下に記録する。
    """
    import ast
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    owner: Dict[str, str] = {}
    out = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "add_parser" and node.value.args
                and isinstance(node.value.args[0], ast.Constant)):
            name = node.value.args[0].value
            out.add(name)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    owner[target.id] = name
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in owner):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and str(arg.value).startswith("--"):
                    out.add(f"{owner[node.func.value.id]} {arg.value}")
    return out


def suggest_level(
    before: Dict[str, Optional[str]],
    after: Dict[str, Optional[str]],
    added_paths: Sequence[str],
    goldens_changed: bool,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Classify the changes since the last release by the RELEASING.md table.
    前回リリースからの変更を RELEASING.md の表で分類する。

    Parameters
    ----------
    before, after
        Path to text at the last release and now, for the paths
        `suggest_paths` names (None when absent on that side).
        前回リリース時点と現在の、`suggest_paths` の各パスのテキスト（無ければ None）。
    added_paths
        Files added since the last release.
        前回リリース以降に追加されたファイル。
    goldens_changed
        Whether ``tests/strict_regression_golden.json`` changed.
        ``tests/strict_regression_golden.json`` が変わったかどうか。

    Returns
    -------
    tuple
        ``(level, reasons)``: the highest level any signal reached, and one
        ``(level, reason)`` per signal. ``"NOTE"`` reasons do not raise the
        level.
        ``(level, reasons)``。信号が達した最も高い段階と、信号ごとの
        ``(段階, 理由)``。``"NOTE"`` の理由は段階を上げない。
    """
    reasons: List[Tuple[str, str]] = []

    def text(side, path):
        return side.get(path) or ""

    # Parameter files.
    old_f = cv.dataclass_fields(text(before, cv.PIPELINE), "ProcParams") or []
    new_f = cv.dataclass_fields(text(after, cv.PIPELINE), "ProcParams") or []
    gone = [f for f in old_f if f not in new_f]
    added = [f for f in new_f if f not in old_f]
    if gone:
        reasons.append((MAJOR, "ProcParams field(s) removed or renamed: " + ", ".join(gone)
                        + " (a _param.json carrying them no longer loads)"))
    if added:
        reasons.append((MINOR, "ProcParams field(s) added: " + ", ".join(added)))

    # Bundle format.
    old_fmt = cv.module_constant(text(before, cv.SCHEMA), "BUNDLE_FORMAT_VERSION")
    new_fmt = cv.module_constant(text(after, cv.SCHEMA), "BUNDLE_FORMAT_VERSION")
    if old_fmt and new_fmt and old_fmt != new_fmt:
        reasons.append((MINOR, f"bundle format {old_fmt} -> {new_fmt} (the last "
                        "release cannot read the new bundles)"))
    old_sup = cv.module_constant(text(before, cv.SCHEMA), "SUPPORTED_BUNDLE_VERSIONS") or ()
    new_sup = cv.module_constant(text(after, cv.SCHEMA), "SUPPORTED_BUNDLE_VERSIONS") or ()
    dropped = [v for v in old_sup if v not in new_sup]
    if dropped:
        reasons.append((MAJOR, "bundle format(s) no longer readable: " + ", ".join(dropped)))

    # Public lib/ API.
    for path in sorted(set(before) | set(after)):
        if not (path.startswith("lib/") and path.endswith(".py")):
            continue
        if before.get(path) is None:
            continue
        if after.get(path) is None:
            reasons.append((MAJOR, f"module {path} removed"))
            continue
        lost = sorted(public_names(before[path]) - public_names(after[path]))
        if lost:
            reasons.append((MAJOR, f"public name(s) removed from {path}: " + ", ".join(lost)
                            + " (MAJOR if listed in AGENTS.md §8.7 or used outside lib/;"
                            " an alias keeps them working)"))

    # CLI.
    old_cli, new_cli = cli_options(text(before, CLI)), cli_options(text(after, CLI))
    if old_cli - new_cli:
        reasons.append((MAJOR, "CLI option(s) removed: " + ", ".join(sorted(old_cli - new_cli))))
    if new_cli - old_cli:
        reasons.append((MINOR, "CLI option(s) added: " + ", ".join(sorted(new_cli - old_cli))))

    # Supported Python.
    old_py = _REQUIRES_PYTHON_RE.search(text(before, PYPROJECT))
    new_py = _REQUIRES_PYTHON_RE.search(text(after, PYPROJECT))
    if old_py and new_py and tuple(map(int, new_py.groups())) > tuple(map(int, old_py.groups())):
        reasons.append((MAJOR, f"requires-python raised {'.'.join(old_py.groups())} -> "
                        f"{'.'.join(new_py.groups())} (RELEASING.md lists dropping a "
                        "Python as MAJOR)"))

    # New GUI plugins.
    plugins = [p for p in added_paths
               if re.fullmatch(r"guis/GUI[^/]*\.py", p)]
    if plugins:
        reasons.append((MINOR, "GUI plugin(s) added: " + ", ".join(sorted(plugins))))

    # Changelog headings the author already wrote.
    unreleased = cv.unreleased_section(text(after, CHANGELOG))
    if re.search(r"^###\s+Added", unreleased, re.MULTILINE):
        reasons.append((MINOR, "CHANGELOG [Unreleased] has an '### Added' section"))
    if re.search(r"^###\s+Removed", unreleased, re.MULTILINE):
        reasons.append(("NOTE", "CHANGELOG [Unreleased] has a '### Removed' section: "
                        "MAJOR if something users call stops working"))
    if goldens_changed:
        reasons.append(("NOTE", "the strict-regression goldens changed, so results "
                        "change: the CHANGELOG entry must say so (PATCH or MINOR, "
                        "RELEASING.md)"))

    level = PATCH
    for lvl, _ in reasons:
        if lvl in _LEVELS and _LEVELS.index(lvl) > _LEVELS.index(level):
            level = lvl
    return level, reasons


def next_version(last: str, level: str) -> str:
    """The release number one `level` step above `last` ("X.Y.Z").
    `last`（"X.Y.Z"）から `level` を 1 段上げたリリース番号。
    """
    major, minor, patch = (int(p) for p in last.split("."))
    if level == MAJOR:
        return f"{major + 1}.0.0"
    if level == MINOR:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ----------------------------------------------------------------------------
# Repository side
# ----------------------------------------------------------------------------

def _root() -> str:
    return cv._repo_root()


def _read_files(paths: Sequence[str]) -> Dict[str, str]:
    out = {}
    for path in paths:
        with open(os.path.join(_root(), path), "rb") as f:
            out[path] = f.read().decode("utf-8")
    return out


def _write_files(files: Dict[str, str]) -> None:
    """Write texts back, keeping each file's line endings."""
    for path, text in files.items():
        full = os.path.join(_root(), path)
        with open(full, "rb") as f:
            crlf = b"\r\n" in f.read()
        text = text.replace("\r\n", "\n")
        with open(full, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
            f.write(text)


def _tracked_python() -> Dict[str, str]:
    """Text of every tracked ``.py`` file in the working tree, where markers live."""
    out = {}
    for path in (_git("ls-files", "*.py") or "").split():
        full = os.path.join(_root(), path)
        if os.path.exists(full):
            with open(full, "rb") as f:
                out[path] = f.read().decode("utf-8", "replace")
    return out


def _git(*args: str) -> str:
    out = cv._git(*args)
    return out or ""


def _preconditions(target: str, paths: Sequence[str]) -> Optional[str]:
    """Check the tree and the version order; return the last release."""
    if cv.parse_version(target) is None:
        raise ReleaseError(f"{target!r} is not a version of the form X.Y.Z")
    dirty = _git("status", "--porcelain", "--untracked-files=no", "--", *paths).strip()
    if dirty:
        raise ReleaseError(
            "these files have uncommitted changes; commit or stash them first:\n"
            + dirty)
    last = cv._last_release("HEAD")
    if last and cv.parse_version(target) <= cv.parse_version(last):
        raise ReleaseError(f"{target} is not later than the last release v{last}")
    return last


def _run_checks() -> List[str]:
    """Run RELEASING.md step 6; return the commands that failed."""
    failed = []
    for cmd in ([sys.executable, "-m", "pytest", "-q"],
                [sys.executable, "-m", "ruff", "check", "."],
                [sys.executable, "check.py", "--verify"]):
        print("$ " + " ".join(os.path.basename(c) if i == 0 else c
                              for i, c in enumerate(cmd)), flush=True)
        if subprocess.run(cmd, cwd=_root()).returncode != 0:
            failed.append(" ".join(cmd[1:]))
    return failed


def _commit(paths: Sequence[str], message: str) -> None:
    """Commit `paths` through a message file, as AGENTS.md requires."""
    msg_dir = os.path.join(_root(), ".tmp")
    os.makedirs(msg_dir, exist_ok=True)
    msg_path = os.path.join(msg_dir, "release_commit_msg.txt")
    with open(msg_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(message)
    _git("add", "--", *paths)
    proc = subprocess.run(["git", "-C", _root(), "commit", "-F", msg_path])
    if proc.returncode != 0:
        raise ReleaseError("git commit failed (see the hook output above)")


def cmd_prepare(args: argparse.Namespace) -> int:
    version = args.version
    date = args.date or _dt.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ReleaseError(f"--date must be YYYY-MM-DD, got {date!r}")
    last = _preconditions(version, RELEASE_FILES)
    if _git("tag", "--list", f"v{version}").strip():
        raise ReleaseError(f"tag v{version} already exists")
    current = cv.pyproject_version(_read_files([PYPROJECT])[PYPROJECT]) or ""
    if cv.parse_version(current) and cv.parse_version(current) > cv.parse_version(version):
        raise ReleaseError(
            f"{version} is lower than the development version {current}")
    due = due_removals(_tracked_python(), version)
    if due:
        raise ReleaseError(
            f"these are marked for removal in {version} or earlier; delete them "
            "(and say so in CHANGELOG.md under '### Removed') before releasing:\n  "
            + "\n  ".join(due))

    edits = release_edits(_read_files(RELEASE_FILES), version, date, last)
    _write_files(edits)
    print(f"Set {version} ({date}) in: " + ", ".join(RELEASE_FILES))

    if not args.skip_checks:
        failed = _run_checks()
        if failed:
            print("\nChecks failed: " + "; ".join(failed)
                  + "\nThe edits are left in place; fix the failure and run the "
                  "checks again, or restore the files with git.", file=sys.stderr)
            return 1

    if args.commit:
        _commit(RELEASE_FILES, f"Release v{version}\n")
        _git("tag", f"v{version}")
        print(f"\nCommitted and tagged v{version}.")
        steps = [f"git push origin main v{version}"]
    else:
        steps = [f"review the diff, commit the files above as 'Release v{version}', "
                 f"and run: git tag v{version}",
                 f"git push origin main v{version}"]
    nxt = cv.parse_version(version)
    steps += [
        f"create the GitHub Release for v{version} from its CHANGELOG section "
        "(Zenodo archives it when the integration is on; then add the DOI to "
        f"{CITATION})",
        f"python scripts/release.py start-dev {nxt[0]}.{nxt[1]}.{nxt[2] + 1} --commit "
        f"(or {nxt[0]}.{nxt[1] + 1}.0 if features are planned)",
    ]
    print("\nLeft to do:")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step}")
    return 0


def cmd_start_dev(args: argparse.Namespace) -> int:
    dev = f"{args.version}.dev0"
    _preconditions(args.version, DEV_FILES)
    last = cv._last_release("HEAD")
    if last and cv.parse_version(dev) <= cv.parse_version(last):
        raise ReleaseError(f"{dev} is not later than the last release v{last}")
    _write_files(dev_edits(_read_files(DEV_FILES), dev))
    print(f"Set {dev} in: " + ", ".join(DEV_FILES)
          + f" ({CITATION} and the READMEs keep the released number).")
    if args.commit:
        _commit(DEV_FILES, f"Start {args.version} development\n")
        print("Committed. Push it with: git push origin main")
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    last = cv._last_release("HEAD")
    if not last:
        raise ReleaseError("no vX.Y.Z tag is reachable from HEAD; nothing to compare with")
    tag = f"v{last}"
    lib_files = set()
    for rev in (tag, "HEAD"):
        listing = _git("ls-tree", "-r", "--name-only", rev, "--", "lib") or ""
        lib_files.update(p for p in listing.split() if p.endswith(".py"))
    paths = sorted(lib_files | {cv.PIPELINE, cv.SCHEMA, CLI, PYPROJECT, CHANGELOG})
    before = {p: cv._read(tag, p) for p in paths}
    after = {p: cv._read("HEAD", p) for p in paths}
    added = (_git("diff", "--name-only", "--diff-filter=A", f"{tag}..HEAD") or "").split()
    changed = (_git("diff", "--name-only", f"{tag}..HEAD") or "").split()
    goldens = "tests/strict_regression_golden.json" in changed

    level, reasons = suggest_level(before, after, added, goldens)
    proposal = next_version(last, level)
    print(f"Changes in {tag}..HEAD (committed state only):")
    for lvl, why in reasons or [(PATCH, "no MAJOR or MINOR signal: fixes and documentation")]:
        print(f"  [{lvl}] {why}")
    print()
    print(f"Suggested: {level} -> {proposal}")

    current = cv.pyproject_version(after.get(PYPROJECT) or "") or ""
    cur = cv.parse_version(current)
    want = cv.parse_version(proposal)
    if cur and want and cur[:3] < want[:3]:
        print(f"The development version {current} is below {proposal}: run "
              f"'python scripts/release.py start-dev {proposal} --commit'.")
    elif cur:
        print(f"The development version {current} already points at "
              f"{'.'.join(map(str, cur[:3]))}.")
    due = due_removals(_tracked_python(), proposal)
    if due:
        print(f"Marked for removal by {proposal} (release.py prepare will refuse "
              "until they are deleted):")
        for item in due:
            print(f"  {item}")
    print("This is a proposal from the signals above; the number is your decision "
          "(RELEASING.md, MAJOR / MINOR / PATCH).")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="write release X.Y.Z (RELEASING.md steps 1-6, 7-8 with --commit)")
    p.add_argument("version", help="the release number, X.Y.Z")
    p.add_argument("--date", help="release date YYYY-MM-DD (default: today)")
    p.add_argument("--commit", action="store_true", help="also commit and create the tag")
    p.add_argument("--skip-checks", action="store_true",
                   help="do not run pytest / ruff / check.py --verify")
    p.set_defaults(func=cmd_prepare)
    d = sub.add_parser("start-dev", help="set X.Y.Z.dev0 after a release (RELEASING.md step 13)")
    d.add_argument("version", help="the next planned release, X.Y.Z")
    d.add_argument("--commit", action="store_true", help="also commit")
    d.set_defaults(func=cmd_start_dev)
    g = sub.add_parser("suggest", help="propose the next version from the changes since the last tag")
    g.set_defaults(func=cmd_suggest)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.func(args)
    except (ReleaseError, RuntimeError) as exc:
        print(f"release: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
