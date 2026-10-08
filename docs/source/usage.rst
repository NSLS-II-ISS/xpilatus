Usage
=====

Run ``pixi run demo`` for an interactive simulation, or ``pixi run smoke`` for a
headless startup check.

In an existing Qt application, construct the widget with your detector::

    from pilatus_tools.widgets.widget_pilatus import UIPilatusMonitor

    monitor = UIPilatusMonitor({"Pilatus 100k": {"device": pilatus}}, hhm=hhm)
    monitor.show()

The monochromator is optional. To load existing polygon ROIs, supply
``polygon_roi_path="/path/to/pilatus_polygon_roi.json"`` or set
``XPILATUS_POLYGON_ROI_PATH``. The JSON maps polygon names to ``[x, y]`` vertices.
Close the monitor to release its subscriptions before discarding it.

See the repository README for the detector interface, display options, and
migration notes.
