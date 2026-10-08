Contributing
============

Create a branch in your checkout, then prepare the development environment::

    pixi install --locked
    pixi run demo

Before submitting a pull request, run::

    pixi run format
    pixi run lint
    pixi run test
    pixi run smoke
    pixi run build
    pixi run docs

Tests run with Qt's offscreen platform and a simulated detector, without EPICS.
Include regression tests for behavioral changes and update the documentation
when changing public APIs. Describe any beamline validation still needed.

Update dependencies in ``pyproject.toml`` and run ``pixi update`` to regenerate
``pixi.lock``. Commit both files together after running the checks.
