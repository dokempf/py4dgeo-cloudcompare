"""CloudCompare M3C2 plugin with an in-process Tkinter interface."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time
import traceback
from typing import Any, Sequence

import numpy as np
import pycc

from .m3c2_configuration import (
    CloudChoice,
    DialogRequest,
    M3C2Configuration,
    M3C2Parameters,
)


_TEMPORARY_DIRECTORY = Path(tempfile.gettempdir())
_PY4DGEO_LOG_PATH = (
    _TEMPORARY_DIRECTORY / f"py4dgeo-cloudcompare-{os.getpid()}.log"
)
_ERROR_REPORT_PATH = (
    _TEMPORARY_DIRECTORY / f"py4dgeo-cloudcompare-error-{os.getpid()}.log"
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

    from py4dgeo import Epoch, M3C2, set_py4dgeo_logfile

    # CloudCompare may run from a read-only installation directory, so direct
    # py4dgeo's delayed log file into the operating system's temporary folder.
    set_py4dgeo_logfile(str(_PY4DGEO_LOG_PATH))

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


def _write_error_report() -> Path | None:
    """Persist the current full traceback where it can be viewed untruncated."""

    try:
        _ERROR_REPORT_PATH.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        return None
    return _ERROR_REPORT_PATH


def _clouds_by_id(clouds: Sequence[Any]) -> dict[int, Any]:
    return {int(cloud.getUniqueID()): cloud for cloud in clouds}


class M3C2TkinterPlugin(pycc.PythonPluginInterface):
    """CloudCompare plugin for py4dgeo M3C2 using a Tkinter dialog."""

    def __init__(self) -> None:
        super().__init__()
        self.app = pycc.GetInstance()

    def getActions(self):
        return [
            pycc.Action(
                name="Compute M3C2 (py4dgeo, Tkinter)",
                target=self.run,
            )
        ]

    def run(self) -> None:
        try:
            request = _dialog_request(self.app, _loaded_point_clouds(self.app))
            dialog = _M3C2TkinterDialog(request)
            last_request = request

            try:
                # A cooperative loop services both Tk and CloudCompare's
                # native Qt event queue on the action's calling thread.
                while dialog.is_open:
                    request = _dialog_request(
                        self.app, _loaded_point_clouds(self.app)
                    )
                    if request != last_request:
                        dialog.update_request(request)
                        last_request = request

                    dialog.process_events()
                    if dialog.is_open:
                        pycc.ProcessEvents()
                        time.sleep(0.02)
                configuration = dialog.result
            finally:
                dialog.destroy()

            if configuration is not None:
                self._compute(configuration)
        except Exception:
            report_path = _write_error_report()
            if report_path is not None:
                print(f"py4dgeo M3C2: full traceback written to '{report_path}'")
            raise

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


class _CloudSelector:
    """A ttk combobox that exposes a selected CloudCompare unique ID."""

    def __init__(self, parent: Any, ttk: Any, tk: Any) -> None:
        self.variable = tk.StringVar(parent)
        self.widget = ttk.Combobox(
            parent,
            textvariable=self.variable,
            state="readonly",
            width=46,
        )
        self._ids_by_label: dict[str, int] = {}

    def selected_id(self) -> int | None:
        return self._ids_by_label.get(self.variable.get())

    def set_choices(self, request: DialogRequest, selected_id: int | None) -> None:
        labels = tuple(cloud.label for cloud in request.clouds)
        self._ids_by_label = {
            cloud.label: cloud.unique_id for cloud in request.clouds
        }
        self.widget.configure(values=labels)
        selected_label = next(
            (
                cloud.label
                for cloud in request.clouds
                if cloud.unique_id == selected_id
            ),
            "",
        )
        self.variable.set(selected_label)


class _M3C2TkinterDialog:
    """Tk widgets whose inputs and output are configuration values only."""

    def __init__(self, request: DialogRequest) -> None:
        # Lazy imports keep plugin discovery working on installations where
        # Tk is unavailable; only launching this alternative requires it.
        import tkinter as tk
        from tkinter import messagebox, ttk

        from .tkinter_widgets import FloatList

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.request = request
        self.result: M3C2Configuration | None = None
        self.is_open = True

        self.root = tk.Tk()
        self.root.title("py4dgeo M3C2 (Tkinter)")
        self.root.minsize(540, 0)
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)

        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        description = ttk.Label(
            frame,
            text="Compute signed M3C2 distances for CloudCompare point clouds.",
            wraplength=500,
        )
        description.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.reference = self._add_cloud_selector(frame, 1, "Reference cloud")
        self.compared = self._add_cloud_selector(frame, 2, "Compared cloud")
        self.core = self._add_cloud_selector(frame, 3, "Core points")
        self.cloud_status = ttk.Label(frame, wraplength=500)
        self.cloud_status.grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 8)
        )

        defaults = M3C2Parameters()
        self.cylinder_radius = tk.StringVar(
            self.root, value=str(defaults.cylinder_radius)
        )
        self.max_distance = tk.StringVar(
            self.root, value=str(defaults.max_distance)
        )
        self.registration_error = tk.StringVar(
            self.root, value=str(defaults.registration_error)
        )
        self.orientation = tuple(
            tk.StringVar(self.root, value=str(value))
            for value in defaults.orientation_vector
        )
        self.robust = tk.BooleanVar(
            self.root, value=defaults.robust_aggregation
        )
        self.output_name = tk.StringVar(self.root, value="M3C2 result")

        row = 5
        ttk.Label(frame, text="Normal radii").grid(
            row=row, column=0, sticky="nw", padx=(0, 8), pady=3
        )
        self.normal_radii = FloatList(
            frame,
            defaults.normal_radii,
            validator=self._validate_normal_radius,
            on_invalid=self._show_invalid_normal_radius,
            spinbox_from=0.0,
        )
        self.normal_radii.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        self._add_entry(
            frame, row, "Projection cylinder radius", self.cylinder_radius
        )
        row += 1
        self._add_entry(frame, row, "Maximum projection depth", self.max_distance)
        row += 1
        self._add_entry(frame, row, "Registration error", self.registration_error)
        row += 1
        self._add_orientation(frame, row)
        row += 1
        ttk.Label(frame, text="Robust aggregation").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        ttk.Checkbutton(
            frame, text="Use median and IQR", variable=self.robust
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1
        self._add_entry(frame, row, "Output cloud name", self.output_name)
        row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self._cancel).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.compute_button = ttk.Button(
            buttons, text="Compute", command=self._accept
        )
        self.compute_button.grid(row=0, column=1)

        self.update_request(request, preserve_selection=False)
        self.root.lift()

    def _add_cloud_selector(
        self, parent: Any, row: int, label: str
    ) -> _CloudSelector:
        self.ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        selector = _CloudSelector(parent, self.ttk, self.tk)
        selector.widget.grid(row=row, column=1, sticky="ew", pady=3)
        return selector

    def _add_entry(
        self, parent: Any, row: int, label: str, variable: Any
    ) -> None:
        self.ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self.ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", pady=3
        )

    def _add_orientation(self, parent: Any, row: int) -> None:
        self.ttk.Label(parent, text="Normal orientation vector").grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=3
        )
        coordinates = self.ttk.Frame(parent)
        coordinates.grid(row=row, column=1, sticky="ew", pady=3)
        for column, (label, variable) in enumerate(
            zip("XYZ", self.orientation)
        ):
            coordinates.columnconfigure(column * 2 + 1, weight=1)
            self.ttk.Label(coordinates, text=label).grid(
                row=0, column=column * 2, padx=(0 if column == 0 else 8, 3)
            )
            self.ttk.Entry(
                coordinates, textvariable=variable, width=10
            ).grid(row=0, column=column * 2 + 1, sticky="ew")

    @staticmethod
    def _validate_normal_radius(value: float) -> None:
        if value <= 0.0:
            raise ValueError("A normal radius must be greater than zero.")

    def _show_invalid_normal_radius(self, _error: ValueError) -> None:
        self.messagebox.showwarning(
            "Invalid normal radius",
            "Enter a finite normal radius greater than zero.",
            parent=self.root,
        )

    def update_request(
        self, request: DialogRequest, preserve_selection: bool = True
    ) -> None:
        selectors = (self.reference, self.compared, self.core)
        previous_ids = tuple(selector.selected_id() for selector in selectors)
        default_ids = (
            request.reference_cloud_id,
            request.compared_cloud_id,
            request.core_cloud_id,
        )
        available_ids = {cloud.unique_id for cloud in request.clouds}
        had_choices = len(self.request.clouds) >= 2
        self.request = request

        for selector, previous_id, default_id in zip(
            selectors, previous_ids, default_ids
        ):
            selected_id = (
                previous_id
                if preserve_selection and had_choices and previous_id in available_ids
                else default_id
            )
            selector.set_choices(request, selected_id)

        if not request.clouds:
            status = "No point clouds are currently loaded in CloudCompare."
        elif len(request.clouds) == 1:
            status = "Load one more point cloud before computing."
        else:
            status = f"{len(request.clouds)} point clouds available."
        self.cloud_status.configure(text=status)
        self.compute_button.configure(
            state="normal" if len(request.clouds) >= 2 else "disabled"
        )

    def configuration(self) -> M3C2Configuration:
        reference_id = self.reference.selected_id()
        compared_id = self.compared.selected_id()
        core_id = self.core.selected_id()
        if reference_id is None or compared_id is None or core_id is None:
            raise ValueError(
                "Load at least two point clouds in CloudCompare before computing."
            )

        configuration = M3C2Configuration(
            reference_cloud_id=reference_id,
            compared_cloud_id=compared_id,
            core_cloud_id=core_id,
            parameters=M3C2Parameters(
                normal_radii=self.normal_radii.get(),
                cylinder_radius=float(self.cylinder_radius.get()),
                max_distance=float(self.max_distance.get()),
                registration_error=float(self.registration_error.get()),
                orientation_vector=tuple(
                    float(variable.get()) for variable in self.orientation
                ),
                robust_aggregation=bool(self.robust.get()),
            ),
            output_name=self.output_name.get().strip(),
        )
        configuration.validate()
        return configuration

    def _accept(self) -> None:
        try:
            configuration = self.configuration()
        except ValueError as error:
            self.messagebox.showwarning(
                "Invalid M3C2 configuration", str(error), parent=self.root
            )
            return
        self.result = configuration
        self.is_open = False

    def _cancel(self) -> None:
        self.result = None
        self.is_open = False

    def process_events(self) -> None:
        try:
            self.root.update_idletasks()
            self.root.update()
        except self.tk.TclError:
            self._cancel()

    def destroy(self) -> None:
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass
