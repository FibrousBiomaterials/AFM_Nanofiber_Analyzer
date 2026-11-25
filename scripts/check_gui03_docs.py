#!/usr/bin/env python3
"""Keep `docs/gui03_statistics.md` in step with the code it quotes.
`docs/gui03_statistics.md` を、引用しているコードと一致させ続ける検査。

The document explains the statistics GUI03 computes — what one sample is, the
summary statistics, the frame corrections of contour length, and the
between-group tests — quoting the source. Quoted code rots faster than prose,
so this script turns each way the page can go stale into a failure:
この文書は、GUI03 が計算する統計（1 標本とは何か、要約統計量、輪郭長の枠補正、
群間検定）を、ソースを引用しながら説明する。引用したコードは散文より速く陳腐化
するため、本スクリプトは文書が古くなる経路をそれぞれ失敗に変える。

1. Every code excerpt names its source (``# source: <path>::<symbol>``) and
   must still appear, line for line, in that symbol.
   各コード片は出典（``# source: <path>::<symbol>``）を名乗り、そのシンボル内に
   行単位で今も存在しなければならない。
2. Every symbol in `WATCHED_SYMBOLS` is fingerprinted with comments and
   docstrings removed. A change to what one of them computes fails until the
   document has been reviewed and `tests/gui03_doc_manifest.json` refreshed.
   `WATCHED_SYMBOLS` の各シンボルを、コメントと docstring を除いて指紋化する。
   計算内容が変わると、文書を見直して `tests/gui03_doc_manifest.json` を更新
   するまで失敗する。
3. The English and Japanese versions share one heading skeleton and quote the
   same code.
   英語版と日本語版が同じ見出し構造を持ち、同じコードを引用している。

The fingerprint and excerpt machinery is the one `scripts/check_gui04_docs.py`
uses for the GUI04 document, through `scripts/doc_excerpts.py`. It is run in
three places: `.githooks/pre-commit` (``--staged``, against the index),
`tests/test_gui03_docs.py` in CI, and the Claude Code hook
`.claude/hooks/doc_code_reminder.py`, which uses `drifted_symbols` to tell an
agent the moment it edits a documented symbol. Only the standard library is
imported, because the hooks run outside the project environment.
指紋と引用の仕組みは、GUI04 文書の `scripts/check_gui04_docs.py` と同じもので、
`scripts/doc_excerpts.py` を通して使う。実行箇所は 3 つ。`.githooks/pre-commit`
（``--staged``、インデックスに対して）、CI の `tests/test_gui03_docs.py`、および
Claude Code フック `.claude/hooks/doc_code_reminder.py`（`drifted_symbols` を使い、
エージェントが解説対象のシンボルを編集した時点で知らせる）。フックはプロジェクト
環境の外で動くため、標準ライブラリしか import しない。

Usage:
    python scripts/check_gui03_docs.py            # check the working tree
    python scripts/check_gui03_docs.py --staged   # check the index (pre-commit)
    python scripts/check_gui03_docs.py --update   # refresh the fingerprints

Exit codes: 0 = clean, 1 = findings, 2 = usage or git error (fails closed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# The shared excerpt contract lives beside this script. Put its directory on the
# path explicitly, because the Claude Code hook loads this file by path, where
# the script's own directory is not searched.
# 共通の引用規約はこのスクリプトの隣にある。Claude Code フックはこのファイルを
# パス指定で読み込み、その場合スクリプト自身のディレクトリは検索されないため、
# 明示的にパスへ加える。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from doc_excerpts import (  # noqa: E402
    ROOT,
    Reader,
    _SOURCE_HEADER,  # noqa: F401  (read by .claude/hooks/doc_code_reminder.py)
    check_pair_excerpts,
    headings,
    read_staged,
    read_worktree,
    split_symbol,
    symbol_digest,
)

DOC_EN = "docs/gui03_statistics.md"
DOC_JA = "docs/gui03_statistics.ja.md"
MANIFEST = "tests/gui03_doc_manifest.json"

_GUI03 = "guis/GUI03_Fiber_Morphology_Statistics.py"
_COMPARE = "afm_nanofiber_analyzer/group_compare.py"
_MEASURE = "afm_nanofiber_analyzer/measure.py"

# The symbols the document quotes and explains, fingerprinted one by one rather
# than by module: GUI03 is several thousand lines, and a module-level
# fingerprint would demand a document review for every unrelated UI edit.
# Adding an excerpt of a new symbol means adding it here; the check refuses an
# excerpt of a symbol that is not watched, so quoted code is always guarded.
# 文書が引用・解説するシンボル。モジュール単位ではなく 1 つずつ指紋化する。
# GUI03 は数千行あり、モジュール単位の指紋では無関係な UI 編集のたびに文書の
# 見直しを要求してしまうためである。新しいシンボルを引用するときはここへ追加する。
# 監視外のシンボルの引用は検査が拒否するため、引用したコードは常に守られる。
WATCHED_SYMBOLS: Tuple[str, ...] = (
    f"{_GUI03}::PARAM_SPECS",
    f"{_GUI03}::_fiber_value",
    f"{_GUI03}::App._values_from_fiber_stats",
    f"{_GUI03}::App._curvature_values",
    f"{_GUI03}::_kink_totals",
    f"{_GUI03}::App._collect_bundle_values",
    f"{_MEASURE}::_skeleton_pixel_heights",
    f"{_GUI03}::_summary_stats",
    f"{_GUI03}::_bin_results",
    f"{_GUI03}::MIN_SAMPLES_FOR_SHAPE",
    f"{_GUI03}::App._draw_ecdf",
    f"{_GUI03}::App._draw_box",
    f"{_GUI03}::_apply_frame_mode",
    f"{_MEASURE}::_frame_weight",
    f"{_GUI03}::App._run_comparison",
    f"{_MEASURE}::fiber_real_end_count",
    f"{_MEASURE}::kaplan_meier_length_weights",
    f"{_GUI03}::_apply_kaplan_meier",
    f"{_GUI03}::_kaplan_meier_bounds",
    f"{_GUI03}::_kaplan_meier_summary",
    f"{_GUI03}::KM_RESAMPLES",
    f"{_GUI03}::KM_RESAMPLE_SEED",
    f"{_GUI03}::_kaplan_meier_interval",
    f"{_GUI03}::TESTABLE_UNITS",
    f"{_COMPARE}::_split_statistics",
    f"{_COMPARE}::MIN_SAMPLES_FOR_TEST",
    f"{_COMPARE}::_EXACT_ARRANGEMENT_LIMIT",
    f"{_COMPARE}::_SAMPLED_SPLITS",
    f"{_COMPARE}::_SAMPLED_SEED",
    f"{_COMPARE}::_SAMPLED_MAX_VALUES",
    f"{_COMPARE}::_pair_pvalues",
    f"{_COMPARE}::_exact_pvalues",
    f"{_COMPARE}::_sampled_pvalues",
    f"{_COMPARE}::holm_adjusted",
    f"{_COMPARE}::compare_groups",
    f"{_COMPARE}::cliffs_delta",
    f"{_COMPARE}::MAGNITUDE_THRESHOLDS",
    f"{_COMPARE}::MAGNITUDE_LARGE",
    f"{_COMPARE}::delta_magnitude",
    f"{_COMPARE}::_min_attainable_p",
    f"{_GUI03}::CONVENTIONAL_ALPHA",
    f"{_GUI03}::_attainable_p_note",
)


# ----------------------------------------------------------------------------
# Fingerprints
# ----------------------------------------------------------------------------

def current_digests(reader: Reader = read_worktree,
                    symbols: Sequence[str] = WATCHED_SYMBOLS) -> Dict[str, Optional[str]]:
    """Fingerprint the given symbols as `reader` sees the sources."""
    cache: Dict[str, Optional[str]] = {}
    out: Dict[str, Optional[str]] = {}
    for key in symbols:
        path, name = split_symbol(key)
        if path not in cache:
            cache[path] = reader(path)
        source = cache[path]
        out[key] = None if source is None else symbol_digest(source, name)
    return out


def recorded_digests(reader: Reader = read_worktree) -> Dict[str, str]:
    """Return the fingerprints recorded in the manifest (empty if absent)."""
    text = reader(MANIFEST)
    if text is None:
        return {}
    return json.loads(text).get("symbols", {})


def drifted_symbols(path: str, reader: Reader = read_worktree) -> List[str]:
    """
    Return the watched symbols of one file whose code no longer matches.
    1 ファイル内の監視シンボルのうち、記録と一致しなくなったものを返す。

    Used by the Claude Code hook right after an edit to `path`.
    `path` の編集直後に Claude Code フックが使う。
    """
    keys = [k for k in WATCHED_SYMBOLS if split_symbol(k)[0] == path]
    if not keys:
        return []
    recorded = recorded_digests(reader)
    now = current_digests(reader, keys)
    return [k for k in keys if recorded.get(k) != now[k]]


def watched_paths() -> List[str]:
    """Return the source files that hold at least one watched symbol."""
    return sorted({split_symbol(k)[0] for k in WATCHED_SYMBOLS})


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

def check_documents(reader: Reader = read_worktree) -> List[str]:
    """
    Return every problem with the documents themselves.
    文書自体の問題をすべて返す。

    Covers presence, the shared structure of the pair, the excerpts, and the
    coverage of every watched symbol.
    存在、対の構造一致、引用、全監視シンボルの網羅を扱う。
    """
    problems: List[str] = []
    docs = {rel: reader(rel) for rel in (DOC_EN, DOC_JA)}
    for rel, text in docs.items():
        if text is None:
            problems.append(f"{rel} is missing")
    if any(text is None for text in docs.values()):
        return problems
    en, ja = docs[DOC_EN], docs[DOC_JA]

    if headings(en) != headings(ja):
        problems.append(
            f"{DOC_EN} and {DOC_JA} have diverged in structure; add the "
            "corresponding section to the other file"
        )
    excerpt_problems, quoted = check_pair_excerpts(
        docs, reader, allowed=WATCHED_SYMBOLS,
        allowed_label="WATCHED_SYMBOLS (scripts/check_gui03_docs.py)",
    )
    problems.extend(excerpt_problems)

    # A watched symbol nothing quotes would be fingerprinted for no reader, and
    # its changes would demand reviews of a page that does not show it.
    # 何も引用しない監視シンボルは読者のいない指紋となり、それを示さないページの
    # 見直しを変更のたびに要求してしまう。
    for rel in docs:
        for key in WATCHED_SYMBOLS:
            if key not in quoted[rel]:
                problems.append(f"{rel}: watched symbol {key} is never quoted")
    return problems


def check_fingerprints(reader: Reader = read_worktree) -> List[str]:
    """Return one problem per watched symbol whose code changed or vanished."""
    recorded = recorded_digests(reader)
    problems = []
    for key, digest in current_digests(reader).items():
        if digest is None:
            problems.append(f"{key} no longer exists")
        elif recorded.get(key) != digest:
            problems.append(f"{key} changed since the document was reviewed")
    stale = sorted(set(recorded) - set(WATCHED_SYMBOLS))
    for key in stale:
        problems.append(f"{MANIFEST} records {key}, which is no longer watched")
    return problems


def _staged_names() -> set:
    """Return the repository-relative paths in the staged diff."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "-z"],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git diff --cached failed: {detail}")
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def update_manifest() -> None:
    """Rewrite the fingerprint manifest from the working tree."""
    digests = current_digests(read_worktree)
    missing = [k for k, v in digests.items() if v is None]
    if missing:
        raise SystemExit("cannot fingerprint missing symbols: " + ", ".join(missing))
    payload = {
        "_comment": (
            "SHA-256 of each symbol docs/gui03_statistics.md explains, with "
            "comments and docstrings removed. Refresh with "
            "`python scripts/check_gui03_docs.py --update` only after "
            "rereading the affected sections of both language versions."
        ),
        "symbols": digests,
    }
    (ROOT / MANIFEST).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"updated {MANIFEST}")


_HOW_TO_FIX = (
    "\n"
    "docs/gui03_statistics.md (and its .ja.md pair) explains the code above\n"
    "to the people who cite GUI03's statistics. Reread the sections that quote\n"
    "the changed symbols, update both language versions (including the quoted\n"
    "excerpts), then refresh the fingerprints:\n"
    "\n"
    "    .venv\\Scripts\\python.exe scripts\\check_gui03_docs.py --update\n"
)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point: check the working tree, check the index, or update."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--staged", action="store_true",
                       help="check the staged snapshot; used by pre-commit")
    group.add_argument("--update", action="store_true",
                       help="refresh tests/gui03_doc_manifest.json")
    args = parser.parse_args(argv)

    if args.update:
        update_manifest()
        return 0

    reader = read_staged if args.staged else read_worktree
    try:
        problems = check_fingerprints(reader) + check_documents(reader)
        if args.staged:
            staged = _staged_names()
            # Refreshing the fingerprints is the claim that the document was
            # reread, so it has to come with the document.
            # 指紋の更新は「文書を読み直した」という主張なので、文書の変更を伴う
            # 必要がある。
            if MANIFEST in staged and not staged & {DOC_EN, DOC_JA}:
                problems.append(
                    f"{MANIFEST} is refreshed but neither {DOC_EN} nor "
                    f"{DOC_JA} is part of the commit"
                )
    except (RuntimeError, SyntaxError, ValueError) as exc:
        print(f"gui03-doc check: {exc}", file=sys.stderr)
        return 2

    if not problems:
        return 0
    label = "staged snapshot" if args.staged else "working tree"
    print(f"gui03-doc check ({label}):", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(_HOW_TO_FIX, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
