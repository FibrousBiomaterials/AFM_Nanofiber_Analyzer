#!/usr/bin/env python3
"""Keep ``CHANGELOG.ja.md`` a translation of ``CHANGELOG.md``, entry by entry.
``CHANGELOG.ja.md`` が ``CHANGELOG.md`` の訳であり続けるよう、項目ごとに検査する。

Invoked by ``.githooks/pre-commit`` (``--staged``) and carried into CI by
``tests/test_changelog_ja.py``. The rule it serves is ``AGENTS.md`` section
8.11. Both files are split into the same entries (a top-level list item with
everything indented under it, or a paragraph outside a list), and a commit is
blocked when
``.githooks/pre-commit``（``--staged``）から呼ばれ、``tests/test_changelog_ja.py``
が CI へ持ち込む。支える規則は ``AGENTS.md`` 8.11 節である。両ファイルを同じ項目
（字下げされた続きを含むトップレベルの箇条書き、または箇条書きの外の段落）に
分け、次の場合にコミットを止める。

- the headings or the number of entries in a section differ;
- an entry and its translation differ mechanically: the inline code, the URLs,
  the number of bold spans, paragraphs or nested items, a number of the English
  or a Japanese UI label quoted in the English is missing from the translation;
- an English entry changed and its translation did not.
- 見出し、または節の項目数が異なる。
- 項目と訳が機械的に異なる。インラインコード、URL、太字・段落・入れ子の項目の
  数が違う、または英文の数値や英文が引用する日本語の UI ラベルが訳に無い。
- 英語の項目が変わったのに訳が変わっていない。

The last test compares against ``tests/changelog_ja_manifest.json``, which
records each English entry's fingerprint beside the fingerprint of the
translation read with it. ``--update`` records the current pairs and refuses an
English entry whose translation is one already recorded, so it cannot be used to
silence the check without translating. Fingerprints ignore line wrapping. Like
the fingerprints of ``docs/algorithms.md`` (section 8.13) this is a tripwire, not
a proof: whether a translation says what the English says is for a reader.
最後の検査は ``tests/changelog_ja_manifest.json`` と比べる。これは英語の各項目の
指紋を、それと読み合わせた訳の指紋と並べて記録する。``--update`` は現在の組を
記録するが、訳が記録済みのままの英語の項目は拒否するので、訳さずに検査を黙らせる
ためには使えない。指紋は行の折り返しを無視する。``docs/algorithms.md`` の指紋
（8.13 節）と同じく、これは検知の仕掛けであって証明ではない。訳が英文と同じことを
言っているかは、人が読んで判断する。

Usage:
    python scripts/check_changelog_ja.py            # the working tree
    python scripts/check_changelog_ja.py --staged   # the index (pre-commit)
    python scripts/check_changelog_ja.py --update   # record the current pairs
    python scripts/check_changelog_ja.py --update --english-only

``--english-only`` also records entries whose English changed in a way that does
not touch the translation, such as a typo; say so in the commit message.
``--english-only`` は、誤字の修正のように訳に関わらない英語の変更も記録する。その旨を
コミットメッセージに書くこと。

Exit codes: 0 = clean, 1 = findings (the commit is blocked), 2 = usage error.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from doc_excerpts import ROOT, read_staged, read_worktree  # noqa: E402

CHANGELOG_EN = "CHANGELOG.md"
CHANGELOG_JA = "CHANGELOG.ja.md"
MANIFEST = "tests/changelog_ja_manifest.json"

# Headings below "##" are translated by this table. "##" headings carry the
# version and date, which `scripts/release.py` writes, and stay identical.
# "##" より下の見出しはこの表で訳す。"##" の見出しは `scripts/release.py` が書く
# 版と日付を持つので、同一のままにする。
TITLE_JA = "変更履歴"
SECTION_JA = {
    "Added": "追加",
    "Changed": "変更",
    "Deprecated": "非推奨",
    "Removed": "削除",
    "Fixed": "修正",
    "Security": "セキュリティ",
    "Known issues": "既知の問題",
}

_HEADING = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")
_LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s")
_CODE = re.compile(r"`[^`]+`")
_URL = re.compile(r"https?://[^\s)>]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_CJK = "぀-ヿ㐀-鿿ｦ-ﾟ"
_CJK_GAP = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")
_CJK_RUN = re.compile(rf"[{_CJK}]+")
_NESTED_ITEM = re.compile(r"^[ \t]+[-*] ", re.MULTILINE)

Reader = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class Entry:
    """One list item or paragraph of a changelog.
    変更履歴の 1 つの箇条書きまたは段落。

    Attributes
    ----------
    section
        The ``##`` and ``###`` headings above it, for messages.
        上にある ``##`` と ``###`` の見出し（メッセージ用）。
    text
        The raw lines of the entry.
        項目の元の行。
    """

    section: str
    text: str

    @property
    def normalized(self) -> str:
        """The text with line wrapping and indentation removed."""
        return _CJK_GAP.sub("", " ".join(self.text.split()))

    @property
    def fingerprint(self) -> str:
        """A hash of the text that does not depend on line wrapping."""
        return hashlib.sha256(self.normalized.encode("utf-8")).hexdigest()[:16]

    @property
    def label(self) -> str:
        """Where the entry is and how it starts, for messages."""
        return f"[{self.section}] {self.normalized[:60]}"


def parse(text: str) -> Tuple[List[str], List[Entry], List[str]]:
    """Split a changelog into its headings, its entries and its link definitions.
    変更履歴を見出し・項目・リンク定義に分ける。

    Parameters
    ----------
    text
        The whole file.
        ファイル全体。

    Returns
    -------
    tuple
        ``(headings, entries, link_definitions)``. A line starts a new entry
        when it is a top-level list item, or unindented text after a blank line
        or a heading.
        ``(見出し, 項目, リンク定義)``。トップレベルの箇条書きの行、または空行や
        見出しの後の字下げの無い行が、新しい項目を始める。
    """
    headings: List[str] = []
    entries: List[Entry] = []
    links: List[str] = []
    above = {1: "", 2: "", 3: ""}
    current: List[str] = []
    after_break = True

    def close() -> None:
        if current:
            section = " / ".join(h for h in (above[2], above[3]) if h) or above[1]
            entries.append(Entry(section, "\n".join(current).rstrip()))
            current.clear()

    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            close()
            level = len(heading.group(1))
            headings.append(line.strip())
            above[level] = heading.group(2)
            if level == 2:
                above[3] = ""
            after_break = True
        elif not line.strip():
            if current:
                current.append("")
            after_break = True
        elif _LINK_DEFINITION.match(line):
            close()
            links.append(line.strip())
            after_break = True
        else:
            indented = line[0] in " \t"
            if line.startswith("- ") or (after_break and not indented):
                close()
            current.append(line)
            after_break = False
    close()
    return headings, entries, links


def expected_ja_heading(heading: str) -> Optional[str]:
    """The Japanese file's form of an English heading, or None when not in the table.
    英語の見出しに対応する日本語版の見出し。表に無ければ None。
    """
    match = _HEADING.match(heading)
    level, title = len(match.group(1)), match.group(2)
    if level == 1:
        return f"# {TITLE_JA}"
    if level == 2:
        return heading
    if title in SECTION_JA:
        return f"### {SECTION_JA[title]}"
    return None


def _numbers(text: str) -> List[str]:
    """The numbers in `text`, outside inline code and URLs."""
    return _NUMBER.findall(_URL.sub(" ", _CODE.sub(" ", text)))


def translation_problems(en: Entry, ja: Entry) -> List[str]:
    """Mechanical differences between an entry and its translation.
    項目と訳の機械的に検出できる食い違い。

    A number the translation adds is allowed, because Japanese writes digits for
    words the English spells out ("second-order" 2 次, "a quarter" 4 分の 1).
    Whether the translation says the same thing is for a reader to judge.
    訳が数値を加えるのは認める。英語が単語で書く数を日本語は数字で書くためである
    （"second-order" 2 次、"a quarter" 4 分の 1）。訳が同じことを言っているかは、
    人が読んで判断する。
    """
    problems: List[str] = []
    en_text, ja_text = en.normalized, ja.normalized
    if sorted(_CODE.findall(en_text)) != sorted(_CODE.findall(ja_text)):
        only_en = sorted(set(_CODE.findall(en_text)) - set(_CODE.findall(ja_text)))
        only_ja = sorted(set(_CODE.findall(ja_text)) - set(_CODE.findall(en_text)))
        problems.append(f"inline code differs (English only {only_en[:4]}, "
                        f"Japanese only {only_ja[:4]})")
    if sorted(_URL.findall(en_text)) != sorted(_URL.findall(ja_text)):
        problems.append("URLs differ")
    if en_text.count("**") != ja_text.count("**"):
        problems.append(f"bold markers differ ({en_text.count('**')} in English, "
                        f"{ja_text.count('**')} in Japanese)")
    if en.text.count("\n\n") != ja.text.count("\n\n"):
        problems.append(f"paragraphs differ ({en.text.count(chr(10) * 2) + 1} in English, "
                        f"{ja.text.count(chr(10) * 2) + 1} in Japanese)")
    if len(_NESTED_ITEM.findall(en.text)) != len(_NESTED_ITEM.findall(ja.text)):
        problems.append("nested list items differ")
    remaining = _numbers(ja_text)
    for number in _numbers(en_text):
        if number in remaining:
            remaining.remove(number)
        else:
            problems.append(f"number {number} missing from the translation")
    for run in _CJK_RUN.findall(_CODE.sub(" ", en_text)):
        if run not in ja_text:
            problems.append(f"Japanese label {run} missing from the translation")
    return problems


def structure_problems(en_text: str, ja_text: str) -> List[str]:
    """What keeps the two files from being aligned entry by entry.
    2 つのファイルを項目ごとに対応させられない原因。
    """
    en_headings, en_entries, en_links = parse(en_text)
    ja_headings, ja_entries, ja_links = parse(ja_text)
    problems: List[str] = []
    expected = [expected_ja_heading(h) for h in en_headings]
    for heading, wanted in zip(en_headings, expected):
        if wanted is None:
            problems.append(f"heading {heading!r} has no translation in SECTION_JA")
    if expected != ja_headings:
        for wanted, found in zip(expected, ja_headings):
            if wanted != found:
                problems.append(f"headings differ: expected {wanted!r}, found {found!r}")
                break
        else:
            problems.append(f"{len(en_headings)} headings in {CHANGELOG_EN}, "
                            f"{len(ja_headings)} in {CHANGELOG_JA}")
    if en_links != ja_links:
        problems.append("the link definitions at the end of the two files differ")
    if problems:
        return problems

    def by_section(entries: List[Entry]) -> List[List[Entry]]:
        groups: List[List[Entry]] = []
        last = None
        for entry in entries:
            if entry.section != last:
                groups.append([])
                last = entry.section
            groups[-1].append(entry)
        return groups

    en_groups = by_section(en_entries)
    ja_groups = by_section(ja_entries)
    if len(en_groups) != len(ja_groups):
        return [f"{len(en_groups)} sections hold entries in {CHANGELOG_EN}, "
                f"{len(ja_groups)} in {CHANGELOG_JA}"]
    for en_group, ja_group in zip(en_groups, ja_groups):
        if len(en_group) != len(ja_group):
            first = next((e.label for e, j in zip(en_group, ja_group)
                          if _numbers(e.normalized)[:3] != _numbers(j.normalized)[:3]),
                         en_group[-1].label)
            problems.append(
                f"[{en_group[0].section}] holds {len(en_group)} entries in English and "
                f"{len(ja_group)} in Japanese; the first that looks unaligned: {first}")
    return problems


def _in_head(rel: str) -> bool:
    """Whether the last commit holds `rel`."""
    proc = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"HEAD:{rel}"],
                          capture_output=True)
    return proc.returncode == 0


def load_manifest(read: Reader) -> Dict[str, str]:
    """Return ``{English fingerprint: translation fingerprint}`` as recorded."""
    text = read(MANIFEST)
    if text is None:
        return {}
    return {en: ja for en, ja in json.loads(text)["pairs"]}


def find_problems(en_text: Optional[str], ja_text: Optional[str],
                  recorded: Dict[str, str]) -> List[str]:
    """Every finding for one state of the two files and the manifest.
    2 つのファイルとマニフェストのある状態についての、すべての指摘。
    """
    if en_text is None or ja_text is None:
        return [f"{CHANGELOG_EN if en_text is None else CHANGELOG_JA} is missing"]
    problems = structure_problems(en_text, ja_text)
    if problems:
        return problems
    recorded_ja = set(recorded.values())
    for en, ja in zip(parse(en_text)[1], parse(ja_text)[1]):
        problems += [f"{en.label}: {p}" for p in translation_problems(en, ja)]
        if recorded.get(en.fingerprint) == ja.fingerprint:
            continue
        if en.fingerprint not in recorded and ja.fingerprint in recorded_ja:
            problems.append(f"{en.label}: the English changed and its translation did not")
        else:
            problems.append(f"{en.label}: not read against the translation yet; read "
                            "the pair, then run scripts/check_changelog_ja.py --update")
    return problems


def update(en_text: str, ja_text: str, recorded: Dict[str, str],
           english_only: bool = False) -> Tuple[Optional[str], List[str]]:
    """The new manifest text for the current pairs, or the findings that refuse it.
    現在の組についての新しいマニフェストの本文、または記録を拒む指摘。

    Returns
    -------
    tuple
        ``(manifest text or None, problems)``.
        ``(マニフェストの本文または None, 指摘)``。
    """
    problems = structure_problems(en_text, ja_text)
    if problems:
        return None, problems
    recorded_ja = set(recorded.values())
    pairs = {}
    for en, ja in zip(parse(en_text)[1], parse(ja_text)[1]):
        problems += [f"{en.label}: {p}" for p in translation_problems(en, ja)]
        if (not english_only and en.fingerprint not in recorded
                and ja.fingerprint in recorded_ja):
            problems.append(f"{en.label}: the English changed and its translation did not")
        pairs[en.fingerprint] = ja.fingerprint
    if problems:
        return None, problems
    body = ",\n".join(f'    ["{en}", "{ja}"]' for en, ja in sorted(pairs.items()))
    return ('{\n  "_comment": "Written by scripts/check_changelog_ja.py --update; '
            'see AGENTS.md section 8.11.",\n'
            f'  "pairs": [\n{body}\n  ]\n}}\n'), []


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point.
    エントリポイント。
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staged", action="store_true",
                        help="check the index; used by pre-commit")
    parser.add_argument("--update", action="store_true",
                        help="record the current pairs after reading them")
    parser.add_argument("--english-only", action="store_true",
                        help="with --update, also record English edits that need no "
                             "change to the translation")
    args = parser.parse_args(argv)
    if args.english_only and not args.update:
        parser.error("--english-only needs --update")

    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    read: Reader = read_staged if args.staged else read_worktree
    en_text, ja_text = read(CHANGELOG_EN), read(CHANGELOG_JA)
    recorded = load_manifest(read)

    # A commit made before the translation was ever committed has nothing to
    # compare, and must not be blocked over a file that is not part of it.
    # 訳が一度もコミットされていない間のコミットには比較するものが無く、そのコミットに
    # 含まれないファイルを理由に止めてはならない。
    if args.staged and ja_text is None and not _in_head(CHANGELOG_JA):
        print(f"changelog translation check: {CHANGELOG_JA} not committed yet; skipped.",
              file=sys.stderr)
        return 0

    if args.update:
        if en_text is None or ja_text is None:
            print("changelog translation check: a changelog file is missing", file=sys.stderr)
            return 1
        text, problems = update(en_text, ja_text, recorded, args.english_only)
        if text is None:
            print("changelog translation check: not recorded:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        (ROOT / MANIFEST).write_text(text, encoding="utf-8", newline="\n")
        print(f"changelog translation check: recorded {MANIFEST}.", file=sys.stderr)
        return 0

    problems = find_problems(en_text, ja_text, recorded)
    if not problems:
        print("changelog translation check: OK.", file=sys.stderr)
        return 0
    print(f"changelog translation check: {CHANGELOG_JA} does not follow {CHANGELOG_EN}:",
          file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\nCHANGELOG.ja.md is the translation of CHANGELOG.md, kept entry by entry.\n"
        "Apply the same edit to it, read the pair, and record it:\n"
        "\n"
        "    .venv\\Scripts\\python.exe scripts\\check_changelog_ja.py --update\n"
        "\n"
        "See AGENTS.md section 8.11.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
