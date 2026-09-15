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

### 1.3 `trendfill` — the default method

Named for what it does: subtract the trend, fill the holes. It was called
`inpaint` up to version 1.0.0, when the fill was OpenCV Navier–Stokes
inpainting; `bg_calibrator.BG_METHOD_ALIASES` still translates the old spelling
so a stored parameter file keeps running.

#### Step 1 — Find the fiber pixels from gradient statistics

`BGCalibrator._detect_fiber_mask` runs four helpers in sequence.

`_difXY` takes first differences along each axis, $\Delta_x$ and $\Delta_y$.
Large absolute differences mark edges, which on this specimen means fiber
flanks.

`_bg_fit` histograms each difference image into 150 bins and fits a **Gaussian
plus a linear baseline** with `lmfit`. The Gaussian is the *background*
population: the noise of the substrate, centred near zero. The fiber flanks
live in the tails. X and Y are fitted independently because the AFM slow-scan
axis has different noise characteristics and typically a broader $\sigma$.

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

#### Step 3 — Fill, smooth, subtract

The masked pixels are filled from their **nearest background-candidate pixel**,
found with `scipy.ndimage.distance_transform_edt`. Because a background pixel's
nearest background pixel is itself, this preserves the real data exactly and
needs no explicit restore step.

The filled surface is smoothed with a Savitzky–Golay filter (`savgol_window`
default 31, `savgol_polyorder` default 1), the trend is added back, and
`_bg_calibrate` subtracts the result from the original.

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

Line ends are deliberately **not extrapolated**. Beyond a line's first or last
valid sample there is background data on one side only, so any 1-D model of
that run is fitted to that single line and its error is uncorrelated with its
neighbours. This is what made the historical `pandas` implementation fail
(constant padding, visible as streaks), and a fitted spline's own extrapolation
fails the same way, only as smooth bands instead of thin streaks. Those runs
are filled from the nearest background pixel in 2-D instead, which draws on the
neighbouring lines.

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

### 2.2 Area filter

`_remove_small_fragments` drops 8-connected components with area
$\le$ `area_min` (default 100 px²) and then applies a 3×3 median blur, which
removes isolated single pixels and smooths ragged component edges.

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

### 3.2 Height-gated branch pruning

This is the only cleanup step that uses height rather than geometry.

`set_low_bp_coor` splits the skeleton's branch points into **low** and **high**
by comparing the calibrated height against `bp_height` (default 10 nm). A
branch point sitting at fiber height is where two real fibers cross; one
sitting near the substrate is where the mask sprouted something spurious.

`get_close_eps` then finds endpoints within `branch_length` px (default 12) of
a low branch point — only those can plausibly be short spurious branches.

`track_branches` walks the skeleton from each such endpoint, up to
`branch_length` steps. The arm is **pruned** if the walk reaches a low branch
point, or dead-ends without reaching any branch point (an isolated short
fragment). It is **kept** if the walk touches a high branch point or exhausts
the step budget, because neither confirms a short low branch.

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

### 3.6 Remove small and ring components

`remove_small_and_ring` drops components below `min_area` (default 10 px) and
components with **no endpoints at all**. An endpoint-free component is a closed
ring, which no fiber tracing can traverse.

### 3.7 Endpoints and branch points

`imp_tools.endPoints` and `imp_tools.branchedPoints` classify each skeleton
pixel by hit-or-miss matching (`cv2.MORPH_HITMISS`) against a fixed set of 3×3
neighbourhood patterns, in the rotation order of the original lab code. The
resulting `ep` and `bp` maps are stored in the bundle and are what downstream
tracing and the isolation test in `measure.isolated_fiber_flags` read.

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

The result has exactly one point per skeleton point. That is what lets the
kinks judged on the line be stored at skeleton pixels in the bundle, and what
lets exclusions and connections keep referring to skeleton pixels while
everything drawn and measured uses the line.

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

**Code:** `KinkDetector.kinks_on_line`.

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
for 30° of excess turning. The kink's angle is stored as the interior angle
$180^\circ - E$, in radians, so `kinkangle_deg` keeps its meaning: a bend at or
below that interior angle is a kink.

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

The reported angle is the **excess**, not the whole turning, and it reads low on
sharp corners because the probe and the line round them: isolated synthetic
corners of 40°, 60°, 90° and 120° read 37–38°, 52–56°, 83–84° and 101–110°. A
bend just above the threshold can therefore fall below it; the bend drawn at
33.5° in the test suite reads 28.7°.

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

---

## 5. What these stages deliberately do not do

Everything above produces arrays. Turning arrays into numbers happens
elsewhere, and keeping the boundary sharp is what lets a measurement be redone
without re-analysing an image:

- **Per-fiber measurement** — contour length, height statistics, straightness,
  curvature, kink density — lives in `lib/measure.py`, shared by GUI03, GUI04,
  and `cli.py measure`. It reads every fiber along the line of §4.2, which
  `fiber_tracking_image.FiberTrackingImage` rebuilds from the stored skeleton
  and heights when a bundle is opened.
- **Reconnecting fragments** split at crossings lives in
  `lib/fiber_connector.py`, and only GUI04 runs the search; other readers apply
  the chains that search recorded.
- **Manual exclusions** live in `lib/fiber_selection.py`.
- **The pixel size** enters only at measurement time. Every stage above is
  pixel-based, which is why a stage parameter means the same thing regardless
  of whether the scan size was recorded.

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
