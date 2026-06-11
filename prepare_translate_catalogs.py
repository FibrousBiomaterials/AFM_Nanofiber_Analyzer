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


def _extract_plugin_descriptions() -> list[tuple[str, int, str]]:
    """
    Extract literal PLUGIN_INFO descriptions from GUI plugin files.
    GUI プラグインファイルからリテラルの PLUGIN_INFO description を抽出する。
    """
    descriptions: list[tuple[str, int, str]] = []
    for py_file in sorted(GUIS_DIR.glob("*.py"), key=lambda path: path.name.lower()):
        if py_file.name == "__init__.py":
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


def _append_plugin_descriptions_to_pot() -> int:
    """
    Add PLUGIN_INFO description msgids to the POT file when missing.
    POT ファイルに未登録の PLUGIN_INFO description msgid を追加する。
    """
    text = POT_FILE.read_text(encoding="utf-8")
    existing = _parse_msgids(text)
    additions: list[str] = []

    for rel_path, lineno, description in _extract_plugin_descriptions():
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

    _run_babel(["extract", "-F", str(BABEL_CFG), "-o", str(POT_FILE), "."])
    added = _append_plugin_descriptions_to_pot()
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
