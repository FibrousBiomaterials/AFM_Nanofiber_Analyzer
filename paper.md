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
images exported as text or CSV, removes instrument background, segments and
skeletonizes the fibers, detects sharp bends ("kinks"), and reports per-fiber
statistics such as length, height, and kink geometry.

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
development or packaged as a standalone Windows executable for laboratory users
who do not maintain a Python environment.

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
through gettext (English and Japanese are provided) so the GUI is usable by the
originating laboratory's maintainers as well as an international audience.

# Acknowledgements

During development, the authors used AI coding assistants — Claude Code
(Anthropic) and Codex (OpenAI) — to help draft and refactor code and to
translate docstrings and comments between English and Japanese. All
AI-assisted output was reviewed and verified by the authors, who take full
responsibility for the software and its documentation.

# References
