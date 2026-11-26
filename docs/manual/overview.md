# User manual

This manual describes how to run AFM Nanofiber Analyzer. What the analysis
computes is explained in [algorithms.md](../algorithms.md),
[gui04_measurements.md](../gui04_measurements.md) and
[gui03_statistics.md](../gui03_statistics.md).

## Using the GUIs

Each tool is started from the launcher (`python Main.py`, or the `run_venv` /
`run_conda` launchers described in the README), which has one button per tool.

- [Format Converter (GUI00)](gui00_format_converter.md): converts files in
  formats this software cannot read into `.gwy` files for GUI01.
- [Image Preprocessor (GUI01)](gui01_image_preprocessor.md): analyzes AFM
  height images into the `.b2z` bundles the other tools read.
- [Thumbnail Viewer (GUI05)](gui05_thumbnail_viewer.md): shows many bundles
  side by side and saves them as A4 sheets.
- [Plot Profiler (GUI02)](gui02_plot_profiler.md): extracts a height profile
  along a line drawn on a height image.
- [Bundle Editor (GUI06)](gui06_bundle_editor.md): corrects an analysis by
  hand and saves it as a new bundle.
- [Fiber Tracker (GUI04)](gui04_fiber_tracker.md): lists the fibers of a bundle
  with their values, and joins or excludes fibers before they are aggregated.
- [Fiber Morphology Statistics (GUI03)](gui03_fiber_morphology_statistics.md):
  compares the distribution of one fiber quantity between groups of bundles.

## Analyzing in Python with Jupyter

[`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb) runs the analysis
from Python without the GUIs. It analyzes an AFM scan into a `.b2z` bundle,
measures every fiber into a pandas table, draws the height image with the
measured centerlines and kinks, saves the table as CSV, and measures several
scans together. [`notebooks/quickstart.ja.ipynb`](notebooks/quickstart.ja.ipynb)
is the same notebook with the explanations in Japanese.

The package is not on PyPI. Install it from a checkout of the repository,
together with JupyterLab, and open the notebook there:

```
python -m pip install .
python -m pip install jupyterlab
python -m jupyter lab
```

The notebook reads the scans bundled in `testdata/` through paths relative to
its own folder; replace them in its first code cell with your own files. It is
stored without outputs, so the tables and figures appear when it is run.
`tests/test_manual_notebooks.py` runs it in the test suite, so its code follows
the current API.
