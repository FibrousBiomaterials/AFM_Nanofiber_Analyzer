# -*- coding: utf-8 -*-
"""
GUI-independent fiber measurement on GUI01 ``.b2z`` bundles.
GUI01 の ``.b2z`` バンドルに対する GUI 非依存のファイバー計測モジュール。

This module owns the measurement-side responsibilities that were previously
embedded in GUI03 and GUI04: rebuilding `FiberTrackingImage` objects from a
bundle, computing per-fiber summary statistics, collecting skeleton-pixel
heights, and writing the result CSV files.
GUI03 と GUI04 に埋め込まれていた計測側の責務（バンドルからの
`FiberTrackingImage` 再構築、ファイバーごとの要約統計、スケルトン画素高さの
収集、結果 CSV の書き出し）をこのモジュールが持つ。

GUI04 and the `measure` command both call `measure_bundle` and
`write_fiber_csv`, so a complete, unfiltered GUI04 export matches the CLI for
the same bundle and scale. When GUI04's height filter is active, it deliberately
exports statistics for only the retained fiber portions. GUI03 and the
`heights` command share `skeleton_height_values`.
GUI04 と `measure` コマンドは `measure_bundle` と `write_fiber_csv` を共有するため、
GUI04 で全件をフィルターなしに出力すれば、同じバンドルとスケールに対する CLI
出力と一致する。GUI04 の高さフィルターが有効な場合は、意図どおり残った
ファイバー部分だけの統計を出力する。GUI03 と `heights` コマンドは
`skeleton_height_values` を共有する。

Like `lib.pipeline`, this module reports errors as fixed English strings and
keeps gettext out of the analysis layer; callers translate as needed.
`lib.pipeline` と同様、エラーは固定の英語文字列で返し、解析層に gettext を
持ち込まない。翻訳は呼び出し側で行う。

Notes
-----
When a bundle records the physical scan size (``spatial_calibration`` vlmeta,
populated from the instrument header or a manual/manifest value at processing
time), `measure_bundle` defaults `scale_um` to that recorded value, so
length and distance results are reproducible from the bundle alone. Callers
may still pass `scale_um` explicitly, and must do so for older bundles that
predate the scan-size contract.
バンドルが物理走査範囲（``spatial_calibration`` vlmeta。処理時に装置ヘッダ
または手入力／マニフェスト値から設定される）を記録していれば、
`measure_bundle` は `scale_um` をその記録値で既定化するため、長さ・距離の
結果がバンドル単体で再現できる。呼び出し側は `scale_um` を明示指定もでき、
走査範囲契約より前のバンドルでは明示指定が必須となる。
"""

# ===== Standard library =====
import csv
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ===== Numerical / scientific libraries =====
import numpy as np

# ===== Project libraries =====
from .blosc2_io import load_bundle, load_bundle_meta
# The key contract and validation are owned by bundle_schema; TRACKING_BUNDLE_KEYS
# is re-imported here so existing `measure.TRACKING_BUNDLE_KEYS` users keep working.
# キー契約と検証は bundle_schema が管理する。既存の
# `measure.TRACKING_BUNDLE_KEYS` 利用側が動き続けるよう、ここで再インポートする。
from .bundle_schema import (
    TRACKING_BUNDLE_KEYS,
    scan_size_um_from_meta,
    validate_bundle,
)
from .fiber import Fiber
from .fiber_tracking_image import FiberTrackingImage

# Column order of the per-fiber statistics CSV. This is the single source of
# truth shared by the GUI04 export and the `cli.py measure` subcommand.
# ファイバー統計 CSV の列順。GUI04 のエクスポートと `cli.py measure` が共有する
# 唯一の定義源。
FIBER_CSV_COLUMNS = (
    "index", "length_nm", "height_median_nm", "height_max_nm",
    "ep_count", "kink_count", "kink_angles_deg",
)


@dataclass(frozen=True)
class FiberStats:
    """
    Summary statistics for one traced fiber.
    追跡された 1 本のファイバーの要約統計値。

    Attributes
    ----------
    index
        Zero-based fiber index within the source list.
        元リスト内での 0 始まりのファイバー番号。
    length_nm
        Total fiber length along the skeleton path in nanometers.
        骨格線に沿ったファイバー全長 (nm)。
    height_median_nm
        Median height over the skeleton path in nanometers. 0.0 when the
        fiber has no height samples.
        骨格線上の高さ中央値 (nm)。高さサンプルが無い場合は 0.0。
    height_max_nm
        Maximum height over the skeleton path in nanometers. 0.0 when the
        fiber has no height samples.
        骨格線上の高さ最大値 (nm)。高さサンプルが無い場合は 0.0。
    ep_count
        Number of endpoints detected on this fiber.
        このファイバーで検出された端点の数。
    kink_count
        Number of kink points detected on this fiber.
        このファイバーで検出されたキンク点の数。
    kink_angles_deg
        Kink interior angles converted to degrees, in track order.
        The bundle stores angles in radians (`ka` key); the conversion to
        degrees happens here so every consumer reports the same unit.
        追跡順に並んだキンク内角（度）。バンドルは角度をラジアン（`ka` キー）で
        保存しているため、度への変換をここで一元化し、全ての利用側が同じ単位で
        出力する。
    """

    index: int
    length_nm: float
    height_median_nm: float
    height_max_nm: float
    ep_count: int
    kink_count: int
    kink_angles_deg: Tuple[float, ...]


@dataclass(frozen=True)
class MeasureResult:
    """
    Result of measuring one ``.b2z`` bundle.
    1 つの ``.b2z`` バンドルを計測した結果。

    Attributes
    ----------
    image
        Rebuilt tracking container with `size_per_pixel` resolved.
        `size_per_pixel` を確定済みの再構築済み追跡コンテナ。
    fibers
        Traced fibers in stable component order.
        安定した連結成分順のファイバーリスト。
    stats
        Per-fiber statistics aligned with `fibers` by index.
        `fibers` とインデックスで対応するファイバーごとの統計値。
    """

    image: FiberTrackingImage
    fibers: List[Fiber]
    stats: List[FiberStats]


def compute_fiber_stats(fibers: Sequence[Fiber]) -> List[FiberStats]:
    """
    Compute summary statistics for each fiber.
    各ファイバーの要約統計値を計算する。

    Parameters
    ----------
    fibers
        Fibers produced by `FiberTrackingImage`.
        `FiberTrackingImage` が生成したファイバー列。

    Returns
    -------
    list of FiberStats
        One entry per input fiber, in the same order.
        入力ファイバーと同順の統計値リスト。
    """
    stats = []
    for i, f in enumerate(fibers):
        med = float(np.median(f.height)) if len(f.height) > 0 else 0.0
        mx = float(np.max(f.height)) if len(f.height) > 0 else 0.0
        angles = tuple(float(np.degrees(a)) for a in f.kink_angles)
        stats.append(FiberStats(
            index=i,
            length_nm=float(f.length),
            height_median_nm=med,
            height_max_nm=mx,
            ep_count=len(f.ep_indices),
            kink_count=len(f.kink_indices),
            kink_angles_deg=angles,
        ))
    return stats


def _load_validated_arrays(bundle_path: str, keys: List[str]) -> Dict[str, np.ndarray]:
    """
    Load bundle keys and enforce the ``.b2z`` contract before use.
    バンドルキーを読み込み、使用前に ``.b2z`` 契約を強制する。

    Validation here converts malformed bundles into one clear error at the
    load boundary instead of cryptic NumPy failures inside fiber tracking.
    The format version recorded in vlmeta is checked as well, so bundles
    written by an incompatible future release are rejected explicitly.
    ここで検証することで、不正なバンドルはファイバー追跡内部での不可解な
    NumPy エラーではなく、読み込み境界での明確なエラー 1 件になる。vlmeta に
    記録された形式バージョンも照合し、非互換な将来リリースが書いたバンドルを
    明示的に拒否する。

    Raises
    ------
    ValueError
        If the loaded arrays or the recorded format version violate the
        bundle contract, or if the bundle metadata cannot be read.
    """
    arrays = load_bundle(bundle_path, keys=keys)
    # A bundle without metadata legitimately yields an empty dict (bundles
    # from old releases lack vlmeta). A read failure here means corruption,
    # so it becomes a loud contract error instead of silently skipping the
    # format-version check.
    # メタデータの無いバンドル（旧リリース製）は正常に空辞書になる。ここでの
    # 読み込み失敗は破損を意味するため、形式バージョン検査を黙ってスキップ
    # せず、明示的な契約エラーにする。
    try:
        meta = load_bundle_meta(bundle_path)
    except Exception as e:
        raise ValueError(
            f"unreadable bundle metadata in {os.path.basename(bundle_path)}: "
            f"{type(e).__name__}: {e}"
        ) from e
    problems = validate_bundle(arrays, meta=meta, require=keys)
    if problems:
        raise ValueError(
            f"bundle contract violation in {os.path.basename(bundle_path)}: "
            + "; ".join(problems)
        )
    return arrays


def _tracking_image_from_arrays(
    name: str,
    data: Dict[str, np.ndarray],
    size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
) -> FiberTrackingImage:
    """
    Assemble a `FiberTrackingImage` from already-loaded bundle arrays.
    読み込み済みのバンドル配列から `FiberTrackingImage` を組み立てる。

    Used by both `load_tracking_image` and `measure_bundle` so the bundle is
    read from disk only once per call path. ``size_per_pixel`` is the X (column)
    pixel size; ``y_size_per_pixel`` is the Y (row) pixel size and defaults to
    the X value for an isotropic (square-pixel) scale.
    `load_tracking_image` と `measure_bundle` の両方から使い、各呼び出し経路で
    バンドルのディスク読み込みを 1 回に抑える。``size_per_pixel`` は X（列）軸、
    ``y_size_per_pixel`` は Y（行）軸のピクセルサイズで、省略時は X 値を流用して
    等方（正方ピクセル）スケールとする。
    """
    cal = data["calibrated"]
    skl = data["skeletonized"].astype(np.uint8)
    bp = data["bp"].astype(np.uint8)
    ep = data["ep"].astype(np.uint8)
    kp = data["kp"]   # shape (2, N)
    dp = data["dp"]   # shape (2, N)
    ka = data["ka"]   # shape (N,), radians

    image = FiberTrackingImage(
        original_AFM=cal,
        name=name,
        size_per_pixel=size_per_pixel,
        y_size_per_pixel=y_size_per_pixel,
    )
    # Assign GUI01 analysis outputs directly; no lib processing module is rerun.
    # GUI01 の解析結果を属性へ直接代入する。lib の処理モジュールは再実行しない。
    image.calibrated_image = cal
    image.skeleton_image = skl
    image.bp = bp
    image.ep = ep
    image.all_kink_coordinates = (kp[0], kp[1])
    image.decomposed_point_coordinates = dp
    image.all_kink_angles = ka
    return image


def load_tracking_image(
    bundle_path: str,
    size_per_pixel: float,
    y_size_per_pixel: Optional[float] = None,
) -> FiberTrackingImage:
    """
    Rebuild a `FiberTrackingImage` from a GUI01 ``.b2z`` bundle.
    GUI01 が保存した ``.b2z`` バンドルから `FiberTrackingImage` を再構築する。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。
    size_per_pixel
        Physical X (column) pixel size in nanometers used for fiber-length
        calculations.
        ファイバー長さ計算に使う X（列）軸の物理ピクセルサイズ (nm/px)。
    y_size_per_pixel
        Physical Y (row) pixel size in nanometers. ``None`` reuses
        ``size_per_pixel`` for an isotropic (square-pixel) scale.
        Y（行）軸の物理ピクセルサイズ (nm/px)。``None`` のときは
        ``size_per_pixel`` を流用し等方（正方ピクセル）スケールとする。

    Returns
    -------
    FiberTrackingImage
        Reconstructed object populated with GUI01 analysis outputs.
        GUI01 の解析結果を設定した再構築済みオブジェクト。

    Raises
    ------
    ValueError
        If the bundle violates the ``.b2z`` contract (see
        `lib.bundle_schema.validate_bundle`).
    """
    # Load all required bundle keys in one call so the dataset is reconstructed atomically.
    # データセットを一貫して再構築できるよう、必要キーを 1 回でまとめて読み込む。
    data = _load_validated_arrays(bundle_path, TRACKING_BUNDLE_KEYS)
    name = os.path.splitext(os.path.basename(bundle_path))[0]
    return _tracking_image_from_arrays(name, data, size_per_pixel, y_size_per_pixel)


def read_scan_size_from_bundle(
    bundle_path: str,
) -> Optional[Tuple[float, float]]:
    """
    Read the recorded scan size ``(x_um, y_um)`` from a bundle, if present.
    バンドルに記録された走査範囲 ``(x_um, y_um)`` を読み取る（記録があれば）。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。

    Returns
    -------
    tuple of float or None
        Per-axis scan size in micrometers, or ``None`` when the bundle stores
        no valid spatial calibration (e.g. bundles written before the scan
        size was added to the contract).
        軸ごとの走査範囲 (µm)。有効な空間較正が無ければ ``None``（走査範囲が
        契約へ追加される前に書かれたバンドル等）。
    """
    return scan_size_um_from_meta(load_bundle_meta(bundle_path))


def measure_bundle(
    bundle_path: str,
    scale_um: Optional[float] = None,
    max_workers: Optional[int] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    scale_y_um: Optional[float] = None,
) -> MeasureResult:
    """
    Trace all fibers in one bundle and compute their statistics.
    1 つのバンドル内の全ファイバーを追跡し、統計値を計算する。

    Parameters
    ----------
    bundle_path
        Path to the ``.b2z`` bundle file.
        ``.b2z`` バンドルファイルのパス。
    scale_um
        Full physical width of the raw scan along the X (column) axis in
        micrometers. The X pixel size is ``scale_um * 1000 / (width_px + 1)``
        because the analysis arrays are cropped by one column relative to the
        raw scan (see the pixel-size note in the function body). When
        ``None``, the scan size recorded in the bundle
        (``spatial_calibration``) supplies both axes. A ``ValueError`` is
        raised if neither an explicit value nor a recorded scan size is
        available.
        X（列）軸方向の生スキャン全体の物理幅 (µm)。解析配列は生スキャンより
        1 列クロップされているため、X のピクセルサイズは
        ``scale_um * 1000 / (横px + 1)``（関数本体のピクセルサイズ注記参照）。
        ``None`` のときはバンドルに記録された走査範囲
        （``spatial_calibration``）が両軸を供給する。明示値も記録値も
        無い場合は ``ValueError`` を送出する。
    max_workers
        Maximum number of worker threads for parallel fiber tracing.
        並列ファイバー追跡に使うワーカースレッドの最大数。
    progress_cb
        Progress callback receiving ``(done, total)`` per traced fiber.
        ファイバー 1 本完了ごとに ``(done, total)`` を受け取る進捗コールバック。
    scale_y_um
        Full physical height of the raw scan along the Y (row) axis in
        micrometers. The Y pixel size is
        ``scale_y_um * 1000 / (height_px + 1)``, mirroring the one-row crop
        of the analysis arrays. When ``None`` it defaults to the recorded Y
        scan size (if ``scale_um`` is also ``None``) or to ``scale_um``
        otherwise, keeping the historical single-value (square-scan)
        behavior. Pass a distinct value for rectangular scans.
        Y（行）軸方向の生スキャン全体の物理高さ (µm)。解析配列の 1 行クロップに
        対応して、Y のピクセルサイズは ``scale_y_um * 1000 / (縦px + 1)``。
        ``None`` のときは（``scale_um`` も
        ``None`` なら）記録された Y 走査範囲、そうでなければ ``scale_um`` を
        既定値とし、従来の単一値（正方スキャン）挙動を保つ。矩形スキャンでは
        別の値を渡す。

    Returns
    -------
    MeasureResult
        Rebuilt image, traced fibers, and per-fiber statistics.
        再構築済み画像、追跡されたファイバー、ファイバーごとの統計値。

    Raises
    ------
    ValueError
        If `scale_um` is ``None`` and the bundle records no scan size, if a
        resolved scale is not a positive number, or if the bundle violates
        the ``.b2z`` contract (see `lib.bundle_schema.validate_bundle`).

    Notes
    -----
    Pixel size is resolved per axis (X from image width, Y from image height)
    so rectangular fields of view and non-square pixel grids are measured
    correctly. Square scans on square pixel grids are unchanged.
    ピクセルサイズは軸ごと（X は画像の幅、Y は画像の高さ）に解決するため、
    矩形視野や非正方ピクセル格子も正しく測れる。正方ピクセル格子の正方スキャンの
    結果は変わらない。
    """
    if scale_um is None:
        recorded = read_scan_size_from_bundle(bundle_path)
        if recorded is None:
            raise ValueError(
                "scale_um is None and the bundle records no scan size; "
                "pass scale_um explicitly or re-process the input so its "
                "scan size is stored in the bundle"
            )
        scale_um = recorded[0]
        if scale_y_um is None:
            scale_y_um = recorded[1]

    # A single value means a square scan, so Y reuses the X scale.
    # 単一値は正方スキャンを意味するため、Y は X のスケールを流用する。
    if scale_y_um is None:
        scale_y_um = scale_um

    if not (scale_um > 0):
        raise ValueError(f"scale_um must be a positive number, got {scale_um!r}")
    if not (scale_y_um > 0):
        raise ValueError(
            f"scale_y_um must be a positive number, got {scale_y_um!r}"
        )

    data = _load_validated_arrays(bundle_path, TRACKING_BUNDLE_KEYS)
    height_px, width_px = data["calibrated"].shape
    # Per-axis pixel size: X spans the columns (width), Y spans the rows
    # (height), matching the bundle coordinate convention (x=column, y=row).
    # The scan size describes the raw scan, but BGCalibrator crops every
    # analysis array by one row and one column (``original[1:, 1:]``), so the
    # raw pixel count is the bundle shape plus one. Dividing by the cropped
    # shape would inflate every length by width/(width-1) (~0.2% at 512 px).
    # 軸別ピクセルサイズ：X は列（幅）、Y は行（高さ）に対応し、バンドルの
    # 座標規約（x=列, y=行）に一致する。走査範囲は生スキャン全体の寸法だが、
    # BGCalibrator は解析配列を 1 行・1 列クロップする（``original[1:, 1:]``）
    # ため、生スキャンの画素数はバンドル形状 +1 になる。クロップ後の形状で
    # 割ると全長さが width/(width-1) 倍（512 px で約 +0.2%）に膨らむ。
    x_size_per_pixel = scale_um * 1000.0 / (width_px + 1)
    y_size_per_pixel = scale_y_um * 1000.0 / (height_px + 1)

    name = os.path.splitext(os.path.basename(bundle_path))[0]
    image = _tracking_image_from_arrays(
        name, data, x_size_per_pixel, y_size_per_pixel,
    )
    fibers = image.fibers_in_image_parallel(
        max_workers=max_workers,
        progress_cb=progress_cb,
    )
    return MeasureResult(image=image, fibers=fibers, stats=compute_fiber_stats(fibers))


def write_fiber_csv(path: str, stats: Sequence[FiberStats]) -> None:
    """
    Write per-fiber statistics to a CSV file.
    ファイバーごとの統計値を CSV ファイルへ書き出す。

    Parameters
    ----------
    path
        Output CSV path. The file is overwritten if it exists.
        出力 CSV パス。既存ファイルは上書きされる。
    stats
        Statistics rows, typically from `compute_fiber_stats`.
        統計値の行。通常は `compute_fiber_stats` の戻り値。

    Notes
    -----
    The encoding is UTF-8 with BOM (`utf-8-sig`) so Excel on Japanese Windows
    opens the file without mojibake.
    エンコーディングは BOM 付き UTF-8（`utf-8-sig`）とし、日本語 Windows の
    Excel で文字化けせずに開けるようにする。
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(list(FIBER_CSV_COLUMNS))
        for s in stats:
            writer.writerow([
                s.index,
                f"{s.length_nm:.1f}",
                f"{s.height_median_nm:.3f}",
                f"{s.height_max_nm:.3f}",
                s.ep_count,
                s.kink_count,
                ";".join(f"{a:.1f}" for a in s.kink_angles_deg),
            ])


def all_pixel_height(calimage_list, sklimage_list):
    """
    Collect calibrated height values at skeletonized fiber pixels.
    細線化された繊維画素位置の補正済み高さ値を収集する。

    Parameters
    ----------
    calimage_list
        Calibrated AFM height images whose values are sampled.
        サンプリング対象となる補正済み AFM 高さ画像。
    sklimage_list
        Skeletonized masks; nonzero pixels mark fiber centerlines.
        非ゼロ画素が繊維中心線を表す細線化マスク。

    Returns
    -------
    list
        Height values sampled from the calibrated images.
        補正済み画像からサンプリングされた高さ値。

    Notes
    -----
    The sampled values come from calibrated images, not from the raw AFM input.
    サンプリング値は元の AFM 入力ではなく、補正済み画像から取得する。
    """
    all_height = []
    for calimage, sklimage in zip(calimage_list, sklimage_list):
        all_height.extend(calimage[np.where(sklimage)])
    return all_height


def skeleton_height_values(
    bundle_paths: Sequence[str],
) -> Tuple[np.ndarray, List[Tuple[str, str]]]:
    """
    Collect skeleton-pixel heights from multiple ``.b2z`` bundles.
    複数の ``.b2z`` バンドルからスケルトン画素の高さ値を収集する。

    Parameters
    ----------
    bundle_paths
        Paths to ``.b2z`` bundles containing ``calibrated`` and
        ``skeletonized`` keys.
        ``calibrated`` と ``skeletonized`` キーを含む ``.b2z`` バンドルのパス。

    Returns
    -------
    tuple
        ``(heights, errors)``. `heights` is a 1D float array of all collected
        height values in nanometers; `errors` lists ``(bundle_path, message)``
        pairs for bundles that failed to load, with fixed English messages.
        ``(heights, errors)``。`heights` は収集した全高さ値 (nm) の 1 次元
        float 配列。`errors` は読み込みに失敗したバンドルの
        ``(バンドルパス, メッセージ)`` ペアのリストで、メッセージは固定の
        英語文字列。

    Notes
    -----
    A load failure in one bundle does not abort the collection; remaining
    bundles are still processed so grouped GUI runs degrade gracefully.
    1 つのバンドルの読み込み失敗で収集全体は中断しない。残りのバンドルは
    処理を続け、グループ実行が部分的な失敗に耐えられるようにする。
    """
    heights: List[float] = []
    errors: List[Tuple[str, str]] = []
    for path in bundle_paths:
        try:
            # Contract validation included: a malformed bundle becomes an
            # error entry here instead of corrupting the pooled heights.
            # 契約検証込み。不正なバンドルは集約高さ値を汚染せず、ここで
            # エラー項目になる。
            bundle = _load_validated_arrays(path, ["calibrated", "skeletonized"])
        except Exception as e:
            errors.append((path, f"{type(e).__name__}: {e}"))
            continue
        heights.extend(
            all_pixel_height([bundle["calibrated"]], [bundle["skeletonized"]])
        )
    return np.asarray(heights, dtype=float), errors


def write_heights_csv(
    path: str,
    per_bundle: Sequence[Tuple[str, np.ndarray]],
) -> None:
    """
    Write skeleton-pixel heights to a long-format CSV file.
    スケルトン画素の高さ値を縦持ち形式の CSV ファイルへ書き出す。

    Parameters
    ----------
    path
        Output CSV path. The file is overwritten if it exists.
        出力 CSV パス。既存ファイルは上書きされる。
    per_bundle
        ``(bundle_name, heights)`` pairs; one output row is written per
        height value so external tools can regroup and re-bin freely.
        ``(バンドル名, 高さ配列)`` のペア列。高さ値 1 つにつき 1 行を書き出し、
        外部ツールで自由に再グループ化・再ビニングできるようにする。
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["bundle", "height_nm"])
        for name, heights in per_bundle:
            for h in np.asarray(heights, dtype=float):
                writer.writerow([name, f"{h:.6g}"])
