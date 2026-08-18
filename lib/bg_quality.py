# -*- coding: utf-8 -*-
"""
GUI-independent quality metrics for the estimated background surface.
推定された背景曲面に対する GUI 非依存の品質評価指標。

`lib.bg_calibrator` offers four `bg_method` strategies whose relative merit
depends on the sample, and nothing in the pipeline reported how well the
chosen one actually worked. This module scores one processed image so that a
method or parameter choice can be justified by numbers instead of by eye.
`lib.bg_calibrator` は 4 種類の `bg_method` を提供し、どれが優れているかは
試料に依存するが、選んだ方式が実際どれだけうまく効いたかを報告する仕組みは
パイプラインに無かった。本モジュールは処理済み画像 1 枚を採点し、方式や
パラメータの選択を目視ではなく数値で正当化できるようにする。

Three defects are measured, chosen because each was observed to occur while
the other two read clean, and each maps to a different fix.
測定する欠陥は 3 つである。いずれも他の 2 つが正常を示す状況で実際に発生する
ことが確認されており、それぞれ対処法が異なるという理由で選ばれている。

* A **halo** beside fibers, from a background estimate that is wrong close to
  them. Above `Segmenter.global_threshold` it binarizes as a phantom fiber
  running parallel to a real one.
* **Stripe residual**, from line-to-line offsets the background model did not
  remove. This is the defect `bg_method='spline1d'` exists to fix.
* A **mask footprint**, from over-dilating the calibrator's fiber mask until
  it excludes real substrate structure from the background pool.
* 繊維の脇に生じる**ハロー**。繊維近傍で背景推定が誤っていることによる。
  `Segmenter.global_threshold` を超えると、実際の繊維に並走する偽の繊維として
  二値化される。
* **縞残差**。背景モデルが除去しきれなかったライン間オフセットによる。
  `bg_method='spline1d'` が修正対象とする欠陥そのもの。
* **マスク足跡**。補正器の繊維マスクを過剰に膨張させ、実在する基板構造まで
  背景プールから除外してしまうことによる。

Every metric is reported in nanometers and is individually interpretable;
deliberately no single composite score is produced, because collapsing these
into one number requires weights with no physical basis and invites tuning the
weights until the answer matches an expectation.
全指標は nm で報告し、単独で解釈できるようにしてある。総合スコアは意図的に
作らない。1 つの数値へ畳むには物理的根拠のない重みが必要になり、期待する答えが
出るまで重みを調整する誘惑を生むためである。

Notes
-----
Halo detection samples a *signed* cross-section perpendicular to the local
fiber direction at points along the skeleton, and uses no binarized mask at
all. Two properties make this the only formulation that works.

First, the halo the background methods actually produce is antisymmetric: the
retired inpainting fill left "a trough on the uphill side, a ridge on the
downhill side" (`bg_calibrator._bg_generate`). Any statistic that pools both
flanks of a fiber together -- an isotropic distance transform, for instance --
averages the two signs and reports approximately zero for exactly the defect
that motivated replacing that method. A signed offset keeps the two sides
apart, so the antisymmetric part survives as `halo_asymmetry_nm`.

Second, a halo running parallel to a fiber is 8-connected to it and merges
into the fiber's binarized component, which puts it at mask-distance zero
where any mask-anchored measurement is blind. The skeleton stays on the fiber
centerline regardless of how far the mask spread.
ハロー検出は、スケルトン上の各点で局所繊維方向に垂直な*符号付き*断面を
標本化し、二値化マスクを一切使わない。この形式でなければならない理由が
2 つある。

第一に、背景方式が実際に生むハローは反対称である。廃止された inpaint 充填は
「上り側に溝、下り側に尾根」を残していた（`bg_calibrator._bg_generate`）。
繊維の両側を一緒に集計する統計量――例えば等方的な距離変換――は 2 つの符号を
平均してしまい、その方式の置き換えを動機づけた当の欠陥に対してほぼ 0 を
報告する。符号付きオフセットなら左右が分離されるため、反対称成分が
`halo_asymmetry_nm` として残る。

第二に、繊維に並走するハローは繊維と 8 連結になって二値化成分へ併合される
ため、マスク距離 0 の位置に入り、マスクを基準にした測定はそこが盲点になる。
スケルトンはマスクがどれだけ広がろうと繊維の中心線上に留まる。

The local fiber direction comes from a principal-component fit to nearby
skeleton pixels. At a crossing the two branches make the fit isotropic, so
requiring an elongated fit discards crossing samples without consulting the
branch-point mask.
局所繊維方向は近傍スケルトン画素への主成分フィットから求める。交差点では
2 本の枝によりフィットが等方的になるため、細長いフィットのみを採用すれば
分岐点マスクを参照せずに交差サンプルを除外できる。

The binarized mask is still used, deliberately, for the stripe residual, where
its only job is to say which pixels are substrate. A halo swallowed into a
fiber's component is harmless there: it merely removes a few pixels from a
background pool of hundreds of thousands.
縞残差では、意図的に二値化マスクを引き続き使う。そこでのマスクの役割はどの
画素が基板かを示すことだけである。繊維の成分へ飲み込まれたハローはここでは
無害で、数十万画素の背景プールから数画素を取り除くにすぎない。
"""

# ===== Standard library =====
import warnings as warnings_module
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates

# Scale factor converting a median absolute deviation to a Gaussian sigma.
# 中央絶対偏差をガウス分布の sigma へ換算する係数。
_MAD_TO_SIGMA = 1.4826

# Half-length of each perpendicular cross-section, in pixels, before the
# automatic expansion below. Must reach well past the fiber flank into open
# substrate so the profile has a tail to use as its own reference level.
# 各垂直断面の片側長さ (px)。後述の自動拡張が効く前の初期値。プロファイル自身が
# 参照レベルに使える裾を持つよう、繊維斜面を十分に超えて開けた基板まで届く
# 必要がある。
PROFILE_HALF_LEN_PX = 20

# Every Nth skeleton pixel starts a cross-section. Neighboring skeleton pixels
# give nearly identical profiles, so sampling all of them multiplies cost
# without adding independent information.
# N 画素ごとにスケルトン画素から断面を取る。隣接するスケルトン画素はほぼ同一の
# プロファイルを与えるため、全画素を使っても独立な情報は増えず計算量だけが増える。
SKELETON_SUBSAMPLE = 3

# Radius of the window whose skeleton pixels are fitted to get the local fiber
# direction. Large enough to average out the staircase of a digitized line,
# small enough that a gently curving fiber is still locally straight.
# 局所繊維方向を得るためにスケルトン画素をフィットする窓の半径。離散化された
# 線の階段状のギザギザを平均できる程度に大きく、かつ緩やかに湾曲する繊維が
# 局所的には直線とみなせる程度に小さく取る。
PCA_RADIUS_PX = 5

# Minimum ratio of the principal to the secondary variance for a direction fit
# to be accepted. At a crossing the two branches make the fit isotropic
# (ratio near 1), which is how crossing samples are rejected without using the
# branch-point mask.
# 方向フィットを採用する主分散/副分散比の下限。交差点では 2 本の枝により
# フィットが等方的になり（比が 1 付近）、これにより分岐点マスクを使わずに
# 交差サンプルを排除する。
MIN_ELONGATION = 4.0

# Offsets nearer than this to the fiber center are exempt from the
# neighbor-fiber check, since a cross-section necessarily crosses its own
# skeleton at the origin.
# これより中心に近いオフセットは近傍繊維チェックの対象外とする。断面は原点で
# 必ず自身のスケルトンと交わるためである。
SELF_GUARD_PX = 3

# Multiple of the half-width at half-maximum at which the fiber core is taken
# to have ended. Half-maximum is the right reference because it is a property
# of the core alone: a halo is far smaller than half the fiber height, so it
# cannot move the measured width. At 2x the half-width a Gaussian ridge has
# fallen to about 4% of its peak. Used to anchor the mask-footprint bands and
# to bound the profile length; the halo itself is located from the derivative,
# not from this factor.
# 繊維コアが終わったとみなす半値半幅の倍数。半値を基準にするのは、それが
# コアのみの性質だからである。ハローは繊維高さの半分よりはるかに小さいため
# 実測幅を動かせない。半値半幅の 2 倍ではガウス型の尾根はピークの約 4% まで
# 落ちている。マスク足跡帯の基準位置と断面長の見積もりに使う。ハロー自体は
# この係数ではなく微分から位置を特定する。
FLANK_END_FACTOR = 2.0

# Smoothing window, in samples, applied to the aggregate cross-section before
# it is differentiated. The profile is already a median over thousands of
# cross-sections, so this only removes single-sample jitter that would put
# spurious sign changes in the derivative.
# 集約断面を微分する前にかける平滑化窓（サンプル数）。断面は既に数千本の
# 中央値なので、この平滑化は微分に偽の符号反転を生む 1 サンプルのがたつきを
# 取り除くだけである。
PROFILE_SMOOTH_PX = 3

# A located extremum must exceed this multiple of the profile's own tail noise
# to count as a halo. Without the gate, the noise wiggles of a clean profile
# always produce some extremum and every image would report a halo.
# 特定された極値がハローとみなされるために超えるべき、断面自身の裾ノイズに
# 対する倍数。この判定が無いと、清浄な断面のノイズのゆらぎからも必ず極値が
# 得られ、あらゆる画像がハローを報告してしまう。
HALO_SIGNIFICANCE_SIGMA = 3.0

# Asymptotic standard error of a median relative to that of a mean. Used to
# floor the significance threshold with the aggregate profile's own sampling
# uncertainty: the tail of one profile can happen to be flatter than the data
# warrant, and a threshold read from that stretch alone collapses and passes
# noise as a halo.
# 中央値の標準誤差の平均値に対する漸近比。集約断面自身の標本誤差で有意性
# しきい値に下限を与えるために使う。1 本の断面の裾はデータが許す以上に平坦に
# なることがあり、その区間だけから読んだしきい値は潰れてノイズをハローとして
# 通してしまう。
_MEDIAN_SE_FACTOR = 1.2533

# Pixels kept beyond the measured features, so the cross-section still has an
# open stretch of substrate to use as its own reference level. Four of them are
# the tail actually averaged (`PROFILE_TAIL_PX`); the rest separate that tail
# from the features so the two do not sample the same structure.
# 実測対象の外側に確保する余白 (px)。断面が参照レベルに使える開けた基板の
# 区間を残すためのもの。うち 4 px が実際に平均される裾
# (`PROFILE_TAIL_PX`) で、残りは裾と対象が同じ構造を標本化しないよう両者を
# 引き離す。
PROFILE_TAIL_MARGIN_PX = 8

# Pixels at the far end of the cross-section averaged into the reference level.
# 参照レベルとして平均する断面の遠端の画素数。
PROFILE_TAIL_PX = 4

# Ceiling on the auto-expanded half-length, as a fraction of the shorter image
# axis. A pathological width measurement must not request a cross-section
# comparable to the image itself, which would reject every sample for leaving
# the frame.
# 自動拡張される片側長さの上限。短いほうの画像軸に対する割合で与える。異常な
# 幅推定が画像と同程度の断面を要求すると、全サンプルが枠外へ出て棄却される
# ため、それを防ぐ。
PROFILE_MAX_LEN_FRACTION = 4

# Most re-samplings allowed while the half-length converges. The width is a
# core property that barely moves as the profile lengthens, so this terminates
# after one expansion in practice; the bound only guards against oscillation.
# 片側長さが収束するまでに許す再取得の最大回数。幅は断面を伸ばしてもほとんど
# 動かないコアの性質なので実際には 1 回の拡張で収束する。この上限は振動に
# 対する保険にすぎない。
MAX_PROFILE_EXPANSIONS = 3

# Distance from the exclusion mask beyond which a pixel counts as far-field.
# 除外マスクからこの距離を超えた画素を遠方場として扱う。
FAR_PX = 20

# Fiber coverage above which the median-based statistics stop being robust.
# The same assumption is documented for the tophat median re-centering.
# 中央値ベースの統計が頑健でなくなる繊維被覆率。tophat の中央値再センタリング
# にも同じ前提が記録されている。
MAX_TRUSTED_COVERAGE = 0.5

# Fewest cross-sections whose aggregate describes the image rather than one or
# two fibers that happened to be traced. A deliberately round, conservative
# number: the halo of a handful of cross-sections may be perfectly real and
# still say nothing about the scan as a whole.
# 集約結果が、たまたま追跡された 1〜2 本の繊維ではなく画像を表していると
# みなせる断面本数の下限。意図的に丸めた保守的な値である。ごく少数の断面から
# 得たハローは、それ自体は正確でも走査全体については何も語らない。
MIN_TRUSTED_PROFILES = 30

# Fixed English warning strings; callers translate for display if needed.
# 固定の英語警告文字列。表示時の翻訳は呼び出し側で行う。
WARN_HIGH_COVERAGE = "fiber coverage above 50%: stripe residual unreliable"
WARN_NO_SKELETON = "empty skeleton: halo metrics unavailable"
WARN_NO_PROFILES = "no usable cross-section: halo metrics unavailable"
WARN_FEW_PROFILES = (
    "fewer than 30 usable cross-sections: halo metrics describe the few fibers "
    "that were traced, not the image"
)
WARN_NO_FAR_BACKGROUND = (
    "no pixels beyond the far-field distance: wide-halo check unavailable"
)
WARN_PROFILE_TRUNCATED = (
    "fibers too wide for the cross-section length allowed by the image: "
    "measured features may extend past the sampled range"
)
WARN_WIDE_HALO = (
    "cross-section reference level disagrees with the image far field: "
    "a halo wider than the cross-section is present (see halo_wide_nm)"
)


@dataclass(frozen=True)
class BgQuality:
    """
    Background-estimation quality metrics for one processed image.
    処理済み画像 1 枚に対する背景推定の品質指標。

    Attributes
    ----------
    halo_nm
        Symmetric part of the halo, as the mean of the extremum located on
        each flank. Positive means height is left behind beside fibers,
        negative means over-subtraction has cut a trench there. Compare its
        magnitude against `Segmenter.global_threshold`: a residual above that
        threshold can binarize as a phantom fiber running parallel to the real
        one. Exactly `0.0` when neither flank holds a significant extremum,
        which is the honest reading of "no halo" rather than a small nonzero
        number produced by averaging a band that mostly missed the feature.
        両側の斜面それぞれで特定した極値の平均として求めたハローの対称成分。
        正なら繊維の脇に高さが残留し、負なら過剰減算で溝が掘れている。大きさは
        `Segmenter.global_threshold` と比較する。しきい値を超える残留は、実際の
        繊維に並走する偽の繊維として二値化されうる。どちらの斜面にも有意な
        極値が無い場合はちょうど `0.0` となる。これは「ハロー無し」の正直な
        表現であり、対象をほとんど外した帯を平均して得られる小さな非ゼロ値
        よりも適切である。
    halo_asymmetry_nm
        Difference between the two flanks' extrema, measured with the
        cross-section oriented to point along +X. This is the signature of the
        antisymmetric halo (trough on one side, ridge on the other) that a
        both-sides-pooled statistic cancels to zero. Largest for fibers crossed
        along X, since the Savitzky-Golay smoothing that produces it runs along
        that axis.
        左右の斜面の極値の差。断面は +X 方向を向くよう揃えて測る。両側をまとめる
        統計量では 0 に相殺されてしまう反対称ハロー（片側が溝、反対側が尾根）の
        指標である。これを生む Savitzky-Golay 平滑化が X 軸に沿って走るため、
        X 方向に横切られる繊維で最大になる。
    halo_position_px
        Distance from the fiber center at which the halo extremum sits, in
        pixels, averaged over the flanks that had one. How far the defect
        reaches is diagnostic in its own right: a halo hugging the fiber points
        at the mask boundary, one further out at the smoothing window. `NaN`
        when no significant extremum was found.
        ハローの極値が位置する繊維中心からの距離 (px)。極値が見つかった斜面
        について平均する。欠陥がどこまで及ぶかはそれ自体が診断情報であり、
        繊維に密着したハローはマスク境界を、より外側のものは平滑化窓を示唆する。
        有意な極値が無い場合は `NaN`。
    halo_wide_nm
        Cross-section reference level minus the image-wide far-field median. A
        halo broader than the cross-section puts the reference tail inside the
        defect, so everything is measured against the wrong zero and the
        located extrema read near zero. This difference recovers that
        offset -- it is the depth of the broad defect the cross-section cannot
        see past.
        断面の参照レベルから画像全体の遠方場中央値を引いた値。断面より広い
        ハローは参照用の裾を欠陥の内部に置いてしまい、すべてが誤ったゼロ基準で
        測られて極値がほぼ 0 と読まれる。この差はそのオフセットを回収する。
        すなわち、断面では見通せない広域欠陥の深さそのものである。
    row_residual_nm
        Robust spread of the per-row background medians, i.e. the strength of
        residual horizontal stripes (line-to-line offsets). This is the defect
        `bg_method='spline1d'` with `spline1d_axis='y'` exists to remove. Read
        it against `Segmenter.global_threshold` as well: stripes above that
        level binarize as structure.
        行ごとの背景中央値の頑健なばらつき、すなわち残存する横縞（ライン間
        オフセット）の強さ。`spline1d_axis='y'` の `bg_method='spline1d'` が
        除去対象とする欠陥そのもの。これも `Segmenter.global_threshold` と
        比較して読む。しきい値を超える縞は構造として二値化される。
    col_residual_nm
        Same statistic across columns, for residual vertical stripes. The two
        are meaningful mostly as a pair: a large ratio between them identifies
        the stripe direction and therefore which `spline1d_axis` would fix it.
        列方向で取った同じ統計。残存する縦縞に対応する。両者は主として対で
        意味を持つ。比が大きければ縞の向きが分かり、したがってどの
        `spline1d_axis` が効くかが決まる。
    mask_footprint_nm
        Step in the cross-section at the fiber-mask dilation radius: the level
        inside the dilated annulus minus the level immediately beyond it.
        Over-dilating the calibrator's fiber mask excludes genuine substrate
        structure from the background pool, so the model cannot reproduce it
        and the subtraction leaves it behind -- imprinting a plateau whose
        width is the dilation radius and lifting the fiber with it. Positive
        means the mask footprint is floating its own neighborhood. `NaN` when
        the caller did not say what dilation was used, or when the method uses
        no fiber mask.
        繊維マスクの膨張半径における断面の段差。膨張した環帯の内側のレベルから
        そのすぐ外側のレベルを引いた値。補正器の繊維マスクを過剰に膨張させると
        実在する基板構造が背景プールから除外され、モデルがそれを再現できず、
        減算後にその構造が残る。結果として幅が膨張半径に等しい台地が刻まれ、
        繊維もろとも持ち上がる。正の値はマスクの足跡が自身の近傍を浮かせて
        いることを示す。呼び出し側が使用した膨張量を伝えなかった場合、または
        繊維マスクを使わない方式の場合は `NaN`。
    warnings
        Fixed English descriptions of conditions that make some metric
        unreliable or unavailable; empty when none apply.
        一部の指標が信頼できない、または算出不能となる条件を示す固定英語
        文字列。該当が無ければ空。
    """

    halo_nm: float
    halo_asymmetry_nm: float
    halo_position_px: float
    halo_wide_nm: float
    row_residual_nm: float
    col_residual_nm: float
    mask_footprint_nm: float
    warnings: Tuple[str, ...]

    def to_meta(self) -> Dict[str, object]:
        """
        Convert to a msgpack-serializable mapping for bundle vlmeta storage.
        バンドル vlmeta へ保存するための msgpack 直列化可能な辞書へ変換する。

        Returns
        -------
        dict
            Plain Python scalars and lists, matching the storage convention of
            `bundle_schema.make_spatial_calibration`.
            素の Python スカラーとリストからなる辞書。
            `bundle_schema.make_spatial_calibration` の保存流儀に合わせる。

        Notes
        -----
        Every scalar goes through `_opt_float`, so a metric that could not be
        computed on this image is stored as `None` rather than NaN. Readers
        must treat `None` as "not evaluated", never as zero: a halo of `0.0`
        means the search ran and found nothing, which is a different statement
        from the search not having been possible.
        全スカラーは `_opt_float` を通すため、この画像で算出できなかった指標は
        NaN ではなく `None` として保存される。読み取り側は `None` を「未評価」
        として扱い、決して 0 と見なしてはならない。ハローの `0.0` は探索が
        実行され何も見つからなかったことを意味し、探索自体が不可能だったことと
        は別の主張である。
        """
        return {
            "halo_nm": _opt_float(self.halo_nm),
            "halo_asymmetry_nm": _opt_float(self.halo_asymmetry_nm),
            "halo_position_px": _opt_float(self.halo_position_px),
            "halo_wide_nm": _opt_float(self.halo_wide_nm),
            "row_residual_nm": _opt_float(self.row_residual_nm),
            "col_residual_nm": _opt_float(self.col_residual_nm),
            "mask_footprint_nm": _opt_float(self.mask_footprint_nm),
            "warnings": list(self.warnings),
        }

    def format_lines(self) -> Tuple[str, ...]:
        """
        Render the metrics as fixed English log lines.
        指標を固定英語のログ行として整形する。

        Returns
        -------
        tuple of str
            One line per defect, plus one per warning. Lines whose metric could
            not be computed are omitted rather than printed as "n/a", so a log
            entry only ever shows numbers that mean something.
            欠陥ごとに 1 行、加えて警告ごとに 1 行。算出できなかった指標の行は
            "n/a" と表示せず省略するため、ログには意味のある数値だけが並ぶ。

        Notes
        -----
        These are reporting strings, not operational UI text, so they stay
        fixed English and are not wrapped with `_()`.
        これらは操作用 UI テキストではなく報告用文字列であるため、固定英語の
        まま維持し `_()` で包まない。
        """
        lines = [
            f"halo = {self.halo_nm:+.3f} nm "
            f"(asym {self.halo_asymmetry_nm:+.3f}, "
            f"at {_fmt(self.halo_position_px, '.1f')} px, "
            f"wide {self.halo_wide_nm:+.3f})",
            f"stripes = {_fmt(self.row_residual_nm)} / "
            f"{_fmt(self.col_residual_nm)} nm (row/col)",
        ]
        if np.isfinite(self.mask_footprint_nm):
            lines.append(f"mask footprint = {self.mask_footprint_nm:+.3f} nm")
        lines.extend(f"warning: {w}" for w in self.warnings)
        return tuple(lines)


def _fmt(value: float, spec: str = ".3f") -> str:
    """Format a metric, showing "n/a" where it could not be computed."""
    return "n/a" if not np.isfinite(value) else format(float(value), spec)


def _opt_float(value: Optional[float]) -> Optional[float]:
    """
    Return `value` as a float, mapping `None` and NaN alike to `None`.
    `value` を float として返し、`None` と NaN はいずれも `None` に写す。

    Notes
    -----
    NaN is the right in-memory marker for "not computed" but a poor one in
    stored metadata: it is unequal to itself, so two bundles holding identical
    metrics compare as different, and it has no JSON representation. `None`
    carries the same meaning through msgpack, comparison and export.
    NaN はメモリ上では「未算出」の印として適切だが、保存メタデータとしては
    不適切である。自分自身と等しくないため、同一の指標を持つ 2 つのバンドルが
    異なるものとして比較され、JSON 表現も持たない。`None` は同じ意味を
    msgpack・比較・エクスポートのいずれにも通す。
    """
    if value is None:
        return None
    value = float(value)
    return None if not np.isfinite(value) else value


def _mad_sigma(values: np.ndarray) -> float:
    """
    Estimate a Gaussian sigma from the median absolute deviation.
    中央絶対偏差からガウス分布の sigma を推定する。

    Notes
    -----
    Undetected fibers and scan artifacts give the residual distribution heavy
    tails, where a plain standard deviation reports the outliers rather than
    the substrate. The MAD ignores them.
    検出漏れの繊維や走査アーティファクトにより残差分布は裾が重くなり、単純な
    標準偏差では基板ではなく外れ値を報告してしまう。MAD はそれらを無視する。
    """
    if values.size == 0:
        return float("nan")
    med = np.median(values)
    return float(_MAD_TO_SIGMA * np.median(np.abs(values - med)))


def _band_indices(
    offsets: np.ndarray, lo: float, hi: float, positive: Optional[bool] = None
) -> np.ndarray:
    """
    Boolean selector for offsets whose magnitude falls in the band [lo, hi].
    絶対値が帯 [lo, hi] に入るオフセットを選ぶ真偽値セレクタ。

    Parameters
    ----------
    offsets
        Signed cross-section offsets.
        符号付き断面オフセット。
    lo, hi
        Inclusive band limits, as distances from the fiber center.
        繊維中心からの距離で表した帯の両端（両端を含む）。
    positive
        `True` selects only the +X flank, `False` only the -X flank, `None`
        both.
        `True` なら +X 側のみ、`False` なら -X 側のみ、`None` なら両側を選ぶ。
    """
    magnitude = np.abs(offsets)
    band = (magnitude >= lo) & (magnitude <= hi)
    if positive is True:
        band &= offsets > 0
    elif positive is False:
        band &= offsets < 0
    return band


def _local_normals(
    skeleton: np.ndarray, points: np.ndarray, radius: int, min_elongation: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fit the local fiber direction at each point and return its unit normal.
    各点で局所繊維方向をフィットし、その単位法線を返す。

    Parameters
    ----------
    skeleton
        Boolean skeleton mask.
        真偽値のスケルトンマスク。
    points
        Sample positions as `(N, 2)` integer `(y, x)` rows.
        `(N, 2)` の整数 `(y, x)` 行として与えるサンプル位置。
    radius
        Half-width of the square window whose skeleton pixels are fitted.
        スケルトン画素をフィットする正方窓の半幅。
    min_elongation
        Least principal-to-secondary variance ratio for an accepted fit.
        フィットを採用する主分散/副分散比の下限。

    Returns
    -------
    tuple of np.ndarray
        Unit normals as `(N, 2)` `(ny, nx)` rows, and a boolean acceptance
        mask marking the points whose direction fit was elongated enough.
        `(N, 2)` の `(ny, nx)` 行で表した単位法線と、方向フィットが十分に
        細長かった点を示す真偽値の採用マスク。

    Notes
    -----
    The normal is oriented to point along +X (ties broken toward +Y) so that
    "positive offset" means the same geometric side for every sample. Without
    a fixed convention the eigenvector sign is arbitrary and the antisymmetric
    halo would cancel across samples exactly as it does when both flanks are
    pooled.
    法線は +X 方向（同値の場合は +Y 方向）を向くよう揃え、「正のオフセット」が
    全サンプルで同じ幾何学的側面を指すようにする。規約を固定しないと固有ベクトルの
    符号は任意となり、両側をまとめた場合とまったく同様に反対称ハローが
    サンプル間で相殺されてしまう。
    """
    h, w = skeleton.shape
    offsets = np.arange(-radius, radius + 1)
    dy, dx = np.meshgrid(offsets, offsets, indexing="ij")
    dy = dy.ravel().astype(np.float64)
    dx = dx.ravel().astype(np.float64)

    ys = points[:, 0:1] + dy[None, :].astype(np.int64)
    xs = points[:, 1:2] + dx[None, :].astype(np.int64)
    inside = (ys >= 0) & (ys < h) & (xs >= 0) & (xs < w)
    weight = skeleton[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)] & inside
    weight = weight.astype(np.float64)

    count = weight.sum(axis=1)
    # Three points is the least that defines a direction with any redundancy.
    usable = count >= 3
    count_safe = np.where(usable, count, 1.0)

    mean_y = (weight * dy).sum(axis=1) / count_safe
    mean_x = (weight * dx).sum(axis=1) / count_safe
    cy = dy[None, :] - mean_y[:, None]
    cx = dx[None, :] - mean_x[:, None]
    cov_yy = (weight * cy * cy).sum(axis=1) / count_safe
    cov_xx = (weight * cx * cx).sum(axis=1) / count_safe
    cov_yx = (weight * cy * cx).sum(axis=1) / count_safe

    # Closed-form eigenvalues of the symmetric 2x2 covariance; cheaper and
    # better conditioned here than a general eigensolver over N matrices.
    # 対称 2x2 共分散の固有値を閉形式で求める。N 個の行列に汎用固有値ソルバを
    # かけるより高速で、条件も良い。
    trace = cov_yy + cov_xx
    det = cov_yy * cov_xx - cov_yx * cov_yx
    disc = np.sqrt(np.maximum(trace * trace / 4.0 - det, 0.0))
    lam1 = trace / 2.0 + disc
    lam2 = trace / 2.0 - disc

    elongated = usable & (lam2 > 0) & (lam1 >= min_elongation * lam2)
    # A perfectly straight digitized line can give lam2 == 0 exactly, which is
    # maximally elongated rather than degenerate; accept it explicitly.
    # 完全に直線的な離散線では lam2 がちょうど 0 になりうる。これは退化ではなく
    # 最も細長い状態なので、明示的に採用する。
    elongated |= usable & (lam2 <= 0) & (lam1 > 0)

    # Principal eigenvector (the tangent) of [[cov_yy, cov_yx], [cov_yx, cov_xx]].
    tangent_y = cov_yx
    tangent_x = lam1 - cov_yy
    # That form vanishes when the fiber is axis-aligned and cov_yx is zero;
    # the equivalent second form stays well conditioned there.
    # 繊維が軸に平行で cov_yx が 0 のときこの形は消えるため、そこでは条件の
    # 良い等価な第 2 の形へ切り替える。
    degenerate = np.hypot(tangent_y, tangent_x) < 1e-12
    tangent_y = np.where(degenerate, lam1 - cov_xx, tangent_y)
    tangent_x = np.where(degenerate, cov_yx, tangent_x)
    still_degenerate = np.hypot(tangent_y, tangent_x) < 1e-12
    tangent_y = np.where(still_degenerate, 1.0, tangent_y)
    tangent_x = np.where(still_degenerate, 0.0, tangent_x)
    norm = np.hypot(tangent_y, tangent_x)
    tangent_y = tangent_y / norm
    tangent_x = tangent_x / norm

    # Rotate the tangent by 90 degrees to get the cross-section direction.
    normal_y = -tangent_x
    normal_x = tangent_y
    # Fix the sign so +offset is always the same geometric side; see Notes.
    flip = (normal_x < 0) | ((normal_x == 0) & (normal_y < 0))
    normal_y = np.where(flip, -normal_y, normal_y)
    normal_x = np.where(flip, -normal_x, normal_x)

    return np.stack([normal_y, normal_x], axis=1), elongated


def _cross_sections(
    calibrated: np.ndarray,
    skeleton: np.ndarray,
    *,
    half_len: int,
    subsample: int,
    pca_radius: int,
    min_elongation: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Sample signed cross-sections perpendicular to the fiber at skeleton points.
    スケルトン上の各点で繊維に垂直な符号付き断面を標本化する。

    Parameters
    ----------
    calibrated
        Background-subtracted height image in nanometers.
        背景減算後の高さ画像 (nm)。
    skeleton
        Boolean skeleton mask supplying both the sample points and the local
        direction fit.
        サンプル点と局所方向フィットの両方を供給する真偽値スケルトンマスク。
    half_len
        Half-length of each cross-section in pixels.
        各断面の片側長さ (px)。
    subsample
        Stride applied to the skeleton pixel list.
        スケルトン画素リストに適用する間引き幅。
    pca_radius
        Window half-width for the direction fit.
        方向フィットに使う窓の半幅。
    min_elongation
        Least principal-to-secondary variance ratio for an accepted fit.
        フィットを採用する主分散/副分散比の下限。

    Returns
    -------
    tuple of np.ndarray
        Signed offsets of shape `(2 * half_len + 1,)`, and the accepted
        cross-sections of shape `(n_accepted, 2 * half_len + 1)` in nanometers.
        形状 `(2 * half_len + 1,)` の符号付きオフセットと、形状
        `(n_accepted, 2 * half_len + 1)` の採用された断面 (nm)。

    Notes
    -----
    Three rejections are applied, all derived from the skeleton alone so that
    no binarized mask is consulted: an isotropic direction fit (a crossing), a
    cross-section leaving the image, and a cross-section that runs into
    another fiber. The last is detected by sampling the skeleton distance
    field along the same line and looking for it returning to zero away from
    the origin, where the profile necessarily meets its own fiber.
    3 つの棄却規則を適用する。いずれもスケルトンのみから導かれ、二値化マスクを
    参照しない。すなわち、等方的な方向フィット（交差点）、画像外へ出る断面、
    他の繊維へ突き当たる断面である。最後のものは、同じ直線上でスケルトン距離場を
    標本化し、原点（断面が必ず自身の繊維と交わる位置）から離れた場所で 0 へ
    戻るかどうかで判定する。
    """
    offsets = np.arange(-half_len, half_len + 1, dtype=np.float64)
    ys, xs = np.nonzero(skeleton)
    if ys.size == 0:
        return offsets, np.empty((0, offsets.size), dtype=np.float64)

    points = np.stack([ys[::subsample], xs[::subsample]], axis=1)
    normals, accepted = _local_normals(
        skeleton, points, pca_radius, min_elongation
    )
    if not accepted.any():
        return offsets, np.empty((0, offsets.size), dtype=np.float64)

    points = points[accepted]
    normals = normals[accepted]

    sample_y = points[:, 0:1] + normals[:, 0:1] * offsets[None, :]
    sample_x = points[:, 1:2] + normals[:, 1:2] * offsets[None, :]

    h, w = calibrated.shape
    within = (
        (sample_y >= 0) & (sample_y <= h - 1)
        & (sample_x >= 0) & (sample_x <= w - 1)
    )
    keep = within.all(axis=1)
    if not keep.any():
        return offsets, np.empty((0, offsets.size), dtype=np.float64)
    sample_y = sample_y[keep]
    sample_x = sample_x[keep]

    coords = np.stack([sample_y.ravel(), sample_x.ravel()])
    values = map_coordinates(
        calibrated, coords, order=1, mode="nearest"
    ).reshape(sample_y.shape)

    # Reject any cross-section that runs into a different fiber, which would
    # put a second fiber's body where the substrate should be.
    # 他の繊維へ突き当たる断面を棄却する。基板であるべき位置に別の繊維の本体が
    # 入り込んでしまうためである。
    skeleton_distance = distance_transform_edt(~skeleton)
    near_skeleton = map_coordinates(
        skeleton_distance, coords, order=1, mode="nearest"
    ).reshape(sample_y.shape)
    outer = np.abs(offsets) > SELF_GUARD_PX
    clean = (near_skeleton[:, outer] >= 1.0).all(axis=1)

    return offsets, values[clean]


def _profile_reference_and_width(
    offsets: np.ndarray, profile: np.ndarray, half_len: float
) -> Tuple[float, np.ndarray, float]:
    """
    Reduce an aggregate cross-section to its reference level and fiber width.
    集約断面から参照レベルと繊維幅を求める。

    Parameters
    ----------
    offsets
        Signed cross-section offsets in pixels.
        符号付き断面オフセット (px)。
    profile
        Median height at each offset.
        各オフセットにおける高さ中央値。
    half_len
        Half-length of the cross-section, used to locate its far tail.
        断面の片側長さ。遠端の裾を特定するために使う。

    Returns
    -------
    tuple
        The reference level, the profile with that level removed, and the
        half-width at half-maximum.
        参照レベル、それを差し引いた断面、および半値半幅。

    Notes
    -----
    The reference is the median of the profile's own far tail, so the halo is
    measured without any mask-derived far-field pool. The width is taken at
    half-maximum because that is a property of the fiber core alone: a halo is
    far smaller than half the fiber height and therefore cannot move it.
    参照レベルは断面自身の遠端の裾の中央値とし、マスク由来の遠方場プールを
    使わずにハローを測る。幅を半値で取るのは、それが繊維コアのみの性質だから
    である。ハローは繊維高さの半分よりはるかに小さく、幅を動かせない。
    """
    tail = _band_indices(offsets, half_len - PROFILE_TAIL_PX, half_len)
    reference = float(np.median(profile[tail])) if tail.any() else 0.0
    centered = profile - reference

    half_width = float("nan")
    peak = float(centered.max())
    if peak > 0:
        below_half = np.abs(offsets)[centered < peak / 2.0]
        if below_half.size:
            half_width = float(below_half.min())
    if not np.isfinite(half_width):
        half_width = float(half_len) / 2.0
    return reference, centered, half_width


def _locate_halo(
    offsets: np.ndarray,
    centered: np.ndarray,
    positive: bool,
    noise_nm: float,
) -> Tuple[float, float]:
    """
    Locate the halo extremum on one flank from the profile's derivative.
    断面の微分から片側の斜面におけるハローの極値を特定する。

    Parameters
    ----------
    offsets
        Signed cross-section offsets in pixels.
        符号付き断面オフセット (px)。
    centered
        Cross-section with the reference level already removed.
        参照レベルを差し引いた断面。
    positive
        `True` to work on the +X flank, `False` on the -X flank.
        `True` なら +X 側、`False` なら -X 側を対象とする。
    noise_nm
        Noise level of the profile, used as the significance threshold.
        断面のノイズ水準。有意性判定のしきい値として使う。

    Returns
    -------
    tuple
        The extremum's signed height and its distance from the fiber center.
        `(0.0, nan)` when the flank holds no significant extremum.
        極値の符号付き高さと繊維中心からの距離。斜面に有意な極値が無い場合は
        `(0.0, nan)`。

    Notes
    -----
    Walking outward from the center, the profile descends the fiber flank, so
    the derivative is negative. The first offset at which it stops being
    negative is a turning point of the surface, and it is where the halo lives:
    for a trench the descent runs straight on into it and the turning point is
    the trench floor; for a ridge the descent stops at the ridge's base and the
    ridge crest follows. Taking the largest excursion from the turning point
    outward therefore lands on the halo in both cases.
    中心から外向きに進むと断面は繊維斜面を下るため微分は負である。微分が負で
    なくなる最初のオフセットは曲面の転回点であり、そこにハローが存在する。溝の
    場合は下降がそのまま溝へ続くので転回点が溝底そのものになり、尾根の場合は
    下降が尾根の裾で止まりその先に稜線が来る。したがって転回点から外側で最大の
    偏位を取れば、どちらの場合もハローに当たる。

    Measuring at the extremum rather than averaging a fixed band matters: a
    band placed by a rule of thumb only partly overlaps the real feature and
    dilutes it toward zero, which understates exactly the large halos that
    matter most.
    固定帯を平均するのではなく極値で測ることが重要である。経験則で置いた帯は
    実際の対象と部分的にしか重ならず 0 側へ希釈されるため、最も重要な大きな
    ハローほど過小評価される。

    One case is not separable and is reported as no halo: a *positive* halo
    close enough to the fiber only makes the flank decay more slowly, leaving
    the profile monotone with no feature distinguishing halo from fiber tail.
    Recovering it would need an assumed fiber shape. `mask_footprint_nm` and
    `halo_wide_nm` cover the systematic versions of that case.
    分離できず「ハロー無し」と報告される場合が 1 つある。繊維に十分近い*正の*
    ハローは斜面の減衰を緩やかにするだけで、プロファイルは単調なままとなり、
    ハローと繊維裾を区別する特徴が現れない。これを復元するには繊維形状の仮定が
    必要になる。その系統的なケースは `mask_footprint_nm` と `halo_wide_nm` が
    カバーする。
    """
    side = offsets > 0 if positive else offsets < 0
    if side.sum() < 3:
        return 0.0, float("nan")

    # Re-order the flank so the index increases with distance from the center,
    # which makes "outward" the direction of the derivative.
    # 中心からの距離が増える向きに斜面を並べ替え、微分の向きが「外向き」に
    # 一致するようにする。
    order = np.argsort(np.abs(offsets[side]))
    distances = np.abs(offsets[side])[order]
    values = centered[side][order]
    slope = np.gradient(values)

    descending = slope < 0
    turn = int(np.argmin(descending)) if not descending.all() else values.size
    if turn >= values.size - 1:
        # The profile never stopped descending inside the sampled range.
        return 0.0, float("nan")

    outward = values[turn:]
    peak_index = int(np.argmax(np.abs(outward)))
    value = float(outward[peak_index])
    if abs(value) < HALO_SIGNIFICANCE_SIGMA * noise_nm:
        return 0.0, float("nan")
    return value, float(distances[turn + peak_index])


def _mask_footprint(
    offsets: np.ndarray,
    centered: np.ndarray,
    flank_end: float,
    dilation_px: int,
) -> float:
    """
    Measure the step the fiber mask's dilation radius leaves in the profile.
    繊維マスクの膨張半径が断面に残す段差を測る。

    Parameters
    ----------
    offsets
        Signed cross-section offsets in pixels.
        符号付き断面オフセット (px)。
    centered
        Cross-section with the reference level already removed.
        参照レベルを差し引いた断面。
    flank_end
        Distance at which the fiber core is taken to have ended, i.e. where
        the dilated annulus starts.
        繊維コアが終わったとみなす距離。すなわち膨張した環帯の始まり。
    dilation_px
        Dilation radius the calibrator applied to its fiber mask.
        補正器が繊維マスクへ適用した膨張半径。

    Returns
    -------
    float
        Inside-annulus level minus the level immediately beyond it, or `NaN`
        when either band falls outside the sampled range.
        環帯内側のレベルからそのすぐ外側のレベルを引いた値。いずれかの帯が
        標本化範囲の外に出る場合は `NaN`。

    Notes
    -----
    The dilation radius is where the defect's edge must be if the mask caused
    it, which is what makes this a targeted test rather than a search: the
    excluded region reaches exactly that far, so background structure is erased
    exactly that far and no further. Comparing across that radius separates a
    mask artifact from a genuine feature of the sample, which has no reason to
    change at a radius set by a processing parameter.
    マスクが原因であれば欠陥の縁は必ず膨張半径にある。これが本測定を探索では
    なく的を絞った検定にしている。除外領域はちょうどそこまで届き、背景構造も
    ちょうどそこまでが消され、それ以上は消されないからである。この半径を跨いで
    比較することで、マスク由来のアーティファクトと試料本来の構造を切り分けら
    れる。後者が処理パラメータで決まる半径で変化する理由は無い。
    """
    if dilation_px <= 0:
        return float("nan")

    inner = _band_indices(offsets, flank_end, flank_end + dilation_px)
    outer = _band_indices(
        offsets, flank_end + dilation_px, flank_end + 2 * dilation_px
    )
    if not inner.any() or not outer.any():
        return float("nan")
    if (flank_end + 2 * dilation_px) > np.abs(offsets).max():
        return float("nan")
    return float(np.median(centered[inner]) - np.median(centered[outer]))


def _required_half_len(
    half_width: float, image_shape: Tuple[int, int], dilation_px: int
) -> int:
    """
    Half-length a cross-section needs to hold the halo band plus a tail.
    ハロー帯と裾を収めるために断面が必要とする片側長さ。

    Parameters
    ----------
    half_width
        Measured half-width at half-maximum of the fiber.
        実測した繊維の半値半幅。
    image_shape
        Shape of the image, which caps how long a cross-section may get.
        画像の形状。断面の長さの上限を決める。
    dilation_px
        Fiber-mask dilation radius, whose footprint bands reach twice as far as
        the radius itself and so can dominate the required length.
        繊維マスクの膨張半径。その足跡帯は半径の 2 倍まで届くため、必要長を
        支配しうる。

    Returns
    -------
    int
        Required half-length in pixels, clipped to the image-derived ceiling.
        必要な片側長さ (px)。画像由来の上限で頭打ちにする。

    Notes
    -----
    The length must cover whichever reaches further, the fiber core plus room
    for the halo beyond it or the two mask-footprint bands, and then leave a
    gap before the reference tail. Scaling with the measured width is what
    makes the sampled range follow the sample: a fixed length silently puts the
    features of a wide fiber outside the range that was actually sampled.
    断面長は、繊維コアとその外側のハロー用の余地か、マスク足跡の 2 つの帯か、
    より遠くまで届くほうを覆い、さらに参照裾との間隔を残す必要がある。実測幅に
    比例させることで標本化範囲が試料に追従する。固定長では、太い繊維の対象が
    実際に標本化した範囲の外へ黙って出てしまう。
    """
    flank_end = FLANK_END_FACTOR * half_width
    needed = (
        max(flank_end + PROFILE_TAIL_MARGIN_PX, flank_end + 2 * max(dilation_px, 0))
        + PROFILE_TAIL_MARGIN_PX
    )
    ceiling = max(
        PROFILE_HALF_LEN_PX, min(image_shape) // PROFILE_MAX_LEN_FRACTION
    )
    return int(min(np.ceil(needed), ceiling))


def _line_residual(values: np.ndarray, background: np.ndarray, axis: int) -> float:
    """
    Robust spread of the per-line background medians along one axis.
    1 軸に沿ったライン単位の背景中央値の頑健なばらつき。

    Parameters
    ----------
    values
        Calibrated height image.
        補正済み高さ画像。
    background
        True where the pixel is background.
        背景画素で True となるマスク。
    axis
        0 to take one median per row, 1 to take one median per column.
        0 なら行ごと、1 なら列ごとに中央値を取る。

    Returns
    -------
    float
        MAD-based sigma over the per-line medians, in nanometers.
        ライン単位中央値に対する MAD ベースの sigma (nm)。

    Notes
    -----
    Lines are dropped rather than filled when they hold no background pixel,
    so a fiber crossing the full width does not pull the series toward zero.
    背景画素を 1 つも持たないラインは補完せず除外する。全幅を横切る繊維が
    系列を 0 側へ引っ張るのを防ぐためである。
    """
    masked = np.where(background, values, np.nan)
    with warnings_module.catch_warnings():
        # A line fully covered by fiber is an all-NaN slice; NumPy warns and
        # returns NaN, which is the wanted outcome since it is dropped below.
        warnings_module.simplefilter("ignore", RuntimeWarning)
        line_medians = np.nanmedian(masked, axis=1 - axis)
    line_medians = line_medians[np.isfinite(line_medians)]
    return _mad_sigma(line_medians)


def evaluate_background(
    calibrated: np.ndarray,
    binarized: np.ndarray,
    skeletonized: np.ndarray,
    *,
    exclusion_mask: Optional[np.ndarray] = None,
    mask_dilation: int = 3,
    bg_mask_dilation_px: Optional[int] = None,
    profile_half_len_px: int = PROFILE_HALF_LEN_PX,
    skeleton_subsample: int = SKELETON_SUBSAMPLE,
) -> BgQuality:
    """
    Score how well the background was estimated for one processed image.
    処理済み画像 1 枚について背景推定の良否を採点する。

    Parameters
    ----------
    calibrated
        Background-subtracted height image in nanometers.
        背景減算後の高さ画像 (nm)。
    binarized
        Segmenter output, used only to decide which pixels are substrate for
        the stripe residual. The halo metrics never consult it.
        Segmenter の出力。縞残差でどの画素が基板かを決めるためだけに使う。
        ハロー指標はこれを一切参照しない。
    skeletonized
        Skeleton mask supplying the cross-section sample points and the local
        fiber directions.
        断面のサンプル点と局所繊維方向を供給するスケルトンマスク。
    exclusion_mask
        Explicit substrate exclusion mask overriding `binarized` plus
        dilation. Pass the union of the masks from every run being compared so
        that the stripe residual of all methods is computed over one identical
        pixel set.
        `binarized` と膨張処理に代わる明示的な基板除外マスク。比較対象の全実行の
        マスクの和集合を渡すと、全方式の縞残差が同一の画素集合で計算される。
    mask_dilation
        Pixels by which `binarized` is dilated when `exclusion_mask` is not
        given, so that sub-threshold fiber flank does not enter the background
        pool.
        `exclusion_mask` 未指定時に `binarized` を膨張させる画素数。しきい値
        以下の繊維斜面が背景プールへ混入しないようにする。
    bg_mask_dilation_px
        Dilation radius the *calibrator* applied to its own fiber mask, i.e.
        `ProcParams.mask_dilation`, needed to know where the mask footprint
        would be. This is a different quantity from `mask_dilation` above,
        which only grows the substrate mask used here for the stripe residual.
        Pass `None` for a method that builds no fiber mask (`tophat`), which
        leaves `mask_footprint_nm` unset.
        *補正器* が自身の繊維マスクへ適用した膨張半径。すなわち
        `ProcParams.mask_dilation` で、マスク足跡がどこに現れるかを知るために
        必要となる。上の `mask_dilation` とは別の量であり、そちらは本モジュール
        が縞残差に使う基板マスクを広げるだけである。繊維マスクを構築しない
        方式 (`tophat`) では `None` を渡す。この場合 `mask_footprint_nm` は
        未設定のままとなる。
    profile_half_len_px
        Starting half-length of each perpendicular cross-section. It grows
        automatically with the measured fiber half-width and the mask dilation
        radius, so this is a floor rather than a fixed length. The ceiling
        comes from the image size.
        各垂直断面の片側長さの初期値。実測した繊維半値半幅とマスク膨張半径に
        応じて自動的に拡張されるため、これは固定長ではなく下限として働く。
        上限は画像サイズから決まる。
    skeleton_subsample
        Stride applied to the skeleton pixel list when choosing sample points.
        サンプル点を選ぶ際にスケルトン画素リストへ適用する間引き幅。

    Returns
    -------
    BgQuality
        The metric set, with `warnings` naming any metric that could not be
        computed on this image.
        指標一式。この画像で算出できなかった指標があれば `warnings` に記載
        される。

    Raises
    ------
    ValueError
        If the input arrays do not all share one shape.

    Notes
    -----
    Read-only: no input array is modified, and nothing here feeds back into
    the analysis, so enabling the metrics cannot change pipeline output.
    読み取り専用。入力配列を一切変更せず、結果が解析へ戻ることもないため、
    本指標を有効にしてもパイプラインの出力は変化しない。
    """
    calibrated = np.asarray(calibrated, dtype=np.float64)
    mask = np.asarray(binarized).astype(bool)
    skeleton = np.asarray(skeletonized).astype(bool)
    shapes = {calibrated.shape, mask.shape, skeleton.shape}
    if len(shapes) != 1:
        raise ValueError(
            f"evaluate_background requires one common shape, got {sorted(shapes)}"
        )

    notes: List[str] = []

    # ===== Substrate exclusion mask and the image-wide far-field level =====
    # Resolved before the halo metrics because the cross-section's own tail has
    # to be checked against a level measured over the whole image: a halo wider
    # than the cross-section moves that tail with it, and only an independent
    # reference can reveal it.
    # ハロー指標より先に解決する。断面自身の裾は画像全体で測ったレベルと照合
    # する必要があるためである。断面より広いハローは裾ごと動かしてしまい、
    # 独立した基準でなければそれを露見させられない。
    if exclusion_mask is not None:
        excluded = np.asarray(exclusion_mask).astype(bool)
        if excluded.shape != calibrated.shape:
            raise ValueError(
                f"exclusion_mask shape {excluded.shape} does not match "
                f"image shape {calibrated.shape}"
            )
    elif mask_dilation > 0 and mask.any():
        # Grow the mask with a Chebyshev-distance test rather than a
        # convolution so this module needs no OpenCV dependency.
        # 畳み込みではなくチェビシェフ距離判定でマスクを膨張させ、本モジュール
        # が OpenCV に依存しないようにする。
        excluded = distance_transform_edt(~mask) <= mask_dilation
    else:
        excluded = mask

    if float(excluded.mean()) > MAX_TRUSTED_COVERAGE:
        notes.append(WARN_HIGH_COVERAGE)
    is_background = ~excluded

    if excluded.any():
        far = distance_transform_edt(~excluded) > FAR_PX
    else:
        far = np.ones_like(mask, dtype=bool)
    if not far.any():
        notes.append(WARN_NO_FAR_BACKGROUND)
        bg_offset = float("nan")
    else:
        bg_offset = float(np.median(calibrated[far]))

    # ===== Halo metrics: skeleton-anchored, no binarized mask involved =====
    halo = asymmetry = float("nan")
    halo_position = halo_wide = footprint = float("nan")

    if not skeleton.any():
        notes.append(WARN_NO_SKELETON)
    else:
        # The length a cross-section needs depends on the fiber width, which is
        # only known once a cross-section has been taken. Start from the
        # requested length, measure, and re-sample if the features and their
        # reference tail do not fit. Fibers wide enough to need this are the
        # exact case a fixed length gets wrong, silently.
        # 断面に必要な長さは繊維幅に依存するが、その幅は断面を取って初めて
        # 分かる。指定された長さから始めて幅を測り、対象と参照用の裾が収まら
        # なければ取り直す。これを必要とするほど太い繊維こそ、固定長が黙って
        # 誤る場合そのものである。
        dilation = 0 if bg_mask_dilation_px is None else int(bg_mask_dilation_px)
        half_len = int(profile_half_len_px)
        offsets = sections = profile = centered = None
        reference = half_width = float("nan")
        for _attempt in range(MAX_PROFILE_EXPANSIONS):
            offsets, sections = _cross_sections(
                calibrated,
                skeleton,
                half_len=half_len,
                subsample=max(1, skeleton_subsample),
                pca_radius=PCA_RADIUS_PX,
                min_elongation=MIN_ELONGATION,
            )
            if sections.shape[0] == 0:
                break
            profile = np.median(sections, axis=0)
            reference, centered, half_width = _profile_reference_and_width(
                offsets, profile, half_len
            )
            needed = _required_half_len(half_width, calibrated.shape, dilation)
            if needed <= half_len:
                break
            half_len = needed
        # Running out of attempts is not itself a problem and is deliberately
        # not warned about. Lengthening the cross-section pushes its reference
        # tail further into open substrate, which nudges the measured width up
        # a little each time, so the request can keep creeping by a pixel or
        # two without ever settling. What matters is only whether the features
        # ended up inside the sampled range, which is checked below.
        # 試行回数を使い切ること自体は問題ではないため、意図的に警告しない。
        # 断面を伸ばすと参照用の裾がより開けた基板へ入るため、測定される幅が
        # 毎回わずかに上がり、要求長が 1〜2 px ずつ増え続けて収束しないことが
        # ある。重要なのは対象が標本化範囲に収まったかどうかだけで、それは下で
        # 判定する。

        n_profiles = int(sections.shape[0])
        if n_profiles == 0:
            notes.append(WARN_NO_PROFILES)
        else:
            if n_profiles < MIN_TRUSTED_PROFILES:
                notes.append(WARN_FEW_PROFILES)
            flank_end = half_width * FLANK_END_FACTOR

            if flank_end + 2 * dilation > half_len \
                    and WARN_PROFILE_TRUNCATED not in notes:
                # The image-derived ceiling stopped the expansion short, so say
                # so rather than reporting features never fully sampled as if
                # they had been.
                # 画像由来の上限により拡張が届かなかった。完全に標本化していない
                # 対象を、あたかも測ったかのように報告せず明示する。
                notes.append(WARN_PROFILE_TRUNCATED)

            # Smooth before differentiating: a single-sample wobble would put a
            # sign change in the derivative and invent a turning point.
            # 微分の前に平滑化する。1 サンプルのぶれが微分に符号反転を生み、
            # 転回点を捏造してしまうためである。
            smoothed = np.convolve(
                centered,
                np.ones(PROFILE_SMOOTH_PX) / PROFILE_SMOOTH_PX,
                mode="same",
            )

            # Significance threshold for a located extremum. The tail's own
            # scatter is the direct estimate, floored by the sampling
            # uncertainty of the median profile so an unusually flat stretch of
            # tail cannot drive the threshold to zero and let noise through.
            # 特定された極値に対する有意性しきい値。直接の推定値は裾自身の
            # ばらつきだが、集約断面の中央値の標本誤差で下限を与える。裾が異常に
            # 平坦だった場合にしきい値が 0 へ潰れ、ノイズを通すのを防ぐ。
            tail = _band_indices(offsets, half_len - PROFILE_TAIL_PX, half_len)
            if tail.any():
                per_section = _mad_sigma(sections[:, tail].ravel())
                standard_error = (
                    _MEDIAN_SE_FACTOR * per_section / max(np.sqrt(n_profiles), 1.0)
                )
                profile_noise = max(_mad_sigma(centered[tail]), standard_error)
            else:
                per_section = profile_noise = 0.0

            value_plus, position_plus = _locate_halo(
                offsets, smoothed, True, profile_noise
            )
            value_minus, position_minus = _locate_halo(
                offsets, smoothed, False, profile_noise
            )
            halo = (value_plus + value_minus) / 2.0
            asymmetry = value_plus - value_minus
            positions = [p for p in (position_plus, position_minus) if np.isfinite(p)]
            halo_position = float(np.mean(positions)) if positions else float("nan")

            # A halo broader than the cross-section drags the reference tail
            # into itself, so the located extrema read near zero. The image-wide
            # far field is measured independently and still sits on substrate,
            # so their difference is the depth of that broad defect.
            # 断面より広いハローは参照用の裾を自身の内部へ引き込むため、特定
            # される極値はほぼ 0 と読まれる。画像全体の遠方場は独立に測られて
            # おり依然として基板上にあるので、両者の差が広域欠陥の深さになる。
            #
            # Judged against the surface's own measurement noise, not against
            # the sampling error used for the extremum. Both levels here are
            # averages over enough pixels that a hundredth of a nanometer is
            # statistically significant, yet a background level that far off
            # changes no downstream threshold.
            # 極値に用いた標本誤差ではなく、曲面自身の測定ノイズを基準に判定
            # する。ここで比較する 2 つのレベルはいずれも十分な画素数の平均で
            # あり、0.01 nm 単位の差でも統計的には有意になるが、その程度の
            # 背景レベルのずれは下流のどのしきい値も変えない。
            if np.isfinite(reference) and np.isfinite(bg_offset):
                halo_wide = float(reference - bg_offset)
                if abs(halo_wide) > HALO_SIGNIFICANCE_SIGMA * per_section:
                    notes.append(WARN_WIDE_HALO)

            footprint = _mask_footprint(offsets, centered, flank_end, dilation)

    # ===== Stripe residual over background pixels =====
    row_residual = _line_residual(calibrated, is_background, axis=0)
    col_residual = _line_residual(calibrated, is_background, axis=1)

    return BgQuality(
        halo_nm=float(halo),
        halo_asymmetry_nm=float(asymmetry),
        halo_position_px=float(halo_position),
        halo_wide_nm=float(halo_wide),
        row_residual_nm=float(row_residual),
        col_residual_nm=float(col_residual),
        mask_footprint_nm=float(footprint),
        warnings=tuple(notes),
    )
