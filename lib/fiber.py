"""
Define an immutable data container for a single fiber.
1本のファイバーを表す不変データコンテナを定義する。

This module provides the `Fiber` dataclass used across analysis and GUI layers.
このモジュールは、解析処理と GUI 層で共通利用される `Fiber` データクラスを提供する。
The class groups geometry, height profile, and feature indices
so downstream code can access fiber properties in a consistent structure.
このクラスは、形状情報・高さプロファイル・特徴点インデックスをまとめ、
後段処理が一貫した構造でファイバー情報にアクセスできるようにする。
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from .centerline import SKELETON_TRACK


@dataclass(frozen=True)
class Fiber:
    """
    Represent one nanofiber as an immutable data object.
    1 本のナノファイバーを表す不変データクラス。

    The dataclass is marked `frozen=True`, which means its fields cannot be
    reassigned after creation. This helps avoid accidental mutation bugs.
    このデータクラスは `frozen=True` のため、生成後に属性を再代入できない。
    これにより、意図しない書き換えバグを防ぎやすくなる。

    Attributes
    ----------
    fiber_image
        Cropped image array around this fiber.
        ファイバー領域を切り出した画像配列。
    data
        Optional metadata tuple (for example component stats).
        任意のメタデータタプル (例: 連結成分の統計情報)。
    xtrack
        X-coordinate sequence of the line the fiber is drawn and measured
        along (px, relative to the bounding-box origin in ``data``). For a
        bundle of format 1.1 this is the half-maximum centerline of
        `lib.centerline`, with sub-pixel values; for an older bundle it is
        the skeleton pixel chain (see `centerline`).
        繊維を描画し計測する線の x 座標列（px、``data`` の外接矩形原点基準）。
        形式 1.1 のバンドルでは `lib.centerline` の半値中点線で小数値を持ち、
        それより古いバンドルではスケルトンの画素鎖である（`centerline` 参照）。
    ytrack
        Y-coordinate sequence of the same line (px).
        同じ線の y 座標列 (px)。
    horizon
        Cumulative distance along the line (nm).
        線に沿った累積距離列 (nm)。
    height
        Height values sampled along the line (nm).
        線上の高さ列 (nm)。
    kink_indices
        Indices of kink points in the track arrays.
        キンク点のインデックス列。
    ep_indices
        Endpoint indices in the track arrays.
        A fiber is treated as independent when this has length 2.
        端点のインデックス列。要素数が 2 のとき独立したファイバーと判定する。
    kink_angles
        Interior angles at kink points in radians, same unit as the bundle
        ``ka`` key. Degrees appear only in user-facing output; the conversion
        is centralized in `lib.measure.FiberStats.kink_angles_deg`.
        各キンク点における内角列（ラジアン）。バンドルの ``ka`` キーと同じ
        単位で保持する。度数値はユーザー向け出力でのみ使い、変換は
        `lib.measure.FiberStats.kink_angles_deg` に一元化されている。
    decomposed_point_indices
        Indices of the vertices of the polyline a bundle of format 1.0 judged
        kinks on; empty from format 1.1, whose kink rule does not decompose
        the line.
        形式 1.0 のバンドルがキンクを判定した折れ線の頂点インデックス列。形式 1.1
        以降のキンク規則は線を分解しないため空である。
    skeleton_xtrack
        X coordinates of the skeleton pixels the line was traced from, one per
        line point (px, bounding-box relative). They identify the fiber --
        exclusion and connection anchors, the branch-point and frame tests --
        and are never drawn or measured. ``None`` when the line is the
        skeleton itself. Read them through `skeleton_track`.
        線の元になったスケルトン画素の x 座標。線の点ごとに 1 つ（px、外接矩形
        基準）。繊維の識別（除外・連結のアンカー、分岐点・画像端の判定）にだけ
        使い、描画にも計測にも使わない。線がスケルトンそのものなら ``None``。
        `skeleton_track` を通して読むこと。
    skeleton_ytrack
        Y coordinates of the same skeleton pixels.
        同じスケルトン画素の y 座標。
    centerline
        Which line `xtrack` / `ytrack` hold: `centerline.HALF_MAX_CENTERLINE`
        or `centerline.SKELETON_TRACK`.
        `xtrack` / `ytrack` がどの線か。`centerline.HALF_MAX_CENTERLINE` または
        `centerline.SKELETON_TRACK`。
    unjudged_indices
        Indices of the bends the kink rule measured within 1.5 apparent widths
        of an end of the line, where too little fiber lies on one side to tell
        a kink from the shape of the end itself. They are drawn but never
        counted as kinks. Empty for a bundle older than format 1.1.
        線の端から見かけ幅 1.5 本分以内でキンク規則が測った折れのインデックス列。
        そこでは片側の繊維が短すぎ、キンクと端そのものの形を区別できない。描画は
        するがキンクとしては数えない。形式 1.1 より古いバンドルでは空。
    """

    fiber_image: np.ndarray
    data: tuple
    xtrack: np.ndarray
    ytrack: np.ndarray
    horizon: np.ndarray
    height: np.ndarray
    kink_indices: np.ndarray
    ep_indices: np.ndarray
    kink_angles: np.ndarray
    decomposed_point_indices: np.ndarray
    skeleton_xtrack: Optional[np.ndarray] = None
    skeleton_ytrack: Optional[np.ndarray] = None
    centerline: str = SKELETON_TRACK
    unjudged_indices: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.intp))

    @property
    def length(self) -> float:
        """
        Return total fiber length along its line in nanometers.
        線に沿ったファイバー全長（nm）を返す。

        Returns
        -------
        Last value of `horizon`, interpreted as full path length.
        `horizon` の末尾値（全経路長として解釈される）。
        """
        # `horizon` is cumulative distance, so the final element is total length.
        # `horizon` は累積距離のため、末尾要素が全長に対応する。
        return self.horizon[-1]


def skeleton_track(fiber) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return the skeleton pixels a fiber was traced from, bounding-box relative.
    ファイバーの元になったスケルトン画素を、外接矩形基準で返す。

    Parameters
    ----------
    fiber
        A `Fiber`, or any object with ``xtrack`` / ``ytrack`` arrays.
        `Fiber`、または ``xtrack`` / ``ytrack`` 配列を持つ任意のオブジェクト。

    Returns
    -------
    tuple of ndarray
        ``(x, y)`` integer pixel coordinates, one per line point.
        線の点ごとに 1 つの整数画素座標 ``(x, y)``。

    Notes
    -----
    Everything that identifies a fiber reads this rather than the drawn line:
    the exclusion and connection sidecars store skeleton pixels, and the
    branch-point and frame tests were measured on them. The drawn line moves
    whenever the centerline estimate changes, while the skeleton moves only
    when the image is re-analyzed, which `connect_selection.skeleton_digest`
    already detects.
    繊維を識別する処理はすべて、描画される線ではなくこれを読む。除外・連結の
    サイドカーはスケルトン画素を保存しており、分岐点・画像端の判定もその上で
    測って決めたものである。描画される線は中心線の推定が変わるたびに動くが、
    スケルトンが動くのは画像を再解析したときだけであり、それは
    `connect_selection.skeleton_digest` が既に検出する。
    """
    sx = getattr(fiber, "skeleton_xtrack", None)
    sy = getattr(fiber, "skeleton_ytrack", None)
    if sx is None or sy is None:
        return (np.asarray(fiber.xtrack).astype(int),
                np.asarray(fiber.ytrack).astype(int))
    return np.asarray(sx).astype(int), np.asarray(sy).astype(int)
