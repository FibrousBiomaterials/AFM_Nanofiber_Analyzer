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
import ast
import re
import sys
from pathlib import Path

# ===== Test libraries =====
import pytest

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
        {"afm_nanofiber_analyzer/stage.py": doc_excerpts.code_symbol_digests(source)}, versions)


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
    for rel in ("afm_nanofiber_analyzer/bg_calibrator.py", "afm_nanofiber_analyzer/segmenter.py", "afm_nanofiber_analyzer/skeletonizer.py",
                "afm_nanofiber_analyzer/kink_detector.py", "afm_nanofiber_analyzer/centerline.py"):
        assert rel in reached


def test_the_fingerprint_covers_the_code_that_draws_synthetic_scans():
    """
    The renderer and the sweep that cached synthetic bundles are drawn with are fingerprinted.
    キャッシュする合成バンドルの画像を描く描画器と掃引は、指紋に含まれる。

    A bundle of a synthetic scan depends on how the scan was drawn as much as
    on the pipeline, so a renderer left out would let a scan drawn by older
    code be reused after the drawing changed.
    合成画像のバンドルは、パイプラインと同じだけ画像の描き方に依存する。描画器が
    含まれていないと、描き方を変えた後も古いコードで描いた画像が使い回される。
    """
    for rel in ("tests/synthetic_fibers.py", "scripts/kink_rule_sweep.py",
                "scripts/synthetic_suite.py"):
        assert rel in bundle_cache.INPUT_GENERATORS
    for rel in bundle_cache.INPUT_GENERATORS:
        assert (bundle_cache.ROOT / rel).is_file(), rel


NARROWED = "def draw():\n    return 1\n\n\ndef score():\n    return 2\n"


def test_a_narrowed_file_follows_only_its_named_definitions(monkeypatch):
    """
    Of a file with named definitions, only those select a new folder.
    定義を名指ししたファイルでは、その定義だけが新しいフォルダを選ぶ。

    A definition that is named but no longer in the file is an error rather
    than a silent hole in the fingerprint.
    名指しした定義がファイルから無くなった場合は、指紋に黙って穴が開くのではなく、
    エラーになる。
    """
    monkeypatch.setitem(bundle_cache.GENERATOR_DEFINITIONS, "x.py", ("draw",))
    base = bundle_cache.generator_digests("x.py", NARROWED)
    assert base == bundle_cache.generator_digests("x.py", NARROWED.replace("return 2", "return 3"))
    assert base != bundle_cache.generator_digests("x.py", NARROWED.replace("return 1", "return 4"))
    with pytest.raises(KeyError):
        bundle_cache.generator_digests("x.py", "def score():\n    return 2\n")
    whole = bundle_cache.generator_digests("y.py", NARROWED)
    assert whole != bundle_cache.generator_digests("y.py", NARROWED.replace("return 2", "return 3"))


def _module_definitions(tree: ast.Module) -> dict:
    """Top-level functions and assigned names of a module, by name."""
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def test_the_named_definitions_of_each_narrowed_file_are_closed():
    """
    A named definition reads no definition of its file that is not named too.
    名指しした定義は、同じファイルの名指ししていない定義を読まない。

    Otherwise a constant or helper the drawing code uses could change without
    the folder changing, and scans drawn the old way would be reused.
    そうでなければ、描画のコードが使う定数や補助関数が変わってもフォルダが変わらず、
    古い描き方の画像が使い回されてしまう。
    """
    for rel, names in bundle_cache.GENERATOR_DEFINITIONS.items():
        source = (bundle_cache.ROOT / rel).read_text(encoding="utf-8")
        assert set(bundle_cache.generator_digests(rel, source)) == set(names)
        definitions = _module_definitions(ast.parse(source))
        for name in names:
            read = {n.id for n in ast.walk(definitions[name]) if isinstance(n, ast.Name)}
            unnamed = sorted((read & set(definitions)) - set(names))
            assert not unnamed, f"{rel}::{name} reads {unnamed}, which the fingerprint leaves out"


# Names of scripts/kink_rule_sweep.py that scripts/measure_docs.py uses and
# that decide no bundle's content: how the sweep is run, and the grid of
# widths and noise levels, each value of which is part of a scan's file name.
# scripts/measure_docs.py が使う scripts/kink_rule_sweep.py の名前のうち、
# バンドルの中身を決めないもの。掃引の実行方法と、幅・ノイズ水準の格子
# （その各値は画像のファイル名に含まれる）。
SWEEP_NAMES_OUTSIDE_THE_FINGERPRINT = {"run", "default_jobs", "WIDTHS_PX", "NOISES_NM"}


def test_the_experiments_draw_only_with_fingerprinted_sweep_definitions():
    """
    Every sweep definition the documentation experiments use is fingerprinted or listed as harmless.
    文書用の実験が使う掃引の定義は、すべて指紋に入っているか、無害なものとして挙げてある。
    """
    source = (bundle_cache.ROOT / "scripts" / "measure_docs.py").read_text(encoding="utf-8")
    used = set(re.findall(r"\bsweep\.([A-Za-z_]\w*)", source))
    named = set(bundle_cache.GENERATOR_DEFINITIONS["scripts/kink_rule_sweep.py"])
    assert used - named - SWEEP_NAMES_OUTSIDE_THE_FINGERPRINT == set()


def _recorder(removed):
    """Stand-in for the recycle bin that records the folders it is given."""
    return lambda paths: removed.extend(paths)


def test_switching_folders_removes_only_other_fingerprints(tmp_path):
    """Other fingerprints' folders go; unrelated files and folders stay."""
    base = tmp_path / "cache"
    old = base / "0123456789ab"
    (old / "scan").mkdir(parents=True)
    keep_dir = base / "worktree_v1.0.0"
    keep_dir.mkdir()
    keep_file = base / "notes.txt"
    keep_file.write_text("keep", encoding="utf-8")

    removed = []
    folder = bundle_cache.cache_root(base, current="fedcba987654", remove=_recorder(removed))

    assert folder == base / "fedcba987654" and folder.is_dir()
    assert removed == [old]


def test_the_current_folder_is_kept(tmp_path):
    """Bundles already cached under the current fingerprint are reused."""
    current = tmp_path / "fedcba987654"
    current.mkdir()
    (current / "x.b2z").write_bytes(b"cached")
    removed = []
    bundle_cache.cache_root(tmp_path, current="fedcba987654", remove=_recorder(removed))
    assert removed == [] and (current / "x.b2z").read_bytes() == b"cached"


def test_the_trash_refuses_paths_outside_the_repository(tmp_path):
    """Nothing outside the repository can be sent to the recycle bin."""
    import pytest
    import trash

    outside = tmp_path / "data.txt"
    outside.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        trash.send_to_trash([outside])
    with pytest.raises(ValueError):
        trash.send_to_trash([PROJECT_ROOT])
    assert outside.read_text(encoding="utf-8") == "keep"
