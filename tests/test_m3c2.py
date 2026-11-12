import importlib
import sys
from types import ModuleType

import numpy as np
import pytest


class PythonPluginInterface:
    pass


class Action:
    def __init__(self, *, name, target, icon=None):
        self.name = name
        self.target = target
        self.icon = icon


class PointCloud:
    pass


@pytest.fixture
def m3c2_module(monkeypatch):
    pycc = ModuleType("pycc")
    pycc.PythonPluginInterface = PythonPluginInterface
    pycc.Action = Action
    pycc.ccPointCloud = PointCloud
    pycc.PointCoordinateType = np.float32
    pycc.ScalarType = np.float32
    pycc.GetInstance = lambda: None
    monkeypatch.setitem(sys.modules, "pycc", pycc)
    sys.modules.pop("py4dgeo_cloudcompare.m3c2", None)
    return importlib.import_module("py4dgeo_cloudcompare.m3c2")


def test_parse_normal_radii(m3c2_module):
    assert m3c2_module.parse_normal_radii("0.5, 1; 2") == (0.5, 1.0, 2.0)

    for invalid in ("", "one", "0", "-1", "nan"):
        with pytest.raises(ValueError):
            m3c2_module.parse_normal_radii(invalid)


def test_global_points_applies_cloudcompare_shift_and_scale(m3c2_module):
    class Shift:
        x, y, z = (-100.0, 50.0, -2.0)

    class Cloud:
        def points(self):
            return np.array([[2.0, 4.0, 6.0]], dtype=np.float32)

        def getGlobalShift(self):
            return Shift()

        def getGlobalScale(self):
            return 2.0

    # global = local / scale - shift
    np.testing.assert_allclose(
        m3c2_module._global_points(Cloud()), [[101.0, -48.0, 5.0]]
    )


def test_loaded_point_clouds_walks_database_tree(m3c2_module):
    class Group:
        def __init__(self, *children):
            self.children = children

        def getChildrenNumber(self):
            return len(self.children)

        def getChild(self, index):
            return self.children[index]

    cloud1 = PointCloud()
    cloud1.getChildrenNumber = lambda: 0
    cloud2 = PointCloud()
    cloud2.getChildrenNumber = lambda: 0
    root = Group(Group(cloud1), cloud2)
    app = type("App", (), {"dbRootObject": lambda self: root})()

    assert m3c2_module._loaded_point_clouds(app) == [cloud1, cloud2]


def test_selection_only_controls_cloud_defaults(m3c2_module):
    clouds = [PointCloud(), PointCloud(), PointCloud()]
    for identifier, cloud in enumerate(clouds, start=10):
        cloud.getUniqueID = lambda identifier=identifier: identifier

    app = type(
        "App",
        (),
        {"getSelectedEntities": lambda self: [clouds[2], clouds[0]]},
    )()
    assert m3c2_module._preferred_cloud_indices(app, clouds) == (0, 2)


def test_calculate_m3c2_maps_parameters(monkeypatch, m3c2_module):
    py4dgeo = ModuleType("py4dgeo")

    class Epoch:
        def __init__(self, points):
            self.points = points

    class M3C2:
        last_kwargs = None

        def __init__(self, **kwargs):
            M3C2.last_kwargs = kwargs
            self.count = len(kwargs["corepoints"])

        def run(self):
            dtype = [
                ("lodetection", float),
                ("spread1", float),
                ("spread2", float),
                ("num_samples1", int),
                ("num_samples2", int),
            ]
            return np.arange(self.count), np.zeros(self.count, dtype=dtype)

        def directions(self):
            return np.tile([0.0, 0.0, 1.0], (self.count, 1))

        def directions_radii(self):
            return np.full((self.count, 1), 2.0)

    py4dgeo.Epoch = Epoch
    py4dgeo.M3C2 = M3C2
    monkeypatch.setitem(sys.modules, "py4dgeo", py4dgeo)

    points = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    parameters = m3c2_module.M3C2Parameters(
        normal_radii=(1.0, 2.0),
        cylinder_radius=3.0,
        max_distance=4.0,
        registration_error=0.2,
        orientation_vector=(0.0, 1.0, 0.0),
        robust_aggregation=True,
    )
    result = m3c2_module.calculate_m3c2(points, points, points, parameters)

    assert M3C2.last_kwargs["cyl_radius"] == 3.0
    assert M3C2.last_kwargs["normal_radii"] == [1.0, 2.0]
    assert M3C2.last_kwargs["max_distance"] == 4.0
    assert M3C2.last_kwargs["registration_error"] == 0.2
    assert M3C2.last_kwargs["robust_aggr"] is True
    assert result.distances.tolist() == [0, 1]
    assert result.normal_radii.tolist() == [2.0, 2.0]


def test_plugin_action(m3c2_module):
    plugin = m3c2_module.M3C2Plugin()
    actions = plugin.getActions()
    assert len(actions) == 1
    assert actions[0].name == "Compute M3C2 (py4dgeo)"


def test_plugin_opens_dialog_without_loaded_clouds(monkeypatch, m3c2_module):
    shown = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class Dialog:
        def __init__(self, app):
            self.app = app
            self.dialog = type("Widget", (), {"accepted": Signal()})()

        def show(self):
            shown.append(True)

    monkeypatch.setattr(m3c2_module, "_M3C2Dialog", Dialog)
    plugin = m3c2_module.M3C2Plugin()
    plugin.run()
    assert shown == [True]


def test_plugin_run_propagates_dialog_exception(monkeypatch, m3c2_module):
    error = RuntimeError("dialog failed")

    class Dialog:
        def __init__(self, app):
            raise error

    monkeypatch.setattr(m3c2_module, "_M3C2Dialog", Dialog)
    plugin = m3c2_module.M3C2Plugin()

    with pytest.raises(RuntimeError) as caught:
        plugin.run()

    assert caught.value is error


def test_dialog_validation_propagates_exception(m3c2_module):
    dialog = type(
        "Dialog",
        (),
        {
            "clouds": [],
            "refresh_clouds": lambda self: None,
        },
    )()

    with pytest.raises(ValueError, match="Load at least two point clouds"):
        m3c2_module._M3C2Dialog._validate_and_accept(dialog)


def test_plugin_compute_propagates_raw_exception(monkeypatch, m3c2_module):
    error = RuntimeError("M3C2 failed")
    cloud = object()
    combo = type("Combo", (), {"currentIndex": lambda self: 0})()
    output_name = type("Name", (), {"text": lambda self: "result"})()
    dialog = type(
        "Dialog",
        (),
        {
            "clouds": [cloud],
            "reference": combo,
            "compared": combo,
            "core": combo,
            "output_name": output_name,
            "parameters": lambda self: m3c2_module.M3C2Parameters(),
        },
    )()
    monkeypatch.setattr(m3c2_module, "_global_points", lambda cloud: np.empty((1, 3)))

    def fail(*args):
        raise error

    monkeypatch.setattr(m3c2_module, "calculate_m3c2", fail)
    plugin = m3c2_module.M3C2Plugin()
    plugin._dialog = dialog

    with pytest.raises(RuntimeError) as caught:
        plugin._compute()

    assert caught.value is error
