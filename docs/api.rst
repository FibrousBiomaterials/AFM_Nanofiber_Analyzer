API reference
=============

The modules below make up ``afm_nanofiber_analyzer/``, the analysis library shared by the GUI
plugins and the command-line interface. The grouping follows the stages of the
preprocessing pipeline: input, background calibration, segmentation,
skeletonization, kink detection, and per-fiber measurement.

Pipeline
--------

.. automodule:: afm_nanofiber_analyzer.pipeline
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.processed_image
   :members:
   :show-inheritance:

Input and output
----------------

.. automodule:: afm_nanofiber_analyzer.afm_io
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.gwy_io
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.gwy_convert
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.blosc2_io
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.bundle_schema
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.stripe_noise
   :members:
   :show-inheritance:

Analysis stages
---------------

.. automodule:: afm_nanofiber_analyzer.bg_calibrator
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.segmenter
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.skeletonizer
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.centerline
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.kink_detector
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.imp_tools
   :members:
   :show-inheritance:

Measurement
-----------

.. automodule:: afm_nanofiber_analyzer.measure
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.fiber
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.fiber_tracking_image
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.fiber_connector
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.fiber_selection
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.connect_selection
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.group_compare
   :members:
   :show-inheritance:

Editing bundles by hand
-----------------------

.. automodule:: afm_nanofiber_analyzer.bundle_edit
   :members:
   :show-inheritance:

Support modules
---------------

.. automodule:: afm_nanofiber_analyzer.translator
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.ui_tools
   :members:
   :show-inheritance:

.. automodule:: afm_nanofiber_analyzer.plugin_launch
   :members:
   :show-inheritance:

Compatibility
-------------

.. automodule:: afm_nanofiber_analyzer.bg_calibrator_shimadzu
   :members:
   :show-inheritance:
