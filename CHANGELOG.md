# Changelog

All notable changes to AFM Nanofiber Analyzer are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- GUI03 logs how many samples fall outside the plotted histogram range. The
  summary statistics describe the whole sample while the bars show only the
  selected range; the count makes that difference visible instead of leaving
  excluded data silently missing from the figure.

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
