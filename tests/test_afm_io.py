# -*- coding: utf-8 -*-
"""
Tests for lib/afm_io.py text loading.
lib/afm_io.py のテキスト読み込みテスト。
"""

import numpy as np
import pytest

from lib.afm_io import load_afm_text
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
