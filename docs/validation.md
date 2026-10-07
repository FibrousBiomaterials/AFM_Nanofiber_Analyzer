# Evaluation on particular data

[Analysis algorithms](algorithms.md) explains what each stage of the analysis
computes. This page collects what the stages did on particular data: the scans
bundled with the repository, and synthetic scans drawn with a known answer.
Several defaults of the code were chosen by looking at these results, and the
page says which.

**Every number on this page describes the data it was measured on, not the
algorithm.** The bundled scans are 5<!--m:kink_reference.scans--> images: three specimens and two
artificial samples. The synthetic scans are drawn with fixed fiber and probe
shapes. Neither tells how the analysis behaves on another specimen, another
instrument or another scan size. A result here shows the kind of behaviour worth
checking for; whether it holds on your images is decided by looking at your
images.

## Data and how the numbers are kept

| Data | What it is | Code |
|---|---|---|
| Bundled scans | a tunicate CNF scan (`testdata_tunicateCNF`), a higher-plant TOC scan (`testdata_higherplantTOC`), a Bruker NDTOC scan (`testdata_Bruker_txt`), and two artificial scans, isotropic and anisotropic (`testdata_artificial`) | `SCANS` in `scripts/kink_reference_score.py` |
| Visual reference | kinks marked by eye on the height images of the bundled scans, with no detector output on screen: 64<!--m:kink_reference.clear_marks--> clear kinks | `scripts/kink_reference_score.py` |
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
| tunicate CNF | 0.23<!--m:bg_stats.tunicate.plane_slope_nm_per_px--> | 4.6<!--m:bg_stats.tunicate.drop_across_hole_nm--> | 15.2<!--m:bg_stats.tunicate.quadratic_p2p_nm--> | 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> |
| artificial, isotropic | 0.24<!--m:bg_stats.art_iso.plane_slope_nm_per_px--> | 2.4<!--m:bg_stats.art_iso.drop_across_hole_nm--> | 3.5<!--m:bg_stats.art_iso.quadratic_p2p_nm--> | 7.5<!--m:bg_stats.art_iso.skeleton_height_median_nm--> |
| artificial, anisotropic | 0.24<!--m:bg_stats.art_aniso.plane_slope_nm_per_px--> | 2.4<!--m:bg_stats.art_aniso.drop_across_hole_nm--> | 7.5<!--m:bg_stats.art_aniso.quadratic_p2p_nm--> | 7.2<!--m:bg_stats.art_aniso.skeleton_height_median_nm--> |
| higher-plant TOC | 0.001<!--m:bg_stats.hplantTOC.plane_slope_nm_per_px--> | 0.01<!--m:bg_stats.hplantTOC.drop_across_hole_nm--> | 1.7<!--m:bg_stats.hplantTOC.quadratic_p2p_nm--> | 1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> |
| Bruker NDTOC | 0.003<!--m:bg_stats.NDTOC.plane_slope_nm_per_px--> | 0.04<!--m:bg_stats.NDTOC.drop_across_hole_nm--> | 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> | 2.1<!--m:bg_stats.NDTOC.skeleton_height_median_nm--> |

The plane slope is that of the least-squares plane through the raw heights;
the fall is that slope times the median width of the dilated fiber mask; the
bowl is the peak-to-peak of the quadratic terms of a second-order surface
fitted after the plane; the height is the median calibrated height under the
default skeleton (experiment bg_stats). On the tunicate scan the background
falls 4.6<!--m:bg_stats.tunicate.drop_across_hole_nm--> nm across one masked fiber whose median height is 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm. The
higher-plant and Bruker scans are level as planes, but the Bruker scan's bowl
alone spans 21.9<!--m:bg_stats.NDTOC.quadratic_p2p_nm--> nm. The trend surface of the background calibration is
second-order rather than a plane because of scans like the last.

### 1.2 Fill accuracy with and without detrending

On 20<!--m:bg_fill.holes--> square holes of 21<!--m:bg_fill.hole_size_px--> px cut into fiber-free background of the tunicate
scan (experiment bg_fill), the filled values departed from the heights actually
measured there by 2.5<!--m:bg_fill.none.nearest.fill_error_median_nm--> nm with nearest-neighbour propagation and 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm with
inpainting when nothing was detrended, and by 0.30<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm and 0.27<!--m:bg_fill.quadratic.inpaint.fill_error_median_nm--> nm after the
quadratic trend was removed (the median over the holes of the largest
departure in each). On these holes the detrending, not the filler, set the
accuracy, and a plane did almost as well as the quadratic surface (0.34<!--m:bg_fill.plane.nearest.fill_error_median_nm--> nm
against 0.30<!--m:bg_fill.quadratic.nearest.fill_error_median_nm--> nm with nearest-neighbour fill).

### 1.3 The fill used up to 1.0.0

Without detrending, the inpainting used up to 1.0.0 departed from the true
background by 1.7<!--m:bg_fill.none.inpaint.fill_error_median_nm--> nm on the tunicate holes above. Running the calibrator of release
1.0.0 (from tag `v1.0.0`) on a synthetic scan with one 8<!--m:bg_legacy_halo.fiber_height_nm--> nm fiber across a
0.24<!--m:bg_legacy_halo.slope_nm_per_px--> nm/px plane (experiment bg_legacy_halo), the calibrated background beside
the fiber ranged from −0.76<!--m:bg_legacy_halo.v1_0_0.beside_min_nm--> to +0.77<!--m:bg_legacy_halo.v1_0_0.beside_max_nm--> nm, beyond the default binarization
threshold of 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm; the current code leaves −0.21<!--m:bg_legacy_halo.current.beside_min_nm--> to +0.18<!--m:bg_legacy_halo.current.beside_max_nm--> nm there.

### 1.4 `tophat` at the border

On a ramp of 0.24<!--m:tophat_border.slope_nm_per_px--> nm/px, the steepest plane of the bundled scans (§1.1),
opening the raw heights with the 25<!--c:lib/pipeline.py::ProcParams.tophat_se_size-->-px element leaves a band
**3.1<!--m:tophat_border.raw.uphill_band_max_nm--> nm** high within 12<!--n:definition--> px of the uphill edge, far above the
0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm binarization threshold; opening the detrended heights leaves
0.29<!--m:tophat_border.detrended.uphill_band_max_nm--> nm (experiment tophat_border).

### 1.5 Run time

Measured on the bundled 1024<!--m:bg_timing.image_rows-->×1024<!--m:bg_timing.image_cols--> Bruker scan (second of two runs each),
`tophat` took about 0.5<!--m:bg_timing.tophat.seconds--> s, `trendfill` about 1.0<!--m:bg_timing.trendfill.seconds--> s, and `spline1d` about
2.3<!--m:bg_timing.spline1d.seconds--> s; in `trendfill`, the `lmfit` histogram fit took about half as long as
`_bg_generate` (experiment bg_timing). These are wall times on one machine
and vary with the machine and its load.

### 1.6 The axis of `spline1d`

Each test input was calibrated by `trendfill` and by `spline1d` along `'x'` and
along `'y'`, everything else at the defaults (experiment spline1d_axis). On the
background (pixels more than 5<!--n:definition--> px from the union of the three binarized
masks), the table gives the spread (standard deviation, nm) of the per-row
medians, which grows with horizontal stripes, and of the per-column medians,
which grows with vertical ones.

| Input | Rows, `trendfill` | Rows, `'x'` | Rows, `'y'` | Columns, `trendfill` | Columns, `'x'` | Columns, `'y'` |
|---|---|---|---|---|---|---|
| tunicate CNF | 0.009<!--m:spline1d_axis.tunicate.trendfill.row_median_std_nm--> | 0.007<!--m:spline1d_axis.tunicate.x.row_median_std_nm--> | 0.062<!--m:spline1d_axis.tunicate.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.tunicate.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.x.column_median_std_nm--> | 0.015<!--m:spline1d_axis.tunicate.y.column_median_std_nm--> |
| artificial, isotropic | 0.011<!--m:spline1d_axis.art_iso.trendfill.row_median_std_nm--> | 0.013<!--m:spline1d_axis.art_iso.x.row_median_std_nm--> | 0.039<!--m:spline1d_axis.art_iso.y.row_median_std_nm--> | 0.012<!--m:spline1d_axis.art_iso.trendfill.column_median_std_nm--> | 0.026<!--m:spline1d_axis.art_iso.x.column_median_std_nm--> | 0.019<!--m:spline1d_axis.art_iso.y.column_median_std_nm--> |
| artificial, anisotropic | 0.005<!--m:spline1d_axis.art_aniso.trendfill.row_median_std_nm--> | 0.006<!--m:spline1d_axis.art_aniso.x.row_median_std_nm--> | 0.016<!--m:spline1d_axis.art_aniso.y.row_median_std_nm--> | 0.011<!--m:spline1d_axis.art_aniso.trendfill.column_median_std_nm--> | 0.022<!--m:spline1d_axis.art_aniso.x.column_median_std_nm--> | 0.014<!--m:spline1d_axis.art_aniso.y.column_median_std_nm--> |
| higher-plant TOC | 0.224<!--m:spline1d_axis.hplantTOC.trendfill.row_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.row_median_std_nm--> | 0.286<!--m:spline1d_axis.hplantTOC.y.row_median_std_nm--> | 0.005<!--m:spline1d_axis.hplantTOC.trendfill.column_median_std_nm--> | 0.006<!--m:spline1d_axis.hplantTOC.x.column_median_std_nm--> | 0.011<!--m:spline1d_axis.hplantTOC.y.column_median_std_nm--> |
| Bruker NDTOC | 0.019<!--m:spline1d_axis.NDTOC.trendfill.row_median_std_nm--> | 0.019<!--m:spline1d_axis.NDTOC.x.row_median_std_nm--> | 0.307<!--m:spline1d_axis.NDTOC.y.row_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.trendfill.column_median_std_nm--> | 0.015<!--m:spline1d_axis.NDTOC.x.column_median_std_nm--> | 0.036<!--m:spline1d_axis.NDTOC.y.column_median_std_nm--> |

Along `'y'`, the per-row spread was larger than with `trendfill` on every
input. Rendered, the calibrated images along `'y'` carry bright and dark
horizontal bands across the whole image on the tunicate, Bruker and higher-plant
inputs, and the scan-line glitch of the higher-plant scan stays. Along `'x'`,
that glitch is removed on the higher-plant scan, and a horizontal streak
that `trendfill` leaves on the tunicate scan is gone; but a dark rim, visibly
deeper than with `trendfill`, forms along the right side of fibers running
close to vertical on the tunicate and both artificial scans; the inputs whose
per-column spread along `'x'` exceeds that of `trendfill` are the same ones.

### 1.7 Smoothing along X only

Each test input was calibrated by the default `trendfill` with the
Savitzky–Golay smoothing of the background along X only, as the code does, and
along X and then Y (experiment savgol_axis). The table gives the spread
(standard deviation, nm) of the per-row medians of the background (pixels more
than 5<!--n:definition--> px from the union of the two binarized masks), which grows with
horizontal stripes.

| Input | Rows, X only | Rows, X and Y |
|---|---|---|
| tunicate CNF | 0.009<!--m:savgol_axis.tunicate.x_only.row_median_std_nm--> | 0.070<!--m:savgol_axis.tunicate.x_and_y.row_median_std_nm--> |
| artificial, isotropic | 0.011<!--m:savgol_axis.art_iso.x_only.row_median_std_nm--> | 0.073<!--m:savgol_axis.art_iso.x_and_y.row_median_std_nm--> |
| artificial, anisotropic | 0.005<!--m:savgol_axis.art_aniso.x_only.row_median_std_nm--> | 0.070<!--m:savgol_axis.art_aniso.x_and_y.row_median_std_nm--> |
| higher-plant TOC | 0.224<!--m:savgol_axis.hplantTOC.x_only.row_median_std_nm--> | 0.291<!--m:savgol_axis.hplantTOC.x_and_y.row_median_std_nm--> |
| Bruker NDTOC | 0.016<!--m:savgol_axis.NDTOC.x_only.row_median_std_nm--> | 0.046<!--m:savgol_axis.NDTOC.x_and_y.row_median_std_nm--> |
Smoothing along Y as well made the per-row spread larger on every input.
Rendered, the images smoothed along both axes carry horizontal streaks across
the tunicate, artificial isotropic and higher-plant scans, which the X-only
smoothing does not leave; the Bruker scan looks much the same either way.

### 1.8 When `spline1d` adds the trend back

`spline1d` adds the trend back before the Savitzky–Golay smoothing, `trendfill`
after it. Each test input was calibrated by `spline1d` both ways (experiment
spline1d_trend_order); the table gives the largest difference in calibrated
height (nm).

| Input | Largest difference (nm) |
|---|---|
| tunicate CNF | 0.006<!--m:spline1d_trend_order.tunicate.max_difference_nm--> |
| artificial, isotropic | 0.004<!--m:spline1d_trend_order.art_iso.max_difference_nm--> |
| artificial, anisotropic | 0.005<!--m:spline1d_trend_order.art_aniso.max_difference_nm--> |
| higher-plant TOC | 0.000<!--m:spline1d_trend_order.hplantTOC.max_difference_nm--> |
| Bruker NDTOC | 0.000<!--m:spline1d_trend_order.NDTOC.max_difference_nm--> |
Because the smoothing is linear, the two orders differ only by the trend minus
its smoothed self, which is largest where the trend curves most along X. On
every input the difference stays far below the 0.3<!--c:lib/pipeline.py::ProcParams.global_threshold--> nm binarization threshold.

## 2. Binarization

See [Analysis algorithms](algorithms.md) §2.

### 2.1 The edge map of the linearity filter

Up to 1.0.0 the edge map was built from the whole mask inside the bounding box.
On all 5<!--m:hough_edge_map.identical--> bundled scans the final binarized mask is bit-identical either way
(experiment hough_edge_map).

### 2.2 Ridge recovery

On the tunicate scan 99.8<!--m:ridge_hysteresis.ridge.far_below_low_percent--> % of the pixels at least 10<!--n:value tried--> px from the
binarized mask lie below the low level of the hysteresis on the ridge response
(experiment ridge_hysteresis).
<!-- TODO(review): the contrast with raw amplitude is not reproduced: on the tunicate scan hysteresis on the calibrated heights covered 11.6 % of the image against 7.7 % for the ridge response (experiment ridge_hysteresis), with no spreading across it. -->
<!-- TODO(review): a measured example of subtracting the accepted mask before the component pass (one 10 µm scan, 56 candidate components, the longest 1476 nm) came from a scan that is not in the repository and was removed. On the bundled scans the candidates that reach ridge_min_length_nm are a horizontal scan-line artefact (higher-plant scan) and short pieces at the border and at crossings (tunicate scan), not fibers (experiment ridge_recovery_bundled, rendered). -->
<!-- TODO(review): that candidates below about 100 nm stop being distinguishable from particle skirts and tip artefacts by eye was a visual judgment made while evaluating the ridge filter; no experiment in scripts/measure_docs.py reproduces it. -->

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
| tunicate CNF | 15.6<!--m:local_threshold.tunicate.global.mask_width_px--> → 10.1<!--m:local_threshold.tunicate.both.mask_width_px--> | 1<!--m:local_threshold.tunicate.global.mask_components--> → 9<!--m:local_threshold.tunicate.both.mask_components--> | 68<!--m:local_threshold.tunicate.global.branch_points--> → 33<!--m:local_threshold.tunicate.both.branch_points--> | 25<!--m:local_threshold.tunicate.removed_percent_of_crest--> / 83<!--m:local_threshold.tunicate.kept_percent_of_crest--> |
| artificial, isotropic | 17.4<!--m:local_threshold.art_iso.global.mask_width_px--> → 11.2<!--m:local_threshold.art_iso.both.mask_width_px--> | 2<!--m:local_threshold.art_iso.global.mask_components--> → 2<!--m:local_threshold.art_iso.both.mask_components--> | 0<!--m:local_threshold.art_iso.global.branch_points--> → 0<!--m:local_threshold.art_iso.both.branch_points--> | 22<!--m:local_threshold.art_iso.removed_percent_of_crest--> / 85<!--m:local_threshold.art_iso.kept_percent_of_crest--> |
| artificial, anisotropic | 15.4<!--m:local_threshold.art_aniso.global.mask_width_px--> → 10.0<!--m:local_threshold.art_aniso.both.mask_width_px--> | 4<!--m:local_threshold.art_aniso.global.mask_components--> → 3<!--m:local_threshold.art_aniso.both.mask_components--> | 0<!--m:local_threshold.art_aniso.global.branch_points--> → 0<!--m:local_threshold.art_aniso.both.branch_points--> | 22<!--m:local_threshold.art_aniso.removed_percent_of_crest--> / 84<!--m:local_threshold.art_aniso.kept_percent_of_crest--> |
| higher-plant TOC | 12.2<!--m:local_threshold.hplantTOC.global.mask_width_px--> → 9.0<!--m:local_threshold.hplantTOC.both.mask_width_px--> | 10<!--m:local_threshold.hplantTOC.global.mask_components--> → 7<!--m:local_threshold.hplantTOC.both.mask_components--> | 6<!--m:local_threshold.hplantTOC.global.branch_points--> → 5<!--m:local_threshold.hplantTOC.both.branch_points--> | 34<!--m:local_threshold.hplantTOC.removed_percent_of_crest--> / 75<!--m:local_threshold.hplantTOC.kept_percent_of_crest--> |
| Bruker NDTOC | 12.9<!--m:local_threshold.NDTOC.global.mask_width_px--> → 9.6<!--m:local_threshold.NDTOC.both.mask_width_px--> | 16<!--m:local_threshold.NDTOC.global.mask_components--> → 20<!--m:local_threshold.NDTOC.both.mask_components--> | 160<!--m:local_threshold.NDTOC.global.branch_points--> → 77<!--m:local_threshold.NDTOC.both.branch_points--> | 35<!--m:local_threshold.NDTOC.removed_percent_of_crest--> / 72<!--m:local_threshold.NDTOC.kept_percent_of_crest--> |

Rendered over the height images of all 5<!--m:kink_reference.scans--> bundled scans, the pixels the local threshold removes are the
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

On the 5<!--m:linearity_filter.inputs--> test inputs (experiment linearity_filter), $s_{\text{ratio}}$ reached
3.36<!--m:linearity_filter.s_ratio_max-->, and 51<!--m:linearity_filter.s_ratio_above_one--> components scored $s_{\text{ratio}} > 1$. The filter removed
251<!--m:linearity_filter.removed_reaching_h_length--> components whose bounding box reaches `h_length`; each was rendered over the
calibrated height image and judged by eye. Most were background texture,
particles and the scan-line glitches of the higher-plant scan, but 7<!--m:linearity_filter.removed_fiber_pieces-->
were pieces of real fibers: short bent or kinked pieces (on the tunicate scan)
and fiber ends cut by the image border (on the artificial anisotropic,
higher-plant and Bruker scans).

On a synthetic band along the rows (area 865<!--m:linearity_filter.band.horizontal.area--> pixels), Canny found
14<!--m:linearity_filter.band.horizontal.edge_pixels--> edge pixels in the bounding-box crop, all at the rounded ends, the score was
0<!--m:linearity_filter.band.horizontal.s_ratio-->, and the band was removed; the same band at 45<!--n:definition-->° (area 620<!--m:linearity_filter.band.diagonal.area--> pixels)
gave 356<!--m:linearity_filter.band.diagonal.edge_pixels--> edge pixels and a score of 1.35<!--m:linearity_filter.band.diagonal.s_ratio--> and was kept.

### 2.6 Components the linearity filter does not test

The linearity filter keeps components of 1000<!--n:literal in the quoted code--> pixels or more without testing them.
Each test input was filtered as the code does and with every component tested
(experiment linearity_large_exemption); the times are wall times of the filter
on one machine and vary with the machine and its load.

| Input | Components of 1000<!--n:literal in the quoted code--> px or more | Of those, removed if tested | Time as in the code (s) | Time testing all (s) |
|---|---|---|---|---|
| tunicate CNF | 9<!--m:linearity_large_exemption.tunicate.large_components--> | 0<!--m:linearity_large_exemption.tunicate.large_removed_if_tested--> | 0.071<!--m:linearity_large_exemption.tunicate.code.seconds--> | 1.386<!--m:linearity_large_exemption.tunicate.all.seconds--> |
| artificial, isotropic | 1<!--m:linearity_large_exemption.art_iso.large_components--> | 0<!--m:linearity_large_exemption.art_iso.large_removed_if_tested--> | 0.011<!--m:linearity_large_exemption.art_iso.code.seconds--> | 0.053<!--m:linearity_large_exemption.art_iso.all.seconds--> |
| artificial, anisotropic | 3<!--m:linearity_large_exemption.art_aniso.large_components--> | 0<!--m:linearity_large_exemption.art_aniso.large_removed_if_tested--> | 0.011<!--m:linearity_large_exemption.art_aniso.code.seconds--> | 0.093<!--m:linearity_large_exemption.art_aniso.all.seconds--> |
| higher-plant TOC | 4<!--m:linearity_large_exemption.hplantTOC.large_components--> | 0<!--m:linearity_large_exemption.hplantTOC.large_removed_if_tested--> | 0.097<!--m:linearity_large_exemption.hplantTOC.code.seconds--> | 0.278<!--m:linearity_large_exemption.hplantTOC.all.seconds--> |
| Bruker NDTOC | 15<!--m:linearity_large_exemption.NDTOC.large_components--> | 0<!--m:linearity_large_exemption.NDTOC.large_removed_if_tested--> | 1.363<!--m:linearity_large_exemption.NDTOC.code.seconds--> | 3.123<!--m:linearity_large_exemption.NDTOC.all.seconds--> |
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
1.0<!--m:border_drift.padded.end_median_px--> px from the crest (experiment border_drift). On all 5<!--m:border_padding.identical_inside_band--> bundled scans the
skeleton outside a 12<!--c:lib/skeletonizer.py::DEFAULT_BORDER_PAD--> px border band was identical with and without the
correction (experiment border_padding), but that is not a guarantee.

### 3.2 `bp_height` against the fiber heights

The default `bp_height` of 10<!--c:lib/pipeline.py::ProcParams.bp_height--> nm lies above the median height under the
skeleton on every bundled scan (1.7<!--m:bg_stats.hplantTOC.skeleton_height_median_nm--> to 7.9<!--m:bg_stats.tunicate.skeleton_height_median_nm--> nm, §1.1). At the branch points of
the first skeleton (experiment branch_pruning) the median height is 9.3<!--m:branch_pruning.tunicate.bp_height_median_nm--> nm on
the tunicate scan, where 41<!--m:branch_pruning.tunicate.bp_at_or_above_percent--> % of the branch points reach `bp_height`. On the other
scans none does (median 1.9<!--m:branch_pruning.hplantTOC.bp_height_median_nm--> nm on the higher-plant scan, 2.0<!--m:branch_pruning.NDTOC.bp_height_median_nm--> nm on the Bruker
scan, 7.9<!--m:branch_pruning.art_iso.bp_height_median_nm--> and 7.6<!--m:branch_pruning.art_aniso.bp_height_median_nm--> nm on the artificial scans): every branch point is low, and
the split by height does nothing there.

Rendered on the tunicate height image, the branch points at or above `bp_height`
lie where two fibers cross or one joins another, where the heights of two
overlapping fibers add up. The branch points below it include crossings and
junctions as well, for instance of the thinner fibers in the tangle at the
bottom of the scan, so on this scan a low branch point is not a sign of a
spurious branch.

The height-gated pruning changes little in the final skeleton. Skipping it
changes 1<!--m:branch_pruning.tunicate.skipped.final_changed_pixels--> of 7975<!--m:branch_pruning.tunicate.final_pixels--> skeleton pixels on the tunicate scan,
24<!--m:branch_pruning.hplantTOC.skipped.final_changed_pixels--> of 1789<!--m:branch_pruning.hplantTOC.final_pixels--> on the higher-plant scan, 161<!--m:branch_pruning.NDTOC.skipped.final_changed_pixels--> of 9030<!--m:branch_pruning.NDTOC.final_pixels--> on the Bruker scan and
0<!--m:branch_pruning.art_iso.skipped.final_changed_pixels--> on the artificial scans; treating every branch point as low changes
0<!--m:branch_pruning.tunicate.all_low.final_changed_pixels--> pixels on the tunicate scan. The short arms it removes are removed again
by the spur pruning of [Analysis algorithms](algorithms.md) §3.5, which judges by
length alone: with the spur pruning switched off, skipping the height-gated
pruning changes 139<!--m:branch_pruning.tunicate.spurs_off.skipped.final_changed_pixels-->, 161<!--m:branch_pruning.hplantTOC.spurs_off.skipped.final_changed_pixels--> and 899<!--m:branch_pruning.NDTOC.spurs_off.skipped.final_changed_pixels--> pixels on the same three scans.

### 3.3 Loop enclosures

On the bundled scans each loop left by an interior hole of the mask puts 1<!--m:loop_candidates.all.branch_points_range[0]--> to
4<!--m:loop_candidates.all.branch_points_range[1]--> branch points on its ring. All 18<!--m:loop_candidates.candidates--> enclosures small enough to qualify
for filling lie in a fiber (10<!--m:loop_candidates.fiber.count-->) or at a crossing (8<!--m:loop_candidates.crossing.count-->), judged by eye on the
height image, and their median interior height is 78<!--m:loop_candidates.all.ratio_percent_range[0]-->–105<!--m:loop_candidates.all.ratio_percent_range[1]--> % of the
surrounding ridge's median (experiment loop_candidates). No sliver enclosed by
two distinct fibers touching twice qualifies on the bundled scans.
Such slivers were built synthetically instead (§3.4).

### 3.4 Two fibers enclosing a sliver

On 24<!--m:loop_sliver.scans--> synthetic scans of two straight fibers that part into a lens-shaped
gap and rejoin (Gaussian sections 4<!--n:value tried--> nm high with standard deviations of 1.5<!--n:value tried-->, 2<!--n:value tried-->
and 3<!--n:value tried--> px, gaps of 4<!--n:value tried--> to 12<!--n:value tried--> px; experiment loop_sliver), 5<!--m:loop_sliver.candidates--> enclosures were small
enough for `collapse_skeleton_loops` to consider. Their median interior height
was 53<!--m:loop_sliver.ratio_percent_range[0]-->–97<!--m:loop_sliver.ratio_percent_range[1]--> % of the surrounding ridge's, because the flanks of two close
fibers overlap, so all 5<!--m:loop_sliver.filled--> passed the 0.3<!--c:lib/skeletonizer.py::DEFAULT_LOOP_HEIGHT_RATIO--> guard and were filled; rendered,
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
| tunicate CNF | 0<!--m:border_margins.tunicate.branch_margin_2.changed_px--> | 0<!--m:border_margins.tunicate.branch_margin_2.farthest_from_border_px--> | 10<!--m:border_margins.tunicate.spur_margin_wide.changed_px--> | 12<!--m:border_margins.tunicate.spur_margin_wide.farthest_from_border_px--> |
| artificial, isotropic | 1<!--m:border_margins.art_iso.branch_margin_2.changed_px--> | 9<!--m:border_margins.art_iso.branch_margin_2.farthest_from_border_px--> | 2<!--m:border_margins.art_iso.spur_margin_wide.changed_px--> | 9<!--m:border_margins.art_iso.spur_margin_wide.farthest_from_border_px--> |
| artificial, anisotropic | 0<!--m:border_margins.art_aniso.branch_margin_2.changed_px--> | 0<!--m:border_margins.art_aniso.branch_margin_2.farthest_from_border_px--> | 0<!--m:border_margins.art_aniso.spur_margin_wide.changed_px--> | 0<!--m:border_margins.art_aniso.spur_margin_wide.farthest_from_border_px--> |
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
58<!--m:diagonal_ybranch.all.only_diagonal_y--> of the 115<!--m:diagonal_ybranch.all.branch_points--> branch points: 16<!--m:diagonal_ybranch.tunicate.only_diagonal_y--> of 33<!--m:diagonal_ybranch.tunicate.branch_points--> on the tunicate scan, 3<!--m:diagonal_ybranch.hplantTOC.only_diagonal_y--> of 5<!--m:diagonal_ybranch.hplantTOC.branch_points--> on the
higher-plant TOC scan and 39<!--m:diagonal_ybranch.NDTOC.only_diagonal_y--> of 77<!--m:diagonal_ybranch.NDTOC.branch_points--> on the Bruker scan; the artificial scans have
no branch point. Each pixel only this kernel finds has at least three
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
crest) on all 5<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> of them, 1.1<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->–1.4<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> times as far as the default line
(root-mean-square lateral offset), and the kink rule reported 0<!--m:synthetic_centerline.ribbons.kinks_reported--> kinks on
the 6<!--m:synthetic_centerline.ribbons.count--> ribbon scans, which include a round control fiber (experiment
synthetic_centerline). A lower level was not uniformly better: the
quarter-height midpoint sat closer to the axis than the default line on 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> of
the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> ribbons, but background bumps pulled it up to 3.5<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm off the thin, round
control fiber.

**Why a quarter width.** The smoothing width sets how close two features may
lie before the centerline averages them into one. The test used the same-sense
corner pairs of the synthetic suite: 8<!--m:synthetic_centerline.pairs--> scans, each holding two
60<!--n:value tried-->° corners 1–3<!--n:value tried--> $W$ apart:

| Smoothing of the frame and offsets | Corner pairs judged as one bend | Median distance, corner vertex to centerline (range over the spacings) | Median distance to the true centerline |
|---|---|---|---|
| $W/2$ | 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> of 8<!--m:synthetic_centerline.pairs--> | 0.97<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[0]-->–1.17<!--m:synthetic_centerline.pairs_w2.vertex_median_px_range[1]--> px | 0.12<!--m:synthetic_centerline.pairs_w2.centerline_median_px--> px |
| $W/4$ (default) | 0<!--m:synthetic_centerline.pairs_w4.merged_pairs--> of 8<!--m:synthetic_centerline.pairs--> | 0.63<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[0]-->–0.84<!--m:synthetic_centerline.pairs_w4.vertex_median_px_range[1]--> px | 0.10<!--m:synthetic_centerline.pairs_w4.centerline_median_px--> px |

**Accuracy against known centerlines.** On the 60<!--m:synthetic_centerline.scans_af--> scans of groups A–F of the
synthetic suite, rendered with a spherical probe (corners, zigzags, corner
pairs, corners near an end, straight fibers, arcs, meanders, crossings and
junctions):

| | Median distance to the true centerline | 95<!--n:definition-->th percentile | Contour length error (range over groups of scans) |
|---|---|---|---|
| Half-maximum centerline | 0.11<!--m:synthetic_centerline.half_max_025w.median_px--> px | 0.35<!--m:synthetic_centerline.half_max_025w.p95_px--> px | −1.5<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[0]--> to +0.5<!--m:synthetic_centerline.half_max_025w.length_error_percent_range[1]--> % |
| Skeleton track (corrected chain-code length) | 0.29<!--m:synthetic_centerline.skeleton_track.median_px--> px | 0.90<!--m:synthetic_centerline.skeleton_track.p95_px--> px | −1.4<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[0]--> to +2.2<!--m:synthetic_centerline.skeleton_track.length_error_percent_range[1]--> % |

### 4.3 The selectable centerlines compared

Two caveats apply to the table:

- **Median distance** is, for each of the groups A–F of the synthetic suite, the
  median distance to the true centerline in nm; the column gives the range
  over the groups (experiment synthetic_centerline).
- **Real scans** scores a centerline against the visual reference with the
  excess-turning rule, as clear kinks found / missed / reported bends that
  match no marked kink. Detections displaced 1–2<!--n:definition--> widths from a mark (the
  "Found 1–2<!--n:definition--> widths from the mark" column of §4.4) and "merged" marks, where one
  detection spans two marks, are left out, so found and missed do not add up
  to 64<!--m:kink_reference.clear_marks-->. Only three centerlines were scored.

| `centerline_method` | Median distance (nm) | Real scans | Notes |
|---|---|---|---|
| `"half_max_025w"` (default) | 0.21<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[0]-->–0.24<!--m:synthetic_centerline.half_max_025w.group_median_nm_range[1]--> | 60<!--m:kink_reference.default.found--> / 3<!--m:kink_reference.default.missed--> / 64<!--m:kink_reference.default.false--> | |
| `"half_max_05w"` | 0.20<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[0]-->–0.25<!--m:synthetic_centerline.half_max_05w.group_median_nm_range[1]--> | 56<!--m:kink_reference.hm05.found--> / 4<!--m:kink_reference.hm05.missed--> / 43<!--m:kink_reference.hm05.false--> | The fewest unmatched bends of the three scored, but it merged the two corners of 2<!--m:synthetic_centerline.pairs_w2.merged_pairs--> of the 8<!--m:synthetic_centerline.pairs--> synthetic same-sense pairs, and slightly stronger smoothing raised the misses to 10–13<!--m:kink_reference.hm05_stronger.missed_range-->. |
| `"skeleton_pixels"` | 0.54<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[0]-->–0.62<!--m:synthetic_centerline.skeleton_pixels.group_median_nm_range[1]--> | 62<!--m:kink_reference.skeleton_pixels.found--> / 0<!--m:kink_reference.skeleton_pixels.missed--> / 135<!--m:kink_reference.skeleton_pixels.false--> | The staircase and the swing at junctions read as bends. |
| `"smoothed_skeleton_05w"`, `"smoothed_skeleton_1w"` | 0.33<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[0]-->–0.56<!--m:synthetic_centerline.smoothed_skeleton_05w.group_median_nm_range[1]--> / 0.39<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[0]-->–0.95<!--m:synthetic_centerline.smoothed_skeleton_1w.group_median_nm_range[1]--> | not scored | |
| `"quarter_max"` | 0.20<!--m:synthetic_centerline.quarter_max.group_median_nm_range[0]-->–0.24<!--m:synthetic_centerline.quarter_max.group_median_nm_range[1]--> | not scored | Closer to the axis than the default on 4<!--m:synthetic_centerline.ribbons.quarter_closer_than_default--> of the 5<!--m:synthetic_centerline.ribbons.anisotropic_count--> twisted ribbons, but pulled up to 3.5<!--m:synthetic_centerline.G_circle_d3.max_nm.quarter_max--> nm off the thin, round control fiber. |
| `"centroid"` | 0.32<!--m:synthetic_centerline.centroid.group_median_nm_range[0]-->–0.38<!--m:synthetic_centerline.centroid.group_median_nm_range[1]--> | not scored | |
| `"crest"` | 0.42<!--m:synthetic_centerline.crest.group_median_nm_range[0]-->–0.48<!--m:synthetic_centerline.crest.group_median_nm_range[1]--> | not scored | The farthest from the axis on all 5<!--m:synthetic_centerline.ribbons.crest_farthest_of_three--> twisted ribbons (1.1<!--m:synthetic_centerline.ribbons.crest_over_default_range[0]-->–1.4<!--m:synthetic_centerline.ribbons.crest_over_default_range[1]--> times as far as the default). |

### 4.4 The kink rule against the visual reference

"Unmatched" counts reported bends that match no marked kink; these are the
false detections referred to below.

| Rule | Found | Found 1–2<!--n:definition--> widths from the mark | Missed | Unmatched |
|---|---|---|---|---|
| Excess-turning rule, on the centerline | 60<!--m:kink_reference.default.found--> | 1<!--m:kink_reference.default.displaced--> | 3<!--m:kink_reference.default.missed--> | 64<!--m:kink_reference.default.false--> |
| Earlier polyline rule, on the skeleton track | 52<!--m:kink_reference.old_rule.found--> | 4<!--m:kink_reference.old_rule.displaced--> | 8<!--m:kink_reference.old_rule.missed--> | 76<!--m:kink_reference.old_rule.false--> |

The earlier rule's row applies `KinkDetector.kinks_and_decomposed_from_track`,
kept for bundles of format 1.0<!--n:bundle format version--> (`kink_decompose_px` = 3<!--c:lib/pipeline.py::ProcParams.kink_decompose_px--> px, `kinkangle_deg` =
150<!--c:lib/pipeline.py::ProcParams.kinkangle_deg-->°), to the traced skeleton tracks of the same images.

The lengths of the rule are multiples of $W$ set from $W$ being the resolution
of the image; they were checked against this reference, not fitted to it.
Changing any one of them to a neighbouring value moved the clear kinks found
within 56–62<!--m:kink_reference.sens_all.found_range--> and the unmatched bends within 48–80<!--m:kink_reference.sens_all.false_range--> (60<!--m:kink_reference.default.found--> and 64<!--m:kink_reference.default.false--> at
the defaults). The largest drops came from stronger smoothing: 56<!--m:kink_reference.sens_heading_0.35.found--> with the
heading smoothed over 0.35<!--n:value tried--> W, 57<!--m:kink_reference.sens_line_x1.4.found--> with the centerline smoothing ×1.4<!--n:value tried-->.

| Length | Default | Neighbouring values tried |
|---|---|---|
| centerline smoothing | W/4 | ×0.6<!--n:value tried-->, ×1.4<!--n:value tried--> |
| window half-length $c$ | 0.75<!--c:lib/kink_detector.py::_CORE_WIDTHS--> W | 0.6<!--n:value tried--> W, 0.9<!--n:value tried--> W |
| flank length $f$ | 1.0<!--c:lib/kink_detector.py::_FLANK_WIDTHS--> W | 0.75<!--n:value tried--> W, 1.5<!--n:value tried--> W |
| heading smoothing $\sigma$ | 0.25<!--c:lib/kink_detector.py::_HEADING_SIGMA_WIDTHS--> W | 0.15<!--n:value tried--> W, 0.35<!--n:value tried--> W |
| end margin | 1.5<!--c:lib/kink_detector.py::END_MARGIN_WIDTHS--> W | 1.0<!--n:value tried--> W, 2.0<!--n:value tried--> W |
| suppression radius | 0.75<!--c:lib/kink_detector.py::_SUPPRESS_WIDTHS--> W | 0.5<!--n:value tried--> W, 1.0<!--n:value tried--> W |

Without the candidates taken from the maxima of the window turning itself, the
rule found 56<!--m:turn_maxima.without.found--> instead of 60<!--m:turn_maxima.with.found--> of the clear reference kinks, and reported
47<!--m:turn_maxima.without.false--> instead of 64<!--m:turn_maxima.with.false--> unmatched bends (experiment turn_maxima).

### 4.5 The angle stored for a kink

The excess turning read low on sharp synthetic corners, where the probe and the
centerline round the apex:

| Corner turning | Excess turning read |
|---|---|
| 40<!--n:value tried-->° | 37–38<!--m:synthetic_kinks.corner40.excess_read_range_deg-->° |
| 60<!--n:value tried-->° | 52–56<!--m:synthetic_kinks.corner60.excess_read_range_deg-->° |
| 90<!--n:value tried-->° | 83–85<!--m:synthetic_kinks.corner90.excess_read_range_deg-->° |
| 120<!--n:value tried-->° | 101–110<!--m:synthetic_kinks.corner120.excess_read_range_deg-->° |

A bend just above the threshold can therefore read below it: the bend drawn at
33.5<!--m:test_suite_bend.drawn_turn_deg-->° in the test suite reads 26.5<!--m:test_suite_bend.read_excess_deg-->° (experiment test_suite_bend). This is why the
angle stored for a kink is read from its arms rather than taken as 180<!--n:definition-->° minus
the excess. On synthetic corners of 120<!--n:example-->°, 140<!--n:example-->° and 145<!--n:example-->° interior angle rendered
with a 10<!--c:scripts/kink_rule_sweep.py::TIP_RADIUS_NM--> nm probe, the median angle error over the corners found, pooled over
the 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> noise levels, was:

| Apparent width | Arm angle | 180<!--n:definition-->° minus the excess |
|---|---|---|
| 3<!--m:kink_rule_sweep.W5.measured_width_px--> px | 4.2<!--m:kink_rule_sweep.W5.arm_error_deg-->° | 4.6<!--m:kink_rule_sweep.W5.excess_error_deg-->° |
| 5.5<!--m:kink_rule_sweep.W8.measured_width_px--> px | 1.7<!--m:kink_rule_sweep.W8.arm_error_deg-->° | 7.9<!--m:kink_rule_sweep.W8.excess_error_deg-->° |
| 11<!--m:kink_rule_sweep.W16.measured_width_px--> px | 1.7<!--m:kink_rule_sweep.W16.arm_error_deg-->° | 3.4<!--m:kink_rule_sweep.W16.excess_error_deg-->° |

### 4.6 Synthetic shapes

- On synthetic zigzags, corners 1.5–3<!--n:value tried--> $W$ apart were all found
  (30<!--m:synthetic_kinks.zigzag_1.5W_up.found--> of 30<!--m:synthetic_kinks.zigzag_1.5W_up.clear-->), but corners 1<!--n:value tried--> $W$ apart only 4<!--m:synthetic_kinks.zigzag1W.found--> of 10<!--m:synthetic_kinks.zigzag1W.clear-->.
- No bend was reported on straight fibers (0<!--m:synthetic_kinks.straight.reported--> on 2<!--m:synthetic_kinks.straight.scans--> scans), arcs of radius
  3–10<!--n:value tried--> $W$ (0<!--m:synthetic_kinks.arcs.reported--> on 6<!--m:synthetic_kinks.arcs.scans-->), crossings and junctions (0<!--m:synthetic_kinks.crossings_branches.reported--> on 10<!--m:synthetic_kinks.crossings_branches.scans-->) or twisted
  ribbons (0<!--m:synthetic_centerline.ribbons.kinks_reported--> on 6<!--m:synthetic_centerline.ribbons.count-->).
- Every isolated corner of 40<!--n:value tried-->° or more was found (8<!--m:synthetic_kinks.corners_40_up.found--> of 8<!--m:synthetic_kinks.corners_40_up.clear-->).
- 12<!--m:synthetic_kinks.sines.reported--> bends were reported on 4<!--m:synthetic_kinks.sines.scans--> sine meanders whose tightest radius is
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
| 4<!--n:value tried--> | 5<!--m:kink_reference.noise4.lost--> | 10<!--m:kink_reference.noise4.fewer_false--> |

The false detections on these scans are rounded bends, tangles, bends next to
crossings, and shallow bends whose excess turning only just clears the
threshold, not noise: 28<!--m:kink_reference.default.false_excess_30_40--> of the 64<!--m:kink_reference.default.false--> have an excess of 30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->–40<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|190 - v-->°. For
11<!--m:kink_reference.default.false_arm_turn_below_threshold--> of them the turning read from the arms (180<!--n:definition-->° − `ka`) falls below
30<!--c:lib/pipeline.py::ProcParams.kinkangle_deg|180 - v-->°, because the arm angle is measured apart from the excess turning the rule
tests. A heavily bent fiber's own kinks raise its floor, which is where the
lost clear kinks lay. On the synthetic sweep the floor changed no corner found
anywhere, and changed the false positives only at the finest pixel size with
the heaviest noise (11<!--m:kink_rule_sweep.W16.measured_width_px--> px width, 0.30<!--n:value tried--> nm pixel noise), where it cut them from
3.9<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> to 3.7<!--m:kink_rule_sweep.W16.n0.30.k3.fp_per_um--> per µm without recovering the corners that condition had already
lost.

### 4.8 Where the rule applied in the sweep

The apparent width here is the $W$ the pipeline measured on the straight fiber
of each setting, not the width the synthetic scan was designed with. Each
corner was drawn at 3<!--c:scripts/kink_rule_sweep.py::len(NOISES_NM)--> noise levels with 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> seeds, 6<!--m:kink_rule_sweep.W5.kink120.cases--> scans per angle and
width.

- At 3<!--m:kink_rule_sweep.W5.measured_width_px--> px, the corners of 120<!--n:example-->° and 145<!--n:example-->° interior angle were all found
  (6<!--m:kink_rule_sweep.W5.kink120.found--> and 6<!--m:kink_rule_sweep.W5.kink145.found--> of 6<!--m:kink_rule_sweep.W5.kink145.cases-->) and the 140<!--n:example-->° corner in 4<!--m:kink_rule_sweep.W5.kink140.found--> of 6<!--m:kink_rule_sweep.W5.kink140.cases-->. In the missed
  140<!--n:example-->° cases the fiber was traced unbroken through the corner, so the miss is
  the rule's, not the tracing's. Why 140<!--n:example-->° was harder to find than 145<!--n:example-->° has
  not been established.
- At 5.5<!--m:kink_rule_sweep.W8.measured_width_px--> px every corner was found (6<!--m:kink_rule_sweep.W8.kink120.found-->, 6<!--m:kink_rule_sweep.W8.kink140.found--> and 6<!--m:kink_rule_sweep.W8.kink145.found--> of 6<!--m:kink_rule_sweep.W8.kink140.cases-->).
- At 11<!--m:kink_rule_sweep.W16.measured_width_px--> px each angle was found in 5<!--m:kink_rule_sweep.W16.kink120.found-->, 5<!--m:kink_rule_sweep.W16.kink140.found--> and 5<!--m:kink_rule_sweep.W16.kink145.found--> of 6<!--m:kink_rule_sweep.W16.kink140.cases-->: every time
  at pixel noise up to 0.15<!--n:value tried--> nm, and in 1<!--m:kink_rule_sweep.W16.n0.30.kink120.found--> of 2<!--c:scripts/kink_rule_sweep.py::len(SEEDS)--> scans at 0.30<!--n:value tried--> nm. At that noise
  the near-horizontal arm is drawn broken in the height image itself, the
  tracing split the fiber into many fragments, and false bends gathered on
  that arm. On the straight, arc and sine fibers of the same setting the rule
  reported 3.9<!--m:kink_rule_sweep.W16.n0.30.base.fp_per_um--> false bends per µm.
- There was no false positive on straight fibers, arcs or meanders at pixel
  noise up to 0.15<!--n:value tried--> nm at any width, and none on a 165<!--n:example-->° bend.
- At the coarsest pixel size of the sweep (5.2<!--c:scripts/kink_rule_sweep.py::APPARENT_WIDTH_NM|v / 3--> nm, where the fiber spans
  fewer pixels than at the 3<!--m:kink_rule_sweep.W5.measured_width_px--> px setting), the tracing itself was mostly broken,
  the width could not be measured, the fallback applied, and no corner was
  found. The rule still received traced fibers and judged them, but it
  reported no bend that matched a true corner.

### 4.9 The end margin

On the 3<!--n:count--> real bundled scans, 46<!--m:track_ends.hplantTOC.near_branch_percent-->–68<!--m:track_ends.tunicate.near_branch_percent--> % of track ends lie within 3<!--n:definition--> px of a
branch point (experiment track_ends): many track ends are cuts at a crossing,
not fiber ends.

At a margin of $1.0\,W$ the false detections on the bundled scans rose from
64<!--m:kink_reference.default.false--> to 80<!--m:kink_reference.sens_end_1.false--> without a further clear kink being found; at $2.0\,W$ they fell to
49<!--m:kink_reference.sens_end_2.false-->, but the synthetic corners 2<!--n:value tried--> $W$ from an end, judged at the default
(2<!--m:synthetic_kinks.margin_default.end2W.corners_judged--> of 2<!--m:synthetic_kinks.end_cases_per_distance-->), were no longer judged (0<!--m:synthetic_kinks.margin_2W.end2W.corners_judged-->). None of the 48<!--m:kink_reference.default.unjudged--> bends left
unjudged on the bundled scans lay on a clear reference kink.

### 4.10 Crest height against the height at the centerline

On every traceable skeleton component of every test input, with the default
centerline placed as `KinkDetector` places it (experiment crest_height), the
crest height was compared with the calibrated height read at the centerline, at
the reliable points:

| Input | Median difference (nm) | 90<!--n:definition-->th percentile (nm) | Median, % of crest | 90<!--n:definition-->th percentile, % of crest |
|---|---|---|---|---|
| tunicate CNF | 0.072<!--m:crest_height.tunicate.median_nm--> | 0.211<!--m:crest_height.tunicate.p90_nm--> | 0.941<!--m:crest_height.tunicate.median_percent--> | 2.620<!--m:crest_height.tunicate.p90_percent--> |
| artificial, isotropic | 0.108<!--m:crest_height.art_iso.median_nm--> | 0.234<!--m:crest_height.art_iso.p90_nm--> | 1.322<!--m:crest_height.art_iso.median_percent--> | 2.829<!--m:crest_height.art_iso.p90_percent--> |
| artificial, anisotropic | 0.075<!--m:crest_height.art_aniso.median_nm--> | 0.210<!--m:crest_height.art_aniso.p90_nm--> | 1.031<!--m:crest_height.art_aniso.median_percent--> | 2.975<!--m:crest_height.art_aniso.p90_percent--> |
| higher-plant TOC | 0.012<!--m:crest_height.hplantTOC.median_nm--> | 0.064<!--m:crest_height.hplantTOC.p90_nm--> | 0.712<!--m:crest_height.hplantTOC.median_percent--> | 3.573<!--m:crest_height.hplantTOC.p90_percent--> |
| Bruker NDTOC | 0.024<!--m:crest_height.NDTOC.median_nm--> | 0.128<!--m:crest_height.NDTOC.p90_nm--> | 1.227<!--m:crest_height.NDTOC.median_percent--> | 6.996<!--m:crest_height.NDTOC.p90_percent--> |
The crest height was never below the height at the centerline. Reading the
height at the centerline would therefore make the fiber lower, by the small but
one-sided amounts in the table, because the half-maximum midpoint lies beside the
crest on an asymmetric section.

### 4.11 Height near a cut end

On every test input, along the default centerline of each track at least 5<!--n:definition--> W long
(experiment cut_end_skirt), the crest height near each end was divided by the
track's median crest height and pooled by median, separately for ends cut at a
crossing (within 3<!--n:definition--> px of a branch point) and free ends. The artificial scans have
no cut end.

| Input | Cut ends | Ratio at a cut end | Back to 1.05<!--n:definition--> or less within (W) | Ratio at a free end |
|---|---|---|---|---|
| tunicate CNF | 49<!--m:cut_end_skirt.tunicate.cut_ends--> | 1.41<!--m:cut_end_skirt.tunicate.cut.ratio_at_end--> | 0.75<!--m:cut_end_skirt.tunicate.cut.back_within_widths--> | 1.03<!--m:cut_end_skirt.tunicate.free.ratio_at_end--> |
| higher-plant TOC | 7<!--m:cut_end_skirt.hplantTOC.cut_ends--> | 1.31<!--m:cut_end_skirt.hplantTOC.cut.ratio_at_end--> | 1.00<!--m:cut_end_skirt.hplantTOC.cut.back_within_widths--> | 0.93<!--m:cut_end_skirt.hplantTOC.free.ratio_at_end--> |
| Bruker NDTOC | 89<!--m:cut_end_skirt.NDTOC.cut_ends--> | 1.23<!--m:cut_end_skirt.NDTOC.cut.ratio_at_end--> | 0.50<!--m:cut_end_skirt.NDTOC.cut.back_within_widths--> | 0.69<!--m:cut_end_skirt.NDTOC.free.ratio_at_end--> |

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
| tunicate CNF | 7814<!--m:section_width_limit.tunicate.points--> | 87.3<!--m:section_width_limit.tunicate.reliable_full_percent--> | 82.4<!--m:section_width_limit.tunicate.reliable_half_percent--> |
| artificial, isotropic | 436<!--m:section_width_limit.art_iso.points--> | 97.9<!--m:section_width_limit.art_iso.reliable_full_percent--> | 95.9<!--m:section_width_limit.art_iso.reliable_half_percent--> |
| artificial, anisotropic | 963<!--m:section_width_limit.art_aniso.points--> | 98.4<!--m:section_width_limit.art_aniso.reliable_full_percent--> | 96.7<!--m:section_width_limit.art_aniso.reliable_half_percent--> |
| higher-plant TOC | 1764<!--m:section_width_limit.hplantTOC.points--> | 91.4<!--m:section_width_limit.hplantTOC.reliable_full_percent--> | 88.3<!--m:section_width_limit.hplantTOC.reliable_half_percent--> |
| Bruker NDTOC | 8601<!--m:section_width_limit.NDTOC.points--> | 81.4<!--m:section_width_limit.NDTOC.reliable_full_percent--> | 74.9<!--m:section_width_limit.NDTOC.reliable_half_percent--> |

The fiber of the tunicate scan that loses the most points, 146<!--m:section_width_limit.tunicate.most_lost.lost--> of its 919<!--m:section_width_limit.tunicate.most_lost.points-->,
was rendered over the calibrated height image with its cross-sections. The
points it loses are the straight stretch from its corner to the right border: a
single fiber, crossed once by another, whose sections are single-peaked with the
crest a little off the middle, so that one half is wider than 0.75<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS|v / 2--> W while the
full width stays within 1.5<!--c:lib/centerline.py::_MAX_SECTION_WIDTHS--> W.

## 5. Stripe-noise screening

### 5.1 The step threshold

`stripe_noise.evaluate_scan_lines` flags the boundary between two scan lines
whose median heights differ by more than 3<!--c:lib/stripe_noise.py::DEFAULT_STEP_THRESHOLD_NM--> nm. On the raw heights of each test
input, as GUI01 screens them (experiment stripe_threshold):

| Input | Flagged boundaries | Smallest flagged step (nm) | Largest unflagged step (nm) | Unflagged steps, percentile 99<!--n:definition--> (nm) |
|---|---|---|---|---|
| tunicate CNF | 0<!--m:stripe_threshold.tunicate.flagged--> | — | 2.71<!--m:stripe_threshold.tunicate.unflagged_max_step_nm--> | 1.24<!--m:stripe_threshold.tunicate.unflagged_p99_step_nm--> |
| artificial, isotropic | 0<!--m:stripe_threshold.art_iso.flagged--> | — | 1.59<!--m:stripe_threshold.art_iso.unflagged_max_step_nm--> | 1.03<!--m:stripe_threshold.art_iso.unflagged_p99_step_nm--> |
| artificial, anisotropic | 0<!--m:stripe_threshold.art_aniso.flagged--> | — | 1.59<!--m:stripe_threshold.art_aniso.unflagged_max_step_nm--> | 1.03<!--m:stripe_threshold.art_aniso.unflagged_p99_step_nm--> |
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
| tunicate CNF | 60<!--m:frame_margin.tunicate.fibers--> | 16<!--m:frame_margin.tunicate.margin_0.reaching--> | 16<!--m:frame_margin.tunicate.margin_2.reaching--> | 16<!--m:frame_margin.tunicate.margin_5.reaching--> |
| artificial, isotropic | 3<!--m:frame_margin.art_iso.fibers--> | 3<!--m:frame_margin.art_iso.margin_0.reaching--> | 3<!--m:frame_margin.art_iso.margin_2.reaching--> | 3<!--m:frame_margin.art_iso.margin_5.reaching--> |
| artificial, anisotropic | 4<!--m:frame_margin.art_aniso.fibers--> | 4<!--m:frame_margin.art_aniso.margin_0.reaching--> | 4<!--m:frame_margin.art_aniso.margin_2.reaching--> | 4<!--m:frame_margin.art_aniso.margin_5.reaching--> |
| higher-plant TOC | 14<!--m:frame_margin.hplantTOC.fibers--> | 2<!--m:frame_margin.hplantTOC.margin_0.reaching--> | 2<!--m:frame_margin.hplantTOC.margin_2.reaching--> | 2<!--m:frame_margin.hplantTOC.margin_5.reaching--> |
| Bruker NDTOC | 139<!--m:frame_margin.NDTOC.fibers--> | 17<!--m:frame_margin.NDTOC.margin_0.reaching--> | 17<!--m:frame_margin.NDTOC.margin_2.reaching--> | 18<!--m:frame_margin.NDTOC.margin_5.reaching--> |

Margins of 1<!--n:value tried--> and 2<!--n:value tried--> px changed no verdict (changes: 0<!--m:frame_margin.all.changed_up_to_2-->). From 3<!--n:value tried--> px on,
1<!--m:frame_margin.all.changed_at_5--> fiber of the Bruker scan joins. Rendered over the calibrated height
image, it is a short fragment between crossings that runs along the left border
a few pixels from it rather than out of the scan, so a margin would count it as
continuing outside the scan when it does not.
