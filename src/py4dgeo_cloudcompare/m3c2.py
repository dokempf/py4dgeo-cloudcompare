"""CloudCompare front end for :class:`py4dgeo.M3C2`.

The PySide6 window lives in a spawned child process.  Only configuration
values cross that boundary; all CloudCompare objects, coordinate arrays, and
M3C2 processing stay on the CloudCompare action's calling thread.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
from typing import Any, Sequence

import numpy as np
import pycc

from .m3c2_protocol import (
    CloudChoice,
    DialogRequest,
    M3C2Configuration,
    M3C2Parameters,
    parse_normal_radii,
)


@dataclass(frozen=True)
class M3C2Result:
    """Numerical result used to construct a CloudCompare point cloud."""

    distances: np.ndarray
    uncertainties: np.ndarray
    normals: np.ndarray
    normal_radii: np.ndarray


def calculate_m3c2(
    reference_points: np.ndarray,
    compared_points: np.ndarray,
    core_points: np.ndarray,
    parameters: M3C2Parameters,
) -> M3C2Result:
    """Run py4dgeo M3C2 on three ``(n, 3)`` coordinate arrays."""

    from py4dgeo import Epoch, M3C2

    reference = Epoch(_points_array(reference_points, "reference cloud"))
    compared = Epoch(_points_array(compared_points, "compared cloud"))
    core = _points_array(core_points, "core points")

    orientation = np.asarray(parameters.orientation_vector, dtype=np.float64)
    if orientation.shape != (3,) or not np.isfinite(orientation).all():
        raise ValueError("The orientation vector must contain three finite values.")
    if np.linalg.norm(orientation) == 0.0:
        raise ValueError("The orientation vector must not be zero.")
    if parameters.cylinder_radius <= 0.0:
        raise ValueError("The projection cylinder radius must be greater than zero.")
    if not parameters.normal_radii or any(
        not np.isfinite(radius) or radius <= 0.0 for radius in parameters.normal_radii
    ):
        raise ValueError("Normal radii must be finite and greater than zero.")
    if parameters.max_distance < 0.0 or parameters.registration_error < 0.0:
        raise ValueError("Maximum depth and registration error cannot be negative.")

    algorithm = M3C2(
        epochs=(reference, compared),
        corepoints=core,
        cyl_radius=float(parameters.cylinder_radius),
        normal_radii=list(parameters.normal_radii),
        max_distance=float(parameters.max_distance),
        registration_error=float(parameters.registration_error),
        orientation_vector=orientation,
        robust_aggr=parameters.robust_aggregation,
    )
    distances, uncertainties = algorithm.run()
    return M3C2Result(
        distances=np.asarray(distances),
        uncertainties=uncertainties,
        normals=np.asarray(algorithm.directions()),
        normal_radii=np.asarray(algorithm.directions_radii()).reshape(-1),
    )


def _points_array(points: np.ndarray, description: str) -> np.ndarray:
    array = np.ascontiguousarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3 or array.shape[0] == 0:
        raise ValueError(f"The {description} must be a non-empty (n, 3) array.")
    if not np.isfinite(array).all():
        raise ValueError(f"The {description} contains non-finite coordinates.")
    return array


def _cloud_name(cloud: Any) -> str:
    return str(cloud.getName())


def _global_points(cloud: Any) -> np.ndarray:
    """Return CloudCompare local points in their global coordinate system."""

    points = np.asarray(cloud.points(), dtype=np.float64).copy()
    shift_value = cloud.getGlobalShift()
    shift = np.array([shift_value.x, shift_value.y, shift_value.z])
    scale = float(cloud.getGlobalScale())
    if scale == 0.0:
        raise ValueError(f"Cloud '{_cloud_name(cloud)}' has a zero global scale.")
    # CloudCompare stores local = (global + shift) * scale.
    return points / scale - shift


def _loaded_point_clouds(app: Any) -> list[Any]:
    """Collect point clouds recursively from CloudCompare's database tree."""

    root = app.dbRootObject()
    if root is None:
        return []

    clouds: list[Any] = []
    pending = [root]
    while pending:
        entity = pending.pop()
        if isinstance(entity, pycc.ccPointCloud):
            clouds.append(entity)
        pending.extend(
            entity.getChild(index)
            for index in reversed(range(entity.getChildrenNumber()))
        )
    return clouds


def _preferred_cloud_indices(app: Any, clouds: Sequence[Any]) -> tuple[int, int]:
    """Use the current selection as defaults without requiring a selection."""

    selected_ids = {
        entity.getUniqueID()
        for entity in app.getSelectedEntities()
        if isinstance(entity, pycc.ccPointCloud)
    }
    selected_indices = [
        index
        for index, cloud in enumerate(clouds)
        if cloud.getUniqueID() in selected_ids
    ]
    if len(selected_indices) >= 2:
        return selected_indices[0], selected_indices[1]
    if len(selected_indices) == 1:
        other = 0 if selected_indices[0] != 0 else 1
        return selected_indices[0], other
    return 0, 1


def create_result_cloud(
    core_cloud: Any,
    result: M3C2Result,
    name: str,
) -> Any:
    """Create a display-ready CloudCompare cloud with M3C2 scalar fields."""

    local_core_points = np.asarray(core_cloud.points(), dtype=pycc.PointCoordinateType)
    output = pycc.ccPointCloud(
        np.ascontiguousarray(local_core_points[:, 0]),
        np.ascontiguousarray(local_core_points[:, 1]),
        np.ascontiguousarray(local_core_points[:, 2]),
    )
    output.setName(name)

    shift = core_cloud.getGlobalShift()
    output.setGlobalShift(shift.x, shift.y, shift.z)
    output.setGlobalScale(core_cloud.getGlobalScale())

    fields = (
        ("M3C2 distance", result.distances),
        ("M3C2 LoD", result.uncertainties["lodetection"]),
        ("M3C2 spread cloud 1", result.uncertainties["spread1"]),
        ("M3C2 spread cloud 2", result.uncertainties["spread2"]),
        ("M3C2 samples cloud 1", result.uncertainties["num_samples1"]),
        ("M3C2 samples cloud 2", result.uncertainties["num_samples2"]),
        ("M3C2 normal X", result.normals[:, 0]),
        ("M3C2 normal Y", result.normals[:, 1]),
        ("M3C2 normal Z", result.normals[:, 2]),
        ("M3C2 normal radius", result.normal_radii),
    )
    distance_index = -1
    for field_name, values in fields:
        values = np.asarray(values, dtype=pycc.ScalarType).reshape(-1)
        if values.size != local_core_points.shape[0]:
            raise ValueError(f"Result field '{field_name}' has an unexpected size.")
        index = output.addScalarField(field_name, values)
        output.getScalarField(index).computeMinAndMax()
        if field_name == "M3C2 distance":
            distance_index = index

    output.setCurrentDisplayedScalarField(distance_index)
    output.showSF(True)
    output.showSFColorsScale(True)
    return output


def _dialog_request(app: Any, clouds: Sequence[Any]) -> DialogRequest:
    """Describe the configuration UI without exposing CloudCompare objects."""

    choices = tuple(
        CloudChoice(
            unique_id=int(cloud.getUniqueID()),
            label=f"{_cloud_name(cloud)}  [ID {cloud.getUniqueID()}]",
        )
        for cloud in clouds
    )
    if len(clouds) >= 2:
        reference_index, compared_index = _preferred_cloud_indices(app, clouds)
        reference_id = choices[reference_index].unique_id
        compared_id = choices[compared_index].unique_id
    elif len(clouds) == 1:
        reference_id = choices[0].unique_id
        compared_id = None
    else:
        reference_id = None
        compared_id = None
    return DialogRequest(
        clouds=choices,
        reference_cloud_id=reference_id,
        compared_cloud_id=compared_id,
        core_cloud_id=reference_id,
    )


def _start_configuration_process(request: DialogRequest) -> subprocess.Popen[str]:
    """Start the child GUI without blocking CloudCompare's event loop."""

    command = [str(_python_executable()), "-m", "py4dgeo_cloudcompare.m3c2_gui"]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    _send_dialog_request(process, "configure", request)
    return process


def _send_dialog_request(
    process: subprocess.Popen[str], message_type: str, request: DialogRequest
) -> None:
    """Send one configuration snapshot to the child GUI."""

    if process.stdin is None:
        raise RuntimeError("The M3C2 GUI process has no configuration input.")
    process.stdin.write(
        json.dumps({"type": message_type, "request": request.to_payload()}) + "\n"
    )
    process.stdin.flush()


def _configuration_from_process(
    returncode: int, stdout: str, stderr: str
) -> M3C2Configuration | None:
    """Validate and decode the child process's final response."""

    if not stdout.strip():
        detail = stderr.strip() or "no diagnostic output"
        raise RuntimeError(
            f"The M3C2 GUI process exited without responding (exit code "
            f"{returncode}): {detail}"
        )
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("The M3C2 GUI process returned invalid JSON.") from error

    response_type = response.get("type")
    if response_type == "cancelled":
        return None
    if response_type == "error":
        error_type = response.get("error_type", "Error")
        message = response.get("message", "Unknown error")
        raise RuntimeError(f"M3C2 GUI {error_type}: {message}")
    if response_type != "configured":
        raise RuntimeError("The M3C2 GUI process returned an invalid response.")
    if returncode != 0:
        raise RuntimeError(f"The M3C2 GUI process exited with code {returncode}.")
    return M3C2Configuration.from_payload(response["configuration"])


def _python_executable() -> Path:
    """Find the standalone interpreter belonging to the embedded environment."""

    executable = Path(sys.executable)
    if executable.stem.lower().startswith("python") and executable.is_file():
        return executable

    executable_name = sysconfig.get_config_var("EXENAME")
    candidates = []
    if executable_name:
        candidates.append(Path(sys.prefix) / "bin" / executable_name)
        candidates.append(Path(sys.prefix) / executable_name)
    candidates.extend(
        (
            Path(sys.prefix) / "bin" / "python3",
            Path(sys.prefix) / "bin" / "python",
            Path(sys.prefix) / "python.exe",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"Cannot find a standalone Python interpreter in {sys.prefix!r} for the "
        "M3C2 GUI process."
    )


def _clouds_by_id(clouds: Sequence[Any]) -> dict[int, Any]:
    return {int(cloud.getUniqueID()): cloud for cloud in clouds}


class M3C2Plugin(pycc.PythonPluginInterface):
    """CloudCompare PythonRuntime plugin exposing py4dgeo M3C2."""

    def __init__(self) -> None:
        super().__init__()
        self.app = pycc.GetInstance()
        self._dialog_process: subprocess.Popen[str] | None = None
        self._last_dialog_request: dict[str, Any] | None = None

    def getActions(self):
        return [pycc.Action(name="Compute M3C2 (py4dgeo)", target=self.run)]

    def run(self) -> None:
        if self._dialog_process is not None:
            return

        request = _dialog_request(self.app, _loaded_point_clouds(self.app))
        self._dialog_process = _start_configuration_process(request)
        self._last_dialog_request = request.to_payload()

        # Keep this action on CloudCompare's thread while explicitly pumping
        # its native event loop.  The application remains interactive, but no
        # PySide6 module is imported into the host process.
        while self._dialog_process is not None:
            self._poll_dialog_process()
            if self._dialog_process is not None:
                pycc.ProcessEvents()
                time.sleep(0.05)

    def _poll_dialog_process(self) -> None:
        """Refresh cloud metadata or consume the completed dialog response."""

        process = self._dialog_process
        if process is None:
            return
        returncode = process.poll()
        if returncode is None:
            request = _dialog_request(self.app, _loaded_point_clouds(self.app))
            payload = request.to_payload()
            if payload != self._last_dialog_request:
                try:
                    _send_dialog_request(process, "refresh", request)
                except (BrokenPipeError, OSError):
                    return
                self._last_dialog_request = payload
            return

        stdout, stderr = process.communicate()
        self._dialog_process = None
        self._last_dialog_request = None

        configuration = _configuration_from_process(returncode, stdout, stderr)
        if configuration is not None:
            self._compute(configuration)

    def _compute(self, configuration: M3C2Configuration) -> None:
        """Compute synchronously on the CloudCompare action's calling thread."""

        configuration.validate()
        clouds = _clouds_by_id(_loaded_point_clouds(self.app))
        try:
            reference = clouds[configuration.reference_cloud_id]
            compared = clouds[configuration.compared_cloud_id]
            core = clouds[configuration.core_cloud_id]
        except KeyError as error:
            raise RuntimeError(
                f"Point cloud ID {error.args[0]} is no longer available."
            ) from error
        result = calculate_m3c2(
            _global_points(reference),
            _global_points(compared),
            _global_points(core),
            configuration.parameters,
        )
        output = create_result_cloud(core, result, configuration.output_name)
        self.app.addToDB(output, updateZoom=False)
        self.app.redrawAll()
        print(
            f"py4dgeo M3C2: added '{configuration.output_name}' "
            f"with {output.size()} core points"
        )

