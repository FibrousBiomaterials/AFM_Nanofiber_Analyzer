# -*- coding: utf-8 -*-
"""
Bundle caches are keyed by the code and libraries that made the bundles.
バンドルのキャッシュは、バンドルを作ったコードとライブラリで区別される。

`scripts/measure_docs.py` and `scripts/kink_reference_score.py` reuse analyzed
bundles. A bundle reused after the analysis changed reports what the old code
computed under the new code's name, so the cache folder is named by
`bundle_cache.fingerprint`; these tests check that the name follows a change
to the computation or to a library and ignores a comment, and that switching
folders removes only the folders of other fingerprints.
`scripts/measure_docs.py` と `scripts/kink_reference_score.py` は解析済みの
バンドルを使い回す。解析が変わった後に使い回すと、新しいコードの名で古いコードの
計算結果を報告してしまうため、キャッシュフォルダは `bundle_cache.fingerprint` で
名付ける。このテストは、その名前が計算やライブラリの変更には追従しコメントには
反応しないこと、フォルダを切り替えると他の指紋のフォルダだけが消えることを確かめる。
"""

# ===== Standard library =====
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import bundle_cache  # noqa: E402
import doc_excerpts  # noqa: E402

SOURCE = "def stage(x):\n    return x + 1\n"
COMMENTED = "def stage(x):\n    # add one\n    return x + 1\n"
CHANGED = "def stage(x):\n    return x + 2\n"
VERSIONS = {"python": "3.13.0", "numpy": "2.3.0"}


def _fp(source: str, versions=VERSIONS) -> str:
    return bundle_cache.fingerprint_of(
        {"lib/stage.py": doc_excerpts.code_symbol_digests(source)}, versions)


def test_a_computation_change_selects_a_new_folder():
    """Changing what the code computes changes the folder name."""
    assert _fp(SOURCE) != _fp(CHANGED)


def test_a_comment_keeps_the_folder():
    """A comment or docstring edit keeps the cached bundles."""
    assert _fp(SOURCE) == _fp(COMMENTED)


def test_a_library_upgrade_selects_a_new_folder():
    """A different version of a numerical library changes the folder name."""
    assert _fp(SOURCE) != _fp(SOURCE, {**VERSIONS, "numpy": "2.4.0"})


def test_the_pipeline_fingerprint_covers_every_stage():
    """Every analysis stage module is part of the fingerprinted code."""
    reached = set(bundle_cache.closure(bundle_cache.PIPELINE_ROOTS))
    for rel in ("lib/bg_calibrator.py", "lib/segmenter.py", "lib/skeletonizer.py",
                "lib/kink_detector.py", "lib/centerline.py"):
        assert rel in reached


def test_switching_folders_removes_only_other_fingerprints(tmp_path):
    """Other fingerprints' folders go; unrelated files and folders stay."""
    old = tmp_path / "0123456789ab"
    (old / "scan").mkdir(parents=True)
    (old / "scan" / "x.b2z").write_bytes(b"old")
    keep_dir = tmp_path / "worktree_v1.0.0"
    keep_dir.mkdir()
    keep_file = tmp_path / "notes.txt"
    keep_file.write_text("keep", encoding="utf-8")

    folder = bundle_cache.cache_root(tmp_path, current="fedcba987654")

    assert folder == tmp_path / "fedcba987654" and folder.is_dir()
    assert not old.exists()
    assert keep_dir.is_dir() and keep_file.is_file()


def test_the_current_folder_is_kept(tmp_path):
    """Bundles already cached under the current fingerprint are reused."""
    current = tmp_path / "fedcba987654"
    current.mkdir()
    (current / "x.b2z").write_bytes(b"cached")
    bundle_cache.cache_root(tmp_path, current="fedcba987654")
    assert (current / "x.b2z").read_bytes() == b"cached"
