# -*- coding: utf-8 -*-
"""
Pairwise comparison of grouped fiber-morphology samples.
グループ化されたファイバー形態標本の 2 群間比較。

Reporting that two samples "look different" from their medians alone leaves
the reader to guess whether the difference exceeds the spread. This module
supplies the two things that turn a described difference into a comparable
one: a test of whether the groups are distinguishable at all, and an effect
size saying how large the separation is independently of sample size.
中央値だけを見て「違って見える」と述べるのでは、その差がばらつきを超えている
のかどうかの判断を読み手に委ねてしまう。本モジュールは、記述された差を比較可能
にするための 2 つを提供する。すなわち、群が区別できるかどうかの検定と、標本数に
依存せず隔たりの大きさを表す効果量である。

Both tests are rank-based and distribution-free, because fiber morphology
distributions are right-skewed and a t-test's normality assumption does not
hold for them.
どちらの検定も順位に基づくノンパラメトリック検定である。ファイバー形態の分布は
右に裾を引いており、t 検定が仮定する正規性が成り立たないためである。

The samples handed in must be independent observations. Skeleton pixels
pooled from whole images are not: a long fiber contributes more pixels than a
short one and neighbouring pixels of one fiber repeat the same object, so a
p-value computed over them reflects the pixel count rather than the specimen.
Choosing what one sample is remains the caller's responsibility.
渡す標本は独立観測でなければならない。画像全体から集めた骨格画素はそうではない。
長いファイバーほど多くの画素を出し、同一ファイバーの隣接画素は同じ対象の
繰り返しであるため、それらに対する p 値は試料ではなく画素数を反映してしまう。
1 標本を何とするかの決定は呼び出し側の責任である。
"""

# ===== Standard library =====
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from math import comb
from typing import List, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# Effect-size magnitude labels and their |delta| thresholds (Romano et al.,
# 2006), reported verbatim, so they stay fixed English like every other
# exported label in this project.
# 効果量の大きさラベルと |delta| のしきい値（Romano et al., 2006）。そのまま
# 出力されるため、本プロジェクトの他の出力ラベルと同様に固定英語とする。
MAGNITUDE_THRESHOLDS = (
    (0.147, "negligible"),
    (0.330, "small"),
    (0.474, "medium"),
)
MAGNITUDE_LARGE = "large"

# Below this many observations a rank test says nothing useful, so the pair is
# reported as not computed rather than given a meaningless p-value.
# これ未満の観測数では順位検定は何も語らないため、無意味な p 値を与えるのでは
# なく「計算せず」として報告する。
MIN_SAMPLES_FOR_TEST = 3

# Pairs that can be split into at most this many arrangements are tested by
# counting every arrangement. That count is exact with tied values, where
# scipy's Mann-Whitney turns to its normal approximation and its KS test treats
# the data as untied; small groups are where that matters, because there a
# p-value sits close to the level. Ten against ten makes 184,756 arrangements.
# 並べ方がこの数以下のペアは、全ての並べ方を数えて検定する。この数え上げは
# 同順位があっても厳密である。scipy の Mann-Whitney は同順位があると正規近似に
# 切り替わり、KS 検定は同順位が無いものとして扱う。それが問題になるのは小さな
# 群であり、そこでは p 値が有意水準の近くにある。10 対 10 では 184,756 通りになる。
_EXACT_ARRANGEMENT_LIMIT = 100_000


@dataclass(frozen=True)
class PairComparison:
    """
    Result of comparing one pair of groups.
    1 組のグループ間比較の結果。

    Attributes
    ----------
    group_a
        Name of the first group.
        1 つ目のグループ名。
    group_b
        Name of the second group.
        2 つ目のグループ名。
    n_a
        Number of observations in the first group.
        1 つ目のグループの観測数。
    n_b
        Number of observations in the second group.
        2 つ目のグループの観測数。
    mannwhitney_p
        Two-sided Mann-Whitney U p-value, or NaN when not computed.
        両側 Mann-Whitney U 検定の p 値。計算しなかった場合は NaN。
    mannwhitney_p_adjusted
        Same p-value after Holm correction across all pairs.
        全ペアにまたがる Holm 補正後の同 p 値。
    ks_p
        Two-sided two-sample Kolmogorov-Smirnov p-value, or NaN.
        両側 2 標本 Kolmogorov-Smirnov 検定の p 値。計算しない場合は NaN。
    ks_p_adjusted
        Same p-value after Holm correction across all pairs.
        全ペアにまたがる Holm 補正後の同 p 値。
    cliffs_delta
        Effect size in [-1, 1]; positive means group A tends to exceed B.
        [-1, 1] の効果量。正なら A が B を上回る傾向。
    magnitude
        Interpretation label for `cliffs_delta`.
        `cliffs_delta` の解釈ラベル。
    min_attainable_p
        Smallest p-value either test returns at these sample sizes, reached
        when the two groups do not overlap at all and hold no tied values;
        NaN when the pair was not tested. A pair whose value is above the
        significance level cannot reject at it however far apart the groups
        are, so a non-significant result there says nothing about whether
        they differ. For a pair tested by counting arrangements, tied values
        cannot bring two groups of equal size below it, while two groups of
        unequal size can fall to half of it (see `_min_attainable_p`).
        この標本数でどちらかの検定が返しうる最小の p 値。2 群がまったく重ならず、
        同じ値を含まないときに達する。未検定のペアでは NaN。この値が有意水準を
        上回るペアは、群がどれほど離れていてもその水準で棄却できないため、そこでの
        「有意差なし」は差の有無について何も言っていない。並べ方を数えて検定する
        ペアでは、同順位があっても同じ大きさの 2 群はこの値を下回らず、大きさの違う
        2 群はその半分まで下がりうる（`_min_attainable_p` 参照）。

    Notes
    -----
    Two tests are reported because they answer different questions. The
    Mann-Whitney U test detects a shift in location, while the
    Kolmogorov-Smirnov test responds to any difference in distribution shape,
    including two samples with the same median but different spread. A pair
    that separates on one and not the other is informative, not contradictory.
    2 つの検定を報告するのは、両者が別の問いに答えるためである。Mann-Whitney U
    は位置のずれを検出し、Kolmogorov-Smirnov は分布形状の任意の差に反応する
    （中央値が同じでばらつきが異なる 2 標本を含む）。片方だけで分離するペアは
    矛盾ではなく、それ自体が情報である。
    """

    group_a: str
    group_b: str
    n_a: int
    n_b: int
    mannwhitney_p: float
    mannwhitney_p_adjusted: float
    ks_p: float
    ks_p_adjusted: float
    cliffs_delta: float
    magnitude: str
    min_attainable_p: float = float("nan")


def _exact_pvalues(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
    """
    Return exact two-sided Mann-Whitney U and KS p-values by full enumeration.
    全ての並べ方を数え上げ、厳密な両側 Mann-Whitney U と KS の p 値を返す。

    Parameters
    ----------
    a
        First sample, finite values only.
        1 つ目の標本。有限値のみ。
    b
        Second sample, finite values only.
        2 つ目の標本。有限値のみ。

    Returns
    -------
    tuple of float
        ``(mannwhitney_p, ks_p)``: the share of all ways of assigning the
        pooled values to groups of these sizes whose statistic is at least as
        extreme as the observed one.
        ``(mannwhitney_p, ks_p)``。合併した値をこの大きさの 2 群に割り振る全ての
        方法のうち、統計量が観測値と同じかそれ以上に極端なものの割合。

    Notes
    -----
    This is the permutation test of each statistic, conditional on the values
    observed, so it is exact whether or not they are tied. The two-sided
    Mann-Whitney statistic is ``|U - n_a n_b / 2|``; the KS statistic is the
    largest gap between the two empirical distribution functions, read only
    at the end of each run of equal values, where both functions step. Both
    are compared on an integer scale (twice U, and ``n_a n_b`` times the gap)
    so equal statistics compare equal. Without tied values the result equals
    scipy's exact methods.
    各統計量の並べ替え検定であり、観測された値を条件とするため、同順位の有無に
    かかわらず厳密である。両側 Mann-Whitney の統計量は ``|U - n_a n_b / 2|``、
    KS の統計量は 2 つの経験分布関数の差の最大値であり、両関数が段を上がる、
    等しい値の連なりの終わりでのみ読む。どちらも整数の尺度（U の 2 倍、差の
    ``n_a n_b`` 倍）で比べ、等しい統計量が等しく比較されるようにする。同順位が
    無ければ、結果は scipy の厳密法と一致する。
    """
    from scipy.stats import rankdata

    n_a, n_b = a.size, b.size
    pooled = np.concatenate([a, b])
    n = pooled.size
    # Row 0 is the observed split: the first n_a pooled values form group A.
    # 0 行目が観測された分け方であり、合併した値の先頭 n_a 個が群 A になる。
    members = np.fromiter(
        (i for split in combinations(range(n), n_a) for i in split),
        dtype=np.intp,
    ).reshape(-1, n_a)

    # Midranks are multiples of one half, so twice them are integers.
    # 中間順位は 1/2 の倍数なので、その 2 倍は整数になる。
    rank2 = np.rint(2.0 * rankdata(pooled)).astype(np.int64)
    u2 = rank2[members].sum(axis=1) - n_a * (n_a + 1)
    u_stat = np.abs(u2 - n_a * n_b)

    order = np.argsort(pooled, kind="stable")
    ordered = pooled[order]
    run_ends = np.flatnonzero(np.r_[ordered[1:] != ordered[:-1], True])
    in_a = np.zeros((members.shape[0], n), dtype=bool)
    np.put_along_axis(in_a, members, True, axis=1)
    count_a = np.cumsum(in_a[:, order], axis=1)[:, run_ends]
    count_b = (run_ends + 1) - count_a
    d_stat = np.abs(count_a * n_b - count_b * n_a).max(axis=1)

    return (float(np.mean(u_stat >= u_stat[0])),
            float(np.mean(d_stat >= d_stat[0])))


def _pair_pvalues(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
    """
    Return the two-sided Mann-Whitney U and KS p-values of one pair.
    1 組の両側 Mann-Whitney U と KS の p 値を返す。

    Parameters
    ----------
    a
        First sample.
        1 つ目の標本。
    b
        Second sample.
        2 つ目の標本。

    Returns
    -------
    tuple of float
        ``(mannwhitney_p, ks_p)``; either is NaN when it cannot be computed.
        ``(mannwhitney_p, ks_p)``。計算できないものは NaN。

    Notes
    -----
    A pair with at most `_EXACT_ARRANGEMENT_LIMIT` arrangements is tested by
    `_exact_pvalues`; a larger one by `scipy.stats.mannwhitneyu`, whose
    p-value carries a tie correction, and `scipy.stats.ks_2samp`.
    並べ方が `_EXACT_ARRANGEMENT_LIMIT` 以下のペアは `_exact_pvalues` で、それより
    大きいペアは同順位補正つきの `scipy.stats.mannwhitneyu` と
    `scipy.stats.ks_2samp` で検定する。
    """
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        return float("nan"), float("nan")
    if comb(a.size + b.size, a.size) <= _EXACT_ARRANGEMENT_LIMIT:
        return _exact_pvalues(a, b)

    from scipy.stats import ks_2samp, mannwhitneyu

    try:
        u_p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
    except Exception:
        # Degenerate input (for example two constant samples) leaves the
        # pair reported as not tested rather than aborting the whole
        # comparison table.
        # 退化した入力（例: 定数の 2 標本）では、比較表全体を中断せず、
        # そのペアを未検定として報告する。
        u_p = float("nan")
    try:
        ks_p = float(ks_2samp(a, b).pvalue)
    except Exception:
        ks_p = float("nan")
    return u_p, ks_p


@lru_cache(maxsize=None)
def _min_attainable_p(n_a: int, n_b: int) -> float:
    """
    Return the smallest p-value either test can return at these sample sizes.
    この標本数でどちらかの検定が返しうる最小の p 値を返す。

    Parameters
    ----------
    n_a
        Number of observations in the first group.
        1 つ目のグループの観測数。
    n_b
        Number of observations in the second group.
        2 つ目のグループの観測数。

    Returns
    -------
    float
        The smaller of the Mann-Whitney U and Kolmogorov-Smirnov p-values for
        two samples of these sizes that do not overlap and hold no tied
        values.
        これらの大きさで、重ならず同じ値も含まない 2 標本に対する Mann-Whitney U
        と Kolmogorov-Smirnov の p 値のうち小さい方。

    Notes
    -----
    Complete separation is the most extreme arrangement both rank statistics
    can take, so the tests are run on it rather than on a formula: the value
    then follows the method `_pair_pvalues` uses at these sizes.
    完全な分離は両方の順位統計量がとりうる最も極端な並びであるため、式ではなく
    その並びに対して検定を実行する。こうすると値は、`_pair_pvalues` がこの標本数で
    使う方法に従う。

    When the arrangements are counted, both separated arrangements -- A
    entirely below B and entirely above it -- are as extreme as each other,
    so the value is 2 / C(n_a + n_b, n_a). Swapping the groups' labels leaves
    both statistics unchanged when the groups are the same size, so no data
    of equal sizes, tied or not, gets below it. With unequal sizes, tied
    values can leave the observed split the only one that extreme, and the
    p-value then reaches 1 / C(n_a + n_b, n_a): three equal values against
    four other equal values give 0.029, where untied samples cannot get
    below 0.057.
    並べ方を数える場合、分離した 2 つの並び（A が B より全て下、全て上）は同じだけ
    極端なので、値は 2 / C(n_a + n_b, n_a) となる。2 群が同じ大きさなら、群の
    ラベルを入れ替えても両統計量は変わらないため、同順位の有無にかかわらず、同じ
    大きさのデータはこれを下回らない。大きさが違うと、同順位によって観測された
    分け方だけがその極端さになることがあり、p 値は 1 / C(n_a + n_b, n_a) に
    達する。等しい 3 値対 別の等しい 4 値では 0.029 となり、同順位の無い標本は
    0.057 を下回れない。

    Beyond `_EXACT_ARRANGEMENT_LIMIT` the value is scipy's for separated
    samples, which tied samples can undercut through its approximations; it
    is then far below any conventional significance level.
    `_EXACT_ARRANGEMENT_LIMIT` を超えると値は分離した標本に対する scipy の値で
    あり、同順位のある標本はその近似によってこれを下回りうる。その場合の値は
    通常のどの有意水準よりもはるかに小さい。

    Examples
    --------
    >>> from lib.group_compare import _min_attainable_p
    >>> round(_min_attainable_p(3, 3), 3), round(_min_attainable_p(4, 4), 4)
    (0.1, 0.0286)
    """
    a = np.arange(n_a, dtype=float)
    b = np.arange(n_a, n_a + n_b, dtype=float)
    return min(_pair_pvalues(a, b))


def delta_magnitude(delta: float) -> str:
    """
    Return the interpretation label for a Cliff's delta value.
    Cliff's delta の値に対する解釈ラベルを返す。

    Parameters
    ----------
    delta
        Effect size in [-1, 1]; only its magnitude is used.
        [-1, 1] の効果量。絶対値のみを使う。

    Returns
    -------
    str
        One of the labels in `MAGNITUDE_THRESHOLDS` or `MAGNITUDE_LARGE`; an
        empty string for a NaN input.
        `MAGNITUDE_THRESHOLDS` または `MAGNITUDE_LARGE` のいずれかのラベル。
        入力が NaN の場合は空文字列。

    Notes
    -----
    The thresholds are those of [Romano2006]_.
    しきい値は [Romano2006]_ による。

    References
    ----------
    .. [Romano2006] J. Romano, J. D. Kromrey, J. Coraggio and J. Skowronek,
       "Appropriate statistics for ordinal level data," Annual meeting of the
       Florida Association of Institutional Research, 2006.

    Examples
    --------
    >>> from lib.group_compare import delta_magnitude
    >>> [delta_magnitude(d) for d in (0.1, -0.2, 0.4, 0.9)]
    ['negligible', 'small', 'medium', 'large']
    >>> delta_magnitude(float("nan"))
    ''
    """
    if not np.isfinite(delta):
        return ""
    magnitude = abs(float(delta))
    for threshold, label in MAGNITUDE_THRESHOLDS:
        if magnitude < threshold:
            return label
    return MAGNITUDE_LARGE


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """
    Return Cliff's delta, the rank-based effect size between two samples.
    2 標本間の順位ベース効果量である Cliff's delta を返す。

    Parameters
    ----------
    a
        First sample.
        1 つ目の標本。
    b
        Second sample.
        2 つ目の標本。

    Returns
    -------
    float
        ``P(a > b) - P(a < b)`` in [-1, 1], or NaN when either sample is
        empty. Zero means the two samples overlap symmetrically; ±1 means
        every value of one exceeds every value of the other.
        ``P(a > b) - P(a < b)``（[-1, 1]）。どちらかの標本が空なら NaN。0 は
        2 標本が対称に重なることを、±1 は一方の全値が他方の全値を上回ることを
        意味する。

    Notes
    -----
    Reported alongside the p-values because a rank test's significance grows
    with sample size while this does not: with a few hundred fibers per group
    a negligible separation still reaches a small p-value, and the effect size
    is what distinguishes "detectable" from "large".
    p 値と併せて報告する。順位検定の有意性は標本数とともに増大するが、この値は
    増大しないためである。1 群あたり数百本のファイバーがあれば、ごくわずかな
    隔たりでも小さい p 値に達する。「検出できる」と「大きい」を区別するのは
    効果量の側である。

    The value is derived from the Mann-Whitney U statistic rather than by
    counting pairs, which would be quadratic in the sample sizes.
    値はペアを数え上げるのではなく Mann-Whitney U 統計量から導く。数え上げは
    標本数に対して二次のコストになるためである。

    The statistic is defined in [Cliff1993]_.
    この統計量の定義は [Cliff1993]_ による。

    References
    ----------
    .. [Cliff1993] N. Cliff, "Dominance statistics: Ordinal analyses to answer
       ordinal questions," Psychological Bulletin, vol. 114, pp. 494-509,
       1993.

    Examples
    --------
    >>> from lib.group_compare import cliffs_delta
    >>> cliffs_delta([1, 2, 3], [4, 5, 6])
    -1.0
    >>> cliffs_delta([1, 2, 3, 4], [2, 3])
    0.0
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return float("nan")

    # Local import: scipy.stats is heavy and only this module needs it, so a
    # plugin that never compares groups does not pay for the import.
    # 局所インポート。scipy.stats は重く、必要とするのは本モジュールだけである。
    # 群間比較を行わないプラグインが読み込みコストを負担しないようにする。
    from scipy.stats import mannwhitneyu

    # U counts (a > b) pairs plus half the ties, so 2U/(n*m) - 1 reduces
    # exactly to #(a>b) - #(a<b) over n*m -- Cliff's delta, ties included.
    # U は (a > b) のペア数に同順位の半分を加えた値であり、2U/(n*m) - 1 は
    # ちょうど #(a>b) - #(a<b) を n*m で割った値、すなわち同順位込みの
    # Cliff's delta に一致する。
    statistic = mannwhitneyu(a, b, alternative="two-sided").statistic
    return float(2.0 * statistic / (a.size * b.size) - 1.0)


def holm_adjusted(pvalues: Sequence[float]) -> List[float]:
    """
    Return Holm-corrected p-values for a family of comparisons.
    比較の一群に対する Holm 補正後の p 値を返す。

    Parameters
    ----------
    pvalues
        Raw p-values; NaN entries are passed through untouched.
        生の p 値。NaN の要素はそのまま返す。

    Returns
    -------
    list of float
        Adjusted p-values in the input order, each capped at 1.
        入力と同順の補正後 p 値。上限は 1。

    Notes
    -----
    Comparing k groups makes k(k-1)/2 pairs, and testing each of them at 0.05
    on its own finds a "difference" somewhere more often than 5% of the time
    when no difference is present. Holm's step-down procedure [Holm1979]_
    controls the family-wise error rate while staying uniformly more powerful
    than Bonferroni.
    k 群を比較すると k(k-1)/2 組のペアができ、それぞれを単独に 0.05 で検定すると、
    差が無くてもどこかに「差」が見つかる確率は 5% を超える。Holm の段階的手順
    [Holm1979]_ はファミリーワイズ誤り率を制御しつつ、Bonferroni より一様に
    検出力が高い。

    References
    ----------
    .. [Holm1979] S. Holm, "A simple sequentially rejective multiple test
       procedure," Scandinavian Journal of Statistics, vol. 6, no. 2,
       pp. 65-70, 1979.

    Examples
    --------
    >>> from lib.group_compare import holm_adjusted
    >>> holm_adjusted([0.01, 0.04, 0.03])
    [0.03, 0.06, 0.06]
    """
    values = [float(p) for p in pvalues]
    finite = [(i, p) for i, p in enumerate(values) if np.isfinite(p)]
    adjusted = list(values)
    if not finite:
        return adjusted

    finite.sort(key=lambda item: item[1])
    count = len(finite)
    running = 0.0
    for rank, (index, p) in enumerate(finite):
        # Holm steps down: each p is scaled by the number of hypotheses not
        # yet rejected, and the sequence is kept non-decreasing so a later
        # comparison never ends up more significant than an earlier one.
        # Holm 法は段階的に下る。各 p は未棄却の仮説数で拡大され、後の比較が
        # 前の比較より有意になることがないよう、列は非減少に保たれる。
        running = max(running, (count - rank) * p)
        adjusted[index] = min(1.0, running)
    return adjusted


def compare_groups(
    groups: Sequence[Tuple[str, np.ndarray]],
) -> List[PairComparison]:
    """
    Compare every pair of groups with rank tests and an effect size.
    全てのグループ対を順位検定と効果量で比較する。

    Parameters
    ----------
    groups
        ``(name, samples)`` pairs, one per group, in display order.
        グループごとの ``(名前, 標本)`` の列。表示順に並べる。

    Returns
    -------
    list of PairComparison
        One entry per unordered pair, in the order the pairs are formed from
        the input; empty when fewer than two groups are given.
        順序を問わないペアごとに 1 件。入力から作られるペアの順に並ぶ。
        グループが 2 つ未満なら空。

    Notes
    -----
    A pair whose groups are too small to test still appears in the result,
    with NaN p-values, so a caller rendering a table shows every pair and
    reports which ones could not be tested rather than dropping them.
    検定するには小さすぎるグループのペアも、NaN の p 値を持つ項目として結果に
    残す。表を描く呼び出し側が全ペアを表示し、検定できなかったものを落とさずに
    報告できるようにするためである。

    The tests are the two-sided Mann-Whitney U test [MannWhitney1947]_ and the
    two-sample Kolmogorov-Smirnov test [Smirnov1948]_. A pair whose groups
    can be arranged in at most `_EXACT_ARRANGEMENT_LIMIT` ways is tested by
    counting every arrangement, which is exact with tied values too; a larger
    pair by `scipy.stats.mannwhitneyu` and `scipy.stats.ks_2samp`.
    検定は両側 Mann-Whitney U 検定 [MannWhitney1947]_ と 2 標本
    Kolmogorov-Smirnov 検定 [Smirnov1948]_ である。群の並べ方が
    `_EXACT_ARRANGEMENT_LIMIT` 通り以下のペアは全ての並べ方を数えて検定し、これは
    同順位があっても厳密である。それより大きいペアは `scipy.stats.mannwhitneyu` と
    `scipy.stats.ks_2samp` で計算する。

    On a larger pair the Kolmogorov-Smirnov p-value assumes continuous
    distributions. Tied values -- for example the zeros of a per-fiber kink
    density, where a fiber without a kink reads 0 -- make it conservative:
    with no difference present it rejects less often than its nominal level,
    so a small KS p-value still stands while a large one may miss a real
    difference. The Mann-Whitney p-value is computed there with a tie
    correction.
    大きいペアでは、Kolmogorov-Smirnov の p 値は連続分布を仮定している。同順位
    （例えばファイバー単位のキンク密度で、キンクの無いファイバーが 0 となるもの）
    があると保守的になり、差が無いときに名目の水準より少なくしか棄却しない。
    したがって小さい KS の p 値はそのまま有効だが、大きい値は実在の差を見逃して
    いることがある。そこでの Mann-Whitney の p 値は同順位の補正を入れて計算する。

    References
    ----------
    .. [MannWhitney1947] H. B. Mann and D. R. Whitney, "On a test of whether
       one of two random variables is stochastically larger than the other,"
       The Annals of Mathematical Statistics, vol. 18, pp. 50-60, 1947.
       doi:10.1214/aoms/1177730491
    .. [Smirnov1948] N. Smirnov, "Table for estimating the goodness of fit of
       empirical distributions," The Annals of Mathematical Statistics,
       vol. 19, no. 2, pp. 279-281, 1948. doi:10.1214/aoms/1177730256

    Examples
    --------
    Three groups make three pairs. Group ``C`` has fewer than
    `MIN_SAMPLES_FOR_TEST` samples, so its pairs are listed untested:

    >>> import numpy as np
    >>> from lib.group_compare import compare_groups
    >>> pairs = compare_groups([("A", np.array([1.0, 2, 3, 4, 5])),
    ...                         ("B", np.array([6.0, 7, 8, 9, 10])),
    ...                         ("C", np.array([1.0, 2]))])
    >>> [(p.group_a, p.group_b) for p in pairs]
    [('A', 'B'), ('A', 'C'), ('B', 'C')]
    >>> first = pairs[0]
    >>> first.cliffs_delta, first.magnitude, round(first.mannwhitney_p, 4)
    (-1.0, 'large', 0.0079)
    >>> bool(np.isnan(pairs[1].mannwhitney_p))
    True
    """
    if len(groups) < 2:
        return []

    pairs = []
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            name_a, sample_a = groups[i]
            name_b, sample_b = groups[j]
            a = np.asarray(sample_a, dtype=float)
            b = np.asarray(sample_b, dtype=float)

            testable = (
                a.size >= MIN_SAMPLES_FOR_TEST and b.size >= MIN_SAMPLES_FOR_TEST
            )
            u_p = ks_p = float("nan")
            if testable:
                u_p, ks_p = _pair_pvalues(a, b)

            # The effect size is gated on the same sample-size condition as the
            # tests, so a row is either wholly computed or wholly blank. Cliff's
            # delta is defined for one observation against one, where it always
            # reads +-1 and would be labelled "large" beside p-values that could
            # not be computed at all.
            # 効果量は検定と同じ標本数条件で抑制し、行全体が計算済みか空白かの
            # どちらかになるようにする。Cliff's delta は 1 観測対 1 観測でも
            # 定義され、その場合は必ず ±1 となって、そもそも計算できなかった
            # p 値の隣に "large" と表示されてしまう。
            delta = cliffs_delta(a, b) if testable else float("nan")
            min_p = (_min_attainable_p(int(a.size), int(b.size)) if testable
                     else float("nan"))
            pairs.append({
                "group_a": name_a, "group_b": name_b,
                "n_a": int(a.size), "n_b": int(b.size),
                "u_p": u_p, "ks_p": ks_p,
                "delta": delta, "min_p": min_p,
            })

    # Correction spans the whole family of pairs, once per test.
    # 補正は検定ごとに、ペアの一群全体へまとめて適用する。
    u_adjusted = holm_adjusted([p["u_p"] for p in pairs])
    ks_adjusted = holm_adjusted([p["ks_p"] for p in pairs])

    return [
        PairComparison(
            group_a=p["group_a"],
            group_b=p["group_b"],
            n_a=p["n_a"],
            n_b=p["n_b"],
            mannwhitney_p=p["u_p"],
            mannwhitney_p_adjusted=ua,
            ks_p=p["ks_p"],
            ks_p_adjusted=ka,
            cliffs_delta=p["delta"],
            magnitude=delta_magnitude(p["delta"]),
            min_attainable_p=p["min_p"],
        )
        for p, ua, ka in zip(pairs, u_adjusted, ks_adjusted)
    ]
