# Welcome to py4dgeo-cloudcompare

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/dokempf/py4dgeo-cloudcompare/ci.yml?branch=main)](https://github.com/dokempf/py4dgeo-cloudcompare/actions/workflows/ci.yml)
[![Documentation Status](https://readthedocs.org/projects/py4dgeo-cloudcompare/badge/)](https://py4dgeo-cloudcompare.readthedocs.io/)
[![codecov](https://codecov.io/gh/dokempf/py4dgeo-cloudcompare/branch/main/graph/badge.svg)](https://codecov.io/gh/dokempf/py4dgeo-cloudcompare)

## Installation

The Python package `py4dgeo_cloudcompare` can be installed from PyPI:

```
python -m pip install py4dgeo_cloudcompare
```

## Development installation

If you want to contribute to the development of `py4dgeo_cloudcompare`, we recommend
the following editable installation from this repository:

```
git clone git@github.com:dokempf/py4dgeo-cloudcompare.git
cd py4dgeo-cloudcompare
python -m pip install --editable .[tests]
```

Having done so, the test suite can be run using `pytest`:

```
python -m pytest
```

## CloudCompare plugin

This package provides a Python M3C2 plugin for
[CloudCompare-PythonRuntime](https://tmontaigu.github.io/CloudCompare-PythonRuntime/getting_started.html#plugin).
Install the package into the Python environment used by CloudCompare:

```console
python -m pip install .
```

After restarting CloudCompare, run
**Compute M3C2 (py4dgeo)** from the Python action launcher or the Python
plugins menu. The configuration window starts even if fewer than two point
clouds are loaded and reports the current availability; computation requires
at least two. It runs in a separate PySide6 process and lets you assign the
reference, compared, and core point clouds. An existing selection is used only
to choose convenient defaults. The dialog also configures normal radii,
projection radius and depth, registration error, normal orientation, and robust
aggregation.

CloudCompare remains responsive while the window is open because the plugin
pumps CloudCompare's native Qt event loop while waiting for configuration. No
PySide6 module is imported into the CloudCompare process. The window's cloud
choices refresh as point clouds are added to or removed from the database.

CloudCompare sends only cloud IDs, display labels, and default selections to
the window. The window returns only the selected IDs and M3C2 parameters as
JSON. Point-cloud objects and coordinate data never leave CloudCompare. After
the window closes, the original CloudCompare action thread runs M3C2
synchronously and adds the result to the database there.

The result is added to CloudCompare as a new point cloud at the core-point
locations. It displays the signed M3C2 distance and also contains scalar
fields for the level of detection, cloud spreads and sample counts, computed
normal components, and selected normal radius. CloudCompare global shifts and
scales are respected when clouds use different local coordinate systems.
CloudCompare discovers the plugin through the `cloudcompare.plugins` package
entry point declared in `pyproject.toml`.

## Acknowledgments

This repository was set up using the [SSC Cookiecutter for Python Packages](https://github.com/ssciwr/cookiecutter-python-package).
