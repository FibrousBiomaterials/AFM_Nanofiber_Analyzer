# -*- coding: utf-8 -*-
"""
Tests for lib/measure.py using the synthetic bent-fiber image.
合成の折れ繊維画像を用いた lib/measure.py のテスト。

Like test_pipeline.py, these tests assert physically self-evident properties
of the synthetic input (one fiber, drawn length, drawn height, one kink at the
drawn bend) so they stay valid when algorithm details are tuned.
test_pipeline.py と同様、合成入力の物理的に自明な性質（繊維 1 本・描画した
長さと高さ・描いた折れ目にキンク 1 点）を検証するため、アルゴリズムの調整後も
成立し続ける。

The CSV identity test additionally guarantees that `cli.py measure` and the
GUI04 export path produce byte-identical files, because both call
`lib.measure.write_fiber_csv`.
CSV 同一性テストは、`cli.py measure` と GUI04 のエクスポート経路がともに
`lib.measure.write_fiber_csv` を呼ぶことで、バイト単位で同一のファイルを
出力することを保証する。
"""

import csv
import os

import numpy as np
import pytest

import cli
from lib import imp_tools
from lib.blosc2_io import load_bundle, save_bundle
from lib.bundle_schema import BUNDLE_FORMAT_VERSION
from lib.fiber_tracking_image import FiberTrackingImage
from lib.measure import (
    FIBER_CSV_COLUMNS,
    compute_fiber_stats,
    load_tracking_image,
    measure_bundle,
    skeleton_height_values,
    write_fiber_csv,
    write_heights_csv,
)
from lib.pipeline import ProcParams, process_file
from tests.conftest import write_synthetic_fiber_txt

# tophat keeps the test fast; physical assertions do not depend on bg_method.
# 高速な tophat を使う。物理的な検証内容は bg_method に依存しない。
FAST_PARAMS = ProcParams(bg_method="tophat")

# The scan size refers to the raw 192x192 scan; the calibrator trims the
# analysis arrays to 191x191 and measure_bundle divides by the raw pixel
# count (bundle shape + 1), so scale_um=1.92 gives an exact pixel size of
# 10 nm/px and keeps length assertions easy to read.
# 走査範囲は生の 192x192 スキャンに対する寸法。補正器は解析配列を 191x191 に
# トリミングし、measure_bundle は生スキャンの画素数（バンドル形状 +1）で
# 割るため、scale_um=1.92 でピクセルサイズがちょうど 10 nm/px になり、
# 長さの検証式が読みやすくなる。
SCALE_UM = 1.92
EXPECTED_SIZE_PER_PIXEL = 10.0

# Corrected chain-code step weights used by convert_track_to_distance
# (Kulpa 1977; Vossepoel & Smeulders 1982). Pinned here so an accidental
# change to the documented constants fails these tests.
# convert_track_to_distance が使う補正済みチェーンコード重み
# (Kulpa 1977; Vossepoel & Smeulders 1982)。文書化された定数が誤って変わったら
# テストが失敗するよう、ここに値を固定する。
STEP_ORTHOGONAL = 0.948
STEP_DIAGONAL = 1.340


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    """
    Run pipeline + measurement once and share across this module's tests.
    パイプラインと計測を 1 回だけ実行し、本モジュールのテストで共有する。
    """
    tmp_path = tmp_path_factory.mktemp("measure")
    txt = write_synthetic_fiber_txt(tmp_path)
    out_dir = os.path.join(tmp_path, "out")
    os.makedirs(out_dir)
    pipeline_result = process_file(txt, FAST_PARAMS, output_dir=out_dir)
    result = measure_bundle(pipeline_result.bundle_path, scale_um=SCALE_UM)
    return pipeline_result.bundle_path, result


def test_pixel_size_follows_gui04_convention(measured):
    """size_per_pixel is scale_nm divided by the raw scan pixel count."""
    _bundle_path, result = measured
    assert result.image.size_per_pixel == pytest.approx(EXPECTED_SIZE_PER_PIXEL)


def test_single_fiber_with_drawn_geometry(measured):
    """The synthetic image yields one fiber with the drawn length and features."""
    _bundle_path, result = measured
    assert len(result.fibers) == 1
    assert len(result.stats) == 1
    s = result.stats[0]

    # The drawn pixel path is ~173 px (axis steps plus diagonal steps), i.e.
    # ~1730 nm naive at 10 nm/px, or ~1640 nm after the chain-code length
    # correction (~x0.948); skeleton end erosion shortens it slightly.
    # 描画した画素経路は約 173 px（軸方向ステップ + 斜めステップ）で、
    # 10 nm/px なら素朴計算で約 1730 nm、チェーンコード長補正（約 x0.948）後は
    # 約 1640 nm。骨格端の侵食でわずかに短くなる。
    assert 1400.0 < s.length_nm < 1800.0

    # The fiber is drawn ~3 nm high; the median must sit near that value.
    # 繊維は高さ約 3 nm で描画されており、中央値はその近傍になるはず。
    assert s.height_median_nm == pytest.approx(3.0, abs=0.7)
    assert s.height_max_nm >= s.height_median_nm
    assert s.height_max_nm < 5.0

    # One unbranched fiber has exactly two endpoints and the one drawn kink.
    # 分岐のない繊維 1 本の端点はちょうど 2 つで、キンクは描いた 1 点のみ。
    assert s.ep_count == 2
    assert s.kink_count == 1
    assert len(s.kink_angles_deg) == 1
    assert s.kink_angles_deg[0] == pytest.approx(147.0, abs=8.0)


def test_stats_match_recomputation_from_fibers(measured):
    """compute_fiber_stats on the returned fibers reproduces result.stats."""
    _bundle_path, result = measured
    assert compute_fiber_stats(result.fibers) == result.stats


def test_load_tracking_image_matches_measure_bundle(measured):
    """The standalone loader rebuilds the same arrays measure_bundle used."""
    bundle_path, result = measured
    image = load_tracking_image(bundle_path, EXPECTED_SIZE_PER_PIXEL)
    np.testing.assert_array_equal(
        image.skeleton_image, result.image.skeleton_image
    )
    np.testing.assert_allclose(
        image.calibrated_image, result.image.calibrated_image
    )
    assert image.size_per_pixel == result.image.size_per_pixel


def test_tracking_rejects_non_two_endpoint_component():
    """A malformed skeleton component fails with a clear tracing error."""
    skeleton = np.zeros((8, 8), dtype=np.uint8)
    skeleton[2, 1:5] = 1
    skeleton[1:5, 3] = 1
    with pytest.raises(ValueError, match="exactly 2 endpoints"):
        imp_tools.tracking(skeleton)


def test_tracking_image_skips_untraceable_components():
    """One untraceable component does not discard traceable fibers."""
    skeleton = np.zeros((24, 24), dtype=np.uint8)
    skeleton[2, 2:16] = 1
    skeleton[10, 10:15] = 1
    skeleton[14, 10:15] = 1
    skeleton[10:15, 10] = 1
    skeleton[10:15, 14] = 1

    image = FiberTrackingImage(
        original_AFM=np.zeros_like(skeleton, dtype=float),
        name="mixed",
        size_per_pixel=1.0,
    )
    image.calibrated_image = np.ones_like(skeleton, dtype=float)
    image.skeleton_image = skeleton
    image.ep = imp_tools.endPoints(skeleton)
    image.all_kink_coordinates = (
        np.array([], dtype=np.int64),
        np.array([], dtype=np.int64),
    )
    image.decomposed_point_coordinates = np.zeros((2, 0), dtype=np.int64)
    image.all_kink_angles = np.array([], dtype=float)

    fibers = image.fibers_in_image_parallel(max_workers=1)
    assert len(fibers) == 1
    assert len(image.skipped_fiber_labels) == 1
    assert "exactly 2 endpoints" in image.skipped_fiber_labels[0][1]


def test_measure_bundle_rejects_invalid_scale(measured):
    """A non-positive scale must fail loudly instead of producing 0-nm output."""
    bundle_path, _result = measured
    with pytest.raises(ValueError):
        measure_bundle(bundle_path, scale_um=0.0)


def test_convert_track_to_distance_isotropic_corrected_weights():
    """Isotropic steps carry the Kulpa-corrected chain-code weights."""
    # Orthogonal steps count as 0.948 * pixel size (naive weight 1 would
    # overestimate digital curve length by ~5.5% on average).
    # 直交ステップは 0.948 × ピクセルサイズ（素朴な重み 1 はデジタル曲線長を
    # 平均約 5.5% 過大評価する）。
    horizon = imp_tools.convert_track_to_distance(
        np.array([0, 1, 2, 3]), np.array([0, 0, 0, 0]), 10.0
    )
    assert horizon[-1] == pytest.approx(3 * STEP_ORTHOGONAL * 10.0)
    # Diagonal steps count as 1.340 * pixel size (instead of sqrt(2)).
    # 斜めステップは sqrt(2) ではなく 1.340 × ピクセルサイズ。
    diag = imp_tools.convert_track_to_distance(
        np.array([0, 1, 2]), np.array([0, 1, 2]), 10.0
    )
    assert diag[-1] == pytest.approx(2 * STEP_DIAGONAL * 10.0)


def test_convert_track_to_distance_anisotropic():
    """Per-axis pixel sizes measure X, Y, and diagonal steps independently."""
    horiz = imp_tools.convert_track_to_distance(
        np.array([0, 1, 2, 3]), np.array([0, 0, 0, 0]), 10.0, 20.0
    )
    assert horiz[-1] == pytest.approx(3 * STEP_ORTHOGONAL * 10.0)  # X steps only
    vert = imp_tools.convert_track_to_distance(
        np.array([0, 0, 0, 0]), np.array([0, 1, 2, 3]), 10.0, 20.0
    )
    assert vert[-1] == pytest.approx(3 * STEP_ORTHOGONAL * 20.0)  # Y steps only
    # Anisotropic diagonal steps scale the Euclidean step by the same
    # correction factor as the isotropic case (1.340 / sqrt(2)).
    # 異方性の斜めステップは、等方の場合と同じ補正係数 (1.340 / sqrt(2)) を
    # ユークリッドステップ長に乗じる。
    diag = imp_tools.convert_track_to_distance(
        np.array([0, 1, 2]), np.array([0, 1, 2]), 10.0, 20.0
    )
    assert diag[-1] == pytest.approx(
        2 * (STEP_DIAGONAL / np.sqrt(2)) * np.hypot(10.0, 20.0)
    )


def test_measure_bundle_anisotropic_scale(measured):
    """A larger Y scale enlarges the Y pixel size and the measured lengths."""
    bundle_path, iso = measured
    aniso = measure_bundle(
        bundle_path, scale_um=SCALE_UM, scale_y_um=2 * SCALE_UM
    )
    # Square 191x191 grid: X pixel size unchanged, Y pixel size doubled.
    assert aniso.image.size_per_pixel == pytest.approx(EXPECTED_SIZE_PER_PIXEL)
    assert aniso.image.y_size_per_pixel == pytest.approx(
        2 * EXPECTED_SIZE_PER_PIXEL
    )
    # The fiber spans both axes, so a larger Y scale must lengthen it.
    assert aniso.stats[0].length_nm > iso.stats[0].length_nm


def test_measure_bundle_rejects_invalid_scale_y(measured):
    """A non-positive Y scale fails loudly like an invalid X scale."""
    bundle_path, _result = measured
    with pytest.raises(ValueError):
        measure_bundle(bundle_path, scale_um=SCALE_UM, scale_y_um=0.0)


# A 15-pixel (14-step) straight line traces reliably, unlike a very short one.
LINE_STEPS = 14


def _write_straight_line_bundle(path, shape, orientation):
    """
    Save a minimal valid bundle with one straight skeleton fiber.
    まっすぐな骨格ファイバー 1 本を持つ最小の有効バンドルを保存する。

    The fiber is a single 15-pixel line (``LINE_STEPS`` unit steps) along one
    axis, so its physical length is a closed-form ``LINE_STEPS *
    STEP_ORTHOGONAL * per_axis_pixel_size`` (orthogonal chain-code weight) —
    ideal for asserting per-axis pixel-size derivation on non-square arrays
    without pipeline noise.
    ファイバーは単一軸方向の 15 画素直線（``LINE_STEPS`` ステップ）で、物理長は
    ``LINE_STEPS * STEP_ORTHOGONAL * 軸別ピクセルサイズ``（直交チェーンコード
    重み）の閉形式になる。パイプライン由来のばらつき無しに非正方配列での
    軸別ピクセルサイズ導出を検証するのに適する。
    """
    skel = np.zeros(shape, np.uint8)
    ep = np.zeros(shape, np.uint8)
    if orientation == "horizontal":
        skel[5, 5:5 + LINE_STEPS + 1] = 1
        ep[5, 5] = ep[5, 5 + LINE_STEPS] = 1
    else:  # vertical
        skel[5:5 + LINE_STEPS + 1, 5] = 1
        ep[5, 5] = ep[5 + LINE_STEPS, 5] = 1
    arrays = {
        "calibrated":   np.ones(shape, np.float64),
        "binarized":    skel.astype(bool),
        "skeletonized": skel,
        "bp":           np.zeros(shape, np.uint8),
        "ep":           ep,
        "kp":           np.zeros((2, 0), np.int64),
        "dp":           np.zeros((2, 0), np.int64),
        "ka":           np.zeros((0,), np.float64),
    }
    save_bundle(path, arrays, vlmeta={"version": BUNDLE_FORMAT_VERSION})


def test_measure_bundle_non_square_horizontal_uses_width_scale(tmp_path):
    """On a tall (H>W) array, a horizontal fiber's length uses X = scale/width."""
    # 40 rows x 30 cols: the old max(H,W) convention would wrongly divide by 40.
    bundle = os.path.join(tmp_path, "h.b2z")
    _write_straight_line_bundle(bundle, shape=(40, 30), orientation="horizontal")

    result = measure_bundle(bundle, scale_um=3.1, scale_y_um=5.0)
    assert result.image.calibrated_image.shape == (40, 30)
    assert len(result.fibers) == 1
    # x_px = 3.1 um * 1000 / (30 + 1) raw cols = 100 nm/px;
    # 14 orthogonal steps -> 0.948 * 1400 nm.
    # The Y scale (5.0) must not affect a purely horizontal fiber.
    assert result.stats[0].length_nm == pytest.approx(
        STEP_ORTHOGONAL * 100.0 * LINE_STEPS
    )


def test_measure_bundle_non_square_vertical_uses_height_scale(tmp_path):
    """On a wide (W>H) array, a vertical fiber's length uses Y = scale/height."""
    bundle = os.path.join(tmp_path, "v.b2z")
    _write_straight_line_bundle(bundle, shape=(30, 40), orientation="vertical")

    result = measure_bundle(bundle, scale_um=5.0, scale_y_um=3.1)
    assert result.image.calibrated_image.shape == (30, 40)
    assert len(result.fibers) == 1
    # y_px = 3.1 um * 1000 / (30 + 1) raw rows = 100 nm/px;
    # 14 orthogonal steps -> 0.948 * 1400 nm.
    # The X scale (5.0) must not affect a purely vertical fiber.
    assert result.stats[0].length_nm == pytest.approx(
        STEP_ORTHOGONAL * 100.0 * LINE_STEPS
    )


def test_fiber_csv_schema_and_values(measured, tmp_path):
    """write_fiber_csv emits the documented columns with parseable values."""
    _bundle_path, result = measured
    csv_path = os.path.join(tmp_path, "fibers.csv")
    write_fiber_csv(csv_path, result.stats)

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(FIBER_CSV_COLUMNS)
    assert len(rows) == 1 + len(result.stats)

    row = rows[1]
    s = result.stats[0]
    assert int(row[0]) == s.index
    assert float(row[1]) == pytest.approx(s.length_nm, abs=0.1)
    assert float(row[2]) == pytest.approx(s.height_median_nm, abs=1e-3)
    assert int(row[4]) == s.ep_count
    assert int(row[5]) == s.kink_count
    # Angle list is semicolon-joined degrees with one decimal place.
    # 角度リストはセミコロン区切りの度数値（小数 1 桁）。
    assert float(row[6]) == pytest.approx(s.kink_angles_deg[0], abs=0.1)


def test_cli_measure_writes_identical_csv(measured, tmp_path):
    """`cli.py measure` output is byte-identical to write_fiber_csv output."""
    bundle_path, result = measured

    direct_path = os.path.join(tmp_path, "direct.csv")
    write_fiber_csv(direct_path, result.stats)

    out_dir = os.path.join(tmp_path, "cli_out")
    rc = cli.main([
        "measure", bundle_path,
        "--scale-um", str(SCALE_UM),
        "--output-dir", out_dir,
    ])
    assert rc == 0

    stem = os.path.splitext(os.path.basename(bundle_path))[0]
    cli_path = os.path.join(out_dir, stem + "_fibers.csv")
    assert os.path.isfile(cli_path)
    with open(direct_path, "rb") as fa, open(cli_path, "rb") as fb:
        assert fa.read() == fb.read()


def test_skeleton_height_values_counts_and_range(measured):
    """Collected heights cover every skeleton pixel and sit near 3 nm."""
    bundle_path, _result = measured
    heights, errors = skeleton_height_values([bundle_path])
    assert errors == []

    skeleton = load_bundle(bundle_path, keys=["skeletonized"])["skeletonized"]
    assert heights.size == int((skeleton > 0).sum())
    assert float(np.median(heights)) == pytest.approx(3.0, abs=0.7)


def test_skeleton_height_values_reports_missing_bundle(measured, tmp_path):
    """A missing bundle yields one error entry and no height values."""
    missing = os.path.join(tmp_path, "missing.b2z")
    heights, errors = skeleton_height_values([missing])
    assert heights.size == 0
    assert len(errors) == 1
    assert errors[0][0] == missing


def test_partial_failure_keeps_other_bundles(measured, tmp_path):
    """One unreadable bundle does not discard heights from readable ones."""
    bundle_path, _result = measured
    missing = os.path.join(tmp_path, "missing.b2z")
    heights, errors = skeleton_height_values([missing, bundle_path])
    assert heights.size > 0
    assert len(errors) == 1


def test_cli_heights_writes_long_format_csv(measured, tmp_path):
    """`cli.py heights` writes one row per skeleton pixel plus a header."""
    bundle_path, _result = measured
    out_csv = os.path.join(tmp_path, "heights.csv")
    rc = cli.main(["heights", bundle_path, "--output", out_csv])
    assert rc == 0

    heights, _errors = skeleton_height_values([bundle_path])
    with open(out_csv, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["bundle", "height_nm"]
    assert len(rows) == 1 + heights.size
    assert float(rows[1][1]) == pytest.approx(heights[0], rel=1e-4)


def test_write_heights_csv_groups_by_bundle_name(measured, tmp_path):
    """write_heights_csv labels each row with its source bundle name."""
    bundle_path, _result = measured
    heights, _errors = skeleton_height_values([bundle_path])
    out_csv = os.path.join(tmp_path, "grouped.csv")
    write_heights_csv(out_csv, [("a", heights[:3]), ("b", heights[:2])])

    with open(out_csv, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert [r[0] for r in rows[1:]] == ["a", "a", "a", "b", "b"]
