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
import shutil

import numpy as np
import pytest

import cli
from lib import imp_tools
from lib.blosc2_io import load_bundle, save_bundle
from lib.bundle_schema import BUNDLE_FORMAT_VERSION
from lib.fiber import Fiber
from lib.fiber_tracking_image import FiberTrackingImage
from lib.fiber_selection import exclusion_path_for, fiber_anchor, save_exclusions
from lib.measure import (
    FIBER_CSV_COLUMNS,
    FiberStats,
    FIBER_CSV_COLUMNS_V1,
    collect_fiber_curvature,
    collect_fiber_stats,
    collect_fiber_stats_from_csv,
    collect_skeleton_height_profiles,
    compute_fiber_stats,
    contour_length_weights,
    fiber_curvature_profile,
    fiber_kink_angle,
    fiber_kink_density,
    fiber_mean_curvature,
    fiber_straightness,
    isolated_fiber_flags,
    load_tracking_image,
    measure_bundle,
    read_fiber_csv,
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
    # The pixel size is passed because straightness needs it; measure_bundle
    # supplies the same values, so the recomputation must too.
    # 直線度がピクセルサイズを必要とするため引き渡す。measure_bundle も同じ値を
    # 与えているので、再計算側も渡さなければ一致しない。
    assert compute_fiber_stats(
        result.fibers,
        result.image.size_per_pixel,
        result.image.y_size_per_pixel,
    ) == result.stats


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
    # The ring must enclose more than DEFAULT_MAX_LOOP_AREA (100 px) so the
    # load-time loop collapsing keeps it intact and it still reaches tracking
    # as an endpoint-free, untraceable component.
    # リングの囲み面積は DEFAULT_MAX_LOOP_AREA (100 px) を超える必要がある。
    # 読み込み時のループ潰しで温存され、端点なしの追跡不能成分のまま
    # tracking に到達させるためである。
    skeleton[5, 5:20] = 1
    skeleton[19, 5:20] = 1
    skeleton[5:20, 5] = 1
    skeleton[5:20, 19] = 1

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


def test_collect_fiber_stats_matches_measure_bundle(measured):
    """Collecting one bundle reproduces the statistics measure_bundle returns."""
    bundle_path, result = measured
    per_bundle, errors = collect_fiber_stats([bundle_path], scale_um=SCALE_UM)
    assert errors == []
    assert len(per_bundle) == 1
    path, stats = per_bundle[0]
    assert path == bundle_path
    assert stats == result.stats


def test_collect_fiber_stats_keeps_bundles_separate(measured):
    """Each input path yields its own entry, so per-image aggregation is possible."""
    bundle_path, _result = measured
    per_bundle, errors = collect_fiber_stats(
        [bundle_path, bundle_path], scale_um=SCALE_UM,
    )
    assert errors == []
    assert len(per_bundle) == 2
    assert [len(stats) for _p, stats in per_bundle] == [1, 1]


def test_collect_fiber_stats_reports_bundle_without_scan_size(measured):
    """A bundle with no recorded scan size errors instead of raising."""
    bundle_path, _result = measured
    # The synthetic fixture is processed from a header-less text file, so the
    # bundle stores no scan size and the length scale cannot be resolved.
    # 合成データはヘッダの無いテキストから処理されるためバンドルに走査範囲が
    # 無く、長さのスケールを解決できない。
    per_bundle, errors = collect_fiber_stats([bundle_path])
    assert per_bundle == []
    assert len(errors) == 1
    assert errors[0][0] == bundle_path
    assert "scale_um" in errors[0][1]


def test_collect_fiber_stats_partial_failure(measured, tmp_path):
    """One unreadable bundle does not discard statistics from readable ones."""
    bundle_path, _result = measured
    missing = os.path.join(tmp_path, "missing.b2z")
    per_bundle, errors = collect_fiber_stats(
        [missing, bundle_path], scale_um=SCALE_UM,
    )
    assert len(per_bundle) == 1
    assert per_bundle[0][0] == bundle_path
    assert len(errors) == 1
    assert errors[0][0] == missing


def test_contour_length_weights_sum_to_fiber_length(measured):
    """Per-point weights add up to exactly the fiber's contour length."""
    _bundle_path, result = measured
    fiber = result.fibers[0]
    weights = contour_length_weights(fiber.horizon)
    assert weights.shape == fiber.height.shape
    assert float(weights.sum()) == pytest.approx(float(fiber.length))
    # Diagonal skeleton steps are longer than orthogonal ones, so equal
    # weights would be wrong; the spread is what length weighting corrects.
    # 斜めの骨格ステップは直交ステップより長いため、重みが一様では誤りになる。
    # このばらつきこそ長さ重み付けが補正する対象である。
    assert weights.max() > weights.min()


def test_contour_length_weights_single_point_fiber():
    """A one-point track represents no contour length and weighs zero."""
    assert contour_length_weights(np.array([0.0])).tolist() == [0.0]


def test_collect_skeleton_height_profiles_totals_match_fiber_lengths(measured):
    """Collected weights total the summed contour length of the bundle."""
    bundle_path, result = measured
    per_bundle, errors = collect_skeleton_height_profiles(
        [bundle_path], scale_um=SCALE_UM,
    )
    assert errors == []
    assert len(per_bundle) == 1
    path, heights, weights = per_bundle[0]
    assert path == bundle_path
    assert heights.shape == weights.shape
    assert float(weights.sum()) == pytest.approx(
        sum(s.length_nm for s in result.stats)
    )


def test_collect_skeleton_height_profiles_reports_bundle_without_scan_size(measured):
    """A bundle with no recorded scan size errors instead of raising."""
    bundle_path, _result = measured
    per_bundle, errors = collect_skeleton_height_profiles([bundle_path])
    assert per_bundle == []
    assert len(errors) == 1
    assert errors[0][0] == bundle_path


class _StraightTrack:
    """Minimal stand-in exposing the track and length straightness reads."""

    def __init__(self, xs, ys, length):
        self.xtrack = np.asarray(xs)
        self.ytrack = np.asarray(ys)
        self.length = length


def _chain_code_length(xs, ys, spp):
    return float(imp_tools.convert_track_to_distance(xs, ys, spp, spp)[-1])


@pytest.mark.parametrize("name,xs,ys", [
    ("horizontal", np.arange(51), np.zeros(51, dtype=int)),
    ("vertical", np.zeros(51, dtype=int), np.arange(51)),
    ("diagonal", np.arange(51), np.arange(51)),
])
def test_straight_tracks_have_straightness_one(name, xs, ys):
    """
    A perfectly straight track reads exactly 1.0 in any direction.
    完全な直線トラックは、どの向きでもちょうど 1.0 になる。

    The Euclidean chord over the corrected chain-code length would give about
    1.055 instead, because that metric reports a straight digitised path as
    roughly 5% shorter than its chord. Measuring the reference line the same
    way is what puts straightness on a readable scale.
    ユークリッド弦を補正済みチェーンコード長で割ると約 1.055 になる。この尺度は
    離散化された直線経路を弦より約 5% 短く報告するためである。基準線を同じ方法で
    測ることが、直線度を読める尺度に載せている。
    """
    spp = 10.0
    length = _chain_code_length(xs, ys, spp)
    assert fiber_straightness(
        _StraightTrack(xs, ys, length), spp
    ) == pytest.approx(1.0, abs=1e-9)


def test_curved_track_is_less_straight_than_a_line():
    """A digitised semicircle falls well below a straight track."""
    theta = np.linspace(0.0, np.pi, 200)
    xs = np.rint(50 + 40 * np.cos(theta)).astype(int)
    ys = np.rint(50 + 40 * np.sin(theta)).astype(int)
    keep = np.concatenate([[True], (np.abs(np.diff(xs)) + np.abs(np.diff(ys))) > 0])
    xs, ys = xs[keep], ys[keep]
    value = fiber_straightness(_StraightTrack(xs, ys, _chain_code_length(xs, ys, 10.0)), 10.0)
    assert 0.4 < value < 0.8


def test_closed_track_has_zero_straightness():
    """A track returning to its start has no straight-line extent."""
    xs = np.array([10, 11, 12, 11, 10])
    ys = np.array([10, 11, 10, 9, 10])
    assert fiber_straightness(_StraightTrack(xs, ys, 100.0), 10.0) == 0.0


def test_straightness_is_bounded_on_a_real_bundle(measured):
    """Every measured fiber lands in [0, 1]."""
    _bundle_path, result = measured
    values = [s.straightness for s in result.stats]
    assert values
    assert all(0.0 <= v <= 1.0 + 1e-9 for v in values)


def test_straightness_is_undefined_without_a_pixel_size(measured):
    """Omitting the scale leaves straightness undefined, not zero."""
    _bundle_path, result = measured
    stats = compute_fiber_stats(result.fibers)
    assert all(np.isnan(s.straightness) for s in stats)
    # Every other statistic is unaffected by the missing scale.
    # 他の統計値はスケールが無くても影響を受けない。
    assert [s.length_nm for s in stats] == [s.length_nm for s in result.stats]


def test_read_fiber_csv_accepts_the_released_column_set(measured, tmp_path):
    """
    A CSV written before straightness existed still reads.
    straightness 追加前に書かれた CSV も引き続き読める。

    That file is how a curated fiber population travels from GUI04 to GUI03,
    so rejecting an older export would strand work that is still valid for
    every other column.
    このファイルはキュレーション済みのファイバー母集団が GUI04 から GUI03 へ
    渡る経路であり、古い出力を拒否すると、他の全列については依然として有効な
    作業を無駄にしてしまう。
    """
    _bundle_path, result = measured
    path = os.path.join(tmp_path, "legacy_fibers.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(list(FIBER_CSV_COLUMNS_V1))
        for s in result.stats:
            writer.writerow([
                s.index, f"{s.length_nm:.1f}", f"{s.height_median_nm:.3f}",
                f"{s.height_max_nm:.3f}", s.ep_count, s.kink_count,
                ";".join(f"{a:.1f}" for a in s.kink_angles_deg),
            ])

    restored = read_fiber_csv(path)
    assert len(restored) == len(result.stats)
    assert all(np.isnan(s.straightness) for s in restored)
    assert restored[0].length_nm == pytest.approx(result.stats[0].length_nm, abs=0.05)


def _digitised_arc(radius_px, spp):
    """Digitise a quarter circle the way a skeleton would."""
    span = np.pi / 2.0
    theta = np.linspace(0.0, span, int(radius_px * span * 4) + 2)
    xs = np.rint(radius_px * np.cos(theta)).astype(int) + radius_px + 2
    ys = np.rint(radius_px * np.sin(theta)).astype(int) + 2
    keep = np.concatenate([[True], (np.abs(np.diff(xs)) + np.abs(np.diff(ys))) > 0])
    return _ArcTrack(xs[keep].astype(float), ys[keep].astype(float), spp)


class _ArcTrack:
    """Minimal stand-in exposing the track and horizon curvature reads."""

    def __init__(self, xs, ys, spp):
        self.xtrack = xs
        self.ytrack = ys
        self.horizon = imp_tools.convert_track_to_distance(xs, ys, spp, spp)


def test_curvature_of_a_straight_track_is_zero():
    """A digitised straight line has no curvature at any window."""
    spp = 2.0
    track = _ArcTrack(np.arange(400.0), np.zeros(400), spp)
    for window in (50.0, 100.0, 200.0):
        profile = fiber_curvature_profile(track, spp, spp, window_nm=window)
        assert profile.size > 0
        assert float(np.max(profile)) == pytest.approx(0.0, abs=1e-9)


def test_curvature_recovers_a_known_radius():
    """
    A digitised arc of radius R measures close to 1/R.
    半径 R の離散化円弧は 1/R に近い値として測られる。

    The residual is the contour-length metric over-measuring a strongly
    curved digitised path, not the turning angle, which is exact. The
    tolerance is wide enough to accept that documented bias and narrow enough
    to fail if the estimator loses its factor of two again: dividing by the
    whole window instead of the half-window separating the two chord
    midpoints reported half the true curvature.
    残差は、回転角ではなく、輪郭長の尺度が強く曲がった離散化経路を過大に測ること
    に由来する。回転角は厳密である。許容幅は、その文書化された偏りを受け入れつつ、
    推定量が再び 2 倍の係数を失えば失敗する程度に狭くしてある。2 つの弦の中点を
    隔てる半窓ではなく窓全体で割ると、真の曲率の半分を報告してしまう。
    """
    spp = 1.953
    for radius_px in (100, 250):
        radius_um = radius_px * spp / 1000.0
        expected = 1.0 / radius_um
        arc = _digitised_arc(radius_px, spp)
        measured = float(np.median(
            fiber_curvature_profile(arc, spp, spp, window_nm=100.0)
        ))
        assert measured == pytest.approx(expected, rel=0.30)


def test_curvature_window_below_the_pixel_scale_is_noise():
    """
    A window of a few pixels reports the same value whatever the true curvature.
    数画素の窓は、真の曲率によらず同じ値を返す。

    Skeleton steps are orthogonal or diagonal only, so the turn between
    consecutive steps is quantised to multiples of 45 degrees. This is why the
    estimator takes a window at all, and why the default is not smaller.
    骨格のステップは直交か斜めのみであり、連続するステップ間の回転は 45 度の
    倍数に量子化される。推定量が窓を取る理由であり、既定値をこれ以上小さく
    しない理由でもある。
    """
    spp = 1.953
    tight = float(np.median(fiber_curvature_profile(
        _digitised_arc(100, spp), spp, spp, window_nm=20.0)))
    gentle = float(np.median(fiber_curvature_profile(
        _digitised_arc(250, spp), spp, spp, window_nm=20.0)))
    # The true curvatures differ by a factor of 2.5; the noise floor does not.
    # 真の曲率は 2.5 倍違うが、ノイズ下限は違わない。
    assert tight == pytest.approx(gentle, rel=0.05)


def test_curvature_is_empty_for_a_fiber_shorter_than_the_window():
    """A fiber that cannot span the window yields no curvature at all."""
    spp = 2.0
    short = _ArcTrack(np.arange(10.0), np.zeros(10), spp)
    assert fiber_curvature_profile(short, spp, spp, window_nm=500.0).size == 0


def test_kink_angle_and_density_handle_a_kinkless_fiber_differently():
    """
    A fiber with no kink has no angle but a real density of zero.
    キンクの無いファイバーは角度を持たないが、密度は 0 という実在の値を持つ。

    The asymmetry is the point: an undetected kink is not a measured angle of
    zero, so averaging one in would pull the population toward a value no
    fiber has; zero kinks over a measured contour length, on the other hand,
    is a density that was genuinely measured.
    この非対称性が要点である。キンクが検出されなかったことは「0 度のキンクを
    計測した」ことではなく、平均に混ぜればどのファイバーも持たない値へ母集団を
    引っ張る。一方、計測済みの輪郭長に対するキンク 0 本は、実際に計測された密度
    である。
    """
    kinkless = FiberStats(
        index=0, length_nm=1000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=0, kink_angles_deg=(), straightness=1.0,
    )
    assert np.isnan(fiber_kink_angle(kinkless))
    assert fiber_kink_density(kinkless) == 0.0

    kinked = FiberStats(
        index=1, length_nm=2000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=3, kink_angles_deg=(100.0, 120.0, 170.0),
        straightness=0.8,
    )
    # The median, not the mean, so one extreme kink does not represent the fiber.
    # 平均ではなく中央値。極端なキンク 1 つがファイバーを代表しないようにする。
    assert fiber_kink_angle(kinked) == pytest.approx(120.0)
    assert fiber_kink_density(kinked) == pytest.approx(3.0 / 2.0)


def test_kink_density_normalises_by_length():
    """The same kink count over twice the contour is half the density."""
    short = FiberStats(
        index=0, length_nm=500.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=4, kink_angles_deg=(90.0,) * 4, straightness=0.9,
    )
    long = FiberStats(
        index=1, length_nm=1000.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=4, kink_angles_deg=(90.0,) * 4, straightness=0.9,
    )
    assert fiber_kink_density(short) == pytest.approx(8.0)
    assert fiber_kink_density(long) == pytest.approx(4.0)
    # A zero-length fiber cannot yield a density and must not divide by zero.
    # 長さ 0 のファイバーは密度を出せず、0 除算も起こしてはならない。
    zero = FiberStats(
        index=2, length_nm=0.0, height_median_nm=1.0, height_max_nm=2.0,
        ep_count=2, kink_count=1, kink_angles_deg=(90.0,), straightness=1.0,
    )
    assert np.isnan(fiber_kink_density(zero))


def test_mean_curvature_is_nan_for_a_fiber_shorter_than_the_window():
    """
    An unmeasurable fiber gives NaN, and a measurable one gives the profile mean.
    計測不能なファイバーは NaN を返し、計測可能なものはプロファイルの平均を返す。

    NaN rather than 0.0 because 0.0 means "perfectly straight", which a caller
    would then average into a population that never measured the fiber at all.
    0.0 は「完全な直線」を意味し、そもそも計測していないファイバーを母集団に
    平均として混ぜてしまうため、0.0 ではなく NaN とする。
    """
    spp = 2.0
    short = _ArcTrack(np.arange(10.0), np.zeros(10), spp)
    assert np.isnan(fiber_mean_curvature(short, spp, spp, window_nm=500.0))

    long_track = _ArcTrack(np.arange(400.0), np.zeros(400), spp)
    profile = fiber_curvature_profile(long_track, spp, spp, window_nm=100.0)
    assert fiber_mean_curvature(
        long_track, spp, spp, window_nm=100.0
    ) == pytest.approx(float(np.mean(profile)))


def test_collect_fiber_curvature_reports_unmeasurable_fibers(measured):
    """A window longer than a fiber leaves its curvature undefined, not zero."""
    bundle_path, result = measured
    per_bundle, errors = collect_fiber_curvature(
        [bundle_path], scale_um=SCALE_UM, curvature_window_nm=100000.0,
    )
    assert errors == []
    _path, curvature = per_bundle[0]
    # One entry per fiber survives, so the caller can count what it lost.
    # ファイバー 1 本につき 1 要素が残るため、呼び出し側は失われた本数を数えられる。
    assert curvature.size == len(result.fibers)
    assert np.all(np.isnan(curvature))


def test_fiber_csv_round_trip(measured, tmp_path):
    """Reading back an exported CSV reproduces the statistics that wrote it."""
    _bundle_path, result = measured
    path = os.path.join(tmp_path, "sample_fibers.csv")
    write_fiber_csv(path, result.stats)
    back = read_fiber_csv(path)

    assert len(back) == len(result.stats)
    for original, restored in zip(result.stats, back):
        assert restored.index == original.index
        # write_fiber_csv formats length to 0.1 nm and heights to 0.001 nm.
        # write_fiber_csv は長さを 0.1 nm、高さを 0.001 nm に丸めて出力する。
        assert restored.length_nm == pytest.approx(original.length_nm, abs=0.05)
        assert restored.height_median_nm == pytest.approx(
            original.height_median_nm, abs=0.0005
        )
        assert restored.ep_count == original.ep_count
        assert restored.kink_count == original.kink_count
        assert len(restored.kink_angles_deg) == len(original.kink_angles_deg)


def test_read_fiber_csv_rejects_a_foreign_csv(tmp_path):
    """A CSV with different columns is reported, not partially read."""
    path = os.path.join(tmp_path, "other.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("bundle,height_nm\na,1.0\n")
    with pytest.raises(ValueError):
        read_fiber_csv(path)


def test_collect_fiber_stats_from_csv_keeps_files_separate(measured, tmp_path):
    """Each CSV becomes its own entry, so per-image aggregation is possible."""
    _bundle_path, result = measured
    paths = []
    for name in ("a_fibers.csv", "b_fibers.csv"):
        path = os.path.join(tmp_path, name)
        write_fiber_csv(path, result.stats)
        paths.append(path)
    missing = os.path.join(tmp_path, "missing_fibers.csv")

    per_file, errors = collect_fiber_stats_from_csv(paths + [missing])
    assert [p for p, _s in per_file] == paths
    assert len(errors) == 1
    assert errors[0][0] == missing


def test_collect_fiber_stats_applies_the_exclusion_sidecar(measured, tmp_path):
    """
    An exclusion sidecar drops its fibers only when asked.
    除外サイドカーは、要求されたときにのみ対象ファイバーを取り除く。

    The default stays off so an existing sidecar cannot silently change what
    `cli.py measure` reports for a bundle nobody asked to curate.
    既定を OFF に保つことで、キュレーションを指示されていないバンドルについて
    既存のサイドカーが `cli.py measure` の報告内容を黙って変えないようにする。
    """
    bundle_path, result = measured
    # Copy the bundle so the shipped test data never gains a sidecar.
    # 同梱テストデータにサイドカーを作らないよう、バンドルを複製して使う。
    copied = os.path.join(tmp_path, "copy.b2z")
    shutil.copyfile(bundle_path, copied)

    anchor = fiber_anchor(result.fibers[0])
    save_exclusions(
        exclusion_path_for(copied), "copy.b2z",
        [{"x": anchor[0], "y": anchor[1], "note": "debris"}],
    )

    plain, _errors = collect_fiber_stats([copied], scale_um=SCALE_UM)
    curated, _errors2 = collect_fiber_stats(
        [copied], scale_um=SCALE_UM, apply_exclusions=True,
    )
    assert len(curated[0][1]) == len(plain[0][1]) - 1
    # Retained fibers are renumbered, matching GUI04's export.
    # 残ったファイバーは採番し直され、GUI04 の出力と一致する。
    assert [s.index for s in curated[0][1]] == list(range(len(curated[0][1])))


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


def _straight_fiber(x0: int, x1: int, y: int) -> Fiber:
    """
    Build a minimal horizontal fiber whose track runs from x0 to x1 at row y.
    行 y 上を x0 から x1 まで走る、水平な最小構成のファイバーを作る。

    `isolated_fiber_flags` reads only ``data`` (bbox origin) and the track
    arrays; the remaining fields are valid placeholders.
    `isolated_fiber_flags` が読むのは ``data``（bbox 原点）とトラック配列のみ。
    残りのフィールドは妥当なプレースホルダで埋める。
    """
    n = x1 - x0 + 1
    return Fiber(
        fiber_image=np.zeros((1, n)),
        data=(x0, y, n, 1, n),
        xtrack=np.arange(n),
        ytrack=np.zeros(n, dtype=int),
        horizon=np.arange(n, dtype=float),
        height=np.zeros(n),
        kink_indices=np.array([], dtype=int),
        ep_indices=np.array([0, n - 1]),
        kink_angles=np.array([]),
        decomposed_point_indices=np.array([], dtype=int),
    )


def test_isolated_fiber_flags_exclude_fibers_reaching_a_crossing():
    """
    A fiber whose track reaches a branch point is not isolated.
    トラックが分岐点に達するファイバーは孤立ではない。

    This is the test behind GUI04's "非孤立を除外" button. Fibers cut at a
    crossing have a truncated length, so excluding them is what keeps the
    length statistics free of partial measurements.
    GUI04 の「非孤立を除外」ボタンの判定である。交差部で切断された
    ファイバーは長さが切り詰められているため、除外することで長さ統計に部分
    計測が混ざらないようにする。
    """
    image = FiberTrackingImage(
        original_AFM=np.zeros((40, 40)), name="synthetic", size_per_pixel=10.0,
    )
    bp = np.zeros((40, 40), dtype=np.uint8)
    bp[20, 20] = 1
    image.bp = bp

    far = _straight_fiber(x0=2, x1=12, y=5)
    through = _straight_fiber(x0=14, x1=26, y=20)   # runs through (20, 20)
    ending_at = _straight_fiber(x0=8, x1=18, y=20)  # terminal 2 px from (20, 20)

    assert isolated_fiber_flags(image, [far, through, ending_at]) == [True, False, False]


def test_isolated_fiber_flags_exclude_fibers_reaching_the_frame():
    """
    A fiber touching the outermost row or column is not isolated.
    最外周の行または列に接するファイバーは孤立ではない。

    Such a fiber continues outside the scan, so its measured length is the part
    that happened to fall inside the frame. The branch-point test cannot catch
    this on its own — there are no branch points beyond the frame, which makes
    a fiber leaving the scan look *more* isolated, not less.
    このようなファイバーは走査範囲の外へ続いており、計測された長さは、たまたま
    枠内に入った部分でしかない。分岐点の判定だけではこれを捉えられない。枠の外
    に分岐点は無いため、走査範囲から出ていくファイバーほど、かえって孤立して
    見えてしまう。
    """
    image = FiberTrackingImage(
        original_AFM=np.zeros((40, 40)), name="synthetic", size_per_pixel=10.0,
    )
    image.bp = np.zeros((40, 40), dtype=np.uint8)
    image.bp[35, 35] = 1

    inside = _straight_fiber(x0=5, x1=15, y=5)
    left_edge = _straight_fiber(x0=0, x1=15, y=10)
    right_edge = _straight_fiber(x0=25, x1=39, y=15)

    assert isolated_fiber_flags(
        image, [inside, left_edge, right_edge]
    ) == [True, False, False]


def test_isolated_fiber_flags_exclude_fibers_the_connector_could_extend():
    """
    A fiber with a connectable neighbour is not measured over its whole length.
    連結相手を持つファイバーは、全長を計測できたファイバーではない。

    The branch-point test misses this case whenever the crossing sits just
    outside its 2 px touch radius, while the connector plainly sees the fiber
    continue past the gap.
    交差が 2 画素の接触半径のわずかに外側にあると、分岐点の判定はこの場合を取り
    逃がす。一方で連結器からは、隙間の先へファイバーが続いているのが明らかに
    見えている。
    """
    image = FiberTrackingImage(
        original_AFM=np.zeros((60, 60)), name="synthetic", size_per_pixel=10.0,
    )
    # A flat height field keeps the connector's height gate satisfied, so the
    # test turns on the distance and angle gates alone.
    # 高さを一定にして連結器の高さ判定を常に満たし、距離と角度の判定だけを
    # 切り分けて検証する。
    image.calibrated_image = np.full((60, 60), 5.0, dtype=float)
    image.bp = np.zeros((60, 60), dtype=np.uint8)
    image.bp[55, 55] = 1

    # Two collinear fibers a short gap apart: each is the other's continuation.
    # 短い隙間を挟んで一直線に並ぶ 2 本。互いが互いの続きである。
    left = _straight_fiber(x0=5, x1=20, y=30)
    right = _straight_fiber(x0=26, x1=41, y=30)
    # A third fiber far away, with nothing to join to.
    # 遠く離れた 3 本目。連結相手を持たない。
    lone = _straight_fiber(x0=5, x1=20, y=10)

    assert isolated_fiber_flags(image, [left, right, lone]) == [False, False, True]


def test_isolated_fiber_flags_apply_the_frame_test_without_a_branch_mask():
    """
    The frame test still runs when no `bp` mask is available.
    `bp` マスクが無い場合でも枠の判定は行われる。

    Entanglement is unknowable without the mask, but the frame is not: it needs
    only the image shape, so a fiber leaving the scan is still rejected.
    マスクが無ければ絡まりは判定できないが、枠は判定できる。必要なのは画像の形状
    だけなので、走査範囲から出ていくファイバーはこの場合も除外される。
    """
    image = FiberTrackingImage(
        original_AFM=np.zeros((40, 40)), name="synthetic", size_per_pixel=10.0,
    )
    inside = _straight_fiber(x0=5, x1=15, y=5)
    at_edge = _straight_fiber(x0=20, x1=39, y=10)

    assert isolated_fiber_flags(image, [inside, at_edge]) == [True, False]


def test_isolated_fiber_flags_without_branch_mask_keep_every_fiber():
    """
    Without a `bp` mask the test cannot discriminate, so nothing is dropped.
    `bp` マスクが無い場合は判別できないため、除外は行わない。
    """
    image = FiberTrackingImage(
        original_AFM=np.zeros((40, 40)), name="synthetic", size_per_pixel=10.0,
    )
    fibers = [_straight_fiber(x0=2, x1=12, y=5)]
    assert isolated_fiber_flags(image, fibers) == [True]


def test_isolated_fiber_flags_match_endpoint_count_without_connection(measured):
    """
    Without fiber connection, isolation agrees with having two free ends.
    ファイバー連結なしでは、孤立判定は自由端 2 つを持つことと一致する。

    `remove_bp` cuts every fiber at its crossings before tracing, so a fragment
    keeps both original endpoints exactly when it never reached one. The two
    criteria are therefore equivalent in this mode, and the filter reproduces
    what the endpoint count already showed.
    追跡前に `remove_bp` が交差部で全ファイバーを切断するため、断片が元の端点を
    2 つとも保つのは交差に達しなかった場合に限られる。このモードでは両基準が
    等価であり、フィルターは端点数が示していた内容を再現する。

    The equivalence holds only away from the frame: a fiber running off the
    scan edge keeps two endpoints but is not isolated. No fiber in this
    fixture reaches the frame, which is what lets the assertion stand.
    この等価性が成り立つのは枠から離れている場合に限る。走査範囲の外へ出ていく
    ファイバーは端点を 2 つ保つが孤立ではない。本フィクスチャのファイバーはいず
    れも枠に達しないため、この表明が成立する。
    """
    _bundle_path, result = measured
    flags = isolated_fiber_flags(result.image, result.fibers)
    assert flags == [s.ep_count == 2 for s in result.stats]
