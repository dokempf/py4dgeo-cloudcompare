import importlib
import sys
from types import ModuleType


class PythonPluginInterface:
    pass


class Action:
    def __init__(self, *, name, target, icon=None):
        self.name = name
        self.target = target
        self.icon = icon


def test_qt_versions_plugin_reports_compile_time_and_runtime_versions(
    monkeypatch, capsys
):
    pycc = ModuleType("pycc")
    pycc.PythonPluginInterface = PythonPluginInterface
    pycc.Action = Action
    pycc.QT_VERSION_STR = "6.8.3"
    pycc.qtVersion = lambda: "6.8.2"
    monkeypatch.setitem(sys.modules, "pycc", pycc)
    sys.modules.pop("py4dgeo_cloudcompare.qt_versions", None)

    plugin_module = importlib.import_module("py4dgeo_cloudcompare.qt_versions")
    actions = plugin_module.QtVersionsPlugin().getActions()

    assert len(actions) == 1
    assert actions[0].name == "Report Qt Versions"

    actions[0].target()
    assert capsys.readouterr().out == (
        "Qt compile-time version: 6.8.3\n"
        "Qt runtime version: 6.8.2\n"
    )
