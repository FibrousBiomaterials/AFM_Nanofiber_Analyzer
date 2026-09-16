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

Reconnection is split in two. `plan_from_auto_connect` **searches**, returning
one chain of ``(fragment index, flip)`` per fibril, and `build_connected_fibers`
**constructs**, docking a chain back into a `Fiber`; `connect_fiber_fragments`
composes the two for a caller with nothing to store. `connection_candidates`
and `connection_candidates_by_index` list the partners a person can join by
hand, and `chain_for_manual_join` splices two chains into one.
再結合は 2 段に分かれる。`plan_from_auto_connect` が**探索**を行い、フィブリル
ごとに ``(断片インデックス, 反転)`` の連鎖を 1 本返す。`build_connected_fibers`
が**構築**を行い、連鎖を `Fiber` へ組み直す。`connect_fiber_fragments` は保存
すべきものを持たない呼び出し側のために両者を合成したものである。
`connection_candidates` と `connection_candidates_by_index` は人が手動で連結
できる相手を列挙し、`chain_for_manual_join` は 2 本の連鎖を 1 本に繋ぐ。

Notes
-----
The search is a port of the lab notebook
``generate_connected_fiber_instances``. **Only the search is sequential**
(it consumes fragments as it grows, so which joins happen depends on the
visiting order), which is why it is not parallelized and why its result is
recorded rather than repeated; construction is a pure function of the chain.
That boundary is what lets a later measurement rebuild the fibrils that were
on screen instead of searching again over a population that has meanwhile
changed — see `lib.connect_selection`.
探索はラボのノートブック ``generate_connected_fiber_instances`` の移植である。
**逐次なのは探索だけ**であり（成長しながら断片を消費するため、どの連結が起きるかは
訪問順に依存する）、並列化しないのも、結果を再現せず記録するのもこのためである。
構築は連鎖の純関数である。この境界があるからこそ、後の計測は、その間に変化した
母集団に対して探索をやり直すのではなく、画面に表示されていたフィブリルを組み直せる
（`lib.connect_selection` を参照）。

Feature points (kinks, the bends too close to an end to judge, and endpoints;
decomposition points on a bundle of format 1.0) are recomputed on the
reconnected geometry rather than copied from the fragments, because
reconnection creates new corners and merges former endpoints into the
interior. A fragment that **no chain claims is passed through untouched**, not
rebuilt, so adding one join does not perturb every unrelated fiber in the
image.
特徴点（キンク、端に近すぎて判定しない折れ、端点。形式 1.0 のバンドルでは分解点
も）は断片から複写せず、再結合後の形状に対して再計算する。
再結合により新たな折れ点が生まれ、旧端点が内部に取り込まれるためである。ただし
**どの連鎖にも属さない断片は再構築せず、そのまま素通しする**。連結を 1 つ加えた
だけで画像内の無関係なファイバーすべてが動いてしまわないようにするためである。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from . import imp_tools
from .centerline import (
    HALF_MAX_CENTERLINE,
    SKELETON_TRACK,
    measure_apparent_width,
    polyline_distance,
)
from .fiber import Fiber, skeleton_track
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


def _detector_for(image: FiberTrackingImage) -> KinkDetector:
    """
    Build the kink detector the image was analyzed with.
    その画像の解析に使われた kink 検出器を組み立てる。

    Parameters
    ----------
    image
        Tracking container carrying the thresholds `lib.measure` read from the
        bundle. A field left at ``None`` means the bundle records no usable
        value and the detector's own default applies.
        `lib.measure` がバンドルから読み取ったしきい値を保持する追跡コンテナ。
        ``None`` のフィールドは、使用可能な値がバンドルに無いことを意味し、
        検出器自身の既定値を使う。

    Returns
    -------
    KinkDetector
        Detector matching the analysis that produced the image's stored kinks.
        画像の保存済みキンクを生んだ解析と一致する検出器。

    Notes
    -----
    This exists because a fiber the connector builds is displayed and measured
    beside fibers it did not touch. Both construction sites used
    ``KinkDetector()`` with its hard-coded defaults, so a scan analyzed at any
    other angle put two rules in one image: measured on the tunicate test scan
    re-analyzed at 130 degrees, the 15 reconnected fibrils carried 52 kinks
    against the 22 the user's own threshold gives, while the 30 fragments no
    chain claimed carried 9 kinks judged at 130. The extra ones were bends of
    136 to 149 degrees on fibrils that curve smoothly in the height image.
    本関数が存在するのは、連結器が組み立てたファイバーが、連結器の触れていない
    ファイバーと並べて表示・計測されるためである。2 か所の生成箇所はどちらも
    ハードコード既定値の ``KinkDetector()`` を使っており、既定以外の角度で解析
    したスキャンでは 1 枚の画像に 2 つの規則が同居していた。tunicate テスト
    スキャンを 130 度で再解析して実測すると、再結合フィブリル 15 本のキンクは
    52 個で、ユーザー自身のしきい値なら 22 個、どの連鎖にも属さない断片 30 本は
    130 度判定の 9 個であった。余分な分は、高さ画像では滑らかに湾曲している
    フィブリル上の 136〜149 度の曲がりであった。

    A `Fiber` the connector passes through untouched is unaffected either way:
    its features come from the bundle, not from a detector.
    連結器がそのまま通す `Fiber` はいずれにせよ影響を受けない。その特徴点は
    検出器ではなくバンドル由来だからである。
    """
    kwargs = {}
    if image.kink_angle_deg is not None:
        # ProcParams stores degrees; KinkDetector expects radians.
        # ProcParams は度で保持するが、KinkDetector はラジアンを受け取る。
        kwargs["threshold_angle_from_decomposed_indices"] = (
            image.kink_angle_deg * np.pi / 180.0
        )
    if image.kink_decompose_px is not None:
        kwargs["threshold_distance"] = image.kink_decompose_px
    return KinkDetector(**kwargs)


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
        # Ends and look-back points are read on the skeleton pixels, where the
        # search thresholds were tuned: which fragments form one fibril is a
        # question of topology, and the skeleton owns topology.
        # 端点と振り返り点はスケルトン画素で読む。探索のしきい値はその上で調整
        # したものであり、どの断片が 1 本のフィブリルかはトポロジーの問題で、
        # トポロジーはスケルトンが担うためである。
        sx, sy = skeleton_track(frag)
        xs = sx + frag.data[0]
        ys = sy + frag.data[1]
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


def _fragment_median_heights(
    calibrated: np.ndarray,
    fragments: Sequence[Fiber],
) -> np.ndarray:
    """
    Return each fragment's median calibrated height along its own track.
    各断片について、自身のトラック上での補正済み高さの中央値を返す。

    Parameters
    ----------
    calibrated
        Whole-image calibrated height array the tracks index into.
        トラックが参照する画像全体の補正済み高さ配列。
    fragments
        Traced fragments with bounding-box-local track arrays.
        外接矩形ローカルのトラック配列を持つ追跡済み断片。

    Returns
    -------
    ndarray
        One median height per fragment, in nanometers.
        断片ごとの高さ中央値 (nm) を 1 つずつ並べた配列。

    Notes
    -----
    The height gate compares two fragments by this value, so every caller has
    to read it the same way: a candidate whose median height differs sharply
    is a fiber crossing underneath, not a continuation of the same fibril.
    高さゲートはこの値で 2 つの断片を比較するため、全ての呼び出し側が同じ読み方を
    しなければならない。高さ中央値が大きく異なる候補は、同じフィブリルの続きでは
    なく下を横切る別の繊維である。
    """
    medians = np.empty(len(fragments), dtype=float)
    for i, frag in enumerate(fragments):
        # Read on the skeleton pixels, like the end geometry, so the height
        # gate means what it did when its threshold was chosen.
        # 端の幾何と同じくスケルトン画素で読み、高さゲートがしきい値を決めたとき
        # と同じ意味を保つようにする。
        sx, sy = skeleton_track(frag)
        xs = sx + frag.data[0]
        ys = sy + frag.data[1]
        medians[i] = float(np.median(calibrated[ys, xs]))
    return medians


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
    medians = _fragment_median_heights(cal, fragments)

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
        # The search grows on skeleton pixels; see `_fragment_end_geometry`.
        # 探索はスケルトン画素上で成長する。`_fragment_end_geometry` 参照。
        seed_x, seed_y = skeleton_track(current_frag)
        current_x = list(seed_x + x_offset)
        current_y = list(seed_y + y_offset)
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
                    cand_x, cand_y = skeleton_track(next_frag)
                    nx_pts = cand_x + nx_offset
                    ny_pts = cand_y + ny_offset

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
                dock_x, dock_y = skeleton_track(next_frag)
                next_x = list(dock_x + nx_offset)
                next_y = list(dock_y + ny_offset)
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
    # A single detector instance is reused for every reconnected fibril, built
    # from the thresholds the image was analyzed with so the recomputed
    # features are consistent with the fragments passed through untouched.
    # 検出器インスタンスは全フィブリルで使い回す。画像の解析時しきい値から作る
    # ため、再計算した特徴点は、そのまま通される断片とも整合する。
    detector = _detector_for(image)

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
    on_centerline = (
        getattr(image, "centerline", SKELETON_TRACK) == HALF_MAX_CENTERLINE
    )

    # Two index-aligned tracks are docked together. The skeleton pixels carry
    # the fibril's identity and set the bridge lengths exactly as before; the
    # line is what the fibril is drawn and measured along, and each fragment
    # keeps the line it was displayed with, so a join does not move it. For a
    # bundle older than format 1.1 the two tracks are the same pixels.
    # 添字の揃った 2 本のトラックを一緒に繋ぐ。スケルトン画素はフィブリルの識別を
    # 担い、橋渡しの長さを従来どおりに決める。線はフィブリルを描画・計測する線で
    # あり、各断片は表示されていた線をそのまま保つため、連結によって線は動かない。
    # 形式 1.1 より古いバンドルでは 2 本は同じ画素である。
    xs: List[int] = []
    ys: List[int] = []
    lxs: List[float] = []
    lys: List[float] = []
    hs: List[float] = []
    # Per point: whether the line was located on the fragment's own section,
    # and whether the height is a sample of the image. Bridge points are
    # neither, so the fibril's height statistics can leave them out.
    # 点ごとに、線を断片自身の断面で位置決めしたか、高さが画像の標本か。橋渡しの
    # 点はどちらでもないため、フィブリルの高さ統計はそれを除外できる。
    rel: List[bool] = []
    meas: List[bool] = []
    last = len(chain) - 1
    head_real = tail_real = True

    for k, (idx, flip) in enumerate(chain):
        frag = fragments[idx]
        sx, sy = skeleton_track(frag)
        n_frag = len(sx)
        fx = list(sx + frag.data[0])
        fy = list(sy + frag.data[1])
        flx = list(np.asarray(frag.xtrack) + frag.data[0])
        fly = list(np.asarray(frag.ytrack) + frag.data[1])
        fr = frag.line_reliable
        fr = list(np.ones(n_frag, dtype=bool) if fr is None else np.asarray(fr, dtype=bool))
        fm = frag.height_measured
        fm = list(np.ones(n_frag, dtype=bool) if fm is None else np.asarray(fm, dtype=bool))
        ends = set(int(i) for i in np.asarray(frag.ep_indices).tolist())
        if flip:
            fx.reverse()
            fy.reverse()
            flx.reverse()
            fly.reverse()
            fr.reverse()
            fm.reverse()
        # The fibril's outer ends are real fiber ends only where the fragments
        # they come from ended at a skeleton endpoint rather than at a cut.
        # フィブリルの外側の端が本物の繊維端なのは、元になった断片が切断ではなく
        # スケルトンの端点で終わっていた場合だけである。
        if k == 0:
            head_real = (n_frag - 1 if flip else 0) in ends
        if k == last:
            tail_real = (0 if flip else n_frag - 1) in ends
        if on_centerline:
            # Heights along the fragment's own line, as it was measured alone.
            # 断片単独で計測したときと同じ、その断片自身の線に沿った高さ。
            fh = list(np.asarray(frag.height, dtype=float))
            if flip:
                fh.reverse()
        else:
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
            flx, fly = flx[head_trim:], fly[head_trim:]
            fr, fm = fr[head_trim:], fm[head_trim:]
        if tail_trim:
            fx, fy, fh = fx[:-tail_trim], fy[:-tail_trim], fh[:-tail_trim]
            flx, fly = flx[:-tail_trim], fly[:-tail_trim]
            fr, fm = fr[:-tail_trim], fm[:-tail_trim]

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
                bridge_y = np.linspace(b_y, c_y, num=num_points).round().astype(int).tolist()[1:-1]
                bridge_x = np.linspace(b_x, c_x, num=num_points).round().astype(int).tolist()[1:-1]
                ys.extend(bridge_y)
                xs.extend(bridge_x)
                if on_centerline:
                    # The line bridges straight between the two fragments'
                    # lines, with as many points as the pixel bridge so the
                    # two tracks stay index-aligned.
                    # 線は 2 断片の線の間をまっすぐ橋渡しする。点数は画素の
                    # 橋渡しと同じにし、2 本のトラックの添字を揃えたままにする。
                    lys.extend(np.linspace(lys[-1], fly[0], num=num_points).tolist()[1:-1])
                    lxs.extend(np.linspace(lxs[-1], flx[0], num=num_points).tolist()[1:-1])
                else:
                    lys.extend(bridge_y)
                    lxs.extend(bridge_x)
                bridge_h = np.linspace(tail_avg, head_avg, num=num_points).tolist()[1:-1]
                hs.extend(bridge_h)
                rel.extend([False] * len(bridge_h))
                meas.extend([False] * len(bridge_h))

        xs.extend(fx)
        ys.extend(fy)
        lxs.extend(flx)
        lys.extend(fly)
        hs.extend(fh)
        rel.extend(fr)
        meas.extend(fm)

    return _rebuild_connected_fiber(
        image, detector, lxs, lys, hs, size_per_pixel, y_size_per_pixel,
        pixel_x=xs, pixel_y=ys,
        line_reliable=rel, height_measured=meas,
        end_is_real=(head_real, tail_real),
    )


def _manual_reach(params: ConnectParams, radius: Optional[float]) -> float:
    """
    Return the radius a manual connection searches within.
    手動連結が相手を探す半径を返す。

    Parameters
    ----------
    params
        Thresholds the automatic search uses; its `clusters_range` is the base.
        自動探索が使うしきい値。その `clusters_range` を基準とする。
    radius
        Explicit radius in pixels, or ``None`` to derive it from `params`.
        明示的な半径（画素）。``None`` なら `params` から導出する。

    Returns
    -------
    float
        Search radius in pixels.
        探索半径（画素）。
    """
    if radius is None:
        return float(params.clusters_range * MANUAL_RANGE_FACTOR)
    return float(radius)


def _candidates_for(
    index: int,
    ends: np.ndarray,
    backs: np.ndarray,
    medians: np.ndarray,
    params: ConnectParams,
    reach: float,
) -> List[Dict]:
    """
    Scan one fiber's two ends against every other end within `reach`.
    1 本のファイバーの両端を、`reach` 内にある他の全ての端と突き合わせる。

    Parameters
    ----------
    index
        Position of the fiber whose partners are being listed.
        相手を列挙する対象ファイバーの位置。
    ends, backs
        End geometry from `_fragment_end_geometry`, for the whole population.
        母集団全体について `_fragment_end_geometry` が返した端の幾何。
    medians
        Per-fiber median heights from `_fragment_median_heights`.
        `_fragment_median_heights` が返したファイバーごとの高さ中央値。
    params
        Thresholds whose gates are reported per candidate.
        候補ごとに判定結果を報告するためのしきい値。
    reach
        Search radius in pixels.
        探索半径（画素）。

    Returns
    -------
    list of dict
        Unsorted candidate records, as documented on `connection_candidates`.
        並べ替え前の候補レコード。項目は `connection_candidates` の記述どおり。

    Notes
    -----
    Split out so the single-fiber and whole-population entry points cannot
    drift apart in what they report or in which gates they apply.
    単一ファイバー版と母集団一括版とで、報告内容や適用するゲートがずれないよう
    切り出してある。
    """
    n = len(medians)
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
    return out


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

    ends, backs = _fragment_end_geometry(fibers, params.lookback_length)
    medians = _fragment_median_heights(image.calibrated_image, fibers)
    reach = _manual_reach(params, radius)
    out = _candidates_for(index, ends, backs, medians, params, reach)

    out.sort(key=lambda c: (not c["auto"], c["distance"]))
    return out


def connection_candidates_by_index(
    image: FiberTrackingImage,
    fibers: Sequence[Fiber],
    params: ConnectParams = ConnectParams(),
    radius: Optional[float] = None,
) -> Dict[int, List[Dict]]:
    """
    List every fiber's manual-connection candidates in one pass.
    全ファイバーの手動連結候補を 1 回の走査でまとめて列挙する。

    Parameters
    ----------
    image
        Tracking container providing ``calibrated_image`` for the heights.
        高さの取得元となる ``calibrated_image`` を提供する追跡コンテナ。
    fibers
        The population the user is looking at.
        ユーザーが見ている母集団。
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
    dict
        Position in `fibers` -> its candidate list, exactly as
        `connection_candidates` returns it. Fibers with no candidate are
        absent, so the mapping doubles as the set of connectable fibers.
        `fibers` 内の位置 → その候補リスト。内容は `connection_candidates` の
        戻り値と同一。候補の無いファイバーは含めないため、この写像はそのまま
        「連結し得るファイバーの集合」としても使える。

    Notes
    -----
    The end geometry and the per-fiber median heights describe the whole
    population, so calling `connection_candidates` once per fiber rebuilds
    them ``n`` times over: measured on the tunicate test scan (60 fibers) that
    was 0.55 s against 0.015 s for the equivalent whole-population pass in
    `connection_candidate_flags`, and it grows as ``n^2``. GUI04 needs the
    candidates for every fiber before the table is filled, so it takes them
    from here.
    端の幾何とファイバーごとの高さ中央値はいずれも母集団全体を記述するため、
    `connection_candidates` をファイバーごとに呼ぶとそれらを ``n`` 回作り直す
    ことになる。ホヤ CNF のテスト走査（60 本）で実測 0.55 秒であり、同等の母集団
    一括処理である `connection_candidate_flags` の 0.015 秒に対して ``n^2`` で
    増える。GUI04 は表を埋める前に全ファイバーの候補を必要とするため、ここから
    受け取る。
    """
    n = len(fibers)
    if n < 2 or image.calibrated_image is None:
        return {}

    ends, backs = _fragment_end_geometry(fibers, params.lookback_length)
    medians = _fragment_median_heights(image.calibrated_image, fibers)
    reach = _manual_reach(params, radius)

    out: Dict[int, List[Dict]] = {}
    for index in range(n):
        found = _candidates_for(index, ends, backs, medians, params, reach)
        if found:
            found.sort(key=lambda c: (not c["auto"], c["distance"]))
            out[index] = found
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
    pixel_x: Optional[List] = None,
    pixel_y: Optional[List] = None,
    line_reliable: Optional[Sequence[bool]] = None,
    height_measured: Optional[Sequence[bool]] = None,
    end_is_real: Tuple[bool, bool] = (True, True),
) -> Fiber:
    """
    Rebuild one `Fiber` from a reconnected track and recompute its features.
    再結合したトラックから `Fiber` を 1 本再構築し、特徴点を再計算する。

    Kinks, and the bends too close to an end to judge, are recomputed on the
    reconnected geometry via `KinkDetector`, because joining fragments
    introduces new corners and the former fragment endpoints are no longer
    real fiber ends: a bend that sat next to a cut is judged once the cut is
    bridged. The two real endpoints of the reconnected 1D path are the first
    and last track points. The rule is the one the bundle was judged by --
    `KinkDetector.kinks_on_line` on the centerline, the polyline rule on the
    skeleton track of a bundle older than format 1.1 -- so one image never
    carries kinks from two rules.
    キンクと、端に近すぎて判定しない折れは、`KinkDetector` で再結合後の形状に
    対して再計算する。断片の連結により新たな折れ点が生じ、旧断片端点はもはや真の
    繊維端ではないためである。切断のそばにあった折れは、切断が橋渡しされれば判定
    される。再結合した 1 次元パスの真の端点は、トラックの先頭点と末尾点。規則は
    バンドルを判定した規則と同じもの（中心線上では `KinkDetector.kinks_on_line`、
    形式 1.1 より古いバンドルのスケルトントラック上では折れ線規則）を使い、1 枚の
    画像に 2 つの規則のキンクが混在しないようにする。

    ``current_x`` / ``current_y`` are the line the fibril is drawn and
    measured along, and ``pixel_x`` / ``pixel_y`` the skeleton pixels it was
    docked from, index-aligned with it; ``None`` means the line is those
    pixels, as for a bundle older than format 1.1. The bounding box is taken
    from the pixels, so a fibril's frame does not depend on where the line
    was placed.
    ``current_x`` / ``current_y`` はフィブリルを描画・計測する線で、
    ``pixel_x`` / ``pixel_y`` はそれと添字の揃った、繋ぐ元になったスケルトン画素で
    ある。``None`` は線がその画素そのものであること（形式 1.1 より古いバンドル）を
    意味する。外接矩形は画素から取り、フィブリルの枠が線の置き方に依存しない
    ようにする。

    ``line_reliable`` and ``height_measured`` are the per-point flags of
    `Fiber`, index-aligned with the line; ``None`` leaves the field unset.
    ``end_is_real`` says whether the first and the last point are real fiber
    ends (skeleton endpoints) rather than cuts, which is what `ep_indices`
    records: a fibril whose outer fragment ended at a crossing is still cut
    there, and the height statistics leave the cut zone out
    (`measure.height_sample_mask`).
    ``line_reliable`` と ``height_measured`` は `Fiber` の点ごとのフラグで、線と
    添字が揃っている。``None`` はそのフィールドを未設定のままにする。
    ``end_is_real`` は先頭点と末尾点が切断ではなく本物の繊維端（スケルトンの
    端点）かどうかを示し、`ep_indices` はこれを記録する。外側の断片が交差で終わって
    いたフィブリルは依然としてそこで切断されており、高さ統計はその切断域を除く
    （`measure.height_sample_mask`）。
    """
    line_x = np.array(current_x)
    line_y = np.array(current_y)
    if pixel_x is None or pixel_y is None:
        pix_x, pix_y = line_x, line_y
    else:
        pix_x = np.asarray(pixel_x)
        pix_y = np.asarray(pixel_y)

    x, y = int(np.min(pix_x)), int(np.min(pix_y))
    w = int(np.max(pix_x) - x + 1)
    h = int(np.max(pix_y) - y + 1)
    # OpenCV-style stats tuple (x, y, width, height, area); GUI04 unpacks all
    # five, so keep the shape even though area is not otherwise used here.
    # OpenCV 形式の統計タプル (x, y, 幅, 高さ, 面積)。GUI04 は 5 要素で
    # アンパックするため、面積を他で使わなくても形を保つ。
    data = (x, y, w, h, int(len(pix_x)))

    xtrack = line_x - x
    ytrack = line_y - y
    kind = getattr(image, "centerline", SKELETON_TRACK)
    if kind == HALF_MAX_CENTERLINE:
        horizon = polyline_distance(
            xtrack, ytrack, size_per_pixel, y_size_per_pixel,
        )
        skeleton_xtrack = pix_x.astype(int) - x
        skeleton_ytrack = pix_y.astype(int) - y
    else:
        horizon = imp_tools.convert_track_to_distance(
            xtrack, ytrack, size_per_pixel, y_size_per_pixel,
        )
        skeleton_xtrack = skeleton_ytrack = None
    height = np.array(current_h)
    fiber_image = image.calibrated_image[y: y + h, x: x + w].copy()

    if kind == HALF_MAX_CENTERLINE:
        # The rule is scaled by the fibril's own apparent width, read on the
        # skeleton pixels it was docked from, as each fragment's was.
        # 規則はフィブリル自身の見かけ幅で尺度付けする。各断片と同じく、繋ぐ元に
        # なったスケルトン画素の上で読む。
        width, width_measured = measure_apparent_width(
            image.calibrated_image, pix_x, pix_y, return_measured=True,
        )
        judged = detector.judge_line(line_x, line_y, width)
        kink_indices, kink_angles = judged.kink_indices, judged.kink_angles
        kink_excess, unjudged_indices = judged.kink_excess, judged.unjudged_indices
        decomposed_point_indices = np.zeros(0, dtype=np.intp)
        reliable = (None if line_reliable is None
                    else np.asarray(line_reliable, dtype=bool))
    else:
        kink_indices, kink_angles, decomposed_point_indices = \
            detector.kinks_and_decomposed_from_track(line_x, line_y)
        unjudged_indices = np.zeros(0, dtype=np.intp)
        kink_excess = np.zeros(0, dtype=np.float64)
        width, width_measured = float("nan"), False
        reliable = None
    # The reconnected path is a single ordered polyline, so only its first and
    # last points can be endpoints, and each is one only where the fragment it
    # came from ended at a skeleton endpoint rather than at a cut.
    # 再結合したパスは単一の順序付き折れ線なので、端点になり得るのは先頭点と末尾点
    # だけであり、それぞれ元の断片が切断ではなくスケルトンの端点で終わっていた
    # 場合に限り端点である。
    ep_indices = np.array([
        i for i, real in zip((0, len(line_x) - 1), end_is_real) if real
    ], dtype=int)
    measured = (None if height_measured is None
                else np.asarray(height_measured, dtype=bool))

    return Fiber(
        fiber_image, data, xtrack, ytrack, horizon, height,
        np.asarray(kink_indices), ep_indices,
        np.asarray(kink_angles), np.asarray(decomposed_point_indices),
        skeleton_xtrack=skeleton_xtrack, skeleton_ytrack=skeleton_ytrack,
        centerline=kind,
        unjudged_indices=np.asarray(unjudged_indices, dtype=np.intp),
        width_px=float(width), width_measured=bool(width_measured),
        line_reliable=reliable, height_measured=measured,
        kink_excess=np.asarray(kink_excess, dtype=np.float64),
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
    detector = _detector_for(image)

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
        # A sub-fiber is a piece of its parent's line, cut together with the
        # parent's skeleton pixels, so the band shows exactly the line that
        # was drawn before filtering.
        # サブファイバーは親の線の一部であり、親のスケルトン画素と一緒に切り出す。
        # そのため帯域は、フィルター前に描かれていた線そのものを示す。
        sx, sy = skeleton_track(fib)
        pix_x = sx + fib.data[0]
        pix_y = sy + fib.data[1]
        n_points = len(h)
        ends = set(int(i) for i in np.asarray(fib.ep_indices).tolist())
        rel = fib.line_reliable
        meas = fib.height_measured

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
                    _rebuild_connected_fiber(
                        image, detector, xs, ys, hs, spp, spp_y,
                        pixel_x=list(pix_x[start:stop]),
                        pixel_y=list(pix_y[start:stop]),
                        line_reliable=(None if rel is None
                                       else list(np.asarray(rel)[start:stop])),
                        height_measured=(None if meas is None
                                         else list(np.asarray(meas)[start:stop])),
                        # A sub-fiber's end is a real fiber end only where it
                        # is the parent's own real end; a cut the filter made
                        # is a cut.
                        # サブファイバーの端が本物の繊維端なのは、それが親自身の
                        # 本物の端である場合だけである。フィルターが作った切断は
                        # 切断である。
                        end_is_real=(start == 0 and 0 in ends,
                                     stop == n_points and n_points - 1 in ends),
                    )
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
