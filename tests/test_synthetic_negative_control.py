# -*- coding: utf-8 -*-
"""
Negative control for kink detection, against a centerline with a known answer.
キンク検出の負例対照。正解のわかっている中心線に対して検証する。

Every other check on kink detection in this repository compares the pipeline
against a real scan, where nobody knows how many kinks a fiber truly has, so a
change in the kink count cannot be read as better or worse. The scans built by
`synthetic_fibers` have an analytic centerline, so the answer is known by
construction: a straight, circular or tapering fiber has no kink anywhere, and
a two-armed fiber has exactly one at a known place. That makes a false
positive and a miss separately visible, which is the only way to tell an
improvement from a threshold that merely reports less.
本リポジトリの他のキンク検出の検査は、実スキャンとの比較である。実スキャンでは
繊維に本当は何点の折れがあるか誰も知らないため、キンク数の増減を「良くなった」
とも「悪くなった」とも読めない。`synthetic_fibers` が作る画像は中心線が解析
曲線なので、正解が構成上わかる。直線・円弧・先細りの繊維はどこにも折れが無く、
2 本腕の繊維は既知の位置にちょうど 1 点だけ折れを持つ。これにより偽陽性と
見落としが別々に見えるようになる。両者を分離することだけが、真の改善と「単に
報告数が減っただけ」のしきい値変更を区別する手段である。

Notes
-----
The scans carry the spatially correlated background roughness that the bundled
real specimens actually have (see `scripts/kink_false_positive_sweep.py` for
how the injected settings were matched to them). Without it the pipeline sees
a background no real scan has, and the test passes on conditions the software
never meets.
画像には、同梱の実試料が実際に持つ空間相関のある背景粗さを載せてある（注入値を
実試料へ合わせた経緯は `scripts/kink_false_positive_sweep.py` を参照）。これが
無いと、パイプラインは実スキャンには存在しない背景を見ることになり、ソフト
ウェアが決して遭遇しない条件でテストが通ってしまう。

The values asserted here are not recorded outputs to be updated when they
drift. Zero kinks on a smooth fiber is the correct answer, not a measurement,
so a failure means the detector changed for the worse — or, if the change was
deliberate, that the trade it made has to be stated.
ここで検証する値は、ずれたら更新する記録値ではない。平滑な繊維でキンク 0 点は
測定結果ではなく正解であり、失敗は検出器が悪化したことを意味する。意図的な
変更であったなら、その変更が何と引き換えたのかを明示する必要がある。
"""

import os

import numpy as np
import pytest
from scipy.spatial import cKDTree

import synthetic_fibers as sf
from lib import measure
from lib.pipeline import ProcParams, process_file

# Geometry shared by every case. 2 nm/px with a 3 nm fiber puts the pixel size
# to fiber width ratio in the same regime as the bundled Shimadzu and Bruker
# scans, so the digitisation the skeleton has to cope with is the real one.
# 全ケース共通の形状。2 nm/px・繊維径 3 nm は、画素サイズと繊維幅の比を同梱の
# 島津機・Bruker 機スキャンと同じ領域に置くため、スケルトンが相手にする量子化が
# 実データのものと同じになる。
SHAPE = (384, 384)
NM_PER_PX = 2.0
LENGTH_NM = 600.0

# Background matched to the bundled specimens; see the module docstring.
# 同梱試料に合わせた背景。モジュール docstring 参照。
BACKGROUND = dict(
    tip_radius_nm=10.0,
    noise_nm=0.05,
    line_noise_nm=0.03,
    tilt_nm=1.0,
    roughness_nm=0.40,
    roughness_corr_nm=120.0,
    roughness_hurst=0.6,
    seed=1,
)

# A detected kink counts as the known one within this distance of it. The scale
# is set by how well a polyline decomposition can localize a vertex at all,
# which is of order the apparent fiber width (about 10 nm here).
# 検出キンクがこの距離以内にあれば既知の折れと一致とみなす。この尺度は折れ線
# 分解が頂点をそもそもどれだけ局在化できるかで決まり、見かけの繊維幅（ここでは
# 約 10 nm）程度である。
MATCH_TOLERANCE_NM = 30.0

# Bound on how far the tracked centerline may sit from the true one. The
# bundled scans measure 0.5 to 1.7 nm under the same comparison, so this leaves
# room for ordinary variation while still failing on a centerline that has
# left the fiber.
# 追跡中心線が真の中心線からどれだけ離れてよいかの上限。同じ比較で同梱スキャンは
# 0.5〜1.7 nm を示すため、通常のばらつきには余裕を残しつつ、繊維から外れた中心線
# では失敗する。
MAX_CENTERLINE_ERROR_NM = 3.0

_GEOM = dict(shape=SHAPE, nm_per_px=NM_PER_PX)


def _smooth_cases():
    """
    Cases whose centerline is smooth everywhere, so the true kink count is zero.
    中心線がどこでも滑らかで、真のキンク数がゼロであるケース。

    The four shapes are not variations on one another. A straight fiber isolates
    the detector's noise floor; an arc asks whether curvature alone is reported
    as a bend; a tapering end reproduces the low, broad foot that segmentation
    admits at a real fiber tip; and a crossing produces the branch point at
    which the pipeline cuts the skeleton, which is where the bundled real scans
    put most of their questionable kinks.
    4 つの形状は互いの変種ではない。直線は検出器のノイズ床を切り分ける。円弧は
    曲率だけで折れと報告されないかを問う。先細り末端は、実際の繊維先端で
    セグメンテーションが取り込む低く広い裾を再現する。交差はパイプラインが
    スケルトンを切断する分岐点を作り、そこは同梱の実スキャンで疑わしいキンクが
    最も集中する場所である。
    """
    return {
        "straight": ([sf.straight_centerline(LENGTH_NM, **_GEOM)], {}),
        "arc_90deg": ([sf.arc_centerline(LENGTH_NM, LENGTH_NM / np.radians(90.0),
                                         **_GEOM)], {}),
        "tapering_end": ([sf.straight_centerline(LENGTH_NM, **_GEOM)],
                         {"taper_nm": 40.0}),
        "crossing_30deg": ([sf.straight_centerline(LENGTH_NM, **_GEOM),
                            sf.straight_centerline(LENGTH_NM, angle_deg=53.0,
                                                   **_GEOM)],
                           {"taper_nm": 40.0}),
    }


def _kinked_cases():
    """
    Cases with exactly one kink of a known interior angle at a known place.
    既知の内角の折れを、既知の位置にちょうど 1 点だけ持つケース。

    145 degrees sits below the pipeline's 150 degree default and must be found;
    165 degrees sits above it and must not be. Asserting only the first would
    be the recovery-only metric that any loosened threshold improves.
    145 度はパイプラインの既定 150 度を下回るので検出されなければならず、
    165 度は上回るので検出されてはならない。前者だけを検証するのは、しきい値を
    緩めれば必ず改善する「回収率のみの指標」になってしまう。
    """
    return {
        "kink_145deg": ([sf.kinked_centerline(LENGTH_NM, 145.0, **_GEOM)], {}),
        "gentle_165deg": ([sf.kinked_centerline(LENGTH_NM, 165.0, **_GEOM)], {}),
    }


def _analyze(centerlines, extra, out_dir, stem):
    """
    Render one case, run the real pipeline over it, and return its fibers.
    1 ケースを描画し、実際のパイプラインを実行して、その繊維を返す。

    The pipeline is driven through `process_file`, the same entry point GUI01
    and `cli.py process` use, so the test exercises the shipped path rather
    than a reassembled one.
    パイプラインは GUI01 と `cli.py process` が使うのと同じ入口 `process_file`
    経由で駆動する。組み直した経路ではなく出荷される経路を検証するためである。
    """
    scan = sf.render_scan(centerlines, shape=SHAPE, nm_per_px=NM_PER_PX,
                          **{**BACKGROUND, **extra})
    txt = sf.write_afm_text(scan, os.path.join(out_dir, stem + ".txt"))
    result = process_file(txt, ProcParams(), scan_size_um=scan.scan_size_um,
                          scan_size_source="manual")
    image = measure.load_tracking_image(result.bundle_path, NM_PER_PX, NM_PER_PX)
    return scan, image.fibers_in_image_parallel()


def _detected_kinks_xy(fibers):
    """
    Pixel coordinates of every detected kink, at the pixel-centre convention.
    検出された全キンクの画素座標。画素中心の慣例に合わせる。

    The half pixel matches what GUI04 applies when it draws a track over the
    image, so a detected kink and an analytic centerline are compared in one
    frame rather than two that differ by half a pixel.
    半画素は GUI04 が画像上にトラックを描くときに掛ける補正と同じである。これに
    より検出キンクと解析中心線を、半画素ずれた 2 つの座標系ではなく 1 つの座標系
    で比較できる。
    """
    xs, ys = [], []
    for fiber in fibers:
        bx, by = int(fiber.data[0]), int(fiber.data[1])
        idx = np.asarray(fiber.kink_indices, dtype=int)
        if idx.size:
            xs.append(fiber.xtrack[idx].astype(float) + bx + 0.5)
            ys.append(fiber.ytrack[idx].astype(float) + by + 0.5)
    if not xs:
        return np.empty(0), np.empty(0)
    return np.concatenate(xs), np.concatenate(ys)


def _centerline_error_nm(scan, fibers):
    """
    Distance from each tracked point to the nearest true centerline point.
    追跡された各点から、真の中心線上の最近傍点までの距離。
    """
    xs = np.concatenate([line.x for line in scan.centerlines])
    ys = np.concatenate([line.y for line in scan.centerlines])
    tree = cKDTree(np.column_stack([xs, ys]))
    errors = []
    for fiber in fibers:
        bx, by = int(fiber.data[0]), int(fiber.data[1])
        px = fiber.xtrack.astype(float) + bx + 0.5
        py = fiber.ytrack.astype(float) + by + 0.5
        errors.append(tree.query(np.column_stack([px, py]))[0] * scan.nm_per_px)
    return np.concatenate(errors) if errors else np.empty(0)


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    """
    Run the pipeline once per case and share the results across the tests.
    ケースごとにパイプラインを 1 回だけ実行し、結果をテスト間で共有する。
    """
    out_dir = str(tmp_path_factory.mktemp("negative_control"))
    cases = {}
    cases.update(_smooth_cases())
    cases.update(_kinked_cases())
    return {name: _analyze(lines, extra, out_dir, name)
            for name, (lines, extra) in cases.items()}


@pytest.mark.slow
@pytest.mark.parametrize("case", sorted(_smooth_cases()))
def test_a_smooth_fiber_carries_no_kink(analyzed, case):
    """
    A fiber with no tangent discontinuity must produce no kink at all.
    接線の不連続を持たない繊維は、キンクを 1 点も生じてはならない。
    """
    scan, fibers = analyzed[case]
    assert fibers, "the pipeline detected no fiber at all in case %r" % case
    kx, _ = _detected_kinks_xy(fibers)
    assert kx.size == 0, (
        "%d kink(s) reported on a smooth %s fiber, which has none" % (kx.size, case)
    )


@pytest.mark.slow
def test_the_known_kink_is_found_where_it_is(analyzed):
    """
    The one 145 degree bend must be reported, and at its own position.
    145 度の折れ 1 点は報告されなければならず、その位置で報告されねばならない。
    """
    scan, fibers = analyzed["kink_145deg"]
    kx, ky = _detected_kinks_xy(fibers)
    tx, ty = scan.true_kinks_xy
    assert tx.size == 1
    assert kx.size == 1, "expected exactly one kink, got %d" % kx.size
    distance_nm = float(np.hypot(kx[0] - tx[0], ky[0] - ty[0]) * scan.nm_per_px)
    assert distance_nm <= MATCH_TOLERANCE_NM, (
        "the kink was reported %.0f nm from the real bend" % distance_nm
    )


@pytest.mark.slow
def test_a_bend_above_the_threshold_is_not_a_kink(analyzed):
    """
    A 165 degree bend is gentler than the 150 degree default and must be ignored.
    165 度の曲がりは既定の 150 度より緩く、無視されなければならない。
    """
    scan, fibers = analyzed["gentle_165deg"]
    kx, _ = _detected_kinks_xy(fibers)
    assert kx.size == 0, "%d kink(s) reported on a 165 degree bend" % kx.size


@pytest.mark.slow
@pytest.mark.parametrize("case", sorted({**_smooth_cases(), **_kinked_cases()}))
def test_the_track_follows_the_true_centerline(analyzed, case):
    """
    The tracked centerline must stay on the fiber it was drawn from.
    追跡された中心線は、元になった繊維の上に留まらなければならない。
    """
    scan, fibers = analyzed[case]
    assert fibers, "the pipeline detected no fiber at all in case %r" % case
    error = _centerline_error_nm(scan, fibers)
    median_nm = float(np.median(error))
    assert median_nm <= MAX_CENTERLINE_ERROR_NM, (
        "median centerline error %.2f nm in case %s" % (median_nm, case)
    )
