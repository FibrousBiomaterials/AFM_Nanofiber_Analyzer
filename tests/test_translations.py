# -*- coding: utf-8 -*-
"""
Consistency tests between .po sources and compiled .mo catalogs.
.po ソースとコンパイル済み .mo カタログの整合性テスト。

The compiled .mo files are version-controlled so fresh clones get working
translations without Babel. That works only if the .mo files never go stale,
so these tests fail whenever a translated .po entry is missing from (or
differs in) the corresponding .mo — i.e. when someone edited a .po file and
forgot to run `pybabel compile -d locale`.
コンパイル済み .mo はバージョン管理されており、クローン直後でも Babel なしで
翻訳が機能する。これは .mo が古くならないことが前提なので、本テストは翻訳済み
.po エントリが対応する .mo に存在しない・一致しない場合（= .po を編集して
`pybabel compile -d locale` を忘れた場合）に失敗する。

Only singular entries without msgctxt are compared; plural and contextual
entries are skipped because the simple parser here does not model them.
比較対象は msgctxt なしの単数エントリのみ。複数形・文脈付きエントリは
この簡易パーサでは扱わないためスキップする。
"""

import ast
import gettext
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALE_DIR = PROJECT_ROOT / "locale"

PO_FILES = sorted(LOCALE_DIR.glob("*/LC_MESSAGES/messages.po"))


def _collect_quoted(lines: list[str], start: int, keyword: str) -> str:
    """Join a PO quoted string with its continuation lines."""
    first = lines[start][len(keyword):].strip()
    parts = [ast.literal_eval(first)]
    index = start + 1
    while index < len(lines) and lines[index].strip().startswith('"'):
        parts.append(ast.literal_eval(lines[index].strip()))
        index += 1
    return "".join(parts)


def _parse_po_singular_entries(po_path: Path) -> dict[str, str]:
    """
    Return translated singular entries as a msgid -> msgstr mapping.
    翻訳済みの単数エントリを msgid -> msgstr の辞書として返す。

    Skips the header, obsolete (#~) and fuzzy blocks, plural / msgctxt
    entries, and untranslated entries (empty msgstr) — matching what
    `pybabel compile` includes in the .mo by default.
    ヘッダ、obsolete (#~)・fuzzy ブロック、複数形・msgctxt エントリ、未翻訳
    （msgstr が空）はスキップする。これは `pybabel compile` が既定で .mo に
    含める範囲と一致する。
    """
    catalog: dict[str, str] = {}
    text = po_path.read_text(encoding="utf-8")

    for block in text.split("\n\n"):
        lines = block.splitlines()
        if any(line.startswith("#~") for line in lines):
            continue
        if any(line.startswith("#,") and "fuzzy" in line for line in lines):
            continue
        if any(line.startswith(("msgid_plural ", "msgctxt ")) for line in lines):
            continue

        msgid_index = next(
            (i for i, line in enumerate(lines) if line.startswith("msgid ")), None
        )
        msgstr_index = next(
            (i for i, line in enumerate(lines) if line.startswith("msgstr ")), None
        )
        if msgid_index is None or msgstr_index is None:
            continue

        msgid = _collect_quoted(lines, msgid_index, "msgid ")
        msgstr = _collect_quoted(lines, msgstr_index, "msgstr ")
        if msgid and msgstr:
            catalog[msgid] = msgstr
    return catalog


def test_po_files_exist():
    """At least one language catalog must ship with the repository."""
    assert PO_FILES, f"no messages.po found under {LOCALE_DIR}"


@pytest.mark.parametrize("po_path", PO_FILES, ids=lambda p: p.parent.parent.name)
def test_compiled_mo_exists(po_path):
    """Each .po must have a sibling compiled .mo committed next to it."""
    mo_path = po_path.with_suffix(".mo")
    assert mo_path.exists(), (
        f"{mo_path} is missing; run `pybabel compile -d locale` and commit it"
    )


@pytest.mark.parametrize("po_path", PO_FILES, ids=lambda p: p.parent.parent.name)
def test_mo_matches_po(po_path):
    """Every translated .po entry must be present and identical in the .mo."""
    mo_path = po_path.with_suffix(".mo")
    if not mo_path.exists():
        pytest.skip("missing .mo is reported by test_compiled_mo_exists")

    with open(mo_path, "rb") as f:
        translations = gettext.GNUTranslations(f)
    # _catalog is the de facto stable mapping used by gettext internals.
    # _catalog は gettext 内部で実質安定して使われている辞書。
    mo_catalog = getattr(translations, "_catalog")

    stale = {
        msgid: (msgstr, mo_catalog.get(msgid))
        for msgid, msgstr in _parse_po_singular_entries(po_path).items()
        if mo_catalog.get(msgid) != msgstr
    }
    assert not stale, (
        f"{mo_path.name} is stale for {len(stale)} entr(y/ies), e.g. "
        f"{next(iter(stale.items()))!r}; "
        "run `pybabel compile -d locale` and commit the .mo files"
    )
