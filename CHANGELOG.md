# Changelog

All notable changes to AFM Nanofiber Analyzer are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Background-estimation quality metrics (`lib/bg_quality.py`), so a
  `bg_method` or parameter choice can be justified by numbers rather than by
  eye. Halo detection samples a signed cross-section perpendicular to the
  local fiber direction along the skeleton and uses no binarized mask, which
  keeps it sensitive to the *antisymmetric* halo — a trough on one flank and a
  ridge on the other — that any both-flanks-pooled statistic averages to zero.
  The halo is read at the extremum located from the cross-section's
  derivative, and its distance from the fiber is reported with it; averaging a
  band placed by a rule of thumb only partly overlaps the real feature and
  understates exactly the large halos that matter most. How far each
  cross-section reaches follows the fiber width measured from the
  cross-section itself, rather than a fixed pixel count, so the features of a
  wide fiber cannot fall outside the range that was actually sampled; when the
  image is too small to reach that far, the result reports the truncation
  instead of unsampled features. Reported alongside it: `halo_wide_nm` for a
  halo broader than the cross-section, which drags the cross-section's own
  reference level with it and would otherwise read as no halo;
  `halo_position_px` for how far the defect reaches; per-row and per-column
  stripe residual, the defect `bg_method="spline1d"` exists to remove; and
  `mask_footprint_nm`, which detects an over-dilated fiber mask imprinting its
  dilation radius on the result (excluding real substrate structure from the
  background pool makes the model unable to reproduce it, and the fiber floats
  above the background). Seven numbers in total, covering three defects that
  were each observed to occur while the other two read clean. No composite
  score is produced, because collapsing these into one number needs weights
  with no physical basis. They exist to screen which scans are worth training
  on: the ML tasks are trained against the classical pipeline's output, so a
  scan whose background correction went wrong supplies bad labels. Nothing in
  the classical pipeline calls them, so its processing speed and its outputs
  are unchanged.
- `python cli.py bgquality` reports those metrics for existing `.b2z` bundles,
  with `--csv` for a comparison table across a parameter sweep and
  `--union-mask` to score every input over one identical pixel set so runs
  that differ only in `bg_method` stay comparable.
- `python cli.py bgcompare DIR_A DIR_B` compares two processing conditions run
  on the same inputs, pairing bundles by filename. It always reports the fiber
  population split into real fibers and shorter fragments (`--min-fiber-um`),
  and always renders the calibrated, binarized and skeletonized images of both
  conditions side by side at a fixed display range. Neither is optional:
  a median pooled over a population whose composition changed measures the
  composition rather than the measurement, and a fiber count read without the
  images can suggest fibers were lost when they are intact.
- The metrics are computed on demand and deliberately not stored in the
  `.b2z` bundle. They are exactly reproducible from the arrays and parameters
  it already holds, so a stored copy would save about a second per file while
  making it possible to read back values from an older definition of the
  metrics and compare them, unmarked, against current ones. The bundle format
  and its contract are unchanged by this feature.
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

- The `inpaint` background method is renamed to `trendfill`, because it no
  longer inpaints: the mask is filled by subtracting a fitted second-order
  trend surface, propagating the nearest background pixel, smoothing, and
  restoring the trend. `_param.json` files and GUI01 startup settings written
  before the rename keep working — `"inpaint"` is translated to `"trendfill"`
  on load (`lib.bg_calibrator.canonical_bg_method`), accepted by
  `validate_params`, and normalized by `BGCalibrator`. Only the new name is
  offered in the GUI01 dropdown.

### Fixed

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
- GUI07 overlays are centered on their pixels too. The annotator was built on
  GUI04 and inherited the same upper-left placement, so the fiber track, the
  kink markers on both the overview and the single-fiber view, the filtered and
  color-coded fiber scatters, and the connection lines were all drawn half a
  pixel up and to the left. The connection lines are only shifted where they
  are drawn: the endpoint coordinates recorded in a connection label file stay
  integer pixel indices, so existing label files still match. Fiber bounding
  boxes are unchanged — a box edge belongs at the pixel boundary, not its
  center.
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
