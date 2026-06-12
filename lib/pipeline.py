# -*- coding: utf-8 -*-
"""
GUI-independent driver for the AFM nanofiber preprocessing pipeline.
GUI に依存しない AFM ナノファイバー前処理パイプラインの駆動モジュール。

This module owns the analysis-side responsibilities that were previously
embedded in GUI01: the `ProcParams` parameter schema, the `.b2z` bundle key
contract, stage construction, and single-file processing with output saving.
GUI01 に埋め込まれていた解析側の責務（`ProcParams` スキーマ、`.b2z` バンドル
キー契約、ステージ構築、1 ファイル処理と出力保存）をこのモジュールが持つ。

GUI01 and the command-line interface both call `process_file`, so the two
entry points always produce byte-identical analysis outputs for the same
input and parameters.
GUI01 とコマンドラインの両方が `process_file` を呼ぶため、同じ入力と
パラメータに対して両入口の解析出力は常に一致する。

Progress reporting uses fixed English stage keys (see `STAGE_KEYS`) passed to
an optional callback; callers translate or print them as needed. This keeps
gettext out of the analysis layer.
進捗通知は固定の英語ステージキー（`STAGE_KEYS` 参照）をコールバックへ渡す
方式とし、翻訳や表示は呼び出し側に任せる。解析層に gettext を持ち込まない。
"""

# ===== Standard library =====
import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from . import __version__
from .afm_io import detect_afm_format, load_afm_text
from .bg_calibrator import BGCalibrator
from .blosc2_io import save_bundle, bundle_has_keys, BUNDLE_EXT
# The bundle key contract and format version are owned by bundle_schema;
# re-imported here so existing `pipeline.REQUIRED_BUNDLE_KEYS` users keep working.
# バンドルのキー契約と形式バージョンは bundle_schema が管理する。既存の
# `pipeline.REQUIRED_BUNDLE_KEYS` 利用側が動き続けるよう、ここで再インポートする。
from .bundle_schema import (
    BUNDLE_FORMAT_VERSION, OPTIONAL_BUNDLE_KEYS, REQUIRED_BUNDLE_KEYS,
    validate_bundle,
)
from .kink_detector import KinkDetector
from .processed_image import ProcessedImage
from .segmenter import Segmenter
from .skeletonizer import Skeletonizer


@dataclass
class ProcParams:
    """
    Processing parameters shared by the preprocessing pipeline.
    前処理パイプラインで共有する解析パラメータ。

    Attributes
    ----------
    bg_method
        Background-estimation method.
        背景推定方式。
    tophat_se_size
        Diameter of the structuring element in pixels for `tophat`.
        `tophat` 用の構造要素直径 (px)。
    spline1d_axis
        Direction used by the one-dimensional spline background model.
        1D スプライン背景モデルで補間する方向。
    spline1d_degree
        Spline degree used by `spline1d`.
        `spline1d` で用いるスプライン次数。
    spline2d_degree
        Spline degree used by `spline2d`.
        `spline2d` で用いるスプライン次数。
    spline2d_subsample
        Pixel subsampling factor for the `spline2d` fit.
        `spline2d` フィット用の画素サブサンプル係数。
    spline2d_smoothing
        Smoothing factor for `spline2d`; kept out of the GUI by default.
        `spline2d` の平滑化係数。既定では GUI に露出しない。
    threshold_factor
        Sigma multiplier used to define the background range.
        背景範囲を定める sigma 係数。
    fiber_detect_factor
        Threshold for excluding abrupt height changes as fibers.
        急峻な高さ変化を繊維として除外するしきい値。
    noise_detect_factor
        Threshold for distinguishing structural changes from noise.
        構造変化とノイズを区別するしきい値。
    savgol_window
        Window length for the Savitzky-Golay smoothing filter.
        Savitzky-Golay 平滑化フィルタの窓幅。
    savgol_polyorder
        Polynomial order for the Savitzky-Golay filter.
        Savitzky-Golay フィルタの多項式次数。
    apply_median
        Whether to apply a final median filter.
        最後に中央値フィルタを適用するか。
    mask_dilation
        Pixel radius used to dilate the fiber mask.
        繊維マスクを膨張させる画素数。
    min_mask_component_area
        Minimum connected-component area retained in the mask.
        マスク内に保持する連結成分の最小面積。
    wsize_localbin
        Window size for local thresholding.
        局所しきい値計算のウィンドウサイズ。
    global_threshold
        Global binarization threshold.
        全体一律の二値化しきい値。
    area_min
        Minimum component area retained after binarization.
        二値化後に保持する連結成分の最小面積。
    area_min_connecting
        Area threshold used by the disconnected-component cleanup.
        つながり除去で用いる面積しきい値。
    apply_no_connecting
        Whether to run disconnected-component cleanup.
        つながり除去を実行するか。
    h_length
        Minimum line length for Hough-based line detection.
        Hough 変換で線分とみなす最小長。
    h_sratio
        Line-likeness threshold.
        線らしさを示す s_ratio のしきい値。
    low_threshold
        Height threshold in nanometers for removing low components.
        低い成分を除去する高さしきい値 (nm)。
    bp_height
        Height threshold for branch-point filtering.
        分岐点を判定する高さしきい値。
    branch_length
        Maximum branch length traced during skeleton cleanup.
        スケルトン整理時に枝として追跡する最大長。
    min_area
        Minimum area retained after skeletonization.
        細線化後に保持する最小面積。
    kinkangle_deg
        Bend-angle threshold in degrees for kink detection.
        キンク検出に用いる折れ角しきい値 (度)。

    Notes
    -----
    Field names are serialized verbatim into `<input_stem>_param.json` and the
    startup settings file; do not rename them.
    フィールド名は `<input_stem>_param.json` と起動時設定ファイルへそのまま
    シリアライズされるため、リネームしてはならない。

    Physical image size is intentionally excluded. It is display metadata, not
    an analysis parameter, and folders may contain images with different scan
    sizes.
    画像の実寸は意図的に除外している。実寸は解析結果に影響しない表示用
    メタ情報であり、同一フォルダ内に異なるスキャンサイズの画像が混在する
    可能性があるため。
    """

    # BGCalibrator parameters.
    bg_method: str = "inpaint"             # Background method: inpaint, tophat, spline1d, or spline2d.
    tophat_se_size: int = 25               # Structuring-element diameter for tophat, in pixels.
    spline1d_axis: str = "x"               # Axis used for the one-dimensional spline interpolation.
    spline1d_degree: int = 2               # Spline degree for spline1d; practical range is 1 to 3.
    spline2d_degree: int = 2               # Spline degree for spline2d; practical range is 1 to 3.
    spline2d_subsample: int = 4            # Pixel subsampling factor per axis for spline2d.
    spline2d_smoothing: Optional[float] = None  # Hidden advanced spline2d smoothing value; None keeps SciPy's default and avoids unstable near-interpolation fits.
    threshold_factor: float = 2.0          # Sigma multiplier for the background range.
    fiber_detect_factor: float = 10.0      # Threshold for treating abrupt height changes as fibers.
    noise_detect_factor: float = 10.0      # Threshold for separating structural change from noise.
    savgol_window: int = 31                # Savitzky-Golay smoothing window for inpaint, tophat, and spline1d.
    savgol_polyorder: int = 1              # Savitzky-Golay polynomial order for inpaint, tophat, and spline1d.
    apply_median: bool = False             # Whether to apply the final median filter.
    mask_dilation: int = 3                 # Fiber-mask dilation radius in pixels; 0 disables dilation.
    min_mask_component_area: int = 10      # Minimum mask component area retained before dilation; 1 disables filtering.

    # Segmenter parameters.
    wsize_localbin: int = 17               # Window size for local thresholding.
    global_threshold: float = 0.3         # Global binarization threshold.
    area_min: int = 100                    # Minimum component area retained, in px^2.
    area_min_connecting: int = 3           # Area threshold for disconnected-component cleanup.
    apply_no_connecting: bool = False      # Whether to run disconnected-component cleanup.
    h_length: int = 20                     # Minimum Hough line length.
    h_sratio: float = 0.5                  # Line-likeness threshold.
    low_threshold: float = 1.8             # Low-height removal threshold, in nanometers.

    # Skeletonizer parameters.
    bp_height: float = 10.0               # Height threshold for branch-point filtering.
    branch_length: int = 12               # Maximum branch length traced during skeleton cleanup, in pixels.
    min_area: int = 10                    # Minimum area retained after skeletonization.

    # Kink-detection parameters.
    kinkangle_deg: float = 150.0          # Bends at or below this angle are detected as kinks.


# Fixed English stage keys reported through the `on_stage` callback, in order.
# These are internal identifiers, not user-visible text; do not translate them.
# `on_stage` コールバックへ順に通知される固定の英語ステージキー。
# 内部識別子でありユーザー表示文字列ではないため翻訳しない。
STAGE_KEYS = ("load", "bg", "binarize", "skeletonize", "kink", "save")


def _sha256_of_file(path: str) -> str:
    """
    Return the SHA-256 hex digest of a file's contents.
    ファイル内容の SHA-256 16進ダイジェストを返す。

    Recorded in bundle provenance metadata so the exact input of an analysis
    can be verified afterwards.
    解析の入力を事後検証できるよう、バンドルの来歴メタデータに記録される。
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_path_for(stem: str) -> str:
    """
    Return the bundle path for an extensionless input path.
    拡張子を除いた入力パスに対応するバンドルパスを返す。
    """
    return stem + BUNDLE_EXT


def param_path_for(stem: str) -> str:
    """
    Return the sidecar parameter JSON path for an extensionless input path.
    拡張子を除いた入力パスに対応するパラメータ JSON のパスを返す。
    """
    return stem + "_param.json"


def existing_min_set(stem: str) -> Tuple[bool, List[str]]:
    """
    Check whether all required bundle keys exist for an input stem.
    入力 stem に対応するバンドルへ必須キーが揃っているか確認する。
    """
    return bundle_has_keys(bundle_path_for(stem), REQUIRED_BUNDLE_KEYS)


def merge_params_dict(d: Dict) -> Tuple[ProcParams, List[str], List[str]]:
    """
    Build `ProcParams` from a raw dict, tolerating missing and unknown keys.
    欠損キー・未知キーを許容しつつ、生の辞書から `ProcParams` を構築する。

    Missing keys fall back to `ProcParams` defaults so old settings files keep
    working when new fields are added; keys outside the current schema are
    ignored. Callers decide how to report both lists to the user.
    欠損キーは `ProcParams` の既定値で補完し、旧設定ファイルに新規フィールドが
    無くても動作を維持する。現スキーマ外のキーは無視する。両リストの通知方法は
    呼び出し側が決める。

    Parameters
    ----------
    d
        Raw key-value mapping loaded from a settings or parameter JSON file.
        設定／パラメータ JSON から読み込んだ生のキーと値の辞書。

    Returns
    -------
    tuple
        The merged `ProcParams`, the missing key names filled from defaults,
        and the unknown key names that were ignored.
        マージ済み `ProcParams`、既定値で補完した欠損キー名、無視した未知
        キー名の組。

    Raises
    ------
    TypeError
        If a known key holds a value `ProcParams` cannot accept.
    """
    defaults_dict = asdict(ProcParams())
    missing = [k for k in defaults_dict if k not in d]
    obsolete = [k for k in d if k not in defaults_dict]
    merged = {k: d.get(k, defaults_dict[k]) for k in defaults_dict}
    return ProcParams(**merged), missing, obsolete


# Allowed values for enumerated string parameters.
# 列挙型文字列パラメータの許容値。
BG_METHODS = ("inpaint", "tophat", "spline1d", "spline2d")
SPLINE1D_AXES = ("x", "y")


def validate_params(p: ProcParams) -> List[str]:
    """
    Return all detected problems in analysis parameters; empty when valid.
    解析パラメータの問題点をすべて返す。問題がなければ空リスト。

    All violations are collected instead of failing fast, so a parameter JSON
    can be fixed in one editing pass. Messages are fixed English strings
    because field names are serialized identifiers; callers wrap them in
    translated UI text as needed (gettext stays out of the analysis layer).
    一括修正できるよう fail-fast にせず全違反を収集する。フィールド名は
    シリアライズされる識別子のため、メッセージは固定英語とする。表示用の
    翻訳文への包み込みは呼び出し側が行う（解析層に gettext を持ち込まない）。

    Only constraints that provably break the pipeline or are structurally
    nonsensical are enforced. Settings such as a negative `low_threshold`
    (which disables low-component removal) stay legal on purpose.
    パイプラインが確実に壊れる制約、または構造的に無意味な値のみを検査する。
    負の `low_threshold`（低成分除去の実質無効化）のような使い方は意図的に
    許容したままにする。

    Notes
    -----
    Range sources verified against the libraries in use:
    使用ライブラリに対して検証済みの制約の出典:

    - `savgol_polyorder < savgol_window`: required by
      `scipy.signal.savgol_filter`.
    - `wsize_localbin` odd: required by `skimage.filters.threshold_local`.
    - `spline2d_degree` 1-5: `scipy.interpolate.SmoothBivariateSpline` kx/ky.
    - `spline1d_degree` 1-5: pandas spline interpolation delegates to
      `scipy.interpolate.UnivariateSpline` (k must be 1-5).
    """
    problems: List[str] = []

    def _num(value) -> bool:
        # bool passes isinstance(int) checks but is never a valid number here.
        # bool は isinstance(int) を満たすが、数値パラメータとしては常に不正。
        return (
            isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, bool)
        )

    def _intval(value) -> bool:
        return isinstance(value, (int, np.integer)) and not isinstance(value, bool)

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    # --- Background calibration ---
    require(p.bg_method in BG_METHODS,
            f"bg_method must be one of {BG_METHODS}, got {p.bg_method!r}")
    require(_intval(p.tophat_se_size) and p.tophat_se_size >= 1,
            f"tophat_se_size must be a positive int (px), got {p.tophat_se_size!r}")
    require(p.spline1d_axis in SPLINE1D_AXES,
            f"spline1d_axis must be one of {SPLINE1D_AXES}, got {p.spline1d_axis!r}")
    require(_intval(p.spline1d_degree) and 1 <= p.spline1d_degree <= 5,
            f"spline1d_degree must be an int in [1, 5], got {p.spline1d_degree!r}")
    require(_intval(p.spline2d_degree) and 1 <= p.spline2d_degree <= 5,
            f"spline2d_degree must be an int in [1, 5], got {p.spline2d_degree!r}")
    require(_intval(p.spline2d_subsample) and p.spline2d_subsample >= 1,
            f"spline2d_subsample must be a positive int, got {p.spline2d_subsample!r}")
    require(p.spline2d_smoothing is None
            or (_num(p.spline2d_smoothing) and p.spline2d_smoothing >= 0),
            f"spline2d_smoothing must be None or a non-negative number, "
            f"got {p.spline2d_smoothing!r}")
    for name in ("threshold_factor", "fiber_detect_factor", "noise_detect_factor"):
        value = getattr(p, name)
        require(_num(value) and value > 0,
                f"{name} must be a positive number, got {value!r}")
    require(_intval(p.savgol_window) and p.savgol_window >= 1,
            f"savgol_window must be a positive int, got {p.savgol_window!r}")
    require(_intval(p.savgol_polyorder) and p.savgol_polyorder >= 0,
            f"savgol_polyorder must be a non-negative int, got {p.savgol_polyorder!r}")
    if _intval(p.savgol_window) and _intval(p.savgol_polyorder):
        require(p.savgol_polyorder < p.savgol_window,
                f"savgol_polyorder must be less than savgol_window, got "
                f"polyorder={p.savgol_polyorder} >= window={p.savgol_window}")
    require(isinstance(p.apply_median, bool),
            f"apply_median must be a bool, got {p.apply_median!r}")
    require(_intval(p.mask_dilation) and p.mask_dilation >= 0,
            f"mask_dilation must be a non-negative int (0 disables dilation), "
            f"got {p.mask_dilation!r}")
    require(_intval(p.min_mask_component_area) and p.min_mask_component_area >= 1,
            f"min_mask_component_area must be a positive int (1 disables "
            f"filtering), got {p.min_mask_component_area!r}")

    # --- Binarization ---
    require(_intval(p.wsize_localbin) and p.wsize_localbin >= 1
            and p.wsize_localbin % 2 == 1,
            f"wsize_localbin must be a positive odd int (local-threshold "
            f"block size), got {p.wsize_localbin!r}")
    require(_num(p.global_threshold),
            f"global_threshold must be a number (nm), got {p.global_threshold!r}")
    require(_intval(p.area_min) and p.area_min >= 0,
            f"area_min must be a non-negative int (px^2), got {p.area_min!r}")
    require(_intval(p.area_min_connecting) and p.area_min_connecting >= 0,
            f"area_min_connecting must be a non-negative int (px^2), "
            f"got {p.area_min_connecting!r}")
    require(isinstance(p.apply_no_connecting, bool),
            f"apply_no_connecting must be a bool, got {p.apply_no_connecting!r}")
    require(_intval(p.h_length) and p.h_length >= 1,
            f"h_length must be a positive int (px), got {p.h_length!r}")
    require(_num(p.h_sratio) and p.h_sratio >= 0,
            f"h_sratio must be a non-negative number, got {p.h_sratio!r}")
    require(_num(p.low_threshold),
            f"low_threshold must be a number (nm), got {p.low_threshold!r}")

    # --- Skeletonization ---
    require(_num(p.bp_height),
            f"bp_height must be a number (nm), got {p.bp_height!r}")
    # branch_length is also the tracking window radius; 0 would create empty
    # slices and crash the branch-tracking loop.
    # branch_length は追跡窓の半径でもあり、0 だと空スライスになって
    # 枝追跡ループが壊れる。
    require(_intval(p.branch_length) and p.branch_length >= 1,
            f"branch_length must be a positive int (px), got {p.branch_length!r}")
    require(_intval(p.min_area) and p.min_area >= 0,
            f"min_area must be a non-negative int (px^2), got {p.min_area!r}")

    # --- Kink detection ---
    require(_num(p.kinkangle_deg) and 0 <= p.kinkangle_deg <= 180,
            f"kinkangle_deg must be a number in [0, 180] degrees, "
            f"got {p.kinkangle_deg!r}")

    return problems


@dataclass
class PipelineStages:
    """
    Constructed stage objects reused across a batch run.
    バッチ実行中に再利用されるステージオブジェクト群。

    Attributes
    ----------
    bg_calibrator
        Background-calibration stage.
        背景補正ステージ。
    segmenter
        Binarization / component-cleanup stage.
        二値化・成分処理ステージ。
    skeletonizer
        Skeletonization stage.
        細線化ステージ。
    kink_detector
        Kink-detection stage.
        キンク検出ステージ。
    """

    bg_calibrator: BGCalibrator
    segmenter: Segmenter
    skeletonizer: Skeletonizer
    kink_detector: KinkDetector


def build_stages(p: ProcParams) -> PipelineStages:
    """
    Construct the four pipeline stage objects from analysis parameters.
    解析パラメータから 4 つのパイプラインステージを構築する。

    Analysis results are written into the `ProcessedImage`. Stage objects do
    keep per-call intermediate arrays on themselves for debugging and
    parameter-tuning inspection, but those are overwritten on every call, so
    one set can be reused for a sequential batch. Stage objects are NOT
    thread-safe: do not share one set across concurrent workers.
    解析結果は `ProcessedImage` に書き込まれる。ステージオブジェクトは
    デバッグ・パラメータ調整時の確認用に呼び出しごとの中間配列を自身に
    保持するが、毎回上書きされるため、逐次バッチなら 1 セットを再利用
    できる。スレッドセーフではないため、並行ワーカー間で同一セットを
    共有してはならない。

    Parameters
    ----------
    p
        Analysis parameters for all four stages.
        4 ステージ分の解析パラメータ。

    Returns
    -------
    PipelineStages
        Ready-to-call stage objects.
        呼び出し可能な状態のステージオブジェクト群。
    """
    bg_calibrator = BGCalibrator(
        bg_method=p.bg_method,
        tophat_se_size=p.tophat_se_size,
        spline1d_axis=p.spline1d_axis,
        spline1d_degree=p.spline1d_degree,
        spline2d_degree=p.spline2d_degree,
        spline2d_subsample=p.spline2d_subsample,
        spline2d_smoothing=p.spline2d_smoothing,
        threshold_factor=p.threshold_factor,
        fiber_detect_factor=p.fiber_detect_factor,
        noise_detect_factor=p.noise_detect_factor,
        savgol_window=p.savgol_window,
        savgol_polyorder=p.savgol_polyorder,
        apply_median=p.apply_median,
        mask_dilation=p.mask_dilation,
        min_mask_component_area=p.min_mask_component_area,
    )
    segmenter = Segmenter(
        wsize_localbin=p.wsize_localbin,
        global_threshold=p.global_threshold,
        area_min=p.area_min,
        area_min_connecting=p.area_min_connecting,
        apply_no_connecting=p.apply_no_connecting,
        h_length=p.h_length,
        h_sratio=p.h_sratio,
        low_threshold=p.low_threshold,
    )
    skeletonizer = Skeletonizer(
        bp_height=p.bp_height,
        branch_length=p.branch_length,
        min_area=p.min_area,
    )
    kink_detector = KinkDetector(
        # KinkDetector expects radians, while ProcParams stores degrees.
        # KinkDetector はラジアンを受け取るが、ProcParams は度で保持する。
        threshold_angle_from_decomposed_indices=p.kinkangle_deg * np.pi / 180.0
    )
    return PipelineStages(
        bg_calibrator=bg_calibrator,
        segmenter=segmenter,
        skeletonizer=skeletonizer,
        kink_detector=kink_detector,
    )


@dataclass
class PipelineResult:
    """
    Outputs of one `process_file` run.
    `process_file` 1 回分の実行結果。

    Attributes
    ----------
    image
        Processed image container holding all intermediate arrays.
        全中間配列を保持する処理済み画像コンテナ。
    bundle_path
        Path of the written `.b2z` bundle.
        書き込まれた `.b2z` バンドルのパス。
    param_path
        Path of the written sidecar parameter JSON.
        書き込まれたパラメータ JSON のパス。
    elapsed_s
        Wall-clock processing time in seconds.
        処理に要した実時間 (秒)。
    """

    image: ProcessedImage
    bundle_path: str
    param_path: str
    elapsed_s: float


def process_file(
    txt_path: str,
    params: ProcParams,
    *,
    stages: Optional[PipelineStages] = None,
    output_dir: Optional[str] = None,
    save_original: bool = False,
    on_stage: Optional[Callable[[str], None]] = None,
    input_format: str = "auto",
) -> PipelineResult:
    """
    Run the full preprocessing pipeline on one input file and save outputs.
    1 入力ファイルに前処理パイプライン全体を実行し、出力を保存する。

    The pipeline order is fixed: load -> background calibration ->
    binarization -> skeletonization -> kink detection -> save. Outputs are one
    `.b2z` bundle plus one `_param.json` sidecar, written next to the input
    file unless `output_dir` overrides the destination.
    パイプラインの順序は固定（読み込み→背景補正→二値化→細線化→キンク検出→
    保存）。出力は 1 つの `.b2z` バンドルと 1 つの `_param.json` で、
    `output_dir` 指定がなければ入力ファイルと同じ場所に書き込む。

    Parameters
    ----------
    txt_path
        Path to the raw AFM text/CSV input file.
        生の AFM テキスト/CSV 入力ファイルのパス。
    params
        Analysis parameters; serialized verbatim into the sidecar JSON.
        解析パラメータ。そのままサイドカー JSON にシリアライズされる。
    stages
        Pre-built stage objects to reuse across a batch. Built from `params`
        when omitted.
        バッチで再利用する構築済みステージ。省略時は `params` から構築する。
    output_dir
        Destination directory for outputs. Defaults to the input directory.
        出力先ディレクトリ。省略時は入力ファイルと同じディレクトリ。
    save_original
        When True, the raw height image is bundled under the "original" key,
        making the `.b2z` self-contained (no dependency on the source text).
        True のとき元の高さ画像を "original" キーで同梱し、`.b2z` を入力
        テキストに依存しない自己完結形式にする。
    on_stage
        Optional progress callback receiving one of `STAGE_KEYS` before each
        stage starts.
        各ステージ開始前に `STAGE_KEYS` の値を受け取る進捗コールバック。
    input_format
        Text-layout selection passed to `detect_afm_format`: ``"auto"``
        (default), ``"multi-column"``, or ``"single-column"``. The resolved
        layout is recorded in the bundle provenance metadata.
        `detect_afm_format` へ渡すテキストレイアウト指定。``"auto"``（既定）、
        ``"multi-column"``、``"single-column"``。確定したレイアウトは
        バンドルの来歴メタデータへ記録される。

    Returns
    -------
    PipelineResult
        Processed image and written output paths.
        処理済み画像と書き込まれた出力パス。

    Raises
    ------
    ValueError
        If `params` fails `validate_params`; the message lists every problem.
        `params` が `validate_params` に通らない場合。メッセージに全問題を
        列挙する。
    Exception
        Any stage or I/O failure propagates unchanged; batch callers decide
        whether to continue with remaining files.
        ステージ・入出力の失敗はそのまま送出する。バッチ続行の判断は
        呼び出し側が行う。
    """
    t0 = time.time()

    # Reject invalid parameters before any file I/O or stage construction.
    # ファイル入出力やステージ構築の前に不正パラメータを拒否する。
    problems = validate_params(params)
    if problems:
        raise ValueError(
            "Invalid analysis parameters:\n- " + "\n- ".join(problems)
        )

    if stages is None:
        stages = build_stages(params)

    def report(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    report("load")
    # Resolve the text layout once, load with it, and keep it for provenance.
    # テキストレイアウトを一度確定し、それで読み込み、来歴記録用に保持する。
    text_format = detect_afm_format(txt_path, fmt=input_format)
    height_data = load_afm_text(txt_path, fmt=text_format)
    name = os.path.splitext(os.path.basename(txt_path))[0]
    image = ProcessedImage(original_AFM=height_data, name=name)

    report("bg")
    stages.bg_calibrator(image)

    report("binarize")
    stages.segmenter(image)

    report("skeletonize")
    stages.skeletonizer(image)

    report("kink")
    stages.kink_detector(image)

    report("save")
    if output_dir is None:
        stem = os.path.splitext(txt_path)[0]
    else:
        stem = os.path.join(output_dir, name)

    # Store point coordinate pairs as shape (2, N) arrays for GUI04.
    # GUI04 用に座標ペアを shape (2, N) 配列として保存する。
    kp_x, kp_y = image.all_kink_coordinates
    dp_x, dp_y = image.decomposed_point_coordinates

    arrays = {
        "calibrated":   image.calibrated_image,
        "binarized":    image.binarized_image,
        "skeletonized": image.skeleton_image,
        "bp":           image.bp,                        # Branch-point mask.
        "ep":           image.ep,                        # End-point mask.
        "kp":           np.stack([kp_x, kp_y]),          # Kink coordinates, shape (2, N).
        "dp":           np.stack([dp_x, dp_y]),          # Decomposed-point coordinates, shape (2, N).
        "ka":           image.all_kink_angles,           # Kink angles in radians.
    }

    # Optionally bundle the raw original AFM height image. When included,
    # the .b2z is self-contained (no dependency on the source .txt) and can
    # serve as a fast-loading input for downstream machine-learning GUIs.
    # 任意で元の AFM 高さ画像を同梱する。同梱すると .b2z は .txt に依存せず
    # 自己完結し、下流の機械学習用 GUI の高速読み込み入力としても使える。
    if save_original:
        arrays["original"] = height_data

    # Enforce the bundle contract at write time. A violation here is a bug in
    # the pipeline itself, so fail loudly instead of saving a malformed bundle
    # that downstream GUIs would only reject much later.
    # 書き込み時点でバンドル契約を強制する。ここでの違反はパイプライン自体の
    # バグなので、不正なバンドルを保存してしまい下流 GUI で初めて発覚する
    # 事態を避け、即座に失敗させる。
    problems = validate_bundle(arrays, require=REQUIRED_BUNDLE_KEYS)
    if problems:
        raise ValueError(
            "bundle contract violation before save: " + "; ".join(problems)
        )

    params_dict = asdict(params)
    # Provenance metadata: records which input was processed, by which
    # software release, and when, so a bundle's origin can be verified
    # afterwards. "version" is the bundle FORMAT version, distinct from
    # "software_version" (the application release). Readers must treat the
    # provenance keys as optional — bundles written by older releases lack them.
    # 来歴メタデータ: どの入力を・どのリリースのソフトで・いつ処理したかを
    # 記録し、バンドルの由来を事後検証できるようにする。"version" はバンドル
    # 形式のバージョンであり、"software_version"（アプリのリリース）とは別物。
    # 旧リリースが書いたバンドルには来歴キーが無いため、読み取り側は任意
    # キーとして扱うこと。
    vlmeta = {
        "params":           params_dict,          # Analysis parameters for reproducibility.
        "version":          BUNDLE_FORMAT_VERSION,  # Bundle format version.
        "software_version": __version__,
        "input_file":       os.path.basename(txt_path),
        "input_sha256":     _sha256_of_file(txt_path),
        "created_utc":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # How the input text was parsed (kind/skiprows/n_cols/encoding), so a
        # suspected layout mis-detection can be audited after the fact.
        # 入力テキストの解釈方法（種別・スキップ行数・列数・エンコーディング）。
        # レイアウト誤判定が疑われた際に事後監査できるようにする。
        "input_format":     asdict(text_format),
    }

    bundle_path = bundle_path_for(stem)
    save_bundle(bundle_path, arrays, vlmeta=vlmeta)

    # Keep analysis parameters as sidecar JSON because it is easy to inspect by hand.
    # 解析パラメータは手で確認しやすいよう、サイドカー JSON としても保存する。
    param_path = param_path_for(stem)
    with open(param_path, "w", encoding="utf-8") as f:
        json.dump(params_dict, f, ensure_ascii=False, indent=2)

    return PipelineResult(
        image=image,
        bundle_path=bundle_path,
        param_path=param_path,
        elapsed_s=time.time() - t0,
    )
