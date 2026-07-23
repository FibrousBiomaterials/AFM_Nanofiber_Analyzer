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


# Endpoint / branch-point detection lives in imp_tools, which now uses the same
# OpenCV MORPH_HITMISS path that was previously duplicated here. Skeletonizer
# calls imp_tools.endPoints / imp_tools.branchedPoints directly.
# 端点・分岐点検出は imp_tools 側にあり、以前ここに重複していた OpenCV
# MORPH_HITMISS と同じ処理を使う。Skeletonizer は imp_tools.endPoints /
# imp_tools.branchedPoints を直接呼ぶ。


# Default geometric-cleanup limits shared by the pipeline (Skeletonizer) and
# the load-time defensive cleanup in FiberTrackingImage. Loops and spurs are
# skeletonization artifacts: interior holes in the binary mask survive
# topology-preserving thinning as small double-path loops, and fiber-width
# bumps leave short dead-end side branches. Both put branch points on a single
# continuous fiber, and tracking later cuts the fiber at every branch point.
# パイプライン（Skeletonizer）と FiberTrackingImage の読み込み時防御クリーニング
# が共有する幾何クリーニングの既定値。ループとスパーは細線化アーティファクト
# であり、二値マスク内部の穴はトポロジー保存細線化で二重経路の小ループとして
# 残り、ファイバー幅の揺らぎは短い行き止まりの側枝を残す。どちらも 1 本の
# 連続ファイバー上に分岐点を作り、追跡時にその分岐点ごとに分断が起きる。
DEFAULT_MAX_LOOP_AREA = 100
DEFAULT_SPUR_LENGTH = 12

# Height-ratio guard for loop filling. A loop artifact encloses pixels of the
# fiber body itself (just below the binarization threshold, e.g. 40-90% of the
# surrounding ridge height on the bundled scans), while the enclosure formed
# by two real fibers touching twice contains background-level pixels (~10% of
# ridge height). 0.3 sits between the two regimes with margin on both sides.
# ループ充填の高さ比ガード。ループアーティファクトが囲むのはファイバー本体の
# 画素（二値化しきい値をわずかに下回るだけで、同梱スキャンでは周囲リッジ高の
# 40〜90%）だが、実ファイバー 2 本が 2 点で接触してできる囲みは背景レベル
# （リッジ高の約 10%）の画素を含む。0.3 は両者の間に双方向の余裕を持って位置する。
DEFAULT_LOOP_HEIGHT_RATIO = 0.3


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
        filled. ``0`` disables loop collapsing. Two genuinely crossing fibers
        enclose far larger regions, so keep this value small.
        ループアーティファクトとして充填する、囲まれた背景領域の最大面積 (px)。
        ``0`` で無効化。実ファイバー 2 本の交差が囲む領域ははるかに大きいため、
        小さい値を保つこと。
    calibrated_image
        Height-calibrated image used to reject enclosures whose interior is at
        background level. ``None`` skips this guard and fills by area alone.
        囲み内部が背景レベルの場合に充填を拒否するための較正済み高さ画像。
        ``None`` の場合はこのガードを行わず面積のみで充填する。
    min_height_ratio
        Minimum ratio of the enclosed region's median height to the
        surrounding skeleton ridge's median height for the enclosure to count
        as a loop artifact. A loop artifact lies inside the fiber body, so its
        interior stays elevated; a sliver enclosed by two distinct fibers
        touching twice contains background-level pixels and must not be
        filled, because filling would fuse the two fibers and fabricate a
        mid-groove path.
        囲み領域をループアーティファクトとみなすための、内部の中央値高さと
        周囲骨格リッジの中央値高さの最小比。ループアーティファクトは
        ファイバー本体の内側にあるため内部は高いままだが、別々の 2 本が
        2 点で接触して囲む細長い隙間は背景レベルの画素を含む。これを充填
        すると 2 本が融合し、溝の中間に経路が捏造されるため充填してはならない。

    Returns
    -------
    ndarray
        uint8 0/1 skeleton image with small loops replaced by single lines.
        小ループを 1 本の線へ置き換えた uint8 0/1 スケルトン画像。

    Notes
    -----
    Interior holes in the binarized fiber mask survive topology-preserving
    thinning as a double path around each hole, and each such loop yields two
    or three branch points on one continuous fiber. Filling the enclosed
    region and re-skeletonizing merges the double path back into one line.
    Re-skeletonization is a fixed point on the already-thin line, so pixels
    far from the filled loops stay in place and coordinate-keyed feature
    lookups (kinks, endpoints) remain valid there.
    二値マスク内部の穴はトポロジー保存細線化で穴を囲む二重経路として残り、
    ループ 1 つが連続ファイバー上に分岐点を 2〜3 個作る。囲まれた領域を充填して
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
            # 2 px ring; background-level interiors mark a gap between two
            # real fibers, not a loop artifact, and are left untouched.
            # 囲み内部と周囲 2 px リング上のリッジ高を比較する。内部が背景
            # レベルなら実ファイバー 2 本の間の隙間でありループではないため
            # 充填しない。
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
    """Count live skeleton neighbors of (y, x) in the 8-neighborhood."""
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

        The workflow first thins the binary mask, removes short branches derived
        from low-height branch points, collapses small loop artifacts and prunes
        short spurs geometrically, and then removes tiny or ring-shaped
        connected components.
        まず二値マスクを細線化し、低い高さの分岐点から伸びる短い枝を除去し、
        小ループの潰しと短いスパーの幾何的除去を行った後、微小成分やリング状
        成分を除去する。
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

        init_skeleton_image = thin(image.binarized_image).astype(np.uint8)
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

        Returns
        -------
        None
            Coordinates are stored on the instance.
            座標はインスタンスに保存される。
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

        Returns
        -------
        None
            Endpoint coordinates are stored on the instance.
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
        Tracking stops when it reaches a low branch point, encounters a high
        branch point, leaves the local branch window, or exhausts the configured
        branch length.
        低い分岐点に到達した場合、高い分岐点に接した場合、局所探索窓から外れる場合、
        または設定された枝長を使い切った場合に追跡を停止する。
        """
        branches_coor_x = []
        branches_coor_y = []
        image_for_tracking = self._init_skeleton_image.copy()

        height, width = image_for_tracking.shape

        image_low_bps = np.zeros_like(image_for_tracking, dtype=bool)
        image_low_bps[self._coor_low_bps] = True  # Mark low branch points in the boolean mask.

        image_high_bps = np.zeros_like(image_for_tracking, dtype=bool)
        image_high_bps[self._coor_high_bps] = True
        # Start tracking from endpoints and stop when a low branch point is reached.
        # ep からトラック開始。low_bp にぶつかったら終了。
        starts_x, starts_y = self._coor_close_eps
        for step_num, (start_x, start_y) in enumerate(zip(starts_x, starts_y)):
            bl = self.branch_length
            if (start_x < bl or start_x + bl > height or
                    start_y < bl or start_y + bl > width):
                continue
        
            tracking_area = image_for_tracking[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
            image_for_low_bp_detection = image_low_bps[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
            image_for_high_bp_detection = image_high_bps[
                start_x - bl : start_x + bl,
                start_y - bl : start_y + bl,
            ]
        
            x, y = bl, bl
            xtrack = [x + start_x - bl]
            ytrack = [y + start_y - bl]
        
            for i in range(bl):
                tracking_area[x, y] = 0
                window = tracking_area[x - 1 : x + 2, y - 1 : y + 2]
        
                if (window == 0).all():
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                elif image_for_low_bp_detection[x - 1 : x + 2, y - 1 : y + 2].any():
                    branches_coor_x += xtrack
                    branches_coor_y += ytrack
                    break
                elif image_for_high_bp_detection[x - 1 : x + 2, y - 1 : y + 2].any():
                    break
        
                direction_rows, direction_cols = np.where(window != 0)
                if len(direction_rows) == 0:
                    break
                x += int(direction_rows[0]) - 1
                y += int(direction_cols[0]) - 1
                xtrack.append(x + start_x - bl)
                ytrack.append(y + start_y - bl)

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
