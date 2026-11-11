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

## Acknowledgments

This repository was set up using the [SSC Cookiecutter for Python Packages](https://github.com/ssciwr/cookiecutter-python-package).
