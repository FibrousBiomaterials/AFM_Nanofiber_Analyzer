# -*- coding: utf-8 -*-
"""
Strict (exact) regression test of the measurement layer on the bundled scans.
同梱スキャンに対する、計測層の厳密（完全一致）回帰テスト。

`test_strict_regression.py` pins the arrays the preprocessing pipeline stores;
this test pins what is *measured* from them. Each of the five bundled scans
(`scripts/kink_reference_score.SCANS`) is analyzed with the default settings
and with each skeleton cleanup turned off (``max_loop_area=0``,
``spur_length=0``), and the bundle is measured as GUI03, GUI04 and ``cli.py``
measure it (`measure.measure_bundle`, `measure.skeleton_height_values`). The
per-fiber CSV that `measure.write_fiber_csv` writes and the traced height
values are recorded as SHA-256 hashes, so a change to any measured value fails
the test, including one made only when a bundle is read, which the pipeline
goldens cannot see. The settings that turn a cleanup off are included because
a reader that repeats a cleanup at its own defaults leaves the default
analysis unchanged and overrides only such settings.
`test_strict_regression.py` はパイプラインが保存する配列を固定する。本テストは
そこから *計測される* 値を固定する。同梱の 5 スキャン
（`scripts/kink_reference_score.SCANS`）を既定の設定と、骨格のクリーニングを
それぞれ切った設定（``max_loop_area=0``、``spur_length=0``）で解析し、GUI03・
GUI04・``cli.py`` と同じ方法（`measure.measure_bundle`、
`measure.skeleton_height_values`）で計測する。`measure.write_fiber_csv` が書く
繊維ごとの CSV と追跡した高さの値を SHA-256 ハッシュで記録するので、計測値が
1 つでも変われば失敗する。バンドルを読むときだけに起きる変化も含み、これは
パイプラインの golden からは見えない。クリーニングを切る設定を含めるのは、
読み込み側が自分の既定値でクリーニングを繰り返すと、既定の解析は変わらず、
そうした設定だけが上書きされるためである。

A change to `measurement_regression_golden.json` means measured results moved,
so `scripts/check_changelog.py` requires a ``## [Unreleased]`` entry in
``CHANGELOG.md`` in the same commit (AGENTS.md §8.11).
`measurement_regression_golden.json` の変更は計測結果が動いたことを意味する
ので、`scripts/check_changelog.py` は同じコミットに ``CHANGELOG.md`` の
``## [Unreleased]`` への追記を求める（AGENTS.md §8.11）。

Like the pipeline goldens, exact hashes reproduce only on the machine that
recorded them, so this test is skipped on CI. Re-baseline after an intended
change with::

    .venv/Scripts/python.exe tests/test_measurement_regression.py --update

パイプラインの golden と同じく、厳密ハッシュは記録した環境でしか再現しないため
CI ではスキップする。意図した変更の後は上記コマンドでベースラインを更新する。
"""

# ===== Standard library =====
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Test / project libraries =====
import pytest

from lib.blosc2_io import load_bundle, load_bundle_meta
from lib.bundle_schema import scan_size_um_from_meta
from lib.measure import measure_bundle, skeleton_height_values, write_fiber_csv
from lib.pipeline import ProcParams, process_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = Path(__file__).resolve().parent / "measurement_regression_golden.json"

if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from kink_reference_score import SCANS  # noqa: E402

# Analysis settings measured for every scan: the defaults, and each geometric
# skeleton cleanup turned off, so that a reader overriding an analysis setting
# changes a recorded value.
# 各スキャンで計測する解析設定。既定と、骨格の幾何クリーニングをそれぞれ切った
# もの。読み込み側が解析の設定を上書きすると、記録した値が変わるようにする。
SETTINGS = {
    "default": {},
    "max_loop_area_0": {"max_loop_area": 0},
    "spur_length_0": {"spur_length": 0},
}

# Pixel size, in nm, for a scan whose bundle records no scan size (the two
# artificial inputs): 1 nm per pixel, so lengths are in pixels.
# 走査範囲を記録していないバンドル（人工入力 2 つ）に使う画素サイズ (nm)。
# 1 画素 1 nm とし、長さは画素数になる。
FALLBACK_NM_PER_PX = 1.0

_ON_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _sha256(data: bytes) -> str:
    """
    Return the hex SHA-256 digest of a byte string.
    バイト列の SHA-256 を 16 進で返す。
    """
    return hashlib.sha256(data).hexdigest()


def _measure_signatures(rel: str) -> dict:
    """
    Analyze one scan under every setting and fingerprint what is measured.
    1 スキャンを全設定で解析し、計測結果の指紋を取る。

    Parameters
    ----------
    rel
        Input path relative to the repository root.
        リポジトリルートからの入力パス。

    Returns
    -------
    dict
        For each setting name, the fiber count, the total contour length
        (nm, rounded to 0.1 for reading a mismatch), and the SHA-256 of the
        fiber CSV and of the traced height values.
        設定名ごとに、繊維数、輪郭長の合計（nm。食い違いを読むため 0.1 に
        丸める）、繊維 CSV と追跡した高さの値の SHA-256。
    """
    out: dict = {}
    with tempfile.TemporaryDirectory() as folder:
        for name, overrides in SETTINGS.items():
            sub = os.path.join(folder, name)
            os.makedirs(sub)
            bundle = process_file(str(PROJECT_ROOT / rel), ProcParams(**overrides),
                                  output_dir=sub).bundle_path
            scale = None
            if scan_size_um_from_meta(load_bundle_meta(bundle)) is None:
                # measure_bundle divides the scan size by the raw width, one
                # column more than the calibrated image.
                # measure_bundle は走査範囲を元データの幅で割る。補正後の画像
                # より 1 列多い。
                arrays = load_bundle(bundle)
                arrays = arrays[0] if isinstance(arrays, tuple) else arrays
                width = np.asarray(arrays["calibrated"]).shape[1]
                scale = FALLBACK_NM_PER_PX * (width + 1) / 1000.0
            result = measure_bundle(bundle, scale_um=scale)
            csv_path = os.path.join(sub, "fibers.csv")
            write_fiber_csv(csv_path, result.stats)
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
            heights, errors = skeleton_height_values([bundle])
            assert not errors, errors
            out[name] = {
                "fibers": len(result.stats),
                "total_length_nm": round(float(sum(s.length_nm for s in result.stats)), 1),
                "fiber_csv_sha256": _sha256(csv_bytes),
                "heights_sha256": _sha256(np.ascontiguousarray(heights, dtype=np.float64).tobytes()),
            }
    return out


def _load_golden() -> dict:
    """
    Load the recorded signatures, or an empty mapping when absent.
    記録済みの署名を読み込む。無い場合は空辞書。
    """
    if not GOLDEN_PATH.exists():
        return {}
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        _ON_CI,
        reason="exact-byte golden is environment-specific; run locally, not on CI",
    ),
    pytest.mark.skipif(
        not GOLDEN_PATH.exists(),
        reason="measurement_regression_golden.json missing; run with --update to create it",
    ),
]


@pytest.mark.parametrize("scan", sorted(SCANS))
def test_measured_values_match_golden(scan):
    """Every measured value of every setting matches the recorded baseline."""
    golden = _load_golden()
    rel = Path(SCANS[scan]).as_posix()
    assert rel in golden, (
        f"no golden baseline for {rel}; regenerate with: "
        "python tests/test_measurement_regression.py --update"
    )
    actual = _measure_signatures(SCANS[scan])
    mismatches = [
        f"{name}: expected {golden[rel].get(name)} got {actual.get(name)}"
        for name in sorted(set(golden[rel]) | set(actual))
        if golden[rel].get(name) != actual.get(name)
    ]
    assert not mismatches, (
        f"measured values changed for {rel}:\n  " + "\n  ".join(mismatches)
        + "\n\nIf this change is intentional, add a CHANGELOG.md [Unreleased] entry "
        "and re-baseline with: python tests/test_measurement_regression.py --update"
    )


def _regenerate_golden() -> None:
    """
    Recompute and overwrite the baseline for every bundled scan.
    全同梱スキャンのベースラインを再計算して上書きする。
    """
    golden = {}
    for i, (scan, rel) in enumerate(sorted(SCANS.items()), start=1):
        print(f"[{i}/{len(SCANS)}] {scan}")
        golden[Path(rel).as_posix()] = _measure_signatures(rel)
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"wrote {GOLDEN_PATH} ({len(golden)} scans)")


if __name__ == "__main__":
    if "--update" in sys.argv:
        _regenerate_golden()
    else:
        print(__doc__)
        print("Pass --update to regenerate the golden baseline.")
