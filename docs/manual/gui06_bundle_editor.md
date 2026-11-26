# Bundle Editor (GUI06)

Bundle Editor corrects an analysis by hand where the algorithms get it wrong.
It opens one bundle written by Image Preprocessor (GUI01), shows the result of
every analysis stage as a layer, lets the masks, the skeleton and the kinks be
edited, runs single stages again on the edited results, and saves the outcome
as a new bundle that records that a person changed it. The bundle the analysis
wrote is never overwritten. The README describes every rule in detail.

![Bundle Editor zoomed in on a kink: the kink chosen with Edit Kink is circled
in red, with the two arms that set its angle; the status line gives its
interior angle, and the layer list is on the right.](images/gui06.png)

## Opening a bundle

Press **Open Bundle…**, or **Open in GUI06** in Image Preprocessor (GUI01).
Only a bundle of the current format can be edited; an older one is shown, and
is analyzed again in GUI01 to be edited.

Some layers need the raw height data, which the bundle holds only when GUI01's
**Save original data during analysis** was on. Otherwise it is read from the
input file the bundle records, when a file of that name is in the bundle's
folder and has not changed since the analysis. Without it there is no
**Original data** layer, and **Ridge mask detection** and
**Background correction** cannot be run again.

## Layers

The layer list on the right holds, from the top: **Kinks** (bends the kink
rule measured but did not judge are drawn hollow), **Centerline**,
**Skeletonized image**, **Binarized image**, **Ridge mask**,
**Background-corrected image** and **Original data**.

- The checkbox of a row shows or hides the layer, and the slider sets its
  opacity. **Binarized image**, **Ridge mask** and **Original data** start
  hidden.
- Dragging a row changes the stacking order.
- A layer marked **Stale** is computed from a layer that has changed since,
  and its stage has not been run again.

The mouse wheel zooms, dragging with the right or middle button moves the
view, and **Show Whole Image** returns to the whole image.

## Editing

Click the name of a layer to edit it. **Kinks**, **Skeletonized image**,
**Binarized image** and **Ridge mask** can be edited; the other layers are
shown only. The tools available depend on the layer:

| Layer | Tools |
|---|---|
| **Ridge mask**, **Binarized image** | **Pencil** adds the pixels dragged over; **Eraser** removes them. |
| **Skeletonized image** | **Eraser** only, so that its lines stay one pixel wide. |
| **Kinks** | **Add Kink**, **Erase Kink**, **Move Kink**, **Edit Kink**. |

- **Brush size (px)** sets the width of the pencil and the eraser, 1 to 99
  pixels.
- Kinks are placed on the skeleton pixels of a fiber. **Erase Kink** also
  removes a hollow mark (a bend that was not judged).
- **Edit Kink**: click a kink to show, in red, the two end points that set its
  angle, and drag them along the skeleton. A kink the analysis found keeps the
  analysis's angle, with its end points drawn dashed, until one of them is
  moved.
- **Undo** (Ctrl+Z) and **Redo** (Ctrl+Y) step through the changes.
  **View only** makes clicks change nothing.

## Running stages again

The buttons after **Re-run** run one stage again on the results as they stand:

| Button | Computes from |
|---|---|
| **Ridge mask detection** | The original data. |
| **Background correction** | The original data, with the current ridge mask (the `tophat` method uses none). |
| **Binarization** | The background-corrected image. |
| **Skeletonization** | The binarized image. |
| **Kink detection** | The skeletonized and the background-corrected image. |

**Settings…** beside **Background correction** and **Binarization** changes
the settings of that stage. A stage whose result was changed by hand asks
before replacing it (**Undo** brings the changes back).

## Saving

- **Save As…** (Ctrl+Shift+S) saves a bundle and its `_param.json` under a
  name of your choice, by default the opened bundle's name followed by
  `_edited`, and then opens the saved bundle.
- **Save** (Ctrl+S) saves over the opened bundle, after asking, when that
  bundle is an edited one and something has changed. While a bundle written by
  the analysis is open, Ctrl+S opens **Save As…** instead.
- **Editor (optional)** records a name in the saved bundle as the person who
  edited it.
- Layers still marked **Stale** can be saved after a confirmation, and the
  saved bundle records which ones they are.

The saved bundle is read by the other tools and `cli.py` like any bundle.
**Save Log** saves the log as a text file.
