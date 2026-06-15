# AFM Nanofiber Analyzer

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.xxxxxxx.svg)](https://doi.org/10.5281/zenodo.xxxxxxx)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![tests](https://github.com/q9-droid/AFM_Nanofiber_Analyzer/actions/workflows/test.yml/badge.svg)](https://github.com/q9-droid/AFM_Nanofiber_Analyzer/actions/workflows/test.yml)

AFM Nanofiber Analyzer is a tkinter-based desktop toolkit for preprocessing
atomic force microscopy (AFM) height images and inspecting nanofiber morphology.
It provides a plugin launcher, a preprocessing pipeline, profile and histogram
tools, and a fiber-tracking viewer for bundle files produced by the pipeline.

## Overview

The application separates GUI plugins from the reusable modules they call:

- `Main.py` launches GUI plugins discovered in `guis/`.
- `guis/` contains the user-facing tkinter tools.
- `lib/` contains AFM I/O, background calibration, segmentation,
  skeleton cleanup, kink detection, fiber containers, bundle I/O, translation,
  and shared UI helpers.

GUI01 writes one compressed `.b2z` bundle per analyzed input file. Downstream
GUIs read those bundles directly instead of relying on many sidecar `.npy`
files.

## GUI Tools

| File | Launcher name | Purpose |
|---|---|---|
| `guis/GUI01_Image_Preprocessor.py` | Image Preprocessor | Load raw AFM text data, run background calibration, segmentation, skeletonization, and kink-related feature extraction, then save a `.b2z` bundle and a parameter JSON file. |
| `guis/GUI02_PlotProfiler.py` | Plot Profiler | Load raw, calibrated, or bundled AFM height data and interactively extract height profiles along selected line segments. |
| `guis/GUI03_Fiber_Height_Histogram.py` | Fiber Height Histogram | Compare height distributions from skeletonized fiber pixels across user-defined groups of `.b2z` bundles. |
| `guis/GUI04_Tracking_fiber.py` | Fiber Tracker | Load `.b2z` bundles, rebuild tracked `Fiber` objects, inspect individual fibers, export plots, and export fiber statistics to CSV. |

## Directory Structure

```text
AFM_Nanofiber_Analyzer/
|-- Main.py
|-- cli.py
|-- babel.cfg
|-- build.py
|-- check.py
|-- pyproject.toml
|-- requirements.txt
|-- requirements.lock.txt
|-- 01_setup_venv.bat
|-- 02_run_from_venv.bat
|-- 11_setup_conda_env.bat
|-- 12_run_from_conda_env.bat
|-- 91_setup_anaconda.bat
|-- 92_run_from_anaconda.bat
|-- 01_setup_venv.sh
|-- 02_run_from_venv.sh
|-- 11_setup_conda_env.sh
|-- 12_run_from_conda_env.sh
|-- 91_setup_anaconda.sh
|-- 92_run_from_anaconda.sh
|-- guis/
|   |-- GUI01_Image_Preprocessor.py
|   |-- GUI02_PlotProfiler.py
|   |-- GUI03_Fiber_Height_Histogram.py
|   |-- GUI04_Tracking_fiber.py
|   `-- __init__.py
|-- lib/
|   |-- afm_io.py
|   |-- bg_calibrator.py
|   |-- bg_calibrator_shimadzu.py
|   |-- blosc2_io.py
|   |-- bundle_schema.py
|   |-- fiber.py
|   |-- fiber_tracking_image.py
|   |-- imp_tools.py
|   |-- kink_detector.py
|   |-- measure.py
|   |-- pipeline.py
|   |-- processed_image.py
|   |-- segmenter.py
|   |-- skeletonizer.py
|   |-- translator.py
|   |-- ui_tools.py
|   `-- __init__.py
|-- tests/
|-- locale/
|   `-- ja/
|       `-- LC_MESSAGES/
|-- assets/
|   `-- afm_symbol.png
`-- README.md
```

Windows `.bat` helper scripts are intentionally kept ASCII-only. Japanese
comments in UTF-8 batch files can be misread by `cmd.exe` under the system code
page and executed as garbled commands, so Japanese maintenance notes belong in
Markdown documents such as `docs/maintainer-notes.ja.md`.

## Core Modules

| Module | Main contents |
|---|---|
| `lib/afm_io.py` | Text/CSV AFM loader with automatic header, column, and encoding detection, explicit format override, and layout-consistency verification. |
| `lib/bg_calibrator.py` | `BGCalibrator`, with `inpaint`, `tophat`, `spline1d`, and `spline2d` background methods. |
| `lib/bg_calibrator_shimadzu.py` | Compatibility shim keeping the historical `BG_Calibrator_shimadzu` name importable. |
| `lib/blosc2_io.py` | Blosc2 array storage and `.b2z` TreeStore bundle helpers. |
| `lib/bundle_schema.py` | Executable `.b2z` contract: required keys, array shapes, value ranges, units, coordinate convention, and format version, with `validate_bundle` enforcing them at write and load time. |
| `lib/fiber.py` | Immutable `Fiber` dataclass for fiber geometry, height profile, kink indices, and endpoint indices. |
| `lib/fiber_tracking_image.py` | `FiberTrackingImage`, used by GUI04 to rebuild and track fibers from GUI01 bundle outputs. |
| `lib/imp_tools.py` | Skeleton morphology helpers, endpoint/branch-point detection, line tracing, and path-distance conversion. |
| `lib/kink_detector.py` | `KinkDetector`, which detects kink points from tracked skeleton components. |
| `lib/measure.py` | GUI-independent fiber measurement on `.b2z` bundles: `measure_bundle`, per-fiber `FiberStats`, skeleton-height collection, and the CSV writers shared by GUI03/GUI04 and `cli.py`. |
| `lib/pipeline.py` | `ProcParams` parameter schema, `.b2z` key contract, and `process_file`, the GUI-independent pipeline driver shared by GUI01 and `cli.py`. |
| `lib/processed_image.py` | `ProcessedImage`, the container passed through the GUI01 preprocessing pipeline. |
| `lib/segmenter.py` | `Segmenter`, which builds binary nanofiber masks from calibrated AFM images. |
| `lib/skeletonizer.py` | `Skeletonizer`, which thins segmented masks, prunes branches, and labels skeleton components. |
| `lib/translator.py` | gettext language selection helpers. |
| `lib/ui_tools.py` | Shared tkinter, matplotlib, logging, dialog, and export helpers used by the GUI plugins. |

## Requirements

- Python 3.10 or later
- Windows is the primary target platform

Install the Python dependencies listed in `requirements.txt`:

```text
blosc2
lmfit
matplotlib
numpy
opencv-python
pandas
Pillow
scikit-image
scipy
```

`check.py` can regenerate `requirements.txt` by scanning imports in the source
tree. PyInstaller is used only for standalone builds and is installed
separately when building a distribution.

For an exact, reproducible environment, `requirements.lock.txt` records a
test-verified snapshot of all package versions:

```powershell
python -m pip install -r requirements.lock.txt
```

`check.py` also provides dependency consistency checking and pinning:

```powershell
python check.py            # regenerate the loose requirements.txt (as before)
python check.py --verify   # CI-style check: code imports vs pyproject vs environment
python check.py --pin      # re-lock requirements.lock.txt after all checks and tests pass
```

`--verify` exits nonzero when an import is missing from `pyproject.toml`
dependencies (or vice versa), when a scanned dependency is not installed, or
when `pip check` reports version conflicts. `--pin` runs those same checks
plus the pytest suite, and rewrites `requirements.lock.txt` only when
everything passes, so the lock file always records a version set that the
tests have actually validated.

## Installation and Usage

Before running the helper scripts, install one of the following Python
distributions:

- Python 3.10 or later from <https://www.python.org/>
- Anaconda or Miniconda from <https://www.anaconda.com/download> or
  <https://docs.conda.io/en/latest/miniconda.html>

### Recommended: use a dedicated venv

Clone the repository, move into the project root, and run the venv helper
scripts for your operating system. This is the recommended setup because it
keeps AFM Nanofiber Analyzer dependencies separate from packages already
installed in Anaconda or other Python environments.

```powershell
git clone https://github.com/<your-username>/afm-nanofiber-analyzer.git
cd afm-nanofiber-analyzer
```

Windows:

```powershell
.\01_setup_venv.bat
.\02_run_from_venv.bat
```

macOS or Linux:

```bash
chmod +x 01_setup_venv.sh 02_run_from_venv.sh
./01_setup_venv.sh
./02_run_from_venv.sh
```

The setup scripts create the `.venv`, upgrade `pip`, and install the project in
editable mode (`pip install -e .`), so all dependencies come from
`pyproject.toml` (the single source of truth) and the `afm-analyzer` /
`afm-analyzer-cli` commands are registered. The run scripts launch `Main.py`
from that `.venv`. Developers and reviewers can reproduce the same setup
without the scripts using the editable-install commands below; for an exact,
pinned version set, install `requirements.lock.txt` instead (see Requirements
above).

### Anaconda or Miniconda

Starting the application directly from an existing Anaconda `base` environment
is not recommended. Pre-installed binary packages such as NumPy, Matplotlib,
SciPy, and scikit-image may conflict with the versions required by this
application.

If you need to use Anaconda or Miniconda, use the conda environment helper
scripts. They create a dedicated `afm-analyzer` environment and run the
application from that environment instead of modifying `base`.

Windows:

```powershell
.\11_setup_conda_env.bat
.\12_run_from_conda_env.bat
```

macOS or Linux:

```bash
chmod +x 11_setup_conda_env.sh 12_run_from_conda_env.sh
./11_setup_conda_env.sh
./12_run_from_conda_env.sh
```

The `91_setup_anaconda.*` and `92_run_from_anaconda.*` scripts are kept for
compatibility with older distributions, but they should not be used for new
setups because they install into an existing Anaconda environment.

### Localization

The graphical interface uses Python's `gettext` system for operational UI
strings such as menus, buttons, dialogs, status messages, and tooltips.
Translation catalogs are stored under `locale/`, and language selection is
handled by `lib/translator.py` using the configured environment and system
locale.

Scientific and reproducibility-oriented strings, including plot titles, axis
labels, CSV headers, exported result labels, data keys, and units, are kept in
English so analysis outputs remain consistent across languages.

To refresh translation catalogs after editing user-facing strings or plugin
descriptions, run:

```powershell
python prepare_translate_catalogs.py
```

This script extracts gettext messages, adds launcher descriptions from
`PLUGIN_INFO["description"]`, updates the catalogs, removes obsolete
`#~` entries, and compiles the catalogs to `.mo`. It does not fill `msgstr`
values automatically. Commit or back up catalogs first if you need to keep old
obsolete translations for reference.

After editing `messages.po`, review any `#, fuzzy` entries before distribution.
Fuzzy entries are provisional Babel matches; confirm that the `msgid` and
`msgstr` meanings match and that placeholders such as `{path}`, `%s`, `%d`, and
`\n` are preserved. Remove the `#, fuzzy` line only after the translation is
confirmed. Then compile the catalogs:

Do not add `\n` in the middle of a translated sentence only to tune visual line
wrapping. Different languages wrap at different positions, so the UI should
handle wrapping. Use explicit line breaks only when the text needs a meaningful
paragraph or line break in the interface.

```powershell
pybabel compile -d locale
```

The compiled `.mo` files are version-controlled so that fresh clones get
working translations without installing Babel. Commit the regenerated `.mo`
files together with the edited `.po` files; the test suite fails when a
`.mo` file is stale relative to its `.po` source.

### Manual setup from source

```powershell
git clone https://github.com/<your-username>/afm-nanofiber-analyzer.git
cd afm-nanofiber-analyzer

py -3.12 -m venv .venv
.\.venv\Scripts\activate

python -m pip install -U pip
python -m pip install -r requirements.txt

python Main.py
```

### Editable install for development (pip)

The project ships a `pyproject.toml` for development installs. Installing in
editable mode declares all runtime dependencies and registers two console
commands; adding `[dev]` also installs pytest:

```powershell
python -m pip install -e ".[dev]"

afm-analyzer                          # launcher GUI (same as python Main.py)
afm-analyzer-cli process data\*.txt   # batch pipeline (same as python cli.py)
```

The editable install targets development from a checkout. End-user
distribution remains the PyInstaller bundle described below.

### Build a standalone Windows bundle

Install PyInstaller before running the build script:

```powershell
python -m pip install pyinstaller
```

```powershell
python build.py
```

The build script generates a PyInstaller bundle under `dist/Main/` and copies
the plugin/resource folders needed by the launcher. Distribute the entire
`dist/Main/` folder, not only `Main.exe`.

## Supported Input Formats

`lib/afm_io.py` loads text/CSV height exports and auto-detects the header
length, column count, and encoding (UTF-8, cp932/Shift-JIS, latin-1 fallback),
so no import settings are required. Two layouts are recognized:

| Layout | Typical source | Description |
|---|---|---|
| Multi-column | Shimadzu SPM-9600 | Comma-separated values, one row per scan line. Non-square scans are supported. |
| Single-column | Bruker NanoScope | Text header lines (e.g. `Height(nm)`) followed by one value per line. The value count must be a perfect square; the data is reshaped to `(s, s)`. |

Height values are interpreted as nanometers. The physical scan size is not
read from the input file; pixel-to-physical scaling is configured in the GUIs.
Sample scans are bundled under `testdata_tunicateCNF/` (Shimadzu) and
`Bruker_testdata/` (one representative Bruker NanoScope export).

The background calibrator (`BGCalibrator` in `lib/bg_calibrator.py`)
implements general line-scan AFM background correction and is applied to both
formats. It was developed on Shimadzu SPM-9600 scans and was historically
named `BG_Calibrator_shimadzu`; that import path and class name remain
available through a compatibility shim.

## Analysis Pipeline

```text
Raw AFM text/CSV input
        |
        v
GUI01 Image Preprocessor
        |
        |-- afm_io.load_afm_text()
        |-- BGCalibrator
        |-- Segmenter
        |-- Skeletonizer
        |-- KinkDetector
        |
        v
<input_stem>.b2z      compressed TreeStore bundle
<input_stem>_param.json
        |
        +-- GUI02 Plot Profiler
        +-- GUI03 Fiber Height Histogram
        `-- GUI04 Fiber Tracker
```

The preprocessing parameters are stored in the generated
`<input_stem>_param.json` file. They cover background calibration, segmentation,
skeletonization, and kink detection settings, including options such as
background method, threshold values, branch pruning length, and kink angle
threshold.

### Command-line batch processing

The same pipeline can be run without the GUI through `cli.py`, which calls
`lib.pipeline.process_file` — the identical code path used by GUI01 — so CLI
and GUI outputs match for the same input and parameters. This supports
scripted batch runs and reproducible analyses.

```powershell
# Print the default analysis parameters as an editable JSON template.
python cli.py show-params > my_param.json

# Process files with default or customized parameters.
python cli.py process testdata_tunicateCNF\*.txt
python cli.py process scan.txt --params my_param.json --output-dir results --overwrite
```

`process` writes one `.b2z` bundle and one `_param.json` per input, next to
the input file unless `--output-dir` is given. Inputs whose outputs already
exist are skipped unless `--overwrite` is passed. `--save-original` embeds the
raw height image in the bundle under the `original` key. With `--strict`,
unknown keys in the `--params` file are an error instead of being ignored,
which catches typos that would otherwise silently fall back to defaults.
`--format` forces the input text layout (`multi-column` or `single-column`)
when auto-detection would lock onto a numeric header block; the resolved
layout is always recorded in the bundle metadata (`input_format`) for audit.

### Validating bundles

The `.b2z` contract (required keys, array shapes, mask values, kink-angle
units, format version) is defined in code by `lib/bundle_schema.py`. The
pipeline validates every bundle before saving and the measurement layer
validates at load time; `validate` runs the same checks on demand:

```powershell
python cli.py validate results\*.b2z
```

Each bundle is reported as `OK` (with format version, image size, kink count,
and provenance status) or `INVALID` with the specific contract violations.
The exit code is non-zero when any bundle fails, so the command can guard
scripted workflows.

### Command-line fiber measurement

The fiber-level measurements shown by GUI03 and GUI04 are also available from
the command line through `lib.measure` — the identical code path used by the
GUIs — so the statistics CSV produced by `measure` is byte-identical to the
GUI04 export for the same bundle and scale.

```powershell
# Per-fiber statistics (length, height median/max, endpoints, kinks).
# The physical image size in micrometers must be given explicitly because
# the scan size is not stored in the bundle.
python cli.py measure results\*.b2z --scale-um 2.0
python cli.py measure results --scale-um 2.0 --output-dir stats

# Skeleton-pixel heights (the data behind the GUI03 height histogram).
python cli.py heights results --output heights.csv
```

`measure` writes one `<stem>_fibers.csv` per bundle with columns `index`,
`length_nm`, `height_median_nm`, `height_max_nm`, `ep_count`, `kink_count`,
and `kink_angles_deg` (semicolon-separated degrees). `heights` prints a
per-bundle summary and optionally writes a long-format CSV (`bundle`,
`height_nm`) for regrouping and re-binning in external tools. Folder
arguments expand to all bundles directly inside the folder.

### Running tests

The test suite uses pytest. Unit tests run on a small synthetic fiber image;
an integration test processes a bundled real scan with default parameters and
compares summary statistics against recorded baseline values.

```powershell
python -m pip install pytest
python -m pytest tests/
python -m pytest tests/ -m "not slow"   # skip the real-scan integration test
```

## Data Format

The current analysis output is a single `.b2z` bundle per input file. Bundles
are written by `lib/blosc2_io.py` using `blosc2.TreeStore`. The layout is
documented below so the bundles can be read without this project's code, and
`cli.py export` converts them to standard formats (see the end of this
section).

GUI01 writes these array keys:

| Key | Shape | Content |
|---|---|---|
| `calibrated` | `(H, W)` | Background-corrected AFM height image, floating point, in nm. |
| `binarized` | `(H, W)` | Binary nanofiber mask (nonzero = fiber). |
| `skeletonized` | `(H, W)` | Skeletonized fiber image (nonzero = centerline). |
| `bp` | `(H, W)` | Branch-point mask on the skeleton (nonzero = branch point). |
| `ep` | `(H, W)` | Endpoint mask on the skeleton (nonzero = endpoint). |
| `kp` | `(2, N)` | Kink-point pixel coordinates; see the convention below. |
| `dp` | `(2, M)` | Decomposition-point pixel coordinates; see the convention below. |
| `ka` | `(N,)` | Kink interior angles in radians, one per `kp` column. |
| `original` | `(H+1, W+1)` | Raw height image in nm; present only when saving the original was requested. |

All image-like arrays in one bundle share the same `(H, W)` shape. The
background calibrator trims one pixel per axis, so `H` and `W` are one less
than the raw input size (and one less than `original` when present).

Coordinate convention: `kp[0]` and `dp[0]` hold x (column) indices, and
`kp[1]` and `dp[1]` hold y (row) indices — 0-based pixel positions in the
`calibrated` image. For example, `calibrated[kp[1][i], kp[0][i]]` is the
height at the i-th kink.

Each bundle also stores root metadata (blosc2 `vlmeta`):

| Key | Content |
|---|---|
| `params` | Analysis-parameter dictionary, identical to `<input_stem>_param.json`. |
| `version` | Bundle format version (currently `"1.0"`). |
| `software_version` | Application release that wrote the bundle. |
| `input_file` | Base name of the processed input file. |
| `input_sha256` | SHA-256 digest of the input file contents. |
| `created_utc` | Processing time as an ISO 8601 UTC timestamp. |

The provenance keys (`software_version`, `input_file`, `input_sha256`,
`created_utc`) are optional: bundles written by older releases lack them, and
readers must not require them.

GUI01 also writes `<input_stem>_param.json` for analysis parameters. The raw
AFM image is not duplicated in the bundle by default because it can be
reloaded from the source text file.

### Exporting bundles to standard formats

`.b2z` is a project-specific container. To use analysis results outside this
project, export bundles to standard formats:

```powershell
python cli.py export results\*.b2z                # one .npz archive per bundle
python cli.py export results\*.b2z --format csv   # one CSV file per array key
```

Both formats are accompanied by a `<stem>_meta.json` sidecar holding the
bundle metadata. NumPy `.npz` archives can be read with standard tooling from
Python, MATLAB, R, and Julia.

## Adding a GUI Plugin

1. Add a Python file under `guis/`.
2. Define a literal `PLUGIN_INFO` dictionary near the top of the file.
3. Define a typed `main() -> None` entry point.

Example:

```python
PLUGIN_INFO = {
    "name": "My Tool",
    "description": "Short launcher-facing description.",
}


class App(tk.Tk):
    ...


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

`Main.py` discovers plugin files automatically. `PLUGIN_INFO` values must remain
plain literals because the launcher reads them with `ast.literal_eval()`.
Plugin names are shown as fixed English strings. Plugin descriptions are also
plain literals in the plugin file, but `Main.py` passes them through gettext
after AST parsing so they can be translated through the locale catalogs.
Do not insert `\n` in `PLUGIN_INFO["description"]` only to tune launcher line
wrapping. Keep the description as natural text; the launcher UI is responsible
for wrapping it. Splitting the Python string literal across source lines is fine
as long as it does not add an actual newline to the value.
When changing `PLUGIN_INFO["description"]`, refresh the translation catalogs so
the corresponding `msgid` is available to translators.

`PLUGIN_INFO` may also define an optional numeric `order` key. The launcher
sorts buttons by this value (smaller first); plugins without `order` appear
after the ordered ones, in filename order. Unknown `PLUGIN_INFO` keys are
ignored for forward compatibility. The plugin contract — a literal
`PLUGIN_INFO` with non-empty `name` and `description` strings, a top-level
`main()`, an `if __name__ == "__main__":` guard, and no GUI launch at import
time — is enforced by `tests/test_plugins.py`, so a violating plugin fails the
test suite instead of degrading silently in the launcher.

## Development Utilities

- `check.py` scans Python imports and writes `requirements.txt`; `--verify`
  reports drift between code imports, `pyproject.toml`, and the installed
  environment, and `--pin` regenerates `requirements.lock.txt` after the
  consistency checks and the test suite pass.
- `build.py` verifies imports, collects PyInstaller materials, writes
  `Main.auto.spec`, runs PyInstaller, and copies project resource folders.
- `prepare_translate_catalogs.py` refreshes gettext catalogs, extracts plugin
  descriptions, and removes obsolete translation entries.

## Citation

If you use this software in your research, please cite it as:

```bibtex
@software{afm_nanofiber_analyzer,
  author    = {[Author Names]},
  title     = {AFM Nanofiber Analyzer},
  year      = {2025},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.xxxxxxx},
  url       = {https://github.com/<your-username>/afm-nanofiber-analyzer}
}
```

## Authors

| Role | Name |
|---|---|
| Analysis algorithms and AFM-domain methods | [KK], [IT] |
| GUI and application packaging | [KS] |

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
details.

## Acknowledgements

The background calibration workflow includes methods developed for Shimadzu
SPM-9600 AFM data. Related AFM image-processing work is available at
<https://github.com/terio0819/Image-processing-of-AFM-image>.
