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
from typing import Callable, List, Optional, Sequence

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from . import imp_tools
from .fiber import Fiber
from .fiber_tracking_image import FiberTrackingImage
from .kink_detector import KinkDetector


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


def connect_fiber_fragments(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    params: ConnectParams = ConnectParams(),
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[Fiber]:
    """
    Reconnect skeleton fragments into whole fibrils and rebuild `Fiber` objects.
    骨格断片を 1 本のフィブリルへ再結合し、`Fiber` を再構築する。

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
        Skeleton fragments to reconnect, typically the output of
        `FiberTrackingImage.fibers_in_image_parallel`.
        再結合する骨格断片。通常は
        `FiberTrackingImage.fibers_in_image_parallel` の出力。
    params
        Reconnection thresholds.
        再結合のしきい値。
    progress_cb
        Optional callback receiving ``(done, total)`` once per source fragment
        examined as a growth seed.
        成長の起点として走査する元断片 1 つごとに ``(done, total)`` を受け取る
        任意のコールバック。

    Returns
    -------
    list of Fiber
        One `Fiber` per reconnected fibril.
        再結合したフィブリルごとに 1 つの `Fiber`。
    """
    if not fragments:
        return []

    cal = image.calibrated_image
    spp = image.size_per_pixel
    spp_y = image.y_size_per_pixel if image.y_size_per_pixel is not None else spp
    # A single detector instance is reused for every reconnected fibril; its
    # thresholds match the per-label kink detection GUI01 ran, so the recomputed
    # features are consistent with the non-connected path.
    # 検出器インスタンスは全フィブリルで使い回す。しきい値は GUI01 のラベル単位
    # kink 検出と一致するため、再計算した特徴点は非連結経路とも整合する。
    detector = KinkDetector()

    clusters_range = params.clusters_range
    angle_threshold = params.angle_threshold
    lookback_length = params.lookback_length
    num_avg_points = params.num_avg_points
    height_diff_ratio = params.height_diff_ratio
    trim_points = params.trim_points

    n_frag = len(fragments)
    used = np.zeros(n_frag, dtype=bool)
    connected_fibers: List[Fiber] = []

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

        connected_fibers.append(
            _rebuild_connected_fiber(
                image, detector, current_x, current_y, current_h, spp, spp_y,
            )
        )

    return connected_fibers


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
