#!/usr/bin/env python3
"""Tell the AI coding agent when an edit makes a code-explaining document stale.
AI コーディングエージェントに、編集でコード解説文書が古くなったことを知らせる。

What this file is
-----------------
Not part of the AFM analysis software, and never imported by it. It is
configuration for Claude Code, the AI coding agent used on this repository.
`.claude/settings.json` attaches it to `PostToolUse` for the file-editing tools.

このファイルは AFM 解析ソフトウェアの一部ではなく、本体から import されることも
ない。本リポジトリで使う AI コーディングエージェント Claude Code の設定である。
`.claude/settings.json` でファイル編集ツールの `PostToolUse` に登録してある。

Why it exists
-------------
Two document pairs explain the analysis with the code that performs it:
`docs/algorithms.md` (the four preprocessing stages and the centerline) and
`docs/gui04_measurements.md` (GUI04's centerline and every value it shows),
each with a Japanese counterpart. The pre-commit hook and CI catch a stale
page, but only at commit time, after the agent has moved on. This hook reports
the drift right after the edit that caused it, while the change is still in the
agent's context, so the documents are updated as part of the same change.

コードとともに解析を説明する文書が 2 組ある。`docs/algorithms.md`（前処理 4 段階と
中心線）と `docs/gui04_measurements.md`（GUI04 の中心線と表示する全数値）で、
それぞれ日本語版を持つ。古くなったページは pre-commit フックと CI が捕らえるが、
それはコミット時であり、エージェントが次の作業へ移った後である。このフックは
ずれを生んだ編集の直後に報告する。変更がまだエージェントの文脈にあるうちに伝え、
文書の更新を同じ変更の一部にするためである。

How it decides
--------------
After an Edit / Write / MultiEdit / NotebookEdit of a project file:

- GUI04 document: if the file holds a symbol that document quotes,
  `scripts/check_gui04_docs.drifted_symbols` compares the quoted symbols'
  fingerprints (comments and docstrings ignored) with
  `tests/gui04_doc_manifest.json`.
- Algorithm document: if the file is one of the fingerprinted algorithm modules,
  its module fingerprint is compared with `tests/algorithm_doc_manifest.json`;
  and if the algorithm document quotes code from the file, every such excerpt is
  compared with the code (`scripts/doc_excerpts.check_pair_excerpts`).

A comment-only edit reports nothing. Each finding is reported once per session.

プロジェクト内のファイルを Edit / Write / MultiEdit / NotebookEdit した後、

- GUI04 文書：そのファイルが文書の引用するシンボルを含むなら、
  `scripts/check_gui04_docs.drifted_symbols` が引用シンボルの指紋（コメントと
  docstring を無視）を `tests/gui04_doc_manifest.json` と比べる。
- アルゴリズム文書：そのファイルが指紋化対象のアルゴリズムモジュールなら、
  モジュールの指紋を `tests/algorithm_doc_manifest.json` と比べる。さらに文書が
  そのファイルのコードを引用していれば、各コード片をコードと照合する
  （`scripts/doc_excerpts.check_pair_excerpts`）。

コメントだけの編集では何も報告しない。各指摘はセッションごとに 1 回だけ報告する。

The hook never blocks and exits 0 on any error: it is a reminder, and the
pre-commit hook and CI remain the enforcement.
フックは決して処理を止めず、エラー時も終了コード 0 で抜ける。これは通知であり、
強制するのは引き続き pre-commit フックと CI である。
"""

import importlib.util
import json
import os
import re
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

ALGORITHM_DOCS = ("docs/algorithms.md", "docs/algorithms.ja.md")
ALGORITHM_MANIFEST = "tests/algorithm_doc_manifest.json"


def _project_root() -> str:
    """Return the project directory Claude Code runs in."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root:
        return root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_script(root: str, name: str):
    """Import a module from `scripts/` by path."""
    path = os.path.join(root, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _relative(root: str, file_path: str):
    """Return `file_path` relative to the project with ``/`` separators."""
    try:
        rel = os.path.relpath(os.path.abspath(file_path), os.path.abspath(root))
    except ValueError:
        # Different drive on Windows: the file is outside the project.
        # Windows で別ドライブ: ファイルはプロジェクト外にある。
        return None
    if rel.startswith(".."):
        return None
    return rel.replace(os.sep, "/")


def _sections_quoting(excerpts, text, keys):
    """Map each symbol key to the headings of the sections that quote it."""
    found = {k: [] for k in keys}
    heading = ""
    in_fence = False
    first = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            first = in_fence
            continue
        if not in_fence:
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
            continue
        if first:
            first = False
            match = excerpts._SOURCE_HEADER.match(line.strip())
            if not match:
                continue
            for name in (n.strip() for n in match.group(2).split(",")):
                key = f"{match.group(1)}::{name}"
                if key in found and heading not in found[key]:
                    found[key].append(heading)
    return found


def _gui04_findings(root, rel):
    """Return ``(state key, message)`` pairs for the GUI04 document."""
    checker = _load_script(root, "check_gui04_docs")
    if rel not in checker.watched_paths():
        return []
    drifted = checker.drifted_symbols(rel)
    if not drifted:
        return []
    text = checker.read_worktree(checker.DOC_EN) or ""
    sections = _sections_quoting(checker, text, drifted)
    out = []
    for key in drifted:
        where = "; ".join(sections.get(key) or []) or "no section found"
        out.append((
            f"gui04:{key}",
            f"- docs/gui04_measurements.md: {key} changed (quoted in: {where}). "
            "Update prose and excerpts in both language versions, then run "
            "`.venv/Scripts/python.exe scripts/check_gui04_docs.py --update` "
            "and `.venv/Scripts/python.exe scripts/check_gui04_docs.py`.",
        ))
    return out


def _algorithm_findings(root, rel):
    """Return ``(state key, message)`` pairs for the algorithm document."""
    excerpts = _load_script(root, "doc_excerpts")
    out = []

    manifest_text = excerpts.read_worktree(ALGORITHM_MANIFEST)
    recorded = json.loads(manifest_text).get("modules", {}) if manifest_text else {}
    if rel in recorded:
        source = excerpts.read_worktree(rel)
        digest = excerpts.module_digest(source) if source is not None else None
        if digest != recorded[rel]:
            out.append((
                f"algorithms-module:{rel}:{digest}",
                f"- docs/algorithms.md: {rel} changed what it computes. Reread "
                "the sections explaining it in both language versions, update "
                "them (prose and excerpts), then run "
                "`.venv/Scripts/python.exe tests/test_algorithm_docs.py --update`.",
            ))

    docs = {name: excerpts.read_worktree(name) for name in ALGORITHM_DOCS}
    if all(text is not None for text in docs.values()):
        quoted_paths = {
            excerpts.split_symbol(key)[0]
            for keys, _lines in excerpts.excerpts(docs[ALGORITHM_DOCS[0]])
            for key in keys
        }
        if rel in quoted_paths:
            problems, _quoted = excerpts.check_pair_excerpts(docs)
            for problem in problems:
                if f"{rel}::" in problem:
                    out.append((
                        f"algorithms-excerpt:{problem}",
                        f"- {problem}. Update the excerpt, and the explanation "
                        "around it, in both docs/algorithms.md and "
                        "docs/algorithms.ja.md.",
                    ))
    return out


def _state_path(root: str, payload: dict) -> str:
    """Return the per-session file recording what was already reported."""
    sid = re.sub(r"[^A-Za-z0-9_-]", "_", str(payload.get("session_id") or "default"))[:80]
    return os.path.join(root, ".tmp", "hook_state", f"doc_code_reminder_{sid}.json")


def main() -> int:
    """Read the PostToolUse payload and emit a reminder when needed."""
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if payload.get("tool_name") not in EDIT_TOOLS:
            return 0
        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not file_path:
            return 0
        root = _project_root()
        rel = _relative(root, file_path)
        if rel is None or not rel.endswith(".py"):
            return 0

        findings = _gui04_findings(root, rel) + _algorithm_findings(root, rel)
        if not findings:
            return 0

        state_file = _state_path(root, payload)
        try:
            with open(state_file, encoding="utf-8") as fh:
                reported = set(json.load(fh))
        except (OSError, ValueError):
            reported = set()
        fresh = [(key, message) for key, message in findings if key not in reported]
        if not fresh:
            return 0
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as fh:
            json.dump(sorted(reported | {key for key, _ in fresh}), fh)

        lines = [
            "This edit changed code that a document explains with its code "
            "(comments and docstrings are ignored by this check):",
            *(message for _, message in fresh),
            "Updating the documents is part of this change (AGENTS.md §8.13, "
            "§8.14). If the edit is not finished yet, do it once it is.",
        ]
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(lines),
            }
        }))
    except Exception:
        # A reminder must never break the session.
        # 通知がセッションを壊してはならない。
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
