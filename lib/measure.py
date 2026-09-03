# -*- coding: utf-8 -*-
"""
GUI-independent fiber measurement on GUI01 ``.b2z`` bundles.
GUI01 の ``.b2z`` バンドルに対する GUI 非依存のファイバー計測モジュール。

This module owns the measurement-side responsibilities that were previously
embedded in GUI03 and GUI04: rebuilding `FiberTrackingImage` objects from a
bundle, computing per-fiber summary statistics, collecting skeleton-pixel
heights, and writing the result CSV files.
GUI03 と GUI04 に埋め込まれていた計測側の責務（バンドルからの
`FiberTrackingImage` 再構築、ファイバーごとの要約統計、スケルトン画素高さの
収集、結果 CSV の書き出し）をこのモジュールが持つ。

GUI04 and the `measure` command both call `measure_bundle` and
`write_fiber_csv`, so a complete, unfiltered GUI04 export matches the CLI for
the same bundle and scale. When GUI04's height filter is active, it deliberately
exports statistics for only the retained fiber portions. GUI03 and the
`heights` command share `skeleton_height_values`.
GUI04 と `measure` コマンドは `measure_bundle` と `write_fiber_csv` を共有するため、
GUI04 で全件をフィルターなしに出力すれば、同じバンドルとスケールに対する CLI
出力と一致する。GUI04 の高さフィルターが有効な場合は、意図どおり残った
ファイバー部分だけの統計を出力する。GUI03 と `heights` コマンドは
`skeleton_height_values` を共有する。

Like `lib.pipeline`, this module reports errors as fixed English strings and
keeps gettext out of the analysis layer; callers translate as needed.
`lib.pipeline` と同様、エラーは固定の英語文字列で返し、解析層に gettext を
持ち込まない。翻訳は呼び出し側で行う。

Notes
-----
When a bundle records the physical scan size (``spatial_calibration`` vlmeta,
populated from the instrument header or a manual/manifest value at processing
time), `measure_bundle` defaults `scale_um` to that recorded value, so
length and distance results are reproducible from the bundle alone. Callers
may still pass `scale_um` explicitly, and must do so for older bundles that
predate the scan-size contract.
バンドルが物理走査範囲（``spatial_calibration`` vlmeta。処理時に装置ヘッダ
または手入力／マニフェスト値から設定される）を記録していれば、
`measure_bundle` は `scale_um` をその記録値で既定化するため、長さ・距離の
結果がバンドル単体で再現できる。呼び出し側は `scale_um` を明示指定もでき、
走査範囲契約より前のバンドルでは明示指定が必須となる。
"""

# ===== Standard library =====
import csv
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .blosc2_io import load_bundle, load_bundle_meta
# The key contract and validation are owned by bundle_schema; TRACKING_BUNDLE_KEYS
# is re-imported here so existing `measure.TRACKING_BUNDLE_KEYS` users keep working.
# キー契約と検証は bundle_schema が管理する。既存の
# `measure.TRACKING_BUNDLE_KEYS` 利用側が動き続けるよう、ここで再インポートする。
from .bundle_schema import (
    TRACKING_BUNDLE_KEYS,
    scan_size_um_from_meta,
    validate_bundle,
)
from .fiber import Fiber
from .fiber_connector import (
    ConnectParams,
    connect_fiber_fragments,
    connection_candidate_flags,
)
from .fiber_selection import (
    excluded_flags,
    exclusion_path_for,
    load_exclusions,
)
from .fiber_tracking_image import FiberTrackingImage
# Straightness measures a straight reference line with the same corrected
# chain-code metric the fiber's own length uses, so the two are comparable.
# 直線度は、ファイバー自身の長さが使うのと同じ補正済みチェーンコード尺度で
# 基準となる直線を測るため、両者が比較可能になる。
from . import imp_tools

# Chebyshev distance in pixels within which a track pixel counts as touching a
# branch point. `imp_tools.remove_bp` clears a 3x3 neighborhood around each
# branch point, so the terminal of a fragment cut there lands exactly 2 px from
# the branch-point center; a smaller radius would miss every cut terminal.
# 追跡画素が分岐点に接していると見なすチェビシェフ距離 (px)。
# `imp_tools.remove_bp` は各分岐点の 3x3 近傍を消去するため、そこで切断された
# 断片の端は分岐点中心のちょうど 2 px 先に来る。これより小さい半径では切断端を
# 1 つも捉えられない。
BRANCH_TOUCH_RADIUS_PX = 2

# Arc length over which local curvature measures its turning angle, chosen by
# measuring digitised circles of known radius and by rendering real fibers
# coloured by curvature across a range of windows.
#
# Against arcs of known radius, a 20 nm window returned 19.4 rad/um whatever
# the true curvature was -- the direction-quantisation floor, not a
# measurement -- and 50 nm was erratic (-30%, -19%, +46% across three radii).
# From 100 nm upwards the estimate settled to a consistent -13% to -19%. On a
# real hooked fibril, 100 nm was the first window whose map separated the
# straight runs from the corners; 400 nm smeared the corners into them.
#
# Larger is not simply better: a fiber shorter than the window yields no
# curvature at all, and with median fiber lengths near 200 nm in these
# samples, a 200 nm default would silently drop about half the population.
# 100 nm is the smallest window that is not noise-dominated, which keeps the
# most fibers measurable.
# 局所曲率が回転角を測る弧長。既知半径の離散化円での測定と、窓幅を振って実際の
# ファイバーを曲率で色分け描画した結果から選定した。
#
# 既知半径の円弧に対し、20 nm の窓は真の曲率によらず 19.4 rad/um を返した。これは
# 計測ではなく方向量子化の下限である。50 nm は 3 つの半径で -30%, -19%, +46% と
# 不安定だった。100 nm 以上では -13%〜-19% の一貫した値に落ち着く。実際の鉤状
# フィブリルでは、直線部と角を区別できた最小の窓が 100 nm であり、400 nm では角が
# 周囲へにじんだ。
#
# 大きければよいわけではない。窓より短いファイバーは曲率を一切返さず、これらの
# 試料ではファイバー長の中央値が 200 nm 前後であるため、200 nm を既定にすると
# 母集団の約半数が黙って落ちる。100 nm はノイズに支配されない最小の窓であり、
# 測定可能なファイバーを最も多く残す。
DEFAULT_CURVATURE_WINDOW_NM = 100.0

# Column order of the per-fiber statistics CSV. This is the single source of
# truth shared by the GUI04 export and the `cli.py measure` subcommand.
# ファイバー統計 CSV の列順。GUI04 のエクスポートと `cli.py measure` が共有する
# 唯一の定義源。
FIBER_CSV_COLUMNS = (
    "index", "length_nm", "height_median_nm", "height_max_nm",
    "ep_count", "kink_count", "kink_angles_deg", "straightness",
)

# The column set shipped in 1.0.0, before straightness was added. Kept so a
# CSV written by that version still reads: the file is how a curated fiber
# population travels between GUI04 and GUI03, and rejecting an older export
# would strand work that is still perfectly valid for every other column.
# 1.0.0 で出荷した列構成（straightness 追加前）。そのバージョンが書き出した CSV
# を今も読めるように残す。このファイルはキュレーション済みのファイバー母集団が
# GUI04 から GUI03 へ渡る経路であり、古い出力を拒否すると、他の全列については
# 依然として有効な作業を無駄にしてしまう。
FIBER_CSV_COLUMNS_V1 = FIBER_CSV_COLUMNS[:-1]


@dataclass(frozen=True)
class FiberStats:
    """
    Summary statistics for one traced fiber.
    追跡された 1 本のファイバーの要約統計値。

    Attributes
    ----------
    index
        Zero-based fiber index within the source list.
        元リスト内での 0 始まりのファイバー番号。
    length_nm
        Total fiber length along the skeleton path in nanometers.
        骨格線に沿ったファイバー全長 (nm)。
    height_median_nm
        Median height over the skeleton path in nanometers. 0.0 when the
        fiber has no height samples.
        骨格線上の高さ中央値 (nm)。高さサンプルが無い場合は 0.0。
    height_max_nm
        Maximum height over the skeleton path in nanometers. 0.0 when the
        fiber has no height samples.
        骨格線上の高さ最大値 (nm)。高さサンプルが無い場合は 0.0。
    ep_count
        Number of endpoints detected on this fiber.
        このファイバーで検出された端点の数。
    kink_count
        Number of kink points detected on this fiber.
        このファイバーで検出されたキンク点の数。
    kink_angles_deg
        Kink interior angles converted to degrees, in track order.
        The bundle stores angles in radians (`ka` key); the conversion to
        degrees happens here so every consumer reports the same unit.
        追跡順に並んだキンク内角（度）。バンドルは角度をラジアン（`ka` キー）で
        保存しているため、度への変換をここで一元化し、全ての利用側が同じ単位で
        出力する。
    straightness
        End-to-end distance divided by contour length, in (0, 1]; 1.0 is a
        straight fiber and a coiled one approaches 0. NaN when the pixel size
        was not supplied, or when the contour length is zero.
        端点間距離を輪郭長で割った値（(0, 1]）。1.0 は直線状のファイバーで、
        巻き込んだものほど 0 に近づく。ピクセルサイズが与えられなかった場合、
        または輪郭長が 0 の場合は NaN。
    """

    index: int
    length_nm: float
    height_median_nm: float
    height_max_nm: float
    ep_count: int
    kink_count: int
    kink_angles_deg: Tuple[float, ...]
    straightness: float = float("nan")


@dataclass(frozen=True)
class MeasureResult:
    """
    Result of measuring one ``.b2z`` bundle.
    1 つの ``.b2z`` バンドルを計測した結果。

    Attributes
    ----------
    image
        Rebuilt tracking container with `size_per_pixel` resolved.
        `size_per_pixel` を確定済みの再構築済み追跡コンテナ。
    fibers
        Measured fibers in stable component order, after exclusions and any
        reconnection were applied.
        除外と（有効なら）再結合を適用した後の、安定した連結成分順のファイバー
        リスト。
    stats
        Per-fiber statistics aligned with `fibers` by index.
        `fibers` とインデックスで対応するファイバーごとの統計値。
    fragments
        Traced skeleton fragments as they came out of tracing, before any
        exclusion or reconnection. Kept so a caller that changes the
        curation can rebuild `fibers` without tracing the bundle again.
        追跡直後の骨格断片。除外・再結合を適用する前の状態。キュレーションを
        変更する呼び出し側が、バンドルを追跡し直さずに `fibers` を組み立て直せる
        ようにするため保持する。
    curated_count
        How many fibers were left after exclusions, i.e. how many entered
        reconnection. Equal to ``len(fibers)`` when reconnection was off, and
        the difference from it is the number of joins the connector made.
        除外の適用後に残ったファイバー数。すなわち再結合へ入った本数である。
        再結合が無効なら ``len(fibers)`` に等しく、両者の差が連結器の行った連結
        の件数となる。
    """

    image: FiberTrackingImage
    fibers: List[Fiber]
    stats: List[FiberStats]
    fragments: List[Fiber] = field(default_factory=list)
    curated_count: int = 0


def _image_frame_shape(image: FiberTrackingImage) -> Optional[Tuple[int, int]]:
    """
    Return the ``(height, width)`` of the analyzed image, if it is knowable.
    解析対象画像の ``(高さ, 幅)`` を返す（判明する場合）。

    Parameters
    ----------
    image
        Tracking container to read an image array from.
        画像配列を読み取る追跡コンテナ。

    Returns
    -------
    tuple of int or None
        Pixel shape, or ``None`` when the container holds no 2-D array.
        画素単位の形状。2 次元配列を持たないコンテナでは ``None``。

    Notes
    -----
    Every bundle array shares one shape, so any of them answers the question;
    they are tried in turn only because a container may be built with some of
    them missing.
    バンドルの各配列は同一形状なので、どれを見ても答えは同じである。順に試すの
    は、一部の配列を持たないコンテナが構築され得るという理由だけによる。
    """
    for candidate in (image.calibrated_image, image.skeleton_image,
                      image.bp, image.original_image):
        if candidate is None:
            continue
        arr = np.asarray(candidate)
        if arr.ndim == 2 and arr.size:
            return (int(arr.shape[0]), int(arr.shape[1]))
    return None


def _reaches_frame(
    fiber: Fiber,
    frame: Optional[Tuple[int, int]],
) -> bool:
    """
    Report whether a fiber's track reaches the outermost row or column.
    ファイバーのトラックが最外周の行または列に達しているかを返す。

    Parameters
    ----------
    fiber
        Traced fiber with bounding-box-local track arrays.
        外接矩形ローカルのトラック配列を持つ追跡済みファイバー。
    frame
        Image shape from `_image_frame_shape`; ``None`` disables the test.
        `_image_frame_shape` が返した画像形状。``None`` の場合は判定しない。

    Returns
    -------
    bool
        True when the fiber continues beyond the scanned area.
        走査範囲の外へ続いている場合に True。
    """
    if frame is None:
        return False
    height, width = frame
    gx = np.asarray(fiber.xtrack) + fiber.data[0]
    gy = np.asarray(fiber.ytrack) + fiber.data[1]
    if gx.size == 0:
        return False
    return bool(
        gx.min() <= 0 or gy.min() <= 0
        or gx.max() >= width - 1 or gy.max() >= height - 1
    )


def isolated_fiber_flags(
    image: FiberTrackingImage,
    fibers: Sequence[Fiber],
    connect_params: Optional[ConnectParams] = None,
) -> List[bool]:
    """
    Flag which fibers were measured over their whole length.
    全長にわたって計測できたファイバーを判定する。

    A fiber qualifies when all three of these hold: no pixel of its track lies
    within `BRANCH_TOUCH_RADIUS_PX` of a branch point of the source skeleton,
    no pixel of its track reaches the outermost row or column of the image,
    and the reconnection logic finds nothing it could be joined to. Branch
    points are where the skeleton of one fiber meets another, so the first test
    is a direct test of entanglement rather than a proxy for it; the second
    catches a length cut short by the scan boundary; the third catches an end
    the connector can see a continuation past.
    次の 3 条件をすべて満たすとき、そのファイバーを対象とする。追跡画素のいずれ
    もが元の骨格の分岐点から `BRANCH_TOUCH_RADIUS_PX` 以内に無いこと、追跡画素の
    いずれもが画像の最外周の行・列に達していないこと、そして再結合ロジックが連結
    相手を見つけないこと。分岐点は 1 本の骨格が別の骨格と出会う位置なので、第 1 の
    判定は絡まりの代用指標ではなく直接の判定である。第 2 の判定は走査範囲の境界に
    より切り詰められた長さを、第 3 の判定は連結器から見て続きがある端を捉える。

    A fiber that reaches the frame continues outside it, so what was measured
    is the part that happened to fall inside the scan, not the fiber. Nothing
    in the branch-point test catches this: there are no branch points beyond
    the frame, which makes a fiber running off the edge look *more* isolated,
    not less.
    画像の枠に達したファイバーは枠の外へ続いており、計測されたのはたまたま走査
    範囲に入った部分であってファイバーそのものではない。分岐点の判定ではこれを
    捉えられない。枠の外に分岐点は存在しないため、外へ出ていくファイバーほど、
    かえって孤立しているように見えてしまう。

    The whole track is tested, not only its terminals, so the result means the
    same thing with and without fiber connection. A fragment cut at a crossing
    has a terminal at the cut; a fibril reconnected across that crossing has
    interior pixels there instead. Testing terminals alone would call the
    reconnected fibril isolated even though it runs straight through another
    fiber.
    端だけでなくトラック全体を判定するため、ファイバー連結の有無にかかわらず
    結果の意味が変わらない。交差部で切断された断片はその位置に端を持ち、交差を
    越えて再結合されたフィブリルは同じ位置に内部画素を持つ。端だけを見ると、
    他のファイバーを貫通している再結合フィブリルまで孤立と判定してしまう。

    Parameters
    ----------
    image
        Tracking container whose `bp` branch-point mask defines the crossings
        and whose image arrays give the frame the border test uses.
        交差位置を与える `bp` 分岐点マスクと、枠の判定に使う画像配列を持つ追跡
        コンテナ。
    fibers
        Fibers to classify, from either tracing mode.
        判定対象のファイバー列。どちらの追跡モードのものでもよい。
    connect_params
        Thresholds for the connection-candidate test. ``None`` uses
        `ConnectParams` defaults. Pass the same values the connection feature
        is set to, so the filter and the connector agree on what counts as a
        continuation.
        連結候補判定のしきい値。``None`` は `ConnectParams` の既定値を使う。連結
        機能に設定されているものと同じ値を渡すこと。何を「続き」とみなすかについて
        フィルターと連結器の判断を一致させるためである。

    Returns
    -------
    list of bool
        One flag per input fiber, in the same order; True means isolated.
        入力と同順の判定フラグ。True は孤立を意味する。

    Notes
    -----
    A container without a `bp` mask cannot judge entanglement, so no fiber is
    dropped on that ground rather than silently dropping all of them; the
    border test still applies, because it needs only the image shape.
    `bp` マスクを持たないコンテナでは絡まりを判定できないため、その理由でファイ
    バーを除外せず、黙って全件を落とすことを避ける。枠の判定は画像の形状だけを
    必要とするため、この場合も引き続き適用する。

    The frame is the outermost row and column, with no margin. Measured on two
    real scans, the count of fibers reaching the frame was identical for
    margins of 0 through 5 pixels: a fiber that leaves the scan reaches the
    very edge, so a wider margin would only start excluding fibers that merely
    come close.
    枠とは最外周の行と列そのものであり、余白は取らない。実測した 2 枚の走査像で
    は、枠に達するファイバーの本数が余白 0〜5 画素で同一だった。走査範囲から出て
    いくファイバーは最外周まで到達するため、余白を広げても、近づいただけの
    ファイバーを除外し始めるだけである。

    The connection-candidate test is used **only in conjunction with the other
    two, never alone**. On its own it is far looser: on two real scans it
    admitted 51 of 61 and 110 of 136 fibers, against 3 and 13 for the
    branch-point test, because "no candidate found" conflates "this fiber is
    complete" with "the connector could not tell what the continuation was",
    and the second case is common in a dense tangle. What it adds to the
    conjunction is the case the branch-point test misses: an end whose nearest
    branch point sits just outside the touch radius while the connector can
    plainly see the fiber continue past it.
    連結候補の判定は**他の 2 条件と併用する場合に限り**用い、単独では使わない。
    単独ではるかに緩いためである。実測した 2 枚の走査像では、分岐点判定が 3 本・
    13 本を通すのに対し、61 本中 51 本・136 本中 110 本を通した。「候補が見つから
    ない」は「このファイバーは完結している」と「連結器には続きが判断できなかった」
    を混同しており、後者は密に絡んだ領域で頻繁に起こる。この条件が組み合わせに
    加えるのは、分岐点判定が取り逃がす場合である。すなわち、最も近い分岐点が接触
    半径のわずかに外側にありながら、連結器からは続きが明らかに見えている端である。

    Against what the connector actually joined on those two scans, the
    candidate test agreed on 145 of the 146 fragments it extended. The one
    disagreement had no other fragment end within `clusters_range` — its
    nearest was 21.4 px against a 20 px range — so the connector reached it
    from a position that exists only after growth, which an order-independent
    predicate deliberately does not model.
    この 2 枚について、連結器が実際に延長した 146 断片のうち 145 断片で候補判定は
    一致した。唯一相違した 1 件は、`clusters_range` 内に他の断片の端点を持たず
    （最近傍は 20 px の範囲に対して 21.4 px）、連結器は成長後にのみ存在する位置から
    そこへ到達している。順序に依存しない述語は、その状態を意図的に扱わない。
    """
    frame = _image_frame_shape(image)
    # A fiber the connector could extend is not one whose whole length was
    # measured, whatever the crossings and the frame say.
    # 連結器が延長し得るファイバーは、交差や枠の判定がどうであれ、全長を計測できた
    # ファイバーではない。
    has_candidate = connection_candidate_flags(
        image, fibers, connect_params or ConnectParams(),
    )
    bp_mask = np.asarray(image.bp) if image.bp is not None else None
    if bp_mask is None or bp_mask.ndim != 2 or not bp_mask.any():
        return [
            (not _reaches_frame(f, frame)) and (not c)
            for f, c in zip(fibers, has_candidate)
        ]

    by, bx = np.where(bp_mask)
    r = BRANCH_TOUCH_RADIUS_PX
    flags: List[bool] = []
    for f, candidate in zip(fibers, has_candidate):
        # Track arrays are bbox-local; shift by the bbox origin to compare
        # against the whole-image branch-point coordinates.
        # トラック配列は BBox ローカル座標なので、BBox 原点を加えて全体画像上の
        # 分岐点座標と比較する。
        gx = np.asarray(f.xtrack) + f.data[0]
        gy = np.asarray(f.ytrack) + f.data[1]
        # A fiber the connector can extend, or one leaving the scan, is
        # disqualified whatever the crossings say. Both tests are already
        # computed or cheap, so they run before the branch-point search.
        # 連結器が延長し得るファイバー、および走査範囲から出ていくファイバーは、
        # 交差の有無にかかわらず対象外となる。どちらも計算済みまたは軽いので、
        # 分岐点の探索より前に行う。
        if candidate:
            flags.append(False)
            continue
        if _reaches_frame(f, frame):
            flags.append(False)
            continue
        # Restrict to branch points inside the fiber's bounding box (grown by
        # the touch radius) before the pairwise test, so a dense image does not
        # cost len(track) * len(branch points) comparisons per fiber.
        # 総当たり前に、ファイバーの外接矩形（接触半径分だけ拡張）内の分岐点へ
        # 絞り込み、密な画像でファイバーごとに
        # len(トラック) * len(分岐点) 回の比較を行わないようにする。
        near_box = (
            (bx >= gx.min() - r) & (bx <= gx.max() + r)
            & (by >= gy.min() - r) & (by <= gy.max() + r)
        )
        if not near_box.any():
            flags.append(True)
            continue
        cbx, cby = bx[near_box], by[near_box]
        touching = (
            (np.abs(cbx[:, None] - gx[None, :]) <= r)
            & (np.abs(cby[:, None] - gy[None, :]) <= r)
        ).any()
        flags.append(not bool(touching))
    return flags


def fiber_straightness(
    fiber: Fiber,
    x_size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
) -> float:
    """
    Return one fiber's end-to-end distance divided by its contour length.
    1 本のファイバーの端点間距離を輪郭長で割った値を返す。

    Parameters
    ----------
    fiber
        Traced fiber whose track and contour length are read.
        トラックと輪郭長を参照する追跡済みファイバー。
    x_size_per_pixel
        Physical X (column) pixel size in nanometers.
        X（列）方向の物理ピクセルサイズ (nm)。
    y_size_per_pixel
        Physical Y (row) pixel size in nanometers; ``None`` reuses the X size
        for a square pixel grid.
        Y（行）方向の物理ピクセルサイズ (nm)。``None`` のときは正方ピクセル格子
        として X の値を流用する。

    Returns
    -------
    float
        Ratio in [0, 1], or NaN when the contour length is zero. A straight
        fiber gives exactly 1.0, a coiled one approaches 0, and a closed loop
        gives 0.
        [0, 1] の比。輪郭長が 0 の場合は NaN。直線状ならちょうど 1.0、巻き込んだ
        ものほど 0 に近づき、閉ループは 0 になる。

    Notes
    -----
    The numerator is not the Euclidean chord but the length of a digitised
    straight line between the same two endpoints, measured with the same
    corrected chain-code metric as the fiber itself. That metric weights an
    orthogonal step 0.948 and a diagonal one 1.340 to remove the length
    overestimate digitisation produces on generic curves, and it therefore
    reports a perfectly straight track as about 5% shorter than its Euclidean
    chord: measured directly, chord over contour comes to 1.0549 for a
    horizontal or vertical line and 1.0554 for a 45-degree one. Measuring the
    reference line the same way puts a straight fiber at exactly 1.0, which is
    what "straightness" has to mean to be readable.

    The cancellation is exact only when the fiber and its reference line are
    made of the same mix of orthogonal and diagonal steps, which holds for a
    straight fiber and approximately otherwise: a digitised semicircle reads
    0.586 here against 0.637 for the Euclidean chord-over-arc definition. The
    value is a dimensionless shape descriptor for comparing fibers measured
    the same way, not a quantity to compare against a Euclidean ratio computed
    elsewhere.
    分子はユークリッド弦ではなく、同じ 2 端点を結ぶ離散化された直線の長さであり、
    ファイバー自身と同じ補正済みチェーンコード尺度で測る。この尺度は直交ステップ
    に 0.948、斜めステップに 1.340 の重みを与え、一般の曲線で離散化が生む長さの
    過大評価を取り除くため、完全な直線経路をユークリッド弦より約 5% 短く報告
    する。実測では chord / contour が水平・垂直で 1.0549、45 度で 1.0554 になる。
    基準線を同じ方法で測ることで直線状のファイバーがちょうど 1.0 になり、
    「直線度」として読める値になる。

    偏りが完全に相殺されるのは、ファイバーと基準線の直交・斜めステップの構成が
    一致する場合、すなわち直線状のファイバーに限られ、それ以外では近似である。
    離散化した半円はここでは 0.586 となり、ユークリッドの弦/弧による定義の
    0.637 とは異なる。この値は同じ方法で計測したファイバー同士を比較するための
    無次元の形状記述子であり、他所で計算されたユークリッド比と突き合わせる量では
    ない。

    The endpoints are the first and last tracked points, so a fiber cut at a
    crossing is described over the part that was actually traced.
    Bounding-box offsets cancel in the difference and are not needed.
    端点は追跡された最初と最後の点であり、交差で切断されたファイバーは実際に
    追跡された部分について記述される。外接矩形のオフセットは差分で相殺される
    ため不要である。
    """
    length = float(fiber.length)
    if not (length > 0.0):
        return float("nan")
    if y_size_per_pixel is None:
        y_size_per_pixel = x_size_per_pixel

    x0, x1 = int(fiber.xtrack[0]), int(fiber.xtrack[-1])
    y0, y1 = int(fiber.ytrack[0]), int(fiber.ytrack[-1])
    steps = max(abs(x1 - x0), abs(y1 - y0))
    if steps == 0:
        # Both endpoints on one pixel: a closed loop, with no straight-line
        # extent at all.
        # 両端点が同一画素にある閉ループ。直線方向の広がりを持たない。
        return 0.0

    # Sampling at max(|dx|, |dy|) steps makes consecutive rounded points differ
    # by at most one pixel per axis, so the result is an 8-connected line the
    # chain-code metric can measure the same way it measures the fiber.
    # max(|dx|, |dy|) 分割で標本化すると、丸めた連続点は各軸で最大 1 画素しか
    # 違わないため、結果は 8 近傍で連結した直線となり、ファイバーと同じ方法で
    # チェーンコード尺度が測れる。
    t = np.linspace(0.0, 1.0, steps + 1)
    line_x = np.rint(x0 + t * (x1 - x0)).astype(int)
    line_y = np.rint(y0 + t * (y1 - y0)).astype(int)
    straight = float(imp_tools.convert_track_to_distance(
        line_x, line_y, x_size_per_pixel, y_size_per_pixel,
    )[-1])
    return float(straight / length)


def fiber_curvature_profile(
    fiber: Fiber,
    x_size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
    window_nm: float = DEFAULT_CURVATURE_WINDOW_NM,
) -> np.ndarray:
    """
    Return local curvature along one fiber, in radians per micrometer.
    1 本のファイバーに沿った局所曲率 (rad/µm) を返す。

    Parameters
    ----------
    fiber
        Traced fiber whose track and cumulative distance are read.
        トラックと累積距離を参照する追跡済みファイバー。
    x_size_per_pixel
        Physical X (column) pixel size in nanometers.
        X（列）方向の物理ピクセルサイズ (nm)。
    y_size_per_pixel
        Physical Y (row) pixel size in nanometers; ``None`` reuses the X size.
        Y（行）方向の物理ピクセルサイズ (nm)。``None`` のときは X の値を流用。
    window_nm
        Arc length over which the turning angle is measured.
        回転角を測る弧長。

    Returns
    -------
    ndarray
        One curvature per interior point that has a full window on both
        sides; empty when the fiber is shorter than the window.
        両側に完全な窓を確保できる内部点ごとに 1 つの曲率。ファイバーが窓より
        短い場合は空。

    Notes
    -----
    Curvature has to be measured over a window, not between neighbouring
    pixels. A skeleton step is either orthogonal or diagonal, so the turning
    angle between consecutive steps can only be a multiple of 45 degrees:
    at the pixel scale the estimate is pure digitisation noise regardless of
    the fiber's real shape. Taking the directions of two chords that span
    ``window_nm`` of arc reduces that quantisation in proportion to the number
    of pixels each chord covers.
    曲率は隣接画素間ではなく窓幅にわたって測る必要がある。骨格のステップは直交か
    斜めのいずれかであり、連続するステップ間の回転角は 45 度の倍数にしかならない。
    つまり画素スケールでの推定は、ファイバーの実際の形状によらず離散化ノイズその
    ものになる。``window_nm`` の弧長を張る 2 つの弦の方向を使えば、各弦が覆う画素
    数に比例して量子化が減る。

    The window is given in nanometers rather than pixels so the same setting
    means the same physical smoothing on scans of different sizes.
    窓幅は画素ではなく nm で指定する。走査範囲の異なる画像でも、同じ設定が同じ
    物理的な平滑化を意味するようにするためである。
    """
    if y_size_per_pixel is None:
        y_size_per_pixel = x_size_per_pixel

    horizon = np.asarray(fiber.horizon, dtype=float)
    if horizon.size < 3 or float(horizon[-1]) < window_nm:
        return np.empty(0, dtype=float)

    xs = np.asarray(fiber.xtrack, dtype=float) * x_size_per_pixel
    ys = np.asarray(fiber.ytrack, dtype=float) * y_size_per_pixel
    half = window_nm / 2.0

    # searchsorted finds each point's window ends in one pass; the arc length
    # is read back from `horizon` instead of assumed, because the two chords
    # rarely land exactly on the requested half-window.
    # searchsorted で各点の窓端を一括で求める。弧長は仮定せず `horizon` から
    # 読み戻す。2 つの弦が要求した半窓にちょうど収まることはまれなためである。
    before = np.searchsorted(horizon, horizon - half, side="left")
    after = np.searchsorted(horizon, horizon + half, side="left")
    valid = (before >= 0) & (after < horizon.size) & (after > before)
    valid &= (horizon - horizon[np.clip(before, 0, horizon.size - 1)] >= half * 0.5)
    if not valid.any():
        return np.empty(0, dtype=float)
    # The turning angle itself is exact on a digitised arc (measured: 0.0%
    # error), so the residual bias of this estimator lives entirely in the
    # denominator: the corrected chain-code metric over-measures a strongly
    # curved digitised path, by 15-21% at 1.5 rad of total turn and 0.8% at
    # 0.15 rad. Curvature therefore reads low in proportion to how tightly the
    # fiber bends, consistently enough for comparison but not as an absolute.
    # 回転角そのものは離散化された円弧に対して厳密である（実測誤差 0.0%）。
    # したがってこの推定量に残る偏りは全て分母にある。補正済みチェーンコード尺度
    # は強く曲がった離散化経路を過大に測り、総回転角 1.5 rad で +15〜21%、
    # 0.15 rad で +0.8% になる。よって曲率はファイバーの曲がりが急なほど低く出る。
    # 比較には十分一貫しているが、絶対値としては扱えない。

    i = np.nonzero(valid)[0]
    j = before[i]
    k = after[i]

    angle_in = np.arctan2(ys[i] - ys[j], xs[i] - xs[j])
    angle_out = np.arctan2(ys[k] - ys[i], xs[k] - xs[i])
    # Wrap into (-pi, pi] so a turn through the +-pi seam is small, not huge.
    # (-pi, pi] へ折り返す。±pi の継ぎ目をまたぐ回転が巨大な値にならないように
    # するため。
    turn = np.abs((angle_out - angle_in + np.pi) % (2.0 * np.pi) - np.pi)
    # The direction of a chord over a sub-arc is the tangent direction at that
    # sub-arc's midpoint, so the two chord directions are separated by half the
    # window, not the whole of it. Dividing by the full arc would report half
    # the true curvature: measured against digitised circles of known radius,
    # the uncorrected form came out 57% low at every radius and window.
    # 部分弧に張る弦の方向は、その部分弧の中点における接線方向に等しい。したがって
    # 2 つの弦方向の間隔は窓全体ではなくその半分である。弧全体で割ると真の曲率の
    # 半分を報告してしまう。既知半径の離散化円で測ったところ、未補正の式は
    # あらゆる半径・窓幅で 57% 低い値を返した。
    arc = (horizon[k] - horizon[j]) / 2.0
    good = arc > 0.0
    return (turn[good] / arc[good]) * 1000.0


def fiber_mean_curvature(
    fiber: Fiber,
    x_size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
    window_nm: float = DEFAULT_CURVATURE_WINDOW_NM,
) -> float:
    """
    Return one fiber's mean curvature, in radians per micrometer.
    1 本のファイバーの平均曲率 (rad/µm) を返す。

    Parameters
    ----------
    fiber
        Traced fiber to measure.
        計測対象の追跡済みファイバー。
    x_size_per_pixel
        Physical X (column) pixel size in nanometers.
        X（列）方向の物理ピクセルサイズ (nm)。
    y_size_per_pixel
        Physical Y (row) pixel size in nanometers; ``None`` reuses the X size.
        Y（行）方向の物理ピクセルサイズ (nm)。``None`` のときは X の値を流用。
    window_nm
        Arc length the curvature estimator turns over.
        曲率推定が回転角を測る弧長。

    Returns
    -------
    float
        Mean of the curvature profile, or NaN for a fiber shorter than the
        window.
        曲率プロファイルの平均。窓より短いファイバーでは NaN。

    Notes
    -----
    NaN rather than 0.0 for a fiber the window cannot span, so a caller can
    report it as unmeasured instead of counting it as perfectly straight.
    窓が張れないファイバーは 0.0 ではなく NaN とする。呼び出し側が、完全な直線と
    数えるのではなく未計測として報告できるようにするためである。

    This is the single definition of "the curvature of a fiber": GUI04's fiber
    table and `collect_fiber_curvature` both call it, so a value inspected
    beside the fiber image is the same value GUI03 histograms.
    これが「ファイバーの曲率」の唯一の定義である。GUI04 の一覧テーブルと
    `collect_fiber_curvature` の双方がこれを呼ぶため、ファイバー画像の横で確認した
    値は GUI03 がヒストグラム化する値と同一になる。
    """
    profile = fiber_curvature_profile(
        fiber, x_size_per_pixel, y_size_per_pixel, window_nm=window_nm,
    )
    return float(np.mean(profile)) if profile.size else float("nan")


def compute_fiber_stats(
    fibers: Sequence[Fiber],
    x_size_per_pixel: Optional[float] = None,
    y_size_per_pixel: Optional[float] = None,
) -> List[FiberStats]:
    """
    Compute summary statistics for each fiber.
    各ファイバーの要約統計値を計算する。

    Parameters
    ----------
    fibers
        Fibers produced by `FiberTrackingImage`.
        `FiberTrackingImage` が生成したファイバー列。
    x_size_per_pixel
        Physical X pixel size in nanometers. Straightness needs it to measure
        the chord in the same units as the contour length; without it that
        one field is NaN and every other statistic is unaffected.
        X 方向の物理ピクセルサイズ (nm)。直線度は弦を輪郭長と同じ単位で測るため
        これを必要とする。与えない場合はその項目のみ NaN となり、他の統計値は
        影響を受けない。
    y_size_per_pixel
        Physical Y pixel size in nanometers; ``None`` reuses the X size.
        Y 方向の物理ピクセルサイズ (nm)。``None`` のときは X の値を流用する。

    Returns
    -------
    list of FiberStats
        One entry per input fiber, in the same order.
        入力ファイバーと同順の統計値リスト。
    """
    stats = []
    for i, f in enumerate(fibers):
        med = float(np.median(f.height)) if len(f.height) > 0 else 0.0
        mx = float(np.max(f.height)) if len(f.height) > 0 else 0.0
        angles = tuple(float(np.degrees(a)) for a in f.kink_angles)
        straightness = (
            float("nan") if x_size_per_pixel is None
            else fiber_straightness(f, x_size_per_pixel, y_size_per_pixel)
        )
        stats.append(FiberStats(
            index=i,
            length_nm=float(f.length),
            height_median_nm=med,
            height_max_nm=mx,
            ep_count=len(f.ep_indices),
            kink_count=len(f.kink_indices),
            kink_angles_deg=angles,
            straightness=straightness,
        ))
    return stats


def fiber_kink_angle(stat: FiberStats) -> float:
    """
    Return one fiber's representative kink angle, in degrees.
    1 本のファイバーを代表するキンク角 (degree) を返す。

    Parameters
    ----------
    stat
        Per-fiber statistics row.
        ファイバー単位の統計行。

    Returns
    -------
    float
        Median of the fiber's kink angles, or NaN when it has no kink.
        そのファイバーのキンク角の中央値。キンクが無い場合は NaN。

    Notes
    -----
    The median makes one fiber contribute exactly one value however many kinks
    it carries, so a heavily kinked fiber does not outweigh the rest.
    中央値を使うことで、キンクの本数によらず 1 本のファイバーが 1 つの値を出す。
    キンクの多いファイバーが他を圧倒しないようにするためである。

    A fiber with no kink is NaN rather than 0: an undetected kink is not a
    measured angle of zero, and averaging it in would pull the population
    toward a value no fiber has.
    キンクの無いファイバーは 0 ではなく NaN とする。キンクが検出されなかったこと
    は「0 度のキンクを計測した」ことではなく、平均に混ぜるとどのファイバーも
    持たない値へ母集団を引っ張ってしまう。
    """
    if not stat.kink_angles_deg:
        return float("nan")
    return float(np.median(stat.kink_angles_deg))


def fiber_kink_density(stat: FiberStats) -> float:
    """
    Return one fiber's kink density, in kinks per micrometer of contour.
    1 本のファイバーのキンク密度（輪郭長 1 µm あたりのキンク数）を返す。

    Parameters
    ----------
    stat
        Per-fiber statistics row.
        ファイバー単位の統計行。

    Returns
    -------
    float
        Kinks per micrometer, or NaN when the contour length is unusable.
        1 µm あたりのキンク数。輪郭長が使えない場合は NaN。

    Notes
    -----
    Normalising by length is what makes fibers of different length
    comparable; a raw kink count rises with length alone.
    長さで正規化することが、長さの異なるファイバーを比較可能にする。素のキンク数
    は長さだけでも増えてしまう。

    Unlike `fiber_kink_angle`, a fiber with no kink is a valid zero here: zero
    kinks over a measured length is a real density, not a missing measurement.
    `fiber_kink_angle` と異なり、ここではキンクの無いファイバーは有効な 0 である。
    計測済みの長さに対してキンク 0 本というのは実在の密度であり、欠測ではない。
    """
    length_um = float(stat.length_nm) / 1000.0
    if length_um <= 0.0:
        return float("nan")
    return float(stat.kink_count) / length_um


def _load_validated_arrays(bundle_path: str, keys: List[str]) -> Dict[str, np.ndarray]:
    """
    Load bundle keys and enforce the ``.b2z`` contract before use.
    バンドルキーを読み込み、使用前に ``.b2z`` 契約を強制する。

    Validation here converts malformed bundles into one clear error at the
    load boundary instead of cryptic NumPy failures inside fiber tracking.
    The format version recorded in vlmeta is checked as well, so bundles
    written by an incompatible future release are rejected explicitly.
    ここで検証することで、不正なバンドルはファイバー追跡内部での不可解な
    NumPy エラーではなく、読み込み境界での明確なエラー 1 件になる。vlmeta に
    記録された形式バージョンも照合し、非互換な将来リリースが書いたバンドルを
    明示的に拒否する。

    Raises
    ------
    ValueError
        If the loaded arrays or the recorded format version violate the
        bundle contract, or if the bundle metadata cannot be read.
    """
    arrays = load_bundle(bundle_path, keys=keys)
    # A bundle without metadata legitimately yields an empty dict (bundles
    # from old releases lack vlmeta). A read failure here means corruption,
    # so it becomes a loud contract error instead of silently skipping the
    # format-version check.
    # メタデータの無いバンドル（旧リリース製）は正常に空辞書になる。ここでの
    # 読み込み失敗は破損を意味するため、形式バージョン検査を黙ってスキップ
    # せず、明示的な契約エラーにする。
    try:
        meta = load_bundle_meta(bundle_path)
    except Exception as e:
        raise ValueError(
            f"unreadable bundle metadata in {os.path.basename(bundle_path)}: "
            f"{type(e).__name__}: {e}"
        ) from e
    problems = validate_bundle(arrays, meta=meta, require=keys)
    if problems:
        raise ValueError(
            f"bundle contract violation in {os.path.basename(bundle_path)}: "
            + "; ".join(problems)
        )
    return arrays


def _tracking_image_from_arrays(
    name: str,
    data: Dict[str, np.ndarray],
    size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
) -> FiberTrackingImage:
    """
    Assemble a `FiberTrackingImage` from already-loaded bundle arrays.
    読み込み済みのバンドル配列から `FiberTrackingImage` を組み立てる。

    Used by both `load_tracking_image` and `measure_bundle` so the bundle is
    read from disk only once per call path. ``size_per_pixel`` is the X (column)
    pixel size; ``y_size_per_pixel`` is the Y (row) pixel size and defaults to
    the X value for an isotropic (square-pixel) scale.
    `load_tracking_image` と `measure_bundle` の両方から使い、各呼び出し経路で
    バンドルのディスク読み込みを 1 回に抑える。``size_per_pixel`` は X（列）軸、
    ``y_size_per_pixel`` は Y（行）軸のピクセルサイズで、省略時は X 値を流用して
    等方（正方ピクセル）スケールとする。
    """
    cal = data["calibrated"]
    skl = data["skeletonized"].astype(np.uint8)
    bp = data["bp"].astype(np.uint8)
    ep = data["ep"].astype(np.uint8)
    kp = data["kp"]   # shape (2, N)
    dp = data["dp"]   # shape (2, N)
    ka = data["ka"]   # shape (N,), radians

    image = FiberTrackingImage(
        original_AFM=cal,
        name=name,
        size_per_pixel=size_per_pixel,
        y_size_per_pixel=y_size_per_pixel,
    )
    # Assign GUI01 analysis outputs directly; no lib processing module is rerun.
    # GUI01 の解析結果を属性へ直接代入する。lib の処理モジュールは再実行しない。
    image.calibrated_image = cal
    image.skeleton_image = skl
    image.bp = bp
    image.ep = ep
    image.all_kink_coordinates = (kp[0], kp[1])
    image.decomposed_point_coordinates = dp
    image.all_kink_angles = ka
    return image


def load_tracking_image(
    bundle_path: str,
    size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
) -> FiberTrackingImage:
    """
    Rebuild a `FiberTrackingImage` from a GUI01 ``.b2z`` bundle.
    GUI01 が保存した ``.b2z`` バンドルから `FiberTrackingImage` を再構築する。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。
    size_per_pixel
        Physical X (column) pixel size in nanometers used for fiber-length
        calculations.
        ファイバー長さ計算に使う X（列）軸の物理ピクセルサイズ (nm/px)。
    y_size_per_pixel
        Physical Y (row) pixel size in nanometers. ``None`` reuses
        ``size_per_pixel`` for an isotropic (square-pixel) scale.
        Y（行）軸の物理ピクセルサイズ (nm/px)。``None`` のときは
        ``size_per_pixel`` を流用し等方（正方ピクセル）スケールとする。

    Returns
    -------
    FiberTrackingImage
        Reconstructed object populated with GUI01 analysis outputs.
        GUI01 の解析結果を設定した再構築済みオブジェクト。

    Raises
    ------
    ValueError
        If the bundle violates the ``.b2z`` contract (see
        `lib.bundle_schema.validate_bundle`).
    """
    # Load all required bundle keys in one call so the dataset is reconstructed atomically.
    # データセットを一貫して再構築できるよう、必要キーを 1 回でまとめて読み込む。
    data = _load_validated_arrays(bundle_path, TRACKING_BUNDLE_KEYS)
    name = os.path.splitext(os.path.basename(bundle_path))[0]
    return _tracking_image_from_arrays(name, data, size_per_pixel, y_size_per_pixel)


def read_scan_size_from_bundle(
    bundle_path: str,
) -> Optional[Tuple[float, float]]:
    """
    Read the recorded scan size ``(x_um, y_um)`` from a bundle, if present.
    バンドルに記録された走査範囲 ``(x_um, y_um)`` を読み取る（記録があれば）。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。

    Returns
    -------
    tuple of float or None
        Per-axis scan size in micrometers, or ``None`` when the bundle stores
        no valid spatial calibration (e.g. bundles written before the scan
        size was added to the contract).
        軸ごとの走査範囲 (µm)。有効な空間較正が無ければ ``None``（走査範囲が
        契約へ追加される前に書かれたバンドル等）。
    """
    return scan_size_um_from_meta(load_bundle_meta(bundle_path))


def curate_fibers(
    image: FiberTrackingImage,
    fragments: Sequence[Fiber],
    exclude_anchors: Sequence[Tuple[int, int]] = (),
    connect_fibers: bool = False,
    connect_params: Optional[ConnectParams] = None,
) -> MeasureResult:
    """
    Build the measured population from traced skeleton fragments.
    追跡済みの骨格断片から、計測対象の母集団を組み立てる。

    Parameters
    ----------
    image
        Tracking container the fragments were traced from, carrying the
        resolved per-axis pixel size used for the statistics.
        断片の追跡元となった追跡コンテナ。統計計算に使う軸別ピクセルサイズを
        確定済みで保持する。
    fragments
        Traced skeleton fragments, before any curation is applied.
        キュレーション適用前の追跡済み骨格断片。
    exclude_anchors
        Anchor pixels of manually excluded fibers, as recorded by
        `lib.fiber_selection`. Empty means nothing was excluded.
        `lib.fiber_selection` が記録した、手動除外ファイバーのアンカー画素。
        空の場合は除外なしを意味する。
    connect_fibers
        Whether to reconnect the surviving fragments into whole fibrils.
        残った断片を 1 本のフィブリルへ再結合するかどうか。
    connect_params
        Reconnection thresholds; ``None`` uses `ConnectParams` defaults.
        再結合のしきい値。``None`` は `ConnectParams` の既定値を使う。

    Returns
    -------
    MeasureResult
        Curated population and its statistics, carrying `fragments` through
        unchanged.
        キュレーション済みの母集団と統計値。`fragments` はそのまま引き継ぐ。

    Notes
    -----
    Exclusions are applied **before** reconnection, and this function is the
    only place that decides that order. An exclusion states that an object is
    not a fiber at all — debris, a scan-line artifact — so the connector must
    never see it. Applied the other way round, a fibril is discarded whenever
    it happens to have absorbed an excluded fragment, taking the real fiber
    that fragment was joined to with it: on a test scan, excluding five
    debris fragments discarded close to four times their total contour length
    in fibrils.
    除外は再結合の**前**に適用し、その順序を決めるのは本関数だけである。除外
    とは「この対象はそもそもファイバーではない（ゴミ、走査線アーティファクト）」
    という表明であり、連結器がそれを見てはならない。逆順で適用すると、除外され
    た断片を取り込んだフィブリルが丸ごと捨てられ、その断片が繋がっていた実在の
    ファイバーまで巻き添えで失われる。あるテスト画像では、ゴミ断片 5 本の除外に
    より、その輪郭長合計の 4 倍近い長さのフィブリルが失われた。

    The height filter deliberately keeps the opposite order — connect, then
    filter, see `lib.fiber_connector.filter_fibers_by_height` — because it
    selects a height band *inside* a real fibril, which only has a meaning
    once the fibril is whole.
    高さフィルターは意図的に逆の順序（連結してからフィルター、
    `lib.fiber_connector.filter_fibers_by_height` 参照）を保つ。実在する
    フィブリルの*内部*で高さ帯を選ぶ操作であり、フィブリルが 1 本に揃って初めて
    意味を持つためである。
    """
    fibers = list(fragments)
    if len(exclude_anchors) > 0:
        drop = excluded_flags(fibers, exclude_anchors)
        fibers = [f for f, d in zip(fibers, drop) if not d]
    curated_count = len(fibers)
    if connect_fibers:
        fibers = connect_fiber_fragments(
            image, fibers, params=connect_params or ConnectParams(),
        )
    return MeasureResult(
        image=image,
        fibers=fibers,
        stats=compute_fiber_stats(
            fibers, image.size_per_pixel, image.y_size_per_pixel,
        ),
        fragments=list(fragments),
        curated_count=curated_count,
    )


def measure_bundle(
    bundle_path: str,
    scale_um: Optional[float] = None,
    max_workers: Optional[int] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    scale_y_um: Optional[float] = None,
    connect_fibers: bool = False,
    connect_params: Optional[ConnectParams] = None,
    exclude_anchors: Sequence[Tuple[int, int]] = (),
) -> MeasureResult:
    """
    Trace all fibers in one bundle and compute their statistics.
    1 つのバンドル内の全ファイバーを追跡し、統計値を計算する。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。
    scale_um
        Full physical width of the raw scan along the X (column) axis in
        micrometers. The X pixel size is ``scale_um * 1000 / (width_px + 1)``
        because the analysis arrays are cropped by one column relative to the
        raw scan (see the pixel-size note in the function body). When
        ``None``, the scan size recorded in the bundle
        (``spatial_calibration``) supplies both axes. A ``ValueError`` is
        raised if neither an explicit value nor a recorded scan size is
        available.
        X（列）軸方向の生スキャン全体の物理幅 (µm)。解析配列は生スキャンより
        1 列クロップされているため、X のピクセルサイズは
        ``scale_um * 1000 / (横px + 1)``（関数本体のピクセルサイズ注記参照）。
        ``None`` のときはバンドルに記録された走査範囲
        （``spatial_calibration``）が両軸を供給する。明示値も記録値も
        無い場合は ``ValueError`` を送出する。
    max_workers
        Maximum number of worker threads for parallel fiber tracing.
        並列ファイバー追跡に使うワーカースレッドの最大数。
    progress_cb
        Progress callback receiving ``(done, total)`` per traced fiber.
        ファイバー 1 本完了ごとに ``(done, total)`` を受け取る進捗コールバック。
    scale_y_um
        Full physical height of the raw scan along the Y (row) axis in
        micrometers. The Y pixel size is
        ``scale_y_um * 1000 / (height_px + 1)``, mirroring the one-row crop
        of the analysis arrays. When ``None`` it defaults to the recorded Y
        scan size (if ``scale_um`` is also ``None``) or to ``scale_um``
        otherwise, keeping the historical single-value (square-scan)
        behavior. Pass a distinct value for rectangular scans.
        Y（行）軸方向の生スキャン全体の物理高さ (µm)。解析配列の 1 行クロップに
        対応して、Y のピクセルサイズは ``scale_y_um * 1000 / (縦px + 1)``。
        ``None`` のときは（``scale_um`` も
        ``None`` なら）記録された Y 走査範囲、そうでなければ ``scale_um`` を
        既定値とし、従来の単一値（正方スキャン）挙動を保つ。矩形スキャンでは
        別の値を渡す。
    connect_fibers
        When ``True``, reconnect the traced skeleton fragments into whole
        fibrils with `lib.fiber_connector.connect_fiber_fragments` before
        computing statistics. Fragments that GUI01 split at crossings and
        branches are then measured as single fibers. Defaults to ``False``
        (each skeleton fragment is one fiber, the historical behavior).
        ``True`` のとき、統計計算の前に、追跡した骨格断片を
        `lib.fiber_connector.connect_fiber_fragments` で 1 本のフィブリルへ
        再結合する。GUI01 が交差・分岐で分断した断片が 1 本の繊維として計測
        される。既定は ``False``（各骨格断片が 1 本の繊維、従来挙動）。
    connect_params
        Reconnection thresholds used when ``connect_fibers`` is ``True``.
        ``None`` uses `ConnectParams` defaults.
        ``connect_fibers`` が ``True`` のときに使う再結合しきい値。``None`` は
        `ConnectParams` の既定値を使う。
    exclude_anchors
        Anchor pixels of manually excluded fibers, applied to the traced
        fragments **before** reconnection (see `curate_fibers`). Defaults to
        empty, so a bundle measures exactly as it did before unless the
        caller asks for curation.
        手動除外ファイバーのアンカー画素。再結合の**前**に、追跡済み断片へ
        適用する（`curate_fibers` 参照）。既定は空で、呼び出し側がキュレーション
        を要求しない限り、従来と全く同じ計測結果になる。

    Returns
    -------
    MeasureResult
        Rebuilt image, traced (optionally curated and reconnected) fibers,
        per-fiber statistics, and the uncurated fragments.
        再構築済み画像、追跡（必要に応じてキュレーション・再結合）されたファイバー、
        ファイバーごとの統計値、およびキュレーション前の断片。

    Raises
    ------
    ValueError
        If `scale_um` is ``None`` and the bundle records no scan size, if a
        resolved scale is not a positive number, or if the bundle violates
        the ``.b2z`` contract (see `lib.bundle_schema.validate_bundle`).

    Notes
    -----
    Pixel size is resolved per axis (X from image width, Y from image height)
    so rectangular fields of view and non-square pixel grids are measured
    correctly. Square scans on square pixel grids are unchanged.
    ピクセルサイズは軸ごと（X は画像の幅、Y は画像の高さ）に解決するため、
    矩形視野や非正方ピクセル格子も正しく測れる。正方ピクセル格子の正方スキャンの
    結果は変わらない。
    """
    if scale_um is None:
        recorded = read_scan_size_from_bundle(bundle_path)
        if recorded is None:
            raise ValueError(
                "scale_um is None and the bundle records no scan size; "
                "pass scale_um explicitly or re-process the input so its "
                "scan size is stored in the bundle"
            )
        scale_um = recorded[0]
        if scale_y_um is None:
            scale_y_um = recorded[1]

    # A single value means a square scan, so Y reuses the X scale.
    # 単一値は正方スキャンを意味するため、Y は X のスケールを流用する。
    if scale_y_um is None:
        scale_y_um = scale_um

    if not (scale_um > 0):
        raise ValueError(f"scale_um must be a positive number, got {scale_um!r}")
    if not (scale_y_um > 0):
        raise ValueError(
            f"scale_y_um must be a positive number, got {scale_y_um!r}"
        )

    data = _load_validated_arrays(bundle_path, TRACKING_BUNDLE_KEYS)
    height_px, width_px = data["calibrated"].shape
    # Per-axis pixel size: X spans the columns (width), Y spans the rows
    # (height), matching the bundle coordinate convention (x=column, y=row).
    # The scan size describes the raw scan, but BGCalibrator crops every
    # analysis array by one row and one column (``original[1:, 1:]``), so the
    # raw pixel count is the bundle shape plus one. Dividing by the cropped
    # shape would inflate every length by width/(width-1) (~0.2% at 512 px).
    # 軸別ピクセルサイズ：X は列（幅）、Y は行（高さ）に対応し、バンドルの
    # 座標規約（x=列, y=行）に一致する。走査範囲は生スキャン全体の寸法だが、
    # BGCalibrator は解析配列を 1 行・1 列クロップする（``original[1:, 1:]``）
    # ため、生スキャンの画素数はバンドル形状 +1 になる。クロップ後の形状で
    # 割ると全長さが width/(width-1) 倍（512 px で約 +0.2%）に膨らむ。
    x_size_per_pixel = scale_um * 1000.0 / (width_px + 1)
    y_size_per_pixel = scale_y_um * 1000.0 / (height_px + 1)

    name = os.path.splitext(os.path.basename(bundle_path))[0]
    image = _tracking_image_from_arrays(
        name, data, x_size_per_pixel, y_size_per_pixel,
    )
    fragments = image.fibers_in_image_parallel(
        max_workers=max_workers,
        progress_cb=progress_cb,
    )
    # Curation and reconnection both run after fragment tracing, and their
    # order is owned by `curate_fibers`.
    # キュレーションと再結合はいずれも断片追跡の後に実行し、その順序は
    # `curate_fibers` が一元的に決める。
    return curate_fibers(
        image,
        fragments,
        exclude_anchors=exclude_anchors,
        connect_fibers=connect_fibers,
        connect_params=connect_params,
    )


def _exclusion_anchors(bundle_path: str) -> List[Tuple[int, int]]:
    """
    Read the anchor pixels from a bundle's manual exclusion sidecar.
    バンドルの手動除外サイドカーからアンカー画素を読み出す。

    Parameters
    ----------
    bundle_path
        Bundle whose sidecar is consulted.
        サイドカーを参照するバンドル。

    Returns
    -------
    list of tuple of int
        ``(x, y)`` anchors in input order; empty when no sidecar exists.
        入力順の ``(x, y)`` アンカー列。サイドカーが無ければ空。

    Notes
    -----
    The anchors are handed to `measure_bundle` rather than applied to the
    measured fibers here, so exclusions reach the fragments before
    reconnection; `curate_fibers` documents why that order matters.
    アンカーはここで計測済みファイバーへ適用せず `measure_bundle` へ渡す。
    これにより除外は再結合より前に断片へ届く。その順序が重要な理由は
    `curate_fibers` に記載している。
    """
    records = load_exclusions(exclusion_path_for(bundle_path))
    return [(int(r["x"]), int(r["y"])) for r in records]


def collect_fiber_stats(
    bundle_paths: Sequence[str],
    scale_um: Optional[float] = None,
    scale_y_um: Optional[float] = None,
    max_workers: Optional[int] = None,
    apply_exclusions: bool = False,
) -> Tuple[List[Tuple[str, List[FiberStats]]], List[Tuple[str, str]]]:
    """
    Measure several ``.b2z`` bundles and return per-fiber statistics per bundle.
    複数の ``.b2z`` バンドルを計測し、バンドルごとのファイバー統計値を返す。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles containing the tracking keys.
        追跡用キーを含む ``.b2z`` バンドルのパス。
    scale_um
        X-axis scan size in micrometers, forwarded to `measure_bundle`.
        ``None`` lets each bundle supply its own recorded scan size, so a
        folder of differently sized scans measures correctly in one call.
        `measure_bundle` へ渡す X 軸走査範囲 (µm)。``None`` のとき各バンドルが
        自身の記録済み走査範囲を使うため、寸法の異なるスキャンが混在する
        フォルダも 1 回の呼び出しで正しく計測できる。
    scale_y_um
        Y-axis scan size in micrometers, forwarded to `measure_bundle`.
        `measure_bundle` へ渡す Y 軸走査範囲 (µm)。
    max_workers
        Maximum number of worker threads used per bundle.
        1 バンドルあたりの並列追跡ワーカースレッド数の上限。
    apply_exclusions
        When ``True``, drop the fibers each bundle's
        ``<stem>_excluded.json`` sidecar marks as manually excluded. Defaults
        to ``False`` so an existing sidecar cannot silently change what
        `cli.py measure` reports for a bundle it was not asked to curate.
        ``True`` のとき、各バンドルの ``<stem>_excluded.json`` サイドカーが
        手動除外として記録しているファイバーを取り除く。既定は ``False``。
        キュレーションを指示されていないバンドルについて、既存のサイドカーが
        `cli.py measure` の報告内容を黙って変えてしまわないようにするため。

    Returns
    -------
    tuple
        ``(per_bundle, errors)``. `per_bundle` lists ``(bundle_path, stats)``
        pairs in input order for every bundle that measured successfully;
        `errors` lists ``(bundle_path, message)`` pairs for the others, with
        fixed English messages.
        ``(per_bundle, errors)``。`per_bundle` は計測に成功したバンドルの
        ``(バンドルパス, 統計値リスト)`` を入力順に並べたもの。`errors` は
        失敗したバンドルの ``(バンドルパス, メッセージ)`` で、メッセージは
        固定の英語文字列。

    Notes
    -----
    This is the per-fiber counterpart of `skeleton_height_values` and shares
    its failure contract: one unreadable or uncalibrated bundle becomes an
    error entry instead of aborting the collection, so a grouped GUI run
    degrades gracefully. Bundles are kept separate in the result because the
    caller decides whether one sample is one fiber or one image; pooling them
    here would destroy that distinction.
    本関数は `skeleton_height_values` のファイバー単位版で、失敗時の契約も
    共通である。読み込めない、あるいは走査範囲が未記録のバンドル 1 つで収集
    全体を中断せず、エラー項目として返すため、グループ実行が部分的な失敗に
    耐えられる。結果をバンドルごとに分けたまま返すのは、1 標本をファイバー
    1 本とするか画像 1 枚とするかを呼び出し側が決めるためで、ここで併合すると
    その区別が失われる。
    """
    per_bundle: List[Tuple[str, List[FiberStats]]] = []
    errors: List[Tuple[str, str]] = []
    for path in bundle_paths:
        # Exclusions go in as anchors so `measure_bundle` applies them to the
        # fragments; statistics then come back already renumbered over the
        # retained fibers, exactly as GUI04's export does.
        # 除外はアンカーとして渡し、`measure_bundle` が断片へ適用する。統計値は
        # 残ったファイバーで採番し直された状態で返るため、GUI04 の出力と一致する。
        try:
            anchors = _exclusion_anchors(path) if apply_exclusions else ()
            result = measure_bundle(
                path,
                scale_um=scale_um,
                scale_y_um=scale_y_um,
                max_workers=max_workers,
                exclude_anchors=anchors,
            )
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            continue

        per_bundle.append((path, list(result.stats)))
    return per_bundle, errors


def contour_length_weights(horizon: np.ndarray) -> np.ndarray:
    """
    Return the contour length each tracked point represents, in nanometers.
    追跡点 1 点が代表する輪郭長 (nm) を返す。

    Parameters
    ----------
    horizon
        Cumulative distance along one fiber's skeleton path, as stored in
        `lib.fiber.Fiber.horizon`.
        1 本のファイバーの骨格経路に沿った累積距離。`lib.fiber.Fiber.horizon`
        に格納されているもの。

    Returns
    -------
    ndarray
        Per-point weights summing to the fiber's total length. A fiber of a
        single point represents no contour length and gets weight zero.
        合計がファイバー全長に一致する点ごとの重み。1 点だけのファイバーは
        輪郭長を持たないため重み 0 になる。

    Notes
    -----
    Each point takes half of the step on either side of it, so the weights
    sum exactly to `horizon[-1] - horizon[0]`. Weighting by these instead of
    counting points equally matters twice over. Within one image the skeleton
    alternates orthogonal and diagonal steps, whose corrected chain-code
    lengths differ by a factor of about 1.41, so counting points
    under-represents the diagonal runs. Across images the pixel size differs
    with the scan size, so a finely sampled scan contributes more points per
    micrometer of fiber and would dominate a pooled distribution. Length
    weighting removes both biases and makes the distribution scale-invariant:
    it describes the fraction of observed contour length at each value rather
    than the fraction of sampled points.
    各点は前後のステップの半分ずつを受け取るため、重みの合計はちょうど
    `horizon[-1] - horizon[0]` になる。点を等しく数える代わりにこの重みを使う
    ことには 2 つの意味がある。1 枚の画像内では骨格が直交ステップと斜めステップ
    を混在させ、補正済みチェーンコード長は約 1.41 倍異なるため、点を数えると
    斜め区間が過小評価される。画像間では走査範囲に応じてピクセルサイズが変わり、
    細かくサンプリングされた画像ほどファイバー 1 µm あたりの点数が多くなって
    集約分布を支配してしまう。長さ重み付けは両方の偏りを取り除き、分布を
    スケール不変にする。すなわち「サンプル点のうちの割合」ではなく「観測した
    輪郭長のうちの割合」を表すようになる。
    """
    horizon = np.asarray(horizon, dtype=float)
    if horizon.size < 2:
        return np.zeros(horizon.shape, dtype=float)
    steps = np.diff(horizon)
    weights = np.empty(horizon.shape, dtype=float)
    weights[0] = steps[0] / 2.0
    weights[-1] = steps[-1] / 2.0
    weights[1:-1] = (steps[:-1] + steps[1:]) / 2.0
    return weights


def collect_skeleton_height_profiles(
    bundle_paths: Sequence[str],
    scale_um: Optional[float] = None,
    scale_y_um: Optional[float] = None,
    max_workers: Optional[int] = None,
    apply_exclusions: bool = False,
) -> Tuple[List[Tuple[str, np.ndarray, np.ndarray]], List[Tuple[str, str]]]:
    """
    Collect tracked height profiles and their contour length weights.
    追跡された高さプロファイルと、その輪郭長重みを収集する。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles containing the tracking keys.
        追跡用キーを含む ``.b2z`` バンドルのパス。
    scale_um
        X-axis scan size in micrometers, forwarded to `measure_bundle`.
        `measure_bundle` へ渡す X 軸走査範囲 (µm)。
    scale_y_um
        Y-axis scan size in micrometers, forwarded to `measure_bundle`.
        `measure_bundle` へ渡す Y 軸走査範囲 (µm)。
    max_workers
        Maximum number of worker threads used per bundle.
        1 バンドルあたりの並列追跡ワーカースレッド数の上限。

    Returns
    -------
    tuple
        ``(per_bundle, errors)``. `per_bundle` lists
        ``(bundle_path, heights_nm, weights_nm)`` triples with every traced
        fiber of that bundle concatenated; `errors` lists
        ``(bundle_path, message)`` pairs with fixed English messages.
        ``(per_bundle, errors)``。`per_bundle` はバンドルごとに
        ``(バンドルパス, 高さ配列 (nm), 重み配列 (nm))`` を並べたもので、その
        バンドルの全追跡ファイバーを連結して保持する。`errors` は
        ``(バンドルパス, メッセージ)`` で、メッセージは固定の英語文字列。

    Notes
    -----
    This is the length-weighted counterpart of `skeleton_height_values`, and
    shares the same per-bundle failure contract. The two do not sample the
    same population: `skeleton_height_values` reads every pixel of the
    skeleton mask, while this walks the traced fibers, which exclude the
    branch-point neighborhoods removed before tracing.
    本関数は `skeleton_height_values` の長さ重み付け版で、バンドル単位の失敗
    契約も共通である。ただし両者の母集団は同一ではない。
    `skeleton_height_values` は骨格マスクの全画素を読むのに対し、本関数は追跡
    済みファイバーをたどるため、追跡前に除去される分岐点近傍を含まない。
    """
    per_bundle: List[Tuple[str, np.ndarray, np.ndarray]] = []
    errors: List[Tuple[str, str]] = []
    for path in bundle_paths:
        try:
            anchors = _exclusion_anchors(path) if apply_exclusions else ()
            result = measure_bundle(
                path,
                scale_um=scale_um,
                scale_y_um=scale_y_um,
                max_workers=max_workers,
                exclude_anchors=anchors,
            )
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            continue

        fibers = result.fibers

        heights: List[np.ndarray] = []
        weights: List[np.ndarray] = []
        for fiber in fibers:
            height = np.asarray(fiber.height, dtype=float)
            if height.size == 0:
                continue
            heights.append(height)
            weights.append(contour_length_weights(fiber.horizon))

        if heights:
            per_bundle.append(
                (path, np.concatenate(heights), np.concatenate(weights))
            )
        else:
            per_bundle.append(
                (path, np.empty(0, dtype=float), np.empty(0, dtype=float))
            )
    return per_bundle, errors


def collect_fiber_curvature(
    bundle_paths: Sequence[str],
    scale_um: Optional[float] = None,
    scale_y_um: Optional[float] = None,
    max_workers: Optional[int] = None,
    apply_exclusions: bool = False,
    curvature_window_nm: float = DEFAULT_CURVATURE_WINDOW_NM,
) -> Tuple[List[Tuple[str, np.ndarray]], List[Tuple[str, str]]]:
    """
    Measure the per-fiber mean curvature across several bundles.
    複数のバンドルについて、ファイバーごとの平均曲率を計測する。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles containing the tracking keys.
        追跡用キーを含む ``.b2z`` バンドルのパス。
    scale_um
        X-axis scan size in micrometers, forwarded to `measure_bundle`.
        `measure_bundle` へ渡す X 軸走査範囲 (µm)。
    scale_y_um
        Y-axis scan size in micrometers, forwarded to `measure_bundle`.
        `measure_bundle` へ渡す Y 軸走査範囲 (µm)。
    max_workers
        Maximum number of worker threads used per bundle.
        1 バンドルあたりの並列追跡ワーカースレッド数の上限。
    apply_exclusions
        When ``True``, drop manually excluded fibers, as in
        `collect_fiber_stats`.
        ``True`` のとき、`collect_fiber_stats` と同様に手動除外されたファイバーを
        取り除く。
    curvature_window_nm
        Arc length the curvature estimator turns over.
        曲率推定が回転角を測る弧長。

    Returns
    -------
    tuple
        ``(per_bundle, errors)``. `per_bundle` lists
        ``(bundle_path, mean_curvature)`` pairs whose array holds one entry
        per fiber, NaN for a fiber shorter than the curvature window.
        `errors` follows the same per-bundle failure contract as
        `collect_fiber_stats`.
        ``(per_bundle, errors)``。`per_bundle` はバンドルごとに
        ``(バンドルパス, 平均曲率)`` を並べ、配列はファイバー 1 本につき 1 要素を
        持つ。曲率窓より短いファイバーは NaN になる。`errors` は
        `collect_fiber_stats` と同じバンドル単位の失敗契約に従う。

    Notes
    -----
    A fiber too short for the window keeps NaN rather than 0.0, so a caller
    can report how many fibers the window excluded instead of mistaking them
    for perfectly straight ones.
    窓より短いファイバーは 0.0 ではなく NaN のままとする。呼び出し側が、それらを
    完全な直線と取り違えることなく、窓によって除外された本数を報告できるように
    するためである。
    """
    per_bundle: List[Tuple[str, np.ndarray]] = []
    errors: List[Tuple[str, str]] = []
    for path in bundle_paths:
        try:
            anchors = _exclusion_anchors(path) if apply_exclusions else ()
            result = measure_bundle(
                path,
                scale_um=scale_um,
                scale_y_um=scale_y_um,
                max_workers=max_workers,
                exclude_anchors=anchors,
            )
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            continue

        fibers = result.fibers

        x_spp = result.image.size_per_pixel
        y_spp = result.image.y_size_per_pixel
        curvature = [
            fiber_mean_curvature(
                fiber, x_spp, y_spp, window_nm=curvature_window_nm,
            )
            for fiber in fibers
        ]

        per_bundle.append((path, np.asarray(curvature, dtype=float)))
    return per_bundle, errors


def read_fiber_csv(path: str) -> List[FiberStats]:
    """
    Read a per-fiber statistics CSV back into `FiberStats` rows.
    ファイバー統計 CSV を `FiberStats` の行として読み戻す。

    Parameters
    ----------
    path
        CSV written by `write_fiber_csv`, from GUI04's export or
        ``cli.py measure``.
        `write_fiber_csv` が書き出した CSV。GUI04 の出力または
        ``cli.py measure`` によるもの。

    Returns
    -------
    list of FiberStats
        One row per fiber, in file order.
        ファイバーごとの行を、ファイル内の順序で返す。

    Raises
    ------
    ValueError
        If the header does not match `FIBER_CSV_COLUMNS`, or a row cannot be
        parsed. A file with the right name but the wrong columns is reported
        rather than partially read.

    Notes
    -----
    This closes the loop that makes visual curation usable: GUI04 exports the
    fibers a person actually looked at and accepted, and reading them back
    lets the distribution be built over exactly that population rather than
    over every object the tracer found. The `index` column is the position
    within the exported file, not within the bundle's full fiber list, because
    the export renumbers what it writes.
    目視によるキュレーションを実用にするための復路である。GUI04 は人が実際に
    見て採用したファイバーを出力し、それを読み戻すことで、追跡器が見つけた
    全ての対象ではなく、まさにその母集団に対して分布を作れる。`index` 列は
    出力ファイル内での位置であり、バンドルの全ファイバーリスト内での位置では
    ない。出力時に採番し直されるためである。
    """
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path} is empty") from None

        columns = [h.strip() for h in header]
        if columns == list(FIBER_CSV_COLUMNS):
            expected = FIBER_CSV_COLUMNS
        elif columns == list(FIBER_CSV_COLUMNS_V1):
            # A file written before straightness existed; every other column
            # is unchanged, so it is read with that one field left undefined.
            # straightness が存在する前に書かれたファイル。他の列は変わって
            # いないため、その 1 項目だけ未定義として読む。
            expected = FIBER_CSV_COLUMNS_V1
        else:
            raise ValueError(
                f"{path} is not a fiber statistics CSV; expected columns "
                f"{list(FIBER_CSV_COLUMNS)} or {list(FIBER_CSV_COLUMNS_V1)}, "
                f"found {header}"
            )

        stats: List[FiberStats] = []
        for row_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(expected):
                raise ValueError(
                    f"{path} line {row_number}: expected "
                    f"{len(expected)} columns, found {len(row)}"
                )
            try:
                angles = tuple(
                    float(a) for a in row[6].split(";") if a.strip()
                )
                straightness = float("nan")
                if len(expected) > 7 and row[7].strip():
                    straightness = float(row[7])
                stats.append(FiberStats(
                    index=int(row[0]),
                    length_nm=float(row[1]),
                    height_median_nm=float(row[2]),
                    height_max_nm=float(row[3]),
                    ep_count=int(row[4]),
                    kink_count=int(row[5]),
                    kink_angles_deg=angles,
                    straightness=straightness,
                ))
            except ValueError as e:
                raise ValueError(f"{path} line {row_number}: {e}") from e
    return stats


def collect_fiber_stats_from_csv(
    csv_paths: Sequence[str],
) -> Tuple[List[Tuple[str, List[FiberStats]]], List[Tuple[str, str]]]:
    """
    Read several per-fiber CSV files, keeping each file separate.
    複数のファイバー統計 CSV を、ファイルごとに分けたまま読み込む。

    Parameters
    ----------
    csv_paths
        Paths to CSV files written by `write_fiber_csv`.
        `write_fiber_csv` が書き出した CSV のパス。

    Returns
    -------
    tuple
        ``(per_file, errors)`` with the same shape and failure contract as
        `collect_fiber_stats`: one unreadable file becomes an error entry
        instead of aborting the collection.
        `collect_fiber_stats` と同じ形と失敗契約の ``(per_file, errors)``。
        読めないファイル 1 つで収集全体を中断せず、エラー項目として返す。
    """
    per_file: List[Tuple[str, List[FiberStats]]] = []
    errors: List[Tuple[str, str]] = []
    for path in csv_paths:
        try:
            per_file.append((path, read_fiber_csv(path)))
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
    return per_file, errors


def write_fiber_csv(path: str, stats: Sequence[FiberStats]) -> None:
    """
    Write per-fiber statistics to a CSV file.
    ファイバーごとの統計値を CSV ファイルへ書き出す。

    Parameters
    ----------
    path
        Output CSV path. The file is overwritten if it exists.
        出力 CSV パス。既存ファイルは上書きされる。
    stats
        Statistics rows, typically from `compute_fiber_stats`.
        統計値の行。通常は `compute_fiber_stats` の戻り値。

    Notes
    -----
    The encoding is UTF-8 with BOM (`utf-8-sig`) so Excel on Japanese Windows
    opens the file without mojibake.
    エンコーディングは BOM 付き UTF-8（`utf-8-sig`）とし、日本語 Windows の
    Excel で文字化けせずに開けるようにする。
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(list(FIBER_CSV_COLUMNS))
        for s in stats:
            writer.writerow([
                s.index,
                f"{s.length_nm:.1f}",
                f"{s.height_median_nm:.3f}",
                f"{s.height_max_nm:.3f}",
                s.ep_count,
                s.kink_count,
                ";".join(f"{a:.1f}" for a in s.kink_angles_deg),
                "" if not np.isfinite(s.straightness) else f"{s.straightness:.4f}",
            ])


def all_pixel_height(calimage_list, sklimage_list):
    """
    Collect calibrated height values at skeletonized fiber pixels.
    細線化された繊維画素位置の補正済み高さ値を収集する。

    Parameters
    ----------
    calimage_list
        Calibrated AFM height images whose values are sampled.
        サンプリング対象となる補正済み AFM 高さ画像。
    sklimage_list
        Skeletonized masks; nonzero pixels mark fiber centerlines.
        非ゼロ画素が繊維中心線を表す細線化マスク。

    Returns
    -------
    list
        Height values sampled from the calibrated images.
        補正済み画像からサンプリングされた高さ値。

    Notes
    -----
    The sampled values come from calibrated images, not from the raw AFM input.
    サンプリング値は元の AFM 入力ではなく、補正済み画像から取得する。
    """
    all_height = []
    for calimage, sklimage in zip(calimage_list, sklimage_list):
        all_height.extend(calimage[np.where(sklimage)])
    return all_height


def skeleton_height_values(
    bundle_paths: Sequence[str],
) -> Tuple[np.ndarray, List[Tuple[str, str]]]:
    """
    Collect skeleton-pixel heights from multiple ``.b2z`` bundles.
    複数の ``.b2z`` バンドルからスケルトン画素の高さ値を収集する。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles containing ``calibrated`` and
        ``skeletonized`` keys.
        ``calibrated`` と ``skeletonized`` キーを含む ``.b2z`` バンドルのパス。

    Returns
    -------
    tuple
        ``(heights, errors)``. `heights` is a 1D float array of all collected
        height values in nanometers; `errors` lists ``(bundle_path, message)``
        pairs for bundles that failed to load, with fixed English messages.
        ``(heights, errors)``。`heights` は収集した全高さ値 (nm) の 1 次元
        float 配列。`errors` は読み込みに失敗したバンドルの
        ``(バンドルパス, メッセージ)`` ペアのリストで、メッセージは固定の
        英語文字列。

    Notes
    -----
    A load failure in one bundle does not abort the collection; remaining
    bundles are still processed so grouped GUI runs degrade gracefully.
    1 つのバンドルの読み込み失敗で収集全体は中断しない。残りのバンドルは
    処理を続け、グループ実行が部分的な失敗に耐えられるようにする。
    """
    heights: List[float] = []
    errors: List[Tuple[str, str]] = []
    for path in bundle_paths:
        try:
            # Contract validation included: a malformed bundle becomes an
            # error entry here instead of corrupting the pooled heights.
            # 契約検証込み。不正なバンドルは集約高さ値を汚染せず、ここで
            # エラー項目になる。
            bundle = _load_validated_arrays(path, ["calibrated", "skeletonized"])
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            continue
        heights.extend(
            all_pixel_height([bundle["calibrated"]], [bundle["skeletonized"]])
        )
    return np.asarray(heights, dtype=float), errors


def write_heights_csv(
    path: str,
    per_bundle: Sequence[Tuple[str, np.ndarray]],
) -> None:
    """
    Write skeleton-pixel heights to a long-format CSV file.
    スケルトン画素の高さ値を縦持ち形式の CSV ファイルへ書き出す。

    Parameters
    ----------
    path
        Output CSV path. The file is overwritten if it exists.
        出力 CSV パス。既存ファイルは上書きされる。
    per_bundle
        ``(bundle_name, heights)`` pairs; one output row is written per
        height value so external tools can regroup and re-bin freely.
        ``(バンドル名, 高さ配列)`` のペア列。高さ値 1 つにつき 1 行を書き出し、
        外部ツールで自由に再グループ化・再ビニングできるようにする。
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["bundle", "height_nm"])
        for name, heights in per_bundle:
            for h in np.asarray(heights, dtype=float):
                writer.writerow([name, f"{h:.6g}"])
