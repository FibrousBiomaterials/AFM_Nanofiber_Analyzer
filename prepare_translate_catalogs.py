"""
Prepare gettext catalogs without machine translation.

This script runs the Babel extract/update flow, injects
``PLUGIN_INFO["description"]`` entries into ``locale/messages.pot``, and
removes obsolete ``#~`` entries from language-specific ``messages.po`` files.
It does not fill ``msgstr`` values; use this when translations are edited
manually or by an external non-Python tool.
"""

import ast
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
BABEL_CFG = BASE_DIR / "babel.cfg"
LOCALE_DIR = BASE_DIR / "locale"
POT_FILE = LOCALE_DIR / "messages.pot"
GUIS_DIR = BASE_DIR / "guis"


def _babel_command() -> list[str]:
    """
    Return the command prefix used to invoke Babel.
    Babel を起動するためのコマンド接頭辞を返す。
    """
    pybabel = shutil.which("pybabel")
    if pybabel:
        return [pybabel]
    return [sys.executable, "-m", "babel.messages.frontend"]


def _run_babel(args: list[str]) -> None:
    """
    Run a Babel command from the project root.
    プロジェクトルートから Babel コマンドを実行する。
    """
    subprocess.run(_babel_command() + args, cwd=BASE_DIR, check=True)


def _tracked_python_files() -> Optional[list[str]]:
    """
    List the repository-relative paths of every git-tracked Python file.
    git が追跡している Python ファイルのリポジトリ相対パスを列挙する。

    Returns
    -------
    list of str or None
        Tracked paths, or None when git cannot answer and the caller should
        fall back to scanning the working tree.
        追跡されているパス。git が応答できずスキャンへフォールバックすべき
        場合は None。

    Notes
    -----
    The catalogs are a product artifact, so their contents must be a function
    of the repository rather than of whatever happens to sit in the working
    tree. Babel resolves `babel.cfg`'s `**/*.py` against the filesystem and
    knows nothing about git, so an ignored local file (the GUI01B diagnostic
    copy of GUI01) otherwise lands in the catalogs and makes them differ
    between a fresh clone and a developer's machine.
    カタログは成果物であり、その内容は作業ツリーではなくリポジトリによって
    決まらなければならない。Babel は `babel.cfg` の `**/*.py` をファイル
    システム上で解決し git を一切見ないため、無視されたローカルファイル
    (GUI01 の診断用コピー GUI01B) がカタログに入り、クローン直後と開発者の
    手元とで内容が食い違ってしまう。

    Returning None on failure keeps the script usable where git is absent --
    a source tarball, for instance -- which is also a case where no ignored
    file can be present to begin with.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=BASE_DIR, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = [p for p in result.stdout.decode("utf-8").split("\0") if p]
    return paths or None


def _po_escape(text: str) -> str:
    """
    Escape a Python string fragment for a PO quoted string.
    Python 文字列断片を PO の引用文字列向けにエスケープする。
    """
    return (
        text.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _po_field(field: str, text: str) -> list[str]:
    """
    Format a PO field while preserving embedded newlines.
    改行を保持して PO フィールドを整形する。
    """
    if "\n" not in text:
        return [f'{field} "{_po_escape(text)}"']

    lines = [f'{field} ""']
    for part in text.splitlines(keepends=True):
        lines.append(f'"{_po_escape(part)}"')
    return lines


def _po_unescape(text: str) -> str:
    """
    Decode a PO quoted-string fragment.
    PO の引用文字列断片をデコードする。
    """
    return ast.literal_eval(f'"{text}"')


def _parse_msgids(po_text: str) -> set[str]:
    """
    Return msgids already present in a PO/POT file.
    PO/POT ファイルに既に存在する msgid を返す。
    """
    msgids: set[str] = set()
    lines = po_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("msgid "):
            i += 1
            continue

        value = ""
        first = line[len("msgid "):].strip()
        if first.startswith('"') and first.endswith('"'):
            value += _po_unescape(first[1:-1])
        i += 1
        while i < len(lines):
            continuation = lines[i].strip()
            if not (continuation.startswith('"') and continuation.endswith('"')):
                break
            value += _po_unescape(continuation[1:-1])
            i += 1
        msgids.add(value)
    return msgids


def _extract_plugin_descriptions(
    tracked: Optional[list[str]] = None,
) -> list[tuple[str, int, str]]:
    """
    Extract literal PLUGIN_INFO descriptions from GUI plugin files.
    GUI プラグインファイルからリテラルの PLUGIN_INFO description を抽出する。

    Parameters
    ----------
    tracked
        Git-tracked paths to restrict the scan to, or None to scan `guis/` as
        it stands on disk. This is the second path into the catalogs, beside
        Babel's own extraction, so it needs the same filter.
        走査対象を限定する git 追跡パス。None なら `guis/` をディスク上の
        状態のまま走査する。Babel の抽出と並ぶカタログへの second path で
        あるため、同じフィルタが必要。
    """
    allowed = None if tracked is None else set(tracked)
    descriptions: list[tuple[str, int, str]] = []
    for py_file in sorted(GUIS_DIR.glob("*.py"), key=lambda path: path.name.lower()):
        if py_file.name == "__init__.py":
            continue
        if allowed is not None:
            if py_file.relative_to(BASE_DIR).as_posix() not in allowed:
                continue

        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "PLUGIN_INFO"
                for target in node.targets
            ):
                continue
            if not isinstance(node.value, ast.Dict):
                continue

            for key, value in zip(node.value.keys, node.value.values):
                if not (isinstance(key, ast.Constant) and key.value == "description"):
                    continue
                description = ast.literal_eval(value)
                if isinstance(description, str) and description:
                    rel_path = py_file.relative_to(BASE_DIR).as_posix()
                    descriptions.append((rel_path, value.lineno, description))
            break
    return descriptions


def _append_plugin_descriptions_to_pot(
    tracked: Optional[list[str]] = None,
) -> int:
    """
    Add PLUGIN_INFO description msgids to the POT file when missing.
    POT ファイルに未登録の PLUGIN_INFO description msgid を追加する。

    Parameters
    ----------
    tracked
        Git-tracked paths limiting which plugin files are scanned, or None to
        scan every file present in `guis/`.
        走査するプラグインファイルを限定する git 追跡パス。None なら `guis/`
        にある全ファイルを走査する。
    """
    text = POT_FILE.read_text(encoding="utf-8")
    existing = _parse_msgids(text)
    additions: list[str] = []

    for rel_path, lineno, description in _extract_plugin_descriptions(tracked):
        if description in existing:
            continue
        additions.append("")
        additions.append(f"#: {rel_path}:{lineno}")
        additions.extend(_po_field("msgid", description))
        additions.append('msgstr ""')
        existing.add(description)

    if additions:
        if not text.endswith("\n"):
            text += "\n"
        POT_FILE.write_text(text + "\n".join(additions) + "\n", encoding="utf-8")
    return sum(1 for line in additions if line.startswith("msgid "))


def _remove_obsolete_entries(po_file: Path) -> int:
    """
    Remove obsolete #~ blocks from a PO file and return the removed count.
    PO ファイルから obsolete な #~ ブロックを削除し、削除数を返す。
    """
    text = po_file.read_text(encoding="utf-8")
    kept: list[str] = []
    removed = 0
    for block in text.split("\n\n"):
        if any(line.startswith("#~") for line in block.splitlines()):
            removed += 1
            continue
        kept.append(block)

    if removed:
        po_file.write_text("\n\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return removed


def _remove_all_obsolete_entries() -> int:
    """
    Remove obsolete entries from every locale messages.po file.
    すべての locale messages.po から obsolete 項目を削除する。
    """
    total = 0
    for po_file in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/messages.po")):
        total += _remove_obsolete_entries(po_file)
    return total


def main() -> None:
    """
    Run the catalog preparation workflow without machine translation.
    機械翻訳なしのカタログ準備ワークフローを実行する。
    """
    if not BABEL_CFG.exists():
        raise FileNotFoundError(f"Missing Babel config: {BABEL_CFG}")
    LOCALE_DIR.mkdir(exist_ok=True)

    tracked = _tracked_python_files()
    if tracked is None:
        print(
            "  [WARN] git could not list tracked files; extracting from the "
            "working tree. Ignored .py files, if any, will enter the catalogs."
        )
        inputs = ["."]
    else:
        inputs = tracked
    _run_babel(["extract", "-F", str(BABEL_CFG), "-o", str(POT_FILE), *inputs])
    added = _append_plugin_descriptions_to_pot(tracked)
    _run_babel(["update", "-i", str(POT_FILE), "-d", str(LOCALE_DIR)])
    removed = _remove_all_obsolete_entries()

    # Compile so the version-controlled .mo files never go stale after an
    # update. Fuzzy entries are skipped by pybabel's default, so compiling
    # here is safe even before translators review the catalogs. Re-run
    # `pybabel compile -d locale` (and commit the .mo files) after editing
    # msgstr values by hand.
    # バージョン管理される .mo が更新後に古いまま残らないよう、ここで
    # コンパイルする。fuzzy エントリは pybabel の既定で除外されるため、
    # 翻訳者のレビュー前に実行しても安全。msgstr を手で編集した後は
    # `pybabel compile -d locale` を再実行し、.mo もコミットすること。
    _run_babel(["compile", "-d", str(LOCALE_DIR)])

    print(
        "Translation catalogs prepared without machine translation. "
        f"Added PLUGIN_INFO descriptions: {added}. "
        f"Removed obsolete entries: {removed}. "
        "Catalogs compiled to .mo."
    )


if __name__ == "__main__":
    main()
