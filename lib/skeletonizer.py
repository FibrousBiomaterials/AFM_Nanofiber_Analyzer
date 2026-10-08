"""
Skeleton pruning and cleanup for segmented AFM nanofiber images.
セグメント化された AFM ナノファイバー画像のスケルトン枝刈りと後処理を行う。

The module thins a binary nanofiber mask, removes short low-height branches,
and labels the remaining skeleton segments for downstream fiber analysis.
二値化されたナノファイバーマスクを細線化し、低い高さの短い枝を除去して、
後段の繊維解析に使うスケルトン成分へラベル付けする。
"""

from typing import Optional

import cv2
import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import maximum_filter
from skimage.morphology import skeletonize, thin

from . import imp_tools
from .processed_image import ProcessedImage


# Endpoint / branch-point detection lives in imp_tools; Skeletonizer calls
# imp_tools.endPoints / imp_tools.branchedPoints directly.
# 端点・分岐点検出は imp_tools 側にあり、Skeletonizer は imp_tools.endPoints /
# imp_tools.branchedPoints を直接呼ぶ。


# Default geometric-cleanup limits of the pipeline (Skeletonizer), used as the
# defaults of `ProcParams.max_loop_area` and `ProcParams.spur_length`. The
# cleanup runs only in the pipeline; a bundle's skeleton is traced as stored.
# Loops and spurs are skeletonization artifacts: interior holes in the binary
# mask survive topology-preserving thinning as small double-path loops, and
# fiber-width bumps leave short dead-end side branches. Both put branch points
# on a single continuous fiber, and tracking later cuts the fiber at every
# branch point.
# パイプライン（Skeletonizer）の幾何クリーニングの既定値で、
# `ProcParams.max_loop_area` と `ProcParams.spur_length` の既定値として使う。
# クリーニングはパイプラインでのみ行い、バンドルの骨格は保存されたとおりに
# 追跡する。ループとスパーは細線化アーティファクトであり、二値マスク内部の穴は
# トポロジー保存細線化で二重経路の小ループとして残り、ファイバー幅の揺らぎは
# 短い行き止まりの側枝を残す。どちらも 1 本の連続ファイバー上に分岐点を作り、
# 追跡時にその分岐点ごとに分断が起きる。
DEFAULT_MAX_LOOP_AREA = 100
DEFAULT_SPUR_LENGTH = 12

# Width the image border is replicated outward before thinning. `skimage.thin`
# treats everything outside the array as background, so a fiber leaving the
# field of view is a shape cut flat by the array edge, and the medial axis of
# such a truncated end turns toward the nearer corner of the cut. 12 px is
# somewhat wider than the fibers of the bundled scans, and the bend reaches
# roughly half a fiber width inward, so this covers it with margin.
# 細線化の前に画像端を外側へ複製する幅。`skimage.thin` は配列外をすべて背景と
# して扱うため、視野外へ抜けるファイバーは配列端で平らに切断された形状になり、
# その切断端の medial axis は切り口の近い側の角へ向かって折れる。12 px は同梱
# スキャンのファイバー幅よりやや広く、折れの及ぶ範囲 (おおよそファイバー幅の
# 半分) を余裕をもって覆う。
DEFAULT_BORDER_PAD = 12

# Height-ratio guard for loop filling: an enclosure is filled only when its
# median interior height is at least this fraction of the median height of the
# skeleton ring around it. A loop artifact encloses pixels of the fiber body
# itself, so its interior stays close to the ring height and passes. The guard
# refuses only enclosures whose interior lies near the background; a narrow
# gap between two fibers that touch twice keeps an elevated interior and passes
# as well, so the guard does not tell such a gap from a loop artifact
# (docs/validation.md §3.3-§3.4).
# ループ充填の高さ比ガード。囲みの内部の高さの中央値が、周りのスケルトンの輪の
# 高さの中央値のこの割合以上のときだけ塗りつぶす。ループアーティファクトが囲むのは
# ファイバー本体の画素なので、内部は輪の高さに近く、ガードを通る。ガードが止める
# のは内部が背景に近い囲みだけであり、2 点で接する 2 本の繊維の間の狭い隙間は
# 内部が高いままなので同じく通る。そのため、このガードはそうした隙間をループ
# アーティファクトと区別しない（docs/validation.ja.md §3.3〜§3.4）。
DEFAULT_LOOP_HEIGHT_RATIO = 0.3

# Terminal-hook pruning defaults. When segmentation admits a low, widened
# "skirt" at a fiber tip, thinning follows the mask's medial axis into the
# skirt and curls back along its periphery, leaving a junction-free hook at
# the end of an otherwise straight centerline. Neither branch pruning (needs
# a branch point) nor spur pruning (needs a junction) nor loop collapsing
# (needs an enclosed hole) can see it. A hook is recognized by a direction
# reversal near an endpoint (interior apex angle below
# DEFAULT_HOOK_APEX_ANGLE_DEG within DEFAULT_HOOK_LENGTH px of the end) and
# trimmed only where the calibrated height has fallen below
# DEFAULT_HOOK_HEIGHT_RATIO of the adjacent fiber body, so a bent end whose
# height stays at or above that fraction is not cut; 120 deg is far sharper
# than the 150 deg kink threshold, keeping kink detection intact.
# 末端フック除去の既定値。セグメンテーションがファイバー先端の低い「裾」を
# マスクに含めると、細線化はその medial axis を裾へ辿って周縁を回り込み、
# 直線的な中心線の末端に分岐点を持たないフックを残す。枝刈り（分岐点が必要）
# もスパー除去（合流点が必要）もループ潰し（閉じた穴が必要）もこれを検出
# できない。フックは端点近傍の方向反転（端から DEFAULT_HOOK_LENGTH px 以内で
# 頂点内角が DEFAULT_HOOK_APEX_ANGLE_DEG 未満）で認識し、較正高さが隣接する
# 本体の DEFAULT_HOOK_HEIGHT_RATIO 未満に落ちた画素だけを切除するため、高さが
# 本体のこの割合以上にとどまる折れた端は切られない。120 度はキンク判定しきい値
# 150 度よりはるかに鋭く、
# キンク検出には干渉しない。
DEFAULT_HOOK_LENGTH = 12
DEFAULT_HOOK_APEX_ANGLE_DEG = 120.0
DEFAULT_HOOK_HEIGHT_RATIO = 0.5

# Window sizes for terminal-hook analysis: pixels used to estimate the fiber
# body direction at a candidate apex, and pixels of body used as the height
# reference. Both are internal tuning constants, not user parameters.
# 末端フック解析の窓幅。頂点候補での本体方向の推定に使う画素数と、高さ基準に
# 使う本体画素数。どちらも内部調整定数でありユーザーパラメータではない。
_HOOK_DIRECTION_WINDOW = 6
_HOOK_BODY_WINDOW = 12


def thin_ignoring_image_border(
    binary_image: NDArray[np.uint8],
    pad: int = DEFAULT_BORDER_PAD,
) -> NDArray[np.uint8]:
    """
    Thin a binary mask without treating the image border as an object edge.
    画像端を物体の輪郭として扱わずに二値マスクを細線化する。

    Parameters
    ----------
    binary_image
        Binary fiber mask. Nonzero pixels are treated as foreground.
        二値のファイバーマスク。非ゼロ画素を前景として扱う。
    pad
        Width in pixels the border is replicated outward before thinning.
        ``0`` reproduces plain `skimage.morphology.thin`.
        細線化前に画像端を外側へ複製する幅 (px)。``0`` は素の
        `skimage.morphology.thin` と同じ結果になる。

    Returns
    -------
    ndarray
        uint8 0/1 skeleton with the same shape as the input.
        入力と同じ形状の uint8 0/1 スケルトン画像。

    Notes
    -----
    A fiber leaving the field of view is cut flat by the array edge, and the
    medial axis of such a truncated end turns toward the nearer corner of the
    cut, so the traced line drifts off the fiber crest over its last pixels.
    Replicating the border extends those fibers outward instead of capping
    them, which removes the bend. Its effect away from the border is in
    docs/validation.md §3.1.
    視野外へ抜けるファイバーは配列端で平らに切断され、その切断端の medial axis
    は切り口の近い側の角へ折れるため、追跡線が末端の数画素で稜線から外れる。
    端を複製するとファイバーは打ち切られず外側へ延長されるため、この折れが消える。
    端から離れた画素への影響は docs/validation.ja.md §3.1 にある。

    The replication also inflates a blob that lies *along* the border instead
    of crossing it, and its axis can be pushed outside the image. Any mask
    component the padded pass would leave without a skeleton keeps its plain
    thinning result, so this correction never deletes a fiber.
    一方で複製は、端を横切らず端に沿って延びる塊を太らせ、その軸を画像外へ
    押し出すことがある。パディング版でスケルトンが空になる連結成分は素の細線化
    結果を採用するため、本補正でファイバーが失われることはない。
    """
    mask = (np.asarray(binary_image) > 0).astype(np.uint8)
    plain = thin(mask).astype(np.uint8)
    if pad <= 0:
        return plain

    extended = np.pad(mask, pad, mode='edge')
    padded = thin(extended).astype(np.uint8)[pad:-pad, pad:-pad]

    # Per-component fallback for blobs whose axis the replication pushed out
    # of the image; label 0 is the background and is never restored.
    # 複製により軸が画像外へ出た塊だけを成分単位で素の結果へ戻す。ラベル 0 は
    # 背景なので対象外。
    n_labels, labels = cv2.connectedComponents(mask)
    plain_counts = np.bincount(labels[plain > 0], minlength=n_labels)
    padded_counts = np.bincount(labels[padded > 0], minlength=n_labels)
    lost = np.nonzero((plain_counts > 0) & (padded_counts == 0))[0]
    lost = lost[lost != 0]
    if lost.size:
        padded = np.where(np.isin(labels, lost), plain, padded).astype(np.uint8)
    return padded


def collapse_skeleton_loops(
    skeleton_image: NDArray[np.uint8],
    max_loop_area: int = DEFAULT_MAX_LOOP_AREA,
    calibrated_image: Optional[np.ndarray] = None,
    min_height_ratio: float = DEFAULT_LOOP_HEIGHT_RATIO,
) -> NDArray[np.uint8]:
    """
    Collapse small skeleton loops into single lines by filling and re-thinning.
    小さなスケルトンループを充填・再細線化して 1 本の線へ潰す。

    Parameters
    ----------
    skeleton_image
        Binary skeleton image. Nonzero pixels are treated as skeleton pixels.
        二値スケルトン画像。非ゼロ画素をスケルトン画素として扱う。
    max_loop_area
        Maximum enclosed background area in px treated as a loop artifact and
        filled. ``0`` disables loop collapsing. Keep it small: the larger it
        is, the more regions enclosed by separate fibers the fill reaches, and
        a gap between two fibers that touch twice can be as small as a loop
        artifact (docs/validation.md §3.3).
        ループアーティファクトとして充填する、囲まれた背景領域の最大面積 (px)。
        ``0`` で無効化。小さい値を保つこと。大きいほど、別々の繊維が囲む領域まで
        充填が及ぶ。2 点で接する 2 本の繊維の間の隙間は、ループアーティファクトと
        同じくらい小さいこともある（docs/validation.ja.md §3.3）。
    calibrated_image
        Height-calibrated image used to reject enclosures whose interior is at
        background level. ``None`` skips this guard and fills by area alone.
        囲み内部が背景レベルの場合に充填を拒否するための較正済み高さ画像。
        ``None`` の場合はこのガードを行わず面積のみで充填する。
    min_height_ratio
        Minimum ratio of the enclosed region's median height to the
        surrounding skeleton ridge's median height for the enclosure to count
        as a loop artifact. A loop artifact lies inside the fiber body, so its
        interior stays elevated. An enclosure whose interior lies near the
        background is a region between fibers, not a hole in a fiber body, and
        is not filled, because filling it would fuse the fibers and draw a path
        down the groove between them. A narrow gap between two fibers that
        touch twice keeps an elevated interior, so this ratio does not refuse
        it (docs/validation.md §3.3-§3.4).
        囲み領域をループアーティファクトとみなすための、内部の中央値高さと
        周囲骨格リッジの中央値高さの最小比。ループアーティファクトは
        ファイバー本体の内側にあるため内部は高いままである。内部が背景に近い
        囲みは繊維の本体の穴ではなく繊維の間の領域であり、充填すると繊維が
        融合して溝の中に経路が引かれるため充填しない。2 点で接する 2 本の繊維の
        間の狭い隙間は内部が高いままなので、この比では拒否されない
        （docs/validation.ja.md §3.3〜§3.4）。

    Returns
    -------
    ndarray
        uint8 0/1 skeleton image with small loops replaced by single lines.
        小ループを 1 本の線へ置き換えた uint8 0/1 スケルトン画像。

    Notes
    -----
    Interior holes in the binarized fiber mask survive topology-preserving
    thinning as a double path around each hole, and each such loop puts branch
    points on one continuous fiber. Filling the enclosed
    region and re-skeletonizing merges the double path back into one line.
    Re-skeletonization is a fixed point on the already-thin line, so pixels
    far from the filled loops stay in place and coordinate-keyed feature
    lookups (kinks, endpoints) remain valid there.
    二値マスク内部の穴はトポロジー保存細線化で穴を囲む二重経路として残り、
    ループが連続ファイバー上に分岐点を作る。囲まれた領域を充填して
    再細線化すると二重経路は 1 本の線に戻る。再細線化は既に細い線に対して
    不動点なので、充填箇所から離れた画素は動かず、座標キーによる特徴点照合
    （kink・端点）はそのまま有効に保たれる。
    """
    skel = (np.asarray(skeleton_image) > 0).astype(np.uint8)
    if max_loop_area <= 0:
        return skel
    # Label background with 4-connectivity, the topological complement of the
    # 8-connected skeleton: a region is enclosed exactly when the skeleton
    # surrounds it. The outer background always touches the border, so any
    # component whose bounding box avoids the border is a true hole.
    # 背景は 8 連結スケルトンの位相的補集合である 4 連結でラベル付けする。
    # スケルトンが囲む領域だけが「閉じた穴」になる。外側の背景は必ず画像端に
    # 接するため、バウンディングボックスが端に接しない成分は真の穴である。
    inv = (skel == 0).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inv, connectivity=4
    )
    height, width = skel.shape
    fill_labels = []
    for i in range(1, n_labels):
        x, y, cw, ch, area = stats[i]
        if not (area <= max_loop_area and x > 0 and y > 0
                and x + cw < width and y + ch < height):
            continue
        if calibrated_image is not None:
            # Compare the enclosed interior against the surrounding ridge in a
            # 2 px ring; a background-level interior marks a gap between
            # fibers, not a loop artifact, and is left untouched. A narrow gap
            # between two fibers that touch twice keeps an elevated interior
            # and is not caught here.
            # 囲み内部と周囲 2 px リング上のリッジ高を比較する。内部が背景
            # レベルなら繊維の間の隙間でありループではないため充填しない。
            # 2 点で接する 2 本の繊維の間の狭い隙間は内部が高いままなので、
            # ここでは見分けられない。
            x0, y0 = max(0, x - 2), max(0, y - 2)
            x1, y1 = min(width, x + cw + 2), min(height, y + ch + 2)
            hole_local = labels[y0:y1, x0:x1] == i
            dilated = cv2.dilate(
                hole_local.astype(np.uint8), np.ones((5, 5), np.uint8)
            )
            ring = (dilated > 0) & ~hole_local & (skel[y0:y1, x0:x1] > 0)
            cal_local = calibrated_image[y0:y1, x0:x1]
            if ring.any():
                interior_h = float(np.median(cal_local[hole_local]))
                ridge_h = float(np.median(cal_local[ring]))
                if interior_h < min_height_ratio * ridge_h:
                    continue
        fill_labels.append(i)
    if not fill_labels:
        return skel
    filled = (skel > 0) | np.isin(labels, fill_labels)
    return skeletonize(filled).astype(np.uint8)


def _junction_degree(skel: NDArray[np.uint8], y: int, x: int) -> int:
    """
    Count live skeleton neighbors of (y, x) in the 8-neighborhood.
    (y, x) の 8 近傍にある骨格画素を数える。

    Parameters
    ----------
    skel
        Binary skeleton image.
        2 値の骨格画像。
    y, x
        Pixel whose neighbours are counted.
        近傍を数える画素。

    Returns
    -------
    int
        Number of skeleton pixels among the 8 neighbours; the image border
        clips the neighbourhood.
        8 近傍のうち骨格画素の数。画像の端では近傍を切り詰める。
    """
    y0, y1 = max(0, y - 1), min(skel.shape[0], y + 2)
    x0, x1 = max(0, x - 1), min(skel.shape[1], x + 2)
    return int(skel[y0:y1, x0:x1].sum()) - int(skel[y, x])


def prune_short_spurs(
    skeleton_image: NDArray[np.uint8],
    max_length: int = DEFAULT_SPUR_LENGTH,
    border_margin: int = 2,
) -> NDArray[np.uint8]:
    """
    Remove short dead-end side branches (spurs) attached to junctions.
    分岐点に接続した短い行き止まりの側枝（スパー）を除去する。

    Parameters
    ----------
    skeleton_image
        Binary skeleton image. Nonzero pixels are treated as skeleton pixels.
        二値スケルトン画像。非ゼロ画素をスケルトン画素として扱う。
    max_length
        Maximum spur length in pixels to remove. Only arms that start at an
        endpoint and reach a branch point within this many pixels are deleted;
        the branch point itself is kept. ``0`` disables pruning.
        除去するスパーの最大長 (px)。端点から出発してこの画素数以内に分岐点へ
        到達する枝だけを削除する。分岐点自体は保持する。``0`` で無効化。
    border_margin
        Arms whose endpoint lies within this many pixels of the image border
        are never pruned. A short arm ending at the scan border is a real
        fiber leaving the field of view — e.g. two fibers that touch just
        before exiting the scan — not a skeletonization artifact; pruning it
        would demote the genuine junction and fuse the two fibers into one.
        端点が画像端からこの画素数以内にある腕は決して刈らない。スキャン端で
        終わる短い腕は視野外へ続く本物のファイバーであり（例: スキャン端の
        直前で接触する 2 本のファイバー）、細線化アーティファクトではない。
        これを刈ると真の合流点が消え、2 本のファイバーが 1 本に融合して
        しまう。

    Returns
    -------
    ndarray
        uint8 0/1 skeleton image with short spurs removed.
        短いスパーを除去した uint8 0/1 スケルトン画像。

    Notes
    -----
    Unlike `Skeletonizer.prune_branches` this is purely geometric: no height
    gate is applied. A spur growing from the fiber body sits at fiber height,
    so a height threshold cannot separate it from a genuine crossing, while a
    length limit can — a real fiber arm is rarely this short. Isolated short
    segments (no branch point within reach) are kept.
    `Skeletonizer.prune_branches` と異なり高さゲートのない純幾何判定である。
    ファイバー本体から生えたスパーの根元はファイバー自身の高さになるため、
    高さしきい値では本物の交差と区別できないが、長さ制限なら区別できる
    （実ファイバーの枝がこの長さ以下になることはまれ）。分岐点に到達しない
    孤立短片は保持する。

    The sweep repeats until no spur is removed, so nested spur trees collapse
    fully. A branch point whose spur was already deleted in the same sweep is
    re-checked against its live neighbor count, so the main line is never
    truncated through a stale branch-point mask.
    掃引は除去が発生しなくなるまで繰り返すため、入れ子のスパー群も完全に潰れる。
    同一掃引内でスパーが削除済みの分岐点は現時点の近傍数で再判定するので、
    古い分岐点マスク経由で本線の先端が誤って切り詰められることはない。
    """
    skel = (np.asarray(skeleton_image) > 0).astype(np.uint8)
    if max_length <= 0:
        return skel
    height, width = skel.shape
    while True:
        bp = imp_tools.branchedPoints(skel).astype(bool)
        if not bp.any():
            return skel
        ep_mask = imp_tools.endPoints(skel).astype(bool) & (skel > 0)
        removed = False
        for sy, sx in zip(*np.where(ep_mask)):
            # An endpoint at the scan border marks a fiber leaving the field
            # of view, not a spur tip: keep the whole arm (see border_margin).
            # スキャン端の端点は視野外へ続くファイバーの印でありスパーの先端
            # ではないため、腕全体を保持する（border_margin 参照）。
            if (sy < border_margin or sx < border_margin
                    or sy >= height - border_margin
                    or sx >= width - border_margin):
                continue
            path = [(int(sy), int(sx))]
            cy, cx = int(sy), int(sx)
            while len(path) <= max_length:
                candidates = []
                hit_junction = False
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if not (0 <= ny < height and 0 <= nx < width):
                            continue
                        if not skel[ny, nx] or (ny, nx) in path:
                            continue
                        # The mask can be stale within one sweep (an earlier
                        # removal may have demoted this junction), so confirm
                        # against the live neighbor count before cutting.
                        # マスクは同一掃引内で古くなり得る（先の除去で分岐点で
                        # なくなる）ため、切断前に現在の近傍数で確認する。
                        if bp[ny, nx] and _junction_degree(skel, ny, nx) >= 3:
                            hit_junction = True
                        else:
                            candidates.append((ny, nx))
                if hit_junction:
                    for py, px in path:
                        skel[py, px] = 0
                    removed = True
                    break
                if len(candidates) != 1:
                    # Dead end (isolated segment) or an ambiguous widening the
                    # branch templates missed: keep the pixels untouched.
                    break
                cy, cx = candidates[0]
                path.append((cy, cx))
        if not removed:
            return skel


def _walk_from_endpoint(
    skel: NDArray[np.uint8], sy: int, sx: int, max_steps: int,
) -> list[tuple[int, int]]:
    """
    Collect the ordered single-path pixels starting at a skeleton endpoint.
    スケルトン端点から始まる順序付き単一経路の画素列を収集する。

    The walk follows the unique unvisited neighbor at each step and stops at a
    dead end, at a junction (more than one continuation), or after `max_steps`
    pixels, so it never wanders into ambiguous topology.
    各ステップで唯一の未訪問隣接画素を辿り、行き止まり・合流点（続きが複数）・
    `max_steps` 画素到達で停止する。曖昧なトポロジーへは踏み込まない。

    Parameters
    ----------
    skel
        Binary skeleton image.
        2 値の骨格画像。
    sy, sx
        Endpoint the walk starts from.
        たどり始める端点。
    max_steps
        Most pixels the walk collects, the start included.
        たどって集める画素数の上限（始点を含む）。

    Returns
    -------
    list of tuple
        ``(y, x)`` of the pixels walked, starting with the endpoint.
        たどった画素の ``(y, x)``。端点から始まる。
    """
    height, width = skel.shape
    path = [(sy, sx)]
    cy, cx = sy, sx
    while len(path) < max_steps:
        candidates = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cy + dy, cx + dx
                if not (0 <= ny < height and 0 <= nx < width):
                    continue
                if not skel[ny, nx] or (ny, nx) in path:
                    continue
                candidates.append((ny, nx))
        if len(candidates) != 1:
            break
        cy, cx = candidates[0]
        path.append((cy, cx))
    return path


def prune_terminal_hooks(
    skeleton_image: NDArray[np.uint8],
    calibrated_image: Optional[np.ndarray],
    max_hook_length: int = DEFAULT_HOOK_LENGTH,
    max_apex_angle_deg: float = DEFAULT_HOOK_APEX_ANGLE_DEG,
    max_height_ratio: float = DEFAULT_HOOK_HEIGHT_RATIO,
    border_margin: int = 2,
) -> NDArray[np.uint8]:
    """
    Remove junction-free terminal hooks that curl back over background pixels.
    背景画素の上へ折り返す、分岐点を持たない末端フックを除去する。

    Parameters
    ----------
    skeleton_image
        Binary skeleton image. Nonzero pixels are treated as skeleton pixels.
        二値スケルトン画像。非ゼロ画素をスケルトン画素として扱う。
    calibrated_image
        Height-calibrated image supplying the background-level guard. ``None``
        disables pruning entirely: without heights a reversal alone cannot be
        distinguished from a genuinely bent fiber end, so nothing is trimmed.
        背景レベル判定に使う較正済み高さ画像。``None`` の場合は除去を完全に
        無効化する。高さ情報なしでは方向反転だけで本当に折れ曲がった末端と
        区別できないため、何も切除しない。
    max_hook_length
        Maximum distance in pixels from an endpoint within which a reversal
        apex is searched, and the cap on trimmed pixels. ``0`` disables
        pruning.
        反転頂点を探索する端点からの最大距離 (px)。切除画素数の上限でもある。
        ``0`` で無効化。
    max_apex_angle_deg
        A terminal segment counts as reversed when the interior angle at some
        apex — between the arm toward the fiber body and the chord to the
        endpoint — is below this value (degrees; 180 = straight). Keep it well
        below the kink-detection threshold so kink analysis is unaffected.
        端から見た頂点の内角（本体側の腕と端点への弦のなす角。180 = 直線）が
        この値（度）未満のとき、末端セグメントを反転とみなす。キンク検出への
        干渉を避けるため、キンク判定しきい値より十分小さく保つこと。
    max_height_ratio
        Only pixels whose calibrated height is below this fraction of the
        adjacent fiber body's median height are trimmed. This is the guard
        that protects genuinely bent fiber ends, which stay at fiber height.
        較正高さが隣接する本体の中央値高さのこの比率未満の画素だけを切除する。
        繊維の高さを保つ本当に折れ曲がった末端を守るガードである。
    border_margin
        Endpoints within this many pixels of the image border are left alone,
        matching the guard in `prune_short_spurs`: an arm ending at the scan
        border is a fiber leaving the field of view, not an artifact.
        画像端からこの画素数以内の端点は対象外とする（`prune_short_spurs` と
        同じガード）。スキャン端で終わる腕は視野外へ続くファイバーであり
        アーティファクトではない。

    Returns
    -------
    ndarray
        uint8 0/1 skeleton image with background-level terminal hooks removed.
        背景レベルの末端フックを除去した uint8 0/1 スケルトン画像。

    Notes
    -----
    Boundary-shape perturbations producing spurious terminal skeleton
    segments, and their removal by pruning, are the classic artifact class of
    the skeletonization literature (Shaked & Bruckstein 1998; Saha et al.
    2016). Those binary-shape significance measures cannot help here, though:
    relative to the (flawed) mask the hook is a faithful medial axis of the
    admitted skirt, so the missing information is the height data. The
    trimming criterion instead follows grayscale-guided fiber tracing (e.g.
    FiberApp, Usov & Mezzenga 2015): a fiber centerline must lie on the height
    ridge, so a reversed end segment running at background level is removed,
    while a reversed end at fiber height is kept as real geometry. The height
    gate mirrors `collapse_skeleton_loops`' ratio guard.
    境界形状の摂動が偽の末端スケルトンセグメントを生み、それを枝刈りで除去
    するという構図は、細線化文献の古典的なアーティファクト類型である
    (Shaked & Bruckstein 1998; Saha et al. 2016)。ただし二値形状のみの有意性
    測度はここでは役に立たない。（誤りを含む）マスクを所与とすればフックは
    裾の忠実な medial axis であり、欠けている情報は高さデータだからである。
    切除基準はグレースケール誘導の繊維トレース（例: FiberApp, Usov &
    Mezzenga 2015）に従う。繊維の中心線は高さの稜線上になければならないため、
    背景レベルを走る反転末端は除去し、繊維高さを保つ反転末端は実在の形状と
    して保持する。高さゲートは `collapse_skeleton_loops` の比率ガードと同じ
    設計である。

    The trim is capped at the deepest reversal apex found, so a straight
    faded end — even one at low height — is never shortened; only the pixels
    of the returning tail itself are candidates.
    切除は検出された最も深い反転頂点までに制限されるため、（低い高さでも）
    まっすぐ薄れていく末端が短縮されることはない。折り返している尾の画素
    だけが候補になる。
    """
    skel = (np.asarray(skeleton_image) > 0).astype(np.uint8)
    if max_hook_length <= 0 or calibrated_image is None:
        return skel
    height, width = skel.shape
    ep_mask = imp_tools.endPoints(skel).astype(bool) & (skel > 0)
    walk_cap = max_hook_length + _HOOK_DIRECTION_WINDOW + _HOOK_BODY_WINDOW
    for sy, sx in zip(*np.where(ep_mask)):
        if (sy < border_margin or sx < border_margin
                or sy >= height - border_margin
                or sx >= width - border_margin):
            continue
        # A previous trim on a tiny component may have erased this endpoint.
        # 小さな成分では先行する切除がこの端点を消していることがある。
        if not skel[sy, sx]:
            continue
        path = _walk_from_endpoint(skel, int(sy), int(sx), walk_cap)
        n = len(path)
        py = np.array([p[0] for p in path], dtype=float)
        px = np.array([p[1] for p in path], dtype=float)

        # Deepest apex whose interior angle marks a reversal. The body arm is
        # averaged over _HOOK_DIRECTION_WINDOW px so single-pixel jitter of
        # the 8-connected chain cannot fake a reversal.
        # 内角が反転を示す最も深い頂点を探す。本体側の腕は
        # _HOOK_DIRECTION_WINDOW px で平均化し、8 連結チェーンの 1 画素の
        # ジグザグが反転と誤認されないようにする。
        apex = -1
        for j in range(1, min(max_hook_length, n - _HOOK_DIRECTION_WINDOW - 1) + 1):
            body_y = py[j + _HOOK_DIRECTION_WINDOW] - py[j]
            body_x = px[j + _HOOK_DIRECTION_WINDOW] - px[j]
            end_y = py[0] - py[j]
            end_x = px[0] - px[j]
            norm_body = float(np.hypot(body_y, body_x))
            norm_end = float(np.hypot(end_y, end_x))
            if norm_body == 0.0 or norm_end == 0.0:
                continue
            cos_apex = (body_y * end_y + body_x * end_x) / (norm_body * norm_end)
            angle = float(np.degrees(np.arccos(np.clip(cos_apex, -1.0, 1.0))))
            if angle < max_apex_angle_deg:
                apex = j
        if apex < 0:
            continue

        # Height reference from the fiber body just beyond the apex.
        # 頂点のすぐ先の本体画素から高さ基準を取る。
        body_px = path[apex + 1: apex + 1 + _HOOK_BODY_WINDOW]
        if len(body_px) < 4:
            continue
        body_median = float(np.median(
            [calibrated_image[p] for p in body_px]
        ))
        threshold = max_height_ratio * body_median
        if threshold <= 0.0:
            continue

        # Trim the terminal run of background-level pixels, never past the
        # apex, so at most the returning tail is removed.
        # 端から背景レベル画素の連なりを切除する。頂点より先へは進まないため、
        # 除去されるのは最大でも折り返しの尾だけである。
        run = 0
        while run < apex and calibrated_image[path[run]] < threshold:
            run += 1
        for i in range(run):
            skel[path[i]] = 0
    return skel


class Skeletonizer:
    """
    Extract and clean skeleton traces from a segmented AFM nanofiber mask.
    セグメント化された AFM ナノファイバーマスクからスケルトントレースを抽出・整形する。

    Attributes
    ----------
    bp_height
        Height threshold used to classify low branch points in the calibrated image.
        較正済み画像で低い分岐点を分類するための高さしきい値。
    branch_length
        Search radius in pixels used to connect nearby endpoints to low branch points.
        近傍端点を低い分岐点へ接続して追跡する探索半径 (px)。
    min_area
        Minimum connected-component area retained in the final skeleton.
        最終スケルトンに残す連結成分の最小面積。
    max_loop_area
        Maximum enclosed area of skeleton loop artifacts collapsed by
        `collapse_skeleton_loops`. ``0`` disables loop collapsing.
        `collapse_skeleton_loops` で潰すループアーティファクトの最大囲み面積。
        ``0`` で無効化。
    spur_length
        Maximum length of dead-end spurs removed by `prune_short_spurs`
        regardless of height. ``0`` disables spur pruning.
        高さに関係なく `prune_short_spurs` で除去する行き止まりスパーの最大長。
        ``0`` で無効化。
    image_shape
        Shape of the working image as ``(height, width)``.
        作業画像の形状 ``(高さ, 幅)``。

    Examples
    --------
    The stage reads the binary mask and the calibrated image, so the two
    stages before it run first. The input path is relative to the repository
    root:

    >>> import numpy as np
    >>> from lib.afm_io import load_afm_text
    >>> from lib.pipeline import ProcParams, build_stages
    >>> from lib.processed_image import ProcessedImage
    >>> heights = load_afm_text("testdata_artificial/sample_isotropic.txt")
    >>> image = ProcessedImage(original_AFM=heights, name="sample_isotropic")
    >>> stages = build_stages(ProcParams())
    >>> stages.bg_calibrator(image)
    >>> stages.segmenter(image)
    >>> stages.skeletonizer(image)
    >>> np.unique(image.skeleton_image)
    array([0, 1], dtype=uint8)
    >>> image.label_image.shape == image.skeleton_image.shape
    True
    """

    def __init__(
        self,
        bp_height: float = 5,
        branch_length: int = 8,
        min_area: int = 10,
        max_loop_area: int = DEFAULT_MAX_LOOP_AREA,
        spur_length: int = DEFAULT_SPUR_LENGTH,
    ) -> None:
        """
        Initialize skeleton pruning parameters.
        スケルトン枝刈り用のパラメータを初期化する。

        Parameters
        ----------
        bp_height
            Height threshold used to classify branch points as low or high.
            分岐点を低い点または高い点として分類する高さしきい値。
        branch_length
            Search radius in pixels for short branch tracking.
            短い枝を追跡するための探索半径 (px)。
        min_area
            Minimum connected-component area retained after cleanup.
            後処理後に保持する連結成分の最小面積。
        max_loop_area
            Maximum enclosed area (px) of loop artifacts to collapse; ``0``
            disables loop collapsing.
            潰すループアーティファクトの最大囲み面積 (px)。``0`` で無効化。
        spur_length
            Maximum dead-end spur length (px) removed without a height gate;
            ``0`` disables spur pruning.
            高さゲートなしで除去する行き止まりスパーの最大長 (px)。
            ``0`` で無効化。
        """
        self.bp_height = bp_height
        self.branch_length = branch_length
        self.min_area = min_area
        self.max_loop_area = max_loop_area
        self.spur_length = spur_length
        self.image_shape = None
        self._coor_low_bps = None
        self._coor_high_bps = None
        self._coor_close_eps = None
        self._branches_image = None

        self._init_skeleton_image = None
        self._nobranch_image = None
        self._nobranch_skeleton_image = None
        self._cleaned_skeleton_image = None
        self._nosmall_skeleton_image = None

    def __call__(self, image: ProcessedImage) -> None:
        """
        Add a branch-pruned skeleton and connected-component data to an image.
        画像へ枝除去済みスケルトンと連結成分データを追加する。

        Parameters
        ----------
        image
            Processed image produced by background calibration and segmentation.
            背景補正とセグメンテーション後に得られた ProcessedImage インスタンス。

        Returns
        -------
        None
            The input instance is updated in place.
            入力インスタンスをインプレースで更新する。

        Raises
        ------
        ValueError
            If `image.binarized_image` or `image.calibrated_image` is None,
            i.e. segmentation or background calibration has not been run yet.

        Notes
        -----
        Reads `image.binarized_image` and `image.calibrated_image`; writes
        `image.skeleton_image`, `image.label_image`, `image.nLabels`,
        `image.data`, `image.ep`, and `image.bp`.

        The workflow first thins the binary mask without letting the image
        border cut fibers short (`thin_ignoring_image_border`), removes short
        branches derived from low-height branch points, collapses small loop
        artifacts and prunes short spurs geometrically, trims background-level
        terminal hooks against the calibrated heights
        (`prune_terminal_hooks`), prunes the short spurs that trimming leaves,
        and then removes tiny or ring-shaped connected components.
        まず画像端でファイバーを切断しない形で二値マスクを細線化し
        (`thin_ignoring_image_border`)、低い高さの分岐点から伸びる短い枝を除去し、
        小ループの潰しと短いスパーの幾何的除去を行い、較正高さに基づいて背景
        レベルの末端フックを切除し (`prune_terminal_hooks`)、その切除で残った
        短いスパーを刈った後、微小成分やリング状成分を除去する。
        """
        # Fail loudly at the stage boundary instead of deep inside skimage/cv2.
        if image.binarized_image is None:
            raise ValueError(
                "Skeletonizer requires image.binarized_image; "
                "run Segmenter on the image first."
            )
        if image.calibrated_image is None:
            raise ValueError(
                "Skeletonizer requires image.calibrated_image; "
                "run BGCalibrator on the image first."
            )

        init_skeleton_image = thin_ignoring_image_border(image.binarized_image)
        self.image_shape = image.binarized_image.shape
        self._init_skeleton_image = init_skeleton_image
        self.set_low_bp_coor(image.calibrated_image, init_skeleton_image, self.bp_height)
        self.get_close_eps()
        nobranch_image = self.prune_branches(image.calibrated_image, init_skeleton_image)
        self._nobranch_image = nobranch_image
        nobranch_skeleton_image = skeletonize(nobranch_image).astype(np.uint8)
        self._nobranch_skeleton_image = nobranch_skeleton_image
        # Geometric cleanup: collapse loop artifacts left by mask holes, then
        # prune short spurs the height-gated pruning cannot catch. Without
        # this, each artifact puts branch points on a continuous fiber and
        # tracking later splits the fiber there.
        # 幾何クリーニング。マスクの穴が残すループを潰し、高さゲート付き枝刈りで
        # 拾えない短いスパーを除去する。これを行わないと各アーティファクトが
        # 連続ファイバー上に分岐点を作り、追跡時にそこで分断される。
        cleaned_skeleton_image = collapse_skeleton_loops(
            nobranch_skeleton_image, self.max_loop_area, image.calibrated_image
        )
        cleaned_skeleton_image = prune_short_spurs(
            cleaned_skeleton_image, self.spur_length
        )
        # Junction-free hooks at fiber tips (thinning curling into a low mask
        # skirt) survive both passes above; trim them against the height data.
        # ファイバー先端の分岐点を持たないフック（細線化が低いマスクの裾へ
        # 回り込んだもの）は上の 2 パスでは残るため、高さデータで切除する。
        cleaned_skeleton_image = prune_terminal_hooks(
            cleaned_skeleton_image, image.calibrated_image
        )
        # Trimming a hook shortens the arm it ends; an arm that reaches a
        # junction and is now no longer than spur_length is a spur, so prune
        # spurs once more rather than store it.
        # フックの切除はそれが終端する腕を短くする。分岐に届き、長さが
        # spur_length 以下になった腕はスパーなので、保存せずにもう一度刈る。
        cleaned_skeleton_image = prune_short_spurs(
            cleaned_skeleton_image, self.spur_length
        )
        self._cleaned_skeleton_image = cleaned_skeleton_image
        nosmall_skeleton_image = self.remove_small_and_ring(cleaned_skeleton_image)
        self._nosmall_skeleton_image = nosmall_skeleton_image

        # Store connected-component data on the ProcessedImage instance.
        nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(
            nosmall_skeleton_image
        )
        image.skeleton_image = nosmall_skeleton_image
        image.label_image = label_Images
        image.nLabels = nLabels
        image.data = data

        image.ep = imp_tools.endPoints(nosmall_skeleton_image)
        image.bp = imp_tools.branchedPoints(nosmall_skeleton_image)


    def prune_branches(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
    ) -> NDArray[np.uint8]:
        """
        Remove tracked short branches from the initial skeleton.
        初期スケルトンから追跡された短い枝を除去する。

        Parameters
        ----------
        calibrated_image
            Height-calibrated image used to classify branch-point height.
            分岐点の高さ分類に使う較正済み高さ画像。
        init_skeleton_image
            Initial skeleton image before branch pruning.
            枝刈り前の初期スケルトン画像。

        Returns
        -------
        numpy.ndarray
            Skeleton image with tracked branch pixels removed.
            追跡された枝画素を除去したスケルトン画像。
        """
        branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
        return init_skeleton_image - branches_image

    def calc_branches_image(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
    ) -> NDArray[np.uint8]:
        """
        Create a mask of branch pixels selected for pruning.
        枝刈り対象として選ばれた枝画素のマスクを作成する。

        Parameters
        ----------
        calibrated_image
            Height-calibrated image used to classify branch-point height.
            分岐点の高さ分類に使う較正済み高さ画像。
        init_skeleton_image
            Initial skeleton image before branch pruning.
            枝刈り前の初期スケルトン画像。

        Returns
        -------
        numpy.ndarray
            Binary image whose nonzero pixels mark branches to remove.
            非ゼロ画素が除去対象の枝を表す二値画像。
        """
        branches_image = np.zeros_like(init_skeleton_image, dtype=np.uint8)
        coor_branch = self.track_branches()
        if coor_branch[0].size != 0:
            branches_image[coor_branch] = 1
        return branches_image

    def set_low_bp_coor(
        self,
        calibrated_image: np.ndarray,
        init_skeleton_image: NDArray[np.uint8],
        bp_height: float,
    ) -> None:
        """
        Split skeleton branch points into low-height and high-height coordinates.
        スケルトン分岐点を低い高さと高い高さの座標に分ける。

        The coordinates are stored on the instance.
        座標はインスタンスに保存される。

        Parameters
        ----------
        calibrated_image
            Height-calibrated AFM image.
            高さ較正済みの AFM 画像。
        init_skeleton_image
            Skeleton image whose branch points are classified.
            分岐点を分類する対象のスケルトン画像。
        bp_height
            Height threshold separating low and high branch points.
            低い分岐点と高い分岐点を分ける高さしきい値。
        """
        all_bps = imp_tools.branchedPoints(init_skeleton_image)
        low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
        high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
        self._coor_low_bps = low_bp_coor
        self._coor_high_bps = high_bp_coor

    def get_close_eps(self) -> None:
        """
        Find endpoints close to low-height branch points.
        低い高さの分岐点に近い端点を検出する。

        The endpoint coordinates are stored on the instance.
        端点座標はインスタンスに保存される。

        Notes
        -----
        The dilation radius is controlled by `branch_length`, so only endpoints
        that can plausibly be short branches are considered for pruning.
        膨張半径は `branch_length` で制御されるため、短い枝とみなせる端点のみが
        枝刈り候補になる。
        """
        all_eps_image = imp_tools.endPoints(self._init_skeleton_image)
        _low_bps_image = np.zeros_like(self._init_skeleton_image, dtype=np.uint8)
        _low_bps_image[self._coor_low_bps] = 1

        k = self.branch_length
        dilated_low_bps = maximum_filter(
            _low_bps_image.astype(float), size=2 * k, mode='constant', cval=0, origin=0
        )
        close_eps = all_eps_image & (dilated_low_bps > 0).astype(np.uint8)
        self._coor_close_eps = np.where(close_eps)

    def track_branches(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Track branch pixels from nearby endpoints toward low-height branch points.
        近傍端点から低い高さの分岐点に向かって枝画素を追跡する。

        Returns
        -------
        tuple of numpy.ndarray
            Row and column coordinates of branch pixels selected for pruning.
            枝刈り対象として選ばれた枝画素の行・列座標。

        Notes
        -----
        An arm is pruned when the walk reaches a low branch point, or when it
        dead-ends without reaching any branch point (an isolated short
        fragment). It is kept when the walk touches a high branch point or
        exhausts the configured branch length, because neither confirms a short
        low branch.
        腕を刈るのは、探索が低い分岐点に到達した場合と、分岐点に到達しないまま
        行き止まりになった場合（孤立した短片）である。高い分岐点に接した場合と
        設定された枝長を使い切った場合は、短い低分岐であることが確認できないため
        保持する。

        The walk covers the whole image with explicit bounds checks, so a
        fiber that continues beyond the neighbourhood of its endpoint is never
        read as a dead end. Each walk carries its own visited set, so the
        result does not depend on the order the endpoints are processed in.
        探索は画像全体を明示的な境界判定で辿るため、端点の近傍の外へ続く
        ファイバーが行き止まりと読まれることはない。各探索は自前の訪問済み集合を
        持つため、結果は端点の処理順に依存しない。
        """
        branches_coor_x = []
        branches_coor_y = []
        # Read-only: the walk never blanks pixels as it advances.
        # 読み取り専用。探索は進行中に画素を消さない。
        skeleton = self._init_skeleton_image
        height, width = skeleton.shape

        image_low_bps = np.zeros(skeleton.shape, dtype=bool)
        image_low_bps[self._coor_low_bps] = True  # Mark low branch points in the boolean mask.

        image_high_bps = np.zeros(skeleton.shape, dtype=bool)
        image_high_bps[self._coor_high_bps] = True

        def touches(mask: np.ndarray, row: int, col: int) -> bool:
            """Whether `mask` is set anywhere in the 3x3 neighborhood of (row, col)."""
            return bool(mask[max(0, row - 1): row + 2, max(0, col - 1): col + 2].any())

        # Start tracking from endpoints and stop when a low branch point is reached.
        # ep からトラック開始。low_bp にぶつかったら終了。
        # `_coor_close_eps` comes from `np.where`, so `x` is a row index and `y`
        # a column index throughout this method.
        # `_coor_close_eps` は `np.where` 由来のため、本メソッドを通して `x` は行、
        # `y` は列のインデックスを表す。
        starts_x, starts_y = self._coor_close_eps
        bl = self.branch_length
        for start_x, start_y in zip(starts_x, starts_y):
            # Leave endpoints near the scan border alone. An arm ending that
            # close to the edge is a fiber leaving the field of view rather
            # than a branch tip, so pruning it would cut a real fiber short —
            # the same reason `prune_short_spurs` keeps its `border_margin`
            # arms.
            # スキャン端に近い端点は対象外とする。端の近くで終わる腕は枝の先端では
            # なく視野外へ抜けるファイバーであり、刈ると実ファイバーを切り詰めて
            # しまう（`prune_short_spurs` が `border_margin` の腕を残すのと同じ
            # 理由）。
            if not (bl <= start_x <= height - bl and bl <= start_y <= width - bl):
                continue
            x, y = int(start_x), int(start_y)
            xtrack = [x]
            ytrack = [y]
            # Each walk carries its own visited set, so an earlier endpoint's
            # walk cannot hide skeleton from a later one.
            # 各探索は自前の訪問済み集合を持つため、先に処理した端点の探索が
            # 後続の探索から骨格を隠すことはない。
            visited = {(x, y)}

            for _ in range(bl):
                # Candidates are taken in raster order (row-major).
                next_pixels = [
                    (x + dx, y + dy)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if (dx, dy) != (0, 0)
                    and 0 <= x + dx < height and 0 <= y + dy < width
                    and skeleton[x + dx, y + dy]
                    and (x + dx, y + dy) not in visited
                ]
                if not next_pixels:
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                if touches(image_low_bps, x, y):
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                if touches(image_high_bps, x, y):
                    break

                x, y = next_pixels[0]
                visited.add((x, y))
                xtrack.append(x)
                ytrack.append(y)

        branches_coor_x = np.asarray(branches_coor_x)
        branches_coor_y = np.asarray(branches_coor_y)
        return branches_coor_x, branches_coor_y

    def remove_small_and_ring(self, skeleton_image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """
        Remove tiny skeleton components and closed components without endpoints.
        微小なスケルトン成分と端点を持たない閉じた成分を除去する。

        Parameters
        ----------
        skeleton_image
            Skeleton image after branch pruning.
            枝刈り後のスケルトン画像。

        Returns
        -------
        numpy.ndarray
            Skeleton image with small components and endpoint-free rings removed.
            微小成分と端点を持たないリング状成分を除去したスケルトン画像。
        """
        returned_image = np.copy(skeleton_image)
        nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(returned_image)
        ep = imp_tools.endPoints(returned_image)
        ring_frac_label = np.setdiff1d(np.arange(1, nLabels), label_Images[ep > 0])
        # Vectorize: collect all labels to remove, then apply a single boolean mask
        areas = np.array([data[i][4] for i in range(1, nLabels)])
        small_labels = np.nonzero(areas < self.min_area)[0] + 1  # +1: labels are 1-indexed
        remove_labels = np.union1d(small_labels, ring_frac_label)
        if remove_labels.size > 0:
            returned_image[np.isin(label_Images, remove_labels)] = 0
        return returned_image
