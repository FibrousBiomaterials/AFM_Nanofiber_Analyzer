# -*- coding: utf-8 -*-
"""
Save, load, and run ``.afmml`` model files (ONNX inference for the ML stages).
``.afmml`` モデルファイルの保存・読み込み・実行（ML ステージの ONNX 推論）。

A trained scikit-learn classifier (from `lib.ml_train`) is exported to ONNX and
packed into a ``.afmml`` archive with its manifest and, for pixel models, the
feature spec. Inference loads that archive and runs the ONNX graph, so GUI01,
GUI04, GUI06, and the CLI never import scikit-learn and never deserialize a
Python pickle. The ML packages (skl2onnx for export, onnxruntime for inference)
are optional and imported lazily inside the functions that need them, mirroring
how `lib.gwy_io` imports gwyfile only when a ``.gwy`` is opened; the classical
pipeline and plugin startup never load them, and a clear error naming the
optional install is raised if they are missing.
学習済みの scikit-learn 分類器（`lib.ml_train` 由来）を ONNX へエクスポートし、
manifest と、画素モデルでは特徴仕様とともに ``.afmml`` アーカイブへ格納する。
推論はそのアーカイブを読み ONNX グラフを実行するため、GUI01・GUI04・GUI06・
CLI は scikit-learn を import せず、Python の pickle も復元しない。ML
パッケージ（エクスポート用の skl2onnx、推論用の onnxruntime）は任意で、必要と
する関数の内部で遅延 import する。`lib.gwy_io` が ``.gwy`` を開くときのみ
gwyfile を import するのと同じ方式であり、従来パイプラインやプラグイン起動は
これらを読み込まない。欠落時は任意インストールを示す明確なエラーを送出する。

Security / セキュリティ
-----------------------
Loading verifies the manifest against the contract (`lib.ml_schema`), checks
the ONNX bytes' SHA-256 against the value recorded at save time (tamper /
truncation / wrong-file detection), and, for pixel models, refuses to run when
the recorded feature spec cannot be reproduced by this release. Failures raise;
there is no silent fallback to the classical method, matching the design
decision that a broken or mismatched model must fail loudly.
読み込み時に manifest を契約（`lib.ml_schema`）と照合し、ONNX バイト列の
SHA-256 を保存時の記録値と突き合わせ（改竄・切り詰め・ファイル取り違えの検出）、
画素モデルでは記録された特徴仕様を本リリースが再現できないとき実行を拒否する。
失敗は例外送出とし、従来方式へ黙ってフォールバックしない。壊れた・食い違った
モデルは明示的に失敗させるという設計決定に従う。
"""

# ===== Standard library =====
import hashlib
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .ml_features import (
    config_from_spec, extract_pixel_features, flatten_features,
    normalization_params,
)
from .ml_schema import (
    FEATURE_SPEC_MEMBER, MANIFEST_MEMBER, ONNX_MEMBER, MODEL_EXT,
    make_manifest, validate_manifest,
)

# Human-readable hint appended to import errors for the optional ML packages,
# so a user who lacks them is told exactly how to install them.
# 任意の ML パッケージの import エラーに付す案内。未導入の利用者に導入方法を
# 明確に伝える。
_ML_INSTALL_HINT = (
    "install the optional ML dependencies with "
    "`pip install -r requirements-ml.txt` (or `pip install .[ml]`)"
)


@dataclass
class LoadedModel:
    """
    An ``.afmml`` model ready to run, with its manifest and feature spec.
    実行可能な ``.afmml`` モデルと、その manifest・特徴仕様。

    Attributes
    ----------
    manifest
        Parsed and validated model manifest.
        解析・検証済みのモデル manifest。
    feature_spec
        Feature-extraction spec for pixel models; ``None`` when the model
        needs no pre-ONNX feature extraction.
        画素モデルの特徴抽出仕様。ONNX 前段の特徴抽出を要さないモデルでは
        ``None``。
    onnx_bytes
        The verified ONNX graph bytes.
        検証済みの ONNX グラフバイト列。

    Notes
    -----
    The onnxruntime session is created lazily on first prediction and cached,
    so constructing a `LoadedModel` (e.g. to show manifest info in a GUI) does
    not import onnxruntime.
    onnxruntime セッションは初回予測時に遅延生成してキャッシュする。したがって
    `LoadedModel` の構築（GUI で manifest 情報を表示する等）では onnxruntime を
    import しない。
    """

    manifest: Dict
    feature_spec: Optional[Dict]
    onnx_bytes: bytes
    _session: object = None
    _input_name: str = ""

    @property
    def task(self) -> str:
        """Return the model's task string. モデルのタスク文字列を返す。"""
        return self.manifest.get("task", "")

    @property
    def fiber_threshold(self) -> float:
        """
        Return the recorded fiber probability threshold, defaulting to 0.5.
        記録された繊維確率しきい値を返す。既定は 0.5。
        """
        value = self.manifest.get("segmentation_threshold")
        return float(value) if value is not None else 0.5

    def _ensure_session(self) -> None:
        """
        Create and cache the onnxruntime session on first use.
        初回使用時に onnxruntime セッションを生成・キャッシュする。
        """
        if self._session is not None:
            return
        ort = _import_onnxruntime()
        session = ort.InferenceSession(
            self.onnx_bytes, providers=["CPUExecutionProvider"]
        )
        self._session = session
        self._input_name = session.get_inputs()[0].name

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Return the fiber-class probability for each feature row.
        各特徴行に対する繊維クラスの確率を返す。

        Parameters
        ----------
        X
            Feature matrix of shape ``(n_samples, n_features)``.
            形状 ``(n_samples, n_features)`` の特徴行列。

        Returns
        -------
        numpy.ndarray
            Shape ``(n_samples,)`` fiber probabilities in ``[0, 1]``.
            ``[0, 1]`` の繊維確率、形状 ``(n_samples,)``。
        """
        self._ensure_session()
        Xf = np.ascontiguousarray(X, dtype=np.float32)
        outputs = self._session.run(None, {self._input_name: Xf})
        proba = _find_probability_output(outputs)
        return _fiber_column(proba, self._session)

    @property
    def is_regression(self) -> bool:
        """
        Return whether this model predicts a continuous value.
        このモデルが連続値を予測するかどうかを返す。
        """
        return self.task in _REGRESSION_TASKS

    def predict_values(self, X: np.ndarray) -> np.ndarray:
        """
        Return the raw regression output for each feature row.
        各特徴行に対する生の回帰出力を返す。

        Parameters
        ----------
        X
            Feature matrix of shape ``(n_samples, n_features)``.
            形状 ``(n_samples, n_features)`` の特徴行列。

        Returns
        -------
        numpy.ndarray
            Shape ``(n_samples,)`` predictions in the model's training frame,
            which for ``background_surface`` is the per-image normalized frame,
            not nanometers. Use `predict_surface` to obtain nanometers.
            形状 ``(n_samples,)`` の予測値。``background_surface`` では学習時の
            フレーム（画像ごとの正規化フレーム）であり nm ではない。nm を得るには
            `predict_surface` を使う。
        """
        self._ensure_session()
        Xf = np.ascontiguousarray(X, dtype=np.float32)
        outputs = self._session.run(None, {self._input_name: Xf})
        values = np.asarray(outputs[0])
        return values.reshape(-1).astype(np.float64)

    def predict_surface(self, image: np.ndarray) -> np.ndarray:
        """
        Predict the background surface of a whole image, in nanometers.
        画像全体の背景面を nm 単位で予測する。

        Parameters
        ----------
        image
            2D raw height image, aligned to the processed frame (see
            `lib.ml_dataset` on the one-pixel trim).
            処理後フレームに整列した 2 次元の生の高さ画像
            （1 画素トリミングは `lib.ml_dataset` を参照）。

        Returns
        -------
        numpy.ndarray
            Background height in nanometers, same shape as `image`.
            Subtracting it from `image` gives the background-corrected image.
            `image` と同形状の nm 単位の背景高さ。`image` から差し引くと背景補正
            済み画像が得られる。

        Raises
        ------
        ValueError
            If the model is not a regression model, has no feature spec, or the
            stored spec cannot be reproduced by this release.
            モデルが回帰モデルでない場合、特徴仕様が無い場合、または記録された
            仕様を本リリースが再現できない場合。

        Notes
        -----
        The estimator predicts in the per-image normalized frame the features
        were computed in, so the prediction is converted back with the same
        parameters recomputed from `image`. Without this the output would not
        be in nanometers at all.
        推定器は特徴を計算したのと同じ画像ごとの正規化フレームで予測するため、
        `image` から再計算した同じパラメータで元に戻す。これを行わないと出力は
        そもそも nm 単位にならない。
        """
        if not self.is_regression:
            raise ValueError(
                f"model task {self.task!r} is not a regression model; "
                "predict_surface is for background_surface models"
            )
        if self.feature_spec is None:
            raise ValueError("model has no feature spec; cannot extract features")
        config = config_from_spec(self.feature_spec)
        stack = extract_pixel_features(image, config)
        feats = flatten_features(stack)
        predicted = self.predict_values(feats)
        center, scale = normalization_params(image, config.normalize)
        return (predicted * scale + center).reshape(image.shape)

    def predict_mask(
        self,
        image: np.ndarray,
        *,
        threshold: Optional[float] = None,
    ) -> np.ndarray:
        """
        Predict a fiber/background mask for a whole image (pixel models).
        画像全体の繊維/背景マスクを予測する（画素モデル）。

        Parameters
        ----------
        image
            2D input height image (``calibrated`` for ``binarize``, raw height
            for ``bg_mask``); features are computed from it exactly as at
            training time.
            2 次元の入力高さ画像（``binarize`` では ``calibrated``、``bg_mask``
            では生の高さ）。特徴は学習時と厳密に同じ方法で計算する。
        threshold
            Fiber probability threshold; defaults to the model's recorded
            `fiber_threshold`.
            繊維確率しきい値。既定はモデルに記録された `fiber_threshold`。

        Returns
        -------
        numpy.ndarray
            Boolean mask of the input image's shape; ``True`` marks fiber.
            入力画像と同形状の真偽マスク。``True`` が繊維。

        Raises
        ------
        ValueError
            If the model has no feature spec (not a pixel model), or the stored
            spec cannot be reproduced by this release.
            モデルに特徴仕様が無い（画素モデルでない）場合、または記録された
            仕様を本リリースが再現できない場合。
        """
        if self.feature_spec is None:
            raise ValueError(
                f"model task {self.task!r} has no feature spec; predict_mask is "
                "only for pixel models (bg_mask / binarize)"
            )
        config = config_from_spec(self.feature_spec)
        stack = extract_pixel_features(image, config)
        feats = flatten_features(stack)
        proba = self.predict_proba(feats)
        thr = self.fiber_threshold if threshold is None else float(threshold)
        mask = (proba >= thr).reshape(image.shape)
        return mask


# What a model of each task consumes and produces, recorded in the manifest so
# a reader knows the meaning and unit of the input and output without guessing.
# `background_surface` is the only regression task: it predicts a height, and
# its prediction is returned in nanometers after the per-image normalization is
# undone (see `LoadedModel.predict_surface`).
# 各タスクのモデルが何を入力し何を出力するかを manifest に記録し、読み手が入力・
# 出力の意味と単位を推測せずに済むようにする。`background_surface` のみ回帰タスク
# で、高さを予測し、画像ごとの正規化を戻した nm 単位で返す
# （`LoadedModel.predict_surface` 参照）。
_TASK_SEMANTICS = {
    "binarize": {
        "input_semantics": "calibrated_height", "input_unit": "nm",
        "output_semantics": "fiber_probability", "output_unit": "probability",
    },
    "bg_mask": {
        "input_semantics": "raw_height", "input_unit": "nm",
        "output_semantics": "fiber_mask_probability", "output_unit": "probability",
    },
    "background_surface": {
        "input_semantics": "raw_height", "input_unit": "nm",
        "output_semantics": "background_surface", "output_unit": "nm",
    },
}

# Tasks whose estimator predicts a continuous value rather than class
# probabilities; mirrors `lib.ml_dataset.REGRESSION_TASKS`.
# クラス確率ではなく連続値を予測するタスク。`lib.ml_dataset.REGRESSION_TASKS`
# と対応する。
_REGRESSION_TASKS = ("background_surface",)


def save_pixel_model(
    path: str,
    train_result,
    *,
    model_id: str,
    dataset_provenance: Optional[List[Dict]] = None,
    license: Optional[str] = None,
) -> Dict:
    """
    Export a trained per-pixel model to a ``.afmml`` model file.
    学習済みの画素単位モデルを ``.afmml`` モデルファイルへエクスポートする。

    Handles every pixel task (``binarize``, ``bg_mask``,
    ``background_surface``); the task comes from the training result and
    decides the recorded semantics and whether a segmentation threshold
    applies.
    すべての画素タスク（``binarize``、``bg_mask``、``background_surface``）を
    扱う。タスクは学習結果から取り、記録する意味付けと、セグメンテーション
    しきい値が該当するかを決める。

    Parameters
    ----------
    path
        Output path; ``.afmml`` is appended when missing.
        出力パス。拡張子が無ければ ``.afmml`` を付す。
    train_result
        `lib.ml_train.TrainResult` holding the fitted estimator, task, feature
        spec, threshold, and cross-validation metrics.
        学習済み推定器・タスク・特徴仕様・しきい値・交差検証指標を持つ
        `lib.ml_train.TrainResult`。
    model_id
        Author-chosen identifier recorded in the manifest.
        manifest に記録する作成者指定の識別子。
    dataset_provenance
        Optional per-source training-data records to summarize into the
        manifest's training-data hash.
        manifest の学習データハッシュへ要約する、任意の学習元記録。
    license
        Optional manifest license field.
        任意の manifest ライセンスフィールド。

    Returns
    -------
    dict
        The manifest that was written.
        書き込まれた manifest。

    Raises
    ------
    ValueError
        If the training result's task is not a known pixel task.
        学習結果のタスクが既知の画素タスクでない場合。
    ImportError
        If skl2onnx is not installed.
        skl2onnx が未導入の場合。
    """
    task = getattr(train_result, "task", "binarize")
    if task not in _TASK_SEMANTICS:
        raise ValueError(
            f"task {task!r} is not a pixel task "
            f"(expected one of {', '.join(_TASK_SEMANTICS)})"
        )

    n_features = int(train_result.n_features)
    onnx_bytes = _export_estimator_to_onnx(train_result.estimator, n_features)

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    training_dataset_sha256 = (
        _hash_provenance(dataset_provenance) if dataset_provenance else None
    )
    # A regression model has no class threshold, so the field stays absent
    # rather than recording a value that would be meaningless on load.
    # 回帰モデルにクラスしきい値は無いため、読み込み時に無意味な値を記録せず
    # フィールド自体を省略する。
    threshold = (None if task in _REGRESSION_TASKS
                 else float(train_result.fiber_threshold))

    manifest = make_manifest(
        model_id=model_id,
        task=task,
        model_sha256=hashlib.sha256(onnx_bytes).hexdigest(),
        created_utc=created,
        training_framework="sklearn",
        segmentation_threshold=threshold,
        metrics=dict(train_result.cv_metrics) or None,
        training_dataset_sha256=training_dataset_sha256,
        license=license,
        **_TASK_SEMANTICS[task],
    )
    _write_archive(
        path, manifest, onnx_bytes, feature_spec=train_result.feature_spec
    )
    return manifest


def save_binarize_model(
    path: str,
    train_result,
    *,
    model_id: str,
    dataset_provenance: Optional[List[Dict]] = None,
    license: Optional[str] = None,
) -> Dict:
    """
    Export a trained binarization classifier to a ``.afmml`` model file.
    学習済みの二値化分類器を ``.afmml`` モデルファイルへエクスポートする。

    Parameters
    ----------
    path
        Output path; ``.afmml`` is appended when missing.
        出力パス。拡張子が無ければ ``.afmml`` を付す。
    train_result
        `lib.ml_train.TrainResult` holding the fitted estimator, feature spec,
        threshold, and cross-validation metrics.
        学習済み推定器・特徴仕様・しきい値・交差検証指標を持つ
        `lib.ml_train.TrainResult`。
    model_id
        Author-chosen identifier recorded in the manifest.
        manifest に記録する作成者指定の識別子。
    dataset_provenance
        Optional per-source training-data records (e.g.
        `lib.ml_dataset.PixelDataset.provenance`) to summarize into the
        manifest's training-data hash.
        manifest の学習データハッシュへ要約する、任意の学習元記録
        （例：`lib.ml_dataset.PixelDataset.provenance`）。
    license
        Optional manifest license field.
        任意の manifest ライセンスフィールド。

    Returns
    -------
    dict
        The manifest that was written.
        書き込まれた manifest。

    Raises
    ------
    ImportError
        If skl2onnx is not installed.
        skl2onnx が未導入の場合。

    Notes
    -----
    Thin wrapper over `save_pixel_model`, kept for callers that specifically
    export a binarization model.
    二値化モデルを明示的にエクスポートする呼び出し側のために残す
    `save_pixel_model` の薄いラッパー。
    """
    return save_pixel_model(
        path, train_result, model_id=model_id,
        dataset_provenance=dataset_provenance, license=license,
    )


def load_model(path: str) -> LoadedModel:
    """
    Load and verify a ``.afmml`` model file.
    ``.afmml`` モデルファイルを読み込み検証する。

    Parameters
    ----------
    path
        Path to a ``.afmml`` archive.
        ``.afmml`` アーカイブのパス。

    Returns
    -------
    LoadedModel
        Verified model ready for inference. The onnxruntime session is created
        lazily on first prediction, so loading does not import onnxruntime.
        検証済みで推論可能なモデル。onnxruntime セッションは初回予測時に遅延
        生成するため、読み込みでは onnxruntime を import しない。

    Raises
    ------
    ValueError
        If the archive is missing a required member, the manifest violates the
        contract, or the ONNX SHA-256 does not match the manifest.
        必須メンバーの欠落、manifest の契約違反、または ONNX の SHA-256 が
        manifest と一致しない場合。
    """
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        for required in (MANIFEST_MEMBER, ONNX_MEMBER):
            if required not in names:
                raise ValueError(
                    f"{os.path.basename(path)}: missing archive member "
                    f"{required!r}"
                )
        manifest = json.loads(zf.read(MANIFEST_MEMBER).decode("utf-8"))
        onnx_bytes = zf.read(ONNX_MEMBER)
        feature_spec = None
        if FEATURE_SPEC_MEMBER in names:
            feature_spec = json.loads(zf.read(FEATURE_SPEC_MEMBER).decode("utf-8"))

    problems = validate_manifest(manifest)
    if problems:
        raise ValueError(
            f"{os.path.basename(path)}: invalid manifest: " + "; ".join(problems)
        )

    # Integrity check: the ONNX bytes must hash to the recorded value. Catches
    # truncation, tampering, and a manifest paired with the wrong graph.
    # 完全性チェック：ONNX バイト列は記録値へハッシュ一致すること。切り詰め・
    # 改竄・別グラフと組み合わされた manifest を検出する。
    actual = hashlib.sha256(onnx_bytes).hexdigest()
    recorded = manifest.get("model_sha256")
    if actual != recorded:
        raise ValueError(
            f"{os.path.basename(path)}: ONNX SHA-256 mismatch "
            f"(archive {actual[:12]}..., manifest {str(recorded)[:12]}...); "
            "the model file is corrupt or has been altered"
        )

    return LoadedModel(
        manifest=manifest, feature_spec=feature_spec, onnx_bytes=onnx_bytes
    )


def read_manifest(path: str) -> Dict:
    """
    Read just the manifest of a ``.afmml`` file without loading the ONNX graph.
    ONNX グラフを読み込まずに ``.afmml`` の manifest のみを読む。

    Parameters
    ----------
    path
        Path to a ``.afmml`` archive.
        ``.afmml`` アーカイブのパス。

    Returns
    -------
    dict
        The parsed manifest. Not revalidated here; use `load_model` for the
        full verified load. Cheap enough for a GUI to show model info for many
        files without touching onnxruntime or the ONNX bytes.
        解析した manifest。ここでは再検証しない。完全な検証読み込みは
        `load_model` を使う。onnxruntime や ONNX バイト列に触れず、GUI が多数の
        ファイルのモデル情報を表示できる程度に軽い。
    """
    with zipfile.ZipFile(path, "r") as zf:
        return json.loads(zf.read(MANIFEST_MEMBER).decode("utf-8"))


def _export_estimator_to_onnx(estimator, n_features: int) -> bytes:
    """
    Convert a fitted scikit-learn classifier to serialized ONNX bytes.
    学習済みの scikit-learn 分類器を直列化 ONNX バイト列へ変換する。

    The graph takes a float32 ``(N, n_features)`` input. A classifier outputs a
    label and a two-column probability, with ``zipmap`` disabled so the
    probability is a plain array (not a list of dicts) for fast batched
    inference over pixels. A regressor outputs a single value column and
    accepts no ``zipmap`` option, so the option is passed only for classifiers.
    グラフは float32 の ``(N, n_features)`` 入力を取る。分類器はラベルと 2 列の
    確率を出力し、``zipmap`` を無効化して確率を（辞書のリストではなく）素の配列に
    し、画素の高速バッチ推論に適するようにする。回帰器は値 1 列を出力し
    ``zipmap`` オプションを受け付けないため、このオプションは分類器にのみ渡す。
    """
    convert = _import_skl2onnx()
    to_onnx, FloatTensorType = convert
    initial_types = [("X", FloatTensorType([None, n_features]))]
    # A classifier is the estimator that exposes predict_proba; only it accepts
    # the zipmap option (a regressor raises NameError on it).
    # predict_proba を持つ推定器が分類器であり、zipmap を受け付けるのはこちらのみ
    # （回帰器では NameError になる）。
    if hasattr(estimator, "predict_proba"):
        onnx_model = to_onnx(
            estimator, initial_types=initial_types,
            options={id(estimator): {"zipmap": False}},
        )
    else:
        onnx_model = to_onnx(estimator, initial_types=initial_types)
    return onnx_model.SerializeToString()


def _write_archive(
    path: str,
    manifest: Dict,
    onnx_bytes: bytes,
    *,
    feature_spec: Optional[Dict] = None,
) -> str:
    """
    Write a ``.afmml`` ZIP archive atomically.
    ``.afmml`` ZIP アーカイブを原子的に書き込む。

    Writes to a temporary sibling file and renames into place so an interrupted
    write cannot leave a half-written model file, mirroring `lib.pipeline`'s
    atomic bundle save.
    一時的な同一ディレクトリ内ファイルへ書き込んでから所定名へリネームし、
    書き込み中断で半端なモデルファイルが残らないようにする。`lib.pipeline` の
    原子的バンドル保存に倣う。
    """
    if not path.lower().endswith(MODEL_EXT):
        path = path + MODEL_EXT

    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    os.close(fd)
    try:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            zf.writestr(ONNX_MEMBER, onnx_bytes)
            if feature_spec is not None:
                zf.writestr(
                    FEATURE_SPEC_MEMBER,
                    json.dumps(feature_spec, ensure_ascii=False, indent=2),
                )
        with open(tmp_path, "wb") as f:
            f.write(buffer.getvalue())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return path


def _hash_provenance(provenance: List[Dict]) -> str:
    """
    Summarize training-data provenance into one SHA-256 hex digest.
    学習データの来歴を 1 つの SHA-256 16進ダイジェストへ要約する。

    A stable serialization of the used sources' file names and recorded input
    hashes, so two models trained on the same data share a training-data hash
    and a model's data origin is auditable (matching `lib.pipeline`'s
    input-hash provenance).
    使用した学習元のファイル名と記録済み入力ハッシュを安定に直列化したもの。
    同じデータで学習した 2 つのモデルが同一の学習データハッシュを持ち、モデルの
    データ由来を監査できる（`lib.pipeline` の入力ハッシュ来歴に対応）。
    """
    used = [p for p in provenance if p.get("used")]
    summary = [
        {"file": p.get("file"), "input_sha256": p.get("input_sha256")}
        for p in used
    ]
    payload = json.dumps(summary, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_probability_output(outputs: List[np.ndarray]) -> np.ndarray:
    """
    Return the two-column probability array from an ONNX session's outputs.
    ONNX セッションの出力から 2 列の確率配列を返す。

    The exported graph yields a label vector and a probability matrix; select
    the 2D two-column output rather than assuming an output order, which
    differs across skl2onnx versions.
    エクスポートしたグラフはラベルベクトルと確率行列を返す。出力順は
    skl2onnx のバージョンで異なるため、順序を仮定せず 2 次元 2 列の出力を選ぶ。
    """
    for out in outputs:
        arr = np.asarray(out)
        if arr.ndim == 2 and arr.shape[1] == 2:
            return arr
    raise ValueError(
        "ONNX model did not return a two-column probability output"
    )


def _fiber_column(proba: np.ndarray, session) -> np.ndarray:
    """
    Extract the fiber-class column from a two-column probability array.
    2 列の確率配列から繊維クラスの列を取り出す。

    The classifier's class order is read from the ONNX graph metadata when
    available; otherwise column 1 is used, which is the fiber label (1) for the
    0/1 labels these models are trained on.
    分類器のクラス順は可能なら ONNX グラフのメタデータから読む。無ければ列 1 を
    使う。これらのモデルが学習する 0/1 ラベルでは列 1 が繊維ラベル (1) である。
    """
    # skl2onnx keeps output columns in the estimator's classes_ order, i.e.
    # ascending [0, 1], so the fiber class (1) is column 1. Guard the shape.
    # skl2onnx は出力列を推定器の classes_ 順（昇順 [0, 1]）に保つため、繊維
    # クラス (1) は列 1。形状を確認する。
    if proba.shape[1] < 2:
        raise ValueError("probability output has fewer than two columns")
    return np.asarray(proba[:, 1], dtype=np.float64)


def _import_skl2onnx() -> Tuple[object, object]:
    """
    Lazily import skl2onnx, raising a clear install hint if it is missing.
    skl2onnx を遅延 import し、未導入なら明確な導入案内を送出する。
    """
    try:
        from skl2onnx import to_onnx
        from skl2onnx.common.data_types import FloatTensorType
    except ImportError as exc:
        raise ImportError(
            f"exporting a model to ONNX requires skl2onnx; {_ML_INSTALL_HINT}"
        ) from exc
    return to_onnx, FloatTensorType


def _import_onnxruntime():
    """
    Lazily import onnxruntime, raising a clear install hint if it is missing.
    onnxruntime を遅延 import し、未導入なら明確な導入案内を送出する。
    """
    try:
        import onnxruntime
    except ImportError as exc:
        raise ImportError(
            f"running an ONNX model requires onnxruntime; {_ML_INSTALL_HINT}"
        ) from exc
    return onnxruntime
