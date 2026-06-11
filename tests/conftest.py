# -*- coding: utf-8 -*-
"""
Shared pytest fixtures for the AFM Nanofiber Analyzer test suite.
AFM Nanofiber Analyzer テストスイート共通の pytest フィクスチャ。

The synthetic-fiber fixture builds a small AFM-like text file with one bent
fiber so pipeline tests can assert physically meaningful results (one fiber,
one kink at the drawn bend) without depending on large real scans.
合成繊維フィクスチャは、折れ曲がった繊維 1 本を含む小さな AFM 風テキストを
生成する。これにより、巨大な実測データに依存せずに「繊維 1 本・描いた折れ目に
キンク 1 点」という物理的に自明な性質を検証できる。
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the project root importable regardless of how pytest is invoked.
# pytest の起動方法によらずプロジェクトルートを import 可能にする。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Real Shimadzu test scans bundled with the repository.
# リポジトリに同梱された島津機の実測テストデータ。
REAL_DATA = PROJECT_ROOT / "testdata_tunicateCNF" / "test_1.txt"


# The "slow" marker is registered in pyproject.toml [tool.pytest.ini_options].
# "slow" マーカーは pyproject.toml の [tool.pytest.ini_options] で登録される。


@pytest.fixture
def synthetic_fiber_txt(tmp_path):
    """
    Write a synthetic AFM text image containing one bent fiber.
    折れ曲がった繊維 1 本を含む合成 AFM テキスト画像を書き出す。

    Returns
    -------
    str
        Path to a 192x192 CSV text image with a ~3 nm high fiber drawn as two
        line segments meeting at an interior angle of about 147 degrees, on a
        tilted-plane background with mild noise.
        傾斜平面背景 + 弱ノイズの上に、高さ約 3 nm の繊維を内角約 147 度で
        交わる 2 線分として描いた 192x192 の CSV テキスト画像のパス。
    """
    import cv2

    rng = np.random.default_rng(42)
    fiber = np.zeros((192, 192), np.float32)
    # Two segments bending at (100, 90); interior angle ~147 deg, which is
    # below the default 150 deg threshold and must be detected as a kink.
    # (100, 90) で折れる 2 線分。内角は約 147 度で、既定しきい値 150 度を
    # 下回るためキンクとして検出されなければならない。
    cv2.line(fiber, (30, 30), (100, 90), 1.0, 3)
    cv2.line(fiber, (100, 90), (120, 160), 1.0, 3)
    fiber = cv2.GaussianBlur(fiber, (5, 5), 0) * 3.0  # Peak height ~3 nm.

    # Tilted-plane background drift plus mild measurement noise.
    # 傾斜平面のドリフト背景と弱い測定ノイズを加える。
    yy, xx = np.mgrid[0:192, 0:192]
    background = 2.0 * xx / 191 + 1.0 * yy / 191
    image = fiber + background + rng.normal(0.0, 0.05, fiber.shape)

    path = os.path.join(tmp_path, "synthetic_fiber.txt")
    np.savetxt(path, image, delimiter=",", fmt="%.4f")
    return path
