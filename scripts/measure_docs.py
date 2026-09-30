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
