# -*- coding: utf-8 -*-
"""
Tests for the half-maximum centerline (`lib.centerline`) and for the fibers
built on it.
半値中点線（`lib.centerline`）と、その上に組み立てる繊維のテスト。

The unit tests use analytic height ridges whose centre is known exactly, so the
line is compared with the geometry itself rather than with another pipeline
stage, none of which is ground truth. The integration tests run the real
pipeline on a small synthetic scan and check that a format 1.1 bundle is built
on the centerline while a 1.0 bundle keeps its skeleton track.
単体テストは中心が厳密にわかっている解析的な高さ稜線を使い、線を、いずれも
正解ではない他のパイプライン段とではなく幾何そのものと比較する。統合テストは
小さな合成スキャンに実際のパイプラインを適用し、形式 1.1 のバンドルは中心線で、
1.0 のバンドルはスケルトントラックのまま組み立てられることを確かめる。
"""

import os

import numpy as np
import pytest

from lib import blosc2_io, measure
from lib.centerline import (
    HALF_MAX_CENTERLINE,
    SKELETON_TRACK,
    half_max_centerline,
    measure_apparent_width,
    polyline_distance,
    refine_centerline,
)
from lib.fiber import skeleton_track
from lib.fiber_selection import fiber_anchor, fiber_track_pixels
from lib.imp_tools import convert_track_to_distance
from lib.kink_detector import KinkDetector
from lib.pipeline import ProcParams, process_file

import synthetic_fibers as sf

# Geometry shared by the straight-ridge cases. The ridge runs at 23 degrees so
# the pixel track carries the staircase an oblique real fiber has.
# 直線稜線ケースで共有する形状。稜線を 23 度にするのは、斜めに走る実際の繊維と
# 同じ階段状の画素トラックにするためである。
SHAPE = (120, 160)
CENTER = (80.0, 60.0)
ANGLE = np.radians(23.0)
UX, UY = np.cos(ANGLE), np.sin(ANGLE)
NX, NY = -UY, UX
FWHM = 6.0


def _normal_distance():
    """Signed distance of every pixel from the ridge axis through CENTER."""
    rows, cols = np.mgrid[0:SHAPE[0], 0:SHAPE[1]].astype(float)
    return (cols - CENTER[0]) * NX + (rows - CENTER[1]) * NY, rows, cols


def _ridge(amplitude, fwhm, offset, extent=None):
    """
    Straight Gaussian ridge `offset` px along the normal, optionally cut short.
    法線方向に `offset` px ずれた直線ガウス稜線。必要なら長さを区切る。
    """
    d, rows, cols = _normal_distance()
    d = d - offset
    height = amplitude * np.exp(-0.5 * (d / (fwhm / 2.3548)) ** 2)
    if extent is not None:
        u = (cols - CENTER[0]) * UX + (rows - CENTER[1]) * UY
        centre = 0.5 * (extent[0] + extent[1])
        half = 0.5 * (extent[1] - extent[0])
        height = height * 0.5 * (1.0 - np.tanh((np.abs(u - centre) - half) / 2.0))
    return height


def _track(lateral, half_length=45):
    """
    Pixel track along the ridge direction, displaced by `lateral` px.
    稜線方向に沿い、法線方向に `lateral` px ずれた画素トラック。
    """
    u = np.arange(-half_length, half_length + 1, 1.0)
    off = lateral(u) if callable(lateral) else np.full_like(u, float(lateral))
    x = np.round(CENTER[0] + UX * u + NX * off)
    y = np.round(CENTER[1] + UY * u + NY * off)
    keep = np.concatenate([[True], (np.diff(x) != 0) | (np.diff(y) != 0)])
    return x[keep], y[keep]


def _signed_offset(x, y):
    """Signed perpendicular distance from each point to the ridge axis."""
    return (x - CENTER[0]) * NX + (y - CENTER[1]) * NY


def test_a_track_off_a_symmetric_ridge_lands_on_its_centre():
    """
    A track 2 px off a symmetric ridge ends within 0.15 px of its centre.
    対称な稜線から 2 px ずれたトラックが、稜線の中心から 0.15 px 以内に移る。
    """
    height = _ridge(3.0, FWHM, 0.0)
    x, y = _track(2.0)
    width = measure_apparent_width(height, x, y)
    rx, ry, reliable = refine_centerline(height, x, y, width)
    core = slice(8, -8)
    assert np.median(np.abs(_signed_offset(x, y))[core]) > 1.5
    assert np.median(np.abs(_signed_offset(rx, ry))[core]) < 0.15
    assert reliable[core].all()


def test_an_asymmetric_section_is_placed_at_its_half_maximum_midpoint():
    """
    On a skewed cross-section the line sits at the half-maximum midpoint, not the crest.
    非対称な断面では、線は頂点ではなく半値中点に置かれる。

    This is the property the method was chosen for. A twisted fibril with an
    anisotropic cross-section presents a skewed profile whose crest lies off
    the axis, and a line that follows the crest swings with the twist. Here
    the crest is at 0 and the two half-maximum crossings at -4 and +1 px, so
    the midpoint is -1.5 px.
    本手法を選んだ理由となる性質である。断面が異方性のねじれたフィブリルは頂点が
    軸から外れた歪んだ断面を示し、頂点を追う線はねじれとともに振れる。ここでは
    頂点が 0、2 つの半値交点が -4 px と +1 px にあるため、中点は -1.5 px である。
    """
    d, _rows, _cols = _normal_distance()
    gentle, steep = 8.0, 2.0
    height = np.where(
        d <= 0.0,
        np.clip(1.0 + d / gentle, 0.0, None),
        np.clip(1.0 - d / steep, 0.0, None),
    ) * 3.0
    x, y = _track(0.0)
    lx, ly = half_max_centerline(height, x, y)
    core = slice(8, -8)
    offset = np.median(_signed_offset(lx, ly)[core])
    assert abs(offset - (-1.5)) < 0.25


def test_the_line_keeps_one_point_per_input_point_and_the_length():
    """
    The line has the input's point count and the ridge's length.
    線は入力と同じ点数を持ち、長さは稜線上の長さに等しい。

    One point per input point is what lets kinks found on the line be stored
    at skeleton pixels; the length check guards against the ends being pulled
    inward, which shortened short fragments in a prototype.
    入力点ごとに 1 点であることが、線上で見つけたキンクをスケルトン画素に保存できる
    理由である。長さの検査は、試作で短い断片を縮めた端の引き込みを防ぐ。
    """
    height = _ridge(3.0, FWHM, 0.0)
    x, y = _track(1.0)
    lx, ly = half_max_centerline(height, x, y)
    assert lx.shape == x.shape and ly.shape == y.shape
    chord = np.hypot(x[-1] - x[0], y[-1] - y[0])
    length = polyline_distance(lx, ly, 1.0)[-1]
    assert abs(length / chord - 1.0) < 0.02


def test_a_brighter_neighbour_within_reach_does_not_capture_the_track():
    """
    Points beside a brighter, nearer ridge are not pulled onto it.
    より明るい近くの稜線の横にある点は、その稜線へ引き寄せられない。

    Captured means placed on the neighbour's side of the line midway between
    the two ridges. Where the neighbour's flank overlaps the fiber, the summed
    height itself moves toward it, which no line read from height alone can
    undo, so that shift is not what is tested.
    奪われるとは、2 本の稜線の中間線より隣の側に置かれることを指す。隣の斜面が
    繊維に重なる場所では合計した高さそのものが隣の方へ動き、高さだけから読む線では
    それを取り消せないため、そのずれは検査の対象ではない。
    """
    separation = 4.0
    height = (_ridge(1.0, FWHM, 0.0)
              + _ridge(3.0, 3.0, separation, extent=(-12.0, 12.0)))
    x, y = _track(0.0)
    width = measure_apparent_width(height, x, y)
    rx, ry, reliable = refine_centerline(height, x, y, width)
    beside = np.abs((x - CENTER[0]) * UX + (y - CENTER[1]) * UY) <= 8.0
    assert not reliable[beside].any()
    assert np.abs(_signed_offset(rx, ry))[beside].max() < 0.5 * separation


def test_points_within_one_width_of_a_branch_point_are_interpolated():
    """
    The line is not measured within one apparent width of a junction.
    分岐から見かけ幅 1 本分以内では線の位置を測らない。
    """
    height = _ridge(3.0, FWHM, 0.0)
    x, y = _track(0.0)
    width = measure_apparent_width(height, x, y)
    branch = np.zeros(SHAPE, dtype=np.uint8)
    mid = len(x) // 2
    branch[int(y[mid]), int(x[mid])] = 1
    _, _, reliable = refine_centerline(height, x, y, width, branch)
    near = np.hypot(x - x[mid], y - y[mid]) < width
    assert not reliable[near].any()
    assert reliable[~near].mean() > 0.95


def test_a_skeleton_excursion_on_a_straight_fiber_is_not_a_kink():
    """
    A detour of the skeleton off a straight ridge is not a kink on the centerline.
    直線稜線からスケルトンが外れても、中心線上ではキンクにならない。

    This is the defect reported on the higher-plant TOC scan: the medial axis
    swung off a straight fiber below a Y junction and the kink rule reported
    the swing as a sharp bend. The same rule is run on the raw track to show
    that the detour is sharp enough to be reported there. The detour sits in
    the middle of the fiber so that the end rule cannot be what removes it.
    高等植物 TOC スキャンで報告された欠陥である。Y 字の下で medial axis がまっすぐな
    繊維から振れ、キンク規則がその振れを鋭い折れとして報告した。同じ規則を生の
    トラックにも適用し、そこでは報告されるほど鋭い迂回であることを示す。迂回は
    繊維の中ほどに置き、それを消したのが端の規則ではありえないようにする。
    """
    height = _ridge(3.0, FWHM, 0.0)
    x, y = _track(lambda u: 4.0 * np.clip(1.0 - np.abs(u) / 5.0, 0.0, None))
    detector = KinkDetector()
    lx, ly, width = half_max_centerline(height, x, y, return_width=True)
    on_track, _, _ = detector.kinks_on_line(x, y, width)
    on_line, _, unjudged = detector.kinks_on_line(lx, ly, width)
    assert len(on_track) >= 1
    assert len(on_line) == 0 and len(unjudged) == 0


def _ray_ridge(corner, direction, amplitude=3.0, fwhm=FWHM):
    """Gaussian ridge along one ray from `corner`, with a rounded cap."""
    rows, cols = np.mgrid[0:SHAPE[0], 0:SHAPE[1]].astype(float)
    ux, uy = np.cos(direction), np.sin(direction)
    px, py = cols - corner[0], rows - corner[1]
    u = px * ux + py * uy
    d = np.where(u >= 0.0, np.abs(-px * uy + py * ux), np.hypot(px, py))
    return amplitude * np.exp(-0.5 * (d / (fwhm / 2.3548)) ** 2)


def test_a_real_corner_is_still_reported_on_the_centerline():
    """
    A 120 degree corner in the ridge itself is reported once, near the corner.
    稜線そのものの 120 度のコーナーは、コーナー付近で 1 回報告される。

    The companion of the excursion test: without it, a line that smoothed
    every bend away would pass that test.
    迂回テストの対になるテストである。これが無いと、あらゆる折れを平滑化で
    消してしまう線でも迂回テストに合格してしまう。
    """
    a1 = np.radians(203.0)
    a2 = a1 + np.radians(120.0)
    height = np.maximum(_ray_ridge(CENTER, a1), _ray_ridge(CENTER, a2))
    u = np.arange(0.0, 46.0, 1.0)
    xs = np.concatenate([CENTER[0] + np.cos(a1) * u[::-1], CENTER[0] + np.cos(a2) * u[1:]])
    ys = np.concatenate([CENTER[1] + np.sin(a1) * u[::-1], CENTER[1] + np.sin(a2) * u[1:]])
    x, y = np.round(xs), np.round(ys)
    keep = np.concatenate([[True], (np.diff(x) != 0) | (np.diff(y) != 0)])
    x, y = x[keep], y[keep]
    lx, ly, width = half_max_centerline(height, x, y, return_width=True)
    kinks, angles, _ = KinkDetector().kinks_on_line(lx, ly, width)
    assert len(kinks) == 1
    assert np.hypot(lx[kinks[0]] - CENTER[0], ly[kinks[0]] - CENTER[1]) < FWHM
    assert abs(np.degrees(angles[0]) - 120.0) < 10.0


def test_polyline_distance_uses_per_axis_pixel_sizes():
    """
    A step along X is scaled by the X pixel size and a step along Y by the Y one.
    X 方向のステップは X、Y 方向のステップは Y のピクセルサイズで換算される。
    """
    x = np.array([0.0, 3.0, 3.0])
    y = np.array([0.0, 0.0, 4.0])
    horizon = polyline_distance(x, y, 2.0, 5.0)
    assert horizon.tolist() == pytest.approx([0.0, 6.0, 26.0])


# ----- Bundles built on the centerline and on the skeleton -----

@pytest.fixture(scope="module")
def synthetic_bundle(tmp_path_factory):
    """
    Analyze a small synthetic scan (a straight fiber and a 120 degree corner).
    小さな合成スキャン（直線の繊維と 120 度のコーナー）を解析する。
    """
    shape, nm_per_px = (256, 256), 2.0
    lines = [
        sf.straight_centerline(360.0, shape=shape, nm_per_px=nm_per_px,
                               center_px=(128.0, 70.0)),
        sf.kinked_centerline(360.0, 120.0, shape=shape, nm_per_px=nm_per_px,
                             center_px=(128.0, 170.0)),
    ]
    scan = sf.render_scan(lines, shape=shape, nm_per_px=nm_per_px,
                          noise_nm=0.05, roughness_nm=0.2, seed=3)
    out = tmp_path_factory.mktemp("centerline")
    txt = sf.write_afm_text(scan, str(out / "scan.txt"))
    result = process_file(txt, ProcParams(), scan_size_um=scan.scan_size_um,
                          scan_size_source="manual")
    return result.bundle_path


def _as_format_1_0(bundle_path, out_path):
    """Copy a bundle, recording it as written by format 1.0."""
    arrays = blosc2_io.load_bundle(bundle_path)
    meta = dict(blosc2_io.load_bundle_meta(bundle_path))
    meta["version"] = "1.0"
    blosc2_io.save_bundle(out_path, arrays, vlmeta=meta)
    return out_path


def test_a_format_1_1_bundle_is_built_on_the_centerline(synthetic_bundle):
    """
    Fibers of a new bundle carry the centerline and the skeleton pixels under it.
    新しいバンドルの繊維は中心線と、その元になったスケルトン画素を持つ。
    """
    assert blosc2_io.load_bundle_meta(synthetic_bundle)["version"] == "1.1"
    result = measure.measure_bundle(synthetic_bundle)
    assert result.image.centerline == HALF_MAX_CENTERLINE
    assert result.fibers
    sx_ = result.image.size_per_pixel
    sy_ = result.image.y_size_per_pixel
    for fiber in result.fibers:
        assert fiber.centerline == HALF_MAX_CENTERLINE
        px, py = skeleton_track(fiber)
        assert px.shape == np.asarray(fiber.xtrack).shape
        # The line stays on the fiber the skeleton pixel under it belongs to.
        # 線は、その下のスケルトン画素が属する繊維の上に留まる。
        assert np.max(np.hypot(fiber.xtrack - px, fiber.ytrack - py)) < 3.0
        np.testing.assert_allclose(
            fiber.horizon, polyline_distance(fiber.xtrack, fiber.ytrack, sx_, sy_))
        # Identity is the skeleton pixels, whatever the line does.
        # 識別は線に関係なくスケルトン画素で行う。
        anchor = fiber_anchor(fiber)
        assert anchor in fiber_track_pixels(fiber)


def test_the_stored_kinks_are_the_ones_judged_on_the_displayed_line(synthetic_bundle):
    """
    Kinks written by the pipeline equal the kinks recomputed on each fiber's line.
    パイプラインが書いたキンクは、各繊維の線上で再計算したキンクと一致する。

    GUI01 judges kinks on a line it builds and then discards; the fiber tracker
    rebuilds the line when the bundle is opened. If the two lines differed,
    the kinks on screen would sit on a line they were not judged on. The bends
    left unjudged next to an end (``up``) are checked the same way, and must
    reach each fiber as `Fiber.unjudged_indices`.
    GUI01 は自分で作って捨てる線の上でキンクを判定し、ファイバートラッカーは
    バンドルを開くときに線を作り直す。2 本の線が異なれば、画面上のキンクは判定に
    使われていない線の上に載ることになる。端のそばで判定しなかった折れ（``up``）も
    同じく検査し、各繊維に `Fiber.unjudged_indices` として届かなければならない。
    """
    result = measure.measure_bundle(synthetic_bundle)
    arrays = blosc2_io.load_bundle(synthetic_bundle)
    stored = arrays["kp"]
    stored_set = set(zip(stored[0].tolist(), stored[1].tolist()))
    stored_up = set(zip(arrays["up"][0].tolist(), arrays["up"][1].tolist()))
    cal = result.image.calibrated_image
    detector = KinkDetector()
    recomputed, recomputed_up, carried_up = set(), set(), set()
    for fiber in result.fibers:
        x0, y0 = int(fiber.data[0]), int(fiber.data[1])
        px, py = skeleton_track(fiber)
        width = measure_apparent_width(cal, px + x0, py + y0)
        ki, _, ui = detector.kinks_on_line(
            np.asarray(fiber.xtrack) + x0, np.asarray(fiber.ytrack) + y0, width)
        recomputed |= {(int(px[i]) + x0, int(py[i]) + y0) for i in ki}
        recomputed_up |= {(int(px[i]) + x0, int(py[i]) + y0) for i in ui}
        carried_up |= {(int(px[i]) + x0, int(py[i]) + y0) for i in fiber.unjudged_indices}
    assert recomputed == stored_set
    assert recomputed_up == stored_up == carried_up
    # The corner is found, and the straight fiber carries none.
    # コーナーは検出され、直線の繊維にはキンクが無い。
    assert len(stored_set) >= 1


def test_a_straight_fiber_on_the_centerline_reads_straight(synthetic_bundle):
    """
    Straightness of the straight synthetic fiber is within 0.5 % of 1.0.
    合成の直線繊維の直線度は 1.0 から 0.5 % 以内である。
    """
    result = measure.measure_bundle(synthetic_bundle)
    longest = max(result.stats, key=lambda s: s.length_nm if s.kink_count == 0 else 0.0)
    assert longest.kink_count == 0
    assert longest.straightness > 0.995


def test_a_format_1_0_bundle_keeps_its_skeleton_track(synthetic_bundle, tmp_path):
    """
    An older bundle is measured along the skeleton, exactly as before 1.1.
    古いバンドルは、1.1 より前と全く同じくスケルトンに沿って計測される。
    """
    old = _as_format_1_0(synthetic_bundle, str(tmp_path / "old.b2z"))
    result = measure.measure_bundle(old)
    assert result.image.centerline == SKELETON_TRACK
    assert measure.read_centerline_from_bundle(old) == SKELETON_TRACK
    spp = result.image.size_per_pixel
    spp_y = result.image.y_size_per_pixel
    for fiber in result.fibers:
        assert fiber.centerline == SKELETON_TRACK
        assert fiber.skeleton_xtrack is None
        assert np.issubdtype(np.asarray(fiber.xtrack).dtype, np.integer)
        np.testing.assert_allclose(
            fiber.horizon,
            convert_track_to_distance(fiber.xtrack, fiber.ytrack, spp, spp_y))


def test_both_formats_trace_the_same_skeleton(synthetic_bundle, tmp_path):
    """
    The two formats differ in the line only: identity and topology are shared.
    2 つの形式の違いは線だけであり、識別とトポロジーは共通である。

    Exclusion and connection sidecars store skeleton pixels, so a curation
    saved on an older bundle must select the same fibers after re-analysis.
    除外・連結のサイドカーはスケルトン画素を保存するため、古いバンドルで保存した
    キュレーションは再解析後も同じ繊維を選ばなければならない。
    """
    old = _as_format_1_0(synthetic_bundle, str(tmp_path / "old.b2z"))
    new_fibers = measure.measure_bundle(synthetic_bundle).fibers
    old_fibers = measure.measure_bundle(old).fibers
    assert [fiber_anchor(f) for f in new_fibers] == [fiber_anchor(f) for f in old_fibers]
    assert [fiber_track_pixels(f) for f in new_fibers] == \
        [fiber_track_pixels(f) for f in old_fibers]


def test_the_synthetic_fixture_is_not_empty(synthetic_bundle):
    """The fixture scan has to yield fibers for the tests above to mean anything."""
    assert os.path.exists(synthetic_bundle)
    assert len(measure.measure_bundle(synthetic_bundle).fibers) >= 2


def test_place_centerline_reports_width_reliability_and_crest():
    """
    Placing the line also reports W, whether W was measured, the reliable
    points, and the crest height, which is the section maximum.
    線を置くと、W、W が測定値か、信頼できる点、断面最大値である頂点高さも報告する。

    The crest is what a fiber's height means; a height interpolated at the
    line reads low wherever the line is beside the top, so the crest may never
    fall below that sample.
    頂点高さが繊維の高さの意味である。線の位置で補間した高さは線が頂部の脇にある
    ところで低く読むので、頂点高さがその標本を下回ることはあってはならない。
    """
    from lib.centerline import FALLBACK_WIDTH_PX, place_centerline, sample_height

    height = _ridge(5.0, FWHM, 0.0)
    x, y = _track(1.5)
    placed = place_centerline(height, x, y)

    assert placed.width_measured
    assert abs(placed.width_px - FWHM) < 1.5
    assert placed.reliable.shape == x.shape and placed.reliable.mean() > 0.8
    assert placed.crest.shape == x.shape
    at_line = sample_height(height, placed.x, placed.y)
    assert np.all(placed.crest >= at_line - 0.05)
    # On a Gaussian ridge of amplitude 5 the crest is the ridge top itself.
    # 振幅 5 のガウス稜線では、頂点高さは稜線の頂部そのものである。
    assert np.all(placed.crest[placed.reliable] > 4.85)

    # A flat image gives no half-maximum run, so the width is the fallback
    # and is reported as such rather than as a measurement.
    # 平坦な画像には半値区間が無いので、幅は代替値であり、測定値ではなくそのように
    # 報告される。
    flat = place_centerline(np.zeros(SHAPE), x, y)
    assert not flat.width_measured
    assert flat.width_px == FALLBACK_WIDTH_PX
