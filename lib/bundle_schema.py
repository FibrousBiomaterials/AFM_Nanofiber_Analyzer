# -*- coding: utf-8 -*-
"""
Executable schema for the ``.b2z`` bundle contract.
``.b2z`` バンドル契約の実行可能スキーマ。

This module is the single in-code definition of the bundle contract that was
previously documented only in prose (README, the Japanese specification, and
AGENTS.md §8.2): required keys, array shapes, value ranges, units, and the
coordinate convention. `validate_bundle` turns contract violations into clear
English messages instead of letting malformed bundles fail deep inside the
tracking code with cryptic NumPy errors.
本モジュールは、これまで散文（README、日本語仕様書、AGENTS.md §8.2）でのみ
記述されていたバンドル契約（必須キー、配列形状、値域、単位、座標規約）の
コード上の唯一の定義である。`validate_bundle` は契約違反を明確な英語
メッセージへ変換し、壊れたバンドルが追跡コードの奥で不可解な NumPy エラーに
なるのを防ぐ。

Contract summary / 契約の要約
-----------------------------
- ``calibrated``, ``binarized``, ``skeletonized``, ``bp``, ``ep``: 2D arrays
  sharing one image shape. ``binarized``/``skeletonized``/``bp``/``ep`` hold
  only values 0 and 1.
  画像系キーは同一形状の 2 次元配列。二値キーの値は 0 と 1 のみ。
- ``kp``, ``dp``: integer coordinate arrays of shape ``(2, N)`` where row 0 is
  the x (column) index and row 1 is the y (row) index.
  ``kp``/``dp`` は形状 ``(2, N)`` の座標配列。行 0 が x（列）、行 1 が y（行）。
- ``ka``: shape ``(N,)`` kink interior angles in **radians**, strictly inside
  ``(0, pi)``; ``N`` equals ``kp.shape[1]``. Degrees appear only in user-facing
  output (see `lib.measure.FiberStats.kink_angles_deg`).
  ``ka`` は形状 ``(N,)`` のキンク内角（**ラジアン**、開区間 ``(0, pi)``）で、
  ``N`` は ``kp.shape[1]`` と一致する。度数値はユーザー向け出力のみで使う。
- ``original`` (optional): the raw height image **before** the one-pixel trim
  applied by the background calibrator, so its shape intentionally differs
  from the other image keys.
  ``original``（任意キー）は背景補正器による 1 画素トリミング**前**の生画像で、
  形状が他の画像キーと異なるのは仕様である。

Known accepted limitation / 既知の許容済み制限
----------------------------------------------
The one-pixel trim is a legacy artifact of the gradient-based background
mask (a row/column difference shrinks the array by one), not a scientific
requirement. It shifts the coordinate frame of every processed key by one
pixel relative to ``original``, so raw and processed data cannot be compared
pixel-aligned. It is kept in format 1.0 because removing it changes the
shape contract of every existing bundle; restoring full-size output (e.g.
by padding the trimmed edge) is the leading candidate change for bundle
format 2.0.
1 画素トリミングは勾配ベースの背景マスク（行・列差分で配列が 1 つ縮む）に
由来する歴史的産物であり、科学的な必然ではない。処理済みキーの座標系が
``original`` に対して 1 画素ずれるため、生データと処理結果を画素単位で
整合比較できない。トリミングの廃止は既存全バンドルの形状契約を変えるため
形式 1.0 では維持し、フルサイズ出力への復元（トリム端のパディング等）を
バンドル形式 2.0 の変更候補の筆頭とする。

This module depends only on NumPy so GUI plugins and `lib.measure` can import
it without pulling in the heavy preprocessing stack.
本モジュールの依存は NumPy のみとし、GUI プラグインや `lib.measure` が重い
前処理スタックを読み込まずに import できるようにする。
"""

# ===== Standard library =====
from typing import Dict, List, Optional, Sequence

# ===== Numerical / scientific libraries =====
import numpy as np

# Version of the bundle layout itself, distinct from the application release
# recorded as "software_version". Bump only when keys, shapes, or units change.
# バンドル形式自体のバージョン。アプリのリリース ("software_version") とは
# 別物。キー・形状・単位が変わるときのみ繰り上げる。
BUNDLE_FORMAT_VERSION = "1.0"

# Versions this code base can read. Readers reject unknown versions loudly so
# a future format change cannot be silently misinterpreted by old releases.
# 本コードベースが読める形式バージョン。未知のバージョンは明示的に拒否し、
# 将来の形式変更を旧リリースが黙って誤解釈しないようにする。
SUPPORTED_BUNDLE_VERSIONS = ("1.0",)

# Bundle keys required to treat a file as analyzed.
# One .b2z bundle is written per analyzed file; all keys below must exist.
# 1 解析ファイルにつき 1 つの .b2z バンドルが生成され、下記キーが揃っていれば解析済みと判定する。
#   /calibrated   : Background-corrected image.
#   /binarized    : Binarized image.
#   /skeletonized : Skeletonized image.
#   /bp           : Branch-point mask.
#   /ep           : End-point mask.
#   /kp           : Kink coordinates, shape (2, N), [0]=x, [1]=y.
#   /dp           : Decomposed points used for kink detection, shape (2, N).
#   /ka           : Kink angles in radians, shape (N,).
REQUIRED_BUNDLE_KEYS = [
    "calibrated", "binarized", "skeletonized",
    "bp", "ep",
    "kp", "dp", "ka",
]

# Optional keys must not affect the analyzed/not-analyzed decision for backward compatibility.
# 後方互換のため、任意キーは解析済み判定に使わない。
OPTIONAL_BUNDLE_KEYS = ["original"]

# Keys needed to rebuild a FiberTrackingImage (GUI04 / lib.measure contract).
# Unlike REQUIRED_BUNDLE_KEYS, `binarized` is not needed for tracking.
# FiberTrackingImage の再構築に必要なキー（GUI04 / lib.measure 契約）。
# REQUIRED_BUNDLE_KEYS と異なり、追跡に `binarized` は不要。
TRACKING_BUNDLE_KEYS = [
    "calibrated", "skeletonized",
    "bp", "ep", "kp", "dp", "ka",
]

# Image-like keys that must share one shape. `original` is excluded because it
# is saved before the calibrator's one-pixel trim.
# 同一形状を共有すべき画像系キー。`original` は補正器のトリミング前に保存
# されるため除外する。
_IMAGE_KEYS = ("calibrated", "binarized", "skeletonized", "bp", "ep")

# Mask keys restricted to values 0 and 1 (bool or integer storage).
# 値が 0 と 1 に限定されるマスクキー（bool または整数で格納）。
_BINARY_KEYS = ("binarized", "skeletonized", "bp", "ep")

# Point-set keys stored as (2, N) coordinate arrays.
# (2, N) 座標配列として格納される点群キー。
_POINT_KEYS = ("kp", "dp")


def _is_finite_array(a: np.ndarray) -> bool:
    """
    Return whether all array values are finite numeric values.
    配列の全値が有限の数値かどうかを返す。
    """
    try:
        return bool(np.isfinite(a).all())
    except TypeError:
        return False


def validate_bundle(
    arrays: Dict[str, np.ndarray],
    meta: Optional[Dict] = None,
    require: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Check loaded bundle arrays against the ``.b2z`` contract.
    読み込んだバンドル配列を ``.b2z`` 契約と照合する。

    Only the keys present in `arrays` are inspected, so partial loads (for
    example GUI03 reading just ``calibrated`` and ``skeletonized``) can be
    validated without loading the whole bundle. Unknown keys are ignored so
    future additive format changes do not break old readers.
    検査対象は `arrays` に存在するキーのみ。GUI03 のように ``calibrated`` と
    ``skeletonized`` だけを読む部分読み込みでも、バンドル全体を読まずに検証
    できる。未知キーは無視し、将来のキー追加が旧リーダーを壊さないようにする。

    Parameters
    ----------
    arrays
        Mapping from bundle key to loaded array.
        バンドルキーから読み込み済み配列への辞書。
    meta
        Bundle vlmeta dictionary. When given, the recorded format version is
        checked against `SUPPORTED_BUNDLE_VERSIONS`. A missing ``version``
        entry is accepted because bundles from old releases lack it.
        バンドルの vlmeta 辞書。指定時は記録された形式バージョンを
        `SUPPORTED_BUNDLE_VERSIONS` と照合する。旧リリースのバンドルには
        ``version`` が無いため、欠落は許容する。
    require
        Keys that must be present in `arrays`; ``None`` skips the
        presence check (use for partial loads).
        `arrays` に存在しなければならないキー。``None`` なら存在チェックを
        省略する（部分読み込み用）。

    Returns
    -------
    list of str
        Fixed English problem descriptions; empty when the bundle conforms.
        Callers translate or wrap as needed, matching `validate_params`.
        固定英語の問題記述リスト。契約に適合していれば空。`validate_params`
        と同様、翻訳や文脈付けは呼び出し側で行う。
    """
    problems: List[str] = []

    if require is not None:
        missing = [k for k in require if k not in arrays]
        if missing:
            problems.append("missing required keys: " + ", ".join(missing))

    # Reject non-array values early so the shape checks below cannot crash.
    # 後続の形状チェックが落ちないよう、配列でない値を先に弾く。
    known = set(_IMAGE_KEYS) | set(_POINT_KEYS) | {"ka", "original"}
    bad_type = [
        k for k in arrays
        if k in known and not isinstance(arrays[k], np.ndarray)
    ]
    if bad_type:
        problems.append(
            "values must be NumPy arrays: " + ", ".join(sorted(bad_type))
        )
        return problems

    # --- Image keys: 2D and mutually consistent shape -----------------------
    image_shape = None
    image_shape_key = None
    for key in _IMAGE_KEYS:
        if key not in arrays:
            continue
        a = arrays[key]
        if a.ndim != 2:
            problems.append(f"{key}: expected a 2D image, got {a.ndim}D")
            continue
        if image_shape is None:
            image_shape, image_shape_key = a.shape, key
        elif a.shape != image_shape:
            problems.append(
                f"{key}: shape {a.shape} differs from "
                f"{image_shape_key} shape {image_shape}"
            )

    if "original" in arrays and arrays["original"].ndim != 2:
        problems.append(
            f"original: expected a 2D image, got {arrays['original'].ndim}D"
        )

    for key in ("calibrated", "original"):
        if key in arrays and not _is_finite_array(arrays[key]):
            problems.append(f"{key}: image values must be finite numbers")

    # --- Binary masks: values restricted to {0, 1} --------------------------
    for key in _BINARY_KEYS:
        if key not in arrays:
            continue
        a = arrays[key]
        if a.size > 0 and not np.isin(a, (0, 1)).all():
            problems.append(f"{key}: mask values must be only 0 or 1")

    # --- Point sets: (2, N) with x within width, y within height ------------
    for key in _POINT_KEYS:
        if key not in arrays:
            continue
        a = arrays[key]
        if a.ndim != 2 or a.shape[0] != 2:
            problems.append(f"{key}: expected shape (2, N), got {a.shape}")
            continue
        if a.size > 0 and not np.issubdtype(a.dtype, np.integer):
            problems.append(f"{key}: coordinate arrays must use an integer dtype")
            continue
        if a.size > 0 and not _is_finite_array(a):
            problems.append(f"{key}: coordinates must be finite numbers")
            continue
        if image_shape is not None and a.shape[1] > 0:
            # Row 0 is x (column index), row 1 is y (row index). The bound
            # check also catches swapped axes on non-square images.
            # 行 0 が x（列）、行 1 が y（行）。範囲チェックは非正方画像での
            # 軸の取り違えも検出する。
            h, w = image_shape
            if a[0].min() < 0 or a[0].max() >= w:
                problems.append(
                    f"{key}: x coordinates outside [0, {w}) for image width {w}"
                )
            if a[1].min() < 0 or a[1].max() >= h:
                problems.append(
                    f"{key}: y coordinates outside [0, {h}) for image height {h}"
                )

    # --- Kink angles: (N,) radians strictly inside (0, pi) ------------------
    if "ka" in arrays:
        ka = arrays["ka"]
        if ka.ndim != 1:
            problems.append(f"ka: expected shape (N,), got {ka.shape}")
        else:
            if not _is_finite_array(ka):
                problems.append("ka: kink angles must be finite numbers")
            if "kp" in arrays and arrays["kp"].ndim == 2 \
                    and arrays["kp"].shape[0] == 2 \
                    and ka.shape[0] != arrays["kp"].shape[1]:
                problems.append(
                    f"ka: {ka.shape[0]} angles but kp holds "
                    f"{arrays['kp'].shape[1]} points"
                )
            # A value of, say, 147.0 here almost certainly means degrees were
            # stored by mistake; the contract fixes radians for the bundle.
            # 147.0 のような値はほぼ確実に度数値の誤格納。バンドル契約では
            # ラジアンに固定している。
            if ka.size > 0 and not (np.all(ka > 0) and np.all(ka < np.pi)):
                problems.append(
                    "ka: kink angles must be radians strictly inside (0, pi)"
                )

    # --- Format version ------------------------------------------------------
    if meta is not None and "version" in meta:
        version = meta["version"]
        if version not in SUPPORTED_BUNDLE_VERSIONS:
            problems.append(
                f"unsupported bundle format version {version!r} "
                f"(supported: {', '.join(SUPPORTED_BUNDLE_VERSIONS)})"
            )

    return problems
