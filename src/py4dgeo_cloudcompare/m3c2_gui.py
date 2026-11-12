"""PySide6 M3C2 configuration window, run only in a child process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
from typing import Any

from .m3c2_protocol import (
    DialogRequest,
    M3C2Configuration,
    M3C2Parameters,
    parse_normal_radii,
)


def main() -> None:
    """Read dialog context as JSON, then emit a configuration-only response."""

    try:
        line = sys.stdin.readline()
        if not line:
            raise RuntimeError("CloudCompare closed the M3C2 configuration channel.")
        message = json.loads(line)
        if message.get("type") != "configure":
            raise ValueError("Unexpected M3C2 GUI request.")
        request = DialogRequest.from_payload(message["request"])
        configuration = _show_dialog(request)
        if configuration is None:
            response = {"type": "cancelled"}
        else:
            response = {
                "type": "configured",
                "configuration": configuration.to_payload(),
            }
    except BaseException as error:
        response = {
            "type": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _show_dialog(request: DialogRequest) -> M3C2Configuration | None:
    """Construct and execute the Qt dialog in the GUI child process."""

    from PySide6 import QtCore, QtWidgets

    # CloudCompare may have configured plugin paths for its own Qt build.  A
    # standalone PySide6 process must use the plugins shipped with PySide6;
    # mixing these paths can make even QApplication construction abort.
    plugin_root = Path(
        QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.PluginsPath)
    )
    os.environ["QT_PLUGIN_PATH"] = str(plugin_root)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugin_root / "platforms")
    QtCore.QCoreApplication.setLibraryPaths([str(plugin_root)])

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication(sys.argv[:1])

    dialog = _M3C2Dialog(request, QtWidgets)

    class _RequestBridge(QtCore.QObject):
        request_received = QtCore.Signal(object)

    bridge = _RequestBridge()
    bridge.request_received.connect(dialog.update_request)

    def read_requests() -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
                if message.get("type") == "refresh":
                    bridge.request_received.emit(
                        DialogRequest.from_payload(message["request"])
                    )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                # A malformed refresh must not terminate an otherwise usable
                # configuration window.
                continue

    request_thread = threading.Thread(
        target=read_requests,
        name="py4dgeo-m3c2-configuration-reader",
        daemon=True,
    )
    request_thread.start()
    accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
    result = dialog.configuration() if accepted else None

    if owns_application:
        application.quit()
    return result


class _M3C2Dialog:
    """Qt widget whose inputs and output are configuration values only."""

    def __init__(self, request: DialogRequest, QtWidgets: Any):
        self.QtWidgets = QtWidgets
        self.request = request
        self.dialog = QtWidgets.QDialog()
        self.dialog.setWindowTitle("py4dgeo M3C2")
        self.dialog.setMinimumWidth(480)
        layout = QtWidgets.QVBoxLayout(self.dialog)

        description = QtWidgets.QLabel(
            "Compute signed M3C2 distances for CloudCompare point clouds."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.reference = self._cloud_combo()
        self.compared = self._cloud_combo()
        self.core = self._cloud_combo()
        form.addRow("Reference cloud", self.reference)
        form.addRow("Compared cloud", self.compared)
        form.addRow("Core points", self.core)
        self.cloud_status = QtWidgets.QLabel()
        self.cloud_status.setWordWrap(True)
        form.addRow("", self.cloud_status)

        defaults = M3C2Parameters()
        self.normal_radii = QtWidgets.QLineEdit(
            ", ".join(str(radius) for radius in defaults.normal_radii)
        )
        self.normal_radii.setToolTip(
            "One or more py4dgeo search radii, separated by commas"
        )
        form.addRow("Normal radii", self.normal_radii)
        self.cylinder_radius = self._spin(defaults.cylinder_radius, 1.0e-9)
        form.addRow("Projection cylinder radius", self.cylinder_radius)
        self.max_distance = self._spin(defaults.max_distance, 0.0)
        self.max_distance.setSpecialValueText("Automatic")
        form.addRow("Maximum projection depth", self.max_distance)
        self.registration_error = self._spin(defaults.registration_error, 0.0)
        form.addRow("Registration error", self.registration_error)

        orientation = QtWidgets.QHBoxLayout()
        self.orientation = []
        for label, initial in zip("XYZ", defaults.orientation_vector):
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
        self.compute_button = buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        self.compute_button.setText("Compute")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)
        self.update_request(request, preserve_selection=False)

    def _cloud_combo(self):
        combo = self.QtWidgets.QComboBox()
        return combo

    def update_request(
        self, request: DialogRequest, preserve_selection: bool = True
    ) -> None:
        """Apply a refreshed CloudCompare cloud list on the GUI thread."""

        combos = (self.reference, self.compared, self.core)
        previous_ids = tuple(combo.currentData() for combo in combos)
        default_ids = (
            request.reference_cloud_id,
            request.compared_cloud_id,
            request.core_cloud_id,
        )
        available_ids = {cloud.unique_id for cloud in request.clouds}
        had_choices = len(self.request.clouds) >= 2
        self.request = request

        for combo, previous_id, default_id in zip(
            combos, previous_ids, default_ids
        ):
            combo.clear()
            for cloud in request.clouds:
                combo.addItem(cloud.label, cloud.unique_id)
            selected_id = (
                previous_id
                if preserve_selection and had_choices and previous_id in available_ids
                else default_id
            )
            selected_index = combo.findData(selected_id)
            if selected_index >= 0:
                combo.setCurrentIndex(selected_index)

        if not request.clouds:
            status = "No point clouds are currently loaded in CloudCompare."
        elif len(request.clouds) == 1:
            status = "Load one more point cloud before computing."
        else:
            status = f"{len(request.clouds)} point clouds available."
        self.cloud_status.setText(status)
        self.compute_button.setEnabled(len(request.clouds) >= 2)

    def _spin(self, value: float, minimum: float):
        widget = self.QtWidgets.QDoubleSpinBox()
        widget.setDecimals(6)
        widget.setRange(minimum, 1.0e12)
        widget.setValue(value)
        return widget

    def configuration(self) -> M3C2Configuration:
        reference_id = self.reference.currentData()
        compared_id = self.compared.currentData()
        core_id = self.core.currentData()
        if reference_id is None or compared_id is None or core_id is None:
            raise ValueError(
                "Load at least two point clouds in CloudCompare before computing."
            )
        configuration = M3C2Configuration(
            reference_cloud_id=int(reference_id),
            compared_cloud_id=int(compared_id),
            core_cloud_id=int(core_id),
            parameters=M3C2Parameters(
                normal_radii=parse_normal_radii(self.normal_radii.text()),
                cylinder_radius=self.cylinder_radius.value(),
                max_distance=self.max_distance.value(),
                registration_error=self.registration_error.value(),
                orientation_vector=tuple(
                    widget.value() for widget in self.orientation
                ),
                robust_aggregation=self.robust.isChecked(),
            ),
            output_name=self.output_name.text().strip(),
        )
        configuration.validate()
        return configuration

    def _validate_and_accept(self) -> None:
        try:
            self.configuration()
        except ValueError as error:
            self.QtWidgets.QMessageBox.warning(
                self.dialog, "Invalid M3C2 configuration", str(error)
            )
            return
        self.dialog.accept()

    def exec(self) -> int:
        return self.dialog.exec()


if __name__ == "__main__":
    main()
