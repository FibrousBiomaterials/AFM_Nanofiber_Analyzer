# Thumbnail Viewer (GUI05)

Thumbnail Viewer shows the background-corrected height images of many `.b2z`
bundles side by side, to check a series of analyses at a glance, and saves them
as A4 sheets. It writes nothing to the bundles.

![Thumbnail Viewer with six bundles: each thumbnail has its file name above it
and a scale bar and a color bar below it; the two strips are the higher-plant
scan analyzed as two scan-line ranges.](images/gui05.png)

## Adding bundles

Start **Thumbnail Viewer** from the launcher, or press **Open in GUI05** in
Image Preprocessor (GUI01) to open the bundles of its folder. Then:

- **Add Folder** adds the bundles directly inside a folder.
- **Add Files** adds the bundles chosen in the dialog.
- Files and folders can also be dropped onto the gallery. This needs the
  `tkinterdnd2` package; without it the window opens, and adding works through
  the two buttons.

A bundle already in the gallery is skipped, and a dropped file that is not a
`.b2z` is ignored; the log gives both numbers. A bundle that cannot be read is
listed under **Files that could not be read** below the pages, with the
reason.

## The gallery

Each thumbnail is drawn with the shape of its scan, so a rectangular scan or a
scan-line range appears as the strip it is. Its file name stands above it, and
below it:

- a scale bar, aligned with the image's left edge (none for a bundle that
  records no scan size);
- a color bar, the colors between the two heights its ends stand for.

**Scale bar** and **Colorbar** turn them off, and **Font Sizes…** sets the
size of the three texts, on the screen and on the saved sheet alike.

The gallery is drawn as the pages of the sheet it will save. **Paper**
(**A4 portrait** or **A4 landscape**), **Columns** and **Rows** set the page,
and **Display** sets how large the pages are drawn: **Fit width**,
**Whole page**, or a percentage of the paper's real size. Ctrl with the mouse
wheel changes the size too.

## Selecting, ordering and removing

- Click a thumbnail to select it, Ctrl+click to add to the selection,
  Shift+click to select a range, and Ctrl+A to select all.
- Thumbnails stand in the order they were added. Drag one to move it, together
  with the other selected ones. **Sort** puts the gallery once into the order
  of the file names (**By Name**) or of the files' modification times, oldest
  first (**By Date**).
- **Delete** and **Delete All** take thumbnails out of the window. The files
  stay where they are.

## Color range

Each image is colored over a range chosen for it automatically, so the fibers
of every image are visible, but the same color can mean different heights in
two thumbnails. To set the range, select thumbnails, enter **vmin** and
**vmax** (nm), and press Enter. With all thumbnails selected (Ctrl+A), every
image gets one range and the colors can be compared.

When the selected images differ in a value, its entry is blank; an entry left
blank keeps each image's own value, so one end of the range can be set alone.
**Auto** returns the selected images to their automatic range.

## Saving a sheet

**Save Sheet** saves the pages as they appear on the screen. A PDF holds all
pages in one file; a PNG holds one page, and with more than one page `_p01`,
`_p02`, … is added to the chosen name. The images are read again from the
bundles for the sheet, not enlarged from the thumbnails.

The window has no print command. With **Open after saving** checked, the saved
sheet opens in the system's default application (the first page of a PNG
series), and it is printed from there.

## Opening bundles in other tools

| Button | Opens the selected bundles in |
|---|---|
| **Open in GUI02** | Plot Profiler, one window per bundle. |
| **Open in GUI03** | Fiber Morphology Statistics, in one window with all of them in one group. |
| **Open in GUI04** | Fiber Tracker, one window per bundle. |

With four or more bundles selected, **Open in GUI02** and **Open in GUI04** ask
first, since each opens a window of its own.

**Save Log** saves the log as a text file.
