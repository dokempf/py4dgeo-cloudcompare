"""In-process Tkinter front end for :class:`py4dgeo.M3C2`.

This is an alternative to :mod:`py4dgeo_cloudcompare.m3c2`.  It deliberately
uses the standard-library Tk bindings instead of importing another Qt binding
into CloudCompare, and it does not create a child process.
"""

from __future__ import annotations

import time
from typing import Any

import pycc

from .m3c2 import (
    M3C2Plugin,
    _clear_cloudcompare_wait_cursor,
    _dialog_request,
    _loaded_point_clouds,
)
from .m3c2_protocol import (
    DialogRequest,
    M3C2Configuration,
    M3C2Parameters,
    parse_normal_radii,
)


class M3C2TkinterPlugin(M3C2Plugin):
    """CloudCompare M3C2 plugin with an in-process Tkinter dialog."""

    def getActions(self):
        return [
            pycc.Action(
                name="Compute M3C2 (py4dgeo, Tkinter)",
                target=self.run,
            )
        ]

    def run(self) -> None:
        request = _dialog_request(self.app, _loaded_point_clouds(self.app))
        dialog = _M3C2TkinterDialog(request)
        last_request = request.to_payload()
        _clear_cloudcompare_wait_cursor()

        try:
            # Both GUI toolkits run on the CloudCompare action thread.  A
            # small cooperative loop services Tk and the host's native Qt
            # event queue without starting another Python process.
            while dialog.is_open:
                request = _dialog_request(
                    self.app, _loaded_point_clouds(self.app)
                )
                payload = request.to_payload()
                if payload != last_request:
                    dialog.update_request(request)
                    last_request = payload

                dialog.process_events()
                if dialog.is_open:
                    pycc.ProcessEvents()
                    time.sleep(0.02)
            configuration = dialog.result
        finally:
            dialog.destroy()

        if configuration is not None:
            self._compute(configuration)


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
        self.normal_radii = tk.StringVar(
            self.root,
            value=", ".join(str(radius) for radius in defaults.normal_radii),
        )
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
        self._add_entry(frame, row, "Normal radii", self.normal_radii)
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
                normal_radii=parse_normal_radii(self.normal_radii.get()),
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
