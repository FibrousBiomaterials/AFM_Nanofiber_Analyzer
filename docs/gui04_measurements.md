# GUI04 fiber measurements

This page explains what GUI04 (`guis/GUI04_Tracking_fiber.py`) computes after
it opens a `.b2z` bundle: the centerline each fiber is drawn and measured along, and
every number in the fiber table, the fiber detail window, and the
fiber-connection dialog. It quotes the code that does each step, so a reader can
check a value in a figure caption against the computation that produced it.

The four preprocessing stages that write the bundle — background calibration,
binarization, skeletonization, and kink detection — are explained in
[Analysis algorithms](algorithms.md). This page starts where that one ends. The
kink rule itself is explained there (§4.3–§4.6) and only its use is covered here.

## How to read the code excerpts

Every code block starts with a header naming where it comes from:

```text
# source: lib/measure.py::compute_fiber_stats
```

That is the file and the function, method (`Class.method`), or module constant
the code belongs to. A header may list several constants of one file, separated
by commas. A line holding only `...` marks omitted code. Comments and blank rows
are left out of the excerpts, and method bodies are shown without their
indentation. To read the code with its comments, open the named symbol.

These excerpts cannot silently go out of date. `scripts/check_gui04_docs.py`
checks every excerpt, line for line, against the symbol it names. It also
fingerprints each quoted symbol with comments and docstrings removed. A change
to what one of them computes fails the check until this page has been reread and
the fingerprints refreshed (see §6).

## Conventions

| Quantity | Unit | Notes |
|---|---|---|
| Centerline coordinates `Fiber.xtrack`, `Fiber.ytrack` | px, relative to the fiber's bounding box | The box origin is `Fiber.data[0]`, `Fiber.data[1]` in the analysis array. The coordinates are fractional. |
| Skeleton-track coordinates `Fiber.skeleton_xtrack`, `Fiber.skeleton_ytrack` | px, relative to the fiber's bounding box | Integer pixel coordinates. |
| Distance along the centerline `Fiber.horizon` | nm | Cumulative, starting at 0. |
| Height `Fiber.height` | nm | Background-corrected height, with the substrate at 0 nm. |
| Apparent width W | px internally, nm in the table | See §2.1. |
| Curvature | rad/µm | See §3.6. |
| Kink density | 1/µm | See §3.9. |
| Connection distance | px | Measured between skeleton pixels, see §5.1. |

**Centerline and skeleton track.** This page distinguishes two coordinate
sequences along a fiber by these names, and always names the one it means.

- **Skeleton track**: the pixels of the skeletonized image (the bundle's
  `skeletonized`) that form one fiber, as integer coordinates ordered from one
  end to the other. They are held in `Fiber.skeleton_xtrack` /
  `Fiber.skeleton_ytrack` and returned by `fiber.skeleton_track`. They identify
  the fiber and are never drawn or measured (§1.3).
- **Centerline**: each skeleton-track point moved to the half-maximum midpoint
  of the height cross-section, as fractional coordinates (§2). It is held in
  `Fiber.xtrack` / `Fiber.ytrack`, and the fiber is drawn and every value is
  measured along it.

A bundle of format 1.0 has no centerline: `Fiber.xtrack` / `Fiber.ytrack` hold
the skeleton track itself (§1.2). For such a bundle, read "centerline" on this
page as "the skeleton track held in `Fiber.xtrack` / `Fiber.ytrack`". Where the
computation differs, the difference is stated (§2.7, §3.5).

**Pixel size.** Every physical length on this page uses the pixel size that
`measure.measure_bundle` works out from the scan size. By default the scan
size is the one recorded in the bundle (`spatial_calibration`). GUI04 passes the
X and Y scan sizes from its scale fields instead, and a blank Y reuses X. The
analysis arrays are one pixel smaller than the raw scan on each axis (see
[Analysis algorithms](algorithms.md), *Conventions*), so the divisor is the
array size plus one:

```python
# source: lib/measure.py::measure_bundle
data, meta = _load_validated_arrays(
    bundle_path, TRACKING_BUNDLE_KEYS, optional=_TRACKING_OPTIONAL_KEYS,
)
height_px, width_px = data["calibrated"].shape
x_size_per_pixel = scale_um * 1000.0 / (width_px + 1)
y_size_per_pixel = scale_y_um * 1000.0 / (height_px + 1)
...
fragments = image.fibers_in_image_parallel(
    max_workers=max_workers,
    progress_cb=progress_cb,
)
...
return curate_fibers(
    image,
    fragments,
    exclude_anchors=exclude_anchors,
    plan=plan,
)
```

`curate_fibers` applies the user's saved exclusions to the traced fragments.
It then applies the saved connection plan to the fragments that remain (§5).
The fibers it returns are the rows of the fiber table.

## 1. From a bundle to fibers

### 1.1 One traced component per fiber

`FiberTrackingImage` never re-runs a preprocessing stage. It reads the
`calibrated`, `skeletonized`, `bp`, `ep`, `kp` and `ka` arrays of the bundle, plus
`up` and `ke` when the bundle has them. It cuts the skeleton at every branch
point and keeps each remaining connected component as one fiber. This is the
same cleanup kink detection used ([Analysis algorithms](algorithms.md) §4.1).
Each component is then passed to `_build_fiber`.

### 1.2 Whether a fiber is built on the centerline or the skeleton track

A bundle of format 1.1 had its kinks judged on the half-maximum centerline, so
GUI04 builds its fibers on the centerline. An older bundle had its kinks judged on
the skeleton pixels, so GUI04 keeps the skeleton track for it until the image is
re-analyzed. `bundle_schema.centerline_from_meta` makes this choice from the
bundle's format version, so the kinks and the coordinates they are drawn on
(centerline or skeleton track) always come from one definition.

```python
# source: lib/fiber_tracking_image.py::_build_fiber
xtrack_prcimg, ytrack_prcimg = imp_tools.tracking(target_image)
fiber_image = cal[y: y + h, x: x + w].copy()
if centerline == HALF_MAX_CENTERLINE:
    placed = place_centerline(
        cal, xtrack_prcimg, ytrack_prcimg, branch_points,
    )
    xtrack = placed.x - x
    ytrack = placed.y - y
    horizon = polyline_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = placed.crest
    skeleton_xtrack = xtrack_prcimg - x
    skeleton_ytrack = ytrack_prcimg - y
    width_px = placed.width_px
    width_measured = placed.width_measured
    line_reliable = placed.reliable
else:
    xtrack = xtrack_prcimg - x
    ytrack = ytrack_prcimg - y
    horizon = imp_tools.convert_track_to_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
    height = cal[ytrack_prcimg, xtrack_prcimg]
...
for i, (px, py) in enumerate(zip(xtrack_prcimg.tolist(), ytrack_prcimg.tolist())):
    if (px, py) in kink_set:
        kink_indices.append(i)
    if (px, py) in dp_set:
        decomposed_point_indices.append(i)
    if (px, py) in ep_set:
        ep_indices.append(i)
    if (px, py) in unjudged:
        unjudged_indices.append(i)
```

`imp_tools.tracking` walks the component from one end to the other and returns
its pixels in order. The centerline has exactly one point per skeleton pixel,
so index `i` refers to the same place on the centerline and on the skeleton
track. That is why the kinks, endpoints, and unjudged bends stored at skeleton
pixels in the bundle can be looked up by skeleton coordinate and then drawn at
the same index on the centerline.

### 1.3 Identity and geometry are kept apart

A fiber carries both an index-aligned centerline and skeleton track.
`Fiber.xtrack` / `Fiber.ytrack` is the centerline that is drawn and measured.
`Fiber.skeleton_xtrack` / `Fiber.skeleton_ytrack` holds the skeleton track the
centerline was placed from, and `fiber.skeleton_track`
returns them. Everything that **identifies** a fiber reads the skeleton pixels:
exclusion and connection anchors, the connection search (§5.1), and the
branch-point and frame tests. The skeleton changes only when the image is
re-analyzed. The centerline moves whenever the way it is estimated changes, and
keying identity on it would detach the saved sidecars.

## 2. The centerline

A skeleton is the medial axis of the binarized mask. The mask boundary is a
threshold contour, so it shifts with the background residual and with nearby
objects, and the 8-connected pixel chain adds a staircase on top of that. The
half-maximum centerline instead places each skeleton point on the fiber's own
height cross-section. The reasoning behind this definition, and its accuracy on
synthetic scans, is in [Analysis algorithms](algorithms.md) §4.2. This section
follows the code.

`centerline.place_centerline` measures the width, then places the centerline:

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

Every length used to place the centerline is a multiple of the apparent width W, so
the procedure means the same thing at any pixel size:

```python
# source: lib/centerline.py::_WIDTH_SEARCH_PX, _WIDTH_STEP_PX, _WIDTH_TANGENT_HALF, FALLBACK_WIDTH_PX, _CREST_WINDOW_WIDTHS, _FRAME_SIGMA_WIDTHS, _CREST_REACH_WIDTHS, _HALF_MAX_REACH_WIDTHS, _MAX_SECTION_WIDTHS, _OFFSET_SMOOTH_WIDTHS, _JUNCTION_WIDTHS, _MIN_CREST_AMPLITUDE_FRAC
_WIDTH_SEARCH_PX = 12.0
_WIDTH_STEP_PX = 0.25
_WIDTH_TANGENT_HALF = 3
FALLBACK_WIDTH_PX = 8.0
_CREST_WINDOW_WIDTHS = 0.25
_FRAME_SIGMA_WIDTHS = 0.25
_CREST_REACH_WIDTHS = 0.75
_HALF_MAX_REACH_WIDTHS = 1.5
_MAX_SECTION_WIDTHS = 1.5
_OFFSET_SMOOTH_WIDTHS = 0.25
_JUNCTION_WIDTHS = 1.0
_MIN_CREST_AMPLITUDE_FRAC = 0.25
```

Only the first three are in pixels: they set how finely the width profile is
sampled, not a property of the fiber.

### 2.1 Apparent width W

`centerline.measure_apparent_width` reads the fiber's full width at half maximum
from the **height** image. It does not use the binarized mask.

```python
# source: lib/centerline.py::measure_apparent_width
tx, ty = _unit_tangents(x, y, _WIDTH_TANGENT_HALF)
nx, ny = -ty, tx
offsets = np.arange(-_WIDTH_SEARCH_PX, _WIDTH_SEARCH_PX + 1e-9, _WIDTH_STEP_PX)
profiles = _bilinear(
    np.asarray(height, dtype=np.float64),
    y[:, None] + ny[:, None] * offsets[None, :],
    x[:, None] + nx[:, None] * offsets[None, :],
)
peak = profiles.max(axis=1)
base = np.percentile(profiles, 10.0, axis=1)
level = base + 0.5 * (peak - base)
above = profiles >= level[:, None]
centre = offsets.size // 2
widths = np.empty(x.size, dtype=np.float64)
usable = np.zeros(x.size, dtype=bool)
for i in range(x.size):
    lo = centre
    while lo > 0 and above[i, lo - 1]:
        lo -= 1
    hi = centre
    while hi < offsets.size - 1 and above[i, hi + 1]:
        hi += 1
    widths[i] = offsets[hi] - offsets[lo]
    usable[i] = lo > 0 and hi < offsets.size - 1
if usable.sum() < max(1, x.size // 2):
    return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
width = float(np.median(widths[usable]))
if not np.isfinite(width) or width < 2.0:
    return (FALLBACK_WIDTH_PX, False) if return_measured else FALLBACK_WIDTH_PX
return (width, True) if return_measured else width
```

Step by step:

1. At each skeleton point the normal comes from a centered difference over ±3
   points of the skeleton track. A height profile is sampled along it every 0.25 px, out to
   ±12 px, by bilinear interpolation.
2. Each profile has its own base, the 10th percentile of its samples, so a fiber
   on a residual background slope is measured against its local base. The level
   is halfway between that base and the profile's maximum.
3. The run above that level is grown outward from the skeleton point. It stops
   where the profile first drops below the level, so a second fiber further
   along the normal cannot widen it. A run that reaches the end of the search
   range never came back down and is not used.
4. W is the **median** over the usable points. A width is a property of the
   fiber, so one value is used along the whole fiber.

If fewer than half the points are usable, or the median is below 2 px,
`FALLBACK_WIDTH_PX` (8 px) is used instead. The substitution is reported:
`CenterlineResult.width_measured` is `False`, and GUI04 leaves the fiber's
`W (nm)` cell blank (§3.10).

### 2.2 The frame: a smoothed copy that only supplies directions

`centerline._refine` first smooths a copy of the skeleton track with a Gaussian
of $\sigma = W/4$, measured in skeleton-track points. Padding each end by linear
extrapolation keeps a straight end from being pulled inward. This smoothed copy,
the *frame*, supplies only the normal each point may move along and the base
its sideways offset is measured from. No point is ever moved to the smoothed
position, which would round off real corners.

```python
# source: lib/centerline.py::_refine
width = float(width_px)
mean_step = max(float(np.hypot(np.diff(x), np.diff(y)).mean()), 1e-9)
sigma = _FRAME_SIGMA_WIDTHS * width / mean_step
fx = _smooth_extrapolated(x, sigma)
fy = _smooth_extrapolated(y, sigma)
tx = np.gradient(fx)
ty = np.gradient(fy)
norm = np.hypot(tx, ty)
norm[norm == 0.0] = 1.0
nx, ny = -ty / norm, tx / norm
reach = _CREST_REACH_WIDTHS * width
half_reach = _HALF_MAX_REACH_WIDTHS * width
s = np.arange(-(reach + half_reach), reach + half_reach + 1e-9, _WIDTH_STEP_PX)
ns = s.size
prof = _bilinear(img, fy[:, None] + ny[:, None] * s[None, :],
                 fx[:, None] + nx[:, None] * s[None, :])
```

`prof[i, :]` is the cross-section at point $i$, sampled every 0.25 px along the
normal. It extends $\pm(0.75 + 1.5)\,W$ from the frame: 0.75 W in which to find
the section's maximum, plus 1.5 W beyond it in which to find the half-maximum
crossings.

### 2.3 Climbing to the nearest maximum

From the frame point each section is climbed uphill to the **nearest** local
maximum, not to the highest point in reach. This keeps a brighter neighbouring
fiber from capturing the centerline.

```python
# source: lib/centerline.py::_refine
c = int(np.argmin(np.abs(s)))
dif = np.diff(prof, axis=1)
k = np.full(n, c)
go_right = dif[:, c] > 0
go_left = ~go_right & (dif[:, c - 1] < 0)
stop_right = dif[:, c:] <= 0
right_end = np.where(stop_right.any(1), stop_right.argmax(1), stop_right.shape[1]) + c
k = np.where(go_right, np.minimum(right_end, ns - 1), k)
stop_left = dif[:, :c][:, ::-1] >= 0
left_steps = np.where(stop_left.any(1), stop_left.argmax(1), c)
k = np.where(go_left, c - left_steps, k)
peak = prof[rows, k]
within_reach = np.abs(s[k]) < reach - 0.5 * _WIDTH_STEP_PX
```

`k[i]` is the sample index of that maximum and `peak[i]` its height. A maximum
at or beyond 0.75 W from the frame belongs to something else. Such a section is
not `within_reach` and is not used to place the centerline.

### 2.4 The half-maximum midpoint

On each side of the maximum, the lowest sample within 1.5 W is taken. The base
is the lower of these two minima, and the level is halfway between the base and
the peak. The crossing on each side is
the sample nearest the maximum that lies below that level, refined to a
sub-sample position by linear interpolation. The centerline point is placed at
the midpoint of the two crossings.

```python
# source: lib/centerline.py::_refine
window = np.abs(s[None, :] - s[k][:, None]) <= half_reach
left = window & (col < k[:, None])
right = window & (col > k[:, None])
left_min = np.where(left, prof, np.inf).min(1)
right_min = np.where(right, prof, np.inf).min(1)
left_min = np.where(np.isfinite(left_min), left_min, peak)
right_min = np.where(np.isfinite(right_min), right_min, peak)
base = np.minimum(left_min, right_min)
amplitude = peak - base
level = base + 0.5 * amplitude
below = prof < level[:, None]
li = np.where(left & below, col, -1).max(1)
ri = np.where(right & below, col, ns).min(1)
resolved = within_reach & (li >= 0) & (ri < ns) & (amplitude > 0)
offset = s[k].astype(np.float64)
r = np.nonzero(resolved)[0]
if r.size:
    jl = li[r]
    pl0 = prof[r, jl]
    pl1 = prof[r, jl + 1]
    xl = s[jl] + (level[r] - pl0) / np.where(pl1 != pl0, pl1 - pl0, 1.0) * _WIDTH_STEP_PX
    jr = ri[r]
    pr0 = prof[r, jr - 1]
    pr1 = prof[r, jr]
    xr = s[jr - 1] + (pr0 - level[r]) / np.where(pr0 != pr1, pr0 - pr1, 1.0) * _WIDTH_STEP_PX
    offset[r] = 0.5 * (xl + xr)
    owns = (xl <= 0.0) & (xr >= 0.0)
    narrow = (xr - xl) <= _MAX_SECTION_WIDTHS * width
    resolved[r[~(owns & narrow)]] = False
```

So the offset of a resolved point is

$$
\text{offset}_i = \tfrac{1}{2}\,(x_{\text{L},i} + x_{\text{R},i}),
$$

measured along the normal from the frame. It is read on the steep flanks, where
noise moves a crossing least, not on the flat top.

After placement, a section is still rejected in two cases. If the frame point
lies outside its half-maximum run (`owns`), the section is not the one the
skeleton track lies on. If the run is wider than 1.5 W (`narrow`), two fibers are lying
side by side.

### 2.5 Reliable points and interpolated offsets

A point counts as **reliable** only if its section located this one fiber. A
resolved section must also have an amplitude of at least a quarter of the
skeleton track's median resolved amplitude, and must lie more than 1 W from every branch
point:

```python
# source: lib/centerline.py::_refine
typical = float(np.median(amplitude[resolved])) if resolved.any() else float(np.median(amplitude))
weight = (resolved & (amplitude >= _MIN_CREST_AMPLITUDE_FRAC * typical)).astype(np.float64)
if branch_points is not None:
    mask = np.asarray(branch_points)
    radius = _JUNCTION_WIDTHS * width
...
    weight[d2 < radius * radius] = 0.0
lam = (_OFFSET_SMOOTH_WIDTHS * width / mean_step) ** 2
lateral = np.clip(_whittaker_first_order(offset, weight, lam), -reach, reach)
reliable = weight > 0.0
```

The offsets are then joined along the skeleton track by a weighted first-order
Whittaker smoother, in which unreliable points have zero weight:

$$
\min_z \; \sum_i w_i\,(z_i - \text{offset}_i)^2 \;+\; \lambda \sum_i (z_{i+1} - z_i)^2,
\qquad \lambda = \left(\frac{W/4}{\overline{\Delta s}}\right)^2
$$

```python
# source: lib/centerline.py::_whittaker_first_order
n = target.size
if n == 1:
    return target.astype(np.float64).copy()
main = weight + 1e-6 + lam * np.concatenate([[1.0], np.full(n - 2, 2.0), [1.0]])
off = np.full(n - 1, -lam)
return _solve_tridiagonal(off, main, off, weight * target)
```

A first-order penalty interpolates linearly across a run of unreliable points.
Past the last reliable point it holds the offset constant, so an unreliable end
keeps the offset of the reliable part next to it instead of drifting. The result
is clipped to ±0.75 W. An interpolated run is straight, so no kink or curvature
can be found on it. That is what the `reliable` column reports (§3.11).

### 2.6 Crest height

The centerline sits at the half-maximum midpoint, which on an asymmetric
section lies beside the top rather than on it. A height interpolated at the
centerline would read
low. A fiber's height is therefore the **crest** of its section:

```python
# source: lib/centerline.py::_refine
near = np.abs(s[None, :] - lateral[:, None]) <= _CREST_WINDOW_WIDTHS * width
crest_near = np.where(near, prof, -np.inf).max(1)
line_x = fx + nx * lateral
line_y = fy + ny * lateral
at_line = _bilinear(img, line_y, line_x)
crest_near = np.where(np.isfinite(crest_near), crest_near, at_line)
crest = np.maximum(np.where(reliable, peak, crest_near), at_line)
return line_x, line_y, reliable, crest.astype(np.float64)
```

- A reliable point takes the maximum its section was climbed to, `peak`.
- An interpolated point has no section of its own. It takes the maximum within
  W/4 of the centerline along the normal.
- Either value is raised, if necessary, to the height interpolated at the
  centerline itself. The profile is sampled only every 0.25 px, so this keeps the crest
  from ever reading below the centerline.

`_build_fiber` stores this as `Fiber.height` (§1.2). Every height number on this
page reads it.

### 2.7 Contour length

On the centerline, distance along the fiber is the plain Euclidean length of
the polyline. Each axis is scaled by its own pixel size:

```python
# source: lib/centerline.py::polyline_distance
x = np.asarray(xtrack, dtype=np.float64)
y = np.asarray(ytrack, dtype=np.float64)
x_step = float(pixel_step_size)
y_step = x_step if y_pixel_step_size is None else float(y_pixel_step_size)
out = np.zeros(x.size, dtype=np.float64)
if x.size > 1:
    steps = np.hypot(np.diff(x) * x_step, np.diff(y) * y_step)
    out[1:] = np.cumsum(steps)
return out
```

$$
s_j = \sum_{i=1}^{j} \sqrt{\bigl((x_i - x_{i-1})\,p_x\bigr)^2 + \bigl((y_i - y_{i-1})\,p_y\bigr)^2}
$$

This array is `Fiber.horizon`, and the fiber's length is its last element:

```python
# source: lib/fiber.py::Fiber.length
@property
def length(self) -> float:
...
    return self.horizon[-1]
```

On the skeleton track of an older bundle, `imp_tools.convert_track_to_distance`
is used instead. Its corrected chain-code weights remove the length overestimate
of an 8-connected pixel chain, which the sub-pixel centerline does not have.

## 3. The fiber table

GUI04's fiber table has these columns:

```python
# source: guis/GUI04_Tracking_fiber.py::App._build_fiber_table
cols = ("#", "length (nm)", "median (nm)", "max (nm)", "p90 (nm)",
        "straightness", "curvature (rad/" + UNIT_MICROMETER + ")",
        "EP count", "Kink count",
        "kink density (1/" + UNIT_MICROMETER + ")",
        "unjudged", "W (nm)", "reliable")
```

All of them except `#`, `EP count`, and `Kink count` are computed by
`lib/measure.py`. The same functions are called by the CSV export, by GUI03, and
by `cli.py measure`, so a value checked here is the value those report.

| Column | Source | Blank when |
|---|---|---|
| `#` | Row position in the displayed list | — |
| `length (nm)` | `Fiber.length` | — |
| `median (nm)` | `FiberStats.height_median_nm` | — |
| `max (nm)` | `FiberStats.height_max_nm` | — |
| `p90 (nm)` | `FiberStats.height_p90_nm` | no height samples |
| `straightness` | `measure.fiber_straightness` | contour length is 0 |
| `curvature (rad/µm)` | `measure.fiber_mean_curvature` | fiber shorter than the 100 nm window |
| `EP count` | `len(Fiber.ep_indices)` | — |
| `Kink count` | `len(Fiber.kink_indices)` | — |
| `kink density (1/µm)` | `measure.fiber_kink_density` | nothing judged |
| `unjudged` | `len(Fiber.unjudged_indices)` | — |
| `W (nm)` | `FiberStats.width_nm` | width not measured, or a format 1.0 bundle (skeleton track) |
| `reliable` | `FiberStats.line_reliable_fraction` | a format 1.0 bundle (skeleton track) |

The table is filled like this:

```python
# source: guis/GUI04_Tracking_fiber.py::App._populate_fiber_table
x_spp = self.current_image.size_per_pixel
y_spp = self.current_image.y_size_per_pixel
fresh = _table_values(
    compute_fiber_stats(fibers, x_spp, y_spp), fibers, x_spp, y_spp,
)
...
self.fiber_tree.insert("", "end", iid=str(i), values=(
    i,
    f"{f.length:.0f}",
    f"{med:.2f}",
    f"{mx:.2f}",
    blank_if_nan(p90, "{0:.2f}"),
    blank_if_nan(straight, "{0:.3f}"),
    blank_if_nan(curv, "{0:.2f}"),
    len(f.ep_indices),
    len(f.kink_indices),
    blank_if_nan(kink_dens, "{0:.2f}"),
    int(unjudged),
    blank_if_nan(width_nm if width_measured else float("nan"),
                 "{0:.1f}"),
    blank_if_nan(reliable, "{0:.2f}"),
))
```

```python
# source: guis/GUI04_Tracking_fiber.py::_table_values
return [
    (s.height_median_nm, s.height_max_nm, s.straightness,
     fiber_mean_curvature(
         f, x_spp, y_spp, window_nm=DEFAULT_CURVATURE_WINDOW_NM,
     ),
     fiber_kink_density(s),
     s.height_p90_nm, s.width_nm, s.width_measured,
     s.line_reliable_fraction, s.unjudged_count)
    for s, f in zip(stats, fibers)
]
```

When no filter is active, the values the analysis worker computed are reused.
Otherwise they are recomputed through the same two functions. Either way, the
cells come from `compute_fiber_stats` and `_table_values`.

### 3.1 `#`

The row's position in the list currently shown. Turning connection on or off,
or applying a height filter, renumbers the list. The number is therefore not a
stable identity: exclusions and connections are stored as skeleton pixels
(§1.3), never as this index.

### 3.2 `length (nm)`

`Fiber.length`, the contour length along the fiber's centerline (§2.7), rounded to
the nanometer. For a connected fibril it includes the straight bridges across
each gap (§5.2).

### 3.3 Which height samples count

Not every point of `Fiber.height` enters the height statistics.
`measure.height_sample_mask` leaves out two kinds of sample:

```python
# source: lib/measure.py::CUT_END_EXCLUSION_WIDTHS, MIN_HEIGHT_SAMPLES, HEIGHT_UPPER_PERCENTILE
CUT_END_EXCLUSION_WIDTHS = 1.0
MIN_HEIGHT_SAMPLES = 3
HEIGHT_UPPER_PERCENTILE = 90.0
```

```python
# source: lib/measure.py::height_sample_mask
n = len(fiber.height)
if n == 0:
    return np.zeros(0, dtype=bool)
measured = getattr(fiber, "height_measured", None)
measured = (np.ones(n, dtype=bool) if measured is None
            else np.asarray(measured, dtype=bool))
mask = measured.copy()
width = float(getattr(fiber, "width_px", float("nan")))
if np.isfinite(width) and width > 0.0 and n > 1:
    ends = set(int(i) for i in np.asarray(fiber.ep_indices).tolist())
    arc = polyline_distance(fiber.xtrack, fiber.ytrack, 1.0)
    zone = CUT_END_EXCLUSION_WIDTHS * width
    if 0 not in ends:
        mask &= ~(arc < zone)
    if n - 1 not in ends:
        mask &= ~(arc > arc[-1] - zone)
if mask.sum() < MIN_HEIGHT_SAMPLES:
    mask = measured
    if not mask.any():
        mask = np.ones(n, dtype=bool)
return mask
```

1. **Bridge samples.** A connected fibril's bridge heights were interpolated by
   the connector (§5.2) and are not measurements of the image. They are marked
   with `Fiber.height_measured` = `False`.
2. **The last width at a cut end.** An end whose point is not in `ep_indices` is
   a cut: the skeleton continued into a crossing there. `imp_tools.remove_bp`
   clears only a 3×3 neighbourhood around the branch point, while the other
   fiber's skirt reaches about one width further. The samples within 1 W of such
   an end, measured in pixel arc length along the centerline, therefore partly belong
   to the other fiber. A real fiber end keeps its samples.

If fewer than 3 samples would remain, the cut-end exclusion is dropped so that a
short fragment still reports a height. If nothing measured remains at all, every
sample is used. A fiber without a width (format 1.0, on the skeleton track) has no cut-end
exclusion.

### 3.4 `median (nm)`, `max (nm)`, `p90 (nm)`

```python
# source: lib/measure.py::compute_fiber_stats
for i, f in enumerate(fibers):
    samples = np.asarray(f.height, dtype=float)
    if samples.size:
        samples = samples[height_sample_mask(f)]
    med = float(np.median(samples)) if samples.size else 0.0
    mx = float(np.max(samples)) if samples.size else 0.0
    p90 = (float(np.percentile(samples, HEIGHT_UPPER_PERCENTILE))
           if samples.size else float("nan"))
```

These are the median, the maximum, and the 90th percentile of the crest heights
(§2.6) that the mask keeps. NumPy's default linear interpolation between order
statistics is used. The maximum is an extreme value and moves with a single
noise spike or contamination particle. `p90` summarizes the tall end of the
fiber without depending on one sample.

### 3.5 `straightness`

```python
# source: lib/measure.py::fiber_straightness
length = float(fiber.length)
if not (length > 0.0):
    return float("nan")
if y_size_per_pixel is None:
    y_size_per_pixel = x_size_per_pixel
if getattr(fiber, "centerline", SKELETON_TRACK) == HALF_MAX_CENTERLINE:
    dx = (float(fiber.xtrack[-1]) - float(fiber.xtrack[0])) * x_size_per_pixel
    dy = (float(fiber.ytrack[-1]) - float(fiber.ytrack[0])) * y_size_per_pixel
    return float(np.hypot(dx, dy) / length)
x0, x1 = int(fiber.xtrack[0]), int(fiber.xtrack[-1])
y0, y1 = int(fiber.ytrack[0]), int(fiber.ytrack[-1])
steps = max(abs(x1 - x0), abs(y1 - y0))
if steps == 0:
    return 0.0
t = np.linspace(0.0, 1.0, steps + 1)
line_x = np.rint(x0 + t * (x1 - x0)).astype(int)
line_y = np.rint(y0 + t * (y1 - y0)).astype(int)
straight = float(imp_tools.convert_track_to_distance(
    line_x, line_y, x_size_per_pixel, y_size_per_pixel,
)[-1])
return float(straight / length)
```

On the centerline, straightness is the Euclidean distance between the first and
last centerline points divided by the contour length:

$$
\text{straightness} = \frac{\sqrt{(\Delta x\,p_x)^2 + (\Delta y\,p_y)^2}}{L}
$$

1.0 is straight and a coiled fiber approaches 0. A straight synthetic fiber
reads 0.9994: only the centerline's own small sideways noise keeps it below 1. The
endpoints are the ends of the traced part, so a fiber cut at a crossing is
described over the part that was traced.

For the skeleton track of an older bundle, the numerator is not the Euclidean
chord. It is a digitised straight line between the same two pixels, measured
with the same chain-code metric as the contour. That metric reports a straight
pixel chain about 5 % shorter than its Euclidean chord, and measuring both
lengths the same way cancels that bias for a straight fiber.

### 3.6 `curvature (rad/µm)`

```python
# source: lib/measure.py::DEFAULT_CURVATURE_WINDOW_NM
DEFAULT_CURVATURE_WINDOW_NM = 100.0
```

```python
# source: lib/measure.py::fiber_curvature_profile
if y_size_per_pixel is None:
    y_size_per_pixel = x_size_per_pixel
horizon = np.asarray(fiber.horizon, dtype=float)
if horizon.size < 3 or float(horizon[-1]) < window_nm:
    return np.empty(0, dtype=float)
xs = np.asarray(fiber.xtrack, dtype=float) * x_size_per_pixel
ys = np.asarray(fiber.ytrack, dtype=float) * y_size_per_pixel
half = window_nm / 2.0
before = np.searchsorted(horizon, horizon - half, side="left")
after = np.searchsorted(horizon, horizon + half, side="left")
valid = (after < horizon.size) & (after > before)
valid &= (horizon - horizon[np.clip(before, 0, horizon.size - 1)] >= half * 0.5)
if not valid.any():
    return np.empty(0, dtype=float)
i = np.nonzero(valid)[0]
j = before[i]
k = after[i]
angle_in = np.arctan2(ys[i] - ys[j], xs[i] - xs[j])
angle_out = np.arctan2(ys[k] - ys[i], xs[k] - xs[i])
turn = np.abs((angle_out - angle_in + np.pi) % (2.0 * np.pi) - np.pi)
arc = (horizon[k] - horizon[j]) / 2.0
good = arc > 0.0
return (turn[good] / arc[good]) * 1000.0
```

```python
# source: lib/measure.py::fiber_mean_curvature
profile = fiber_curvature_profile(
    fiber, x_size_per_pixel, y_size_per_pixel, window_nm=window_nm,
)
return float(np.mean(profile)) if profile.size else float("nan")
```

For each centerline point $i$, take the point $j$ half a window (50 nm of arc) behind
it and the point $k$ half a window ahead. Two chords are drawn, $j \to i$ and
$i \to k$, and the curvature is the unsigned angle between them divided by half
the arc they span:

$$
\kappa_i = \frac{\lvert \operatorname{wrap}(\phi_{ik} - \phi_{ji}) \rvert}{(s_k - s_j)/2}
\times 1000 \quad [\text{rad/µm}]
$$

The divisor is half the arc because each chord's direction is the tangent at
its own midpoint, so the two directions are only half the window apart. Dividing
by the whole arc reports half the true curvature. The column shows the mean of
$\kappa_i$ over the fiber.

The window is needed even on the sub-pixel centerline. Over a few pixels the
turning angle is set by the centerline's own sideways noise. On synthetic arcs of
80–400 nm radius with 2 nm pixels, the 100 nm window read within 2 % of $1/R$.

A point is used only if a full half window exists **ahead** of it (`after <
horizon.size`). **Behind** it, half of a half window (25 nm) is enough. This
check is `horizon[i] - horizon[j] >= half * 0.5`, so points 25–50 nm from the
start use a shorter backward chord. A fiber shorter than 100 nm has no
curvature, and its cell is blank rather than 0, so it is not read as perfectly
straight.

### 3.7 `EP count`

`len(Fiber.ep_indices)`: the number of the fiber's end points that are
**skeleton endpoints** in the bundle's `ep` array (§1.2). A cut made at a branch
point is not an endpoint, so the count is 2 for a fiber with both ends free, 1
for a fiber cut at one end, and 0 for a fragment between two crossings. For a
connected fibril, each outer end counts only if the fragment it comes from ended
at a skeleton endpoint (§5.2). An endpoint on the image border still counts, even
though the fiber may continue outside the scan.

### 3.8 `Kink count` and `unjudged`

`len(Fiber.kink_indices)` and `len(Fiber.unjudged_indices)`. For a traced
fragment, both are read from the bundle: `kp` holds the judged kinks and `up`
the bends measured within 1.5 W of a centerline end and left unjudged. Both are
matched to the fiber by skeleton pixel (§1.2). The rule that produced them is
[Analysis algorithms](algorithms.md) §4.3–§4.4.

A connected fibril or a height-band sub-fiber is a centerline the bundle does
not contain. GUI04 judges it again with `KinkDetector.judge_line`, using the
`kinkangle_deg` recorded in the bundle, so that one image never shows kinks from
two rules (§5.2). An unjudged bend is drawn as a hollow grey circle. It is never
counted in `Kink count`, the kink density, or the CSV kink angles.

### 3.9 `kink density (1/µm)`

```python
# source: lib/kink_detector.py::END_MARGIN_WIDTHS
END_MARGIN_WIDTHS = 1.5
```

```python
# source: lib/measure.py::fiber_kink_density
length_um = float(stat.length_nm) / 1000.0
width_nm = float(getattr(stat, "width_nm", float("nan")))
if np.isfinite(width_nm) and width_nm > 0.0:
    length_um -= 2.0 * END_MARGIN_WIDTHS * width_nm / 1000.0
if length_um <= 0.0:
    return float("nan")
return float(stat.kink_count) / length_um
```

$$
\text{kink density} = \frac{N_\text{kink}}{(L - 2 \times 1.5\,W)/1000}
$$

The divisor is the **judged** length. The kink rule does not judge a bend within
1.5 W of either end, so dividing by the whole contour would bias the density
low, most of all on dense specimens with many short fragments. A fiber shorter
than 3 W had nothing judged and is blank. A fiber with no kink over a judged
length is a real 0.00. The W used here is `FiberStats.width_nm` even when it is
the fallback width, which the `W (nm)` column leaves blank. A fiber without a
width (format 1.0, on the skeleton track) is divided by its whole contour.

### 3.10 `W (nm)`

```python
# source: lib/measure.py::compute_fiber_stats
width_px = float(getattr(f, "width_px", float("nan")))
width_nm = (
    width_px * x_size_per_pixel
    if x_size_per_pixel is not None and np.isfinite(width_px)
    else float("nan")
)
```

The apparent width W of §2.1, converted to nanometers with the **X** pixel size.
W is measured along the normal in pixel units, whatever the fiber's direction,
so on a scan whose X and Y pixel sizes differ it is exact only for a fiber
running along Y. The cell is blank when the fallback width was substituted
(`Fiber.width_measured` is `False`); the load log reports how many fibers used
it. W is the scale at which the fiber's kinks were judged, and it includes the
probe's broadening. It is not the fiber's physical diameter.

### 3.11 `reliable`

```python
# source: lib/measure.py::compute_fiber_stats
reliable = getattr(f, "line_reliable", None)
reliable_fraction = (
    float("nan") if reliable is None or len(reliable) == 0
    else float(np.mean(np.asarray(reliable, dtype=bool)))
)
```

The fraction of centerline points whose position was measured on this fiber's own
cross-section (§2.5) rather than interpolated. A low value means much of the
centerline is a straight interpolation, where kinks and curvature cannot be found.
A connected fibril counts its bridge points as not reliable (§5.2).

## 4. The fiber detail window

### 4.1 The fiber image

```python
# source: guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_fiber_image
x_scale, y_scale, unit_label = app._get_extent_scale_xy_and_unit()
if app.current_image is not None:
    full_h, full_w = app.current_image.calibrated_image.shape[:2]
    x_spp = x_scale / full_w
    y_spp = y_scale / full_h
...
if app.show_fiber_track_var.get() and len(fiber.xtrack) > 0:
    ax.plot((fiber.xtrack + off_x + 0.5) * x_spp,
            (fiber.ytrack + off_y + 0.5) * y_spp,
            color="lime", lw=1.0, alpha=0.75, zorder=4)
if app.show_fiber_kink_var.get() and len(fiber.kink_indices) > 0:
    kx = (fiber.xtrack[fiber.kink_indices] + off_x + 0.5) * x_spp
    ky = (fiber.ytrack[fiber.kink_indices] + off_y + 0.5) * y_spp
    ax.scatter(kx, ky, c="cyan", s=20, zorder=5)
unjudged = getattr(fiber, "unjudged_indices", None)
if app.show_fiber_kink_var.get() and unjudged is not None and len(unjudged) > 0:
    ux = (fiber.xtrack[unjudged] + off_x + 0.5) * x_spp
    uy = (fiber.ytrack[unjudged] + off_y + 0.5) * y_spp
    ax.scatter(ux, uy, s=20, facecolors="none", edgecolors="0.6",
               linewidths=1.0, zorder=5)
```

The green curve is the centerline (`Fiber.xtrack` / `Fiber.ytrack`), along
which every number in the table is measured. Cyan dots are kinks and hollow grey circles are
unjudged bends, both drawn at their index on the centerline. The 0.5 offset puts
each coordinate at the center of its pixel, so the centerline sits on the ridge.

This view scales the axes by the displayed extent divided by the array size
(`x_scale / full_w`). The measurement pixel size divides by the array size plus
one (see *Conventions*), so the drawn axes and the measured lengths differ by
one pixel in the scan width.

### 4.2 The height profile

```python
# source: guis/GUI04_Tracking_fiber.py::FiberDetailWindow._redraw_profile
horizon = np.asarray(fiber.horizon, dtype=float)
height = np.asarray(fiber.height, dtype=float)
used = height_sample_mask(fiber)
if used.all():
    ax.plot(horizon, height, color="dimgray", lw=1.5)
else:
    grown = used | np.roll(used, 1) | np.roll(used, -1)
    ax.plot(horizon, np.where(grown, height, np.nan),
            color="dimgray", lw=1.5)
    ax.plot(horizon, np.where(~used, height, np.nan),
            color="silver", lw=1.2, linestyle="--")
if app.show_medmax_var.get():
    med = float(np.median(height[used]))
    mx  = float(np.max(height[used]))
...
if app.show_kink_var.get() and len(fiber.kink_indices) > 0:
    for i, ki in enumerate(fiber.kink_indices):
        if ki < len(fiber.horizon):
            ax.axvline(x=fiber.horizon[ki], color="cyan", linestyle="--", lw=1.0,
                       label="Kink" if i == 0 else None)
```

The profile plots `Fiber.height` (the crest heights, §2.6) against
`Fiber.horizon` (§2.7). The samples the height statistics use are solid. The ones
`height_sample_mask` leaves out (§3.3) are dashed and lighter. The median and
maximum guide lines are computed from the same mask as `median (nm)` and
`max (nm)`, so the plot and the table always agree. The vertical cyan lines mark
the kinks at their distance along the centerline.

## 5. Connected fibrils

GUI01 cuts the skeleton at every crossing and branch, so one physical fibril
reaches GUI04 as several fragments. Pressing 「自動連結」 runs a search that
decides which fragments form one fibril. The connection dialog lists the
candidates for one fiber so that a join can be chosen by hand. Both kinds of
join are saved as chains of fragments and rebuilt at measurement time.

### 5.1 Candidate values

```python
# source: lib/fiber_connector.py::ConnectParams
clusters_range: float = 20.0
angle_threshold: float = 110.0
lookback_length: int = 15
num_avg_points: int = 5
height_diff_ratio: float = 1.0
trim_points: int = 5
```

The search and the candidate list read the **skeleton pixels** (§1.3), in
`(row, col)` order. Which fragments continue each other is a question of
topology, and the thresholds were tuned on the skeleton. For each end $B$ of a
fragment, the look-back point $A$ lies `lookback_length` − 1 = 14 skeleton-track
points inside it. For a fragment shorter than 15 points, it is the fragment's other
end:

```python
# source: lib/fiber_connector.py::_fragment_end_geometry
sx, sy = skeleton_track(frag)
xs = sx + frag.data[0]
ys = sy + frag.data[1]
step = min(lookback_length, len(xs))
ends[i, 0] = (ys[0], xs[0])
backs[i, 0] = (ys[step - 1], xs[step - 1])
ends[i, 1] = (ys[-1], xs[-1])
backs[i, 1] = (ys[-step], xs[-step])
```

Each fragment's height for the height gate is the median of the calibrated
image over its skeleton pixels. This is not the crest height of §2.6.

```python
# source: lib/fiber_connector.py::_fragment_median_heights
medians[i] = float(np.median(calibrated[ys, xs]))
```

The dialog searches within twice `clusters_range`, 40 px by default:

```python
# source: lib/fiber_connector.py::MANUAL_RANGE_FACTOR
MANUAL_RANGE_FACTOR = 2.0
```

```python
# source: lib/fiber_connector.py::_manual_reach
if radius is None:
    return float(params.clusters_range * MANUAL_RANGE_FACTOR)
return float(radius)
```

For every end $C$ of another fiber within that radius, with look-back point
$D$, the dialog reports:

```python
# source: lib/fiber_connector.py::_candidates_for
dist = float(np.hypot(B[0] - C[0], B[1] - C[1]))
if dist > reach:
    continue
angle_abd = angle_between_three_points(A, B, D)
angle_acd = angle_between_three_points(A, C, D)
low = min(medians[index], medians[j])
ratio = (
    abs(medians[index] - medians[j]) / low if low > 0 else 0.0
)
auto = (
    dist <= params.clusters_range
    and angle_abd > params.angle_threshold
    and angle_acd > params.angle_threshold
    and ratio <= params.height_diff_ratio
)
out.append({
    "index": j,
    "self_end": e,
    "other_end": f,
    "distance": dist,
    "angle": float(min(angle_abd, angle_acd)),
    "height_ratio": float(ratio),
    "auto": bool(auto),
})
```

```python
# source: lib/fiber_connector.py::angle_between_three_points
ba = np.array(A) - np.array(B)
bd = np.array(D) - np.array(B)
denom = np.linalg.norm(ba) * np.linalg.norm(bd)
if denom == 0:
    return 0.0
cosine_angle = np.dot(ba, bd) / denom
return float(np.degrees(np.arccos(np.clip(cosine_angle, -1.0, 1.0))))
```

| Dialog column | Value |
|---|---|
| distance (px) | $\lVert B - C \rVert$ in pixel indices. It is not scaled by the pixel size. |
| angle (degree) | $\min(\angle ABD,\ \angle ACD)$. Two fragments that continue in a straight line give about 180°, and a U-turn gives about 0°. |
| height diff | $\lvert m_1 - m_2 \rvert / \min(m_1, m_2)$ for the two median heights; 0 when the lower median is not positive. |
| 自動 | Whether all four gates pass: distance ≤ `clusters_range`, both angles > `angle_threshold`, height diff ≤ `height_diff_ratio`. |

The gates are **reported, not applied**, so a continuation the angle gate
rejects can still be chosen by hand. Candidates are listed with the ones that
pass all gates first, then by distance:

```python
# source: lib/fiber_connector.py::connection_candidates
ends, backs = _fragment_end_geometry(fibers, params.lookback_length)
medians = _fragment_median_heights(image.calibrated_image, fibers)
reach = _manual_reach(params, radius)
out = _candidates_for(index, ends, backs, medians, params, reach)
out.sort(key=lambda c: (not c["auto"], c["distance"]))
return out
```

### 5.2 Building a fibril from a chain

A chain is an ordered list of fragments, each with a flag saying whether to
reverse it. `_build_chain_fiber` joins the fragments end to end:

```python
# source: lib/fiber_connector.py::_build_chain_fiber
long_enough = len(fh) > trim + n_avg
head_trim = trim if (k > 0 and long_enough) else 0
tail_trim = trim if (k < last and long_enough) else 0
...
if xs:
    b_y, b_x = ys[-1], xs[-1]
    c_y, c_x = fy[0], fx[0]
    tail_avg = float(np.mean(hs[-min(n_avg, len(hs)):]))
    head_avg = float(np.mean(fh[:min(n_avg, len(fh))]))
    num_points = max(abs(b_y - c_y), abs(b_x - c_x))
    if num_points > 1:
        bridge_y = np.linspace(b_y, c_y, num=num_points).round().astype(int).tolist()[1:-1]
        bridge_x = np.linspace(b_x, c_x, num=num_points).round().astype(int).tolist()[1:-1]
        ys.extend(bridge_y)
        xs.extend(bridge_x)
        if on_centerline:
            lys.extend(np.linspace(lys[-1], fly[0], num=num_points).tolist()[1:-1])
            lxs.extend(np.linspace(lxs[-1], flx[0], num=num_points).tolist()[1:-1])
        else:
            lys.extend(bridge_y)
            lxs.extend(bridge_x)
        bridge_h = np.linspace(tail_avg, head_avg, num=num_points).tolist()[1:-1]
        hs.extend(bridge_h)
        rel.extend([False] * len(bridge_h))
        meas.extend([False] * len(bridge_h))
```

1. **Trim.** At each joined end, `trim_points` = 5 points are removed to drop the
   noise of the crossing where the fragment was cut. A fragment is trimmed only
   if it is longer than `trim_points` + `num_avg_points`. If the two trims
   would consume an interior fragment entirely, its tail trim is dropped, and
   then its head trim if that is still not enough.
2. **Bridge.** The gap between the two trimmed ends is filled with
   $\max(\lvert\Delta\text{row}\rvert, \lvert\Delta\text{col}\rvert) - 2$ points
   on a straight segment. This is done on the skeleton track and on the centerline
   together, so the two stay index-aligned. Each fragment keeps the centerline
   it was displayed with. Joining does not move it.
3. **Bridge heights.** The bridge heights run linearly from the mean of the last
   `num_avg_points` = 5 heights before the gap to the mean of the first 5 after
   it. Bridge points are marked neither reliable nor measured. They lower the
   `reliable` fraction and are left out of the height statistics (§3.3), but
   they count toward `length (nm)`.

The joined centerline then becomes a `Fiber`:

```python
# source: lib/fiber_connector.py::_rebuild_connected_fiber
if kind == HALF_MAX_CENTERLINE:
    horizon = polyline_distance(
        xtrack, ytrack, size_per_pixel, y_size_per_pixel,
    )
...
if kind == HALF_MAX_CENTERLINE:
    width, width_measured = measure_apparent_width(
        image.calibrated_image, pix_x, pix_y, return_measured=True,
    )
    judged = detector.judge_line(line_x, line_y, width)
    kink_indices, kink_angles = judged.kink_indices, judged.kink_angles
    kink_excess, unjudged_indices = judged.kink_excess, judged.unjudged_indices
...
ep_indices = np.array([
    i for i, real in zip((0, len(line_x) - 1), end_is_real) if real
], dtype=int)
```

- The fibril's length is the polyline length of the joined centerline (§2.7).
- Its W is measured again (§2.1) over the joined skeleton pixels, bridges
  included.
- Its kinks and unjudged bends are judged again on the joined centerline at that W,
  using the bundle's own `kinkangle_deg`. A bend that sat next to a cut end of a
  fragment is no longer next to an end, so it can now be judged.
- Its endpoints are the first and last point, each counted only if the outer
  fragment ended at a skeleton endpoint (§3.7).

### 5.3 The height filter

GUI04's height filter runs after connection. It cuts each fiber into the
contiguous runs whose `Fiber.height` lies in the chosen band, bridge heights
included, and rebuilds each run with `_rebuild_connected_fiber`:

```python
# source: lib/fiber_connector.py::filter_fibers_by_height
h = np.asarray(fib.height)
lower_cond = (h >= lower_height) if include_lower_limit else (h > lower_height)
upper_cond = (h <= upper_height) if include_upper_limit else (h < upper_height)
in_band = lower_cond & upper_cond
if not in_band.any():
    continue
...
for start, stop in _contiguous_runs(in_band):
    if stop - start < 2:
        continue
```

A sub-fiber is a piece of its parent's centerline. Its W is re-measured and its kinks
are re-judged on that piece, so its `Kink count`, `unjudged`, `W (nm)`, and
kink density can differ from the parent's. Its end is a real end only where it
is the parent's own real end. An end made by the filter's cut is a cut, and the
height statistics treat it as one (§3.3).

## 6. Keeping this page current

This page quotes the code. Whenever the quoted code changes, the page has to be
reread. Three mechanisms catch such a change:

- `scripts/check_gui04_docs.py` holds the list of quoted symbols
  (`WATCHED_SYMBOLS`) and runs all the checks: every excerpt matches its symbol,
  every watched symbol is quoted in both languages, the two language versions
  share one heading structure and identical excerpts, every fiber-table column
  has a subsection of §3 whose heading names it, the prose always names
  which of the centerline and the skeleton track it means, and every
  symbol's fingerprint matches
  `tests/gui04_doc_manifest.json`.
- `.githooks/pre-commit` runs it on the staged snapshot and blocks the commit on
  any finding. It also blocks a commit that refreshes the fingerprints without
  touching either language version of this page. `tests/test_gui04_docs.py`
  runs the same checks in CI, where they cannot be skipped.
- The Claude Code hook `.claude/hooks/doc_code_reminder.py` runs after an AI
  agent edits one of the watched files. When the edit changed what a quoted
  symbol computes, it tells the agent which sections to update.

After a change, update the affected sections and excerpts of both
`docs/gui04_measurements.md` and `docs/gui04_measurements.ja.md`, then refresh
the fingerprints:

```text
.venv\Scripts\python.exe scripts\check_gui04_docs.py --update
```

A new column in GUI04's fiber table must be explained in a subsection of §3
of both language versions, with the column name in backticks in its heading
(for example ``### 3.12 `new column` ``). Adding the name to the overview table
alone does not pass the check.

To quote a new symbol, add it to `WATCHED_SYMBOLS` first. The check refuses an
excerpt of a symbol it does not watch, so quoted code is always guarded.
