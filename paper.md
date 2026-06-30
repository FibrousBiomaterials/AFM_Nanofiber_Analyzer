---
title: "AFM Nanofiber Analyzer: A GUI and CLI toolkit for nanofiber morphology from AFM height images"
tags:
  - Python
  - atomic force microscopy
  - nanofiber
  - cellulose nanofiber
  - image analysis
  - skeletonization
authors:
  - name: Shingo Kiyoto
    orcid: 0000-0002-5228-9964
    affiliation: 1
    corresponding: true
  - name: Keita Mayumi
    orcid: 0009-0003-2304-7549
    affiliation: 1
  - name: Tomoki Ito
    orcid: 0000-0002-2473-7117
    affiliation: 2
  - name: Kayoko Kobayashi
    orcid: 0000-0003-0459-7900
    affiliation: 1
affiliations:
  - name: Kyoto University, Japan
    index: 1
  - name: The University of Tokyo, Japan
    index: 2
date: 14 June 2026
bibliography: paper.bib
---

# Summary

Atomic force microscopy (AFM) resolves the height topography of individual
nanofibers, but turning raw height scans into quantitative, per-fiber
measurements is laborious and difficult to reproduce by hand. `AFM Nanofiber
Analyzer` is a Python toolkit that automates this workflow. It reads AFM height
images exported as text/CSV or stored in native Gwyddion `.gwy` files, removes
instrument background, segments and skeletonizes the fibers, detects sharp
bends ("kinks"), and reports per-fiber statistics such as length, height, and
kink geometry.

The software exposes the same analysis through three complementary surfaces: a
tkinter plugin launcher with four interactive tools (preprocessing, profile
extraction, height-distribution comparison, and a fiber tracker), a
command-line interface for batch processing, and a small set of reusable
library modules. The graphical and command-line entry points share a single
pipeline implementation, so an analysis run from the GUI and the same run from
the CLI produce identical numerical outputs for the same input and parameters.
Intermediate and final results are stored in a single compressed bundle file
per input (`.b2z`) whose contents — array keys, shapes, units, and coordinate
convention — are governed by an executable schema that is validated when
bundles are written and read. The toolkit can be installed from source for
development or packaged as a standalone Windows application bundle for
laboratory users who do not maintain a Python environment.

# Statement of need

Researchers studying cellulose nanofibers and related nanomaterials routinely
acquire large numbers of AFM scans and need fiber-level descriptors — height,
length, branching, and kink angle distributions — to characterize how
processing conditions affect morphology. General-purpose scanning-probe
software such as Gwyddion [@Necas2012] is excellent for image-level
visualization, leveling, and grain analysis, but it does not provide the
fiber-centric skeleton tracing, kink detection, and grouped statistical
comparison that this domain requires. As a result, these measurements are often
made manually or with one-off scripts that are hard to share, parameterize
consistently, or reproduce.

`AFM Nanofiber Analyzer` addresses this gap with a documented, reproducible
pipeline built on the scientific Python stack — NumPy [@Harris2020],
SciPy [@Virtanen2020], scikit-image [@vanderWalt2014],
OpenCV [@Bradski2000], lmfit [@Newville2014], and Matplotlib [@Hunter2007].
It packages the background-calibration, segmentation, skeletonization, and
kink-detection stages that were previously implemented as ad hoc scripts
[@Ito_afm_image] into a maintained, tested library with both interactive and
batch front ends. Background calibration offers four interchangeable methods
(inpainting, morphological top-hat, and 1D/2D spline surfaces) and was tuned
for, but is not limited to, height images exported by a Shimadzu SPM-9600
instrument. The shared pipeline, the validated bundle contract, and an
automated test suite that runs the full-size analysis on real scans make
results portable between laboratory machines and reproducible over time.

The software is intended for materials-science and polymer researchers who work
with AFM images of fibrous samples. It lowers the barrier to consistent,
high-throughput morphological analysis and provides a stable data format and
library API that other tools can build on. User-facing strings are localized
through gettext (English, Japanese, and Chinese catalogs are provided) so the
GUI is usable by the originating laboratory's maintainers as well as an
international audience.

# State of the field

Several mature, openly licensed tools cover parts of the AFM analysis workflow.
Gwyddion [@Necas2012] is the most widely used open-source scanning-probe
microscopy package and provides extensive image-level functionality — levelling,
filtering, statistical characterization, and grain (particle) analysis —
together with a scripting interface. These capabilities target surfaces, grains,
and roughness rather than networks of individual fibers, so Gwyddion does not
provide the skeleton-based fiber tracing, kink-angle detection, or grouped
comparison of per-fiber height distributions that this domain requires. The
general scientific-Python ecosystem supplies the lower-level building blocks for
such an analysis — n-dimensional arrays [@Harris2020], image processing and
skeletonization [@vanderWalt2014], interpolation and signal routines
[@Virtanen2020], and computer-vision primitives [@Bradski2000] — but assembling
them into a consistent, validated, fiber-level pipeline is left to each
laboratory.

As a result, fiber-level AFM morphology is commonly quantified with bespoke,
unpublished scripts; the analysis in `AFM Nanofiber Analyzer` itself began as
such a collection of single-purpose scripts [@Ito_afm_image]. Rather than
extending a surface-oriented tool with a fiber-specific plugin, or leaving the
steps as disconnected scripts, this project consolidates the fiber-centric
stages into one tested library with shared GUI and CLI front ends and an
explicit, versioned data contract, so that the same analysis can be reproduced,
scripted, and audited across machines.

# Software design

The toolkit is organized into three layers that share a single implementation
of the analysis. Reusable modules in `lib/` perform AFM text/CSV and native
Gwyddion input, background calibration, segmentation, skeletonization, kink
detection, and per-fiber measurement (\autoref{fig:pipeline}). A tkinter plugin
launcher discovers the four interactive tools in `guis/` — a preprocessor, a
profile extractor, a height-distribution comparison tool, and a fiber tracker
— while a command-line interface provides batch preprocessing, validation,
measurement, skeleton-height extraction, and bundle export. Both the GUI
preprocessor and the CLI call the single pipeline function `process_file`, and
the GUI measurement views and CLI call the same measurement routines, so
equivalent runs produce identical numerical results for the same input and
parameters. Keeping the analysis logic in `lib/` and the user interfaces thin
is a deliberate choice that prevents the front ends from drifting apart.

![Analysis pipeline: the six stages from raw AFM height image to per-fiber statistics.\label{fig:pipeline}](figures/pipeline.png)

Results are persisted as one compressed bundle per input (`.b2z`, built on
`blosc2`), accompanied by a JSON record of the analysis parameters. The bundle's
contents — required array keys, shapes, value ranges, units, coordinate
convention, and a format version — are defined by an executable schema that is
validated both when bundles are written and when they are read, so downstream
tools fail loudly on a malformed or out-of-contract bundle instead of producing
silently wrong measurements. The physical scan size travels with each bundle,
read from the input when present (Shimadzu `SizeX`/`SizeY`, Gwyddion Export
Text metadata, or native `.gwy` channel extents) or supplied explicitly; this
keeps length measurements reproducible from the bundle alone and lets a folder
of differently sized scans be processed without a single batch-wide value.
Bundles can be exported to standard NumPy `.npz` or CSV for use outside the
project.

Background calibration is provided as four interchangeable methods (inpainting,
morphological top-hat, and 1D/2D spline surfaces) so that line-scan artefacts of
differing severity can be addressed without changing the rest of the pipeline;
it was developed and tuned on Shimadzu SPM-9600 height images but is not specific
to that instrument. For laboratory users who do not maintain a Python
environment, the application is packaged as a standalone Windows application
bundle with PyInstaller; the trade-off is a larger download and a
platform-specific build, while developers continue to install the package from
source. An automated test suite — including regression tests that run the
full-size analysis on real scans and compare outputs against recorded baselines
— guards the numerical behaviour of the pipeline over time.

# Research impact statement

`AFM Nanofiber Analyzer` turns a laboratory AFM image-analysis workflow that was
previously difficult to reproduce outside the originating scripts into a
versioned, citable, and reviewer-testable software package. The repository
includes representative AFM text exports from Shimadzu and Bruker instruments,
Gwyddion Export Text samples, and a native `.gwy` file, along with command-line
examples and automated regression tests that run the full analysis on real
scans. These materials give reviewers and future users an objective way to
verify that the software installs, reads real instrument exports, writes valid
bundles, and preserves the numerical behaviour of the fiber-analysis pipeline
over time.

The package is designed for near-term reuse in nanocellulose and related
materials workflows where researchers need to compare fiber height, length, and
kink distributions across many AFM scans. Its impact is not limited to an
interactive desktop GUI: the shared CLI and library layers allow the same
analysis to be scripted for batch studies, embedded in other Python workflows,
or exported to standard NumPy and CSV formats for downstream statistics. The
validated `.b2z` bundle contract also makes intermediate AFM analysis products
shareable between collaborators without relying on many loose sidecar arrays or
undocumented local scripts.

# AI usage disclosure

During development, the authors used AI coding assistants — Claude Code
(Anthropic) and Codex (OpenAI) — to help draft and refactor code, to write and
translate docstrings and comments between English and Japanese, and to prepare
documentation. The assistants were used under author supervision; they did not
design the analysis methods or determine scientific results. All AI-assisted
output was reviewed, edited, and verified by the authors against the source code
and their domain knowledge, and the authors take full responsibility for the
software and its documentation.

# Acknowledgements

<!-- Authors: add funding sources, instrument facilities, and personal
acknowledgements here before submission. -->

# References
