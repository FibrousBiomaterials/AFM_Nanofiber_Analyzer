# Contributing to AFM Nanofiber Analyzer

Thank you for your interest in improving AFM Nanofiber Analyzer. This document
explains how to report problems, ask for help, and contribute code or
documentation. Contributions of all kinds — bug reports, feature requests,
documentation fixes, and pull requests — are welcome.

## Getting help and support

- **Questions and usage help:** open a thread on the GitHub
  [Discussions](https://github.com/q9-droid/AFM_Nanofiber_Analyzer/discussions)
  page if it is enabled, or open an issue labeled `question`.
- **Documentation:** the user-facing documentation is the `README.md`
  (English) / `README.ja.md` (Japanese) pair. Maintainer-oriented notes live in
  `docs/`.

If you are unsure whether something is a bug or expected behavior, open an issue
and ask — we would rather hear about it.

## Reporting bugs

Please open an issue on the
[issue tracker](https://github.com/q9-droid/AFM_Nanofiber_Analyzer/issues) and
include, where possible:

- what you did, what you expected, and what actually happened;
- the operating system and Python version (`python --version`);
- how you installed the toolkit (editable source install or the packaged
  Windows bundle);
- the full error message or traceback;
- a minimal AFM input file or the parameters needed to reproduce the problem,
  if the issue is data-dependent. If the data cannot be shared, a description of
  its format (header rows, column count, encoding) is still helpful.

## Requesting features

Open an issue describing the scientific or workflow need behind the request, not
only the proposed implementation. Explaining *why* a capability is needed helps
us design it so it fits the existing pipeline and data contract.

## Development setup

The project targets Python 3.10 or later. Install it as an editable package
with the development dependencies:

```bash
python -m pip install -e ".[dev]"
```

This installs the launcher (`afm-analyzer`), the CLI (`afm-analyzer-cli`), and
the test tools (`pytest`, `pytest-xdist`, `Babel`). End-user distribution is the
standalone Windows bundle produced by `build.py`; see the README for details.

## Running the tests

Run the full suite before opening a pull request:

```bash
python -m pytest
```

The suite includes slow regression tests that process full-size real scans;
they are parallelized across CPU cores by default. The same checks run in
continuous integration on Linux and Windows across two Python versions.

If you add or change dependencies, keep the import declarations consistent and
verify them:

```bash
python check.py --verify
```

## Coding standards

The repository follows a detailed set of conventions for code structure,
comments, docstrings, GUI plugin layout, the `.b2z` bundle data contract, and
translations. These rules are defined in [`AGENTS.md`](AGENTS.md), which is the
canonical contributor guide for both human and AI contributors. Please read it
before making non-trivial changes. Highlights:

- **Comments and docstrings** follow a tiered bilingual policy: English is
  always required; Japanese is added where it preserves domain knowledge
  (instrument behavior, algorithm rationale, physical meaning) for the
  laboratory's maintainers. Do not delete existing Japanese comments wholesale.
- **Preserve existing non-ASCII text.** Edit files with a UTF-8 / cp932 aware
  editor; do not rewrite a whole file through shell redirection, which can save
  mojibake.
- **Data contract.** The `.b2z` bundle format is defined in
  `lib/bundle_schema.py`, which is the source of truth. Changing keys, shapes,
  or units requires bumping the format version and updating the dependent files
  listed in `AGENTS.md` (§8). Because such a change can break cross-tool
  workflows (GUI01–GUI04, the CLI, and external readers), please open an issue
  to discuss it before submitting the pull request.
- **GUI/CLI parity.** GUI plugins and the CLI share the pipeline in
  `lib/pipeline.py` and the measurement code in `lib/measure.py`. Keep analysis
  logic in `lib/` so both front ends stay numerically identical.
- **GUI plugins.** New GUI tools live under `guis/` and follow the plugin
  conventions in `AGENTS.md` §7: a literal `PLUGIN_INFO` dictionary, a typed
  `main() -> None` entry point guarded by `if __name__ == "__main__":`, shared
  helpers from `lib/ui_tools.py`, and no GUI launch at import time. The
  "Adding a GUI Plugin" section of the README shows a minimal template.
- **Localization.** Operational UI strings (menus, buttons, dialogs, status
  messages, tooltips) are translated with gettext: wrap them in `_()`, then
  update the catalogs with `pybabel` and commit the regenerated `.mo` files
  (see `AGENTS.md` §8.8); do not edit `.mo` files directly. Scientific and
  reporting strings — plot titles, axis labels, CSV headers, exported result
  labels, data keys, and units — stay fixed in English so analysis outputs are
  consistent across languages.
- **README pair.** `README.md` and `README.ja.md` are kept synchronized; an
  edit to one should be mirrored (and translated) in the other.

## Submitting a pull request

1. Fork the repository and create a topic branch from `main`.
2. Make focused, minimal changes; avoid unrelated refactors or formatting churn
   in the same pull request.
3. Add or update tests for any change in behavior.
4. Ensure `python -m pytest` and `python check.py --verify` pass locally.
5. Describe the motivation and the change in the pull request, and reference any
   related issue.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
