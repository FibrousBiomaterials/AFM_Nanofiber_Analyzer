# -*- coding: utf-8 -*-
"""
Tests for lib/fiber_connector.py fragment reconnection.
lib/fiber_connector.py の断片再結合のテスト。

These assert self-evident geometric properties: two near-collinear fragments a
short gap apart are reconnected into a single fiber, while fragments that are
far apart or nearly perpendicular are left separate. A synthetic-bundle test
also checks the `measure_bundle(plan=...)` integration path so the fiber
tracker exercises the same code as the CLI.
自明な幾何学的性質を検証する。短い隙間を挟んでほぼ一直線に並ぶ 2 断片は 1 本へ
再結合され、離れている／ほぼ直交する断片は分離したまま残る。合成バンドルの
テストは `measure_bundle(plan=...)` の統合経路も確認し、ファイバートラッカーが
CLI と同じコードを通ることを保証する。

The reconnection scenario is also where the curation contracts are pinned
down, because they need exactly this setup: fragments the search would merge,
one of them excluded. Two of them are properties of storing the connection
*result* — an exclusion may cut a recorded chain but never extend one, and a
stored chain rebuilds the same fibers whatever order the file lists them in.
キュレーションの契約もこの再結合シナリオで固定する。「探索が統合するはずの断片
のうち 1 本を除外する」という、まさにこの構成を必要とするためである。そのうち
2 つは連結*結果*を保存することの性質である。除外は記録された連鎖を切ることは
できても伸ばすことはできず、保存された連鎖はファイル上の並び順によらず同じ
ファイバーを再構築する。
"""

import os

import numpy as np

from lib.connect_selection import plan_from_chains, resolve_plan_chains
from lib.fiber import Fiber
from lib.fiber_connector import (
    ConnectParams,
    angle_between_three_points,
    build_connected_fibers,
    chain_for_manual_join,
    connect_fiber_fragments,
    connection_candidate_flags,
    connection_candidates,
    connection_candidates_by_index,
    plan_from_auto_connect,
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


def _auto_plan(image, fragments, params=ConnectParams()):
    """
    Build the connection plan the automatic search finds for these fragments.
    これらの断片について自動探索が見つける連結プランを作る。

    The GUI stores a result rather than a request to search, so a test that
    wants "connected" has to record what the search found, exactly as GUI04
    does.
    GUI は「探索せよ」という指示ではなく結果を保存するため、「連結された状態」を
    使うテストは GUI04 と同じく探索の結果を記録する必要がある。
    """
    chains = plan_from_auto_connect(image, fragments, params)
    return plan_from_chains(fragments, chains, params)


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

    frags = [near_a, near_b, far]
    joined = curate_fibers(image, frags, plan=_auto_plan(image, frags))
    assert joined.curated_count == 3
    assert joined.curated_count - len(joined.fibers) == 1

    # Nothing within range of anything else: a real result, not a failure.
    # 互いに範囲内に無い構成。失敗ではなく実在の結果である。
    far_apart = [_horizontal_fragment(5, 20, y=10),
                 _horizontal_fragment(5, 20, y=60)]
    apart = curate_fibers(
        image, far_apart, plan=_auto_plan(image, far_apart),
    )
    assert apart.curated_count - len(apart.fibers) == 0

    # With reconnection off the two counts agree, so the same subtraction
    # reports zero joins without a special case.
    # 再結合が無効なら両者は一致するため、同じ引き算が特別扱いなしに 0 件を返す。
    plain = curate_fibers(image, frags)
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


def test_candidates_by_index_match_the_per_fiber_call():
    """
    The whole-population pass reports exactly what the per-fiber call does.
    母集団一括の走査は、ファイバー単位の呼び出しと完全に同じ内容を報告する。

    GUI04 needs every fiber's candidates before the table is filled, and the
    end geometry and median heights describe the whole population, so building
    them once is the difference between linear and quadratic setup. That is
    only a safe substitution while the two agree entry for entry, including
    the order the automatic candidates come first in.
    GUI04 は表を埋める前に全ファイバーの候補を必要とし、端の幾何と高さ中央値は
    いずれも母集団全体を記述する。したがって 1 度だけ構築することが、準備計算を
    線形にするか二乗にするかを分ける。この置き換えが安全なのは、両者がエントリ
    単位で、自動候補を先に並べる順序も含めて一致している間だけである。
    """
    image = _flat_image()
    fibers = [
        _horizontal_fragment(5, 20, y=25),
        _horizontal_fragment(24, 39, y=25),
        _horizontal_fragment(43, 58, y=25),
        _horizontal_fragment(5, 20, y=60),
    ]

    batch = connection_candidates_by_index(image, fibers)
    per_fiber = {
        i: connection_candidates(image, fibers, i)
        for i in range(len(fibers))
    }
    # Fibers with no candidate are absent from the mapping, so it doubles as
    # the set of connectable fibers.
    # 候補の無いファイバーは写像に含まれないため、これはそのまま「連結し得る
    # ファイバーの集合」としても使える。
    assert batch == {i: c for i, c in per_fiber.items() if c}
    assert batch, "the fixture must produce at least one candidate"


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
        plan=_auto_plan(image, [frag_a, frag_b]),
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
        plan=_auto_plan(image, [frag_a, frag_b]),
    )
    assert result.fibers == []

    # Contrast: the fibril's own single anchor leaves a remnant behind.
    # 対照：フィブリル自身の単一アンカーでは残骸が残る。
    partial = curate_fibers(
        image, [frag_a, frag_b],
        exclude_anchors=[fiber_anchor(merged)],
        plan=_auto_plan(image, [frag_a, frag_b]),
    )
    assert len(partial.fibers) == 1


def test_excluding_the_middle_of_a_chain_does_not_join_its_neighbours():
    """
    Removing ``B`` from ``A-B-C`` leaves ``A`` and ``C`` separate.
    ``A-B-C`` から ``B`` を取り除いても ``A`` と ``C`` は繋がらない。

    This is what storing the result buys over storing the settings. Re-running
    the search on the survivors would join ``A`` to ``C``, because ``C`` has
    become ``A``'s only remaining candidate — a fibril the user never chose,
    appearing as a side effect of discarding a speck of debris in the middle
    of it. A recorded chain can only be cut by an exclusion, never extended.
    設定ではなく結果を保存することの利点がこれである。残った断片に対して探索を
    やり直すと、``C`` が ``A`` にとって唯一残った候補になるため両者は連結される。
    それはユーザーが一度も選んでいないフィブリルであり、その途中にあったゴミを
    1 粒捨てた副作用として現れる。記録された連鎖は、除外によって切られることは
    あっても伸びることはない。
    """
    image = _flat_image(size=120)
    frag_a = _horizontal_fragment(5, 20, y=25)
    frag_b = _horizontal_fragment(24, 39, y=25)
    frag_c = _horizontal_fragment(43, 58, y=25)
    fragments = [frag_a, frag_b, frag_c]

    plan = _auto_plan(image, fragments)
    # Precondition: the search does chain all three together.
    # 前提条件：探索は 3 本を 1 本の連鎖にまとめる。
    assert len(plan.chains) == 1 and len(plan.chains[0]) == 3

    result = curate_fibers(
        image, fragments,
        exclude_anchors=[fiber_anchor(frag_b)],
        plan=plan,
    )

    # A and C survive as two separate fibers, and the split is reported.
    # A と C は 2 本の別々のファイバーとして残り、分割が報告される。
    assert len(result.fibers) == 2
    assert result.plan_missing == 1
    assert result.plan_splits == 1
    kept = [fiber_track_pixels(f) for f in result.fibers]
    assert any(px & fiber_track_pixels(frag_a) for px in kept)
    assert any(px & fiber_track_pixels(frag_c) for px in kept)
    assert not any(px & fiber_track_pixels(frag_b) for px in kept)


def test_a_manual_join_connects_what_the_gates_reject():
    """
    A candidate the automatic gates refuse can still be joined by hand.
    自動ゲートが拒否する候補でも、手動でなら連結できる。

    The manual candidate list reaches past the automatic gates on purpose: the
    join a human is needed for is exactly the one the machine declined. The
    gates are reported per candidate so the decision is informed, not hidden.
    手動候補の一覧は意図的に自動ゲートの外まで届く。人間が必要になる連結とは、
    まさに機械が断った連結だからである。ゲートは候補ごとに報告され、判断は隠され
    ずに行われる。
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
    fibers = [horizontal, vertical]

    # The automatic search leaves these two alone.
    # 自動探索はこの 2 本に手を付けない。
    assert plan_from_auto_connect(image, fibers) == []

    candidates = connection_candidates(image, fibers, 0)
    assert candidates, "a near neighbour must still be offered to the user"
    assert all(not c["auto"] for c in candidates), \
        "and must be marked as failing the automatic gates"

    best = candidates[0]
    chains = chain_for_manual_join(
        [[(0, False)], [(1, False)]], 0, best["self_end"],
        best["index"], best["other_end"],
    )
    joined = build_connected_fibers(image, fibers, chains)

    assert len(joined) == 1
    merged = fiber_track_pixels(joined[0])
    assert merged & fiber_track_pixels(horizontal)
    assert merged & fiber_track_pixels(vertical)


def test_a_stored_plan_does_not_depend_on_the_order_of_its_chains():
    """
    Shuffling the stored chains rebuilds the same fibers in the same order.
    保存された連鎖を並べ替えても、同じファイバーが同じ順序で再構築される。

    A chain is a decision, not a step in an algorithm, so the file must not
    encode one. Construction places a chain at its lowest member index, which
    is what makes the fiber list reproducible from a file whose chains could
    have been written in any order.
    連鎖はアルゴリズムの手順ではなく決定であるから、ファイルが手順を含んでは
    ならない。構築は連鎖を最小メンバーインデックスの位置に置く。これにより、
    どの順序で書かれた連鎖からでもファイバーリストが再現できる。
    """
    image = _flat_image(size=140)
    fragments = [
        _horizontal_fragment(5, 20, y=25),
        _horizontal_fragment(24, 39, y=25),
        _horizontal_fragment(5, 20, y=70),
        _horizontal_fragment(24, 39, y=70),
    ]
    plan = _auto_plan(image, fragments)
    assert len(plan.chains) == 2

    forward, _m, _s = resolve_plan_chains(fragments, plan)
    reverse, _m, _s = resolve_plan_chains(
        fragments, plan.__class__(
            chains=tuple(reversed(plan.chains)), params=plan.params,
        ),
    )

    def signature(fibers):
        return [
            (len(f.xtrack), int(f.data[0]), int(f.data[1])) for f in fibers
        ]

    assert signature(build_connected_fibers(image, fragments, forward)) == \
        signature(build_connected_fibers(image, fragments, reverse))


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


def _bent_pair():
    """
    Build two fragments that reconnect into one fibril with a single bend.
    再結合すると 1 か所だけ折れ曲がる 1 本のフィブリルになる 2 断片を作る。

    The second fragment leaves the first at a 60 degree turn, so the joined
    track has one corner and nothing else a kink detector could pick up.
    2 本目は 1 本目から 60 度向きを変えて伸びるため、結合後のトラックには折れが
    1 か所だけあり、キンク検出器が拾える他の特徴は無い。
    """
    def line(p, q, n):
        return [(int(round(p[0] + (q[0] - p[0]) * t / (n - 1))),
                 int(round(p[1] + (q[1] - p[1]) * t / (n - 1))))
                for t in range(n)]

    def fragment(points):
        xs = np.array([p[0] for p in points])
        ys = np.array([p[1] for p in points])
        x0, y0 = int(xs.min()), int(ys.min())
        w, h, n = int(xs.max() - x0 + 1), int(ys.max() - y0 + 1), len(points)
        return Fiber(
            fiber_image=np.zeros((h, w)),
            data=(x0, y0, w, h, n),
            xtrack=xs - x0,
            ytrack=ys - y0,
            horizon=np.arange(n, dtype=float),
            height=np.full(n, 5.0),
            kink_indices=np.array([], dtype=int),
            ep_indices=np.array([0, n - 1]),
            kink_angles=np.array([]),
            decomposed_point_indices=np.array([0, n - 1]),
        )

    turn = np.radians(60.0)
    straight = line((10, 60), (55, 60), 46)
    bent = line((63, 60 - int(round(8 * np.tan(turn)))),
                (63 + int(round(45 * np.cos(turn))),
                 60 - int(round(45 * np.sin(turn)))), 46)
    return [fragment(straight), fragment(bent)]


def test_reconnected_fibril_uses_the_image_kink_threshold():
    """
    A reconnected fibril's kinks obey the threshold the image was analyzed at.
    再結合フィブリルのキンクは、その画像の解析しきい値に従う。

    The connector recomputes kinks because joining fragments creates corners
    that exist in no fragment, but the fibril is then displayed and measured
    beside fragments no chain claimed, whose kinks came from the bundle. Both
    construction sites used `KinkDetector()` with its hard-coded defaults, so
    a scan analyzed at any other angle showed two rules in one image.
    連結器がキンクを再計算するのは、断片の結合によりどの断片にも無かった折れが
    生じるためである。しかしそのフィブリルは、どの連鎖にも属さずキンクをバンドル
    から受け取った断片と並べて表示・計測される。2 か所の生成箇所はどちらも
    ハードコード既定値の `KinkDetector()` を使っていたため、既定以外の角度で解析
    したスキャンでは 1 枚の画像に 2 つの規則が同居していた。

    The junction trim and the interpolated bridge round the corner off, so the
    120 degree turn built here is reported at about 133 degrees. The test
    asserts that measured value lies between the two thresholds rather than
    assuming it, so a change in the bridging geometry fails loudly instead of
    quietly making the comparison vacuous.
    接合部の切り落としと補間による橋渡しが角を丸めるため、ここで作る 120 度の
    折れは約 133 度として報告される。テストはその実測値が 2 つのしきい値の間に
    あることを assert する（仮定しない）ので、橋渡し形状が変わった場合は比較が
    黙って無意味になるのではなく明示的に失敗する。
    """
    image = _flat_image(size=120)
    fragments = _bent_pair()
    chains = plan_from_auto_connect(image, fragments, ConnectParams())
    assert sum(1 for chain in chains if len(chain) >= 2) == 1

    image.kink_angle_deg = 150.0
    loose = build_connected_fibers(image, fragments, chains, ConnectParams())
    assert len(loose) == 1
    angles_deg = np.degrees(loose[0].kink_angles)
    assert len(angles_deg) == 1
    assert 130.0 < angles_deg[0] < 150.0

    image.kink_angle_deg = 130.0
    strict = build_connected_fibers(image, fragments, chains, ConnectParams())
    assert len(strict) == 1
    assert len(strict[0].kink_indices) == 0

    # An unrecorded threshold falls back to the detector default, which is the
    # 150 degrees such a bundle was analyzed with.
    # しきい値が未記録の場合は検出器既定値へフォールバックする。それはその
    # バンドルが実際に解析された 150 度である。
    image.kink_angle_deg = None
    default = build_connected_fibers(image, fragments, chains, ConnectParams())
    assert len(default[0].kink_indices) == 1


def test_measure_bundle_applies_a_connection_plan(tmp_path):
    """
    `measure_bundle(plan=...)` returns valid fibers and stats.
    `measure_bundle(plan=...)` が妥当なファイバーと統計値を返す。
    """
    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    pipeline_result = process_file(txt, ProcParams(bg_method="tophat"), output_dir=out_dir)

    plain = measure_bundle(pipeline_result.bundle_path, scale_um=1.92)
    connected = measure_bundle(
        pipeline_result.bundle_path, scale_um=1.92,
        plan=_auto_plan(plain.image, plain.fragments),
    )

    # Connection never invents fibers: it can only merge fragments, so the
    # reconnected count is at most the fragment count and stays positive.
    # 連結はファイバーを増やさない。断片を統合するだけなので、再結合後の本数は
    # 断片数以下で正のまま。
    assert 0 < len(connected.fibers) <= len(plain.fibers)
    assert len(connected.fibers) == len(connected.stats)
    for stat in connected.stats:
        assert stat.length_nm > 0
