import importlib
import json
from pathlib import Path
import sys
import threading
from types import ModuleType
from types import SimpleNamespace

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
    pycc.ProcessEvents = lambda: None
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


def test_dialog_request_allows_no_loaded_clouds(m3c2_module):
    app = SimpleNamespace(getSelectedEntities=lambda: [])

    request = m3c2_module._dialog_request(app, [])

    assert request.to_payload() == {
        "clouds": [],
        "reference_cloud_id": None,
        "compared_cloud_id": None,
        "core_cloud_id": None,
    }


def test_dialog_request_allows_one_loaded_cloud(m3c2_module):
    cloud = PointCloud()
    cloud.getUniqueID = lambda: 10
    cloud.getName = lambda: "only cloud"
    app = SimpleNamespace(getSelectedEntities=lambda: [cloud])

    request = m3c2_module._dialog_request(app, [cloud])

    assert request.to_payload() == {
        "clouds": [{"unique_id": 10, "label": "only cloud  [ID 10]"}],
        "reference_cloud_id": 10,
        "compared_cloud_id": None,
        "core_cloud_id": 10,
    }


def test_dialog_request_contains_cloud_metadata_only(m3c2_module):
    clouds = [PointCloud(), PointCloud()]
    for identifier, cloud in enumerate(clouds, start=10):
        cloud.getUniqueID = lambda identifier=identifier: identifier
        cloud.getName = lambda identifier=identifier: f"cloud {identifier}"
        cloud.points = lambda: pytest.fail("point data must not be read for the GUI")
    app = SimpleNamespace(getSelectedEntities=lambda: clouds[::-1])

    request = m3c2_module._dialog_request(app, clouds)
    payload = request.to_payload()

    assert payload == {
        "clouds": [
            {"unique_id": 10, "label": "cloud 10  [ID 10]"},
            {"unique_id": 11, "label": "cloud 11  [ID 11]"},
        ],
        "reference_cloud_id": 10,
        "compared_cloud_id": 11,
        "core_cloud_id": 10,
    }


def test_configuration_round_trip_and_validation(m3c2_module):
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=12,
        parameters=m3c2_module.M3C2Parameters(
            normal_radii=(1.0, 2.0), orientation_vector=(0.0, 1.0, 0.0)
        ),
        output_name="result",
    )

    restored = m3c2_module.M3C2Configuration.from_payload(
        json.loads(json.dumps(configuration.to_payload()))
    )
    assert restored == configuration

    invalid = configuration.to_payload()
    invalid["compared_cloud_id"] = 10
    with pytest.raises(ValueError, match="must be different"):
        m3c2_module.M3C2Configuration.from_payload(invalid)


def test_start_configuration_uses_json_subprocess(monkeypatch, m3c2_module):
    request = m3c2_module.DialogRequest(
        clouds=(
            m3c2_module.CloudChoice(10, "one"),
            m3c2_module.CloudChoice(11, "two"),
        ),
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
    )
    invocation = {}

    class Input:
        def __init__(self):
            self.value = ""

        def write(self, value):
            self.value += value

        def flush(self):
            pass

    process = SimpleNamespace(stdin=Input())

    def popen(command, **kwargs):
        invocation["command"] = command
        invocation["kwargs"] = kwargs
        return process

    monkeypatch.setattr(m3c2_module, "_python_executable", lambda: Path("/python"))
    monkeypatch.setattr(m3c2_module.subprocess, "Popen", popen)

    assert m3c2_module._start_configuration_process(request) is process
    assert invocation["command"] == [
        "/python",
        "-m",
        "py4dgeo_cloudcompare.m3c2_gui",
    ]
    wire_request = json.loads(process.stdin.value)
    assert wire_request == {"type": "configure", "request": request.to_payload()}
    assert invocation["kwargs"]["stdin"] is m3c2_module.subprocess.PIPE


def test_configuration_process_response_round_trip(m3c2_module):
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
        parameters=m3c2_module.M3C2Parameters(),
        output_name="result",
    )
    stdout = json.dumps(
        {"type": "configured", "configuration": configuration.to_payload()}
    )

    assert m3c2_module._configuration_from_process(0, stdout, "") == configuration


def test_plugin_computes_on_calling_thread(monkeypatch, m3c2_module):
    caller_thread = threading.get_ident()
    observed_threads = []
    configuration = m3c2_module.M3C2Configuration(
        reference_cloud_id=1,
        compared_cloud_id=2,
        core_cloud_id=1,
        parameters=m3c2_module.M3C2Parameters(),
        output_name="result",
    )
    plugin = m3c2_module.M3C2Plugin()

    def compute(received):
        assert received == configuration
        observed_threads.append(threading.get_ident())

    response = json.dumps(
        {"type": "configured", "configuration": configuration.to_payload()}
    )
    plugin._dialog_process = SimpleNamespace(
        poll=lambda: 0,
        communicate=lambda: (response, ""),
    )
    monkeypatch.setattr(plugin, "_compute", compute)

    plugin._poll_dialog_process()

    assert observed_threads == [caller_thread]


def test_plugin_pumps_cloudcompare_events_without_pyside(
    monkeypatch, m3c2_module
):
    caller_thread = threading.get_ident()
    event_threads = []
    poll_results = iter((None, 0))
    process = SimpleNamespace(
        poll=lambda: next(poll_results),
        communicate=lambda: (json.dumps({"type": "cancelled"}), ""),
        stdin=SimpleNamespace(write=lambda value: None, flush=lambda: None),
    )
    plugin = m3c2_module.M3C2Plugin()
    monkeypatch.setattr(m3c2_module, "_loaded_point_clouds", lambda app: [])
    monkeypatch.setattr(
        m3c2_module, "_start_configuration_process", lambda request: process
    )
    monkeypatch.setattr(
        m3c2_module.pycc,
        "ProcessEvents",
        lambda: event_threads.append(threading.get_ident()),
    )
    monkeypatch.setattr(m3c2_module.time, "sleep", lambda seconds: None)

    plugin.run()

    assert event_threads == [caller_thread]
    assert "PySide6" not in sys.modules


def test_plugin_refreshes_cloud_metadata_while_dialog_is_open(
    monkeypatch, m3c2_module
):
    class Input:
        def __init__(self):
            self.value = ""

        def write(self, value):
            self.value += value

        def flush(self):
            pass

    request = m3c2_module.DialogRequest(
        clouds=(
            m3c2_module.CloudChoice(10, "one"),
            m3c2_module.CloudChoice(11, "two"),
        ),
        reference_cloud_id=10,
        compared_cloud_id=11,
        core_cloud_id=10,
    )
    process_input = Input()
    plugin = m3c2_module.M3C2Plugin()
    plugin._dialog_process = SimpleNamespace(
        poll=lambda: None,
        stdin=process_input,
    )
    plugin._last_dialog_request = {"clouds": []}
    monkeypatch.setattr(m3c2_module, "_loaded_point_clouds", lambda app: [1, 2])
    monkeypatch.setattr(m3c2_module, "_dialog_request", lambda app, clouds: request)

    plugin._poll_dialog_process()

    assert json.loads(process_input.value) == {
        "type": "refresh",
        "request": request.to_payload(),
    }
    assert plugin._last_dialog_request == request.to_payload()


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
    plugin = m3c2_module.M3C2Plugin()
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


def test_tkinter_plugin_is_a_separate_action(monkeypatch, m3c2_module):
    sys.modules.pop("py4dgeo_cloudcompare.m3c2_tkinter", None)
    module = importlib.import_module("py4dgeo_cloudcompare.m3c2_tkinter")

    plugin = module.M3C2TkinterPlugin()
    actions = plugin.getActions()

    assert len(actions) == 1
    assert actions[0].name == "Compute M3C2 (py4dgeo, Tkinter)"


def test_tkinter_plugin_runs_dialog_and_compute_in_process(
    monkeypatch, m3c2_module
):
    sys.modules.pop("py4dgeo_cloudcompare.m3c2_tkinter", None)
    module = importlib.import_module("py4dgeo_cloudcompare.m3c2_tkinter")
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
    monkeypatch.setattr(module, "_clear_cloudcompare_wait_cursor", lambda: None)
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
