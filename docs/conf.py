"""Sphinx configuration for the AFM Nanofiber Analyzer API documentation."""

import re
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

# Napoleon writes each dataclass field's annotation into a `:type:` field, and
# a field body is parsed as reStructuredText. Under docutils.conf's
# character-level inline markup, a dotted type name such as
# `lib.connect_selection.ChainMember` then reads as a hyperlink reference
# (`lib.connect_`) and renders as an error, so the underscores of these
# generated type names are escaped. Running after Napoleon (priority 500) is
# what makes the lines it generated visible here.
_TYPE_FIELD = re.compile(r"^(\s*:r?type:\s*)(.+)$")


def _escape_type_underscores(app, what, name, obj, options, lines):
    for index, line in enumerate(lines):
        match = _TYPE_FIELD.match(line)
        if match and "`" not in match.group(2):
            lines[index] = match.group(1) + match.group(2).replace("_", r"\_")


# The docstrings are bilingual (AGENTS.md section 1): Japanese maintainers read
# them through IDE hovers and help(), while the published reference is English.
# Each Japanese line is dropped here, before Napoleon (priority 500) parses the
# NumPy sections, so the source keeps both languages. Text in inline code,
# double quotes or 「」 does not make a line Japanese, because English lines
# quote Japanese UI labels such as "選択を除外".
_JAPANESE = re.compile(r"[　-〿぀-ヿ一-鿿＀-￯]")
_QUOTED = re.compile(r"``[^`]*``|`[^`]*`|\"[^\"]*\"|「[^」]*」|『[^』]*』")
# "Contract summary / 契約の要約" above an underline, or "Rule / 計算規則::".
_BILINGUAL_TITLE = re.compile(r"^(\s*\S.*?)\s+/\s+(.*)$")
_UNDERLINE = re.compile(r"^\s*([-=~^])\1{2,}\s*$")
_JA_SENTENCE_END = ("。", "！", "？", "：", ":")
_EN_SENTENCE_END = (".", ":", "!", "?", ")")


def _is_japanese(line):
    return bool(_JAPANESE.search(_QUOTED.sub("", line)))


def _indent(line):
    return len(line) - len(line.lstrip())


def _english_title(line, following):
    """Return the English half of a bilingual heading, or None."""
    match = _BILINGUAL_TITLE.match(line)
    if not match or _is_japanese(match.group(1)) or not _is_japanese(match.group(2)):
        return None
    if following is not None and _UNDERLINE.match(following):
        return match.group(1)
    if line.rstrip().endswith("::"):
        return match.group(1) + "::"
    return None


def _english_lines(lines):
    """Return the docstring lines with the Japanese ones removed."""
    n = len(lines)
    japanese = [_is_japanese(line) for line in lines]
    kept = list(lines)
    drop = [False] * n
    for i, line in enumerate(lines):
        if not japanese[i]:
            continue
        title = _english_title(line, lines[i + 1] if i + 1 < n else None)
        if title is None:
            drop[i] = True
        else:
            kept[i] = title
    # A Japanese sentence can wrap onto a line holding only code names, which
    # then sits between two Japanese lines of one paragraph. Such a run is part
    # of the Japanese text when the sentence above it is still open or the run
    # itself does not end an English sentence.
    i = 0
    while i < n:
        if japanese[i] or not lines[i].strip():
            i += 1
            continue
        j = i
        while (j < n and lines[j].strip() and not japanese[j]
               and _indent(lines[j]) == _indent(lines[i])):
            j += 1
        above = i > 0 and drop[i - 1] and _indent(lines[i - 1]) == _indent(lines[i])
        below = j < n and drop[j] and _indent(lines[j]) == _indent(lines[i])
        if above and below and (
            not lines[i - 1].rstrip().endswith(_JA_SENTENCE_END)
            or not lines[j - 1].rstrip().endswith(_EN_SENTENCE_END)
        ):
            for k in range(i, j):
                drop[k] = True
        i = j
    return [line for line, gone in zip(kept, drop) if not gone]


def _drop_japanese_lines(app, what, name, obj, options, lines):
    lines[:] = _english_lines(lines)


def setup(app):
    app.connect("autodoc-process-docstring", _drop_japanese_lines, priority=400)
    app.connect("autodoc-process-docstring", _escape_type_underscores, priority=600)
