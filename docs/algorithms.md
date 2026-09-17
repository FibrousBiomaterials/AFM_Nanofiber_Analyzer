# Analysis algorithms

This page explains what the four preprocessing stages actually do, and where in
the source each step lives. It is written for people who need to justify a
number in a figure caption: which decisions the software made on their behalf,
on what evidence, and which parameter changes each decision.

The API reference documents each function's contract. This page documents the
reasoning that connects them.

## How to read the code references

Code is referenced **by symbol name**, never by line number, because line
numbers go stale on the first unrelated edit. A reference such as
`Segmenter._binaryzation` means the method of that name in `lib/segmenter.py`;
`bg_calibrator.BG_METHOD_NAMES` means the module-level constant. Every symbol
named on this page is checked against the source by
`tests/test_algorithm_docs.py` on every run of the test suite, so a rename or
removal fails the build rather than silently leaving this page wrong.

Each step is also shown **with the code that performs it**. Every code block
starts with a header naming where it comes from:

```text
# source: lib/segmenter.py::Segmenter._binaryzation
```

That is the file and the function, method (`Class.method`), or module constant
the code belongs to; a header may list several symbols of one file, separated by
commas. A line holding only `...` marks omitted code, and comments, blank rows
and the method's indentation are left out. Every excerpt is compared, line for
line, with the symbol it names (`scripts/doc_excerpts.py`, run by
`tests/test_algorithm_docs.py` and by the pre-commit hook), and the English and
Japanese pages must quote identical code, so an excerpt cannot silently differ
from what the software runs.

The same test guards the reverse direction: it hashes the algorithm modules —
the four stages and `lib/centerline.py`, which places the line kinks are
judged on — with comments and docstrings stripped, so any change to what the
code computes fails until this page has been reviewed. The document cannot quietly
drift away from the code it describes.

## Conventions used throughout

| Quantity | Unit | Notes |
|---|---|---|
| Height | nanometres (nm) | The loader converts to nm; every height threshold below is an absolute nm value on the **background-corrected** image, where the substrate sits at 0 nm. |
| In-plane distance | pixels (px) in the stages, micrometres (µm) in the results | The stages are deliberately pixel-based; the pixel size enters only at measurement time. |
| Angles | radians internally, degrees in the parameter file | `pipeline.build_stages` converts `kinkangle_deg` to radians when it constructs `KinkDetector`. |
| Array indexing | `image[row, column]`, i.e. `[y, x]` | Several helpers return `np.where` output, where the first array is the row index. |

**The one-pixel crop.** Background correction is built on first differences
between neighbouring pixels, so its output is one pixel smaller on each axis
than the input: `BGCalibrator._bg_calibrate` returns `original[1:, 1:] - bg_sm`.
Every later stage works on that cropped array. A feature reported at pixel
$(r, c)$ of the analysis therefore sits at pixel $(r+1, c+1)$ of the raw scan.

**Parameters.** Every user-settable value below is a field of
`pipeline.ProcParams`, saved beside each bundle as `<input_stem>_param.json`.
That file is the complete record of how an image was analysed. Values quoted
as "default" are the `ProcParams` defaults, which are what the GUI and CLI
start from — not the constructor defaults of the stage classes, which differ in
places and apply only when a class is built directly in a script.

## The pipeline in one view

```text
raw AFM text / CSV  ->  afm_io.load_afm_text()      \
Gwyddion .gwy       ->  gwy_io.load_gwy_image()     /  -> height array (nm)
                                                        |
                        ProcessedImage.original_image  <-+
                                |
   1. BGCalibrator   ->  calibrated_image   (nm, substrate at 0)
   2. Segmenter      ->  binarized_image    (bool fiber mask)
   3. Skeletonizer   ->  skeleton_image     (1 px wide centrelines) + ep / bp
   4. KinkDetector   ->  kink points and angles per skeleton component,
                         judged on its half-maximum centerline (§4.2)
                                |
                        .b2z bundle + _param.json
```

`pipeline.process_file` runs exactly this sequence, and both GUI01 and
`cli.py process` call it, so the two entry points cannot diverge. The stage
objects are built once by `pipeline.build_stages`.

Each stage reads what the previous one wrote and fails loudly at the boundary
if it is missing — `Segmenter.__call__` raises if `calibrated_image` is `None`
rather than failing somewhere inside OpenCV.

---

## 1. Background correction

**Code:** `lib/bg_calibrator.py` — `BGCalibrator.__call__`, dispatching to
`_call_trendfill`, `_call_tophat`, or `_call_spline1d`.
**Reads:** `original_image`. **Writes:** `calibrated_image`.

`BGCalibrator.__call__` only dispatches:

```python
# source: lib/bg_calibrator.py::BGCalibrator.__call__
if self.bg_method == 'tophat':
    self._call_tophat(image)
elif self.bg_method == 'spline1d':
    self._call_spline1d(image)
else:
    self._call_trendfill(image)
```

### 1.1 The problem being solved

A raw AFM scan is not a height map of the specimen sitting on a flat plane. It
carries the sample tilt and the scanner's bowl distortion, and on this
project's bundled scans those dominate the signal: the least-squares plane
drops **0.23–0.34 nm per pixel**, so the background falls 7–9 nm across the
width of a single fiber, while the fiber itself is only about 10 nm tall. After
the best-fit plane is removed from the bundled Bruker scan, **32 nm of
curvature** still remains.

Two consequences follow, and they set the design of this whole stage:

1. Every later threshold is an **absolute height in nm**. They are only
   meaningful if the substrate has been brought to 0 nm everywhere.
2. Any background estimate that cannot reproduce that ramp leaves an error
   *comparable in size to the signal it is meant to reveal*.

### 1.2 The shape shared by all three methods

All three methods follow the same skeleton, and the differences are confined to
one step:

```text
(optional) identify fiber pixels and exclude them from the background pool
    -> fit and subtract a smooth trend surface        (detrend)
    -> fill the excluded pixels                       <- the methods differ here
    -> Savitzky-Golay smoothing
    -> add the trend surface back                     (retrend)
    -> subtract the result from the original
```

All three then end with an optional 3×3 median filter, enabled by
`apply_median` (default off), which suppresses impulse-like residual noise at
the cost of blunting the sharpest height features.

The detrend/retrend sandwich is the part that matters most. With the trend
removed, the height difference across a masked hole is close to zero, so the
choice of filler barely matters: measured across a 21-px hole, the maximum
deviation from the chord was 0.24 nm for nearest-neighbour propagation against
0.20 nm for inpainting — but **3.93 nm** before detrending. The fitting is done
by `BGCalibrator._fit_trend_surface`.

`_fit_trend_surface` fits a **second-order** surface, not a plane, because real
scans are bowl-shaped as well as tilted; the quadratic reduced the residual
fill error across a fiber hole from 0.68 nm (plane) to 0.24 nm. Coordinates are
normalised to $[-1, 1]$ before the quadratic terms are formed, which keeps the
design matrix well-conditioned. If the background pixels are degenerate — all
on one row, say — `numpy.linalg.lstsq` would silently return a rank-deficient
solution, so the rank is checked explicitly and the fit falls back from
quadratic to plane to the mean background level.

With the coordinates normalised to $x_n, y_n \in [-1, 1]$, the fitted surface
is

$$
T(x, y) = a\,x_n^2 + b\,y_n^2 + c\,x_n y_n + d\,x_n + e\,y_n + g
$$

solved by least squares over the background pixels only (`valid_mask`):

```python
# source: lib/bg_calibrator.py::BGCalibrator._fit_trend_surface
h, w = image.shape
y_grid, x_grid = np.mgrid[0:h, 0:w]
x_n = x_grid / max(w - 1, 1) * 2.0 - 1.0
y_n = y_grid / max(h - 1, 1) * 2.0 - 1.0
ones = np.ones_like(x_n)
z = image[valid_mask]
for terms in (
    (x_n * x_n, y_n * y_n, x_n * y_n, x_n, y_n, ones),
    (x_n, y_n, ones),
):
    design = np.column_stack([t[valid_mask] for t in terms])
    coef, _residuals, rank, _singular = np.linalg.lstsq(design, z, rcond=None)
    if rank == design.shape[1]:
        return sum(c * t for c, t in zip(coef, terms))
return np.full(image.shape, float(np.mean(z)), dtype=np.float64)
```

### 1.3 `trendfill` — the default method

Named for what it does: subtract the trend, fill the holes. It was called
`inpaint` up to version 1.0.0, when the fill was OpenCV Navier–Stokes
inpainting; `bg_calibrator.BG_METHOD_ALIASES` still translates the old spelling
so a stored parameter file keeps running.

`_call_trendfill` runs the three steps below and subtracts the result:

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_trendfill
self._detect_fiber_mask(image.original_image)
self.bg_only, self.bg_sm = self._bg_generate(image.original_image, self.tri_difx_fill, self.tri_dify_fill)
...
calibrated_image = self._bg_calibrate(image.original_image, self.bg_sm)
if self.apply_median:
    calibrated_image = cv2.medianBlur(calibrated_image.astype(np.float32), ksize=3)
image.calibrated_image = calibrated_image
```

#### Step 1 — Find the fiber pixels from gradient statistics

`BGCalibrator._detect_fiber_mask` runs four helpers in sequence.

```python
# source: lib/bg_calibrator.py::BGCalibrator._detect_fiber_mask
self.dif_x, self.dif_y = self._difXY(original)
self.histx, self.histy, self.outx, self.outy = self._bg_fit(self.dif_x, self.dif_y)
self.tri_difx, self.tri_dify = self._dif_sep(self.dif_x, self.dif_y, self.outx, self.outy)
self.tri_difx_fill, self.tri_dify_fill = self._extract_fiber(self.tri_difx, self.tri_dify)
```

`_difXY` takes first differences along each axis, $\Delta_x$ and $\Delta_y$.
Large absolute differences mark edges, which on this specimen means fiber
flanks.

```python
# source: lib/bg_calibrator.py::BGCalibrator._difXY
dif_x = image[:, 1:] - image[:, 0:-1]
dif_y = image[1:, :] - image[0:-1, :]
return dif_x, dif_y
```

`_bg_fit` histograms each difference image into 150 bins and fits a **Gaussian
plus a linear baseline** with `lmfit`. The Gaussian is the *background*
population: the noise of the substrate, centred near zero. The fiber flanks
live in the tails. X and Y are fitted independently because the AFM slow-scan
axis has different noise characteristics and typically a broader $\sigma$.

The fit starts from the median of the differences and a robust width (the
interquartile range divided by 1.349). The Y fit is the same code on `dif_y`:

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_fit
histx = np.histogram(np.ravel(dif_x), bins=bin_n)
...
h_arrayx = (histx[1][1:] + histx[1][:-1]) / 2
...
bg = PolynomialModel(prefix='bg_', degree=1)
pV1 = GaussianModel(prefix='pv1_')
model = pV1 + bg
pars_x = model.make_params()
pars_x['bg_c0'].set(0)
pars_x['bg_c1'].set(0)
pars_x['pv1_amplitude'].set(dif_x.size / 10)
pars_x['pv1_center'].set(np.median(dif_x))
pars_x['pv1_sigma'].set((np.percentile(dif_x, 75) - np.percentile(dif_x, 25)) / 1.349)
outx = model.fit(histx[0], pars_x, x=h_arrayx)
```

`_dif_sep` converts each difference image into a **ternary map** using the
fitted centre $\mu$ and width $\sigma$:

$$
\text{tri} = \begin{cases}
+1 & \Delta > \mu + f\sigma \\
0 & \text{otherwise} \\
-1 & \Delta < \mu - f\sigma
\end{cases}
$$

where $f$ is `threshold_factor` (default 2.0). So $\pm 1$ marks "this step is
too large to be substrate noise", calibrated per image rather than by a fixed
nm value.

The Y map is built the same way from the Y fit.

```python
# source: lib/bg_calibrator.py::BGCalibrator._dif_sep
outx_min = outx.best_values['pv1_center'] - self.threshold_factor * outx.best_values['pv1_sigma']
outx_max = outx.best_values['pv1_center'] + self.threshold_factor * outx.best_values['pv1_sigma']
...
tri_difx = np.where(dif_x < outx_min, -1, 0) + np.where(dif_x > outx_max, 1, 0)
```

`_extract_fiber` then scans each row (for X) and each column (for Y) and
run-length encodes the ternary map, looking for two sign patterns that a ridge
crossing the scan line produces:

- **Pattern 1 — `[+1, 0, -1]`**: up the flank, flat over the crest, down the
  far flank. Accepted when the flat run is shorter than `fiber_detect_factor`
  (default 10), i.e. the crest is narrow enough to be a fiber.
- **Pattern 2 — `[+1, -1]`**: a sharp ridge with no resolved flat crest.
  Accepted when the span exceeds `noise_detect_factor` (default 10), which is
  what keeps single-pixel noise spikes out.

Every pixel between the pattern's outer bounds is marked as fiber. The X and Y
results are combined by union in the next step.

In the code, `l_arr` holds the value of each run and `arg_arr` the index where
it starts. Pattern 1 is accepted when the zero run is shorter than
`fiber_detect_factor`, and pattern 2 when the distance from the start of the +1
run to the start of the run after the −1 run exceeds `noise_detect_factor`. The
Y pass is the same code with rows and columns swapped:

```python
# source: lib/bg_calibrator.py::BGCalibrator._extract_fiber
tri_difx_fill = np.zeros(tri_difx.shape)
for j in range(tri_difx.shape[0] - 1):
    row = tri_difx[j, :]
    change_pos = np.where(np.diff(row) != 0)[0]
    l_arr = np.empty(len(change_pos) + 1, dtype=row.dtype)
    l_arr[0] = row[0]
    l_arr[1:] = row[change_pos + 1]
    arg_arr = np.empty(len(change_pos) + 1, dtype=np.intp)
    arg_arr[0] = 0
    arg_arr[1:] = change_pos + 1
    n = len(l_arr)
    if n < 4:
        continue
    mask1 = (l_arr[:-3] == 1) & (l_arr[1:-2] == 0) & (l_arr[2:-1] == -1)
    gap1_ok = (arg_arr[2:-1] - arg_arr[1:-2]) < self.fiber_detect_factor
    for vi in np.where(mask1 & gap1_ok)[0]:
        tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 3] - 1] = 1
    mask2 = (l_arr[:-3] == 1) & (l_arr[1:-2] == -1)
    gap2_ok = (arg_arr[2:-1] - arg_arr[:-3]) > self.noise_detect_factor
    for vi in np.where(mask2 & gap2_ok)[0]:
        tri_difx_fill[j, arg_arr[vi]:arg_arr[vi + 2] - 1] = 1
```

#### Step 2 — Clean and dilate the mask

In `_bg_generate`, two corrections are applied before the mask is used:

**Small-component removal.** Pattern 2 also fires on 2- to 10-pixel noise
features, which scatter densely across noisy or wide-field images. Components
smaller than `min_mask_component_area` (default 10, 8-connected) are dropped.
Without this, the dilation below expands each false positive into a
$(2d+1)^2$ hole and the reconstructed background acquires a salt-and-pepper
field, visible as a tiled or cellular artefact.

**Dilation.** The mask is dilated by `mask_dilation` px (default 3). Fiber
*shoulder* pixels that `_extract_fiber` does not catch still carry residual
fiber height; leaving them in the background pool biases the estimate upward
and produces over-subtraction — a dark halo — on both sides of every fiber.

`tri_difx_fill[1:, :]` and `tri_dify_fill[:, 1:]` bring the X and Y maps onto
the grid of the cropped image before the union. The small-component removal runs
only when dilation is on (`mask_dilation` > 0) and `min_mask_component_area` is
above 1:

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_generate
raw_mask = (np.abs(tri_difx_fill[1:, :]) + np.abs(tri_dify_fill[:, 1:])) > 0
if self.mask_dilation > 0 and self.min_mask_component_area > 1:
    n_cc, cc_labels, cc_stats, _cc_centroids = cv2.connectedComponentsWithStats(
        raw_mask.astype(np.uint8), connectivity=8,
    )
    keep = np.zeros(n_cc, dtype=bool)
    if n_cc > 1:
        keep[1:] = cc_stats[1:, cv2.CC_STAT_AREA] >= self.min_mask_component_area
    raw_mask = keep[cc_labels]
if self.mask_dilation > 0:
    kernel = np.ones(
        (self.mask_dilation * 2 + 1, self.mask_dilation * 2 + 1),
        dtype=np.uint8,
    )
    fiber_mask = cv2.dilate(raw_mask.astype(np.uint8), kernel).astype(bool)
else:
    fiber_mask = raw_mask
```

#### Step 3 — Fill, smooth, subtract

The masked pixels are filled from their **nearest background-candidate pixel**,
found with `scipy.ndimage.distance_transform_edt`. Because a background pixel's
nearest background pixel is itself, this preserves the real data exactly and
needs no explicit restore step.

The filled surface is smoothed with a Savitzky–Golay filter (`savgol_window`
default 31, `savgol_polyorder` default 1), the trend is added back, and
`_bg_calibrate` subtracts the result from the original.

`signal.savgol_filter` works along the last axis, so the smoothing runs along
each row (X) only:

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_generate
crop = original[1:, 1:]
bg_only = np.where(~fiber_mask, crop, float('nan'))
valid_mask = ~fiber_mask
if not valid_mask.any():
    return bg_only, np.zeros_like(crop, dtype=np.float64)
bg_trend = self._fit_trend_surface(crop, valid_mask)
detrended = crop - bg_trend
nearest_idx = distance_transform_edt(
    fiber_mask, return_distances=False, return_indices=True,
)
bg_int = detrended[tuple(nearest_idx)]
bg_sm = signal.savgol_filter(
    bg_int, self.savgol_window, self.savgol_polyorder,
) + bg_trend
return bg_only, bg_sm
```

```python
# source: lib/bg_calibrator.py::BGCalibrator._bg_calibrate
height_bgcalib = original[1:, 1:] - bg_sm
return height_bgcalib
```

> **Why the fill method was changed.** Navier–Stokes inpainting is a
> boundary-propagation method designed for thin scratches. At `inpaintRadius=3`
> it extended each side of a hole inward as a flat plateau, meeting in a step
> discontinuity in the middle — measured at up to ±4 nm across a 21-px hole.
> Because `savgol_polyorder <= 1` makes the Savitzky–Golay pass a plain moving
> average along X, that step then leaked into the background estimate of every
> genuine background pixel within half a window of the hole, producing an
> antisymmetric halo: a trough on the uphill side, a ridge on the downhill
> side. The ridge reached **+0.76 nm**, above the default binarization
> threshold of 0.3 nm, so it was segmented as a second fiber running parallel
> to the real one.

### 1.4 `tophat` — fast, mask-free

`_call_tophat` estimates the background as a morphological **opening** with an
elliptical structuring element of diameter `tophat_se_size` (default 25 px).
The opening removes bright structures narrower than the disk, so what survives
is the background; the residual `original - opening` is the classic white
top-hat transform.

Here the trend surface is fitted over every pixel, fibers included, and the
opening is taken of the detrended image and smoothed along X before the trend is
restored:

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_tophat
se = cv2.getStructuringElement(
    cv2.MORPH_ELLIPSE,
    (self.tophat_se_size, self.tophat_se_size),
)
bg_trend = self._fit_trend_surface(
    original, np.ones(original.shape, dtype=bool),
)
opened_detrended = cv2.morphologyEx(
    (original - bg_trend).astype(np.float32), cv2.MORPH_OPEN, se,
).astype(np.float64)
self.bg_open = opened_detrended + bg_trend
self.bg_sm = signal.savgol_filter(
    opened_detrended, self.savgol_window, self.savgol_polyorder,
) + bg_trend
calibrated_image = original[1:, 1:] - self.bg_sm[1:, 1:]
calibrated_image -= np.median(calibrated_image)
```

Two details are not optional:

**It opens a detrended copy.** Opening reproduces a plane in the image
interior, but not within one structuring-element radius of the border, because
erosion there takes its minimum from a clipped neighbourhood that dilation
cannot restore. On a 0.34 nm/px ramp with a 25-px element that leaves a band
about **4 nm** high down the uphill edge — far above the 0.3 nm binarization
threshold, so the scan border itself was being segmented as a fiber.

**It re-centres by the median afterwards.** An opening is a *lower-envelope*
estimator: over a noisy substrate it tracks the local noise minima, so after
subtraction the substrate floats above zero by roughly the noise-envelope
depth. Subtracting the image median brings it back to 0 nm, which is what makes
`global_threshold`, `low_threshold`, and `bp_height` mean the same thing here
as under the interpolating methods, which pass through the middle of the noise.
The median is robust while fibers cover less than about half the image.

This method computes no fiber mask, so none of the ridge-detection
intermediates exist on the object afterwards; they are set to `None` so a stale
read from a previous run fails loudly instead of returning the wrong image.

### 1.5 `spline1d` — for line-noise-dominated scans

`_call_spline1d` reuses `trendfill`'s fiber mask, then fills each line
independently with a 1-D B-spline of degree `spline1d_degree` (default 2),
along the axis named by `spline1d_axis`. Interpolating each **column** (`'y'`)
evens out horizontal stripes — the line-to-line offsets a drifting feedback
loop produces; interpolating each **row** (`'x'`) targets vertical stripes
instead.

The default axis is `'x'`. A line with fewer than `spline1d_degree` + 1 valid
samples, or a degree below 2, is filled linearly instead.

Line ends are deliberately **not extrapolated with a shape**. Beyond a line's
first or last valid sample there is background data on one side only, so any
shape a 1-D method puts there — the spline's own extrapolation, or a linear
ramp — is fitted to that single line, its error grows with the length of the
run, and it is uncorrelated with the neighbouring lines, so each line paints its
own band. `_spline1d_fill` instead holds, across each end run, the **mean of
that line's nearest `end_window` background samples**, with `end_window` set to
`savgol_window` (default 31). On a detrended image what remains specific to one
line is essentially its scan-line offset, which is constant along the line, so
holding a level estimates it without extrapolating a slope, and averaging many
samples keeps pixel noise out of that level. Only a line with fewer than two
valid samples is left unfilled; its pixels are filled from the nearest
background pixel in 2-D.

```python
# source: lib/bg_calibrator.py::BGCalibrator._call_spline1d
self._detect_fiber_mask(original)
self.bg_only, _ = self._bg_generate(original, self.tri_difx_fill, self.tri_dify_fill)
...
bg_trend = self._fit_trend_surface(crop, valid_mask)
detrended = np.where(valid_mask, crop - bg_trend, float('nan'))
bg_int = self._spline1d_fill(
    detrended, axis=self.spline1d_axis, order=self.spline1d_degree,
    end_window=self.savgol_window,
)
unfilled = np.isnan(bg_int)
if unfilled.any():
    nearest_idx = distance_transform_edt(
        ~valid_mask, return_distances=False, return_indices=True,
    )
    nearest = np.where(valid_mask, crop - bg_trend, 0.0)[tuple(nearest_idx)]
    bg_int = np.where(unfilled, nearest, bg_int)
bg_int = bg_int + bg_trend
...
self.bg_sm = signal.savgol_filter(bg_int, self.savgol_window, self.savgol_polyorder)
calibrated_image = original[1:, 1:] - self.bg_sm
```

```python
# source: lib/bg_calibrator.py::BGCalibrator._spline1d_fill
if n_valid < 2:
    continue
s = pd.Series(line)
if n_valid >= order + 1 and order >= 2:
    filled = s.interpolate(method='spline', order=order,
                           limit_direction='both')
else:
    filled = s.interpolate(method='linear', limit_direction='both')
filled = filled.to_numpy(copy=True)
valid_pos = np.flatnonzero(valid)
first, last = valid_pos[0], valid_pos[-1]
k = max(1, min(end_window, n_valid))
filled[:first] = np.mean(line[valid_pos[:k]])
filled[last + 1:] = np.mean(line[valid_pos[-k:]])
```

### 1.6 Choosing a method

| `bg_method` | Use when | Cost |
|---|---|---|
| `trendfill` (default) | General use. Excludes fibers from the background pool, so it does not eat into them. | Highest; the `lmfit` histogram fit dominates. |
| `tophat` | Quick screening, or when the ridge detection misbehaves on an unusual specimen. | Low. |
| `spline1d` | Scans dominated by line noise (feedback glitches, scan-line offsets). | Moderate. |

`spline2d` (a tensor-product B-spline surface) was **removed** after 1.0.0: it
left the largest background residual of every method on every test image, and
the smoothing factor that could have improved it was not reachable from the
GUI. It is listed in `bg_calibrator.BG_METHOD_REMOVED`, which reports it by
name rather than substituting a survivor — silently swapping in another method
would change the numbers a stored `_param.json` reproduces.

---

## 2. Binarization

**Code:** `lib/segmenter.py` — `Segmenter.__call__`.
**Reads:** `calibrated_image`. **Writes:** `binarized_image`.

The stage is a chain of filters. Each one is a separate method so its output
can be inspected while tuning:

```text
_binaryzation            -> binary_image
_remove_small_fragments  -> no_small_binary_image
_remove_nonlinear_objects-> no_linear_binary_image
_remove_connecting_fragments (optional) -> no_connecting_binary_image
remove_low_component     -> no_low_binary_image
_recover_missed_ridges (optional) -> ridge_recovered_image
closing                  -> binarized_image
```

`Segmenter.__call__` wires them in this order:

```python
# source: lib/segmenter.py::Segmenter.__call__
self.binary_image = self._binaryzation(
    image.calibrated_image, self.global_threshold, self.wsize_localbin
)
self.no_small_binary_image = self._remove_small_fragments(self.binary_image, self.area_min)
self.no_linear_binary_image = self._remove_nonlinear_objects(
    self.no_small_binary_image, self.h_length, self.h_sratio
)
if self.apply_no_connecting:
    self.no_connecting_binary_image = self._remove_connecting_fragments(
        self.no_linear_binary_image
    )
else:
    self.no_connecting_binary_image = self.no_linear_binary_image
self.no_low_binary_image = self.remove_low_component(
    image.calibrated_image, self.no_connecting_binary_image
)
self.ridge_recovered_image = self._recover_missed_ridges(
    image.calibrated_image, self.no_low_binary_image, nm_per_px,
)
recovered_union = self.no_low_binary_image | self.ridge_recovered_image
no_small_binary_image4 = closing(recovered_union).astype(bool)
image.binarized_image = no_small_binary_image4
```

### 2.1 Two thresholds, ANDed

`_binaryzation` requires a pixel to pass **both** tests:

$$
\text{mask} = (h > t_{\text{global}}) \;\wedge\; (h > t_{\text{local}}(x,y))
$$

The global threshold `global_threshold` (default 0.3 nm) is an absolute height
above the substrate — this is the number that makes background correction
load-bearing. The local threshold comes from
`skimage.filters.threshold_local` over a window of `wsize_localbin` px
(default 17) and adapts to residual slow variation.

Requiring both is deliberate: the local test alone would promote noise in an
empty region (where it only has noise to compare against), and the global test
alone would miss a fiber sitting in a locally depressed area.

`skimage.filters.threshold_local` is called with its defaults, so the local threshold is a
Gaussian-weighted mean over the window with no offset:

```python
# source: lib/segmenter.py::Segmenter._binaryzation
binary_global = image > global_threshold
local_threshold = threshold_local(image, wsize_localbin)
binary_local = image > local_threshold
binary_final = binary_global & binary_local
return binary_final
```

### 2.2 Area filter

`_remove_small_fragments` drops 8-connected components with area
$\le$ `area_min` (default 100 px²) and then applies a 3×3 median blur, which
removes isolated single pixels and smooths ragged component edges.

```python
# source: lib/segmenter.py::Segmenter._remove_small_fragments
out_binary_image = binary_image.copy()
n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
    np.uint8(out_binary_image), 8
)
areas = stats[:, cv2.CC_STAT_AREA]
small_labels = np.where(areas <= area_min)[0]
mask_remove = np.isin(label_image, small_labels)
out_binary_image[mask_remove] = 0
out_binary_image = cv2.medianBlur(out_binary_image.astype(np.float32), ksize=3)
return out_binary_image.astype(bool)
```

### 2.3 Linearity filter

`_remove_nonlinear_objects` asks whether a component looks like a *line*.
Fibers do; contamination particles and tip artefacts do not.

- Components with area $\ge$ 1000 px² are kept without testing — at that size
  the answer is not in doubt.
- Components whose bounding box is smaller than `h_length` (default 20 px) in
  both dimensions are removed: they cannot contain a line of the required
  length.
- Otherwise the component's bounding box is Canny-edged and run through a
  Hough line transform. The score is

  $$
  s_{\text{ratio}} = \frac{\sum \text{Hough peak accumulator votes}}{\sum \text{edge pixels}}
  $$

  which reads as "what fraction of this object's outline is explained by
  straight lines". A component is removed when $s_{\text{ratio}} <$ `h_sratio`
  (default 0.5) *and* its pixel count is below 1000.

The edge map is built from the component's own pixels
(`label_image[bbox] == i`), not from the whole mask inside the bounding box. A
bounding box is axis-aligned, so a diagonal fiber's box is large and mostly
empty and neighbouring objects land inside it often; cropping the whole mask
let their outlines enter both sides of the $s_{\text{ratio}}$ fraction, and a
component's verdict could turn on what happened to lie near it.

```python
# source: lib/segmenter.py::Segmenter._remove_nonlinear_objects
for i in range(1, n_labels):
    left, top, width, height, area = stats[i]
    if area >= 1000:
        continue
    if max(width, height) < self.h_length:
        out_binary_image[label_image == i] = 0
        continue
    target = label_image[
        top : top + height, left : left + width
    ] == i
    target_edge = canny(target, sigma=0, low_threshold=0, high_threshold=1)
    h, theta, d = hough_line(target_edge)
    accums, _, _ = hough_line_peaks(
        h, theta, d,
        min_distance=max(1, linegap),
        min_angle=1,
        threshold=h_length,
    )
    if len(accums) > 0:
        total_length = float(np.sum(accums))
    else:
        total_length = 0.0
    s_ratio = total_length / (np.sum(target_edge) + _DENOM_EPS)
    self.h_sratio_list.append(s_ratio)
    if s_ratio < h_sratio and np.sum(target) < 1000:
        out_binary_image[label_image == i] = 0
```

> **This was changed after 1.0.0.** Measured over 22 real scans (3318
> components, 1726 linearity-tested), 341 tested components had a neighbour
> inside their bounding box, and on one scan one component was judged
> differently because of it. The final binarized mask was bit-identical on
> every scan, and the strict-regression goldens did not move, so no analysis
> output changes — see `CHANGELOG.md` for the full record.

One further detail: the Hough peak `threshold` argument is `h_length`, so that
parameter acts as a minimum vote count (a proxy for line length) rather than a
length in pixels. And because `target` is now the component alone, its pixel
count equals `area`, which the `area >= 1000` guard has already bounded — the
`np.sum(target) < 1000` term states the rule rather than deciding anything.

### 2.4 Weak-connection cleanup (off by default)

`_remove_connecting_fragments` erodes the mask, drops components at or below
`area_min_connecting` px (default 3), dilates back, and closes. The intent is
to break fragments joined by a one-pixel-wide bridge. It runs only when
`apply_no_connecting` is true, which is **not** the default.

```python
# source: lib/segmenter.py::Segmenter._remove_connecting_fragments
out_binary_image = binary_image.copy()
out_binary_image = binary_erosion(out_binary_image)
n_labels, label_image, stats, centers = cv2.connectedComponentsWithStats(
    np.uint8(out_binary_image), 8
)
for i in range(1, n_labels):
    *_, area = stats[i]
    if area <= self.area_min_connecting:
        out_binary_image[label_image == i] = 0
out_binary_image = binary_dilation(out_binary_image)
out_binary_image = closing(out_binary_image).astype(bool)
return out_binary_image
```

> **This was changed after 1.0.0.** The component loop read
> `range(n_labels - 1)`, covering labels `0 .. n-2`: it entered the background
> label 0 and never reached the highest label. Because OpenCV numbers labels in
> raster order, the highest label is the bottom-most component, so exactly one
> component per image escaped the cleanup for a reason unrelated to its size.
> The loop now reads `range(1, n_labels)`. Entering label 0 was harmless — its
> area never meets the threshold, and clearing background pixels is a no-op —
> so only the skipped component mattered. Since the path is off by default it
> did not run in any recorded analysis; forced on over 22 real scans it skipped
> a qualifying component on three of them, of 1 to 3 pixels.

### 2.5 Height filter

`remove_low_component` removes any component whose **maximum** height over the
calibrated image is below `low_threshold` (default 1.8 nm). Using the maximum
rather than the mean is what lets a genuine thin fiber survive while a broad
low smear is discarded.

The maximum is taken per component with `scipy.ndimage.maximum`:

```python
# source: lib/segmenter.py::Segmenter.remove_low_component
labels = np.arange(1, n_labels)
max_heights = ndi_maximum(height_image, labels=label_image, index=labels)
low_labels = labels[np.asarray(max_heights) < self.low_threshold]
if low_labels.size > 0:
    out_binary_image[np.isin(label_image, low_labels)] = 0
return out_binary_image
```

### 2.6 Ridge recovery (off by default)

`_recover_missed_ridges` is a second pass aimed at fibers the thresholding
chain missed *entirely*. It runs only when `ridge_recovery` is true, and only
when a pixel size is known, because its settings are physical lengths.

1. A multi-scale **Frangi** vesselness filter runs at five scales geometrically
   spaced between `ridge_min_width_nm` and `ridge_max_width_nm` converted to
   pixels. Working in physical units means one setting describes the same
   structure at any scan resolution.
2. The response is thresholded by **hysteresis**, with the high level from
   Otsu and the low level from the triangle method. Hysteresis on the ridge
   response works where the same scheme on raw amplitude does not: the response
   falls to near zero between fibers, so a region grows to a boundary instead
   of percolating across the image.
3. The already-accepted mask is subtracted **before** the connected-component
   pass, not after. Taking only whole candidate components that fail to touch
   the existing mask would discard a long fiber the moment it brushes the
   detected network anywhere — and long fibers touch it most often. Measured on
   one 10 µm scan, 56 candidate components held at least 100 nm of fiber
   outside the mask, one of them 1476 nm, and that rule dropped all of them.
4. Surviving components are kept when their skeleton length reaches
   `ridge_min_length_nm` (default 100 nm). Below about 100 nm the candidates
   stop being distinguishable from particle skirts and tip artefacts by eye.

It is off by default so a stored parameter file reproduces the numbers it was
written with. When on, the Frangi filter dominates the cost of this stage.

In the code, the smallest scale is never below 0.6 px and the largest is at
least 1.5 times the smallest, and when the triangle level is not below the Otsu
level the low level falls back to 0.3 of the high one:

```python
# source: lib/segmenter.py::Segmenter._recover_missed_ridges
if not self.ridge_recovery or not nm_per_px or nm_per_px <= 0:
    return empty
lo = max(0.6, self.ridge_min_width_nm / nm_per_px)
hi = max(lo * 1.5, self.ridge_max_width_nm / nm_per_px)
sigmas = np.geomspace(lo, hi, 5)
response = np.nan_to_num(
    frangi(calibrated_image, sigmas=sigmas, black_ridges=False)
)
if not np.any(response > 0):
    return empty
try:
    high = threshold_otsu(response)
    low = threshold_triangle(response)
except ValueError:
    return empty
if not low < high:
    low = high * 0.3
candidate = apply_hysteresis_threshold(response, low, high)
outside = candidate & ~binary_image.astype(bool)
if not outside.any():
    return empty
n_labels, labels = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
keep = [
    label for label in range(1, n_labels)
    if skeletonize(labels == label).sum() * nm_per_px >= self.ridge_min_length_nm
]
if not keep:
    return empty
return np.isin(labels, keep)
```

### 2.7 Closing

Finally a morphological closing bridges one-pixel gaps. Ridge recovery runs
*before* it deliberately, so a recovered segment ending next to an existing
component is bridged into it rather than left as a separate short fiber.

---

## 3. Skeletonization

**Code:** `lib/skeletonizer.py` (with `lib/imp_tools.py` for the morphology).
**Reads:** `binarized_image`, `calibrated_image`.
**Writes:** `skeleton_image`, `label_image`, `nLabels`, `data`, `ep`, `bp`.

The goal is a one-pixel-wide centreline per fiber. The difficulty is that
thinning is faithful to the *mask*, and the mask has defects — interior holes,
width bumps, low skirts at fiber tips. Each defect becomes a topological
feature on the skeleton, and because tracking later cuts every fiber at every
branch point, an artefact branch point does not merely add noise: it **splits a
real fiber into fragments**. Most of this stage exists to remove artefacts that
would cause that split.

`Skeletonizer.__call__` runs the following, in order.

```python
# source: lib/skeletonizer.py::Skeletonizer.__call__
init_skeleton_image = thin_ignoring_image_border(image.binarized_image)
...
self.set_low_bp_coor(image.calibrated_image, init_skeleton_image, self.bp_height)
self.get_close_eps()
nobranch_image = self.prune_branches(image.calibrated_image, init_skeleton_image)
...
nobranch_skeleton_image = skeletonize(nobranch_image).astype(np.uint8)
...
cleaned_skeleton_image = collapse_skeleton_loops(
    nobranch_skeleton_image, self.max_loop_area, image.calibrated_image
)
cleaned_skeleton_image = prune_short_spurs(
    cleaned_skeleton_image, self.spur_length
)
cleaned_skeleton_image = prune_terminal_hooks(
    cleaned_skeleton_image, image.calibrated_image
)
...
nosmall_skeleton_image = self.remove_small_and_ring(cleaned_skeleton_image)
...
image.skeleton_image = nosmall_skeleton_image
...
image.ep = imp_tools.endPoints(nosmall_skeleton_image)
image.bp = imp_tools.branchedPoints(nosmall_skeleton_image)
```

### 3.1 Thin without letting the image border cut fibers

`thin_ignoring_image_border` replicates the image border outward by
`DEFAULT_BORDER_PAD` = 12 px, thins, then crops back.

`skimage.morphology.thin` treats everything outside the array as background, so
a fiber leaving the field of view is a shape cut flat by the array edge, and
the medial axis of such a truncated end turns toward the nearer corner of the
cut. The traced line drifts off the fiber crest over its last pixels —
about 2 px on the bundled scans, against about 0.5 px along the rest of the
fiber. Replicating the border extends those fibers outward instead of capping
them, which removes the bend. Outside a 12 px border band the skeleton is
identical with and without the correction.

Replication can also inflate a blob lying *along* the border and push its axis
out of the image, so any mask component the padded pass would leave without a
skeleton keeps its plain thinning result. The correction never deletes a fiber.

```python
# source: lib/skeletonizer.py::thin_ignoring_image_border
mask = (np.asarray(binary_image) > 0).astype(np.uint8)
plain = thin(mask).astype(np.uint8)
if pad <= 0:
    return plain
extended = np.pad(mask, pad, mode='edge')
padded = thin(extended).astype(np.uint8)[pad:-pad, pad:-pad]
n_labels, labels = cv2.connectedComponents(mask)
plain_counts = np.bincount(labels[plain > 0], minlength=n_labels)
padded_counts = np.bincount(labels[padded > 0], minlength=n_labels)
lost = np.nonzero((plain_counts > 0) & (padded_counts == 0))[0]
lost = lost[lost != 0]
if lost.size:
    padded = np.where(np.isin(labels, lost), plain, padded).astype(np.uint8)
return padded
```

### 3.2 Height-gated branch pruning

This is the only cleanup step that uses height rather than geometry.

`set_low_bp_coor` splits the skeleton's branch points into **low** and **high**
by comparing the calibrated height against `bp_height` (default 10 nm). A
branch point sitting at fiber height is where two real fibers cross; one
sitting near the substrate is where the mask sprouted something spurious.

```python
# source: lib/skeletonizer.py::Skeletonizer.set_low_bp_coor
all_bps = imp_tools.branchedPoints(init_skeleton_image)
low_bp_coor = np.where(all_bps & (calibrated_image < bp_height))
high_bp_coor = np.where(all_bps & (calibrated_image >= bp_height))
```

`get_close_eps` then finds endpoints within `branch_length` px (default 12) of
a low branch point — only those can plausibly be short spurious branches.

The neighbourhood is a `scipy.ndimage.maximum_filter` of size $2k$ around each low branch
point, with $k$ = `branch_length`:

```python
# source: lib/skeletonizer.py::Skeletonizer.get_close_eps
all_eps_image = imp_tools.endPoints(self._init_skeleton_image)
_low_bps_image = np.zeros_like(self._init_skeleton_image, dtype=np.uint8)
_low_bps_image[self._coor_low_bps] = 1
k = self.branch_length
dilated_low_bps = maximum_filter(
    _low_bps_image.astype(float), size=2 * k, mode='constant', cval=0, origin=0
)
close_eps = all_eps_image & (dilated_low_bps > 0).astype(np.uint8)
self._coor_close_eps = np.where(close_eps)
```

`track_branches` walks the skeleton from each such endpoint, up to
`branch_length` steps. The arm is **pruned** if the walk reaches a low branch
point, or dead-ends without reaching any branch point (an isolated short
fragment). It is **kept** if the walk touches a high branch point or exhausts
the step budget, because neither confirms a short low branch.

In the code, `x` is the row and `y` the column. At each step the dead-end test
comes first, then the low-branch-point test and then the high one, each over the
3×3 neighbourhood of the current pixel; the pixels walked so far are recorded as
the branch when the arm is pruned:

```python
# source: lib/skeletonizer.py::Skeletonizer.track_branches
def touches(mask: np.ndarray, row: int, col: int) -> bool:
    return bool(mask[max(0, row - 1): row + 2, max(0, col - 1): col + 2].any())
starts_x, starts_y = self._coor_close_eps
bl = self.branch_length
for start_x, start_y in zip(starts_x, starts_y):
    if not (bl <= start_x <= height - bl and bl <= start_y <= width - bl):
        continue
    x, y = int(start_x), int(start_y)
    xtrack = [x]
    ytrack = [y]
    visited = {(x, y)}
    for _ in range(bl):
        next_pixels = [
            (x + dx, y + dy)
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0)
            and 0 <= x + dx < height and 0 <= y + dy < width
            and skeleton[x + dx, y + dy]
            and (x + dx, y + dy) not in visited
        ]
        if not next_pixels:
            branches_coor_x += xtrack
            branches_coor_y += ytrack
            break
        if touches(image_low_bps, x, y):
            branches_coor_x += xtrack
            branches_coor_y += ytrack
            break
        if touches(image_high_bps, x, y):
            break
        x, y = next_pixels[0]
        visited.add((x, y))
        xtrack.append(x)
        ytrack.append(y)
```

Two properties of this walk are deliberate and were both fixes to real
failures:

- The walk covers the whole image with explicit bounds checks. Tracing inside a
  local crop instead made the neighbourhood read as empty as soon as the walk
  reached the crop edge, so the dead-end rule deleted up to `branch_length`
  pixels from the tip of a fiber that merely continued past the crop —
  regardless of its height, so even for fibers far above `bp_height`.
- Each walk carries its own visited set. Blanking pixels in one shared working
  image let an earlier endpoint's walk hide skeleton from a later one, making
  the result depend on the order endpoints happened to be processed in.

Endpoints within `branch_length` of the scan border are skipped: an arm ending
that close to the edge is a fiber leaving the field of view, not a branch tip.

The pruned mask is then re-skeletonized to restore one-pixel width.

```python
# source: lib/skeletonizer.py::Skeletonizer.prune_branches
branches_image = self.calc_branches_image(calibrated_image, init_skeleton_image)
return init_skeleton_image - branches_image
```

### 3.3 Collapse loop artefacts

`collapse_skeleton_loops` finds background regions **enclosed** by the
skeleton — labelled with 4-connectivity, the topological complement of the
8-connected skeleton, so a component whose bounding box avoids the image border
is a true hole. A hole of area up to `max_loop_area` (default 100 px) is filled
and the result re-skeletonized, merging the double path back into one line.

Interior holes in the binary mask survive topology-preserving thinning as a
double path, and each such loop puts two or three branch points on one
continuous fiber. Re-skeletonization is a fixed point on an already-thin line,
so pixels far from the filled loops do not move and coordinate-keyed lookups
stay valid there.

A **height guard** prevents this from fusing two real fibers. A loop artefact
lies inside the fiber body, so its interior stays elevated — 40–90 % of the
surrounding ridge height on the bundled scans. A sliver enclosed by two
distinct fibers touching twice contains background-level pixels (~10 % of ridge
height). The enclosure is filled only when its median interior height is at
least `DEFAULT_LOOP_HEIGHT_RATIO` = 0.3 of the surrounding ridge's median,
which sits between the two regimes with margin on both sides. Filling the wrong
one would fuse two fibers and fabricate a path down the middle of the groove
between them.

The ring is the skeleton within a 5×5 dilation of the hole, and both heights are
medians:

```python
# source: lib/skeletonizer.py::collapse_skeleton_loops
inv = (skel == 0).astype(np.uint8)
n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
    inv, connectivity=4
)
height, width = skel.shape
fill_labels = []
for i in range(1, n_labels):
    x, y, cw, ch, area = stats[i]
    if not (area <= max_loop_area and x > 0 and y > 0
            and x + cw < width and y + ch < height):
        continue
    if calibrated_image is not None:
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(width, x + cw + 2), min(height, y + ch + 2)
        hole_local = labels[y0:y1, x0:x1] == i
        dilated = cv2.dilate(
            hole_local.astype(np.uint8), np.ones((5, 5), np.uint8)
        )
        ring = (dilated > 0) & ~hole_local & (skel[y0:y1, x0:x1] > 0)
        cal_local = calibrated_image[y0:y1, x0:x1]
        if ring.any():
            interior_h = float(np.median(cal_local[hole_local]))
            ridge_h = float(np.median(cal_local[ring]))
            if interior_h < min_height_ratio * ridge_h:
                continue
    fill_labels.append(i)
if not fill_labels:
    return skel
filled = (skel > 0) | np.isin(labels, fill_labels)
return skeletonize(filled).astype(np.uint8)
```

### 3.4 Prune short spurs

`prune_short_spurs` removes dead-end arms shorter than `spur_length`
(default 12 px) that start at an endpoint and reach a branch point.

Unlike §3.2 this is **purely geometric**, and that is the point: a spur growing
from the fiber body sits at fiber height, so a height threshold cannot separate
it from a genuine crossing, while a length limit can — a real fiber arm is
rarely that short. Isolated short segments with no branch point in reach are
kept, and arms whose endpoint lies within `border_margin` = 2 px of the image
border are never pruned, for the same reason as above: two fibers that touch
just before exiting the scan form a genuine junction, and pruning the short arm
would fuse them.

A junction is a branch point with at least three skeleton neighbours
(`_junction_degree`). The walk stops without pruning at a fork, and the whole
pass repeats until no spur is removed:

```python
# source: lib/skeletonizer.py::prune_short_spurs
while True:
    bp = imp_tools.branchedPoints(skel).astype(bool)
    if not bp.any():
        return skel
    ep_mask = imp_tools.endPoints(skel).astype(bool) & (skel > 0)
    removed = False
    for sy, sx in zip(*np.where(ep_mask)):
        if (sy < border_margin or sx < border_margin
                or sy >= height - border_margin
                or sx >= width - border_margin):
            continue
        path = [(int(sy), int(sx))]
        cy, cx = int(sy), int(sx)
        while len(path) <= max_length:
            candidates = []
            hit_junction = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if not (0 <= ny < height and 0 <= nx < width):
                        continue
                    if not skel[ny, nx] or (ny, nx) in path:
                        continue
                    if bp[ny, nx] and _junction_degree(skel, ny, nx) >= 3:
                        hit_junction = True
                    else:
                        candidates.append((ny, nx))
            if hit_junction:
                for py, px in path:
                    skel[py, px] = 0
                removed = True
                break
            if len(candidates) != 1:
                break
            cy, cx = candidates[0]
            path.append((cy, cx))
    if not removed:
        return skel
```

### 3.5 Trim terminal hooks

`prune_terminal_hooks` handles a defect none of the three passes above can see.
When segmentation admits a low, widened "skirt" at a fiber tip, thinning
follows the mask's medial axis into the skirt and curls back along its
periphery, leaving a **junction-free hook**. Branch pruning needs a branch
point, spur pruning needs a junction, loop collapsing needs an enclosed hole —
the hook has none of them.

A hook is recognised by a direction reversal near an endpoint: an interior apex
angle below `DEFAULT_HOOK_APEX_ANGLE_DEG` = 120° within
`DEFAULT_HOOK_LENGTH` = 12 px of the end. It is trimmed only where the
calibrated height has fallen below `DEFAULT_HOOK_HEIGHT_RATIO` = 0.5 of the
adjacent fiber body's median height. On the bundled scans hook pixels sit at
19–42 % of body height while real bent ends and junction wiggles sit at
55–113 %, so 0.5 separates the regimes. A genuinely bent fiber end stays at
fiber height and is therefore never cut.

The 120° apex threshold is far sharper than the 150° kink threshold, so kink
detection is unaffected. The trim is capped at the deepest reversal apex found,
so a straight faded end is never shortened.

Relative to the (flawed) mask, the hook is a faithful medial axis of the
admitted skirt, so no binary-shape significance measure from the thinning
literature can identify it — the missing information is the height data. The
criterion instead follows grayscale-guided fiber tracing: a fiber centreline
must lie on the height ridge.

In the code the walk from each endpoint (`_walk_from_endpoint`) is followed for
up to 30 px. At walk index $j \le 12$, the apex angle is the angle between the
vector to the point 6 steps further along ($j + 6$) and the vector back to the
endpoint; the deepest $j$ with an angle below 120° is the apex. The body height
is the median over the 12 pixels after the apex (at least 4 are needed), and the
leading pixels are removed while their height stays below half of it, never past
the apex:

```python
# source: lib/skeletonizer.py::DEFAULT_HOOK_LENGTH, DEFAULT_HOOK_APEX_ANGLE_DEG, DEFAULT_HOOK_HEIGHT_RATIO, _HOOK_DIRECTION_WINDOW, _HOOK_BODY_WINDOW
DEFAULT_HOOK_LENGTH = 12
DEFAULT_HOOK_APEX_ANGLE_DEG = 120.0
DEFAULT_HOOK_HEIGHT_RATIO = 0.5
_HOOK_DIRECTION_WINDOW = 6
_HOOK_BODY_WINDOW = 12
```

```python
# source: lib/skeletonizer.py::prune_terminal_hooks
path = _walk_from_endpoint(skel, int(sy), int(sx), walk_cap)
n = len(path)
py = np.array([p[0] for p in path], dtype=float)
px = np.array([p[1] for p in path], dtype=float)
apex = -1
for j in range(1, min(max_hook_length, n - _HOOK_DIRECTION_WINDOW - 1) + 1):
    body_y = py[j + _HOOK_DIRECTION_WINDOW] - py[j]
    body_x = px[j + _HOOK_DIRECTION_WINDOW] - px[j]
    end_y = py[0] - py[j]
    end_x = px[0] - px[j]
    norm_body = float(np.hypot(body_y, body_x))
    norm_end = float(np.hypot(end_y, end_x))
    if norm_body == 0.0 or norm_end == 0.0:
        continue
    cos_apex = (body_y * end_y + body_x * end_x) / (norm_body * norm_end)
    angle = float(np.degrees(np.arccos(np.clip(cos_apex, -1.0, 1.0))))
    if angle < max_apex_angle_deg:
        apex = j
if apex < 0:
    continue
body_px = path[apex + 1: apex + 1 + _HOOK_BODY_WINDOW]
if len(body_px) < 4:
    continue
body_median = float(np.median(
    [calibrated_image[p] for p in body_px]
))
threshold = max_height_ratio * body_median
if threshold <= 0.0:
    continue
run = 0
while run < apex and calibrated_image[path[run]] < threshold:
    run += 1
for i in range(run):
    skel[path[i]] = 0
```

### 3.6 Remove small and ring components

`remove_small_and_ring` drops components below `min_area` (default 10 px) and
components with **no endpoints at all**. An endpoint-free component is a closed
ring, which no fiber tracing can traverse.

```python
# source: lib/skeletonizer.py::Skeletonizer.remove_small_and_ring
returned_image = np.copy(skeleton_image)
nLabels, label_Images, data, center = cv2.connectedComponentsWithStats(returned_image)
ep = imp_tools.endPoints(returned_image)
ring_frac_label = np.setdiff1d(np.arange(1, nLabels), label_Images[ep > 0])
areas = np.array([data[i][4] for i in range(1, nLabels)])
small_labels = np.nonzero(areas < self.min_area)[0] + 1
remove_labels = np.union1d(small_labels, ring_frac_label)
if remove_labels.size > 0:
    returned_image[np.isin(label_Images, remove_labels)] = 0
return returned_image
```

### 3.7 Endpoints and branch points

`imp_tools.endPoints` and `imp_tools.branchedPoints` classify each skeleton
pixel by hit-or-miss matching (`cv2.MORPH_HITMISS`) against a fixed set of 3×3
neighbourhood patterns, in the rotation order of the original lab code. The
resulting `ep` and `bp` maps are stored in the bundle and are what downstream
tracing and the isolation test in `measure.isolated_fiber_flags` read.

The skeleton is padded by one background pixel first, so a pixel on the image
border is classified as if the scan ended there:

```python
# source: lib/imp_tools.py::_hitmiss_union, branchedPoints, endPoints
padded = np.pad(skel, pad_width=1, mode='constant', constant_values=0).astype(np.uint8)
hits = np.zeros_like(padded, dtype=np.uint8)
for p in patterns:
    hits |= cv2.morphologyEx(padded, cv2.MORPH_HITMISS, p)
return np.ascontiguousarray(np.where(hits > 0, 1, 0).astype(np.uint8)[1:-1, 1:-1])
...
return _hitmiss_union(skel, _BRANCH_PATTERNS)
...
return _hitmiss_union(skel, _END_PATTERNS)
```

---

## 4. Kink detection

**Code:** `lib/kink_detector.py` — `KinkDetector.__call__` and
`KinkDetector.kinks_on_line`, on the line built by `lib/centerline.py` (§4.2).
**Reads:** `skeleton_image`, `calibrated_image` and `bp`. **Writes:** the
per-label kink arrays, the bends left unjudged next to an end (§4.4), and
their flattened equivalents.

A kink is a **localized sharp bend** in a fiber, as opposed to smooth
curvature. Detecting one requires deciding what counts as sharp and, less
obviously, deciding at what scale to look — a bend that is sharp when the
centreline is followed pixel by pixel may be a gentle curve at fiber scale.
Here the scale is the fiber's apparent width $W$ (§4.2), which is also the
resolution the probe leaves in the image.

`KinkDetector.__call__` places each traced component's centerline and judges it;
the kinks are judged on `placed.x`, `placed.y` and stored at the skeleton pixels
of the same indices:

```python
# source: lib/kink_detector.py::KinkDetector.__call__
no_bp_skel = imp_tools.remove_bp(image.skeleton_image)
no_Lcorner_skel = imp_tools.remove_Lcorner(no_bp_skel)
nLabels, label_image, data, center = cv2.connectedComponentsWithStats(no_Lcorner_skel)
branch_points = getattr(image, "bp", None)
if branch_points is None:
    branch_points = imp_tools.branchedPoints(image.skeleton_image)
...
for label in range(1, nLabels):
    x, y, w, h, area = data[label]
    sub_label = label_image[y:y+h, x:x+w]
    target_image = (sub_label == label).astype(np.uint8)
    try:
        _xtrack_local, _ytrack_local = imp_tools.tracking(target_image)
...
    _xtrack = _xtrack_local + x
    _ytrack = _ytrack_local + y
    placed = place_centerline(
        image.calibrated_image, _xtrack, _ytrack, branch_points,
    )
...
    judged = self.judge_line(placed.x, placed.y, placed.width_px)
...
    all_kink_coordinate_x.extend(_xtrack[kink_indices])
    all_kink_coordinate_y.extend(_ytrack[kink_indices])
    all_kink_angles.extend(list(kink_angles))
    all_kink_excess.extend(list(judged.kink_excess))
    unjudged_point_x.extend(_xtrack[unjudged_indices])
    unjudged_point_y.extend(_ytrack[unjudged_indices])
```

### 4.1 Prepare traceable tracks

`imp_tools.remove_bp` clears a $(2r+1)$-square neighbourhood ($r$ =
`remove_size` = 1) around every branch point, cutting the skeleton at crossings
so that each remaining component is a single unbranched line. Components below
`min_area` = 10 px are dropped. `imp_tools.remove_Lcorner` then removes 2-pixel
L-shaped corner artefacts that would otherwise register as spurious turns.

Each connected component is traced end to end by `imp_tools.tracking`, which
walks from one endpoint to the other and returns the pixel coordinates **in
order**. A component that does not have exactly two endpoints cannot be traced;
it is logged and skipped rather than aborting the image.

In `imp_tools.remove_Lcorner` a pattern cell of 1 must be skeleton and 0 must
be background, so the removed pixel is the corner of an L whose two arms are
orthogonal neighbours; the L becomes a diagonal step. `imp_tools.tracking`
starts at the endpoint that comes first in raster order and at each step moves
to the first remaining neighbour in raster order of the 3×3 window, clearing
the pixel it leaves:

```python
# source: lib/imp_tools.py::remove_bp
bp = branchedPoints(imgcopy)
bp_coor = np.where(bp)
for bp_x, bp_y in zip(bp_coor[0], bp_coor[1]):
    imgcopy[
    max(int(bp_x) - remove_size, 0): bp_x + remove_size + 1,
    max(int(bp_y) - remove_size, 0): bp_y + remove_size + 1,
    ] = 0
if min_area != 0:
    tmp_nlabels, tmp_label_image = cv2.connectedComponents(np.uint8(imgcopy))
    sizes = np.bincount(tmp_label_image.ravel())
    small_mask = sizes < min_area
    small_mask[0] = False
    imgcopy[small_mask[tmp_label_image]] = 0
```

```python
# source: lib/imp_tools.py::remove_Lcorner
corner = np.array([[0, 1, 0],
                   [1, 1, 0],
                   [0, 0, 0]])
...
for corner_pattern in [corner, corner2, corner3, corner4]:
    h = cv2.morphologyEx(src, cv2.MORPH_HITMISS, _to_cv2_hitmiss_kernel(corner_pattern))
    hits += np.where(h > 0, 1, 0).astype(np.uint8)
Lremoved_img = imgcopy - hits
```

```python
# source: lib/imp_tools.py::tracking
ep = endPoints(imgcopy)
ep_y, ep_x = np.where(ep)
if len(ep_y) != 2:
    raise ValueError(
        "tracking requires exactly 2 endpoints; "
        f"detected {len(ep_y)} endpoint(s)"
    )
...
for i in range(np.sum(imgcopy)):
    imgcopy[y, x] = 0
    window = imgcopy[y - 1: y + 2, x - 1: x + 2]
    direction_y, direction_x = np.where(window != 0)
    if len(direction_y) == 0:
        break
    dy = int(direction_y[0]) - 1
    dx = int(direction_x[0]) - 1
    y += dy
    x += dx
    xtrack.append(x)
    ytrack.append(y)
    if x == ep_x_end and y == ep_y_end:
        break
```

This is why kink detection — and the height sampling that shares the same
tracing path — excludes the branch-point neighbourhoods: at a crossing the
height belongs to no single fiber.

### 4.2 Place the fiber's line on the height

**Code:** `lib/centerline.py` — `centerline.half_max_centerline`.

The traced skeleton decides which pixels form one fiber and in what order, but
it is a poor estimate of *where* the fiber runs. It is the medial axis of the
binarized mask, so it lies midway between two mask boundaries: where a
neighbour, a junction skirt or background roughness widens the mask on one
side, the axis follows, and the 8-connected pixel chain adds a staircase on
top. Judged on those pixels, a straight fiber that the mask happens to widen
reports a bend — below a Y junction on the bundled higher-plant TOC scan the
skeleton produced a 118° "kink" on a fiber that does not bend there.

Each skeleton point is therefore moved onto the fiber's height:

1. `centerline.measure_apparent_width` measures the fiber's apparent width
   $W$: the full width at half maximum of the height cross-sections along the
   track, as a median over the track. Every length below is a multiple of $W$,
   so the step means the same thing at any scan size.
2. A copy of the track smoothed over $W/4$ supplies, for each point, the
   direction it may move in: the normal to the fiber. No point is moved to the
   smoothed position itself, which would round real corners.
3. Along that normal, `centerline.refine_centerline` climbs from the track to
   the nearest local maximum of the height — not the brightest point in reach,
   so a brighter neighbour cannot capture the line — and places the point at
   the **midpoint of the two positions where the cross-section falls to half
   its maximum**.
4. A section that cannot locate this one fiber is marked unreliable, and its
   offset is interpolated from the reliable points around it instead of
   measured: within $W$ of a branch point, where the section is wider than
   $1.5\,W$ (two fibers side by side), where the maximum found does not belong
   to the section the track lies on, and where the section is too faint. The
   offsets are joined along the track by a first-order penalty over $W/4$.

The computation is shown step by step, with its code, in
[GUI04 fiber measurements](gui04_measurements.md) §2; kink detection calls the
same function:

```python
# source: lib/centerline.py::place_centerline
width, measured = measure_apparent_width(height, x, y, return_measured=True)
lx, ly, reliable, crest = _refine(height, x, y, width, branch_points)
return CenterlineResult(lx, ly, float(width), bool(measured), reliable, crest)
```

The result has exactly one point per skeleton point. That is what lets the
kinks judged on the line be stored at skeleton pixels in the bundle, and what
lets exclusions and connections keep referring to skeleton pixels while
everything drawn and measured uses the line.

**What placing the line also reports.** `centerline.place_centerline` returns
the line together with three things the numbers built on it depend on, as a
`centerline.CenterlineResult`:

- **$W$ and whether it was measured.** Every length of the kink rule is a
  multiple of $W$, and $W$ is the probe's broadening as much as the fiber's,
  so $W$ is the physical scale a fiber's kinks were judged at. When too few
  sections give a usable half-maximum run, `centerline.FALLBACK_WIDTH_PX`
  (8 px) is substituted; that is a pixel count, not a multiple of the fiber's
  width, so the substitution is reported rather than hidden. Each fiber
  carries its $W$ (`Fiber.width_px`, `Fiber.width_measured`) into the fiber
  table and the CSV, and the bundle records the image's median $W$ and how
  many components used the fallback (`bundle_schema.APPARENT_WIDTH_KEY`).
- **Which points were located.** A point interpolated under step 4 lies on a
  straight run, so no kink and no curvature can be found there. The per-point
  flag (`Fiber.line_reliable`) reaches the table and the CSV as the fraction
  of the line that was actually located on the fiber.
- **The crest height.** The fiber's height at each point is the **maximum of
  its cross-section** (`CenterlineResult.crest`), not the image interpolated
  at the line: the line sits at the half-maximum midpoint, which on an
  asymmetric section lies beside the top rather than on it, and bilinear
  interpolation cannot reach a peak that falls between pixel centres. Where
  the section could not be resolved, the maximum within $W/4$ of the
  interpolated point is used instead. `Fiber.height`, the height profile, and
  every height statistic read this crest.

**Why a quarter width.** The smoothing sets how close two features may lie
before the line averages them into one. At half a width the line rounded
corners that lie close together: on synthetic scans with known corners (2 nm
pixels, $W$ = 8 px) the kink rule of §4.3 judged two same-sense 60° corners a
few widths apart as one bend in 2 of 16 cases, and the median distance from a
corner vertex to the line was 1.10–1.51 px. At a quarter width no pair was
merged and that distance fell to 0.77–1.21 px, while the median distance to
the true centerline stayed at 0.11 px.

**Why the half-maximum midpoint.** The obvious alternative, the crest of each
cross-section, is the estimator a twisted fibril displaces most: a fibril with
an anisotropic cross-section turns its tallest edge to alternating sides as it
twists. On synthetic twisted ribbons (rectangular sections of 4×2 to 16×3 nm
on a straight axis) the crest left the axis 1.2–1.8 times as far as the
half-maximum midpoint, and the kink rule of §4.3 reported no kink on any of six
such ribbons. A quarter-height midpoint sat closer to the axis on the ribbons
but was pulled up to 3.8 nm off a thin, low fiber by background bumps that the
half-maximum level stays above. With a blunt probe the displacement of a
twisted fibril is in the image itself, and no line read from the height can
remove it.

Against the analytic centerlines of 60 synthetic scans rendered with a
spherical probe (2 nm pixels, $W$ = 8 px; corners, zigzags, corner pairs,
arcs, meanders, crossings and junctions), the median distance to the true
centerline is 0.11 px for this line and 0.29 px for the skeleton, and the 95th
percentile 0.35 px and 0.90 px. Contour length measured along the line lies
within −1.5 to +0.5 % of the true length in every group of those scans,
against −1.4 to +2.5 % for the skeleton's corrected chain-code length.

The same function builds the line in GUI01, where kinks are judged, and again
when a bundle is opened (`fiber_tracking_image.FiberTrackingImage`), so the
kinks shown and the line they sit on come from one computation. A bundle of
format 1.0 was judged on the skeleton and is rebuilt on its skeleton track
(`bundle_schema.centerline_from_meta`) until it is re-analyzed.

### 4.3 Judge each bend by its excess turning

**Code:** `KinkDetector.judge_line` (`KinkDetector.kinks_on_line` is its tuple
form).

The rule works on the heading of the line, $\theta(s)$, resampled every 0.5 px
of arc length $s$ and smoothed with a Gaussian of $\sigma = W/4$
(`kink_detector._heading_profile`). At a position $p$ it compares the turning
inside a window with the fiber's own turning just outside it:

$$
T(p) = \theta(p + c) - \theta(p - c), \qquad c = 0.75\,W
$$

$$
r_{\text{L}} = \frac{\theta(p - c) - \theta(p - c - f)}{f}, \qquad
r_{\text{R}} = \frac{\theta(p + c + f) - \theta(p + c)}{f}, \qquad f = W
$$

$$
E(p) = |T(p)| - 2c \, \max\bigl(0,\ \min(\sigma_T r_{\text{L}},\ \sigma_T r_{\text{R}})\bigr),
\qquad \sigma_T = \operatorname{sgn} T(p)
$$

$E$ is the **excess turning**: what the window turns beyond the rate at which
the fiber was already turning beside it. A bend is a kink when

$$
E \ge 180^\circ - \theta_{\text{max}}
$$

with $\theta_{\text{max}}$ = `kinkangle_deg`, default 150°, so the default asks
for 30° of excess turning. The threshold is written as an interior angle so that
`kinkangle_deg` keeps the meaning it had under the earlier rule; `pipeline.build_stages`
converts it to radians for the detector. The angle *stored* for a kink is
measured separately, from its arms (see *The angle it reports* below).

In the code, the heading is resampled, differenced and smoothed by
`_heading_profile`, and `excess_profile` evaluates $T$ and $E$ at any position.
Near an end the flank interval is clipped to the line but still divided by $f$.
A position $p$ is accepted only when it lies at least $c$ from both ends,
$|T(p)|$ reaches the threshold, and $E(p)$ reaches both the threshold and the
noise floor (which is 0 while `NOISE_SIGMAS` is 0). The threshold is
$\pi - \theta_{\text{max}}$ in radians (`turn_threshold`):

```python
# source: lib/kink_detector.py::_CORE_WIDTHS, _FLANK_WIDTHS, _HEADING_SIGMA_WIDTHS
_CORE_WIDTHS = 0.75
_FLANK_WIDTHS = 1.0
_HEADING_SIGMA_WIDTHS = 0.25
```

```python
# source: lib/kink_detector.py::_heading_profile
seg = np.hypot(np.diff(x), np.diff(y))
keep = np.concatenate([[True], seg > 1e-9])
orig = np.nonzero(keep)[0]
x, y = x[keep], y[keep]
if x.size < 2:
    return None
s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
length = float(s[-1])
su = np.arange(0.0, length + 1e-9, _HEADING_STEP_PX)
if su.size < 2:
    return None
xu = np.interp(su, s, x)
yu = np.interp(su, s, y)
theta = np.unwrap(np.arctan2(np.diff(yu), np.diff(xu)))
sm = su[:-1] + 0.5 * _HEADING_STEP_PX
heading = _smooth_extrapolated(
    theta, _HEADING_SIGMA_WIDTHS * width / _HEADING_STEP_PX,
)
return orig, s, length, sm, heading
```

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
width = float(width_px)
c = _CORE_WIDTHS * width
f = _FLANK_WIDTHS * width
profile = _heading_profile(x, y, width)
...
turn_threshold = max(np.pi - float(self.threshold_angle_from_decomposed_indices), 0.0)
curvature = np.abs(np.gradient(heading, _HEADING_STEP_PX))
curvature_floor = _CURVATURE_FLOOR_FRAC * turn_threshold / (2.0 * c)
radius = _SUPPRESS_WIDTHS * width
def excess_profile(p: NDArray) -> Tuple[NDArray, NDArray]:
    core = np.interp(p + c, sm, heading) - np.interp(p - c, sm, heading)
    sense = np.sign(core)
    left = (np.interp(p - c, sm, heading)
            - np.interp(np.maximum(sm[0], p - c - f), sm, heading)) / f
    right = (np.interp(np.minimum(sm[-1], p + c + f), sm, heading)
             - np.interp(p + c, sm, heading)) / f
    background = np.maximum(0.0, np.minimum(sense * left, sense * right))
    return core, np.abs(core) - 2.0 * c * background
grid = sm[(sm >= c) & (sm <= length - c)]
...
def excess_at(p: float) -> Optional[float]:
    if p < c or p > length - c:
        return None
    core, excess = excess_profile(np.array([p]))
    if abs(float(core[0])) < turn_threshold:
        return None
    excess = float(excess[0])
    return excess if excess >= max(turn_threshold, floor) else None
```

**Why the excess and not the turning.** The window's turning alone reports
curvature as well as kinks: an arc of radius $3\,W$ already turns 29° across
$1.5\,W$. An arc turns at the same rate inside the window and on both flanks, so
its excess is near zero, while a corner between straight arms keeps all of its
turning. The *smaller* of the two flank rates is used because a corner where a
curve ends has one curved flank and one straight one, and it is still a corner.
A flank that turns the other way — the second bend of a jog — contributes no
background at all.

**Candidates.** $E$ is evaluated at the maxima of the curvature
$|d\theta/ds|$ that reach half the mean curvature a bend exactly at the
threshold has across the window. A corner whose curvature peak noise splits in
two, or whose turning runs straight into a curve, has no single curvature
maximum at its centre, so the maxima of $|T|$ itself are added wherever no
curvature maximum passed within $0.75\,W$; on the bundled scans two visible
corners were missed without them. Candidates closer than $0.75\,W$ are one
bend, and the one with the larger excess is kept.

The curvature floor is
$0.5 \times (\pi - \theta_{\text{max}}) / (2c)$ (`_CURVATURE_FLOOR_FRAC` = 0.5),
the $|T|$ maxima are searched on the samples at least $c$ from both ends
(`grid`), and the suppression keeps candidates in decreasing order of excess:

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
fine: List[Tuple[float, float]] = []
for i in range(1, curvature.size - 1):
    if (curvature[i] >= curvature[i - 1] and curvature[i] > curvature[i + 1]
            and curvature[i] >= curvature_floor):
        excess = excess_at(float(sm[i]))
        if excess is not None:
            fine.append((excess, float(sm[i])))
coarse: List[Tuple[float, float]] = []
if grid.size >= 3:
    window_turn = np.abs(np.interp(grid + c, sm, heading)
                         - np.interp(grid - c, sm, heading))
    for i in range(1, grid.size - 1):
        if (window_turn[i] >= window_turn[i - 1]
                and window_turn[i] > window_turn[i + 1]
                and window_turn[i] >= turn_threshold):
            p = float(grid[i])
            excess = excess_at(p)
            if excess is not None and all(abs(p - q) > radius for _, q in fine):
                coarse.append((excess, p))
kept: List[Tuple[float, float]] = []
for excess, p in sorted(fine + coarse, key=lambda t: -t[0]):
    if all(abs(p - q) > radius for _, q in kept):
        kept.append((excess, p))
```

**Scale.** Every length in the rule is a multiple of $W$, which is also the
resolution of the image: the probe spreads each fiber over about $W$, so a
corner occupies about $W$ of the line however sharply the fiber turned, and two
bends much closer than that cannot be told apart. On synthetic zigzags (2 nm
pixels, $W$ = 8 px) corners 1.5–3 $W$ apart were all found (30 of 30), and
corners 1 $W$ apart only 4 of 10. Nothing in the rule is a pixel count, so the
same fibers scanned at another pixel size give the same kinks;
`kink_decompose_px` is no longer used (§4.6).

**What it reports, and how well.** Against a reference marked by eye on the
height images of the bundled scans, with no detector output on screen (64 clear
kinks over five scans), the rule found 60, placed 1 between one and two widths
from its mark, missed 3, and reported 60 further bends that match no marked
kink; the polyline rule it replaces, on the skeleton track, found 53, displaced
5, missed 6 and reported 79. On synthetic scans it reported no bend on straight
fibers, arcs of radius 3–10 $W$, crossings, junctions or twisted ribbons, and
found every isolated corner of 40° or more. It reported 12 bends on sine
meanders whose tightest radius is 1.6–1.8 $W$: below a radius of about
$2.9\,W$ the window alone turns more than 30°, and where the curvature changes
quickly the flanks do not account for it. The polyline rule reported 31 on the
same arcs and meanders. Changing any one length of the rule to a neighbouring
value ($c$ = 0.6 or 0.9 $W$, $f$ = 0.75 or 1.5 $W$, the heading smoothing 0.15
or 0.35 $W$, the end margin of §4.4 1.0 or 2.0 $W$, the suppression radius 0.5
or 1.0 $W$) kept the clear kinks found between 59 and 62.

**The angle it reports.** The excess is the quantity tested, and it reads low
on sharp corners because the probe and the line round the apex: isolated
synthetic corners turning 40°, 60°, 90° and 120° read 37–38°, 52–56°, 83–84°
and 101–110° of excess. A bend just above the threshold can therefore fall
below it; the bend drawn at 33.5° in the test suite reads 28.7°. The angle
*stored* (`ka`) is therefore not 180° minus the excess but the interior angle
between the two **arms** beside the bend
(`KinkDetector.judge_line`): each arm's direction is the mean heading over one
width starting half a width beyond the apex, outside the rounding, and cut
short at the next bend so a jog's second corner does not enter the first
corner's arm. On synthetic corners of 120°, 140° and 145° interior angle
rendered with a 10 nm probe (`scripts/kink_rule_sweep.py`), the median error
of the arm angle was 1.9° at an apparent width of 5.5 px and 1.1° at 11 px,
against 7.5° and 2.5° for 180° minus the excess. The excess is stored beside
the angle as `ke` (§4.5), so what was tested and what the geometry is both
travel with the bundle.

**How the arm angle is computed.** For a bend at arc position $p$ on a line of
length $L$, with $g = 0.5\,W$ (`_ARM_GAP_WIDTHS`) and $a = 1.0\,W$
(`_ARM_LENGTH_WIDTHS`), the two arms are the arc intervals

$$
A_{\text{L}} = \bigl[\max(s_0,\ p - g - a,\ p_{\text{prev}} + g),\ p - g\bigr],
\qquad
A_{\text{R}} = \bigl[p + g,\ \min(s_1,\ p + g + a,\ p_{\text{next}} - g)\bigr]
$$

where $s_0$ and $s_1$ are the positions of the first and last heading samples
(0.25 px from the start, and 0.25–0.75 px from the end), and $p_{\text{prev}}$ and $p_{\text{next}}$ are the nearest other
bends kept on the line — judged or not — and are left out when there is none.
Each arm's direction $\bar\theta$ is the mean of the smoothed heading sampled at
16 evenly spaced points of its interval, and the interior angle is

$$
\phi = \max\bigl(0,\ \pi - |\bar\theta_{\text{R}} - \bar\theta_{\text{L}}|\bigr)
$$

When either interval is shorter than $0.25\,W$ (`_ARM_MIN_WIDTHS`) — two bends
too close together to leave an arm between them — $\phi = \pi - E$ is stored
instead. The angle is then clipped to $[10^{-6},\ \pi - 10^{-6}]$ rad and
written to `ka` in radians, at the line point nearest to $p$ in arc length; when
two bends fall on the same point, the one with the larger excess is kept. The
angle does not decide whether a bend is a kink — $E$ does — so a stored angle is
not guaranteed to lie at or below `kinkangle_deg`.

`measure.compute_fiber_stats` converts the angles to degrees
(`FiberStats.kink_angles_deg`), which is what the fiber CSV holds, and
`measure.fiber_kink_angle` takes their median as the one value per fiber that
GUI03 histograms:

```python
# source: lib/kink_detector.py::_ARM_GAP_WIDTHS, _ARM_LENGTH_WIDTHS, _ARM_MIN_WIDTHS
_ARM_GAP_WIDTHS = 0.5
_ARM_LENGTH_WIDTHS = 1.0
_ARM_MIN_WIDTHS = 0.25
```

```python
# source: lib/kink_detector.py::_arm_interior_angle
gap = _ARM_GAP_WIDTHS * width
arm = _ARM_LENGTH_WIDTHS * width
left_lo = max(float(sm[0]), p - gap - arm)
if prev_bend is not None:
    left_lo = max(left_lo, prev_bend + gap)
left_hi = p - gap
right_lo = p + gap
right_hi = min(float(sm[-1]), p + gap + arm)
if next_bend is not None:
    right_hi = min(right_hi, next_bend - gap)
shortest = _ARM_MIN_WIDTHS * width
if left_hi - left_lo < shortest or right_hi - right_lo < shortest:
    return float("nan")
def mean_heading(lo: float, hi: float) -> float:
    return float(np.mean(np.interp(np.linspace(lo, hi, 16), sm, heading)))
turn = abs(mean_heading(right_lo, right_hi) - mean_heading(left_lo, left_hi))
return max(np.pi - turn, 0.0)
```

```python
# source: lib/kink_detector.py::KinkDetector.judge_line
margin = END_MARGIN_WIDTHS * width
positions = sorted(q for _, q in kept)
...
for excess, p in kept:
    index = int(orig[int(np.argmin(np.abs(s - p)))])
    if index in taken:
        continue
    taken.add(index)
    if margin <= p <= length - margin:
        before = [q for q in positions if q < p]
        after = [q for q in positions if q > p]
        angle = _arm_interior_angle(
            sm, heading, p, width,
            max(before) if before else None,
            min(after) if after else None,
        )
        if not np.isfinite(angle):
            angle = np.pi - excess
        kinks.append((index, angle, excess))
    else:
        unjudged.append(index)
kinks.sort()
kink_indices = np.array([k for k, _, _ in kinks], dtype=np.intp)
kink_angles = np.clip(
    np.array([a for _, a, _ in kinks], dtype=np.float64),
    _MIN_INTERIOR_ANGLE, np.pi - _MIN_INTERIOR_ANGLE,
)
kink_excess = np.array([e for _, _, e in kinks], dtype=np.float64)
```

```python
# source: lib/measure.py::compute_fiber_stats
angles = tuple(float(np.degrees(a)) for a in f.kink_angles)
```

```python
# source: lib/measure.py::fiber_kink_angle
if not stat.kink_angles_deg:
    return float("nan")
return float(np.median(stat.kink_angles_deg))
```

**Significance against the line's own noise.** A per-line noise floor is
implemented (`NOISE_SIGMAS`, `KinkJudgement.noise_excess`): the robust scale
of the excess along the whole line, which a bend's excess would have to exceed
by that factor. It ships **off**, because it did not separate the false
detections from the real kinks. Scored against the visual reference
(`scripts/kink_reference_score.py`), a factor of 3 found 3 fewer clear kinks
for 6 fewer false detections, and a factor of 4 found 5 fewer for 10 fewer:
the false detections on these scans are rounded bends, tangles and bends of
25–40°, not noise, and a heavily bent fiber's own kinks raise its floor, which
is where the lost clear kinks lay. On the synthetic sweep the floor changed
nothing except at the finest pixel size with the heaviest noise (11 px width,
0.30 nm pixel noise), where it cut false positives from 3.9 to 3.1 per µm
without recovering the recall those conditions had already lost.

**Where the rule applies.** The same sweep says at what width the rule works.
With an apparent width of 3 px or more every synthetic 120° and 145° corner
was found (140°: 4 of 6 at 3 px, all at 5.5 px and above), with no false
positive on straight fibers, arcs or meanders at pixel noise up to 0.15 nm and
none on a 165° bend. On a fiber only 2 px wide the width itself could not be
measured, the fallback applied, and nothing was found: below about 3 px the
image no longer resolves the fiber's bends, and the answer is a finer pixel
size, not a looser rule.

### 4.4 Bends next to an end are shown, not judged

A bend whose centre lies within $1.5\,W$ of an end of the line is **not
judged**. One of its arms is then shorter than the visual reference required
before it called a bend clear, and many track ends are not fiber ends at all
but cuts at a crossing — measured on the bundled scans, 46–68 % of track ends
lie within 3 px of a branch point — where the line bends with the junction's
skirt.

Such a bend is not dropped silently. `KinkDetector.kinks_on_line` returns it
separately, the bundle stores it in the optional key `up`, it reaches each
fiber as `Fiber.unjudged_indices`, and GUI04 draws it as a grey hollow circle,
so "not judged" stays distinguishable from "measured and below the threshold".
It is never counted: kink counts, densities, angles and the CSV hold judged
kinks only. Once a reconnected fibril bridges the cut, the bend is no longer
next to an end, and it is judged, because the connector and
`fiber_connector.filter_fibers_by_height` rebuild their fibers through the same
rule.

At a margin of $1.0\,W$ the false detections on the bundled scans rose from 60
to 75 without a further clear kink being found; at $2.0\,W$ they fell to 47,
but synthetic corners 1.5–2 $W$ from an end were no longer judged. None of the
49 bends left unjudged on the bundled scans lay on a clear reference kink.

### 4.5 The threshold travels with the results

The kink parameters are written into the bundle's `params` metadata, and
`bundle_schema.kink_params_from_meta` reads them back. `kinkangle_deg` is the
analysis field a reader *acts* on, and it has to be: anything that recomputes
kinks on a track the bundle does not contain — a fiber reconnected across a
crossing, a height-band sub-fiber — must apply the same rule that produced the
stored kink points, and the bundle is the only place that rule travels together
with the arrays it explains. `kink_decompose_px` is read back too, but only a
bundle of format 1.0 uses it (§4.6).

They are deliberately **not** read from the `_param.json` sidecar. That file is
the analysis *input* and stays editable afterwards, so reading it would let an
edit change a reconnected fiber's kinks with no re-analysis.

The bundle also stores, beside each kink's angle `ka`, the excess turning it
was judged by (`ke`, `KinkJudgement.kink_excess`). The angle is the geometry
of the bend and the excess is the quantity the rule tested; keeping both means
a kink can be audited against the threshold without re-running the rule.

### 4.6 Bundles judged by the earlier rule

Bundles of format 1.0 were judged by an earlier rule, on the skeleton track.
`KinkDetector._binary_decompose_simple` reduced the track to a polyline by the
**Douglas–Peucker** idea, inserting a vertex wherever a track point lay at
least `kink_decompose_px` (default 3.0 px) from its chord, and
`KinkDetector._detect_kink_from_decomposed_indices` kept a vertex whose
interior angle $\theta$ was at most `kinkangle_deg` and whose distance below
straight exceeded the error bar a vertex tolerance $d$ puts on arms of length
$A$:

$$
\pi - \theta > \frac{2d}{\min(A_{\text{prev}},\, A_{\text{next}})}
$$

That rule had no scale beyond a pixel tolerance, so it split smooth arcs into
vertices and reported them as kinks, and it judged the skeleton, whose
staircase and swings at wide spots are bends the fiber does not have. A 1.0
bundle keeps its skeleton track and stored kinks until it is re-analyzed
(`bundle_schema.centerline_from_meta`), and a fibril reconnected in it is judged
by that rule (`KinkDetector.kinks_and_decomposed_from_track`), so one image
never carries kinks from two rules.

In the code, the polyline starts as the two end points and repeatedly gains
the track point farthest from one of its chords until every point lies within
`threshold_distance` (`kink_decompose_px`); the angle at each interior vertex is
then tested:

```python
# source: lib/kink_detector.py::KinkDetector._binary_decompose_simple
decomposed_indices = [0, n_pts - 1]
updated = True
while updated:
    updated = False
    for n, (i, j) in enumerate(zip(decomposed_indices[:-1], decomposed_indices[1:])):
        if j - i < 2:
            continue
        ax = cx[i]; ay = cy[i]
        bx = cx[j]; by = cy[j]
        abx = bx - ax
        aby = by - ay
        length_ab = (abx * abx + aby * aby) ** 0.5
        if length_ab == 0.0:
            continue
        xs = cx[i + 1:j]
        ys = cy[i + 1:j]
        dist = np.abs(abx * (ys - ay) - aby * (xs - ax)) / length_ab
        k = int(dist.argmax())
        farthest_distance = dist[k]
        if farthest_distance == 0:
            continue
        elif farthest_distance >= threshold_distance:
            added_indices = [k + i + 1]
            decomposed_indices = decomposed_indices[:n + 1] + added_indices + decomposed_indices[n + 1:]
            updated = True
            break
```

```python
# source: lib/kink_detector.py::KinkDetector._detect_kink_from_decomposed_indices
v1x = cx[prev_idx] - cx[mid_idx]
v1y = cy[prev_idx] - cy[mid_idx]
v2x = cx[next_idx] - cx[mid_idx]
v2y = cy[next_idx] - cy[mid_idx]
dot = v1x * v2x + v1y * v2y
norm1 = np.sqrt(v1x ** 2 + v1y ** 2)
norm2 = np.sqrt(v2x ** 2 + v2y ** 2)
angles = np.arccos(dot / (norm1 * norm2))
mask = angles <= threshold_angle
arm = np.minimum(norm1, norm2)
with np.errstate(divide="ignore", invalid="ignore"):
    angular_error = np.where(arm > 0.0,
                             2.0 * self.threshold_distance / arm,
                             np.inf)
mask &= (np.pi - angles) > angular_error
return mid_idx[mask], angles[mask]
```

---

## 5. What these stages deliberately do not do

Everything above produces arrays. Turning arrays into numbers happens
elsewhere, and keeping the boundary sharp is what lets a measurement be redone
without re-analysing an image:

- **Per-fiber measurement** — contour length, height statistics, straightness,
  curvature, kink density — lives in `lib/measure.py`, shared by GUI03, GUI04,
  and `cli.py measure`. It reads every fiber along the line of §4.2, which
  `fiber_tracking_image.FiberTrackingImage` rebuilds from the stored skeleton
  and heights when a bundle is opened. Two of its definitions follow from the
  stages above rather than from the line alone. Height statistics are taken
  over the crest heights of §4.2, leaving out the last $W$ at an end that is a
  cut rather than a fiber end (`measure.height_sample_mask`): §4.1 clears only
  a 3×3 neighbourhood around a branch point, while the other fiber's skirt at
  a crossing extends about a width past it, so those samples are partly the
  other fiber's height — the median barely notices, the maximum reads the
  crossing. Bridges the fiber connector interpolates are left out for the
  same reason. And kink density (`measure.fiber_kink_density`) divides by the
  **judged** length, the contour less $1.5\,W$ at each end, because §4.4
  judges nothing closer to an end than that; dividing by the whole contour
  read low, and more so on a dense specimen, where most ends are cuts and the
  fragments are short.
- **Reconnecting fragments** split at crossings lives in
  `lib/fiber_connector.py`, and only GUI04 runs the search; other readers apply
  the chains that search recorded.
- **Manual exclusions** live in `lib/fiber_selection.py`.
- **The pixel size** enters only at measurement time. Every stage above is
  pixel-based, which is why a stage parameter means the same thing regardless
  of whether the scan size was recorded. The other side of that choice is that
  the same parameter file acts at a different physical scale on every scan
  size — a 12 px spur limit prunes about 23 nm on a 2 µm scan and about
  117 nm on a 10 µm one — so when the scan size is known the bundle records
  what each pixel setting amounted to in nanometres
  (`bundle_schema.PIXEL_LENGTHS_KEY`, from `pipeline.pixel_lengths_nm`) and
  GUI01 logs it, which is what makes two bundles comparable on that point.

## 6. Reproducing a result

Three artefacts together pin down any number this software reports:

| Artefact | Records |
|---|---|
| `<stem>_param.json` | Every `ProcParams` field the analysis ran with. Field names are frozen, so an old file still loads. |
| `<stem>.b2z` | The stage output arrays, the bundle format version, the scan size and its source, which scan lines were analysed, and the parameters as provenance. |
| The software version | Recorded in the bundle. `CHANGELOG.md` states explicitly whenever a change moves the numbers. |

A change that alters analysis output is treated as a reproducibility break and
is called out in `CHANGELOG.md` under the version that introduced it, whether
or not any API changed.
