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
    Comparing k groups makes k(k-1)/2 pairs, and testing all of them at 0.05
    each would find a "difference" among four groups about a quarter of the
    time with no difference present. Holm controls the family-wise error rate
    while staying uniformly more powerful than Bonferroni.
    k 群を比較すると k(k-1)/2 組のペアができ、それぞれを 0.05 で検定すると、
    差が無くても 4 群では約 1/4 の確率でどこかに「差」が見つかる。Holm 法は
    ファミリーワイズ誤り率を制御しつつ、Bonferroni より一様に検出力が高い。
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
    """
    if len(groups) < 2:
        return []

    from scipy.stats import ks_2samp, mannwhitneyu

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
                try:
                    u_p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
                except Exception:
                    # Degenerate input (for example two constant samples)
                    # leaves the pair reported as not tested rather than
                    # aborting the whole comparison table.
                    # 退化した入力（例: 定数の 2 標本）では、比較表全体を中断
                    # せず、そのペアを未検定として報告する。
                    u_p = float("nan")
                try:
                    ks_p = float(ks_2samp(a, b).pvalue)
                except Exception:
                    ks_p = float("nan")

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
            pairs.append({
                "group_a": name_a, "group_b": name_b,
                "n_a": int(a.size), "n_b": int(b.size),
                "u_p": u_p, "ks_p": ks_p,
                "delta": delta,
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
        )
        for p, ua, ka in zip(pairs, u_adjusted, ks_adjusted)
    ]
