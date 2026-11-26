# Format Converter (GUI00)

Format Converter turns AFM files that this software cannot read into Gwyddion
`.gwy` files, which Image Preprocessor (GUI01) then analyzes. GUI01 reads text
exports (`.txt`) and `.gwy` files, so a scan saved only in an instrument's own
format is converted here first.

![Format Converter after converting a folder: two files listed with the status
Converted and the Gwyddion module that read them, and the log of the
run.](images/gui00.png)

The example folder holds two Gwyddion Simple Field (`.gsf`) files written from
the scans bundled in `testdata/`.

## Before you start

The conversion runs Gwyddion's file readers through the program `gwyconvert`
of the optional package `gwyddionpy-converter`. The `run_venv` and `run_conda`
launchers install it, and print a message when it cannot be installed. In an
environment set up another way, install it with

```
python -m pip install "gwyddionpy-converter>=0.1.0,<0.2"
```

Without it the window still opens, and **Start Conversion** shows this command.

## Steps

1. Start **Format Converter** from the launcher.
2. Press **Select Folder** and choose the folder that holds the measurement
   files. Every file directly inside it is listed, except those with the
   extensions `.txt`, `.csv`, `.gwy`, `.b2z`, `.json` and `.npy`, which this
   software reads or writes itself. A file whose converted `.gwy` already
   exists is listed as **Already converted (.gwy exists)**.
3. Press **Start Conversion**. Each file is converted into
   `<original file name>_converted.gwy` in the same folder, so `scan.ssp`
   becomes `scan.ssp_converted.gwy`. The table shows each file's outcome and
   the Gwyddion module that read it, and the log ends with the numbers of files
   converted, skipped and not converted.
4. Press **Open in GUI01** to open the folder in Image Preprocessor, which lists
   every `.txt` and `.gwy` file in it, the converted files among them. The
   button is unavailable while no folder is selected and while a conversion
   runs.

## Outcomes

| Status | Meaning |
|---|---|
| **Not converted yet** | Listed, and not yet converted in this window. |
| **Converted** | The `.gwy` file was written. |
| **Already converted (.gwy exists)** | The `.gwy` file already existed, so the file was skipped. |
| **Could not convert** | No `.gwy` file was written; **Details** and the log give the reason. |

A converted file is kept only when it holds a channel with a length unit.
Gwyddion also opens ordinary images such as PNG screenshots, which would
otherwise be analyzed as height maps; such a file is reported as
**Could not convert** with the reason "no channel with a length unit". A failed
conversion leaves no `.gwy` file, so it is attempted again on the next run.

**Save Log** saves the log as a text file. `cli.py convert` runs the same
conversion from the command line.
