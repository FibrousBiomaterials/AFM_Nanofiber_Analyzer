# -*- coding: utf-8 -*-
"""
Connect skeleton fragments into whole fibrils for GUI04 fiber tracking.
GUI04 のファイバー追跡向けに、骨格断片を 1 本のフィブリルへ連結する。

GUI01 preprocessing removes branch points, so a single physical fibril that
crosses or branches is split into several skeleton fragments. This module
re-joins those fragments into whole fibrils by following the local continuity
of position, direction, and height across fragment endpoints, then rebuilds a
`Fiber` for each reconnected fibril.
GUI01 の前処理は分岐点を除去するため、交差・分岐する 1 本の物理的フィブリルは
複数の骨格断片に分断される。本モジュールは、断片の端点をまたぐ位置・方向・高さの
局所的な連続性をたどって断片を 1 本のフィブリルへ再結合し、再結合した各フィブリルに
対して `Fiber` を再構築する。

Notes
-----
The reconnection algorithm is a port of the lab notebook
``generate_connected_fiber_instances``. It is inherently sequential
(fragment consumption is order dependent), so it is not parallelized. Feature
points (kink, decomposition, endpoint) are recomputed on the reconnected
geometry rather than copied from the fragments, because reconnection creates
new corners and merges former endpoints into the interior.
再結合アルゴリズムはラボのノートブック ``generate_connected_fiber_instances``
の移植である。断片の消費順に依存する逐次処理のため並列化しない。特徴点
（kink・分解点・端点）は断片から複写せず、再結合後の形状に対して再計算する。
再結合により新たな折れ点が生まれ、旧端点が内部に取り込まれるためである。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from . import imp_tools
from .fiber import Fiber
from .fiber_tracking_image import FiberTrackingImage
from .kink_detector import KinkDetector


# How much wider than the automatic search a manual connection looks for a
# partner. A human connects across a gap the automatic gates rejected, so the
# list they choose from has to reach past those gates; the gates are reported
# per candidate instead of narrowing the list.
# 手動連結が相手を探す範囲を、自動探索の何倍にするか。人間が連結するのは自動の
# ゲートが弾いた隙間であるため、選択肢の一覧はそのゲートの外まで届く必要がある。
# ゲートは一覧を狭めるのではなく、候補ごとに報告する。
MANUAL_RANGE_FACTOR = 2.0


@dataclass(frozen=True)
class ConnectParams:
    """
    Parameters controlling fragment-to-fibril reconnection.
    断片からフィブリルへの再結合を制御するパラメータ。

    Attributes
    ----------
    clusters_range
        Maximum pixel distance between the growing endpoint and a candidate
        fragment endpoint for the two to be considered connectable.
        成長中の端点と候補断片の端点が連結可能とみなされる最大画素距離。
    angle_threshold
        Minimum straightness angle in degrees. Both the angle at the current
        endpoint and at the candidate endpoint must exceed this, so only
        near-collinear continuations are joined.
        直線性の最小角度（度）。現在の端点と候補端点の両方の角度がこれを
        超える必要があり、ほぼ一直線に続く断片のみを連結する。
    lookback_length
        Number of track points used to estimate the local direction at an
        endpoint (the "look-back" reference point A).
        端点での局所方向を推定するために使うトラック点数（振り返り基準点 A）。
    num_avg_points
        Number of endpoint samples averaged to set the bridge height when two
        fragments are joined.
        2 断片を連結する際、橋渡し部分の高さを決めるために平均する端点サンプル数。
    height_diff_ratio
        Maximum allowed relative difference of median heights between the
        current fibril and a candidate fragment. A fragment whose height is too
        different is not joined. Larger values relax the height gate.
        現在のフィブリルと候補断片の高さ中央値の相対差の上限。高さが大きく
        異なる断片は連結しない。値を大きくすると高さ判定が緩くなる。
    trim_points
        Number of skeleton points trimmed near a junction before bridging, to
        drop crossing-point noise where fragments were cut.
        橋渡し前に交差点付近から切り落とす骨格点数。断片が切断された交差点の
        ノイズを除去する。
    """

    clusters_range: float = 20.0
    angle_threshold: float = 110.0
    lookback_length: int = 15
    num_avg_points: int = 5
    height_diff_ratio: float = 1.0
    trim_points: int = 5


def angle_between_three_points(A, B, D) -> float:
    """
    Return the angle ABD at vertex B in degrees.
    頂点 B における角 ABD を度で返す。

    Parameters
    ----------
    A, B, D
        ``(row, col)`` coordinate pairs; ``B`` is the vertex.
        ``(row, col)`` 座標対。``B`` が頂点。

    Returns
    -------
    float
        Interior angle at ``B`` in degrees, or ``0.0`` when a side has zero
        length.
        ``B`` における内角（度）。辺の長さが 0 のときは ``0.0``。
    """
    ba = np.array(A) - np.array(B)
    bd = np.array(D) - np.array(B)
    denom = np.linalg.norm(ba) * np.linalg.norm(bd)
    if denom == 0:
        return 0.0
    cosine_angle = np.dot(ba, bd) / denom
    return float(np.degrees(np.arccos(np.clip(cosine_angle, -1.0, 1.0))))


def _fragment_end_geometry(
    fragments: Sequence[Fiber],
    lookback_length: int,
) -> tuple:
    """
    Return each fragment's two ends with their look-back reference points.
    各断片の 2 つの端点と、その振り返り基準点を返す。

    Parameters
    ----------
    fragments
        Traced fragments with bounding-box-local track arrays.
        外接矩形ローカルのトラック配列を持つ追跡済み断片。
    lookback_length
        Number of track points back from an end used to estimate its local
        direction.
        端から局所方向を推定するために遡るトラック点数。

    Returns
    -------
    tuple of ndarray
        ``(ends, backs)``, both shaped ``(n_fragments, 2, 2)``: for each
        fragment, the head and tail ``(row, col)`` endpoint and the look-back
        point behind it.
        ``(ends, backs)``。いずれも形状 ``(断片数, 2, 2)`` で、断片ごとに
        先頭側・末尾側の ``(row, col)`` 端点と、その内側の振り返り点を持つ。

    Notes
    -----
    Head and tail are built with the same shape so a candidate end and a
    growing end can be compared by the same expression, which is what makes
    the pairwise test below symmetric in form.
    先頭側と末尾側を同じ形で構成し、候補側の端と成長側の端を同一の式で比較
    できるようにする。これが以下の総当たり判定を形の上で対称にしている。
    """
    ends = np.zeros((len(fragments), 2, 2), dtype=float)
    backs = np.zeros((len(fragments), 2, 2), dtype=float)
    for i, frag in enumerate(fragments):
        xs = np.asarray(frag.xtrack) + frag.data[0]
        ys = np.asarray(frag.ytrack) + frag.data[1]
        step = min(lookback_length, len(xs))
        # Head end and the point `step - 1` further in.
        # 先頭側の端点と、そこから内側へ `step - 1` 進んだ点。
        ends[i, 0] = (ys[0], xs[0])
        backs[i, 0] = (ys[step - 1], xs[step - 1])
        # Tail end and the point `step` back from it.
        # 末尾側の端点と、そこから `step` 戻った点。
        ends[i, 1] = (ys[-1], xs[-1])
        backs[i, 1] = (ys[-step], xs[-step])
    return ends, backs


def connection_candidate_flags(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    params: ConnectParams = ConnectParams(),
) -> List[bool]:
    """
    Flag which fragments have another fragment they could be joined to.
    連結相手となり得る別の断片が存在する断片を判定する。

    Parameters
    ----------
    image
        Tracking container providing ``calibrated_image`` for the height gate.
        高さ判定用の ``calibrated_image`` を提供する追跡コンテナ。
    fragments
        Fragments to classify.
        判定対象の断片列。
    params
        The same thresholds `connect_fiber_fragments` uses.
        `connect_fiber_fragments` が使うものと同じしきい値。

    Returns
    -------
    list of bool
        One flag per fragment; True means at least one other fragment passes
        the distance, angle, and height gates against one of its ends.
        断片ごとの判定。True は、いずれかの端に対して距離・角度・高さの各条件を
        満たす別の断片が少なくとも 1 つ存在することを意味する。

    Notes
    -----
    This asks whether the connector *could* extend a fragment, which is not the
    same question as what `connect_fiber_fragments` actually did. That function
    grows one fibril at a time and marks fragments as consumed, so whether a
    given join happens depends on the order fragments are visited. A predicate
    used to judge a fiber has to be independent of that order, so this one is
    evaluated on the original fragments: each fragment's own end, its own
    look-back direction, and its own median height, as they stand before any
    growth.
    本関数が問うのは連結器が断片を延長し*得る*かであり、
    `connect_fiber_fragments` が実際に何を連結したかとは別の問いである。連結器は
    フィブリルを 1 本ずつ成長させながら断片を消費済みにするため、ある連結が起きる
    かは断片を訪れる順序に依存する。ファイバーの判定に使う述語はその順序から独立
    していなければならないので、ここでは元の断片に対して評価する。すなわち、成長
    前の状態における断片自身の端点・振り返り方向・高さ中央値を用いる。

    A fragment with no candidate is one the connector has nothing to add to,
    which is the closest available statement that its two ends are the fiber's
    real ends rather than cuts. It is not proof: in a dense tangle the
    connector also finds no candidate when the continuation is ambiguous, so
    "no candidate" conflates "complete" with "gave up". That is why
    `lib.measure.isolated_fiber_flags` uses it only in conjunction with the
    branch-point and frame tests, never alone.
    候補が無い断片とは、連結器が付け足すものを持たない断片であり、その 2 端が
    切断ではなくファイバー本来の端であることを示す、利用可能な範囲で最も近い
    言明である。ただし証明ではない。密に絡んだ領域では、続きが曖昧なときにも
    連結器は候補を見つけられないため、「候補なし」は「完結している」と「諦めた」
    を混同する。`lib.measure.isolated_fiber_flags` がこれを分岐点・枠の判定と
    併用し、単独では使わないのはそのためである。
    """
    n = len(fragments)
    if n < 2 or image.calibrated_image is None:
        return [False] * n

    cal = image.calibrated_image
    ends, backs = _fragment_end_geometry(fragments, params.lookback_length)

    medians = np.empty(n, dtype=float)
    for i, frag in enumerate(fragments):
        xs = np.asarray(frag.xtrack) + frag.data[0]
        ys = np.asarray(frag.ytrack) + frag.data[1]
        medians[i] = float(np.median(cal[ys, xs]))

    # Shortlist by distance first: the angle test is the expensive one, and the
    # connection range admits only a handful of end pairs on a real scan.
    # 先に距離で候補を絞る。高価なのは角度判定であり、実際の走査像では連結範囲に
    # 入る端点の組はごく少数に限られる。
    flat_ends = ends.reshape(n * 2, 2)
    deltas = flat_ends[:, None, :] - flat_ends[None, :, :]
    dists = np.hypot(deltas[:, :, 0], deltas[:, :, 1])
    owner = np.repeat(np.arange(n), 2)
    close = (dists <= params.clusters_range) & (owner[:, None] != owner[None, :])

    flags = [False] * n
    for a, b in zip(*np.nonzero(close)):
        i, e = owner[a], a % 2
        j, f = owner[b], b % 2
        if flags[i] and flags[j]:
            continue
        # Height gate, matching connect_fiber_fragments: a candidate at a very
        # different height is a fiber crossing underneath, not a continuation.
        # 高さ判定は connect_fiber_fragments と同じ。高さが大きく異なる候補は
        # 続きではなく、下を横切る別の繊維である。
        low = min(medians[i], medians[j])
        if low > 0 and abs(medians[i] - medians[j]) / low > params.height_diff_ratio:
            continue
        A, B = backs[i, e], ends[i, e]
        C, D = ends[j, f], backs[j, f]
        if angle_between_three_points(A, B, D) > params.angle_threshold \
                and angle_between_three_points(A, C, D) > params.angle_threshold:
            # A joinable pair of ends disqualifies both fragments, not only the
            # one taken as the growing side. The connector's gate is written
            # from the growing fibril's point of view and is not symmetric, so
            # testing one orientation alone missed fragments the connector had
            # in fact absorbed from the other side.
            # 連結可能な端点の組は、成長側として扱った断片だけでなく両方の断片を
            # 対象外とする。連結器の判定は成長中のフィブリル側から書かれており
            # 対称ではないため、片方の向きだけを試すと、実際には反対側から取り込
            # まれていた断片を取り逃がしていた。
            flags[i] = True
            flags[j] = True
    return flags


def plan_from_auto_connect(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    params: ConnectParams = ConnectParams(),
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[List[Tuple[int, bool]]]:
    """
    Search for the fragments that continue one another and return the chains.
    互いの続きとなる断片を探索し、その連鎖を返す。

    Parameters
    ----------
    image
        Tracking container providing ``calibrated_image`` (for height sampling)
        and the resolved ``size_per_pixel`` / ``y_size_per_pixel`` (for path
        length). Populated by `lib.measure`.
        高さ取得用の ``calibrated_image`` と、経路長用に解決済みの
        ``size_per_pixel`` / ``y_size_per_pixel`` を提供する追跡コンテナ。
        `lib.measure` が設定する。
    fragments
        Skeleton fragments to search, typically the output of
        `FiberTrackingImage.fibers_in_image_parallel`.
        探索対象の骨格断片。通常は
        `FiberTrackingImage.fibers_in_image_parallel` の出力。
    params
        Search thresholds.
        探索のしきい値。
    progress_cb
        Optional callback receiving ``(done, total)`` once per source fragment
        examined as a growth seed.
        成長の起点として走査する元断片 1 つごとに ``(done, total)`` を受け取る
        任意のコールバック。

    Returns
    -------
    list of list of tuple
        One chain per reconnected fibril, each a list of
        ``(fragment_index, flip)`` in the order the fibril runs from one
        terminal to the other. ``flip`` says whether that fragment's track is
        reversed to run in the chain's direction. Fragments that were joined
        to nothing do not appear, so an empty result means nothing connects.
        再結合したフィブリルごとに 1 本の連鎖。各連鎖は、フィブリルが一方の端から
        他方の端へ進む順に並べた ``(断片インデックス, 反転)`` のリストである。
        ``flip`` は、その断片のトラックを連鎖の向きに合わせて反転するかどうかを
        表す。どこにも連結されなかった断片は現れないため、結果が空であることは
        「何も繋がらない」を意味する。

    Notes
    -----
    This is the **search** half of reconnection; `build_connected_fibers` is
    the construction half. The split exists because the search is what cannot
    be repeated safely: it is sequential (fragments are consumed as a fibril
    grows), so which joins happen depends on the visiting order, and it is
    population-dependent, so removing one fragment elsewhere can change a join
    here. Recording the chains it found and rebuilding from those is what lets
    a measurement made later reproduce the fibrils that were on screen instead
    of searching again over a population that has meanwhile changed.
    これは再結合のうち**探索**の側であり、構築の側は `build_connected_fibers`
    である。分割したのは、安全に再実行できないのが探索だからである。探索は逐次的
    （フィブリルの成長に伴い断片を消費する）なので、どの連結が起きるかは訪問順に
    依存し、さらに母集団依存でもあるため、離れた場所の断片を 1 つ取り除くとここの
    連結が変わり得る。見つかった連鎖を記録してそこから再構築することで、後から
    行う計測が、その間に変化した母集団に対して探索をやり直すのではなく、画面に
    出ていたフィブリルを再現できるようになる。

    The growth geometry built here is only what the search needs in order to
    look ahead from a growing end; it is deliberately thrown away.
    `build_connected_fibers` rebuilds the fibril from the chain, so there is
    exactly one definition of a connected fiber's geometry and the stored
    chains cannot describe something other than what gets measured.
    ここで組み立てる成長中の形状は、成長端から先を見るために探索が必要とする
    ものにすぎず、意図的に捨てる。フィブリルは `build_connected_fibers` が連鎖
    から作り直すため、連結ファイバーの形状の定義は 1 つだけになり、保存された
    連鎖が計測される対象と違うものを記述することはあり得ない。
    """
    if not fragments:
        return []

    cal = image.calibrated_image

    clusters_range = params.clusters_range
    angle_threshold = params.angle_threshold
    lookback_length = params.lookback_length
    num_avg_points = params.num_avg_points
    height_diff_ratio = params.height_diff_ratio
    trim_points = params.trim_points

    n_frag = len(fragments)
    used = np.zeros(n_frag, dtype=bool)
    chains: List[List[Tuple[int, bool]]] = []

    for i in range(n_frag):
        if progress_cb is not None:
            progress_cb(i + 1, n_frag)
        if used[i]:
            continue

        current_frag = fragments[i]
        used[i] = True

        x_offset, y_offset = current_frag.data[0], current_frag.data[1]
        current_x = list(current_frag.xtrack + x_offset)
        current_y = list(current_frag.ytrack + y_offset)
        current_h = list(cal[current_y, current_x])

        # Members absorbed on each side, in the order they were absorbed. The
        # seed is neither reversed nor absorbed, so it sits between the two.
        # 各側で取り込んだメンバーを、取り込んだ順に保持する。起点は反転もされず
        # 取り込まれもしないため、両者の間に位置する。
        tail_members: List[Tuple[int, bool]] = []
        head_members: List[Tuple[int, bool]] = []

        # Grow the fibril from both ends: first from the tail, then the head.
        # フィブリルを両端から成長させる。まず末尾側、次に先頭側。
        for direction in ("tail", "head"):
            while True:
                # Pick the reference endpoint B and the look-back point A that
                # define the current growth direction at this end.
                # この端での成長方向を定める基準端点 B と振り返り点 A を選ぶ。
                if direction == "tail":
                    target_y, target_x = current_y[-1], current_x[-1]
                    idx_A = -min(lookback_length, len(current_x))
                    A = (current_y[idx_A], current_x[idx_A])
                else:
                    target_y, target_x = current_y[0], current_x[0]
                    idx_A = min(lookback_length, len(current_x)) - 1
                    A = (current_y[idx_A], current_x[idx_A])

                B = (target_y, target_x)
                current_median_h = np.median(current_h)

                best_next_idx = None
                best_flip = False
                max_angle = float(angle_threshold)

                # Search neighboring fragments for the best straight, same-height
                # continuation of the current end.
                # 現在の端に最もまっすぐ・同程度の高さで続く近傍断片を探索する。
                for j in range(n_frag):
                    if used[j]:
                        continue

                    next_frag = fragments[j]
                    nx_offset, ny_offset = next_frag.data[0], next_frag.data[1]
                    nx_pts = next_frag.xtrack + nx_offset
                    ny_pts = next_frag.ytrack + ny_offset

                    next_h_all = cal[ny_pts, nx_pts]
                    next_median_h = np.median(next_h_all)

                    # Height gate: skip fragments whose median height differs too
                    # much from the current fibril, so a crossing fiber at a
                    # different height is not accidentally joined.
                    # 高さゲート：高さ中央値が現在のフィブリルと大きく異なる断片は
                    # 除外し、別の高さで交差する繊維を誤って連結しないようにする。
                    height_diff = abs(current_median_h - next_median_h)
                    min_allowed_h = min(current_median_h, next_median_h)
                    if min_allowed_h > 0 and (height_diff / min_allowed_h) > height_diff_ratio:
                        continue

                    # Test both ends of the candidate fragment as the joining
                    # point C, with D the look-back reference on that side.
                    # 候補断片の両端を連結点 C として試し、D はその側の振り返り
                    # 基準点とする。
                    candidates = [
                        {
                            "C": (ny_pts[0], nx_pts[0]),
                            "D": (
                                ny_pts[min(lookback_length, len(nx_pts)) - 1],
                                nx_pts[min(lookback_length, len(nx_pts)) - 1],
                            ),
                            "flip": False,
                        },
                        {
                            "C": (ny_pts[-1], nx_pts[-1]),
                            "D": (
                                ny_pts[-min(lookback_length, len(nx_pts))],
                                nx_pts[-min(lookback_length, len(nx_pts))],
                            ),
                            "flip": True,
                        },
                    ]

                    for cand in candidates:
                        C, D = cand["C"], cand["D"]
                        dist = np.hypot(B[0] - C[0], B[1] - C[1])

                        if dist <= clusters_range:
                            angle_ABD = angle_between_three_points(A, B, D)
                            angle_ACD = angle_between_three_points(A, C, D)

                            # Require both endpoints to bend little (near 180 deg)
                            # and keep the straightest pair overall.
                            # 両端点の曲がりが小さい（180 度に近い）ことを要求し、
                            # 全体で最も直線的な組を保持する。
                            if angle_ABD > angle_threshold and angle_ACD > angle_threshold \
                                    and angle_ABD + angle_ACD > max_angle:
                                max_angle = angle_ABD + angle_ACD
                                best_next_idx = j
                                best_flip = cand["flip"]

                if best_next_idx is None:
                    # No connectable fragment on this side; move to the next
                    # growth direction.
                    # この側に連結できる断片が無いので次の成長方向へ移る。
                    break

                # --- Docking: append the chosen fragment to the current fibril ---
                # --- ドッキング：選ばれた断片を現在のフィブリルへ連結する ---
                next_frag = fragments[best_next_idx]
                used[best_next_idx] = True

                # Record the member with the orientation it takes in the chain,
                # which is what `build_connected_fibers` replays. Growing from
                # the head mirrors the docking, so the chain-order flip is the
                # opposite of the one the search picked.
                # 連鎖内での向きを添えてメンバーを記録する。これを
                # `build_connected_fibers` が再現する。先頭側への成長は連結の向きが
                # 鏡像になるため、連鎖順での反転は探索が選んだ値の逆になる。
                if direction == "tail":
                    tail_members.append((best_next_idx, bool(best_flip)))
                else:
                    head_members.append((best_next_idx, not bool(best_flip)))

                nx_offset, ny_offset = next_frag.data[0], next_frag.data[1]
                next_x = list(next_frag.xtrack + nx_offset)
                next_y = list(next_frag.ytrack + ny_offset)
                next_h = list(cal[next_y, next_x])

                # Orient the fragment so its start joins the current end.
                # 断片の向きを揃え、その始点が現在の端に接続するようにする。
                if (direction == "tail" and best_flip) or (direction == "head" and not best_flip):
                    next_x.reverse()
                    next_y.reverse()
                    next_h.reverse()

                # Trim crossing-point noise from both sides of the junction.
                # 交差点付近のノイズを接合部の両側から切り落とす。
                if direction == "tail":
                    if len(current_h) > trim_points + num_avg_points:
                        current_x = current_x[:-trim_points]
                        current_y = current_y[:-trim_points]
                        current_h = current_h[:-trim_points]
                    if len(next_h) > trim_points + num_avg_points:
                        next_x = next_x[trim_points:]
                        next_y = next_y[trim_points:]
                        next_h = next_h[trim_points:]
                else:
                    # For head growth the trimmed positions are mirrored.
                    # head 方向の成長では切り落とす位置が逆になる。
                    if len(current_h) > trim_points + num_avg_points:
                        current_x = current_x[trim_points:]
                        current_y = current_y[trim_points:]
                        current_h = current_h[trim_points:]
                    if len(next_h) > trim_points + num_avg_points:
                        next_x = next_x[:-trim_points]
                        next_y = next_y[:-trim_points]
                        next_h = next_h[:-trim_points]

                # Average endpoint heights to bridge smoothly across the gap.
                # 隙間を滑らかに橋渡しするため端点高さを平均する。
                if direction == "tail":
                    n_tail = min(num_avg_points, len(current_h))
                    tail_avg_h = np.mean(current_h[-n_tail:])
                    n_head = min(num_avg_points, len(next_h))
                    head_avg_h = np.mean(next_h[:n_head])
                    new_b_y, new_b_x = current_y[-1], current_x[-1]
                    new_c_y, new_c_x = next_y[0], next_x[0]
                else:
                    n_tail = min(num_avg_points, len(next_h))
                    tail_avg_h = np.mean(next_h[-n_tail:])
                    n_head = min(num_avg_points, len(current_h))
                    head_avg_h = np.mean(current_h[:n_head])
                    new_b_y, new_b_x = next_y[-1], next_x[-1]
                    new_c_y, new_c_x = current_y[0], current_x[0]

                # Linearly interpolate the bridge pixels and heights across the gap.
                # 隙間をまたぐ橋渡し画素と高さを線形補間する。
                num_points = max(abs(new_b_y - new_c_y), abs(new_b_x - new_c_x))
                interp_x, interp_y, interp_h = [], [], []
                if num_points > 1:
                    interp_y = list(np.linspace(new_b_y, new_c_y, num=num_points).round().astype(int))[1:-1]
                    interp_x = list(np.linspace(new_b_x, new_c_x, num=num_points).round().astype(int))[1:-1]
                    interp_h = list(np.linspace(tail_avg_h, head_avg_h, num=num_points))[1:-1]

                # Dock the bridge and the fragment onto the correct end.
                # 橋渡しと断片を正しい端へ連結する。
                if direction == "tail":
                    current_x.extend(interp_x + next_x)
                    current_y.extend(interp_y + next_y)
                    current_h.extend(interp_h + next_h)
                else:
                    current_x = next_x + interp_x + current_x
                    current_y = next_y + interp_y + current_y
                    current_h = next_h + interp_h + current_h

        # Head growth prepends, so those members run from the far terminal back
        # towards the seed; reversing them puts the chain in geometric order.
        # 先頭側の成長は前方に連結するため、その順序は遠い端から起点へ向かう。
        # 反転させることで連鎖が幾何学的な並び順になる。
        if tail_members or head_members:
            chains.append(
                [(idx, flip) for idx, flip in reversed(head_members)]
                + [(i, False)]
                + tail_members
            )

    return chains


def build_connected_fibers(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    chains: Sequence[Sequence[Tuple[int, bool]]],
    params: ConnectParams = ConnectParams(),
) -> List[Fiber]:
    """
    Build the measured fibers from fragments and the chains joining them.
    断片と、それらを繋ぐ連鎖から、計測対象のファイバーを組み立てる。

    Parameters
    ----------
    image
        Tracking container providing ``calibrated_image`` and the resolved
        per-axis pixel size.
        ``calibrated_image`` と解決済みの軸別ピクセルサイズを提供する追跡コンテナ。
    fragments
        Skeleton fragments the chains index into.
        連鎖がインデックスで参照する骨格断片。
    chains
        ``(fragment_index, flip)`` sequences, as returned by
        `plan_from_auto_connect` or resolved from a stored connection plan.
        Each fragment index may appear in at most one chain, once.
        `plan_from_auto_connect` が返す、または保存済み連結プランから解決した
        ``(断片インデックス, 反転)`` の列。各断片インデックスは高々 1 本の連鎖に
        1 度だけ現れてよい。
    params
        Thresholds; only `ConnectParams.trim_points` and
        `ConnectParams.num_avg_points` affect the geometry built here. The
        other four gate the search and cannot change a fiber once the chains
        are fixed.
        しきい値。ここで組み立てる形状に影響するのは
        `ConnectParams.trim_points` と `ConnectParams.num_avg_points` だけで
        ある。残る 4 つは探索を制御するもので、連鎖が確定した後のファイバーを
        変えることはできない。

    Returns
    -------
    list of Fiber
        One `Fiber` per chain plus every fragment no chain claims, in stable
        order: a chain takes the position of its lowest member index.
        連鎖ごとに 1 本の `Fiber` と、どの連鎖にも属さない断片。並び順は安定で、
        連鎖はその最小メンバーインデックスの位置に入る。

    Notes
    -----
    A fragment no chain claims is passed through untouched rather than rebuilt.
    Rebuilding it would recompute its endpoints and feature points from the
    track alone, so adding one join somewhere would perturb the values of every
    unrelated fiber in the image. Keeping the effect of a chain local to that
    chain is what makes a connection decision auditable: the fibers that
    changed are exactly the ones the user connected.
    どの連鎖にも属さない断片は、作り直さずそのまま通す。作り直すと端点や特徴点を
    トラックだけから再計算することになり、どこかで 1 件連結しただけで画像内の無関係
    なファイバーの値まで動いてしまう。連鎖の影響をその連鎖の中に閉じ込めることが、
    連結の判断を監査可能にする。値が変わったファイバーは、ユーザーが連結したもの
    だけになる。
    """
    if not fragments:
        return []

    spp = image.size_per_pixel
    spp_y = image.y_size_per_pixel if image.y_size_per_pixel is not None else spp
    # A single detector instance is reused for every reconnected fibril; its
    # thresholds match the per-label kink detection GUI01 ran, so the recomputed
    # features are consistent with the non-connected path.
    # 検出器インスタンスは全フィブリルで使い回す。しきい値は GUI01 のラベル単位
    # kink 検出と一致するため、再計算した特徴点は非連結経路とも整合する。
    detector = KinkDetector()

    chain_at: Dict[int, Sequence[Tuple[int, bool]]] = {}
    claimed: Dict[int, int] = {}
    for chain in chains:
        members = [(int(idx), bool(flip)) for idx, flip in chain]
        if len(members) < 2:
            continue
        head = min(idx for idx, _flip in members)
        chain_at[head] = members
        for idx, _flip in members:
            claimed[idx] = head

    out: List[Fiber] = []
    for i in range(len(fragments)):
        if i in chain_at:
            out.append(
                _build_chain_fiber(
                    image, detector, fragments, chain_at[i], params, spp, spp_y,
                )
            )
        elif i not in claimed:
            out.append(fragments[i])
    return out


def _build_chain_fiber(
    image: FiberTrackingImage,
    detector: KinkDetector,
    fragments: Sequence[Fiber],
    chain: Sequence[Tuple[int, bool]],
    params: ConnectParams,
    size_per_pixel: float,
    y_size_per_pixel: Optional[float],
) -> Fiber:
    """
    Dock one chain's fragments into a single fibril and rebuild its `Fiber`.
    1 本の連鎖の断片を繋いで 1 本のフィブリルにし、その `Fiber` を再構築する。

    Parameters
    ----------
    image
        Tracking container supplying ``calibrated_image`` for the heights.
        高さの取得元となる ``calibrated_image`` を提供する追跡コンテナ。
    detector
        Kink detector reused across chains.
        連鎖をまたいで使い回す kink 検出器。
    fragments
        Fragments the chain indexes into.
        連鎖がインデックスで参照する断片。
    chain
        ``(fragment_index, flip)`` in geometric order.
        幾何学的な並び順の ``(断片インデックス, 反転)``。
    params
        Supplies the junction trim length and the bridge averaging width.
        接合部の切り落とし長と、橋渡しの平均化幅を与える。
    size_per_pixel, y_size_per_pixel
        Resolved per-axis pixel size for the path length.
        経路長に使う、解決済みの軸別ピクセルサイズ。

    Returns
    -------
    Fiber
        The reconnected fibril.
        再結合したフィブリル。

    Notes
    -----
    Each fragment is trimmed by its own length, not by the length of the fibril
    grown so far. The guard exists so a fragment shorter than the trim is not
    annihilated by it, and that is a property of the fragment; testing the
    accumulated fibril instead made the result depend on which end the search
    happened to grow from, which a stored chain must not.
    切り落としの可否は、そこまで成長したフィブリルの長さではなく、各断片自身の
    長さで判断する。この判定は「切り落とし長より短い断片を消してしまわない」ため
    のものであり、それは断片の性質である。累積したフィブリルで判定すると、探索が
    たまたまどちら側から成長したかに結果が依存してしまい、保存された連鎖には
    それがあってはならない。
    """
    cal = image.calibrated_image
    trim = int(params.trim_points)
    n_avg = int(params.num_avg_points)

    xs: List[int] = []
    ys: List[int] = []
    hs: List[float] = []
    last = len(chain) - 1

    for k, (idx, flip) in enumerate(chain):
        frag = fragments[idx]
        fx = list(np.asarray(frag.xtrack) + frag.data[0])
        fy = list(np.asarray(frag.ytrack) + frag.data[1])
        if flip:
            fx.reverse()
            fy.reverse()
        fh = list(cal[fy, fx])

        # Trim crossing-point noise from each end that meets another fragment.
        # 他の断片と接する各端から、交差点付近のノイズを切り落とす。
        long_enough = len(fh) > trim + n_avg
        head_trim = trim if (k > 0 and long_enough) else 0
        tail_trim = trim if (k < last and long_enough) else 0
        # An interior fragment is trimmed at both ends, so a short one could be
        # consumed entirely; drop the trims rather than produce an empty piece.
        # 内側の断片は両端が切り落とされるため、短いものは消え去り得る。空の断片を
        # 作るくらいなら切り落としをやめる。
        while head_trim + tail_trim >= len(fh) and (head_trim or tail_trim):
            if tail_trim:
                tail_trim = 0
            else:
                head_trim = 0
        if head_trim:
            fx, fy, fh = fx[head_trim:], fy[head_trim:], fh[head_trim:]
        if tail_trim:
            fx, fy, fh = fx[:-tail_trim], fy[:-tail_trim], fh[:-tail_trim]

        if xs:
            # Average endpoint heights to bridge smoothly across the gap, then
            # linearly interpolate the bridge pixels and heights.
            # 隙間を滑らかに橋渡しするため端点高さを平均し、橋渡しの画素と高さを
            # 線形補間する。
            b_y, b_x = ys[-1], xs[-1]
            c_y, c_x = fy[0], fx[0]
            tail_avg = float(np.mean(hs[-min(n_avg, len(hs)):]))
            head_avg = float(np.mean(fh[:min(n_avg, len(fh))]))
            num_points = max(abs(b_y - c_y), abs(b_x - c_x))
            if num_points > 1:
                ys.extend(
                    np.linspace(b_y, c_y, num=num_points).round().astype(int).tolist()[1:-1]
                )
                xs.extend(
                    np.linspace(b_x, c_x, num=num_points).round().astype(int).tolist()[1:-1]
                )
                hs.extend(np.linspace(tail_avg, head_avg, num=num_points).tolist()[1:-1])

        xs.extend(fx)
        ys.extend(fy)
        hs.extend(fh)

    return _rebuild_connected_fiber(
        image, detector, xs, ys, hs, size_per_pixel, y_size_per_pixel,
    )


def connection_candidates(
    image: FiberTrackingImage,
    fibers: Sequence[Fiber],
    index: int,
    params: ConnectParams = ConnectParams(),
    radius: Optional[float] = None,
) -> List[Dict]:
    """
    List the fibers a given fiber could be connected to by hand.
    指定したファイバーに手動で連結し得る相手を列挙する。

    Parameters
    ----------
    image
        Tracking container providing ``calibrated_image`` for the heights.
        高さの取得元となる ``calibrated_image`` を提供する追跡コンテナ。
    fibers
        The population the user is looking at, which may already contain
        connected fibrils. A fibril's ends are its two terminals, so a chain
        can be extended one connection at a time.
        ユーザーが見ている母集団。既に連結済みのフィブリルを含んでいてよい。
        フィブリルの端はその 2 終端なので、連鎖は 1 回の連結ごとに伸ばせる。
    index
        Position in `fibers` of the fiber to find partners for.
        相手を探す対象ファイバーの `fibers` 内での位置。
    params
        Thresholds whose gates are reported per candidate.
        候補ごとに判定結果を報告するためのしきい値。
    radius
        Search radius in pixels; ``None`` uses
        ``params.clusters_range * MANUAL_RANGE_FACTOR``.
        探索半径（画素）。``None`` は
        ``params.clusters_range * MANUAL_RANGE_FACTOR`` を使う。

    Returns
    -------
    list of dict
        One entry per joinable pair of ends, with ``index`` (the other fiber),
        ``self_end`` / ``other_end`` (0 for the track head, 1 for its tail),
        ``distance`` in pixels, ``angle`` (the smaller of the two straightness
        angles, in degrees), ``height_ratio`` (relative median height
        difference), and ``auto`` (whether the automatic search's gates all
        pass). Ordered with the automatic candidates first, then by distance.
        連結し得る端の組ごとに 1 エントリ。``index``（相手のファイバー）、
        ``self_end`` / ``other_end``（0 がトラック先頭、1 が末尾）、``distance``
        （画素）、``angle``（2 つの直線性角度のうち小さい方、度）、
        ``height_ratio``（高さ中央値の相対差）、``auto``（自動探索の全ゲートを
        満たすか）を持つ。自動候補を先に、その後は距離順で並べる。

    Notes
    -----
    The search radius is deliberately looser than the automatic one and the
    angle and height gates are reported rather than applied. Restricting the
    list to what the automatic search would accept would let a manual
    connection only re-choose among joins the machine already considered,
    while the case that actually needs a human — a continuation the angle gate
    rejects — would be unreachable except by editing thresholds, which is the
    mode-like behavior a per-connection decision exists to replace. The user
    is looking at the rendered fibers when they choose, so the gates belong in
    the list as information, not as a filter.
    探索半径は意図的に自動探索より緩く取り、角度と高さのゲートは適用せず報告する。
    自動探索が受け入れる範囲に限ってしまうと、手動連結は機械が既に検討した連結を
    選び直すことしかできなくなる。一方、実際に人間を必要とする場面 — 角度ゲートが
    弾く「続き」— はしきい値を編集しない限り到達できなくなるが、それは連結ごとの
    判断が置き換えるべきモード的な操作そのものである。ユーザーは描画されたファイバー
    を見て選ぶのだから、ゲートはフィルターではなく情報として一覧に載せる。
    """
    n = len(fibers)
    if n < 2 or index < 0 or index >= n or image.calibrated_image is None:
        return []

    cal = image.calibrated_image
    ends, backs = _fragment_end_geometry(fibers, params.lookback_length)
    reach = float(params.clusters_range * MANUAL_RANGE_FACTOR) if radius is None \
        else float(radius)

    medians = np.empty(n, dtype=float)
    for i, fiber in enumerate(fibers):
        xs = np.asarray(fiber.xtrack) + fiber.data[0]
        ys = np.asarray(fiber.ytrack) + fiber.data[1]
        medians[i] = float(np.median(cal[ys, xs]))

    out: List[Dict] = []
    for e in (0, 1):
        B, A = ends[index, e], backs[index, e]
        for j in range(n):
            if j == index:
                continue
            for f in (0, 1):
                C, D = ends[j, f], backs[j, f]
                dist = float(np.hypot(B[0] - C[0], B[1] - C[1]))
                if dist > reach:
                    continue
                angle_abd = angle_between_three_points(A, B, D)
                angle_acd = angle_between_three_points(A, C, D)
                low = min(medians[index], medians[j])
                ratio = (
                    abs(medians[index] - medians[j]) / low if low > 0 else 0.0
                )
                auto = (
                    dist <= params.clusters_range
                    and angle_abd > params.angle_threshold
                    and angle_acd > params.angle_threshold
                    and ratio <= params.height_diff_ratio
                )
                out.append({
                    "index": j,
                    "self_end": e,
                    "other_end": f,
                    "distance": dist,
                    "angle": float(min(angle_abd, angle_acd)),
                    "height_ratio": float(ratio),
                    "auto": bool(auto),
                })

    out.sort(key=lambda c: (not c["auto"], c["distance"]))
    return out


def chain_for_manual_join(
    chains: Sequence[Sequence[Tuple[int, bool]]],
    a_index: int,
    a_end: int,
    b_index: int,
    b_end: int,
) -> List[List[Tuple[int, bool]]]:
    """
    Return the chains after joining two displayed fibers end to end.
    表示中の 2 本のファイバーを端どうしで繋いだ後の連鎖を返す。

    Parameters
    ----------
    chains
        Current chains in **display** index space: entry ``i`` is the chain
        that built displayed fiber ``i``, a one-member chain for a fiber that
        is a bare fragment.
        **表示**インデックス空間での現在の連鎖。要素 ``i`` は表示中のファイバー
        ``i`` を構成した連鎖であり、素の断片であるファイバーでは 1 メンバーの
        連鎖になる。
    a_index, b_index
        Positions in `chains` of the two fibers to join.
        繋ぐ 2 本のファイバーの `chains` 内での位置。
    a_end, b_end
        Which end of each fiber meets the other: 0 for the track head, 1 for
        its tail.
        各ファイバーのどちらの端が相手と接するか。0 がトラック先頭、1 が末尾。

    Returns
    -------
    list of list of tuple
        The chain list with the two entries replaced by their concatenation,
        every other entry unchanged and in order.
        2 つの要素をその連結で置き換えた連鎖リスト。他の要素は順序も内容も
        そのまま。

    Notes
    -----
    Joining at the head of a fiber means the chain has to be walked backwards
    to reach that end, which reverses both the member order and every member's
    flip. Building the new chain this way — rather than recording the join as
    a pair and resolving it later — keeps a chain a plain ordered list, so the
    same construction serves a fragment pair, an extension of a fibril, and
    the merging of two fibrils.
    ファイバーの先頭側で繋ぐということは、その端に達するために連鎖を逆向きに
    たどるということであり、メンバーの順序と各メンバーの反転の両方が逆になる。
    連結をペアとして記録して後で解決するのではなく、この方法で新しい連鎖を作る
    ことで連鎖は単なる順序付きリストのままとなり、断片どうし・フィブリルの延長・
    フィブリルどうしの統合のいずれも同じ構成で扱える。
    """
    def oriented(chain, end):
        """Return the chain running so that `end` is at its tail."""
        members = [(int(i), bool(f)) for i, f in chain]
        if end == 1:
            return members
        return [(i, not f) for i, f in reversed(members)]

    merged = oriented(chains[a_index], a_end) + [
        (i, not f) for i, f in reversed(oriented(chains[b_index], b_end))
    ]

    out: List[List[Tuple[int, bool]]] = []
    for i, chain in enumerate(chains):
        if i == a_index:
            out.append(merged)
        elif i == b_index:
            continue
        else:
            out.append([(int(j), bool(f)) for j, f in chain])
    return out


def connect_fiber_fragments(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    params: ConnectParams = ConnectParams(),
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Fiber]:
    """
    Search for continuations and build the reconnected fibrils in one call.
    続きとなる断片を探索し、再結合したフィブリルの構築までを 1 回で行う。

    Parameters
    ----------
    image
        Tracking container, as for `plan_from_auto_connect`.
        `plan_from_auto_connect` と同じ追跡コンテナ。
    fragments
        Skeleton fragments to reconnect.
        再結合する骨格断片。
    params
        Search and construction thresholds.
        探索と構築のしきい値。
    progress_cb
        Optional ``(done, total)`` callback, forwarded to the search.
        探索へ渡す任意の ``(done, total)`` コールバック。

    Returns
    -------
    list of Fiber
        One `Fiber` per reconnected fibril, plus every unjoined fragment.
        再結合したフィブリルごとに 1 つの `Fiber` と、連結されなかった断片。

    Notes
    -----
    Convenience composition of the two halves, for a caller that wants a
    connection result immediately and has nothing to store. GUI04 keeps the
    chains instead, because a measurement made later has to rebuild the same
    fibrils without searching again.
    2 つの半分を繋いだ簡便版であり、連結結果をその場で得たいだけで保存するものが
    ない呼び出し側のためにある。GUI04 は連鎖の側を保持する。後から行う計測が、
    探索をやり直さずに同じフィブリルを再構築しなければならないためである。
    """
    return build_connected_fibers(
        image,
        fragments,
        plan_from_auto_connect(image, fragments, params, progress_cb),
        params,
    )


def _rebuild_connected_fiber(
    image: FiberTrackingImage,
    detector: KinkDetector,
    current_x: List,
    current_y: List,
    current_h: List,
    size_per_pixel: float,
    y_size_per_pixel: Optional[float],
) -> Fiber:
    """
    Rebuild one `Fiber` from a reconnected track and recompute its features.
    再結合したトラックから `Fiber` を 1 本再構築し、特徴点を再計算する。

    Kink and decomposition indices are recomputed on the reconnected geometry
    via `KinkDetector`, because joining fragments introduces new corners and the
    former fragment endpoints are no longer real fiber ends. The two real
    endpoints of the reconnected 1D path are the first and last track points.
    kink・分解点インデックスは `KinkDetector` で再結合後の形状に対して再計算する。
    断片の連結により新たな折れ点が生じ、旧断片端点はもはや真の繊維端ではない
    ためである。再結合した 1 次元パスの真の端点は、トラックの先頭点と末尾点。
    """
    xtrack_prcimg = np.array(current_x)
    ytrack_prcimg = np.array(current_y)

    x, y = int(np.min(xtrack_prcimg)), int(np.min(ytrack_prcimg))
    w = int(np.max(xtrack_prcimg) - x + 1)
    h = int(np.max(ytrack_prcimg) - y + 1)
    # OpenCV-style stats tuple (x, y, width, height, area); GUI04 unpacks all
    # five, so keep the shape even though area is not otherwise used here.
    # OpenCV 形式の統計タプル (x, y, 幅, 高さ, 面積)。GUI04 は 5 要素で
    # アンパックするため、面積を他で使わなくても形を保つ。
    data = (x, y, w, h, int(len(xtrack_prcimg)))

    xtrack = xtrack_prcimg - x
    ytrack = ytrack_prcimg - y
    horizon = imp_tools.convert_track_to_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = np.array(current_h)
    fiber_image = image.calibrated_image[y: y + h, x: x + w].copy()

    kink_indices, kink_angles, decomposed_point_indices = \
        detector.kinks_and_decomposed_from_track(xtrack_prcimg, ytrack_prcimg)
    # The reconnected path is a single ordered polyline, so its only true
    # endpoints are the first and last points.
    # 再結合したパスは単一の順序付き折れ線なので、真の端点は先頭点と末尾点のみ。
    ep_indices = np.array([0, len(xtrack_prcimg) - 1])

    return Fiber(
        fiber_image, data, xtrack, ytrack, horizon, height,
        np.asarray(kink_indices), ep_indices,
        np.asarray(kink_angles), np.asarray(decomposed_point_indices),
    )


def filter_fibers_by_height(
    image: FiberTrackingImage,
    fibers: Sequence[Fiber],
    lower_height: float,
    upper_height: float,
    include_lower_limit: bool = True,
    include_upper_limit: bool = True,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Fiber]:
    """
    Extract the height-band portions of already-built fibers, one fiber at a time.
    構築済みファイバーから、指定高さ帯に入る区間をファイバー単位で切り出す。

    Unlike `FiberTrackingImage.specific_height_fibers`, which masks the raw
    skeleton by the calibrated image, this tests each fiber against its own
    height profile (`Fiber.height`). For fibrils produced by
    `connect_fiber_fragments` that profile includes the interpolated bridge
    heights, so a bridge whose height stays in band keeps the fibril joined
    instead of re-splitting it at every reconnection gap. This is the
    "connect, then filter" order GUI04 uses when both the fiber-connection and
    height-filter modes are active.
    生スケルトンを補正画像でマスクする
    `FiberTrackingImage.specific_height_fibers` と異なり、本関数は各ファイバー
    自身の高さプロファイル（`Fiber.height`）で判定する。`connect_fiber_fragments`
    が生成したフィブリルではこのプロファイルに橋渡し部の補間高さが含まれるため、
    橋渡しが帯域内に収まる限りフィブリルは連結を保ち、再結合の隙間ごとに
    再分断されない。GUI04 で連結モードと高さフィルターの両方が有効なときに使う
    「連結してからフィルター」の順序に対応する。

    Parameters
    ----------
    image
        Tracking container supplying the resolved per-axis pixel sizes used to
        recompute each sub-segment's path length.
        各サブ区間の経路長を再計算するために使う軸別ピクセルサイズを提供する
        追跡コンテナ。
    fibers
        Fibers to filter, typically the connected fibrils GUI04 currently
        displays (`connect_fiber_fragments` output).
        フィルター対象のファイバー。通常は GUI04 が表示中の連結フィブリル
        （`connect_fiber_fragments` の出力）。
    lower_height, upper_height
        Height band in nanometers, matching the units of `Fiber.height`.
        高さ帯（nm）。`Fiber.height` の単位に一致する。
    include_lower_limit, include_upper_limit
        Whether each bound is inclusive.
        各境界を含むかどうか。
    progress_cb
        Optional callback receiving ``(done, total)`` once per input fiber.
        入力ファイバー 1 本ごとに ``(done, total)`` を受け取る任意のコールバック。

    Returns
    -------
    list of Fiber
        Rebuilt sub-fibers for every contiguous in-band run, in input order.
        帯域内の連続区間ごとに再構築したサブファイバー（入力順）。
    """
    if not fibers:
        return []

    spp = image.size_per_pixel
    spp_y = image.y_size_per_pixel if image.y_size_per_pixel is not None else spp
    # Reuse one detector for every rebuilt sub-fiber, mirroring
    # connect_fiber_fragments so kink thresholds stay consistent.
    # 全サブファイバーで検出器を使い回し、connect_fiber_fragments と同じ
    # キンクしきい値で一貫させる。
    detector = KinkDetector()

    total = len(fibers)
    result: List[Fiber] = []
    for i, fib in enumerate(fibers):
        if progress_cb is not None:
            progress_cb(i + 1, total)

        h = np.asarray(fib.height)
        lower_cond = (h >= lower_height) if include_lower_limit else (h > lower_height)
        upper_cond = (h <= upper_height) if include_upper_limit else (h < upper_height)
        in_band = lower_cond & upper_cond
        if not in_band.any():
            continue

        # Track points are stored relative to the fiber's bounding box; add the
        # (x, y) offset back to index the shared calibrated image space.
        # トラック点は外接矩形基準で保持されるため、(x, y) オフセットを戻して
        # 共有の補正画像座標に合わせる。
        abs_x = np.asarray(fib.xtrack) + fib.data[0]
        abs_y = np.asarray(fib.ytrack) + fib.data[1]

        for start, stop in _contiguous_runs(in_band):
            # A rebuilt fiber needs two real endpoints to form a path; drop
            # single-point survivors that cannot become a segment.
            # 再構築ファイバーは経路を成すのに端点が 2 つ必要。区間にならない
            # 1 点だけの残存はスキップする。
            if stop - start < 2:
                continue
            xs = list(abs_x[start:stop])
            ys = list(abs_y[start:stop])
            hs = list(h[start:stop])
            try:
                result.append(
                    _rebuild_connected_fiber(image, detector, xs, ys, hs, spp, spp_y)
                )
            except Exception:
                # A degenerate run (e.g. collinear duplicates) can fail feature
                # recomputation; skip it rather than aborting the whole filter.
                # 退化区間（同一点の連続など）は特徴再計算に失敗しうる。フィルター
                # 全体を中断せずスキップする。
                continue

    return result


def _contiguous_runs(mask: np.ndarray) -> List[tuple]:
    """
    Return ``(start, stop)`` index pairs for each maximal True run in ``mask``.
    ``mask`` 内の最長 True 連続区間ごとに ``(start, stop)`` インデックス対を返す。

    ``stop`` is exclusive, so ``mask[start:stop]`` is the run. Runs follow the
    ordered track, so each slice is one physically contiguous sub-path.
    ``stop`` は排他的で ``mask[start:stop]`` が区間になる。区間は順序付きトラックに
    沿うため、各スライスは物理的に連続した 1 つの部分経路となる。
    """
    runs: List[tuple] = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i + 1
            while j < n and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs
