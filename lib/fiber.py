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

from dataclasses import dataclass

import numpy as np

# Default pixel size based on 5000 nm scan width over 1024 pixels.
# デフォルトのピクセルサイズ: スキャン範囲 5000 nm を 1024 ピクセルで割った値 (nm/px)
_DEFAULT_PIXELSIZE = 5000 / 1024


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
        X-coordinate sequence of skeleton track (px).
        骨格線の x 座標列 (px)。
    ytrack
        Y-coordinate sequence of skeleton track (px).
        骨格線の y 座標列 (px)。
    horizon
        Cumulative distance along the skeleton path (nm).
        骨格線に沿った累積距離列 (nm)。
    height
        Height values sampled on the skeleton path (nm).
        骨格線上の高さ列 (nm)。
    kink_indices
        Indices of kink points in the track arrays.
        キンク点のインデックス列。
    ep_indices
        Endpoint indices in the track arrays.
        A fiber is treated as independent when this has length 2.
        端点のインデックス列。要素数が 2 のとき独立したファイバーと判定する。
    kink_angles
        Angle values at kink points (deg).
        各キンク点における角度列 (deg)。
    decomposed_point_indices
        Indices of decomposition points used for piecewise approximation.
        分解点のインデックス列。
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

    @property
    def length(self) -> float:
        """
        Return total fiber length along the skeleton path in nanometers.
        骨格線に沿ったファイバー全長（nm）を返す。

        Returns
        -------
        Last value of `horizon`, interpreted as full path length.
        `horizon` の末尾値（全経路長として解釈される）。
        """
        # `horizon` is cumulative distance, so the final element is total length.
        # `horizon` は累積距離のため、末尾要素が全長に対応する。
        return self.horizon[-1]
