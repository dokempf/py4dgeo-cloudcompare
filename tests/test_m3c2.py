import importlib
import sys
import threading
from types import ModuleType
from types import SimpleNamespace

import numpy as np
import pytest

from py4dgeo_cloudcompare.m3c2_configuration import parse_normal_radii


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
    pycc.ProcessEvents = lambda: None
    monkeypatch.setitem(sys.modules, "pycc", pycc)
    sys.modules.pop("py4dgeo_cloudcompare.m3c2_tkinter", None)
    return importlib.import_module("py4dgeo_cloudcompare.m3c2_tkinter")


def test_parse_normal_radii():
    assert parse_normal_radii("0.5, 1; 2") == (0.5, 1.0, 2.0)

    for invalid in ("", "one", "0", "-1", "nan"):
        with pytest.raises(ValueError):
            parse_normal_radii(invalid)


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
    logfiles = []

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
    py4dgeo.set_py4dgeo_logfile = logfiles.append
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
    assert logfiles == [str(m3c2_module._PY4DGEO_LOG_PATH)]


def test_error_report_contains_full_traceback(monkeypatch, tmp_path, m3c2_module):
    report = tmp_path / "m3c2-error.log"
    monkeypatch.setattr(m3c2_module, "_ERROR_REPORT_PATH", report)

    try:
        raise RuntimeError("complete diagnostic")
    except RuntimeError:
        written = m3c2_module._write_error_report()

    assert written == report
    contents = report.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in contents
    assert "RuntimeError: complete diagnostic" in contents


def test_plugin_action(m3c2_module):
    plugin = m3c2_module.M3C2TkinterPlugin()
    actions = plugin.getActions()
    assert len(actions) == 1
    assert actions[0].name == "Compute M3C2 (py4dgeo, Tkinter)"


def test_dialog_request_allows_no_loaded_clouds(m3c2_module):
    app = SimpleNamespace(getSelectedEntities=lambda: [])

    request = m3c2_module._dialog_request(app, [])

    assert request == m3c2_module.DialogRequest((), None, None, None)


def test_dialog_request_allows_one_loaded_cloud(m3c2_module):
    cloud = PointCloud()
    cloud.getUniqueID = lambda: 10
    cloud.getName = lambda: "only cloud"
    app = SimpleNamespace(getSelectedEntities=lambda: [cloud])

    request = m3c2_module._dialog_request(app, [cloud])

    assert request == m3c2_module.DialogRequest(
        clouds=(m3c2_module.CloudChoice(10, "only cloud  [ID 10]"),),
        reference_cloud_id=10,
        compared_cloud_id=None,
        core_cloud_id=10,
    )


def test_dialog_request_contains_cloud_metadata_only(m3c2_module):
    clouds = [PointCloud(), PointCloud()]
    for identifier, cloud in enumerate(clouds, start=10):
        cloud.getUniqueID = lambda identifier=identifier: identifier
        cloud.getName = lambda identifier=identifier: f"cloud {identifier}"
        cloud.points = lambda: pytest.fail("point data must not be read for the GUI")
    app = SimpleNamespace(getSelectedEntities=lambda: clouds[::-1])

    request = m3c2_module._dialog_request(app, clouds)
    assert request == m3c2_module.DialogRequest(
        clouds=(
            m3c2_module.CloudChoice(10, "cloud 10  [ID 10]"),
            m3c2_module.CloudChoice(11, "cloud 11  [ID 11]"),
        ),
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
    )


def test_configuration_validation(m3c2_module):
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=12,
        parameters=m3c2_module.M3C2Parameters(
            normal_radii=(1.0, 2.0), orientation_vector=(0.0, 1.0, 0.0)
        ),
        output_name="result",
    )

    configuration.validate()

    invalid = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=10,
        core_cloud_id=12,
        parameters=configuration.parameters,
        output_name="result",
    )
    with pytest.raises(ValueError, match="must be different"):
        invalid.validate()


def test_plugin_compute_propagates_raw_exception(monkeypatch, m3c2_module):
    error = RuntimeError("M3C2 failed")
    clouds = [PointCloud(), PointCloud()]
    clouds[0].getUniqueID = lambda: 10
    clouds[1].getUniqueID = lambda: 11
    monkeypatch.setattr(m3c2_module, "_loaded_point_clouds", lambda app: clouds)
    monkeypatch.setattr(m3c2_module, "_global_points", lambda cloud: np.empty((1, 3)))

    def fail(*args):
        raise error

    monkeypatch.setattr(m3c2_module, "calculate_m3c2", fail)
    plugin = m3c2_module.M3C2TkinterPlugin()
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
        parameters=m3c2_module.M3C2Parameters(),
        output_name="result",
    )

    with pytest.raises(RuntimeError) as caught:
        plugin._compute(configuration)

    assert caught.value is error


def test_tkinter_plugin_runs_dialog_and_compute_in_process(
    monkeypatch, m3c2_module
):
    module = m3c2_module
    caller_thread = threading.get_ident()
    request = m3c2_module.DialogRequest(
        clouds=(
            m3c2_module.CloudChoice(10, "one"),
            m3c2_module.CloudChoice(11, "two"),
        ),
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
    )
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
        parameters=m3c2_module.M3C2Parameters(),
        output_name="result",
    )
    observed_threads = []
    dialogs = []

    class Dialog:
        def __init__(self, received):
            assert received == request
            self.is_open = True
            self.result = None
            self.event_count = 0
            self.destroyed = False
            dialogs.append(self)

        def update_request(self, received):
            pytest.fail(f"unexpected request refresh: {received}")

        def process_events(self):
            observed_threads.append(("tk", threading.get_ident()))
            self.event_count += 1
            if self.event_count == 2:
                self.result = configuration
                self.is_open = False

        def destroy(self):
            self.destroyed = True

    plugin = module.M3C2TkinterPlugin()
    monkeypatch.setattr(module, "_M3C2TkinterDialog", Dialog)
    monkeypatch.setattr(module, "_loaded_point_clouds", lambda app: [])
    monkeypatch.setattr(module, "_dialog_request", lambda app, clouds: request)
    monkeypatch.setattr(
        module.pycc,
        "ProcessEvents",
        lambda: observed_threads.append(("qt", threading.get_ident())),
    )
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        plugin,
        "_compute",
        lambda received: observed_threads.append(
            ("compute", threading.get_ident(), received)
        ),
    )

    plugin.run()

    assert observed_threads == [
        ("tk", caller_thread),
        ("qt", caller_thread),
        ("tk", caller_thread),
        ("compute", caller_thread, configuration),
    ]
    assert dialogs[0].destroyed is True
