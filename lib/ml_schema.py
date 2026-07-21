# -*- coding: utf-8 -*-
"""
Executable schema for the ``.afmml`` machine-learning model contract.
``.afmml`` 機械学習モデル契約の実行可能スキーマ。

This module is the single in-code definition of the model-file contract: the
archive layout, the manifest keys, the task/framework/format vocabularies, and
the format version. Design background and the decisions this module
implements live in ``private_docs/design/ml-gui-system-design.ja.md`` §14 and
``private_docs/design/ml-decisions-record.ja.md`` (internal, not part of the
public repository), but this code is the source of truth, mirroring how
`lib.bundle_schema` owns the ``.b2z`` contract.
本モジュールはモデルファイル契約（アーカイブ構成、manifestキー、
タスク/フレームワーク/形式の語彙、形式バージョン）のコード上の唯一の定義で
ある。設計の背景と本モジュールが実装する決定事項は
``private_docs/design/ml-gui-system-design.ja.md`` §14 と
``private_docs/design/ml-decisions-record.ja.md``（非公開、公開リポジトリの
対象外）にあるが、正準は本コードとする。`lib.bundle_schema` が ``.b2z``
契約を持つのと同じ関係である。

Contract summary / 契約の要約
-----------------------------
- An ``.afmml`` file is a ZIP archive holding at least `MANIFEST_MEMBER`
  (plain JSON) and `ONNX_MEMBER` (the ONNX inference graph).
  ``.afmml`` は少なくとも `MANIFEST_MEMBER`（平文 JSON）と `ONNX_MEMBER`
  （ONNX 推論グラフ）を保持する ZIP アーカイブ。
- Inference is ONNX-only by policy: no Python pickle/joblib estimator is ever
  loaded by GUI01, GUI04, GUI05, GUI06, or the CLI. Restoring an ONNX graph
  does not execute arbitrary Python code, unlike restoring a scikit-learn
  pickle. This was an explicit, deliberate decision (see the design record
  above): training may use scikit-learn or PyTorch, but both export to ONNX
  before the model file is written, so no inference-side code ever needs to
  import scikit-learn or PyTorch, and no inference-side code ever
  deserializes a pickle.
  推論は方針として ONNX のみ： GUI01・GUI04・GUI05・GUI06・CLI のいずれも
  Python の pickle/joblib 推定器を読み込まない。ONNX グラフの復元は
  scikit-learn の pickle 復元と異なり任意 Python コードを実行しない。これは
  明示的に決定された方針であり（上記の設計記録を参照）、学習には
  scikit-learn または PyTorch を使いうるが、モデルファイル書き出し前に必ず
  ONNX へエクスポートするため、推論側のどのコードも scikit-learn や
  PyTorch を import する必要がなく、pickle を復元することもない。
- The manifest is a single flat schema shared by every `task`; keys that do
  not apply to a given task are simply omitted rather than gated by
  task-specific required/optional/forbidden rules. This was a deliberate
  simplicity choice over a per-task validation scheme (see the design
  record); a key's absence must be read as "not recorded for this model",
  not as an error.
  manifest はすべての `task` が共有する単一のフラットなスキーマである。
  あるタスクに当てはまらないキーは、タスク別の必須／任意／禁止ルールで
  弾くのではなく、単に省略する。これはタスク別検証方式に対して意図的に
  選んだ単純さ優先の方針であり（設計記録を参照）、キーの欠落は「このモデル
  では記録されていない」であって「不正」ではない。
- `task` states which pipeline decision the model replaces. Four tasks exist
  because two pipeline stages each have two competing model classes under
  active comparison (a tree-ensemble classifier and a deep model), not
  because the pipeline has four stages.
  `task` はモデルが置き換えるパイプラインの判断を示す。タスクが 4 つ
  あるのは、パイプラインの段数が 4 つだからではなく、2 つの段それぞれで
  互いに競合する 2 種類のモデルクラス（決定木アンサンブルと深層モデル）を
  比較検証中だからである。

This module depends only on the standard library, so GUI plugins can import it
to inspect or validate a model manifest without pulling in scikit-learn,
PyTorch, or an ONNX runtime.
本モジュールの依存は標準ライブラリのみとし、GUI プラグインが scikit-learn・
PyTorch・ONNX ランタイムを読み込まずにモデルの manifest を検査・検証できる
ようにする。
"""

# ===== Standard library =====
from typing import Dict, List, Optional, Sequence

# Version of the model-file layout itself, distinct from the application
# release recorded elsewhere as "software_version". Bump only when manifest
# keys, the archive layout, or the meaning of a value changes.
# モデルファイル形式自体のバージョン。アプリのリリース（他所で記録される
# "software_version"）とは別物。manifestキー・アーカイブ構成・値の意味が
# 変わるときのみ繰り上げる。
MODEL_FORMAT_VERSION = "1.0"

# Versions this code base can read. Readers reject unknown versions loudly so
# a future format change cannot be silently misinterpreted by old releases.
# 本コードベースが読める形式バージョン。未知のバージョンは明示的に拒否し、
# 将来の形式変更を旧リリースが黙って誤解釈しないようにする。
SUPPORTED_MODEL_VERSIONS = ("1.0",)

# File extension for a model archive.
MODEL_EXT = ".afmml"

# Archive member names. MANIFEST_MEMBER is plain JSON and readable on its own,
# without touching ONNX_MEMBER. ONNX_MEMBER holds the inference graph; loading
# it (via an ONNX runtime) never executes arbitrary Python code, which is the
# reason ONNX was chosen over a pickle/joblib estimator for every task.
# アーカイブのメンバー名。MANIFEST_MEMBER は ONNX_MEMBER に触れずに単体で
# 読める平文 JSON。ONNX_MEMBER は推論グラフを保持し、その読み込み（ONNX
# ランタイム経由）は任意 Python コードを実行しない。これが全タスクで
# pickle/joblib 推定器ではなく ONNX を選んだ理由である。
MANIFEST_MEMBER = "manifest.json"
ONNX_MEMBER = "model.onnx"

# Optional archive member holding the feature-extraction spec for models whose
# input tensor is computed in Python before the ONNX graph (the pixel
# classifiers: their ONNX input is a feature vector, not the raw image). It
# records exactly how those features were produced so inference can reproduce
# them; a mismatch would silently degrade accuracy (see lib.ml_features). This
# is a separate member rather than a manifest key so the manifest key set stays
# exactly the §14.1 contract (see module docstring on the flat schema); its
# absence simply means the model needs no pre-ONNX feature extraction.
# ONNX グラフの前段で入力テンソルを Python 側で計算するモデル（画素分類器：
# その ONNX 入力は生画像ではなく特徴ベクトル）向けに、特徴抽出仕様を保持する
# 任意のアーカイブメンバー。それらの特徴の生成方法を厳密に記録し、推論で
# 再現できるようにする。不一致は精度を静かに劣化させる（lib.ml_features 参照）。
# manifest のキー集合を §14.1 契約そのものに保つため（フラットスキーマに関する
# モジュール docstring参照）、manifest キーではなく別メンバーとする。欠落は
# ONNX 前段の特徴抽出を要さないモデルであることを意味するにすぎない。
FEATURE_SPEC_MEMBER = "feature_spec.json"

# Which pipeline decision a model replaces. These are internal identifiers,
# not user-visible text; do not translate them.
# モデルが置き換えるパイプライン上の判断。内部識別子でありユーザー表示
# 文字列ではないため翻訳しない。
#   bg_mask             : Per-pixel fiber/background classification feeding
#                          the existing background fill (BGCalibrator's
#                          Navier-Stokes inpaint + Savitzky-Golay smoothing);
#                          the pixel classifier is the only replaced part.
#                          既存の背景埋め（BGCalibrator の Navier-Stokes
#                          inpaint + Savitzky-Golay 平滑化）へ渡す画素単位の
#                          繊維/背景分類。置き換えるのは画素分類器のみ。
#   background_surface  : Direct regression of the background height surface
#                          (nm), subtracted from the raw image; replaces the
#                          entire background-generation step, not just the
#                          mask.
#                          背景高さ面 (nm) を直接回帰し、生画像から差し引く。
#                          マスクだけでなく背景生成ステップ全体を置き換える。
#   binarize             : Per-pixel fiber probability/mask replacing
#                          Segmenter._binaryzation; the component filters
#                          after it still run. Shared by both competing
#                          model classes for this stage (a tree ensemble and
#                          a U-Net); `training_framework` distinguishes them,
#                          not `task`.
#                          Segmenter._binaryzation を置き換える画素単位の
#                          繊維確率/マスク。後段の成分フィルタは従来どおり
#                          動く。この段で競合する 2 モデルクラス（決定木
#                          アンサンブルと U-Net）が共有する task。両者の
#                          区別は `task` ではなく `training_framework` が担う。
#   connect              : Probability that two candidate skeleton-fragment
#                          endpoints belong to one fibril, consumed through a
#                          decoupled interface (candidate-pair feature vector
#                          -> probability) so the underlying fragment
#                          enumeration (today's connect_fiber_fragments, or a
#                          future graph representation) can change without
#                          invalidating a trained model or its training data.
#                          2 つの候補骨格断片端点が同一フィブリルに属する
#                          確率。分離されたインターフェース（候補ペアの
#                          特徴ベクトル -> 確率）を通して使われるため、下層の
#                          断片列挙方式（現行の connect_fiber_fragments、
#                          または将来のグラフ表現）が変わっても学習済み
#                          モデルと教師データが無効にならない。
MODEL_TASKS = ("bg_mask", "background_surface", "binarize", "connect")

# Tasks belonging to the same pipeline stage, grouped for GUI use (e.g. GUI06
# offering only background-stage models in a background-model picker). This
# is an identity check ("is this model for the right stage"), not the
# per-task required/optional key validation that was deliberately not
# adopted for the manifest itself (see module docstring).
# 同じパイプライン段に属するタスクを GUI 用途でグループ化する（例：GUI06 の
# 背景モデル選択欄には背景段のタスクのみを提示する）。これは「このモデルが
# 正しい段のものか」という識別チェックであり、manifest 自体には意図的に
# 採用しなかったタスク別の必須/任意キー検証（モジュール docstring参照）とは
# 別物。
BACKGROUND_TASKS = ("bg_mask", "background_surface")
SEGMENTATION_TASKS = ("binarize",)
CONNECTION_TASKS = ("connect",)

# Frameworks used to train a model. Both export to ONNX before the model file
# is written (see module docstring), so this key is provenance only; it never
# gates which runtime GUI01/GUI04/GUI05/GUI06/CLI needs at inference time.
# モデルの学習に使ったフレームワーク。いずれもモデルファイル書き出し前に
# ONNX へエクスポートするため（モジュール docstring参照）、このキーは
# 来歴情報にすぎず、推論時に GUI01/GUI04/GUI05/GUI06/CLI が必要とする
# ランタイムを左右しない。
TRAINING_FRAMEWORKS = ("sklearn", "pytorch")

# Inference formats accepted for `ONNX_MEMBER`. Currently a single-element
# tuple by policy (see module docstring); kept as a checked vocabulary rather
# than a hardcoded literal so a second safe format could be added later
# without touching every call site.
# `ONNX_MEMBER` として受け付ける推論形式。方針により現在は要素数 1
# （モジュール docstring参照）。将来 2 つ目の安全な形式を追加する場合に
# 全呼び出し箇所を触らずに済むよう、ハードコードされたリテラルではなく
# 検査対象の語彙として保持する。
INFERENCE_FORMATS = ("onnx",)

# Manifest keys that carry meaning for every task, per
# ml-gui-system-design.ja.md §14.1. Absence of any of these is always an
# error, regardless of task.
# どのタスクでも意味を持つ manifest キー（ml-gui-system-design.ja.md §14.1
# 準拠）。タスクによらず、これらの欠落は常にエラー。
REQUIRED_MANIFEST_KEYS = (
    "model_format_version",
    "model_id",
    "task",
    "model_sha256",
    "created_utc",
    "training_framework",
    "inference_format",
    "input_semantics",
    "input_unit",
    "output_semantics",
    "output_unit",
)

# Manifest keys recorded when relevant, per §14.1. A given model's task may
# make some of these meaningless (e.g. `segmentation_threshold` for a
# `background_surface` model); by the flat-schema decision (module
# docstring), such keys are simply omitted, not validated against `task`.
# 該当する場合に記録される manifest キー（§14.1 準拠）。あるモデルの
# `task` によっては一部が無意味になりうる（`background_surface` モデルに
# おける `segmentation_threshold` 等）。フラットスキーマの決定
# （モジュール docstring参照）により、そうしたキーは `task` と照合せず
# 単に省略する。
OPTIONAL_MANIFEST_KEYS = (
    "alignment",                # Spatial alignment convention, e.g. "crop_top_and_left_by_one".
    "normalization",            # Input normalization scheme and parameters.
    "tile_size",                # [height, width] inference tile size in pixels, for tiled models.
    "tile_overlap",              # [height, width] overlap between tiles in pixels.
    "pixel_size_range_nm",       # Applicable per-axis pixel-size range, for out-of-range detection.
    "segmentation_threshold",    # Probability threshold applied to a "binarize" model's output.
    "training_dataset_id",       # Identifier of the dataset manifest used to train this model.
    "training_dataset_sha256",   # Hash of the training dataset manifest, for provenance.
    "metrics",                   # Cross-validation / held-out evaluation results.
    "license",                   # License under which this model file is distributed.
)


def validate_manifest(
    meta: Dict,
    require_task: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Check model manifest contents against the ``.afmml`` contract.
    モデル manifest の内容を ``.afmml`` 契約と照合する。

    Only structural and vocabulary checks are performed here (keys present,
    values of a sane type, known enums). Checks that require reading the
    model file itself -- the recorded `model_sha256` actually matching
    `ONNX_MEMBER`'s bytes, the ONNX graph's input/output tensor shapes, or
    finiteness of a sample inference output -- belong to the not-yet-built
    `lib.ml_model`, because this module is deliberately dependency-free and
    never opens the archive.
    ここで行うのは構造・語彙のチェックのみ（キーの存在、値の型の妥当性、
    既知の列挙値）。モデルファイル自体を読む必要のあるチェック
    （記録された `model_sha256` が実際に `ONNX_MEMBER` のバイト列と一致
    するか、ONNX グラフの入出力テンソル形状、サンプル推論出力の有限性）は
    未実装の `lib.ml_model` の責務とする。本モジュールは意図的に依存を
    持たず、アーカイブを開かないため。

    Parameters
    ----------
    meta
        Parsed contents of `MANIFEST_MEMBER`.
        `MANIFEST_MEMBER` を解析した内容。
    require_task
        Tasks the caller accepts at this call site, typically
        `BACKGROUND_TASKS`, `SEGMENTATION_TASKS`, or `CONNECTION_TASKS`.
        ``None`` skips the check. This is a stage-identity check, not the
        per-task key validation the manifest schema deliberately omits (see
        module docstring).
        呼び出し側がこの箇所で受け付けるタスク。通常は `BACKGROUND_TASKS`、
        `SEGMENTATION_TASKS`、`CONNECTION_TASKS` のいずれか。``None`` なら
        検査を省略する。これは段の識別チェックであり、manifest スキーマが
        意図的に省いたタスク別キー検証ではない（モジュール docstring参照）。

    Returns
    -------
    list of str
        Fixed English problem descriptions; empty when the manifest
        conforms. Callers translate or wrap as needed, matching
        `validate_bundle` and `validate_params`.
        固定英語の問題記述リスト。契約に適合していれば空。`validate_bundle`
        や `validate_params` と同様、翻訳や文脈付けは呼び出し側で行う。
    """
    problems: List[str] = []

    if not isinstance(meta, dict):
        return [f"model manifest must be a JSON object, got {type(meta).__name__}"]

    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in meta]
    if missing:
        problems.append("missing required manifest keys: " + ", ".join(missing))

    version = meta.get("model_format_version")
    if version is not None and version not in SUPPORTED_MODEL_VERSIONS:
        problems.append(
            f"unsupported model format version {version!r} "
            f"(supported: {', '.join(SUPPORTED_MODEL_VERSIONS)})"
        )

    task = meta.get("task")
    if task is not None and task not in MODEL_TASKS:
        problems.append(f"task must be one of {MODEL_TASKS}, got {task!r}")
    elif task is not None and require_task is not None and task not in require_task:
        # A valid model for the wrong stage: name both sides, because this is
        # the mistake a user actually makes (picking a "binarize" model in a
        # background-model picker, say) and a bare "invalid task" would not
        # explain it.
        # 有効だが段が異なるモデル。利用者が実際に犯す誤り（背景モデル選択欄で
        # "binarize" モデルを選ぶ等）なので、単なる "invalid task" ではなく
        # 両者を明示する。
        problems.append(
            f"model task {task!r} cannot be used here "
            f"(this stage accepts: {', '.join(require_task)})"
        )

    framework = meta.get("training_framework")
    if framework is not None and framework not in TRAINING_FRAMEWORKS:
        problems.append(
            f"training_framework must be one of {TRAINING_FRAMEWORKS}, "
            f"got {framework!r}"
        )

    inference_format = meta.get("inference_format")
    if inference_format is not None and inference_format not in INFERENCE_FORMATS:
        problems.append(
            f"inference_format must be one of {INFERENCE_FORMATS}, "
            f"got {inference_format!r}"
        )

    for key in ("model_id", "model_sha256", "created_utc",
                "input_semantics", "input_unit",
                "output_semantics", "output_unit"):
        if key in meta and not isinstance(meta[key], str):
            problems.append(
                f"{key} must be a string, got {type(meta[key]).__name__}"
            )

    problems.extend(_optional_key_problems(meta))

    return problems


def _optional_key_problems(meta: Dict) -> List[str]:
    """
    Check the types of optional manifest keys, when present.
    任意 manifest キーの型を、存在する場合に検査する。

    Structure only; whether a key is meaningful for this model's `task` is
    deliberately not checked (see module docstring).
    構造のみを検査する。当該モデルの `task` にとってそのキーが意味を持つ
    かどうかは意図的に検査しない（モジュール docstring参照）。
    """
    problems: List[str] = []

    if "alignment" in meta and not isinstance(meta["alignment"], str):
        problems.append(
            f"alignment must be a string, got {type(meta['alignment']).__name__}"
        )

    if "normalization" in meta and not isinstance(meta["normalization"], dict):
        problems.append(
            f"normalization must be a JSON object, "
            f"got {type(meta['normalization']).__name__}"
        )

    for key in ("tile_size", "tile_overlap"):
        if key not in meta:
            continue
        value = meta[key]
        if (not isinstance(value, (list, tuple)) or len(value) != 2
                or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0
                           for v in value)):
            problems.append(
                f"{key} must be [height, width] with two positive ints, "
                f"got {value!r}"
            )

    if "pixel_size_range_nm" in meta and not isinstance(meta["pixel_size_range_nm"], dict):
        problems.append(
            f"pixel_size_range_nm must be a JSON object, "
            f"got {type(meta['pixel_size_range_nm']).__name__}"
        )

    if "segmentation_threshold" in meta:
        value = meta["segmentation_threshold"]
        if value is not None:
            is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not (is_number and 0.0 <= value <= 1.0):
                problems.append(
                    f"segmentation_threshold must be null or a number in "
                    f"[0, 1], got {value!r}"
                )

    for key in ("training_dataset_id", "training_dataset_sha256", "license"):
        if key in meta and not isinstance(meta[key], str):
            problems.append(
                f"{key} must be a string, got {type(meta[key]).__name__}"
            )

    if "metrics" in meta and not isinstance(meta["metrics"], dict):
        problems.append(
            f"metrics must be a JSON object, got {type(meta['metrics']).__name__}"
        )

    return problems


def make_manifest(
    model_id: str,
    task: str,
    model_sha256: str,
    created_utc: str,
    training_framework: str,
    input_semantics: str,
    input_unit: str,
    output_semantics: str,
    output_unit: str,
    *,
    inference_format: str = "onnx",
    alignment: Optional[str] = None,
    normalization: Optional[Dict] = None,
    tile_size: Optional[Sequence[int]] = None,
    tile_overlap: Optional[Sequence[int]] = None,
    pixel_size_range_nm: Optional[Dict] = None,
    segmentation_threshold: Optional[float] = None,
    training_dataset_id: Optional[str] = None,
    training_dataset_sha256: Optional[str] = None,
    metrics: Optional[Dict] = None,
    license: Optional[str] = None,
) -> Dict:
    """
    Build a conforming manifest dictionary for a model file.
    モデルファイル用の契約準拠 manifest 辞書を組み立てる。

    Parameters
    ----------
    model_id
        Author-chosen identifier for this trained model (not a path).
        作成者が付けるこの学習済みモデルの識別子（パスではない）。
    task
        One of `MODEL_TASKS`; the pipeline decision this model replaces.
        `MODEL_TASKS` のいずれか。このモデルが置き換えるパイプライン上の
        判断。
    model_sha256
        SHA-256 hex digest of `ONNX_MEMBER`'s bytes, computed by the caller
        (this module never opens the archive; see `validate_manifest`).
        `ONNX_MEMBER` のバイト列の SHA-256 16進ダイジェスト。呼び出し側が
        計算する（本モジュールはアーカイブを開かない。`validate_manifest`
        参照）。
    created_utc
        ISO-8601 UTC timestamp; the caller supplies it so a training run and
        its model file can share one timestamp.
        ISO-8601 UTC のタイムスタンプ。学習実行とモデルファイルで同一の値を
        共有できるよう呼び出し側が与える。
    training_framework
        One of `TRAINING_FRAMEWORKS`; provenance only, see module docstring.
        `TRAINING_FRAMEWORKS` のいずれか。来歴情報のみ、モジュール
        docstring参照。
    input_semantics, output_semantics
        Free-form labels describing what the tensors mean, e.g.
        ``"raw_height"``, ``"background_surface"``, ``"fiber_probability"``.
        テンソルの意味を表す自由記述のラベル。例：``"raw_height"``、
        ``"background_surface"``、``"fiber_probability"``。
    input_unit, output_unit
        Physical unit of the tensors, e.g. ``"nm"``.
        テンソルの物理単位。例：``"nm"``。
    inference_format
        One of `INFERENCE_FORMATS`.
        `INFERENCE_FORMATS` のいずれか。
    alignment
        Spatial alignment convention relative to the raw input, e.g.
        ``"crop_top_and_left_by_one"`` for the pipeline's known one-pixel
        trim (see `lib.bundle_schema` module docstring).
        生入力に対する空間位置合わせの規約。既知の 1 画素トリミング
        （`lib.bundle_schema` モジュール docstring参照）には
        ``"crop_top_and_left_by_one"`` を使う。
    normalization
        Input normalization scheme and parameters, applied identically at
        training and inference time.
        入力正規化の方式とパラメータ。学習時・推論時で同一に適用する。
    tile_size, tile_overlap
        ``[height, width]`` in pixels, for models that run on tiles rather
        than the whole image at once.
        画像全体でなくタイル単位で推論するモデル用の ``[height, width]``
        （px）。
    pixel_size_range_nm
        Applicable per-axis pixel-size range, for detecting out-of-range
        inputs before inference.
        推論前に対応範囲外の入力を検出するための、軸ごとの適用可能画素
        サイズ範囲。
    segmentation_threshold
        Probability threshold applied to a ``"binarize"`` model's output;
        meaningless for other tasks and simply omitted for them.
        ``"binarize"`` モデルの出力に適用する確率しきい値。他のタスクには
        無意味なので単に省略する。
    training_dataset_id, training_dataset_sha256
        Provenance of the training data, matching how `lib.pipeline` records
        `input_sha256` for a processed file.
        学習データの来歴。`lib.pipeline` が処理済みファイルの
        `input_sha256` を記録するのと同じ考え方。
    metrics
        Cross-validation / held-out evaluation results, shown when a model
        is picked.
        交差検証・独立評価の結果。モデル選択時に表示する。
    license
        License under which this model file is distributed.
        このモデルファイルの配布ライセンス。

    Returns
    -------
    dict
        JSON-serializable manifest to store as `MANIFEST_MEMBER`.
        `MANIFEST_MEMBER` として保存する JSON 直列化可能な manifest。

    Raises
    ------
    ValueError
        If the resulting manifest would violate the contract; the message
        lists every problem, matching `lib.pipeline.process_file`.
        生成される manifest が契約に違反する場合。`lib.pipeline.process_file`
        と同様、メッセージに全問題を列挙する。
    """
    meta: Dict = {
        "model_format_version": MODEL_FORMAT_VERSION,
        "model_id": model_id,
        "task": task,
        "model_sha256": model_sha256,
        "created_utc": created_utc,
        "training_framework": training_framework,
        "inference_format": inference_format,
        "input_semantics": input_semantics,
        "input_unit": input_unit,
        "output_semantics": output_semantics,
        "output_unit": output_unit,
    }
    # Optional keys are omitted rather than stored as null, so a reader can
    # use plain key presence to mean "recorded for this model" (see module
    # docstring on the flat-schema decision).
    # 任意キーは null ではなく省略し、読み取り側がキーの有無だけで
    # 「このモデルで記録されている」を判定できるようにする
    # （モジュール docstring のフラットスキーマの決定を参照）。
    for key, value in (
        ("alignment", alignment),
        ("normalization", normalization),
        ("tile_size", list(tile_size) if tile_size is not None else None),
        ("tile_overlap", list(tile_overlap) if tile_overlap is not None else None),
        ("pixel_size_range_nm", pixel_size_range_nm),
        ("segmentation_threshold", segmentation_threshold),
        ("training_dataset_id", training_dataset_id),
        ("training_dataset_sha256", training_dataset_sha256),
        ("metrics", metrics),
        ("license", license),
    ):
        if value is not None:
            meta[key] = value

    problems = validate_manifest(meta)
    if problems:
        raise ValueError(
            "model manifest contract violation: " + "; ".join(problems)
        )
    return meta
