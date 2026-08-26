# -*- coding: utf-8 -*-
"""
Measure the stripe noise an AFM scan carries, before it is analyzed.
解析前に AFM 走査が抱える縞ノイズを測定する。

The stripe here is not a texture: it is a scan line the feedback loop misplaced
in Z. Naming the module after the visible symptom keeps it aligned with the
GUI column that reports it, while the code below works on the cause.
ここでいう縞は模様ではなく、フィードバックループが Z 方向に置き損ねた走査線
そのものである。モジュール名を目に見える症状に合わせることで、それを報告する
GUI の列と用語が揃う。一方で以下のコードは原因の側を扱う。

A tapping-mode scan occasionally loses feedback for a few lines: the tip
settles at a wrong Z offset and the whole scan line is displaced, producing a
bright or dark horizontal band. The height *within* such a line is not simply
noisier — it is offset, so the band behaves like a huge sharp structure that
no threshold or ridge filter can tell apart from real material.
タッピングモードの走査では、数ラインにわたってフィードバックが外れることが
ある。探針が誤った Z オフセットで整定し、その走査線全体が上下にずれて、明るい
（または暗い）横帯になる。この帯は線内の高さが単にノイズっぽいのではなく
オフセットしているため、巨大で急峻な構造として振る舞い、しきい値処理でも
リッジフィルタでも実体と区別できない。

That matters beyond the band itself. Several analysis steps derive a threshold
from a statistic taken over the *whole* image, so one glitch band rescales the
analysis everywhere. The starkest case measured on a bundled scan: the ridge
recovery stage takes its hysteresis seed from `threshold_otsu` over the Frangi
response, and with the glitch bands present that seed landed above the maximum
response of every genuine fiber in the clean part of the image, so not one
clean-region pixel could seed the hysteresis and the stage recovered nothing
there. Cropping the analysis to a glitch-free band of the *same* scan raised
the recovered skeleton in those lines from 1.6 um to 50.2 um.
影響は帯の内部にとどまらない。解析の複数の段が *画像全体* の統計からしきい値を
決めるため、グリッチ帯 1 つが解析全体のスケールを狂わせる。実測で最も極端
だった例: リッジ回収段はヒステリシスの種を Frangi 応答に対する
`threshold_otsu` から取るが、グリッチ帯があるとその種が清浄部の本物の繊維の
応答の最大値をも上回り、清浄部からは種が 1 画素も立たず、その領域では何も
回収されなかった。同一走査のグリッチのない帯だけに解析を絞ると、同じ走査線
での回収スケルトンは 1.6 um から 50.2 um に増えた。

This module only measures and reports; it never modifies an image and nothing
it computes is written into the `.b2z` bundle. The metrics are exactly
reproducible from the raw input, so a stored copy could only let values from an
older metric definition be read back and compared, unmarked, against current
ones.
本モジュールは測定と報告のみを行い、画像を改変せず、算出値を `.b2z` バンドルへ
書き込むこともしない。指標は生入力から厳密に再現できるため、保存してしまうと
古い指標定義の値が無印のまま現行値と比較される余地を生むだけである。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import List, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# Height step between neighboring scan lines, in nanometres, above which the
# boundary is treated as a feedback glitch rather than sample topography.
# Chosen to sit well above the line-to-line variation of a healthy scan and
# well below a real glitch: on the bundled scans the median step is 0.4-1.0 nm
# while glitch steps reach 74-128 nm. It is a screening heuristic, not a
# physical constant, so it is exposed as a setting rather than hard-coded at
# the call sites.
# 隣接走査線間の高さ段差（nm）。これを超える境界は試料形状ではなくフィード
# バック不良とみなす。健全な走査の線間変動より十分大きく、実際のグリッチより
# 十分小さい値を選んだ。同梱走査では段差の中央値が 0.4〜1.0 nm であるのに対し、
# グリッチの段差は 74〜128 nm に達する。これは物理定数ではなく検査用の経験則
# なので、呼び出し側に直書きせず設定として露出する。
DEFAULT_STEP_THRESHOLD_NM = 3.0

# Scan lines on each side of a flagged step that are also treated as bad.
# The feedback loop does not recover instantly: it rings for several lines
# after the disturbance, so the lines adjacent to a step are displaced too even
# though their own line-to-line step is small.
# 段差が検出された箇所の前後で、同じく不良とみなす走査線数。フィードバック
# ループは瞬時には復帰せず、擾乱の後で数ライン整定を続けるため、隣接ラインは
# 自身の線間段差が小さくてもずれている。
DEFAULT_GUARD_LINES = 6


@dataclass(frozen=True)
class StripeNoise:
    """
    Per-scan-line glitch assessment of one height image.
    1 枚の高さ画像に対する走査線ごとのグリッチ判定。

    Attributes
    ----------
    step_nm
        Absolute height step between consecutive scan lines, in nanometres.
        Length is one less than the number of scan lines; element ``i`` is the
        step between line ``i`` and line ``i + 1``.
        連続する走査線間の高さ段差の絶対値 (nm)。長さは走査線数より 1 少なく、
        要素 ``i`` は走査線 ``i`` と ``i + 1`` の間の段差を表す。
    bad_lines
        True for every scan line judged to be displaced by a feedback glitch,
        including the guard lines around each flagged step.
        フィードバック不良で変位したと判定された走査線が True。各段差の周囲の
        ガードラインも含む。
    threshold_nm
        Step threshold that produced this assessment.
        この判定に用いた段差しきい値。
    guard_lines
        Guard width that produced this assessment.
        この判定に用いたガード幅。
    """

    step_nm: np.ndarray
    bad_lines: np.ndarray
    threshold_nm: float
    guard_lines: int

    @property
    def bad_fraction(self) -> float:
        """
        Fraction of scan lines judged bad, in the range 0.0 to 1.0.
        不良と判定された走査線の割合（0.0〜1.0）。
        """
        if self.bad_lines.size == 0:
            return 0.0
        return float(self.bad_lines.mean())

    @property
    def flagged_steps(self) -> int:
        """
        Number of line boundaries whose step exceeded the threshold.
        段差がしきい値を超えた走査線境界の数。
        """
        return int((self.step_nm > self.threshold_nm).sum())

    @property
    def worst_step_nm(self) -> float:
        """
        Largest line-to-line step found, in nanometres.
        検出された線間段差の最大値 (nm)。
        """
        if self.step_nm.size == 0:
            return 0.0
        return float(self.step_nm.max())


def evaluate_scan_lines(
    image: np.ndarray,
    *,
    threshold_nm: float = DEFAULT_STEP_THRESHOLD_NM,
    guard_lines: int = DEFAULT_GUARD_LINES,
) -> StripeNoise:
    """
    Flag scan lines displaced by a feedback glitch.
    フィードバック不良で変位した走査線を検出する。

    Parameters
    ----------
    image
        Raw or calibrated height image in nanometres, scan lines along rows.
        生または補正済みの高さ画像 (nm)。走査線が行方向に並ぶ。
    threshold_nm
        Line-to-line step above which a boundary is called a glitch.
        これを超える線間段差をグリッチと判定する値。
    guard_lines
        Scan lines on each side of a flagged step also marked bad.
        検出された段差の前後で同じく不良とする走査線数。

    Returns
    -------
    StripeNoise
        Assessment covering every scan line of the image.
        画像の全走査線に対する判定結果。

    Raises
    ------
    ValueError
        If `image` is not a 2D array.

    Notes
    -----
    The statistic is the *median* height of each scan line, not the mean.
    A scan line crossing many fibers has a higher mean than an empty one, so a
    mean-based step would flag dense regions as glitches; the median tracks the
    substrate level and is insensitive to how much material the line crosses.
    指標には各走査線の高さの *中央値* を使い、平均は使わない。多数の繊維を横切る
    走査線は空の走査線より平均が高くなるため、平均に基づく段差は密な領域を
    グリッチと誤検出する。中央値は基板レベルに追随し、その走査線が横切る実体の
    量に左右されない。
    """
    arr = np.asarray(image, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"evaluate_scan_lines expects a 2D height image, got shape {arr.shape}"
        )

    n_lines = arr.shape[0]
    if n_lines < 2:
        # A single scan line has no neighbor to step against.
        return StripeNoise(
            step_nm=np.zeros(0, dtype=float),
            bad_lines=np.zeros(n_lines, dtype=bool),
            threshold_nm=float(threshold_nm),
            guard_lines=int(guard_lines),
        )

    # nanmedian so a scan with some invalid pixels still yields a usable
    # profile. A line with no valid pixel at all has no level to compare, so it
    # is excluded from the step profile and flagged directly: it carries no
    # analyzable height either way.
    # 一部の画素が無効でも使えるプロファイルを得るため nanmedian を使う。有効
    # 画素が 1 つも無い走査線は比較すべき基準を持たないので、段差プロファイル
    # から除外して直接不良とする。いずれにせよ解析可能な高さを持たない。
    empty_lines = np.isnan(arr).all(axis=1)
    line_median = np.full(n_lines, np.nan, dtype=float)
    if not empty_lines.all():
        line_median[~empty_lines] = np.nanmedian(arr[~empty_lines], axis=1)
        # Carry the nearest measured level across empty lines so their gap does
        # not read as a height step at both of its edges.
        # 空の走査線には最近傍の実測レベルを引き継ぎ、その隙間が両端で高さ段差
        # として読まれないようにする。
        idx = np.where(~empty_lines, np.arange(n_lines), 0)
        np.maximum.accumulate(idx, out=idx)
        line_median = line_median[idx]
        first = int(np.argmax(~empty_lines))
        line_median[:first] = line_median[first]

    step_nm = np.abs(np.diff(line_median))
    step_nm = np.nan_to_num(step_nm, nan=0.0)

    bad_lines = empty_lines.copy()
    guard = max(int(guard_lines), 0)
    for i in np.flatnonzero(step_nm > float(threshold_nm)):
        # Step `i` sits between lines `i` and `i + 1`, so both ends of the
        # boundary are marked before the guard is applied on either side.
        bad_lines[max(0, i - guard):i + guard + 2] = True

    return StripeNoise(
        step_nm=step_nm,
        bad_lines=bad_lines,
        threshold_nm=float(threshold_nm),
        guard_lines=guard,
    )


def propose_clean_ranges(
    quality: StripeNoise,
    *,
    min_lines: int = 1,
) -> List[Tuple[int, int]]:
    """
    List the runs of consecutive glitch-free scan lines.
    連続するグリッチのない走査線の区間を列挙する。

    Parameters
    ----------
    quality
        Assessment returned by `evaluate_scan_lines`.
        `evaluate_scan_lines` が返した判定結果。
    min_lines
        Shortest run kept, in scan lines. Runs below this are dropped.
        保持する最短区間の走査線数。これ未満の区間は捨てる。

    Returns
    -------
    list of tuple
        Half-open ``(start, stop)`` scan-line ranges in image order, so
        ``image[start:stop]`` is the glitch-free block.
        画像の並び順による半開区間 ``(start, stop)`` のリスト。
        ``image[start:stop]`` がグリッチのないブロックになる。

    Notes
    -----
    Ranges are returned in image order rather than sorted by length, because a
    caller presenting them to a user needs them to line up with the image the
    user is looking at. Sort by ``stop - start`` at the call site when the
    longest block is what matters.
    区間は長さ順ではなく画像の並び順で返す。ユーザーに提示する呼び出し側では、
    ユーザーが見ている画像と並びが一致している必要があるためである。最長ブロック
    が必要な場合は呼び出し側で ``stop - start`` により整列する。
    """
    good = ~np.asarray(quality.bad_lines, dtype=bool)
    ranges: List[Tuple[int, int]] = []
    start = None
    for i, ok in enumerate(good):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            ranges.append((start, i))
            start = None
    if start is not None:
        ranges.append((start, len(good)))

    keep = max(int(min_lines), 1)
    return [(a, b) for (a, b) in ranges if b - a >= keep]
