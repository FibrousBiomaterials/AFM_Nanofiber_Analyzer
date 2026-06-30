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

# Representative Bruker NanoScope single-column export (one file is bundled;
# the rest of the folder is gitignored for clone-size reasons).
# 代表の Bruker NanoScope 1 列形式エクスポート（クローンサイズの都合で
# このフォルダは 1 ファイルのみバージョン管理されている）。
BRUKER_DATA = PROJECT_ROOT / "Bruker_testdata" / "NDTOC250306.000.txt"

# Representative Gwyddion "Export Text" matrix (whitespace-separated, height in
# meters, localized "# Width/Height/Value units" header). Bundled only when the
# folder is present, like the Bruker sample above.
# 代表の Gwyddion「Export Text」行列（空白区切り、高さはメートル、ローカライズ
# された "# 幅/高さ/値の単位" ヘッダ）。上の Bruker 同様、フォルダがある場合のみ
# 同梱される。
GWYDDION_DATA = PROJECT_ROOT / "testdata_Gwyddion" / "_20241115-150641_T.txt"


# The "slow" marker is registered in pyproject.toml [tool.pytest.ini_options].
# "slow" マーカーは pyproject.toml の [tool.pytest.ini_options] で登録される。


def write_synthetic_fiber_txt(out_dir) -> str:
    """
    Write a synthetic AFM text image containing one bent fiber.
    折れ曲がった繊維 1 本を含む合成 AFM テキスト画像を書き出す。

    Shared by the function-scoped fixture below and by module-scoped fixtures
    in individual test files that want to run the pipeline only once.
    下の関数スコープのフィクスチャと、パイプラインを 1 回だけ実行したい
    各テストファイルのモジュールスコープのフィクスチャから共用する。

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

    path = os.path.join(out_dir, "synthetic_fiber.txt")
    np.savetxt(path, image, delimiter=",", fmt="%.4f")
    return path


@pytest.fixture
def synthetic_fiber_txt(tmp_path):
    """
    Function-scoped path to the synthetic bent-fiber text image.
    合成の折れ繊維テキスト画像への関数スコープのパス。
    """
    return write_synthetic_fiber_txt(tmp_path)


def write_synthetic_fiber_gwy(out_dir, *, x_um: float = 2.0, y_um: float = 2.0) -> str:
    """
    Write a two-channel Gwyddion ``.gwy`` file for .gwy-path tests.
    .gwy 経路テスト用に 2 チャンネルの Gwyddion ``.gwy`` ファイルを書き出す。

    Channel 0 is a non-length "Phase" channel and channel 1 is the topography
    height channel, so tests can assert that channel auto-selection skips the
    lower-id phase channel and picks topography by its length (meter) unit.
    Heights are stored in SI meters as Gwyddion does, so the reader must convert
    them back to nanometers.
    チャンネル 0 は長さ単位でない "Phase"、チャンネル 1 が地形（高さ）チャンネル
    で、チャンネル自動選択が id の小さい位相チャンネルを飛ばし、長さ（メートル）
    単位で地形を選ぶことを検証できる。高さは Gwyddion と同様 SI メートルで保存
    するため、リーダは nm へ戻す必要がある。

    Returns
    -------
    str
        Path to a 128x128 ``.gwy`` whose topography channel holds a ~3 nm bent
        fiber on a tilted-plane background; the scan size is ``x_um`` × ``y_um``.
        128x128 の ``.gwy`` のパス。地形チャンネルは傾斜平面背景上の高さ約 3 nm の
        折れ繊維を保持し、走査範囲は ``x_um`` × ``y_um``。
    """
    import cv2
    import gwyfile
    from gwyfile.objects import GwyContainer, GwyDataField, GwySIUnit

    rng = np.random.default_rng(7)
    fiber = np.zeros((128, 128), np.float32)
    cv2.line(fiber, (20, 20), (70, 60), 1.0, 3)
    cv2.line(fiber, (70, 60), (90, 110), 1.0, 3)
    fiber = cv2.GaussianBlur(fiber, (5, 5), 0) * 3.0  # Peak height ~3 nm.
    yy, xx = np.mgrid[0:128, 0:128]
    background = 2.0 * xx / 127 + 1.0 * yy / 127
    height_nm = (fiber + background + rng.normal(0.0, 0.05, fiber.shape)).astype(float)

    # Gwyddion stores topography in base SI meters; convert nm -> m for storage.
    # Gwyddion は地形を基底 SI のメートルで保存するため、保存時に nm -> m へ換算する。
    topo = GwyDataField(
        height_nm * 1e-9, xreal=x_um * 1e-6, yreal=y_um * 1e-6,
        si_unit_z=GwySIUnit(unitstr="m"),
    )
    phase = GwyDataField(
        np.full((128, 128), 0.25), xreal=x_um * 1e-6, yreal=y_um * 1e-6,
        si_unit_z=GwySIUnit(unitstr="rad"),
    )
    container = GwyContainer()
    container["/0/data"] = phase
    container["/0/data/title"] = "Phase"
    container["/1/data"] = topo
    container["/1/data/title"] = "Topography"

    path = os.path.join(out_dir, "synthetic_fiber.gwy")
    container.tofile(path)
    return path


@pytest.fixture
def synthetic_fiber_gwy(tmp_path):
    """
    Function-scoped path to the synthetic two-channel ``.gwy`` file.
    合成 2 チャンネル ``.gwy`` ファイルへの関数スコープのパス。
    """
    return write_synthetic_fiber_gwy(tmp_path)
