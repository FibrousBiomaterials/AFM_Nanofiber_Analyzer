# User manual

This manual describes how to run AFM Nanofiber Analyzer. What the analysis
computes is explained in [algorithms.md](../algorithms.md),
[gui04_measurements.md](../gui04_measurements.md) and
[gui03_statistics.md](../gui03_statistics.md).

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
