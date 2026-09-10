"""Sphinx configuration for the AFM Nanofiber Analyzer API documentation."""

import sys
from pathlib import Path

# Document the package from the source tree, so the build works without an
# editable install (e.g. a clean `pip install sphinx furo` in a fresh venv).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import __version__  # noqa: E402  (needs the sys.path entry above)

project = "AFM Nanofiber Analyzer"
copyright = "2026, Shingo Kiyoto, Tomoki Ito, Keita Mayumi, Kayoko Kobayashi"
author = "Shingo Kiyoto, Tomoki Ito, Keita Mayumi, Kayoko Kobayashi"
release = __version__
version = __version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    # Renders the Markdown pages (algorithms.md) alongside the reStructuredText
    # ones. The narrative pages are Markdown so the same source reads correctly
    # both here and on GitHub, which is where the .ja.md counterparts are read.
    "myst_parser",
]

# `dollarmath` enables $...$ and $$...$$ math. GitHub renders the same syntax
# natively, so a formula written once displays in both places; the Sphinx-only
# `.. math::` directive would show as raw text in the repository view.
myst_enable_extensions = ["dollarmath"]

# Docstrings follow NumPy style (see AGENTS.md section 3), not Google style.
napoleon_numpy_docstring = True
napoleon_google_docstring = False

# Type hints already appear in the signature, and the docstrings deliberately
# do not repeat them, so leave autodoc's default signature rendering in place.
autodoc_member_order = "bysource"
autodoc_typehints = "signature"

# lib/ui_tools.py imports tkinter at module level. Mocking it keeps the doc
# build independent of a Tk installation and of a display, which matters on
# headless CI runners.
autodoc_mock_imports = ["tkinter"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "scipy": ("https://docs.scipy.org/doc/scipy", None),
    "skimage": ("https://scikit-image.org/docs/stable", None),
}

templates_path = ["_templates"]
# The published site is English (see AGENTS.md section 1). The `*.ja.md`
# counterparts stay version-controlled and are read on GitHub; excluding them
# here keeps them out of the build instead of raising "not in any toctree".
# `related_afm_tools.md` is a local-only guide (it is listed in .gitignore and
# is absent from a fresh clone), so it is not part of the published site
# either; naming it here keeps a local build warning-free.
exclude_patterns = ["_build", "*.ja.md", "related_afm_tools.md"]

html_theme = "furo"
html_static_path = []
