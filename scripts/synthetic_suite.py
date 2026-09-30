#!/usr/bin/env python3
"""Synthetic scans with known centerlines and kinks, and how to score them.
中心線とキンクが既知の合成走査と、その採点方法。

`scripts/measure_docs.py` measures the synthetic results the algorithm
documents quote on these scans. The scenes are those the centerline and kink
rule were chosen on (2026-09-15, first written as a scratch probe); the
geometry, rendering settings and seeds are kept unchanged so a result here can
be compared with the one that chose the rule.
`scripts/measure_docs.py` は、アルゴリズム解説文書が引用する合成データの結果を
これらの走査で測る。場面は中心線とキンク規則を選んだときのもの（2026-09-15、
当初は作業用の試作として書いた）であり、形状・描画設定・シードは変えていない。
そのため、ここでの結果を規則を選んだときの結果と比べられる。

Groups
  A  isolated corners turning 20/30/40/60/90/120 degrees
  B  zigzags of alternating 60 degree corners spaced 1/1.5/2/3 W
  C  same-sense pairs of 60 degree corners spaced 1/1.5/2/3 W
  D  a 60 degree corner 1/1.5/2/3 W from a fiber end
  E  a straight fiber, arcs of radius 3/5/10 W turning 120 degrees, and two sine
     meanders (amplitude, wavelength) = (1, 8) W and (2, 12) W
  F  crossings at 30/60/90 degrees, fibers ending on another at 30/60 degrees,
     and a fiber merging into another side by side
  G  twisted anisotropic ribbons on a straight axis, and a round control fiber
Groups A-F are drawn with seeds 0 and 1 (60 scans), G once (6 scans). A truth
kink turning 40 degrees or more is "clear", 25-40 "ambiguous", below 25 "none";
a corner closer than 1.5 W to a fiber end is "ambiguous".

Truth coordinates are stored on the bundle's grid: synthetic coordinates less
1.5 (0.5 for the pixel centre and 1 for BGCalibrator's [1:, 1:] crop).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import synthetic_fibers as sf  # noqa: E402

NMPX = 2.0
DIAM, TIP = 4.0, 15.0
# Full width at half maximum of a cylinder dilated by a spherical tip, in px (8.0).
# 球状探針で膨張した円柱の半値全幅（px、8.0）。
W = 2.0 * math.sqrt((DIAM / 2) ** 2 + 2 * TIP * DIAM / 2) / NMPX
REND = dict(fiber_diameter_nm=DIAM, taper_nm=10.0, taper_end_ratio=0.3, tip_radius_nm=TIP,
            noise_nm=0.05, line_noise_nm=0.03, tilt_nm=1.0, roughness_nm=0.3,
            roughness_corr_nm=60.0)
SHIFT = 1.5
STEP = sf.CENTERLINE_STEP_PX
MARGIN = 40
SEEDS = (0, 1)
RIBBON_TIP_NM = 10.0
SINES = ((1, 8), (2, 12))
ARC_RADII_W = (3, 5, 10)
CORNER_TURNS = (20, 30, 40, 60, 90, 120)
SPACINGS_W = (1.0, 1.5, 2.0, 3.0)


def walk(start, heading_deg, parts):
    """Dense path from `start`: ('L', length) | ('T', turn_deg) | ('A', radius, turn_deg)."""
    pts = [np.asarray(start, float)]
    h = math.radians(heading_deg)
    corners = []
    for p in parts:
        if p[0] == "L":
            n = max(1, int(round(p[1] / STEP)))
            d = np.array([math.cos(h), math.sin(h)]) * (p[1] / n)
            for _ in range(n):
                pts.append(pts[-1] + d)
        elif p[0] == "T":
            corners.append((len(pts) - 1, abs(p[1])))
            h += math.radians(p[1])
        else:
            radius, t = p[1], math.radians(p[2])
            n = max(1, int(round(radius * abs(t) / STEP)))
            dt = t / n
            ds = radius * abs(t) / n
            for _ in range(n):
                h += dt / 2
                pts.append(pts[-1] + ds * np.array([math.cos(h), math.sin(h)]))
                h += dt / 2
    return np.array(pts), corners


def _place(paths, angle_deg):
    a = math.radians(angle_deg)
    rot_m = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    rot = [p @ rot_m.T for p in paths]
    allp = np.vstack(rot)
    lo, hi = allp.min(0), allp.max(0)
    w = int(math.ceil((hi[0] - lo[0] + 2 * MARGIN) / 8) * 8)
    h = int(math.ceil((hi[1] - lo[1] + 2 * MARGIN) / 8) * 8)
    off = np.array([MARGIN, MARGIN]) - lo
    return [p + off for p in rot], (max(h, 128), max(w, 128))


def _centerline(p, corners):
    return sf.Centerline(p[:, 0].copy(), p[:, 1].copy(),
                         np.array([c[0] for c in corners], np.int64),
                         np.array([180.0 - c[1] for c in corners]), "poly", float("inf"))


def _path_len(p):
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])


def _truth_class(dev, end_dist):
    if dev < 25:
        return "none"
    if dev < 40 or end_dist < 1.5 * W:
        return "ambiguous"
    return "clear"


def _cases():
    cases = []
    for dev in CORNER_TURNS:
        cases.append((f"A_corner{dev}", "A",
                      lambda s, d=dev: ([walk((0, 0), 0, [("L", 60), ("T", d), ("L", 60)])], {})))
    for sp in SPACINGS_W:
        def zig(s, sp=sp):
            parts = [("L", 50)]
            for k, t in enumerate((60, -60, 60, -60, 60)):
                parts += [("T", t), ("L", sp * W if k < 4 else 50)]
            return [walk((0, 0), -30, parts)], {}
        cases.append((f"B_zigzag{sp:g}W", "B", zig))
        cases.append((f"C_pair{sp:g}W", "C", lambda s, sp=sp: (
            [walk((0, 0), 0, [("L", 60), ("T", 60), ("L", sp * W), ("T", 60), ("L", 60)])], {})))
    for e in SPACINGS_W:
        cases.append((f"D_end{e:g}W", "D", lambda s, e=e: (
            [walk((0, 0), 0, [("L", 80), ("T", 60), ("L", e * W)])], {})))
    cases.append(("E_straight", "E", lambda s: ([walk((0, 0), 0, [("L", 150)])], {})))
    for r in ARC_RADII_W:
        cases.append((f"E_arcR{r}W", "E", lambda s, r=r: (
            [walk((0, 0), 0, [("L", 30), ("A", r * W, 120), ("L", 30)])], {})))
    for amp, lam in SINES:
        def sine(s, amp=amp, lam=lam):
            u = np.arange(0, 2.5 * lam * W + 1e-9, 0.05)
            p = np.column_stack([u, amp * W * np.sin(2 * np.pi * u / (lam * W))])
            cum = np.cumsum(np.hypot(*np.diff(p, axis=0).T)) // STEP
            keep = np.concatenate([[True], cum != np.concatenate([[0], cum[:-1]])])
            return [(p[keep], [])], {}
        cases.append((f"E_sineA{amp}L{lam}", "E", sine))
    for phi in (30, 60, 90):
        def cross(s, phi=phi):
            d = np.array([math.cos(math.radians(phi)), math.sin(math.radians(phi))])
            return [walk((-80, 0), 0, [("L", 160)]), walk(-80 * d, phi, [("L", 160)])], \
                {"junctions": [(0.0, 0.0)]}
        cases.append((f"F_X{phi}", "F", cross))
    for phi in (30, 60):
        cases.append((f"F_Y{phi}", "F", lambda s, phi=phi: (
            [walk((-80, 0), 0, [("L", 160)]), walk((0, 0), phi, [("L", 80)])],
            {"junctions": [(0.0, 0.0)]})))

    def merge(s):
        o = 0.6 * W
        a = math.radians(25)
        start = (-10 - 60 * math.cos(a), o + 60 * math.sin(a))
        return [walk((-100, 0), 0, [("L", 200)]), walk(start, -25, [("L", 60), ("T", 25), ("L", 70)])], \
            {"junctions": [(-10.0, o)]}
    cases.append(("F_merge", "F", merge))
    return cases


RIBBONS = [("G_circle_d3", 0, 0, 0), ("G_ribbon4x2_p300", 4, 2, 300), ("G_ribbon6x2_p300", 6, 2, 300),
           ("G_ribbon10x3_p300", 10, 3, 300), ("G_ribbon10x3_p150", 10, 3, 150),
           ("G_ribbon16x3_p300", 16, 3, 300)]


def _ribbon_height(u, phi, a, b):
    c, s = np.cos(phi), np.sin(phi)
    sc = np.where(c >= 0, 1.0, -1.0)
    ss = np.where(s >= 0, 1.0, -1.0)
    zc = 0.5 * a * np.abs(s) + 0.5 * b * np.abs(c)

    def v(p, q):
        return p * c - q * s, p * s + q * c + zc
    u_t, z_t = v(0.5 * a * ss, 0.5 * b * sc)
    u_l, z_l = v(-0.5 * a * sc, 0.5 * b * ss)
    u_r, z_r = v(0.5 * a * sc, -0.5 * b * ss)
    h = np.zeros_like(u)
    m1 = (u >= u_l) & (u <= u_t)
    h[m1] = (z_l + (z_t - z_l) * (u - u_l) / np.maximum(u_t - u_l, 1e-9))[m1]
    m2 = (u > u_t) & (u <= u_r)
    h[m2] = (z_t + (z_r - z_t) * (u - u_t) / np.maximum(u_r - u_t, 1e-9))[m2]
    return h


def _render_ribbon(a, b, period, seed=1, shape=(384, 384), length=600.0, taper=40.0):
    from scipy.ndimage import grey_dilation
    line = sf.straight_centerline(length, angle_deg=20.0, shape=shape, nm_per_px=NMPX)
    x0, y0 = line.x[0], line.y[0]
    th = math.atan2(line.y[-1] - y0, line.x[-1] - x0)
    gy, gx = np.mgrid[0:shape[0], 0:shape[1]].astype(float)
    dx, dy = gx + 0.5 - x0, gy + 0.5 - y0
    s = (dx * math.cos(th) + dy * math.sin(th)) * NMPX
    u = (-dx * math.sin(th) + dy * math.cos(th)) * NMPX
    scale = 0.2 + 0.8 * np.clip(np.minimum(s, length - s) / taper, 0, 1)
    phi = (2 * np.pi * s / period + 0.3) if period else np.zeros_like(s)
    if a == b == 0:
        r = 1.5 * scale
        surf = np.where(np.abs(u) < r, r + np.sqrt(np.maximum(r * r - u * u, 0)), 0.0)
    else:
        surf = _ribbon_height(u, phi, a * scale, b * scale)
    surf[(s < 0) | (s > length)] = 0.0
    img = grey_dilation(surf, structure=sf.spherical_tip_structure(RIBBON_TIP_NM, NMPX, float(surf.max())),
                        mode="nearest")
    rng = np.random.default_rng(seed)
    img = img + 1.0 * (0.66 * gx / (shape[1] - 1) + 0.34 * gy / (shape[0] - 1))
    img = img + 0.40 * sf.self_affine_field(shape, NMPX, 120.0, 0.6, rng)
    img = img + rng.normal(0, 0.03, (shape[0], 1)) + rng.normal(0, 0.05, shape)
    tmpl = sf.render_scan([line], shape=shape, nm_per_px=NMPX, noise_nm=0.0, tilt_nm=0.0)
    return tmpl.__class__(**{**tmpl.__dict__, "image": img}), line


def build(out_dir: Path) -> List[dict]:
    """
    Write every scan and its truth under `out_dir` (cached) and list them.
    すべての走査とその真値を `out_dir` に書き（キャッシュ）、一覧を返す。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, group, builder in _cases():
        for seed in SEEDS:
            tag = f"{name}_s{seed}"
            truth_path = out_dir / f"{tag}_truth.json"
            if not truth_path.is_file():
                paths_c, extra = builder(seed)
                paths = [p for p, _ in paths_c]
                corners = [c for _, c in paths_c]
                placed, shape = _place(paths + [np.array(extra.get("junctions", [(0, 0)]), float)],
                                       23.0 + 31.0 * seed)
                jpts = placed[-1] if "junctions" in extra else np.empty((0, 2))
                placed = placed[:-1]
                lines = [_centerline(p, c) for p, c in zip(placed, corners)]
                scan = sf.render_scan(lines, shape=shape, nm_per_px=NMPX, seed=seed, **REND)
                kinks = []
                for p, c in zip(placed, corners):
                    s_along = _path_len(p)
                    for idx, dev in c:
                        cls = _truth_class(dev, min(s_along[idx], s_along[-1] - s_along[idx]))
                        if name == "F_merge":
                            cls = "ambiguous"
                        kinks.append([float(p[idx, 0] - SHIFT), float(p[idx, 1] - SHIFT), float(dev), cls])
                sf.write_afm_text(scan, str(out_dir / f"{tag}.txt"))
                truth = dict(case=name, group=group, seed=seed, scan_size_um=list(scan.scan_size_um),
                             centerlines=[dict(x=(p[::2, 0] - SHIFT).round(3).tolist(),
                                               y=(p[::2, 1] - SHIFT).round(3).tolist()) for p in placed],
                             kinks=kinks, junctions=(jpts - SHIFT).round(3).tolist())
                truth_path.write_text(json.dumps(truth), encoding="utf-8")
            entries.append(dict(tag=tag, **json.loads(truth_path.read_text(encoding="utf-8"))))
    for name, a, b, period in RIBBONS:
        truth_path = out_dir / f"{name}_truth.json"
        if not truth_path.is_file():
            scan, line = _render_ribbon(a, b, period)
            sf.write_afm_text(scan, str(out_dir / f"{name}.txt"))
            truth = dict(case=name, group="G", seed=1, scan_size_um=list(scan.scan_size_um),
                         centerlines=[dict(x=(line.x[::2] - SHIFT).round(3).tolist(),
                                           y=(line.y[::2] - SHIFT).round(3).tolist())],
                         kinks=[], junctions=[], ribbon=[a, b, period])
            truth_path.write_text(json.dumps(truth), encoding="utf-8")
        entries.append(dict(tag=name, **json.loads(truth_path.read_text(encoding="utf-8"))))
    return entries


def analyze(entry: dict, out_dir: Path, params=None) -> str:
    """The bundle of one scan, processed with `params` (default ProcParams), cached."""
    from lib.pipeline import ProcParams, process_file
    bundle = out_dir / f"{entry['tag']}.b2z"
    if not bundle.is_file():
        process_file(str(out_dir / f"{entry['tag']}.txt"), params or ProcParams(),
                     scan_size_um=tuple(entry["scan_size_um"]), scan_size_source="manual",
                     output_dir=str(out_dir))
    return str(bundle)


def fibers_of(bundle: str, centerline: Optional[str] = None):
    """
    The traced fibers of a bundle, built on `centerline` (the bundle's own line if None).
    バンドルの追跡済み繊維。`centerline` の線の上に組み立てる（None ならバンドル自身の線）。
    """
    from lib import measure
    image = measure.load_tracking_image(bundle, NMPX, NMPX)   # nm per pixel
    if centerline is not None:
        image.centerline = centerline
    return image, image.fibers_in_image_parallel()


def track(f, line: bool = True) -> Tuple[np.ndarray, np.ndarray]:
    """A fiber's line (or skeleton track) in bundle coordinates."""
    xs = f.xtrack if line else f.skeleton_xtrack
    ys = f.ytrack if line else f.skeleton_ytrack
    return np.asarray(xs, float) + float(f.data[0]), np.asarray(ys, float) + float(f.data[1])


def densify(x, y, step=0.1):
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    if s[-1] == 0:
        return np.column_stack([x[:1], y[:1]])
    su = np.arange(0, s[-1] + 1e-9, step)
    return np.column_stack([np.interp(su, s, x), np.interp(su, s, y)])


def truth_trees(entry):
    from scipy.spatial import cKDTree
    return [cKDTree(densify(np.asarray(c["x"]), np.asarray(c["y"]))) for c in entry["centerlines"]]


def nearest_truth(trees, x, y, limit=3.0):
    """Index of the truth centerline a traced fragment follows, or None."""
    if len(x) < 5:
        return None
    med = [float(np.median(t.query(np.column_stack([x, y]))[0])) for t in trees]
    i = int(np.argmin(med))
    return i if med[i] < limit else None


KEYS = ("clear", "found", "merged", "displaced", "missed", "false", "exempt")


def match(refs: Sequence[tuple], dets: Sequence[tuple], tol: float) -> dict:
    """
    One-to-one matching of detections to the truth kinks of one fiber (Hungarian).
    1 本の繊維の真値キンクと検出を 1 対 1 で対応付ける（ハンガリー法）。
    """
    from scipy.optimize import linear_sum_assignment
    clear = [r for r in refs if r[2] == "clear"]
    other = [r for r in refs if r[2] in ("ambiguous", "junction")]
    res = dict.fromkeys(KEYS, 0)
    res["clear"] = len(clear)
    used = [False] * len(dets)
    matched = set()
    cost = (np.array([[math.hypot(r[0] - d[0], r[1] - d[1]) for d in dets] for r in clear])
            if (clear and dets) else None)
    if cost is not None:
        rows, cols = linear_sum_assignment(np.where(cost <= tol, cost, 1e6))
        for a, b in zip(rows, cols):
            if cost[a, b] <= tol:
                res["found"] += 1
                used[b] = True
                matched.add(a)
    for a in range(len(clear)):
        if a in matched:
            continue
        if cost is not None:
            if any(cost[a, b] <= tol and used[b] for b in range(len(dets))):
                res["merged"] += 1
                continue
            cand = [b for b in range(len(dets)) if cost[a, b] <= 2 * tol and not used[b]]
            if cand:
                used[min(cand, key=lambda b: cost[a, b])] = True
                res["displaced"] += 1
                continue
        res["missed"] += 1
    for b, d in enumerate(dets):
        if used[b]:
            continue
        if any(math.hypot(o[0] - d[0], o[1] - d[1]) <= tol for o in other):
            res["exempt"] += 1
        else:
            res["false"] += 1
    return res


def truth_refs(entry, tracks) -> Dict[int, List[tuple]]:
    """Truth kinks and junctions assigned to the traced fragment passing nearest."""
    from scipy.spatial import cKDTree
    out: Dict[int, List[tuple]] = {}
    trees = [cKDTree(np.column_stack([x, y])) for x, y in tracks]
    for x, y, _dev, cls in entry["kinks"]:
        if cls == "none" or not trees:
            continue
        d = [t.query([x, y])[0] for t in trees]
        if min(d) <= 1.5 * W:
            out.setdefault(int(np.argmin(d)), []).append((x, y, cls))
    for x, y in entry["junctions"]:
        for i, t in enumerate(trees):
            if t.query([x, y])[0] <= 2.0 * W:
                out.setdefault(i, []).append((x, y, "junction"))
    return out
