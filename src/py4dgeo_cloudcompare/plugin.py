"""Minimal CloudCompare Python plugin."""

import pycc


def hello_world() -> None:
    """Print a greeting in CloudCompare's Python console."""
    print("Hello from Python")


class HelloWorldPlugin(pycc.PythonPluginInterface):
    """Expose a Hello World action in CloudCompare."""

    def __init__(self) -> None:
        super().__init__()

    def getActions(self):
        return [pycc.Action(name="Hello World", target=hello_world)]
