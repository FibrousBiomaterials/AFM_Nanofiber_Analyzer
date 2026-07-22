# -*- coding: utf-8 -*-
"""
Feature extraction for the fiber-connection model (process C).
ファイバー連結モデルの特徴抽出（工程C）。

The connection model answers one question per candidate: do these two skeleton
fragment ends belong to the same fibril? This module turns such a pair into the
numeric feature vector that question is decided from. It is the counterpart of
`lib.ml_features` for the pixel models: same role, different unit of analysis
-- a fragment-end pair instead of a pixel.
連結モデルは候補ごとに 1 つの問いに答える。この 2 つの骨格断片の端は同一
フィブリルに属するか、である。本モジュールはそのペアを、判断の元になる数値特徴
ベクトルへ変換する。画素モデルにおける `lib.ml_features` に相当し、役割は同じで
解析単位が異なる（画素ではなく断片端のペア）。

Order independence / 順序非依存
--------------------------------
The classical connector in `lib.fiber_connector` scores a candidate while
growing a fibril, so its angles are measured from the *current fibril's*
look-back point and depend on which fragments were already consumed. Features
here are computed from the two fragments alone and are symmetric under swapping
them, so the same physical pair always yields the same vector.
`lib.fiber_connector` の古典的な連結器はフィブリルを成長させながら候補を採点する
ため、その角度は*成長中のフィブリル*の振り返り点から測られ、どの断片を既に消費
したかに依存する。本モジュールの特徴は 2 つの断片のみから計算し、両者の入れ替えに
対して対称なので、同じ物理的ペアは常に同じベクトルになる。

Two things depend on that. Labels are recorded per endpoint pair
(`lib.ml_connect_labels`), with no growth state to reproduce, so a
growth-dependent feature could not be computed for them at all. And a
probability that depends only on the pair -- not on visit order -- is what
allows the greedy search to be replaced later by a global assignment over all
candidates.
これに 2 つのことが依存する。ラベルは端点ペア単位で記録され
（`lib.ml_connect_labels`）、再現すべき成長状態を持たないため、成長依存の特徴は
そもそも計算できない。また、訪問順ではなくペアのみに依存する確率であればこそ、
貪欲探索を後から全候補にわたる大域割当へ置き換えられる。

Symmetry is achieved by encoding each per-fragment quantity as an unordered
pair: a sorted ``(min, max)``, a sum, or an absolute difference. A raw
"fragment A value, fragment B value" layout would present one physical decision
as two different vectors depending on which end the caller listed first.
対称性は、断片ごとの量を順序のない対（ソート済み ``(min, max)``、和、絶対差）
として符号化することで達成する。「断片Aの値、断片Bの値」という素の並びでは、
呼び出し側がどちらの端を先に並べたかによって、1 つの物理的判断が 2 つの異なる
ベクトルとして現れてしまう。

The bridge features / 橋渡し部の特徴
-------------------------------------
`bridge_*` sample the calibrated height along the straight line between the two
endpoints. This is the one piece of evidence the classical angle-and-distance
rule never looks at: whether there is actually fiber-height material spanning
the gap, or empty substrate. It is where a learned score is most likely to beat
the rule.
`bridge_*` は 2 端点を結ぶ直線に沿って補正済み高さを標本化する。これは古典的な
角度・距離ルールが一切見ていない唯一の証拠、すなわち隙間に実際に繊維の高さの
物質が架かっているのか、それとも空の基板なのか、である。学習したスコアがルールを
上回る見込みが最も高いのはここである。

This module depends only on NumPy and `lib.fiber_connector`'s angle helper; it
never imports scikit-learn or an ONNX runtime, so the same feature code runs
unchanged at training and inference time.
本モジュールの依存は NumPy と `lib.fiber_connector` の角度ヘルパーのみ。
scikit-learn や ONNX ランタイムを import しないため、同じ特徴コードが学習時と
推論時で不変のまま動く。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
# Reused rather than reimplemented so the angle a learned score sees is the same
# quantity the classical rule thresholds. The helper is convention-agnostic: it
# returns the interior angle at the vertex, which is invariant to whether the
# coordinate pairs are ordered (x, y) or (y, x), as long as all three agree.
# 学習スコアが見る角度を古典ルールがしきい値判定する量と同一にするため、
# 再実装せず再利用する。このヘルパーは座標規約に依存しない。頂点における内角を
# 返すため、3 点が同じ規約で揃ってさえいれば (x, y) 順でも (y, x) 順でも不変。
from .fiber_connector import angle_between_three_points

# Identifier for this feature-extraction contract, recorded with a trained model
# and checked before inference; see `lib.ml_features.FEATURE_SPEC_ID`.
# 本特徴抽出契約の識別子。学習済みモデルとともに記録し推論前に照合する。
# `lib.ml_features.FEATURE_SPEC_ID` を参照。
FEATURE_SPEC_ID = "pair_v1"

# Ordered feature-channel names. The order is the contract: a model trained on
# this order must be fed this order.
# 特徴チャンネル名（順序付き）。順序自体が契約であり、この順序で学習したモデルには
# この順序で与えなければならない。
FEATURE_NAMES: Tuple[str, ...] = (
    "gap_px",
    "angle_sum",
    "angle_abs_diff",
    "direction_cos",
    "height_median_min",
    "height_median_max",
    "height_rel_diff",
    "end_height_min",
    "end_height_max",
    "bridge_height_mean",
    "bridge_height_min",
    "bridge_height_max",
    "bridge_vs_ends",
    "length_min",
    "length_max",
)

# Guard against a zero-length direction vector or a zero denominator.
# 長さ 0 の方向ベクトルや分母 0 を防ぐための微小値。
_EPS = 1e-12


@dataclass(frozen=True)
class PairFeatureConfig:
    """
    Configuration of the fragment-pair feature extractor.
    断片ペア特徴抽出器の設定。

    Attributes
    ----------
    lookback_length
        Number of track points used to estimate a fragment's direction at an
        endpoint. Matches `lib.fiber_connector.ConnectParams.lookback_length`
        so the learned features describe the same local geometry the classical
        rule measures.
        端点における断片の方向推定に使うトラック点数。
        `lib.fiber_connector.ConnectParams.lookback_length` と一致させ、学習する
        特徴が古典ルールの測る局所形状と同じものを記述するようにする。
    num_avg_points
        Number of track points averaged to characterize the height right at an
        endpoint.
        端点直近の高さを特徴づけるために平均するトラック点数。
    bridge_samples
        Number of points sampled along the straight line between the two
        endpoints when measuring the gap.
        隙間を測る際に 2 端点間の直線上で標本化する点数。
    """

    lookback_length: int = 15
    num_avg_points: int = 5
    bridge_samples: int = 16

    def spec(self) -> Dict:
        """
        Return the serializable feature spec ``{"id", "params"}``.
        直列化可能な特徴仕様 ``{"id", "params"}`` を返す。
        """
        return {
            "id": FEATURE_SPEC_ID,
            "params": {
                "lookback_length": int(self.lookback_length),
                "num_avg_points": int(self.num_avg_points),
                "bridge_samples": int(self.bridge_samples),
            },
        }


@dataclass(frozen=True)
class FragmentEnd:
    """
    One end of one skeleton fragment.
    骨格断片の片方の端。

    Attributes
    ----------
    fragment_index
        Index into the fragment sequence this end belongs to.
        この端が属する断片列のインデックス。
    at_start
        Whether this is the first track point (``True``) or the last
        (``False``).
        トラックの先頭点（``True``）か末尾点（``False``）か。
    x, y
        Endpoint pixel coordinates in the skeleton's frame, matching the
        coordinates recorded in a label sidecar.
        骨格座標系での端点画素座標。ラベル sidecar に記録される座標と一致する。
    """

    fragment_index: int
    at_start: bool
    x: int
    y: int

    @property
    def xy(self) -> Tuple[int, int]:
        """Return the endpoint as an ``(x, y)`` tuple. 端点を ``(x, y)`` で返す。"""
        return (self.x, self.y)


def config_from_spec(spec: Dict) -> PairFeatureConfig:
    """
    Rebuild the `PairFeatureConfig` that produced a recorded feature spec.
    記録された特徴仕様を生成した `PairFeatureConfig` を復元する。

    Raises
    ------
    ValueError
        If the spec id is not the one this release can reproduce, or a
        parameter is missing. A different id means this code computes features
        differently and cannot faithfully reproduce that spec, so it is
        rejected rather than silently mismatched.
        仕様 id が本リリースで再現可能なものでない場合、またはパラメータが欠けて
        いる場合。異なる id は本コードが特徴を別様に計算することを意味し、その
        仕様を忠実に再現できないため、黙って食い違わせず拒否する。
    """
    if spec.get("id") != FEATURE_SPEC_ID:
        raise ValueError(
            f"feature spec id {spec.get('id')!r} cannot be reproduced by this "
            f"release (this release computes {FEATURE_SPEC_ID!r})")
    try:
        params = spec["params"]
        return PairFeatureConfig(
            lookback_length=int(params["lookback_length"]),
            num_avg_points=int(params["num_avg_points"]),
            bridge_samples=int(params["bridge_samples"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed feature spec params: {exc}") from exc


def specs_match(trained: Dict, current: Dict) -> bool:
    """
    Return whether a recorded feature spec equals the current one.
    記録された特徴仕様が現在のものと一致するかを返す。

    A mismatch must be a hard failure: a model fed features it was not trained
    on raises nothing as long as the column count matches, and simply predicts
    from misaligned columns.
    不一致は致命的エラーとして扱うこと。列数さえ合えば、学習時と異なる特徴を
    与えてもモデルは何も送出せず、食い違った列から予測するだけである。
    """
    return trained == current


def feature_names(config: PairFeatureConfig = PairFeatureConfig()) -> List[str]:
    """
    Return the ordered feature-channel names.
    順序付きの特徴チャンネル名を返す。

    The set is fixed; `config` only changes how the values are measured, not
    which channels exist. It is accepted for symmetry with
    `lib.ml_features.feature_names`.
    チャンネル集合は固定で、`config` は測り方だけを変えチャンネルの有無は変えない。
    `lib.ml_features.feature_names` と形を揃えるために引数を受け取る。
    """
    return list(FEATURE_NAMES)


def num_features(config: PairFeatureConfig = PairFeatureConfig()) -> int:
    """
    Return the number of feature channels.
    特徴チャンネル数を返す。
    """
    return len(FEATURE_NAMES)


def fragment_ends(fragments: Sequence) -> List[FragmentEnd]:
    """
    Enumerate both ends of every fragment.
    各断片の両端を列挙する。

    Parameters
    ----------
    fragments
        `lib.fiber.Fiber` fragments, typically from
        `FiberTrackingImage.fibers_in_image_parallel`.
        `lib.fiber.Fiber` の断片。通常は
        `FiberTrackingImage.fibers_in_image_parallel` の出力。

    Returns
    -------
    list of FragmentEnd
        Two entries per fragment, in fragment order.
        断片ごとに 2 件、断片の順序で並ぶ。
    """
    ends: List[FragmentEnd] = []
    for index, fragment in enumerate(fragments):
        xs, ys = _absolute_track(fragment)
        ends.append(FragmentEnd(index, True, int(xs[0]), int(ys[0])))
        ends.append(FragmentEnd(index, False, int(xs[-1]), int(ys[-1])))
    return ends


def endpoint_lookup(fragments: Sequence) -> Dict[Tuple[int, int], FragmentEnd]:
    """
    Map endpoint coordinates to the fragment end they identify.
    端点座標から、それが指す断片端への対応を作る。

    This is how a label sidecar -- which records coordinates, not indices --
    is resolved against a freshly loaded skeleton.
    ラベル sidecar は番号ではなく座標を記録するため、新たに読み込んだ骨格に対して
    これで解決する。

    Returns
    -------
    dict
        ``(x, y)`` to `FragmentEnd`. Endpoints are distinct pixels on a
        skeleton, so the mapping is unambiguous.
        ``(x, y)`` から `FragmentEnd` への辞書。骨格上の端点は互いに異なる画素
        なので、対応は一意である。
    """
    return {end.xy: end for end in fragment_ends(fragments)}


def extract_pair_features(
    fragments: Sequence,
    end_a: FragmentEnd,
    end_b: FragmentEnd,
    calibrated: np.ndarray,
    config: PairFeatureConfig = PairFeatureConfig(),
) -> np.ndarray:
    """
    Compute the feature vector for one candidate fragment-end pair.
    候補となる断片端ペア 1 組の特徴ベクトルを計算する。

    Parameters
    ----------
    fragments
        The fragment sequence both ends index into.
        両端が参照する断片列。
    end_a, end_b
        The two ends being considered for connection. The result is unchanged
        if they are swapped.
        連結を検討している 2 つの端。入れ替えても結果は変わらない。
    calibrated
        Background-corrected height image, in nanometers, indexed ``[y, x]``.
        nm 単位の背景補正済み高さ画像。``[y, x]`` で添字参照する。
    config
        Feature-extraction configuration.
        特徴抽出の設定。

    Returns
    -------
    numpy.ndarray
        Shape ``(num_features(),)`` float32 vector, ordered as
        `feature_names`. All values are finite.
        `feature_names` の順に並ぶ形状 ``(num_features(),)`` の float32 ベクトル。
        全要素が有限値。

    Raises
    ------
    ValueError
        If the two ends are the same fragment end, or `calibrated` is not 2D.
        2 つの端が同一の断片端である場合、または `calibrated` が 2 次元でない場合。
    """
    if calibrated.ndim != 2:
        raise ValueError(f"calibrated must be a 2D image, got {calibrated.ndim}D")
    if end_a.fragment_index == end_b.fragment_index and end_a.at_start == end_b.at_start:
        raise ValueError("the two ends are the same fragment end")

    frag_a = fragments[end_a.fragment_index]
    frag_b = fragments[end_b.fragment_index]

    pa = np.array(end_a.xy, dtype=float)
    pb = np.array(end_b.xy, dtype=float)

    look_a = _lookback_point(frag_a, end_a, config.lookback_length)
    look_b = _lookback_point(frag_b, end_b, config.lookback_length)

    # --- Geometry -----------------------------------------------------------
    gap = float(np.hypot(*(pa - pb)))

    # Interior angle at each endpoint between its own fragment and the bridge;
    # 180 degrees means the fragment continues straight into the gap.
    # 各端点における、自身の断片と橋渡し方向のなす内角。180 度は断片がそのまま
    # まっすぐ隙間へ続くことを意味する。
    angle_a = angle_between_three_points(tuple(look_a), tuple(pa), tuple(pb))
    angle_b = angle_between_three_points(tuple(look_b), tuple(pb), tuple(pa))
    angle_sum = angle_a + angle_b
    angle_abs_diff = abs(angle_a - angle_b)

    # Cosine between the two outgoing directions. Two fragments forming one
    # straight fibril point at each other, giving about -1. Symmetric because
    # the cosine of an angle between two vectors does not depend on their order.
    # 2 つの外向き方向のなす余弦。1 本の直線状フィブリルを成す 2 断片は互いを
    # 指すため約 -1 になる。2 ベクトル間の余弦は順序に依存しないため対称である。
    dir_a = _unit(pa - look_a)
    dir_b = _unit(pb - look_b)
    direction_cos = float(np.clip(np.dot(dir_a, dir_b), -1.0, 1.0))

    # --- Heights ------------------------------------------------------------
    heights_a = _track_heights(frag_a, calibrated)
    heights_b = _track_heights(frag_b, calibrated)
    median_a = float(np.median(heights_a)) if heights_a.size else 0.0
    median_b = float(np.median(heights_b)) if heights_b.size else 0.0

    # The classical height gate's quantity, kept identical so a learned score
    # can reproduce or override that decision on the same terms.
    # 古典的な高さゲートが用いる量。学習スコアが同じ土俵でその判断を再現または
    # 上書きできるよう、同一の定義を保つ。
    smaller = min(median_a, median_b)
    height_rel_diff = (abs(median_a - median_b) / smaller) if smaller > 0 else 0.0

    end_h_a = _endpoint_height(frag_a, end_a, calibrated, config.num_avg_points)
    end_h_b = _endpoint_height(frag_b, end_b, calibrated, config.num_avg_points)

    # --- Bridge: the evidence the classical rule never uses ------------------
    bridge = _bridge_heights(pa, pb, calibrated, config.bridge_samples)
    if bridge.size:
        bridge_mean = float(np.mean(bridge))
        bridge_min = float(np.min(bridge))
        bridge_max = float(np.max(bridge))
    else:
        # Endpoints adjacent or identical in pixel terms: there is no gap to
        # measure, so fall back to the endpoint heights rather than inventing a
        # value. `bridge_vs_ends` is then 0 by construction, which reads as
        # "nothing missing between the ends" -- the correct meaning here.
        # 端点が画素上で隣接または同一の場合、測るべき隙間が無い。値を捏造せず
        # 端点高さへフォールバックする。このとき `bridge_vs_ends` は構成上 0 に
        # なり、「両端の間に欠けているものは無い」と読める。これが正しい意味である。
        bridge_mean = bridge_min = bridge_max = 0.5 * (end_h_a + end_h_b)

    # Negative means the gap sits lower than the fiber ends -- empty substrate
    # between them; near zero means fiber-height material spans the gap.
    # 負の値は隙間が繊維端より低いこと、すなわち間が空の基板であることを意味する。
    # ゼロ近傍は繊維と同じ高さの物質が隙間に架かっていることを意味する。
    bridge_vs_ends = bridge_mean - 0.5 * (end_h_a + end_h_b)

    # --- Sizes --------------------------------------------------------------
    len_a = float(len(np.asarray(frag_a.xtrack)))
    len_b = float(len(np.asarray(frag_b.xtrack)))

    values = (
        gap,
        angle_sum,
        angle_abs_diff,
        direction_cos,
        min(median_a, median_b),
        max(median_a, median_b),
        height_rel_diff,
        min(end_h_a, end_h_b),
        max(end_h_a, end_h_b),
        bridge_mean,
        bridge_min,
        bridge_max,
        bridge_vs_ends,
        min(len_a, len_b),
        max(len_a, len_b),
    )
    vector = np.asarray(values, dtype=np.float64)
    # A non-finite feature would propagate into the estimator without raising;
    # replace it here so a degenerate fragment cannot poison a whole dataset.
    # 非有限値の特徴は例外を出さずに推定器へ伝播する。退化した断片がデータセット
    # 全体を汚さないよう、ここで置換する。
    return np.nan_to_num(vector, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def _absolute_track(fragment) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return a fragment's track in absolute image coordinates.
    断片のトラックを画像の絶対座標で返す。

    Track points are stored relative to the fragment's bounding box, so the
    ``(x, y)`` offset in ``data`` is added back.
    トラック点は断片の外接矩形基準で保持されるため、``data`` の ``(x, y)``
    オフセットを戻す。
    """
    xs = np.asarray(fragment.xtrack) + fragment.data[0]
    ys = np.asarray(fragment.ytrack) + fragment.data[1]
    return xs, ys


def _lookback_point(fragment, end: FragmentEnd, lookback_length: int) -> np.ndarray:
    """
    Return the point used to estimate a fragment's direction at one end.
    片端における断片の方向推定に使う点を返す。

    Mirrors the classical connector's look-back indexing so both measure the
    same local direction: counted inward from the endpoint, clamped to the
    fragment's length.
    古典的な連結器の振り返り添字付けに倣い、両者が同じ局所方向を測るようにする。
    端点から内側へ数え、断片の長さで打ち切る。
    """
    xs, ys = _absolute_track(fragment)
    n = len(xs)
    step = min(lookback_length, n)
    index = step - 1 if end.at_start else -step
    return np.array([float(xs[index]), float(ys[index])])


def _unit(vector: np.ndarray) -> np.ndarray:
    """
    Return a unit vector, or a zero vector when the input has no length.
    単位ベクトルを返す。入力が長さを持たない場合はゼロベクトルを返す。
    """
    norm = float(np.hypot(*vector))
    if norm < _EPS:
        return np.zeros(2, dtype=float)
    return vector / norm


def _sample(calibrated: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """
    Sample the calibrated image at integer coordinates, clipped to bounds.
    整数座標で補正済み画像を標本化する。範囲外は端へ丸める。
    """
    height, width = calibrated.shape
    cols = np.clip(np.rint(xs).astype(int), 0, width - 1)
    rows = np.clip(np.rint(ys).astype(int), 0, height - 1)
    return np.asarray(calibrated, dtype=float)[rows, cols]


def _track_heights(fragment, calibrated: np.ndarray) -> np.ndarray:
    """
    Return the calibrated heights along a fragment's track.
    断片のトラックに沿った補正済み高さを返す。
    """
    xs, ys = _absolute_track(fragment)
    return _sample(calibrated, xs, ys)


def _endpoint_height(
    fragment, end: FragmentEnd, calibrated: np.ndarray, num_avg_points: int
) -> float:
    """
    Return the mean calibrated height over the points nearest one endpoint.
    片端に最も近い点群における補正済み高さの平均を返す。

    Averaging a short run rather than reading the single endpoint pixel keeps
    the value from being decided by one noisy pixel at the fragment's tip.
    単一の端点画素を読むのではなく短い区間を平均することで、断片先端の 1 画素の
    ノイズに値が左右されないようにする。
    """
    heights = _track_heights(fragment, calibrated)
    if heights.size == 0:
        return 0.0
    count = max(1, min(num_avg_points, heights.size))
    window = heights[:count] if end.at_start else heights[-count:]
    return float(np.mean(window))


def _bridge_heights(
    pa: np.ndarray, pb: np.ndarray, calibrated: np.ndarray, bridge_samples: int
) -> np.ndarray:
    """
    Sample the calibrated height strictly between two endpoints.
    2 端点の厳密に内側で補正済み高さを標本化する。

    The endpoints themselves are excluded so the result describes the gap, not
    the fibers on either side; including them would blend fiber height into the
    very measurement meant to reveal whether the gap is empty.
    端点自体は除外し、結果が両側の繊維ではなく隙間を記述するようにする。端点を
    含めると、隙間が空かどうかを明らかにするための計測そのものに繊維の高さが
    混ざってしまう。

    Returns
    -------
    numpy.ndarray
        Interior samples; empty when the endpoints are adjacent or identical
        and there is no interior to sample.
        内側の標本。端点が隣接または同一で内側が存在しない場合は空。
    """
    span = int(np.ceil(float(np.hypot(*(pa - pb)))))
    if span < 2:
        return np.empty(0, dtype=float)
    count = max(3, min(int(bridge_samples), span + 1))
    xs = np.linspace(pa[0], pb[0], num=count)[1:-1]
    ys = np.linspace(pa[1], pb[1], num=count)[1:-1]
    if xs.size == 0:
        return np.empty(0, dtype=float)
    return _sample(calibrated, xs, ys)


def pair_matrix(
    fragments: Sequence,
    pairs: Sequence[Tuple[FragmentEnd, FragmentEnd]],
    calibrated: np.ndarray,
    config: PairFeatureConfig = PairFeatureConfig(),
) -> np.ndarray:
    """
    Compute the feature matrix for many candidate pairs.
    多数の候補ペアに対する特徴行列を計算する。

    Parameters
    ----------
    fragments
        The fragment sequence the ends index into.
        端が参照する断片列。
    pairs
        Candidate end pairs.
        候補となる端のペア。
    calibrated
        Background-corrected height image in nanometers.
        nm 単位の背景補正済み高さ画像。
    config
        Feature-extraction configuration.
        特徴抽出の設定。

    Returns
    -------
    numpy.ndarray
        Shape ``(len(pairs), num_features())`` float32 matrix, ready for an
        estimator. Batching matters at inference: the connection search
        evaluates many candidates, and calling the model once per pair would
        make the runtime dominated by per-call overhead.
        推定器へ渡せる形状 ``(len(pairs), num_features())`` の float32 行列。
        推論時のバッチ化は重要である。連結探索は多数の候補を評価するため、ペア
        ごとにモデルを呼ぶと実行時間が呼び出しオーバーヘッドに支配される。
    """
    if not pairs:
        return np.empty((0, num_features(config)), dtype=np.float32)
    rows = [
        extract_pair_features(fragments, a, b, calibrated, config)
        for a, b in pairs
    ]
    return np.vstack(rows).astype(np.float32, copy=False)


def candidate_pairs(
    fragments: Sequence,
    max_gap_px: Optional[float] = None,
) -> List[Tuple[FragmentEnd, FragmentEnd]]:
    """
    Enumerate every distinct pair of ends from different fragments.
    異なる断片に属する端の相異なるペアをすべて列挙する。

    Parameters
    ----------
    fragments
        Fragments to pair up.
        ペアを作る対象の断片。
    max_gap_px
        When given, only pairs closer than this are returned. Enumerating all
        pairs is quadratic in the fragment count, so a distance cut keeps a
        dense image tractable; pass ``None`` to enumerate exhaustively.
        指定時、これより近いペアのみを返す。全ペアの列挙は断片数の 2 乗になる
        ため、距離による打ち切りが高密度画像を扱える範囲に保つ。網羅列挙するには
        ``None`` を渡す。

    Returns
    -------
    list of tuple
        Each pair appears once, with the two ends never on the same fragment:
        an end cannot join its own fragment, and the features are symmetric so
        the reversed pair would be a duplicate row.
        各ペアは 1 回だけ現れ、2 つの端が同一断片に属することはない。端は自身の
        断片とは結合できず、また特徴は対称なので逆順のペアは重複行になる。
    """
    ends = fragment_ends(fragments)
    pairs: List[Tuple[FragmentEnd, FragmentEnd]] = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            a, b = ends[i], ends[j]
            if a.fragment_index == b.fragment_index:
                continue
            if max_gap_px is not None:
                if np.hypot(a.x - b.x, a.y - b.y) > max_gap_px:
                    continue
            pairs.append((a, b))
    return pairs
