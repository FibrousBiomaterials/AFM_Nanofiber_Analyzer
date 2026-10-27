# Evaluation on particular data

[Analysis algorithms](algorithms.md) explains what each stage of the analysis
computes. This page collects what the stages did on particular data: the scans
bundled with the repository, and synthetic scans drawn with a known answer.
Several defaults of the code were chosen by looking at these results, and the
page says which.

**Every number on this page describes the data it was measured on, not the
algorithm.** The bundled scans are 3<!--m:kink_reference.scans--> images of two specimens: the higher-plant TOC and
Bruker NDTOC scans image the same dispersion, the latter recorded to test reading
Bruker data. The synthetic scans are drawn with fixed fiber and probe
shapes. Neither tells how the analysis behaves on another specimen, another
instrument or another scan size. A result here shows the kind of behaviour worth
checking for; whether it holds on your images is decided by looking at your
images.

## Data and how the numbers are kept

| Data | What it is | Code |
|---|---|---|
| Bundled scans | a tunicate CNF scan (`testdata_tunicateCNF`), a higher-plant TOC scan (`testdata_higherplantTOC`), and a Bruker NDTOC scan (`testdata_Bruker_txt`); the two samples in `testdata_artificial` are crops of the tunicate scan and are not used | `SCANS` in `scripts/kink_reference_score.py` |
| Visual reference | kinks marked on the height images of the bundled scans by an AI coding agent (Claude Code), which viewed each fiber on an enlarged crop of the height image with no detector output drawn on it, although for some fibers it already knew where the detector then in use placed kinks: 53<!--m:kink_reference.clear_marks--> clear kinks | `scripts/kink_reference_score.py` |
| Synthetic suite | scans drawn with a known centerline and known corners: 2<!--c:scripts/synthetic_suite.py::NMPX--> nm pixels, apparent width $W$ = 8<!--c:scripts/synthetic_suite.py::W--> px | `scripts/synthetic_suite.py` |
| Kink-rule sweep | synthetic kinked, straight, arc and sine fibers over apparent width and pixel noise | `scripts/kink_rule_sweep.py` |

Every number is produced by an experiment of `scripts/measure_docs.py`, named
in the text, and carries a hidden marker that `scripts/check_doc_numbers.py`
compares with the recording in `tests/doc_measurements.json`. When the code an
experiment ran on changes what it computes, the check fails until the
experiment is run again (AGENTS.md §8.15).

## 1. Background calibration

See [Analysis algorithms](algorithms.md) §1.

### 1.1 Tilt and bowl of the bundled scans

| Scan | Plane slope (nm/px) | Fall across a masked fiber (nm) | Bowl, peak to peak (nm) | Median height under the skeleton (nm) |
|---|---|---|---|---|
| tunicate CNF | 0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> | 4.0<!--m:bg_stats.tunicate.drop_across_hole_nm--> | 15.2<!--m:bg_stats.tunicate.quadratic_p2p_nm--> | 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> |
| higher-plant TOC | 0.001<!--m:bg_stats.hplantTOC.plane_slope_nm_per_px--> | 0.01<!--m:bg_stats.hplantTOC.drop_across_hole_nm--> | 1.7<!--m:bg_stats.hplantTOC.quadratic_p2p_nm--> | 1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> |
| Bruker NDTOC | 0.003<!--m:bg_stats.NDTOC.plane_slope_nm_per_px--> | 0.04<!--m:bg_stats.NDTOC.drop_across_hole_nm--> | 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> | 2.1<!--m:bg_stats.NDTOC.skeleton_height_median_nm--> |

The plane slope is that of the least-squares plane through the raw heights;
the fall is that slope times the median width of the dilated fiber mask; the
bowl is the peak-to-peak of the quadratic terms of a second-order surface
fitted after the plane; the height is the median calibrated height under the
default skeleton (experiment bg_stats). On the tunicate scan the background
falls 4.0<!--m:bg_stats.tunicate.drop_across_hole_nm--> nm across one masked fiber whose median height is 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm. The
higher-plant and Bruker scans are level as planes, but the Bruker scan's bowl
alone spans 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> nm. The trend surface of the background calibration is
second-order rather than a plane because of scans like the last.

### 1.2 Fill accuracy with and without detrending

On 13<!--m:bg_fill.holes--> square holes of 21<!--m:bg_fill.hole_size_px--> px cut into fiber-free background of the tunicate
scan (experiment bg_fill), the filled values departed from the heights actually
measured there by 2.4<!--m:bg_fill.none.nearest.fill_error_median_nm--> nm with nearest-neighbour propagation and 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm with
inpainting when nothing was detrended, and by 0.31<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm and 0.25<!--m:bg_fill.quadratic.inpaint.fill_error_median_nm--> nm after the
quadratic trend was removed (the median over the holes of the largest
departure in each). On these holes the detrending, not the filler, set the
accuracy, and a plane did almost as well as the quadratic surface (0.31<!--m:bg_fill.plane.nearest.fill_error_median_nm--> nm
against 0.31<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm with nearest-neighbour fill).

### 1.3 The fill used up to 1.0.0

Without detrending, the inpainting used up to 1.0.0 departed from the true
background by 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm on the tunicate holes above. Running the calibrator of release
1.0.0 (from tag `v1.0.0`) on a synthetic scan with one 8<!--m:bg_legacy_halo.fiber_height_nm--> nm fiber across a
0.24<!--m:bg_legacy_halo.slope_nm_per_px--> nm/px plane (experiment bg_legacy_halo), the calibrated background beside
the fiber ranged from −0.76<!--m:bg_legacy_halo.v1_0_0.beside_min_nm--> to +0.77<!--m:bg_legacy_halo.v1_0_0.beside_max_nm--> nm, beyond the default binarization
threshold of 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm; the current code leaves −0.21<!--m:bg_legacy_halo.current.beside_min_nm--> to +0.18<!--m:bg_legacy_halo.current.beside_max_nm--> nm there.

### 1.4 `tophat` at the border

On a ramp of 0.24<!--m:tophat_border.slope_nm_per_px--> nm/px, a little steeper than the steepest plane of the bundled
scans (0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> nm/px, §1.1),
opening the raw heights with the 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size-->-px element leaves a band
**3.1<!--m:tophat_border.raw.uphill_band_max_nm--> nm** high within 12<!--n:definition--> px of the uphill edge, far above the
0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm binarization threshold; opening the detrended heights leaves
0.29<!--m:tophat_border.detrended.uphill_band_max_nm--> nm (experiment tophat_border).

### 1.5 The axis of `spline1d`

Each test input was calibrated by `trendfill` and by `spline1d` along `'x'` and
along `'y'`, everything else at the defaults (experiment spline1d_axis). On the
background (pixels more than 5<!--n:definition--> px from the union of the three binarized
masks), the table gives the spread (standard deviation, nm) of the per-row
medians, which grows with horizontal stripes, and of the per-column medians,
which grows with vertical ones.

| Input | Rows, `trendfill` | Rows, `'x'` | Rows, `'y'` | Columns, `trendfill` | Columns, `'x'` | Columns, `'y'` |
|---|---|---|---|---|---|---|
| tunicate CNF | 0.010<!--m:spline1d_axis.tunicate.trendfill.row_median_std_nm--> | 0.007<!--m:spline1d_axis.tunicate.x.row_median_std_nm--> | 0.081<!--m:spline1d_axis.tunicate.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.tunicate.trendfill.column_median_std_nm--> | 0.017<!--m:spline1d_axis.tunicate.x.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.y.column_median_std_nm--> |
| higher-plant TOC | 0.226<!--m:spline1d_axis.hplantTOC.trendfill.row_median_std_nm--> | 0.005<!--m:spline1d_axis.hplantTOC.x.row_median_std_nm--> | 0.281<!--m:spline1d_axis.hplantTOC.y.row_median_std_nm--> | 0.005<!--m:spline1d_axis.hplantTOC.trendfill.column_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.column_median_std_nm--> | 0.009<!--m:spline1d_axis.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.019<!--m:spline1d_axis.NDTOC.trendfill.row_median_std_nm--> | 0.019<!--m:spline1d_axis.NDTOC.x.row_median_std_nm--> | 0.306<!--m:spline1d_axis.NDTOC.y.row_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.x.column_median_std_nm--> | 0.036<!--m:spline1d_axis.NDTOC.y.column_median_std_nm--> |

Along `'y'`, the per-row spread was larger than with `trendfill` on every
input. Rendered, the calibrated images along `'y'` carry bright and dark
horizontal bands across the whole image on the tunicate, Bruker and higher-plant
inputs, and the scan-line glitch of the higher-plant scan stays. Along `'x'`,
that glitch is removed on the higher-plant scan, and a horizontal streak
that `trendfill` leaves on the tunicate scan is gone; but a dark rim, visibly
deeper than with `trendfill`, forms along the right side of fibers running
close to vertical on the tunicate scan. On that input the per-column spread
along `'x'` is clearly larger than with `trendfill`; on the higher-plant and
Bruker scans it is nearly the same.

To check vertical stripes, each test input was rotated by 90<!--n:definition-->° (`np.rot90`), so
that its scan lines become columns and its line offsets vertical stripes, and
the same comparison was repeated (experiment spline1d_axis_rotated). The table
gives the per-column spread on the rotated inputs.

| Input (rotated) | Columns, `trendfill` | Columns, `'x'` | Columns, `'y'` |
|---|---|---|---|
| tunicate CNF | 0.069<!--m:spline1d_axis_rotated.tunicate.trendfill.column_median_std_nm--> | 0.120<!--m:spline1d_axis_rotated.tunicate.x.column_median_std_nm--> | 0.072<!--m:spline1d_axis_rotated.tunicate.y.column_median_std_nm--> |
| higher-plant TOC | 0.040<!--m:spline1d_axis_rotated.hplantTOC.trendfill.column_median_std_nm--> | 0.073<!--m:spline1d_axis_rotated.hplantTOC.x.column_median_std_nm--> | 0.040<!--m:spline1d_axis_rotated.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.046<!--m:spline1d_axis_rotated.NDTOC.trendfill.column_median_std_nm--> | 0.261<!--m:spline1d_axis_rotated.NDTOC.x.column_median_std_nm--> | 0.047<!--m:spline1d_axis_rotated.NDTOC.y.column_median_std_nm--> |

On the two inputs other than the higher-plant scan, rotating made the spread
larger for every method, `trendfill` included (compare the first table), so
these numbers do not isolate what `'y'` does. Rendered, the scan-line glitch of
the higher-plant scan stays along `'y'` on the rotated image, as a bright
vertical band, whereas `'x'` removes it from the unrotated image. That band is
binarized as fiber on the rotated image, so it lies outside the background the
spread is taken over and is not in the table. On the rotated tunicate scan,
`trendfill` and `'y'` both leave fine vertical stripes across the whole image.
On these rotated test inputs, `'y'` did not remove the glitch that `'x'`
removes from the unrotated scan.

### 1.6 Smoothing along X only

Each test input was calibrated by the default `trendfill` with the
Savitzky–Golay smoothing of the background along X only, as the code does, and
along X and then Y (experiment savgol_axis). The table gives the spread
(standard deviation, nm) of the per-row medians of the background (pixels more
than 5<!--n:definition--> px from the union of the two binarized masks), which grows with
horizontal stripes.

| Input | Rows, X only | Rows, X and Y |
|---|---|---|
| tunicate CNF | 0.010<!--m:savgol_axis.tunicate.x_only.row_median_std_nm--> | 0.070<!--m:savgol_axis.tunicate.x_and_y.row_median_std_nm--> |
| higher-plant TOC | 0.226<!--m:savgol_axis.hplantTOC.x_only.row_median_std_nm--> | 0.293<!--m:savgol_axis.hplantTOC.x_and_y.row_median_std_nm--> |
| Bruker NDTOC | 0.015<!--m:savgol_axis.NDTOC.x_only.row_median_std_nm--> | 0.046<!--m:savgol_axis.NDTOC.x_and_y.row_median_std_nm--> |
Smoothing along Y as well made the per-row spread larger on every input.
Rendered, the images smoothed along both axes carry horizontal streaks across
the tunicate and higher-plant scans, which the X-only
smoothing does not leave; the Bruker scan looks much the same either way.

### 1.7 When `spline1d` adds the trend back

`spline1d` adds the trend back before the Savitzky–Golay smoothing, `trendfill`
after it. Each test input was calibrated by `spline1d` both ways (experiment
spline1d_trend_order); the table gives the largest difference in calibrated
height (nm).

| Input | Largest difference (nm) |
|---|---|
| tunicate CNF | 0.006<!--m:spline1d_trend_order.tunicate.max_difference_nm--> |
| higher-plant TOC | 0.000<!--m:spline1d_trend_order.hplantTOC.max_difference_nm--> |
| Bruker NDTOC | 0.000<!--m:spline1d_trend_order.NDTOC.max_difference_nm--> |
Because the smoothing is linear, the two orders differ only by the trend minus
its smoothed self, which is largest where the trend curves most along X. On
every input the difference stays far below the 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm binarization threshold.

### 1.8 Scans whose fibers span many pixels

Every length the background methods use is a number of pixels
([Analysis algorithms](algorithms.md) §1), so a fiber spread over many pixels
can be subtracted in part as background. The bundled scans cannot show this,
because their fibers span few pixels, so scans of the same fibers at finer
pixels were built from them (experiment zoomed_background). From each bundled
scan, the default calibrated image smoothed by a Gaussian of 1<!--n:value tried--> px is taken
as the reference height and the background the default analysis subtracted is
the background. The reference is the default analysis at the scan's own pixel
size, so "kept" below measures what finer pixels lose relative to it, not the
error of the default analysis itself; this experiment does not measure the
absolute accuracy of the height, which §1.9 measures on synthetic fibers. The two tiles of 256<!--c:scripts/measure_docs.py::ZOOM_TILE--> px holding the most skeleton pixels are upsampled by each zoom factor, so the field
stays the same and the pixels become finer; white noise at the scan's own level
(0.027<!--m:zoomed_background.tunicate.noise_nm-->–0.064<!--m:zoomed_background.NDTOC.noise_nm--> nm) is added, and each method runs at its defaults through all four
stages. The fibers' apparent widths at the scans' own pixel size are
7.5<!--m:zoomed_background.hplantTOC.width_px-->–8.6<!--m:zoomed_background.NDTOC.width_px--> px, so a zoom factor $k$ spreads them over about $k$ times as many
pixels. "Kept" is the median of calibrated over reference height at the default
skeleton's points, ranged here over the tiles.

| Zoom | trendfill | spline1d | tophat |
|---|---|---|---|
| 1<!--n:value tried--> | 0.97–1.00<!--m:zoomed_background.trendfill.x1.kept_range--> | 0.99–1.01<!--m:zoomed_background.spline1d.x1.kept_range--> | 0.92–0.98<!--m:zoomed_background.tophat.x1.kept_range--> |
| 1.5<!--n:value tried--> | 0.61–1.00<!--m:zoomed_background.trendfill.x1.5.kept_range--> | 0.89–1.00<!--m:zoomed_background.spline1d.x1.5.kept_range--> | 0.83–0.95<!--m:zoomed_background.tophat.x1.5.kept_range--> |
| 2<!--n:value tried--> | 0.32–1.00<!--m:zoomed_background.trendfill.x2.kept_range--> | 0.63–1.00<!--m:zoomed_background.spline1d.x2.kept_range--> | 0.64–0.83<!--m:zoomed_background.tophat.x2.kept_range--> |
| 3<!--n:value tried--> | 0.13–0.96<!--m:zoomed_background.trendfill.x3.kept_range--> | 0.26–0.99<!--m:zoomed_background.spline1d.x3.kept_range--> | 0.31–0.49<!--m:zoomed_background.tophat.x3.kept_range--> |
| 4<!--n:value tried--> | 0.08–0.18<!--m:zoomed_background.trendfill.x4.kept_range--> | 0.13–0.93<!--m:zoomed_background.spline1d.x4.kept_range--> | 0.17–0.28<!--m:zoomed_background.tophat.x4.kept_range--> |

`background_warnings` (`lib/pipeline.py`) was checked on every run; a run it
warned on with a suggested setting was analyzed again with that setting.

| Zoom | Runs | Kept below 0.9<!--n:definition--> | of which not warned | Warned | Warned with 0.97<!--n:definition--> or more kept |
|---|---|---|---|---|---|
| 1<!--n:value tried--> | 18<!--m:zoomed_background.x1.runs--> | 0<!--m:zoomed_background.x1.below_90--> | 0<!--m:zoomed_background.x1.below_90_unwarned--> | 3<!--m:zoomed_background.x1.warned--> | 2<!--m:zoomed_background.x1.warned_above_97--> |
| 1.5<!--n:value tried--> | 18<!--m:zoomed_background.x1.5.runs--> | 7<!--m:zoomed_background.x1.5.below_90--> | 1<!--m:zoomed_background.x1.5.below_90_unwarned--> | 10<!--m:zoomed_background.x1.5.warned--> | 1<!--m:zoomed_background.x1.5.warned_above_97--> |
| 2<!--n:value tried--> | 18<!--m:zoomed_background.x2.runs--> | 12<!--m:zoomed_background.x2.below_90--> | 0<!--m:zoomed_background.x2.below_90_unwarned--> | 12<!--m:zoomed_background.x2.warned--> | 0<!--m:zoomed_background.x2.warned_above_97--> |
| 3<!--n:value tried--> | 18<!--m:zoomed_background.x3.runs--> | 15<!--m:zoomed_background.x3.below_90--> | 2<!--m:zoomed_background.x3.below_90_unwarned--> | 15<!--m:zoomed_background.x3.warned--> | 1<!--m:zoomed_background.x3.warned_above_97--> |
| 4<!--n:value tried--> | 18<!--m:zoomed_background.x4.runs--> | 17<!--m:zoomed_background.x4.below_90--> | 3<!--m:zoomed_background.x4.below_90_unwarned--> | 15<!--m:zoomed_background.x4.warned--> | 0<!--m:zoomed_background.x4.warned_above_97--> |

A warning that no fiber width could be measured carries no setting to follow;
28<!--m:zoomed_background.warned_without_advice--> of the 55<!--m:zoomed_background.warned--> warned runs had only that. Analyzed again as suggested, the other warned
runs kept 0.51–1.01<!--m:zoomed_background.followed.kept_range--> of their height, with the background error's 95<!--n:definition-->th percentile at most
0.24<!--m:zoomed_background.followed.bg95_max--> nm, and 4<!--m:zoomed_background.followed.still_warned--> of them were warned on again; the lowest, 0.51<!--m:zoomed_background.x4.followed_kept_range[0]-->, is the one run at a zoom
of 4<!--n:value tried--> that carried a suggestion. Of the runs that kept less than 0.9<!--n:definition--> of their height, the
warning missed 1<!--m:zoomed_background.x1.5.below_90_unwarned--> at a zoom of 1.5<!--n:value tried-->, 2<!--m:zoomed_background.x3.below_90_unwarned--> at 3<!--n:value tried--> and 3<!--m:zoomed_background.x4.below_90_unwarned--> at 4<!--n:value tried-->. §1.10 separates the warnings that
predict from the apparent width from those that measure the calibrated image.

### 1.9 Synthetic fibers of known height

No bundled scan has a known fiber height, so straight fibers of known height
were drawn and analyzed (experiment synthetic_height): three parallel cylinders
of diameter $D$ = 2<!--n:value tried-->, 4<!--n:value tried--> or 8<!--n:value tried--> nm under a spherical probe apex of radius 15<!--c:scripts/synthetic_suite.py::TIP--> nm, in scans
of 320<!--n:value tried--> × 320<!--n:value tried--> px at 1<!--n:value tried-->, 2<!--n:value tried-->, 5<!--n:value tried--> and 10<!--n:value tried--> nm pixels, with the tilt, roughness and line noise of
the synthetic suite and pixel noise of 0.05<!--n:value tried--> or 0.2<!--n:value tried--> nm. The probe's cross-section of
each cylinder is evaluated at every pixel centre, as a scan samples the
surface. Three quantities are read on the middle 80<!--n:definition--> % of each fiber and divided
by $D$: the height the pixel grid can show (the fiber-only image at the pixels
nearest the axis), the height background calibration removed at those pixels
(the median of the fiber-only image minus the calibrated image), and the
reported height (the median of the traced fibers' height samples). With
`trendfill` and 0.05<!--n:value tried--> nm noise:

| Pixel size | $D$ | $W$ | Pixel grid shows | Removed | Reported |
|---|---|---|---|---|---|
| 1<!--n:value tried--> nm | 2<!--n:value tried--> nm | 11.1<!--m:synthetic_height.px1.d2.w_px--> px | 1.00<!--m:synthetic_height.px1.d2.n0.05.peak--> | 0.13<!--m:synthetic_height.trendfill.px1.d2.n0.05.bg_loss--> | 0.94<!--m:synthetic_height.trendfill.px1.d2.n0.05.height--> |
| 1<!--n:value tried--> nm | 4<!--n:value tried--> nm | 16.0<!--m:synthetic_height.px1.d4.w_px--> px | 1.00<!--m:synthetic_height.px1.d4.n0.05.peak--> | 0.53<!--m:synthetic_height.trendfill.px1.d4.n0.05.bg_loss--> | – |
| 1<!--n:value tried--> nm | 8<!--n:value tried--> nm | 23.3<!--m:synthetic_height.px1.d8.w_px--> px | 1.00<!--m:synthetic_height.px1.d8.n0.05.peak--> | 0.84<!--m:synthetic_height.trendfill.px1.d8.n0.05.bg_loss--> | – |
| 2<!--n:value tried--> nm | 2<!--n:value tried--> nm | 5.6<!--m:synthetic_height.px2.d2.w_px--> px | 0.99<!--m:synthetic_height.px2.d2.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d2.n0.05.bg_loss--> | 1.02<!--m:synthetic_height.trendfill.px2.d2.n0.05.height--> |
| 2<!--n:value tried--> nm | 4<!--n:value tried--> nm | 8.0<!--m:synthetic_height.px2.d4.w_px--> px | 1.00<!--m:synthetic_height.px2.d4.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d4.n0.05.bg_loss--> | 1.02<!--m:synthetic_height.trendfill.px2.d4.n0.05.height--> |
| 2<!--n:value tried--> nm | 8<!--n:value tried--> nm | 11.7<!--m:synthetic_height.px2.d8.w_px--> px | 1.00<!--m:synthetic_height.px2.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px2.d8.n0.05.bg_loss--> | 1.01<!--m:synthetic_height.trendfill.px2.d8.n0.05.height--> |
| 5<!--n:value tried--> nm | 2<!--n:value tried--> nm | 2.2<!--m:synthetic_height.px5.d2.w_px--> px | 0.96<!--m:synthetic_height.px5.d2.n0.05.peak--> | 0.01<!--m:synthetic_height.trendfill.px5.d2.n0.05.bg_loss--> | 0.97<!--m:synthetic_height.trendfill.px5.d2.n0.05.height--> |
| 5<!--n:value tried--> nm | 4<!--n:value tried--> nm | 3.2<!--m:synthetic_height.px5.d4.w_px--> px | 0.98<!--m:synthetic_height.px5.d4.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px5.d4.n0.05.bg_loss--> | 0.99<!--m:synthetic_height.trendfill.px5.d4.n0.05.height--> |
| 5<!--n:value tried--> nm | 8<!--n:value tried--> nm | 4.7<!--m:synthetic_height.px5.d8.w_px--> px | 0.99<!--m:synthetic_height.px5.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px5.d8.n0.05.bg_loss--> | 1.00<!--m:synthetic_height.trendfill.px5.d8.n0.05.height--> |
| 10<!--n:value tried--> nm | 2<!--n:value tried--> nm | 1.1<!--m:synthetic_height.px10.d2.w_px--> px | 0.85<!--m:synthetic_height.px10.d2.n0.05.peak--> | 0.01<!--m:synthetic_height.trendfill.px10.d2.n0.05.bg_loss--> | – |
| 10<!--n:value tried--> nm | 4<!--n:value tried--> nm | 1.6<!--m:synthetic_height.px10.d4.w_px--> px | 0.93<!--m:synthetic_height.px10.d4.n0.05.peak--> | 0.01<!--m:synthetic_height.trendfill.px10.d4.n0.05.bg_loss--> | 0.89<!--m:synthetic_height.trendfill.px10.d4.n0.05.height--> |
| 10<!--n:value tried--> nm | 8<!--n:value tried--> nm | 2.3<!--m:synthetic_height.px10.d8.w_px--> px | 0.97<!--m:synthetic_height.px10.d8.n0.05.peak--> | 0.00<!--m:synthetic_height.trendfill.px10.d8.n0.05.bg_loss--> | 0.97<!--m:synthetic_height.trendfill.px10.d8.n0.05.height--> |

A dash marks a run whose traced lines do not follow the fibers, so their
height samples are not a height of the fiber. At 1<!--n:value tried--> nm pixels with $D$ = 4<!--n:value tried--> and
8<!--n:value tried--> nm the calibrated fibers are hollowed, and the traced lines loop inside them or
miss them; at 10<!--n:value tried--> nm pixels the 2<!--n:value tried--> nm fibers are visible in the calibrated image but
traced over only 0.15<!--m:synthetic_height.trendfill.px10.d2.n0.05.traced--> of their length (both viewed on the calibrated images).

Over all three methods and both noise levels: at 2<!--n:value tried--> nm pixels, where the fibers
span 5.6<!--m:synthetic_height.px2.d2.w_px-->–11.7<!--m:synthetic_height.px2.d8.w_px--> px (the bundled scans' fibers span 7.5<!--m:zoomed_background.hplantTOC.width_px-->–8.6<!--m:zoomed_background.NDTOC.width_px--> px, §1.8), calibration
removed between −0.01<!--m:synthetic_height.px2.removed_range[0]--> and 0.03<!--m:synthetic_height.px2.removed_range[1]--> of the height and the reported height was
0.98–1.05<!--m:synthetic_height.px2.height_range--> of it. At 5<!--n:value tried--> and 10<!--n:value tried--> nm pixels calibration removed at most 0.02<!--m:synthetic_height.coarse.removed_max-->; there
the pixel grid limits the height, showing 0.96–0.99<!--m:synthetic_height.px5.peak_range--> of it at 5<!--n:value tried--> nm and
0.85–0.97<!--m:synthetic_height.px10.peak_range--> at 10<!--n:value tried--> nm, because the narrow top of the fiber falls between pixel
centres. At 1<!--n:value tried--> nm pixels every method removed part of the fibers (ranges over
$D$, at 0.05<!--n:value tried--> and 0.2<!--n:value tried--> nm noise): `trendfill` 0.13–0.84<!--m:synthetic_height.px1.trendfill.n0.05.removed_range--> and 0.70–0.95<!--m:synthetic_height.px1.trendfill.n0.2.removed_range-->, `tophat`
0.07–0.53<!--m:synthetic_height.px1.tophat.n0.05.removed_range--> and 0.10–0.55<!--m:synthetic_height.px1.tophat.n0.2.removed_range-->, `spline1d` 0.01–0.46<!--m:synthetic_height.px1.spline1d.n0.05.removed_range--> and 0.38–0.90<!--m:synthetic_height.px1.spline1d.n0.2.removed_range-->. How `background_warnings` fared on these runs is
in §1.10.

### 1.10 Predicted and measured background warnings

`background_warnings` (`lib/pipeline.py`) raises two kinds of warning. Three
compare the apparent width with the limits of §1.8 and so predict a loss:
`element_small`, `flank_step_low` and `width_unchecked`. Two measure the
calibrated image. `relief_absorbed` fires when, on the fiber mask, 0.1<!--c:lib/pipeline.py::_MAX_ABSORBED_FRACTION--> or more
of the relief the input showed was subtracted as background standing above the
background beside the mask (within 2<!--c:lib/pipeline.py::_ABSORBED_RING_WIDTHS--> apparent widths of it, averaged over 3<!--c:lib/pipeline.py::_ABSORBED_SMOOTH_WIDTHS--> widths);
`width_unmeasured` fires when no apparent width could be measured for most
components, so that no other check could run. The two lengths and the limit
were chosen by looking at the runs below, so these runs served as a development
set rather than an independent test.

A run counts as losing height when it lost more than 0.1<!--n:definition--> of it and as sound when
it lost less than 0.03<!--n:definition-->:

| Runs | Losing height | Sound | Predicted: caught | Predicted: on sound runs | Measured: caught | Measured: on sound runs | Either: caught | Either: on sound runs |
|---|---|---|---|---|---|---|---|---|
| Known-height fibers at 23<!--n:value tried-->° (§1.9) | 14<!--m:synthetic_height.lossy--> | 54<!--m:synthetic_height.sound--> | 7<!--m:synthetic_height.predicted.caught--> | 13<!--m:synthetic_height.predicted.false--> | 13<!--m:synthetic_height.measured.caught--> | 0<!--m:synthetic_height.measured.false--> | 14<!--m:synthetic_height.any.caught--> | 13<!--m:synthetic_height.any.false--> |
| The same at 0.05<!--n:value tried--> nm noise in four orientations | 20<!--m:synthetic_height_orientation.lossy--> | 103<!--m:synthetic_height_orientation.sound--> | 7<!--m:synthetic_height_orientation.predicted.caught--> | 19<!--m:synthetic_height_orientation.predicted.false--> | 18<!--m:synthetic_height_orientation.measured.caught--> | 1<!--m:synthetic_height_orientation.measured.false--> | 19<!--m:synthetic_height_orientation.any.caught--> | 20<!--m:synthetic_height_orientation.any.false--> |
| Zoomed bundled scans (§1.8) | 51<!--m:zoomed_background.tally.lossy--> | 27<!--m:zoomed_background.tally.sound--> | 19<!--m:zoomed_background.tally.predicted.caught--> | 3<!--m:zoomed_background.tally.predicted.false--> | 44<!--m:zoomed_background.tally.measured.caught--> | 1<!--m:zoomed_background.tally.measured.false--> | 45<!--m:zoomed_background.tally.any.caught--> | 4<!--m:zoomed_background.tally.any.false--> |

The four orientations are 0<!--n:value tried-->, 23<!--n:value tried-->, 45<!--n:value tried--> and 90<!--n:value tried-->° to the scan lines (experiment
synthetic_height_orientation). The measured warnings flagged 1<!--m:synthetic_height_orientation.measured.false_axis_parallel--> sound
run there, with its fibers parallel to an image axis: 90<!--n:value tried-->° at 1<!--n:value tried--> nm pixels, with
`spline1d`, flagged because no width could be measured. Rendered, the
calibrated fibers keep their height, but the traced lines break into loops and
fragments inside them, so the warning that no width could be measured is true
there although the trouble lies after calibration.

### 1.11 Scan-line offsets under `tophat`

`tophat` removes less of the height offsets between scan lines than `trendfill`.
The step between adjacent scan lines was measured as the median absolute
difference between the median heights of adjacent rows, each row's median taken
over its lowest 60<!--n:definition--> % of pixels so that the fibers stay out of it, after a
least-squares plane is removed (experiment line_steps):

| Scan | Raw | `trendfill` | `tophat` |
|---|---|---|---|
| higher-plant TOC | 0.020<!--m:line_steps.hplantTOC.raw_nm--> nm | 0.004<!--m:line_steps.hplantTOC.trendfill_nm--> nm | 0.018<!--m:line_steps.hplantTOC.tophat_nm--> nm |
| tunicate CNF | 0.044<!--m:line_steps.tunicate.raw_nm--> nm | 0.005<!--m:line_steps.tunicate.trendfill_nm--> nm | 0.013<!--m:line_steps.tunicate.tophat_nm--> nm |
| Bruker NDTOC | 0.042<!--m:line_steps.NDTOC.raw_nm--> nm | 0.007<!--m:line_steps.NDTOC.trendfill_nm--> nm | 0.020<!--m:line_steps.NDTOC.tophat_nm--> nm |

`trendfill` left 0.11<!--m:line_steps.trendfill.over_raw_range[0]-->–0.19<!--m:line_steps.trendfill.over_raw_range[1]--> of the raw step and `tophat` 0.30<!--m:line_steps.tophat.over_raw_range[0]-->–0.93<!--m:line_steps.tophat.over_raw_range[1]-->,
2.8<!--m:line_steps.tophat_over_trendfill_range[0]-->–4.8<!--m:line_steps.tophat_over_trendfill_range[1]--> times as much as `trendfill`. Rendered with the contrast set on the
background, the `tophat` images of all three scans carry the horizontal stripes
of the raw scans, and a dark band across the tunicate scan that `trendfill`
removes is left by `tophat`. `background_warnings` suggests `tophat` when
`trendfill` or `spline1d` loses fiber height (§1.8), so following that
suggestion keeps the fibers' height at the cost of these stripes.

## 2. Binarization

See [Analysis algorithms](algorithms.md) §2.

### 2.1 The edge map of the linearity filter

Up to 1.0.0 the edge map was built from the whole mask inside the bounding box.
On all 3<!--m:hough_edge_map.identical--> bundled scans the final binarized mask is bit-identical either way
(experiment hough_edge_map).

### 2.2 Ridge recovery

On the tunicate scan 99.8<!--m:ridge_hysteresis.ridge.far_below_low_percent--> % of the pixels at least 10<!--n:value tried--> px from the
binarized mask lie below the low level of the hysteresis on the ridge response
(experiment ridge_hysteresis).

### 2.3 Closing

The closing joins mask components across gaps of up to
2<!--m:closing_gaps.thick3.largest_gap_joined_px--> px when they are at least 3<!--n:value tried--> px thick; it joins no gap between lines 1<!--n:value tried--> px
thick (0<!--m:closing_gaps.thick1.gaps_joined--> of 3<!--n:count--> gaps tried; experiment closing_gaps).

### 2.4 The local threshold

Binarizing with the global threshold alone, everything else at the defaults,
changes the masks as follows (experiment local_threshold). The mean mask width
is the area of the final mask over the length of the final skeleton; the two
heights are medians, as a percentage of the highest height within 3<!--n:definition--> px.

| Scan | Mean mask width, global alone → both (px) | Mask components | Branch points of the final skeleton | Height of the pixels the local threshold removes / keeps (%) |
|---|---|---|---|---|
| tunicate CNF | 15.6<!--m:local_threshold.tunicate.global.mask_width_px--> → 10.1<!--m:local_threshold.tunicate.both.mask_width_px--> | 1<!--m:local_threshold.tunicate.global.mask_components--> → 11<!--m:local_threshold.tunicate.both.mask_components--> | 69<!--m:local_threshold.tunicate.global.branch_points--> → 33<!--m:local_threshold.tunicate.both.branch_points--> | 25<!--m:local_threshold.tunicate.removed_percent_of_crest--> / 83<!--m:local_threshold.tunicate.kept_percent_of_crest--> |
| higher-plant TOC | 12.0<!--m:local_threshold.hplantTOC.global.mask_width_px--> → 8.5<!--m:local_threshold.hplantTOC.both.mask_width_px--> | 12<!--m:local_threshold.hplantTOC.global.mask_components--> → 12<!--m:local_threshold.hplantTOC.both.mask_components--> | 6<!--m:local_threshold.hplantTOC.global.branch_points--> → 5<!--m:local_threshold.hplantTOC.both.branch_points--> | 34<!--m:local_threshold.hplantTOC.removed_percent_of_crest--> / 75<!--m:local_threshold.hplantTOC.kept_percent_of_crest--> |
| Bruker NDTOC | 12.9<!--m:local_threshold.NDTOC.global.mask_width_px--> → 9.5<!--m:local_threshold.NDTOC.both.mask_width_px--> | 22<!--m:local_threshold.NDTOC.global.mask_components--> → 24<!--m:local_threshold.NDTOC.both.mask_components--> | 156<!--m:local_threshold.NDTOC.global.branch_points--> → 76<!--m:local_threshold.NDTOC.both.branch_points--> | 35<!--m:local_threshold.NDTOC.removed_percent_of_crest--> / 72<!--m:local_threshold.NDTOC.kept_percent_of_crest--> |

Rendered over the height images of all 3<!--m:kink_reference.scans--> bundled scans, the pixels the local threshold removes are the
lower flanks of the fibers; where a fiber lies alone, the only effect is a
narrower mask. The joining described next was seen on the tunicate and Bruker
scans, where fibers run close together or over a textured background. With the global
threshold alone, two fibers running close together joined through their flanks
into one component and the skeleton ran between them; on the tunicate scan the
whole network formed a single component. On the Bruker scan, the worm-like
texture of the background touched the fibers' flanks, joined their masks, and
left side branches on the skeleton; with the local threshold those patches came
apart from the fibers and the later filters of the binarization removed them.

### 2.5 The linearity filter

On the 3<!--m:linearity_filter.inputs--> test inputs (experiment linearity_filter), $s_{	ext{ratio}}$ reached
5.16<!--m:linearity_filter.s_ratio_max-->, and 159<!--m:linearity_filter.s_ratio_above_one--> components scored $s_{	ext{ratio}} > 1$. The filter removed
160<!--m:linearity_filter.removed_reaching_h_length--> components whose largest extent reaches `h_length`; each was rendered over the
calibrated height image and judged by eye. Most were background texture,
particles and the scan-line glitches of the higher-plant scan, but 2<!--m:linearity_filter.removed_fiber_pieces-->
were pieces of real fibers: a short bent piece reaching the image border on the
tunicate scan, and a fiber end cut by the image border on the Bruker scan.

On a synthetic band along the rows (area 865<!--m:linearity_filter.band.horizontal.area--> pixels), Canny found
264<!--m:linearity_filter.band.horizontal.edge_pixels--> edge pixels in the bounding-box crop with the filter's one-pixel margin and
14<!--m:linearity_filter.band.horizontal.edge_pixels_unpadded--> without it, all of those at the rounded ends; the score was
1.39<!--m:linearity_filter.band.horizontal.s_ratio-->, and the band was kept. The same band at 45<!--n:definition-->° (area 620<!--m:linearity_filter.band.diagonal.area--> pixels)
gave 364<!--m:linearity_filter.band.diagonal.edge_pixels--> edge pixels (356<!--m:linearity_filter.band.diagonal.edge_pixels_unpadded--> without the margin) and a score of
1.81<!--m:linearity_filter.band.diagonal.s_ratio--> and was kept.

The two straightest clearly visible fibers under 1000<!--n:literal in the quoted code--> px on the Bruker scan
(experiment linearity_axis_fibers) were analyzed as scanned and with the whole
scan rotated so that the principal axis of each fiber's component runs along
the columns and, turned a further 90<!--n:definition-->°, along the rows. The fifth column counts
the outline pixels lying on the sides of the bounding box, which Canny finds
only because of the margin. Where the filter tested them, it kept them:

| Fiber | View | Area (px) | Outline pixels | of which on the box's sides | $s_{	ext{ratio}}$ |
|---|---|---|---|---|---|
| first | as scanned, axis at 91.1<!--m:linearity_axis_fibers.a.original_axis_deg-->° | 871<!--m:linearity_axis_fibers.a.original.area--> | 300<!--m:linearity_axis_fibers.a.original.outline_px--> | 22<!--m:linearity_axis_fibers.a.original.outline_on_box_sides_px--> | 2.52<!--m:linearity_axis_fibers.a.original.s_ratio--> |
| second | as scanned, axis at 63.4<!--m:linearity_axis_fibers.b.original_axis_deg-->° | 482<!--m:linearity_axis_fibers.b.original.area--> | 177<!--m:linearity_axis_fibers.b.original.outline_px--> | 18<!--m:linearity_axis_fibers.b.original.outline_on_box_sides_px--> | 1.28<!--m:linearity_axis_fibers.b.original.s_ratio--> |
| second | along the columns | 574<!--m:linearity_axis_fibers.b.columns.area--> | 247<!--m:linearity_axis_fibers.b.columns.outline_px--> | 36<!--m:linearity_axis_fibers.b.columns.outline_on_box_sides_px--> | 1.83<!--m:linearity_axis_fibers.b.columns.s_ratio--> |
| second | along the rows | 685<!--m:linearity_axis_fibers.b.rows.area--> | 339<!--m:linearity_axis_fibers.b.rows.outline_px--> | 19<!--m:linearity_axis_fibers.b.rows.outline_on_box_sides_px--> | 3.16<!--m:linearity_axis_fibers.b.rows.s_ratio--> |

Rotated, the first fiber joined the background texture beside it, and its
component reached 1349<!--m:linearity_axis_fibers.a.columns.area--> and 1367<!--m:linearity_axis_fibers.a.rows.area--> px, which the filter does not test. Every view
of both fibers stayed in the final binarized mask (viewed on the calibrated
image). This is two fibers of one scan.

How far the verdict on a straight shape still depends on its angle was measured
on synthetic rods with round ends, drawn at every 5<!--n:value tried-->° from 0<!--n:value tried-->° to 90<!--n:value tried-->° with
3<!--n:value tried--> random sub-pixel placements each and passed alone through the filter
(experiment linearity_rotated_rods). The table gives how many of the
57<!--m:linearity_rotated_rods.placements--> placements of each rod were kept:

| Width (px) | 16<!--n:value tried--> px long | 20<!--n:value tried--> | 22<!--n:value tried--> | 24<!--n:value tried--> | 26<!--n:value tried--> | 28<!--n:value tried--> | 32<!--n:value tried--> | 40<!--n:value tried--> |
|---|---|---|---|---|---|---|---|---|
| 3<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w3.l16.kept--> | 20<!--m:linearity_rotated_rods.w3.l20.kept--> | 46<!--m:linearity_rotated_rods.w3.l22.kept--> | 57<!--m:linearity_rotated_rods.w3.l24.kept--> | 57<!--m:linearity_rotated_rods.w3.l26.kept--> | 57<!--m:linearity_rotated_rods.w3.l28.kept--> | 57<!--m:linearity_rotated_rods.w3.l32.kept--> | 57<!--m:linearity_rotated_rods.w3.l40.kept--> |
| 5<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w5.l16.kept--> | 12<!--m:linearity_rotated_rods.w5.l20.kept--> | 37<!--m:linearity_rotated_rods.w5.l22.kept--> | 52<!--m:linearity_rotated_rods.w5.l24.kept--> | 56<!--m:linearity_rotated_rods.w5.l26.kept--> | 57<!--m:linearity_rotated_rods.w5.l28.kept--> | 57<!--m:linearity_rotated_rods.w5.l32.kept--> | 57<!--m:linearity_rotated_rods.w5.l40.kept--> |
| 7<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w7.l16.kept--> | 8<!--m:linearity_rotated_rods.w7.l20.kept--> | 22<!--m:linearity_rotated_rods.w7.l22.kept--> | 50<!--m:linearity_rotated_rods.w7.l24.kept--> | 56<!--m:linearity_rotated_rods.w7.l26.kept--> | 57<!--m:linearity_rotated_rods.w7.l28.kept--> | 57<!--m:linearity_rotated_rods.w7.l32.kept--> | 57<!--m:linearity_rotated_rods.w7.l40.kept--> |
| 9<!--n:value tried--> | 0<!--m:linearity_rotated_rods.w9.l16.kept--> | 5<!--m:linearity_rotated_rods.w9.l20.kept--> | 11<!--m:linearity_rotated_rods.w9.l22.kept--> | 30<!--m:linearity_rotated_rods.w9.l24.kept--> | 52<!--m:linearity_rotated_rods.w9.l26.kept--> | 57<!--m:linearity_rotated_rods.w9.l28.kept--> | 57<!--m:linearity_rotated_rods.w9.l32.kept--> | 57<!--m:linearity_rotated_rods.w9.l40.kept--> |

A rod was kept at every placement from 24<!--m:linearity_rotated_rods.w3.shortest_always_kept--> px long at a width of 3<!--n:value tried--> px and from
28<!--m:linearity_rotated_rods.w9.shortest_always_kept--> px at the other widths, and at none 16<!--m:linearity_rotated_rods.w9.longest_never_kept--> px long. In between, whether it was
kept depended on its angle and placement.

### 2.6 Components the linearity filter does not test

The linearity filter keeps components of 1000<!--n:literal in the quoted code--> pixels or more without testing them.
Each test input was filtered as the code does and with every component tested
(experiment linearity_large_exemption, which also records the wall times of
both runs):

| Input | Components of 1000<!--n:literal in the quoted code--> px or more | Of those, removed if tested |
|---|---|---|
| tunicate CNF | 9<!--m:linearity_large_exemption.tunicate.large_components--> | 0<!--m:linearity_large_exemption.tunicate.large_removed_if_tested--> |
| higher-plant TOC | 4<!--m:linearity_large_exemption.hplantTOC.large_components--> | 0<!--m:linearity_large_exemption.hplantTOC.large_removed_if_tested--> |
| Bruker NDTOC | 15<!--m:linearity_large_exemption.NDTOC.large_components--> | 0<!--m:linearity_large_exemption.NDTOC.large_removed_if_tested--> |
On no input would testing the large components have removed any of them, while
testing them made the filter take several times longer, and over ten times
longer on the tunicate scan, because the Hough transform of a large crop is slow. A large
non-linear object, such as a big contamination blob, is still kept untested.

## 3. Skeletonization

See [Analysis algorithms](algorithms.md) §3.

### 3.1 Thinning at the image border

On the bundled scans, without the replicated border, the last 5<!--n:definition--> points of
tracks that run off the image lie a median 3.9<!--m:border_drift.plain.end_median_px--> px from the height crest along
their normal, against 0.9<!--m:border_drift.plain.middle_median_px--> px in the middle of fibers; with it, the ends lie
1.1<!--m:border_drift.padded.end_median_px--> px from the crest (experiment border_drift). On all 3<!--m:border_padding.identical_inside_band--> bundled scans the
skeleton outside a 12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px border band was identical with and without the
correction (experiment border_padding), but that is not a guarantee.

### 3.2 `bp_height` against the fiber heights

The default `bp_height` of 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm lies above the median height under the
skeleton on every bundled scan (1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> to 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm, §1.1). At the branch points of
the first skeleton (experiment branch_pruning) the median height is 9.2<!--m:branch_pruning.tunicate.bp_height_median_nm--> nm on
the tunicate scan, where 41<!--m:branch_pruning.tunicate.bp_at_or_above_percent--> % of the branch points reach `bp_height`. On the other
scans none does (median 1.8<!--m:branch_pruning.hplantTOC.bp_height_median_nm--> nm on the higher-plant scan, 2.0<!--m:branch_pruning.NDTOC.bp_height_median_nm--> nm on the Bruker
scan): every branch point is low, and
the split by height does nothing there.

Rendered on the tunicate height image, the branch points at or above `bp_height`
lie where two fibers cross or one joins another, where the heights of two
overlapping fibers add up. The branch points below it include crossings and
junctions as well, for instance of the thinner fibers in the tangle at the
bottom of the scan, so on this scan a low branch point is not a sign of a
spurious branch.

The height-gated pruning changes little in the final skeleton. Skipping it
changes 1<!--m:branch_pruning.tunicate.skipped.final_changed_pixels--> of 8075<!--m:branch_pruning.tunicate.final_pixels--> skeleton pixels on the tunicate scan,
10<!--m:branch_pruning.hplantTOC.skipped.final_changed_pixels--> of 2076<!--m:branch_pruning.hplantTOC.final_pixels--> on the higher-plant scan and 200<!--m:branch_pruning.NDTOC.skipped.final_changed_pixels--> of 9183<!--m:branch_pruning.NDTOC.final_pixels--> on the Bruker scan; treating every branch point as low changes
0<!--m:branch_pruning.tunicate.all_low.final_changed_pixels--> pixels on the tunicate scan. The short arms it removes are removed again
by the spur pruning of [Analysis algorithms](algorithms.md) §3.5, which judges by
length alone: with the spur pruning switched off, skipping the height-gated
pruning changes 133<!--m:branch_pruning.tunicate.spurs_off.skipped.final_changed_pixels-->, 159<!--m:branch_pruning.hplantTOC.spurs_off.skipped.final_changed_pixels--> and 974<!--m:branch_pruning.NDTOC.spurs_off.skipped.final_changed_pixels--> pixels on the same three scans.

### 3.3 Loop enclosures

On the bundled scans each loop left by an interior hole of the mask puts 1<!--m:loop_candidates.all.branch_points_range[0]--> to
4<!--m:loop_candidates.all.branch_points_range[1]--> branch points on its ring. Of the 18<!--m:loop_candidates.candidates--> enclosures small enough to qualify
for filling, judged by eye on the height image, 8<!--m:loop_candidates.fiber.count--> lie in a fiber, 8<!--m:loop_candidates.crossing.count--> at a crossing,
and 1<!--m:loop_candidates.gap.count--> on the tunicate scan is a sliver enclosed by two distinct fibers, which run
side by side with a groove between them and touch at both ends; the remaining
1<!--m:loop_candidates.particle.count--> lies inside a particle at the end of a faint strand on the Bruker scan. The median
interior height is 83<!--m:loop_candidates.all.ratio_percent_range[0]-->–105<!--m:loop_candidates.all.ratio_percent_range[1]--> % of the surrounding ridge's median for every one of
them, and the sliver's 83<!--m:loop_candidates.gap.ratio_percent_range[0]--> % lies inside that range, just above a loop artefact inside a fiber (experiment loop_candidates), so no
threshold on this ratio fills every loop artefact and keeps the sliver. The sliver
is filled too, and, rendered, the two fibers are joined into one line running down
the groove. More such slivers were built synthetically (§3.4).

### 3.4 Two fibers enclosing a sliver

On 24<!--m:loop_sliver.scans--> synthetic scans of two straight fibers that part into a lens-shaped
gap and rejoin (Gaussian sections 4<!--n:value tried--> nm high with standard deviations of 1.5<!--n:value tried-->, 2<!--n:value tried-->
and 3<!--n:value tried--> px, gaps of 4<!--n:value tried--> to 12<!--n:value tried--> px; experiment loop_sliver), 6<!--m:loop_sliver.candidates--> enclosures were small
enough for `collapse_skeleton_loops` to consider. Their median interior height
was 53<!--m:loop_sliver.ratio_percent_range[0]-->–97<!--m:loop_sliver.ratio_percent_range[1]--> % of the surrounding ridge's, because the flanks of two close
fibers overlap, so all 6<!--m:loop_sliver.filled--> passed the 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> guard and were filled; rendered,
the two fibers were then joined into one line running down the middle of the
gap. Wider gaps enclosed more than `max_loop_area` and kept both fibers. On these
scans the guard never stopped a fill.

### 3.5 The border margins of the two prunings

The branch pruning (§3.3 of the algorithm page) skips endpoints within
`branch_length` (12<!--c:lib/pipeline.py::ProcParams.branch_length--> px) of the border, the spur pruning (§3.5 there) spares
arms within 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px. Each test input was skeletonized with one margin at a time
set to the other's value (experiment border_margins):

| Input | Branch pruning at 2<!--c:lib/skeletonizer.py::prune_short_spurs(border_margin)--> px: pixels changed | farthest from the border (px) | Spur pruning at 12<!--c:lib/pipeline.py::ProcParams.branch_length--> px: pixels changed | farthest from the border (px) |
|---|---|---|---|---|
| tunicate CNF | 0<!--m:border_margins.tunicate.branch_margin_2.changed_px--> | 0<!--m:border_margins.tunicate.branch_margin_2.farthest_from_border_px--> | 8<!--m:border_margins.tunicate.spur_margin_wide.changed_px--> | 12<!--m:border_margins.tunicate.spur_margin_wide.farthest_from_border_px--> |
| higher-plant TOC | 0<!--m:border_margins.hplantTOC.branch_margin_2.changed_px--> | 0<!--m:border_margins.hplantTOC.branch_margin_2.farthest_from_border_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.changed_px--> | 0<!--m:border_margins.hplantTOC.spur_margin_wide.farthest_from_border_px--> |
| Bruker NDTOC | 8<!--m:border_margins.NDTOC.branch_margin_2.changed_px--> | 7<!--m:border_margins.NDTOC.branch_margin_2.farthest_from_border_px--> | 21<!--m:border_margins.NDTOC.spur_margin_wide.changed_px--> | 13<!--m:border_margins.NDTOC.spur_margin_wide.farthest_from_border_px--> |
Rendered, the narrower branch-pruning margin removed short arms running into the
border, and the wider spur-pruning margin kept short spurs next to the border
that the code removes. Either way the change stays within a band along the
border; no reason for the two margins to differ was found.

### 3.6 The diagonal Y kernel of the branch-point search

`imp_tools.branchedPoints` matches the skeleton against hit-or-miss kernels. One
of them, the diagonal Y kernel, leaves 4<!--n:definition--> of its 9<!--n:definition--> cells free so that it catches Y
junctions at angles the axis-aligned kernels miss. On the default skeleton of
each test input (experiment diagonal_ybranch) it was the only kernel to find
53<!--m:diagonal_ybranch.all.only_diagonal_y--> of the 114<!--m:diagonal_ybranch.all.branch_points--> branch points: 15<!--m:diagonal_ybranch.tunicate.only_diagonal_y--> of 33<!--m:diagonal_ybranch.tunicate.branch_points--> on the tunicate scan, 3<!--m:diagonal_ybranch.hplantTOC.only_diagonal_y--> of 5<!--m:diagonal_ybranch.hplantTOC.branch_points--> on the
higher-plant TOC scan and 35<!--m:diagonal_ybranch.NDTOC.only_diagonal_y--> of 76<!--m:diagonal_ybranch.NDTOC.branch_points--> on the Bruker scan. Each pixel only this kernel finds has at least three
8<!--n:definition-->-connected skeleton neighbours (pixels with fewer: 0<!--m:diagonal_ybranch.all.only_diagonal_y_below_3_neighbours-->), so none of them lies on a
plain stretch of the skeleton, where a pixel has two.

## 4. Centerline and kinks

See [Analysis algorithms](algorithms.md) §4.

### 4.1 A straight fiber below a Y junction

Below a Y junction on the bundled higher-plant TOC scan, the earlier polyline
rule reads the skeleton as a 118<!--m:y_branch_kink.old_rule_angle_deg-->° "kink" on a fiber that does not bend
there; the current rule, on the centerline, reports 0<!--m:y_branch_kink.current_kinks_within_one_width--> kinks within one width
of it (experiment y_branch_kink).

### 4.2 Why the half-maximum midpoint at a quarter width

The default centerline, `"half_max_025w"`, was chosen from the comparisons of
this section and the next.

**Why the half-maximum midpoint.** The obvious alternative is the crest of each
cross-section, but a fibril with an anisotropic cross-section turns its tallest
edge to alternating sides as it twists. On the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> twisted ribbons of the
synthetic suite (rectangular sections of 4<!--n:value tried-->×2<!--n:value tried--> to 16<!--n:value tried-->×3<!--n:value tried--> nm on a straight
axis, drawn with a 10<!--c:scripts/synthetic_suite.py::RIBBON_TIP_NM--> nm probe), the crest strayed farthest from the axis of
the three lines measured (the default line, the quarter-height midpoint and the
crest) on 4<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> of them. Its root-mean-square lateral offset was 0.98<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->–1.48<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> times
that of the default line; the exception, at 0.98<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->, was the 10<!--n:value tried-->×3<!--n:value tried--> nm ribbon twisting
every 150<!--n:value tried--> nm, the shortest twist period of the suite. The kink rule reported 0<!--m:synthetic_centerline.ribbons.kinks_reported--> kinks on
the 6<!--m:synthetic_centerline.ribbons.count--> ribbon scans, which include a round control fiber (experiment
synthetic_centerline). A lower level was not uniformly better: the
quarter-height midpoint sat closer to the axis than the default line on 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> of
the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> ribbons, but background bumps pulled it up to 3.6<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm off the thin, round
control fiber.

**The probe apex.** How the swing depends on the probe was checked as follows.
Three of the ribbons (16<!--n:value tried-->×3<!--n:value tried-->, 10<!--n:value tried-->×3<!--n:value tried--> and 6<!--n:value tried-->×2<!--n:value tried--> nm, twist period
300<!--n:value tried--> nm) were drawn without noise, tilt or roughness and dilated by a spherical
apex of radius 0<!--n:value tried--> (no dilation), 10<!--n:value tried--> and 40<!--n:value tried--> nm, and each line was placed on the
pixel track of the true axis (experiment ribbon_tip_swing). The table gives the
root-mean-square lateral offset from the axis (nm) over the middle of the track.

| Ribbon (nm) | Apex radius (nm) | default line | quarter-height midpoint | centroid | crest |
|---|---|---|---|---|---|
| 16<!--n:value tried-->×3<!--n:value tried--> | 0<!--n:value tried--> | 1.48<!--m:ribbon_tip_swing.16x3.R0.half_max_025w.rms_nm--> | 0.69<!--m:ribbon_tip_swing.16x3.R0.quarter_max.rms_nm--> | 1.11<!--m:ribbon_tip_swing.16x3.R0.centroid.rms_nm--> | 2.99<!--m:ribbon_tip_swing.16x3.R0.crest.rms_nm--> |
| 16<!--n:value tried-->×3<!--n:value tried--> | 10<!--n:value tried--> | 3.40<!--m:ribbon_tip_swing.16x3.R10.half_max_025w.rms_nm--> | 2.37<!--m:ribbon_tip_swing.16x3.R10.quarter_max.rms_nm--> | 2.88<!--m:ribbon_tip_swing.16x3.R10.centroid.rms_nm--> | 4.49<!--m:ribbon_tip_swing.16x3.R10.crest.rms_nm--> |
| 16<!--n:value tried-->×3<!--n:value tried--> | 40<!--n:value tried--> | 3.31<!--m:ribbon_tip_swing.16x3.R40.half_max_025w.rms_nm--> | 3.24<!--m:ribbon_tip_swing.16x3.R40.quarter_max.rms_nm--> | 3.23<!--m:ribbon_tip_swing.16x3.R40.centroid.rms_nm--> | 3.24<!--m:ribbon_tip_swing.16x3.R40.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 0<!--n:value tried--> | 0.74<!--m:ribbon_tip_swing.10x3.R0.half_max_025w.rms_nm--> | 0.45<!--m:ribbon_tip_swing.10x3.R0.quarter_max.rms_nm--> | 0.66<!--m:ribbon_tip_swing.10x3.R0.centroid.rms_nm--> | 1.82<!--m:ribbon_tip_swing.10x3.R0.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 10<!--n:value tried--> | 1.97<!--m:ribbon_tip_swing.10x3.R10.half_max_025w.rms_nm--> | 1.54<!--m:ribbon_tip_swing.10x3.R10.quarter_max.rms_nm--> | 1.75<!--m:ribbon_tip_swing.10x3.R10.centroid.rms_nm--> | 2.67<!--m:ribbon_tip_swing.10x3.R10.crest.rms_nm--> |
| 10<!--n:value tried-->×3<!--n:value tried--> | 40<!--n:value tried--> | 2.05<!--m:ribbon_tip_swing.10x3.R40.half_max_025w.rms_nm--> | 1.96<!--m:ribbon_tip_swing.10x3.R40.quarter_max.rms_nm--> | 1.99<!--m:ribbon_tip_swing.10x3.R40.centroid.rms_nm--> | 2.08<!--m:ribbon_tip_swing.10x3.R40.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 0<!--n:value tried--> | 0.48<!--m:ribbon_tip_swing.6x2.R0.half_max_025w.rms_nm--> | 0.37<!--m:ribbon_tip_swing.6x2.R0.quarter_max.rms_nm--> | 0.43<!--m:ribbon_tip_swing.6x2.R0.centroid.rms_nm--> | 0.83<!--m:ribbon_tip_swing.6x2.R0.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 10<!--n:value tried--> | 1.25<!--m:ribbon_tip_swing.6x2.R10.half_max_025w.rms_nm--> | 1.06<!--m:ribbon_tip_swing.6x2.R10.quarter_max.rms_nm--> | 1.16<!--m:ribbon_tip_swing.6x2.R10.centroid.rms_nm--> | 1.64<!--m:ribbon_tip_swing.6x2.R10.crest.rms_nm--> |
| 6<!--n:value tried-->×2<!--n:value tried--> | 40<!--n:value tried--> | 1.32<!--m:ribbon_tip_swing.6x2.R40.half_max_025w.rms_nm--> | 1.27<!--m:ribbon_tip_swing.6x2.R40.quarter_max.rms_nm--> | 1.29<!--m:ribbon_tip_swing.6x2.R40.centroid.rms_nm--> | 1.37<!--m:ribbon_tip_swing.6x2.R40.crest.rms_nm--> |

Relative to the crest, the default line strayed 0.41<!--m:ribbon_tip_swing.R0.default_over_crest_range[0]-->–0.58<!--m:ribbon_tip_swing.R0.default_over_crest_range[1]--> times as far without
dilation, 0.74<!--m:ribbon_tip_swing.R10.default_over_crest_range[0]-->–0.76<!--m:ribbon_tip_swing.R10.default_over_crest_range[1]--> times at a 10<!--n:value tried--> nm apex and 0.97<!--m:ribbon_tip_swing.R40.default_over_crest_range[0]-->–1.02<!--m:ribbon_tip_swing.R40.default_over_crest_range[1]--> times at 40<!--n:value tried--> nm; at
40<!--n:value tried--> nm the default line, the quarter-height midpoint and the centroid all strayed
0.93<!--m:ribbon_tip_swing.R40.height_lines_over_crest_range[0]-->–1.02<!--m:ribbon_tip_swing.R40.height_lines_over_crest_range[1]--> times as far as the crest. On these three ribbons and three apex radii, the
blunter the apex, the closer the swing of each of these three lines came to
that of the crest.

**Why a quarter width.** The smoothing width sets how close two features may
lie before the centerline averages them into one. The test used the same-sense
corner pairs of the synthetic suite: 8<!--m:synthetic_centerline.pairs--> scans, each holding two
60<!--n:value tried-->° corners 1–3<!--n:value tried--> $W$ apart:

| Smoothing of the frame and offsets | Corner pairs judged as one bend | Median distance, corner vertex to centerline (range over the spacings) | Median distance to the true centerline |
|---|---|---|---|
| $W/2$ | 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> of 8<!--m:synthetic_centerline.pairs--> | 0.94<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[0]-->–1.13<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[1]--> px | 0.11<!--m:synthetic_centerline.pairs_w2.centerline_median_px--> px |
| $W/4$ (default) | 1<!--m:synthetic_centerline.pairs_w4.merged_pairs--> of 8<!--m:synthetic_centerline.pairs--> | 0.59<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[0]-->–0.89<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[1]--> px | 0.11<!--m:synthetic_centerline.pairs_w4.centerline_median_px--> px |

**Accuracy against known centerlines.** On the 60<!--m:synthetic_centerline.scans_af--> scans of groups A–F of the
synthetic suite, rendered with a spherical probe (corners, zigzags, corner
pairs, corners near an end, straight fibers, arcs, meanders, crossings and
junctions):

| | Median distance to the true centerline | 95<!--n:definition-->th percentile | Contour length error (range over groups of scans) |
|---|---|---|---|
| Half-maximum centerline | 0.11<!--m:synthetic_centerline.half_max_025w.median_px--> px | 0.37<!--m:synthetic_centerline.half_max_025w.p95_px--> px | −0.6<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[0]--> to +2.3<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[1]--> % |
| Skeleton track (corrected chain-code length) | 0.30<!--m:synthetic_centerline.skeleton_track.median_px--> px | 0.90<!--m:synthetic_centerline.skeleton_track.p95_px--> px | −0.7<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[0]--> to +3.8<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[1]--> % |

The contour length error is measured between the points of the true centerline
nearest the two ends of the measured line, so it leaves out the length the
ends add or lose; that is measured in §4.14.

These are the scenes the centerline and the kink rule were chosen on
(`scripts/synthetic_suite.py`), so, like the visual reference of §4.4, they
served as a development set rather than an independent test.

### 4.3 The selectable centerlines compared

Two caveats apply to the table:

- **Median distance** is, for each of the groups A–F of the synthetic suite, the
  median distance to the true centerline in nm; the column gives the range
  over the groups (experiment synthetic_centerline).
- **Real scans** scores a centerline against the visual reference with the
  excess-turning rule, as clear kinks found / missed / reported bends that
  match no marked kink. Detections displaced 1–2<!--n:definition--> widths from a mark (the
  "Found 1–2<!--n:definition--> widths from the mark" column of §4.4) and "merged" marks, where one
  detection spans two marks, are left out, so found and missed need not add up
  to 53<!--m:kink_reference.clear_marks-->. Only three centerlines were scored.

| `centerline_method` | Median distance (nm) | Real scans | Notes |
|---|---|---|---|
| `"half_max_025w"` (default) | 0.22<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[0]-->–0.24<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[1]--> | 50<!--m:kink_reference.default.found--> / 3<!--m:kink_reference.default.missed--> / 68<!--m:kink_reference.default.false--> | |
| `"half_max_05w"` | 0.19<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[0]-->–0.26<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[1]--> | 48<!--m:kink_reference.hm05.found--> / 4<!--m:kink_reference.hm05.missed--> / 45<!--m:kink_reference.hm05.false--> | The fewest unmatched bends of the three scored, but it merged the two corners of 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> of the 8<!--m:synthetic_centerline.pairs--> synthetic same-sense pairs (the default: 1<!--m:synthetic_centerline.pairs_w4.merged_pairs-->), and slightly stronger smoothing raised the misses to 10–12<!--m:kink_reference.hm05_stronger.missed_range-->. |
| `"skeleton_pixels"` | 0.54<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[0]-->–0.64<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[1]--> | 52<!--m:kink_reference.skeleton_pixels.found--> / 0<!--m:kink_reference.skeleton_pixels.missed--> / 140<!--m:kink_reference.skeleton_pixels.false--> | The staircase and the swing at junctions read as bends. |
| `"smoothed_skeleton_05w"`, `"smoothed_skeleton_1w"` | 0.37<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[0]-->–0.51<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[1]--> / 0.44<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[0]-->–0.95<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[1]--> | not scored | |
| `"quarter_max"` | 0.20<!--m:synthetic_centerline.quarter_max.group_median_nm_range[0]-->–0.25<!--m:synthetic_centerline.quarter_max.group_median_nm_range[1]--> | not scored | Closer to the axis than the default on 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> of the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> twisted ribbons, but pulled up to 3.6<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm off the thin, round control fiber. |
| `"centroid"` | 0.32<!--m:synthetic_centerline.centroid.group_median_nm_range[0]-->–0.39<!--m:synthetic_centerline.centroid.group_median_nm_range[1]--> | not scored | |
| `"crest"` | 0.43<!--m:synthetic_centerline.crest.group_median_nm_range[0]-->–0.48<!--m:synthetic_centerline.crest.group_median_nm_range[1]--> | not scored | The farthest from the axis on 4<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> of the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> twisted ribbons (0.98<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->–1.48<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> times as far as the default). |

### 4.4 The kink rule against the visual reference

"Unmatched" counts reported bends that match no marked kink; these are the
false detections referred to below.

| Rule | Found | Found 1–2<!--n:definition--> widths from the mark | Missed | Unmatched |
|---|---|---|---|---|
| Excess-turning rule, on the centerline | 50<!--m:kink_reference.default.found--> | 0<!--m:kink_reference.default.displaced--> | 3<!--m:kink_reference.default.missed--> | 68<!--m:kink_reference.default.false--> |
| Earlier polyline rule, on the skeleton track | 42<!--m:kink_reference.old_rule.found--> | 3<!--m:kink_reference.old_rule.displaced--> | 8<!--m:kink_reference.old_rule.missed--> | 77<!--m:kink_reference.old_rule.false--> |

The earlier rule's row applies `KinkDetector.kinks_and_decomposed_from_track`,
kept for bundles of format 1.0<!--n:bundle format version--> (`kink_decompose_px` = 3<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px, `kinkangle_deg` =
150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg-->°), to the traced skeleton tracks of the same images.

A reported bend within $W$ of a mark the reference calls ambiguous or a
junction is counted neither as found nor as unmatched. Of the 143<!--m:kink_reference.default.detections--> bends the
excess-turning rule reported, 25<!--m:kink_reference.default.exempt--> were such. Per scan, the rule's row reads:

| Scan | Clear kinks marked | Reported bends | Found | Missed | Unmatched | Near an ambiguous or junction mark |
|---|---|---|---|---|---|---|
| higher-plant TOC | 3<!--m:kink_reference.default.hplantTOC.ref--> | 9<!--m:kink_reference.default.hplantTOC.detections--> | 3<!--m:kink_reference.default.hplantTOC.found--> | 0<!--m:kink_reference.default.hplantTOC.missed--> | 6<!--m:kink_reference.default.hplantTOC.false--> | 0<!--m:kink_reference.default.hplantTOC.exempt--> |
| tunicate CNF | 44<!--m:kink_reference.default.tunicate.ref--> | 69<!--m:kink_reference.default.tunicate.detections--> | 42<!--m:kink_reference.default.tunicate.found--> | 2<!--m:kink_reference.default.tunicate.missed--> | 15<!--m:kink_reference.default.tunicate.false--> | 12<!--m:kink_reference.default.tunicate.exempt--> |
| Bruker NDTOC | 6<!--m:kink_reference.default.NDTOC.ref--> | 65<!--m:kink_reference.default.NDTOC.detections--> | 5<!--m:kink_reference.default.NDTOC.found--> | 1<!--m:kink_reference.default.NDTOC.missed--> | 47<!--m:kink_reference.default.NDTOC.false--> | 13<!--m:kink_reference.default.NDTOC.exempt--> |

The higher-plant TOC and Bruker NDTOC scans image the same dispersion; on them
the rule reported 9<!--m:kink_reference.default.hplantTOC.detections--> and 65<!--m:kink_reference.default.NDTOC.detections--> bends where the reference marks 3<!--m:kink_reference.default.hplantTOC.ref--> and 6<!--m:kink_reference.default.NDTOC.ref--> clear kinks.

The lengths of the rule are multiples of $W$ set from $W$ being the resolution
of the image and were not optimized against this reference, but the rule and
its centerline were chosen among candidates by their scores on it, so the
reference served as a development set rather than an independent test; no
held-out scans were scored.
Changing any one of them to a neighbouring value moved the clear kinks found
within 48–52<!--m:kink_reference.sens_all.found_range--> and the unmatched bends within 51–88<!--m:kink_reference.sens_all.false_range--> (50<!--m:kink_reference.default.found--> and 68<!--m:kink_reference.default.false--> at
the defaults). The largest drops came from stronger smoothing: 48<!--m:kink_reference.sens_heading_0.35.found--> with the
heading smoothed over 0.35<!--n:value tried--> W, 49<!--m:kink_reference.sens_line_x1.4.found--> with the centerline smoothing ×1.4<!--n:value tried-->.

| Length | Default | Neighbouring values tried |
|---|---|---|
| centerline smoothing | W/4 | ×0.6<!--n:value tried-->, ×1.4<!--n:value tried--> |
| window half-length $c$ | 0.75<!--c:lib/kink_detector.py::_CORE_WIDTHS--> W | 0.6<!--n:value tried--> W, 0.9<!--n:value tried--> W |
| flank length $f$ | 1.0<!--c:lib/kink_detector.py::_FLANK_WIDTHS--> W | 0.75<!--n:value tried--> W, 1.5<!--n:value tried--> W |
| heading smoothing $\sigma$ | 0.25<!--c:lib/kink_detector.py::_HEADING_SIGMA_WIDTHS--> W | 0.15<!--n:value tried--> W, 0.35<!--n:value tried--> W |
| end margin | 1.5<!--c:lib/kink_detector.py::END_MARGIN_WIDTHS--> W | 1.0<!--n:value tried--> W, 2.0<!--n:value tried--> W |
| suppression radius | 0.75<!--c:lib/kink_detector.py::_SUPPRESS_WIDTHS--> W | 0.5<!--n:value tried--> W, 1.0<!--n:value tried--> W |

Without the candidates taken from the maxima of the window turning itself, the
rule found 47<!--m:turn_maxima.without.found--> instead of 50<!--m:turn_maxima.with.found--> of the clear reference kinks, and reported
48<!--m:turn_maxima.without.false--> instead of 68<!--m:turn_maxima.with.false--> unmatched bends (experiment turn_maxima).

### 4.5 The angle stored for a kink

The excess turning read low on sharp synthetic corners, where the probe and the
centerline round the apex:

| Corner turning | Excess turning read |
|---|---|
| 40<!--n:value tried-->° | 35–39<!--m:synthetic_kinks.corner40.excess_read_range_deg-->° |
| 60<!--n:value tried-->° | 55–56<!--m:synthetic_kinks.corner60.excess_read_range_deg-->° |
| 90<!--n:value tried-->° | 83–84<!--m:synthetic_kinks.corner90.excess_read_range_deg-->° |
| 120<!--n:value tried-->° | 100–101<!--m:synthetic_kinks.corner120.excess_read_range_deg-->° |

A bend just above the threshold can therefore read below it: the bend drawn at
33.5<!--m:test_suite_bend.drawn_turn_deg-->° in the test suite reads 26.5<!--m:test_suite_bend.read_excess_deg-->° (experiment test_suite_bend). This is why the
angle stored for a kink is read from its arms rather than taken as 180<!--n:definition-->° minus
the excess. On synthetic corners of 120<!--n:example-->°, 140<!--n:example-->° and 145<!--n:example-->° interior angle rendered
with a 10<!--c:scripts/kink_rule_sweep.py::TIP_RADIUS_NM--> nm probe, the median angle error over the corners found, pooled over
the 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> noise levels, was:

| Apparent width | Arm angle | 180<!--n:definition-->° minus the excess |
|---|---|---|
| 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px | 0.7<!--m:kink_rule_sweep.W5.arm_error_deg-->° | 1.7<!--m:kink_rule_sweep.W5.excess_error_deg-->° |
| 5.75<!--m:kink_rule_sweep.W8.measured_width_px--> px | 2.0<!--m:kink_rule_sweep.W8.arm_error_deg-->° | 2.4<!--m:kink_rule_sweep.W8.excess_error_deg-->° |
| 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px | 2.35<!--m:kink_rule_sweep.W16.arm_error_deg-->° | 2.1<!--m:kink_rule_sweep.W16.excess_error_deg-->° |

At 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px the excess was the closer of the two.

### 4.6 Synthetic shapes

- On synthetic zigzags, corners 1.5–3<!--n:value tried--> $W$ apart were all found
  (30<!--m:synthetic_kinks.zigzag_1.5W_up.found--> of 30<!--m:synthetic_kinks.zigzag_1.5W_up.clear-->), but corners 1<!--n:value tried--> $W$ apart only 4<!--m:synthetic_kinks.zigzag1W.found--> of 10<!--m:synthetic_kinks.zigzag1W.clear-->.
- No bend was reported on straight fibers (0<!--m:synthetic_kinks.straight.reported--> on 2<!--m:synthetic_kinks.straight.scans--> scans), arcs of radius
  3–10<!--n:value tried--> $W$ (0<!--m:synthetic_kinks.arcs.reported--> on 6<!--m:synthetic_kinks.arcs.scans-->), crossings and junctions (0<!--m:synthetic_kinks.crossings_branches.reported--> on 10<!--m:synthetic_kinks.crossings_branches.scans-->) or twisted
  ribbons (0<!--m:synthetic_centerline.ribbons.kinks_reported--> on 6<!--m:synthetic_centerline.ribbons.count-->).
- Every isolated corner of 40<!--n:value tried-->° or more was found (8<!--m:synthetic_kinks.corners_40_up.found--> of 8<!--m:synthetic_kinks.corners_40_up.clear-->).
- 11<!--m:synthetic_kinks.sines.reported--> bends were reported on 4<!--m:synthetic_kinks.sines.scans--> sine meanders whose tightest radius is
  1.6–1.8<!--m:synthetic_kinks.sines.tightest_radius_w_range--> $W$. Below a radius of about $2.9\,W$ the window alone turns more than
  30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->°, and where the curvature changes quickly the flanks do not account for it.
- The earlier polyline rule reported 31<!--m:synthetic_kinks.old_rule.arcs_sines_reported--> bends on the same arcs and meanders
  (experiment synthetic_kinks).

### 4.7 The per-centerline noise floor

The noise floor ships off because it did not separate the false detections from
the real kinks. Scored against the visual reference
(`scripts/kink_reference_score.py`):

| Noise-floor factor | Clear kinks lost | False detections removed |
|---|---|---|
| 3<!--n:value tried--> | 3<!--m:kink_reference.noise3.lost--> | 6<!--m:kink_reference.noise3.fewer_false--> |
| 4<!--n:value tried--> | 5<!--m:kink_reference.noise4.lost--> | 9<!--m:kink_reference.noise4.fewer_false--> |

The false detections on these scans are rounded bends, tangles, bends next to
crossings, bends on faint strands and on a patch of the higher-plant scan's
disturbed scan line, and shallow bends whose excess turning only just clears
the threshold, not noise: 31<!--m:kink_reference.default.false_excess_30_40--> of the 68<!--m:kink_reference.default.false--> have an excess of 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->–40<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|190 - v-->°. For
16<!--m:kink_reference.default.false_arm_turn_below_threshold--> of them the turning read from the arms (180<!--n:definition-->° − `ka`) falls below
30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->°, because the arm angle is measured apart from the excess turning the rule
tests. A heavily bent fiber's own kinks raise its floor, which is where the
lost clear kinks lay. On the synthetic sweep the floor changed the false bends
on the straight, arc and sine fibers only at the finest pixel size with the
heaviest noise (11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px width, 0.30<!--n:value tried--> nm pixel noise), from 5.4<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> to 3.3<!--m:kink_rule_sweep.W16.n0.30.k3.fp_per_um--> per µm. At
that setting it left the bends reported on the 165<!--n:example-->° bend, which must not be
reported, unchanged (4<!--m:kink_rule_sweep.W16.n0.30.base.kink165_reported--> without it, 4<!--m:kink_rule_sweep.W16.n0.30.k3.kink165_reported--> with it). It changed none of the corners found;
at the coarsest pixel size with the heaviest noise, for example, 3<!--m:kink_rule_sweep.W3.n0.30.base.kinked_found--> were found
without it and 3<!--m:kink_rule_sweep.W3.n0.30.k3.kinked_found--> with it (§4.8).

### 4.8 Where the rule applied in the sweep

The apparent width here is the $W$ the pipeline measured on the straight fiber
of each setting, not the width the synthetic scan was designed with. Each
corner was drawn at 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> noise levels with 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> seeds, 6<!--m:kink_rule_sweep.W5.kink120.cases--> scans per angle and
width.

- At 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px every corner was found (6<!--m:kink_rule_sweep.W5.kink120.found-->, 6<!--m:kink_rule_sweep.W5.kink140.found--> and 6<!--m:kink_rule_sweep.W5.kink145.found--> of 6<!--m:kink_rule_sweep.W5.kink145.cases-->).
- At 5.75<!--m:kink_rule_sweep.W8.measured_width_px--> px every corner was found (6<!--m:kink_rule_sweep.W8.kink120.found-->, 6<!--m:kink_rule_sweep.W8.kink140.found--> and 6<!--m:kink_rule_sweep.W8.kink145.found--> of 6<!--m:kink_rule_sweep.W8.kink140.cases-->).
- At 11.5<!--m:kink_rule_sweep.W16.measured_width_px--> px each angle was found in 5<!--m:kink_rule_sweep.W16.kink120.found-->, 5<!--m:kink_rule_sweep.W16.kink140.found--> and 5<!--m:kink_rule_sweep.W16.kink145.found--> of 6<!--m:kink_rule_sweep.W16.kink140.cases-->: every time
  at pixel noise up to 0.15<!--n:value tried--> nm, and in 1<!--m:kink_rule_sweep.W16.n0.30.kink120.found--> of 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> scans at 0.30<!--n:value tried--> nm. At that noise,
  rendered, background calibration removed most of the height of the
  near-horizontal arm, which the raw scan shows unbroken. In one of these
  scans the fiber mask covered only part of the arm, and filling the masked
  pixels from the nearest unmasked ones, which lay on the arm itself, put
  nearly all of its height into the background; smoothing along the scan lines,
  which the arm runs along, kept it there, whereas with the scan turned by
  90<!--n:value tried-->° the same smoothing took most of it out of the background.
  `background_warnings` warned on that scan (`flank_step_low` and
  `relief_absorbed`). The tracing split that arm into many fragments, and false
  bends gathered on it. On the
  straight, arc and sine fibers of the same setting the rule reported 5.4<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um-->
  false bends per µm.
- At the three finer pixel sizes, at pixel noise up to 0.15<!--n:value tried--> nm, the straight
  fibers, arcs and meanders carried no false positive, and there was none on a
  165<!--n:example-->° bend.
- At the coarsest pixel size of the sweep (5.2<!--c:scripts/kink_rule_sweep.py::APPARENT_WIDTH_NM|v / 3--> nm, where the fiber spans
  fewer pixels than at the 3.5<!--m:kink_rule_sweep.W5.measured_width_px--> px setting), the width measured below
  2<!--c:lib/centerline.py::_MIN_WIDTH_PX--> px and was raised to 2<!--m:kink_rule_sweep.W3.measured_width_px--> px. The 120<!--n:example-->° corner was found in 6<!--m:kink_rule_sweep.W3.kink120.found--> of
  6<!--m:kink_rule_sweep.W3.kink120.cases--> scans, the 145<!--n:example-->° corner in 5<!--m:kink_rule_sweep.W3.kink145.found--> and the 140<!--n:example-->° corner in 2<!--m:kink_rule_sweep.W3.kink140.found-->. Rendered, the
  six 140<!--n:example-->° scans are traced unbroken through the corner, and the other bends the
  rule reported there lie on the straight arms and at the fiber's ends: with the
  width at 2<!--m:kink_rule_sweep.W3.measured_width_px--> px, only bends within 3<!--x:1.5 * 2--> px of a track end are left unjudged. On
  the straight, arc and sine fibers the rule reported between 1.0<!--m:kink_rule_sweep.W3.n0.15.base.fp_per_um--> and
  1.9<!--m:kink_rule_sweep.W3.n0.05.base.fp_per_um--> false bends per µm at every noise level, and 1<!--m:kink_rule_sweep.W3.n0.30.base.kink165_reported--> bend on the 165<!--n:example-->° bend at
  0.30<!--n:value tried--> nm.

### 4.9 The end margin

On the 3<!--n:count--> real bundled scans, 34<!--m:track_ends.hplantTOC.near_branch_percent-->–64<!--m:track_ends.tunicate.near_branch_percent--> % of track ends lie within 3<!--n:definition--> px of a
branch point (experiment track_ends): many track ends are cuts at a crossing,
not fiber ends.

At a margin of $1.0\,W$ the false detections on the bundled scans rose from
68<!--m:kink_reference.default.false--> to 88<!--m:kink_reference.sens_end_1.false--> without a further clear kink being found; at $2.0\,W$ they fell to
52<!--m:kink_reference.sens_end_2.false--> with the same 50<!--m:kink_reference.sens_end_2.found--> clear kinks found. On the synthetic corners 1.5<!--n:value tried--> $W$
from an end, the default judged 1<!--m:synthetic_kinks.margin_default.end1.5W.corners_judged--> of 2<!--m:synthetic_kinks.end_cases_per_distance--> and $2.0\,W$ judged 0<!--m:synthetic_kinks.margin_2W.end1.5W.corners_judged-->; on those 2<!--n:value tried--> $W$ from an
end, the default judged 1<!--m:synthetic_kinks.margin_default.end2W.corners_judged--> of 2<!--m:synthetic_kinks.end_cases_per_distance--> and $2.0\,W$ judged 1<!--m:synthetic_kinks.margin_2W.end2W.corners_judged-->. Rendered, in the scan of each
pair that neither margin judged, the trace of the short arm ends short of the
fiber's end, which puts the corner within $1.5\,W$ of the track's end. None of
the 49<!--m:kink_reference.default.unjudged--> bends left unjudged on the bundled scans lay on a clear reference kink.

### 4.10 Crest height against the height at the centerline

On every traceable skeleton component of every test input, with the default
centerline placed as `KinkDetector` places it (experiment crest_height), the
crest height was compared with the calibrated height read at the centerline, at
the reliable points:

| Input | Median difference (nm) | 90<!--n:definition-->th percentile (nm) | Median, % of crest | 90<!--n:definition-->th percentile, % of crest |
|---|---|---|---|---|
| tunicate CNF | 0.070<!--m:crest_height.tunicate.median_nm--> | 0.211<!--m:crest_height.tunicate.p90_nm--> | 0.937<!--m:crest_height.tunicate.median_percent--> | 2.646<!--m:crest_height.tunicate.p90_percent--> |
| higher-plant TOC | 0.014<!--m:crest_height.hplantTOC.median_nm--> | 0.089<!--m:crest_height.hplantTOC.p90_nm--> | 0.846<!--m:crest_height.hplantTOC.median_percent--> | 5.004<!--m:crest_height.hplantTOC.p90_percent--> |
| Bruker NDTOC | 0.025<!--m:crest_height.NDTOC.median_nm--> | 0.129<!--m:crest_height.NDTOC.p90_nm--> | 1.269<!--m:crest_height.NDTOC.median_percent--> | 7.252<!--m:crest_height.NDTOC.p90_percent--> |
The crest height was never below the height at the centerline. Reading the
height at the centerline would therefore make the fiber lower, by the small but
one-sided amounts in the table, because the half-maximum midpoint lies beside the
crest on an asymmetric section.

### 4.11 Height near a cut end

On every test input, along the default centerline of each track at least 5<!--n:definition--> W long
(experiment cut_end_skirt), the crest height near each end was divided by the
track's median crest height and pooled by median, separately for ends cut at a
crossing (within 3<!--n:definition--> px of a branch point) and free ends.

| Input | Cut ends | Ratio at a cut end | Back to 1.05<!--n:definition--> or less within (W) | Ratio at a free end |
|---|---|---|---|---|
| tunicate CNF | 45<!--m:cut_end_skirt.tunicate.cut_ends--> | 1.43<!--m:cut_end_skirt.tunicate.cut.ratio_at_end--> | 0.75<!--m:cut_end_skirt.tunicate.cut.back_within_widths--> | 1.03<!--m:cut_end_skirt.tunicate.free.ratio_at_end--> |
| higher-plant TOC | 7<!--m:cut_end_skirt.hplantTOC.cut_ends--> | 1.25<!--m:cut_end_skirt.hplantTOC.cut.ratio_at_end--> | 1.00<!--m:cut_end_skirt.hplantTOC.cut.back_within_widths--> | 0.74<!--m:cut_end_skirt.hplantTOC.free.ratio_at_end--> |
| Bruker NDTOC | 83<!--m:cut_end_skirt.NDTOC.cut_ends--> | 1.26<!--m:cut_end_skirt.NDTOC.cut.ratio_at_end--> | 0.50<!--m:cut_end_skirt.NDTOC.cut.back_within_widths--> | 0.70<!--m:cut_end_skirt.NDTOC.free.ratio_at_end--> |

Rendered as profiles, the height at a cut end is raised above the fiber's own
height and falls back within about one width, while free ends show no such rise:
the skirt of the other fiber at the crossing reaches past the pixels cleared at
the branch point.

### 4.12 The width limit of a cross-section

`centerline._refine` takes a cross-section as this fiber's only when its full
width at half maximum is at most 1.5<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS--> W; the limit is not applied to each half
of it. With each half limited instead to 0.75<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS|v / 2--> W from the crest (experiment
section_width_limit), the share of centerline points located on their own
section fell on every test input and rose on none:

| Input | Points | Located, full width (%) | Located, each half (%) |
|---|---|---|---|
| tunicate CNF | 7917<!--m:section_width_limit.tunicate.points--> | 88.1<!--m:section_width_limit.tunicate.reliable_full_percent--> | 83.7<!--m:section_width_limit.tunicate.reliable_half_percent--> |
| higher-plant TOC | 2051<!--m:section_width_limit.hplantTOC.points--> | 86.7<!--m:section_width_limit.hplantTOC.reliable_full_percent--> | 80.9<!--m:section_width_limit.hplantTOC.reliable_half_percent--> |
| Bruker NDTOC | 8765<!--m:section_width_limit.NDTOC.points--> | 81.7<!--m:section_width_limit.NDTOC.reliable_full_percent--> | 75.6<!--m:section_width_limit.NDTOC.reliable_half_percent--> |

The fiber of the tunicate scan that loses the most points, 137<!--m:section_width_limit.tunicate.most_lost.lost--> of its 919<!--m:section_width_limit.tunicate.most_lost.points-->,
was rendered over the calibrated height image with its cross-sections. The
points it loses are the straight stretch from its corner to the right border: a
single fiber, crossed once by another, whose sections are single-peaked with the
crest a little off the middle, so that one half is wider than 0.75<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS|v / 2--> W while the
full width stays within 1.5<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS--> W.

### 4.13 Curvature of a straight fiber

`measure.fiber_mean_curvature` averages an unsigned curvature, so it reads above
zero on a fiber that is straight. A straight synthetic fiber 2<!--n:condition--> nm high,
with a Gaussian cross-section 20<!--n:condition--> nm wide at half maximum and 1200<!--n:condition--> nm long at
20<!--n:condition-->° to the rows, was imaged at three pixel sizes with three levels of
Gaussian height noise, 5<!--n:condition--> noise draws each, and its mean curvature taken
along the default centerline placed on the pixel track of its axis (experiment
curvature_noise_floor, rad/µm, mean over the draws):

| Pixel (nm) | Noise 0<!--n:condition--> nm | Noise 0.05<!--n:condition--> nm | Noise 0.15<!--n:condition--> nm |
|---|---|---|---|
| 2<!--n:condition--> | 0.03<!--m:curvature_noise_floor.px2.noise0.mean--> | 0.06<!--m:curvature_noise_floor.px2.noise0.05.mean--> | 0.16<!--m:curvature_noise_floor.px2.noise0.15.mean--> |
| 5<!--n:condition--> | 0.29<!--m:curvature_noise_floor.px5.noise0.mean--> | 0.27<!--m:curvature_noise_floor.px5.noise0.05.mean--> | 0.35<!--m:curvature_noise_floor.px5.noise0.15.mean--> |
| 10<!--n:condition--> | 0.64<!--m:curvature_noise_floor.px10.noise0.mean--> | 0.66<!--m:curvature_noise_floor.px10.noise0.05.mean--> | 0.82<!--m:curvature_noise_floor.px10.noise0.15.mean--> |

Without noise the reading comes from the pixel grid. Rendered against the true
axis, the centerline at 5<!--n:condition--> and 10<!--n:condition--> nm pixels carries a ripple at the period of
the skeleton track's staircase, larger at 10<!--n:condition--> nm, where the fiber spans fewer
pixels; at 2<!--n:condition--> nm its sideways deviation is much smaller (W is 9.5<!--m:curvature_noise_floor.px2.width_px-->, 3.75<!--m:curvature_noise_floor.px5.width_px--> and
2.00<!--m:curvature_noise_floor.px10.width_px--> px at 2<!--n:condition-->, 5<!--n:condition--> and 10<!--n:condition--> nm pixels). Noise of 0.15<!--n:condition--> nm raised the mean at every pixel
size; 0.05<!--n:condition--> nm raised it at 2<!--n:condition--> and 10<!--n:condition--> nm pixels and left it slightly lower at
5<!--n:condition--> nm. Both
depend on the pixel size, so a difference in curvature between groups imaged at
different pixel sizes contains a difference in imaging; GUI03 warns when the
bundles it compares for curvature differ in pixel size.

### 4.14 Length at the free ends of a fiber

What the ends add to or take from the contour length was measured on single
straight fibers 600<!--c:scripts/measure_docs.py::END_LOSS_LENGTH_NM--> nm long lying inside the scan, with square ends and with
ends tapering to 0.3<!--n:value tried--> of the diameter over 20<!--n:value tried--> nm (experiment end_loss: a cylinder
of diameter 3<!--n:value tried--> nm under a 10<!--n:value tried--> nm apex, the background of the kink sweep with
0.05<!--n:value tried--> nm pixel noise, 3<!--c:scripts/measure_docs.py::len(END_LOSS_SEEDS)--> seeds per setting). Each end of the measured centerline was
projected onto the true axis. A positive deficit means that the measured
centerline stops short of the true end, a negative one that it runs past it.
Every scan traced the fiber as one piece (18<!--m:end_loss.single_fiber_runs--> of 18<!--m:end_loss.runs-->).

| Pixel size | Ends | Deficit per end | In apparent widths | Contour length error |
|---|---|---|---|---|
| 1<!--n:value tried--> nm | square | −0.5<!--m:end_loss.px1.taper0.end_deficit_nm_range[0]--> to +0.5<!--m:end_loss.px1.taper0.end_deficit_nm_range[1]--> nm | −0.04<!--m:end_loss.px1.taper0.end_deficit_w_range[0]--> to +0.04<!--m:end_loss.px1.taper0.end_deficit_w_range[1]--> | +0.07<!--m:end_loss.px1.taper0.length_error_percent_range[0]--> to +0.33<!--m:end_loss.px1.taper0.length_error_percent_range[1]--> % |
| 1<!--n:value tried--> nm | tapered | −5.4<!--m:end_loss.px1.taper20.end_deficit_nm_range[0]--> to +0.9<!--m:end_loss.px1.taper20.end_deficit_nm_range[1]--> nm | −0.49<!--m:end_loss.px1.taper20.end_deficit_w_range[0]--> to +0.08<!--m:end_loss.px1.taper20.end_deficit_w_range[1]--> | +0.03<!--m:end_loss.px1.taper20.length_error_percent_range[0]--> to +1.62<!--m:end_loss.px1.taper20.length_error_percent_range[1]--> % |
| 2<!--n:value tried--> nm | square | −0.8<!--m:end_loss.px2.taper0.end_deficit_nm_range[0]--> to +0.2<!--m:end_loss.px2.taper0.end_deficit_nm_range[1]--> nm | −0.07<!--m:end_loss.px2.taper0.end_deficit_w_range[0]--> to +0.02<!--m:end_loss.px2.taper0.end_deficit_w_range[1]--> | +0.26<!--m:end_loss.px2.taper0.length_error_percent_range[0]--> to +0.34<!--m:end_loss.px2.taper0.length_error_percent_range[1]--> % |
| 2<!--n:value tried--> nm | tapered | −2.6<!--m:end_loss.px2.taper20.end_deficit_nm_range[0]--> to +1.3<!--m:end_loss.px2.taper20.end_deficit_nm_range[1]--> nm | −0.24<!--m:end_loss.px2.taper20.end_deficit_w_range[0]--> to +0.12<!--m:end_loss.px2.taper20.end_deficit_w_range[1]--> | +0.03<!--m:end_loss.px2.taper20.length_error_percent_range[0]--> to +0.74<!--m:end_loss.px2.taper20.length_error_percent_range[1]--> % |
| 4<!--n:value tried--> nm | square | −3.3<!--m:end_loss.px4.taper0.end_deficit_nm_range[0]--> to +0.5<!--m:end_loss.px4.taper0.end_deficit_nm_range[1]--> nm | −0.30<!--m:end_loss.px4.taper0.end_deficit_w_range[0]--> to +0.05<!--m:end_loss.px4.taper0.end_deficit_w_range[1]--> | +0.46<!--m:end_loss.px4.taper0.length_error_percent_range[0]--> to +1.13<!--m:end_loss.px4.taper0.length_error_percent_range[1]--> % |
| 4<!--n:value tried--> nm | tapered | +1.0<!--m:end_loss.px4.taper20.end_deficit_nm_range[0]--> to +9.3<!--m:end_loss.px4.taper20.end_deficit_nm_range[1]--> nm | +0.10<!--m:end_loss.px4.taper20.end_deficit_w_range[0]--> to +0.85<!--m:end_loss.px4.taper20.end_deficit_w_range[1]--> | −1.68<!--m:end_loss.px4.taper20.length_error_percent_range[0]--> to −0.91<!--m:end_loss.px4.taper20.length_error_percent_range[1]--> % |

Rendered, at 1<!--n:value tried--> nm pixels the measured centerline of a tapered end continues past
the fiber's end into the image the probe spreads around it, and in one scan
bends off the axis there; at 4<!--n:value tried--> nm pixels the tapered end fades into the
background and the measured centerline stops before it; square ends stop
within a pixel of the true end. The error at an end is therefore not of one
sign: it depends on the pixel size and on how the fiber ends, and a real scan
does not show how its fibers end. These are free ends; an end cut at a
crossing is the case of §4.11.

## 5. Stripe-noise screening

### 5.1 The step threshold

`stripe_noise.evaluate_scan_lines` flags the boundary between two scan lines
whose median heights differ by more than 3<!--c:lib/stripe_noise.py::DEFAULT_STEP_THRESHOLD_NM--> nm. On the raw heights of each test
input, as GUI01 screens them (experiment stripe_threshold):

| Input | Flagged boundaries | Smallest flagged step (nm) | Largest unflagged step (nm) | Unflagged steps, percentile 99<!--n:definition--> (nm) |
|---|---|---|---|---|
| tunicate CNF | 0<!--m:stripe_threshold.tunicate.flagged--> | — | 2.71<!--m:stripe_threshold.tunicate.unflagged_max_step_nm--> | 1.24<!--m:stripe_threshold.tunicate.unflagged_p99_step_nm--> |
| higher-plant TOC | 2<!--m:stripe_threshold.hplantTOC.flagged--> | 5.53<!--m:stripe_threshold.hplantTOC.flagged_min_step_nm--> | 0.21<!--m:stripe_threshold.hplantTOC.unflagged_max_step_nm--> | 0.13<!--m:stripe_threshold.hplantTOC.unflagged_p99_step_nm--> |
| Bruker NDTOC | 0<!--m:stripe_threshold.NDTOC.flagged--> | — | 0.23<!--m:stripe_threshold.NDTOC.unflagged_max_step_nm--> | 0.18<!--m:stripe_threshold.NDTOC.unflagged_p99_step_nm--> |

Rendered, the two flagged boundaries of the higher-plant scan enclose rows
displaced across the whole width, a feedback glitch. The largest unflagged
step, on the tunicate scan, is not a glitch. That raw scan is steeply tilted
along each line, so a line's median is the height at whichever column holds the
middle-ranked value, and material crossing a few lines moves that column; with a
plane removed, the heights show no band there. On that scan the threshold sits
only 0.29<!--x:3 - 2.70925--> nm above a step that is not a glitch.

## 6. The isolation test of GUI04

### 6.1 The frame

`measure.isolated_fiber_flags` takes a fiber whose skeleton pixels reach the
outermost row or column as continuing outside the scan, with no margin. The
frame was widened to a margin of 1<!--n:value tried--> to 5<!--n:value tried--> px on the traced fibers of each test
input (experiment frame_margin):

| Input | Fibers | Reaching the frame, no margin | 2<!--n:value tried--> px margin | 5<!--n:value tried--> px margin |
|---|---|---|---|---|
| tunicate CNF | 63<!--m:frame_margin.tunicate.fibers--> | 17<!--m:frame_margin.tunicate.margin_0.reaching--> | 17<!--m:frame_margin.tunicate.margin_2.reaching--> | 17<!--m:frame_margin.tunicate.margin_5.reaching--> |
| higher-plant TOC | 19<!--m:frame_margin.hplantTOC.fibers--> | 3<!--m:frame_margin.hplantTOC.margin_0.reaching--> | 3<!--m:frame_margin.hplantTOC.margin_2.reaching--> | 3<!--m:frame_margin.hplantTOC.margin_5.reaching--> |
| Bruker NDTOC | 143<!--m:frame_margin.NDTOC.fibers--> | 16<!--m:frame_margin.NDTOC.margin_0.reaching--> | 16<!--m:frame_margin.NDTOC.margin_2.reaching--> | 17<!--m:frame_margin.NDTOC.margin_5.reaching--> |

Margins of 1<!--n:value tried--> and 2<!--n:value tried--> px changed no verdict (changes: 0<!--m:frame_margin.all.changed_up_to_2-->). From 3<!--n:value tried--> px on,
1<!--m:frame_margin.all.changed_at_5--> fiber of the Bruker scan joins. Rendered over the calibrated height
image, it is a short fragment between crossings that runs along the left border
a few pixels from it rather than out of the scan, so a margin would count it as
continuing outside the scan when it does not.
