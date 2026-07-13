API reference
=============

The modules below make up ``lib/``, the analysis library shared by the GUI
plugins and the command-line interface. The grouping follows the stages of the
preprocessing pipeline: input, background calibration, segmentation,
skeletonization, kink detection, and per-fiber measurement.

Pipeline
--------

.. automodule:: lib.pipeline
   :members:
   :show-inheritance:

.. automodule:: lib.processed_image
   :members:
   :show-inheritance:

Input and output
----------------

.. automodule:: lib.afm_io
   :members:
   :show-inheritance:

.. automodule:: lib.gwy_io
   :members:
   :show-inheritance:

.. automodule:: lib.blosc2_io
   :members:
   :show-inheritance:

.. automodule:: lib.bundle_schema
   :members:
   :show-inheritance:

Analysis stages
---------------

.. automodule:: lib.bg_calibrator
   :members:
   :show-inheritance:

.. automodule:: lib.segmenter
   :members:
   :show-inheritance:

.. automodule:: lib.skeletonizer
   :members:
   :show-inheritance:

.. automodule:: lib.kink_detector
   :members:
   :show-inheritance:

.. automodule:: lib.imp_tools
   :members:
   :show-inheritance:

Measurement
-----------

.. automodule:: lib.measure
   :members:
   :show-inheritance:

.. automodule:: lib.fiber
   :members:
   :show-inheritance:

.. automodule:: lib.fiber_tracking_image
   :members:
   :show-inheritance:

Support modules
---------------

.. automodule:: lib.translator
   :members:
   :show-inheritance:

.. automodule:: lib.ui_tools
   :members:
   :show-inheritance:

Compatibility
-------------

.. automodule:: lib.bg_calibrator_shimadzu
   :members:
   :show-inheritance:
