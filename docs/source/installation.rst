Installation
============

Install Pixi, then run from the repository::

    pixi install --locked
    pixi run demo

The lockfile targets Linux x86-64 and Python 3.12. For other environments,
install the Python package with Python 3.11 or newer::

    python -m pip install .

For development with pip::

    python -m pip install -e '.[dev,docs]'
