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
REAL_DATA = PROJECT_ROOT / "testdata_tunicateCNF" / "TunicateACTOCCNF.txt"
HIGHER_PLANT_DATA = (
    PROJECT_ROOT / "testdata_higherplantTOC" / "_20250318-164122_T.ssp .txt"
)

# Representative Bruker NanoScope single-column export (one file is bundled;
# the rest of the folder is gitignored for clone-size reasons).
# 代表の Bruker NanoScope 1 列形式エクスポート（クローンサイズの都合で
# このフォルダは 1 ファイルのみバージョン管理されている）。
BRUKER_DATA = PROJECT_ROOT / "testdata_Bruker_txt" / "NDTOC250306.000.txt"

# Gwyddion "Export Text" matrices with Japanese and English localized headers.
# Both contain whitespace-separated heights in meters from the same scan.
# Gwyddion「Export Text」の日本語・英語ヘッダ版。同一スキャンの高さを
# メートル単位の空白区切り行列として保持する。
GWYDDION_DATA = (
    PROJECT_ROOT / "testdata_Gwyddion_txt" / "_20250318-164122_T.ssp.txt"
)
GWYDDION_ENGLISH_DATA = (
    PROJECT_ROOT / "testdata_Gwyddion_txt" / "_20250318-164122_T.ssp2.txt"
)

# Gwyddion native file exported from the same scan as the text samples.
# 上記テキスト試料と同じスキャンを保存した Gwyddion ネイティブファイル。
REAL_GWY_DATA = (
    PROJECT_ROOT / "testdata_Gwyddion_gwy" / "_20250318-164122_T.ssp.gwy"
)


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


# ===== GUI test support =====
#
# GUI tests drive the plugins through their action methods and through the
# dialogs they open, never through widget lookup by name or label. Asserting on
# widget structure would make the suite fail on every cosmetic UI change; going
# through the action methods means a passing test says the *behavior* still
# holds, and a failing test means the behavior changed.
# GUI テストはウィジェットを名前やラベルで探して操作せず、アクションメソッドと
# ダイアログ経由で駆動する。ウィジェット構造を検証すると UI の見た目を変える
# たびにテストが壊れるが、この方式なら「振る舞い」が変わったときだけ失敗する。


def tk_available() -> bool:
    """
    Report whether a Tk root window can be created in this environment.
    この環境で Tk のルートウィンドウを生成できるかを返す。

    Tk needs a display, so the GUI tests are skipped on a headless machine and
    on CI runners that are not wrapped in a virtual framebuffer (xvfb-run).
    Tk は表示装置を要求するため、ヘッドレス環境や仮想フレームバッファ
    (xvfb-run) の下で動いていない CI では GUI テストをスキップする。
    """
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception:
        return False
    root.destroy()
    return True


requires_tk = pytest.mark.skipif(
    not tk_available(), reason="no display available for Tk"
)


def pump_until(app, predicate, timeout: float = 180.0, interval: float = 0.01) -> None:
    """
    Run the Tk event loop until ``predicate`` holds or the timeout expires.
    ``predicate`` が成立するまで、あるいはタイムアウトまで Tk のイベントループを回す。

    The GUI plugins hand long work to a worker thread and deliver its results
    through a queue drained by an ``after()`` callback (AGENTS.md section 8.4).
    A test therefore cannot simply join the thread: without an event loop the
    queue is never drained and the app never leaves its running state.
    GUI プラグインは重い処理をワーカースレッドに渡し、結果は ``after()`` で
    排出されるキュー経由で届く。したがってスレッドを join するだけでは不十分で、
    イベントループを回さない限りキューは排出されず実行状態も解除されない。

    Raises
    ------
    TimeoutError
        If the predicate does not hold within ``timeout`` seconds.
    """
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(f"GUI did not reach the expected state in {timeout}s")
        app.update()
        time.sleep(interval)


@pytest.fixture
def tk_app():
    """
    Construct GUI plugin windows and guarantee they are destroyed afterwards.
    GUI プラグインのウィンドウを生成し、終了時に確実に破棄する。

    Returns
    -------
    callable
        Factory taking an ``App`` class, returning a constructed and laid-out
        instance. Widgets are only created once the event loop processes the
        idle queue, so the factory pumps it before returning: construction
        errors surface inside the test rather than at teardown.
        ``App`` クラスを受け取り、構築済みインスタンスを返すファクトリ。
        ウィジェットはイベントループがアイドルキューを処理して初めて生成される
        ため、返す前にポンプする。これにより構築時エラーが teardown ではなく
        テスト本体で表面化する。
    """
    apps = []

    def _make(app_cls):
        app = app_cls()
        apps.append(app)
        app.update_idletasks()
        return app

    yield _make

    for app in apps:
        try:
            app.destroy()
        except Exception:
            # A test that already failed may leave a half-torn-down window;
            # do not mask the real failure with a teardown error.
            pass


@pytest.fixture
def silence_dialogs(monkeypatch):
    """
    Replace modal dialogs in a GUI module with recorders.
    GUI モジュール内のモーダルダイアログを記録用の代替に差し替える。

    A modal ``messagebox`` call blocks forever without a user, so any error path
    a test happens to hit would hang the suite instead of failing it. Recording
    the calls also lets a test assert that the GUI *did* report a problem.
    モーダルな ``messagebox`` は人がいない環境では永久に待ち続けるため、テストが
    エラー経路を踏むとスイートがハングする。呼び出しを記録に置き換えることで
    ハングを防ぎ、GUI がエラーを報告したこと自体も検証できるようにする。

    Returns
    -------
    callable
        Factory taking the GUI module, returning a list that receives one
        ``(kind, title, message)`` tuple per dialog the GUI opens.
    """

    def _install(module):
        calls = []

        def recorder(kind):
            def _call(title=None, message=None, *args, **kwargs):
                calls.append((kind, title, message))
                return True

            return _call

        for kind in ("showerror", "showinfo", "showwarning"):
            monkeypatch.setattr(module.messagebox, kind, recorder(kind))
        return calls

    return _install
