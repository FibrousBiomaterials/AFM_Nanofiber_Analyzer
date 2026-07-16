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
