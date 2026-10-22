#!/usr/bin/env python3
"""Check that every sentence of the JOSS manuscript records what supports it.
JOSS 原稿のすべての文が、それを裏付ける根拠を記録していることを確認する。

`paper.md` is what reviewers and readers cite, and it makes claims of three
kinds: about this software, about other tools and published work, and about the
authors. A sentence written from memory or inference reads exactly like one
checked against its source, so the manuscript carried statements about other
tools that nobody had read in the original. Every prose sentence therefore has
an entry in `CLAIMS` naming its sources, and this script checks the entries:
`paper.md` は査読者と読者が引用する文書であり、本ソフトウェアについて、他の
ツールや既刊の文献について、著者について、の三種類の主張を含む。記憶や推測で
書いた文は原典で確かめた文と見分けがつかず、実際に原典を誰も読んでいない
他ツールについての記述が原稿に載っていた。そこで本文のすべての文について
`CLAIMS` に根拠を記録し、本スクリプトがそれを照合する。

``doc``
    A repository document (``path``) containing ``quote``; checked here.
    リポジトリ内の文書（``path``）が ``quote`` を含むこと。ここで照合する。
``code``
    A source file (``path``) with a definition (``symbol``) that exists, a
    ``quote`` that appears in it, or both; checked here.
    ソースファイル（``path``）に定義（``symbol``）が存在すること、``quote`` が
    含まれること、またはその両方。ここで照合する。
``figure``
    An image in the repository (``path``) and what was seen in it
    (``observed``); only the file is checked here.
    リポジトリ内の画像（``path``）と、そこに見て取った内容（``observed``）。
    ここで照合できるのはファイルの存在だけ。
``external``
    Published work or another project: ``ref`` (a `paper.bib` key or a URL),
    ``locator`` (page, section or file) and ``quote`` (the passage read).
    Only the key is checked here; the quote is what a reviewer compares.
    既刊文献や他のプロジェクト。``ref``（`paper.bib` のキーまたは URL）、
    ``locator``（ページ・節・ファイル）、``quote``（読んだ箇所）。ここで照合
    できるのはキーだけで、引用は査読者が原典と照らし合わせるためのもの。
``author``
    Something only the authors know (affiliation, funding, which data a study
    used); ``reason`` names who confirmed it.
    著者だけが知っている事柄（所属、助成、ある研究が使ったデータ）。
    ``reason`` に誰が確認したかを書く。

An entry is ``"status": "verified"`` with at least one source, or
``"status": "unverified"`` with a ``note`` saying what is missing. The staged
check refuses a commit that adds an unverified sentence, so the unverified set
only shrinks: a sentence that is edited no longer matches its entry and must be
verified again before it is committed.
項目は、根拠を 1 つ以上持つ ``"status": "verified"`` か、何が足りないかを
``note`` に書いた ``"status": "unverified"`` のどちらか。未確認の文を追加する
コミットはステージ済みの検査が拒否するため、未確認の集合は減る方向にしか
変わらない。編集した文は項目と一致しなくなるため、コミット前に確かめ直す
必要がある。

Only the standard library is imported, because the git hooks run outside the
project environment.
git フックはプロジェクト環境の外で動くため、標準ライブラリしか import しない。

Usage
-----
``python scripts/check_paper_claims.py``                   check the working tree
``python scripts/check_paper_claims.py --staged``          check the staged snapshot
``python scripts/check_paper_claims.py --list-unverified`` print unverified sentences
``python scripts/check_paper_claims.py --add-missing``     add unrecorded sentences as unverified
``python scripts/check_paper_claims.py --write-ja``        regenerate paper.ja.md

Each entry also carries the sentence's Japanese translation (``ja``), and the
record carries ``title_ja`` and ``headings_ja``; ``paper.ja.md`` is generated
from them and checked against what ``--write-ja`` would write, so it is never
edited by hand.
各項目は文の日本語訳（``ja``）も持ち、記録全体は ``title_ja`` と
``headings_ja`` を持つ。``paper.ja.md`` はそれらから生成し、``--write-ja`` が
書くものと一致するかを検査するため、手で編集しない。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Callable, Dict, List, Optional, Sequence

import doc_excerpts

ROOT = doc_excerpts.ROOT
PAPER = "paper.md"
PAPER_JA = "paper.ja.md"
BIB = "paper.bib"
CLAIMS = "tests/paper_claims.json"

Reader = Callable[[str], Optional[str]]

# A sentence ends at . ! or ? followed by whitespace and a capital, a digit, a
# backtick, an opening bracket or a citation; "A* path" and "4.8," do not end one.
# 文は . ! ? の後に空白と大文字・数字・バッククォート・開き括弧・引用が続く
# 位置で終わる。"A* path" や "4.8," では終わらない。
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9`(\[@*_])")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BIB_KEY = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


def _squash(text: str) -> str:
    """Whitespace-collapsed text without HTML comments, for comparison."""
    return " ".join(_COMMENT.sub("", text).split())


def front_matter(text: str) -> List[str]:
    """Lines of the YAML front matter, delimiters included; empty without one."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), 0)
        return lines[:end + 1]
    return []


def _split_sentences(lines: Sequence[str]) -> List[str]:
    joined = _squash(" ".join(lines))
    return [s.strip() for s in _SENTENCE_END.split(joined) if s.strip()]


def paper_blocks(text: str) -> List[tuple]:
    """
    Split the manuscript body into headings, paragraphs, list items and figures.
    原稿の本文を見出し・段落・箇条書きの項目・図に分割する。

    Returns tuples ``("heading", marks, title)``, ``("para", sentences)``,
    ``("item", sentences)`` and ``("figure", caption_sentences, label, path)``.
    The YAML front matter is not part of the body.
    ``("heading", marks, title)``、``("para", sentences)``、
    ``("item", sentences)``、``("figure", caption_sentences, label, path)`` の
    タプルを返す。YAML フロントマターは本文に含めない。
    """
    lines = text.splitlines()[len(front_matter(text)):]
    blocks: List[tuple] = []
    current: List[str] = []
    kind = "para"

    def flush() -> None:
        if current:
            blocks.append((kind, _split_sentences(current)))
            current.clear()

    for raw in lines:
        line = raw.strip()
        heading = re.match(r"(#+)\s+(.*)", line)
        if not line or heading:
            flush()
            if heading:
                blocks.append(("heading", heading.group(1), heading.group(2).strip()))
            continue
        figure = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if figure:
            flush()
            label = re.search(r"\\label\{[^}]*\}", figure.group(1))
            caption = re.sub(r"\\label\{[^}]*\}", "", figure.group(1))
            blocks.append(("figure", _split_sentences([caption]),
                           label.group(0) if label else "", figure.group(2)))
            continue
        if line.startswith("- "):
            flush()
            kind = "item"
            line = line[2:]
        elif not current:
            kind = "para"
        current.append(line)
    flush()
    return blocks


def paper_sentences(text: str) -> List[str]:
    """
    Split the manuscript's prose into sentences.
    原稿の本文を文に分割する。

    The YAML front matter, headings and the trailing References heading carry
    no claim and are skipped. A figure contributes its caption; each list item
    is a paragraph of its own.
    YAML フロントマター・見出し・末尾の References 見出しは主張を含まないため
    除く。図はキャプションを、箇条書きは各項目を 1 段落として扱う。
    """
    sentences: List[str] = []
    for block in paper_blocks(text):
        if block[0] in ("para", "item", "figure"):
            sentences += block[1]
    return sentences


def bib_keys(text: str) -> set:
    return set(_BIB_KEY.findall(text or ""))


def _source_problems(src: dict, read: Reader, keys: set) -> List[str]:
    kind = src.get("kind")
    if kind == "doc":
        body = read(src.get("path", ""))
        if body is None:
            return [f"doc {src.get('path')!r} not found"]
        quote = _squash(src.get("quote", ""))
        if not quote:
            return ["doc source without a quote"]
        if quote not in _squash(body):
            return [f"quote not found in {src['path']}: {quote[:70]!r}"]
        return []
    if kind == "code":
        body = read(src.get("path", ""))
        if body is None:
            return [f"code {src.get('path')!r} not found"]
        symbol = src.get("symbol", "")
        quote = _squash(src.get("quote", ""))
        if not symbol and not quote:
            return [f"code source {src['path']!r} without a symbol or a quote"]
        if symbol and doc_excerpts.symbol_source(body, symbol) is None:
            return [f"symbol {symbol!r} not found in {src['path']}"]
        if quote and quote not in _squash(body):
            return [f"quote not found in {src['path']}: {quote[:70]!r}"]
        return []
    if kind == "figure":
        if not (ROOT / src.get("path", "")).is_file():
            return [f"figure {src.get('path')!r} not found"]
        if not src.get("observed", "").strip():
            return [f"figure source {src['path']!r} without what was observed"]
        return []
    if kind == "external":
        problems = []
        ref = src.get("ref", "")
        if not ref:
            problems.append("external source without ref")
        elif "://" not in ref and ref not in keys:
            problems.append(f"ref {ref!r} is neither a URL nor a key of {BIB}")
        for field in ("locator", "quote"):
            if not src.get(field, "").strip():
                problems.append(f"external source {ref!r} without {field}")
        return problems
    if kind == "author":
        return [] if src.get("reason", "").strip() else ["author source without reason"]
    return [f"unknown source kind {kind!r}"]


def load_record(read: Reader) -> dict:
    text = read(CLAIMS)
    return json.loads(text) if text else {}


def load_claims(read: Reader) -> List[dict]:
    return load_record(read).get("claims", [])


_CITE = re.compile(r"@[A-Za-z][\w]*")
_CODE = re.compile(r"`[^`]+`")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                 "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def _numbers(text: str) -> List[str]:
    # Citation keys, code and LaTeX labels carry digits that are not values.
    # 引用キー・コード・LaTeX のラベルに含まれる数字は値ではない。
    text = _CODE.sub(" ", _CITE.sub(" ", re.sub(r"\\\w+\{[^}]*\}", " ", text)))
    return sorted(_NUMBER.findall(text))


def translation_problems(en: str, ja: str) -> List[str]:
    """
    Mechanical differences between a sentence and its Japanese translation.
    文とその日本語訳の機械的に検出できる食い違い。

    The citations and the inline code must be the same, and every number of
    the English must appear in the translation; a number the translation adds
    must be one the English spells out ("three scans" -> 3). Whether the
    translation says the same thing is for a reader to judge.
    引用とインラインコードが同じで、英文の数値がすべて訳にあること。訳が
    加える数値は、英文が単語で書いた数（"three scans" -> 3）に限る。訳が同じ
    ことを言っているかは人が判断する。
    """
    problems = []
    if sorted(_CITE.findall(en)) != sorted(_CITE.findall(ja)):
        problems.append("citations differ")
    if sorted(_CODE.findall(en)) != sorted(_CODE.findall(ja)):
        problems.append("inline code differs")
    en_nums, ja_nums = _numbers(en), _numbers(ja)
    spelled = {_NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", en.lower()) if w in _NUMBER_WORDS}
    remaining = list(ja_nums)
    for n in en_nums:
        if n in remaining:
            remaining.remove(n)
        else:
            problems.append(f"number {n} missing from the translation")
    problems += [f"number {n} not in the English" for n in remaining if n not in spelled]
    return problems


def render_ja(paper: str, record: dict) -> str:
    """
    Build the Japanese manuscript from the English one and the recorded translations.
    英語の原稿と記録された訳から日本語の原稿を組み立てる。

    Raises
    ------
    KeyError
        When a sentence, a heading or the title has no translation.
    """
    ja = {c["sentence"]: c["ja"] for c in record.get("claims", []) if c.get("ja")}
    headings = record.get("headings_ja", {})
    out: List[str] = []
    for line in front_matter(paper):
        if line.startswith("title:"):
            line = "title: " + json.dumps(record["title_ja"], ensure_ascii=False)
        out.append(line)
    out += ["", JA_NOTICE, ""]
    previous = None
    for block in paper_blocks(paper):
        kind = block[0]
        if out[-1] != "" and not (kind == "item" and previous == "item"):
            out.append("")
        if kind == "heading":
            out.append(f"{block[1]} {headings[block[2]]}")
        elif kind == "figure":
            caption = "".join(ja[s] for s in block[1])
            out.append(f"![{caption}{block[2]}]({block[3]})")
        else:
            text = "".join(ja[s] for s in block[1])
            out.append(f"- {text}" if kind == "item" else text)
        previous = kind
    return "\n".join(out).rstrip("\n") + "\n"


JA_NOTICE = (
    "<!-- Generated from paper.md and tests/paper_claims.json by "
    "`python scripts/check_paper_claims.py --write-ja`; do not edit by hand. -->\n"
    "<!-- paper.md と tests/paper_claims.json から生成した日本語版。"
    "直接編集しないこと。 -->"
)


def check(read: Reader) -> List[str]:
    """
    Problems with the recorded claims of the manuscript, empty when all hold.
    原稿の主張記録の問題点。すべて成り立てば空。
    """
    paper = read(PAPER)
    if paper is None:
        return [f"{PAPER} not found"]
    if read(CLAIMS) is None:
        return [f"{CLAIMS} not found"]
    claims = load_claims(read)
    keys = bib_keys(read(BIB) or "")
    sentences = paper_sentences(paper)
    problems: List[str] = []

    recorded: Dict[str, int] = {}
    for entry in claims:
        s = entry.get("sentence", "")
        recorded[s] = recorded.get(s, 0) + 1
    for s, n in recorded.items():
        if n > 1:
            problems.append(f"recorded {n} times: {s[:80]!r}")

    present = set(sentences)
    for s in sentences:
        if s not in recorded:
            problems.append(f"no record for: {s[:100]!r}")
    for entry in claims:
        s = entry.get("sentence", "")
        if s not in present:
            problems.append(f"record for a sentence not in {PAPER}: {s[:80]!r}")
            continue
        status = entry.get("status")
        sources = entry.get("sources", [])
        if status == "verified":
            if not sources:
                problems.append(f"verified without a source: {s[:80]!r}")
            for src in sources:
                problems += [f"{p} (for {s[:50]!r})" for p in _source_problems(src, read, keys)]
        elif status == "unverified":
            if not entry.get("note", "").strip():
                problems.append(f"unverified without a note: {s[:80]!r}")
        else:
            problems.append(f"status must be verified or unverified: {s[:80]!r}")
        ja = entry.get("ja", "").strip()
        if not ja:
            problems.append(f"no Japanese translation for: {s[:80]!r}")
        else:
            problems += [f"{p} in the translation of {s[:50]!r}"
                         for p in translation_problems(s, ja)]

    record = load_record(read)
    headings_ja = record.get("headings_ja", {})
    for block in paper_blocks(paper):
        if block[0] == "heading" and not headings_ja.get(block[2], "").strip():
            problems.append(f"no Japanese translation for the heading {block[2]!r}")
    if front_matter(paper) and not record.get("title_ja", "").strip():
        problems.append("no Japanese translation for the title")
    if not problems:
        expected = render_ja(paper, record)
        if read(PAPER_JA) != expected:
            problems.append(f"{PAPER_JA} does not match paper.md and the recorded translations; "
                            "run `python scripts/check_paper_claims.py --write-ja`")
    return problems


def unverified(claims: Sequence[dict]) -> set:
    return {c.get("sentence", "") for c in claims if c.get("status") == "unverified"}


def unverified_additions(before: Optional[Sequence[dict]], now: Sequence[dict]) -> List[str]:
    """
    Unverified sentences in ``now`` that were not unverified in ``before``.
    ``before`` で未確認でなかったのに ``now`` で未確認の文。

    ``before`` is ``None`` when the record is introduced, which adds nothing.
    記録の導入時は ``before`` が ``None`` で、追加は無いものとする。
    """
    if before is None:
        return []
    return sorted(unverified(now) - unverified(before))


def _head_claims() -> Optional[List[dict]]:
    proc = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{CLAIMS}"],
                          capture_output=True)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout.decode("utf-8")).get("claims", [])


def _write(claims: List[dict]) -> None:
    payload = load_record(doc_excerpts.read_worktree)
    payload["_comment"] = (
        "One entry per prose sentence of paper.md, recording what supports it and "
        "its Japanese translation (ja), from which paper.ja.md is generated. See "
        "scripts/check_paper_claims.py for the source kinds. A commit may not add an "
        "unverified sentence."
    )
    payload["claims"] = claims
    (ROOT / CLAIMS).write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                               encoding="utf-8")


def write_ja() -> int:
    """Regenerate paper.ja.md; refuses while a translation is missing."""
    read = doc_excerpts.read_worktree
    try:
        text = render_ja(read(PAPER) or "", load_record(read))
    except KeyError as e:
        print(f"paper-claims: no Japanese translation for {str(e)[:100]}", file=sys.stderr)
        return 1
    (ROOT / PAPER_JA).write_text(text, encoding="utf-8")
    print(f"wrote {PAPER_JA}")
    return 0


def add_missing() -> int:
    """Append an unverified entry for each sentence without one, in paper order."""
    read = doc_excerpts.read_worktree
    claims = load_claims(read)
    by_sentence = {c.get("sentence"): c for c in claims}
    sentences = paper_sentences(read(PAPER) or "")
    ordered = []
    added = 0
    for s in sentences:
        if s in by_sentence:
            ordered.append(by_sentence.pop(s))
        else:
            ordered.append({"sentence": s, "status": "unverified",
                            "note": "not yet checked against a source"})
            added += 1
    # Records whose sentence left the paper stay, so the check names them.
    # paper.md から消えた文の記録は残し、検査がそれを指摘するようにする。
    ordered += list(by_sentence.values())
    _write(ordered)
    print(f"added {added} unverified entries")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--staged", action="store_true",
                        help="check the staged snapshot (pre-commit)")
    parser.add_argument("--list-unverified", action="store_true",
                        help="print every unverified sentence with its note")
    parser.add_argument("--add-missing", action="store_true",
                        help="add each unrecorded sentence as unverified")
    parser.add_argument("--write-ja", action="store_true",
                        help="regenerate paper.ja.md from the recorded translations")
    args = parser.parse_args(argv)
    if args.add_missing:
        return add_missing()
    if args.write_ja:
        return write_ja()
    read = doc_excerpts.read_staged if args.staged else doc_excerpts.read_worktree
    if args.list_unverified:
        for c in load_claims(read):
            if c.get("status") == "unverified":
                print(f"- {c['sentence']}\n    note: {c.get('note', '')}")
        return 0
    problems = check(read)
    if args.staged:
        problems += [f"this commit adds an unverified sentence: {s[:100]!r}"
                     for s in unverified_additions(_head_claims(), load_claims(read))]
    for p in problems:
        print(f"paper-claims: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
