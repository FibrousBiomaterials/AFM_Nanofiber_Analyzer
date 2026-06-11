# -*- coding: utf-8 -*-
"""
Tests for lib/afm_io.py text loading.
lib/afm_io.py のテキスト読み込みテスト。
"""

import numpy as np
import pytest

from lib.afm_io import load_afm_text
from tests.conftest import REAL_DATA


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
