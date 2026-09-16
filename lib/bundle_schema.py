# -*- coding: utf-8 -*-
"""
Executable schema for the ``.b2z`` bundle contract.
``.b2z`` バンドル契約の実行可能スキーマ。

This module is the single in-code definition of the bundle contract: required
keys, array shapes, value ranges, units, and the coordinate convention.
README and AGENTS.md §8.2 describe the contract, but this code is the source of
truth. `validate_bundle` turns violations into clear English messages instead
of letting malformed bundles fail deep inside the tracking code with cryptic
NumPy errors.
本モジュールはバンドル契約（必須キー、配列形状、値域、単位、座標規約）の
コード上の唯一の定義である。README と AGENTS.md §8.2 にも説明はあるが、
本コードを正準とする。`validate_bundle` は契約違反を明確な英語メッセージへ
変換し、壊れたバンドルが追跡コードの奥で不可解な NumPy エラーになるのを防ぐ。

Contract summary / 契約の要約
-----------------------------
- ``calibrated``, ``binarized``, ``skeletonized``, ``bp``, ``ep``: 2D arrays
  sharing one image shape. ``binarized``/``skeletonized``/``bp``/``ep`` hold
  only values 0 and 1.
  画像系キーは同一形状の 2 次元配列。二値キーの値は 0 と 1 のみ。
- ``kp``, ``dp``: integer coordinate arrays of shape ``(2, N)`` where row 0 is
  the x (column) index and row 1 is the y (row) index. From format 1.1
  ``dp`` is written empty: the kink rule no longer decomposes the line, and
  the key stays so every bundle carries the same required keys.
  ``kp``/``dp`` は形状 ``(2, N)`` の座標配列。行 0 が x（列）、行 1 が y（行）。
  形式 1.1 以降、``dp`` は空で書く。キンク規則はもう線を分解しないが、どの
  バンドルも同じ必須キーを持つようにキーは残す。
- ``up`` (optional, from format 1.1): the bends the kink rule measured within
  1.5 apparent widths of a track end, where it does not judge them, in the
  layout of ``kp``. Readers show them but never count them as kinks.
  ``up``（任意キー、形式 1.1 から）は、トラック端から見かけ幅 1.5 本分以内に
  あるためキンク規則が判定しなかった折れで、``kp`` と同じ形式で持つ。読み取り
  側は表示するが、キンクとしては数えない。
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

This module depends only on NumPy and on `lib.centerline`, which is itself
NumPy-only, so GUI plugins and `lib.measure` can import it without pulling in
the heavy preprocessing stack.
本モジュールの依存は NumPy と、それ自体 NumPy のみに依存する `lib.centerline`
だけとし、GUI プラグインや `lib.measure` が重い前処理スタックを読み込まずに
import できるようにする。
"""

# ===== Standard library =====
from typing import Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .centerline import HALF_MAX_CENTERLINE, SKELETON_TRACK

# Version of the bundle layout itself, distinct from the application release
# recorded as "software_version". Bump when keys, shapes, or units change, and
# also when a stored array keeps its shape but changes meaning: an old release
# would otherwise misread it without noticing, and only an unknown version
# makes it refuse the bundle.
# バンドル形式自体のバージョン。アプリのリリース ("software_version") とは
# 別物。キー・形状・単位が変わるとき、および保存配列の形状が同じまま意味が
# 変わるときに繰り上げる。後者で上げないと旧リリースは気付かないまま誤読する。
# 旧リリースにバンドルを拒否させられるのは未知のバージョンだけである。
#
# 1.1: `kp` and `ka` are judged on the half-maximum centerline of
#      `lib.centerline` by the excess-turning rule of `lib.kink_detector`,
#      instead of on the skeleton track by a polyline decomposition, and a
#      reader draws and measures fibers along that line
#      (`centerline_from_meta`). `dp` keeps its shape but is written empty,
#      since nothing is decomposed, and the optional `up` holds the bends not
#      judged next to a track end. The line has one point per skeleton point,
#      so kinks are still stored at skeleton pixels.
# 1.1: `kp`・`ka` は、スケルトントラック上の折れ線分解ではなく、
#      `lib.centerline` の半値中点線上で `lib.kink_detector` の超過回転規則に
#      より判定したものであり、読み取り側はその線に沿って繊維を描画・計測する
#      （`centerline_from_meta`）。`dp` は形状を保つが、何も分解しないため空で
#      書く。任意キー `up` はトラック端のそばで判定しなかった折れを持つ。線は
#      スケルトン点ごとに 1 点を持つため、キンクは引き続きスケルトン画素に保存する。
BUNDLE_FORMAT_VERSION = "1.1"

# Versions this code base can read. Readers reject unknown versions loudly so
# a future format change cannot be silently misinterpreted by old releases.
# 本コードベースが読める形式バージョン。未知のバージョンは明示的に拒否し、
# 将来の形式変更を旧リリースが黙って誤解釈しないようにする。
SUPPORTED_BUNDLE_VERSIONS = ("1.0", "1.1")

# Format versions whose kinks were judged on, and whose fibers are drawn and
# measured along, the half-maximum centerline. A 1.0 bundle, or one recording
# no version at all, keeps the skeleton track until it is re-analyzed.
# キンクを半値中点線上で判定し、繊維をその線に沿って描画・計測する形式
# バージョン。1.0 のバンドル、およびバージョンを記録していないバンドルは、
# 再解析されるまでスケルトントラックを使い続ける。
HALF_MAX_CENTERLINE_VERSIONS = ("1.1",)

# Bundle keys required to treat a file as analyzed.
# One .b2z bundle is written per analyzed file; all keys below must exist.
# 1 解析ファイルにつき 1 つの .b2z バンドルが生成され、下記キーが揃っていれば解析済みと判定する。
#   /calibrated   : Background-corrected image.
#   /binarized    : Binarized image.
#   /skeletonized : Skeletonized image.
#   /bp           : Branch-point mask.
#   /ep           : End-point mask.
#   /kp           : Kink coordinates, shape (2, N), [0]=x, [1]=y.
#   /dp           : Polyline vertices kinks were judged at, shape (2, N);
#                   empty from format 1.1, whose rule does not decompose.
#   /ka           : Kink angles in radians, shape (N,).
REQUIRED_BUNDLE_KEYS = [
    "calibrated", "binarized", "skeletonized",
    "bp", "ep",
    "kp", "dp", "ka",
]

# Optional keys must not affect the analyzed/not-analyzed decision for backward compatibility.
# 後方互換のため、任意キーは解析済み判定に使わない。
#   /original     : Raw height image before the calibrator's one-pixel trim.
#   /up           : Bends not judged next to a track end, shape (2, N);
#                   written from format 1.1, so an older bundle lacks it.
OPTIONAL_BUNDLE_KEYS = ["original", "up"]

# vlmeta key holding the physical spatial calibration (scan size). It is
# optional provenance metadata, like "input_format": bundles written before
# this key existed simply lack it, and readers must treat its absence as
# "scale unknown" rather than an error. Storing it lets length/distance
# measurements be reproduced from the bundle alone instead of re-entering the
# scan size at measurement time.
# 物理空間較正（走査範囲）を保持する vlmeta キー。"input_format" と同様の
# 任意の来歴メタデータで、このキー導入前のバンドルには存在しない。読み取り側は
# 欠落を「スケール不明」として扱い、エラーにしてはならない。これを保存すると、
# 計測時に走査範囲を再入力せずバンドル単体で長さ・距離計測を再現できる。
SPATIAL_CALIBRATION_KEY = "spatial_calibration"

# Where a stored scan size came from, recorded as the calibration "source".
# Priority when resolving a value is input_header > manifest > manual, but any
# single bundle records exactly the source that produced its stored value.
# 保存された走査範囲の出所を示す較正の "source"。値を解決する際の優先順位は
# input_header > manifest > manual だが、各バンドルにはその値を生んだ source を
# そのまま記録する。
SCAN_SIZE_SOURCES = ("input_header", "manifest", "manual")

# vlmeta key naming which part of the input file the bundle was produced from.
# Present only when the analysis ran on a sub-range of the input's scan lines
# (GUI01's scan-line-range crop, `cli.py process --rows`); a bundle covering
# the whole image omits it. Holds `row_start` / `row_stop` (a half-open scan
# line range) and `row_total` (the input's full scan-line count).
# Optional provenance like `input_format`: readers must treat a missing entry
# as "the whole image", never as an error.
# Adding this key does not bump `BUNDLE_FORMAT_VERSION`: no array key, shape,
# or unit changes, and a reader that does not know the key still interprets
# every array correctly, because the stored arrays and the recorded
# `spatial_calibration` already describe the cropped image.
# バンドルが入力ファイルのどの部分から作られたかを示す vlmeta キー。解析が入力の
# 走査線の部分範囲に対して行われた場合（GUI01 の走査線範囲切り出し、
# `cli.py process --rows`）のみ存在し、画像全体のバンドルでは省略される。
# `row_start` / `row_stop`（半開区間の走査線範囲）と `row_total`（入力の全走査
# 線数）を持つ。`input_format` と同様の任意の来歴情報であり、読み取り側は欠落を
# 「画像全体」と解釈しなければならず、エラーにしてはならない。
# このキーの追加で `BUNDLE_FORMAT_VERSION` は上げない。配列キー・形状・単位の
# いずれも変わらず、このキーを知らない読み取り側でも全配列を正しく解釈できる。
# 保存された配列と記録済みの `spatial_calibration` が既に切り出し後の画像を
# 表しているためである。
SOURCE_REGION_KEY = "source_region"

# vlmeta key holding the apparent widths the kink rule scaled its lengths by
# (`centerline.measure_apparent_width`): `median_px`, the median over the
# traced components; `component_count`; `fallback_count`, how many components
# gave no usable width and were placed with `fallback_px`
# (`centerline.FALLBACK_WIDTH_PX`) instead. The kink rule is expressed in
# multiples of the width, so this entry is what says at which physical scale
# a bundle's kinks were judged -- the width is the probe's broadening as much
# as the fiber's, and changes with the tip. Optional provenance, like the
# other keys above: older bundles lack it, and adding it does not bump
# `BUNDLE_FORMAT_VERSION`, because a reader recomputes the per-fiber widths
# from the arrays when it traces them.
# キンク規則が長さを尺度付けした見かけ幅（`centerline.measure_apparent_width`）
# を保持する vlmeta キー。`median_px` は追跡した成分にわたる中央値、
# `component_count` は成分数、`fallback_count` は使える幅が得られず代わりに
# `fallback_px`（`centerline.FALLBACK_WIDTH_PX`）で線を置いた成分数。キンク規則は
# 幅の倍数で表されるため、この項目がバンドルのキンクをどの物理尺度で判定したかを
# 示す。幅は繊維の幅であると同時に探針による広がりでもあり、探針が変われば
# 変わる。上の各キーと同様の任意の来歴情報であり、旧バンドルには無い。追加しても
# `BUNDLE_FORMAT_VERSION` は上げない。読み取り側は繊維を追跡するときに配列から
# 繊維ごとの幅を再計算するためである。
APPARENT_WIDTH_KEY = "apparent_width"

# vlmeta key holding what the pixel-unit settings of the stages amount to in
# nanometres on this scan (`pipeline.pixel_lengths_nm`): the pixel size per
# axis, and every `ProcParams` length or area given in pixels, plus the
# skeleton cleanup's fixed pixel constants, converted with it. The stages are
# deliberately pixel-based, so the same `_param.json` prunes a 12 px spur on a
# 2 µm scan (about 23 nm) and on a 10 µm scan (about 117 nm); this entry is
# what makes that difference visible when two bundles are compared. Derived
# entirely from `params` and `spatial_calibration`, so it is a convenience
# record, not a second source of truth. Optional: absent when the scan size
# was unknown, and older bundles lack it.
# 各段の画素単位の設定がこの走査で何 nm にあたるかを保持する vlmeta キー
# （`pipeline.pixel_lengths_nm`）。軸ごとのピクセルサイズと、画素で与える
# `ProcParams` の長さ・面積のすべて、および骨格クリーニングの固定画素定数を、
# それで換算したもの。各段は意図的に画素基準なので、同じ `_param.json` でも
# 12 px のスパーは 2 µm 走査では約 23 nm、10 µm 走査では約 117 nm を刈る。この
# 項目は、2 つのバンドルを比べるときにその違いを見えるようにする。`params` と
# `spatial_calibration` から完全に導けるため、便宜的な記録であって第 2 の
# 真実の源ではない。任意項目で、走査範囲が不明なら無く、旧バンドルにも無い。
PIXEL_LENGTHS_KEY = "pixel_lengths_nm"

# vlmeta key holding the `ProcParams` dictionary the analysis ran with, the
# same content as the `<input_stem>_param.json` sidecar. It is provenance for
# every field but two: a reader that recomputes kink points on a track the
# bundle does not contain — reconnected fibrils, height-band sub-fibers — has
# to apply the same rule that produced `kp` / `ka`, and the bundle is the only
# place that rule travels with the arrays it explains. The sidecar is the
# analysis *input* and is editable afterwards, so reading the thresholds from
# it would let an edit change a fibril's kinks with no re-analysis.
# Optional like the other provenance keys: bundles from older releases lack it,
# and `kink_params_from_meta` reports a missing field as "not recorded" so the
# caller falls back to the detector defaults those runs used.
# 解析実行時の `ProcParams` 辞書を保持する vlmeta キー。内容は
# `<input_stem>_param.json` サイドカーと同一。ほとんどのフィールドは来歴情報
# だが、バンドルに含まれないトラック上でキンクを再計算する読み取り側
# （再結合フィブリル、高さ帯サブファイバー）は `kp` / `ka` を生んだ規則と
# 同じものを適用する必要があり、その規則が説明対象の配列と一緒に運ばれる場所は
# バンドルだけである。サイドカーは解析の*入力*であり事後編集が可能なので、
# そこからしきい値を読むと、再解析なしにフィブリルのキンクが変わってしまう。
# 他の来歴キーと同様に任意項目。旧リリースのバンドルには存在せず、
# `kink_params_from_meta` は欠落フィールドを「未記録」として返すため、
# 呼び出し側はその実行が使った検出器既定値へフォールバックする。
PARAMS_KEY = "params"

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
_POINT_KEYS = ("kp", "dp", "up")


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
    known = set(_IMAGE_KEYS) | set(_POINT_KEYS) | {"ka"} | set(OPTIONAL_BUNDLE_KEYS)
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


def make_spatial_calibration(
    x_um: float, y_um: float, source: str
) -> Dict[str, object]:
    """
    Build the ``spatial_calibration`` vlmeta entry for a known scan size.
    既知の走査範囲から ``spatial_calibration`` vlmeta エントリを組み立てる。

    Parameters
    ----------
    x_um, y_um
        Physical scan size per axis in micrometers; both must be positive.
        軸ごとの物理走査範囲 (µm)。いずれも正の値であること。
    source
        Provenance of the value, one of `SCAN_SIZE_SOURCES`.
        値の出所。`SCAN_SIZE_SOURCES` のいずれか。

    Returns
    -------
    dict
        msgpack-serializable mapping to store under `SPATIAL_CALIBRATION_KEY`.
        `SPATIAL_CALIBRATION_KEY` 配下に保存する msgpack 直列化可能な辞書。

    Notes
    -----
    Pixel size is intentionally not stored: it is a derived quantity
    (``scan_size_um * 1000 / pixels`` along each axis) that the measurement
    layer recomputes from the saved image shape, so persisting it would risk
    drifting out of sync with the actual array (and with the one-pixel trim
    documented at module top).
    ピクセルサイズは意図的に保存しない。これは各軸の
    ``走査範囲_um * 1000 / 画素数`` から導出される量で、計測層が保存済み画像形状
    から再計算する。保存すると実配列（およびモジュール冒頭に記載の 1 画素
    トリミング）と不整合になる恐れがあるため。

    Raises
    ------
    ValueError
        If a size is not positive or `source` is not a known source.
    """
    if not (x_um > 0 and y_um > 0):
        raise ValueError(
            f"scan size must be positive, got x={x_um!r}, y={y_um!r}"
        )
    if source not in SCAN_SIZE_SOURCES:
        raise ValueError(
            f"unknown scan-size source {source!r} "
            f"(expected one of {', '.join(SCAN_SIZE_SOURCES)})"
        )
    return {
        "scan_size_x_um": float(x_um),
        "scan_size_y_um": float(y_um),
        "source": source,
    }


def scan_size_um_from_meta(
    meta: Optional[Dict],
) -> Optional[Tuple[float, float]]:
    """
    Extract ``(x_um, y_um)`` scan size from bundle vlmeta, if recorded.
    バンドル vlmeta から走査範囲 ``(x_um, y_um)`` を取り出す（記録があれば）。

    Parameters
    ----------
    meta
        Bundle vlmeta dictionary, or ``None``.
        バンドルの vlmeta 辞書、または ``None``。

    Returns
    -------
    tuple of float or None
        Per-axis scan size in micrometers, or ``None`` when the bundle does
        not record a valid spatial calibration.
        軸ごとの走査範囲 (µm)。有効な空間較正が記録されていなければ ``None``。
    """
    if not meta:
        return None
    cal = meta.get(SPATIAL_CALIBRATION_KEY)
    if not isinstance(cal, dict):
        return None
    try:
        x_um = float(cal["scan_size_x_um"])
        y_um = float(cal["scan_size_y_um"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (x_um > 0 and y_um > 0):
        return None
    return x_um, y_um


def kink_params_from_meta(
    meta: Optional[Dict],
) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract the kink-detection thresholds the analysis ran with, if recorded.
    解析実行時のキンク検出しきい値を取り出す（記録があれば）。

    Parameters
    ----------
    meta
        Bundle vlmeta dictionary, or ``None``.
        バンドルの vlmeta 辞書、または ``None``。

    Returns
    -------
    tuple
        ``(kinkangle_deg, kink_decompose_px)``, each ``None`` when the bundle
        does not record a valid value for it. The angle is in degrees, as
        stored; converting to the radians `KinkDetector` takes is the caller's
        job, and is done in exactly one place (`lib.pipeline.build_stages`).
        ``(kinkangle_deg, kink_decompose_px)``。有効な値が記録されていない項目は
        ``None``。角度は保存形式どおり度で返す。`KinkDetector` が受け取る
        ラジアンへの変換は呼び出し側の役割で、変換箇所は 1 つだけである
        （`lib.pipeline.build_stages`）。

    Notes
    -----
    The two are reported independently because they entered the parameter set
    at different times: a bundle written before `kink_decompose_px` existed
    records the angle and not the tolerance, and that run used the detector's
    own default for the tolerance. Returning ``None`` for the missing one lets
    the caller reproduce exactly that, where a single "all or nothing" result
    would discard the angle the bundle does record.
    2 つを独立に返すのは、パラメータ集合へ加わった時期が異なるためである。
    `kink_decompose_px` 導入前に書かれたバンドルは角度のみを記録しており、その
    実行は許容値に検出器自身の既定値を使っていた。欠落側を ``None`` で返せば
    呼び出し側はその状態をそのまま再現できる。一括で「全部あるか無しか」にすると、
    バンドルが実際に記録している角度まで捨てることになる。

    Bounds match `lib.pipeline.validate_params`, so a value this function
    accepts is one the pipeline would have accepted. An out-of-range or
    non-numeric entry reads as "not recorded" rather than raising: it is
    provenance written by an unknown release, and refusing to open the bundle
    over it would block measurement that does not depend on it.
    値域は `lib.pipeline.validate_params` と一致させてあり、本関数が受け入れる値は
    パイプラインが受け入れたはずの値である。範囲外や非数値は例外ではなく
    「未記録」として扱う。これは未知のリリースが書いた来歴情報であり、それを理由に
    バンドルを開けなくすると、その値に依存しない計測まで止めてしまうためである。
    """
    if not meta:
        return None, None
    params = meta.get(PARAMS_KEY)
    if not isinstance(params, dict):
        return None, None

    def _valid(
        key: str, lo: float, hi: Optional[float], strict_lo: bool = False,
    ) -> Optional[float]:
        try:
            value = float(params[key])
        except (KeyError, TypeError, ValueError):
            return None
        if not np.isfinite(value):
            return None
        if value < lo or (strict_lo and value == lo):
            return None
        if hi is not None and value > hi:
            return None
        return value

    return (
        _valid("kinkangle_deg", 0.0, 180.0),
        _valid("kink_decompose_px", 0.0, None, strict_lo=True),
    )


def centerline_from_meta(meta: Optional[Dict]) -> str:
    """
    Return which line a bundle's kinks were judged on and its fibers are measured along.
    バンドルのキンクを判定した線、すなわち繊維を計測する線の種類を返す。

    Parameters
    ----------
    meta
        Bundle vlmeta dictionary, or ``None``.
        バンドルの vlmeta 辞書、または ``None``。

    Returns
    -------
    str
        `centerline.HALF_MAX_CENTERLINE` for a format listed in
        `HALF_MAX_CENTERLINE_VERSIONS`, otherwise `centerline.SKELETON_TRACK`.
        `HALF_MAX_CENTERLINE_VERSIONS` に含まれる形式なら
        `centerline.HALF_MAX_CENTERLINE`、それ以外は `centerline.SKELETON_TRACK`。

    Notes
    -----
    The stored kinks and the line they are drawn on have to come from one
    definition. Rebuilding a 1.0 bundle on the centerline would put kinks
    judged on the skeleton onto a line that no longer has the bends they
    marked, and would change its lengths and heights without a re-analysis.
    An older bundle therefore keeps the skeleton track, and the caller tells
    the user it can be re-analyzed. A missing version means an older release,
    not an error.
    保存済みのキンクと、それを描く線は 1 つの定義から来なければならない。1.0 の
    バンドルを半値中点線で組み立て直すと、スケルトン上で判定したキンクを、それが
    示した折れをもう持たない線の上に載せることになり、再解析なしに長さと高さも
    変わってしまう。そのため古いバンドルはスケルトントラックを使い続け、呼び出し側が
    再解析できることを利用者に伝える。バージョンの欠落は旧リリース製であることを
    意味し、エラーではない。
    """
    if meta and meta.get("version") in HALF_MAX_CENTERLINE_VERSIONS:
        return HALF_MAX_CENTERLINE
    return SKELETON_TRACK
