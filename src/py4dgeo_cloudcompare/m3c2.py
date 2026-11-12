"""CloudCompare front end for :class:`py4dgeo.M3C2`.

The imports of py4dgeo and PySide6 deliberately happen when the action is
executed.  CloudCompare can therefore discover the plugin even while its
Python environment is still being configured, and the numerical parts of
this module can be tested without a Qt application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pycc


@dataclass(frozen=True)
class M3C2Parameters:
    """Parameters exposed by the M3C2 dialog, in py4dgeo units."""

    normal_radii: tuple[float, ...] = (0.5, 1.0, 2.0)
    cylinder_radius: float = 1.0
    max_distance: float = 0.0
    registration_error: float = 0.0
    orientation_vector: tuple[float, float, float] = (0.0, 0.0, 1.0)
    robust_aggregation: bool = False


@dataclass(frozen=True)
class M3C2Result:
    """Numerical result used to construct a CloudCompare point cloud."""

    distances: np.ndarray
    uncertainties: np.ndarray
    normals: np.ndarray
    normal_radii: np.ndarray


def parse_normal_radii(value: str) -> tuple[float, ...]:
    """Parse a comma/semicolon/whitespace separated list of positive radii."""

    tokens = value.replace(";", " ").replace(",", " ").split()
    if not tokens:
        raise ValueError("Specify at least one normal radius.")
    radii = tuple(float(token) for token in tokens)
    if any(not np.isfinite(radius) or radius <= 0.0 for radius in radii):
        raise ValueError("Normal radii must be finite and greater than zero.")
    return radii


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


class _M3C2Dialog:
    """Small wrapper that keeps Qt imports local to GUI execution."""

    def __init__(self, app: Any):
        from PySide6 import QtCore, QtWidgets

        self.QtWidgets = QtWidgets
        self.app = app
        self.clouds: list[Any] = []
        self.dialog = QtWidgets.QDialog(QtWidgets.QApplication.activeWindow())
        self.dialog.setWindowTitle("py4dgeo M3C2")
        self.dialog.setMinimumWidth(480)
        layout = QtWidgets.QVBoxLayout(self.dialog)
        description = QtWidgets.QLabel(
            "Compute signed M3C2 distances for selected CloudCompare point clouds."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.reference = QtWidgets.QComboBox()
        self.compared = QtWidgets.QComboBox()
        self.core = QtWidgets.QComboBox()
        form.addRow("Reference cloud", self.reference)
        form.addRow("Compared cloud", self.compared)
        form.addRow("Core points", self.core)
        self.cloud_status = QtWidgets.QLabel()
        self.refresh_button = QtWidgets.QPushButton("Refresh point clouds")
        self.refresh_button.clicked.connect(self.refresh_clouds)
        cloud_controls = QtWidgets.QHBoxLayout()
        cloud_controls.addWidget(self.cloud_status)
        cloud_controls.addStretch()
        cloud_controls.addWidget(self.refresh_button)
        form.addRow("", cloud_controls)

        self.normal_radii = QtWidgets.QLineEdit("0.5, 1.0, 2.0")
        self.normal_radii.setToolTip("One or more py4dgeo search radii, separated by commas")
        form.addRow("Normal radii", self.normal_radii)
        self.cylinder_radius = self._spin(1.0, 1.0e-9)
        form.addRow("Projection cylinder radius", self.cylinder_radius)
        self.max_distance = self._spin(0.0, 0.0)
        self.max_distance.setSpecialValueText("Automatic")
        form.addRow("Maximum projection depth", self.max_distance)
        self.registration_error = self._spin(0.0, 0.0)
        form.addRow("Registration error", self.registration_error)

        orientation = QtWidgets.QHBoxLayout()
        self.orientation = []
        for label, initial in zip("XYZ", (0.0, 0.0, 1.0)):
            orientation.addWidget(QtWidgets.QLabel(label))
            widget = self._spin(initial, -1.0e12)
            widget.setMaximum(1.0e12)
            self.orientation.append(widget)
            orientation.addWidget(widget)
        form.addRow("Normal orientation vector", orientation)
        self.robust = QtWidgets.QCheckBox("Use median and IQR")
        form.addRow("Robust aggregation", self.robust)
        self.output_name = QtWidgets.QLineEdit("M3C2 result")
        form.addRow("Output cloud name", self.output_name)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Compute")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)
        self._align_center = QtCore.Qt.AlignmentFlag.AlignCenter
        description.setAlignment(self._align_center)

        # Keep the picker synchronized while the modeless dialog is open. This
        # lets users load point clouds after launching the plugin.
        self._refresh_timer = QtCore.QTimer(self.dialog)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh_clouds)
        self._refresh_timer.start()
        self.refresh_clouds(use_selection_defaults=True)

    @staticmethod
    def _cloud_label(cloud: Any) -> str:
        return f"{_cloud_name(cloud)}  [ID {cloud.getUniqueID()}]"

    @staticmethod
    def _cloud_id(cloud: Any) -> Any:
        return cloud.getUniqueID()

    def refresh_clouds(self, use_selection_defaults: bool = False) -> None:
        """Refresh the pickers while preserving the current assignments."""

        combos = (self.reference, self.compared, self.core)
        selected_ids = []
        for combo in combos:
            index = combo.currentIndex()
            selected_ids.append(
                self._cloud_id(self.clouds[index])
                if 0 <= index < len(self.clouds)
                else None
            )

        clouds = _loaded_point_clouds(self.app)
        cloud_ids = [self._cloud_id(cloud) for cloud in clouds]
        if cloud_ids == [self._cloud_id(cloud) for cloud in self.clouds]:
            if len(clouds) == 0:
                self.cloud_status.setText("No point clouds loaded")
            return

        self.clouds = clouds
        labels = [self._cloud_label(cloud) for cloud in clouds]
        if use_selection_defaults and len(clouds) >= 2:
            reference_index, compared_index = _preferred_cloud_indices(self.app, clouds)
            default_indices = (reference_index, compared_index, reference_index)
        else:
            default_indices = (0, 1, 0)

        for combo, selected_id, default_index in zip(
            combos, selected_ids, default_indices
        ):
            combo.clear()
            combo.addItems(labels)
            if selected_id in cloud_ids:
                combo.setCurrentIndex(cloud_ids.index(selected_id))
            elif default_index < len(clouds):
                combo.setCurrentIndex(default_index)

        if len(clouds) == 0:
            self.cloud_status.setText("No point clouds loaded")
        elif len(clouds) == 1:
            self.cloud_status.setText("Load one more point cloud")
        else:
            self.cloud_status.setText(f"{len(clouds)} point clouds available")

    def _spin(self, value: float, minimum: float):
        widget = self.QtWidgets.QDoubleSpinBox()
        widget.setDecimals(6)
        widget.setRange(minimum, 1.0e12)
        widget.setValue(value)
        return widget

    def _validate_and_accept(self) -> None:
        self.refresh_clouds()
        if len(self.clouds) < 2:
            raise ValueError(
                "Load at least two point clouds in CloudCompare before computing."
            )
        parameters = self.parameters()
        if np.linalg.norm(parameters.orientation_vector) == 0.0:
            raise ValueError("The normal orientation vector must not be zero.")
        if self.reference.currentIndex() == self.compared.currentIndex():
            raise ValueError("Reference and compared clouds must be different.")
        if not self.output_name.text().strip():
            raise ValueError("Specify a name for the output cloud.")
        self.dialog.accept()

    def show(self) -> None:
        self.refresh_clouds()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def parameters(self) -> M3C2Parameters:
        return M3C2Parameters(
            normal_radii=parse_normal_radii(self.normal_radii.text()),
            cylinder_radius=self.cylinder_radius.value(),
            max_distance=self.max_distance.value(),
            registration_error=self.registration_error.value(),
            orientation_vector=tuple(widget.value() for widget in self.orientation),
            robust_aggregation=self.robust.isChecked(),
        )


class M3C2Plugin(pycc.PythonPluginInterface):
    """CloudCompare PythonRuntime plugin exposing py4dgeo M3C2."""

    def __init__(self) -> None:
        super().__init__()
        self.app = pycc.GetInstance()
        self._dialog: _M3C2Dialog | None = None

    def getActions(self):
        return [pycc.Action(name="Compute M3C2 (py4dgeo)", target=self.run)]

    def run(self) -> None:
        if self._dialog is None:
            self._dialog = _M3C2Dialog(self.app)
            self._dialog.dialog.accepted.connect(self._compute)
        self._dialog.show()

    def _compute(self) -> None:
        """Compute from the assignments captured by the modeless dialog."""

        assert self._dialog is not None
        dialog = self._dialog
        clouds = dialog.clouds
        reference = clouds[dialog.reference.currentIndex()]
        compared = clouds[dialog.compared.currentIndex()]
        core = clouds[dialog.core.currentIndex()]
        result = calculate_m3c2(
            _global_points(reference),
            _global_points(compared),
            _global_points(core),
            dialog.parameters(),
        )
        output = create_result_cloud(core, result, dialog.output_name.text().strip())
        self.app.addToDB(output, updateZoom=False)
        self.app.redrawAll()
        print(
            f"py4dgeo M3C2: added '{dialog.output_name.text().strip()}' "
            f"with {output.size()} core points"
        )

