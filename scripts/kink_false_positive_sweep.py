# -*- coding: utf-8 -*-
"""
Measure kink false positives and centerline error against a known answer.
既知の正解に対して、キンクの偽陽性と中心線誤差を測定する。

Runs the real preprocessing pipeline over the synthetic scans built by
`tests/synthetic_fibers.py`, whose centerline is an analytic curve, and scores
what came out against what went in. Two numbers come back for every condition
and they have to be read together:

* false positives per micrometre of detected contour length, on families that
  contain no kink at all;
* recall of the single known kink, on the family that contains exactly one.

A threshold tuned on either number alone moves the other one. Recall on its
own is the recovery-only metric that improves monotonically as a threshold
loosens, which is why this script refuses to print it without its cost.

`tests/synthetic_fibers.py` が作る、中心線が解析曲線である合成画像に対して実際
の前処理パイプラインを実行し、入力した真値と出力を突き合わせて採点する。各条件
について 2 つの数値が得られ、両者は必ず併せて読む必要がある。

* キンクを一切含まない族における、検出輪郭長 1 µm あたりの偽陽性数
* ちょうど 1 点含む族における、その既知キンクの再現率

どちらか一方だけで調整したしきい値は、必ずもう一方を動かす。再現率だけを見る
のは、しきい値を緩めれば単調に改善する「回収率のみの指標」であり、本スクリプト
がそれを対価なしに表示しない理由である。

Limitations
-----------
What this measures is a trade-off under known conditions, not an absolute
error rate for real data. The generated scans do **not** reproduce how often
the pipeline goes wrong on a real specimen: measured against the height ridge,
23 to 48 % of the kinks reported on the three bundled scans sit where the
ridge has no bend, while the smooth families here yield well under one false
positive per fiber. The gap is in the images, not in the scoring — a generated
scan carries background roughness matched to a real one, but not its
sub-threshold debris, its scan-line glitches, or the density at which real
fibrils merge and cross.

So read a number from here as "this change made the detector better or worse
than it was", never as "the detector is right x % of the time on real data".
Setting a threshold to hit a target false-positive rate measured here would be
fitting to the generator. A threshold belongs to something measurable in the
image being analyzed — the local line width, or the uncertainty of the ridge
position — so that it adapts per scan instead of being a number chosen once.

ここで測れるのは既知条件下でのトレードオフであり、実データに対する絶対的な
誤り率ではない。生成画像は、実試料でパイプラインがどれだけの頻度で誤るかを
**再現していない**。高さ稜線に対して測ると、同梱の実スキャン 3 種で報告される
キンクの 23〜48 % は稜線に曲がりの無い位置にあるが、ここの平滑族が出す偽陽性は
繊維 1 本あたり 1 点を大きく下回る。差は採点ではなく画像の側にある。生成画像は
実試料に合わせた背景粗さを持つが、しきい値以下のデブリも、走査線グリッチも、
実際のフィブリルが融合・交差する密度も持たない。

したがってここの数値は「この変更で検出器が以前より良くなったか悪くなったか」
として読むこと。「実データで x % 正しい」と読んではならない。ここで測った偽陽性率
の目標値に合わせてしきい値を決めるのは、生成器への当てはめである。しきい値は
解析対象の画像から測れる量——局所的な線幅、あるいは稜線位置の不確かさ——に
紐づけ、一度選んだ数字ではなく走査ごとに適応する形にすべきである。

Usage
-----
``.venv\\Scripts\\python.exe scripts/kink_false_positive_sweep.py --quick``

Outputs a CSV and, with ``--figures``, overlay images under the output
directory (``.tmp/kink_fp_sweep`` by default).
出力は CSV と、``--figures`` 指定時は重ね描き画像で、出力ディレクトリ
（既定は ``.tmp/kink_fp_sweep``）に書き込まれる。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import cKDTree

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# The generator is test support, not a shipped library, so it lives under
# tests/ and is imported by path rather than as a package.
# 生成モジュールは配布ライブラリではなくテスト支援なので tests/ に置き、
# パッケージとしてではなくパス指定で import する。
_TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import synthetic_fibers as sf  # noqa: E402
from lib import measure  # noqa: E402
from lib.pipeline import ProcParams, process_file  # noqa: E402

# Default geometry of a generated scan. 2 nm/px with a 3 nm fiber reproduces
# the pixel-size-to-fiber-width ratio of the bundled Shimadzu and Bruker
# scans, so the digitisation regime is the same one the real data sits in.
# 生成画像の既定形状。2 nm/px・繊維径 3 nm は同梱の島津機・Bruker 機スキャンに
# おける画素サイズと繊維幅の比を再現するため、量子化の条件が実データと同じ域に
# 入る。
DEFAULT_SHAPE: Tuple[int, int] = (384, 384)
DEFAULT_NM_PER_PX: float = 2.0
DEFAULT_LENGTH_NM: float = 600.0
DEFAULT_FIBER_DIAMETER_NM: float = 3.0
DEFAULT_TIP_RADIUS_NM: float = 10.0
DEFAULT_LINE_NOISE_NM: float = 0.03
DEFAULT_TILT_NM: float = 1.0

# Spatially correlated background roughness. Injected before the pipeline
# runs; the background stage removes part of it, so the value that matters is
# what survives into the calibrated image. These three numbers were chosen by
# sweeping the injected settings and comparing the calibrated result against
# the bundled scans: 0.40 nm at a 120 nm outer scale and H=0.6 leaves 0.263 nm
# of background deviation, against 0.266 nm measured on the higher-plant TOC
# scan (0.15 nm on tunicate, 0.46 nm on Bruker NDTOC). Independent pixel noise
# alone leaves 0.05 nm and no correlation at all, a regime no real scan sits
# in, so a control generated without roughness would certify a detector
# against conditions it never meets.
# 空間相関を持つ背景粗さ。パイプライン実行前に注入するが、背景段がその一部を
# 除去するため、意味を持つのは較正済み画像に残る量である。この 3 つの値は、注入
# 設定を掃引して較正後の結果を同梱スキャンと比較して選んだ。外側スケール 120 nm・
# H=0.6 で 0.40 nm を注入すると較正後の背景標準偏差は 0.263 nm となり、higher-
# plant TOC スキャンでの実測 0.266 nm に一致する（tunicate は 0.15 nm、Bruker
# NDTOC は 0.46 nm）。画素独立ノイズだけでは 0.05 nm かつ無相関で、これは実
# スキャンが存在しない領域であり、粗さ無しで生成した対照は検出器が決して遭遇
# しない条件で合格を出してしまう。
#
# The amplitude matches; the shape does not, and clutter is why. A stationary
# random background put through the background stage acquires a negative
# autocorrelation lobe around 25 nm (the stage subtracts a smoothed copy of
# it), while every real scan stays positive out to 50 nm and beyond. The real
# long-range correlation is not substrate roughness at all: it comes from
# sub-threshold *objects* — low fibrils and debris the segmenter never
# detects, plainly visible as elongated bright streaks in a Bruker background
# crop. On a drop-cast dispersion those are expected, which is what the
# `clutter` family below adds.
# 振幅は一致するが形は一致せず、その理由は散乱物である。定常なランダム背景を
# 背景段に通すと 25 nm 付近に負の自己相関ローブが生じる（背景段がその平滑コピー
# を差し引くため）が、実スキャンはどれも 50 nm 以遠まで正のままである。実際の
# 長距離相関は基板の粗さではなく、しきい値以下の「物体」——セグメンタが検出しない
# 低いフィブリルやデブリ。Bruker の背景クロップでは細長い明部としてはっきり
# 見える——に由来する。分散液のドロップキャストではそれが当然であり、下の
# `clutter` 族が加えるのはこれである。
DEFAULT_ROUGHNESS_NM: float = 0.40
DEFAULT_ROUGHNESS_CORR_NM: float = 120.0
DEFAULT_ROUGHNESS_HURST: float = 0.6

# A detected kink counts as the true one when it lands within this distance of
# it. The scale is set by how well the decomposition can localize a vertex at
# all, which is of order the apparent fiber width (about 10 nm here), so a few
# widths is generous without letting a kink at the far end of the fiber match.
# 検出キンクが真のキンクからこの距離以内にあれば一致とみなす。この尺度は分解が
# 頂点をそもそもどれだけ局在化できるかで決まり、それは見かけの繊維幅（ここでは
# 約 10 nm）程度である。その数倍なら十分に緩く、かつ繊維の反対端のキンクが
# 一致してしまうことはない。
DEFAULT_MATCH_TOLERANCE_NM: float = 30.0


@dataclass
class Condition:
    """
    One generated scan and the ground truth it should be scored against.
    生成した 1 枚の画像と、それを採点するための真値。

    Attributes
    ----------
    family
        Centerline family name, used to group results.
        中心線の族の名前。結果の集約に用いる。
    label
        Human-readable description of the varied parameter.
        変化させたパラメータの可読な説明。
    scan
        The rendered scan carrying the ground-truth centerlines.
        真値中心線を保持する描画済み画像。
    knobs
        Varied parameter values, written verbatim into the CSV.
        変化させたパラメータ値。CSV にそのまま書き出す。
    """

    family: str
    label: str
    scan: "sf.SyntheticScan"
    knobs: Dict[str, float] = field(default_factory=dict)


def build_conditions(
    seeds: Sequence[int],
    *,
    shape: Tuple[int, int] = DEFAULT_SHAPE,
    nm_per_px: float = DEFAULT_NM_PER_PX,
    length_nm: float = DEFAULT_LENGTH_NM,
) -> List[Condition]:
    """
    Build the sweep: noise, curvature, tip radius, and known kink angles.
    掃引条件を構築する。ノイズ、曲率、探針半径、既知のキンク角。

    Parameters
    ----------
    seeds
        Noise seeds; each condition is repeated once per seed so a reported
        rate is not one draw of the noise.
        ノイズの乱数シード。各条件をシードごとに繰り返すため、報告される率が
        ノイズの 1 回の引きに依存しない。
    shape, nm_per_px, length_nm
        Image size, pixel size, and fiber contour length.
        画像サイズ、画素サイズ、繊維の輪郭長。

    Returns
    -------
    list of Condition
        Every generated scan, in a stable order.
        生成した全画像。順序は安定。

    Notes
    -----
    The arc radii are chosen so the fiber's total turn spans the range from
    barely bent to a quarter turn and beyond: at 600 nm of contour, radii of
    1200, 600, 300 and 150 nm turn the fiber by 29, 57, 115 and 229 degrees.
    A detector with no length scale reports the sharp end of that range as a
    kink even though the curve has no tangent discontinuity anywhere.
    円弧の半径は、繊維全体の回転角がわずかな曲がりから 4 分の 1 回転超までを
    覆うように選んである。輪郭長 600 nm に対し半径 1200 / 600 / 300 / 150 nm は
    それぞれ 29 / 57 / 115 / 229 度回転する。長さスケールを持たない検出器は、
    接線の不連続がどこにも無いにもかかわらず、この鋭い側をキンクとして報告する。
    """
    base = dict(
        shape=shape,
        nm_per_px=nm_per_px,
        fiber_diameter_nm=DEFAULT_FIBER_DIAMETER_NM,
        tip_radius_nm=DEFAULT_TIP_RADIUS_NM,
        line_noise_nm=DEFAULT_LINE_NOISE_NM,
        tilt_nm=DEFAULT_TILT_NM,
        roughness_nm=DEFAULT_ROUGHNESS_NM,
        roughness_corr_nm=DEFAULT_ROUGHNESS_CORR_NM,
        roughness_hurst=DEFAULT_ROUGHNESS_HURST,
    )
    geom = dict(shape=shape, nm_per_px=nm_per_px)
    out: List[Condition] = []

    for seed in seeds:
        # Pure noise floor: no curvature, no kink, nothing to detect.
        for noise in (0.02, 0.05, 0.10, 0.20):
            line = sf.straight_centerline(length_nm, **geom)
            out.append(Condition(
                "straight", "noise=%.2f nm" % noise,
                sf.render_scan([line], **{**base, "noise_nm": noise, "seed": seed}),
                {"noise_nm": noise},
            ))

        # Tip broadening at fixed noise; 0 nm is the ideal-probe control.
        for tip in (0.0, 4.0, 20.0):
            line = sf.straight_centerline(length_nm, **geom)
            out.append(Condition(
                "straight", "tip=%.0f nm" % tip,
                sf.render_scan([line], **{**base, "tip_radius_nm": tip,
                                          "noise_nm": 0.05, "seed": seed}),
                {"tip_radius_nm": tip, "noise_nm": 0.05},
            ))

        # Constant curvature, no kink. The sweep is parameterized by the
        # fiber's total turn rather than by its radius, because a radius swept
        # at fixed contour length curls the fiber into a ring: at 600 nm of
        # contour, a 100 nm radius turns 344 degrees, and the object being
        # scored stops being a fibril. Total turn keeps every member of the
        # family a plausible dispersed fibril while still spanning from barely
        # bent to sharply bent.
        # 曲率一定、キンク無し。掃引は半径ではなく繊維全体の回転角で行う。輪郭長
        # を固定して半径を掃引すると繊維がリングに丸まってしまうからである
        # （輪郭長 600 nm では半径 100 nm で 344 度回転し、採点対象がフィブリル
        # ではなくなる）。回転角で刻めば、族のどの条件も分散したフィブリルとして
        # あり得る形を保ったまま、わずかな曲がりから鋭い曲がりまでを覆える。
        for turn_deg in (30.0, 60.0, 90.0, 120.0, 150.0):
            radius = length_nm / np.radians(turn_deg)
            line = sf.arc_centerline(length_nm, radius, **geom)
            out.append(Condition(
                "arc", "turn=%.0f deg (R=%.0f nm)" % (turn_deg, radius),
                sf.render_scan([line], **{**base, "noise_nm": 0.05, "seed": seed}),
                {"turn_deg": turn_deg, "radius_nm": round(radius, 1), "noise_nm": 0.05},
            ))

        # Tapering ends, no kink. A real fibril thins over its last tens of
        # nanometers, and after tip dilation that end is a low broad foot the
        # segmenter admits. This is the family that carries the failure the
        # real scans showed most often, and a square-ended cylinder cannot
        # produce it.
        # 先細りする末端、キンク無し。実際のフィブリルは末端数十 nm で細くなり、
        # 探針 dilation 後のその末端はセグメンタが取り込む低く広い裾になる。実
        # スキャンで最も多く現れた故障を担う族であり、角で終わる円柱では作れない。
        for taper in (20.0, 40.0, 80.0):
            line = sf.straight_centerline(length_nm, **geom)
            out.append(Condition(
                "taper", "straight taper=%.0f nm" % taper,
                sf.render_scan([line], **{**base, "noise_nm": 0.05,
                                          "taper_nm": taper, "seed": seed}),
                {"taper_nm": taper, "noise_nm": 0.05},
            ))
            curved = sf.arc_centerline(length_nm, length_nm / np.radians(90.0), **geom)
            out.append(Condition(
                "taper", "arc90 taper=%.0f nm" % taper,
                sf.render_scan([curved], **{**base, "noise_nm": 0.05,
                                            "taper_nm": taper, "seed": seed}),
                {"taper_nm": taper, "turn_deg": 90.0, "noise_nm": 0.05},
            ))

        # Correlated background roughness, no kink. Swept across the range the
        # bundled specimens span, on a straight fiber, a bent one, and a
        # tapering one, so an effect can be attributed to roughness alone
        # rather than to roughness interacting with one particular shape.
        # 相関を持つ背景粗さ、キンク無し。同梱試料が覆う範囲を、直線・曲がり・
        # 先細りの各形状について掃引する。粗さが特定の形状と相互作用した結果では
        # なく、粗さ単独の効果として帰属できるようにするためである。
        for rough in (0.0, 0.15, 0.30, 0.45):
            shapes = (
                ("straight", sf.straight_centerline(length_nm, **geom), {}),
                ("arc90", sf.arc_centerline(length_nm, length_nm / np.radians(90.0), **geom), {}),
                ("taper40", sf.straight_centerline(length_nm, **geom), {"taper_nm": 40.0}),
            )
            for shape_tag, line, extra in shapes:
                out.append(Condition(
                    "roughness", "%s rough=%.2f nm" % (shape_tag, rough),
                    sf.render_scan([line], **{**base, "noise_nm": 0.05,
                                              "roughness_nm": rough,
                                              "seed": seed, **extra}),
                    {"roughness_nm": rough, "noise_nm": 0.05, **extra},
                ))

        # Two fibers crossing: no kink anywhere, but the merged mask and the
        # branch-point cut are present, and unequal heights make the merged
        # mask asymmetric about both ridges. A shallow crossing angle widens
        # the merged region the most, which is the geometry the real scans
        # showed a wandering skeleton in.
        # 繊維 2 本の交差。キンクはどこにも無いが、融合マスクと分岐点による切断
        # が存在し、高さが異なれば融合マスクはどちらの稜線に対しても非対称になる。
        # 浅い交差角ほど融合領域は広くなり、これは実スキャンでスケルトンが蛇行
        # していた形状そのものである。
        for cross_deg in (15.0, 30.0, 60.0, 90.0):
            first = sf.straight_centerline(length_nm, **geom)
            second = sf.straight_centerline(length_nm, angle_deg=23.0 + cross_deg, **geom)
            out.append(Condition(
                "crossing", "angle=%.0f deg equal" % cross_deg,
                sf.render_scan([first, second],
                               **{**base, "noise_nm": 0.05, "taper_nm": 40.0,
                                  "seed": seed}),
                {"crossing_angle_deg": cross_deg, "height_ratio": 1.0,
                 "taper_nm": 40.0, "noise_nm": 0.05},
            ))
            out.append(Condition(
                "crossing", "angle=%.0f deg 3:1.5 nm" % cross_deg,
                sf.render_scan([first, second],
                               **{**base, "noise_nm": 0.05, "taper_nm": 40.0,
                                  "fiber_diameter_nm": (3.0, 1.5), "seed": seed}),
                {"crossing_angle_deg": cross_deg, "height_ratio": 0.5,
                 "taper_nm": 40.0, "noise_nm": 0.05},
            ))

        # Reversing curvature, no kink.
        for amp, wav in ((10.0, 300.0), (25.0, 300.0), (40.0, 300.0)):
            line = sf.sine_centerline(length_nm, amp, wav, **geom)
            out.append(Condition(
                "sine", "A=%.0f lam=%.0f (Rmin=%.0f nm)" % (amp, wav, line.curvature_radius_nm),
                sf.render_scan([line], **{**base, "noise_nm": 0.05, "seed": seed}),
                {"amplitude_nm": amp, "wavelength_nm": wav,
                 "min_radius_nm": line.curvature_radius_nm, "noise_nm": 0.05},
            ))

        # A target fiber among sub-threshold clutter: short, low, smooth
        # fibrils and fragments scattered at random, as a drop-cast dispersion
        # leaves them. Every centerline here is smooth, so the true kink count
        # is still zero and any kink at all is a false positive. This is the
        # family that reproduces what the real scans actually do wrong: a low
        # neighbour merges into the target's mask from one side, the mask stops
        # being symmetric about the ridge, and the medial axis follows the mask
        # instead of the fiber.
        # しきい値以下の散乱物の中に置いた対象繊維。分散液のドロップキャストが
        # 残すような、短く低く滑らかなフィブリルや断片をランダムに撒く。ここの
        # 中心線はすべて平滑なので真のキンク数はやはりゼロであり、検出された
        # キンクはすべて偽陽性である。実スキャンで実際に起きている誤りを再現する
        # のはこの族である。低い隣接物が対象のマスクへ片側から融合し、マスクが
        # 稜線に対して対称でなくなり、medial axis が繊維ではなくマスクに従う。
        for n_clutter in (5, 15, 30):
            rng = np.random.default_rng(1000 * seed + n_clutter)
            target = sf.straight_centerline(length_nm, **geom)
            lines = [target]
            diameters = [DEFAULT_FIBER_DIAMETER_NM]
            for _ in range(n_clutter):
                # Low and gently curved: a neighbour has to stay below what
                # the segmenter detects for this family to test what it is
                # meant to test. A clutter fibril tall enough to be traced is
                # simply one more smooth fiber — still a valid negative
                # control, but it exercises curvature, not mask asymmetry.
                # Its curvature is bounded to what a dispersed fibril plausibly
                # has, so a false positive here cannot be blamed on a hairpin
                # nobody would deposit.
                # 低く、緩やかに曲がっている。この族が意図した対象を試すには、
                # 隣接物がセグメンタの検出閾以下に留まる必要がある。追跡される
                # ほど高い散乱フィブリルは単にもう 1 本の平滑な繊維であり、負例
                # としては有効だが、試すのはマスクの非対称性ではなく曲率になって
                # しまう。曲率も分散したフィブリルとしてあり得る範囲に抑え、ここ
                # での偽陽性を「誰も置かないようなヘアピン」のせいにできないよう
                # にする。
                span = float(rng.uniform(100.0, 400.0))
                turn = float(rng.uniform(5.0, 60.0))
                centre = (float(rng.uniform(0.15, 0.85)) * shape[1],
                          float(rng.uniform(0.15, 0.85)) * shape[0])
                lines.append(sf.arc_centerline(
                    span, span / np.radians(turn),
                    angle_deg=float(rng.uniform(0.0, 360.0)),
                    center_px=centre, **geom))
                diameters.append(float(rng.uniform(0.3, 1.2)))
            out.append(Condition(
                "clutter", "n=%d neighbours" % n_clutter,
                sf.render_scan(lines, **{**base, "noise_nm": 0.05,
                                         "taper_nm": 40.0,
                                         "fiber_diameter_nm": diameters,
                                         "seed": seed}),
                {"n_clutter": n_clutter, "taper_nm": 40.0, "noise_nm": 0.05},
            ))

        # Exactly one kink, spanning the 150 deg default threshold.
        for angle in (120.0, 135.0, 145.0, 155.0, 165.0):
            line = sf.kinked_centerline(length_nm, angle, **geom)
            out.append(Condition(
                "kinked", "interior=%.0f deg" % angle,
                sf.render_scan([line], **{**base, "noise_nm": 0.05, "seed": seed}),
                {"interior_angle_deg": angle, "noise_nm": 0.05},
            ))
    return out


def _ground_truth_tree(scan: "sf.SyntheticScan") -> cKDTree:
    """
    KD-tree over every ground-truth centerline sample, in pixel coordinates.
    全真値中心線サンプルの KD 木（画素座標）。
    """
    xs = np.concatenate([line.x for line in scan.centerlines])
    ys = np.concatenate([line.y for line in scan.centerlines])
    return cKDTree(np.column_stack([xs, ys]))


def evaluate(
    condition: Condition,
    work_dir: str,
    params: ProcParams,
    *,
    stem: str,
    tolerance_nm: float = DEFAULT_MATCH_TOLERANCE_NM,
) -> Dict[str, object]:
    """
    Run the pipeline on one condition and score it against the ground truth.
    1 条件についてパイプラインを実行し、真値に対して採点する。

    Parameters
    ----------
    condition
        The generated scan and its ground truth.
        生成した画像とその真値。
    work_dir
        Directory the input text and pipeline outputs are written to.
        入力テキストとパイプライン出力を書き出すディレクトリ。
    params
        Analysis parameters; the caller's defaults are what is under test.
        解析パラメータ。試験対象は呼び出し側の既定値である。
    stem
        Unique file stem for this run.
        この実行に固有のファイル名幹。
    tolerance_nm
        Distance within which a detected kink matches the true one.
        検出キンクが真のキンクと一致したとみなす距離。

    Returns
    -------
    dict
        One flat record per run, ready to be written as a CSV row.
        1 実行あたり 1 件の平坦なレコード。CSV の 1 行としてそのまま書ける。

    Notes
    -----
    Track coordinates are compared at ``xtrack + 0.5`` because a track index
    names a pixel while the ground truth is a continuous curve; the half pixel
    is the same shift GUI04 applies when it draws a track over the image.
    トラック座標は ``xtrack + 0.5`` で比較する。トラックの添字は画素を指すのに
    対し真値は連続曲線であるためで、この半画素は GUI04 が画像上にトラックを
    描くときに掛けるのと同じ補正である。
    """
    scan = condition.scan
    nm = scan.nm_per_px
    txt_path = sf.write_afm_text(scan, os.path.join(work_dir, stem + ".txt"))
    result = process_file(
        txt_path, params,
        scan_size_um=scan.scan_size_um, scan_size_source="manual",
    )
    image = measure.load_tracking_image(result.bundle_path, nm, nm)
    fibers = image.fibers_in_image_parallel()

    record: Dict[str, object] = {
        "family": condition.family,
        "label": condition.label,
        "seed": scan.seed,
        "nm_per_px": nm,
        "true_length_nm": round(scan.true_length_nm, 1),
        "true_kinks": int(len(scan.true_kinks_xy[0])),
        "n_fibers": len(fibers),
    }
    record.update({k: v for k, v in condition.knobs.items()})

    if not fibers:
        record.update({
            "detected_length_nm": 0.0, "kinks_detected": 0,
            "true_positive": 0, "false_positive": 0,
            "fp_per_um": float("nan"), "recall": float("nan"),
            "centerline_err_med_nm": float("nan"),
            "centerline_err_p90_nm": float("nan"),
            "centerline_err_max_nm": float("nan"),
        })
        return record

    tree = _ground_truth_tree(scan)
    errors: List[np.ndarray] = []
    kink_x: List[np.ndarray] = []
    kink_y: List[np.ndarray] = []
    detected_length = 0.0
    for fiber in fibers:
        bx, by = int(fiber.data[0]), int(fiber.data[1])
        px = fiber.xtrack.astype(float) + bx + 0.5
        py = fiber.ytrack.astype(float) + by + 0.5
        errors.append(tree.query(np.column_stack([px, py]))[0] * nm)
        detected_length += float(fiber.length)
        idx = np.asarray(fiber.kink_indices, dtype=int)
        if idx.size:
            kink_x.append(px[idx])
            kink_y.append(py[idx])

    err = np.concatenate(errors)
    kx = np.concatenate(kink_x) if kink_x else np.empty(0)
    ky = np.concatenate(kink_y) if kink_y else np.empty(0)

    true_x, true_y = scan.true_kinks_xy
    if true_x.size and kx.size:
        d_nm = np.hypot(kx[:, None] - true_x[None, :],
                        ky[:, None] - true_y[None, :]) * nm
        matched_detection = d_nm.min(axis=1) <= tolerance_nm
        matched_truth = d_nm.min(axis=0) <= tolerance_nm
        tp = int(matched_truth.sum())
        fp = int((~matched_detection).sum())
    else:
        tp = 0
        fp = int(kx.size)

    length_um = detected_length / 1000.0
    record.update({
        "detected_length_nm": round(detected_length, 1),
        "kinks_detected": int(kx.size),
        "true_positive": tp,
        "false_positive": fp,
        "fp_per_um": round(fp / length_um, 3) if length_um > 0 else float("nan"),
        "recall": (round(tp / true_x.size, 3) if true_x.size else float("nan")),
        "centerline_err_med_nm": round(float(np.median(err)), 3),
        "centerline_err_p90_nm": round(float(np.percentile(err, 90)), 3),
        "centerline_err_max_nm": round(float(err.max()), 3),
        "_bundle": result.bundle_path,
        "_kink_xy": (kx, ky),
    })
    return record


def summarize(records: Sequence[Dict[str, object]]) -> List[str]:
    """
    Group runs by family and label and format one line per condition.
    実行結果を族とラベルで集約し、条件ごとに 1 行へ整形する。
    """
    order: List[Tuple[str, str]] = []
    groups: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    for rec in records:
        key = (str(rec["family"]), str(rec["label"]))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)

    lines = ["%-9s %-28s %5s %7s %7s %7s %9s %9s %9s"
             % ("family", "condition", "fib", "kinks", "TP", "FP",
                "FP/um", "err_med", "err_p90")]
    for key in order:
        rows = groups[key]

        def mean(name: str, _rows: List[Dict[str, object]] = rows) -> float:
            """
            Mean over replicates, tolerating a condition that detected nothing.
            繰り返しにわたる平均。何も検出できなかった条件も許容する。

            A run with no fiber has no rate and no centerline error to report,
            so those columns are NaN by design; averaging them with `nanmean`
            would warn on an all-NaN slice, and the honest value is NaN.
            繊維を検出できなかった実行には報告すべき率も中心線誤差も無いため、
            該当カラムは設計上 NaN である。`nanmean` はすべて NaN のスライスで
            警告を出すが、正直な値は NaN そのものである。
            """
            values = np.array([float(r.get(name, np.nan)) for r in _rows], dtype=float)
            finite = values[np.isfinite(values)]
            return float(finite.mean()) if finite.size else float("nan")

        lines.append("%-9s %-28s %5.1f %7.1f %7.1f %7.1f %9.2f %9.2f %9.2f"
                     % (key[0], key[1][:28],
                        mean("n_fibers"), mean("kinks_detected"),
                        mean("true_positive"), mean("false_positive"),
                        mean("fp_per_um"),
                        mean("centerline_err_med_nm"),
                        mean("centerline_err_p90_nm")))
    return lines


def write_csv(records: Sequence[Dict[str, object]], path: str) -> None:
    """
    Write every run as one CSV row, dropping the private object columns.
    各実行を CSV の 1 行として書き出す。先頭が下線の内部カラムは除く。
    """
    rows = [{k: v for k, v in rec.items() if not k.startswith("_")} for rec in records]
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def render_overlays(
    records: Sequence[Dict[str, object]],
    conditions: Sequence[Condition],
    path: str,
    *,
    per_family: int = 2,
) -> Optional[str]:
    """
    Draw detections over the calibrated height image for a few conditions.
    いくつかの条件について、較正高さ像の上に検出結果を重ねて描く。

    Notes
    -----
    The overlay is drawn on the calibrated height image, never on a stage
    output, because a mask or a skeleton is itself a detection and comparing
    one detection against another cannot show which is right.
    重ね描きは較正高さ像の上に行い、ステージ出力の上には描かない。マスクや
    スケルトンはそれ自体が検出結果であり、検出結果どうしを比べてもどちらが
    正しいかは示せないからである。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from lib.blosc2_io import load_bundle

    # Show each family's worst runs, not its first ones. A figure of the runs
    # that happened to be generated first would document the easy cases; the
    # question a reader has is what the detector does where it fails.
    # 各族の最悪の実行を示す。先に生成された実行の図は簡単な条件を記録するだけ
    # であり、読み手が知りたいのは検出器が失敗する場所での挙動である。
    def severity(pair: Tuple[Dict[str, object], Condition]) -> Tuple[float, float]:
        rec = pair[0]
        fp = float(rec.get("false_positive", 0) or 0)
        err = float(rec.get("centerline_err_p90_nm", 0) or 0)
        return (fp, err if np.isfinite(err) else 0.0)

    by_family: Dict[str, List[Tuple[Dict[str, object], Condition]]] = {}
    for rec, cond in zip(records, conditions):
        if "_bundle" not in rec:
            continue
        by_family.setdefault(str(rec["family"]), []).append((rec, cond))
    picked: List[Tuple[Dict[str, object], Condition]] = []
    for family in by_family:
        ranked = sorted(by_family[family], key=severity, reverse=True)
        picked.extend(ranked[:per_family])
    if not picked:
        return None

    ncol = 4
    nrow = int(np.ceil(len(picked) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 5.4 * nrow), dpi=105)
    axes = np.atleast_1d(axes).ravel()
    for ax in axes:
        ax.axis("off")
    for ax, (rec, cond) in zip(axes, picked):
        bundle = load_bundle(str(rec["_bundle"]))
        cal = bundle["calibrated"]
        lo = float(np.percentile(cal, 3))
        hi = float(np.percentile(cal, 99.9))
        ax.axis("on")
        ax.imshow(cal, cmap="afmhot", vmin=lo, vmax=hi, aspect="equal",
                  interpolation="bilinear")
        for line in cond.scan.centerlines:
            ax.plot(line.x, line.y, color="deepskyblue", lw=1.6, alpha=0.9)
            if line.kink_indices.size:
                ax.scatter(line.x[line.kink_indices], line.y[line.kink_indices],
                           facecolors="none", edgecolors="deepskyblue", s=340,
                           linewidths=2.2, zorder=6)
        image = measure.load_tracking_image(str(rec["_bundle"]),
                                            cond.scan.nm_per_px, cond.scan.nm_per_px)
        for fiber in image.fibers_in_image_parallel():
            bx, by = int(fiber.data[0]), int(fiber.data[1])
            ax.plot(fiber.xtrack + bx + 0.5, fiber.ytrack + by + 0.5,
                    color="lime", lw=1.0, alpha=0.9)
        kx, ky = rec["_kink_xy"]  # type: ignore[assignment]
        if len(kx):
            ax.scatter(kx, ky, c="magenta", s=120, marker="X", zorder=8,
                       edgecolors="k", linewidths=0.7)
        ax.set_title("%s  %s\ntrue kinks %s / detected %s (FP %s)"
                     % (rec["family"], rec["label"], rec["true_kinks"],
                        rec["kinks_detected"], rec["false_positive"]), fontsize=9)
        ax.tick_params(labelsize=7)
    fig.suptitle("blue = ground-truth centerline and true kink (circle); "
                 "lime = detected track; magenta X = detected kink; "
                 "background = calibrated height", fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path)
    plt.close(fig)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Run the sweep and write the CSV, the summary, and optional overlays.
    掃引を実行し、CSV・要約・任意の重ね描き画像を書き出す。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, ".tmp", "kink_fp_sweep"),
                        help="output directory (default: .tmp/kink_fp_sweep)")
    parser.add_argument("--seeds", type=int, default=3,
                        help="noise replicates per condition (default: 3)")
    parser.add_argument("--quick", action="store_true",
                        help="one replicate per condition")
    parser.add_argument("--figures", action="store_true",
                        help="also render detection overlays on the height image")
    parser.add_argument("--tolerance-nm", type=float, default=DEFAULT_MATCH_TOLERANCE_NM,
                        help="distance within which a detected kink matches the true one")
    args = parser.parse_args(argv)

    seeds = [1] if args.quick else list(range(1, args.seeds + 1))
    out_dir = os.path.abspath(args.out)
    work_dir = os.path.join(out_dir, "work")
    os.makedirs(work_dir, exist_ok=True)

    conditions = build_conditions(seeds)
    params = ProcParams()
    records: List[Dict[str, object]] = []
    started = time.time()
    for i, cond in enumerate(conditions):
        stem = "%s_%03d" % (cond.family, i)
        record = evaluate(cond, work_dir, params, stem=stem,
                          tolerance_nm=args.tolerance_nm)
        records.append(record)
        print("[%3d/%3d] %-9s %-28s fibers=%s kinks=%s FP=%s err_med=%s nm"
              % (i + 1, len(conditions), cond.family, cond.label[:28],
                 record["n_fibers"], record["kinks_detected"],
                 record["false_positive"], record["centerline_err_med_nm"]),
              flush=True)

    csv_path = os.path.join(out_dir, "kink_fp_sweep.csv")
    write_csv(records, csv_path)
    print("\n".join(summarize(records)))
    print("\nCSV: %s" % csv_path)
    if args.figures:
        fig_path = render_overlays(records, conditions,
                                   os.path.join(out_dir, "overlays.png"))
        print("overlays: %s" % fig_path)
    print("elapsed %.1f s" % (time.time() - started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
