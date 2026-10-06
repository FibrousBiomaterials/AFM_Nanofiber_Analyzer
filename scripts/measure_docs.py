#!/usr/bin/env python3
"""Measure the numbers the algorithm documents state, and record them.
アルゴリズム解説文書が述べる数値を測り、記録する。

Each experiment below reproduces one group of statements in
`docs/algorithms.md` from the current code and writes its values, with the
fingerprints of the analysis code it ran on, to ``tests/doc_measurements.json``.
The documents cite those values by key (``<!--m:experiment.key-->``) and
``scripts/check_doc_numbers.py`` compares them, so a number in the documents is
exactly what an experiment here produced, and a change to the analysis code
marks the recording stale until the experiment is run again.
以下の各実験は `docs/algorithms.md` の一群の記述を現在のコードで再現し、その値を、
実行した解析コードの指紋とともに ``tests/doc_measurements.json`` に書く。文書は
それらの値を項目名で引用し（``<!--m:experiment.key-->``）、
``scripts/check_doc_numbers.py`` が照合する。そのため文書の数値は、ここの実験が
出した値そのものであり、解析コードが変わると、実験をやり直すまで記録は古いものと
して扱われる。

Usage
-----
``.venv\\Scripts\\python.exe scripts/measure_docs.py --list``
``.venv\\Scripts\\python.exe scripts/measure_docs.py --only kink_reference``
``.venv\\Scripts\\python.exe scripts/measure_docs.py``        (every experiment; slow)

Intermediate files go under ``.tmp/measure_docs``. The visual reference of
``kink_reference`` lives in ``private_docs/`` and is not part of the public
repository; without it that experiment cannot run.
中間ファイルは ``.tmp/measure_docs`` に置く。``kink_reference`` の目視基準は
``private_docs/`` にあり公開リポジトリには含まれないため、それが無い環境ではその
実験は実行できない。
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "scripts", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import doc_excerpts  # noqa: E402

MEASUREMENTS = ROOT / "tests" / "doc_measurements.json"
WORK = ROOT / ".tmp" / "measure_docs"


# ----------------------------------------------------------------------------
# Code snapshots
# ----------------------------------------------------------------------------

def _lib_imports(rel: str) -> List[str]:
    """The lib modules one lib module imports, as repository paths."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                if node.module:
                    out.append(f"lib/{node.module.replace('.', '/')}.py")
                else:
                    out += [f"lib/{a.name}.py" for a in node.names]
            elif node.module and node.module.startswith("lib"):
                if node.module == "lib":
                    out += [f"lib/{a.name}.py" for a in node.names]
                else:
                    out.append(node.module.replace(".", "/") + ".py")
        elif isinstance(node, ast.Import):
            out += [a.name.replace(".", "/") + ".py" for a in node.names
                    if a.name.startswith("lib.")]
    return [p for p in out if (ROOT / p).is_file()]


def closure(roots: Sequence[str]) -> List[str]:
    """Every lib module the given lib modules reach through their imports."""
    seen: set = set()
    todo = list(roots)
    while todo:
        rel = todo.pop()
        if rel in seen or not (ROOT / rel).is_file():
            continue
        seen.add(rel)
        todo += _lib_imports(rel)
    return sorted(seen)


def snapshot(modules: Sequence[str]) -> Dict[str, Dict[str, str]]:
    """Per-definition fingerprints of the given modules (`doc_excerpts`)."""
    return {rel: doc_excerpts.code_symbol_digests((ROOT / rel).read_text(encoding="utf-8"))
            for rel in modules}


# ----------------------------------------------------------------------------
# Experiments
# ----------------------------------------------------------------------------

EXPERIMENTS: Dict[str, dict] = {}


def experiment(name: str, roots: Sequence[str], description: str):
    """Register an experiment that depends on the analysis modules `roots` reach."""
    def wrap(func: Callable[[], dict]) -> Callable[[], dict]:
        EXPERIMENTS[name] = dict(func=func, roots=list(roots), description=description)
        return func
    return wrap


@contextlib.contextmanager
def patched(module, **values):
    """Temporarily replace module constants, restoring them afterwards."""
    old = {k: getattr(module, k) for k in values}
    for k, v in values.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


@experiment(
    "kink_reference",
    ["lib/pipeline.py", "lib/measure.py", "lib/kink_detector.py", "lib/centerline.py"],
    "Score the kink rule, its variants and the earlier polyline rule against the "
    "visual reference of 64 clear kinks on the five bundled scans "
    "(scripts/kink_reference_score.py procedure).",
)
def kink_reference() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from lib import centerline as cl
    from lib import kink_detector as kd
    from lib.kink_detector import KinkDetector
    from lib.pipeline import ProcParams

    refs = krs.load_reference()
    keys = ("ref", "found", "displaced", "merged", "missed", "false", "unjudged",
            "unjudged_on_clear")

    def load(method):
        cache = str(WORK / ("kink_reference_" + method))
        params = ProcParams(centerline_method=method)
        return {name: krs.prepare_scan(name, cache, params) for name in krs.SCANS}

    def total(scans, detector, old_rule=False):
        out = dict.fromkeys(keys, 0)
        for name, (_image, fibers) in scans.items():
            skip = krs.EXCLUDED_FIBERS.get(name, set())
            if old_rule:
                kinks = []
                for i, f in enumerate(fibers):
                    if i in skip:
                        continue
                    x = np.asarray(f.skeleton_xtrack, float) + float(f.data[0])
                    y = np.asarray(f.skeleton_ytrack, float) + float(f.data[1])
                    idx, _a, _d = detector.kinks_and_decomposed_from_track(x, y)
                    kinks += [dict(x=float(x[k]), y=float(y[k]), w=float(f.width_px), fiber=i)
                              for k in idx]
                res = krs.score(refs[name], kinks, [])
            else:
                kinks, unjudged = krs.detect(fibers, detector, skip)
                res = krs.score(refs[name], kinks, unjudged)
            for k in keys:
                out[k] += res[k]
        return out

    values: dict = {"scans": len(krs.SCANS)}
    base = KinkDetector()
    default = load(cl.HALF_MAX_025W_CENTERLINE)
    results = {"default": total(default, base),
               "noise3": total(default, KinkDetector(noise_sigmas=3.0)),
               "noise4": total(default, KinkDetector(noise_sigmas=4.0))}
    sensitivity = {}
    for name, vals, label in (("_CORE_WIDTHS", (0.6, 0.9), "core"),
                              ("_FLANK_WIDTHS", (0.75, 1.5), "flank"),
                              ("_HEADING_SIGMA_WIDTHS", (0.15, 0.35), "heading"),
                              ("END_MARGIN_WIDTHS", (1.0, 2.0), "end"),
                              ("_SUPPRESS_WIDTHS", (0.5, 1.0), "suppress")):
        for v in vals:
            with patched(kd, **{name: v}):
                sensitivity[f"{label}_{v:g}"] = total(default, base)
    for factor in (0.6, 1.4):
        with patched(cl, _FRAME_SIGMA_WIDTHS=cl._FRAME_SIGMA_WIDTHS * factor,
                     _OFFSET_SMOOTH_WIDTHS=cl._OFFSET_SMOOTH_WIDTHS * factor):
            sensitivity[f"line_x{factor:g}"] = total(load(cl.HALF_MAX_025W_CENTERLINE), base)
    results.update({f"sens_{k}": v for k, v in sensitivity.items()})
    results["old_rule"] = total(default, KinkDetector(
        threshold_distance=3.0, threshold_angle_from_decomposed_indices=math.radians(150.0)),
        old_rule=True)
    wide = load(cl.HALF_MAX_05W_CENTERLINE)
    results["hm05"] = total(wide, base)
    with patched(cl, _WIDE_SMOOTH_WIDTHS=cl._WIDE_SMOOTH_WIDTHS * 1.4):
        results["hm05_line_x1.4"] = total(load(cl.HALF_MAX_05W_CENTERLINE), base)
    with patched(kd, _HEADING_SIGMA_WIDTHS=0.35):
        results["hm05_heading_0.35"] = total(wide, base)
    with patched(kd, _CORE_WIDTHS=0.6):
        results["hm05_core_0.6"] = total(wide, base)
    results["skeleton_pixels"] = total(load(cl.SKELETON_PIXEL_LINE), base)

    for variant, counts in results.items():
        for k, v in counts.items():
            values[f"{variant}.{k}"] = v
    values["clear_marks"] = results["default"]["ref"]
    # The unmatched detections of the default rule: how many only just clear the
    # threshold, and how many read shallower than it from their arms.
    # 既定の規則の一致しない検出のうち、しきい値をわずかに超えるだけのものと、腕から
    # 読むとしきい値より浅いものの数。
    false_items = []
    for name, (_image, fibers) in default.items():
        kinks, unjudged = krs.detect(fibers, base, krs.EXCLUDED_FIBERS.get(name, set()))
        false_items += krs.score(refs[name], kinks, unjudged)["false_list"]
    threshold = 180.0 - ProcParams().kinkangle_deg
    values["default.false_excess_30_40"] = sum(threshold <= k["excess_deg"] <= threshold + 10
                                               for k in false_items)
    values["default.false_arm_turn_below_threshold"] = sum(
        180.0 - k["interior_deg"] < threshold for k in false_items)
    kink_sens = [v for k, v in sensitivity.items() if not k.startswith("line_")]
    all_sens = list(sensitivity.values())
    values["sens_kink_lengths.found_range"] = [min(r["found"] for r in kink_sens),
                                               max(r["found"] for r in kink_sens)]
    values["sens_kink_lengths.false_range"] = [min(r["false"] for r in kink_sens),
                                               max(r["false"] for r in kink_sens)]
    values["sens_all.found_range"] = [min(r["found"] for r in all_sens),
                                      max(r["found"] for r in all_sens)]
    values["sens_all.false_range"] = [min(r["false"] for r in all_sens),
                                      max(r["false"] for r in all_sens)]
    for n in (3, 4):
        values[f"noise{n}.lost"] = results["default"]["found"] - results[f"noise{n}"]["found"]
        values[f"noise{n}.fewer_false"] = results["default"]["false"] - results[f"noise{n}"]["false"]
    hm05_stronger = [results[k]["missed"] for k in
                     ("hm05_line_x1.4", "hm05_heading_0.35", "hm05_core_0.6")]
    values["hm05_stronger.missed_range"] = [min(hm05_stronger), max(hm05_stronger)]
    return values


@experiment(
    "kink_rule_sweep",
    ["lib/pipeline.py", "lib/measure.py", "lib/kink_detector.py", "lib/centerline.py"],
    "Synthetic kinked, straight, arc and sine fibers over apparent width and "
    "pixel noise, scored against the analytic centerline "
    "(scripts/kink_rule_sweep.py with the base rule and a 3-sigma noise floor).",
)
def kink_rule_sweep() -> dict:
    import numpy as np
    import kink_rule_sweep as sweep

    class Args:
        out = str(WORK / "kink_rule_sweep")
        quick = False
        variants = ["base", "k3"]

    rows = sweep.run(Args)
    values: dict = {}
    for w in sweep.WIDTHS_PX:
        sub = [r for r in rows if r["W_px"] == w and r["variant"] == "base"]
        measured = [r["W_measured_px"] for r in sub if np.isfinite(r["W_measured_px"])
                    and r["family"] == "straight"]
        values[f"W{w:g}.measured_width_px"] = float(np.median(measured)) if measured else None
        for fam in ("kink120", "kink140", "kink145"):
            s = [r for r in sub if r["family"] == fam]
            values[f"W{w:g}.{fam}.found"] = int(sum(r["found"] for r in s))
            values[f"W{w:g}.{fam}.cases"] = len(s)
            for noise in sweep.NOISES_NM:
                sn = [r for r in s if r["noise_nm"] == noise]
                values[f"W{w:g}.n{noise:.2f}.{fam}.found"] = int(sum(r["found"] for r in sn))
        judged = [r for r in sub if r["found"] and r["family"] != "kink165"]
        if judged:
            values[f"W{w:g}.arm_error_deg"] = float(np.median(
                [abs(r["arm_interior_deg"] - r["true_interior_deg"]) for r in judged]))
            values[f"W{w:g}.excess_error_deg"] = float(np.median(
                [abs((180.0 - r["excess_deg"]) - r["true_interior_deg"]) for r in judged]))
        for noise in sweep.NOISES_NM:
            for variant in ("base", "k3"):
                sv = [r for r in rows if r["W_px"] == w and r["noise_nm"] == noise
                      and r["variant"] == variant]
                smooth = [r for r in sv if not np.isfinite(r["true_interior_deg"])]
                um = sum(r["length_um"] for r in smooth)
                values[f"W{w:g}.n{noise:.2f}.{variant}.fp_per_um"] = (
                    sum(r["false"] for r in smooth) / um if um else None)
                values[f"W{w:g}.n{noise:.2f}.{variant}.kinked_found"] = int(sum(
                    r["found"] for r in sv if r["family"] in ("kink120", "kink140", "kink145")))
                values[f"W{w:g}.n{noise:.2f}.{variant}.reported_on_smooth"] = int(
                    sum(r["false"] for r in smooth))
                values[f"W{w:g}.n{noise:.2f}.{variant}.kink165_reported"] = int(
                    sum(r["kinks"] for r in sv if r["family"] == "kink165"))
    return values


@experiment(
    "bg_timing",
    ["lib/pipeline.py"],
    "Wall time of the three background methods on the bundled 1024 x 1024 "
    "Bruker scan, second of two runs, on the machine that ran this script.",
)
def bg_timing() -> dict:
    from dataclasses import replace
    from lib.afm_io import load_afm_text
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    arr = load_afm_text(str(ROOT / "testdata_Bruker_txt" / "NDTOC250306.000.txt"))
    arr = arr[0] if isinstance(arr, tuple) else arr
    values = {"image_rows": int(arr.shape[0]), "image_cols": int(arr.shape[1])}
    for method in ("trendfill", "tophat", "spline1d"):
        stage = build_stages(replace(ProcParams(), bg_method=method)).bg_calibrator
        times = []
        for _ in range(2):
            image = ProcessedImage(arr, "timing")
            t0 = time.perf_counter()
            stage(image)
            times.append(time.perf_counter() - t0)
        values[f"{method}.seconds"] = times[-1]
    b = build_stages(ProcParams()).bg_calibrator
    for _ in range(2):
        t0 = time.perf_counter(); dx, dy = b._difXY(arr)
        t1 = time.perf_counter(); _hx, _hy, ox, oy = b._bg_fit(dx, dy)
        t2 = time.perf_counter(); tx, ty = b._dif_sep(dx, dy, ox, oy)
        t3 = time.perf_counter(); fx, fy = b._extract_fiber(tx, ty)
        t4 = time.perf_counter(); b._bg_generate(arr, fx, fy)
        t5 = time.perf_counter()
    values["trendfill.bg_fit_seconds"] = t2 - t1
    values["trendfill.bg_generate_seconds"] = t5 - t4
    values["trendfill.bg_fit_over_bg_generate"] = (t2 - t1) / (t5 - t4)
    return values


@experiment(
    "thinning_example",
    ["lib/skeletonizer.py"],
    "The five-pixel band with a one-pixel hole and a two-pixel bump drawn in "
    "section 3.1, thinned by skimage.morphology.thin.",
)
def thinning_example() -> dict:
    import numpy as np
    from skimage.morphology import skeletonize, thin

    rows = [
        "........................",
        ".......#................",
        ".......#................",
        "..####################..",
        "..####################..",
        "..############.#######..",
        "..####################..",
        "..####################..",
    ]
    mask = np.array([[c == "#" for c in r] for r in rows])
    band_rows = [i for i, r in enumerate(rows) if r.count("#") > 5]
    band_cols = np.flatnonzero(mask[band_rows[0]])
    t = thin(mask)
    centre = band_rows[len(band_rows) // 2]
    line_cols = np.flatnonzero(t[centre])
    bump_col = int(np.flatnonzero(mask[1])[0])
    branch = int(t[:centre, bump_col].sum())
    return {
        "band_width_px": len(band_rows),
        "bump_height_px": int(mask[:band_rows[0], bump_col].sum()),
        "branch_length_px": branch,
        "shortening_per_end_px": int(line_cols.min() - band_cols.min()),
        "skeletonize_of_thin_unchanged": int(bool((skeletonize(t) == t).all())),
        "thin_and_skeletonize_differ": int(bool((skeletonize(mask) != t).any())),
    }


@experiment(
    "border_padding",
    ["lib/pipeline.py", "lib/skeletonizer.py"],
    "Thinning with and without the replicated border, compared outside the "
    "border band, on the binarized masks of the five bundled scans.",
)
def border_padding() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from skimage.morphology import thin
    from lib.blosc2_io import load_bundle
    from lib.pipeline import ProcParams, process_file
    from lib.skeletonizer import DEFAULT_BORDER_PAD as pad, thin_ignoring_image_border

    identical = 0
    cache = WORK / "kink_reference_half_max_025w"
    for rel in krs.SCANS.values():
        stem = Path(rel).stem
        bundle = cache / (stem + ".b2z")
        if not bundle.is_file():
            cache.mkdir(parents=True, exist_ok=True)
            bundle = Path(process_file(str(ROOT / rel), ProcParams(), output_dir=str(cache)).bundle_path)
        data = load_bundle(str(bundle))
        data = data[0] if isinstance(data, tuple) else data
        mask = (np.asarray(data["binarized"]) > 0).astype(np.uint8)
        plain = thin(mask).astype(np.uint8)
        padded = thin_ignoring_image_border(mask)
        h, w = mask.shape
        identical += int((plain[pad:h - pad, pad:w - pad] == padded[pad:h - pad, pad:w - pad]).all())
    return {"scans": len(krs.SCANS), "identical_inside_band": identical}


def _raw_scan(rel: str):
    from lib.afm_io import load_afm_text
    arr = load_afm_text(str(ROOT / rel))
    return arr[0] if isinstance(arr, tuple) else arr


def _trendfill_mask(arr):
    """The dilated fiber mask `_bg_generate` fills, on the [1:, 1:] grid."""
    import numpy as np
    from lib.pipeline import ProcParams, build_stages
    bg = build_stages(ProcParams()).bg_calibrator
    bg._detect_fiber_mask(arr)
    bg_only, _ = bg._bg_generate(arr, bg.tri_difx_fill, bg.tri_dify_fill)
    return np.isnan(bg_only)


def _default_bundle(rel: str):
    """The default-parameter bundle of a bundled scan (shared with kink_reference)."""
    from lib.blosc2_io import load_bundle
    from lib.pipeline import ProcParams, process_file
    cache = WORK / "kink_reference_half_max_025w"
    bundle = cache / (Path(rel).stem + ".b2z")
    if not bundle.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        bundle = Path(process_file(str(ROOT / rel), ProcParams(), output_dir=str(cache)).bundle_path)
    data = load_bundle(str(bundle))
    return data[0] if isinstance(data, tuple) else data


@experiment(
    "bg_stats",
    ["lib/pipeline.py"],
    "Per bundled scan: the slope of the least-squares plane through the raw heights, "
    "the median width of the dilated trendfill fiber mask (twice the distance to its "
    "edge along its medial axis), the height the plane falls across that width, the "
    "peak-to-peak of the quadratic part left after the plane, and the median "
    "calibrated height under the default skeleton.",
)
def bg_stats() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from scipy.ndimage import distance_transform_edt
    from skimage.morphology import skeletonize

    values: dict = {}
    for name, rel in krs.SCANS.items():
        arr = _raw_scan(rel)
        h, w = arr.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(float)
        design = np.column_stack([xx.ravel(), yy.ravel(), np.ones(h * w)])
        coef, *_ = np.linalg.lstsq(design, arr.ravel(), rcond=None)
        slope = float(np.hypot(coef[0], coef[1]))
        resid = arr - (design @ coef).reshape(h, w)
        xn = xx / (w - 1) * 2 - 1
        yn = yy / (h - 1) * 2 - 1
        quad_terms = np.column_stack([t.ravel() for t in (xn * xn, yn * yn, xn * yn,
                                                          xn, yn, np.ones_like(xn))])
        qc, *_ = np.linalg.lstsq(quad_terms, resid.ravel(), rcond=None)
        quad = (quad_terms[:, :3] @ qc[:3]).reshape(h, w)
        mask = _trendfill_mask(arr)
        width = float(np.median(2.0 * distance_transform_edt(mask)[skeletonize(mask)]))
        data = _default_bundle(rel)
        cal = np.asarray(data["calibrated"], float)
        skel = np.asarray(data["skeletonized"]) > 0
        values[f"{name}.plane_slope_nm_per_px"] = slope
        values[f"{name}.hole_width_px"] = width
        values[f"{name}.drop_across_hole_nm"] = slope * width
        values[f"{name}.quadratic_p2p_nm"] = float(quad.max() - quad.min())
        values[f"{name}.skeleton_height_median_nm"] = float(np.median(cal[skel]))
    return values


@experiment(
    "bg_fill",
    ["lib/bg_calibrator.py"],
    "Square holes of 21 px cut into fiber-free background of the tunicate scan: how far "
    "the smoothed background estimate inside each hole, and on the genuine background "
    "beside it, moves from the estimate made with those pixels known, for each "
    "combination of detrending (none, plane, quadratic) and filler (nearest background "
    "pixel, OpenCV Navier-Stokes inpainting with radius 3).",
)
def bg_fill() -> dict:
    import cv2
    import numpy as np
    import kink_reference_score as krs
    from scipy import signal
    from scipy.ndimage import distance_transform_edt, binary_dilation
    from lib.pipeline import ProcParams

    params = ProcParams()
    half = 10          # a 21-px hole
    pad = 45           # crop margin around a hole: beyond the smoothing window
    n_holes = 20
    arr = _raw_scan(krs.SCANS["tunicate"])
    crop = arr[1:, 1:].astype(float)
    fiber = _trendfill_mask(arr)
    h, w = crop.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    xn = xx / (w - 1) * 2 - 1
    yn = yy / (h - 1) * 2 - 1
    terms = {"plane": (xn, yn, np.ones_like(xn)),
             "quadratic": (xn * xn, yn * yn, xn * yn, xn, yn, np.ones_like(xn))}

    def trend(kind, valid):
        if kind == "none":
            return np.zeros_like(crop)
        t = terms[kind]
        design = np.column_stack([v[valid] for v in t])
        coef, *_ = np.linalg.lstsq(design, crop[valid], rcond=None)
        return sum(c * v for c, v in zip(coef, t))

    def estimate(valid, tr, filler, win):
        y0, y1, x0, x1 = win
        sub = (crop - tr)[y0:y1, x0:x1]
        hole = ~valid[y0:y1, x0:x1]
        if filler == "nearest":
            idx = distance_transform_edt(hole, return_distances=False, return_indices=True)
            filled = sub[tuple(idx)]
        else:
            filled = cv2.inpaint(sub.astype(np.float32), hole.astype(np.uint8), 3,
                                 cv2.INPAINT_NS).astype(float)
        smoothed = signal.savgol_filter(filled, params.savgol_window, params.savgol_polyorder)
        return smoothed + tr[y0:y1, x0:x1], filled + tr[y0:y1, x0:x1]

    # Hole centres on a coarse grid, where the hole and its surroundings are free of fibers.
    free = ~binary_dilation(fiber, iterations=half + params.savgol_window)
    centres = [(y, x) for y in range(pad, h - pad, 37) for x in range(pad, w - pad, 37)
               if free[y, x]]
    rng = np.random.default_rng(0)
    centres = [centres[i] for i in sorted(rng.choice(len(centres), n_holes, replace=False))]
    values: dict = {"holes": n_holes, "hole_size_px": 2 * half + 1}
    valid = ~fiber
    trends = {k: trend(k, valid) for k in ("none", "plane", "quadratic")}
    for kind in ("none", "plane", "quadratic"):
        for filler in ("nearest", "inpaint"):
            inside, beside, fill_error = [], [], []
            for cy, cx in centres:
                win = (cy - pad, cy + pad + 1, cx - pad, cx + pad + 1)
                with_hole = valid.copy()
                with_hole[cy - half:cy + half + 1, cx - half:cx + half + 1] = False
                tr2 = trends[kind] if kind == "none" else trend(kind, with_hole)
                base, _ = estimate(valid, trends[kind], filler, win)
                moved, filled = estimate(with_hole, tr2, filler, win)
                diff = np.abs(moved - base)
                hole_local = ~with_hole[win[0]:win[1], win[2]:win[3]] & valid[win[0]:win[1], win[2]:win[3]]
                inside.append(float(diff[hole_local].max()))
                ring = binary_dilation(hole_local, iterations=params.savgol_window // 2) & ~hole_local
                beside.append(float(diff[ring].max()))
                # The filled values themselves, before smoothing, against the heights
                # that were actually measured there.
                # 平滑化前の充填値そのものを、そこで実際に測られた高さと比べる。
                actual = crop[win[0]:win[1], win[2]:win[3]]
                fill_error.append(float(np.abs(filled - actual)[hole_local].max()))
            values[f"{kind}.{filler}.fill_error_median_nm"] = float(np.median(fill_error))
            values[f"{kind}.{filler}.fill_error_max_nm"] = float(np.max(fill_error))
            values[f"{kind}.{filler}.inside_median_nm"] = float(np.median(inside))
            values[f"{kind}.{filler}.inside_max_nm"] = float(np.max(inside))
            values[f"{kind}.{filler}.beside_median_nm"] = float(np.median(beside))
            values[f"{kind}.{filler}.beside_max_nm"] = float(np.max(beside))
    return values


_LEGACY_SCRIPT = """
import sys, numpy as np
sys.path.insert(0, sys.argv[1])
from lib.pipeline import ProcParams, build_stages
from lib.processed_image import ProcessedImage
arr = np.load(sys.argv[2])
image = ProcessedImage(arr, "legacy")
build_stages(ProcParams()).bg_calibrator(image)
np.save(sys.argv[3], np.asarray(image.calibrated_image, dtype=float))
"""


@experiment(
    "bg_legacy_halo",
    ["lib/pipeline.py", "lib/bg_calibrator.py"],
    "A synthetic 512 x 512 scan: a plane rising along X at the steepest slope of the "
    "bundled scans (0.24 nm/px), one straight fiber across it (Gaussian section, 8 nm "
    "high, sigma 3 px) and 0.05 nm noise, calibrated by the default background method "
    "of release 1.0.0 (run from a worktree of tag v1.0.0) and of the current code: "
    "the highest and lowest calibrated background beside the fiber.",
)
def bg_legacy_halo() -> dict:
    import subprocess
    import numpy as np
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    n, slope, height, sigma = 512, 0.24, 8.0, 3.0
    xx = np.tile(np.arange(n, dtype=float), (n, 1))
    axis = n / 2 + 0.3
    fiber = height * np.exp(-0.5 * ((xx - axis) / sigma) ** 2)
    rng = np.random.default_rng(0)
    arr = slope * xx + fiber + rng.normal(0.0, 0.05, xx.shape)
    WORK.mkdir(parents=True, exist_ok=True)
    src = WORK / "bg_legacy_input.npy"
    np.save(src, arr)

    tree = WORK / "worktree_v1.0.0"
    if not tree.is_dir():
        subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), "v1.0.0"],
                       check=True, capture_output=True)
    out = WORK / "bg_legacy_output.npy"
    script = WORK / "bg_legacy_run.py"
    script.write_text(_LEGACY_SCRIPT, encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(tree), str(src), str(out)], check=True)
    legacy = np.load(out)

    image = ProcessedImage(arr, "current")
    build_stages(ProcParams()).bg_calibrator(image)
    current = np.asarray(image.calibrated_image, float)

    # The calibrated grid is the raw grid less its first row and column. Beside the
    # fiber: from 4 sigma off its axis to 4 sigma plus the smoothing half-window.
    # 補正後の格子は生の格子から先頭の行と列を除いたもの。繊維の脇は、軸から
    # 4 sigma 離れた所から、さらに平滑化の半窓幅まで。
    cols = np.arange(n - 1) + 1
    off = np.abs(cols - axis)
    beside = (off >= 4 * sigma) & (off <= 4 * sigma + ProcParams().savgol_window // 2)
    interior = slice(40, n - 41)
    values = {"slope_nm_per_px": slope, "fiber_height_nm": height}
    for name, cal in (("v1_0_0", legacy), ("current", current)):
        band = cal[interior][:, beside]
        values[f"{name}.beside_max_nm"] = float(band.max())
        values[f"{name}.beside_min_nm"] = float(band.min())
        values[f"{name}.beside_row_median_max_nm"] = float(np.median(band, axis=0).max())
    return values


# Visual labels of the loop candidates, keyed by (scan, x, y) of the enclosed
# region's bounding-box centre. Every candidate was rendered over the calibrated
# height image and judged by eye (2026-09-30): "fiber" when the loop lies inside one
# fiber body, "crossing" when it lies where fibers cross or branch, "gap" when two
# separate fibers enclose background between them. A candidate without a label fails
# the experiment, so a change in what the skeletonizer produces forces a new look.
# ループ候補の目視ラベル。囲まれた領域の外接矩形の中心 (scan, x, y) をキーとする。
# 各候補を較正済み高さ画像に重ねて描画し、目視で判断した（2026-09-30）。1 本の繊維
# 本体の内側なら "fiber"、繊維の交差・分岐の場所なら "crossing"、別々の繊維が背景を
# 囲んでいるなら "gap"。ラベルの無い候補があると実験は失敗するため、細線化の結果が
# 変われば見直しが強制される。
LOOP_LABELS = {
    ("hplantTOC", 923, 554): "fiber", ("tunicate", 1001, 367): "fiber",
    ("tunicate", 986, 441): "fiber", ("tunicate", 775, 890): "fiber",
    ("tunicate", 633, 1010): "crossing", ("NDTOC", 641, 219): "crossing",
    ("NDTOC", 812, 232): "fiber", ("NDTOC", 761, 356): "fiber",
    ("NDTOC", 981, 393): "crossing", ("NDTOC", 531, 397): "fiber",
    ("NDTOC", 371, 482): "crossing", ("NDTOC", 953, 500): "crossing",
    ("NDTOC", 912, 505): "crossing", ("NDTOC", 645, 595): "crossing",
    ("NDTOC", 816, 684): "fiber", ("NDTOC", 810, 906): "crossing",
    ("NDTOC", 262, 915): "fiber", ("NDTOC", 151, 947): "fiber",
}


@experiment(
    "loop_candidates",
    ["lib/pipeline.py", "lib/skeletonizer.py"],
    "Every region enclosed by the skeleton that collapse_skeleton_loops considers on "
    "the bundled scans (at most max_loop_area, clear of the border): the median "
    "height inside over the median height of the skeleton ring around it, the branch "
    "points on that ring, and the visual label in LOOP_LABELS.",
)
def loop_candidates() -> dict:
    import cv2
    import numpy as np
    import kink_reference_score as krs
    from lib import imp_tools
    from lib import skeletonizer as sk
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    found = []
    current = {"name": None}
    original = sk.collapse_skeleton_loops

    def spy(skel, max_loop_area=sk.DEFAULT_MAX_LOOP_AREA, calibrated_image=None,
            min_height_ratio=sk.DEFAULT_LOOP_HEIGHT_RATIO):
        s = (np.asarray(skel) > 0).astype(np.uint8)
        bp = imp_tools.branchedPoints(s) > 0
        n, labels, stats, _ = cv2.connectedComponentsWithStats((s == 0).astype(np.uint8),
                                                               connectivity=4)
        h, w = s.shape
        for i in range(1, n):
            x, y, cw, ch, area = stats[i]
            if not (area <= max_loop_area and x > 0 and y > 0 and x + cw < w and y + ch < h):
                continue
            x0, y0 = max(0, x - 2), max(0, y - 2)
            x1, y1 = min(w, x + cw + 2), min(h, y + ch + 2)
            hole = labels[y0:y1, x0:x1] == i
            ring = (cv2.dilate(hole.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) \
                & ~hole & (s[y0:y1, x0:x1] > 0)
            if not ring.any():
                continue
            cal = calibrated_image[y0:y1, x0:x1]
            found.append(dict(key=(current["name"], int(x + cw // 2), int(y + ch // 2)),
                              ratio=float(np.median(cal[hole])) / float(np.median(cal[ring])),
                              branch_points=int((bp[y0:y1, x0:x1] & ring).sum())))
        return original(skel, max_loop_area, calibrated_image, min_height_ratio)

    sk.collapse_skeleton_loops = spy
    try:
        for name, rel in krs.SCANS.items():
            current["name"] = name
            stages = build_stages(ProcParams())
            image = ProcessedImage(_raw_scan(rel), name)
            stages.bg_calibrator(image)
            stages.segmenter(image)
            stages.skeletonizer(image)
    finally:
        sk.collapse_skeleton_loops = original
    unlabeled = [c["key"] for c in found if c["key"] not in LOOP_LABELS]
    if unlabeled:
        raise SystemExit(f"loop candidates without a visual label: {unlabeled}")
    values: dict = {"candidates": len(found)}
    for label in ("fiber", "crossing", "gap"):
        group = [c for c in found if LOOP_LABELS[c["key"]] == label]
        values[f"{label}.count"] = len(group)
        if group:
            values[f"{label}.ratio_percent_range"] = [100 * min(c["ratio"] for c in group),
                                                      100 * max(c["ratio"] for c in group)]
    values["all.ratio_percent_range"] = [100 * min(c["ratio"] for c in found),
                                         100 * max(c["ratio"] for c in found)]
    values["all.branch_points_range"] = [min(c["branch_points"] for c in found),
                                         max(c["branch_points"] for c in found)]
    return values


def _skeleton_counts(skel) -> dict:
    import numpy as np
    from lib import imp_tools
    s = (np.asarray(skel) > 0).astype(np.uint8)
    return {"pixels": int(s.sum()), "branch_points": int(imp_tools.branchedPoints(s).sum())}


@experiment(
    "local_threshold",
    ["lib/pipeline.py", "lib/segmenter.py", "lib/skeletonizer.py"],
    "Binarization with the global threshold alone against the default global AND local "
    "threshold, everything else at the defaults, on each bundled scan: the height of the "
    "pixels the local threshold removes and keeps relative to the highest height within "
    "3 px, the mean mask width (final mask area over final skeleton length), the 8-connected "
    "components of the final mask, and the branch points of the final skeleton.",
)
def local_threshold() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from scipy import ndimage as ndi
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage
    from lib.segmenter import Segmenter

    class GlobalOnly(Segmenter):
        @staticmethod
        def _binaryzation(image, global_threshold, wsize_localbin):
            return image > global_threshold

    params = ProcParams()
    values: dict = {}
    for name, rel in krs.SCANS.items():
        raw = _raw_scan(rel)
        stages = build_stages(params)
        base = ProcessedImage(raw.copy(), name)
        stages.bg_calibrator(base)
        cal = np.asarray(base.calibrated_image, float)
        seg = stages.segmenter
        variants = {"both": seg,
                    "global": GlobalOnly(**{k: getattr(seg, k) for k in (
                        "wsize_localbin", "global_threshold", "area_min",
                        "area_min_connecting", "apply_no_connecting", "h_length",
                        "h_sratio", "low_threshold", "ridge_recovery",
                        "ridge_min_length_nm", "ridge_min_width_nm",
                        "ridge_max_width_nm")})}
        thresholded = {}
        for tag, segmenter in variants.items():
            image = ProcessedImage(raw.copy(), name)
            image.calibrated_image = cal.copy()
            segmenter(image)
            thresholded[tag] = segmenter.binary_image.astype(bool)
            mask = np.asarray(image.binarized_image, bool)
            stages.skeletonizer(image)
            skel = _skeleton_counts(image.skeleton_image)
            values[f"{name}.{tag}.mask_width_px"] = mask.sum() / skel["pixels"]
            values[f"{name}.{tag}.mask_components"] = int(
                ndi.label(mask, structure=np.ones((3, 3)))[1])
            values[f"{name}.{tag}.branch_points"] = skel["branch_points"]
        crest = ndi.maximum_filter(cal, size=7)
        removed = thresholded["global"] & ~thresholded["both"]
        kept = thresholded["both"]
        values[f"{name}.removed_percent_of_crest"] = 100 * float(np.median(cal[removed] / crest[removed]))
        values[f"{name}.kept_percent_of_crest"] = 100 * float(np.median(cal[kept] / crest[kept]))
    return values


@experiment(
    "branch_pruning",
    ["lib/pipeline.py", "lib/skeletonizer.py"],
    "The height-gated pruning of Skeletonizer (set_low_bp_coor to prune_branches) on the "
    "default binarized mask of each bundled scan: the calibrated height at the branch "
    "points of the first skeleton and the share at or above bp_height, the pixels the "
    "pruning removes at the default bp_height and with every branch point treated as low, "
    "and how many pixels of the final skeleton change when the pruning is skipped or every "
    "branch point is treated as low, and when it is skipped with prune_short_spurs also "
    "switched off.",
)
def branch_pruning() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from lib import imp_tools
    from lib import skeletonizer as sk_module
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage
    from lib.skeletonizer import Skeletonizer, thin_ignoring_image_border

    params = ProcParams()
    values: dict = {"bp_height_nm": params.bp_height}
    for name, rel in krs.SCANS.items():
        stages = build_stages(params)
        image = ProcessedImage(_raw_scan(rel), name)
        stages.bg_calibrator(image)
        stages.segmenter(image)
        cal = np.asarray(image.calibrated_image, float)
        mask = np.asarray(image.binarized_image, bool)
        first = thin_ignoring_image_border(mask).astype(bool)
        bp_h = cal[imp_tools.branchedPoints(first.astype(np.uint8)).astype(bool)]
        values[f"{name}.branch_points"] = int(bp_h.size)
        values[f"{name}.bp_height_median_nm"] = float(np.median(bp_h))
        values[f"{name}.bp_at_or_above_percent"] = 100 * float((bp_h >= params.bp_height).mean())
        finals = {}
        for tag, bp_height, spurs in (("default", params.bp_height, True),
                                      ("all_low", np.inf, True),
                                      ("skipped", None, True),
                                      ("spurs_off", params.bp_height, False),
                                      ("spurs_off_skipped", None, False)):
            sk = Skeletonizer(bp_height=params.bp_height if bp_height is None else bp_height,
                              branch_length=params.branch_length, min_area=params.min_area,
                              max_loop_area=params.max_loop_area, spur_length=params.spur_length)
            if bp_height is None:
                sk.prune_branches = lambda calibrated, skeleton: skeleton
            run = ProcessedImage(_raw_scan(rel), name)
            run.calibrated_image = cal.copy()
            run.binarized_image = mask.copy()
            if spurs:
                sk(run)
            else:
                with patched(sk_module, prune_short_spurs=lambda skel, max_length: skel):
                    sk(run)
            finals[tag] = np.asarray(run.skeleton_image) > 0
            if tag in ("default", "all_low"):
                values[f"{name}.{tag}.pruned_pixels"] = int(
                    (first & ~(np.asarray(sk._nobranch_image) > 0)).sum())
        values[f"{name}.final_pixels"] = int(finals["default"].sum())
        values[f"{name}.skipped.final_changed_pixels"] = int((finals["default"] ^ finals["skipped"]).sum())
        values[f"{name}.all_low.final_changed_pixels"] = int((finals["default"] ^ finals["all_low"]).sum())
        values[f"{name}.spurs_off.skipped.final_changed_pixels"] = int(
            (finals["spurs_off"] ^ finals["spurs_off_skipped"]).sum())
    return values


# Every test input of the repository: the bundled scans plus the two Gwyddion
# exports of the higher-plant scan, whose heights differ from its text export.
# testdata_Gwyddion_txt/..._T.ssp2.txt holds the same heights as ..._T.ssp.txt
# and is left out.
# リポジトリのすべてのテスト入力。同梱スキャンに、高等植物のスキャンを Gwyddion で
# 書き出した 2 つ（高さがテキスト書き出しと異なる）を加える。
# testdata_Gwyddion_txt/..._T.ssp2.txt は ..._T.ssp.txt と同じ高さなので除く。
def _all_test_inputs() -> Dict[str, str]:
    import kink_reference_score as krs
    inputs = dict(krs.SCANS)
    inputs["gwy"] = "testdata_Gwyddion_gwy/_20250318-164122_T.ssp.gwy"
    inputs["gwy_txt"] = "testdata_Gwyddion_txt/_20250318-164122_T.ssp.txt"
    return inputs


# Components the linearity filter removes whose bounding box reaches h_length,
# per test input, as counted when every one of them was rendered over the
# calibrated height image and judged by eye (2026-10-06). LINEARITY_FIBER_PIECES
# lists, by the centre of the bounding box, the ones judged to be pieces of real
# fibers (bent fiber pieces and fiber ends cut by the image border); the others
# were background texture, particles and scan-line glitches, or could not be
# told apart. A different count fails the experiment, so a change in what the
# filter removes forces a new look.
# 直線性フィルタが消すかたまりのうち、囲む長方形が h_length に届くものの数
# （テスト入力ごと）。すべてを補正後の高さ画像に重ねて描き、目視で判断したときの
# 数である（2026-10-06）。LINEARITY_FIBER_PIECES は、そのうち本物の繊維の片
# （曲がった繊維片と、画像の端で切れた繊維の端）と判断したものを、囲む長方形の
# 中心で並べる。ほかは背景の凹凸、粒子、走査線のグリッチ、または見分けられない
# ものであった。数が変わると実験は失敗するので、フィルタが消すものが変われば
# 見直しが強制される。
LINEARITY_REMOVED_INSPECTED = {
    "hplantTOC": 12, "tunicate": 4, "NDTOC": 234, "art_iso": 0, "art_aniso": 1,
    "gwy": 12, "gwy_txt": 10,
}
LINEARITY_FIBER_PIECES = {
    ("tunicate", 17, 688), ("tunicate", 10, 843), ("tunicate", 613, 922),
    ("tunicate", 557, 934), ("art_aniso", 739, 246), ("hplantTOC", 106, 1012),
    ("gwy", 106, 1012), ("gwy_txt", 106, 1012), ("gwy_txt", 839, 797),
    ("NDTOC", 591, 1010),
}


@experiment(
    "linearity_filter",
    ["lib/pipeline.py", "lib/segmenter.py"],
    "The linearity filter of Segmenter (_remove_nonlinear_objects) at the defaults: on "
    "every test input, the largest s_ratio and how many components score above 1, and "
    "the components it removes whose bounding box reaches h_length, against the visual "
    "labels in LINEARITY_REMOVED_INSPECTED and LINEARITY_FIBER_PIECES; on synthetic bands "
    "(a line about 120 px long, horizontal or at 45 degrees, dilated three times with the "
    "4-connected element), the Canny edge pixels found "
    "in the bounding-box crop, the s_ratio and whether the band is kept.",
)
def linearity_filter() -> dict:
    import numpy as np
    from scipy import ndimage as ndi
    from skimage.feature import canny
    from lib.afm_io import load_afm_image
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    params = ProcParams()
    values: dict = {}
    total_removed = fibers = above_one = 0
    largest = 0.0
    for name, rel in _all_test_inputs().items():
        stages = build_stages(params)
        image = ProcessedImage(np.asarray(load_afm_image(str(ROOT / rel)), float), name)
        stages.bg_calibrator(image)
        stages.segmenter(image)
        seg = stages.segmenter
        scores = np.asarray(seg.h_sratio_list, float)
        largest = max(largest, float(scores.max()) if scores.size else 0.0)
        above_one += int((scores > 1).sum())
        removed = seg.no_small_binary_image.astype(bool) & ~seg.no_linear_binary_image.astype(bool)
        lab, _ = ndi.label(removed, structure=np.ones((3, 3)))
        centres = []
        for sl in ndi.find_objects(lab):
            if max(sl[0].stop - sl[0].start, sl[1].stop - sl[1].start) >= params.h_length:
                centres.append(((sl[1].start + sl[1].stop) // 2, (sl[0].start + sl[0].stop) // 2))
        if len(centres) != LINEARITY_REMOVED_INSPECTED[name]:
            raise SystemExit(f"{name}: the linearity filter removes {len(centres)} components "
                             f"reaching h_length, {LINEARITY_REMOVED_INSPECTED[name]} were "
                             "inspected; render and judge them again")
        for scan, x, y in LINEARITY_FIBER_PIECES:
            if scan == name and not any(abs(cx - x) <= 3 and abs(cy - y) <= 3 for cx, cy in centres):
                raise SystemExit(f"{name}: the fiber piece at ({x}, {y}) is no longer removed")
        total_removed += len(centres)
        fibers += sum(1 for scan, _, _ in LINEARITY_FIBER_PIECES if scan == name)
    values["inputs"] = len(_all_test_inputs())
    values["s_ratio_max"] = largest
    values["s_ratio_above_one"] = above_one
    values["removed_reaching_h_length"] = total_removed
    values["removed_fiber_pieces"] = fibers

    seg = build_stages(params).segmenter
    for tag, (r0, c0, r1, c1) in (("horizontal", (100, 30, 100, 150)),
                                  ("diagonal", (40, 40, 125, 125))):
        mask = np.zeros((200, 200), bool)
        n = max(abs(r1 - r0), abs(c1 - c0)) + 1
        mask[np.linspace(r0, r1, n).round().astype(int), np.linspace(c0, c1, n).round().astype(int)] = True
        mask = ndi.binary_dilation(mask, iterations=3)
        rows, cols = np.where(mask)
        crop = mask[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
        seg.h_sratio_list = []
        kept = seg._remove_nonlinear_objects(mask, params.h_length, params.h_sratio)
        values[f"band.{tag}.area"] = int(mask.sum())
        values[f"band.{tag}.edge_pixels"] = int(canny(crop, sigma=0, low_threshold=0,
                                                      high_threshold=1).sum())
        values[f"band.{tag}.s_ratio"] = float(seg.h_sratio_list[-1])
        values[f"band.{tag}.kept"] = int(bool(np.asarray(kept).any()))
    return values


@experiment(
    "spline1d_axis",
    ["lib/pipeline.py", "lib/bg_calibrator.py", "lib/segmenter.py"],
    "Every test input calibrated by trendfill and by spline1d along 'x' and along 'y', "
    "everything else at the defaults: on the background (pixels more than 5 px from the "
    "union of the three binarized masks), the spread (standard deviation) of the per-row "
    "and per-column medians of the calibrated height, and of the background pixels "
    "themselves.",
)
def spline1d_axis() -> dict:
    import numpy as np
    from dataclasses import replace
    from scipy import ndimage as ndi
    from lib.afm_io import load_afm_image
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    base = ProcParams()
    variants = {"trendfill": base,
                "x": replace(base, bg_method="spline1d", spline1d_axis="x"),
                "y": replace(base, bg_method="spline1d", spline1d_axis="y")}
    values: dict = {}
    for name, rel in _all_test_inputs().items():
        arr = np.asarray(load_afm_image(str(ROOT / rel)), float)
        cals, fiber = {}, None
        for tag, params in variants.items():
            stages = build_stages(params)
            image = ProcessedImage(arr.copy(), name)
            stages.bg_calibrator(image)
            stages.segmenter(image)
            cals[tag] = np.asarray(image.calibrated_image, float)
            mask = np.asarray(image.binarized_image, bool)
            fiber = mask if fiber is None else fiber | mask
        background = ~ndi.binary_dilation(fiber, iterations=5)
        for tag, cal in cals.items():
            masked = np.where(background, cal, np.nan)
            rows = np.nanmedian(masked[background.sum(axis=1) > 50], axis=1)
            cols = np.nanmedian(masked[:, background.sum(axis=0) > 50], axis=0)
            values[f"{name}.{tag}.row_median_std_nm"] = float(np.std(rows))
            values[f"{name}.{tag}.column_median_std_nm"] = float(np.std(cols))
            values[f"{name}.{tag}.background_std_nm"] = float(np.std(cal[background]))
    return values


SYNTH_DIR = WORK / "synthetic"


def _synthetic():
    import synthetic_suite as ss
    entries = ss.build(SYNTH_DIR)
    for e in entries:
        ss.analyze(e, SYNTH_DIR)
    return ss, entries


@experiment(
    "synthetic_centerline",
    ["lib/pipeline.py", "lib/measure.py", "lib/centerline.py", "lib/kink_detector.py"],
    "On the synthetic suite of scripts/synthetic_suite.py (groups A-F: 60 scans, 2 nm "
    "pixels, W = 8 px; group G: twisted ribbons): the distance of each centerline "
    "method from the true centerline, the contour-length error, the same-sense corner "
    "pairs, and the lateral offset on the ribbons.",
)
def synthetic_centerline() -> dict:
    import numpy as np
    from lib import centerline as cl
    from lib.imp_tools import convert_track_to_distance
    from lib.kink_detector import KinkDetector

    ss, entries = _synthetic()
    af = [e for e in entries if e["group"] != "G"]
    values: dict = {"scans_af": len(af), "scans_g": len(entries) - len(af)}
    methods = list(cl.CENTERLINE_METHODS)
    detector = KinkDetector()

    def line_points(f, method_is_pixel_chain):
        x, y = ss.track(f)
        s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        inner = (s > 0.5 * f.width_px) & (s < s[-1] - 0.5 * f.width_px)
        return x, y, inner

    per_method: dict = {}
    for method in methods:
        by_group: dict = {}
        lengths: dict = {}
        for e in af:
            trees = ss.truth_trees(e)
            _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"), method)
            for f in fibers:
                sx, sy = ss.track(f, line=False)
                ci = ss.nearest_truth(trees, sx, sy)
                if ci is None:
                    continue
                x, y, inner = line_points(f, False)
                if inner.any():
                    d = trees[ci].query(np.column_stack([x[inner], y[inner]]))[0]
                    by_group.setdefault(e["group"], []).extend(d.tolist())
                if len(sx) >= 20:
                    ia = trees[ci].query([sx[0], sy[0]])[1]
                    ib = trees[ci].query([sx[-1], sy[-1]])[1]
                    true_len = abs(ib - ia) * 0.1
                    if true_len > 0:
                        measured = float(np.hypot(np.diff(x), np.diff(y)).sum())
                        lengths.setdefault(e["group"], []).append(measured / true_len - 1.0)
        per_method[method] = (by_group, lengths)
        medians_nm = [ss.NMPX * float(np.median(v)) for v in by_group.values()]
        values[f"{method}.group_median_nm_range"] = [min(medians_nm), max(medians_nm)]
        alld = np.concatenate([np.asarray(v) for v in by_group.values()])
        values[f"{method}.median_px"] = float(np.median(alld))
        values[f"{method}.p95_px"] = float(np.percentile(alld, 95))
        lerr = [100.0 * float(np.median(v)) for v in lengths.values()]
        values[f"{method}.length_error_percent_range"] = [min(lerr), max(lerr)]

    # The skeleton track itself, measured with the corrected chain-code metric.
    # スケルトントラックそのもの。補正済みチェーンコードで長さを測る。
    by_group, lengths = {}, {}
    for e in af:
        trees = ss.truth_trees(e)
        _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"))
        for f in fibers:
            sx, sy = ss.track(f, line=False)
            ci = ss.nearest_truth(trees, sx, sy)
            if ci is None:
                continue
            s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(sx), np.diff(sy)))])
            inner = (s > 0.5 * f.width_px) & (s < s[-1] - 0.5 * f.width_px)
            if inner.any():
                d = trees[ci].query(np.column_stack([sx[inner], sy[inner]]))[0]
                by_group.setdefault(e["group"], []).extend(d.tolist())
            if len(sx) >= 20:
                ia = trees[ci].query([sx[0], sy[0]])[1]
                ib = trees[ci].query([sx[-1], sy[-1]])[1]
                true_len = abs(ib - ia) * 0.1
                if true_len > 0:
                    measured = float(convert_track_to_distance(sx, sy, 1.0)[-1])
                    lengths.setdefault(e["group"], []).append(measured / true_len - 1.0)
    alld = np.concatenate([np.asarray(v) for v in by_group.values()])
    values["skeleton_track.median_px"] = float(np.median(alld))
    values["skeleton_track.p95_px"] = float(np.percentile(alld, 95))
    lerr = [100.0 * float(np.median(v)) for v in lengths.values()]
    values["skeleton_track.length_error_percent_range"] = [min(lerr), max(lerr)]

    # Same-sense corner pairs (group C) on the default line (W/4) and on the line
    # smoothed over half a width.
    # 同じ向きのコーナー対（C 群）。既定の線（W/4）と、半幅で平滑化した線。
    pairs = [e for e in af if e["group"] == "C"]
    values["pairs"] = len(pairs)
    for label, method in (("w4", cl.HALF_MAX_025W_CENTERLINE), ("w2", cl.HALF_MAX_05W_CENTERLINE)):
        merged_pairs = 0
        vertex_by_spacing: dict = {}
        dist = []
        for e in pairs:
            trees = ss.truth_trees(e)
            _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"), method)
            tracks = [ss.track(f, line=False) for f in fibers]
            refs = ss.truth_refs(e, tracks)
            merged = 0
            for i, f in enumerate(fibers):
                x, y = ss.track(f)
                judged = detector.judge_line(x, y, f.width_px)
                dets = [(float(x[k]), float(y[k])) for k in judged.kink_indices]
                merged += ss.match(refs.get(i, []), dets, f.width_px)["merged"]
                dense = ss.densify(x, y)
                from scipy.spatial import cKDTree
                tree = cKDTree(dense)
                for rx, ry, cls in refs.get(i, []):
                    if cls == "clear":
                        vertex_by_spacing.setdefault(e["case"], []).append(float(tree.query([rx, ry])[0]))
                ci = ss.nearest_truth(trees, *tracks[i])
                if ci is not None:
                    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
                    inner = (s > 0.5 * f.width_px) & (s < s[-1] - 0.5 * f.width_px)
                    dist += trees[ci].query(np.column_stack([x[inner], y[inner]]))[0].tolist()
            merged_pairs += int(merged > 0)
        vmed = [float(np.median(v)) for v in vertex_by_spacing.values()]
        values[f"pairs_{label}.merged_pairs"] = merged_pairs
        values[f"pairs_{label}.vertex_median_px_range"] = [min(vmed), max(vmed)]
        values[f"pairs_{label}.centerline_median_px"] = float(np.median(dist))

    # Twisted ribbons (group G): lateral offset from the straight axis.
    # ねじれリボン（G 群）。直線の軸からの横方向のずれ。
    ribbons = [e for e in entries if e["group"] == "G"]
    ratios = []
    kinks_on_ribbons = 0
    for e in ribbons:
        trees = ss.truth_trees(e)
        rms = {}
        maxdev = {}
        for method in (cl.HALF_MAX_025W_CENTERLINE, cl.CREST_CENTERLINE, cl.QUARTER_MAX_CENTERLINE):
            _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"), method)
            d_all = []
            for f in fibers:
                x, y = ss.track(f)
                s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
                inner = (s > 0.5 * f.width_px) & (s < s[-1] - 0.5 * f.width_px)
                d_all += trees[0].query(np.column_stack([x[inner], y[inner]]))[0].tolist()
                if method == cl.HALF_MAX_025W_CENTERLINE:
                    kinks_on_ribbons += len(detector.judge_line(x, y, f.width_px).kink_indices)
            d_all = np.asarray(d_all)
            rms[method] = float(np.sqrt(np.mean(d_all ** 2)))
            maxdev[method] = float(d_all.max())
        values[f"{e['tag']}.rms_px.default"] = rms[cl.HALF_MAX_025W_CENTERLINE]
        values[f"{e['tag']}.rms_px.crest"] = rms[cl.CREST_CENTERLINE]
        values[f"{e['tag']}.rms_px.quarter_max"] = rms[cl.QUARTER_MAX_CENTERLINE]
        values[f"{e['tag']}.max_nm.quarter_max"] = ss.NMPX * maxdev[cl.QUARTER_MAX_CENTERLINE]
        if e["ribbon"][0] > 0:
            ratios.append(rms[cl.CREST_CENTERLINE] / rms[cl.HALF_MAX_025W_CENTERLINE])
    aniso = [e["tag"] for e in ribbons if e["ribbon"][0] > 0]
    values["ribbons.quarter_closer_than_default"] = sum(
        values[f"{t}.rms_px.quarter_max"] < values[f"{t}.rms_px.default"] for t in aniso)
    values["ribbons.crest_farthest_of_three"] = sum(
        values[f"{t}.rms_px.crest"] > max(values[f"{t}.rms_px.default"],
                                          values[f"{t}.rms_px.quarter_max"]) for t in aniso)
    values["ribbons.crest_over_default_range"] = [min(ratios), max(ratios)]
    values["ribbons.anisotropic_count"] = len(ratios)
    values["ribbons.count"] = len(ribbons)
    values["ribbons.kinks_reported"] = kinks_on_ribbons
    return values


@experiment(
    "synthetic_kinks",
    ["lib/pipeline.py", "lib/measure.py", "lib/centerline.py", "lib/kink_detector.py"],
    "The kink rule on the synthetic suite of scripts/synthetic_suite.py (default "
    "centerline): the excess read at isolated corners, corners found in zigzags, "
    "bends reported on straight fibers, arcs, meanders, crossings and branches, the "
    "earlier polyline rule on the arcs and meanders, and corners near an end judged at "
    "an end margin of 1.5 W and 2.0 W.",
)
def synthetic_kinks() -> dict:
    import math
    import numpy as np
    from lib import kink_detector as kd
    from lib.kink_detector import KinkDetector

    ss, entries = _synthetic()
    detector = KinkDetector()
    old = KinkDetector(threshold_distance=3.0,
                       threshold_angle_from_decomposed_indices=math.radians(150.0))
    values: dict = {}

    def judge(e, margin=None):
        _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"))
        tracks = [ss.track(f, line=False) for f in fibers]
        refs = ss.truth_refs(e, tracks)
        total = dict.fromkeys(ss.KEYS, 0)
        reported = 0
        excess_near = []
        for i, f in enumerate(fibers):
            x, y = ss.track(f)
            if margin is None:
                judged = detector.judge_line(x, y, f.width_px)
            else:
                with patched(kd, END_MARGIN_WIDTHS=margin):
                    judged = detector.judge_line(x, y, f.width_px)
            reported += len(judged.kink_indices)
            dets = [(float(x[k]), float(y[k])) for k in judged.kink_indices]
            res = ss.match(refs.get(i, []), dets, f.width_px)
            for k in ss.KEYS:
                total[k] += res[k]
            for tx, ty, _dev, cls in e["kinks"]:
                near = [(math.hypot(dx - tx, dy - ty), math.degrees(float(ex)))
                        for (dx, dy), ex in zip(dets, judged.kink_excess)]
                near = [n for n in near if n[0] <= f.width_px]
                if near:
                    excess_near.append(min(near)[1])
        return total, reported, excess_near, fibers

    # Isolated corners (group A).
    for turn in ss.CORNER_TURNS:
        group = [e for e in entries if e["case"] == f"A_corner{turn}"]
        reads, found, clear = [], 0, 0
        for e in group:
            total, _rep, excess, _f = judge(e)
            reads += excess
            found += total["found"]
            clear += total["clear"]
        values[f"corner{turn}.found"] = found
        values[f"corner{turn}.clear"] = clear
        if reads:
            values[f"corner{turn}.excess_read_range_deg"] = [min(reads), max(reads)]
    corners40 = [t for t in ss.CORNER_TURNS if t >= 40]
    values["corners_40_up.found"] = sum(values[f"corner{t}.found"] for t in corners40)
    values["corners_40_up.clear"] = sum(values[f"corner{t}.clear"] for t in corners40)

    # Zigzags (group B).
    for sp in ss.SPACINGS_W:
        found = clear = 0
        for e in entries:
            if e["case"] == f"B_zigzag{sp:g}W":
                total, _r, _x, _f = judge(e)
                found += total["found"]
                clear += total["clear"]
        values[f"zigzag{sp:g}W.found"] = found
        values[f"zigzag{sp:g}W.clear"] = clear
    wide = [sp for sp in ss.SPACINGS_W if sp >= 1.5]
    values["zigzag_1.5W_up.found"] = sum(values[f"zigzag{sp:g}W.found"] for sp in wide)
    values["zigzag_1.5W_up.clear"] = sum(values[f"zigzag{sp:g}W.clear"] for sp in wide)

    # Smooth families and crossings: every bend the rule reports there is false.
    families = {
        "straight": [e for e in entries if e["case"] == "E_straight"],
        "arcs": [e for e in entries if e["case"].startswith("E_arc")],
        "sines": [e for e in entries if e["case"].startswith("E_sine")],
        "crossings_branches": [e for e in entries if e["group"] == "F" and e["case"] != "F_merge"],
    }
    for name, group in families.items():
        values[f"{name}.reported"] = sum(judge(e)[1] for e in group)
        values[f"{name}.scans"] = len(group)
    tightest = [lam ** 2 / (4 * math.pi ** 2 * amp) for amp, lam in ss.SINES]
    values["sines.tightest_radius_w_range"] = [min(tightest), max(tightest)]
    old_reported = 0
    for e in families["arcs"] + families["sines"]:
        _img, fibers = ss.fibers_of(str(SYNTH_DIR / f"{e['tag']}.b2z"))
        for f in fibers:
            sx, sy = ss.track(f, line=False)
            old_reported += len(old.kinks_and_decomposed_from_track(sx, sy)[0])
    values["old_rule.arcs_sines_reported"] = old_reported

    # Corners near an end (group D) judged at the default margin and at 2.0 W.
    for margin, label in ((None, "margin_default"), (2.0, "margin_2W")):
        for e_w in (1.5, 2.0):
            judged_found = 0
            for e in entries:
                if e["case"] == f"D_end{e_w:g}W":
                    total, _r, excess, _f = judge(e, margin)
                    judged_found += len(excess)
            values[f"{label}.end{e_w:g}W.corners_judged"] = judged_found
    values["end_cases_per_distance"] = len([e for e in entries if e["case"] == "D_end1.5W"])
    return values


@experiment(
    "closing_gaps",
    [],
    "skimage.morphology.closing with its default footprint on two straight bands of "
    "equal thickness separated by a gap: whether it joins them into one component, "
    "for thicknesses 1, 3 and 5 px and gaps 1, 2 and 3 px.",
)
def closing_gaps() -> dict:
    import numpy as np
    from scipy.ndimage import label
    from skimage.morphology import closing

    values: dict = {}
    for thick in (1, 3, 5):
        for gap in (1, 2, 3):
            a = np.zeros((20, 30), bool)
            a[8:8 + thick, 2:12] = True
            a[8:8 + thick, 12 + gap:28] = True
            values[f"thick{thick}.gap{gap}.joined"] = int(label(closing(a))[1] == 1)
    for thick in (3, 5):
        joined = [g for g in (1, 2, 3) if values[f"thick{thick}.gap{g}.joined"]]
        values[f"thick{thick}.largest_gap_joined_px"] = max(joined) if joined else 0
    values["thick1.gaps_joined"] = sum(values[f"thick1.gap{g}.joined"] for g in (1, 2, 3))
    return values


@experiment(
    "ridge_hysteresis",
    ["lib/pipeline.py", "lib/segmenter.py"],
    "On the bundled tunicate scan (5 um): the ridge filter of _recover_missed_ridges and "
    "the calibrated heights themselves, each thresholded by hysteresis with the Otsu "
    "high and triangle low levels; the fraction of the image each covers, and the "
    "fraction of the ridge response below its low level on pixels at least 10 px from "
    "the default binarized mask.",
)
def ridge_hysteresis() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from scipy.ndimage import distance_transform_edt
    from skimage.filters import apply_hysteresis_threshold, frangi, threshold_otsu, threshold_triangle
    from lib.pipeline import ProcParams

    base = ProcParams()
    data = _default_bundle(krs.SCANS["tunicate"])
    cal = np.asarray(data["calibrated"], float)
    nm_per_px = 5.0 * 1000.0 / cal.shape[1]
    lo = max(0.6, base.ridge_min_width_nm / nm_per_px)
    hi = max(lo * 1.5, base.ridge_max_width_nm / nm_per_px)
    response = np.nan_to_num(frangi(cal, sigmas=np.geomspace(lo, hi, 5), black_ridges=False))
    far = distance_transform_edt(~(np.asarray(data["binarized"]) > 0)) >= 10

    def cover(img):
        high, low = threshold_otsu(img), threshold_triangle(img)
        if not low < high:
            low = high * 0.3
        return float(apply_hysteresis_threshold(img, low, high).mean()), low

    ridge_cover, ridge_low = cover(response)
    height_cover, _ = cover(cal)
    return {
        "ridge.cover_percent": 100.0 * ridge_cover,
        "height.cover_percent": 100.0 * height_cover,
        "ridge.far_below_low_percent": 100.0 * float((response[far] < ridge_low).mean()),
    }


@experiment(
    "turn_maxima",
    ["lib/pipeline.py", "lib/measure.py", "lib/kink_detector.py", "lib/centerline.py"],
    "The visual reference of kink_reference scored with the rule as it is and with its "
    "second kind of candidate (maxima of |T| away from any accepted curvature maximum) "
    "disabled: the clear kinks found and the unmatched bends of each.",
)
def turn_maxima() -> dict:
    import inspect
    import re
    import textwrap
    import kink_reference_score as krs
    from lib import kink_detector as kd
    from lib.kink_detector import KinkDetector
    from lib.pipeline import ProcParams

    refs = krs.load_reference()
    cache = str(WORK / "kink_reference_half_max_025w")
    scans = {name: krs.prepare_scan(name, cache, ProcParams()) for name in krs.SCANS}

    def score():
        out = dict(found=0, false=0)
        detector = KinkDetector()
        for name, (_image, fibers) in scans.items():
            kinks, unjudged = krs.detect(fibers, detector, krs.EXCLUDED_FIBERS.get(name, set()))
            res = krs.score(refs[name], kinks, unjudged)
            out["found"] += res["found"]
            out["false"] += res["false"]
        return out

    with_all = score()
    current = KinkDetector.judge_line
    source = textwrap.dedent(inspect.getsource(current))
    assert source.count("if grid.size >= 3:") == 1, "the |T| candidate block was not found"
    namespace = dict(vars(kd))
    exec(compile(source.replace("if grid.size >= 3:", "if False:"), "<no |T| maxima>", "exec"),
         namespace)
    KinkDetector.judge_line = namespace["judge_line"]
    try:
        without = score()
    finally:
        KinkDetector.judge_line = current
    return {"with.found": with_all["found"], "with.false": with_all["false"],
            "without.found": without["found"], "without.false": without["false"],
            "clear_kinks_lost_without": with_all["found"] - without["found"]}


@experiment(
    "y_branch_kink",
    ["lib/pipeline.py", "lib/measure.py", "lib/kink_detector.py", "lib/centerline.py"],
    "On the bundled higher-plant TOC scan, the bend the earlier polyline rule reports "
    "on the skeleton track below the Y-branch near pixel (288, 695) (viewed on the "
    "height image, 2026-09-30: two fibers join and the trunk below does not bend), and "
    "the kinks the current rule reports within one apparent width of it.",
)
def y_branch_kink() -> dict:
    import math
    import numpy as np
    import kink_reference_score as krs
    from lib.kink_detector import KinkDetector
    from lib.pipeline import ProcParams

    target = (288.0, 695.0)
    _image, fibers = krs.prepare_scan("hplantTOC", str(WORK / "kink_reference_half_max_025w"),
                                      ProcParams())
    old = KinkDetector(threshold_distance=3.0,
                       threshold_angle_from_decomposed_indices=math.radians(150.0))
    best = None
    for f in fibers:
        x = np.asarray(f.skeleton_xtrack, float) + float(f.data[0])
        y = np.asarray(f.skeleton_ytrack, float) + float(f.data[1])
        idx, ang, _ = old.kinks_and_decomposed_from_track(x, y)
        for k, a in zip(idx, ang):
            d = math.hypot(x[k] - target[0], y[k] - target[1])
            if d <= 5 and (best is None or d < best[0]):
                lx = np.asarray(f.xtrack, float) + float(f.data[0])
                ly = np.asarray(f.ytrack, float) + float(f.data[1])
                near = sum(math.hypot(lx[j] - x[k], ly[j] - y[k]) <= f.width_px
                           for j in f.kink_indices)
                best = (d, math.degrees(a), near)
    if best is None:
        raise SystemExit("the earlier rule reports no bend near (288, 695) any more")
    return {"old_rule_angle_deg": best[1], "current_kinks_within_one_width": int(best[2])}


@experiment(
    "test_suite_bend",
    ["lib/pipeline.py", "lib/kink_detector.py", "lib/centerline.py"],
    "The bent fiber of tests/conftest.write_synthetic_fiber_txt (two segments meeting "
    "at a 146.5 degree interior angle, a 33.5 degree turn), analyzed as "
    "tests/test_pipeline.test_detects_the_drawn_kink does (tophat, kinkangle_deg 155): "
    "the excess turning the rule reads at the bend.",
)
def test_suite_bend() -> dict:
    import math
    import conftest
    import numpy as np
    from lib.pipeline import ProcParams, process_file

    out = WORK / "test_suite_bend"
    out.mkdir(parents=True, exist_ok=True)
    txt = conftest.write_synthetic_fiber_txt(str(out))
    image = process_file(txt, ProcParams(bg_method="tophat", kinkangle_deg=155.0),
                         output_dir=str(out)).image
    excess = np.asarray(image.all_kink_excess, float)
    if excess.size != 1:
        raise SystemExit(f"expected one kink, found {excess.size}")
    # The fixture draws (30, 30) -> (100, 90) -> (120, 160).
    # フィクスチャは (30, 30) -> (100, 90) -> (120, 160) を描く。
    turn = math.degrees(math.atan2(70, 20)) - math.degrees(math.atan2(60, 70))
    read = math.degrees(float(excess[0]))
    return {"drawn_turn_deg": turn, "read_excess_deg": read, "read_interior_deg": 180.0 - read}


@experiment(
    "border_drift",
    ["lib/pipeline.py", "lib/skeletonizer.py", "lib/measure.py"],
    "Per bundled scan, thinned without and with the replicated border: the lateral "
    "distance from each skeleton point to the height crest along the point's normal "
    "(within half the fiber's apparent width), for the last 5 points of tracks that "
    "end within 2 px of the image edge and for points more than 10 px from either end.",
)
def border_drift() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from skimage.morphology import thin
    from lib import skeletonizer as sk_mod
    from lib.centerline import sample_height
    from lib.fiber import skeleton_track
    from lib.pipeline import ProcParams

    def offsets(image, fibers):
        cal = np.asarray(image.calibrated_image, float)
        h, w = cal.shape
        end_off, mid_off = [], []
        for f in fibers:
            sx, sy = skeleton_track(f)
            x = np.asarray(sx, float) + float(f.data[0])
            y = np.asarray(sy, float) + float(f.data[1])
            n = x.size
            if n < 25:
                continue
            half = max(0.5 * float(f.width_px), 2.0)
            s = np.arange(-half, half + 1e-9, 0.25)
            for i in range(n):
                a, b = max(0, i - 3), min(n - 1, i + 3)
                tx, ty = x[b] - x[a], y[b] - y[a]
                norm = np.hypot(tx, ty) or 1.0
                nx, ny = -ty / norm, tx / norm
                prof = sample_height(cal, x[i] + nx * s, y[i] + ny * s)
                off = abs(float(s[int(np.argmax(prof))]))
                near_edge_end = [(j, (x[j] <= 2 or y[j] <= 2 or x[j] >= w - 3 or y[j] >= h - 3))
                                 for j in (0, n - 1)]
                if any(e and abs(i - j) < 5 for j, e in near_edge_end):
                    end_off.append(off)
                elif 10 < i < n - 11:
                    mid_off.append(off)
        return end_off, mid_off

    values: dict = {}
    original = sk_mod.thin_ignoring_image_border
    for mode in ("plain", "padded"):
        if mode == "plain":
            sk_mod.thin_ignoring_image_border = lambda img, pad=0: thin(
                np.asarray(img) > 0).astype(np.uint8)
        try:
            ends, mids = [], []
            for name in krs.SCANS:
                cache = str(WORK / f"border_drift_{mode}")
                image, fibers = krs.prepare_scan(name, cache, ProcParams())
                e, m = offsets(image, fibers)
                ends += e
                mids += m
        finally:
            sk_mod.thin_ignoring_image_border = original
        values[f"{mode}.end_points"] = len(ends)
        values[f"{mode}.end_median_px"] = float(np.median(ends)) if ends else None
        values[f"{mode}.middle_median_px"] = float(np.median(mids)) if mids else None
    return values


@experiment(
    "hough_edge_map",
    ["lib/pipeline.py", "lib/segmenter.py"],
    "Per bundled scan: whether the final binarized mask is identical when the "
    "linearity filter builds each component's edge map from the component alone (the "
    "current code) or, as up to release 1.0.0, from the whole working mask inside the "
    "component's bounding box.",
)
def hough_edge_map() -> dict:
    import inspect
    import textwrap
    import numpy as np
    import kink_reference_score as krs
    from lib import segmenter as seg_mod
    from lib.pipeline import ProcParams, build_stages
    from lib.processed_image import ProcessedImage

    current = seg_mod.Segmenter._remove_nonlinear_objects
    import re
    source = textwrap.dedent(inspect.getsource(current))
    pattern = re.compile(
        r"target = label_image\[(\s*top : top \+ height, left : left \+ width\s*)\] == i")
    assert len(pattern.findall(source)) == 1, "the current edge-map line was not found"
    namespace = dict(vars(seg_mod))
    exec(compile(pattern.sub(r"target = out_binary_image[\1]", source),
                 "<edge map up to 1.0.0>", "exec"), namespace)
    legacy = namespace["_remove_nonlinear_objects"]

    identical = 0
    values: dict = {}
    for name, rel in krs.SCANS.items():
        stages = build_stages(ProcParams())
        image = ProcessedImage(_raw_scan(rel), name)
        stages.bg_calibrator(image)
        stages.segmenter(image)
        now = np.asarray(image.binarized_image, bool)
        seg_mod.Segmenter._remove_nonlinear_objects = legacy
        try:
            stages.segmenter(image)
        finally:
            seg_mod.Segmenter._remove_nonlinear_objects = current
        before = np.asarray(image.binarized_image, bool)
        same = bool((now == before).all())
        identical += int(same)
        values[f"{name}.identical"] = int(same)
    values["scans"] = len(krs.SCANS)
    values["identical"] = identical
    return values


@experiment(
    "tophat_border",
    ["lib/bg_calibrator.py"],
    "A 256 x 256 plane rising along X at the steepest slope found on the bundled "
    "scans (0.24 nm/px), opened with the default 25-px ellipse: the largest residual "
    "within 12 px of the uphill edge, opening the raw ramp (before the fix) and the "
    "detrended ramp (the current code).",
)
def tophat_border() -> dict:
    import cv2
    import numpy as np
    from lib.pipeline import ProcParams

    slope = 0.24
    size = ProcParams().tophat_se_size | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    n = 256
    xx = np.tile(np.arange(n, dtype=float), (n, 1))
    ramp = slope * xx
    rng = np.random.default_rng(0)
    img = ramp + rng.normal(0.0, 0.05, ramp.shape)
    raw_open = cv2.morphologyEx(img.astype(np.float32), cv2.MORPH_OPEN, se).astype(float)
    trend = np.polyval(np.polyfit(xx.ravel(), img.ravel(), 1), xx)
    det_open = cv2.morphologyEx((img - trend).astype(np.float32), cv2.MORPH_OPEN, se).astype(float) + trend
    band = slice(n - 12, n)
    return {
        "slope_nm_per_px": slope,
        "element_px": size,
        "raw.uphill_band_max_nm": float((img - raw_open)[:, band].max()),
        "detrended.uphill_band_max_nm": float((img - det_open)[:, band].max()),
        "raw.interior_median_nm": float(np.median((img - raw_open)[:, 60:196])),
    }


@experiment(
    "track_ends",
    ["lib/pipeline.py", "lib/measure.py"],
    "Per bundled scan: the fraction of traced track ends that lie within 3 px of a "
    "branch point of the skeleton.",
)
def track_ends() -> dict:
    import numpy as np
    import kink_reference_score as krs
    from scipy.ndimage import distance_transform_edt
    from lib.fiber import skeleton_track
    from lib.pipeline import ProcParams

    values: dict = {}
    cache = str(WORK / "kink_reference_half_max_025w")
    for name in krs.SCANS:
        image, fibers = krs.prepare_scan(name, cache, ProcParams())
        dist = distance_transform_edt(~(np.asarray(image.bp) > 0))
        near = total = 0
        for f in fibers:
            sx, sy = skeleton_track(f)
            for x, y in ((sx[0], sy[0]), (sx[-1], sy[-1])):
                total += 1
                near += int(dist[int(y) + int(f.data[1]), int(x) + int(f.data[0])] <= 3.0)
        values[f"{name}.ends"] = total
        values[f"{name}.near_branch_percent"] = 100.0 * near / total if total else None
    return values


@experiment(
    "ridge_recovery_bundled",
    ["lib/pipeline.py", "lib/segmenter.py"],
    "Ridge recovery switched on for each bundled scan at its recorded scan size: the "
    "candidate components outside the thresholded mask whose skeleton reaches "
    "ridge_min_length_nm, how many of them touch that mask (the earlier rule dropped "
    "those), and the longest.",
)
def ridge_recovery_bundled() -> dict:
    import cv2
    import numpy as np
    import kink_reference_score as krs
    from dataclasses import replace
    from scipy.ndimage import binary_dilation
    from skimage.filters import apply_hysteresis_threshold, frangi, threshold_otsu, threshold_triangle
    from skimage.morphology import skeletonize
    from lib.bundle_schema import scan_size_um_from_meta
    from lib import blosc2_io
    from lib.pipeline import ProcParams, process_file

    values: dict = {}
    base = ProcParams()
    for name, rel in krs.SCANS.items():
        data = _default_bundle(rel)
        # The scan size recorded with the bundled test data (instrument header or the
        # dataset's scale table), since the raw text of most scans carries none.
        # 同梱テストデータに記録された走査サイズ（装置ヘッダまたはデータセットの
        # スケール表）。多くの走査の生テキストには走査サイズが無いため。
        recorded = ROOT / (str(Path(rel).with_suffix("")) + ".b2z")
        size = scan_size_um_from_meta(blosc2_io.load_bundle_meta(str(recorded))) \
            if recorded.is_file() else None
        cal = np.asarray(data["calibrated"], float)
        if not size:
            continue
        sx = float(size[0])
        nm_per_px = sx * 1000.0 / cal.shape[1]
        # The thresholded mask the recovery runs against: re-run segmentation with
        # recovery off up to the low-height filter (the default bundle's binarized
        # image is exactly that mask closed).
        from lib.pipeline import build_stages
        from lib.processed_image import ProcessedImage
        seg = build_stages(base).segmenter
        img = ProcessedImage(_raw_scan(rel), name)
        img.calibrated_image = cal
        seg(img)
        mask = seg.no_low_binary_image.astype(bool)
        lo = max(0.6, base.ridge_min_width_nm / nm_per_px)
        hi = max(lo * 1.5, base.ridge_max_width_nm / nm_per_px)
        response = np.nan_to_num(frangi(cal, sigmas=np.geomspace(lo, hi, 5), black_ridges=False))
        high, low = threshold_otsu(response), threshold_triangle(response)
        if not low < high:
            low = high * 0.3
        outside = apply_hysteresis_threshold(response, low, high) & ~mask
        n, labels = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
        kept = touching = 0
        longest = 0.0
        grown = binary_dilation(mask)
        for lab in range(1, n):
            comp = labels == lab
            length = float(skeletonize(comp).sum()) * nm_per_px
            if length >= base.ridge_min_length_nm:
                kept += 1
                touching += int((comp & grown).any())
                longest = max(longest, length)
        values[f"{name}.scan_um"] = sx
        values[f"{name}.kept"] = kept
        values[f"{name}.touching_mask"] = touching
        values[f"{name}.longest_nm"] = longest
    return values


# ----------------------------------------------------------------------------
# Recording
# ----------------------------------------------------------------------------

def _clean(value):
    import numpy as np
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else round(value, 6)
    return value


def _read() -> dict:
    return (json.loads(MEASUREMENTS.read_text(encoding="utf-8")) if MEASUREMENTS.is_file()
            else {"snapshots": {}, "experiments": {}})


def record(names: Sequence[str]) -> None:
    """
    Run the experiments and write each one's values as soon as it finishes.
    実験を実行し、終わるたびにその値を書き込む。

    The file is re-read before every write, so two processes measuring
    different experiments do not overwrite each other's results.
    書き込みのたびにファイルを読み直すため、別々の実験を測る 2 つのプロセスが
    互いの結果を上書きしない。
    """
    for name in names:
        spec = EXPERIMENTS[name]
        print(f"[measure_docs] {name}: {spec['description']}", flush=True)
        t0 = time.time()
        values = _clean(spec["func"]())
        snap = snapshot(closure(spec["roots"]))
        snap_id = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]
        data = _read()
        data["_comment"] = (
            "Values the algorithm documents cite with <!--m:experiment.key-->, written by "
            "scripts/measure_docs.py and checked by scripts/check_doc_numbers.py. Each "
            "experiment names the snapshot of the analysis code it ran on; a change to what "
            "that code computes marks it stale. Do not edit by hand."
        )
        data["snapshots"][snap_id] = snap
        data["experiments"][name] = dict(description=spec["description"],
                                         snapshot=snap_id, values=values)
        used = {e["snapshot"] for e in data["experiments"].values()}
        data["snapshots"] = {k: v for k, v in data["snapshots"].items() if k in used}
        MEASUREMENTS.write_text(
            json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"[measure_docs] {name}: {len(values)} values in {time.time() - t0:.0f} s",
              flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--only", nargs="*", help="experiments to run (default: all)")
    parser.add_argument("--list", action="store_true", help="list the experiments")
    args = parser.parse_args(argv)
    if args.list:
        for name, spec in EXPERIMENTS.items():
            print(f"{name}: {spec['description']}")
        return 0
    names = args.only or list(EXPERIMENTS)
    unknown = [n for n in names if n not in EXPERIMENTS]
    if unknown:
        parser.error(f"unknown experiment(s): {unknown}")
    WORK.mkdir(parents=True, exist_ok=True)
    record(names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
