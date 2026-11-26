# Fiber Tracker (GUI04)

Fiber Tracker lists every fiber of a bundle with its measured values, shows
each fiber on the height image, and lets the fibers be curated — fragments
joined into whole fibrils and unwanted objects excluded — before Fiber
Morphology Statistics (GUI03) aggregates them. How each value is computed is
explained in [gui04_measurements.md](../gui04_measurements.md), and the README
describes every rule in detail.

![Fiber Tracker with a bundle open: the fiber list with the values of each
fiber, and the height image with every fiber numbered in its box; the selected
fiber is framed in yellow.](images/gui04.png)

## Opening a bundle

Press **Open File**, or **Open in GUI04** in Image Preprocessor (GUI01) or
Thumbnail Viewer (GUI05). One bundle is open at a time, and the window title
names it. **Scale (µm)** holds the scan size the bundle records; a size entered
there measures the lengths at that size instead, and the log says so.

## The fiber list and the overview

Each row of **Fiber List** is one fiber. Resting the pointer on a column
heading explains the value, and **About the Measurements** lists all of them.
A `≥` in front of a length marks a lower bound: the fiber continues past what
was measured, at the edge of the scan or at a cut.

Selecting a row frames the fiber in the **AFM Overview**. Shift+click selects a
range of rows and Ctrl+click adds rows one at a time.

- **Height** / **Color-coded fibers** chooses how the overview is drawn.
- **Auto**, **vmin** and **vmax** set the color range; the **Font Size**
  entries set the text sizes.
- The tools under the overview pan and zoom it. **Reset** returns to the whole
  image, **Zoom to Selection** zooms in until the selected fiber fills the
  view, and **Numbers & Boxes** shows or hides the fiber numbers and dashed
  boxes (the yellow frame of the selection stays).
- **Save Image** saves the overview as it is drawn, zoom included.
- **Individual View** opens the selected fiber in windows of its own: the
  enlarged image with its centerline and kinks, and its height profile, each
  with its own display settings and **Save Image**.
- **Save as CSV** saves the values of the fibers in the list.

**Height Filter** keeps, of each fiber, the stretches whose height lies
between **Minimum** and **Maximum** (nm). Checking or clearing it applies at
once.

## Joining fragments (Connection)

The skeleton is split at crossings and branches, so one fibril can be listed as
several fragments. They can be joined:

| Button | Action |
|---|---|
| **Auto Connect** | Searches for fragments whose position, direction and height continue each other, and joins them. The result is kept; it asks before replacing an existing connection. |
| **Auto Connect Settings** | The thresholds of the search, used at the next **Auto Connect**. |
| **Connect Manually** | For the selected fiber, lists the candidates near its ends, with whether the automatic search would accept each, and joins the one chosen. |
| **Disconnect** | Lists every junction, shows the chosen one in the overview, and cuts it or all of them. |
| **Undo** | Undoes the last connection operation (an automatic run, a manual join or a disconnection). |

## Excluding fibers (Exclusion)

| Button | Action |
|---|---|
| **Exclude selected** | Takes the selected fibers out of the list, the overview and the CSV. |
| **Exclude non-isolated** | Excludes every fiber whose whole length could not be measured: one that touches another fiber, reaches the edge of the scan, or has a continuation the connector finds. Disconnect all junctions first. In a dense sample few fibers, or none, may remain; that is the result, not a fault. |
| **Undo last** | Undoes the last exclusion; pressing it again walks further back. |
| **Select by Region** | Drag a rectangle on the overview to select every fiber it touches (Ctrl adds to the selection; Esc cancels). Check the frames, then press **Exclude selected**. |
| **Exclusion settings** | Lists the exclusions, and restores any one or all of them. |

## Saving the curation

**Save Curation** writes the exclusions and the connection together, to
`<bundle name>_excluded.json` and `<bundle name>_connect.json` beside the
bundle. Fiber Morphology Statistics reads both files (its **Apply exclusions**
and **Apply connection**), so it aggregates the fibers this window shows. The
button can be pressed only while there are unsaved changes, and leaving a bundle
with unsaved changes asks whether to save them.

**Save Log** saves the log as a text file.
