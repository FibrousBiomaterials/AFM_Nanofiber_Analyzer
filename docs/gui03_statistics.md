# GUI03 statistics

This page explains the statistics GUI03 (`guis/GUI03_Fiber_Morphology_Statistics.py`)
computes from the fibers it measures: what one sample is, how the summary
statistics and the figures are computed, how contour lengths cut by the image
frame are treated, and how two groups are compared. It quotes the code that does
each step and names the published method each step follows, so a reader can
check a number in a results table against the computation that produced it and
find the original description of the method. The works cited by author and year
are listed under *References* at the end.

The measured quantities themselves — the height, contour length, straightness,
curvature and kink count of one fiber — are computed by `afm_nanofiber_analyzer.measure`,
the same code that fills GUI04's fiber table, and are explained in
[GUI04 fiber measurements](gui04_measurements.md) §3. This page starts from the
per-fiber values. Results of these methods on particular data are in
[Evaluation on particular data](validation.md).

## How to read the code excerpts

Every code block starts with a header naming where it comes from:

```text
# source: afm_nanofiber_analyzer/group_compare.py::compare_groups
```

That is the file and the function, method (`Class.method`), or module constant
the code belongs to. A header may list several constants of one file, separated
by commas. A line holding only `...` marks omitted code. Comments and blank rows
are left out of the excerpts, and method bodies are shown without their
indentation. To read the code with its comments, open the named symbol.

`scripts/check_gui03_docs.py` checks every excerpt, line for line, against the
symbol it names, and fingerprints each quoted symbol with comments and
docstrings removed. A change to what one of them computes fails the check until
this page has been reread and the fingerprints refreshed (see §5).

## Conventions

| Term | Meaning |
|---|---|
| Group | The bundles registered under one name in GUI03's list. A group stands for one specimen, and its bundles are measured and aggregated together. |
| Aggregation unit | What one sample is: `pixel` (one skeleton pixel), `fiber` (one fiber), or `image` (one bundle). |
| Sample | One value in a group's distribution, at the chosen aggregation unit. |
| Weight | A number attached to a sample by the frame correction of contour length (§3). Samples carry no weight otherwise. |

The names of the quantities, units and frame modes (`contour length`, `fiber`,
`Miles-Lantuejoul`, ...) are fixed English keys that GUI03 shows as they are,
so this page writes them in the same form.

## 1. What one sample is

### 1.1 The units each quantity offers

Each quantity lists the aggregation units GUI03 offers for it; the first is the
default.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::PARAM_SPECS
PARAM_SPECS = {
PARAM_HEIGHT: {
"slug": "height",
"value_unit": "nm",
"axis_label": "height (nm)",
"units": (UNIT_PIXEL, UNIT_FIBER, UNIT_IMAGE),
...
PARAM_LENGTH: {
"slug": "contour_length",
"value_unit": "nm",
"axis_label": "contour length (nm)",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "straightness",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "curvature (rad/" + UNIT_MICROMETER + ")",
"units": (UNIT_FIBER, UNIT_IMAGE),
...
"axis_label": "kink density (" + UNIT_PER_MICROMETER_PLOT + ")",
...
"units": (UNIT_IMAGE,),
```

Only height can be pooled per skeleton pixel (§1.4). Kink density is offered per
image only (§1.3).

### 1.2 One value per fiber

At the `fiber` unit every fiber contributes at most one sample, whatever its
length, so a long fiber weighs no more than a short one.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_fiber_value
def _fiber_value(stat, param: str):
if param == PARAM_HEIGHT:
value = float(stat.height_median_nm)
return None if not np.isfinite(value) else value
if param == PARAM_LENGTH:
return float(stat.length_nm)
if param == PARAM_STRAIGHTNESS:
value = float(stat.straightness)
return None if not np.isfinite(value) else value
return None
```

A fiber's height is the median of the height samples along its centerline
(`FiberStats.height_median_nm`, see [GUI04 fiber measurements](gui04_measurements.md)
§3.3–§3.4). A fiber whose height or straightness is undefined (NaN) contributes
no sample rather than a zero. Curvature is collected separately
(`measure.collect_fiber_curvature`), one value per fiber; a fiber shorter than
the curvature window has no value and contributes none (GUI03 logs how many).

### 1.3 One value per image

At the `image` unit each bundle contributes one sample: the median of the
values its fibers contribute, so a scan with many fibers does not outweigh a
sparse scan of the same specimen.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._values_from_fiber_stats
def pooled(source_values, source_weights) -> float:
if frame_weighted:
return _summary_stats(
np.asarray(source_values, dtype=float),
np.asarray(source_weights, dtype=float),
)["median"]
return float(np.median(source_values))
...
for _path, stats in per_source:
if param == PARAM_KINK_DENSITY and unit == UNIT_IMAGE:
kinks, judged_um, used = _kink_totals(stats)
if used == 0:
continue
n_fibers += used
n_images += 1
values.append(kinks / judged_um)
continue
...
if not source_values:
continue
n_images += 1
if unit == UNIT_IMAGE:
values.append(pooled(source_values, source_weights))
else:
values.extend(source_values)
if weights is not None:
weights.extend(source_weights)
```

When the lengths carry the Miles-Lantuéjoul weight (§3.2), the image's value is
the weighted median of §2.1, and the image sample itself carries no weight.
Curvature follows the same rule, one median per bundle:

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._curvature_values
for _path, curvature in per_fiber:
measurable = curvature[np.isfinite(curvature)]
if measurable.size == 0:
continue
n_fibers += int(measurable.size)
n_images += 1
if unit == UNIT_IMAGE:
values.append(float(np.median(measurable)))
else:
values.extend(measurable.tolist())
```

**Kink density** is the one quantity whose image value is not a median. The
kinks of every fiber in the image are added up and divided by the sum of the
fibers' judged lengths:

$$\rho_\text{image} = \frac{\sum_f k_f}{\sum_f L_f}$$

where $k_f$ is the kink count of fiber $f$ and $L_f$ its judged length in µm
(`measure.fiber_judged_length_um`, [GUI04 fiber measurements](gui04_measurements.md)
§3.9). A fiber without a judged length is left out of both sums.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kink_totals
def _kink_totals(stats) -> tuple:
kinks = 0
judged_um = 0.0
n_fibers = 0
for stat in stats:
length_um = fiber_judged_length_um(stat)
if not np.isfinite(length_um):
continue
kinks += int(stat.kink_count)
judged_um += length_um
n_fibers += 1
return kinks, judged_um, n_fibers
```

The reason, as the code states it: one fiber's density can only take the values
$0, 1/L, 2/L, \dots$ of its own judged length $L$, so a distribution of per-fiber
densities is shaped by the fragment lengths, and when more than half of an
image's fibers carry no kink the median of their densities is 0 whatever the
kinked fibers do. The pooled ratio counts every fiber in proportion to the
length it was judged over. This is why kink density offers the `image` unit
only.

### 1.4 Skeleton-pixel heights

At the `pixel` unit, height is read at every skeleton pixel of the bundle,
without tracing fibers:

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._collect_bundle_values
if param == PARAM_HEIGHT and unit == UNIT_PIXEL:
parts, load_errors = self._collect_per_bundle(
skeleton_height_values, bundle_paths,
```

`measure.skeleton_height_values` keeps the calibrated height at each skeleton
pixel except two kinds, both where fibers cross or branch: the 3 × 3
neighbourhood of every stored branch point, and the pixels closer to such a
neighbourhood, measured along the skeleton, than `CUT_END_EXCLUSION_WIDTHS`
times the median apparent width the bundle records. A bundle that records no
width keeps the second kind.

```python
# source: afm_nanofiber_analyzer/measure.py::_skeleton_pixel_heights
near_branch = cv2.dilate((np.asarray(arrays["bp"]) > 0).astype(np.uint8), square) > 0
kept = skeleton & ~near_branch
cleared = skeleton & near_branch
...
width = _recorded_median_width(meta)
if width is not None:
cut = kept & (cv2.dilate(cleared.astype(np.uint8), square) > 0)
if cut.any():
zone = CUT_END_EXCLUSION_WIDTHS * width
distance = _distance_along_skeleton(
kept, cut, pixel_aspect_from_meta(meta, cal.shape), zone)
kept &= ~(distance < zone)
return cal[kept], int(pieces), int(pieces - len(excluded))
```

Every pixel counts once, so a fiber contributes in proportion to its pixel
count, and bundles of finer pixels contribute more pixels per micrometer of
fiber. These samples are not independent observations of a specimen, which is
why GUI03 does not test them (§4.1).

## 2. Summary statistics and figures

### 2.1 Mean, standard deviation and quartiles

The results table reports, per group, the mean, the standard deviation, the
median, the first and third quartiles $Q_1$ and $Q_3$ (and the interquartile
range $Q_3 - Q_1$), and the mode (§2.2).

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_summary_stats
def _summary_stats(values: np.ndarray, weights=None) -> dict:
if weights is None:
q1, median, q3 = (
float(v) for v in np.percentile(values, [25.0, 50.0, 75.0])
)
return {
"mean": float(np.mean(values)),
"std": (float(np.std(values, ddof=1)) if np.size(values) > 1
else float("nan")),
"q1": q1, "median": median, "q3": q3,
"std_definition": STD_SAMPLE,
}

total = float(weights.sum())
mean = float(np.sum(values * weights) / total)
variance = float(np.sum(weights * (values - mean) ** 2) / total)
order = np.argsort(values)
sorted_values = values[order]
sorted_weights = weights[order]
cumulative = np.cumsum(sorted_weights)
positions = (cumulative - 0.5 * sorted_weights) / total
q1, median, q3 = (
float(v) for v in np.interp([0.25, 0.5, 0.75], positions, sorted_values)
)
return {
"mean": mean,
"std": float(np.sqrt(variance)),
"q1": q1, "median": median, "q3": q3,
"std_definition": STD_WEIGHTED,
}
```

**Unweighted samples.** The standard deviation is the sample standard deviation,

$$s = \sqrt{\frac{1}{n-1}\sum_{i=1}^{n}(x_i - \bar x)^2},$$

and is undefined (NaN) for a single value. The quartiles are those of
`numpy.percentile` with its default method, `linear`, which NumPy's
documentation identifies as definition 7 of Hyndman and Fan (1996):
with the $n$ values sorted, quantile $q$ lies at position $(n-1)q$ counted from
0, interpolated linearly between the neighbouring values.

**Weighted samples** (the frame corrections of §3). The mean and the standard
deviation divide by the total weight $W = \sum_i w_i$:

$$\bar x_w = \frac{1}{W}\sum_i w_i x_i, \qquad s_w = \sqrt{\frac{1}{W}\sum_i w_i (x_i - \bar x_w)^2}.$$

For the quartiles, the sorted values are placed at the midpoints of the weight
intervals they occupy, $p_i = (\sum_{j \le i} w_j - w_i/2)/W$, and quantile $q$ is
read by linear interpolation between those positions. The results table names
which standard deviation it holds (`SD (n-1)` or `weighted SD`). The code keeps
the two branches apart instead of passing weights of one to the weighted
branch, because the two quantile definitions do not agree exactly.

### 2.2 Histogram and mode

The histogram counts the samples, weighted when they carry a weight, into bins
of the width and range the user enters. The mode is the centre of the tallest
bin, so it depends on the binning.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_bin_results
counts, _edges = np.histogram(
r["values"], bins=edges, weights=r["weights"], density=False,
)
...
if total > 0:
k = int(np.argmax(counts))
r["mode"] = float((edges[k] + edges[k + 1]) / 2.0)
else:
r["mode"] = float("nan")
r["norm_total"] = total
if r.get("km_beyond", 0.0) > 0.0:
r["norm_total"] = r["weight_total"] + r["km_beyond"]
r["mode"] = float("nan")
```

The summary statistics are computed from every sample, also those outside the
entered range; the log states the share of the total weight that falls outside
the bins. Under the Kaplan-Meier estimate (§3.3) the bars are fractions of every
fiber the estimate stands for, so they sum to less than one by the share the
estimate could not place, and no mode is reported. GUI03 also notes when a
group has fewer than `MIN_SAMPLES_FOR_SHAPE` samples, below which the
histogram shows no distribution shape:

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::MIN_SAMPLES_FOR_SHAPE
MIN_SAMPLES_FOR_SHAPE = 8
```

### 2.3 ECDF and box plot

The ECDF plots, for each group, the cumulative fraction of samples (or of
weight) at or below each value, so it needs no bin width. Under Kaplan-Meier it
stops below one by the share the estimate could not place.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._draw_ecdf
cumulative = np.cumsum(weights) / (
float(weights.sum()) + r.get("km_beyond", 0.0))
```

The box plot is drawn from the quartiles of the results table, not by handing
the raw samples to Matplotlib, so the box and the table cannot disagree. The
whiskers follow the fences of Tukey (1977): each reaches the
furthest sample still within 1.5 interquartile ranges of the box. Samples
beyond the fences are not drawn. A group whose quartiles the Kaplan-Meier
estimate leaves undetermined (§3.4) gets no box; the range they lie in is
written in its place.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._draw_box
iqr = r["q3"] - r["q1"]
low_fence = r["q1"] - 1.5 * iqr
high_fence = r["q3"] + 1.5 * iqr
inside = values[(values >= low_fence) & (values <= high_fence)]
```

## 3. Contour lengths cut by the frame

A fiber that reaches the image frame continues outside the scan, so its
measured length is a lower bound. Because a long fiber is more likely to reach
the frame than a short one, both keeping and dropping such fibers bias the
length distribution towards short fibers. GUI03 offers four treatments
(`FRAME_MODES`). They apply to `contour length` only: the height, curvature and
kinks of the part inside the scan are still measurements of that part.

| Mode | What it does |
|---|---|
| `include` | Keeps every fiber at its measured length. |
| `exclude` | Drops the fibers that reach the frame. |
| `Miles-Lantuejoul` | Drops them and weights each remaining fiber by the inverse of its chance of fitting inside the frame (§3.2). |
| `Kaplan-Meier` | Estimates the length distribution from every fiber with an end of its own, treating a fiber cut at its other end as known to be at least as long as measured (§3.3). `fiber` unit only. |

### 3.1 `include` and `exclude`

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_apply_frame_mode
def _apply_frame_mode(per_source, frame_mode: str) -> tuple:
if frame_mode == FRAME_KAPLAN_MEIER:
return _apply_kaplan_meier(per_source)
kept = []
report = {"total": 0, "frame": 0, "lower_bound": 0, "unrecorded": []}
for path, stats in per_source:
if any(s.touches_frame is None for s in stats):
report["unrecorded"].append(path)
continue
survivors = [s for s in stats if not s.touches_frame]
report["total"] += len(stats)
report["frame"] += len(stats) - len(survivors)
report["lower_bound"] += sum(1 for s in survivors if s.cut_end_count)
kept.append((path, survivors))
return (per_source if frame_mode == FRAME_INCLUDE else kept), report
```

A fiber reaches the frame when a pixel of its skeleton track lies on the
outermost row or column of the analysis array (`FiberStats.touches_frame`). A
bundle whose fibers do not record this test is kept unfiltered under `include`
and left out whole under the other modes; the log names it either way. Under
`include`, `exclude` and `Miles-Lantuejoul` the log also reports how many of the
fibers that do not reach the frame have an end that is a cut rather than a
fiber end (`cut_end_count`), for example at a crossing: their lengths are lower
bounds too, which only the Kaplan-Meier estimate takes into account.

### 3.2 `Miles-Lantuejoul`: weighting by the chance of fitting

The mode is named after the edge correction of Miles and Lantuéjoul
(Miles 1974): when only the objects lying wholly inside a
sampling window are kept, each kept object is weighted by the inverse of the
chance that an object of its extent lies wholly inside the window.
<!-- TODO(review): Lantuéjoul's publication of this correction has not been
identified; add the reference after checking it. -->
GUI03 uses the skeleton track's bounding box as the extent. For an image of
$W \times H$ pixels and a box of $w \times h$ pixels, a box that avoids the
outermost row and column can be placed at $(W-1-w)(H-1-h)$ positions, and the
weight is normalized so that a single pixel weighs 1:

$$\omega = \frac{(W-2)(H-2)}{(W-1-w)(H-1-h)}.$$

```python
# source: afm_nanofiber_analyzer/measure.py::_frame_weight
def _frame_weight(
fiber: Fiber,
frame: Optional[Tuple[int, int]],
) -> float:
if frame is None or _reaches_frame(fiber, frame):
return float("nan")
height, width = frame
sx, sy = skeleton_track(fiber)
if len(sx) == 0:
return float("nan")
box_w = int(np.max(sx) - np.min(sx)) + 1
box_h = int(np.max(sy) - np.min(sy)) + 1
free_x = width - 1 - box_w
free_y = height - 1 - box_h
if free_x <= 0 or free_y <= 0:
return float("nan")
return float((width - 2) * (height - 2)) / float(free_x * free_y)
```

The weight is a ratio of pixel counts, so the pixel size cancels and weighted
fibers from scans of different sizes can be pooled. It corrects the frame only:
a fiber cut at a crossing is still counted as if it were whole.

The weights have no upper bound: a fiber whose box nearly fills the image can
carry most of a group's weight. GUI03 therefore logs, per group, the effective
sample size of the weights (Kish 1965) and the share of the total
weight held by the heaviest fiber:

$$n_\text{eff} = \frac{\left(\sum_i \omega_i\right)^2}{\sum_i \omega_i^2}.$$

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._run_comparison
"n_effective": (
float(wts.sum() ** 2 / np.sum(wts ** 2))
if frame_weighted and wts is not None and wts.size else None
),
"max_weight_share": (
float(wts.max() / wts.sum())
if frame_weighted and wts is not None and wts.size else None
),
```

The sample size in the results table stays the number of fibers measured, since
the total weight is an estimated fiber count, not an observed one.

### 3.3 `Kaplan-Meier`: lengths cut at one end as censored observations

The Kaplan-Meier estimator (Kaplan and Meier 1958) estimates a
distribution from observations some of which are known only to exceed the
value recorded (right-censored). GUI03 applies it to fiber lengths by counting
how many of a fiber's two ends are its own, that is, neither a cut at a
crossing nor on the frame:

```python
# source: afm_nanofiber_analyzer/measure.py::fiber_real_end_count
def fiber_real_end_count(stat: "FiberStats") -> Optional[int]:
if (stat.touches_frame is None or stat.cut_end_count is None
or stat.frame_end_count is None):
return None
own = max(0, 2 - int(stat.cut_end_count) - int(stat.frame_end_count))
if stat.touches_frame and stat.frame_end_count == 0:
own = min(own, 1)
return own
```

A fiber whose skeleton touches the frame away from its ends leaves the scan
there, so at most one of its ends is counted as its own.

Each own end starts one observation of the length, measured from a fiber end. A
fiber with both ends its own gives two complete observations at its length; a
fiber with one own end gives one observation censored at its measured length;
a fiber with no own end gives none. With $d_j$ complete observations at length
$\ell_j$ and $r_j$ observations still at risk there (every observation of
length $\ell_j$ or longer), the estimate of the share of fibers longer than
$\ell$ is

$$\hat S(\ell) = \prod_{\ell_j \le \ell} \left(1 - \frac{d_j}{r_j}\right),$$

and each step $\hat S(\ell_{j-1}) - \hat S(\ell_j)$ is the share of fibers at
length $\ell_j$. At a tied length, complete observations are counted before
censored ones.

```python
# source: afm_nanofiber_analyzer/measure.py::kaplan_meier_length_weights
lengths = np.asarray(lengths, dtype=np.float64)
own = np.asarray(own_ends, dtype=np.int64)
weights = np.zeros(lengths.size, dtype=np.float64)
observations = float(own.sum())
if observations == 0.0:
return weights, 1.0
order = np.lexsort((own != 2, lengths))
at_risk = observations
survival = 1.0
i = 0
while i < order.size:
j = i
while j < order.size and lengths[order[j]] == lengths[order[i]]:
j += 1
tied = order[i:j]
complete = tied[own[tied] == 2]
if complete.size and at_risk > 0.0:
step = survival * (2.0 * complete.size) / at_risk
weights[complete] = step / complete.size * (observations / 2.0)
survival -= step
at_risk -= float(own[tied].sum())
i = j
return weights, max(survival, 0.0)
```

The step at each length is shared among the fibers seen whole at that length
and multiplied by half the number of observations, so a weight counts fibers.
The second value returned is what is left of $\hat S$ after the longest fiber
seen whole: the share of fibers the estimate places beyond it without knowing
where. For example, two fibers seen whole at lengths 1 and 3 and one fiber cut
at one end at length 2 receive the weights 1, 1.5 and 0: the cut fiber is longer
than 2, so its share goes to the fiber seen whole beyond it.

The code states the assumption the estimate rests on: a cut or the frame stops
an observation independently of the fiber's length as long as the fibers are
spread evenly over a region larger than the scan and the crossings along a
fiber do not depend on its length. How the estimate fared on cut random
segments is in [Evaluation on particular data](validation.md) §6.3.

GUI03 makes one estimate per group, over all of its bundles together; only the
fibers seen whole carry a weight into the statistics:

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_apply_kaplan_meier
lengths = [s.length_nm for _p, stats, _o in recorded for s in stats]
own = [o for _p, _s, owns in recorded for o in owns]
weights, rest = kaplan_meier_length_weights(lengths, own)
kept = []
at = 0
for path, stats, owns in recorded:
survivors = []
for s, o in zip(stats, owns):
if o == 2 and weights[at] > 0.0:
survivors.append(dataclasses.replace(s, frame_weight=float(weights[at])))
at += 1
kept.append((path, survivors))
...
report["unassigned"] = rest if sum(own) else 0.0
report["beyond"] = rest * sum(own) / 2.0
```

The mode is offered for the `fiber` unit only: the median of one image could
itself lie beyond what was seen whole.

### 3.4 Quartiles the estimate leaves undetermined

When the estimate places part of the distribution beyond the longest fiber seen
whole, a quartile can depend on where that part lies. GUI03 computes, for each
quartile, the range it can lie in: the upper end places the unplaced share at
infinity, the lower end just above the longest fiber seen whole.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_bounds
upper_positions = (np.cumsum(sorted_weights) - 0.5 * sorted_weights) / total
...
for q, key in QUARTILE_KEYS:
if sorted_values.size == 0:
bounds[key] = (0.0, float("inf"))
continue
upper = (float(np.interp(q, upper_positions, sorted_values))
if q <= assigned / total else float("inf"))
lower = float(np.interp(q, positions, lengths))
bounds[key] = (min(lower, upper), upper)
```

A quartile is reported as a number only where the two ends agree; otherwise the
table shows the range, `[lower, upper]`, or `> lower` when the quartile can lie
anywhere beyond `lower`. The mean and the standard deviation are not reported,
because they depend on the part that was not estimated.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_summary
if sum(b for _l, b in estimates) <= 0.0:
return dict(_summary_stats(values, weights), bounds={})
bounds = _kaplan_meier_bounds(values, weights, estimates)
stats = {"mean": float("nan"), "std": float("nan"),
"std_definition": STD_WEIGHTED, "bounds": bounds}
for _q, key in QUARTILE_KEYS:
lower, upper = bounds[key]
stats[key] = (upper if np.isfinite(upper)
and upper - lower <= 1e-9 * max(1.0, abs(upper))
else float("nan"))
return stats
```

### 3.5 The resampling interval of the quartiles

The bounds of §3.4 cover only where the unplaced share might lie; the fibers
measured are themselves a sample. GUI03 therefore resamples each group's fibers
with replacement, the bootstrap of Efron (1979), recomputes the
estimate and its bounds `KM_RESAMPLES` times, and logs for each quartile the
interval from the 2.5th percentile of its lower bound to the 97.5th percentile
of its upper bound over the resamples. The seed is fixed, so the same data give
the same interval.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::KM_RESAMPLES, KM_RESAMPLE_SEED
KM_RESAMPLES = 200
KM_RESAMPLE_SEED = 20261104
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_kaplan_meier_interval
for _resample in range(resamples):
values, weights, estimates = [], [], []
for lengths, own in samples:
pick = rng.integers(0, lengths.size, lengths.size)
drawn, drawn_own = lengths[pick], own[pick]
fiber_weights, rest = kaplan_meier_length_weights(drawn, drawn_own)
...
return {key: (float(np.percentile(lowers[key], 2.5)),
float(np.percentile(uppers[key], 97.5, method="higher")))
for _q, key in QUARTILE_KEYS}
```

## 4. Comparing groups

With two or more groups, GUI03 compares every pair of groups with two rank
tests and an effect size (`afm_nanofiber_analyzer.group_compare`). The tests are
rank-based because fiber morphology distributions are right-skewed, so the
normality a t-test assumes does not hold for them.

### 4.1 When GUI03 tests

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::TESTABLE_UNITS
TESTABLE_UNITS = (UNIT_FIBER, UNIT_IMAGE)
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::App._run_comparison
comparisons = []
comparison_note = ""
if len(results) < 2:
...
elif unit not in TESTABLE_UNITS:
...
elif frame_weighted and unit == UNIT_FIBER:
...
else:
try:
comparisons = compare_groups(
[(r["name"], r["values"]) for r in results]
)
```

Tests are run on exactly the samples the table and the figure describe, and
only at the `fiber` and `image` units:

- **`pixel` samples are not tested.** Neighbouring pixels of one fiber repeat
  the same object and a long fiber contributes more of them, so a p-value over
  them measures how finely the images were sampled rather than whether the
  specimens differ.
- **Weighted `fiber` samples are not tested.** The Mann-Whitney U and
  Kolmogorov-Smirnov tests take no weights, so lengths under `Miles-Lantuejoul`
  or `Kaplan-Meier` at the `fiber` unit are described but not tested. At the
  `image` unit under `Miles-Lantuejoul`, each image's sample is one unweighted
  value (its weighted median, §1.3), and it is tested.
- **`fiber` and `image` treat different things as independent.** The `fiber`
  unit counts the fibers of one image as independent, although they share one
  place on the specimen, one tip and one background calibration; its p-values
  shrink as the number of fibers grows. The `image` unit takes one value per
  image, so the difference between places on a specimen enters the comparison.
  GUI03 states this under the comparison table for the `fiber` unit
  (`_comparison_caveat`).

### 4.2 The two tests and their statistics

For a pair of groups A and B with $n_A$ and $n_B$ samples:

- The **Mann-Whitney U test** (Mann and Whitney 1947) uses
  $U = R_A - n_A(n_A+1)/2$, where $R_A$ is the sum of the ranks of A's samples
  in the pooled sample (tied values take the mean of their ranks). The two-sided
  statistic is $|U - n_A n_B/2|$. It responds to one group tending to lie above
  the other.
- The **two-sample Kolmogorov-Smirnov test** (Smirnov 1948) uses
  $D = \max_x |F_A(x) - F_B(x)|$, the largest gap between the two empirical
  distribution functions. It responds to any difference in shape, including two
  groups with the same median and different spread.

In the first two ways of computing a p-value (§4.3), both statistics are
computed on an integer scale, $2|U - n_A n_B/2|$ and $n_A n_B D$, so equal
statistics compare equal; $D$ is read only at the end of each run of equal
values, where both distribution functions step.

```python
# source: afm_nanofiber_analyzer/group_compare.py::_split_statistics
rank2 = np.rint(2.0 * rankdata(pooled)).astype(np.int64)
u2 = rank2[members].sum(axis=1) - n_a * (n_a + 1)
u_stat = np.abs(u2 - n_a * n_b)

order = np.argsort(pooled, kind="stable")
ordered = pooled[order]
run_ends = np.flatnonzero(np.r_[ordered[1:] != ordered[:-1], True])
in_a = np.zeros((members.shape[0], pooled.size), dtype=bool)
np.put_along_axis(in_a, members, True, axis=1)
count_a = np.cumsum(in_a[:, order], axis=1)[:, run_ends]
count_b = (run_ends + 1) - count_a
d_stat = np.abs(count_a * n_b - count_b * n_a).max(axis=1)
return u_stat, d_stat
```

GUI03 takes the Mann-Whitney U test as the primary test: the comparison table
shows its p-value after the correction of §4.4, with the uncorrected value in
parentheses, and shows the KS p-value uncorrected, as a reference for a
difference in shape. Reading whichever of the
two came out smaller would test each pair twice, which the correction of §4.4
does not cover. The note under the comparison table says so
(`_primary_test_note`).

### 4.3 How a p-value is computed

A pair is tested only when both groups hold at least `MIN_SAMPLES_FOR_TEST`
samples; a smaller pair is listed with no p-value and no effect size. The
p-value of a pair is then computed in one of three ways:

```python
# source: afm_nanofiber_analyzer/group_compare.py::MIN_SAMPLES_FOR_TEST, _EXACT_ARRANGEMENT_LIMIT, _SAMPLED_SPLITS, _SAMPLED_SEED, _SAMPLED_MAX_VALUES
MIN_SAMPLES_FOR_TEST = 3
_EXACT_ARRANGEMENT_LIMIT = 100_000
_SAMPLED_SPLITS = 20_000
_SAMPLED_SEED = 0
_SAMPLED_MAX_VALUES = 5_000
```

```python
# source: afm_nanofiber_analyzer/group_compare.py::_pair_pvalues
if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
return float("nan"), float("nan")
if comb(a.size + b.size, a.size) <= _EXACT_ARRANGEMENT_LIMIT:
return _exact_pvalues(a, b)
n_values = a.size + b.size
if (n_values <= _SAMPLED_MAX_VALUES
and np.unique(np.concatenate([a, b])).size < n_values):
return _sampled_pvalues(a, b)

from scipy.stats import ks_2samp, mannwhitneyu

try:
u_p = float(mannwhitneyu(a, b, alternative="two-sided").pvalue)
...
try:
ks_p = float(ks_2samp(a, b).pvalue)
```

1. **Every arrangement counted.** When the pooled values can be split into
   groups of sizes $n_A$ and $n_B$ in at most `_EXACT_ARRANGEMENT_LIMIT` ways,
   $\binom{n_A+n_B}{n_A}$, every split is formed and the p-value is the share
   of splits whose statistic is at least as extreme as the observed one. This
   is the permutation distribution of each statistic given the values observed,
   so it is exact with tied values too. Two groups of 9 make 48,620
   arrangements and are counted; two groups of 10 make 184,756 and are not.

   ```python
   # source: afm_nanofiber_analyzer/group_compare.py::_exact_pvalues
   n_a, n_b = a.size, b.size
   pooled = np.concatenate([a, b])
   members = np.fromiter(
   (i for split in combinations(range(pooled.size), n_a) for i in split),
   dtype=np.intp,
   ).reshape(-1, n_a)
   u_stat, d_stat = _split_statistics(pooled, members, n_a, n_b)
   return (float(np.mean(u_stat >= u_stat[0])),
   float(np.mean(d_stat >= d_stat[0])))
   ```

2. **Random splits.** A larger pair with tied values and at most
   `_SAMPLED_MAX_VALUES` values is tested on `_SAMPLED_SPLITS` random splits
   drawn with the fixed seed `_SAMPLED_SEED`. The observed split counts as one
   of them, so the p-value is $(1+k)/(1+N)$ for $k$ splits at least as extreme
   among $N$, never 0 and never below $1/(1+N)$.

   ```python
   # source: afm_nanofiber_analyzer/group_compare.py::_sampled_pvalues
   rng = np.random.default_rng(_SAMPLED_SEED)
   u_count = d_count = 0
   for start in range(0, _SAMPLED_SPLITS, _SAMPLED_BATCH):
   size = min(_SAMPLED_BATCH, _SAMPLED_SPLITS - start)
   members = np.argpartition(
   rng.random((size, pooled.size)), n_a - 1, axis=1)[:, :n_a]
   u_stat, d_stat = _split_statistics(pooled, members, n_a, n_b)
   u_count += int(np.count_nonzero(u_stat >= observed_u[0]))
   d_count += int(np.count_nonzero(d_stat >= observed_d[0]))
   return ((1 + u_count) / (1 + _SAMPLED_SPLITS),
   (1 + d_count) / (1 + _SAMPLED_SPLITS))
   ```

3. **SciPy.** Any other pair — one without tied values, or one with more than
   `_SAMPLED_MAX_VALUES` values — goes to `scipy.stats.mannwhitneyu`
   (two-sided) and `scipy.stats.ks_2samp`.

The reason for the first two paths, as the code records it: with tied values
SciPy's Mann-Whitney turns to its normal approximation and its KS test treats
the values as untied. For example, three equal values against three other equal
values give p = 0.047 from `scipy.stats.mannwhitneyu`, below the 0.1 that
counting every arrangement gives and that is the smallest p-value two groups of
three can reach (§4.6).

### 4.4 Correcting for many pairs: Holm

Comparing $k$ groups makes $k(k-1)/2$ pairs. Each p-value is corrected across
all pairs of the run, separately for each test, by the step-down procedure of
Holm (1979). With the $m$ p-values sorted,
$p_{(1)} \le \dots \le p_{(m)}$, the corrected values are

$$\tilde p_{(i)} = \min\left(1,\ \max_{j \le i} (m - j + 1)\, p_{(j)}\right),$$

which keeps the sequence non-decreasing, so a later comparison never ends up
more significant than an earlier one. A pair that could not be tested (NaN) is
left out of $m$.

```python
# source: afm_nanofiber_analyzer/group_compare.py::holm_adjusted
values = [float(p) for p in pvalues]
finite = [(i, p) for i, p in enumerate(values) if np.isfinite(p)]
adjusted = list(values)
if not finite:
return adjusted

finite.sort(key=lambda item: item[1])
count = len(finite)
running = 0.0
for rank, (index, p) in enumerate(finite):
running = max(running, (count - rank) * p)
adjusted[index] = min(1.0, running)
return adjusted
```

For example, the p-values 0.01, 0.04 and 0.03 become 0.03, 0.06 and 0.06. The
correction covers the pairs of one quantity; testing several quantities makes a
further family, which GUI03 cannot correct because it runs one quantity at a
time, and the note under the comparison table says so.

```python
# source: afm_nanofiber_analyzer/group_compare.py::compare_groups
u_adjusted = holm_adjusted([p["u_p"] for p in pairs])
ks_adjusted = holm_adjusted([p["ks_p"] for p in pairs])
```

### 4.5 Effect size: Cliff's delta

A p-value grows smaller with the sample size while the separation it detects
may be negligible, so each pair also reports Cliff's delta
(Cliff 1993),

$$\delta = P(a > b) - P(a < b),$$

over all pairs of one sample $a$ of group A and one $b$ of group B. It lies in
$[-1, 1]$: 0 when the groups overlap symmetrically, $\pm 1$ when every value of
one exceeds every value of the other, positive when A tends to exceed B. GUI03
computes it from the Mann-Whitney statistic of SciPy, which counts the pairs
with $a > b$ plus half the ties, so $\delta = 2U/(n_A n_B) - 1$ without forming
the $n_A n_B$ pairs.

```python
# source: afm_nanofiber_analyzer/group_compare.py::cliffs_delta
statistic = mannwhitneyu(a, b, alternative="two-sided").statistic
return float(2.0 * statistic / (a.size * b.size) - 1.0)
```

The magnitude label beside it applies the thresholds the code attributes to
Romano et al. (2006):
<!-- TODO(review): the thresholds 0.147 / 0.33 / 0.474 were checked only against
secondary sources that attribute them to Romano et al. (2006), not against the
conference paper itself. -->

```python
# source: afm_nanofiber_analyzer/group_compare.py::MAGNITUDE_THRESHOLDS, MAGNITUDE_LARGE
MAGNITUDE_THRESHOLDS = (
(0.147, "negligible"),
(0.330, "small"),
(0.474, "medium"),
)
MAGNITUDE_LARGE = "large"
```

```python
# source: afm_nanofiber_analyzer/group_compare.py::delta_magnitude
magnitude = abs(float(delta))
for threshold, label in MAGNITUDE_THRESHOLDS:
if magnitude < threshold:
return label
return MAGNITUDE_LARGE
```

### 4.6 The smallest p-value a pair can reach

With few samples, two groups that do not overlap at all still cannot reach a
small p-value. Each tested pair records the smallest p-value either test returns
at its sample sizes, found by running the tests on two separated samples
without tied values:

```python
# source: afm_nanofiber_analyzer/group_compare.py::_min_attainable_p
def _min_attainable_p(n_a: int, n_b: int) -> float:
a = np.arange(n_a, dtype=float)
b = np.arange(n_a, n_a + n_b, dtype=float)
return min(_pair_pvalues(a, b))
```

When the arrangements are counted, both separated arrangements (A entirely below
B, and entirely above) are as extreme as each other, so the value is
$2/\binom{n_A+n_B}{n_A}$: 0.1 for three images against three, 0.029 for four
against four. When it is not below the conventional level, the note under the
comparison table names the pair, because a "not significant" there says nothing
about whether the groups differ. The Holm correction only raises a p-value, so
such a pair cannot reach the level after it either.

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::CONVENTIONAL_ALPHA
CONVENTIONAL_ALPHA = 0.05
```

```python
# source: guis/GUI03_Fiber_Morphology_Statistics.py::_attainable_p_note
limited = [
c for c in comparisons
if np.isfinite(c.min_attainable_p)
and c.min_attainable_p >= CONVENTIONAL_ALPHA
]
```

`CONVENTIONAL_ALPHA` decides nothing else: the comparison table shows p-values
and marks no pair as significant.

### 4.7 Differences GUI03 reports but does not correct

Some differences between the compared bundles change a measured quantity for
reasons other than the specimen. GUI03 measures the bundles as they are, runs
the comparison, and states the difference in the log or under the comparison
table, so the user can judge what it means for the result:

- the centerlines the bundles were analyzed on (`_centerline_note`);
- for curvature, and within a group for skeleton-pixel heights, the pixel sizes
  (`App._log_pixel_size_spread`, `App._log_group_pixel_size_spread`);
- for kink density, the kink threshold, the pixel size, the bundle format and
  the pixel noise of the bundles (`_kink_condition_report`);
- for contour length under `include` or `exclude`, the scan sizes
  (`_scan_size_spread_note`), and that the frame biases the lengths of the
  groups by different amounts (`_frame_bias_note`).

## 5. Keeping this page in step with the code

Every excerpt names its symbol, and `scripts/check_gui03_docs.py` compares it
with the code line by line. Every quoted symbol is listed in `WATCHED_SYMBOLS`
of that script and fingerprinted, with comments and docstrings removed, in
`tests/gui03_doc_manifest.json`. The check runs in the pre-commit hook
(`--staged`), in `tests/test_gui03_docs.py`, and in the Claude Code hook
`.claude/hooks/doc_code_reminder.py`. After a change to a quoted symbol, reread
the sections that quote it in both language versions, update them, and refresh
the fingerprints:

```text
.venv\Scripts\python.exe scripts\check_gui03_docs.py --update
```

## References

- Cliff, N. (1993). Dominance statistics: Ordinal analyses to answer ordinal
  questions. *Psychological Bulletin*, 114(3), 494–509.
  doi:10.1037/0033-2909.114.3.494
- Efron, B. (1979). Bootstrap methods: Another look at the jackknife. *The
  Annals of Statistics*, 7(1), 1–26. doi:10.1214/aos/1176344552
- Holm, S. (1979). A simple sequentially rejective multiple test procedure.
  *Scandinavian Journal of Statistics*, 6(2), 65–70.
- Hyndman, R. J., & Fan, Y. (1996). Sample quantiles in statistical packages.
  *The American Statistician*, 50(4), 361–365.
  doi:10.1080/00031305.1996.10473566
- Kaplan, E. L., & Meier, P. (1958). Nonparametric estimation from incomplete
  observations. *Journal of the American Statistical Association*, 53(282),
  457–481. doi:10.1080/01621459.1958.10501452
- Kish, L. (1965). *Survey Sampling*. Wiley.
- Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random
  variables is stochastically larger than the other. *The Annals of
  Mathematical Statistics*, 18(1), 50–60. doi:10.1214/aoms/1177730491
- Miles, R. E. (1974). On the elimination of edge effects in planar sampling.
  In E. F. Harding & D. G. Kendall (Eds.), *Stochastic Geometry*
  (pp. 228–247). Wiley.
  <!-- TODO(review): the page range was taken from citing works, which also
  give 227–247 and 229–247; check it against the volume. -->
- Romano, J., Kromrey, J. D., Coraggio, J., & Skowronek, J. (2006). Appropriate
  statistics for ordinal level data: Should we really be using t-test and
  Cohen's d for evaluating group differences on the NSSE and other surveys?
  Paper presented at the annual meeting of the Florida Association of
  Institutional Research, Cocoa Beach, Florida.
  <!-- TODO(review): this entry follows citing works; the paper itself was not
  consulted. -->
- Smirnov, N. (1948). Table for estimating the goodness of fit of empirical
  distributions. *The Annals of Mathematical Statistics*, 19(2), 279–281.
  doi:10.1214/aoms/1177730256
- Tukey, J. W. (1977). *Exploratory Data Analysis*. Addison-Wesley.
