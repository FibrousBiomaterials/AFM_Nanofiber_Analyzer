# Changelog

All notable changes to AFM Nanofiber Analyzer are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- A fiber GUI04 builds itself — a fibril reconnected from fragments, or a
  sub-fiber cut out by the height filter — now has its kinks judged by the
  thresholds the scan was analyzed with, instead of the `KinkDetector`
  defaults. **Kink counts, positions and angles on those fibers change for any
  scan analyzed at a `kinkangle_deg` other than 150 or a `kink_decompose_px`
  other than 3**; at the default settings nothing changes, and a fiber the
  connector passes through untouched was never affected either way because its
  features come from the bundle.

  The connector has to recompute, because joining two fragments creates a
  corner that exists in neither of them and retires the fragment ends that
  were never fiber ends. But it built its detector with a bare
  `KinkDetector()`, so the recomputed fibers were judged at 150 degrees while
  the fragments beside them in the same image carried the user's own
  threshold. Re-analyzing the bundled tunicate CNF scan at 130 degrees and
  reconnecting, the 15 fibrils carried 52 kinks against the 22 that threshold
  gives, while the 30 fragments no chain claimed carried 9. Inspected against
  the calibrated height image, the extra ones are bends of 136 to 149 degrees
  on fibrils that curve smoothly — exactly what setting 130 degrees asks the
  analysis not to report.

  The thresholds now travel with the arrays they explain: `process_file`
  already recorded the whole parameter set in the bundle's `params` metadata,
  and `lib.measure` reads `kinkangle_deg` and `kink_decompose_px` back out of
  it onto the tracking image. They are deliberately not read from the
  `<input_stem>_param.json` sidecar, which is the analysis input and stays
  editable afterwards, so an edit there would change a fibril's kinks with no
  re-analysis. A bundle written before a threshold was recorded lacks it and
  falls back to the default that run used, so existing bundles measure exactly
  as before.

- A kink is now reported only where the bend is larger than the error bar on
  measuring it. The decomposition localizes a vertex only to within
  `threshold_distance` of the true path, so a vertex displaced by that much
  across an arm of length `A` moves the interior angle by about
  `2 * threshold_distance / A`; a candidate is kept only where
  `pi - angle` exceeds that. **Kink counts, kink positions and kink angles
  change from this version**, so results are not bit-identical to 1.0.0. On
  the bundled scans the count falls from 10 to 5 (higher-plant TOC), 81 to 69
  (tunicate CNF) and 96 to 74 (Bruker NDTOC); nothing else in the pipeline
  moves, so lengths, heights, straightness and curvature are unchanged.

  This replaces a fixed minimum arm length of `threshold_distance` index
  steps, which was three pixels against a fiber whose own mask is 7.5 to 9
  pixels wide — an angle measured over less than half a fiber width, with no
  tangent support at the scale the decomposition resolves. The fixed rule was
  wrong in kind, not only in value: how much support an angle needs depends on
  how sharp it is. A 120 degree bend is 60 degrees clear of straight and
  survives on a short arm, while a 149 degree bend is 31 degrees clear and
  needs three times as much before it can be told from vertex jitter. Both
  sides of the new rule are in radians with the pixel units cancelling, so it
  also means the same thing at any scan size, which a pixel count does not:
  three pixels is 5.9 nm on a 2 um scan and 14.7 nm on a 5 um one.

  What it removes is dominated by the terminal arms. A track endpoint is a
  decomposition vertex by construction, so a terminal arm can be one pixel
  long, and after branch-point removal most endpoints are not fiber ends but
  cuts at a crossing, where the mask is least symmetric about the ridge: 46 to
  68 % of track ends on the bundled scans lie within 3 px of a branch point.
  Checked against the calibrated height image on the higher-plant TOC scan,
  all five removed kinks are ones the height ridge has no bend at — a rounded
  tip the skeleton turns into, a low mask skirt the skeleton falls into, a
  junction the track ends in, a smooth hook that had been reported twice, and
  a gradual arc — while all four kinks that do correspond to a bend of the
  ridge are kept. On the Bruker NDTOC scan, 18 of the 22 removed kinks are
  likewise absent from the ridge.

  This does not make every reported kink a real one. 43 % of what survives on
  the NDTOC scan still sits where the ridge has no bend, because those bends
  are sharp — 115 to 136 degrees — and a sharp angle clears its error bar even
  on a short arm. What is wrong there is the centerline, not the angle: the
  skeleton is the medial axis of a thresholded mask, so wherever the mask is
  not symmetric about the ridge the centerline is displaced and genuinely does
  bend. That is a separate fix and this one does not attempt it.

### Added

- `docs/algorithms.md` and `docs/algorithms.ja.md` explain what the four
  preprocessing stages compute — background calibration, binarization,
  skeletonization, kink detection — what each parameter changes, and why the
  non-obvious decisions were made, referencing the source by symbol name. The
  English version is published on the documentation site beside the API
  reference. No analysis behavior changes.

  The reasoning behind each stage was recorded only in the code comments,
  where it is reachable by someone reading that function and by nobody else. A
  user citing a fiber length had no document tying the number to the rules that
  produced it, which is what "black box" means in practice for research
  software.

  Documentation that has silently gone stale is worse than none, because it is
  read as authoritative, so the pair is held to the code mechanically rather
  than by intention. `tests/test_algorithm_docs.py` checks that every project
  symbol the documents name still exists, that every `ProcParams` field and
  every `bg_method` value is documented, that the two language versions share
  one heading skeleton, and it fingerprints the four algorithm modules with
  comments and docstrings removed — so editing a comment does not fire, while
  changing what the code computes fails the suite until the explanation has
  been reviewed. `scripts/check_algorithm_docs.py`, added to
  `.githooks/pre-commit`, gives the same warning at commit time. The rule the
  two mechanisms serve is `AGENTS.md` section 8.13.

- `ProcParams.kink_decompose_px` records the perpendicular tolerance of the
  piecewise-linear decomposition a kink angle is measured on. It was a constant
  inside `KinkDetector` that nothing passed and nothing wrote down, so the
  scale a kink was judged at did not appear in `<input_stem>_param.json` and a
  result could not be reproduced from its own sidecar. The default is the value
  it always had, so no analysis output changes; a parameter file written before
  this version loads with that default, as any missing key does.

  It is left in pixels, like `spur_length` and `branch_length`. Pixels are the
  wrong unit in principle — three pixels is 5.9 nm on a 2 um scan and 14.7 nm
  on a 5 um one — but on the three bundled scans the fiber mask measures 7.5 to
  10 px across, so the same three pixels land at 0.3 to 0.4 of a fiber width on
  every one of them, and there is no measurement here showing that a
  width-derived value would read any differently. Recording the number is what
  was missing; changing it is a separate question that needs its own evidence.

- A negative control for kink detection, built on synthetic scans whose fiber
  centerline is an analytic curve (`tests/synthetic_fibers.py`). Every other
  check compares the pipeline against a real scan, where nobody knows how many
  kinks a fiber truly has, so a change in the kink count reads as neither
  better nor worse. Here the answer is known by construction: a straight,
  circular or tapering fiber has no kink, and a two-armed fiber has exactly one
  at a known place, which makes a false positive and a miss separately visible.
  `tests/test_synthetic_negative_control.py` pins that a smooth fiber yields no
  kink, that a 145 degree bend is found where it is, that a 165 degree bend is
  not reported, and that the tracked centerline stays on the fiber.

  `scripts/kink_false_positive_sweep.py` sweeps noise, tip radius, curvature,
  taper, background roughness, crossings and clutter, and reports false
  positives per micrometre together with the recall of the known kink. The two
  are never reported apart: recall on its own improves monotonically as a
  threshold loosens. Height formation follows the AFM forward model — the ideal
  fiber surface dilated by the probe apex, not blurred — and the background
  roughness is matched to what the bundled scans carry after calibration,
  because a symmetric or noiseless background cannot produce the mask asymmetry
  that displaces a thinning-based centerline. The generated scans reproduce the
  trade-off, not the real failure rate; the script's docstring says what the
  numbers may and may not be used for.

- GUI04 can connect skeleton fragments into whole fibrils by hand, and saves
  the connection result beside the bundle for GUI03 to apply. "自動連結"
  searches for continuations and adopts what it finds; "手動で連結…" offers,
  for one selected fiber, the candidates near its ends — with the distance,
  the angle, and whether the automatic search's gates accept each one — so a
  continuation the automatic gates declined can still be joined by eye.
  "連結を解除" takes a fibril back apart, and "連結を取消" walks back one
  connection decision, including a whole automatic run.

  These are buttons rather than a checkbox because what they produce is a
  result that is kept. Pressing "自動連結" again discards the current
  connection (it asks first), and editing a threshold now changes nothing
  until the next press instead of re-analyzing the dataset behind the user.

  "除外・連結を保存" writes `<stem>_excluded.json` and `<stem>_connect.json` in
  one press, and GUI03's new "連結を適用" checkbox measures the whole fibrils
  the Fiber Tracker was showing instead of the skeleton fragments. The two
  sidecars are never written separately: they are read together, so a pair
  recorded at different moments would describe a population that was never on
  screen: saving the connection, turning it off, curating as fragments and
  saving the exclusions made GUI03 aggregate 29 whole fibrils where the window
  showed 56 fragments, unsignalled. The unsaved-work guard on leaving a dataset
  now covers the connection as well, which it did not before.

  A population curated in GUI04 therefore reaches GUI03's `bundle` input
  intact. Previously only the `fiber csv` export carried it, which gave up the
  `pixel` and `length` aggregation units.

  What is stored is which fragments are joined, in what order and orientation —
  not the settings that produced them, and not whether a join was automatic or
  manual. Storing the result is what stops an exclusion from *creating* a
  connection: with `A-B-C` connected and `B` excluded, `A` and `C` stay
  separate, where re-running the search joined them because `C` had become the
  only remaining candidate — a fibril nobody chose, appearing as a side effect
  of discarding a speck of debris. A recorded chain can be cut by an exclusion
  and never extended.

  The record is the join structure, not the geometry: fragments are named by an
  anchor pixel on their track, and the fibril is docked again at measurement
  time. Storing the pixels would be a cache that can disagree with the bundle
  beside it — re-analyzing the bundle changes the skeleton, and a stored track
  keeps "working" while describing a skeleton that no longer exists, whereas an
  anchor matches no fragment and fails loudly. The file also carries a
  fingerprint of the skeleton it was built on, so that check is immediate
  rather than waiting for the anchors to miss.

  Connection is per bundle, so a folder can be curated one bundle at a time.
  GUI03 logs how many bundles in each folder carried a connection, because a
  partially curated folder is otherwise invisible in the result. Uniformity
  across compared groups is not enforced: `clusters_range` is in pixels, so the
  same value is a different physical gap at a different scan size.

  `lib/fiber_connector.py` is split into a search (`plan_from_auto_connect`)
  and a construction (`build_connected_fibers`) for this, which is what lets
  the decision the search reaches be stored and rebuilt without searching
  again. The split is bit-identical to the previous connector on two real
  scans. One behavior does change: a fragment no chain claims is now passed
  through untouched instead of being rebuilt, so adding one join no longer
  perturbs unrelated fibers. Length, height, and kink count are unaffected;
  `EP count` is corrected, having previously been forced to 2 even for a
  fragment whose second end is a cut at a crossing rather than a real endpoint.

- GUI04's fiber table selects like Explorer: shift-click or drag for a range,
  ctrl-click to add or remove single rows. "選択を除外" acts on the whole
  selection, and "直前を取消" takes the whole batch back in one press, because
  the unit of undo is one exclusion click rather than one stored record. Every
  selected fiber is framed in the overview — the focused row solid, the rest
  dashed — so a batch can be checked against the image before it is applied.

  Debris and scan-line artifacts are judged in groups while looking at the
  overview, and excluding them one row at a time was the slowest part of
  curating a scan.

  "個別表示", "選択へズーム", and the export filenames follow the focused row,
  the one the user last clicked, so they stay unambiguous with several rows
  selected and no longer need a single-selection rule.

- GUI04 reports what fiber connection did: `ファイバー連結: 断片 61 本 →
  フィブリル 31 本（30 件連結）`. The feature used to be silent about its
  result — the log said it was enabled and nothing more — so a run that joined
  nothing looked exactly like a run that joined everything. `MeasureResult`
  gained `curated_count` (fibers left after exclusions, i.e. the number that
  entered reconnection) for it; the difference from the fiber count is the
  number of joins.

  When a run joins nothing and the user has just pressed the checkbox, a dialog
  says so. Joining nothing is a legitimate result, not an error — a well
  dispersed specimen has no fragments to rejoin — so the checkbox is left as
  the user set it, and the dialog never appears on a dataset switch, where it
  would interrupt every load.

- `tests/test_translations.py` now fails when a translation names a
  `str.format` placeholder its source string does not have. `pybabel update`
  carries a similar older translation over as a fuzzy match together with its
  placeholders, which raises `KeyError` in that language only, at the moment
  the message is shown — a path a Japanese-locale test run never reaches. Two
  such entries were caught and fixed while adding the batch-exclusion message.

- `straightness`, `curvature`, and `kink density` columns in the GUI04 fiber
  table, with `lib.measure.fiber_mean_curvature`, `fiber_kink_angle`, and
  `fiber_kink_density`.

  GUI03 shows its quantities only pooled into a distribution, which gives no
  way to judge whether an individual value is right; the fiber table puts each
  one beside the fiber it describes, and selecting a row highlights that fiber
  in the overview, so a number can be read against the shape it came from. The
  new `lib.measure` functions are the single definition of each quantity,
  called by both GUI04's table and GUI03's collection path, so the two windows
  cannot drift apart. A test now fails if a GUI03 quantity has neither a GUI04
  column nor a recorded reason for having none.

  `kink angle` is that recorded exception. A cell holds one number, but the
  kinks along a fiber are distinct defect events rather than repeated
  measurements of a single fiber property the way height pixels are, so a
  per-fiber summary of them describes no property of the fiber; for most fibers
  it degenerates as well, since a fiber usually carries zero or one kink. The
  individual angles are exported in full by the CSV.

  A curvature cell can be blank, for a fiber shorter than the curvature window,
  where 0 would read as perfectly straight. A kink density of 0 is shown,
  because zero kinks over a measured contour length is a real measurement. The
  log reports how many fibers the curvature window excluded.

  `lib.ui_tools.create_scrolled_treeview` gained an `hscroll` option, used
  here. A Treeview requests the sum of its column widths, so ten columns
  pushed the paned divider far enough to force the AFM overview and its
  buttons out of the window.

- GUI03 `curvature`, with `lib.measure.fiber_curvature_profile` and
  `collect_fiber_curvature`.

  Curvature is the mean turning rate along a fiber over an arc window, exposed
  as the "曲率窓" entry. A window is unavoidable: a skeleton step is
  orthogonal or diagonal only, so at the pixel scale the turning angle is
  quantised to multiples of 45 degrees. Measured against digitised arcs of
  known radius, a 20 nm window returned 19.4 rad/µm whatever the true
  curvature — a noise floor, not a measurement — and 50 nm was erratic
  (-30%, -19%, +46% across three radii), while 100 nm and above settled to a
  consistent 13-19% low. The residual is the contour-length metric
  over-measuring strongly curved digitised paths (+15-21% at 1.5 rad of total
  turn, +0.8% at 0.15 rad); the turning angle itself is exact. The default is
  100 nm because a larger window drops every fiber shorter than it, and with
  median fiber lengths near 200 nm a 200 nm default would silently halve the
  population. The log reports how many fibers each window excluded.

  Two quantities were implemented alongside curvature and then dropped before
  release, both because they describe the preparation rather than the fibers.
  The specimen this software analyses is a dispersion drop-cast onto the
  substrate and dried. `orientation order S` (the 2D nematic order parameter
  over one image's fibers) would have measured the number of traced fibers,
  since drop-cast fibers have no preferred direction. `network density` (total
  traced contour length per scanned area) would have measured the dilution,
  the drop volume, and where in the dried droplet the scan was taken — and
  because it aggregated per image, GUI03 would have run rank tests on it and
  produced publication-shaped p-values for a difference in sample preparation.

- A GUI03 `straightness` quantity, which divides the length of a digitised
  straight line between a fiber's endpoints by its contour length, both
  measured with the same corrected chain-code metric. That matters because the
  metric reports a straight digitised path as roughly 5% shorter than its
  Euclidean chord — measured directly, chord over contour is 1.0549 for a
  horizontal or vertical line and 1.0554 for a 45-degree one — so a raw ratio
  would put a straight fiber at 1.055 instead of 1.

  Straightness is exported as a `FiberStats` field and a new CSV column, so it
  reaches GUI03 through a curated GUI04 export as well as through a bundle. A
  CSV written by 1.0.0 still reads, with straightness left undefined:
  rejecting an older export would strand curation work that is still valid for
  every other column. It needs the pixel size to compare a chord against a
  contour length, and is undefined without one rather than silently zero.

- A CSV export for the GUI03 comparison table, carrying both the raw and the
  Holm-adjusted p-values. The adjusted value is what a conclusion rests on, but
  only the raw one lets a different correction be recomputed later.

- A between-group comparison table in GUI03, and `lib/group_compare.py` behind
  it. The per-group statistics describe each group on its own, which left the
  reader to judge from two medians whether a difference exceeds the spread.
  Every pair is now tested with a two-sided Mann-Whitney U and a two-sample
  Kolmogorov-Smirnov test — both rank-based, because these distributions are
  right-skewed and a t-test's normality assumption does not hold — with Holm
  correction across all pairs, since testing every pair of four groups at 0.05
  finds a "difference" about a quarter of the time with none present.

  Cliff's delta accompanies them as an effect size, because a rank test's
  significance grows with sample size while the separation it measures does
  not: with a few hundred fibers per group a negligible difference still
  reaches a small p-value. It is derived from the U statistic rather than by
  counting pairs, which would be quadratic in the sample sizes.

  The tests are offered only for the `fiber` and `image` aggregation units.
  Skeleton pixels, length-weighted points, and several kinks from one fiber are
  not independent observations, so a p-value over them measures how finely the
  images were sampled rather than whether the specimens differ; the other units
  say so instead of producing a number.

- GUI03 plot types `ECDF` and `box` beside the histogram. The ECDF puts every
  group on one axes with no bin width to choose, so a difference cannot be made
  to appear or disappear by rebinning, and the separation between two groups
  reads directly as the horizontal gap. The box is drawn from the quartiles the
  statistics table reports rather than from the raw samples, so the two can
  never disagree — and so the `length` unit's boxes use its weighted quartiles,
  which Matplotlib's own boxplot has no way to compute. The stacked/overlaid
  choice is disabled for both, which place every group on one axes by
  construction.

- Manual fiber exclusion in GUI04, and a GUI03 input path that consumes the
  result. Automatic filters cannot curate a dense network: on a typical
  entangled scan 58 of 60 traced fibers touch a crossing, so the isolated-fiber
  filter leaves nothing to analyze and no rule separates debris and scan-line
  artifacts from real fibrils. Visual judgement is the only option, so GUI04
  gains "選択を除外" to drop the selected fiber from the table, the overview,
  and the CSV export, "直前を取消" to undo the last exclusion (repeatably), and
  a "除外設定..." window that lists them and restores any one or all of them.
  Exclusions are stored in `<stem>_excluded.json` beside the bundle, so they
  survive the session, travel with the data, and can be audited outside the app.
  Changes take effect in the views at once but reach the sidecar only on
  "除外を保存", because that file is an analysis input and a mis-click should
  not rewrite it on its own. Every path out of a dataset — selecting another,
  changing folders, closing the window — offers to save, discard, or cancel,
  so unsaved curation is never dropped silently.

  Each exclusion records an anchor pixel on the excluded fiber's track rather
  than its row number, because turning fiber connection on or off renumbers the
  fiber list while the pixel keeps its meaning — an anchor taken in fragment
  mode still selects the same object once the fragments are connected.

  GUI03 gains an input selector: `bundle` reads `.b2z` as before and applies
  each bundle's exclusion sidecar (a checkbox turns that off, and the log
  reports what was dropped), while `fiber csv` reads a folder of GUI04's
  `_fibers.csv` exports, which are already exactly the fibers a person reviewed
  and kept. Both paths aggregate through the same code, so a curated CSV and
  its bundle give the same distribution. The CSV carries only per-fiber rows,
  so the `pixel` and `length` aggregation units are offered for bundles only.

- `lib/fiber_selection.py`, the exclusion contract (`exclusion_path_for`,
  `fiber_anchor`, `excluded_flags`, `load_exclusions`, `save_exclusions`), and
  `lib.measure.read_fiber_csv` / `collect_fiber_stats_from_csv`, which read
  `write_fiber_csv` output back into `FiberStats`. `collect_fiber_stats` and
  `collect_skeleton_height_profiles` take `apply_exclusions`, defaulting to
  `False` so an existing sidecar never silently changes what `cli.py measure`
  reports for a bundle nobody asked to curate.

- GUI03 compares three morphological quantities besides height: `contour
  length`, `kink angle`, and `kink density` (kinks per micrometer of contour).
  These are the quantities dedicated fiber-tracking software reports for this
  class of sample, and kink geometry in particular is what nanocellulose
  studies use to characterize processing damage — the pipeline already
  detected it, but only GUI04 could show it, one fiber at a time, with no way
  to compare groups. Height still comes from the calibrated image at
  skeletonized pixels; the other three come from the same per-fiber
  measurement `cli.py measure` and GUI04 use, so they require a bundle with a
  recorded scan size and take noticeably longer to compute.

- A GUI03 `length` aggregation unit that weights each skeleton pixel by the
  contour length it represents instead of counting points equally. Counting
  carries two biases: within one image the skeleton alternates orthogonal and
  diagonal steps whose corrected chain-code lengths differ by about 1.41x, and
  across images the pixel size follows the scan size, so a finely sampled scan
  dominates a pooled distribution. Weighting removes both and makes the
  distribution scale-invariant — the fraction of observed contour length at
  each height rather than the fraction of sampled points. Its sample size is
  reported as a contour length in micrometers, and its raw-value CSV gains a
  `weight_nm` column, without which the exported file would recompute an
  unweighted distribution and silently disagree with the figure.

- GUI03 reports non-fatal notices in the log only, instead of also opening a
  modal dialog after every run. Most notices are routine — samples outside the
  plotted range, a group too small for a histogram shape — so the dialog fired
  on essentially every run, adding a dismissal that told the user nothing the
  always-visible log panel did not already show. A run that produces no data
  at all still raises its dialog.

- GUI03 flags a group whose histogram has too few samples to show a shape
  (fewer than eight) and points at the table's median and IQR instead. This is
  the normal situation for the `image` unit, where a group holds as many
  samples as it holds scans.

- A GUI03 aggregation-unit selector deciding what counts as one sample:
  `pixel`, `kink`, `fiber` (the median within that fiber for height and kink
  angle), or `image` (the median of that image's fiber values). Pooled
  skeleton pixels are not independent observations — a long fiber contributes
  more pixels than a short one, and neighboring pixels of one fiber repeat the
  same object — so a group difference measured that way cannot carry the
  weight a per-fiber or per-image one does. The statistics table and the figure
  annotation therefore report the sample count broken down into samples,
  fibers, and images rather than a single N. The default remains height per
  skeleton pixel, so existing histograms are unchanged.

- GUI03 reports median and interquartile range beside mean, standard
  deviation, and mode, in the table, the figure annotation, and the statistics
  CSV. Fiber morphology distributions are right-skewed (contour length
  especially), and the mode moves with the histogram bin width, so neither
  mean ± SD nor mode alone describes them. The statistics CSV gains
  `quantity`, `sample unit`, `N samples`, `N in range`, `N fibers`, and
  `N images` columns, and the raw-value CSV file names now carry the quantity
  and unit (`<group>_contour_length_fiber.csv`) instead of always `_heights`.
  Kink density is written `µm⁻¹` in figures and `1/µm` in Tk labels and CSV
  headers: `1/µm` straight after a number reads as part of the number
  ("3.40 1/µm"), while the plain Unicode superscript minus is missing from
  Arial — which this project's Matplotlib style asks for first — and draws as
  a blank box, so figures get the exponent through Matplotlib mathtext.

- GUI03 logs what share of the samples falls outside the plotted histogram
  range. The summary statistics describe the whole sample while the bars show
  only the selected range; the share makes that difference visible instead of
  leaving excluded data silently missing from the figure.

- `lib.measure.contour_length_weights` and
  `lib.measure.collect_skeleton_height_profiles`, which return each tracked
  point's height together with the contour length it represents (the weights
  sum exactly to the fiber length). They sample the traced fibers rather than
  the skeleton mask, so their population excludes the branch-point
  neighborhoods removed before tracing.

- `lib.measure.collect_fiber_stats`, the multi-bundle wrapper of
  `measure_bundle` and the per-fiber counterpart of `skeleton_height_values`.
  It shares that failure contract — an unreadable bundle, or one without a
  recorded scan size, becomes an error entry instead of aborting the
  collection — and returns results per bundle so the caller decides whether
  one sample is one fiber or one image.

- Pan and zoom on GUI04's AFM overview, matching GUI02: the matplotlib
  Pan/Zoom toolbar plus a "リセット" button, a "選択へズーム" button, and a
  "番号・枠" toggle for the per-fiber numbers and dashed boxes. On a dense scan
  the numbers overlap into noise at full view, which is what made zoom
  necessary in the first place. Saving the overview exports the region on
  screen, so a zoomed view doubles as a region export.

  Three behaviors make it usable rather than merely present. A background
  rebuild (vmin/vmax, either filter, fiber connection, display mode) now
  restores the current view instead of snapping back to the whole image;
  switching the tick unit or the scan size rescales the axes, so those reset to
  the full view deliberately. Selecting a fiber that lies outside a zoomed-in
  view pans to it at the same zoom level, but only for a selection the user
  made — repopulating the fiber table re-selects row 0 on its own, and
  following that would teleport the view on every filter toggle. Finally, the
  fiber numbers and boxes outside the visible limits are no longer drawn: they
  are the single largest cost in an overview redraw (about 410 ms of 940 ms on
  a 136-fiber 1023x1023 scan), so a zoomed-in redraw drops to roughly 350 ms
  and the toggle removes that cost entirely.

- `lib.ui_tools.build_pan_zoom_toolbar`, which builds a matplotlib navigation
  toolbar stripped to Pan/Zoom. It carries the three workarounds the GUI02
  toolbar had accumulated (re-enable pack propagation so the toolbar does not
  span the figure width, match the ttk theme background on classic tk widgets,
  and unmap rather than destroy the unused buttons, because matplotlib still
  configures Back/Forward during Pan/Zoom). GUI02 now uses it instead of its
  own copy; its toolbar behavior is unchanged.

- A margin around the tracked fiber in GUI04's individual-fiber view, set by a
  "余白" entry in the enlarged-image settings (default 10 px, capped at 200;
  0 reproduces the previous tight crop), plus a "追跡範囲" toggle that outlines
  the tracked range with a dashed box. The tracked bounding box fits the fiber
  exactly, so until now both fiber ends sat on the frame and the enlarged image
  could not show whether tracking stopped at a real end point or where the
  fiber crosses a neighbor — the distinction the isolated-fiber filter and
  fiber connection exist to handle. The margin is clipped at the image border,
  where it becomes asymmetric. This re-crops the same calibrated image for
  display only: `Fiber.fiber_image` and the bounding-box-relative
  `xtrack`/`ytrack` that `lib/` measures from are unchanged, so **no measured
  value moves** and exported CSV statistics are unaffected. Only the exported
  enlarged-image PNG changes, and setting the margin to 0 restores its previous
  framing.

- A "孤立ファイバーのみ" filter in GUI04 that restricts the fiber table, the
  AFM overview, and the CSV export to fibers touching no other fiber anywhere
  along their path (`lib.measure.isolated_fiber_flags`, exported alongside
  `BRANCH_TOUCH_RADIUS_PX`). A fiber cut where it crosses another one has a
  *truncated* length, not a short one, so mixing those fragments into the
  population biases length statistics low. The filter selects among the fibers
  already measured and triggers no reanalysis, and it is off by default, so
  fiber counts stay comparable with earlier versions. It is mutually exclusive
  with fiber connection — turning one on turns the other off — because
  connection joins an isolated fiber to the network and it then stops being
  isolated: on the bundled tunicate CNF scan the isolated count drops from 2 to
  1 when connection is enabled. In a dense network most fibers reach a
  crossing, so a small retained count is expected rather than a detection
  failure. Note that the filter tests fiber topology, not whether an object is
  a fiber — a scan-line artifact touches nothing and passes it; use GUI01's
  stripe-noise screening for that.

- Analyzing only part of a scan's scan lines, so feedback-glitch bands can be
  excluded instead of poisoning the whole image. GUI01 gains a "走査線範囲"
  column (one input expands into one entry per range), a "縞ノイズで分割"
  button that fills it from the stripe-noise screening, and a "分割を解除"
  button that collapses the entries back (asking whether to delete the
  outputs the split produced, since keeping them means the entries return
  when the folder is reopened); `cli.py process` gains
  `--rows START-STOP[,...]`; `lib.pipeline.process_file` gains `row_range`.
  Each range is analyzed as its own image and written to
  `<input_stem>_r<start>-<stop>.b2z`, with the range recorded in the bundle's
  `source_region` metadata and restored from the output names when the folder
  is reopened. The recorded Y scan size is scaled so the stored pixel size is
  identical to the uncropped run's on both axes — a fiber measures the same
  whether or not the scan was cropped. **Results are unchanged when no range is
  given**, which is the default; `BUNDLE_FORMAT_VERSION` is unchanged because
  no array key, shape, or unit changed.

- A stripe-noise screening in GUI01 (`lib/stripe_noise.py`) that reports
  feedback glitches before a scan is analyzed. A lost feedback loop displaces
  whole scan lines, and because several analysis steps take a threshold from a
  statistic over the *whole* image, one glitch band rescales the analysis
  everywhere — on a bundled 10 µm scan the ridge-recovery hysteresis seed
  landed above the maximum response of every fiber in the clean part of the
  image, so nothing was recovered there at all. A new "縞ノイズ率" column shows
  the percentage of affected scan lines per file, flagged cells are tinted, the
  glitch-free scan-line ranges are listed in the log, and the affected lines
  are shaded on the Original preview panel. The step threshold is in the
  settings dialog under "縞ノイズの判定". **Analysis results are unchanged**:
  the screening is read-only, no pipeline stage reads it, and nothing it
  computes is written to the `.b2z` bundle.

- An optional ridge-recovery step in binarization (`ProcParams.ridge_recovery`,
  off by default) that adds fibers the height thresholding missed entirely.
  A multi-scale ridge filter runs on the calibrated image, and the material it
  finds outside the existing mask is kept when a segment is at least
  `ridge_min_length_nm` long; the searched fiber half-width range is set in
  nanometres (`ridge_min_width_nm`, `ridge_max_width_nm`) and converted per
  image, so one setting means the same physical structure at any scan
  resolution. Recovery only ever adds to the mask and needs a known scan size;
  it is skipped when the pixel size cannot be resolved. **Results are
  unchanged while it stays off**, which is the default. On a 10 µm scan at
  9.78 nm/px it recovered 391 segments the previous pipeline dropped, while
  adding nothing to four of the other five test datasets.

- Commit- and push-time safety checks (`.githooks/pre-commit`,
  `.githooks/pre-push`, `scripts/check_sensitive.py`) that scan staged diffs
  and outgoing commits for credentials, e-mail addresses, machine-local
  absolute paths, and a locally defined block list before anything is
  published; enable once per clone with `git config core.hooksPath .githooks`
  (see CONTRIBUTING.md).
- A commit-time changelog check (`scripts/check_changelog.py`, run from
  `.githooks/pre-commit`) that blocks a change to the strict-regression
  goldens — that is, a change to the numbers the pipeline produces — unless the
  same commit records it under `## [Unreleased]` here.

### Changed

- `measure.skeleton_height_values` now walks the traced fibers instead of
  reading the calibrated image at every nonzero skeleton pixel, so GUI03's
  `height`/`pixel` combination and `cli.py heights` honor manual exclusions and
  saved connection settings. Neither can be expressed on the skeleton mask: an
  exclusion names an object, and reconnection adds interpolated bridge pixels
  that exist in no mask. **The pooled height distribution changes from this
  version even with no curation applied**, because tracing drops the
  branch-point neighborhoods the mask still contained — on two real scans the
  point count fell by 2.0% and 4.4%, and those pixels sit at the crossings,
  where the height is not one fiber's. The `pixel` unit is now the unweighted
  counterpart of the `length` unit over the same population.

  Bundles with no recorded scan size are still measurable for this quantity:
  heights do not depend on the pixel size, and neither do the connector's gates
  or kink detection, so such a bundle is traced with a placeholder scale.

- GUI04's "孤立ファイバーのみ" checkbox is now a "非孤立を除外" button, and the
  fibers it rejects are recorded as ordinary manual exclusions (with the note
  `not isolated`) instead of being hidden by a view filter. One press of
  "直前を取消" takes the whole batch back, "除外設定..." lists them with the
  reason, and "除外を保存" writes them to the sidecar like any other exclusion,
  so the population is now narrowed in one place instead of two.

  As a filter, the verdict was re-derived every time a view was drawn, which
  applied it to whatever list the views held. With the height filter also on,
  that list is the sub-segments `filter_fibers_by_height` cuts out of a fibril,
  whose ends are the filter's own cuts rather than the fiber's — so "was this
  measured over its whole length?" was being asked of objects for which it has
  no meaning. On the tunicate test scan the two filters together reported 26
  "isolated" objects out of 137 segments, 22 of them pieces of a fiber the
  height filter had cut apart and 2-15 track pixels long, against 1 of 61 for
  the fibers themselves. Taking the verdict once, on the fibers as traced,
  removes that case entirely, and it also makes "isolate first, then filter by
  height" possible — an order that mutually exclusive filters would have
  forbidden.

  Fiber connection and the isolated-fiber test are still incompatible, but the
  button now reports the precondition and leaves the checkbox alone instead of
  switching it off and re-analyzing on the user's behalf.

- The automatic heatmap display range (`lib.ui_tools.compute_auto_vrange`,
  used by GUI02 and GUI04) is now computed from robust statistics instead of
  the image minimum and maximum, so a single contamination spike no longer
  sets `vmax` far above the fibers and leaves the whole image dark, and a few
  negative noise pixels no longer drag `vmin` tens of sigma below the
  substrate and wash the image out. The lower bound comes from the background
  mode and a noise sigma estimated from the deviations below it; the upper
  bound is a percentile of the fiber pixels, taken over the bundle's skeleton
  when GUI02 or GUI04 has one and over the above-background pixels otherwise.
  Both bounds stay inside the data range, and the rule is tunable through the
  `AUTO_VRANGE_*` module constants and the matching keyword arguments. Only
  the display changes; no measured value is affected.

- The `inpaint` background method is renamed to `trendfill`, because it no
  longer inpaints: the mask is filled by subtracting a fitted second-order
  trend surface, propagating the nearest background pixel, smoothing, and
  restoring the trend. `_param.json` files and GUI01 startup settings written
  before the rename keep working — `"inpaint"` is translated to `"trendfill"`
  on load (`lib.bg_calibrator.canonical_bg_method`), accepted by
  `validate_params`, and normalized by `BGCalibrator`. Only the new name is
  offered in the GUI01 dropdown.

### Removed

- `lib.measure.all_pixel_height`. It was the body of `skeleton_height_values`
  before that collector switched to walking the traced fibers, and it has had
  no caller since. **It is not interchangeable with `skeleton_height_values`**:
  it samples every nonzero pixel of the skeleton mask, which includes the
  crossings that `imp_tools.remove_bp` clears before tracing. Measured on the
  two bundled scans it counted 161 of 7,975 and 25 of 1,789 pixels the traced
  population does not, and rendering those pixels over the calibrated height
  image put every one of them on a visible fiber crossing, where the height is
  two fibers stacked rather than one fiber's — their median height was 1.43x
  and 1.78x that of the pixels tracing keeps. Taking raw arrays, it also could
  not express a manual exclusion (which names an object) or a reconnection
  (whose bridge pixels exist in no mask), so calling it silently bypassed both
  sidecars. Use `skeleton_height_values`, and expect different numbers.

- `lib.gwy_io.is_gwy_path`, which had no caller and could not gain one where it
  mattered. `gwy_io` imports from `afm_io`, so `afm_io` cannot import `gwy_io`
  at module level, and `afm_io` / `pipeline` deliberately test the extension
  *before* their lazy `from . import gwy_io` so a text-only workflow never
  loads the module. A predicate living in `gwy_io` is therefore unreachable
  from the three places that test for a `.gwy` path; leaving it invited an
  edit that would have introduced a circular import. Test inline with
  `os.path.splitext(path)[1].lower() == ".gwy"`.

- The `spline2d` background-estimation method. On every test image it left the
  largest background residual of the four methods — 1.3 to 6.1 nm peak-to-peak
  across the scan-line profile, against 0.02 to 0.4 nm for `trendfill` and 0.2
  to 0.8 nm for `tophat` — which shows up as heavy horizontal banding in the
  calibrated image. The cause was its smoothing factor: `spline2d_smoothing`
  defaulted to `None`, which hands SciPy's `SmoothBivariateSpline` the
  heuristic `s = <number of fit points>`. That heuristic assumes the data has
  unit standard deviation, so for AFM heights in nm it stops fitting as soon as
  the residual reaches 1 nm RMS — on a 1023x1023 scan the resulting surface had
  one interior knot along y and none along x, i.e. it subtracted a plane and
  nothing else. Neither GUI-exposed parameter could correct this
  (`spline2d_subsample` cancels out of the criterion, and `spline2d_degree`
  only raises the order of that single patch), and `spline2d_smoothing` itself
  was deliberately hidden from the GUI. Setting it to a statistically
  appropriate value merely matched `trendfill` at roughly 20x the runtime, and
  slightly below that value the fit diverged by six orders of magnitude behind
  a FITPACK warning the code did not check. Use `trendfill`, or `spline1d` for
  line-noise-dominated scans. **Results change from this version for anyone who
  used `bg_method="spline2d"`**: a stored `_param.json` selecting it now stops
  with an explanation rather than silently running a different method, since
  substituting one would change the numbers that file reproduces. The
  `spline2d_degree`, `spline2d_subsample`, and `spline2d_smoothing` fields are
  gone from `ProcParams`; an older parameter file carrying them still loads,
  with those keys reported as unknown. Output for `trendfill`, `tophat`, and
  `spline1d` is bit-identical to before.

### Fixed

- An exclusion sidecar whose `version` is newer than this release now raises
  instead of being read by this version's rules. `lib.connect_selection`
  already refused a newer connection file; `lib.fiber_selection` wrote the
  version key and never read it back, and the asymmetry was undocumented, so a
  maintainer could not tell whether it was deliberate. A later version could
  give an entry a meaning beyond "exclude the fiber through this pixel", and
  applying it as a plain point exclusion would measure a population the user
  never chose. No file in existence triggers this: the key has been written
  since the sidecar was introduced. A file with no `version` key still reads as
  the current version, so a hand-written sidecar keeps loading.

- A fiber crossing another one on the first analyzed scan line or in the first
  analyzed column is no longer dropped. `imp_tools.remove_bp` cuts the skeleton
  at each branch point by clearing a 3x3 neighborhood around it, but at row 0
  or column 0 the neighborhood's lower bound went negative, which NumPy reads
  as a position counted from the far edge, so the slice covered nothing and the
  junction survived. `tracking` then saw a connected component with more than
  two endpoints and `FiberTrackingImage` skipped it, losing every fiber in that
  component rather than the crossing alone. **Results change from this version
  for any image with a crossing on its first row or column**; neither bundled
  test scan has one, so the recorded regression values are unchanged.

- GUI04 builds its manual-connection candidate cache in one pass over the
  fiber population instead of one pass per fiber. The end geometry and the
  per-fiber median heights describe the whole population, so the old form
  rebuilt both once per fiber: 0.55 s for 60 fibers on the Tk main thread,
  growing as the square of the population. `lib.fiber_connector` gained
  `connection_candidates_by_index` for it, which reports exactly what
  `connection_candidates` reports per fiber. No measured quantity changes.

- GUI04's "孤立ファイバーのみ" filter now also rejects a fiber the reconnection
  logic can find a partner for, using the thresholds set under "連結設定...".
  The branch-point test misses exactly the case this catches: an end whose
  nearest crossing sits just outside the 2 px touch radius while the connector
  plainly sees the fiber continue past the gap. `lib.fiber_connector` gained
  `connection_candidate_flags` for it, and `isolated_fiber_flags` gained a
  `connect_params` argument. On two test scans the filter's output drops from
  2 to 1 and from 9 to 7 fibers.

  It is used **only in conjunction with the other two tests**. Alone it is far
  looser — 51 of 61 and 110 of 136 fibers on those scans — because "no partner
  found" conflates "this fiber is complete" with "the connector could not tell
  what the continuation was", and the second case is common in a dense tangle.

  The test is a standalone predicate over the original fragments, not a record
  of what `connect_fiber_fragments` did: that function consumes fragments as it
  grows, so which joins happen depends on the order fragments are visited, and
  a predicate used to judge a fiber has to be independent of it. Against what
  the connector actually joined, the predicate agreed on 145 of the 146
  fragments it extended.

- GUI04's "孤立ファイバーのみ" filter now also rejects a fiber whose track
  reaches the outermost row or column of the image. Such a fiber continues
  outside the scan, so what was measured is the part that happened to fall
  inside the frame, not the fiber — exactly what the filter exists to keep out
  of the length statistics. The branch-point test could not catch it on its
  own, because there are no branch points beyond the frame, which made a fiber
  running off the edge look *more* isolated rather than less. On two test
  scans the filter's output drops from 3 to 2 and from 13 to 9 fibers.

  The frame is the outermost row and column with no margin: measured on those
  scans, the count of fibers reaching it was identical for margins of 0 through
  5 pixels, so a fiber that leaves the scan reaches the very edge and a wider
  margin would only start rejecting fibers that merely come close.

  `isolated_fiber_flags` keeps its name and signature. Only GUI04 calls it, so
  `cli.py` and GUI03 are unaffected except through a GUI04 CSV.

- Re-analyzing the loaded dataset no longer discards its unsaved exclusions.
  Turning fiber connection on, changing the scale, or editing the connection
  parameters all re-analyze the dataset that is staying loaded, but they went
  through the dataset-switch path, which asks whether to save the exclusions
  before replacing them and discards them on "no". A user who had curated a
  scan and then pressed "ファイバー連結" was asked to save or lose the work,
  and lost it on "no" — the connection then ran over every fragment, including
  the ones just rejected.

  A re-analysis is not a dataset switch: the dataset stays loaded and its
  exclusions stay with it, so `_reload_current_file` no longer routes through
  `_on_file_select`, carries the in-memory set into the analysis, and leaves
  its grouping and unsaved flag alone. The sidecar is read only when actually
  switching datasets.

- Manual fiber exclusions are applied to the traced fragments **before** fiber
  connection instead of to the connected fibrils afterwards. **Results change
  from this version whenever exclusions and fiber connection are used
  together**, so a curated population measured with connection on is not
  identical to 1.0.0. Nothing changes when either feature is used alone, and
  `cli.py measure` and GUI03 never connect, so their numbers are unaffected
  except through a GUI04 CSV.

  Excluding one object used to delete others. An exclusion is stored as an
  anchor pixel and was applied after connection, so once the connector had
  joined a discarded speck of debris onto a real fiber, the anchor matched the
  merged fibril and the real fiber went with it. On a test scan, excluding five
  debris fragments discarded close to four times their combined contour length.
  Curation is exactly the judgement that an object is not a fiber, so the
  connector must not see it at all: `lib.measure.curate_fibers` now owns that
  order, and `measure_bundle` takes an `exclude_anchors` argument. The height
  filter deliberately keeps the opposite order — connect, then filter — because
  it selects a height band inside a fibril, which only means something once the
  fibril is whole.

  Excluding a connected fibril in GUI04 now records one anchor per constituent
  fragment (`lib.fiber_selection.constituent_anchors`). A fibril's own midpoint
  lies on only one of the fragments it was built from, so a single anchor
  removed that fragment and let the others reconnect into a shorter fibril:
  the rejected object partly returned, and no longer matched its own anchor.
  "直前を取消" now takes back one exclusion click rather than one record, so a
  fibril excluded in one press is restored in one press. That grouping is a
  within-session convenience — the sidecar stores no grouping, so a set
  restored from disk steps back one record at a time.

  `MeasureResult` gained a `fragments` field holding the traced fragments
  before curation, so GUI04 rebuilds the population after an exclusion change
  without tracing the bundle again; only the connector re-runs, in a worker
  thread with the existing progress bar.

- GUI03's worker thread now stops when it cannot build the histogram bin
  edges, instead of reporting the failure and then continuing into the loop
  that needs them. It reported the error to the user either way, so the
  `UnboundLocalError` that followed only reached stderr — where a windowed or
  frozen build shows it to nobody. The range entries enforce only min < max
  and step > 0, so a wide range with a fine step (min=0, max=1e12, step=1e-6)
  reaches the handler through `np.arange`'s `MemoryError`.

- The traced centerline no longer makes a U-turn at a fiber tip where
  segmentation admitted a low, widened "skirt" of near-background pixels.
  Thinning follows the mask's medial axis into such a skirt and curls back
  along its periphery, leaving a junction-free hook at the end of an otherwise
  straight fiber — on the bundled higher-plant scan, fiber #0 carried an
  8-pixel hook running at 19–42% of the fiber's body height, which faked two
  kinks (119°, 104°) and inflated the length by 14 nm. No existing cleanup
  could see it: branch pruning needs a branch point, spur pruning needs a
  junction, and loop collapsing needs an enclosed hole. A new
  `lib.skeletonizer.prune_terminal_hooks` pass recognizes a direction reversal
  within 12 px of an endpoint and trims only pixels whose calibrated height is
  below half the adjacent body's median — a genuinely bent fiber end keeps its
  fiber-level height and is never cut (verified on every flagged end in the
  bundled scans: real bends and junction wiggles sit at 55–113% of body
  height). The pass runs only in the preprocessing pipeline, so the stored
  bundle remains the single source of truth: a `.b2z` analyzed before this
  version still contains the hook and must be reprocessed (GUI01 or
  `cli.py process`) to receive the fix — GUI04 deliberately does not repair
  it at load time, because a viewer silently changing stored results would
  break the correspondence between a bundle and the numbers it reproduces.
  Kink detection additionally requires both arms of a candidate bend to span
  at least the decomposition scale (`threshold_distance`): the track endpoints
  are decomposition vertices by construction, so a terminal arm could shrink
  to 1–2 px and report an angle with no tangent support — across the bundled
  scans this drops exactly one kink, the artifact above. **Measured lengths,
  kink counts, and kink angles change from this version** for scans whose
  skeletons carried such hooks; results are not bit-identical to 1.0.0.
- `.b2z` bundles can now be written and read under paths containing non-ASCII
  characters, such as a Japanese folder or file name on Japanese Windows.
  blosc2 encodes the path to UTF-8 and hands the bytes to the C-Blosc2
  library, which opens files through the narrow CRT `fopen()`; on Windows that
  call decodes them with the process ANSI code page, so any non-ASCII
  character broke the open. Analysis ran to completion and then failed at the
  save step with "Could not create the Schunk", while every reader failed with
  "blosc2_schunk_open_offset(...) returned NULL" — and because the analyzed
  state check treats a read failure as "keys missing", GUI01 showed an
  analyzed input as unanalyzed and GUI04 silently omitted such bundles from
  its folder list. `lib/blosc2_io.py` now stages the blosc2 side of the work
  through an ASCII scratch directory: writes go through an ASCII working
  directory (the `.b2z` zip itself is written by Python), and reads open the
  bundle through an ASCII hard link, falling back to a copy across volumes.
  Paths that are already ASCII are untouched, and the analysis output is
  unchanged either way. Set `AFM_BLOSC2_SCRATCH_DIR` if none of the default
  scratch locations (`%TEMP%`, `%PUBLIC%`, `%SystemRoot%\Temp`,
  `%ProgramData%`) is usable. Reproduced identically on blosc2 4.7.0, 4.8.1,
  and 4.11.0, so upgrading blosc2 is not an alternative.
- GUI01's settings dialog no longer truncates its parameter descriptions. The
  description labels had no wrap length, so any sentence wider than the row cut
  off at the frame edge with no ellipsis and no tooltip to recover it from.
  Translations are the longer ones: 13 of the 28 English parameter rows and two
  of the four English background-method descriptions were losing their tails,
  including the `trendfill` note that it was called `inpaint` in 1.0.0. The
  labels now wrap to the width their row grants them.
- `spline1d` no longer paints horizontal stripes that are absent from the raw
  scan. **Measured lengths, heights, and fiber counts change from this
  version** for `bg_method="spline1d"`; `trendfill`, `tophat`, and `spline2d`
  are unaffected. Past the first and last background pixel of an interpolation
  line there is background data on one side only, yet those runs were still
  given a *shape* extrapolated from that single line: a slope through its two
  nearest samples. The slope was therefore pixel-to-pixel noise, the resulting
  ramp grew with the run length, and because every line was extrapolated
  independently each one painted its own band - with `spline1d_axis="x"`, a
  horizontal one. On a 1024x1024 scan, 487 of 1023 rows began inside a masked
  run (median 13 px, up to 315 px) and the injected error reached 4.6 nm at the
  median and 108 nm at worst, against a 0.3 nm `global_threshold`, so the
  stripes binarized as false fibers. The whole fill now runs on a detrended
  copy with the second-order trend restored afterwards, as `trendfill` already
  did, so no filler has to reproduce the 0.23-0.34 nm/px sample tilt; and the
  end runs hold the mean level of that line's nearest `savgol_window`
  background samples instead of extrapolating a shape. After detrending, the
  quantity that is still specific to a line is essentially its scan-line
  offset, which is constant along the line, so holding a level estimates it
  without extrapolating a slope, and averaging over a window keeps pixel noise
  out of that level. Measured against a known background on four scans, with
  the fiber geometry taken from the real data so the end-run statistics are
  realistic, the RMS background error over the end-run pixels falls from
  2.5-4.4 nm to 0.3-1.2 nm and the worst-case error from 15-30 nm to 2-4 nm.
  Re-run GUI01 or `cli.py process` to refresh existing `.b2z` bundles.
- The default background method no longer produces a false fiber running
  parallel to a real one on tilted scans. **Measured lengths, heights, and
  fiber counts change from this version**, so results with
  `bg_method="trendfill"` (formerly `"inpaint"`) are not bit-identical to
  1.0.0; `spline1d` and `spline2d` are unaffected. The mask holes were filled with OpenCV
  Navier-Stokes inpainting, a boundary-propagation scheme meant for thin
  scratches: with `inpaintRadius=3` it extended each side of a hole inward as a
  flat plateau and met in a step of up to ±4 nm across a 21-px hole, because a
  raw scan drops 7-9 nm of sample tilt across one fiber width while the fiber is
  only about 10 nm tall. Since `savgol_polyorder <= 1` makes the Savitzky-Golay
  pass a plain moving average along X, that step was averaged into the
  background estimate of every genuine background pixel within half a window,
  leaving a trough on the uphill side and a +0.76 nm ridge on the downhill side
  — above the 0.3 nm `global_threshold`, so it binarized as a second fiber. The
  hole filling now runs on a detrended copy of the image: a second-order surface
  is fitted to the background-candidate pixels and subtracted, holes are filled
  from the nearest background pixel, and the surface is restored after
  smoothing. The residual halo on the affected scans falls from -0.82/+0.76 nm
  to -0.14/+0.17 nm, both below the binarization threshold. On synthetic scans
  with a known 8.0 nm fiber height the recovered height error improves from
  +0.044 nm to -0.004 nm under a linear tilt and from -0.138 nm to -0.012 nm
  under a quadratic bowl, and an untilted image is unchanged, since the
  correction scales with the trend it removes. Re-run GUI01 or `cli.py process`
  to refresh existing `.b2z` bundles.
- `tophat` no longer segments the scan border as a fiber on tilted scans.
  **Measured lengths, heights, and fiber counts change from this version** for
  `bg_method="tophat"` as well. Morphological opening reproduces a plane in the
  image interior but not within one structuring-element radius of the border,
  where erosion takes its minimum from a clipped neighborhood that dilation
  cannot restore; on a 0.34 nm/px ramp with the default 25-px element that left
  a band about 4 nm high down the uphill edge, far above the 0.3 nm
  binarization threshold. The opening now runs on a detrended copy and the
  trend is restored after smoothing, which drops one affected scan from 7
  binarized components (17,716 px) to 3 (9,459 px), matching what the
  interpolating methods find on the same image.
- Skeleton traces no longer bend away from the fiber centerline at the ends of
  fibers that leave the field of view. Thinning treated everything outside the
  image array as background, so a fiber crossing the scan border became a shape
  cut flat by the edge, and the medial axis of that truncated end turned toward
  the nearer corner of the cut. Thinning now runs on a border-replicated copy
  of the mask (`thin_ignoring_image_border` in `lib/skeletonizer.py`). Measured
  against the distance transform of the border-replicated mask — the definition
  of how deep inside the fiber a pixel lies — the mean depth of skeleton pixels
  within 12 px of the border rises from 3.4-3.6 px to 4.0-4.3 px on the bundled
  scans, matching the 3.9-4.5 px seen away from the border. The pixels this
  drops sat 2.6-2.7 px deep, that is, on the edge of the fiber mask.
  Skeleton pixels away from the border are unchanged, and a per-component
  fallback keeps the previous result for any mask blob that lies along the
  border rather than crossing it, so no fiber is lost to the correction.
  Preprocessing outputs (`skeletonized`, `bp`, `ep`, `kp`, `dp`, `ka`) therefore
  change for fibers that touch the scan border; `calibrated` and `binarized` are
  unaffected. Re-run GUI01 or `cli.py process` to refresh existing `.b2z`
  bundles.
- Branch pruning no longer deletes the tip of a fiber that merely continues
  past its local search window. `Skeletonizer.track_branches` traced each
  candidate arm inside a `2 * branch_length` crop, so once the walk reached the
  crop edge the neighborhood read as empty, the "dead end" rule fired, and up
  to `branch_length` pixels were removed from a real fiber — with no height
  gate, so it applied to fibers far above `bp_height`. The walk now covers the
  whole image with explicit bounds checks. Each walk also carries its own
  visited set instead of blanking pixels in one shared working image, so the
  result no longer depends on the order endpoints happen to be processed in.
  Across the bundled scans and all four `bg_method` values this only restores
  pixels (0 to 211 per image) that were previously over-deleted; it removes
  nothing new.
- Feature overlays in GUI01 are no longer mirrored vertically **when the scale
  display is enabled**. Endpoint, branch-point, kink and decomposition markers
  were placed by scaling pixel indices with `scale / (n - 1)`, but `imshow`
  draws row 0 at the top of an `extent` whose y axis runs upward, so the
  markers were reflected about the image center. With the scale display off —
  the default — panels are drawn in pixel coordinates and the overlay was
  already correct, which is why this went unnoticed: it needed both a
  non-default overlay mode and the scale display switched on. Measured on the
  bundled tunicate scan, none of the drawn endpoint markers fell on a skeleton
  pixel with the scale display on; now all of them do, in both display modes.
  Both the 2x2 preview and the enlarged single-file view are corrected.
- Overlays now sit at pixel centers rather than half a pixel up and to the
  left. `imshow` spreads an image of `w` columns across the extent, so the
  center of column `c` is at `(c + 0.5) * scale / w`; GUI01, GUI02 and GUI04
  all placed overlay geometry at the pixel's upper-left corner instead. In
  GUI04 this shifted the fiber track, kink markers and the color-coded fiber
  scatter by half a pixel against the height image.
- GUI02 height profiles are now sampled from the pixel that was clicked. The
  micrometer-to-index conversion omitted the same half-pixel term, so
  `profile_line` read half a pixel down and to the right of the marked points.
  **Extracted profile values change from this version.** The sampling-width
  band drawn on the heatmap is unchanged on screen — it always followed the
  marked points — but it now agrees with the pixels actually sampled, which it
  previously missed by that same half pixel.
- `run_venv.bat` now checks the Python version before building the `.venv`, and
  both launchers point at the download page when no supported Python is found.
  The Windows launcher only tested that the `py` launcher answered at all, so a
  machine with Python 3.9 passed the check, created a `.venv`, and then failed
  inside pip with a `requires-python` message that never mentioned Python's
  version; a machine with `python.exe` on PATH but no `py` launcher was told to
  install Python it already had. The launcher now takes the first of `py -3` and
  `python` that satisfies the `>=3.10` floor from `pyproject.toml` — skipping
  the Windows App Execution Alias stub, which opens the Microsoft Store instead
  of running Python — and otherwise reports the version it found, or that it
  found none, followed by <https://www.python.org/downloads/>. `run_venv.sh`
  already enforced the floor and now reports the rejected version and suggests
  the distribution package manager on Linux, with python.org as the fallback.
- The `run_conda` launchers point at the conda installers when conda is not
  found, instead of only naming Anaconda/Miniconda. They need no Python check:
  `conda create` installs its own Python into the prefix, so conda itself is
  the only prerequisite these launchers can be missing.

### Known issues

- Every coordinate the software reports is one pixel from where it is in the
  input file. Background calibration computes its gradients as
  `image[:, 1:] - image[:, :-1]`, which loses one column and one row, and
  crops its output to `original[1:, 1:]` so the shapes match
  (`lib/bg_calibrator.py`). The calibrated image is therefore one pixel
  smaller than the input on each axis, and pixel `(i, j)` of it is pixel
  `(i + 1, j + 1)` of the raw scan: phase correlation puts the displacement at
  exactly `(1.00, 1.00)` px on both bundled 1024 px scans.

  Everything downstream is derived from the calibrated image, so the offset is
  internally consistent and lengths, heights, angles and every comparison
  between fibers are unaffected. What it does reach is any position read
  against the original scan — a fiber's coordinates in a GUI or an exported
  CSV, a kink's position, and the anchor pixels the exclusion and connection
  sidecars store. One pixel is 2.0 nm on the bundled 2 um scans and 4.9 nm on
  the 5 um one.

  It also reaches the pixel size, which `lib/pipeline.py` obtains by dividing
  the recorded scan size by the width of the *cropped* image. Whichever
  convention an instrument uses for what its recorded scan size spans, the
  crop changes that divisor by one, so the pixel size differs by one part in
  the image width — about 0.1 % on a 1024 px scan — from what the same
  formula would give on the uncropped image, and every length scales with it.

  Fixing this changes every recorded coordinate and every length, so it is
  recorded here rather than changed quietly.

- A bend spread along a fiber can still be reported as a kink. The angle at a
  decomposition vertex is measured between the chords to its two neighbouring
  vertices, and those neighbours sit wherever the piecewise-linear
  decomposition put them, so the measurement carries no scale: a corner and an
  arc that turns by the same amount over a much longer stretch produce the same
  angle. On the synthetic scans of `tests/synthetic_fibers.py`, which have no
  tangent discontinuity anywhere, a meander of 57 nm minimum radius yields
  about four such reports per fiber.

  The distinction is measurable in principle. Compare the turn between chords
  spanning an arc length `L` either side of the point with the same at `2L`:
  for an arc the turn is proportional to `L`, for a corner it is independent of
  it, so `K = 2*turn(L) - turn(2L)` is zero for the first and equals the bend
  for the second. Measured against known geometry, `K` at `L = 3.5 W` (where
  `W` is the mask area divided by the skeleton length, 9.0 to 10.1 px on the
  bundled scans) separates all five families cleanly against the 30 degree
  threshold the default `kinkangle_deg` implies: 36 for a 145 degree kink, 25
  for a 155 degree one, 14 and 21 for meanders of 91 and 57 nm minimum radius,
  and 7 for a 90 degree arc.

  What blocks it is the amount of fiber the measurement needs, not the
  arithmetic. `turn(2L)` reaches `7 W` either side, so the point needs `14 W`
  of track around it — and 57 %, 72 % and 88 % of the fibers on the
  higher-plant TOC, tunicate CNF and Bruker NDTOC scans are shorter than that
  in total. Of the kinks those scans report, only 1 of 5, 32 of 69 and 23 of
  74 could be evaluated at all. A chord also stops describing the fiber where
  the track folds back inside the span, which a convoluted fibril does: of 13
  kinks the test dropped, four had a `2 L` chord that crossed a fold and two or
  three were corners the height image shows plainly.

  The scale is recorded because any future attempt needs it. The turn at a
  corner only reaches its full value once `L` exceeds the rounding that tip
  broadening and thinning leave: for a 145 degree kink it reads 17 degrees at
  `L = W` and settles at 32 to 34 from `L = 3.5 W`, and for a 120 degree kink
  45 degrees at `L = W` settling at 57 to 59 from `L = 2 W`. A baseline of one
  line width sees less than half of a shallow corner.

- One bend can still be reported at two neighbouring decomposition vertices,
  and nothing suppresses the weaker of the two. Nothing does, because no
  available criterion separates that case from two genuine corners that happen
  to have no vertex between them.

  It is rare now. Re-analyzed with the current detector, the three bundled
  scans report 5, 69 and 68 kinks, of which 0, 25 and 20 are pairs sitting at
  neighbouring vertices; only 0, 10 and 5 of those turn the same way, an S
  being two real opposite bends that must never be merged. Inspected against
  the calibrated height image, one pair of the 15 is unmistakably one apex
  marked twice (tunicate CNF fiber 5, 148 and 147 degrees, the two markers
  almost on the same pixel). The significance rule above had already removed
  the higher-plant TOC case this was written for.

  The criterion that ought to work does not. A circular arc of total turn
  `theta` across a chord of length `A` departs from that chord by
  `(A/2) * tan(theta/4)`, so where that is below `kink_decompose_px` the
  decomposition could not have told an arc from a corner-straight-corner: it
  would have placed the same two vertices either way, and reporting two kinks
  asserts a distinction the data does not carry. Applied to the 15 same-way
  pairs it merges 4 (3 on tunicate CNF, 1 on NDTOC, none on higher-plant TOC),
  and against the height image the ordering it produces is not the ordering the
  images give: it merges two pairs that sit on a faint ridge and on a crossing,
  where the kinks are questionable for unrelated reasons, while the clearest
  distributed bend on either scan — a smooth hairpin on tunicate CNF fiber 5,
  104 and 148 degrees, no corner visible at either marker — is kept, missing
  the threshold by 3 %. The decision boundary falls between 2.67 px (merged)
  and 3.09 px (kept) while the visual verdicts interleave across it.

  What is missing is the same thing the entry above records: a scale. Whether
  a turn is one bend or two is a statement about the length over which it
  happens, and the vertex spacing the decomposition chose is not that length —
  it is set by the tolerance and by where the track's noise happened to peak.
  A rule built on it correlates with the answer without measuring it.

## [1.0.0] - 2026-07-08

Initial public release, prepared for subsequent archival on Zenodo and
submission to the Journal of Open Source Software (JOSS).

### Added

- tkinter plugin launcher (`Main.py`) with four interactive tools: Image
  Preprocessor (GUI01), Plot Profiler (GUI02), Fiber Height Histogram (GUI03),
  and Fiber Tracker (GUI04).
- GUI-independent preprocessing pipeline (`lib/pipeline.py`) shared by GUI01 and
  the CLI, covering background calibration, segmentation, skeletonization, and
  kink detection.
- AFM input through auto-detected text/CSV layouts and native, multi-channel
  Gwyddion `.gwy` files with topography-channel auto-selection.
- Command-line interface (`cli.py`) with `process`, `validate`, `measure`,
  `heights`, `export`, and `show-params` subcommands.
- Single-bundle output format (`.b2z`) with an executable, versioned schema
  (`lib/bundle_schema.py`) validated at write and load time, alongside a
  per-input parameter JSON file and spatial-calibration metadata.
- GUI-independent fiber measurement (`lib/measure.py`) shared by GUI03, GUI04,
  and the CLI, so GUI and CLI statistics are identical.
- Background calibration with four interchangeable methods: `inpaint`, `tophat`,
  `spline1d`, and `spline2d`.
- Localization through gettext, with English, Japanese, and Chinese catalogs.
- Editable install via `pyproject.toml`, a loose `requirements.txt`, and a
  test-verified `requirements.lock.txt`.
- Continuous integration (`.github/workflows/test.yml`) running Ruff lint,
  `check.py --verify`, and the pytest suite on Windows and Linux across two
  Python versions.
- Project documentation: `README.md` / `README.ja.md`, `CONTRIBUTING.md`,
  `SUPPORT.md`, maintainer notes, docstring templates, and a JOSS paper
  (`paper.md`).

[Unreleased]: https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/FibrousBiomaterials/AFM_Nanofiber_Analyzer/releases/tag/v1.0.0
