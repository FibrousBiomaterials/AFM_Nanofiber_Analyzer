# Agent Instructions

This file (`AGENTS.md`) is the **canonical instruction file** for every AI
coding agent working in this repository (Claude Code, Codex, and others).
`CLAUDE.md` exists only as a thin pointer that imports this file for Claude
Code. Apply rule changes here and only here; never add rules to `CLAUDE.md`,
and never let the two files diverge.

# Editing Rules

- Do not edit files not explicitly requested by the user.
- Do not perform unrelated refactors, formatting changes, translations, or cleanup.
- Before editing, state the target file paths and the intended change.
- If the change may require touching additional files, ask first. Files that
  this document explicitly requires to stay consistent (the README pair, the
  `.b2z` contract files in §8.2, translation catalogs in §8.8) count as part
  of the requested change once the user approves the edit that triggers them.
- Preserve Japanese text unless the user explicitly asks to translate it or a
  rule in this file requires it (README synchronization below, comment policy
  in §4).
- When reading files with non-ASCII text, do not conclude that the file is
  garbled from terminal display alone. PowerShell `Get-Content`, shell output,
  and chat/tool renderers may misdecode otherwise valid UTF-8 text. Before
  reporting mojibake or editing to "fix" it, inspect the file bytes and decode
  explicitly with UTF-8/UTF-8-SIG and cp932; treat the text as garbled only if
  the decoded file contents themselves contain replacement characters or
  mojibake patterns.
- Do not rewrite an entire non-ASCII file through PowerShell `Set-Content`, shell redirection, or ad hoc scripts merely to make targeted edits; this can permanently save mojibake. Use your agent's targeted-edit tool (`apply_patch`, `Edit`, or equivalent) for small edits, and preserve the file's existing encoding.
- If Japanese text appears garbled after an edit, stop immediately and restore the affected comments/docstrings from Git or a known-good UTF-8/cp932 backup before making further changes.
- Prefer minimal diffs over full rewrites.
- `README.md` and `README.ja.md` are a synchronized pair. When editing either
  one, apply the same corresponding edit to the other. Translating the edited
  passage into the other file's language is part of this synchronization and
  does not require a separate translation request.
- Do not run Git commands that discard or rewrite committed history or
  uncommitted work (`reset --hard`, `push --force`, `clean`, `rebase`, branch
  deletion, history filtering) unless the user explicitly requests that
  specific operation. Exception: restoring files corrupted by your own edit
  (e.g., `git restore <file>`) under the mojibake rule above is allowed.
- Do not use personal information (email addresses, real names, etc.) obtained from system context in examples, output, or generated code. Use placeholder values (e.g., `your@email.com`, `Your Name`) instead.
- Do not display the user's local absolute paths (anything outside the
  repository, such as the user profile directory) in chat responses.
  Repository-relative paths are fine.

# Commenting and Docstring Rules

This project will be submitted to the Journal of Open Source Software (JOSS).
Comments and docstrings must be understandable to English-speaking reviewers
while preserving the Japanese domain knowledge embedded by the original authors
for the lab's Japanese maintainers.

The policy is **tiered bilingual**, not "every line in both languages". Blanket
duplication doubles file size, adds noise for reviewers, and obscures intent.
Apply the level of duplication that matches the audience and content of each
comment, as defined in §1.

---

## 1. Language Policy

| Target | Rule |
|---|---|
| Module / class / public-function docstring | English required. Bilingual (English + Japanese) is the **default** for the summary line and for each `Parameters` / `Returns` / `Attributes` entry, because Japanese maintainers read docstrings via IDE hovers, `help()`, and Sphinx output. `Raises` and `Notes` are bilingual only when the Japanese line adds maintenance value (physical meaning, algorithm rationale, instrument quirk); otherwise English only. |
| Private function (`_foo`) docstring | English required. The summary line is bilingual. In the body, add Japanese for algorithm rationale, physical interpretation, instrument-specific behavior, or any other "why" a Japanese maintainer would want to read in Japanese; routine notes and self-evident parameter descriptions may be English only. |
| Inline / block comments (new or rewritten) | English required. Add a Japanese line only for non-obvious domain knowledge worth preserving for Japanese maintainers. |
| Windows `.bat` comments | Keep executable `.bat` files ASCII-only. Use concise English `REM` comments only; put Japanese explanations in Markdown documentation instead. |
| `.sh` comments | Follow the same intent-focused policy as Python inline comments. For setup, launch, build, and environment scripts, write concise English comments first and Japanese comments directly below for purpose, prerequisites, environment assumptions, failure-prone steps, and non-obvious command choices. Do not explain every command line-by-line. |
| Inline / block comments (existing Japanese) | See §4. Default is keep-and-translate, not delete. |
| README, `docs/`, user-facing prose | English only. Provide `*.ja.md` counterparts separately if needed (e.g., `README.ja.md`). |
| `PLUGIN_INFO`, `gettext` / `_()` strings | See §6. |

The asymmetry between docstrings and inline comments is intentional.
Docstrings are surfaced repeatedly by tooling and read out of code context,
so bilingual entries help Japanese maintainers most. Inline comments are read
in the flow of the surrounding code, where English alone is usually enough.

"Domain knowledge" means information not recoverable from the code alone:
instrument-specific behavior (e.g., Shimadzu SPM-9600 header layout), encoding
rationale (e.g., why `cp932`), algorithm rationale, parameter physical meaning,
calibration choices, or AFM workflow decisions. Implementation mechanics
visible in the code itself do not qualify.

---

## 2. Inline and Block Comments

### 2.1 Default: English, explain intent

New or rewritten inline comments are written in English and explain **why** —
intent, assumptions, limitations, rationale — not **what** the code does.
Apply the same rule to `.sh` files: comment the purpose, prerequisites,
environment assumptions, failure-prone steps, and non-obvious command choices;
avoid line-by-line narration of ordinary shell syntax. Windows `.bat` files are
an exception: keep the executable file ASCII-only, with English `REM` comments
only, because `cmd.exe` may interpret UTF-8 comments using the system code page
and execute garbled fragments as commands.

```python
# Try utf-8-sig first (it also reads BOM-less UTF-8), then cp932 for files
# exported on Japanese Windows; latin-1 is a last-resort byte-preserving fallback.
for enc in ("utf-8-sig", "cp932", "utf-8", "latin-1"):
    ...
```

### 2.2 Bilingual only for domain-specific notes

When a comment records non-obvious domain knowledge that a Japanese-speaking
maintainer would also want to read in Japanese, write the English line first,
then the Japanese translation on the next line. Both lines use `#`, with no
blank line between them. Do not apply this bilingual pattern inside Windows
`.bat` files; put the Japanese explanation in Markdown documentation instead.

```python
# encoding="cp932" handles Shift-JIS files exported on Japanese Windows systems.
# encoding="cp932" は日本語 Windows 環境で出力された Shift-JIS 系ファイルに対応する。
```

If the Japanese line would merely repeat the English line with no additional
maintenance value, omit it.

### 2.3 Do not comment the obvious

```python
# BAD
i += 1   # increment i

# GOOD — comment only when the "why" is non-obvious
i += 1   # skip the header row before entering the main loop
```

---

## 3. Docstrings

All public modules, classes, and functions require a docstring. Apply the
bilingual defaults from §1: English is always required, and the summary line
plus each parameter / return / attribute entry carries an English line and a
Japanese line by default. Use **NumPy-style headings** so Sphinx and numpydoc
can parse them; headings themselves stay in English.

### 3.1 Type hints and docstrings

If a parameter or return value already has a type hint, do **not** repeat the
type in the docstring. Describe meaning, units, constraints, and assumptions.

### 3.2 Heading rules

- Use standard English headings: `Parameters`, `Returns`, `Raises`, `Notes`,
  `Attributes`.
- Do **not** write `Parameters / パラメータ` etc. — translated headings can
  break doc generators.

### 3.3 Bilingual decisions inside the docstring

- Summary line, `Parameters`, `Returns`, `Attributes`: bilingual by default
  (English line then Japanese line).
- `Raises`: typically a short condition. English only is fine unless the
  Japanese line adds domain context.
- `Notes`: bilingual when it records algorithm rationale, instrument behavior,
  or other domain knowledge; English only when it is a routine implementation
  note.

---

## 4. Handling Existing Comments

Existing comments were written in Japanese during development and contain
domain knowledge that cannot be recovered from the code alone.
**Do NOT delete all existing comments and regenerate from scratch.**
That destroys the "why" information needed for review.

For each existing Japanese comment, take **exactly one** of the four actions
below. The default is keep-and-translate.

### 4.1 Keep and translate

If the comment carries non-obvious domain knowledge (instrument behavior, file
format quirks, algorithm rationale, parameter physical meaning, calibration
choice, workflow decision, or any "why" the code does not show), preserve it
and add an English line immediately above.

```python
# Before
# 島津 SPM-9600 が出力する CSV 形式の .txt ファイルを numpy 配列として読み込む

# After
# Load a Shimadzu SPM-9600 CSV-format .txt file as a NumPy array.
# 島津 SPM-9600 が出力する CSV 形式の .txt ファイルを NumPy 配列として読み込む。
```

### 4.2 Rewrite

Rewrite the comment in any of these cases, then apply §2 (English required,
Japanese only for domain notes):

1. The comment is technically correct but vague, redundant with the code, or
   merely restates what the code does.
2. The comment is **incomplete** with respect to the code — it correctly
   describes part of what the code does, and the code does additional things
   the comment does not mention. In this case, *extend* the comment so that
   the original statement remains true and the additional behavior is added.
   Preserve any domain knowledge the original comment carried (units, "why"
   notes) by carrying it into the rewritten version.

```python
# Before — comment is true but incomplete; the code also compresses the data
# CSV ファイルを読み込む
data = np.loadtxt(path, delimiter=",")
return blosc2.compress(data)

# After — original meaning preserved, new behavior added
# Load a CSV file and return a Blosc2-compressed byte string.
# CSV ファイルを読み込み、Blosc2 で圧縮したバイト列を返す。
data = np.loadtxt(path, delimiter=",")
return blosc2.compress(data)
```

Trivial rewrite — comment removed because the code is self-explanatory:

```python
# Before
i += 1   # iをインクリメントする

# After
i += 1
```

**Do NOT rewrite a comment when the comment and the code describe the same
behavior differently** (e.g., the comment says "per-row" but the loop iterates
columns; the comment says "high-pass filter" but the code applies a low-pass
filter). Such a mismatch can mean either:

- The comment is stale and the code is correct (a refactor forgot to update
  the comment); or
- The code has a bug and the comment correctly captures the intent.

An editing agent cannot reliably distinguish these two cases from the source
alone. Rewriting the comment to match the code in case (b) silently documents
a bug as intended behavior. Apply §4.4 (flag with `TODO(review)`) instead; do
not "fix" the comment unless the user has explicitly instructed that the code
is authoritative for this file or block.

### 4.3 Delete

Delete a comment only if it falls into one of:

- Merely restates what the code does (`i += 1  # iを1増やす`).
- Commented-out dead code without a reason for keeping it.
- Personal memos, context-free TODOs, debug remnants (`# hoge`, `# test`).

A comment that has drifted out of sync with the code is **not** in this list —
rewrite it under §4.2 instead, so the domain knowledge it carries is not lost.

Do not classify a Japanese comment as obvious just because the adjacent code
is visible. First check whether it records *why* the code exists, what data
condition it handles, or how the result should be interpreted.
**If a single file would lose many Japanese comments under §4.3, stop and ask
the user to confirm the deletion policy before proceeding.**

### 4.4 Flag, do not guess

Apply this rule when **either** of the following holds:

- The comment's meaning is unclear.
- The comment and the surrounding code are inconsistent and you cannot tell
  which one reflects the intended behavior (for example, the mismatch may be
  hiding a bug fix in the code, or a stale comment, or a comment about a
  different code path).

In either case, **do not silently translate or rewrite based on a guess**.
Keep the original line and add a review marker.

```python
# 元コードと同一条件
# TODO(review): meaning unclear — author to confirm before translation.
```

```python
# 行ごとにベースラインを差し引く
for col in range(image.shape[1]):
    ...
# TODO(review): comment says "row" but loop iterates columns — author to
# confirm which is correct before the comment is rewritten.
```

A confidently worded but incorrect translation or rewrite is worse than an
untranslated or out-of-sync Japanese comment — it misleads reviewers and
corrupts the documentation silently.

---

## 5. AI-Assisted Editing

AI may draft or translate comments and docstrings, but technical correctness
must be verified by the author. Do not accept AI-generated wording for
instrument behavior, physical interpretation, or algorithm rationale until it
has been checked against the code and the author's domain knowledge.

If AI is used in preparing the JOSS submission, disclose that use in the JOSS
paper or submission materials per current JOSS guidelines.

---

## 6. Exceptions

### 6.1 `PLUGIN_INFO` dictionaries

`PLUGIN_INFO` in each GUI plugin file is parsed by `Main.py` via
`ast.literal_eval()`. Function calls such as `_("...")` cause a parse error.
Keep values as plain string literals; do not wrap with `_()`. These values
are standardized in English.
Do not insert `\n` in `PLUGIN_INFO["description"]` only to control launcher
line wrapping. Keep descriptions as natural text; `Main.py` and the UI layout
are responsible for wrapping. Splitting a Python string literal across source
lines is fine as long as it does not add an actual newline to the value.

```python
# Correct
PLUGIN_INFO = {
    "name": "Plot Profiler",
    "description": "Extract AFM height profiles through an interactive UI."
}

# Wrong — literal_eval will crash
PLUGIN_INFO = {
    "name": _("Plot Profiler"),
    "description": _("Extract AFM height profiles through an interactive UI.")
}
```

### 6.2 UI string literals

UI-facing strings (button labels, window titles, status messages, tooltips,
error dialogs) are managed by `gettext` / `_()` and translated through the
`.po` / `.mo` pipeline. Do not apply the bilingual comment rule to them and do
not rewrite them unless the UI text itself is being intentionally updated.
Do not insert `\n` in the middle of a sentence only to control visual line
wrapping in translated `msgstr` entries. Different languages wrap naturally at
different positions, so UI layout should handle wrapping. Use explicit `\n`
only when the source text has a meaningful paragraph or line break that should
appear in the UI.

Localize operational UI strings, but keep scientific and reporting strings
fixed in English. Buttons, menus, tabs, checkboxes, ordinary labels, tooltips,
status text, and error or warning dialogs should usually be wrapped with `_()`.
Plot text such as heatmap, histogram, and profile titles, axis labels, legends,
and colorbar labels should stay in English and should not be wrapped with `_()`.
Classify strings by their eventual display use, not only by the immediate call
that contains the literal. Strings assigned to variables, tuples, lists, dicts,
or helper return values must also remain untranslated if they are later passed
to Matplotlib plot APIs such as `ax.set_title()`, `ax.set_xlabel()`,
`ax.legend()`, or `colorbar.set_label()`. Do not rely only on direct patterns
such as `ax.set_title(_("..."))`; trace indirect flows such as
`sub_titles = (...)` followed by `ax.set_title(sub_titles[i])`.
CSV headers, exported result labels, analysis table column names such as the
GUI03 main-window results table, internal data keys, and scientific units such
as `nm`, `µm`, `px`, `rad`, and `degree` are fixed English strings. When a
localized label is mixed with a fixed unit, wrap only the label and concatenate
the unit, for example `_("Scale") + " (µm)"`.

Do not split a translatable sentence into small `_()` fragments around fixed
English terms. Keep the full sentence as one gettext message and insert fixed
terms with named placeholders so translators can choose natural word order.
This is especially important for logs, warnings, tooltips, and usage guidance.

```python
# Translation targets — leave as-is
self.title(_("AFM Height Histogram"))
btn = ttk.Button(self, text=_("Load File"))
messagebox.showerror(_("Error"), _("File not found."))

# Mixed localized label and fixed scientific unit
scale_label = _("Scale") + " (µm)"

# Fixed mode names inside a translated sentence
msg = _(
    "Use {density} or {percent} when group sizes differ substantially."
).format(density="density", percent="percent")

# Wrong — too fragmented for natural translation
msg = _("Use ") + "density" + _(" or ") + "percent" + _(" when group sizes differ.")

# Scientific/reporting strings — leave as fixed English
sub_titles = ("Original", "Calibrated", "Binarized", "Skeletonized")
ax.set_title(sub_titles[i])
ax.set_xlabel("Scale (µm)")
writer.writerow(["fiber_id", "length_um", "mean_height_nm"])
```

### 6.3 Internal state keys

Fixed English-string keys used for internal state comparison (`"pending"`,
`"running"`, `"analyzed"`, etc.) must not be translated and must not be wrapped
with `_()`. They are identifiers, not user-visible text.

---

## 7. GUI Plugin File Conventions

These rules apply to Python GUI plugin files under `guis/`. They are intended
to keep the software maintainable for JOSS submission, routine code review, and
future GUI additions. `AGENTS.md` itself is only an instruction file for AI
editing agents; it is not part of the JOSS software submission.

### 7.1 Standard top-level order

Use the same top-level structure in every GUI plugin:

1. Encoding comment, only if the file already uses one or needs one.
2. Module docstring.
3. `PLUGIN_INFO` and its literal-evaluation warning comments.
4. Imports, grouped as described in section 7.2.
5. Module constants and internal state keys.
6. Small module-level helper functions or data classes.
7. Main `App` class.
8. Dialog or secondary window classes.
9. `main() -> None`.
10. `if __name__ == "__main__": main()`.

Do not move large classes or helper blocks only for cosmetic reasons unless
the user explicitly asks for a GUI consistency pass. Prefer small, reviewable
diffs.

### 7.2 Import grouping

Group imports in this order, using short section comments when the file is
large enough that they improve scanning:

```python
# ===== Standard library =====

# ===== Numerical / scientific libraries =====

# ===== GUI libraries =====

# ===== Plotting libraries =====

# ===== Project libraries =====
```

Within each group, keep imports simple and predictable. Avoid mixing standard
library imports with third-party or project imports. Keep `matplotlib.use("TkAgg")`
immediately after `import matplotlib` and before importing `matplotlib.pyplot`.

Do not reorder imports if doing so could introduce side effects or if the file
contains intentional local imports. Local imports used to avoid optional
dependencies, heavy startup cost, or circular imports may remain local, but add
a short English comment when the reason is not obvious.

### 7.3 `PLUGIN_INFO`

Place `PLUGIN_INFO` immediately after the module docstring and before imports.
This makes plugin metadata easy to review and keeps all launcher-facing
metadata in a consistent location.

`PLUGIN_INFO` must remain a literal dictionary that can be parsed by
`ast.literal_eval()` in `Main.py`. Do not wrap values in `_()`, do not compute
values dynamically, and do not import modules before defining it unless there
is a strong reason approved by the user.

Prefer English values for `name` and `description`, because the launcher
metadata is part of the reviewer-facing software surface. Keep descriptions
concise: state what the GUI does, what input it expects, and what output or
inspection workflow it provides.
Do not insert `\n` in `description` only to tune launcher wrapping; use actual
newlines only for meaningful line breaks.

### 7.4 Shared GUI helpers and constants

Prefer project-level helpers from `lib.ui_tools` for behavior shared across
GUI plugins, such as:

- window sizing via `apply_window_size`
- ttk theme setup via `setup_ttk_theme`
- Matplotlib defaults via `setup_matplotlib_style` and `PLOT_FS_DEFAULTS`
- plot export via `save_figure_with_dialog`
- tooltip behavior via `ToolTip`
- log saving via `save_text_widget_log`
- common unit strings such as `UNIT_MICROMETER`
- common image display limits such as `DEFAULT_VMIN`, `DEFAULT_VMAX`, and
  `compute_auto_vrange`

When adding a new GUI, reuse these helpers before introducing another local
implementation. If a new helper would be useful to more than one GUI file, ask
before touching `lib/ui_tools.py`.

### 7.5 Initialization pattern

Keep GUI initialization predictable:

1. Call `super().__init__()` first in `App.__init__`.
2. Set the window title.
3. Apply Matplotlib defaults.
4. Apply or capture the ttk theme background.
5. Apply the window size.
6. Initialize state variables.
7. Build widgets.
8. Start any polling loops or deferred loading.

If an existing GUI uses a different order for a functional reason, preserve
that behavior and add a short comment only when the reason is non-obvious.

### 7.6 Entry point pattern

Define a typed entry point in each GUI plugin:

```python
def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
```

Do not create Tk windows at import time. The launcher scans plugin files and
may inspect metadata without launching the GUI.

### 7.7 Naming and compatibility

Use clear English class, function, and constant names for new code. Preserve
existing public names, filenames, plugin names, serialized keys, and internal
state strings unless the user explicitly asks for a compatibility-breaking
rename.

If an existing name contains a typo but may be referenced by saved data,
documentation, scripts, or the launcher, flag it as a compatibility issue
instead of silently renaming it.

### 7.8 Comments, docstrings, and UI text in GUI files

Apply the commenting and docstring rules in sections 1 through 6 to GUI files.
For GUI-specific code:

- Keep module, class, and public method docstrings reviewer-readable in English.
- Add Japanese lines only where they preserve domain knowledge or maintainer
  context under the tiered bilingual policy.
- Do not translate or rewrite UI strings merely while reorganizing code.
- Do not wrap internal state keys or `PLUGIN_INFO` values with `_()`.
- If Japanese text appears garbled, do not guess. Re-read with UTF-8 or cp932,
  then flag unclear text with `TODO(review)` if it cannot be safely recovered.

### 7.9 New GUI checklist

When creating a new GUI plugin, ensure that:

- the file lives under `guis/` and has a module-level `PLUGIN_INFO`
- `PLUGIN_INFO` is a literal dictionary parseable by `ast.literal_eval()`
- imports follow the standard grouping
- GUI launch is guarded by `if __name__ == "__main__"`
- common behavior uses `lib.ui_tools` helpers where applicable
- operational user-facing strings use `_()` per §6.2; plot text, exported
  labels, scientific units, `PLUGIN_INFO` values, and internal state keys
  stay fixed English
- internal state keys remain fixed English identifiers
- outputs and input expectations are documented in the module docstring
- long-running work does not block the Tk event loop
- logs, warnings, and errors are visible to the user when analysis fails

### 7.10 Verifying GUI and visual changes

A GUI change is not verified until the *rendered* result has been confirmed
through the *real* run path. Model values and in-process shortcuts routinely
disagree with what the user sees, so treat them as hints, not proof.

- **Drive the real run path, not `App(); app.update()`.** A manual
  `update()`/`update_idletasks()` forces geometry to settle synchronously and
  hides event-timing and window-sizing races that only appear under
  `mainloop()` or the launcher (`Main.py --run-plugin <module>`). Verify
  layout/resize/maximize behavior by actually running the app (a subprocess
  launch, or an `App()` with a real `mainloop()` plus an `after()` probe).
- **Confirm the rendering, not just the data model.** A widget's data model
  can report the intended state while the canvas draws something else. Check
  the draw state or the pixels, not only the model. Concrete trap: tksheet's
  `Sheet.column_width(<int col>, width, redraw=True)` updates `col_positions`
  but does **not** run the full redraw that resets the canvas `scrollregion`,
  so a widened column is painted only up to the stale scrollregion and leaves
  a blank strip; call `Sheet.refresh()` afterwards. Reading
  `get_column_widths()` alone would have (and did) falsely report "no gap".
- **Believe a user-reported visual defect.** If the user says a margin,
  misalignment, or artifact is present and a check disagrees, the check is
  suspect first — a hand-written pixel/geometry analyzer can misclassify
  borders or gridlines. Re-examine the actual output before re-asserting that
  it is fixed.
- **Scope any screen capture to the target window.** Foreground-then-grab can
  capture whatever window is in front (including unrelated private content).
  Capture the specific window handle (e.g. Windows `PrintWindow`) and confirm
  it is the intended app window.

---

## 8. Project Architecture and Data Contracts

These project-level contracts prevent local edits from breaking cross-GUI
workflows. Where a contract also exists in code, **the code is the source of
truth**: `lib/bundle_schema.py` defines the `.b2z` contract and
`lib/pipeline.py` defines `ProcParams` and the stage pipeline. If this
document and the code disagree, trust the code and update this document in
the same change.

### 8.1 Preprocessing pipeline (`lib/pipeline.py`)

The preprocessing pipeline is implemented in `lib/pipeline.py`.
`guis/GUI01_Image_Preprocessor.py` and `cli.py process` both call
`lib.pipeline.process_file`, so the GUI and CLI entry points produce
identical analysis outputs for the same input and parameters. Each input AFM
file is processed in this order:

```text
raw AFM text/CSV  -> afm_io.load_afm_text()
Gwyddion .gwy     -> gwy_io.load_gwy_image()
    -> ProcessedImage
    -> BGCalibrator
    -> Segmenter
    -> Skeletonizer
    -> KinkDetector
    -> .b2z bundle + _param.json
```

`process_file` dispatches by extension: `.gwy` inputs load through
`lib/gwy_io.py` (selecting one channel), everything else loads through
`lib/afm_io.py`. Both yield a nm height array and an optional scan size, so the
stages downstream are identical regardless of input format.

Keep background calibration, segmentation, skeletonization, and kink detection
as separate responsibilities.

Analysis parameters are defined by the `ProcParams` dataclass in
`lib/pipeline.py` and saved beside the bundle as `<input_stem>_param.json`.
Field names are serialized verbatim into that file, so **every `ProcParams`
field name is frozen** — a rename silently breaks parameter reload. The
authoritative field list is the dataclass itself; do not maintain copies of it
in documentation.

`BGCalibrator` (in `lib/bg_calibrator.py`; the historical name
`BG_Calibrator_shimadzu` remains importable through a compatibility shim)
supports four `bg_method` values:

| `bg_method` | Description |
|---|---|
| `inpaint` | Masks fiber candidates via gradient histogram and ridge detection, then estimates background with inpainting. |
| `tophat` | Fast morphological top-hat correction without masking. |
| `spline1d` | 1D B-spline interpolation per row or column; effective for line-noise-dominant images. |
| `spline2d` | 2D B-spline to estimate a smooth background surface. |

### 8.2 `.b2z` bundle contract

GUI01 currently saves one `<input_stem>.b2z` bundle and one
`<input_stem>_param.json` file per analyzed input. Do not restore the legacy
workflow that emitted multiple standalone `.npy` files unless the user
explicitly requests a format migration.

The executable contract — required and optional keys, array shapes, units,
coordinate convention, and the bundle format version — is defined in
`lib/bundle_schema.py` (`REQUIRED_BUNDLE_KEYS`, `OPTIONAL_BUNDLE_KEYS`,
`TRACKING_BUNDLE_KEYS`, `validate_bundle`, `BUNDLE_FORMAT_VERSION`,
`SUPPORTED_BUNDLE_VERSIONS`). Read the key list, shapes, and units there;
this document intentionally does not duplicate them. The pipeline validates
before saving, `lib/measure.py` validates at load time, and `cli.py validate`
checks bundles on demand. Bump `BUNDLE_FORMAT_VERSION` (recorded in vlmeta as
`version`) only when keys, shapes, or units change.

GUI04 requires the keys listed in `TRACKING_BUNDLE_KEYS` (`calibrated`,
`skeletonized`, `bp`, `ep`, `kp`, `dp`, `ka`).

If a `.b2z` key, shape, unit, or meaning changes, ask before touching
additional files and keep at least these files consistent:

- `lib/bundle_schema.py` (schema, format version, and validation rules)
- `lib/pipeline.py`
- `lib/measure.py`
- `guis/GUI01_Image_Preprocessor.py`
- `guis/GUI02_PlotProfiler.py`
- `guis/GUI03_Fiber_Height_Histogram.py`
- `guis/GUI04_Tracking_fiber.py`
- `lib/blosc2_io.py`
- `README.md` / `README.ja.md`

### 8.3 GUI-specific data expectations

- GUI02 accepts `.b2z`, `.npy`, `.csv`, `.txt`, and Gwyddion `.gwy` inputs. For
  `.b2z`, it reads the `calibrated` key and extracts line profiles with
  `skimage.measure.profile_line`. For `.gwy` it reads the selected channel
  through `lib/gwy_io.py` (auto-selected topography by default; a channel
  dropdown appears for multi-channel files).
- GUI03 expects GUI01 `.b2z` bundles, reads `calibrated` and `skeletonized`, and
  compares height distributions from skeleton pixels across grouped datasets.
- GUI04 expects GUI01 `.b2z` bundles, reconstructs individual `Fiber` instances
  through `FiberTrackingImage`, and preserves workflows for fiber lists, full
  AFM view, individual fiber view, profiles, height filtering, figure export,
  and CSV export.

### 8.4 Long-running GUI work

Analysis and file loading must not block the Tk main loop. Run long operations
in a worker thread, pass results or log events through `queue.Queue`, and poll
from the main thread with `after()`. Prefer `lib/ui_tools.py` helpers such
as `drain_ui_queue` for shared queue-draining behavior.

### 8.5 Renames and imports

Do not rename `lib/` modules casually. If a module filename or public import
path changes, check at least `lib/` imports, `guis/*.py`, `README.md`, and
`README.ja.md`.

`Main.py` launches each plugin through its `--run-plugin` subcommand, which
imports the plugin module in a worker thread behind a splash window. Frozen
PyInstaller builds must keep using this subcommand because the PyInstaller
bootloader does not honor `-c` or `-m`. Keep libraries that are heavy to
import and needed only by a specific feature (e.g. lmfit, pandas) as
function-local imports so plugin startup stays fast. The `gwyfile` package
(read `.gwy` files in `lib/gwy_io.py`) follows the same rule: it is imported
inside the functions that open a `.gwy`, so text-only workflows and plugin
startup never load it.

### 8.6 Build and dependency helpers

`check.py` scans project imports and regenerates `requirements.txt`. `build.py`
performs PyInstaller-oriented import checks, spec generation, build execution,
and copies `guis/`, `lib/`, `locale/`, and `assets/` into `dist/Main/`.
Distribution should treat the entire `dist/Main/` folder as the deliverable.

### 8.7 lib module APIs

Do not rename the public classes and functions listed below without updating
all call sites in `guis/`, `Main.py`, `cli.py`, `tests/`, and `lib/` imports.

| Module | Public API | Notes |
|---|---|---|
| `afm_io.py` | `load_afm_text`, `load_afm_image`, `detect_afm_format`, `read_scan_size`, `AfmTextFormat`, `ScanSize`, `FORMAT_KINDS` | Loads AFM text/CSV as NumPy array; auto-detects header rows, column count, and encoding. `detect_afm_format` reports the detected layout without loading the data. `read_scan_size` reads the physical scan size from the instrument header (Shimadzu `SizeX`/`SizeY`) when present. `load_afm_image` and `read_scan_size` dispatch `.gwy` paths to `gwy_io.py` (importing `gwyfile` only there), so callers handle text and `.gwy` inputs uniformly. |
| `bg_calibrator.py` | `BGCalibrator` | See §8.1 for `bg_method` options. |
| `bg_calibrator_shimadzu.py` | `BG_Calibrator_shimadzu` | Compatibility shim; alias of `BGCalibrator`. Do not add new code here. |
| `blosc2_io.py` | `save_blosc2`, `load_blosc2`, `save_bundle`, `load_bundle` | |
| `bundle_schema.py` | `validate_bundle`, `BUNDLE_FORMAT_VERSION`, `SUPPORTED_BUNDLE_VERSIONS`, `REQUIRED_BUNDLE_KEYS`, `OPTIONAL_BUNDLE_KEYS`, `TRACKING_BUNDLE_KEYS`, `SPATIAL_CALIBRATION_KEY`, `SCAN_SIZE_SOURCES`, `make_spatial_calibration`, `scan_size_um_from_meta` | Executable `.b2z` contract (§8.2): keys, shapes, units, coordinate convention, format version, and the optional `spatial_calibration` vlmeta entry (scan size + source). Depends only on NumPy. |
| `fiber.py` | `Fiber` | Immutable dataclass holding height, length, kink points, and endpoints per fiber. |
| `fiber_connector.py` | `ConnectParams`, `connect_fiber_fragments`, `angle_between_three_points` | Reconnects skeleton fragments split at crossings/branches into whole fibrils by local position/direction/height continuity, rebuilding one `Fiber` per fibril (features recomputed via `KinkDetector`). Used by GUI04's optional fiber-connection mode via `measure_bundle(connect_fibers=True)`. Sequential (order-dependent), so not parallelized. |
| `fiber_tracking_image.py` | `FiberTrackingImage` | GUI04 data container; builds `Fiber` instances from a `.b2z` bundle. |
| `gwy_io.py` | `GWY_EXT`, `GwyChannel`, `GwyImage`, `list_gwy_channels`, `load_gwy_image`, `read_gwy_scan_size`, `select_default_channel`, `is_gwy_path` | Reads Gwyddion native `.gwy` files (binary, multi-channel). `load_gwy_image` returns the selected channel's height matrix in nm plus its scan size (µm); `select_default_channel` auto-selects the topography/height channel, overridable by id or title. Imports the optional `gwyfile` package lazily inside its functions; reuses `afm_io.ScanSize`. |
| `imp_tools.py` | `branchedPoints`, `endPoints`, `tracking`, `convert_track_to_distance` | |
| `kink_detector.py` | `KinkDetector` | |
| `measure.py` | `FiberStats`, `MeasureResult`, `compute_fiber_stats`, `load_tracking_image`, `measure_bundle`, `read_scan_size_from_bundle`, `write_fiber_csv`, `all_pixel_height`, `skeleton_height_values`, `write_heights_csv`, `TRACKING_BUNDLE_KEYS`, `FIBER_CSV_COLUMNS` | GUI-independent fiber measurement shared by GUI03, GUI04, and `cli.py measure` / `heights`; keeps GUI and CLI statistics identical. `measure_bundle` resolves the pixel size per axis (X from image width, Y from image height) so rectangular scans and non-square pixel grids are measured correctly; it defaults both axes to the bundle's recorded scan size when `scale_um` / `scale_y_um` are omitted, and a single `scale_um` keeps a square scan. |
| `pipeline.py` | `ProcParams`, `STAGE_KEYS`, `build_stages`, `PipelineStages`, `process_file`, `PipelineResult`, `merge_params_dict`, `validate_params`, `existing_min_set`, `bundle_path_for`, `param_path_for` | GUI-independent preprocessing driver shared by GUI01 and `cli.py process`; owns `ProcParams` (field names frozen, §8.1) and stage construction. |
| `processed_image.py` | `ProcessedImage` | Image and result container for the GUI01 pipeline. |
| `segmenter.py` | `Segmenter` | |
| `skeletonizer.py` | `Skeletonizer` | |
| `translator.py` | `_`, `set_language`, `current_language` | |
| `ui_tools.py` | See §7.4 | Shared GUI helpers; prefer these over local re-implementations. |

### 8.8 Translation catalog maintenance

Translation uses `gettext`. Source strings wrapped in `_()` are extracted into
`locale/<language>/LC_MESSAGES/messages.po`; compiled output is `messages.mo`.
Do not edit `.mo` files directly — they are compiled from `.po`.
Compiled `.mo` files are version-controlled so fresh clones get working
translations without Babel. After editing a `.po`, run
`pybabel compile -d locale` and commit the regenerated `.mo` together with the
`.po`; `tests/test_translations.py` fails when a `.mo` is stale.
`prepare_translate_catalogs.py` also compiles the catalogs as its final step.
In PO syntax, an entry whose `msgstr ""` is followed by translated continuation
string lines is not empty. When filling empty translations, treat those entries
as existing translations and leave them unchanged.
Do not insert `\n` in the middle of a translated sentence only to control
visual wrapping. Preserve source-required line breaks, and use explicit `\n`
only for meaningful UI paragraphs or line breaks.

When UI strings or `PLUGIN_INFO` descriptions are added or changed, refresh the
catalogs through the project script, which is the canonical entry point:

```powershell
python prepare_translate_catalogs.py
```

It runs `pybabel extract`, injects each `PLUGIN_INFO["description"]` literal into
`locale/messages.pot`, runs `pybabel update`, removes obsolete `#~` entries, and
finally `pybabel compile`. The injection step is essential: `PLUGIN_INFO`
descriptions are plain literals and are deliberately not wrapped in `_()`
(§6.1), so a bare `pybabel extract` never sees them. Running the raw Babel
commands below on their own drops those descriptions from `messages.pot`,
`pybabel update` then marks the matching `.po` entries obsolete (`#~`), the
compiled `.mo` loses them, and the launcher hover text falls back to the
untranslated Japanese source. The script does not fill `msgstr`, so commit or
back up the catalogs first when you want to keep prior translations for
reference. Use the raw commands only to inspect the individual steps it performs:

```powershell
pybabel extract -F babel.cfg -o locale/messages.pot .
pybabel update -i locale/messages.pot -d locale
pybabel compile -d locale
```

To add a new language:

```powershell
pybabel init -i locale/messages.pot -d locale -l <language_code>
```

## 9. Summary

| Item | Rule |
|---|---|
| Canonical agent rules file | This file (`AGENTS.md`); `CLAUDE.md` only imports it. Never let them diverge. |
| Primary review language | English |
| Bilingual order | English first, Japanese second |
| Module / class / public-function docstring | Bilingual default on summary + Parameters/Returns/Attributes; Raises/Notes bilingual only when it adds domain context |
| Private function docstring | Summary line bilingual; body bilingual for algorithm / physical / instrument-specific notes, English only for routine notes |
| New / rewritten inline comments | English required; add Japanese only for domain notes |
| Windows `.bat` comments | ASCII-only executable files; English `REM` comments only; put Japanese explanations in Markdown documentation |
| `.sh` comments | Same intent-focused policy as Python comments; for setup/launch scripts, use concise English-first comments with Japanese directly below for purpose, prerequisites, environment assumptions, failure-prone steps, and non-obvious command choices |
| Existing Japanese inline comments | Default: keep and translate (§4.1). Other actions per §4.2–4.4. |
| Bilingual format | English line `#`, Japanese line `#` directly below, no blank line |
| Docstring headings | English NumPy-style only |
| Type info in docstring | Do not repeat type hints unless clarification is needed |
| Global delete-and-regenerate | Forbidden |
| Mass deletion of Japanese comments in one file | Stop and confirm with user |
| Unclear comments | Flag with `TODO(review)`; never guess |
| Comment incomplete vs. code (code does more than comment says) | Extend the comment under §4.2; preserve original wording's intent |
| Comment contradicts code (says different thing than code does) | Flag with `TODO(review)` under §4.4; do not rewrite to match code unless user explicitly says the code is authoritative |
| `PLUGIN_INFO` | Plain English string literals; never wrap with `_()`; do not add `\n` to `description` only for launcher wrapping |
| UI strings via `_()` | Localize operational UI strings; keep plot text, result exports, analysis table columns, data keys, and scientific units fixed in English |
| Translated line breaks | Do not insert `\n` inside a sentence only for visual wrapping; use explicit line breaks only for meaningful UI paragraphs or source-required breaks. |
| GUI plugin file order | Module docstring, `PLUGIN_INFO`, grouped imports, constants, helpers, `App`, dialogs, `main()` |
| GUI imports | Group as standard library, numerical/scientific, GUI, plotting, project libraries |
| GUI entry point | Use `main() -> None` and guard GUI launch behind `if __name__ == "__main__"` |
| Shared GUI helpers | Prefer `lib.ui_tools` / `lib/ui_tools.py` for common GUI behavior. |
| Verifying GUI/visual changes | Confirm the rendered result via the real run path (not `app.update()`, not the data model); believe user-reported visual defects; scope screen captures to the app window (§7.10). |
| `.b2z` bundle contract | Defined in `lib/bundle_schema.py` (code is source of truth); coordinate dependent files per §8.2. |
| Long-running GUI work | Use worker threads, `queue.Queue`, and Tk `after()` polling; do not block the main loop. |
| `ProcParams` field names | Frozen (serialized verbatim into `_param.json`); authoritative list is the dataclass in `lib/pipeline.py`. |
| `lib/` module public APIs | Do not rename classes/functions in §8.7 without updating all call sites. |
| Translation catalogs | Refresh with `python prepare_translate_catalogs.py` (keeps `PLUGIN_INFO` descriptions; a bare `pybabel extract/update` drops them and obsoletes the entries); never edit `.mo` files directly (§8.8). |
| README pair | `README.md` ↔ `README.ja.md` stay synchronized in both directions, including translation of the edited passage. |
| Destructive Git operations | Forbidden unless explicitly requested; `git restore` of files corrupted by your own edit is allowed. |
