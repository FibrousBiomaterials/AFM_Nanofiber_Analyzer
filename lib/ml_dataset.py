# -*- coding: utf-8 -*-
"""
Build per-pixel training datasets for the ML preprocessing models from ``.b2z``.
``.b2z`` から ML 前処理モデル向けの画素単位教師データを構築する。

This module turns a folder of GUI01 bundles into a ``(X, y)`` sample matrix:
features always come from `lib.ml_features`, while the input image and target
depend on the task.
本モジュールは GUI01 バンドルのフォルダを ``(X, y)`` サンプル行列へ変換する。
特徴は常に `lib.ml_features` 由来で、入力画像とターゲットはタスクごとに異なる。

===================== ==================== ===============================
task                  input image          target
===================== ==================== ===============================
``binarize``          ``calibrated``       fiber/background mask (class)
``bg_mask``           raw height, aligned  fiber-candidate mask (class)
``background_surface`` raw height, aligned background height in nm (value)
===================== ==================== ===============================

``binarize`` (process B) reproduces the pipeline's pixel-level thresholding
decision. ``bg_mask`` and ``background_surface`` (process A) are the two
background-correction approaches kept side by side so they can be compared:
the first classifies which pixels are fiber candidates and hands that mask to
the existing inpaint-and-smooth background fill, the second regresses the
background surface directly so it can be subtracted from the raw image.
``binarize``（工程B）はパイプラインの画素単位しきい値判断を再現する。
``bg_mask`` と ``background_surface``（工程A）は比較のため併存させる 2 つの
背景補正方式で、前者はどの画素が繊維候補かを分類して既存の inpaint・平滑化に
よる背景生成へマスクを渡し、後者は背景面を直接回帰して生画像から差し引く。

Process A needs the raw height image / 工程A は生の高さ画像を要する
--------------------------------------------------------------------
Both process-A tasks read the raw (pre-correction) height image, which is the
optional ``original`` bundle key written only when GUI01 or ``cli.py process``
ran with ``save_original``. When it is absent this module falls back to the
raw input file recorded in the bundle metadata if it still sits next to the
bundle; otherwise the bundle cannot supply process-A training data and
`scan_bundle_folder` says so.
工程Aの両タスクは補正前の生の高さ画像を読む。これは GUI01 や ``cli.py
process`` を ``save_original`` 付きで実行したときのみ書かれる任意キー
``original`` である。存在しない場合は、バンドルのメタデータに記録された生の
入力ファイルがバンドルの隣に残っていればそれを使い、どちらも無ければ工程Aの
教師データを供給できず、`scan_bundle_folder` がその旨を報告する。

The one-pixel trim / 1 画素トリミング
--------------------------------------
The background calibrator's difference-based mask shrinks the image by one row
and one column, so ``calibrated`` is one pixel smaller than ``original`` per
axis (see `lib.bundle_schema`). Process-A features are therefore computed on
``original[1:, 1:]``, which is the frame every processed key shares. Getting
this wrong shifts features against targets by one pixel and silently degrades
the model rather than raising, so the alignment is applied in exactly one place
here.
背景補正器の差分ベースのマスクは画像を 1 行 1 列縮めるため、``calibrated`` は
``original`` より各軸 1 画素小さい（`lib.bundle_schema` 参照）。したがって
工程Aの特徴は ``original[1:, 1:]`` 上で計算する。これが処理済み全キーが共有する
座標系である。ここを誤ると特徴とターゲットが 1 画素ずれ、例外ではなく静かな
精度劣化になるため、整列はこの 1 箇所だけで行う。

Label source / ラベルの出所
---------------------------
The default label is the Segmenter's **intermediate** mask -- the output of
``Segmenter._binaryzation`` before the component filters (small-area removal,
Hough linearity, height cutoff) run. This is the decision the model actually
replaces. The bundle's stored ``binarized`` key is the mask **after** those
filters, so using it as the label would teach the model the filter effects too,
which then run a second time at inference (double application). On real test
data the filters remove roughly a quarter of the fiber pixels, so the two masks
differ materially; the intermediate mask keeps the model's job aligned with the
pipeline stage it stands in for. Obtaining it requires re-running the Segmenter,
which needs the analysis parameters stored in the bundle vlmeta.
既定のラベルは Segmenter の**中間**マスク、すなわち成分フィルタ（微小面積
除去・Hough 線形性・高さ下限）が走る前の ``Segmenter._binaryzation`` の出力で
ある。これがモデルが実際に置き換える判断である。バンドルに保存された
``binarized`` キーはそれらフィルタ**適用後**のマスクなので、これをラベルに
使うとモデルがフィルタ効果まで学習し、推論時に再度フィルタが掛かる（二重
適用）。実テストデータではフィルタが繊維画素の約 1/4 を除去し、両マスクは
実質的に異なる。中間マスクはモデルの役割を、それが代替するパイプライン段と
一致させる。取得には Segmenter の再実行が必要で、バンドル vlmeta に保存された
解析パラメータを要する。

Splitting / 分割
----------------
Every sample carries a group index identifying its source bundle, so a
downstream split (e.g. `sklearn.model_selection.GroupKFold`) can keep all
pixels of one image on the same side of a train/test split. Splitting pixels
randomly would leak information between train and test, because neighboring
pixels of one image are highly correlated. Design background is in
``private_docs/design/ml-gui-system-design.ja.md`` §12.3 (internal).
各サンプルは出所バンドルを識別するグループ番号を持つため、下流の分割
（例：`sklearn.model_selection.GroupKFold`）で 1 枚の画像の全画素を
train/test の同じ側に留められる。画素を無作為に分割すると train と test の
間で情報が漏れる。1 枚の画像の近傍画素は強く相関するためである。設計背景は
``private_docs/design/ml-gui-system-design.ja.md`` §12.3（非公開）にある。

This module imports the heavy preprocessing stack (`lib.pipeline` and its
Segmenter) lazily, inside the function that re-runs segmentation, so importing
this module stays cheap for callers that only need the dataclasses or the
folder scan.
本モジュールは重い前処理スタック（`lib.pipeline` とその Segmenter）を、
セグメンテーションを再実行する関数の内部で遅延 import する。データクラスや
フォルダ走査だけを必要とする呼び出し側のために、本モジュールの import を
軽く保つ。
"""

# ===== Standard library =====
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .blosc2_io import bundle_has_keys, load_bundle, load_bundle_meta
from .ml_features import (
    PixelFeatureConfig, extract_pixel_features, feature_names, flatten_features,
    normalization_params,
)

# Pixel label convention: fiber vs background. Fixed integer identifiers, not
# user-visible text; do not translate.
# 画素ラベルの規約：繊維と背景。固定の整数識別子でユーザー表示文字列では
# ないため翻訳しない。
LABEL_BACKGROUND = 0
LABEL_FIBER = 1

# Label sources for the binarize task (see module docstring). Fixed English
# identifiers.
# binarize タスクのラベル出所（モジュール docstring参照）。固定英語識別子。
LABEL_SEGMENTER_INTERMEDIATE = "segmenter_intermediate"  # B-1: pre-component-filter mask (default).
LABEL_BUNDLE_BINARIZED = "bundle_binarized"              # B-2: final stored mask.
LABEL_SOURCES = (LABEL_SEGMENTER_INTERMEDIATE, LABEL_BUNDLE_BINARIZED)

# Tasks this module can build a dataset for; the vocabulary is owned by
# `lib.ml_schema`. `connect` (fragment pairs, not pixels) is not a pixel task
# and is built elsewhere.
# 本モジュールがデータセットを構築できるタスク。語彙は `lib.ml_schema` が持つ。
# `connect`（画素ではなく断片ペア）は画素タスクではなく別で構築する。
_IMPLEMENTED_TASKS = ("binarize", "bg_mask", "background_surface")

# Tasks whose target is a continuous value rather than a class label. The
# background-surface model regresses the background height in nanometers; every
# other pixel task classifies fiber vs background.
# ターゲットがクラスラベルではなく連続値であるタスク。背景面モデルは背景高さ
# (nm) を回帰する。それ以外の画素タスクは繊維／背景を分類する。
REGRESSION_TASKS = ("background_surface",)

# Background methods that build the gradient-ridge fiber mask the `bg_mask`
# model reproduces. `tophat` never computes one, so a bundle processed with it
# cannot supply a `bg_mask` label.
# `bg_mask` モデルが再現する勾配リッジ由来の繊維マスクを構築する背景方式。
# `tophat` はこれを計算しないため、`tophat` で処理したバンドルからは
# `bg_mask` のラベルを作れない。
_MASK_BG_METHODS = ("inpaint", "spline1d", "spline2d")


def is_regression_task(task: str) -> bool:
    """
    Return whether a task regresses a continuous target.
    タスクが連続値を回帰するかどうかを返す。
    """
    return task in REGRESSION_TASKS

# Default cap on samples drawn per image. One 512x512 image holds ~260k pixels;
# without a cap a folder of many images produces a needlessly large matrix.
# `None` disables the cap. The default keeps class balancing (below) meaningful
# while bounding memory.
# 画像 1 枚あたりに抽出するサンプル数の既定上限。512x512 で約 26 万画素あり、
# 上限がないと多数画像のフォルダで無駄に大きな行列になる。`None` で無効化。
# 既定はメモリを抑えつつクラス均衡（下記）を意味あるものに保つ。
DEFAULT_MAX_SAMPLES_PER_IMAGE = 20000


@dataclass
class BundleLabelInfo:
    """
    Whether one bundle can serve as training data, and why not if it cannot.
    1 バンドルが教師データになりうるか、なれない場合はその理由。

    Attributes
    ----------
    path
        Bundle file path.
        バンドルファイルのパス。
    usable
        Whether the bundle can produce ``(features, label)`` for the task.
        当該タスクの ``(特徴, ラベル)`` を生成できるか。
    reason
        Empty when usable; otherwise a fixed English explanation.
        使用可能なら空。そうでなければ固定英語の説明。
    has_params
        Whether analysis parameters are recorded in the bundle vlmeta,
        required to re-run the Segmenter for the intermediate-mask label.
        中間マスクラベル用に Segmenter を再実行するのに必要な解析パラメータが
        バンドル vlmeta に記録されているか。
    """

    path: str
    usable: bool
    reason: str = ""
    has_params: bool = False


@dataclass
class PixelDataset:
    """
    Assembled per-pixel training samples with per-image grouping.
    画像単位のグループ付きで組み立てた画素単位の教師サンプル。

    Attributes
    ----------
    X
        Feature matrix of shape ``(n_samples, n_features)``, dtype float32.
        形状 ``(n_samples, n_features)``、dtype float32 の特徴行列。
    y
        Target vector of shape ``(n_samples,)``. For a classification task it
        holds `LABEL_FIBER` / `LABEL_BACKGROUND`; for a regression task
        (`REGRESSION_TASKS`) it holds the continuous target, in nanometers for
        ``background_surface``.
        形状 ``(n_samples,)`` のターゲットベクトル。分類タスクでは
        `LABEL_FIBER` / `LABEL_BACKGROUND`、回帰タスク（`REGRESSION_TASKS`）
        では連続値で、``background_surface`` では nm 単位。
    task
        Task this dataset was built for; decides whether `y` is a class label
        or a continuous target.
        このデータセットを構築したタスク。`y` がクラスラベルか連続値かを決める。
    groups
        Source-image index per sample, shape ``(n_samples,)``, for
        group-aware cross-validation and splitting.
        サンプルごとの出所画像番号。形状 ``(n_samples,)``。グループを考慮した
        交差検証・分割用。
    group_names
        Bundle stem for each group index, so ``group_names[g]`` names group
        ``g``.
        グループ番号ごとのバンドル stem。``group_names[g]`` がグループ ``g`` の
        名前。
    feature_names
        Ordered feature-channel names matching the columns of `X`.
        `X` の列に対応する順序付き特徴チャンネル名。
    feature_spec
        Feature-extractor spec, recorded with a trained model and checked at
        inference (see `lib.ml_features`).
        特徴抽出器の仕様。学習済みモデルとともに記録し推論時に照合する
        （`lib.ml_features` 参照）。
    provenance
        One record per source bundle: file name, recorded input hash if any,
        and drawn fiber/background counts. Mirrors how `lib.pipeline` records
        input provenance, so a trained model's data origin is auditable.
        出所バンドルごとの記録：ファイル名、記録があれば入力ハッシュ、抽出した
        繊維/背景数。`lib.pipeline` の入力来歴記録に倣い、学習済みモデルの
        データ由来を監査可能にする。
    """

    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    group_names: List[str]
    feature_names: List[str]
    feature_spec: Dict
    provenance: List[Dict] = field(default_factory=list)
    task: str = "binarize"

    @property
    def is_regression(self) -> bool:
        """
        Return whether `y` holds a continuous target.
        `y` が連続値ターゲットかどうかを返す。
        """
        return is_regression_task(self.task)

    @property
    def n_fiber(self) -> int:
        """
        Return the number of fiber samples, or 0 for a regression task.
        繊維サンプル数を返す。回帰タスクでは 0。
        """
        if self.is_regression:
            return 0
        return int(np.count_nonzero(self.y == LABEL_FIBER))

    @property
    def n_background(self) -> int:
        """
        Return the number of background samples, or 0 for a regression task.
        背景サンプル数を返す。回帰タスクでは 0。
        """
        if self.is_regression:
            return 0
        return int(np.count_nonzero(self.y == LABEL_BACKGROUND))


def scan_bundle_folder(
    folder: str,
    task: str = "binarize",
    label_source: str = LABEL_SEGMENTER_INTERMEDIATE,
) -> List[BundleLabelInfo]:
    """
    List ``.b2z`` bundles in a folder and whether each can be training data.
    フォルダ内の ``.b2z`` バンドルを列挙し、各々が教師データになりうるか返す。

    Parameters
    ----------
    folder
        Directory to scan (non-recursive).
        走査するディレクトリ（非再帰）。
    task
        Target task; currently only ``"binarize"`` is supported.
        対象タスク。現状 ``"binarize"`` のみ対応。
    label_source
        Label source, one of `LABEL_SOURCES`. The intermediate-mask source
        additionally requires analysis parameters in the bundle.
        ラベルの出所。`LABEL_SOURCES` のいずれか。中間マスク方式は加えて
        バンドル内の解析パラメータを要する。

    Returns
    -------
    list of BundleLabelInfo
        One entry per ``.b2z`` file found, sorted by path.
        見つかった ``.b2z`` ファイルごとに 1 エントリ（パス順）。

    Raises
    ------
    ValueError
        If `task` is unsupported or `label_source` is unknown.
        `task` が非対応、または `label_source` が未知の場合。
    """
    _check_task(task)
    _check_label_source(label_source)

    infos: List[BundleLabelInfo] = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".b2z"):
            continue
        path = os.path.join(folder, name)
        infos.append(_inspect_bundle(path, task, label_source))
    return infos


def inspect_bundle(
    path: str,
    task: str = "binarize",
    label_source: str = LABEL_SEGMENTER_INTERMEDIATE,
) -> BundleLabelInfo:
    """
    Report whether a single ``.b2z`` bundle can serve as training data.
    単一の ``.b2z`` バンドルが教師データになりうるかを報告する。

    The single-file counterpart of `scan_bundle_folder`, for callers (e.g. a GUI
    "add files" action) that select individual bundles rather than a folder.
    `scan_bundle_folder` の単一ファイル版。フォルダではなく個別バンドルを選ぶ
    呼び出し側（GUI の「ファイル追加」操作など）向け。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルのパス。
    task
        Target task; currently only ``"binarize"`` is supported.
        対象タスク。現状 ``"binarize"`` のみ対応。
    label_source
        Label source, one of `LABEL_SOURCES`.
        ラベルの出所。`LABEL_SOURCES` のいずれか。

    Returns
    -------
    BundleLabelInfo
        Usability and, if not usable, the reason.
        使用可否と、使用不可なら理由。

    Raises
    ------
    ValueError
        If `task` is unsupported or `label_source` is unknown.
        `task` が非対応、または `label_source` が未知の場合。
    """
    _check_task(task)
    _check_label_source(label_source)
    return _inspect_bundle(path, task, label_source)


def _inspect_bundle(path: str, task: str, label_source: str) -> BundleLabelInfo:
    """
    Inspect one bundle's keys and metadata for training-data suitability.
    1 バンドルのキーとメタデータを教師データ適性の観点で検査する。
    """
    try:
        meta = load_bundle_meta(path)
    except Exception as exc:  # noqa: BLE001 - report any read failure as a reason.
        return BundleLabelInfo(path=path, usable=False, reason=f"cannot read bundle: {exc}")

    has_params = isinstance(meta.get("params"), dict) and bool(meta.get("params"))

    # Check only the keys this task and label source need, via a header probe
    # that does not decompress array data, so scanning a large folder stays fast.
    # このタスクとラベル出所が必要とするキーのみを、配列を展開しないヘッダ確認で
    # 検査する。大きなフォルダの走査を速く保つため。
    needs = ["calibrated"]
    if task == "binarize" and label_source == LABEL_BUNDLE_BINARIZED:
        needs.append("binarized")
    ok, missing = bundle_has_keys(path, needs)
    if not ok:
        return BundleLabelInfo(
            path=path, usable=False,
            reason="missing keys: " + ", ".join(missing),
            has_params=has_params,
        )

    if task in ("bg_mask", "background_surface"):
        return _inspect_background_bundle(path, task, meta, has_params)

    if label_source == LABEL_SEGMENTER_INTERMEDIATE and not has_params:
        return BundleLabelInfo(
            path=path, usable=False,
            reason="no analysis parameters in bundle; cannot re-run Segmenter "
                   "for the intermediate-mask label (use label_source="
                   f"{LABEL_BUNDLE_BINARIZED!r} or re-process the input)",
            has_params=False,
        )

    return BundleLabelInfo(path=path, usable=True, has_params=has_params)


def _inspect_background_bundle(
    path: str, task: str, meta: Dict, has_params: bool
) -> BundleLabelInfo:
    """
    Check whether a bundle can supply process-A training data.
    バンドルが工程Aの教師データを供給できるか確認する。

    Both process-A tasks need the raw height image, and `bg_mask` additionally
    needs analysis parameters recorded with a mask-building background method,
    because its label is recovered by re-running the calibrator.
    工程Aの両タスクは生の高さ画像を要し、`bg_mask` はさらに、マスクを構築する
    背景方式で記録された解析パラメータを要する。ラベルを補正器の再実行で復元
    するためである。
    """
    has_original, _missing = bundle_has_keys(path, ["original"])
    if not has_original:
        name = meta.get("input_file")
        beside = bool(name) and os.path.exists(
            os.path.join(os.path.dirname(os.path.abspath(path)), str(name)))
        if not beside:
            return BundleLabelInfo(
                path=path, usable=False,
                reason="no raw height image: bundle has no 'original' key and "
                       "the recorded input file is not beside it; re-process "
                       "with save_original enabled",
                has_params=has_params,
            )

    if task == "bg_mask":
        if not has_params:
            return BundleLabelInfo(
                path=path, usable=False,
                reason="no analysis parameters in bundle; cannot re-run "
                       "BGCalibrator for the fiber-mask label",
                has_params=False,
            )
        method = (meta.get("params") or {}).get("bg_method")
        if method not in _MASK_BG_METHODS:
            return BundleLabelInfo(
                path=path, usable=False,
                reason=f"bg_method {method!r} builds no fiber mask "
                       f"(need one of {', '.join(_MASK_BG_METHODS)})",
                has_params=has_params,
            )

    return BundleLabelInfo(path=path, usable=True, has_params=has_params)


def build_pixel_dataset(
    bundle_paths: Sequence[str],
    task: str = "binarize",
    config: PixelFeatureConfig = PixelFeatureConfig(),
    *,
    label_source: str = LABEL_SEGMENTER_INTERMEDIATE,
    max_samples_per_image: Optional[int] = DEFAULT_MAX_SAMPLES_PER_IMAGE,
    balance: bool = True,
    random_state: Optional[int] = 0,
    skip_unusable: bool = True,
) -> PixelDataset:
    """
    Assemble a per-pixel training dataset from a list of bundles.
    バンドルのリストから画素単位の教師データセットを組み立てる。

    Parameters
    ----------
    bundle_paths
        Paths to GUI01 ``.b2z`` bundles.
        GUI01 ``.b2z`` バンドルのパス。
    task
        Target task; currently only ``"binarize"`` is supported.
        対象タスク。現状 ``"binarize"`` のみ対応。
    config
        Feature-extraction configuration; also fixes the recorded feature spec.
        特徴抽出設定。記録される特徴仕様も定める。
    label_source
        Label source, one of `LABEL_SOURCES`. Default is the pre-filter
        intermediate mask (see module docstring).
        ラベルの出所。`LABEL_SOURCES` のいずれか。既定はフィルタ前の中間
        マスク（モジュール docstring参照）。
    max_samples_per_image
        Cap on samples drawn per image; ``None`` keeps every pixel.
        画像 1 枚あたりに抽出するサンプル上限。``None`` で全画素を保持。
    balance
        When True, draw equal fiber and background counts per image so the
        dominant background class does not swamp training.
        True のとき画像ごとに繊維と背景を同数抽出し、多数派の背景クラスが
        学習を支配しないようにする。
    random_state
        Seed for the subsampling RNG; ``None`` is nondeterministic.
        サブサンプリング乱数の種。``None`` で非決定的。
    skip_unusable
        When True, silently skip bundles lacking required keys/params (each is
        still recorded in `provenance`); when False, raise on the first one.
        True のとき必要なキー/パラメータを欠くバンドルを黙ってスキップする
        （各々 `provenance` には記録する）。False なら最初の 1 つで例外送出。

    Returns
    -------
    PixelDataset
        Stacked samples across all usable bundles.
        使用可能な全バンドルにわたって積み上げたサンプル。

    Raises
    ------
    ValueError
        If `task`/`label_source` is invalid, or no usable bundle yields
        samples.
        `task`/`label_source` が不正、または使用可能なバンドルが 1 つも
        サンプルを生まない場合。
    """
    _check_task(task)
    _check_label_source(label_source)

    # Class balancing is meaningless for a continuous target, so a regression
    # task ignores `balance` and draws a plain random subset instead.
    # 連続値ターゲットにクラス均衡は意味がないため、回帰タスクは `balance` を
    # 無視して素の無作為部分集合を抽出する。
    regression = is_regression_task(task)

    rng = np.random.default_rng(random_state)
    names = feature_names(config)

    X_parts: List[np.ndarray] = []
    y_parts: List[np.ndarray] = []
    group_parts: List[np.ndarray] = []
    group_names: List[str] = []
    provenance: List[Dict] = []

    for path in bundle_paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            image, label = _load_image_and_label(path, task, label_source)
        except _UnusableBundle as exc:
            if skip_unusable:
                provenance.append({"file": os.path.basename(path),
                                   "used": False, "reason": str(exc)})
                continue
            raise ValueError(f"{path}: {exc}") from exc

        if regression:
            # Express the continuous target in the same per-image normalized
            # frame as the features. The features carry no absolute height
            # level (they are median/MAD normalized per image), so a model
            # trained against absolute nanometers cannot recover that level and
            # generalizes worse than predicting the mean. `lib.ml_model`
            # converts predictions back to nanometers with the same parameters.
            # 連続値ターゲットを、特徴と同じ画像ごとの正規化フレームで表す。特徴は
            # 画像ごとに median/MAD 正規化され絶対高さ水準を持たないため、絶対 nm を
            # 学習対象にするとその水準を復元できず、平均を予測するより悪化する。
            # `lib.ml_model` が同じパラメータで予測を nm へ戻す。
            center, scale = normalization_params(image, config.normalize)
            label = (np.asarray(label, dtype=np.float64) - center) / scale

        # Extract features on the whole image, then index the sampled pixels.
        # 画像全体で特徴抽出し、抽出画素を添字で取り出す。
        stack = extract_pixel_features(image, config)
        feats = flatten_features(stack)                 # (H*W, F)
        # A regression target keeps its continuous values; a class label is
        # stored as an integer so the estimator treats it as a class.
        # 回帰ターゲットは連続値のまま保持し、クラスラベルは推定器がクラスとして
        # 扱うよう整数で保持する。
        target_dtype = np.float64 if regression else np.int64
        labels = np.asarray(label, dtype=target_dtype).reshape(-1)  # (H*W,)

        sel = _select_indices(
            labels, max_samples_per_image, balance and not regression, rng)
        if sel.size == 0:
            provenance.append({"file": os.path.basename(path), "used": False,
                               "reason": "no samples after balancing (empty class)"})
            continue

        group_id = len(group_names)
        X_parts.append(feats[sel])
        y_parts.append(labels[sel])
        group_parts.append(np.full(sel.size, group_id, dtype=np.int64))
        group_names.append(stem)

        meta = _safe_meta(path)
        record = {
            "file": os.path.basename(path),
            "used": True,
            "input_sha256": meta.get("input_sha256"),
            "n_samples": int(sel.size),
        }
        if not regression:
            record["n_fiber"] = int(np.count_nonzero(labels[sel] == LABEL_FIBER))
            record["n_background"] = int(
                np.count_nonzero(labels[sel] == LABEL_BACKGROUND))
        provenance.append(record)

    if not X_parts:
        raise ValueError(
            "no usable bundle produced samples "
            f"(scanned {len(bundle_paths)} path(s)); see per-file reasons"
        )

    return PixelDataset(
        X=np.concatenate(X_parts, axis=0),
        y=np.concatenate(y_parts, axis=0),
        groups=np.concatenate(group_parts, axis=0),
        group_names=group_names,
        feature_names=names,
        feature_spec=config.spec(),
        provenance=provenance,
        task=task,
    )


def load_image_and_label(
    path: str,
    task: str = "binarize",
    label_source: str = LABEL_SEGMENTER_INTERMEDIATE,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load one bundle's input image and its fiber/background label mask.
    1 バンドルの入力画像と繊維/背景ラベルマスクを読み込む。

    The public entry point onto the same ``(image, label)`` pair the dataset
    builder uses per bundle, so a caller comparing a model against the classical
    reference (e.g. an apply/compare GUI) obtains exactly the label the model
    was trained against. For ``binarize`` the image is ``calibrated`` and the
    label is either the re-run Segmenter intermediate mask or the stored
    ``binarized`` mask (see module docstring).
    データセット構築器がバンドルごとに使うのと同じ ``(画像, ラベル)`` 対への
    公開入口。モデルを古典参照と比較する呼び出し側（適用・比較 GUI 等）が、
    モデルの学習対象と厳密に同じラベルを得られるようにする。``binarize`` では
    画像は ``calibrated``、ラベルは再実行 Segmenter の中間マスクか保存済み
    ``binarized`` マスクのいずれか（モジュール docstring参照）。

    Parameters
    ----------
    path
        Bundle file path.
        バンドルファイルのパス。
    task
        Target task; currently only ``"binarize"`` is supported.
        対象タスク。現状 ``"binarize"`` のみ対応。
    label_source
        Label source, one of `LABEL_SOURCES`.
        ラベルの出所。`LABEL_SOURCES` のいずれか。

    Returns
    -------
    tuple of numpy.ndarray
        ``(image, label)``; both 2D and the same shape, with the label holding
        `LABEL_FIBER` / `LABEL_BACKGROUND`.
        ``(画像, ラベル)``。ともに 2 次元で同形状、ラベルは `LABEL_FIBER` /
        `LABEL_BACKGROUND` を持つ。

    Raises
    ------
    ValueError
        If `task`/`label_source` is invalid, or the bundle cannot yield the
        pair (missing keys, or no parameters for the intermediate-mask re-run).
        `task`/`label_source` が不正、またはバンドルが対を生成できない場合
        （キー欠落、または中間マスク再実行のパラメータ欠如）。
    """
    _check_task(task)
    _check_label_source(label_source)
    try:
        return _load_image_and_label(path, task, label_source)
    except _UnusableBundle as exc:
        raise ValueError(f"{path}: {exc}") from exc


class _UnusableBundle(Exception):
    """
    Internal marker: a bundle cannot yield ``(image, label)`` for the task.
    内部マーカー：バンドルが当該タスクの ``(画像, ラベル)`` を生成できない。
    """


def _load_image_and_label(
    path: str, task: str, label_source: str
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load the input image and target for one bundle, dispatching on the task.
    タスクで振り分けて、1 バンドルの入力画像とターゲットを読み込む。

    See the module docstring for the per-task input/target table.
    タスクごとの入力／ターゲット対応は、モジュール docstring の表を参照。
    """
    if task == "binarize":
        return _binarize_pair(path, label_source)
    if task == "bg_mask":
        return _bg_mask_pair(path)
    if task == "background_surface":
        return _background_surface_pair(path)
    raise _UnusableBundle(f"unsupported task {task!r}")


def _binarize_pair(path: str, label_source: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load the ``calibrated`` image and the fiber/background mask (process B).
    ``calibrated`` 画像と繊維/背景マスクを読み込む（工程B）。

    The label is either the Segmenter's pre-filter intermediate mask (re-run
    from the bundle's stored parameters) or the bundle's final ``binarized``
    mask.
    ラベルは Segmenter のフィルタ前中間マスク（バンドル保存パラメータから
    再実行）か、バンドルの最終 ``binarized`` マスクのいずれか。
    """
    try:
        needed = ["calibrated"] + (
            ["binarized"] if label_source == LABEL_BUNDLE_BINARIZED else []
        )
        arrays = load_bundle(path, keys=needed)
    except Exception as exc:  # noqa: BLE001
        raise _UnusableBundle(f"cannot read required arrays: {exc}") from exc

    if "calibrated" not in arrays:
        raise _UnusableBundle("missing key: calibrated")
    calibrated = arrays["calibrated"]

    if label_source == LABEL_BUNDLE_BINARIZED:
        if "binarized" not in arrays:
            raise _UnusableBundle("missing key: binarized")
        label = arrays["binarized"]
    else:
        label = _segmenter_intermediate_mask(path, calibrated)

    label = (np.asarray(label) != 0).astype(np.int64)
    if label.shape != calibrated.shape:
        raise _UnusableBundle(
            f"label shape {label.shape} != calibrated shape {calibrated.shape}"
        )
    return calibrated, label


def _bg_mask_pair(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load the aligned raw height and the fiber-candidate mask (process A).
    整列済みの生の高さと繊維候補マスクを読み込む（工程A）。

    The label is the gradient-ridge fiber mask the background calibrator builds
    before it fills the background, recovered by re-running `BGCalibrator` with
    the bundle's stored parameters and combining the two directional
    intermediates exactly as the calibrator does internally. Re-running is
    deterministic, so the recovered mask is the one that produced the bundle.
    ラベルは、背景補正器が背景を埋める前に構築する勾配リッジ由来の繊維マスク。
    バンドル保存パラメータで `BGCalibrator` を再実行し、補正器内部と厳密に同じ
    方法で 2 方向の中間配列を合成して復元する。再実行は決定的なので、復元した
    マスクはそのバンドルを生んだものと一致する。
    """
    # Local import: the heavy preprocessing stack is only needed on this path.
    # ローカル import：重い前処理スタックはこの経路でのみ必要。
    from .pipeline import merge_params_dict, build_stages
    from .processed_image import ProcessedImage

    original = _load_original(path)
    params = _bundle_params(path)
    if params.bg_method not in _MASK_BG_METHODS:
        raise _UnusableBundle(
            f"bg_method {params.bg_method!r} builds no fiber mask "
            f"(need one of {', '.join(_MASK_BG_METHODS)})"
        )

    calibrator = build_stages(params).bg_calibrator
    image = ProcessedImage(original_AFM=original, name="ml_dataset")
    calibrator(image)
    if calibrator.tri_difx_fill is None or calibrator.tri_dify_fill is None:
        raise _UnusableBundle("BGCalibrator produced no fiber-mask intermediates")

    # Same combination the calibrator performs before filling the background:
    # a pixel is a fiber candidate when either directional pattern marks it.
    # The slicing is what trims one row and one column (see module docstring).
    # 補正器が背景を埋める前に行うのと同じ合成。いずれかの方向パターンが立てば
    # その画素は繊維候補。このスライスが 1 行 1 列を落とす（モジュール docstring 参照）。
    mask = (np.abs(calibrator.tri_difx_fill[1:, :])
            + np.abs(calibrator.tri_dify_fill[:, 1:])) > 0

    aligned = original[1:, 1:]
    label = mask.astype(np.int64)
    if label.shape != aligned.shape:
        raise _UnusableBundle(
            f"mask shape {label.shape} != aligned raw shape {aligned.shape}"
        )
    return aligned, label


def _background_surface_pair(path: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load the aligned raw height and the background surface in nm (process A).
    整列済みの生の高さと nm 単位の背景面を読み込む（工程A）。

    The target is what the pipeline actually subtracted: the aligned raw height
    minus the stored ``calibrated`` image. Deriving it from the stored result
    rather than re-running the calibrator keeps the target identical to the
    correction the bundle records, whichever background method produced it.
    ターゲットはパイプラインが実際に差し引いた量、すなわち整列済みの生の高さ
    から保存済み ``calibrated`` 画像を引いたもの。補正器を再実行せず保存結果から
    導くことで、どの背景方式で生成されたかによらず、ターゲットはバンドルが
    記録する補正と一致する。
    """
    try:
        arrays = load_bundle(path, keys=["calibrated"])
    except Exception as exc:  # noqa: BLE001
        raise _UnusableBundle(f"cannot read required arrays: {exc}") from exc
    if "calibrated" not in arrays:
        raise _UnusableBundle("missing key: calibrated")
    calibrated = arrays["calibrated"]

    original = _load_original(path)
    aligned = original[1:, 1:]
    if aligned.shape != calibrated.shape:
        raise _UnusableBundle(
            f"aligned raw shape {aligned.shape} != calibrated shape "
            f"{calibrated.shape}"
        )
    # Background height in nanometers; subtracting it from the raw image
    # reproduces the calibrated image.
    # nm 単位の背景高さ。生画像から差し引くと補正済み画像を再現する。
    surface_nm = np.asarray(aligned, dtype=np.float64) - np.asarray(
        calibrated, dtype=np.float64
    )
    return aligned, surface_nm


def _load_original(path: str) -> np.ndarray:
    """
    Load a bundle's raw, pre-correction height image.
    バンドルの補正前・生の高さ画像を読み込む。

    Prefers the self-contained ``original`` bundle key; when it is absent (it
    is written only with ``save_original``), falls back to the raw input file
    recorded in the bundle metadata if it still sits beside the bundle.
    自己完結した ``original`` キーを優先する。存在しない場合（``save_original``
    指定時のみ書かれる）は、バンドルのメタデータに記録された生の入力ファイルが
    バンドルの隣に残っていればそれを使う。
    """
    try:
        arrays = load_bundle(path, keys=["original"])
    except Exception:  # noqa: BLE001 - absence is handled by the fallback below.
        arrays = {}
    if "original" in arrays:
        return arrays["original"]

    meta = _safe_meta(path)
    name = meta.get("input_file")
    hint = ("re-process the input with save_original enabled to embed the raw "
            "image in the bundle")
    if not name:
        raise _UnusableBundle(
            f"no 'original' key and no recorded input file; {hint}")
    candidate = os.path.join(os.path.dirname(os.path.abspath(path)), str(name))
    if not os.path.exists(candidate):
        raise _UnusableBundle(
            f"no 'original' key and raw input {name!r} is not beside the "
            f"bundle; {hint}")
    # Local import: keeps the loader (and its optional .gwy dependency) off the
    # path taken by bundles that embed `original`.
    # ローカル import：`original` を同梱するバンドルの経路に、ローダー（および
    # その任意の .gwy 依存）を持ち込まない。
    from .afm_io import load_afm_image
    try:
        return load_afm_image(candidate)
    except Exception as exc:  # noqa: BLE001
        raise _UnusableBundle(
            f"cannot read raw input {name!r}: {exc}") from exc


def _bundle_params(path: str):
    """
    Return the `ProcParams` recorded in a bundle, or fail with a clear reason.
    バンドルに記録された `ProcParams` を返す。無ければ明確な理由で失敗する。
    """
    from .pipeline import merge_params_dict

    meta = _safe_meta(path)
    params_dict = meta.get("params")
    if not isinstance(params_dict, dict) or not params_dict:
        raise _UnusableBundle(
            "no analysis parameters in bundle; cannot re-run the pipeline stage")
    params, _, _ = merge_params_dict(params_dict)
    return params


def _segmenter_intermediate_mask(path: str, calibrated: np.ndarray) -> np.ndarray:
    """
    Re-run the Segmenter to recover its pre-component-filter mask.
    Segmenter を再実行し、成分フィルタ前のマスクを復元する。

    The Segmenter stores the output of ``_binaryzation`` on itself as
    ``binary_image`` before any component filter runs, so calling it and
    reading that attribute reproduces exactly the thresholding decision the
    binarize model is meant to replace. The analysis parameters are taken from
    the bundle so the reconstructed mask matches how the bundle was made.
    Segmenter は成分フィルタが走る前に ``_binaryzation`` の出力を
    ``binary_image`` として自身に保持する。呼び出してこの属性を読むことで、
    binarize モデルが置き換える対象のしきい値判断を厳密に再現できる。解析
    パラメータはバンドルから取り、再構成マスクがバンドル生成時と一致する
    ようにする。
    """
    # Local import: this is the only path that needs the heavy preprocessing
    # stack, so importing it here keeps `import lib.ml_dataset` cheap.
    # ローカル import：重い前処理スタックを要するのはこの経路だけなので、
    # ここで import して `import lib.ml_dataset` を軽く保つ。
    from .pipeline import merge_params_dict, build_stages
    from .processed_image import ProcessedImage

    meta = _safe_meta(path)
    params_dict = meta.get("params")
    if not isinstance(params_dict, dict) or not params_dict:
        raise _UnusableBundle(
            "no analysis parameters in bundle; cannot re-run Segmenter"
        )

    params, _, _ = merge_params_dict(params_dict)
    segmenter = build_stages(params).segmenter

    image = ProcessedImage(original_AFM=calibrated, name="ml_dataset")
    image.calibrated_image = calibrated
    segmenter(image)
    if segmenter.binary_image is None:
        raise _UnusableBundle("Segmenter did not produce an intermediate mask")
    return segmenter.binary_image


def _select_indices(
    labels: np.ndarray,
    max_samples_per_image: Optional[int],
    balance: bool,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Choose flat pixel indices to sample from one image's label vector.
    1 画像のラベルベクトルから抽出する平坦画素添字を選ぶ。

    With balancing, equal fiber and background counts are drawn (capped so the
    two together stay within `max_samples_per_image`); without it, a plain
    random subset is drawn up to the cap. An image missing either class under
    balancing yields no samples, because a single-class draw cannot teach a
    fiber-vs-background boundary.
    均衡ありでは繊維と背景を同数抽出する（両者の合計が
    `max_samples_per_image` に収まるよう上限を掛ける）。均衡なしでは上限まで
    素の無作為部分集合を抽出する。均衡下でいずれかのクラスを欠く画像は
    サンプルを生まない。単一クラスの抽出では繊維対背景の境界を学習できない
    ためである。
    """
    fiber_idx = np.flatnonzero(labels == LABEL_FIBER)
    bg_idx = np.flatnonzero(labels == LABEL_BACKGROUND)

    if balance:
        n_each = min(fiber_idx.size, bg_idx.size)
        if max_samples_per_image is not None:
            n_each = min(n_each, max_samples_per_image // 2)
        if n_each == 0:
            return np.empty(0, dtype=np.int64)
        sel_f = _draw(fiber_idx, n_each, rng)
        sel_b = _draw(bg_idx, n_each, rng)
        return np.concatenate([sel_f, sel_b])

    all_idx = np.arange(labels.size, dtype=np.int64)
    if max_samples_per_image is not None and all_idx.size > max_samples_per_image:
        return _draw(all_idx, max_samples_per_image, rng)
    return all_idx


def _draw(idx: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """
    Draw ``n`` indices from ``idx`` without replacement, or all if fewer exist.
    ``idx`` から ``n`` 個を非復元抽出する。数が足りなければ全て返す。
    """
    if idx.size <= n:
        return idx
    return rng.choice(idx, size=n, replace=False)


def _safe_meta(path: str) -> Dict:
    """
    Load bundle vlmeta, returning an empty dict on any failure.
    バンドル vlmeta を読み込み、失敗時は空辞書を返す。
    """
    try:
        meta = load_bundle_meta(path)
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _check_task(task: str) -> None:
    """Validate the requested task. 要求されたタスクを検証する。"""
    if task not in _IMPLEMENTED_TASKS:
        raise ValueError(
            f"task {task!r} is not supported by this module yet "
            f"(implemented: {', '.join(_IMPLEMENTED_TASKS)})"
        )


def _check_label_source(label_source: str) -> None:
    """Validate the requested label source. 要求されたラベル出所を検証する。"""
    if label_source not in LABEL_SOURCES:
        raise ValueError(
            f"label_source must be one of {LABEL_SOURCES}, got {label_source!r}"
        )
