# -*- coding: utf-8 -*-
"""
Per-pixel feature extraction for the machine-learning preprocessing stages.
機械学習前処理ステージ向けの画素単位特徴抽出。

Both the background-mask model (``bg_mask``) and the binarization model
(``binarize``) frame their problem the same way: classify each pixel as fiber
or background from features describing that pixel's local neighborhood. This
module produces those features and is shared by both stages; the only
difference between the two is the input image (raw height for ``bg_mask``,
background-corrected height for ``binarize``).
背景マスクモデル（``bg_mask``）と二値化モデル（``binarize``）は同じ枠組みで
問題を捉える。すなわち、各画素をその局所近傍を記述する特徴から繊維か背景かに
分類する。本モジュールはその特徴を生成し、両ステージで共有される。両者の
唯一の違いは入力画像であり、``bg_mask`` は生の高さ、``binarize`` は背景補正
済みの高さを入力とする。

Design background lives in ``private_docs/design/ml-decision-options.ja.md``
§5.1 (internal, not part of the public repository). The feature families are a
standard multi-scale set (as used by ilastik-style pixel classifiers): local
smoothed height, isotropic gradient magnitude, Laplacian, and Hessian
eigenvalues for ridge detection, each computed at several Gaussian scales.
設計の背景は ``private_docs/design/ml-decision-options.ja.md`` §5.1（非公開、
公開リポジトリの対象外）にある。特徴ファミリは標準的なマルチスケール集合
（ilastik 系の画素分類器が用いるもの）であり、局所平滑化高さ・等方勾配強度・
ラプラシアン・リッジ検出用のヘッセ固有値を、複数のガウススケールで計算する。

Why a hand-designed feature set (rather than a CNN that learns features): the
training data is distilled from existing pipeline output plus limited manual
correction, so only a handful of independent images are available. A pixel
classifier draws hundreds of thousands of samples from a single image and
trains on that scale; a CNN would need one to two orders of magnitude more
independent images. See the design record for the full rationale.
特徴を人手で設計する理由（特徴を学習する CNN ではなく）：教師データは既存
パイプライン出力の蒸留と限定的な手修正から作られるため、独立した画像は
数枚しか得られない。画素分類器は 1 枚の画像から数十万サンプルを取り、その
規模で学習できるが、CNN は 1〜2 桁多い独立画像を必要とする。詳細な根拠は
設計記録を参照。

Normalization / 正規化
----------------------
The input image is normalized once, per image, by its median and MAD (median
absolute deviation) before any feature is computed. This lets images taken
under different height scales be mixed in one training set: the same physical
structure yields similar feature values regardless of the image's absolute
height range. Tree ensembles are invariant to per-feature monotonic scaling
and would not strictly need this, but a later logistic or U-Net stage would,
and cross-image consistency helps every model class.
特徴計算の前に、入力画像を画像ごとに 1 度、中央値と MAD（中央絶対偏差）で
正規化する。これにより高さスケールの異なる画像を 1 つの教師集合に混ぜられる。
同じ物理構造が、画像の絶対高さ範囲によらず似た特徴値を生む。決定木アンサンブルは
特徴ごとの単調スケーリングに不変なので厳密には不要だが、将来のロジスティック
段や U-Net 段では必要であり、画像間の一貫性はどのモデルクラスにも役立つ。

This module depends only on NumPy, SciPy, and scikit-image (all already core
dependencies); it never imports scikit-learn, PyTorch, or an ONNX runtime, so
the same feature code runs unchanged at training and inference time.
本モジュールの依存は NumPy・SciPy・scikit-image のみ（いずれも既に中核依存）。
scikit-learn・PyTorch・ONNX ランタイムを import しないため、同じ特徴コードが
学習時と推論時で不変のまま動く。
"""

# ===== Standard library =====
from dataclasses import dataclass
from typing import Dict, List, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_gradient_magnitude, gaussian_laplace
from skimage.feature import hessian_matrix, hessian_matrix_eigvals

# Identifier for this feature-extraction contract. Recorded alongside a trained
# model and checked before inference: if the extractor changes in a way that
# alters feature values, this id (or the config below) must change so a stale
# model is rejected loudly instead of predicting from misaligned features.
# 本特徴抽出契約の識別子。学習済みモデルとともに記録し、推論前に照合する。
# 特徴値を変える形で抽出器が変わった場合、このid（または下記のconfig）を変え、
# 古いモデルが食い違った特徴から予測するのを黙認せず明示的に拒否する。
FEATURE_SPEC_ID = "pixel_v1"

# Gaussian scales (standard deviations, in pixels) at which the multi-scale
# features are computed. Larger scales capture wider context; 16 px reaches
# roughly the width of the background variation the classical pipeline models,
# while 1 px captures the sharp fiber edges its directional differences see.
# マルチスケール特徴を計算するガウススケール（標準偏差、px）。大きいスケールは
# 広い文脈を、16 px は古典パイプラインがモデル化する背景変動の幅程度を、
# 1 px はその方向差分が捉える鋭い繊維エッジを捉える。
DEFAULT_SIGMAS: Tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)

# Scale factor turning the MAD into a consistent estimator of the standard
# deviation for normally distributed data (1 / Phi^-1(0.75)).
# 正規分布データで MAD を標準偏差の一致推定量にするスケール係数
# （1 / Phi^-1(0.75)）。
_MAD_TO_STD = 1.4826

# Floor on the normalization denominator so a near-constant image (MAD ~ 0,
# e.g. a blank region) cannot divide by zero or explode the features.
# ほぼ一定の画像（MAD ~ 0、空領域など）でゼロ除算や特徴の発散を起こさない
# ための正規化分母の下限。
_NORM_EPS = 1e-9


@dataclass(frozen=True)
class PixelFeatureConfig:
    """
    Configuration of the per-pixel feature extractor.
    画素単位特徴抽出器の設定。

    Attributes
    ----------
    sigmas
        Gaussian scales in pixels for the multi-scale features.
        マルチスケール特徴用のガウススケール（px）。
    intensity
        Include the Gaussian-smoothed height at each scale.
        各スケールのガウス平滑化高さを含めるか。
    gradient
        Include the Gaussian gradient magnitude at each scale.
        各スケールのガウス勾配強度を含めるか。
    laplacian
        Include the Gaussian Laplacian at each scale.
        各スケールのガウスラプラシアンを含めるか。
    hessian
        Include the two Hessian eigenvalues at each scale (ridge detection).
        各スケールの 2 つのヘッセ固有値を含めるか（リッジ検出）。
    raw_intensity
        Include the normalized input value itself as one scale-free feature.
        正規化した入力値そのものをスケールに依らない特徴 1 つとして含めるか。
    normalize
        Per-image normalization scheme. ``"median_mad"`` centers by the median
        and scales by the MAD; ``"none"`` skips normalization.
        画像ごとの正規化方式。``"median_mad"`` は中央値で中心化し MAD で
        スケールする。``"none"`` は正規化しない。

    Notes
    -----
    This object is frozen and hashable so it can be recorded and compared as a
    feature spec (see `spec` / `specs_match`). Any change here that alters the
    produced feature values must be reflected in `FEATURE_SPEC_ID` or the spec
    params, so a model trained with an old config is rejected before inference.
    本オブジェクトは凍結・ハッシュ可能で、特徴仕様として記録・比較できる
    （`spec` / `specs_match` 参照）。生成される特徴値を変える変更は
    `FEATURE_SPEC_ID` か spec params に反映し、旧 config で学習したモデルを
    推論前に拒否できるようにする。
    """

    sigmas: Tuple[float, ...] = DEFAULT_SIGMAS
    intensity: bool = True
    gradient: bool = True
    laplacian: bool = True
    hessian: bool = True
    raw_intensity: bool = True
    normalize: str = "median_mad"

    def spec(self) -> Dict:
        """
        Return the serializable feature spec ``{"id", "params"}``.
        直列化可能な特徴仕様 ``{"id", "params"}`` を返す。

        Returns
        -------
        dict
            Identifier and parameters fully describing this extractor, for
            recording with a trained model and checking at inference time.
            この抽出器を完全に記述する識別子とパラメータ。学習済みモデルと
            ともに記録し、推論時に照合するためのもの。
        """
        return {
            "id": FEATURE_SPEC_ID,
            "params": {
                "sigmas": [float(s) for s in self.sigmas],
                "intensity": bool(self.intensity),
                "gradient": bool(self.gradient),
                "laplacian": bool(self.laplacian),
                "hessian": bool(self.hessian),
                "raw_intensity": bool(self.raw_intensity),
                "normalize": self.normalize,
            },
        }


def config_from_spec(spec: Dict) -> "PixelFeatureConfig":
    """
    Rebuild the `PixelFeatureConfig` that produced a recorded feature spec.
    記録された特徴仕様を生成した `PixelFeatureConfig` を復元する。

    Used at inference time to extract features exactly as they were at training
    time. The spec's ``id`` must equal this code version's `FEATURE_SPEC_ID`:
    within one id the params fully determine the computation, but a different
    id means this code computes features differently and cannot faithfully
    reproduce that spec, so it is rejected rather than silently mismatched.
    推論時に学習時と厳密に同じ特徴を抽出するために使う。仕様の ``id`` は本コード
    バージョンの `FEATURE_SPEC_ID` と一致しなければならない。同一 id 内では
    params が計算を完全に決めるが、異なる id は本コードが特徴を別様に計算する
    ことを意味し、その仕様を忠実に再現できないため、黙って食い違わせず拒否する。

    Parameters
    ----------
    spec
        Feature spec ``{"id", "params"}`` recorded with a model.
        モデルとともに記録された特徴仕様 ``{"id", "params"}``。

    Returns
    -------
    PixelFeatureConfig
        Configuration reproducing the recorded spec.
        記録された仕様を再現する設定。

    Raises
    ------
    ValueError
        If the spec id is not the one this code version can reproduce, or a
        required parameter is missing.
        仕様 id が本コードバージョンで再現可能なものでない場合、または必須
        パラメータが欠けている場合。
    """
    spec_id = spec.get("id")
    if spec_id != FEATURE_SPEC_ID:
        raise ValueError(
            f"feature spec id {spec_id!r} cannot be reproduced by this release "
            f"(this release computes {FEATURE_SPEC_ID!r}); the model was trained "
            f"with an incompatible feature extractor"
        )
    try:
        params = spec["params"]
        return PixelFeatureConfig(
            sigmas=tuple(float(s) for s in params["sigmas"]),
            intensity=bool(params["intensity"]),
            gradient=bool(params["gradient"]),
            laplacian=bool(params["laplacian"]),
            hessian=bool(params["hessian"]),
            raw_intensity=bool(params["raw_intensity"]),
            normalize=str(params["normalize"]),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed feature spec params: {exc}") from exc


def specs_match(trained: Dict, current: Dict) -> bool:
    """
    Return whether a recorded feature spec equals the current one.
    記録された特徴仕様が現在のものと一致するかを返す。

    Parameters
    ----------
    trained
        `spec` stored with a trained model.
        学習済みモデルとともに保存された `spec`。
    current
        `spec` the loaded extractor would produce now.
        現在の抽出器が生成する `spec`。

    Returns
    -------
    bool
        ``True`` only when id and params match exactly.
        id と params が完全一致する場合のみ ``True``。

    Notes
    -----
    A mismatch must be treated as a hard failure, not a warning: a classifier
    fed features it was not trained on raises nothing inside scikit-learn or an
    ONNX runtime as long as the column count matches; it simply predicts from
    misaligned columns and the accuracy loss is invisible.
    不一致は警告ではなく致命的エラーとして扱うこと。列数さえ一致していれば、
    学習時と異なる特徴を与えても scikit-learn や ONNX ランタイムは何も
    送出しない。食い違った列から予測するだけで、精度低下は表に出ない。
    """
    return trained == current


def feature_names(config: PixelFeatureConfig = PixelFeatureConfig()) -> List[str]:
    """
    Return the ordered channel names produced by `extract_pixel_features`.
    `extract_pixel_features` が生成するチャンネル名を順序どおり返す。

    Parameters
    ----------
    config
        Feature configuration; determines which families and scales are on.
        特徴設定。どのファミリとスケールを有効にするかを決める。

    Returns
    -------
    list of str
        One name per feature channel, in the exact order of the last axis of
        the `extract_pixel_features` output.
        特徴チャンネルごとの名前 1 つ。`extract_pixel_features` 出力の最終軸の
        順序と厳密に一致する。
    """
    names: List[str] = []
    if config.raw_intensity:
        names.append("raw_intensity")
    for sigma in config.sigmas:
        tag = _sigma_tag(sigma)
        if config.intensity:
            names.append(f"intensity_s{tag}")
        if config.gradient:
            names.append(f"gradient_s{tag}")
        if config.laplacian:
            names.append(f"laplacian_s{tag}")
        if config.hessian:
            names.append(f"hessian_ev0_s{tag}")
            names.append(f"hessian_ev1_s{tag}")
    return names


def num_features(config: PixelFeatureConfig = PixelFeatureConfig()) -> int:
    """
    Return the number of feature channels for a configuration.
    設定に対する特徴チャンネル数を返す。
    """
    return len(feature_names(config))


def extract_pixel_features(
    image: np.ndarray,
    config: PixelFeatureConfig = PixelFeatureConfig(),
) -> np.ndarray:
    """
    Compute the per-pixel feature stack for one image.
    1 枚の画像に対する画素単位の特徴スタックを計算する。

    Parameters
    ----------
    image
        2D height image. For ``bg_mask`` this is the raw height; for
        ``binarize`` it is the background-corrected height. Non-float input is
        promoted to float; NaN/Inf are replaced so the filters stay finite.
        2 次元の高さ画像。``bg_mask`` では生の高さ、``binarize`` では背景補正
        済みの高さ。浮動小数点でない入力は float へ昇格し、NaN/Inf は
        フィルタが有限を保つよう置換する。
    config
        Feature configuration.
        特徴設定。

    Returns
    -------
    numpy.ndarray
        Feature stack of shape ``(H, W, num_features(config))`` and dtype
        float32. The last-axis order matches `feature_names(config)`. Use
        `flatten_features` to reshape to ``(H * W, num_features)`` for a
        classifier.
        形状 ``(H, W, num_features(config))``、dtype float32 の特徴スタック。
        最終軸の順序は `feature_names(config)` と一致する。分類器向けに
        ``(H * W, num_features)`` へ整形するには `flatten_features` を使う。

    Raises
    ------
    ValueError
        If `image` is not 2D, is empty, or `config.normalize` is unknown.
        `image` が 2 次元でない・空である場合、または `config.normalize` が
        未知の場合。
    """
    if image.ndim != 2:
        raise ValueError(f"expected a 2D image, got {image.ndim}D")
    if image.size == 0:
        raise ValueError("image is empty")

    # Work in float and remove non-finite values up front: gaussian filters
    # propagate a single NaN across the whole smoothed output, so one bad
    # pixel would otherwise poison every feature.
    # float で処理し、非有限値を先に除去する。ガウスフィルタは 1 つの NaN を
    # 平滑化出力全体へ伝播させるため、1 画素の不良が全特徴を汚染しうる。
    work = np.asarray(image, dtype=np.float64)
    if not np.isfinite(work).all():
        work = np.nan_to_num(work, nan=0.0, posinf=0.0, neginf=0.0)

    work = _normalize(work, config.normalize)

    channels: List[np.ndarray] = []
    if config.raw_intensity:
        channels.append(work)

    for sigma in config.sigmas:
        if config.intensity:
            channels.append(gaussian_filter(work, sigma=sigma))
        if config.gradient:
            channels.append(gaussian_gradient_magnitude(work, sigma=sigma))
        if config.laplacian:
            channels.append(gaussian_laplace(work, sigma=sigma))
        if config.hessian:
            ev0, ev1 = _hessian_eigenvalues(work, sigma)
            channels.append(ev0)
            channels.append(ev1)

    # Stack along a new last axis so each pixel becomes a feature vector; the
    # channel order here must stay in lockstep with feature_names().
    # 各画素が特徴ベクトルになるよう新たな最終軸で積む。ここのチャンネル順は
    # feature_names() と常に一致させること。
    stack = np.stack(channels, axis=-1).astype(np.float32, copy=False)
    return stack


def flatten_features(stack: np.ndarray) -> np.ndarray:
    """
    Reshape a feature stack to a classifier's ``(n_samples, n_features)``.
    特徴スタックを分類器向けの ``(n_samples, n_features)`` へ整形する。

    Parameters
    ----------
    stack
        Output of `extract_pixel_features`, shape ``(H, W, F)``.
        `extract_pixel_features` の出力。形状 ``(H, W, F)``。

    Returns
    -------
    numpy.ndarray
        Shape ``(H * W, F)`` view/reshape in row-major (C) order, so row
        ``y * W + x`` is pixel ``(y, x)``. A predicted label column can be
        reshaped back with ``labels.reshape(H, W)``.
        行優先（C 順）の ``(H * W, F)``。行 ``y * W + x`` が画素 ``(y, x)``。
        予測ラベル列は ``labels.reshape(H, W)`` で画像へ戻せる。

    Raises
    ------
    ValueError
        If `stack` is not 3D.
        `stack` が 3 次元でない場合。
    """
    if stack.ndim != 3:
        raise ValueError(f"expected a 3D feature stack (H, W, F), got {stack.ndim}D")
    h, w, f = stack.shape
    return stack.reshape(h * w, f)


def _normalize(image: np.ndarray, method: str) -> np.ndarray:
    """
    Apply per-image normalization.
    画像ごとの正規化を適用する。

    Centering by the median and scaling by the MAD is robust to the extreme
    heights of the fibers themselves, which a mean/std normalization would let
    dominate the scale. This is what makes features comparable across images
    with different absolute height ranges.
    中央値で中心化し MAD でスケールする方式は、繊維自体の極端な高さに頑健で
    ある。平均・標準偏差による正規化ではその高さがスケールを支配してしまう。
    これが絶対高さ範囲の異なる画像間で特徴を比較可能にする。
    """
    if method == "none":
        return image
    if method == "median_mad":
        median = float(np.median(image))
        mad = float(np.median(np.abs(image - median)))
        scale = mad * _MAD_TO_STD
        return (image - median) / (scale + _NORM_EPS)
    raise ValueError(
        f"unknown normalize method {method!r} (expected 'median_mad' or 'none')"
    )


def _hessian_eigenvalues(image: np.ndarray, sigma: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return the two Hessian eigenvalue images at one scale, descending.
    1 スケールでの 2 つのヘッセ固有値画像を降順で返す。

    Fibers are ridge-like: across a fiber's short axis the second derivative is
    large in magnitude, so the eigenvalue of largest magnitude discriminates
    fiber pixels from flat background. Both eigenvalues are returned because
    their combination also separates ridges (one large) from blobs (both large)
    and flats (both small).
    繊維はリッジ状で、短軸方向の 2 階微分は絶対値が大きい。そのため絶対値
    最大の固有値が繊維画素を平坦な背景から弁別する。両固有値を返すのは、
    その組合せがリッジ（片方が大）・塊（両方が大）・平坦（両方が小）も
    分離するためである。

    Notes
    -----
    ``order="rc"`` and ``use_gaussian_derivatives=True`` follow the scikit-image
    0.26 API, where `hessian_matrix_eigvals` returns eigenvalues sorted in
    descending order along a leading axis of length 2.
    ``order="rc"`` と ``use_gaussian_derivatives=True`` は scikit-image 0.26 の
    API に従う。`hessian_matrix_eigvals` は長さ 2 の先頭軸に沿って降順に
    ソートされた固有値を返す。
    """
    h_elems = hessian_matrix(
        image, sigma=sigma, order="rc", use_gaussian_derivatives=True
    )
    eigvals = hessian_matrix_eigvals(h_elems)
    return eigvals[0], eigvals[1]


def _sigma_tag(sigma: float) -> str:
    """
    Format a sigma value into a compact, stable channel-name suffix.
    シグマ値を簡潔で安定したチャンネル名接尾辞へ整形する。

    An integer-valued sigma renders without a decimal point (``4`` not ``4.0``)
    so feature names stay readable and stable across runs.
    整数値のシグマは小数点なしで表す（``4.0`` ではなく ``4``）。特徴名を
    読みやすく、実行間で安定させるため。
    """
    if float(sigma).is_integer():
        return str(int(sigma))
    return str(sigma).replace(".", "p")
