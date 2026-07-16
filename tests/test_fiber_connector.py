# -*- coding: utf-8 -*-
"""
Tests for lib/fiber_connector.py fragment reconnection.
lib/fiber_connector.py の断片再結合のテスト。

These assert self-evident geometric properties: two near-collinear fragments a
short gap apart are reconnected into a single fiber, while fragments that are
far apart or nearly perpendicular are left separate. A synthetic-bundle test
also checks the `measure_bundle(connect_fibers=True)` integration path so the
GUI04 toggle exercises the same code as the CLI.
自明な幾何学的性質を検証する。短い隙間を挟んでほぼ一直線に並ぶ 2 断片は 1 本へ
再結合され、離れている／ほぼ直交する断片は分離したまま残る。合成バンドルの
テストは `measure_bundle(connect_fibers=True)` の統合経路も確認し、GUI04 の
トグルが CLI と同じコードを通ることを保証する。
"""

import os

import numpy as np

from lib.fiber import Fiber
from lib.fiber_connector import (
    ConnectParams,
    angle_between_three_points,
    connect_fiber_fragments,
)
from lib.fiber_tracking_image import FiberTrackingImage
from lib.measure import measure_bundle
from lib.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt


def _horizontal_fragment(x0: int, x1: int, y: int) -> Fiber:
    """
    Build a minimal horizontal single-pixel fragment for the connector.
    連結器用に、水平な 1 画素幅の最小断片を作る。

    Only ``data`` (bbox origin) and ``xtrack`` / ``ytrack`` are read by
    `connect_fiber_fragments`; the other Fiber fields are filled with valid
    placeholders.
    `connect_fiber_fragments` が読むのは ``data``（bbox 原点）と
    ``xtrack`` / ``ytrack`` のみ。他のフィールドは妥当なプレースホルダで埋める。
    """
    n = x1 - x0 + 1
    xtrack = np.arange(n)
    ytrack = np.zeros(n, dtype=int)
    data = (x0, y, n, 1, n)  # (x, y, width, height, area)
    return Fiber(
        fiber_image=np.zeros((1, n)),
        data=data,
        xtrack=xtrack,
        ytrack=ytrack,
        horizon=np.arange(n, dtype=float),
        height=np.zeros(n),
        kink_indices=np.array([], dtype=int),
        ep_indices=np.array([0, n - 1]),
        kink_angles=np.array([]),
        decomposed_point_indices=np.array([0, n - 1]),
    )


def _flat_image(size: int = 80, height_nm: float = 5.0) -> FiberTrackingImage:
    """
    Build a tracking image with a flat calibrated height field.
    平坦な補正高さ場を持つ追跡画像を作る。

    A constant height keeps the connector's height gate satisfied so the test
    isolates the distance/angle logic.
    高さを一定にして連結器の高さゲートを常に満たし、距離・角度ロジックだけを
    切り分けて検証する。
    """
    cal = np.full((size, size), height_nm, dtype=float)
    image = FiberTrackingImage(
        original_AFM=cal, name="synthetic",
        size_per_pixel=10.0, y_size_per_pixel=10.0,
    )
    image.calibrated_image = cal
    return image


def test_angle_between_three_points_straight_and_right():
    """A straight path gives 180 deg; an L-corner gives 90 deg."""
    assert angle_between_three_points((0, 0), (0, 5), (0, 10)) == 180.0
    assert angle_between_three_points((0, 0), (0, 5), (5, 5)) == 90.0


def test_collinear_fragments_are_connected():
    """
    Two collinear fragments a short gap apart merge into one fiber.
    短い隙間を挟んで一直線に並ぶ 2 断片は 1 本へ統合される。
    """
    image = _flat_image()
    frag_a = _horizontal_fragment(5, 20, y=25)
    frag_b = _horizontal_fragment(24, 39, y=25)

    result = connect_fiber_fragments(image, [frag_a, frag_b])

    assert len(result) == 1
    fiber = result[0]
    # The merged fiber must span from the first fragment start to the last
    # fragment end (bbox x origin near 5, extent reaching x ~ 39).
    # 統合ファイバーは最初の断片の始点から最後の断片の終点までを覆う。
    x0, _y0, w, _h, _area = fiber.data
    assert x0 <= 5
    assert x0 + w - 1 >= 39
    # A single reconnected polyline has exactly two true endpoints.
    # 再結合した 1 本の折れ線の真の端点はちょうど 2 つ。
    assert len(fiber.ep_indices) == 2


def test_distant_fragments_are_not_connected():
    """
    Fragments farther apart than ``clusters_range`` stay separate.
    ``clusters_range`` より離れた断片は分離したまま残る。
    """
    image = _flat_image()
    frag_a = _horizontal_fragment(5, 20, y=25)
    frag_b = _horizontal_fragment(50, 65, y=25)  # gap of 30 px > 20 px

    result = connect_fiber_fragments(
        image, [frag_a, frag_b], params=ConnectParams(clusters_range=20.0),
    )

    assert len(result) == 2


def test_perpendicular_fragments_are_not_connected():
    """
    A near-perpendicular candidate fails the straightness angle gate.
    ほぼ直交する候補は直線性の角度ゲートで弾かれる。
    """
    image = _flat_image()
    frag_a = _horizontal_fragment(5, 20, y=25)
    # Vertical fragment starting just past the horizontal one's end.
    # 水平断片の終端直後から始まる垂直断片。
    n = 16
    frag_b = Fiber(
        fiber_image=np.zeros((n, 1)),
        data=(22, 25, 1, n, n),
        xtrack=np.zeros(n, dtype=int),
        ytrack=np.arange(n),
        horizon=np.arange(n, dtype=float),
        height=np.zeros(n),
        kink_indices=np.array([], dtype=int),
        ep_indices=np.array([0, n - 1]),
        kink_angles=np.array([]),
        decomposed_point_indices=np.array([0, n - 1]),
    )

    result = connect_fiber_fragments(image, [frag_a, frag_b])

    assert len(result) == 2


def test_measure_bundle_connect_flag_runs(tmp_path):
    """
    `measure_bundle(connect_fibers=True)` returns valid fibers and stats.
    `measure_bundle(connect_fibers=True)` が妥当なファイバーと統計値を返す。
    """
    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    pipeline_result = process_file(txt, ProcParams(bg_method="tophat"), output_dir=out_dir)

    plain = measure_bundle(pipeline_result.bundle_path, scale_um=1.92)
    connected = measure_bundle(
        pipeline_result.bundle_path, scale_um=1.92, connect_fibers=True,
    )

    # Connection never invents fibers: it can only merge fragments, so the
    # reconnected count is at most the fragment count and stays positive.
    # 連結はファイバーを増やさない。断片を統合するだけなので、再結合後の本数は
    # 断片数以下で正のまま。
    assert 0 < len(connected.fibers) <= len(plain.fibers)
    assert len(connected.fibers) == len(connected.stats)
    for stat in connected.stats:
        assert stat.length_nm > 0
