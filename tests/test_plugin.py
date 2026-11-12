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


def test_hello_world_plugin(monkeypatch, capsys):
    pycc = ModuleType("pycc")
    pycc.PythonPluginInterface = PythonPluginInterface
    pycc.Action = Action
    monkeypatch.setitem(sys.modules, "pycc", pycc)

    plugin_module = importlib.import_module("py4dgeo_cloudcompare.plugin")
    plugin = plugin_module.HelloWorldPlugin()
    actions = plugin.getActions()

    assert len(actions) == 1
    assert actions[0].name == "Hello World"

    actions[0].target()
    assert capsys.readouterr().out == "Hello from Python\n"
