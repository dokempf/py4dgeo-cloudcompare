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
**Compute M3C2 (py4dgeo, Tkinter)** from the Python action launcher or the Python
plugins menu. The configuration window starts even if fewer than two point
clouds are loaded and reports the current availability; computation requires
at least two. It lets you assign the reference, compared, and core point
clouds. An existing selection is used only to choose convenient defaults. The
dialog also configures normal radii, projection radius and depth, registration
error, normal orientation, and robust aggregation.

The Tkinter window and M3C2 calculation run in the CloudCompare process. While
the window is open, the action cooperatively services both the Tk and
CloudCompare event queues and refreshes its list of loaded clouds.

The result is added to CloudCompare as a new point cloud at the core-point
locations. It displays the signed M3C2 distance and also contains scalar
fields for the level of detection, cloud spreads and sample counts, computed
normal components, and selected normal radius. CloudCompare global shifts and
scales are respected when clouds use different local coordinate systems.
CloudCompare discovers the plugin through the `cloudcompare.plugins` package
entry point declared in `pyproject.toml`.

py4dgeo's runtime log is written to the operating system's temporary directory
instead of CloudCompare's potentially read-only working directory. If M3C2
raises an exception, the plugin also writes the complete, untruncated traceback
there and prints its path in CloudCompare's console.

## Acknowledgments

This repository was set up using the [SSC Cookiecutter for Python Packages](https://github.com/ssciwr/cookiecutter-python-package).
