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
import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Callable, Dict, List, Optional, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .afm_io import load_afm_text
from .bg_calibrator_shimadzu import BG_Calibrator_shimadzu
from .blosc2_io import save_bundle, bundle_has_keys, BUNDLE_EXT
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

    # BG_Calibrator_shimadzu parameters.
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

# Fixed English stage keys reported through the `on_stage` callback, in order.
# These are internal identifiers, not user-visible text; do not translate them.
# `on_stage` コールバックへ順に通知される固定の英語ステージキー。
# 内部識別子でありユーザー表示文字列ではないため翻訳しない。
STAGE_KEYS = ("load", "bg", "binarize", "skeletonize", "kink", "save")


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

    bg_calibrator: BG_Calibrator_shimadzu
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
    bg_calibrator = BG_Calibrator_shimadzu(
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

    Returns
    -------
    PipelineResult
        Processed image and written output paths.
        処理済み画像と書き込まれた出力パス。

    Raises
    ------
    Exception
        Any stage or I/O failure propagates unchanged; batch callers decide
        whether to continue with remaining files.
        ステージ・入出力の失敗はそのまま送出する。バッチ続行の判断は
        呼び出し側が行う。
    """
    t0 = time.time()
    if stages is None:
        stages = build_stages(params)

    def report(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    report("load")
    height_data = load_afm_text(txt_path)
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

    params_dict = asdict(params)
    vlmeta = {
        "params":  params_dict,                  # Analysis parameters for reproducibility.
        "version": "1.0",
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
