# -*- coding: utf-8 -*-
"""
Sweep the kink rule over apparent width and noise on scans with a known answer.
正解のわかる合成画像で、見かけ幅とノイズにわたってキンク規則を掃引する。

`scripts/kink_false_positive_sweep.py` varies the specimen at one pixel size.
This script varies what the rule is scaled by: the apparent width W in
pixels, from a coarse 3 px to a fine 16 px, crossed with the pixel noise. For
every scan the real pipeline runs once, the traced lines are then re-judged by
each `KinkDetector` variant, and three things are scored against the analytic
centerline: false positives per micrometre on the smooth families, recall of
the one known kink on the kinked families (including a 165 degree bend that
must not be reported), and the error of the reported angle, for both the
arm-fitted interior angle and the excess turning.
`scripts/kink_false_positive_sweep.py` は 1 つの画素サイズで試料を変える。本
スクリプトは規則の尺度そのもの、すなわち画素単位の見かけ幅 W を粗い 3 px から
細かい 16 px まで変え、画素ノイズと掛け合わせる。各画像について実際のパイプ
ラインを 1 回走らせ、追跡した線を各 `KinkDetector` 変種で判定し直し、解析的な
中心線に対して 3 つを採点する。平滑族での 1 µm あたりの偽陽性、キンク族での
既知の 1 点の再現率（報告してはならない 165 度の折れを含む）、および報告した
角度の誤差（腕当てはめの内角と超過回転の両方）である。

Usage
-----
``.venv\\Scripts\\python.exe scripts/kink_rule_sweep.py --quick``

Writes ``sweep.csv`` (one row per scan and variant) and prints a summary
table under the output directory (``.tmp/kink_rule_sweep`` by default).
``--jobs N`` sets how many worker processes analyze the scans; the result does
not depend on it.
出力ディレクトリ（既定 ``.tmp/kink_rule_sweep``）に ``sweep.csv``（画像 × 変種
ごとに 1 行）を書き、要約表を表示する。``--jobs N`` で、画像を解析するワーカー
プロセスの数を指定する。結果はこの数によらない。
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
_TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import synthetic_fibers as sf  # noqa: E402
from afm_nanofiber_analyzer import measure  # noqa: E402
from afm_nanofiber_analyzer.kink_detector import KinkDetector  # noqa: E402
from afm_nanofiber_analyzer.pipeline import ProcParams, process_file  # noqa: E402

# Apparent width of the modelled fiber (3 nm cylinder, 10 nm tip) is about
# 15.5 nm on the bundled generator settings; the pixel size is chosen from it.
# モデル繊維（直径 3 nm、探針 10 nm）の見かけ幅は、同梱の生成器設定で約 15.5 nm。
# 画素サイズはそこから決める。
APPARENT_WIDTH_NM = 15.5
LENGTH_NM = 640.0
FIBER_DIAMETER_NM = 3.0
TIP_RADIUS_NM = 10.0
BACKGROUND = dict(
    line_noise_nm=0.03, tilt_nm=1.0,
    roughness_nm=0.40, roughness_corr_nm=120.0, roughness_hurst=0.6,
)

WIDTHS_PX = (3.0, 5.0, 8.0, 16.0)
NOISES_NM = (0.05, 0.15, 0.30)
SEEDS = (1, 2)

DEFAULT_VARIANTS: Dict[str, dict] = {
    "base": dict(noise_sigmas=0.0),
    "k2": dict(noise_sigmas=2.0),
    "k3": dict(noise_sigmas=3.0),
    "k4": dict(noise_sigmas=4.0),
    "k3w4": dict(noise_sigmas=3.0, noise_min_windows=4.0),
}


def families(nm_per_px: float, shape: Tuple[int, int]) -> Dict[str, Tuple[list, float]]:
    """
    The centerline families of one pixel size, with each one's true kink count.
    1 つの画素サイズの中心線族と、それぞれの真のキンク数。
    """
    geom = dict(shape=shape, nm_per_px=nm_per_px)
    out = {
        "straight": ([sf.straight_centerline(LENGTH_NM, **geom)], float("nan")),
        "arc60": ([sf.arc_centerline(LENGTH_NM, LENGTH_NM / math.radians(60.0), **geom)],
                  float("nan")),
        "sine": ([sf.sine_centerline(LENGTH_NM, 25.0, 300.0, **geom)], float("nan")),
    }
    for interior in (120.0, 140.0, 145.0, 165.0):
        out["kink%d" % int(interior)] = (
            [sf.kinked_centerline(LENGTH_NM, interior, **geom)], interior)
    return out


def _shape_for(nm_per_px: float) -> Tuple[int, int]:
    side = int(math.ceil(LENGTH_NM / nm_per_px * 1.25 / 64.0)) * 64
    side = max(side, 192)
    return (side, side)


def _fiber_kinks(fibers, detector: KinkDetector):
    """
    Judge every traced line and return kinks with absolute pixel coordinates.
    追跡した各線を判定し、画像座標のキンクを返す。
    """
    kinks = []
    length_px = 0.0
    widths = []
    for fiber in fibers:
        bx, by = float(fiber.data[0]), float(fiber.data[1])
        x = np.asarray(fiber.xtrack, float) + bx
        y = np.asarray(fiber.ytrack, float) + by
        length_px += float(np.hypot(np.diff(x), np.diff(y)).sum())
        widths.append(float(fiber.width_px))
        judged = detector.judge_line(x, y, fiber.width_px)
        for k, angle, excess in zip(judged.kink_indices, judged.kink_angles,
                                    judged.kink_excess):
            kinks.append((float(x[k]) + 0.5, float(y[k]) + 0.5,
                          math.degrees(float(angle)), math.degrees(float(excess)),
                          float(fiber.width_px)))
    return kinks, length_px, (float(np.median(widths)) if widths else float("nan"))


def default_jobs() -> int:
    """
    Return the number of worker processes the sweep uses by default.
    掃引が既定で使うワーカープロセスの数を返す。

    Returns
    -------
    int
        One less than the logical CPU count, at least 1, so the machine stays
        usable while the scans are analyzed.
        論理 CPU 数より 1 少ない数（最小 1）。画像を解析している間も PC を
        使えるようにするためである。
    """
    return max(1, (os.cpu_count() or 2) - 1)


def _scan_bundle(out: str, reuse: bool, w_px: float, noise: float, seed: int,
                 fam: str) -> Tuple[str, str, list, float]:
    """
    Return one scan's name, bundle, centerlines and true interior angle.
    画像 1 枚の名前・バンドル・中心線・真の内角を返す。

    The scan is drawn and analyzed here unless ``reuse`` is set and its bundle
    is already in ``out``: drawing and the pipeline are nearly all of a scan's
    time, and neither depends on the code that reads the bundle.
    ``reuse`` が真で、バンドルがすでに ``out`` にある場合を除き、ここで画像を描いて
    解析する。1 枚にかかる時間のほとんどは描画とパイプラインであり、どちらも
    バンドルを読む側のコードには依存しない。

    Everything that decides what a scan's bundle holds is this function and
    the definitions it reads (`families`, `_shape_for`, and the fiber and
    background constants). `bundle_cache.GENERATOR_DEFINITIONS` names exactly
    those, so changing one of them starts a new cache folder, while the
    scoring in `_scan_rows` can change without the scans being analyzed again.
    バンドルの中身を決めるものは、この関数と、それが読む定義（`families`、
    `_shape_for`、繊維と背景の定数）がすべてである。
    `bundle_cache.GENERATOR_DEFINITIONS` はちょうどそれらを挙げているので、その
    どれかを変えると新しいキャッシュフォルダから始まる。一方 `_scan_rows` の採点は、
    画像を解析し直すことなく変えられる。
    """
    nm_per_px = APPARENT_WIDTH_NM / w_px
    shape = _shape_for(nm_per_px)
    lines, interior = families(nm_per_px, shape)[fam]
    stem = "W%g_n%.2f_s%d_%s" % (w_px, noise, seed, fam)
    bundle = os.path.join(out, stem + ".b2z")
    if not (reuse and os.path.isfile(bundle)):
        scan = sf.render_scan(
            lines, shape=shape, nm_per_px=nm_per_px,
            fiber_diameter_nm=FIBER_DIAMETER_NM,
            tip_radius_nm=TIP_RADIUS_NM, noise_nm=noise, seed=seed,
            **BACKGROUND,
        )
        txt = sf.write_afm_text(scan, os.path.join(out, stem + ".txt"))
        bundle = process_file(txt, ProcParams(), scan_size_um=scan.scan_size_um,
                              scan_size_source="manual").bundle_path
    return stem, bundle, lines, interior


def _scan_rows(task: tuple) -> Tuple[List[dict], str]:
    """
    Score one scan against its known answer; return its rows and a progress note.
    画像 1 枚を正解と照らして採点し、その行と進捗表示用の文字列を返す。

    A module-level function taking one picklable tuple, so `run` can hand the
    scans to worker processes. A scan depends on nothing but its own task: the
    noise is drawn from the task's seed and every file it writes is named by
    its own stem. The true kinks are read from the centerlines, so a scan
    whose bundle `_scan_bundle` reuses is not drawn at all.
    `run` が画像をワーカープロセスへ渡せるよう、pickle 可能なタプル 1 つを受け取る
    モジュール直下の関数にしている。1 枚の画像は自分のタスクだけで決まる。ノイズは
    タスクの乱数の種から引き、書き出すファイルはすべて自分の stem で名付ける。
    真のキンクは中心線から読むので、`_scan_bundle` がバンドルを使い回す画像は
    一切描かない。
    """
    out, variant_names, reuse, w_px, noise, seed, fam = task
    nm_per_px = APPARENT_WIDTH_NM / w_px
    stem, bundle, lines, interior = _scan_bundle(out, reuse, w_px, noise, seed, fam)
    image = measure.load_tracking_image(bundle, nm_per_px, nm_per_px)
    fibers = image.fibers_in_image_parallel()
    tx = np.concatenate([line.x[line.kink_indices] for line in lines])
    ty = np.concatenate([line.y[line.kink_indices] for line in lines])
    rows: List[dict] = []
    w_med = float("nan")
    for vname in variant_names:
        kinks, length_px, w_med = _fiber_kinks(
            fibers, KinkDetector(**DEFAULT_VARIANTS[vname]))
        length_um = length_px * nm_per_px / 1000.0
        row = dict(W_px=w_px, W_measured_px=round(w_med, 2),
                   nm_per_px=round(nm_per_px, 3), noise_nm=noise,
                   seed=seed, family=fam, variant=vname,
                   n_fibers=len(fibers), length_um=round(length_um, 3),
                   kinks=len(kinks), true_interior_deg=interior,
                   found=0, false=len(kinks),
                   arm_interior_deg=float("nan"),
                   excess_deg=float("nan"))
        if tx.size and kinks:
            # The nearest detection within 1.5 W of the true
            # apex is the match; everything else is false.
            # 真の頂点から 1.5 W 以内で最も近い検出を対応とし、
            # それ以外はすべて偽とする。
            d = [math.hypot(kx - tx[0], ky - ty[0]) for kx, ky, *_ in kinks]
            j = int(np.argmin(d))
            if d[j] <= 1.5 * kinks[j][4]:
                row["found"] = 1
                row["false"] = len(kinks) - 1
                row["arm_interior_deg"] = round(kinks[j][2], 2)
                row["excess_deg"] = round(kinks[j][3], 2)
        rows.append(row)
    return rows, "%-28s fibers %d  W %.1f px" % (stem, len(fibers), w_med)


def run(args) -> List[dict]:
    """
    Analyze every scan of the sweep and return one row per scan and variant.
    掃引のすべての画像を解析し、画像 × 変種ごとに 1 行を返す。

    The scans are independent, so ``args.jobs`` worker processes analyze them
    side by side (1, or an ``args`` without ``jobs``, runs them in this
    process). The rows come back in the order of the scans whatever the number
    of workers, so ``sweep.csv`` and everything computed from the rows are the
    same for any ``jobs``.
    画像どうしは独立なので、``args.jobs`` 個のワーカープロセスが並行して解析する
    （1、または ``jobs`` を持たない ``args`` では、このプロセス内で実行する）。行は
    ワーカー数によらず画像の順に返るため、``sweep.csv`` と、行から計算するものは
    すべて、どの ``jobs`` でも同じになる。

    ``args.reuse`` (absent means off) keeps the bundles already in ``args.out``
    instead of drawing and analyzing their scans again. Only a caller whose
    folder is named by the code that makes the bundles sets it
    (`bundle_cache.cache_root`, as `scripts/measure_docs.py` does): in any
    other folder a bundle left by older code would be read as current.
    ``args.reuse``（無ければ無効）は、``args.out`` にすでにあるバンドルを使い、
    その画像の描画と解析をやり直さない。これを指定するのは、バンドルを作るコードで
    名付けたフォルダを渡す呼び出し側だけである（`bundle_cache.cache_root`。
    `scripts/measure_docs.py` がそうしている）。それ以外のフォルダでは、古いコードが
    残したバンドルを今のものとして読んでしまう。
    """
    widths = WIDTHS_PX if not args.quick else (3.0, 8.0)
    noises = NOISES_NM if not args.quick else (0.05, 0.30)
    seeds = SEEDS if not args.quick else (1,)
    os.makedirs(args.out, exist_ok=True)
    reuse = bool(getattr(args, "reuse", False))
    tasks = []
    for w_px in widths:
        nm_per_px = APPARENT_WIDTH_NM / w_px
        fam_names = list(families(nm_per_px, _shape_for(nm_per_px)))
        for noise in noises:
            for seed in seeds:
                for fam in fam_names:
                    tasks.append((args.out, tuple(args.variants), reuse, w_px, noise, seed, fam))
    jobs = max(1, min(int(getattr(args, "jobs", 1) or 1), len(tasks)))
    rows: List[dict] = []
    t0 = time.time()

    def collect(results) -> None:
        for n_scans, (scan_rows, note) in enumerate(results, 1):
            rows.extend(scan_rows)
            print("[%3d] %s  %.0fs" % (n_scans, note, time.time() - t0), flush=True)

    if jobs == 1:
        collect(map(_scan_rows, tasks))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            collect(pool.map(_scan_rows, tasks))
    with open(os.path.join(args.out, "sweep.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summarize(rows: Sequence[dict]) -> str:
    """
    Per width, noise and variant: false positives per µm, recall, angle error.
    幅・ノイズ・変種ごとの、1 µm あたりの偽陽性、再現率、角度誤差。
    """
    lines = []
    header = "%-5s %-6s %-6s | %8s | %6s %6s %6s %6s | %8s %8s" % (
        "W", "noise", "var", "FP/um", "r120", "r140", "r145", "f165", "arm_err", "exc_err")
    lines.append(header)
    keys = sorted({(r["W_px"], r["noise_nm"], r["variant"]) for r in rows},
                  key=lambda t: (t[0], t[1], list(DEFAULT_VARIANTS).index(t[2])
                                 if t[2] in DEFAULT_VARIANTS else 99))
    for w, noise, var in keys:
        sub = [r for r in rows if (r["W_px"], r["noise_nm"], r["variant"]) == (w, noise, var)]
        smooth = [r for r in sub if not np.isfinite(r["true_interior_deg"])]
        fp = sum(r["false"] for r in smooth)
        um = sum(r["length_um"] for r in smooth)

        def recall(fam):
            s = [r for r in sub if r["family"] == fam]
            return (sum(r["found"] for r in s) / len(s)) if s else float("nan")

        def false_on(fam):
            s = [r for r in sub if r["family"] == fam]
            return sum(r["kinks"] for r in s) / len(s) if s else float("nan")

        judged = [r for r in sub if r["found"] and r["family"] != "kink165"]
        arm_err = np.median([abs(r["arm_interior_deg"] - r["true_interior_deg"]) for r in judged]) if judged else float("nan")
        exc_err = np.median([abs((180.0 - r["excess_deg"]) - r["true_interior_deg"]) for r in judged]) if judged else float("nan")
        lines.append("%-5g %-6.2f %-6s | %8.2f | %6.2f %6.2f %6.2f %6.2f | %8.1f %8.1f" % (
            w, noise, var, fp / um if um else float("nan"),
            recall("kink120"), recall("kink140"), recall("kink145"), false_on("kink165"),
            arm_err, exc_err))
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, ".tmp", "kink_rule_sweep"))
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--variants", nargs="*", default=list(DEFAULT_VARIANTS))
    parser.add_argument("--jobs", type=int, default=default_jobs(),
                        help="worker processes analyzing the scans (default: %(default)s)")
    args = parser.parse_args(argv)
    rows = run(args)
    summary = summarize(rows)
    print(summary)
    with open(os.path.join(args.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(summary + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
