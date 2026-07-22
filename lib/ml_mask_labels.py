# -*- coding: utf-8 -*-
"""
Executable schema for the manual mask-correction sidecar (processes A and B).
手動マスク修正 sidecar の実行可能スキーマ（工程A・B）。

The pixel models for ``binarize`` and ``bg_mask`` are trained by distillation:
their labels are the masks the classical pipeline already computes (see
`lib.ml_dataset`). A model taught only from those can at best imitate the
pipeline; it cannot beat it. Human corrections are what lift that ceiling, and
this module is the single in-code definition of where they are stored: a
sidecar file beside the bundle they describe, leaving the ``.b2z`` itself
untouched -- the same arrangement the pipeline uses for ``<stem>_param.json``
and the connection labels use for ``<stem>_connect_labels.json``.
``binarize`` と ``bg_mask`` の画素モデルは蒸留で学習する。ラベルは古典パイプラインが
既に計算したマスクである（`lib.ml_dataset` 参照）。それだけで学習したモデルは、
よくてパイプラインの模倣に留まり、それを上回ることはできない。この上限を外すのが
人による修正であり、本モジュールはその保存場所のコード上の唯一の定義である。対象
バンドルの隣に sidecar を置き、``.b2z`` 自体は変更しない。パイプラインが
``<stem>_param.json`` を、連結ラベルが ``<stem>_connect_labels.json`` を置くのと
同じ方式である。

An edit layer, not a corrected mask / 修正後マスクではなく編集レイヤ
--------------------------------------------------------------------
The stored array is three-valued (`EDIT_NONE`, `EDIT_FIBER`, `EDIT_BACKGROUND`)
and records only what a person changed, not the finished mask. Storing the
finished mask instead would erase the difference between a pixel a human looked
at and judged, and a pixel the algorithm happened to get right that nobody ever
examined. That difference is what makes the corrections usable: it lets the
dataset builder guarantee the corrected pixels survive subsampling, lets a
reviewer audit how much was actually changed, and lets the base label be
recomputed when analysis parameters change without discarding the human work.
This is the pixel-level form of the "no implicit positives" rule that
`lib.ml_connect_labels` applies to candidate pairs.
保存する配列は 3 値（`EDIT_NONE`・`EDIT_FIBER`・`EDIT_BACKGROUND`）で、完成した
マスクではなく人が変更した箇所だけを記録する。完成マスクを保存すると、人が見て
判断した画素と、たまたまアルゴリズムが正解していて誰も見ていない画素との区別が
消える。この区別こそが修正を使えるものにしている。データセット構築側が修正画素を
サブサンプリングで失わないよう保証でき、どれだけ実際に修正したかを監査でき、解析
パラメータが変わってもベースラベルだけを再計算して人手の作業を捨てずに済む。
`lib.ml_connect_labels` が候補ペアに適用する「暗黙の正例を置かない」規則の、画素版
である。

Bound to the image, not to the input file / 束縛は入力ファイルでなく画像
------------------------------------------------------------------------
A correction is meaningful only for the exact image it was drawn on, so the
sidecar records `image_sha256` of that image -- ``calibrated`` for ``binarize``,
the aligned raw height for ``bg_mask``. The bundle's ``input_sha256`` is not
enough: two bundles produced from one input with different analysis parameters
share it while their images differ, so matching on it would silently apply the
corrections to the wrong pixels. Nothing would raise; the labels would just be
wrong.
修正は、それを描いた当の画像に対してのみ意味を持つ。そこで sidecar はその画像の
`image_sha256` を記録する（``binarize`` なら ``calibrated``、``bg_mask`` なら整列済み
の生の高さ）。バンドルの ``input_sha256`` では不十分である。同一入力からパラメータ
違いで作られた 2 つのバンドルはそれを共有するが画像は異なり、それで照合すると修正が
黙って誤った画素へ適用される。例外は出ず、ラベルが誤るだけである。

The base label source is recorded / ベースのラベル出所を記録する
-----------------------------------------------------------------
An edit layer says "make this pixel fiber", which only has a defined meaning
relative to the mask it was drawn over. For ``binarize`` that base must be the
Segmenter's pre-component-filter intermediate mask, because that is the decision
the model replaces; corrections drawn over the bundle's final ``binarized`` mask
would reintroduce the double-application problem `lib.ml_dataset` documents.
Recording `base_label_source` lets a mismatch be refused instead of silently
training on a label nobody intended.
編集レイヤは「この画素を繊維にする」と述べるが、その意味はどのマスクの上に描いたかに
対してのみ定まる。``binarize`` ではそのベースは Segmenter の成分フィルタ前の中間
マスクでなければならない。それがモデルの置き換える判断だからである。バンドルの最終
``binarized`` マスクの上に描いた修正は、`lib.ml_dataset` が記す二重適用の問題を再び
持ち込む。`base_label_source` を記録することで、不一致を黙って学習させずに拒否できる。

Derived values are computed, never stored / 導出値は保存せず計算する
---------------------------------------------------------------------
Edit counts are not written into the metadata. A stored count can drift from the
array it summarizes, and a stale count that looks authoritative is worse than no
count at all; `edit_counts` derives them from the array on demand. This follows
`lib.ml_connect_labels.review_complete`, which likewise recomputes rather than
trusting a recorded flag.
編集画素数はメタデータへ書かない。保存した集計値は要約対象の配列とずれうるし、
権威ありげに見える古い集計値は集計が無いことより悪い。`edit_counts` が必要時に配列
から導出する。記録されたフラグを信用せず再計算する
`lib.ml_connect_labels.review_complete` と同じ考え方である。

This module depends only on NumPy and `lib.blosc2_io`, so an annotation GUI can
read, write, and validate corrections without pulling in the machine-learning
stack.
本モジュールの依存は NumPy と `lib.blosc2_io` のみ。アノテーション GUI が機械学習
スタックを読み込まずに修正の読み書きと検証を行える。
"""

# ===== Standard library =====
import hashlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .blosc2_io import bundle_has_keys, load_bundle, load_bundle_meta, save_bundle

# Version of the sidecar layout. Bump only when keys, vocabularies, or the
# meaning of a value change.
# sidecar 形式のバージョン。キー・語彙・値の意味が変わるときのみ繰り上げる。
MASK_LABEL_SCHEMA_VERSION = "1.0"

# Versions this code base can read. Unknown versions are rejected loudly so a
# future format change cannot be silently misread by an older release.
# 本コードベースが読める形式バージョン。未知のバージョンは明示的に拒否し、将来の
# 形式変更を旧リリースが黙って誤読しないようにする。
SUPPORTED_MASK_LABEL_VERSIONS = ("1.0",)

# Suffix appended to a bundle stem to form the sidecar name, mirroring the
# pipeline's existing "<stem>_param.json" and "<stem>_connect_labels.json".
# sidecar 名を作るためにバンドル stem へ付ける接尾辞。パイプライン既存の
# "<stem>_param.json"、"<stem>_connect_labels.json" に倣う。
MASK_LABEL_SUFFIX = "_mask_labels.b2z"

# Tasks whose label is a per-pixel mask a person can correct by painting.
# `background_surface` is excluded on purpose: its target is a continuous height
# in nanometers, which a two-state brush cannot express.
# ラベルが画素単位のマスクであり、人がペイントで修正できるタスク。
# `background_surface` は意図的に除く。ターゲットが nm 単位の連続値であり、
# 2 状態のブラシでは表現できないためである。
MASK_LABEL_TASKS = ("binarize", "bg_mask")

# Array key holding the edit layer inside the sidecar bundle.
# sidecar バンドル内で編集レイヤを保持する配列キー。
EDITS_KEY = "edits"

# Edit-layer values. Fixed integer identifiers, not user-visible text.
# `EDIT_NONE` means "no human judgement here", which is distinct from -- and
# must never be collapsed into -- either class (see the module docstring).
# 編集レイヤの値。固定の整数識別子でユーザー表示文字列ではない。
# `EDIT_NONE` は「ここに人の判断は無い」を意味し、どちらのクラスとも異なる。
# 両者を同一視してはならない（モジュール docstring 参照）。
EDIT_NONE = 0
EDIT_FIBER = 1
EDIT_BACKGROUND = 2
EDIT_VALUES = (EDIT_NONE, EDIT_FIBER, EDIT_BACKGROUND)

# Masks a correction can be drawn over. These are the identifiers
# `lib.ml_dataset` uses for its label sources, defined here so the two modules
# share one literal rather than two that can drift apart; `lib.ml_dataset`
# imports them.
# 修正を描く対象となりうるマスク。`lib.ml_dataset` がラベル出所に使う識別子であり、
# 2 つのリテラルがずれることのないよう、ここで定義して共有する。
# `lib.ml_dataset` はこれを import する。
BASE_SEGMENTER_INTERMEDIATE = "segmenter_intermediate"  # Pre-component-filter mask (binarize).
BASE_BUNDLE_BINARIZED = "bundle_binarized"              # Final stored mask (binarize).
BASE_BG_CALIBRATOR_MASK = "bg_calibrator_mask"          # Gradient-ridge fiber candidates (bg_mask).
BASE_SOURCES = (
    BASE_SEGMENTER_INTERMEDIATE, BASE_BUNDLE_BINARIZED, BASE_BG_CALIBRATOR_MASK)

# The base each task's corrections are normally drawn over. For `binarize` this
# is the intermediate mask rather than the stored final one, because that is the
# decision the model replaces (see the module docstring).
# 各タスクの修正が通常描かれるベース。`binarize` では保存済みの最終マスクではなく
# 中間マスクである。それがモデルの置き換える判断だからである
# （モジュール docstring 参照）。
DEFAULT_BASE_SOURCE = {
    "binarize": BASE_SEGMENTER_INTERMEDIATE,
    "bg_mask": BASE_BG_CALIBRATOR_MASK,
}


@dataclass
class MaskLabels:
    """
    A loaded mask-correction sidecar: the edit layer and its metadata.
    読み込んだマスク修正 sidecar：編集レイヤとそのメタデータ。

    Attributes
    ----------
    edits
        2D ``uint8`` edit layer holding `EDIT_VALUES`, in the coordinate frame
        of the image the corrections were drawn on.
        `EDIT_VALUES` を保持する 2 次元 ``uint8`` の編集レイヤ。修正を描いた画像の
        座標系で表される。
    meta
        Sidecar metadata as stored, including `task`, `base_label_source`, and
        `image_sha256`.
        保存されているままの sidecar メタデータ。`task`、`base_label_source`、
        `image_sha256` を含む。
    """

    edits: np.ndarray
    meta: Dict = field(default_factory=dict)

    @property
    def task(self) -> str:
        """
        Return the task these corrections were made for.
        これらの修正が対象とするタスクを返す。
        """
        return str(self.meta.get("task", ""))

    @property
    def base_label_source(self) -> str:
        """
        Return the mask the corrections were drawn over.
        修正を描いた対象のマスクを返す。
        """
        return str(self.meta.get("base_label_source", ""))

    @property
    def n_edited(self) -> int:
        """
        Return how many pixels carry a human judgement.
        人の判断を持つ画素数を返す。
        """
        return int(np.count_nonzero(np.asarray(self.edits) != EDIT_NONE))


def label_path_for(bundle_path: str) -> str:
    """
    Return the mask-label sidecar path for a bundle path.
    バンドルパスに対応するマスクラベル sidecar のパスを返す。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle the corrections describe.
        修正が記述する ``.b2z`` バンドルのパス。

    Returns
    -------
    str
        Sibling path ``<bundle stem>_mask_labels.b2z``.
        同一ディレクトリの ``<バンドル stem>_mask_labels.b2z``。
    """
    return os.path.splitext(bundle_path)[0] + MASK_LABEL_SUFFIX


def has_mask_labels(bundle_path: str) -> bool:
    """
    Report whether a mask-label sidecar exists beside a bundle.
    バンドルの隣にマスクラベル sidecar が存在するかを返す。

    Existence only; the file is not opened or validated here, so a folder scan
    stays cheap.
    存在確認のみ。ここではファイルを開かず検証もしないため、フォルダ走査を軽く
    保てる。
    """
    return os.path.isfile(label_path_for(bundle_path))


def image_sha256(image: np.ndarray) -> str:
    """
    Return a stable hash identifying the image a correction was drawn on.
    修正を描いた画像を一意に識別する安定なハッシュを返す。

    Parameters
    ----------
    image
        The 2D image the corrections are about: ``calibrated`` for
        ``binarize``, the aligned raw height for ``bg_mask``.
        修正の対象となる 2 次元画像。``binarize`` では ``calibrated``、
        ``bg_mask`` では整列済みの生の高さ。

    Returns
    -------
    str
        Hex digest over the shape and the ``float64`` pixel values.
        形状と ``float64`` 画素値に対する 16 進ダイジェスト。

    Notes
    -----
    Values are normalized to C-contiguous ``float64`` before hashing so a
    sliced view (the aligned raw height is one) and a freshly loaded copy of
    the same data agree. The shape is mixed in so two different images cannot
    collide through their flattened bytes alone. This mirrors
    `lib.ml_connect_labels.skeleton_sha256`, which binds connection labels to
    their skeleton for the same reason.
    ハッシュ前に値を C 連続の ``float64`` へ正規化するため、スライスしたビュー
    （整列済みの生の高さがそれにあたる）と同じデータを読み直した複製が一致する。
    形状も混ぜることで、平坦化したバイト列だけで別画像が衝突することを防ぐ。
    連結ラベルを骨格へ束縛する `lib.ml_connect_labels.skeleton_sha256` と同じ
    考え方である。
    """
    values = np.ascontiguousarray(np.asarray(image, dtype=np.float64))
    digest = hashlib.sha256()
    digest.update(f"{values.shape[0]}x{values.shape[1]}:".encode("ascii"))
    digest.update(values.tobytes())
    return digest.hexdigest()


def new_edit_layer(shape: Tuple[int, int]) -> np.ndarray:
    """
    Return an empty edit layer of the given shape.
    指定形状の空の編集レイヤを返す。

    Parameters
    ----------
    shape
        ``(height, width)`` of the image the corrections will be drawn on.
        修正を描く対象画像の ``(高さ, 幅)``。

    Returns
    -------
    numpy.ndarray
        ``uint8`` array filled with `EDIT_NONE`.
        `EDIT_NONE` で埋めた ``uint8`` 配列。
    """
    return np.full(shape, EDIT_NONE, dtype=np.uint8)


def apply_edits(base_label: np.ndarray, edits: np.ndarray) -> np.ndarray:
    """
    Overlay an edit layer on a base label mask.
    ベースのラベルマスクへ編集レイヤを重ねる。

    Parameters
    ----------
    base_label
        The mask the corrections were drawn over, as 0/1 values.
        修正を描いた対象のマスク。0/1 の値。
    edits
        Edit layer holding `EDIT_VALUES`, same shape as `base_label`.
        `EDIT_VALUES` を保持する編集レイヤ。`base_label` と同形状。

    Returns
    -------
    numpy.ndarray
        ``int64`` label mask with the human judgements applied; pixels marked
        `EDIT_NONE` keep their base value.
        人の判断を適用した ``int64`` のラベルマスク。`EDIT_NONE` の画素は
        ベースの値を保つ。

    Raises
    ------
    ValueError
        If the shapes differ. The two arrays index the same image, so a shape
        difference means they describe different images and the overlay would
        be meaningless.
        形状が異なる場合。両配列は同一画像を指すため、形状の違いは別の画像を
        記述していることを意味し、重ね合わせは無意味になる。
    """
    base = (np.asarray(base_label) != 0).astype(np.int64)
    layer = np.asarray(edits)
    if base.shape != layer.shape:
        raise ValueError(
            f"edit layer shape {layer.shape} != base label shape {base.shape}")
    label = base.copy()
    label[layer == EDIT_FIBER] = 1
    label[layer == EDIT_BACKGROUND] = 0
    return label


def edited_indices(edits: np.ndarray) -> np.ndarray:
    """
    Return the flat indices of pixels carrying a human judgement.
    人の判断を持つ画素の平坦添字を返す。

    The dataset builder uses these to keep corrected pixels through per-image
    subsampling. Corrections are a few hundred pixels against a few hundred
    thousand, so a plain random draw would discard nearly all of them and the
    correction would have no effect on training -- a failure that produces no
    error and is hard to notice.
    データセット構築側は、画像ごとのサブサンプリングを通して修正画素を残すために
    これを使う。修正は数十万画素に対して数百画素であり、素の無作為抽出ではその
    ほとんどが捨てられ、修正が学習に影響しない。これは何のエラーも出さず、気付き
    にくい失敗である。

    Parameters
    ----------
    edits
        Edit layer holding `EDIT_VALUES`.
        `EDIT_VALUES` を保持する編集レイヤ。

    Returns
    -------
    numpy.ndarray
        ``int64`` flat indices into the raveled image.
        平坦化した画像に対する ``int64`` の添字。
    """
    return np.flatnonzero(np.asarray(edits).reshape(-1) != EDIT_NONE)


def edit_counts(edits: np.ndarray) -> Dict[str, int]:
    """
    Count the pixels forced to each class.
    各クラスへ強制された画素数を数える。

    Parameters
    ----------
    edits
        Edit layer holding `EDIT_VALUES`.
        `EDIT_VALUES` を保持する編集レイヤ。

    Returns
    -------
    dict
        ``{"fiber": int, "background": int, "total": int}``; fixed English
        keys, not user-visible text.
        ``{"fiber": int, "background": int, "total": int}``。固定英語のキーで
        ユーザー表示文字列ではない。
    """
    layer = np.asarray(edits)
    n_fiber = int(np.count_nonzero(layer == EDIT_FIBER))
    n_background = int(np.count_nonzero(layer == EDIT_BACKGROUND))
    return {
        "fiber": n_fiber,
        "background": n_background,
        "total": n_fiber + n_background,
    }


def make_mask_meta(
    bundle_path: str,
    task: str,
    base_label_source: str,
    image_hash: str,
    *,
    created_utc: str,
    input_sha256: Optional[str] = None,
    reviewer: Optional[str] = None,
) -> Dict:
    """
    Build the sidecar metadata dictionary.
    sidecar のメタデータ辞書を組み立てる。

    Parameters
    ----------
    bundle_path
        Path to the bundle these corrections describe; only its base name is
        stored.
        修正が記述するバンドルのパス。保存するのはその basename のみ。
    task
        One of `MASK_LABEL_TASKS`.
        `MASK_LABEL_TASKS` のいずれか。
    base_label_source
        One of `BASE_SOURCES`; the mask the corrections were drawn over.
        `BASE_SOURCES` のいずれか。修正を描いた対象のマスク。
    image_hash
        `image_sha256` of the image the corrections were drawn on.
        修正を描いた画像の `image_sha256`。
    created_utc
        ISO-8601 UTC timestamp supplied by the caller.
        呼び出し側が与える ISO-8601 UTC のタイムスタンプ。
    input_sha256
        The bundle's recorded input hash, kept for provenance only; the image
        hash is what binds the file (see the module docstring).
        バンドルに記録された入力ハッシュ。来歴のためだけに保持する。ファイルを
        結び付けるのは画像ハッシュである（モジュール docstring 参照）。
    reviewer
        Free-form reviewer identifier, or ``None``. Do not record personal
        information here.
        自由記述の検分者識別子、または ``None``。個人情報は記録しない。

    Returns
    -------
    dict
        Metadata to store as the sidecar's vlmeta.
        sidecar の vlmeta として保存するメタデータ。
    """
    meta: Dict = {
        "schema_version": MASK_LABEL_SCHEMA_VERSION,
        "task": task,
        "base_label_source": base_label_source,
        "image_sha256": image_hash,
        "bundle_file": os.path.basename(bundle_path),
        "created_utc": created_utc,
    }
    if input_sha256 is not None:
        meta["input_sha256"] = input_sha256
    if reviewer is not None:
        meta["reviewer"] = reviewer
    return meta


def validate_mask_labels(
    edits: Optional[np.ndarray],
    meta: Dict,
    *,
    expected_image_sha256: Optional[str] = None,
    expected_task: Optional[str] = None,
    expected_base_source: Optional[str] = None,
    expected_shape: Optional[Tuple[int, int]] = None,
) -> List[str]:
    """
    Check a mask-correction sidecar against the contract.
    マスク修正 sidecar を契約と照合する。

    Parameters
    ----------
    edits
        Edit layer read from the sidecar, or ``None`` when it is absent.
        sidecar から読んだ編集レイヤ。存在しない場合は ``None``。
    meta
        Sidecar metadata.
        sidecar のメタデータ。
    expected_image_sha256
        When given, the recorded image hash must equal it. Supply the hash of
        the image the corrections are about to be applied to, so corrections
        belonging to a different image are rejected instead of silently
        misapplied.
        指定時、記録された画像ハッシュはこれと一致しなければならない。修正を適用
        しようとしている画像のハッシュを渡すことで、別の画像に属する修正が黙って
        誤適用されるのを防ぎ、拒否できる。
    expected_task
        When given, the recorded task must equal it.
        指定時、記録されたタスクはこれと一致しなければならない。
    expected_base_source
        When given, the recorded base must equal it. A correction drawn over a
        different mask does not mean what the caller assumes it means (see the
        module docstring).
        指定時、記録されたベースはこれと一致しなければならない。別のマスクの上に
        描かれた修正は、呼び出し側が想定する意味を持たない
        （モジュール docstring 参照）。
    expected_shape
        When given, the edit layer must have this shape.
        指定時、編集レイヤはこの形状でなければならない。

    Returns
    -------
    list of str
        Fixed English problem descriptions; empty when the sidecar conforms.
        Callers translate or wrap as needed, matching `validate_bundle` and
        `lib.ml_connect_labels.validate_labels`.
        固定英語の問題記述リスト。適合していれば空。`validate_bundle` や
        `lib.ml_connect_labels.validate_labels` と同様、翻訳や文脈付けは呼び出し
        側で行う。
    """
    problems: List[str] = []

    if not isinstance(meta, dict):
        return [f"metadata must be a mapping, got {type(meta).__name__}"]

    version = meta.get("schema_version")
    if version is None:
        problems.append("missing 'schema_version'")
    elif version not in SUPPORTED_MASK_LABEL_VERSIONS:
        problems.append(
            f"unsupported mask label schema version {version!r} "
            f"(supported: {', '.join(SUPPORTED_MASK_LABEL_VERSIONS)})")

    task = meta.get("task")
    if task not in MASK_LABEL_TASKS:
        problems.append(
            f"task must be one of {MASK_LABEL_TASKS}, got {task!r}")
    elif expected_task is not None and task != expected_task:
        problems.append(
            f"corrections were made for task {task!r} but are being used for "
            f"{expected_task!r}")

    base = meta.get("base_label_source")
    if base not in BASE_SOURCES:
        problems.append(
            f"base_label_source must be one of {BASE_SOURCES}, got {base!r}")
    elif expected_base_source is not None and base != expected_base_source:
        problems.append(
            f"corrections were drawn over {base!r} but are being applied to "
            f"{expected_base_source!r}; they do not describe the same mask")

    stored_hash = meta.get("image_sha256")
    if not stored_hash:
        problems.append("missing 'image_sha256'")
    elif expected_image_sha256 is not None and stored_hash != expected_image_sha256:
        problems.append(
            f"image hash mismatch: corrections were made for "
            f"{str(stored_hash)[:12]}... but the target image is "
            f"{expected_image_sha256[:12]}...; these corrections describe a "
            f"different image")

    if not meta.get("created_utc"):
        problems.append("missing 'created_utc'")

    problems.extend(_edit_layer_problems(edits, expected_shape))
    return problems


def _edit_layer_problems(
    edits: Optional[np.ndarray],
    expected_shape: Optional[Tuple[int, int]],
) -> List[str]:
    """
    Check the edit layer's presence, shape, and values.
    編集レイヤの存在・形状・値を検査する。
    """
    if edits is None:
        return [f"missing '{EDITS_KEY}' array"]

    layer = np.asarray(edits)
    problems: List[str] = []

    if layer.ndim != 2:
        problems.append(
            f"'{EDITS_KEY}' must be 2D, got {layer.ndim}D shape {layer.shape}")
        return problems

    if expected_shape is not None and layer.shape != tuple(expected_shape):
        problems.append(
            f"'{EDITS_KEY}' shape {layer.shape} != target image shape "
            f"{tuple(expected_shape)}")

    if not np.issubdtype(layer.dtype, np.integer):
        problems.append(
            f"'{EDITS_KEY}' must hold integers, got dtype {layer.dtype}")
        return problems

    unknown = np.setdiff1d(np.unique(layer), np.asarray(EDIT_VALUES))
    if unknown.size:
        problems.append(
            f"'{EDITS_KEY}' holds values outside {EDIT_VALUES}: "
            + ", ".join(str(int(v)) for v in unknown[:5]))

    return problems


def save_mask_labels(path: str, edits: np.ndarray, meta: Dict) -> str:
    """
    Write a mask-correction sidecar.
    マスク修正 sidecar を書き込む。

    Parameters
    ----------
    path
        Destination path, normally from `label_path_for`.
        保存先パス。通常は `label_path_for` の戻り値。
    edits
        Edit layer holding `EDIT_VALUES`.
        `EDIT_VALUES` を保持する編集レイヤ。
    meta
        Metadata from `make_mask_meta`.
        `make_mask_meta` が返すメタデータ。

    Returns
    -------
    str
        The path written.
        書き込んだパス。

    Raises
    ------
    ValueError
        If the corrections violate the contract; the message lists every
        problem, matching `lib.pipeline.process_file`.
        修正が契約に違反する場合。`lib.pipeline.process_file` と同様、メッセージ
        に全問題を列挙する。

    Notes
    -----
    Stored as a small ``.b2z`` bundle rather than JSON because an edit layer is
    a dense per-pixel array; `lib.blosc2_io.save_bundle` also writes through a
    temporary sibling file, so an interrupted save cannot leave a half-written
    sidecar. A mostly-`EDIT_NONE` layer compresses to a few hundred bytes.
    編集レイヤは画素単位の密な配列であるため、JSON ではなく小さな ``.b2z`` バンドル
    として保存する。`lib.blosc2_io.save_bundle` は一時ファイル経由で書き込むため、
    保存の中断で半端な sidecar が残ることもない。ほとんどが `EDIT_NONE` のレイヤは
    数百バイトに圧縮される。
    """
    layer = np.ascontiguousarray(np.asarray(edits), dtype=np.uint8)
    problems = validate_mask_labels(layer, meta)
    if problems:
        raise ValueError(
            "mask label contract violation: " + "; ".join(problems))
    save_bundle(path, {EDITS_KEY: layer}, vlmeta=dict(meta))
    return path


def load_mask_labels(
    path: str,
    *,
    expected_image_sha256: Optional[str] = None,
    expected_task: Optional[str] = None,
    expected_base_source: Optional[str] = None,
    expected_shape: Optional[Tuple[int, int]] = None,
) -> MaskLabels:
    """
    Read and validate a mask-correction sidecar.
    マスク修正 sidecar を読み込み検証する。

    Parameters
    ----------
    path
        Path to the sidecar.
        sidecar のパス。
    expected_image_sha256, expected_task, expected_base_source, expected_shape
        Optional checks forwarded to `validate_mask_labels`; pass them all when
        the corrections are about to be applied to a specific image.
        `validate_mask_labels` へ渡す任意の検査。特定の画像へ適用する直前には
        すべて渡すこと。

    Returns
    -------
    MaskLabels
        The validated edit layer and its metadata.
        検証済みの編集レイヤとそのメタデータ。

    Raises
    ------
    ValueError
        If the file cannot be read or violates the contract. Failure is
        explicit rather than partial: silently ignoring a mismatched sidecar
        would train on the distilled label while the user believes their
        corrections are in use.
        ファイルが読めない、または契約に違反する場合。部分的に無視せず明示的に
        失敗する。不一致の sidecar を黙って無視すると、利用者は修正が効いている
        と思い込んだまま、蒸留ラベルだけで学習してしまうためである。
    """
    try:
        arrays = load_bundle(path, keys=[EDITS_KEY])
        meta = load_bundle_meta(path)
    except Exception as exc:  # noqa: BLE001 - any read failure is a contract failure here.
        raise ValueError(
            f"{os.path.basename(path)}: cannot read mask labels: {exc}") from exc

    edits = arrays.get(EDITS_KEY)
    problems = validate_mask_labels(
        edits, meta,
        expected_image_sha256=expected_image_sha256,
        expected_task=expected_task,
        expected_base_source=expected_base_source,
        expected_shape=expected_shape,
    )
    if problems:
        raise ValueError(
            f"{os.path.basename(path)}: invalid mask labels: "
            + "; ".join(problems))
    return MaskLabels(edits=np.asarray(edits), meta=dict(meta))


def inspect_mask_labels(bundle_path: str) -> Tuple[bool, str]:
    """
    Report whether a bundle's sidecar is readable, without binding checks.
    バンドルの sidecar が読めるかを、束縛検査なしで報告する。

    Used by folder scans to tell "no corrections yet" apart from "corrections
    exist but are broken", before the target image is loaded and its hash is
    known.
    フォルダ走査で「まだ修正が無い」と「修正はあるが壊れている」を区別するために
    使う。対象画像を読み込んでハッシュが判明する前の段階で使える。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle.
        ``.b2z`` バンドルのパス。

    Returns
    -------
    tuple
        ``(ok, reason)``; `reason` is empty when `ok`, otherwise a fixed
        English explanation.
        ``(ok, reason)``。`ok` のとき `reason` は空、そうでなければ固定英語の説明。
    """
    path = label_path_for(bundle_path)
    if not os.path.isfile(path):
        return False, (
            f"no mask corrections: {os.path.basename(path)} not found beside "
            f"the bundle")
    ok, _missing = bundle_has_keys(path, [EDITS_KEY])
    if not ok:
        return False, (
            f"{os.path.basename(path)} has no {EDITS_KEY!r} array")
    try:
        labels = load_mask_labels(path)
    except ValueError as exc:
        return False, str(exc)
    if labels.n_edited == 0:
        return False, (
            f"{os.path.basename(path)} records no edited pixels")
    return True, ""
