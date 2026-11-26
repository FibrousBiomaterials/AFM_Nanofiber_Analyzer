# Plot Profiler (GUI02)

Plot Profiler extracts a height profile along a line drawn on an AFM height
image, for example along a fiber or across it.

![Plot Profiler with a bundle open: points placed along a fiber on the height
map, and the height profile along the line through them.](images/gui02.png)

## Opening a file

Press **Browse** and choose a file, or press **Open in GUI02** in Image
Preprocessor (GUI01) or Thumbnail Viewer (GUI05) to open a bundle directly.
Plot Profiler reads:

- `.b2z` bundles, whose background-corrected height (`calibrated`) it shows;
- `.npy` arrays, text and CSV exports (`.txt`, `.csv`);
- Gwyddion `.gwy` files. For a file with several channels, **Channel** selects
  the one shown.

**Scale (µm)** X and Y hold the scan size, filled in from the bundle, the
file's header or the `.gwy` channel. A file that records none (an `.npy`
array, for instance) keeps the values already in the entries, so enter its size
before measuring. A blank Y means a square scan (Y = X). The **µm** / **nm**
buttons change only the unit the axes are labelled in.

## Drawing a profile

1. Right-click on the height map to place the first point, and right-click
   again for each further point. From the second point on, the profile along
   the line through all points is drawn on the right.
2. **Undo Last Point** removes the last point; **Clear All Points** removes
   them all.
3. The tools under the height map pan and zoom it; **Reset** returns to the
   whole image.

How each height of the profile is obtained:

- Each sample takes the value of the pixel that contains it, so no height is
  interpolated between pixels.
- **Line Width (pixels)** is an odd number of pixels: one sample on the line,
  and whole pixels to either side. The width is drawn as a blue band on the
  height map.
- With a width above one, **Calculation Method** combines the samples across
  the line: **Maximum** (picks up the top of a fiber), **Minimum** (shows the
  background level) or **Average** (smooths noise). Samples beyond the image
  edge are left out.

**Auto**, **vmin** and **vmax** set the color range of the height map. The
**Font Size** entries set the text sizes of the height map; the **Axis Label**
and **Ticks** sizes apply to the profile as well. Entries take effect when
Enter is pressed.

## Saving

| Button | Saves |
|---|---|
| **Save Image** (under the height map) | The height map with the line. |
| **Save as CSV** | The profile: `Length` in the unit of the axes and `Height (nm)`. |
| **Save Image** (under the profile) | The profile figure. |
| **Create Graph with Layout Adjustment** | Opens a window that draws the profile with a chosen width, height, axis-label and tick size, tick direction and grid, and saves it. |

Nothing is written without one of these buttons.
