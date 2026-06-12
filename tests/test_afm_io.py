# -*- coding: utf-8 -*-
"""
Tests for lib/afm_io.py text loading.
lib/afm_io.py のテキスト読み込みテスト。
"""

import numpy as np
import pytest

from lib.afm_io import AfmTextFormat, detect_afm_format, load_afm_text
from tests.conftest import BRUKER_DATA, REAL_DATA


def test_load_synthetic_csv(synthetic_fiber_txt):
    """A plain comma-separated text image loads with its full shape."""
    a = load_afm_text(synthetic_fiber_txt)
    assert a.shape == (192, 192)
    assert np.isfinite(a).all()


@pytest.mark.skipif(not REAL_DATA.exists(), reason="bundled test scan not present")
def test_load_real_shimadzu_scan():
    """The bundled Shimadzu scan loads as a finite 1024x1024 float image."""
    a = load_afm_text(str(REAL_DATA))
    assert a.shape == (1024, 1024)
    assert a.dtype == np.float64
    assert np.isfinite(a).all()


def _write_single_column(path, values) -> None:
    """Write a Bruker NanoScope-style single-column export.

    Mirrors the real layout: a text header line followed by one value per
    line, with trailing space padding as produced by the instrument software.
    実機ソフトの出力と同様に、テキストヘッダ 1 行+ 1 行 1 値+
    行末の空白パディングという構成で書き出す。
    """
    lines = ["Height(nm)                    "]
    lines += [f"{v:.6e}                 " for v in values]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_synthetic_single_column(tmp_path):
    """A single-column export reshapes into a square image, values intact."""
    rng = np.random.default_rng(0)
    values = rng.normal(0.0, 1.0, 16 * 16)
    path = tmp_path / "single_col.txt"
    _write_single_column(path, values)

    a = load_afm_text(str(path))
    assert a.shape == (16, 16)
    np.testing.assert_allclose(a.ravel(), values, rtol=1e-5)


def test_single_column_non_square_count_raises(tmp_path):
    """A single-column file whose value count is not a perfect square fails."""
    path = tmp_path / "non_square.txt"
    _write_single_column(path, np.arange(15, dtype=float))
    with pytest.raises(ValueError):
        load_afm_text(str(path))


@pytest.mark.skipif(not BRUKER_DATA.exists(), reason="bundled Bruker scan not present")
def test_load_real_bruker_scan():
    """The bundled Bruker NanoScope export loads as a 1024x1024 float image."""
    a = load_afm_text(str(BRUKER_DATA))
    assert a.shape == (1024, 1024)
    assert a.dtype == np.float64
    assert np.isfinite(a).all()


# ---------------------------------------------------------------------------
# Format detection, explicit override, and mis-parse safeguards
# ---------------------------------------------------------------------------

def test_detect_multi_column_format(synthetic_fiber_txt):
    """A plain CSV image is reported as headerless multi-column data."""
    info = detect_afm_format(synthetic_fiber_txt)
    assert info == AfmTextFormat("multi-column", 0, 192, "utf-8-sig")


def test_detect_single_column_format(tmp_path):
    """A Bruker-style export is reported with its one-line text header."""
    path = tmp_path / "single.txt"
    _write_single_column(path, np.arange(16.0))
    info = detect_afm_format(str(path))
    assert info.kind == "single-column"
    assert info.skiprows == 1
    assert info.n_cols == 1


def test_load_with_precomputed_format(synthetic_fiber_txt):
    """Passing a detect_afm_format result reproduces the auto-loaded array."""
    info = detect_afm_format(synthetic_fiber_txt)
    np.testing.assert_array_equal(
        load_afm_text(synthetic_fiber_txt, fmt=info),
        load_afm_text(synthetic_fiber_txt),
    )


def test_explicit_format_overrides_detection(tmp_path):
    """fmt='single-column' skips the multi-column pass entirely.

    This is the escape hatch for headers that contain numeric tables which
    auto-detection would otherwise lock onto.
    自動判定がヘッダ内の数値テーブルに固定されてしまう場合の回避手段。
    """
    # A 12-column numeric block (2 rows) followed by single-column data:
    # auto-detection locks onto the block, the override reads the real data.
    # 12 列の数値ブロック（2 行）の後に 1 列データが続く。自動判定はブロックに
    # 固定されるが、明示指定なら実データを読める。
    header_row = ",".join(str(float(v)) for v in range(12))
    lines = [header_row, header_row]
    lines += [f"{v:.6e}" for v in np.arange(16.0)]
    path = tmp_path / "numeric_header.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    a = load_afm_text(str(path), fmt="single-column")
    assert a.shape == (4, 4)


def test_inconsistent_column_count_raises(tmp_path):
    """A narrow numeric block before wider data fails loudly, not silently.

    Before this check, np.loadtxt(usecols=...) would silently truncate the
    wider rows to the detected narrow width.
    この検証が無いと、np.loadtxt(usecols=...) は幅広の行を検出幅へ黙って
    切り捨てていた。
    """
    narrow = ",".join(str(float(v)) for v in range(12))
    wide = ",".join(str(float(v)) for v in range(20))
    path = tmp_path / "ragged.txt"
    path.write_text("\n".join([narrow, narrow] + [wide] * 5) + "\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="inconsistent column count"):
        load_afm_text(str(path))


def test_requested_multi_column_missing_raises(tmp_path):
    """fmt='multi-column' on a single-column file is an explicit error."""
    path = tmp_path / "single.txt"
    _write_single_column(path, np.arange(16.0))
    with pytest.raises(ValueError, match="no multi-column"):
        load_afm_text(str(path), fmt="multi-column")


def test_unknown_fmt_rejected(synthetic_fiber_txt):
    with pytest.raises(ValueError, match="unknown fmt"):
        load_afm_text(synthetic_fiber_txt, fmt="csv")


def test_non_finite_values_rejected(tmp_path):
    """NaN in the data is refused at load time instead of poisoning stats."""
    rows = [",".join(["1.0"] * 12) for _ in range(12)]
    rows[5] = ",".join(["1.0"] * 5 + ["nan"] + ["1.0"] * 6)
    path = tmp_path / "with_nan.txt"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_afm_text(str(path))
