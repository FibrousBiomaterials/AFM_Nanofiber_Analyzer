# Fiber Morphology Statistics (GUI03)

Fiber Morphology Statistics compares the distribution of one fiber quantity
between groups of bundles. A group stands for one specimen, and the bundles in
it are aggregated together. What one sample is, how each statistic is computed
and which published method each test follows are explained in
[gui03_statistics.md](../gui03_statistics.md); the README describes every rule
in detail.

![Fiber Morphology Statistics with two groups: the height distributions of the
two groups with their summary statistics, and the calibrated image of the
selected bundle under the group list.](images/gui03.png)

## Registering bundles

Start **Fiber Morphology Statistics** from the launcher. **Analyze in GUI03**
in Image Preprocessor (GUI01) and **Open in GUI03** in Thumbnail Viewer (GUI05)
open it with their bundles registered in the first group.

- **Add Group** adds a group; **Delete Group** removes the selected one, and
  **↑** / **↓** move it.
- **Add Files** adds bundles to the selected group (the dialog takes several
  files at once); **Delete Files** removes the selected files from the list and
  **Clear All** removes everything. The files themselves stay where they are.
- Right-click a group to **Rename** it or **Change Color**. A file row can be
  dragged onto another group, or moved with **Move to Group** in its
  right-click menu.
- Selecting a file row shows that bundle's calibrated height image under the
  list.

With **Apply exclusions** and **Apply connection** checked (the default), the
exclusions and connections saved in Fiber Tracker (GUI04) are applied, so the
fibers aggregated are the ones shown there.

## Choosing what to compare

| Control | Choice |
|---|---|
| **Quantity** | `height`, `contour length`, `straightness`, `curvature` or `kink density`. |
| **Sample unit** | What one sample is: `pixel` (one skeleton pixel, for `height`), `fiber` (one fiber) or `image` (one scan). Only the units a quantity allows are offered. |
| **Plot** | `histogram`, `ECDF` or `box`. |
| **Curvature window (nm)** | The arc length over which `curvature` is measured; fibers shorter than it are left out, and the log says how many. |
| **Fibers at frame** | For `contour length`, how fibers reaching the edge of the scan are treated: `include`, `exclude`, `Miles-Lantuejoul` or `Kaplan-Meier`. |

**min**, **max** and **step** set the histogram range and bin width. **Y** sets
the vertical axis: `density`, `percent`, or **Hidden**, which plots the raw
counts without axis ticks. Samples outside the
range are reported in the log; the statistics always describe every sample.
**Display** draws the groups one under another (**Vertical Layout**) or on one
axes (**Overlay**), and **Show Statistics** writes the summary statistics into
the figure. **Fig. width**, **Fig. height** and the **Font Size** entries set
the figure.

## Creating the plot

Press **Create Plot**. **Stop** stops the measurement after the bundle being
measured; the figure and the statistics are then not updated. When the groups
change after a plot was made, a note beside the button says that it has to be
created again. **Save Image** saves the figure, and **Save Values** saves the
sampled values of each group as CSV files.

## Statistics and group comparison

![The Statistics window: the summary statistics of each group above, and below
them the comparison of the two groups with its notes.](images/gui03_stats.png)

**Statistics** opens a window of its own with two tables:

- the summary statistics of each group (median, interquartile range, mean,
  standard deviation, mode, and the numbers of samples, fibers and images),
  saved with **Save Statistics**;
- the comparison of every pair of groups (Mann-Whitney U as the primary test,
  Kolmogorov-Smirnov as a reference, and Cliff's delta as the effect size),
  saved with **Save comparison**.

The notes under the comparison say how to read it. The tests are run only at
the `fiber` and `image` units, and at `image` a group needs at least three
scans. Creating the plot again while the window is open refreshes it.

**Save Log** saves the log as a text file.
