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
  `.b2z` contract files in §8.2, translation catalogs in §8.8, the changelog
  entry in §8.11) count as part of the requested change once the user approves
  the edit that triggers them.
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
- Never write an unverified statement into documentation (`docs/`, the
  READMEs, `CHANGELOG.md`, commit messages, docstrings). A statement about
  what the code does is verified by reading that code; a number or an
  outcome ("found", "separates", "identical", "does not change") is verified
  by running the computation that produces it. A reason you supplied yourself
  — why a threshold works, what a stripe orientation does — is an inference,
  not a verification, however plausible. When a statement cannot be verified,
  do not write it: keep the existing text and mark it `TODO(review)` (§4.4
  applies to documents as well as comments), or ask the user. When reporting
  a documentation change, state for each statement whether it was measured
  (with the script and its output), read in code (with the location), or is
  still unverified; an unverified one is reported, not written.
- Comments, docstrings and the explanatory documents (`docs/algorithms*.md`,
  `docs/gui04_measurements*.md`) describe the code as it is now. Do not
  describe methods the code used before, change history ("up to 1.0.0 …",
  "previously …", 「従来は…」), or what a prototype did; that history belongs
  in `CHANGELOG.md` and Git. State a design reason directly ("moving points
  onto the smoothed track would round real corners"), not as the story of an
  earlier version. Compatibility behaviour the current code still executes —
  retired `bg_method` aliases, removed-method messages, the handling of older
  bundle formats and CSV column sets — is described as current behaviour.
  Results on particular data (the bundled scans, the synthetic suite) belong
  in `docs/validation*.md`, not in comments or the explanatory documents.
- `README.md` and `README.ja.md` are a synchronized pair. When editing either
  one, apply the same corresponding edit to the other. Translating the edited
  passage into the other file's language is part of this synchronization and
  does not require a separate translation request.
- Do not run Git commands that discard or rewrite committed history or
  uncommitted work (`reset --hard`, `push --force`, `clean`, `rebase`, branch
  deletion, history filtering) unless the user explicitly requests that
  specific operation. Exception: restoring files corrupted by your own edit
  (e.g., `git restore <file>`) under the mojibake rule above is allowed.
- Delete files and folders only by sending them to the recycle bin with
  `.venv\Scripts\python.exe scripts\trash.py PATH ...` (`scripts/trash.py`;
  it refuses paths outside the repository), so every deletion can be undone.
  Commands that delete irreversibly — `rm`, `rmdir`, `find -delete`,
  `Remove-Item`, `del`, `rd` — are denied in `.claude/settings.json`. When a
  deletion is denied, do not reach the same result another way (Python's
  `shutil.rmtree` or `os.remove`, a different shell): use `scripts/trash.py`,
  or ask. Code that prunes its own files does the same through
  `trash.send_to_trash`, as `scripts/bundle_cache.py` does.
- Write a multi-line commit message to a file under `.tmp/` and pass it with
  `git commit -F .tmp/commit_msg.txt`. Never hand-quote one inline: PowerShell
  needs a here-string (`@'` … `'@`) and POSIX `sh` needs a here-document
  (`<<'EOF'` … `EOF`), the two are not interchangeable, and an agent that runs
  the wrong form for the shell it is in leaves the delimiter in the message.
  Nothing fails: the commit succeeds with `@` as its subject line and the real
  summary pushed to line 2, and only a history rewrite — which the rule above
  forbids without the user asking for it — can fix it afterwards. The `-F`
  form is identical in both shells. `.githooks/commit-msg` blocks a message
  that carries such a delimiter; write the message properly rather than
  passing `--no-verify`.
- Do not use personal information (email addresses, real names, etc.) obtained from system context in examples, output, or generated code. Use placeholder values (e.g., `your@email.com`, `Your Name`) instead.
- Do not display the user's local absolute paths (anything outside the
  repository, such as the user profile directory) in chat responses.
  Repository-relative paths are fine.
- A request to find, list or check problems — or to confirm there are none —
  is an exhaustive review, not a search of the places you judge suspicious.
  Fix the scope from the request first ("the software" means `afm_nanofiber_analyzer/`, `guis/`,
  `cli.py` and `Main.py`, with `--outputs`) and build the item list from the
  code with `scripts/audit_ledger.py init`; name anything left out with
  `--exclude PATH::REASON`. Mark every item (`mark`, with evidence a reader can
  open), give subagents item ids rather than topics, confirm a subagent's
  finding against the code before marking it, and report from `report`,
  quoting its coverage line. While items are unchecked, never write that the
  list is complete or that there are no problems. A review that leaves part of
  the scope unexamined and does not say so reads as complete, and each later
  review then surfaces problems the earlier one never looked for. In Claude
  Code, `.claude/hooks/audit_prime.py` injects this procedure and
  `.claude/hooks/audit_guard.py` blocks a reply of an open audit that lacks the
  current coverage line.

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

The same rule governs documents. When a passage of `docs/`, a README or
`CHANGELOG.md` is unclear, contradicts the code, or states a result you
cannot reproduce, keep it and add an HTML comment
`<!-- TODO(review): ... -->` naming what is unverified, rather than
replacing it with an explanation you reasoned out. See the Editing Rules
bullet on unverified statements.

---

## 5. AI-Assisted Editing

AI may draft or translate comments and docstrings, but technical correctness
must be verified by the author. Do not accept AI-generated wording for
instrument behavior, physical interpretation, or algorithm rationale until it
has been checked against the code and the author's domain knowledge.

If AI is used in preparing the JOSS submission, `paper.md` must carry an
`AI usage disclosure` section; it is an item of the JOSS review checklist, and
the JOSS AI usage policy
(<https://joss.readthedocs.io/en/latest/policies.html>) requires it to state:

1. **Tools and where they were applied** — each AI system with its version,
   and which parts of the submission it was used on (code, documentation,
   manuscript).
2. **Scope of assistance** — what kind of help it gave, for example code
   generation, refactoring, test scaffolding, translation, editorial review,
   or manuscript drafting.
3. **Human verification** — that the authors reviewed, modified, and
   validated all AI-generated content and made the primary architectural and
   design decisions.

If no AI was used, the section says so explicitly. JOSS treats an incomplete
disclosure as an ethics issue, not a formatting one. An agent working with a
tool or model version the section does not yet name reports that to the user
rather than editing `paper.md` unasked.

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

Prefer project-level helpers from `afm_nanofiber_analyzer.ui_tools` for behavior shared across
GUI plugins, such as:

- window sizing via `apply_window_size`
- ttk theme setup via `setup_ttk_theme`
- Matplotlib defaults via `setup_matplotlib_style` and `PLOT_FS_DEFAULTS`
- plot export via `save_figure_with_dialog`
- tooltip behavior via `ToolTip`, and per-column tooltips on Treeview headings
  via `HeadingToolTip`
- log saving via `save_text_widget_log`
- mouse-wheel scrolling of a canvas via `bind_mousewheel_scroll`
- an embedded Matplotlib pan/zoom toolbar via `build_pan_zoom_toolbar`
- common unit strings such as `UNIT_MICROMETER`
- common image display limits such as `DEFAULT_VMIN`, `DEFAULT_VMAX`, and
  `compute_auto_vrange`
- the image a GUI shows for a bundle via `read_height_image` (the `calibrated`
  array, and `skeletonized` when present, which `compute_auto_vrange` takes as
  its mask); GUI03's preview and GUI05's thumbnails both call it, so the two
  draw the same pixels over the same color range. It lives here and not in
  `afm_nanofiber_analyzer/measure.py`, because adding a function there that other code calls
  marks every measurement recorded on that module as stale (§8.15)
- the X/Y scale-entry contract via `scale_xy_um` (a blank Y follows X, so the
  scan is square) and `extent_scales_xy_and_unit` (X takes the width scale and
  Y the height scale, so a rectangular scan draws with the right aspect)
- a placeholder ghost overlaid on an entry via `refresh_entry_placeholder`

When adding a new GUI, reuse these helpers before introducing another local
implementation. If a new helper would be useful to more than one GUI file, ask
before touching `afm_nanofiber_analyzer/ui_tools.py`.

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
- common behavior uses `afm_nanofiber_analyzer.ui_tools` helpers where applicable
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
truth**: `afm_nanofiber_analyzer/bundle_schema.py` defines the `.b2z` contract and
`afm_nanofiber_analyzer/pipeline.py` defines `ProcParams` and the stage pipeline. If this
document and the code disagree, trust the code and update this document in
the same change.

### 8.1 Preprocessing pipeline (`afm_nanofiber_analyzer/pipeline.py`)

The preprocessing pipeline is implemented in `afm_nanofiber_analyzer/pipeline.py`.
`guis/GUI01_Image_Preprocessor.py` and `cli.py process` both call
`afm_nanofiber_analyzer.pipeline.process_file`, so the GUI and CLI entry points produce
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

`process_file(row_range=...)` analyzes only a half-open range of scan lines,
writing to `<input_stem>_r<start>-<stop>.b2z` (`row_range_suffix`) and recording
the range in the bundle's `source_region` vlmeta entry. This is not the same as
analyzing the whole image and ignoring part of it: stages take thresholds from
statistics over the whole array, so excluding disturbed scan lines changes what
the remaining lines are compared against. `scan_size_um` and the input header
always describe the *whole* scan; `process_file` scales the recorded Y size so
the stored pixel size is identical to the uncropped run's on both axes, and a
fiber measures the same either way. GUI01 exposes this as the scan-line-range
column and `cli.py process` as `--rows`.

`process_file` dispatches by extension: `.gwy` inputs load through
`afm_nanofiber_analyzer/gwy_io.py` (selecting one channel), everything else loads through
`afm_nanofiber_analyzer/afm_io.py`. Both yield a nm height array and an optional scan size, so the
stages downstream are identical regardless of input format.

Keep background calibration, segmentation, skeletonization, and kink detection
as separate responsibilities.

Analysis parameters are defined by the `ProcParams` dataclass in
`afm_nanofiber_analyzer/pipeline.py` and saved beside the bundle as `<input_stem>_param.json`.
Field names are serialized verbatim into that file, so **every `ProcParams`
field name is frozen** — a rename silently breaks parameter reload. The
authoritative field list is the dataclass itself; do not maintain copies of it
in documentation.

`BGCalibrator` (in `afm_nanofiber_analyzer/bg_calibrator.py`; the historical name
`BG_Calibrator_shimadzu` remains importable through a compatibility shim)
supports three `bg_method` values. Retired spellings are listed in
`bg_calibrator.BG_METHOD_ALIASES` and translated by `canonical_bg_method`, so a
`_param.json` written by an older version still runs; add an entry there rather
than breaking an existing parameter file when a method is renamed.

| `bg_method` | Description |
|---|---|
| `trendfill` | Masks fiber candidates via gradient histogram and ridge detection, then subtracts a fitted second-order trend surface, fills the mask from the nearest background pixel, smooths, and restores the trend. Named `inpaint` up to 1.0.0, when the fill was OpenCV Navier-Stokes inpainting. |
| `tophat` | Fast morphological top-hat correction without masking; opens a detrended copy so the scan border is not segmented as a fiber. |
| `spline1d` | 1D B-spline interpolation per row or column; effective for line-noise-dominant images. |

`spline2d` (a 2D B-spline background surface) was removed after 1.0.0: it left
the largest background residual of all methods on every test image, and the
smoothing factor that could have improved it was not reachable from the GUI. It
is listed in `bg_calibrator.BG_METHOD_REMOVED`, which reports removed methods by
name instead of aliasing them to a survivor — silently substituting a method
would change the numbers a stored `_param.json` reproduces.

### 8.2 `.b2z` bundle contract

GUI01 currently saves one `<input_stem>.b2z` bundle and one
`<input_stem>_param.json` file per analyzed input. Do not restore the legacy
workflow that emitted multiple standalone `.npy` files unless the user
explicitly requests a format migration.

The executable contract — required and optional keys, array shapes, units,
coordinate convention, and the bundle format version — is defined in
`afm_nanofiber_analyzer/bundle_schema.py` (`REQUIRED_BUNDLE_KEYS`, `OPTIONAL_BUNDLE_KEYS`,
`TRACKING_BUNDLE_KEYS`, `validate_bundle`, `BUNDLE_FORMAT_VERSION`,
`SUPPORTED_BUNDLE_VERSIONS`), along with the optional vlmeta entries
`SPATIAL_CALIBRATION_KEY` and `SOURCE_REGION_KEY` (which scan lines of the
input were analyzed; absent means the whole image). Read the key list, shapes, and units there;
this document intentionally does not duplicate them. The pipeline validates
before saving, `afm_nanofiber_analyzer/measure.py` validates at load time, and `cli.py validate`
checks bundles on demand. Bump `BUNDLE_FORMAT_VERSION` (recorded in vlmeta as
`version`) when keys, shapes, or units change, and also when a stored array
keeps its shape but changes meaning: an older release would otherwise misread
it without noticing. A reader handles each older format as it was analyzed,
through the `*_from_meta` functions of `bundle_schema`; it never repairs one.
What each format from 1.1 to 1.8 changed, and how a reader treats it, is in
`docs/design_notes.md` (Bundle format history).

`scripts/check_versions.py`, run from `.githooks/pre-commit`, blocks a commit
that bumps `BUNDLE_FORMAT_VERSION` without listing the new version in
`SUPPORTED_BUNDLE_VERSIONS`, in the `## [Unreleased]` section of
`CHANGELOG.md`, and in both READMEs, or without a package version at least one
MINOR step above the last release tag. It also blocks a package version that is
not later than the last release tag or differs between `pyproject.toml` and
`afm_nanofiber_analyzer/__init__.py`, and a removed or renamed `ProcParams` field without a MAJOR
step. Do not bypass it with `--no-verify`; add what it names.
`scripts/release.py prepare X.Y.Z` writes a release into every file that
records the version (RELEASING.md checklist) and `start-dev X.Y.Z` sets the
next `.dev0`; use them rather than editing those files by hand.
A public name listed in §8.7 is renamed, not removed, by keeping the old name
in the module's `_DEPRECATED_ALIASES` (resolved with a `DeprecationWarning` by
the module's `__getattr__`, as `afm_nanofiber_analyzer/centerline.py` does) with a
`# remove-in: X.Y.Z` marker naming the next MAJOR release, and by a CHANGELOG
`### Deprecated` entry. `release.py prepare` refuses to release that version
while the marker remains, so the alias is deleted then and not carried on.
`scripts/release.py suggest` classifies the changes since the last tag by the
RELEASING.md MAJOR / MINOR / PATCH table and proposes the next number, with the
evidence for each signal; the choice stays with the user.
`scripts/compare_bundles.py OLD NEW --reanalyze RAW` re-analyzes the inputs of
earlier bundles with the settings each recorded and compares arrays,
parameters and curated measurements, which is how an unchanged default is
checked on real data before a release.

GUI04 requires the keys listed in `TRACKING_BUNDLE_KEYS` (`calibrated`,
`skeletonized`, `bp`, `ep`, `kp`, `dp`, `ka`), and reads the optional `up` when
the bundle has it.

If a `.b2z` key, shape, unit, or meaning changes, ask before touching
additional files and keep at least these files consistent:

- `afm_nanofiber_analyzer/bundle_schema.py` (schema, format version, and validation rules)
- `afm_nanofiber_analyzer/pipeline.py`
- `afm_nanofiber_analyzer/measure.py`
- `guis/GUI01_Image_Preprocessor.py`
- `guis/GUI02_PlotProfiler.py`
- `guis/GUI03_Fiber_Morphology_Statistics.py`
- `guis/GUI04_Tracking_fiber.py`
- `guis/GUI05_Thumbnail_Viewer.py`
- `afm_nanofiber_analyzer/blosc2_io.py`
- `README.md` / `README.ja.md`

### 8.3 GUI-specific data expectations

- GUI00 writes `.gwy` files only. It converts every file directly inside the
  selected folder whose extension is not in `gwy_convert.SKIPPED_EXTENSIONS`
  into `<original file name>_converted.gwy` beside it, through `gwy_convert.convert_file`
  (the same code as `cli.py convert`), and GUI01 analyzes the results through
  its existing `.gwy` input. It reads no bundle.
- GUI02 accepts `.b2z`, `.npy`, `.csv`, `.txt`, and Gwyddion `.gwy` inputs. For
  `.b2z`, it reads the `calibrated` key and extracts line profiles with
  `skimage.measure.profile_line`. For `.gwy` it reads the selected channel
  through `afm_nanofiber_analyzer/gwy_io.py` (auto-selected topography by default; a channel
  dropdown appears for multi-channel files).
- GUI03 expects GUI01 `.b2z` bundles, registered file by file in groups; a
  group stands for one specimen and its bundles are aggregated together. It has
  no folder registration and reads no fiber CSV. It measures the bundles through
  `afm_nanofiber_analyzer.measure` and compares the distribution of one quantity across the
  groups, per skeleton pixel, fiber, kink or image. It draws the `calibrated`
  image of the selected bundle through `ui_tools.read_height_image`, the reader
  GUI05 uses, and shows the statistics and the between-group comparison in a
  window of its own (`StatisticsWindow`), which is hidden, not destroyed, when
  closed. GUI01's "このフォルダをGUI03で解析" and GUI05's "GUI03で開く" hand it
  bundle paths through a list file (`plugin_launch.path_list_arguments`, read
  with `read_path_arguments`), because a command line holds a limited number of
  characters.
- GUI04 expects GUI01 `.b2z` bundles, reconstructs individual `Fiber` instances
  through `FiberTrackingImage`, and preserves workflows for fiber lists, full
  AFM view, individual fiber view, profiles, height filtering, figure export,
  and CSV export.
- GUI05 expects GUI01 `.b2z` bundles, any number at a time, and draws only
  `calibrated`, as thumbnails with the physical aspect ratio of each scan. It
  reads `skeletonized` and the recorded scan size when the bundle has them (for
  `compute_auto_vrange` and the aspect ratio) and still shows a bundle without
  them. It keeps a reduced copy of each image and reads the bundles again when
  a sheet is saved. It writes PNG or PDF sheets only, never a bundle. The
  gallery on the screen and the saved sheet are both placed by
  `SheetLayout.cell_parts`, so a setting that changes the sheet changes the
  screen with it; keep new sheet elements in that one geometry. Dropping files
  needs the `tkinterdnd2` package, and the window opens without it.

### 8.4 Long-running GUI work

Analysis and file loading must not block the Tk main loop. Run long operations
in a worker thread, pass results or log events through `queue.Queue`, and poll
from the main thread with `after()`. Prefer `afm_nanofiber_analyzer/ui_tools.py` helpers such
as `drain_ui_queue` for shared queue-draining behavior.

### 8.5 Renames and imports

Do not rename `afm_nanofiber_analyzer/` modules casually. If a module filename or public import
path changes, check at least `afm_nanofiber_analyzer/` imports, `guis/*.py`, `README.md`, and
`README.ja.md`.

`Main.py` launches each plugin through its `--run-plugin` subcommand, which
imports the plugin module in a worker thread behind a splash window. Frozen
PyInstaller builds must keep using this subcommand because the PyInstaller
bootloader does not honor `-c` or `-m`. Keep libraries that are heavy to
import and needed only by a specific feature (e.g. lmfit, pandas) as
function-local imports so plugin startup stays fast. The `gwyfile` package
(read `.gwy` files in `afm_nanofiber_analyzer/gwy_io.py`) follows the same rule: it is imported
inside the functions that open a `.gwy`, so text-only workflows and plugin
startup never load it.

### 8.6 Build and dependency helpers

`check.py` scans project imports and regenerates `requirements.txt`. `build.py`
performs PyInstaller-oriented import checks, spec generation, build execution,
and copies `guis/`, `afm_nanofiber_analyzer/`, `locale/`, and `assets/` into `dist/Main/`.
Distribution should treat the entire `dist/Main/` folder as the deliverable.

Both scan every import statement, function-local ones included, so an optional
dependency imported for one feature has to be named where they skip it:
`check.OPTIONAL_TOPLEVEL` keeps it out of `requirements.txt` and the pyproject
consistency check, and `build.OPTIONAL_EXCLUDED_PACKAGES` keeps it out of the
frozen build. `gwyddionpy_converter` is listed in both: its `gwyconvert` is GPL
and ships with its own third-party libraries, so bundling it would make every
release a GPL redistribution.

### 8.7 afm_nanofiber_analyzer module APIs

Do not rename the public classes and functions listed below without updating
all call sites in `guis/`, `Main.py`, `cli.py`, `tests/`, and `afm_nanofiber_analyzer/` imports.
Why each module is built as it is, and what was measured when its design was
chosen, is in `docs/design_notes.md`; read a module's notes there before
changing what it does. Keep a note in this table to one or two sentences.

| Module | Public API | Notes |
|---|---|---|
| `afm_io.py` | `load_afm_text`, `load_afm_image`, `detect_afm_format`, `read_scan_size`, `AfmTextFormat`, `ScanSize`, `FORMAT_KINDS` | Loads AFM text/CSV as NumPy array; auto-detects header rows, column count, and encoding. `detect_afm_format` reports the detected layout without loading the data. `read_scan_size` reads the physical scan size from the instrument header (Shimadzu `SizeX`/`SizeY`) when present. `load_afm_image` and `read_scan_size` dispatch `.gwy` paths to `gwy_io.py` (importing `gwyfile` only there), so callers handle text and `.gwy` inputs uniformly. |
| `bg_calibrator.py` | `BGCalibrator`, `BG_METHOD_NAMES`, `BG_METHOD_ALIASES`, `BG_METHOD_REMOVED`, `canonical_bg_method` | See §8.1 for `bg_method` options. `BG_METHOD_NAMES` is the canonical method list; `canonical_bg_method` translates a retired spelling from `BG_METHOD_ALIASES` so a `_param.json` written by an older version still loads. `BG_METHOD_REMOVED` maps a deleted method to the message shown when a stored parameter file still selects it; removed methods are reported, never aliased to a survivor. |
| `bg_calibrator_shimadzu.py` | `BG_Calibrator_shimadzu` | Compatibility shim; alias of `BGCalibrator`. Do not add new code here. |
| `blosc2_io.py` | `save_blosc2`, `load_blosc2`, `save_bundle`, `load_bundle` | |
| `bundle_schema.py` | `validate_bundle`, `BUNDLE_FORMAT_VERSION`, `SUPPORTED_BUNDLE_VERSIONS`, `REQUIRED_BUNDLE_KEYS`, `OPTIONAL_BUNDLE_KEYS`, `TRACKING_BUNDLE_KEYS`, `SPATIAL_CALIBRATION_KEY`, `SOURCE_REGION_KEY`, `PARAMS_KEY`, `SCAN_SIZE_SOURCES`, `make_spatial_calibration`, `scan_size_um_from_meta`, `pixel_size_nm`, `pixel_aspect`, `pixel_aspect_from_meta`, `kink_params_from_meta`, `HALF_MAX_CENTERLINE_VERSIONS`, `CENTERLINE_KEY_VERSIONS`, `PHYSICAL_GEOMETRY_VERSIONS`, `NEAREST_PEAK_WIDTH_VERSIONS`, `width_peak_from_meta`, `ADAPTIVE_WIDTH_RANGE_VERSIONS`, `width_range_adaptive_from_meta`, `SYMMETRIC_SECTION_VERSIONS`, `symmetric_section_from_meta`, `CENTERLINE_KEY`, `centerline_from_meta`, `APPARENT_WIDTH_KEY`; deprecated alias `PIXEL_LENGTHS_KEY` (removed in 3.0.0) | Executable `.b2z` contract (§8.2): keys, shapes, units, format version, validation, and the `*_from_meta` readers that say how each older format was analyzed; readers take every analysis setting from the bundle, never from `_param.json`. Depends only on NumPy. |
| `connect_selection.py` | `CONNECT_SUFFIX`, `CONNECT_FORMAT`, `CONNECT_VERSION`, `CONNECT_PARAM_FIELDS`, `ChainMember`, `ConnectionPlan`, `connect_path_for`, `skeleton_digest`, `params_to_dict`, `params_from_dict`, `plan_from_chains`, `resolve_plan_chains`, `plan_with_chain`, `plan_without_anchors`, `plan_without_junctions`, `plan_state_key`, `load_connect_plan`, `save_connect_plan` | Fiber-connection **result** in `<stem>_connect.json`, written with the exclusion sidecar by GUI04's 「除外・連結を保存」 and applied by `measure.curate_fibers`: the join structure the user accepted (one chain of `(anchor pixel, flip)` per fibril), never re-derived by searching. `CONNECT_PARAM_FIELDS` names are frozen (§8.1). |
| `fiber.py` | `Fiber`, `skeleton_track` | Immutable per-fiber dataclass. `xtrack` / `ytrack` are the line the fiber is measured along; **everything that identifies a fiber (anchors, track pixels, branch-point and frame tests) reads `skeleton_track`, never the drawn line**. |
| `centerline.py` | `place_centerline`, `CenterlineResult`, `half_max_centerline`, `refine_centerline`, `measure_apparent_width`, `polyline_distance`, `sample_height`, `WIDTH_PEAK_NEAREST`, `WIDTH_PEAK_GLOBAL`, `WIDTH_PEAKS`, `HALF_MAX_025W_CENTERLINE`, `SKELETON_TRACK`, `FALLBACK_WIDTH_PX`, `CENTERLINE_METHODS`, `DEFAULT_CENTERLINE_METHOD`, `SKELETON_PIXEL_LINE`, `SMOOTHED_SKELETON_05W`, `SMOOTHED_SKELETON_1W`, `HALF_MAX_05W_CENTERLINE`, `QUARTER_MAX_CENTERLINE`, `CENTROID_CENTERLINE`, `CREST_CENTERLINE`, `PIXEL_CHAIN_LINES`, `is_pixel_chain_line`, `is_placed_line`; deprecated alias `HALF_MAX_CENTERLINE` (removed in 3.0.0) | The single definition of each selectable centerline (`place_centerline(method=...)`), of the apparent width W and of the crest height. **Do not change the default without re-running the comparison in `docs/validation.md` §4.2–§4.3**: every result of a default analysis moves with it. Covered by §8.13. Depends only on NumPy. |
| `fiber_connector.py` | `ConnectParams`, `MANUAL_RANGE_FACTOR`, `plan_from_auto_connect`, `build_connected_fibers`, `connect_fiber_fragments`, `connection_candidate_flags`, `connection_candidates`, `connection_candidates_by_index`, `chain_for_manual_join`, `filter_fibers_by_height`, `angle_between_three_points` | Reconnection of skeleton fragments into fibrils, split into a **search** (`plan_from_auto_connect`, run only by GUI04's 「自動連結」) and a **construction** (`build_connected_fibers`) so a stored plan rebuilds exactly the fibrils that were on screen; candidate lists for manual connection; `filter_fibers_by_height` (connect, then filter). Reads the fragments' skeleton pixels, never the drawn line. |
| `fiber_selection.py` | `EXCLUSION_SUFFIX`, `EXCLUSION_FORMAT`, `EXCLUSION_VERSION`, `exclusion_path_for`, `fiber_anchor`, `constituent_anchors`, `fiber_track_pixels`, `excluded_flags`, `load_exclusions`, `save_exclusions` | Manual exclusions in `<stem>_excluded.json`, written by GUI04: an **anchor pixel on the skeleton track, never a list index**, applied to the fragments before connection (`measure.curate_fibers`). A malformed or newer-version sidecar is refused, never read as empty. |
| `group_compare.py` | `PairComparison`, `compare_groups`, `cliffs_delta`, `holm_adjusted`, `delta_magnitude`, `MAGNITUDE_THRESHOLDS`, `MAGNITUDE_LARGE`, `MIN_SAMPLES_FOR_TEST` | Between-group tests for GUI03: Mann-Whitney U (primary) and KS (reference) with Holm correction, and Cliff's delta. **The caller owns the independence assumption**: GUI03 tests only its `fiber` and `image` units. Imports `scipy.stats` inside its functions (§8.5). |
| `fiber_tracking_image.py` | `FiberTrackingImage` | GUI04 data container; builds `Fiber` instances from a bundle on the line the bundle records, carrying the kink settings the bundle was analyzed with (filled in by `afm_nanofiber_analyzer.measure` from the bundle, never hard-coded). |
| `gwy_convert.py` | `SKIPPED_EXTENSIONS`, `STATUS_CONVERTED`, `STATUS_EXISTS`, `STATUS_FAILED`, `CONVERTED_SUFFIX`, `DEFAULT_TIMEOUT_S`, `CONVERTER_ENV_VAR`, `INSTALL_COMMAND`, `INSTALL_HINT`, `ConverterNotFoundError`, `ConversionResult`, `converted_path_for`, `is_conversion_candidate`, `list_conversion_candidates`, `find_converter`, `convert_file` | Converts files this software cannot read into `<input file name>_converted.gwy` by running `gwyconvert` (optional `convert` dependency) as a separate process; shared by GUI00 and `cli.py convert`. The converter is GPL: `gwyddionpy_converter` is imported only to locate it and is excluded from the frozen build (§8.6). |
| `gwy_io.py` | `GWY_EXT`, `GwyChannel`, `GwyImage`, `list_gwy_channels`, `load_gwy_image`, `read_gwy_scan_size`, `select_default_channel` | Reads Gwyddion `.gwy` files (selected channel in nm, scan size in µm); imports `gwyfile` lazily. Callers test for a `.gwy` path inline, before importing this module, because `gwy_io` imports from `afm_io`. |
| `imp_tools.py` | `branchedPoints`, `endPoints`, `tracking`, `convert_track_to_distance` | `convert_track_to_distance` applies the corrected chain-code weights of an 8-connected pixel chain. It measures the skeleton track of a bundle older than format 1.1; a centerline is measured with `centerline.polyline_distance`. |
| `kink_detector.py` | `KinkDetector`, `KinkJudgement`, `END_MARGIN_WIDTHS`, `NOISE_SIGMAS`, `UNJUDGED_NEAR_END`, `UNJUDGED_AT_BRIDGE` | Judges kinks on each component's centerline by the **excess-turning rule** (`KinkDetector.judge_line`), storing unjudged bends (`up`) separately, never folded into the kinks. Keep `NOISE_SIGMAS` at 0 unless `scripts/kink_reference_score.py` is re-scored, and do not tune a length to one fiber. Covered by §8.13. |
| `measure.py` | `FiberStats`, `MeasureResult`, `curate_fibers`, `compute_fiber_stats`, `fiber_straightness`, `fiber_curvature_profile`, `fiber_mean_curvature`, `fiber_judged_length_um`, `fiber_kink_density`, `collect_fiber_curvature`, `DEFAULT_CURVATURE_WINDOW_NM`, `isolated_fiber_flags`, `load_tracking_image`, `measure_bundle`, `collect_fiber_stats`, `contour_length_weights`, `read_fiber_csv`, `collect_fiber_stats_from_csv`, `read_scan_size_from_bundle`, `write_fiber_csv`, `skeleton_height_values`, `write_heights_csv`, `TRACKING_BUNDLE_KEYS`, `FIBER_CSV_COLUMNS`, `FIBER_CSV_COLUMNS_V6`, `FIBER_CSV_COLUMNS_V5`, `FIBER_CSV_COLUMNS_V4`, `FIBER_CSV_COLUMNS_V3`, `FIBER_CSV_COLUMNS_V2`, `FIBER_CSV_COLUMNS_V1`, `SCALE_SOURCE_RECORDED`, `SCALE_SOURCE_ENTERED`, `read_centerline_from_bundle`, `height_sample_mask`, `CUT_END_EXCLUSION_WIDTHS`, `HEIGHT_UPPER_PERCENTILE`, `fiber_real_end_count`, `kaplan_meier_length_weights`, `length_floor_nm`; deprecated aliases `fiber_kink_angle` and `collect_skeleton_height_profiles` (removed in 3.0.0) | GUI-independent fiber measurement shared by GUI03, GUI04, and `cli.py measure` / `heights`; keeps GUI and CLI statistics identical. `curate_fibers` owns the order: exclusions on the fragments first, then the stored connection plan (the height filter keeps the opposite order). `isolated_fiber_flags` is evaluated once and recorded as exclusions; do not turn it back into a view filter or loosen a test to make the count larger. **Every quantity GUI03 can histogram has a GUI04 fiber-table column** (enforced by `test_gui04_fiber_table_covers_every_gui03_quantity`), and a quantity is added only if it is a scientifically meaningful parameter of an individual nanofiber, not of the network. |
| `pipeline.py` | `ProcParams`, `STAGE_KEYS`, `build_stages`, `PipelineStages`, `process_file`, `PipelineResult`, `merge_params_dict`, `validate_params`, `existing_min_set`, `bundle_path_for`, `param_path_for`, `row_range_suffix`, `BG_METHODS`, `canonical_bg_method`, `BackgroundWarning`, `background_warnings`, `flank_step_ratio`, `BACKGROUND_CHECKED_MAX_WIDTH_PX`, `MIN_FLANK_STEP_RATIO`, `TOPHAT_MIN_ELEMENT_WIDTHS`, `TOPHAT_SUGGESTED_ELEMENT_WIDTHS`, `NoiseWarning`, `noise_warnings`, `fiber_snr`, `MIN_FIBER_SNR`; deprecated alias `pixel_lengths_nm` (removed in 3.0.0) | GUI-independent preprocessing driver shared by GUI01 and `cli.py process`; owns `ProcParams` (field names frozen, §8.1), stage construction, and the background and noise warnings `process_file` returns. |
| `processed_image.py` | `ProcessedImage` | Image and result container for the GUI01 pipeline. |
| `segmenter.py` | `Segmenter` | |
| `skeletonizer.py` | `Skeletonizer` | |
| `stripe_noise.py` | `StripeNoise`, `evaluate_scan_lines`, `propose_clean_ranges`, `DEFAULT_STEP_THRESHOLD_NM`, `DEFAULT_GUARD_LINES` | Screens a raw scan for feedback glitches: flags scan lines displaced by a lost feedback loop (via the line-to-line median height step) and lists the runs of glitch-free lines. Read-only, like `bg_quality.py`: no pipeline stage calls it and nothing it computes is written to the `.b2z` bundle, since the metrics are exactly reproducible from the raw input. Surfaced by GUI01's stripe-noise-rate column. Depends only on NumPy. |
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
.venv\Scripts\python.exe prepare_translate_catalogs.py
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

### 8.9 Python interpreter invocation

The repository ships a single virtual environment at `.venv/`. Invoke Python
through it, using exactly one spelling per shell:

```bash
# Bash tool (Git Bash)
.venv/Scripts/python.exe -m pytest -q
```

```powershell
# PowerShell tool
.venv\Scripts\python.exe -m pytest -q
```

Do not substitute equivalent-looking variants such as
`./.venv/Scripts/python.exe`, `.venv/Scripts/python` (no `.exe`),
`..\.venv\Scripts\python.exe`, a bare `python`, or a `.conda-env/`
interpreter. Only `.venv/` exists in this repository, and agent permission
allowlists match on the command prefix, so every extra spelling of the same
command needs its own rule and triggers a fresh approval prompt. One spelling
per shell keeps that rule set small.

### 8.10 Scratch and temporary files

Write scratch files — probe scripts, intermediate data, screenshots, captured
output, working copies — to `.tmp/` at the repository root. Create it on first
use. Do not use a per-session scratch directory under the user profile
(`%TEMP%`, `%LOCALAPPDATA%`) even when the agent harness assigns one by
default, and do not invent a parallel directory such as `.temp/` or `tmp/`.

`.tmp/` is already wired into every tool in this repository, so scratch files
there cannot leak into the deliverable:

- `.gitignore` ignores `.tmp/`
- `[tool.ruff] extend-exclude` in `pyproject.toml` skips `.tmp`
- `[tool.pytest.ini_options] testpaths = ["tests"]` never collects it
- `check.py` scans only `Main.py`, `guis/`, and `afm_nanofiber_analyzer/`, so `.tmp/` cannot
  pollute the regenerated `requirements.txt`
- `build.py` copies only `guis/`, `afm_nanofiber_analyzer/`, `locale/`, and `assets/`

Keeping scratch files inside the repository also means an agent needs no read
permission outside the project directory, which keeps the permission allowlist
narrow. `.tmp/` is not cleaned automatically; delete stale contents manually.

### 8.11 Result-changing fixes and `CHANGELOG.md`

When a change makes the analysis produce different numbers, updating
`CHANGELOG.md` is part of that change, not a separate task. This project is
research software: users cite a version and reproduce results from it, so a
silent change in output is a reproducibility break even when no API breaks.

The triggers are two golden files: `tests/strict_regression_golden.json`, the
arrays the pipeline stores, and `tests/measurement_regression_golden.json`, the
values `afm_nanofiber_analyzer/measure.py` reports from them
(`tests/test_measurement_regression.py`; the three bundled scans, analyzed with
the defaults and with each skeleton cleanup turned off). The second exists
because a change made only when a bundle is read leaves every pipeline golden
intact. If a change updates either, the output moved and the changelog entry is
mandatory. If both are untouched, the results did not change and no entry is
required on this ground.

Add the entry under `## [Unreleased]`, normally under `### Fixed`, and state
explicitly that results change from this version — the wording matters more
than the version number the change eventually ships in (see `RELEASING.md`).
Do not assign a version number or a date; that happens at release time.

```markdown
## [Unreleased]

### Fixed

- Skeletonization no longer bends away from the fiber center at the scan
  border. **Measured lengths and heights change from this version**, so
  results are not bit-identical to 1.0.0.
```

This is enforced mechanically by `scripts/check_changelog.py`, run from
`.githooks/pre-commit`: a staged change to the goldens without a new line in
the `[Unreleased]` section blocks the commit. Do not reach for
`git commit --no-verify` to get past it — write the entry. The bypass exists
only for the case where the goldens moved because test data was added or
renamed while the analysis itself is unchanged.

Changes that alter results usually also warrant an entry for other reasons
(new features, removed APIs, packaging fixes); the changelog covers all
notable changes, and this rule only makes the result-changing case
non-optional.

`CHANGELOG.ja.md` is the Japanese translation of `CHANGELOG.md`, and the two are
a synchronized pair on the same terms as the README pair: an edit to one requires
the corresponding edit, including translation, in the other. Translate every
entry; do not shorten or summarize it. The headings stay aligned through
`SECTION_JA` in `scripts/check_changelog_ja.py`, and `scripts/release.py prepare`
rolls `[Unreleased]` and the link definitions in both files.

Three mechanisms enforce the pair, in the manner of §8.13:

- `scripts/check_changelog_ja.py`, run from `.githooks/pre-commit`, splits both
  files into entries and blocks a commit when the headings or the number of
  entries differ; when an entry and its translation differ in inline code, URLs,
  bold spans, paragraphs or nested items, or the translation lacks a number or a
  Japanese UI label of the English; or when an entry changed and its translation
  did not.
- `tests/test_changelog_ja.py` runs the same check in CI, where it cannot be
  skipped.
- The Claude Code hook `.claude/hooks/doc_code_reminder.py` (`PostToolUse`) reports
  what the translation no longer follows right after an edit of `CHANGELOG.md`.

The check compares against `tests/changelog_ja_manifest.json`. After translating
an edit, read the pair and refresh it with
`.venv\Scripts\python.exe scripts\check_changelog_ja.py --update`, which refuses
an English entry whose translation has not changed. An English edit that truly
needs no change to the translation, such as a typo, is recorded with
`--update --english-only`. The manifest is a tripwire, not a proof: whether a
translation says what the English says is not machine-checked.

### 8.12 Verifying analysis and detection changes

A claim about *what the analysis detected* is not verified until the rendered
images have been inspected. This applies to any statement that objects were
detected, missed, gained, or lost, to any count / median / percentage over
detected objects, and to any recommendation for a detection parameter
(`global_threshold`, `area_min`, `h_length`, `low_threshold`, `min_area`, …).
It is the analysis-side counterpart of §7.10.

- **View the images, not only the numbers.** Render the calibrated height
  image beside the stage outputs for the same crop, and overlay the candidate
  result on the height image (captured vs. missed) rather than comparing two
  binary masks to each other. A statistic over detected objects is a proxy;
  when the thing under test is *what got detected*, the proxy measures the
  very change it is supposed to be judging.
- **A recovery-only metric is not evidence.** Any metric counting how many
  targets a looser setting recovers improves monotonically as the threshold
  drops. It must carry a false-positive term, or be replaced by inspection.
- **No pipeline stage is ground truth.** The background-stage fiber mask, the
  binarized mask, and the skeleton are all stage outputs with their own
  misses; validating one against another inherits those misses. The reference
  is the calibrated height image.
- **Do not aggregate over a population whose composition changed.**
  `measure_bundle` returns one entry per detected object, real fibers and
  spurious detections alike, so a worse condition typically *adds* short
  false detections rather than degrading the real fibers. Split real objects
  from fragments, report both, and state the outcome variable explicitly.
- **Believe a user-reported detection failure.** If the user says fibers are
  missing and a metric disagrees, the metric is suspect first.

### 8.13 Algorithm changes and `docs/algorithms.md`

`docs/algorithms.md` and its Japanese counterpart `docs/algorithms.ja.md`
explain what background calibration, binarization, skeletonization, and kink
detection do, and why, referencing the source by symbol name. They exist so the
analysis is not a black box to the people who cite its output — a requirement
of the JOSS submission and of the lab's own reproducibility. When a change
alters what one of these four stages computes, updating both language versions
is **part of that change**, not a follow-up task.

The trigger is a change to any of:

- `afm_nanofiber_analyzer/bg_calibrator.py`
- `afm_nanofiber_analyzer/segmenter.py`
- `afm_nanofiber_analyzer/skeletonizer.py`
- `afm_nanofiber_analyzer/kink_detector.py`
- `afm_nanofiber_analyzer/centerline.py` (the fiber's line, which kink detection and every
  measurement read; explained in §4.2 of the documents)

A stale explanation is worse than a missing one, because it is read as
authoritative: a reader who checks the document instead of the code and finds a
confident description of a rule the software no longer applies has been
actively misled. This is the same reasoning as §4.4 (flag, do not guess) at
document scale.

Two mechanisms enforce it, and neither is sufficient alone:

- `scripts/check_algorithm_docs.py`, run from `.githooks/pre-commit`, blocks a
  commit that changes what one of these modules computes without touching
  either document. It is the early warning, and it is opt-in per clone.
- `tests/test_algorithm_docs.py` runs in CI, where it cannot be skipped. It
  checks that every project symbol the documents name still exists, that every
  `ProcParams` field and every `bg_method` value is documented, that the two
  language versions share one heading skeleton, and it fingerprints each
  definition of these modules with comments and docstrings removed. A
  behavioral change fails the fingerprint test until
  `tests/algorithm_doc_manifest.json` is refreshed with
  `.venv\Scripts\python.exe tests\test_algorithm_docs.py --update`.

Both, and the `PostToolUse` hook below, decide "changes what it computes" by one
rule, `scripts/doc_excerpts.computation_changes`, applied definition by
definition: a changed or removed function, method, constant or import, or a
new definition that existing code refers to by name (which includes shadowing a
builtin). Comments, docstrings, function annotations, `if TYPE_CHECKING:`
blocks, and new definitions that no existing code uses — a deprecated alias, a
helper only new code calls, an import needed only by a type hint — do not
count, so such a commit needs neither a document edit nor `--no-verify`.
Removing an import still counts, because the recorded fingerprint cannot tell
what the name was used for. Do not use
`--no-verify` to get past this check: it skips the sensitive-information and
version checks too. If it reports a change you believe cannot affect the
explanation, the rule is wrong and should be fixed instead.

The fingerprint is a tripwire, not a proof: nothing forces the person
refreshing it to have reread the document. That is what this rule is for. Do
not refresh the manifest as a mechanical step to make a test pass — read the
sections covering the stage you changed first, and update them when the
explanation no longer matches.

Reference code from these documents **by symbol name, never by line number**.
Line numbers rot on the first unrelated edit and cannot be checked; symbol
names are verified on every test run.

**Explain each step with the code that performs it.** The reader of these
documents has to be able to check a number against the computation, so every
stage, every rule, and every stored quantity (for example the kink angle) is
shown with its code and, where there is one, its formula. Quote code only as a
verified excerpt: a fenced block whose first line is
`# source: <path>::<symbol>` (several symbols of one file may be listed,
comma-separated), with `...` on its own line for omitted code, quoting code
only — no comments, docstrings, or method indentation. `scripts/doc_excerpts.py`
compares every excerpt with the code it names, and requires the English and
Japanese versions to quote identical code. When a change alters a quoted line,
update the excerpt and the prose around it in both documents. Never paste code
any other way: an unverified excerpt is exactly the stale explanation this rule
exists to prevent.

The excerpts are checked in three places: `tests/test_algorithm_docs.py` (CI),
`scripts/check_algorithm_docs.py --staged` (pre-commit, against the staged
code), and the Claude Code hook `.claude/hooks/doc_code_reminder.py`, which
reports a stale excerpt or a changed algorithm module right after the edit.
Third-party functions are named in prose with their package prefix
(`skimage.filters.threshold_local`), because a bare snake_case name is checked
as a project symbol.

The two documents are a synchronized pair on the same terms as the README pair
(see Editing Rules): an edit to either one requires the corresponding edit,
including translation, in the other.

### 8.14 GUI04 measurement changes and `docs/gui04_measurements.md`

`docs/gui04_measurements.md` and its Japanese counterpart
`docs/gui04_measurements.ja.md` explain how GUI04 places each fiber's
centerline and computes every value it displays — the fiber-table columns, the
detail window's height profile, and the fiber-connection candidates — quoting
the code that does it. They exist for the same reason as the algorithm
documents (§8.13): the people who cite GUI04's numbers must be able to check
them against the computation. When a change alters what one of the quoted
symbols computes, updating both language versions — prose **and** the quoted
excerpts — is **part of that change**, not a follow-up task.

The trigger is a change to any symbol listed in `WATCHED_SYMBOLS` in
`scripts/check_gui04_docs.py`, which is the authoritative list (functions in
`afm_nanofiber_analyzer/centerline.py`, `afm_nanofiber_analyzer/measure.py`, `afm_nanofiber_analyzer/fiber_tracking_image.py`,
`afm_nanofiber_analyzer/fiber.py`, `afm_nanofiber_analyzer/fiber_connector.py`, `afm_nanofiber_analyzer/kink_detector.py`, and
`guis/GUI04_Tracking_fiber.py`). **Every column of GUI04's fiber table must be
explained**: adding a column requires a subsection of §3 in both documents
whose heading names the column in backticks — how the value is computed, its
unit, and when the cell is blank. A mention in the §3 overview table alone does
not count.

The documents distinguish two coordinate sequences along a fiber, defined in
their *Conventions* section: the **centerline** (the half-maximum centerline in
`Fiber.xtrack` / `Fiber.ytrack`) and the **skeleton track** (the ordered pixels
of the skeletonized image, `Fiber.skeleton_xtrack` / `Fiber.skeleton_ytrack`).
Always write which one is meant — 「中心線」 or 「スケルトントラック」, "centerline"
or "skeleton track" — and never a bare 「線」 / "line" for either. The check
rejects a bare one outside code; compounds that mean neither sequence (直線,
破線, "straight line", "guide lines", ...) are allowed through
`ALLOWED_LINE_JA` / `ALLOWED_LINE_EN` in `scripts/check_gui04_docs.py`.

As in §8.13, these documents **quote code**, because the reader is meant to see
the computation itself, and they follow the same verified-excerpt contract
(`scripts/doc_excerpts.py`): each code block starts with
`# source: <path>::<symbol>` and must still match that symbol line for line.
Do not paste code into these documents in any other form. Unlike §8.13, the
fingerprint is per symbol rather than per module, so add a symbol to
`WATCHED_SYMBOLS` before quoting it (the check refuses unwatched excerpts).

Three mechanisms enforce the rule:

- `scripts/check_gui04_docs.py`, run from `.githooks/pre-commit` on the staged
  snapshot, blocks a commit when a quoted symbol's fingerprint (comments and
  docstrings removed) no longer matches `tests/gui04_doc_manifest.json`, when
  an excerpt no longer matches its symbol, when a fiber-table column has no
  §3 subsection naming it (or the columns can no longer be read), when the
  prose says a bare 「線」 / "line" instead of the centerline or the skeleton
  track, when the two language versions differ in heading structure or
  excerpts, or when the manifest is refreshed without touching either
  document.
- `tests/test_gui04_docs.py` runs the same checks in CI, where they cannot be
  skipped.
- The Claude Code hook `.claude/hooks/doc_code_reminder.py` (`PostToolUse`)
  tells the agent, right after an edit, which quoted symbols drifted and which
  sections quote them. Act on it within the same change.

As with §8.13, the fingerprint is a tripwire, not a proof. Refresh it with
`.venv\Scripts\python.exe scripts\check_gui04_docs.py --update` only after
rereading and updating the affected sections of both documents.

The two documents are a synchronized pair on the same terms as the README pair.

### 8.15 Numbers in the algorithm documents

Every number in the prose of `docs/algorithms.md`, `docs/algorithms.ja.md`,
`docs/validation.md` and `docs/validation.ja.md` carries a hidden source marker
directly after it, and `scripts/check_doc_numbers.py` checks each one. The
reason is what happened without it: the documents quoted evaluation results
from a prototype that the shipped code never reproduced, and nothing compared
them.

The algorithm documents explain what the code computes and hold no result on
particular data (the bundled scans, the synthetic suite): such results go in the
evaluation documents `docs/validation.md` and `docs/validation.ja.md`, which
state the data they were measured on. When a default was chosen from such a
result, the algorithm documents say that it is empirical and link the
evaluation section; they do not restate the result.

| Marker | Meaning | Checked against |
|---|---|---|
| `64<!--m:kink_reference.default.false-->` | measured | the value under that key in `tests/doc_measurements.json` |
| `3<!--c:afm_nanofiber_analyzer/pipeline.py::ProcParams.mask_dilation-->` | a constant or default in the code (`path::NAME`, `path::Class.name`, `path::func(param)`; `\|expr` with `v` transforms it) | the code, read with `ast` |
| `23<!--x:12 * 2000 / 1024-->` | arithmetic on stated numbers | evaluated |
| `1989<!--n:citation-->` | not a result (citation, label, a count in a definition, a value an example is built with); the reason is required | nothing — the reason is reviewed |

A number matches at the precision it is written with; a range `a–b` followed by
one marker matches a two-element value. Numbers in code, math, headings,
section references, link targets, version strings and list markers are exempt.
The two languages must cite the same `m:`, `c:` and `x:` sources.

- **Measured values come only from `scripts/measure_docs.py`.** Each experiment
  there reproduces one group of statements from the current code and records
  its values with the fingerprints of the analysis modules it ran on and a
  digest of the two goldens of §8.11. Never edit `tests/doc_measurements.json`
  by hand, and never write a measured number that no experiment produces: add
  the experiment first.
- **A recording goes stale when the results move.** A recording is stale when
  code it ran on has changed **and** a golden of §8.11 differs from the one it
  recorded (`check_doc_numbers.golden_digest`). The code side is the
  definitions the experiment executed: `measure_docs.traced_run` records
  them as the recording's `depends` — each project definition that ran, and
  the constants, classes and imports those name, followed through project
  imports — and only a change to one of them reaches it
  (`check_doc_numbers._dependency_changes`). A recording without `depends`
  (made before it was recorded, or by an experiment that started a child
  process, whose code cannot be seen) is judged on every definition of the
  modules it ran on (the §8.13 rule, `doc_excerpts.computation_changes`). The
  reason is the cost of the coarser rule: a change to one function marked
  every experiment that had loaded its module, and of the 32 commits that
  updated the recording after the first, six re-recorded 8 to 60 experiments
  each and changed no value. The check then reports the recording — a warning
  at a commit, an error before a release (end of this section) — until the
  experiment is run again with
  `.venv\Scripts\python.exe scripts\measure_docs.py --only <name>` and the
  documents are updated to the new values. The code says which experiments a
  change can reach, the goldens whether the analysis output moved; a change
  that leaves both goldens as they were — the same result computed faster, a
  refactor — marks nothing stale. The reason is what happened while the code
  alone was compared: a change that traces each skeleton component inside its
  bounding box marked 21 recordings stale, although every fiber built from
  the 727 bundles the experiments had cached was identical before and after
  it.
- **The goldens do not see every experiment.** They hold the bundled scans at
  the settings §8.11 names, and they follow the analysis only when the tests
  that compare them are run (`tests/test_strict_regression.py`,
  `tests/test_measurement_regression.py`). The experiments also measure
  synthetic scans and other settings, so a change that moves only such a
  result, or one committed without running those tests, leaves its recordings
  unmarked. Run every experiment once before a release
  (`scripts\measure_docs.py` without `--only`), and measure at once after a
  change known to alter a result the goldens do not hold.
- **Cached bundles are keyed by the code that made them.** The experiments
  reuse analyzed bundles, and a bundle made by older code still yields numbers
  while the recording names the current code — bundles cached on 2026-09-30
  were still being measured on 2026-10-07, after background calibration had
  changed every calibrated pixel. `scripts/bundle_cache.py` therefore names
  each cache folder by a fingerprint of the analysis modules, the code that
  writes synthetic inputs, and the numerical libraries' versions, and sends
  the folders of other fingerprints to the recycle bin. Any new cache an experiment or scoring
  script keeps goes through `measure_docs.cache_dir` or
  `bundle_cache.cache_root`, never a fixed path under `.tmp/`.
  `tests/test_bundle_cache.py` checks that the fingerprint follows a change to
  the computation or a library and ignores a comment.
- **`n:` is not an escape hatch.** Use it only for numbers that are not results.
  A result you cannot yet measure is not written at all (Editing Rules).
- **The pending list only shrinks.** `tests/doc_numbers_pending.json` lists the
  lines whose numbers predate this check and are still unverified. Editing
  such a line makes it no longer match its entry, so its numbers must then be
  marked; `--prune-pending` removes resolved entries, and the staged check
  refuses a commit that adds one.

Enforced by `.githooks/pre-commit` (`--staged`) and `tests/test_doc_numbers.py`
(CI). Do not bypass either with `--no-verify`. A stale recording is a warning
there and an error only with `--release`, which `scripts/release.py prepare`
runs: measuring again takes tens of minutes and, at a commit that does not
change what the analysis outputs, finds the same values, so the stale
recordings are measured again before a release, not at every commit.

### 8.16 Readers measure the stored record

A bundle is the record of one analysis, made with the settings it ran with.
Code that reads bundles — `afm_nanofiber_analyzer/measure.py`, `afm_nanofiber_analyzer/fiber_tracking_image.py`,
`afm_nanofiber_analyzer/fiber_connector.py`, `afm_nanofiber_analyzer/connect_selection.py`, `afm_nanofiber_analyzer/fiber_selection.py`,
GUI02–GUI05, and the bundle-reading commands of `cli.py` — measures that record
as stored. It never runs a stage that produces or rewrites the stored arrays:
background calibration, segmentation, skeletonization or any of its cleanup
passes, `pipeline.process_file`, `pipeline.build_stages`.

The reason is what happened without the rule. A loop-collapse and spur-prune
pass was added to `FiberTrackingImage` so that bundles written before the
pipeline did that cleanup would "benefit without re-analysis". It ran at its own
defaults on every bundle, new ones included, so a `max_loop_area` or
`spur_length` below its default never reached a measurement — two fibers the
user had kept apart with `max_loop_area` = 0 were still joined when measured —
and fibers were traced along pixels the stored skeleton does not contain. The
principle "loading must not reinterpret the stored record" had already been
written for terminal-hook trimming, in the docstring of that same function,
without anyone checking the repair beside it.

- **Recomputing what the recorded settings determine is measurement, not a
  stage**, and is allowed: placing the centerline with the bundle's
  `centerline_method`, judging kinks on a reconnected fibril with
  `kink_params_from_meta`. Such a computation reads its settings from the
  bundle, never from a hard-coded default.
- **An older bundle is handled by its format version, not repaired.** The reader
  measures it as stored and tells the user to re-analyze it, as GUI03, GUI04 and
  `cli.py` do for format 1.0. When a new analysis step changes what the pipeline
  stores, bundles written before it are re-analyzed to receive it.
- **When a rule like this is introduced or tightened, search the existing code
  for violations in the same change.**

Enforced by `tests/test_reader_purity.py` (CI), which fails when a reader module
imports a stage module or a stage driver, and by
`tests/test_measurement_regression.py` (local), whose golden moves — and so
requires a changelog entry under §8.11 — whenever a measured value changes.

### 8.17 Claims in `paper.md`

Every prose sentence of `paper.md` — figure captions and list items included —
has one entry in `tests/paper_claims.json` recording what supports it, and
`scripts/check_paper_claims.py` checks the entries. The reason is what happened
without it: the manuscript attributed to FiberApp's authors a reason nobody
had read in their paper, misdescribed which files FiberApp reads, and described its
A* tracking incorrectly, all in confident prose indistinguishable from the
sentences that had been checked.

- A sentence is `verified` only with at least one source: a repository
  document containing a quoted passage (`doc`), a definition or quoted line of
  code (`code`), an image and what was seen in it (`figure`), a passage read
  in published work or another project (`external`: a `paper.bib` key or URL,
  the page or file, and the passage), or a fact only the authors know
  (`author`, naming who confirmed it). `doc` and `code` quotes are checked
  against the files; an `external` quote is checked by whoever writes it,
  against the original, verbatim.
- **`author` is set only when the user has confirmed the statement in the
  conversation.** An agent never records its own belief about the authors,
  their data, or their tools as an `author` source.
- An evaluative or comparative statement ("the most widely used", "the closest
  tool") is not verified by a source describing the tool; it stays
  `unverified` until the authors confirm it as their assessment or remove it.
- Anything else is `unverified`, with a `note` saying what is missing. Editing
  a sentence detaches it from its entry, so it must be verified again; the
  staged check refuses a commit that adds an unverified sentence, so the
  unverified set only shrinks. `--add-missing` records new sentences as
  unverified for filling in; `--list-unverified` prints them.
- **`paper.ja.md` is generated, never edited.** Each entry also holds the
  sentence's Japanese translation (`ja`), and the record holds `title_ja` and
  `headings_ja`; `--write-ja` builds `paper.ja.md` from them in the paragraph
  structure of `paper.md`. The check fails when a sentence, heading or the title
  has no translation, when a translation's citations or inline code differ from
  the English or it drops a number (an added digit is allowed only for a number
  the English spells out), and when `paper.ja.md` differs from what `--write-ja`
  produces. Editing an English sentence detaches its translation with its
  sources, so the translation is redone with the verification. Whether a
  translation says what the English says is not machine-checked: have it read
  against the English before it is recorded.

Enforced by `.githooks/pre-commit` (`--staged`) and `tests/test_paper_claims.py`
(CI). Do not bypass either with `--no-verify`.

### 8.18 Visual review of analysis changes

A change to what the GUI01 analysis stages compute — the modules in
`VISUAL_MODULES` of `scripts/check_visual_review.py`: background correction,
binarization, skeletonization, the centerline, kink detection, `imp_tools.py`
and `pipeline.py` — is accepted only after its effect has been looked at on
whole images of the bundled scans and a person has approved what it shows.
The goldens report that an output moved, not whether it got better or worse,
and the images show what the numbers do not: while `docs/history.md` was
written, the 2.0.0 `tophat` change was seen to leave the raw scan's line
offsets visible on the tunicate scan, which its changelog entry does not
mention, and the noise-range change of the background mask to deepen a
subtracted fiber on that scan, which its entry summarizes as local and small.

1. Run `.venv\Scripts\python.exe scripts\visual_diff.py compare [BASE]`
   (`BASE` defaults to `HEAD`). It runs the base commit and the working tree on
   the three bundled scans, giving each later stage the working tree's output
   of the earlier stages so a figure shows that stage's change alone, and
   writes figures and `summary.json` to `.tmp/visual_diff/`. When every
   stage's output is bit-identical it records the code as `identical` and
   nothing more is needed.
2. Otherwise Read every figure it writes — each stage, each scan, as whole
   images, and the enlarged centerline — and look at the places that changed
   at full resolution before describing them (§8.12). Record what was seen with
   `visual_diff.py record --stage STAGE=VERDICT:NOTE` for every stage
   (`improved`, `worse`, `mixed` or `unchanged`, with where), which stores a
   `pending` review in `tests/visual_review.json`. Describe what the images
   show; do not choose crops or wording to make a change look better.
3. Show the user the figures and the recorded verdicts. `visual_diff.py
   approve --by NAME` marks the review approved. **An agent runs it only after
   the user has approved that review in the conversation**, with the name the
   user gives, never on its own judgement, and never treats a pending review
   as approved.

The record is keyed by a fingerprint of the code of `VISUAL_MODULES` with
comments and docstrings removed (`doc_excerpts.code_symbol_digests`), so a
comment or docstring edit needs no review. A fingerprint is covered by an
`approved` review with a name, an `identical` record, or the `baseline` entry
for the code the check was introduced on. The rule sits beside §8.11, not in
place of it: a result-changing change still needs its changelog entry.

Enforced by `scripts/check_visual_review.py --staged` in `.githooks/pre-commit`
(only when the staged code changes the fingerprint against `HEAD`),
`tests/test_visual_review.py` (CI, the working tree), and the Claude Code hook
`.claude/hooks/doc_code_reminder.py`, which reports an uncovered change right
after an edit of one of these modules. Like the document fingerprints, the
record shows that a review was recorded, not that anyone looked; that part is
this rule. Do not bypass the check with `--no-verify`.

### 8.19 Running the tests

`pytest` with no arguments runs the whole suite in parallel workers
(`addopts = ["-n", "auto", ...]` in `pyproject.toml`), and the GUI tests in it
open real windows on the screen of whoever is working at the PC. Choose the
tests by what the change touches; do not run the whole suite by habit.

The reason is what happened without the rule. A change to the shared `tk_app`
fixture in `tests/conftest.py` was first run on the whole suite, in the
background and unannounced. The run hung on one test, the user reported GUI02
windows left open in large numbers and unresponsive, and the PC was powered off
41 minutes later.

A test run needs the user's approval, given in the conversation before it
starts, when

- it names no test file or names a folder, so the whole suite or a whole
  folder runs;
- it runs tests of a file that opens windows while the parallel workers are on
  (`-n 0` turns them off, so one window is open at a time); or
- it runs more than 30 tests of files that open windows, even one at a time.

`check.py --pin` and `scripts/release.py prepare` without `--skip-checks` start
the whole suite themselves and need the same approval. Before asking, say what
will run, that windows will open, and roughly how long it takes. Named test
files that open no window, and up to 30 tests of window-opening files with
`-n 0`, run without asking.

After changing `tests/conftest.py`, a fixture, or code that opens or closes a
window, run one test first and confirm that its window is gone when the test
ends, before running more.

Two safeguards in the suite itself hold however the tests are started. The
`tk_app` fixture in `tests/conftest.py` asks Tk whether each window is gone
after `destroy()`; a window left open is closed by force (`close_window`) and
fails the test that built it, so windows cannot pile up unnoticed. And a test
still running after `faulthandler_timeout` seconds (`[tool.pytest.ini_options]`
in `pyproject.toml`) ends its test process, so a hung test cannot hold its
windows and memory until someone kills it. pytest drops that limit once a test
has failed, so the teardown of a failed test is not covered.

In Claude Code, `.claude/hooks/pytest_guard.py` denies a command that needs
approval until a message from the user contains the words 「テスト実行を許可」
(or "allow the test run"); one message approves one run within 30 minutes, and
words inside quotation marks or code approve nothing. The hook reads the
command line only: a test file counts as opening windows when its text matches
the hook's `WINDOW_RE` (Tk, the `tk_app` fixture, a plugin launch), tests are
counted as functions rather than parametrized cases, and a run started from
inside another script is not seen. Other agents, and a person at a terminal,
follow this rule without the hook.

### 8.20 Steps that change what is compared

A step that leaves measured objects out of a result, reweights them, or cuts
them to a common range so that groups or bundles become comparable is proposed
together with the experimental design it assumes, and is not built until the
user has confirmed that design in the conversation.

The reason is what happened without the rule. An academic review of GUI03
noted that a coarser scan keeps no fiber shorter than its length floor
(`measure.length_floor_nm`), and GUI03 was given a setting, on by default when
it was added, that cut every compared group at the largest floor of all
groups. Specimens whose fibers differ in length, such as tunicate and
higher-plant cellulose, or one material after different treatments, are
imaged at different resolutions by design, so the setting removed short fibers
from a finely scanned group because of another group's scan and could distort
the very difference being compared. It passed several reviews, because each
checked that the code did what its rationale said, not whether the rationale
held for how this project's specimens are imaged.

- **Name when it distorts the result.** A proposal states the situations in
  which the step makes a comparison wrong — in particular groups that differ
  in specimen, treatment or imaging on purpose — and what the user loses. A
  proposal that lists only what the step corrects is incomplete.
- **Report rather than alter.** A difference between bundles (resolution,
  analysis settings, kink threshold, centerline) is shown as a warning that
  names it, and the data stay as measured, as GUI03 does for centerlines and
  kink thresholds.
- **One group's data never decide what is kept of another group.**
- **Off by default is not a defence.** An option still has to be right for
  every situation it is offered for, and its tooltip says when not to use it.
- **A review checks the premise, not only the code.** For each such step, write
  down the experimental situation its rationale assumes and check it against
  how this project's specimens are prepared and imaged; a rationale in a
  docstring or a document is a claim to check, not evidence.
- **When this rule is introduced or tightened, search the existing code for
  steps it covers in the same change.**

### 8.21 GUI03 statistics and `docs/gui03_statistics.md`

`docs/gui03_statistics.md` and its Japanese counterpart
`docs/gui03_statistics.ja.md` explain the statistics GUI03 reports — what one
sample is at each aggregation unit, the summary statistics and figures, the
frame corrections of contour length, and the between-group tests — quoting the
code that computes them and citing the published method each follows. They
exist for the same reason as the documents of §8.13 and §8.14. When a change
alters what one of the quoted symbols computes, updating both language
versions — prose **and** the quoted excerpts — is **part of that change**.

The trigger is a change to any symbol listed in `WATCHED_SYMBOLS` in
`scripts/check_gui03_docs.py`, which is the authoritative list (functions and
constants in `guis/GUI03_Fiber_Morphology_Statistics.py`,
`afm_nanofiber_analyzer/group_compare.py` and `afm_nanofiber_analyzer/measure.py`). The
documents follow the verified-excerpt contract of §8.13
(`scripts/doc_excerpts.py`), and every watched symbol must be quoted, so add a
symbol to `WATCHED_SYMBOLS` before quoting it and remove it when it is no
longer quoted. A reference is added only after its bibliographic record has
been checked against a source; what could not be checked is marked
`<!-- TODO(review): ... -->` (§4.4).

Enforced by `scripts/check_gui03_docs.py --staged` in `.githooks/pre-commit`,
`tests/test_gui03_docs.py` (CI), and the Claude Code hook
`.claude/hooks/doc_code_reminder.py`, on the same terms as §8.14. Refresh the
fingerprints with `.venv\Scripts\python.exe scripts\check_gui03_docs.py --update`
only after rereading the affected sections of both documents. The two
documents are a synchronized pair on the same terms as the README pair.

## 9. Index

Where each rule is. The rules themselves are stated once, in their section.

| Topic | Section |
|---|---|
| Edits, unverified statements, history in docs, README pair, Git, deletions, commit messages, exhaustive reviews | Editing Rules |
| Comment and docstring language, existing Japanese comments | §1–§4 |
| AI usage disclosure in `paper.md` | §5 |
| `PLUGIN_INFO`, UI strings, internal state keys | §6 |
| GUI plugin structure, shared helpers, verifying GUI changes | §7 |
| Preprocessing pipeline, `ProcParams`, `bg_method` | §8.1 |
| `.b2z` bundle contract and format versions | §8.2 |
| What each GUI reads | §8.3 |
| Long-running GUI work | §8.4 |
| Renames, imports, the launcher | §8.5 |
| Build and dependency helpers | §8.6 |
| `afm_nanofiber_analyzer/` public APIs (design notes in `docs/design_notes.md`) | §8.7 |
| Translation catalogs | §8.8 |
| Python interpreter spelling | §8.9 |
| Scratch files | §8.10 |
| Result-changing fixes, `CHANGELOG.md` and its translation | §8.11 |
| Claims about what the analysis detected | §8.12 |
| Algorithm documents | §8.13 |
| GUI04 measurement documents | §8.14 |
| Numbers in the documents, doc measurements | §8.15 |
| Readers measure the stored record | §8.16 |
| Claims in `paper.md` | §8.17 |
| Visual review of analysis changes | §8.18 |
| Running the tests | §8.19 |
| Steps that change what is compared | §8.20 |
| GUI03 statistics document | §8.21 |
