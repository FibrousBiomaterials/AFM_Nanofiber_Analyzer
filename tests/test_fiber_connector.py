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

The reconnection scenario is also where the exclusion ordering contract is
pinned down, because it needs exactly this setup: two fragments the connector
would merge, one of them excluded.
除外の順序に関する契約もこの再結合シナリオで固定する。「連結器が統合するはずの
2 断片のうち片方を除外する」という、まさにこの構成を必要とするためである。
"""

import os

import numpy as np

from lib.fiber import Fiber
from lib.fiber_connector import (
    ConnectParams,
    angle_between_three_points,
    connect_fiber_fragments,
    connection_candidate_flags,
)
from lib.fiber_selection import (
    constituent_anchors,
    fiber_anchor,
    fiber_track_pixels,
)
from lib.fiber_tracking_image import FiberTrackingImage
from lib.measure import curate_fibers, measure_bundle
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


def test_connection_candidates_match_what_the_connector_joins():
    """
    The candidate predicate agrees with the connector on the same fragments.
    候補判定は、同じ断片について連結器と一致する。

    It exists because the connector itself cannot answer the question: it
    consumes fragments as it grows, so whether a given join happens depends on
    the order fragments are visited, and a predicate used to judge a fiber has
    to be independent of that order.
    連結器自身ではこの問いに答えられないため、本述語が存在する。連結器は成長し
    ながら断片を消費するので、ある連結が起きるかは断片を訪れる順序に依存する。
    ファイバーの判定に使う述語は、その順序から独立していなければならない。
    """
    image = _flat_image()
    near_a = _horizontal_fragment(5, 20, y=25)
    near_b = _horizontal_fragment(24, 39, y=25)
    far = _horizontal_fragment(5, 20, y=60)

    flags = connection_candidate_flags(image, [near_a, near_b, far])

    # The pair the connector merges is flagged on both sides; the lone
    # fragment, which the connector leaves alone, is not.
    # 連結器が統合する組は両側とも判定され、連結器が手を付けない孤立した断片は
    # 判定されない。
    assert flags == [True, True, False]
    assert len(connect_fiber_fragments(image, [near_a, near_b, far])) == 2


def test_curate_fibers_reports_how_many_joins_were_made():
    """
    `curated_count` minus the fiber count is the number of joins.
    `curated_count` とファイバー数の差が、連結の件数になる。

    Reconnection used to be silent about its result, so a run that joined
    nothing looked exactly like a run that joined everything. Joining nothing
    is a legitimate outcome — a well dispersed specimen has no fragments to
    rejoin — which is why it has to be reported rather than treated as an
    error.
    再結合はこれまで結果について無言だったため、1 件も連結しなかった実行と、
    すべて連結した実行が見分けられなかった。1 件も連結しないことは正当な結果で
    あり（よく分散した試料には再結合すべき断片が無い）、だからこそエラーとして
    扱うのではなく報告する必要がある。
    """
    image = _flat_image()
    near_a = _horizontal_fragment(5, 20, y=25)
    near_b = _horizontal_fragment(24, 39, y=25)
    far = _horizontal_fragment(5, 20, y=60)

    joined = curate_fibers(image, [near_a, near_b, far], connect_fibers=True)
    assert joined.curated_count == 3
    assert joined.curated_count - len(joined.fibers) == 1

    # Nothing within range of anything else: a real result, not a failure.
    # 互いに範囲内に無い構成。失敗ではなく実在の結果である。
    apart = curate_fibers(
        image, [_horizontal_fragment(5, 20, y=10),
                _horizontal_fragment(5, 20, y=60)],
        connect_fibers=True,
    )
    assert apart.curated_count - len(apart.fibers) == 0

    # With reconnection off the two counts agree, so the same subtraction
    # reports zero joins without a special case.
    # 再結合が無効なら両者は一致するため、同じ引き算が特別扱いなしに 0 件を返す。
    plain = curate_fibers(image, [near_a, near_b, far])
    assert plain.curated_count == len(plain.fibers)


def test_connection_candidates_ignore_perpendicular_neighbours():
    """
    A near-perpendicular neighbour is not a continuation.
    ほぼ直交する隣接断片は「続き」ではない。

    Proximity alone would make every fiber in a dense scan look extendable, so
    the predicate applies the connector's angle gate, not just its range.
    近接だけで判定すると、密な走査像ではあらゆるファイバーが延長可能に見えて
    しまう。そのため本述語は距離だけでなく連結器の角度判定も適用する。
    """
    image = _flat_image()
    horizontal = _horizontal_fragment(5, 20, y=25)
    n = 16
    vertical = Fiber(
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

    assert connection_candidate_flags(image, [horizontal, vertical]) == [False, False]


def test_excluding_a_fragment_does_not_delete_its_neighbour():
    """
    Excluding one fragment leaves the fragment it would have merged with.
    片方の断片を除外しても、統合相手だった断片は残る。

    This is the ordering contract: exclusions reach the fragments before the
    connector runs. Applied afterwards instead, the anchor would match the
    merged fibril — which contains the excluded fragment's pixels — and delete
    the neighbour along with it, so a user dropping one speck of debris would
    silently lose the real fiber it was touching.
    これが順序の契約である。除外は連結器の実行前に断片へ届く。後から適用すると、
    アンカーは統合済みフィブリル（除外された断片の画素を含む）に一致し、隣の断片
    まで一緒に削除してしまう。ゴミを 1 粒落としただけで、それに接していた実在の
    ファイバーが黙って失われることになる。
    """
    image = _flat_image()
    frag_a = _horizontal_fragment(5, 20, y=25)
    frag_b = _horizontal_fragment(24, 39, y=25)
    # Precondition: the connector does merge these two.
    # 前提条件：連結器はこの 2 本を統合する。
    assert len(connect_fiber_fragments(image, [frag_a, frag_b])) == 1

    result = curate_fibers(
        image, [frag_a, frag_b],
        exclude_anchors=[fiber_anchor(frag_a)],
        connect_fibers=True,
    )

    assert len(result.fibers) == 1
    kept = fiber_track_pixels(result.fibers[0])
    assert kept & fiber_track_pixels(frag_b)
    assert not (kept & fiber_track_pixels(frag_a))
    # The uncurated fragments come back untouched, so a caller can rebuild the
    # population after a curation change without tracing again.
    # キュレーション前の断片はそのまま返るため、呼び出し側は除外を変更しても
    # 追跡をやり直さずに母集団を組み立て直せる。
    assert len(result.fragments) == 2


def test_excluding_a_connected_fibril_removes_all_of_it():
    """
    Excluding a reconnected fibril removes every fragment it was built from.
    再結合済みフィブリルを除外すると、その構成断片がすべて取り除かれる。

    A fibril's own midpoint lies on only one constituent fragment, so a single
    anchor removes that fragment and lets the rest reconnect: the object the
    user rejected partly returns. `constituent_anchors` is what prevents it.
    フィブリルの中点は構成断片のうち 1 本の上にしか無いため、アンカー 1 つでは
    その断片が消えるだけで残りが再結合し、却下した対象が部分的に戻ってくる。
    それを防ぐのが `constituent_anchors` である。
    """
    image = _flat_image()
    frag_a = _horizontal_fragment(5, 20, y=25)
    frag_b = _horizontal_fragment(24, 39, y=25)
    merged = connect_fiber_fragments(image, [frag_a, frag_b])[0]

    anchors = constituent_anchors(merged, [frag_a, frag_b])
    assert len(anchors) == 2

    result = curate_fibers(
        image, [frag_a, frag_b],
        exclude_anchors=anchors,
        connect_fibers=True,
    )
    assert result.fibers == []

    # Contrast: the fibril's own single anchor leaves a remnant behind.
    # 対照：フィブリル自身の単一アンカーでは残骸が残る。
    partial = curate_fibers(
        image, [frag_a, frag_b],
        exclude_anchors=[fiber_anchor(merged)],
        connect_fibers=True,
    )
    assert len(partial.fibers) == 1


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
