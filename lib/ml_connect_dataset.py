# -*- coding: utf-8 -*-
"""
Build fragment-pair training datasets from bundles and their label sidecars.
バンドルとそのラベル sidecar から断片ペアの教師データセットを構築する。

This is the process-C counterpart of `lib.ml_dataset`: it turns a set of
``.b2z`` bundles into the ``(X, y)`` matrix the connection model trains on.
The unit of analysis is a pair of skeleton fragment ends rather than a pixel,
and the targets come from human review rather than from distilling the existing
pipeline, because no rule in the pipeline knows which fragments belong to the
same fibril -- that judgement is the thing being learned.
本モジュールは工程Cにおける `lib.ml_dataset` の対応物で、``.b2z`` バンドル群を
連結モデルが学習する ``(X, y)`` 行列へ変換する。解析単位は画素ではなく骨格断片端の
ペアであり、ターゲットは既存パイプラインの蒸留ではなく人の検分に由来する。どの断片が
同一フィブリルに属するかを知る規則はパイプラインに無く、その判断こそが学習対象で
あるためである。

Where the labels come from / ラベルの出所
------------------------------------------
Each bundle needs a label sidecar written by the annotation workflow (see
`lib.ml_connect_labels`). Labels name endpoint coordinates, which are resolved
against the freshly loaded skeleton through `lib.ml_connect_features`; the
sidecar is bound to its skeleton by hash, so labels made for a different
skeleton are rejected rather than applied to the wrong fragments.
各バンドルには、アノテーション作業が書いたラベル sidecar が必要である
（`lib.ml_connect_labels` 参照）。ラベルは端点座標を指し、`lib.ml_connect_features`
を通じて新たに読み込んだ骨格へ解決される。sidecar は骨格へハッシュで結び付けられて
おり、別の骨格向けに作られたラベルは誤った断片へ適用されず拒否される。

Only decided candidates become samples: ``uncertain`` and ``unreviewed``
verdicts produce nothing at all, because neither states what the right answer
is and turning either into a negative would teach the model that a connection a
human could not judge -- or never looked at -- is wrong.
標本になるのは判断済みの候補だけである。``uncertain`` と ``unreviewed`` は何も
生成しない。どちらも正解を述べておらず、これらを負例に変えると、人が判断できなかった、
あるいは見てすらいない連結を「誤り」としてモデルに教えることになるためである。

Splitting / 分割
----------------
Every sample carries a group index identifying its source bundle, so a
downstream split keeps all pairs of one image on the same side of a train/test
split. Pairs within one image share fragments and background, so splitting them
randomly would leak information exactly as splitting pixels would.
各標本は出所バンドルを識別するグループ番号を持ち、下流の分割で 1 枚の画像の全ペアを
train/test の同じ側に留められる。1 枚の画像内のペアは断片と背景を共有するため、
無作為に分割すると画素の場合と同様に情報が漏れる。

This module imports only NumPy and the sibling label/feature modules; the heavy
tracking stack is imported lazily inside the function that rebuilds fragments,
so a caller that only scans a folder does not pay for it, and scikit-learn is
never imported here at all.
本モジュールが import するのは NumPy と姉妹モジュール（ラベル・特徴）のみ。重い
追跡スタックは断片を再構築する関数の内部で遅延 import するため、フォルダを走査する
だけの呼び出し側はその費用を払わない。scikit-learn はここでは一切 import しない。
"""

# ===== Standard library =====
import os
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .blosc2_io import bundle_has_keys, load_bundle
from .ml_connect_features import (
    PairFeatureConfig, endpoint_lookup, extract_pair_features, feature_names,
)
from .ml_connect_labels import (
    LABEL_TASK, label_path_for, load_labels, review_complete, skeleton_sha256,
    training_pairs,
)

# Bundle keys needed to rebuild fragments and measure a pair.
# 断片の再構築とペアの計測に必要なバンドルキー。
_REQUIRED_KEYS = ("calibrated", "skeletonized")


@dataclass
class BundleLabelStatus:
    """
    Whether one bundle can contribute connection training data, and why not.
    1 バンドルが連結の教師データを供給できるか、できない場合はその理由。

    Attributes
    ----------
    path
        Bundle file path.
        バンドルファイルのパス。
    usable
        Whether a valid label sidecar was found for this bundle.
        このバンドルに対する有効なラベル sidecar が見つかったか。
    reason
        Empty when usable; otherwise a fixed English explanation.
        使用可能なら空。そうでなければ固定英語の説明。
    n_decided
        Number of decided candidates (``connect`` plus ``reject``) available
        as samples.
        標本として使える判断済み候補数（``connect`` と ``reject`` の合計）。
    review_complete
        Whether every candidate in the sidecar has been decided. A partially
        reviewed image is still usable; its decided candidates are real
        judgements.
        sidecar 内のすべての候補が判断済みか。部分的にしか検分されていない画像も
        使用可能である。判断済みの候補は本物の判断だからである。
    """

    path: str
    usable: bool
    reason: str = ""
    n_decided: int = 0
    review_complete: bool = False


@dataclass
class PairDataset:
    """
    Assembled fragment-pair training samples with per-image grouping.
    画像単位のグループ付きで組み立てた断片ペアの教師標本。

    Satisfies the shape `lib.ml_train.TrainingDataset` declares, so it trains
    through the same code path as the pixel datasets without either module
    importing the other.
    `lib.ml_train.TrainingDataset` が宣言する形に適合するため、どちらのモジュールも
    相手を import することなく、画素データセットと同じ経路で学習できる。

    Attributes
    ----------
    X
        Feature matrix of shape ``(n_samples, n_features)``, dtype float32.
        形状 ``(n_samples, n_features)``、dtype float32 の特徴行列。
    y
        Class labels: 1 for a connection, 0 for a rejection.
        クラスラベル。連結が 1、非連結が 0。
    groups
        Source-bundle index per sample.
        標本ごとの出所バンドル番号。
    group_names
        Bundle stem for each group index.
        グループ番号ごとのバンドル stem。
    feature_names
        Ordered feature-channel names matching the columns of `X`.
        `X` の列に対応する順序付き特徴チャンネル名。
    feature_spec
        Pair feature-extractor spec, recorded with a trained model.
        断片ペア特徴抽出器の仕様。学習済みモデルとともに記録する。
    provenance
        One record per source bundle: file name, sample counts, and whether the
        review was complete.
        出所バンドルごとの記録：ファイル名、標本数、検分が完了していたか。
    task
        Always ``"connect"``; present so this dataset matches the shape
        `lib.ml_train` expects.
        常に ``"connect"``。`lib.ml_train` が期待する形に合わせるために持つ。
    """

    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    group_names: List[str]
    feature_names: List[str]
    feature_spec: Dict
    provenance: List[Dict] = field(default_factory=list)
    task: str = LABEL_TASK

    @property
    def is_regression(self) -> bool:
        """
        Return ``False``: connection is a binary decision, never a regression.
        ``False`` を返す。連結は二値判断であり回帰ではない。
        """
        return False

    @property
    def n_connect(self) -> int:
        """Return the number of positive samples. 正例の数を返す。"""
        return int(np.count_nonzero(self.y == 1))

    @property
    def n_reject(self) -> int:
        """Return the number of negative samples. 負例の数を返す。"""
        return int(np.count_nonzero(self.y == 0))


def scan_bundle_folder(folder: str) -> List[BundleLabelStatus]:
    """
    List ``.b2z`` bundles in a folder and whether each has usable labels.
    フォルダ内の ``.b2z`` バンドルを列挙し、各々に使用可能なラベルがあるか返す。

    Parameters
    ----------
    folder
        Directory to scan (non-recursive).
        走査するディレクトリ（非再帰）。

    Returns
    -------
    list of BundleLabelStatus
        One entry per ``.b2z`` file found, sorted by path.
        見つかった ``.b2z`` ファイルごとに 1 エントリ（パス順）。
    """
    statuses: List[BundleLabelStatus] = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".b2z"):
            continue
        statuses.append(inspect_bundle(os.path.join(folder, name)))
    return statuses


def inspect_bundle(bundle_path: str) -> BundleLabelStatus:
    """
    Report whether one bundle has a usable connection-label sidecar.
    1 バンドルに使用可能な連結ラベル sidecar があるかを報告する。

    Parameters
    ----------
    bundle_path
        Bundle file path.
        バンドルファイルのパス。

    Returns
    -------
    BundleLabelStatus
        Usability, sample count, and the reason when unusable.
        使用可否、標本数、使用不可の場合はその理由。

    Notes
    -----
    Validates the sidecar against the bundle's actual skeleton, so a label file
    left behind from an earlier run of the pipeline is reported as unusable
    here rather than silently contributing wrong samples later.
    sidecar をバンドルの実際の骨格と照合するため、以前のパイプライン実行から
    残っていたラベルファイルは、後で誤った標本を黙って供給するのではなく、ここで
    使用不可として報告される。
    """
    ok, missing = bundle_has_keys(bundle_path, list(_REQUIRED_KEYS))
    if not ok:
        return BundleLabelStatus(
            path=bundle_path, usable=False,
            reason="missing keys: " + ", ".join(missing))

    label_path = label_path_for(bundle_path)
    if not os.path.exists(label_path):
        return BundleLabelStatus(
            path=bundle_path, usable=False,
            reason=f"no label sidecar {os.path.basename(label_path)!r}; "
                   f"review this bundle's connections first")

    try:
        skeleton = load_bundle(bundle_path, keys=["skeletonized"])["skeletonized"]
        labels = load_labels(
            label_path, expected_skeleton_hash=skeleton_sha256(skeleton))
    except Exception as exc:  # noqa: BLE001 - surface any label problem here.
        return BundleLabelStatus(
            path=bundle_path, usable=False, reason=str(exc))

    decided = len(training_pairs(labels))
    complete = review_complete(labels)
    if decided == 0:
        return BundleLabelStatus(
            path=bundle_path, usable=False,
            reason="label sidecar has no decided candidates "
                   "(all uncertain or unreviewed)",
            review_complete=complete)

    return BundleLabelStatus(
        path=bundle_path, usable=True, n_decided=decided,
        review_complete=complete)


def build_pair_dataset(
    bundle_paths: Sequence[str],
    config: PairFeatureConfig = PairFeatureConfig(),
    *,
    skip_unusable: bool = True,
) -> PairDataset:
    """
    Assemble a fragment-pair training dataset from labelled bundles.
    ラベル付きバンドルから断片ペアの教師データセットを組み立てる。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles that have label sidecars beside them.
        隣にラベル sidecar を持つ ``.b2z`` バンドルのパス。
    config
        Pair feature-extraction configuration; also fixes the recorded spec.
        断片ペア特徴抽出の設定。記録される仕様も定める。
    skip_unusable
        When True, skip bundles without usable labels (each is still recorded
        in `provenance`); when False, raise on the first one.
        True のとき使用可能なラベルを持たないバンドルをスキップする（各々
        `provenance` には記録する）。False なら最初の 1 つで例外送出。

    Returns
    -------
    PairDataset
        Stacked samples across all usable bundles.
        使用可能な全バンドルにわたって積み上げた標本。

    Raises
    ------
    ValueError
        If no usable bundle yields samples, or `skip_unusable` is False and a
        bundle cannot be used.
        使用可能なバンドルが 1 つも標本を生まない場合、または `skip_unusable` が
        False で使用できないバンドルがあった場合。
    """
    X_parts: List[np.ndarray] = []
    y_parts: List[np.ndarray] = []
    group_parts: List[np.ndarray] = []
    group_names: List[str] = []
    provenance: List[Dict] = []

    for path in bundle_paths:
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            features, targets, complete = _pairs_for_bundle(path, config)
        except ValueError as exc:
            if skip_unusable:
                provenance.append({"file": os.path.basename(path),
                                   "used": False, "reason": str(exc)})
                continue
            raise

        if features.shape[0] == 0:
            provenance.append({"file": os.path.basename(path), "used": False,
                               "reason": "no decided candidates"})
            continue

        group_id = len(group_names)
        X_parts.append(features)
        y_parts.append(targets)
        group_parts.append(np.full(targets.size, group_id, dtype=np.int64))
        group_names.append(stem)
        provenance.append({
            "file": os.path.basename(path),
            "used": True,
            "n_samples": int(targets.size),
            "n_connect": int(np.count_nonzero(targets == 1)),
            "n_reject": int(np.count_nonzero(targets == 0)),
            # Recorded because a partially reviewed image contributes only the
            # candidates a human actually reached; knowing which images were
            # finished is needed to interpret the class balance later.
            # 部分検分の画像は人が実際に到達した候補のみを供給する。後でクラス
            # 均衡を解釈するには、どの画像が完了していたかを知る必要がある。
            "review_complete": bool(complete),
        })

    if not X_parts:
        raise ValueError(
            "no usable bundle produced connection samples "
            f"(scanned {len(bundle_paths)} path(s)); see per-file reasons")

    return PairDataset(
        X=np.concatenate(X_parts, axis=0),
        y=np.concatenate(y_parts, axis=0),
        groups=np.concatenate(group_parts, axis=0),
        group_names=group_names,
        feature_names=feature_names(config),
        feature_spec=config.spec(),
        provenance=provenance,
    )


def _pairs_for_bundle(
    bundle_path: str, config: PairFeatureConfig
) -> Tuple[np.ndarray, np.ndarray, bool]:
    """
    Build the feature matrix and targets for one labelled bundle.
    ラベル付きバンドル 1 つ分の特徴行列とターゲットを構築する。

    Returns
    -------
    tuple
        ``(features, targets, review_complete)``.
        ``(特徴, ターゲット, 検分完了フラグ)``。

    Raises
    ------
    ValueError
        If the bundle lacks required keys, has no sidecar, the sidecar does not
        match this skeleton, or a labelled endpoint is not a fragment end of
        this skeleton.
        必要キーを欠く、sidecar が無い、sidecar がこの骨格と一致しない、または
        ラベルの端点がこの骨格の断片端でない場合。
    """
    # Local import: rebuilding fragments pulls the tracking stack, which a
    # folder scan does not need.
    # ローカル import：断片の再構築は追跡スタックを要するが、フォルダ走査には不要。
    from .measure import load_tracking_image

    ok, missing = bundle_has_keys(bundle_path, list(_REQUIRED_KEYS))
    if not ok:
        raise ValueError(f"missing keys: {', '.join(missing)}")

    label_path = label_path_for(bundle_path)
    if not os.path.exists(label_path):
        raise ValueError(f"no label sidecar {os.path.basename(label_path)!r}")

    arrays = load_bundle(bundle_path, keys=["calibrated", "skeletonized"])
    calibrated = arrays["calibrated"]
    skeleton = arrays["skeletonized"]

    # The pixel size only scales `Fiber.horizon`, which no pair feature reads;
    # pass 1.0 so a dataset can be built without knowing the scan size, and so
    # two bundles with different scales still yield comparable features.
    # ピクセルサイズは `Fiber.horizon` を縮尺するだけで、断片ペア特徴はこれを
    # 読まない。走査範囲を知らなくてもデータセットを構築でき、スケールの異なる
    # 2 バンドルでも比較可能な特徴になるよう 1.0 を渡す。
    image = load_tracking_image(bundle_path, 1.0)
    fragments = image.fibers_in_image_parallel()
    lookup = endpoint_lookup(fragments)

    labels = load_labels(
        label_path,
        expected_skeleton_hash=skeleton_sha256(skeleton),
        known_endpoints=set(lookup),
    )

    rows: List[np.ndarray] = []
    targets: List[int] = []
    for point_a, point_b, target in training_pairs(labels):
        end_a, end_b = lookup[point_a], lookup[point_b]
        rows.append(extract_pair_features(
            fragments, end_a, end_b, calibrated, config))
        targets.append(target)

    if not rows:
        return (np.empty((0, len(feature_names(config))), dtype=np.float32),
                np.empty(0, dtype=np.int64),
                review_complete(labels))

    return (np.vstack(rows).astype(np.float32, copy=False),
            np.asarray(targets, dtype=np.int64),
            review_complete(labels))
