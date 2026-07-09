#!/usr/bin/env python3
"""Scanner that blocks commits and pushes containing sensitive information.
コミット・push 前に機微情報を検査し、問題があれば中止する安全装置スクリプト。

Invoked by ``.githooks/pre-commit`` (scans the staged diff via ``--staged``)
and ``.githooks/pre-push`` (enable both once per clone with
``git config core.hooksPath .githooks``). In pre-push mode it reads the ref
updates git passes on stdin, collects the commits that would become public,
and scans every added line and commit message for:

- credential patterns (private keys, AWS/GitHub/Slack/Google/API tokens,
  quoted password/secret assignments)
- e-mail addresses (placeholder and no-reply addresses are allowed)
- machine-local absolute paths under a user profile directory
- locally defined blocked words (NG words)

Local, never-committed configuration (looked up via ``git rev-parse
--git-path``, so the block list itself can never leak):

- ``.git/info/sensitive_words.txt`` — blocked words/phrases, one per line,
  case-insensitive substring match, UTF-8, ``#`` comments allowed.
- ``.git/info/sensitive_allow.txt`` — suppression regexes, one per line;
  a line whose text matches any regex is not flagged.

A flagged line can also be suppressed in place by appending the marker
``sensitive-ok`` to it.

Manual scans without committing or pushing:
    python scripts/check_sensitive.py --staged
    python scripts/check_sensitive.py --range origin/main..HEAD

Exit codes: 0 = clean, 1 = findings (the commit/push is blocked), 2 = usage
or git error (also blocked; the check fails closed).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

# Marker that suppresses all findings on the line that contains it.
ALLOW_MARKER = "sensitive-ok"

# All-zero SHA sent by git for ref creation/deletion in the pre-push protocol.
_ZERO_SHA_RE = re.compile(r"^0+$")

_MAX_EXCERPT = 160

# Placeholder user names that may appear in documentation examples; paths
# containing them are not treated as leaks of a real local environment.
_PLACEHOLDER_USER_HINTS = ("<", ">", "%", "$", "{", "}")
_PLACEHOLDER_USERNAMES = {
    "user",
    "username",
    "yourname",
    "your_name",
    "your-name",
    "someone",
    "public",
    "default",
    "runner",
    "runneradmin",
    "vagrant",
}

# E-mail addresses that are intentionally public or placeholders.
_ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "users.noreply.github.com",
}
_ALLOWED_EMAIL_LOCALS = {"noreply", "no-reply", "donotreply", "do-not-reply"}
# AGENTS.md uses this literal as its documentation placeholder.
_ALLOWED_EMAILS = {"your@email.com"}


def _username_allowed(name: str) -> bool:
    """Return True if a path user name is a documentation placeholder.
    パス中のユーザー名がドキュメント用プレースホルダなら True を返す。
    """
    low = name.strip().lower()
    if any(hint in low for hint in _PLACEHOLDER_USER_HINTS):
        return True
    return low in _PLACEHOLDER_USERNAMES or low.startswith("your")


def _email_allowed(email: str) -> bool:
    """Return True if an e-mail address is a known placeholder or no-reply.
    メールアドレスが既知のプレースホルダまたは no-reply 系なら True を返す。
    """
    low = email.lower()
    if low in _ALLOWED_EMAILS:
        return True
    local, _, domain = low.partition("@")
    if domain in _ALLOWED_EMAIL_DOMAINS or domain.endswith(".example.com"):
        return True
    return local in _ALLOWED_EMAIL_LOCALS


@dataclass(frozen=True)
class Rule:
    """One detection rule: id, compiled pattern, and an optional allower.
    検出ルール 1 件(ID・正規表現・許可判定関数)を表す。
    """

    rule_id: str
    pattern: re.Pattern[str]
    message: str
    # Returns True when the specific match is acceptable (e.g. placeholder).
    allowed: Callable[[re.Match[str]], bool] | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        "private-key",
        re.compile(r"-----BEGIN\s+(?:[A-Z]+\s+)*PRIVATE KEY(?: BLOCK)?-----"),
        "private key block",
    ),
    Rule(
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key ID",
    ),
    Rule(
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,})\b"),
        "GitHub token",
    ),
    Rule(
        "slack-token",
        re.compile(r"\bxox[abeprs]-[A-Za-z0-9-]{10,}\b"),
        "Slack token",
    ),
    Rule(
        "google-api-key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
        "Google API key",
    ),
    Rule(
        "secret-key-token",
        re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"),
        "API secret key (sk-...)",
    ),
    Rule(
        "generic-credential",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token"
            r"|auth[_-]?token|client[_-]?secret)\b\s*[:=]\s*[\"'][^\"']{6,}[\"']"
        ),
        "quoted credential assignment",
    ),
    Rule(
        "email-address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}\b"),
        "e-mail address",
        allowed=lambda m: _email_allowed(m.group(0)),
    ),
    Rule(
        "windows-user-path",
        re.compile(r"(?i)(?<![\w.-])[a-z]:[\\/]users[\\/]([^\\/:*?\"'<>|\s]{1,64})"),
        "local Windows user-profile path",
        allowed=lambda m: _username_allowed(m.group(1)),
    ),
    Rule(
        "unix-home-path",
        re.compile(r"(?<![\w.-])/(?:home|Users)/([A-Za-z0-9._-]{2,64})\b"),
        "local Unix/macOS home path",
        allowed=lambda m: _username_allowed(m.group(1)),
    ),
)


@dataclass(frozen=True)
class Finding:
    """One detected problem in the outgoing changes.
    送信予定の変更内容から検出された問題 1 件を表す。
    """

    commit: str
    location: str
    rule_id: str
    message: str
    excerpt: str


def _git(*args: str) -> bytes:
    """Run a git command and return stdout bytes; raise on failure.
    git コマンドを実行して標準出力のバイト列を返す(失敗時は例外)。
    """
    res = subprocess.run(["git", *args], capture_output=True)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return res.stdout


def _object_exists(sha: str) -> bool:
    """Return True if the commit object exists in the local repository.
    コミットオブジェクトがローカルリポジトリに存在すれば True を返す。
    """
    res = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True
    )
    return res.returncode == 0


def _decode_line(raw: bytes) -> str:
    """Decode one diff line, tolerating the encodings used in this project.
    このプロジェクトで現れうるエンコーディングを許容して diff の 1 行を復号する。
    """
    # Try UTF-8 first, then cp932 for files exported on Japanese Windows;
    # latin-1 is a byte-preserving last resort so scanning never fails.
    # まず UTF-8、次に日本語 Windows 由来ファイル向けの cp932、最後に
    # バイト値を保存する latin-1 で復号し、検査自体が失敗しないようにする。
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _local_config_lines(name: str) -> list[str]:
    """Read a local (never committed) config file from the git directory.
    git ディレクトリ内のローカル設定ファイル(コミット対象外)を読み込む。
    """
    try:
        path = _git("rev-parse", "--git-path", f"info/{name}").decode().strip()
    except RuntimeError:
        return []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    lines: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            lines.append(s)
    return lines


class Scanner:
    """Applies all rules, NG words, and suppression settings to text lines.
    全ルール・NG ワード・抑制設定をテキスト行に適用する検査器。
    """

    def __init__(self) -> None:
        self.ng_words = [w.casefold() for w in _local_config_lines("sensitive_words.txt")]
        self.allow_res: list[re.Pattern[str]] = []
        for raw in _local_config_lines("sensitive_allow.txt"):
            try:
                self.allow_res.append(re.compile(raw))
            except re.error as exc:
                print(
                    f"sensitive-info check: ignoring invalid allow regex "
                    f"{raw!r}: {exc}",
                    file=sys.stderr,
                )

    def _suppressed(self, text: str) -> bool:
        if ALLOW_MARKER in text:
            return True
        return any(rx.search(text) for rx in self.allow_res)

    def scan_text(self, text: str, commit: str, location: str) -> list[Finding]:
        """Scan one line of text and return the findings for it.
        テキスト 1 行を検査し、検出結果のリストを返す。
        """
        if not text or self._suppressed(text):
            return []
        excerpt = text.strip()
        if len(excerpt) > _MAX_EXCERPT:
            excerpt = excerpt[:_MAX_EXCERPT] + "..."
        findings: list[Finding] = []
        for rule in RULES:
            for m in rule.pattern.finditer(text):
                if rule.allowed is not None and rule.allowed(m):
                    continue
                findings.append(
                    Finding(commit, location, rule.rule_id, rule.message, excerpt)
                )
                break  # one finding per rule per line is enough
        folded = text.casefold()
        for word in self.ng_words:
            if word in folded:
                findings.append(
                    Finding(commit, location, "ng-word", f"blocked word: {word}", excerpt)
                )
        return findings

    def scan_diff(self, diff: bytes, commit: str) -> list[Finding]:
        """Scan the added lines (and touched file paths) of one diff.
        diff の追加行と対象ファイルパスを検査する。
        """
        findings: list[Finding] = []
        current_file = "?"
        new_line_no: int | None = None
        for raw in diff.split(b"\n"):
            line = _decode_line(raw)
            if line.startswith("+++ "):
                target = line[4:].strip()
                if target != "/dev/null":
                    current_file = target[2:] if target.startswith("b/") else target
                    # File paths themselves can leak names; check NG words only,
                    # since credential/e-mail patterns rarely appear in paths.
                    # ファイルパス自体も名称漏えいの経路になるため NG ワードのみ検査する。
                    folded = current_file.casefold()
                    for word in self.ng_words:
                        if word in folded:
                            findings.append(
                                Finding(
                                    commit,
                                    f"{current_file} (file path)",
                                    "ng-word",
                                    f"blocked word: {word}",
                                    current_file,
                                )
                            )
                new_line_no = None
                continue
            if line.startswith("@@@"):
                # Combined diff of a merge commit: line numbers are ambiguous.
                new_line_no = None
                continue
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                new_line_no = int(m.group(1)) if m else None
                continue
            if line.startswith("+"):
                loc = (
                    f"{current_file}:{new_line_no}"
                    if new_line_no is not None
                    else current_file
                )
                findings.extend(self.scan_text(line[1:], commit, loc))
                if new_line_no is not None:
                    new_line_no += 1
                continue
            if (
                new_line_no is not None
                and not line.startswith("-")
                and not line.startswith("\\")
            ):
                new_line_no += 1
        return findings

    def scan_commit(self, sha: str) -> list[Finding]:
        """Scan one commit: its diff against its parents and its message.
        コミット 1 件(親との diff とコミットメッセージ)を検査する。
        """
        label = f"commit {sha[:10]}"
        diff = _git("show", "--no-color", "--format=", "--unified=0", sha)
        findings = self.scan_diff(diff, label)
        message = _git("show", "-s", "--no-color", "--format=%B", sha)
        for raw in message.split(b"\n"):
            findings.extend(
                self.scan_text(_decode_line(raw), label, "commit message")
            )
        return findings


def _commits_to_push(local_sha: str, remote_sha: str) -> list[str]:
    """List the commits that would become public if this ref update is pushed.
    この ref 更新を push した場合に新たに公開されるコミットを列挙する。
    """
    # Exclude everything already known on any remote; if the remote tip is a
    # locally known object, exclude its ancestry explicitly as well (covers a
    # stale remote-tracking ref).
    args = ["rev-list", local_sha, "--not", "--remotes"]
    if remote_sha and not _ZERO_SHA_RE.match(remote_sha) and _object_exists(remote_sha):
        args.append(remote_sha)
    out = _git(*args).decode().split()
    return out


def _report(findings: list[Finding], action: str, remedy: str, bypass: str) -> None:
    """Print all findings and how to resolve or suppress them.
    検出結果一覧と対処方法(修正・抑制)を表示する。
    """
    print(
        f"\nsensitive-info check BLOCKED the {action}: {len(findings)} potential "
        "leak(s) of sensitive information:\n",
        file=sys.stderr,
    )
    for f in findings:
        print(
            f"  {f.commit}, {f.location} [{f.rule_id}] {f.message}",
            file=sys.stderr,
        )
        print(f"    {f.excerpt}", file=sys.stderr)
    print(
        "\nTo proceed:\n"
        f"  - {remedy}, or\n"
        f'  - for a false positive, append the marker "{ALLOW_MARKER}" to that\n'
        "    line, or add a suppression regex to .git/info/sensitive_allow.txt\n"
        "    (one per line; the file stays local and is never committed).\n"
        f"  - Emergency bypass (use sparingly): {bypass}\n",
        file=sys.stderr,
    )


def _run_hook_mode(scanner: Scanner) -> int:
    """Read pre-push ref updates from stdin and scan the outgoing commits.
    標準入力から pre-push の ref 更新を読み取り、送信予定コミットを検査する。
    """
    seen: set[str] = set()
    findings: list[Finding] = []
    n_commits = 0
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if _ZERO_SHA_RE.match(local_sha):
            continue  # ref deletion: nothing new becomes public
        for sha in _commits_to_push(local_sha, remote_sha):
            if sha in seen:
                continue
            seen.add(sha)
            n_commits += 1
            findings.extend(scanner.scan_commit(sha))
    if findings:
        _report(
            findings,
            action="push",
            remedy="remove the flagged content and amend/rebase the commit(s)",
            bypass="git push --no-verify",
        )
        return 1
    print(
        f"sensitive-info check: OK ({n_commits} outgoing commit(s) scanned, "
        "no findings).",
        file=sys.stderr,
    )
    return 0


def _run_diff_mode(
    scanner: Scanner,
    diff_args: list[str],
    label: str,
    action: str,
    remedy: str,
    bypass: str,
) -> int:
    """Scan a 'git diff' result (staged changes or an arbitrary range).
    'git diff' の結果(ステージ済み差分または任意のレンジ)を検査する。
    """
    diff = _git("diff", "--no-color", "--unified=0", *diff_args)
    findings = scanner.scan_diff(diff, label)
    if findings:
        _report(findings, action=action, remedy=remedy, bypass=bypass)
        return 1
    print(f"sensitive-info check: OK ({label}, no findings).", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point; selects hook mode (stdin) or manual range mode.
    エントリポイント。フックモード(標準入力)か手動レンジモードを選択する。
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remote", default="", help="remote name (from the hook)")
    parser.add_argument("--url", default="", help="remote URL (from the hook)")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="scan the staged diff ('git diff --cached'); used by pre-commit",
    )
    parser.add_argument(
        "--range",
        dest="rev_range",
        default="",
        help="scan 'git diff RANGE' (e.g. origin/main..HEAD) instead of stdin",
    )
    args = parser.parse_args(argv)

    # Report through UTF-8 regardless of the console code page so Japanese
    # excerpts survive Git Bash / VS Code terminals; replace what cannot be
    # encoded rather than crashing mid-report.
    # コンソールのコードページに依存せず UTF-8 で出力する。Git Bash や VS Code
    # の端末で日本語の抜粋が文字化けしないようにし、符号化不能文字は置換する。
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        scanner = Scanner()
        if args.staged:
            return _run_diff_mode(
                scanner,
                diff_args=["--cached"],
                label="staged changes",
                action="commit",
                remedy="fix or unstage the flagged content before committing",
                bypass="git commit --no-verify",
            )
        if args.rev_range:
            return _run_diff_mode(
                scanner,
                diff_args=[args.rev_range],
                label=f"range {args.rev_range}",
                action="push",
                remedy="remove the flagged content from the range",
                bypass="git push --no-verify",
            )
        if sys.stdin.isatty():
            parser.print_help(sys.stderr)
            print(
                "\nsensitive-info check: no ref updates on stdin; for a manual "
                "scan use --staged or --range (e.g. --range origin/main..HEAD).",
                file=sys.stderr,
            )
            return 2
        return _run_hook_mode(scanner)
    except RuntimeError as exc:
        # Fail closed: an internal error also blocks the commit/push.
        # フェイルクローズ方針: 内部エラー時もコミット・push を中止する。
        print(f"sensitive-info check: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
