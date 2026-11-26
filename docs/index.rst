AFM Nanofiber Analyzer
======================

A GUI and command-line toolkit for analyzing nanofiber morphology from atomic
force microscopy (AFM) height images. It reads AFM text/CSV exports and native
Gwyddion ``.gwy`` files, removes the instrument background, segments and
skeletonizes the fibers, detects kinks, and reports per-fiber statistics such as
length, height, and kink geometry.

These pages document the analysis library in ``afm_nanofiber_analyzer/``, which is the layer shared
by the interactive tools in ``guis/`` and by the ``cli.py`` batch interface. The
graphical and command-line front ends call the same pipeline and measurement
routines, so equivalent runs produce identical numerical results.

:doc:`algorithms` explains what the four preprocessing stages do and why, with
references into the source; :doc:`gui04_measurements` explains, with the code,
how GUI04 places each fiber's centerline and computes the values it displays;
:doc:`gui03_statistics` explains, with the code and the published methods it
follows, the summary statistics and between-group tests GUI03 reports;
:doc:`api` documents each module's contract.
Installation, usage, and the ``.b2z`` bundle format are described in the
project README.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   manual/overview
   manual/gui00_format_converter
   manual/gui01_image_preprocessor
   manual/gui05_thumbnail_viewer
   manual/gui02_plot_profiler
   manual/gui06_bundle_editor
   manual/gui04_fiber_tracker
   manual/gui03_fiber_morphology_statistics
   algorithms
   gui04_measurements
   gui03_statistics
   api
