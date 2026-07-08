# Changelog

All notable changes to AFM Nanofiber Analyzer are documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
