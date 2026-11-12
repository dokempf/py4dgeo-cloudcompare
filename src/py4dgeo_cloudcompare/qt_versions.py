"""CloudCompare plugin for reporting the compile-time and runtime Qt versions."""

import pycc


def report_qt_versions() -> None:
    """Print the Qt versions used to build and run CloudCompare."""

    print(f"Qt compile-time version: {pycc.QT_VERSION_STR}")
    print(f"Qt runtime version: {pycc.qtVersion()}")


class QtVersionsPlugin(pycc.PythonPluginInterface):
    """Expose Qt version information as a separate CloudCompare action."""

    def __init__(self) -> None:
        super().__init__()

    def getActions(self):
        return [pycc.Action(name="Report Qt Versions", target=report_qt_versions)]
