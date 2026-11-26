# Image Preprocessor (GUI01)

Image Preprocessor analyzes AFM height images. Each scan goes through
background calibration, binarization, skeletonization and kink detection, and
the result is saved as a `.b2z` bundle, which every other tool reads. What each
stage computes, and what each setting changes, is explained in
[algorithms.md](../algorithms.md).

![Image Preprocessor after analyzing a folder of two scans: the file list with
the scan size of each file, and the Original, Calibrated, Binarized and
Skeletonized images of the selected scan with its kink points
overlaid.](images/gui01.png)

## Opening a folder

Start **Image Preprocessor** from the launcher and press **Select Folder**.
Every `.txt` and `.gwy` file directly inside the folder is listed in the file
list. GUI00's **Open in GUI01** opens a folder the same way.

The file list has one row per file:

| Column | Content |
|---|---|
| **File Name** | The input file. Selecting this cell shows the file in the preview. |
| **X (µm)**, **Y (µm)** | The scan size, editable (see below). |
| **Stripe noise** | The share of scan lines displaced by feedback glitches (see below). |
| **Scan lines** | The scan lines to analyze, editable; empty means the whole image. |
| **Status** | **Not Analyzed**, **Analyzing** or **Analyzed**. |
| **Processing Time** | Seconds the last analysis took. |

A file whose bundle already exists is listed as **Analyzed**.

## Setting the scan size

Every length the software reports is computed from the scan size, so each file
needs one before it is analyzed. When the folder is opened it is filled in
automatically: from the bundle for a file already analyzed, otherwise from the
file's header (the `SizeX` / `SizeY` of a Shimadzu export, the size comments of
a Gwyddion text export, or the channel size of a `.gwy` file). A file with
neither is left empty, and the log says how many are.

To set it by hand:

- Type into the **X (µm)** and **Y (µm)** cells, or paste a column of values
  from a spreadsheet. A blank Y means the scan is square (Y = X).
- Or type X and Y into the entries under the list and press
  **Apply to selected** or **Apply to all**.
- Or press **Load scale table (CSV)** and choose a CSV file with a header row,
  a `filename` column, and either a `scale_um` column or the two columns
  `scale_x_um` and `scale_y_um`. File names match with or without the
  extension, for example:

  ```
  filename,scale_x_um,scale_y_um
  TunicateACTOCCNF.txt,5,5
  ```

An analysis does not start while a file to be analyzed has no scan size; the
error lists those files.

## Analyzing

1. Press **Settings** to check the analysis settings (next section). The
   defaults suit most scans.
2. Press **Analyze All**, or select rows and press **Analyze**.
3. The progress bar under the log shows the file and the stage being analyzed.
   **Stop** stops the batch after the current file.

When **Overwrite Analyzed Files** is cleared, files already analyzed are
skipped, and the log says so for each of them; when it is checked, they are
analyzed again.

Each analysis writes two files beside its input:

- `<input file name without extension>.b2z`: the bundle holding the analysis
  results.
- `<input file name without extension>_param.json`: the settings it was
  analyzed with.

After each file the log may warn that the background calibration may have
lowered the fiber heights, naming the setting to try instead, or that the
pixel noise is large against the fiber height. The README explains both
warnings.

## Settings

![The Settings dialog: the analysis settings grouped by stage, each with its
description; the settings the selected background method does not use are
dimmed.](images/gui01_settings.png)

**Settings** opens the analysis settings, grouped by stage. A change applies
from the next analysis on. Only the settings that the selected `bg_method`
uses can be edited; the others are dimmed.

| Button | Action |
|---|---|
| **Save Settings** | Saves the settings to a JSON file. |
| **Load Settings** | Loads settings from a JSON file. The `_param.json` written beside a bundle is such a file, so an earlier analysis can be repeated with its settings. |
| **Save Current Values as Defaults** | Makes the current values the ones the window starts with (asks first). |
| **Restore Initial Values** | Returns every value in the dialog to the software's defaults (asks first). The values the window starts with change only with **Save Current Values as Defaults**. |

The dialog also holds the step height counted as a feedback glitch
(**Stripe-noise screening**) and **Save original data during analysis**, which
stores the raw height image in the bundle as well.

## Looking at the results

Selecting a cell in the **File Name** column shows that file on the right:
the raw image (**Original**), the background-corrected height
(**Calibrated**), the binarized fibers (**Binarized**) and the skeleton
(**Skeletonized**).

- **Overlay** marks points on the skeleton: end points (`EP`, blue), branch
  points (`BP`, red), kink points (`KP`, cyan) or decomposition points
  (`DP`, orange).
- **vmin** and **vmax** set the height range of the color scale.
  **Show Title**, **Show Scale**, **Axis Tick Unit** and **Font Sizes…**
  change the figure.
- **Save Image** saves the preview with its four images; **Individual View**
  opens one stage in a window of its own, with its own color range.

## Scans with stripe noise

When the feedback loop of the microscope is briefly lost, whole scan lines are
displaced. Several analysis steps take a threshold from statistics over the
whole image, so one such band can affect detection in the rest of the image.
When a folder is opened, every scan is screened for them:

- **Stripe noise** shows the share of scan lines affected; a scan with any is
  highlighted.
- The log lists the scan-line ranges free of glitches.
- The affected lines are shaded in cyan on the **Original** image.

The screening only reports; it changes nothing that is analyzed. To leave the
disturbed lines out, analyze only the clean ranges:

![The file list after Split by stripe noise: the higher-plant scan is listed as
two entries, scan lines 0-817 and 834-1024, each not yet analyzed, and the
affected scan lines are shaded on the Original image.](images/gui01_split.png)

1. Select the scan and press **Split by stripe noise**. With no row selected,
   every scan with stripe noise is split. Each clean range becomes an entry of
   its own, with its range in **Scan lines** and its own Y size.
2. Adjust the ranges if needed by editing the **Scan lines** cells. Scan lines
   are numbered from 0, and `473-696` covers lines 473 to 695; several ranges
   are separated by commas and must not overlap. An empty cell analyzes the
   whole image.
3. Analyze the entries. Each range is analyzed as an image of its own and saved
   as `<input file name without extension>_r<start>-<end>.b2z`.

**Undo split** returns the entries to one entry for the whole image, and asks
whether to delete the bundles the split entries produced (keeping them is the
default).

## Opening the results in other tools

| Button | Opens |
|---|---|
| **Open in GUI02**, **Open in GUI04**, **Open in GUI06** | The bundle shown in the preview, in Plot Profiler, Fiber Tracker or Bundle Editor. |
| **Analyze in GUI03** | Fiber Morphology Statistics, with every bundle in the folder registered in its first group. |
| **Open in GUI05** | Thumbnail Viewer, with every bundle in the folder. |
| **Open Output Folder** | The folder in the file manager. |

Each press opens a new window. The buttons are unavailable while an analysis
runs, the two at the head of the list while no file has been analyzed, and the
three above the preview while the preview shows nothing.

**Save Log** saves the log as a text file. `cli.py process` runs the same
analysis from the command line.
