# -*- coding: utf-8 -*-
"""
Train and cross-validate the tree-ensemble pixel classifier (process B first).
決定木アンサンブル画素分類器の学習と交差検証（まず工程B）。

This module trains the decision-tree side of the binarization model on a
`lib.ml_dataset.PixelDataset`. Per the ML plan (see
``private_docs/design/ml-decisions-record.ja.md``, internal), the tree ensemble
is implemented first as the baseline; a deep model is compared against it only
after it is shown to be beaten on a held-out test. Training uses scikit-learn;
inference never does -- a trained estimator is later exported to ONNX by the
(not-yet-built) ``lib.ml_model``, so GUI01/GUI04/GUI06 and the CLI need no
scikit-learn at inference time.
本モジュールは `lib.ml_dataset.PixelDataset` 上で二値化モデルの決定木側を
学習する。ML 計画（``private_docs/design/ml-decisions-record.ja.md``、非公開）に
従い、決定木アンサンブルをベースラインとして先に実装する。深層モデルは、
独立テストでこれを上回ると示せてから比較する。学習は scikit-learn を使うが、
推論は使わない。学習済み推定器は後に（未実装の）``lib.ml_model`` が ONNX へ
エクスポートするため、GUI01/GUI04/GUI06 と CLI は推論時に scikit-learn を
必要としない。

Cross-validation is group-aware / 交差検証はグループを考慮する
--------------------------------------------------------------
Folds are split by source image (`PixelDataset.groups`), never by pixel, so no
image contributes pixels to both the train and validation side of a fold.
Splitting pixels randomly would leak information, because neighboring pixels of
one image are strongly correlated, and would report optimistic scores.
フォールドは出所画像（`PixelDataset.groups`）で分割し、画素では分割しない。
1 枚の画像が同一フォールドの学習側と検証側の両方へ画素を供給しないように
する。画素を無作為に分割すると、1 枚の画像の近傍画素が強く相関するため
情報が漏れ、楽観的なスコアを報告してしまう。

Metric scope / 指標の範囲
-------------------------
The reported precision / recall / Dice / IoU are computed on the dataset's
sampled pixels. When the dataset was built with class balancing (the default),
these are balanced-sample scores and are optimistic relative to a whole image,
where background dominates. Honest whole-image evaluation -- predicting every
pixel of a held-out image and scoring the full mask, plus downstream skeleton
and measurement effects -- belongs to the later apply/compare step (GUI06), per
``private_docs/design/ml-gui-system-design.ja.md`` §18 (internal). These
sample-level scores are for model selection between classifiers, not for
claiming absolute performance.
報告する precision / recall / Dice / IoU はデータセットの抽出画素上で計算する。
データセットをクラス均衡（既定）で構築した場合、これらは均衡サンプルの
スコアであり、背景が支配する画像全体に比べ楽観的である。誠実な画像全体の
評価（独立画像の全画素を予測して全マスクを採点し、さらに下流の骨格・計測へ
の影響を見る）は後段の適用・比較ステップ（GUI06）の責務であり、
``private_docs/design/ml-gui-system-design.ja.md`` §18（非公開）に従う。この
サンプル単位スコアは分類器間のモデル選択用であり、絶対性能の主張には使わない。
"""

# ===== Standard library =====
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Machine-learning libraries =====
# scikit-learn is an optional, training-only dependency (see requirements-ml).
# It is imported at module top because this module's sole purpose is training;
# a GUI must therefore import lib.ml_train lazily (only when the user starts a
# training run) so plugin startup does not pay the scikit-learn import cost.
# scikit-learn は学習専用の任意依存（requirements-ml 参照）。本モジュールの
# 唯一の目的が学習のため module 冒頭で import する。したがって GUI は
# lib.ml_train を遅延 import すること（利用者が学習を開始したときのみ）。
# プラグイン起動時に scikit-learn の import コストを払わせないため。
from sklearn.ensemble import (
    HistGradientBoostingClassifier, HistGradientBoostingRegressor,
    RandomForestClassifier, RandomForestRegressor,
)
from sklearn.metrics import (
    f1_score, jaccard_score, mean_absolute_error, mean_squared_error,
    precision_score, r2_score, recall_score,
)
from sklearn.model_selection import GroupKFold

# ===== Project libraries =====
from .ml_dataset import LABEL_FIBER, PixelDataset, is_regression_task

# Classifier kinds. Fixed English identifiers recorded with a model; do not
# translate. `random_forest` is the default baseline; `hist_gradient_boosting`
# is scikit-learn's LightGBM-style booster, usually stronger on tabular data
# and available without any extra dependency.
# 分類器の種類。モデルとともに記録する固定英語識別子。翻訳しない。
# `random_forest` が既定のベースライン。`hist_gradient_boosting` は
# scikit-learn の LightGBM 系ブースターで、表形式データで通常より強く、
# 追加依存なしで使える。
MODEL_RANDOM_FOREST = "random_forest"
MODEL_HIST_GRADIENT_BOOSTING = "hist_gradient_boosting"
MODEL_KINDS = (MODEL_RANDOM_FOREST, MODEL_HIST_GRADIENT_BOOSTING)

# Default probability threshold above which a pixel is labeled fiber. Kept as a
# named constant because it is also what a "binarize" model records in its
# manifest as `segmentation_threshold`.
# 画素を繊維と判定する既定の確率しきい値。"binarize" モデルが manifest の
# `segmentation_threshold` として記録する値でもあるため名前付き定数にする。
DEFAULT_FIBER_THRESHOLD = 0.5


@dataclass(frozen=True)
class ModelConfig:
    """
    Classifier choice and its key hyperparameters.
    分類器の選択と主要ハイパーパラメータ。

    Attributes
    ----------
    kind
        One of `MODEL_KINDS`.
        `MODEL_KINDS` のいずれか。
    n_estimators
        Number of trees for `random_forest`. Ignored by
        `hist_gradient_boosting`, which uses `max_iter`.
        `random_forest` の木の本数。`hist_gradient_boosting` は `max_iter` を
        使うため無視する。
    max_iter
        Boosting iterations for `hist_gradient_boosting`. Ignored by
        `random_forest`.
        `hist_gradient_boosting` のブースティング反復数。`random_forest` は
        無視する。
    max_depth
        Maximum tree depth; ``None`` leaves it unbounded (`random_forest`) or
        at the estimator default (`hist_gradient_boosting`).
        木の最大深さ。``None`` で無制限（`random_forest`）または推定器の
        既定（`hist_gradient_boosting`）。
    learning_rate
        Learning rate for `hist_gradient_boosting`. Ignored by
        `random_forest`.
        `hist_gradient_boosting` の学習率。`random_forest` は無視する。
    random_state
        Seed for reproducible training.
        再現可能な学習のための乱数種。
    n_jobs
        Worker count for `random_forest`; ``-1`` uses all cores. Ignored by
        `hist_gradient_boosting` (single-threaded control here).
        `random_forest` のワーカー数。``-1`` で全コア。
        `hist_gradient_boosting` は無視する。
    """

    kind: str = MODEL_RANDOM_FOREST
    n_estimators: int = 200
    max_iter: int = 200
    max_depth: Optional[int] = None
    learning_rate: float = 0.1
    random_state: int = 0
    n_jobs: int = -1


@dataclass
class TrainResult:
    """
    Fitted estimator plus cross-validation metrics and provenance.
    学習済み推定器と交差検証指標・来歴。

    Attributes
    ----------
    estimator
        Final scikit-learn classifier fitted on all samples.
        全サンプルで学習した最終 scikit-learn 分類器。
    model_kind
        The `MODEL_KINDS` value used.
        使用した `MODEL_KINDS` の値。
    feature_names
        Feature-channel names in column order (from the dataset).
        列順の特徴チャンネル名（データセット由来）。
    feature_spec
        Feature-extractor spec, carried through for the model manifest.
        特徴抽出器の仕様。モデル manifest 用に引き継ぐ。
    cv_metrics
        Mean and standard deviation of each metric across folds; empty when
        cross-validation was skipped (fewer than two groups).
        フォールド間の各指標の平均と標準偏差。交差検証を省略した場合
        （グループが 2 未満）は空。
    fold_metrics
        Per-fold metric dictionaries, in fold order.
        フォールドごとの指標辞書（フォールド順）。
    feature_importances
        Per-feature importance when the estimator exposes it (`random_forest`);
        empty otherwise.
        推定器が公開する場合の特徴ごとの重要度（`random_forest`）。無ければ空。
    n_samples, n_features, n_groups
        Dataset dimensions used for training.
        学習に用いたデータセットの規模。
    fiber_threshold
        Probability threshold applied to the fiber class for the reported
        metrics and recorded for inference.
        報告指標に用い、推論用に記録する繊維クラスの確率しきい値。
    """

    estimator: object
    model_kind: str
    feature_names: List[str]
    feature_spec: Dict
    cv_metrics: Dict[str, float] = field(default_factory=dict)
    fold_metrics: List[Dict[str, float]] = field(default_factory=list)
    feature_importances: Dict[str, float] = field(default_factory=dict)
    n_samples: int = 0
    n_features: int = 0
    n_groups: int = 0
    fiber_threshold: float = DEFAULT_FIBER_THRESHOLD
    task: str = "binarize"

    @property
    def is_regression(self) -> bool:
        """
        Return whether this model predicts a continuous value.
        このモデルが連続値を予測するかどうかを返す。
        """
        return is_regression_task(self.task)


def build_estimator(config: ModelConfig, *, regression: bool = False):
    """
    Construct an unfitted scikit-learn estimator from a config.
    設定から未学習の scikit-learn 推定器を構築する。

    Parameters
    ----------
    config
        Estimator choice and hyperparameters.
        推定器の選択とハイパーパラメータ。
    regression
        Build a regressor (continuous target, e.g. ``background_surface``)
        instead of a classifier. The tree ensemble is otherwise identical, so
        the same hyperparameters apply to both.
        分類器ではなく回帰器（連続値ターゲット、例：``background_surface``）を
        構築する。それ以外は同じ決定木アンサンブルであり、同じハイパー
        パラメータが両方に適用される。

    Returns
    -------
    sklearn.base.BaseEstimator
        An estimator exposing ``fit`` plus ``predict_proba`` (classifier) or
        ``predict`` (regressor).
        ``fit`` と、``predict_proba``（分類器）または ``predict``（回帰器）を
        備えた推定器。

    Raises
    ------
    ValueError
        If `config.kind` is not a known estimator kind.
        `config.kind` が既知の推定器種別でない場合。
    """
    if config.kind == MODEL_RANDOM_FOREST:
        cls = RandomForestRegressor if regression else RandomForestClassifier
        return cls(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            random_state=config.random_state,
            n_jobs=config.n_jobs,
        )
    if config.kind == MODEL_HIST_GRADIENT_BOOSTING:
        cls = (HistGradientBoostingRegressor if regression
               else HistGradientBoostingClassifier)
        return cls(
            max_iter=config.max_iter,
            max_depth=config.max_depth,
            learning_rate=config.learning_rate,
            random_state=config.random_state,
        )
    raise ValueError(
        f"model kind must be one of {MODEL_KINDS}, got {config.kind!r}"
    )


def train(
    dataset: PixelDataset,
    config: ModelConfig = ModelConfig(),
    *,
    n_splits: int = 5,
    fiber_threshold: float = DEFAULT_FIBER_THRESHOLD,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> TrainResult:
    """
    Cross-validate, then fit a final classifier on the whole dataset.
    交差検証を行った後、データセット全体で最終分類器を学習する。

    Parameters
    ----------
    dataset
        Training samples with per-image groups.
        画像単位グループ付きの教師サンプル。
    config
        Classifier choice and hyperparameters.
        分類器の選択とハイパーパラメータ。
    n_splits
        Requested cross-validation fold count; clamped to the number of
        groups. Cross-validation is skipped when fewer than two groups exist,
        because a fold needs held-out images.
        要求する交差検証フォールド数。グループ数へ切り詰める。グループが
        2 未満のときは、フォールドに独立画像が必要なため交差検証を省略する。
    fiber_threshold
        Probability threshold for the fiber class used when turning
        `predict_proba` into labels for metrics.
        指標計算のため `predict_proba` をラベル化する際に用いる繊維クラスの
        確率しきい値。
    progress_cb
        Optional callback receiving fixed English stage strings
        (``"cv_fold_{i}_of_{n}"``, ``"final_fit"``, ``"done"``); the caller
        translates or logs them.
        固定英語ステージ文字列（``"cv_fold_{i}_of_{n}"``、``"final_fit"``、
        ``"done"``）を受け取る任意コールバック。翻訳・記録は呼び出し側。

    Returns
    -------
    TrainResult
        Fitted estimator, metrics, and provenance.
        学習済み推定器・指標・来歴。

    Raises
    ------
    ValueError
        If `config.kind` is unknown or the dataset is empty.
        `config.kind` が未知、またはデータセットが空の場合。
    """
    if dataset.X.size == 0:
        raise ValueError("dataset is empty; nothing to train on")

    def report(stage: str) -> None:
        if progress_cb is not None:
            progress_cb(stage)

    regression = dataset.is_regression
    n_groups = len(np.unique(dataset.groups))
    fold_metrics = cross_validate(
        dataset, config, n_splits=n_splits, fiber_threshold=fiber_threshold,
        progress_cb=progress_cb,
    )

    report("final_fit")
    estimator = build_estimator(config, regression=regression)
    estimator.fit(dataset.X, dataset.y)

    importances: Dict[str, float] = {}
    raw = getattr(estimator, "feature_importances_", None)
    if raw is not None:
        importances = {
            name: float(w) for name, w in zip(dataset.feature_names, raw)
        }

    report("done")
    return TrainResult(
        estimator=estimator,
        model_kind=config.kind,
        feature_names=list(dataset.feature_names),
        feature_spec=dict(dataset.feature_spec),
        cv_metrics=_aggregate_metrics(fold_metrics),
        fold_metrics=fold_metrics,
        feature_importances=importances,
        n_samples=int(dataset.X.shape[0]),
        n_features=int(dataset.X.shape[1]),
        n_groups=n_groups,
        fiber_threshold=fiber_threshold,
        task=dataset.task,
    )


def cross_validate(
    dataset: PixelDataset,
    config: ModelConfig = ModelConfig(),
    *,
    n_splits: int = 5,
    fiber_threshold: float = DEFAULT_FIBER_THRESHOLD,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, float]]:
    """
    Run group-aware cross-validation and return per-fold metrics.
    グループを考慮した交差検証を実行し、フォールドごとの指標を返す。

    Parameters
    ----------
    dataset
        Training samples with per-image groups.
        画像単位グループ付きの教師サンプル。
    config
        Classifier choice and hyperparameters.
        分類器の選択とハイパーパラメータ。
    n_splits
        Requested fold count; clamped to the number of groups. Returns an
        empty list when fewer than two groups exist.
        要求フォールド数。グループ数へ切り詰める。グループが 2 未満なら
        空リストを返す。
    fiber_threshold
        Probability threshold for the fiber class.
        繊維クラスの確率しきい値。
    progress_cb
        Optional per-fold progress callback (see `train`).
        フォールドごとの進捗コールバック（`train` 参照）。

    Returns
    -------
    list of dict
        One metric dictionary per fold, each with keys ``precision``,
        ``recall``, ``dice``, ``iou``, ``accuracy``.
        フォールドごとの指標辞書 1 つ。キーは ``precision``、``recall``、
        ``dice``、``iou``、``accuracy``。
    """
    groups = np.asarray(dataset.groups)
    n_groups = len(np.unique(groups))
    if n_groups < 2:
        # A fold must hold out at least one whole image; with a single group
        # there is nothing to validate against without leaking.
        # フォールドは少なくとも 1 枚の画像を除外する必要がある。グループが
        # 1 つでは、漏れなく検証する対象が無い。
        return []

    regression = dataset.is_regression
    splits = min(n_splits, n_groups)
    gkf = GroupKFold(n_splits=splits)

    fold_metrics: List[Dict[str, float]] = []
    for i, (train_idx, val_idx) in enumerate(
        gkf.split(dataset.X, dataset.y, groups), start=1
    ):
        if progress_cb is not None:
            progress_cb(f"cv_fold_{i}_of_{splits}")
        estimator = build_estimator(config, regression=regression)
        estimator.fit(dataset.X[train_idx], dataset.y[train_idx])
        y_true = dataset.y[val_idx]
        if regression:
            y_pred = estimator.predict(dataset.X[val_idx])
            fold_metrics.append(_regression_metrics(y_true, y_pred))
        else:
            y_pred = _predict_labels(
                estimator, dataset.X[val_idx], fiber_threshold)
            fold_metrics.append(_binary_metrics(y_true, y_pred))

    return fold_metrics


def _predict_labels(
    estimator, X: np.ndarray, fiber_threshold: float
) -> np.ndarray:
    """
    Turn an estimator's fiber-class probability into 0/1 labels at a threshold.
    推定器の繊維クラス確率を、しきい値で 0/1 ラベルへ変換する。

    Using an explicit threshold on ``predict_proba`` (rather than ``predict``)
    keeps the decision boundary identical to what a "binarize" model records as
    `segmentation_threshold` and applies at inference.
    ``predict``ではなく ``predict_proba`` に明示しきい値を適用することで、
    判定境界を "binarize" モデルが `segmentation_threshold` として記録し推論で
    適用するものと一致させる。
    """
    proba = estimator.predict_proba(X)
    # Locate the fiber class column; classes_ ordering is not guaranteed to be
    # [0, 1], so index by label rather than assuming column 1.
    # 繊維クラスの列を特定する。classes_ の順序は [0, 1] とは限らないため、
    # 列 1 と仮定せずラベルで添字する。
    classes = list(estimator.classes_)
    if LABEL_FIBER not in classes:
        # The training fold contained no fiber pixels; predict all background.
        # 学習フォールドに繊維画素が無かった。すべて背景と予測する。
        return np.zeros(X.shape[0], dtype=np.int64)
    fiber_col = classes.index(LABEL_FIBER)
    return (proba[:, fiber_col] >= fiber_threshold).astype(np.int64)


def _binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Compute binarization metrics for one fold.
    1 フォールド分の二値化指標を計算する。

    Dice equals the binary F1 score, and IoU equals the Jaccard score; both are
    reported under the names used in the AFM literature and the design docs.
    ``zero_division=0`` keeps a fold with no predicted (or no true) fiber pixels
    from producing a NaN that would poison the aggregate.
    Dice は二値 F1 スコアに、IoU は Jaccard スコアに等しい。いずれも AFM 分野と
    設計文書で使われる名称で報告する。``zero_division=0`` により、予測（または
    正解）の繊維画素が無いフォールドが NaN を生んで集計を汚すのを防ぐ。
    """
    return {
        "precision": float(precision_score(y_true, y_pred, pos_label=LABEL_FIBER, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, pos_label=LABEL_FIBER, zero_division=0)),
        "dice": float(f1_score(y_true, y_pred, pos_label=LABEL_FIBER, zero_division=0)),
        "iou": float(jaccard_score(y_true, y_pred, pos_label=LABEL_FIBER, zero_division=0)),
        "accuracy": float(np.mean(y_true == y_pred)),
    }


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Compute background-surface regression metrics for one fold.
    1 フォールド分の背景面回帰指標を計算する。

    ``mae`` and ``rmse`` are in the target's own unit -- nanometers for
    ``background_surface`` -- so they read directly as the height error the
    correction would introduce. ``bias`` is the signed mean error: a nonzero
    bias shifts the whole corrected image up or down, which matters more for
    height measurement than a symmetric spread of the same size.
    ``mae`` と ``rmse`` はターゲット自身の単位（``background_surface`` では nm）
    なので、補正が持ち込む高さ誤差としてそのまま読める。``bias`` は符号付きの
    平均誤差で、ゼロでない偏りは補正後画像全体を上下にずらす。これは同じ大きさの
    対称的なばらつきよりも高さ計測に効く。
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "bias": float(np.mean(y_pred - y_true)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _aggregate_metrics(fold_metrics: List[Dict[str, float]]) -> Dict[str, float]:
    """
    Reduce per-fold metrics to mean and standard deviation per metric.
    フォールドごとの指標を、指標ごとの平均と標準偏差へ集約する。

    Returns an empty dict when there are no folds, so a caller can tell that
    cross-validation did not run.
    フォールドが無い場合は空辞書を返し、交差検証が実行されなかったことを
    呼び出し側が判別できるようにする。
    """
    if not fold_metrics:
        return {}
    keys = fold_metrics[0].keys()
    aggregate: Dict[str, float] = {}
    for key in keys:
        values = np.array([fm[key] for fm in fold_metrics], dtype=float)
        aggregate[f"{key}_mean"] = float(values.mean())
        aggregate[f"{key}_std"] = float(values.std())
    return aggregate
