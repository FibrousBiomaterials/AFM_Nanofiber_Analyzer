# -*- coding: utf-8 -*-
"""
Score kink-rule variants against the visual reference on the bundled scans.
同梱スキャンの目視基準に対して、キンク規則の各変種を採点する。

The reference (``private_docs/kink_reference_2026-09-15/基準一覧.md``) marks,
on the calibrated height images, every bend a person judged to be a clear
kink, an ambiguous one, or a junction, with no detector output on screen. This
script re-judges every traced fiber's line with one or more `KinkDetector`
configurations and reports, per scan and in total, how many clear kinks each
found, displaced, merged or missed, and how many detections match nothing.
基準（``private_docs/kink_reference_2026-09-15/基準一覧.md``）は、検出器の出力を
一切重ねずに、較正高さ画像上で人が明瞭なキンク・曖昧な折れ・合流点と判断した
すべての折れを記録したものである。本スクリプトは追跡した各繊維の線を 1 つ以上の
`KinkDetector` 設定で判定し直し、スキャンごとと合計で、明瞭なキンクをいくつ
検出・位置ずれ・統合・見落としたか、何にも対応しない検出がいくつあるかを報告する。

Scoring follows the approved procedure: a clear kink is found when an unused
detection lies within the fiber's apparent width W of it, displaced when one
lies within 2 W, merged when the only detection within W already matched
another clear kink, and missed otherwise. Detections within W of an ambiguous
or junction mark are exempt; every other unmatched detection is false. Bends
the rule left unjudged next to an end are counted separately.
採点は承認済みの手順に従う。明瞭なキンクは、未使用の検出が繊維の見かけ幅 W 以内
にあれば「検出」、2 W 以内なら「位置ずれ」、W 以内の検出が既に別の明瞭キンクに
使われていれば「統合」、いずれでもなければ「見落とし」。曖昧・合流の印から W 以内
の検出は除外扱いとし、それ以外の未対応の検出は「誤検出」。端のそばで判定しなかった
折れは別に数える。

Usage
-----
``.venv\\Scripts\\python.exe scripts/kink_reference_score.py``
``.venv\\Scripts\\python.exe scripts/kink_reference_score.py --gallery k3 --out .tmp/kink_ref``

The bundles are produced once with the default `ProcParams` and cached under
``--cache`` (default ``.tmp/kink_reference_cache``); every variant re-judges
the same traced lines, so a difference between variants is the rule alone.
バンドルは既定の `ProcParams` で一度だけ作り ``--cache``（既定
``.tmp/kink_reference_cache``）に置く。すべての変種が同じ追跡済みの線を判定し直す
ため、変種間の差は規則だけによる。
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib import measure  # noqa: E402
from lib.kink_detector import KinkDetector  # noqa: E402
from lib.pipeline import ProcParams, process_file  # noqa: E402

REFERENCE_PATH = os.path.join(
    PROJECT_ROOT, "private_docs", "kink_reference_2026-09-15", "基準一覧.md")

# Reference section name -> bundled scan. The Gwyddion text exports of the
# higher-plant scan share its reference and are not scored separately.
# 基準の節名 -> 同梱スキャン。高等植物スキャンの Gwyddion テキスト出力は同じ
# 基準を共有し、別には採点しない。
SCANS: Dict[str, str] = {
    "hplantTOC": os.path.join("testdata_higherplantTOC", "_20250318-164122_T.ssp .txt"),
    "tunicate": os.path.join("testdata_tunicateCNF", "TunicateACTOCCNF.txt"),
    "NDTOC": os.path.join("testdata_Bruker_txt", "NDTOC250306.000.txt"),
    "art_iso": os.path.join("testdata_artificial", "sample_isotropic.txt"),
    "art_aniso": os.path.join("testdata_artificial", "sample_anisotropic.txt"),
}

# Fibers the reference records as duplicates of another scan's fiber.
# 基準が別スキャンの繊維の重複として記録している繊維。
EXCLUDED_FIBERS: Dict[str, set] = {"art_aniso": {0}}

KIND = {"明瞭": "clear", "曖昧": "ambiguous", "合流": "junction"}

# Detector configurations compared by default: no noise test (the rule as
# shipped in format 1.1), then the floor at 2, 3 and 4 noise scales.
# 既定で比較する検出器の設定。ノイズ検定なし（形式 1.1 で出荷した規則）、次に
# ノイズ尺度の 2・3・4 倍の床。
DEFAULT_VARIANTS: Dict[str, dict] = {
    "base": dict(noise_sigmas=0.0),
    "k2": dict(noise_sigmas=2.0),
    "k3": dict(noise_sigmas=3.0),
    "k4": dict(noise_sigmas=4.0),
    "k3w4": dict(noise_sigmas=3.0, noise_min_windows=4.0),
}


def load_reference(path: str = REFERENCE_PATH) -> Dict[str, List[dict]]:
    """
    Parse the reference tables into per-scan lists of marked bends.
    基準の表を、スキャンごとの印の一覧に解析する。

    Returns
    -------
    dict
        Scan name -> records with ``fiber``, ``kind`` (``clear``,
        ``ambiguous`` or ``junction``), ``x``, ``y`` and ``angle_deg`` (the
        eyeballed turning, NaN where none was written).
        スキャン名 -> ``fiber``・``kind``（``clear`` / ``ambiguous`` /
        ``junction``）・``x``・``y``・``angle_deg``（目測の回転角。無ければ NaN）
        を持つレコード。
    """
    refs: Dict[str, List[dict]] = {name: [] for name in SCANS}
    current: Optional[str] = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            heading = re.match(r"^## (\w+)", line)
            if heading:
                current = heading.group(1)
                continue
            if current not in refs or not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5 or not cells[0].isdigit():
                continue
            kind = KIND.get(cells[2])
            if kind is None:
                continue
            fiber = int(cells[0])
            if fiber in EXCLUDED_FIBERS.get(current, set()):
                continue
            xy = [float(v) for v in cells[3].split(",")]
            angle = re.match(r"(\d+(?:\.\d+)?)", cells[4])
            refs[current].append(dict(
                fiber=fiber, kind=kind, x=xy[0], y=xy[1],
                angle_deg=float(angle.group(1)) if angle else float("nan"),
            ))
    return refs


def prepare_scan(name: str, cache_dir: str, params: ProcParams):
    """
    Analyze one bundled scan (cached) and trace its fibers.
    同梱スキャン 1 枚を解析し（キャッシュ）、繊維を追跡する。
    """
    txt = os.path.join(PROJECT_ROOT, SCANS[name])
    stem = os.path.splitext(os.path.basename(txt))[0]
    bundle = os.path.join(cache_dir, stem + ".b2z")
    if not os.path.isfile(bundle):
        os.makedirs(cache_dir, exist_ok=True)
        bundle = process_file(txt, params, output_dir=cache_dir).bundle_path
    # The pixel size is irrelevant here: every distance below is in pixels.
    # ピクセルサイズはここでは無関係。以下の距離はすべて画素単位である。
    image = measure.load_tracking_image(bundle, 1.0, 1.0)
    return image, image.fibers_in_image_parallel()


def detect(fibers, detector: KinkDetector, skip: set = frozenset()) -> Tuple[List[dict], List[dict]]:
    """
    Re-judge every fiber's line and list its kinks and unjudged bends.
    各繊維の線を判定し直し、キンクと判定しなかった折れを列挙する。
    """
    kinks: List[dict] = []
    unjudged: List[dict] = []
    for i, fiber in enumerate(fibers):
        if i in skip:
            continue
        bx, by = float(fiber.data[0]), float(fiber.data[1])
        x = np.asarray(fiber.xtrack, dtype=float) + bx
        y = np.asarray(fiber.ytrack, dtype=float) + by
        judged = detector.judge_line(x, y, fiber.width_px)
        for k, angle, excess in zip(judged.kink_indices, judged.kink_angles,
                                    judged.kink_excess):
            kinks.append(dict(x=float(x[k]), y=float(y[k]), w=float(fiber.width_px),
                              fiber=i, interior_deg=math.degrees(float(angle)),
                              excess_deg=math.degrees(float(excess)),
                              noise_deg=math.degrees(judged.noise_excess)
                              if np.isfinite(judged.noise_excess) else float("nan")))
        for k in judged.unjudged_indices:
            unjudged.append(dict(x=float(x[k]), y=float(y[k]),
                                 w=float(fiber.width_px), fiber=i))
    return kinks, unjudged


def score(refs: Sequence[dict], kinks: Sequence[dict], unjudged: Sequence[dict]) -> dict:
    """
    Match detections to the marked bends by the approved procedure.
    承認済みの手順で、検出を印の付いた折れに対応付ける。
    """
    clear = [r for r in refs if r["kind"] == "clear"]
    exempt_refs = [r for r in refs if r["kind"] != "clear"]
    used = [False] * len(kinks)
    counts = dict(ref=len(clear), found=0, merged=0, displaced=0, missed=0,
                  false=0, exempt=0, unjudged=len(unjudged), unjudged_on_clear=0)
    pairs: List[Tuple[dict, dict]] = []
    missed: List[dict] = []
    for ref in clear:
        dist = [math.hypot(k["x"] - ref["x"], k["y"] - ref["y"]) for k in kinks]
        within = sorted((d, i) for i, d in enumerate(dist) if d <= kinks[i]["w"])
        free = [i for _, i in within if not used[i]]
        if free:
            used[free[0]] = True
            counts["found"] += 1
            pairs.append((ref, kinks[free[0]]))
            continue
        if within:
            counts["merged"] += 1
            continue
        near = sorted((d, i) for i, d in enumerate(dist)
                      if d <= 2.0 * kinks[i]["w"] and not used[i])
        if near:
            used[near[0][1]] = True
            counts["displaced"] += 1
        else:
            counts["missed"] += 1
            missed.append(ref)
    false: List[dict] = []
    for i, kink in enumerate(kinks):
        if used[i]:
            continue
        if any(math.hypot(kink["x"] - r["x"], kink["y"] - r["y"]) <= kink["w"]
               for r in exempt_refs):
            counts["exempt"] += 1
        else:
            counts["false"] += 1
            false.append(kink)
    for u in unjudged:
        if any(math.hypot(u["x"] - r["x"], u["y"] - r["y"]) <= u["w"] for r in clear):
            counts["unjudged_on_clear"] += 1
    counts["pairs"] = pairs
    counts["false_list"] = false
    counts["missed_list"] = missed
    return counts


def _format_row(name: str, c: dict) -> str:
    return "%-14s %4d %5d %6d %5d %6d %6d %6d %8d %10d" % (
        name, c["ref"], c["found"], c["merged"], c["displaced"], c["missed"],
        c["false"], c["exempt"], c["unjudged"], c["unjudged_on_clear"])


HEADER = "%-14s %4s %5s %6s %5s %6s %6s %6s %8s %10s" % (
    "variant", "ref", "found", "merged", "displ", "missed", "false", "exempt",
    "unjudged", "unj_clear")


def _angle_summary(pairs: Sequence[Tuple[dict, dict]]) -> str:
    """
    Compare the reported turning with the eyeballed one over matched kinks.
    対応が付いたキンクについて、報告した回転角と目測の回転角を比べる。
    """
    ref = np.array([p[0]["angle_deg"] for p in pairs])
    arm = np.array([180.0 - p[1]["interior_deg"] for p in pairs])
    exc = np.array([p[1]["excess_deg"] for p in pairs])
    ok = np.isfinite(ref)
    if not ok.any():
        return "    (no eyeballed angles to compare)"
    ref, arm, exc = ref[ok], arm[ok], exc[ok]
    return ("    turning vs eyeball (n=%d): arm-fit bias %+.1f deg, MAD %.1f | "
            "excess bias %+.1f deg, MAD %.1f" % (
                ref.size, np.median(arm - ref), np.median(np.abs(arm - ref)),
                np.median(exc - ref), np.median(np.abs(exc - ref))))


def gallery(name: str, image, fibers, kinks: Sequence[dict], refs: Sequence[dict],
            items: Sequence[dict], title: str, out_path: str, half: int = 32,
            per_figure: int = 20) -> List[str]:
    """
    Render crops of the calibrated image around each listed bend.
    列挙した各折れの周りの較正画像の切り出しを描画する。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cal = image.calibrated_image
    paths: List[str] = []
    for start in range(0, len(items), per_figure):
        chunk = items[start:start + per_figure]
        cols = 5
        rows = int(math.ceil(len(chunk) / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 3.4 * rows))
        axes = np.atleast_1d(axes).ravel()
        for ax in axes[len(chunk):]:
            ax.axis("off")
        for ax, item in zip(axes, chunk):
            cx, cy = int(round(item["x"])), int(round(item["y"]))
            x0, y0 = max(cx - half, 0), max(cy - half, 0)
            x1, y1 = min(cx + half, cal.shape[1]), min(cy + half, cal.shape[0])
            crop = cal[y0:y1, x0:x1]
            ax.imshow(crop, cmap="afmhot", vmin=-1, vmax=max(6.0, float(np.percentile(crop, 99.5))),
                      extent=(x0, x1, y1, y0))
            for f in fibers:
                bx, by = float(f.data[0]), float(f.data[1])
                fx = np.asarray(f.xtrack, float) + bx + 0.5
                fy = np.asarray(f.ytrack, float) + by + 0.5
                inside = (fx >= x0) & (fx <= x1) & (fy >= y0) & (fy <= y1)
                if inside.any():
                    ax.plot(fx, fy, color="lime", lw=0.8, alpha=0.8)
            for k in kinks:
                if x0 <= k["x"] <= x1 and y0 <= k["y"] <= y1:
                    ax.plot(k["x"] + 0.5, k["y"] + 0.5, "x", color="red", ms=7, mew=2)
            for r in refs:
                if x0 <= r["x"] <= x1 and y0 <= r["y"] <= y1:
                    style = dict(clear=("cyan", "-"), ambiguous=("yellow", "--"),
                                 junction=("white", ":"))[r["kind"]]
                    ax.add_patch(plt.Circle((r["x"], r["y"]), 4.0, fill=False,
                                            color=style[0], ls=style[1], lw=1.2))
            ax.set_xlim(x0, x1)
            ax.set_ylim(y1, y0)
            ax.set_xticks([])
            ax.set_yticks([])
            label = "%s #%d (%d,%d)" % (name, item.get("fiber", -1), cx, cy)
            if "excess_deg" in item:
                label += " exc %.0f arm %.0f" % (item["excess_deg"], 180.0 - item["interior_deg"])
                if np.isfinite(item.get("noise_deg", float("nan"))):
                    label += " n%.0f" % item["noise_deg"]
            elif "angle_deg" in item:
                label += " ref %.0f" % item["angle_deg"]
            ax.set_title(label, fontsize=8)
        fig.suptitle("%s: %s (%d-%d of %d)" % (name, title, start + 1,
                                                start + len(chunk), len(items)))
        fig.tight_layout()
        path = "%s_%d.png" % (out_path, start // per_figure)
        fig.savefig(path, dpi=110)
        plt.close(fig)
        paths.append(path)
    return paths


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", default=os.path.join(PROJECT_ROOT, ".tmp", "kink_reference_cache"))
    parser.add_argument("--variants", nargs="*", default=list(DEFAULT_VARIANTS),
                        help="names from DEFAULT_VARIANTS, or NAME=noise_sigmas[,min_windows]")
    parser.add_argument("--gallery", default=None,
                        help="variant whose false detections and misses are rendered")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, ".tmp", "kink_reference_out"))
    args = parser.parse_args(argv)

    variants: Dict[str, dict] = {}
    for spec in args.variants:
        if "=" in spec:
            name, values = spec.split("=", 1)
            parts = [float(v) for v in values.split(",")]
            variants[name] = dict(noise_sigmas=parts[0])
            if len(parts) > 1:
                variants[name]["noise_min_windows"] = parts[1]
        else:
            variants[spec] = DEFAULT_VARIANTS[spec]

    refs = load_reference()
    params = ProcParams()
    totals: Dict[str, dict] = {v: dict(ref=0, found=0, merged=0, displaced=0, missed=0,
                                       false=0, exempt=0, unjudged=0, unjudged_on_clear=0,
                                       pairs=[]) for v in variants}
    per_scan: Dict[str, Dict[str, dict]] = {}
    scans = {}
    for name in SCANS:
        image, fibers = prepare_scan(name, args.cache, params)
        scans[name] = (image, fibers)
        per_scan[name] = {}
        for vname, kwargs in variants.items():
            detector = KinkDetector(**kwargs)
            kinks, unjudged = detect(fibers, detector, EXCLUDED_FIBERS.get(name, set()))
            result = score(refs[name], kinks, unjudged)
            result["kinks"] = kinks
            per_scan[name][vname] = result
            for key in ("ref", "found", "merged", "displaced", "missed", "false",
                        "exempt", "unjudged", "unjudged_on_clear"):
                totals[vname][key] += result[key]
            totals[vname]["pairs"].extend(result["pairs"])

    print("== REAL, all scans (art_aniso #0 excluded) ==")
    print(HEADER)
    for vname in variants:
        print(_format_row(vname, totals[vname]))
        print(_angle_summary(totals[vname]["pairs"]))
    for name in SCANS:
        print("\n-- %s --" % name)
        print(HEADER)
        for vname in variants:
            print(_format_row(vname, per_scan[name][vname]))

    if args.gallery:
        os.makedirs(args.out, exist_ok=True)
        vname = args.gallery
        for name in SCANS:
            image, fibers = scans[name]
            result = per_scan[name][vname]
            for kind, items in (("false", result["false_list"]),
                                ("missed", result["missed_list"])):
                if not items:
                    continue
                paths = gallery(name, image, fibers, result["kinks"], refs[name], items,
                                "%s %s" % (vname, kind),
                                os.path.join(args.out, "%s_%s_%s" % (vname, name, kind)))
                for p in paths:
                    print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
