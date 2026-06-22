# -*- coding: utf-8 -*-
"""
Strict (exact) pipeline-output regression test on the bundled real scans.
同梱された実測スキャンに対する、パイプライン出力の厳密（完全一致）回帰テスト。

Unlike `test_integration.py`, which checks a few summary statistics with a 5%
tolerance, this test pins every output array of the preprocessing pipeline
(`calibrated`, `binarized`, `skeletonized`, `bp`, `ep`, `kp`, `dp`, `ka`) to a
recorded SHA-256 baseline, for every bundled sample file in
``testdata_tunicateCNF`` and ``testdata_higherplantTOC`` and for all four
``bg_method`` values. It is the permanent form of the by-hand before/after
array comparison used to verify the lib refactor: any code change that alters
a single output value — including ``calibrated`` heights that the tolerant
golden test could mask — makes this test fail.
`test_integration.py` が要約統計を 5% 許容で照合するのに対し、本テストは
前処理パイプラインの全出力配列（``calibrated``・``binarized``・
``skeletonized``・``bp``・``ep``・``kp``・``dp``・``ka``）を記録済みの
SHA-256 ベースラインに固定する。対象は ``testdata_tunicateCNF`` と
``testdata_higherplantTOC`` の同梱サンプル全ファイル × 全 4 ``bg_method``。
lib リファクタリング検証で手作業で行った前後の配列比較を恒久化したもので、
``calibrated`` の高さ 1 要素の変化（許容付きゴールデンテストでは見逃しうる）
を含め、出力を変える変更があれば必ず失敗する。

Re-baselining / ベースライン更新
--------------------------------
The pipeline is deterministic, but exact byte hashes can legitimately change
after an intentional algorithm change or a dependency upgrade that shifts
floating-point results. When that happens, regenerate the golden file and
record the reason in the commit message::

    .venv/Scripts/python.exe tests/test_strict_regression.py --update

パイプラインは決定的だが、意図したアルゴリズム変更や浮動小数点結果が動く
依存更新で、厳密バイトハッシュが正当に変わることがある。その場合は上記
コマンドで golden を再生成し、理由をコミットメッセージに残すこと。
"""

# ===== Standard library =====
import glob
import hashlib
import json
import tempfile
from pathlib import Path

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Test / project libraries =====
import pytest

from lib.pipeline import ProcParams, process_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = Path(__file__).resolve().parent / "strict_regression_golden.json"

# Folders whose bundled .txt scans are used as regression samples.
# 回帰サンプルに使う、同梱 .txt スキャンのフォルダ。
SAMPLE_DIRS = ("testdata_tunicateCNF", "testdata_higherplantTOC")

# All background-estimation methods are exercised so the strict baseline also
# guards the spline and tophat code paths, not just the default inpaint.
# 既定の inpaint だけでなく spline / tophat 経路も厳密ベースラインで守るため、
# 全背景推定方式を実行する。
BG_METHODS = ("inpaint", "tophat", "spline1d", "spline2d")

# Output arrays compared. These are exactly the keys written into the .b2z
# bundle, i.e. the full analysis output of the pipeline.
# 比較する出力配列。.b2z バンドルへ書き込まれるキー全体（パイプラインの
# 解析出力すべて）に一致する。
ARRAY_KEYS = (
    "calibrated", "binarized", "skeletonized",
    "bp", "ep", "kp", "dp", "ka",
)


def _sample_files() -> list:
    """
    Return all bundled sample ``.txt`` scans across the regression folders.
    回帰用フォルダ群に含まれる全サンプル ``.txt`` スキャンを返す。
    """
    files: list = []
    for d in SAMPLE_DIRS:
        files += sorted(glob.glob(str(PROJECT_ROOT / d / "*.txt")))
    return files


def _rel(path: str) -> str:
    """
    Return a stable POSIX-style repo-relative key for a sample path.
    サンプルパスに対する、安定した POSIX 形式のリポジトリ相対キーを返す。
    """
    return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()


def _hash_array(a: np.ndarray) -> dict:
    """
    Return a dtype/shape-qualified SHA-256 signature of one array's bytes.
    配列バイト列の SHA-256 署名（dtype・shape 付き）を返す。

    The dtype and shape are folded into the digest input so that an array
    which changed shape or dtype but happens to share leading bytes still
    produces a different signature.
    dtype と shape をダイジェスト入力に含めることで、shape や dtype が変わり
    先頭バイトが偶然一致するだけの配列でも別署名になるようにする。
    """
    arr = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(arr.dtype).encode("ascii"))
    h.update(str(arr.shape).encode("ascii"))
    h.update(arr.tobytes())
    return {"dtype": str(arr.dtype), "shape": list(arr.shape), "sha256": h.hexdigest()}


def _pipeline_signatures(txt_path: str) -> dict:
    """
    Run the pipeline for every ``bg_method`` and hash all output arrays.
    全 ``bg_method`` でパイプラインを実行し、全出力配列をハッシュ化する。

    Returns
    -------
    dict
        Mapping ``"{method}::{key}"`` to a signature dict from `_hash_array`.
        ``"{method}::{key}"`` から `_hash_array` の署名辞書への対応。
    """
    sigs: dict = {}
    with tempfile.TemporaryDirectory() as out_dir:
        for method in BG_METHODS:
            result = process_file(
                txt_path, ProcParams(bg_method=method), output_dir=out_dir,
            )
            image = result.image
            kx, ky = image.all_kink_coordinates
            dx, dy = image.decomposed_point_coordinates
            arrays = {
                "calibrated":   image.calibrated_image,
                "binarized":    image.binarized_image,
                "skeletonized": image.skeleton_image,
                "bp":           image.bp,
                "ep":           image.ep,
                "kp":           np.stack([np.asarray(kx), np.asarray(ky)]),
                "dp":           np.stack([np.asarray(dx), np.asarray(dy)]),
                "ka":           np.asarray(image.all_kink_angles),
            }
            for key in ARRAY_KEYS:
                sigs[f"{method}::{key}"] = _hash_array(arrays[key])
    return sigs


def _load_golden() -> dict:
    """
    Load the recorded golden signatures, or an empty mapping when absent.
    記録済み golden 署名を読み込む。無い場合は空辞書。
    """
    if not GOLDEN_PATH.exists():
        return {}
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


_SAMPLES = _sample_files()

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not _SAMPLES, reason="no bundled sample scans present"),
    pytest.mark.skipif(
        not GOLDEN_PATH.exists(),
        reason="strict_regression_golden.json missing; run with --update to create it",
    ),
]


@pytest.mark.parametrize("txt_path", _SAMPLES, ids=_rel)
def test_pipeline_output_matches_golden(txt_path):
    """Every pipeline output array exactly matches the recorded baseline."""
    golden = _load_golden()
    key = _rel(txt_path)
    assert key in golden, (
        f"no golden baseline for {key}; a new sample file was added. "
        f"Regenerate with: python tests/test_strict_regression.py --update"
    )
    expected = golden[key]
    actual = _pipeline_signatures(txt_path)

    mismatches = []
    for sig_key, exp in expected.items():
        act = actual.get(sig_key)
        if act != exp:
            mismatches.append(f"{sig_key}: expected {exp} got {act}")
    # Also flag any newly produced signature absent from the baseline.
    # ベースラインに無い新規署名も検出する。
    for sig_key in actual.keys() - expected.keys():
        mismatches.append(f"{sig_key}: not in golden baseline")

    assert not mismatches, (
        f"strict pipeline-output mismatch for {key}:\n  "
        + "\n  ".join(mismatches)
        + "\n\nIf this change is intentional, re-baseline with: "
        "python tests/test_strict_regression.py --update"
    )


def _regenerate_golden() -> None:
    """
    Recompute and overwrite the golden baseline for all sample files.
    全サンプルファイルの golden ベースラインを再計算して上書きする。
    """
    golden = {}
    samples = _sample_files()
    for i, txt_path in enumerate(samples, start=1):
        key = _rel(txt_path)
        print(f"[{i}/{len(samples)}] {key}")
        golden[key] = _pipeline_signatures(txt_path)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"wrote {GOLDEN_PATH} ({len(golden)} files)")


if __name__ == "__main__":
    import sys

    if "--update" in sys.argv:
        _regenerate_golden()
    else:
        print(__doc__)
        print("Pass --update to regenerate the golden baseline.")
