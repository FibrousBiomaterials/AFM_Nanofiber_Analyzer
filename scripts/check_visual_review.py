#!/usr/bin/env python3
"""
Block a change to the GUI01 analysis stages that nobody has looked at.
誰も目で確かめていない、GUI01 の解析段階の変更を止める。

A change to what background correction, binarization, skeletonization, the
centerline or kink detection computes is accepted only after its effect has
been rendered on the bundled scans (``scripts/visual_diff.py compare``) and a
person has looked at the images and approved what they show
(``scripts/visual_diff.py approve``). The record of that review is
``tests/visual_review.json``, keyed by a fingerprint of the code of
`VISUAL_MODULES` with comments and docstrings removed, so editing a comment
needs no review while any change to what the code computes does.
背景補正・二値化・細線化・中心線・キンク検出の計算を変えた変更は、その効果を同梱
スキャンに描き（``scripts/visual_diff.py compare``）、人が画像を見て、示されたことを
承認した（``scripts/visual_diff.py approve``）後でだけ受け入れる。確認の記録は
``tests/visual_review.json`` にあり、コメントと docstring を除いた `VISUAL_MODULES`
のコードの指紋で引く。そのため、コメントの修正には確認が要らず、計算を変える変更には
必ず確認が要る。

A fingerprint is covered by a record whose ``status`` is ``approved`` (with a
non-empty ``approved_by``), ``identical`` (``compare`` found every stage's
output bit-identical to its base on the bundled scans, so there is nothing to
look at), or ``baseline`` (the code this check was introduced on, which no
review covers).
指紋は、``status`` が ``approved``（``approved_by`` が空でない）、``identical``
（``compare`` が同梱スキャンで全段階の出力を基準とビット単位で同一と判定し、見る
ものがない）、``baseline``（このチェックを導入したときのコードで、どの確認にも
覆われない）のいずれかの記録があれば覆われる。

Usage::

    python scripts/check_visual_review.py            # the working tree (CI)
    python scripts/check_visual_review.py --staged   # the staged snapshot (pre-commit)

``--staged`` checks only a commit whose staged code changes the fingerprint
against ``HEAD``, so commits that do not touch the analysis are unaffected.
The pre-commit hook is the early warning; ``tests/test_visual_review.py`` runs
the working-tree check in CI, where it cannot be skipped.
``--staged`` は、ステージしたコードが ``HEAD`` に対して指紋を変えるコミットだけを
調べるので、解析に触れないコミットには影響しない。pre-commit フックは早期警告で、
``tests/test_visual_review.py`` が CI で作業ツリーの検査を行い、そこでは迂回できない。
"""

# ===== Standard library =====
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import doc_excerpts  # noqa: E402

# The modules of the GUI01 analysis stages whose computation needs a review.
# 計算の変更に確認が要る、GUI01 の解析段階のモジュール。
VISUAL_MODULES = (
    "lib/bg_calibrator.py",
    "lib/segmenter.py",
    "lib/skeletonizer.py",
    "lib/centerline.py",
    "lib/kink_detector.py",
    "lib/imp_tools.py",
    "lib/pipeline.py",
)
RECORD = "tests/visual_review.json"
COVERING_STATUSES = ("approved", "identical", "baseline")


def fingerprint(read: Callable[[str], Optional[str]]) -> str:
    """
    Fingerprint the code of `VISUAL_MODULES` as `read` returns it.
    `read` が返す `VISUAL_MODULES` のコードの指紋を取る。

    Parameters
    ----------
    read
        Returns a repository path's text, or None when the file is absent.
        リポジトリのパスの内容を返す。ファイルが無ければ None。

    Returns
    -------
    str
        Twelve hexadecimal characters; comments and docstrings do not enter it.
        16 進 12 文字。コメントと docstring は含まない。
    """
    code = {path: (doc_excerpts.code_symbol_digests(text) if text is not None else None)
            for path in VISUAL_MODULES for text in [read(path)]}
    payload = json.dumps(code, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def read_worktree(path: str) -> Optional[str]:
    """
    Return a file of the working tree, or None.
    作業ツリーのファイルを返す。無ければ None。
    """
    full = ROOT / path
    return full.read_text(encoding="utf-8") if full.is_file() else None


def read_git(revision: str) -> Callable[[str], Optional[str]]:
    """
    Return a reader of files at `revision` (``""`` for the index).
    `revision` 時点のファイルを読む関数を返す（索引は ``""``）。
    """
    def read(path: str) -> Optional[str]:
        done = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=ROOT,
                              capture_output=True)
        return done.stdout.decode("utf-8") if done.returncode == 0 else None
    return read


def load_reviews(text: Optional[str]) -> List[Dict]:
    """
    Parse the review record; an absent record holds no reviews.
    確認の記録を読む。記録が無ければ確認は無い。
    """
    if not text:
        return []
    return list(json.loads(text).get("reviews", []))


def covering(reviews: List[Dict], print_: str) -> Optional[Dict]:
    """
    Return the review that covers fingerprint `print_`, or None.
    指紋 `print_` を覆う確認を返す。無ければ None。
    """
    for review in reviews:
        if review.get("fingerprint") != print_:
            continue
        status = review.get("status")
        if status == "approved" and not str(review.get("approved_by") or "").strip():
            continue
        if status in COVERING_STATUSES:
            return review
    return None


def problems(read: Callable[[str], Optional[str]], base: Optional[Callable] = None) -> List[str]:
    """
    Return why the code `read` returns is not covered by a review.
    `read` が返すコードが確認に覆われていない理由を返す。

    Parameters
    ----------
    read
        Reader of the code and of the record to check.
        調べるコードと記録を読む関数。
    base
        Reader of the code the change is made against; when given and the
        fingerprint equals its fingerprint, nothing is required.
        変更の基準となるコードを読む関数。与えられ、指紋がそれと等しければ何も
        求めない。
    """
    current = fingerprint(read)
    if base is not None and fingerprint(base) == current:
        return []
    if covering(load_reviews(read(RECORD)), current) is not None:
        return []
    return [
        f"the analysis stages ({', '.join(VISUAL_MODULES)}) compute something "
        f"that no review covers (fingerprint {current}). Run "
        "`.venv\\Scripts\\python.exe scripts\\visual_diff.py compare` against the "
        "commit the change is made on, look at the images it writes, record what "
        "changed with `visual_diff.py record`, and have a person approve it with "
        "`visual_diff.py approve --by NAME` (AGENTS.md §8.18)."
    ]


def main(argv: Optional[List[str]] = None) -> int:
    """
    Check the working tree, or the staged snapshot with ``--staged``.
    作業ツリーを、``--staged`` ならステージした内容を調べる。
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--staged", action="store_true",
                        help="check the staged snapshot against HEAD (pre-commit)")
    args = parser.parse_args(argv)
    if args.staged:
        found = problems(read_git(""), base=read_git("HEAD"))
    else:
        found = problems(read_worktree)
    for problem in found:
        print(f"check_visual_review: {problem}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
