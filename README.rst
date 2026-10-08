========
xpilatus
========

Qt monitor for Pilatus detectors, with live images, rectangular and polygon
ROIs, acquisition controls, and optional monochromator controls.
BSD-3-Clause licensed.

Run with Pixi
-------------

Install `Pixi <https://pixi.sh>`__, then from this checkout::

    pixi install --locked
    pixi run demo

The demo uses a simulated detector and requires a graphical desktop. For a
headless startup check, use ``pixi run smoke``. The committed environment targets
Linux x86-64 with Python 3.12. The Python package requires Python 3.11 or newer.

Beamline use
------------

Keep your existing ophyd detector and monochromator definitions. In a running
Qt application::

    from pilatus_tools.widgets.widget_pilatus import UIPilatusMonitor

    monitor = UIPilatusMonitor(
        detector_dict={"Pilatus 100k": {"device": pilatus}},
        hhm=hhm,  # optional; omit for detector-only operation
        polygon_roi_path="/path/to/pilatus_polygon_roi.json",  # optional
    )
    monitor.show()

The detector must provide ophyd-style ``get``, ``put``, ``subscribe``, and
``clear_sub`` signals for ``cam`` acquisition/settings, ``image.array_data``,
``roi1``–``roi4`` coordinates, and ``stats1``–``stats4.total``, plus
``get_roi_coords(index)``. The monochromator provides ``energy.user_readback``
and ``energy.user_setpoint``. Install your beamline's device packages separately;
EPICS connections and device construction remain with the host application.

The default image shape is ``(195, 487)``; pass ``image_shape=(rows, columns)``
for another shape. Display orientation matches the original monitor. Opening the
monitor reads existing acquisition settings without changing them. Close the
widget to stop rendering and release subscriptions; create a new instance to
reopen it.

Polygon configuration is optional. Supply ``polygon_roi_path`` or set
``XPILATUS_POLYGON_ROI_PATH`` to enable persistence. To keep the former ISS
configuration, explicitly pass
``/nsls2/data/iss/legacy/xf08id/settings/json/pilatus_polygon_roi.json``.
The file is a JSON mapping from names to lists of ``[x, y]`` vertices; for example::

    {"main": [[10, 20], [40, 20], [40, 60]]}

Performance and development
---------------------------

Frames arrive through subscriptions and only the newest frame is displayed at
most once per 50 ms (20 fps). Set ``refresh_interval_ms`` to tune this limit.
Idle refreshes perform no detector reads or image redraws. Manual intensity
limits avoid unnecessary automatic level calculation. Counts and settings also
use subscriptions, with widget updates dispatched to the Qt thread.

Development tasks::

    pixi run test
    pixi run lint
    pixi run format-check
    pixi run build
    pixi run docs

Dependencies are declared in ``pyproject.toml`` and resolved in ``pixi.lock``.
Run ``pixi update`` to refresh the lockfile, then rerun the checks above.
The regression tests and demo use a simulated detector; real IOC behavior and
hardware acquisition require validation at the beamline.

For pip-based installations from a checkout::

    python -m pip install .
    python -m pip install -e '.[dev,docs]'
