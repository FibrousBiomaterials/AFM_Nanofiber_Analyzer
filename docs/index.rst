AFM Nanofiber Analyzer
======================

A GUI and command-line toolkit for analyzing nanofiber morphology from atomic
force microscopy (AFM) height images. It reads AFM text/CSV exports and native
Gwyddion ``.gwy`` files, removes the instrument background, segments and
skeletonizes the fibers, detects kinks, and reports per-fiber statistics such as
length, height, and kink geometry.

These pages document the analysis library in ``lib/``, which is the layer shared
by the interactive tools in ``guis/`` and by the ``cli.py`` batch interface. The
graphical and command-line front ends call the same pipeline and measurement
routines, so equivalent runs produce identical numerical results.

Installation, usage, the analysis pipeline, and the ``.b2z`` bundle format are
described in the project README; this site covers the module-level API only.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   api
