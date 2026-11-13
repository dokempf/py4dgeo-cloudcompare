"""Reusable Tkinter widgets for numeric configuration values."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import math
import tkinter as tk
from tkinter import ttk
from typing import Any

__all__ = ["FloatList"]


class FloatList(ttk.Frame):
    """Edit a list of finite floats without parsing a delimited string.

    The listbox is only a presentation of the typed Python values returned by
    :meth:`get`. Applications can supply additional validation and an error
    callback for domain-specific constraints.
    """

    def __init__(
        self,
        master: Any,
        values: Iterable[float] = (),
        *,
        validator: Callable[[float], None] | None = None,
        on_invalid: Callable[[ValueError], None] | None = None,
        spinbox_from: float = -1.0e12,
        spinbox_to: float = 1.0e12,
        increment: float = 0.1,
        height: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._validator = validator
        self._on_invalid = on_invalid
        self._values: list[float] = []

        initial_values = tuple(self._validated(value) for value in values)
        self._new_value = tk.DoubleVar(
            self, value=initial_values[-1] if initial_values else 0.0
        )

        self.columnconfigure(0, weight=1)
        self._listbox = tk.Listbox(
            self,
            height=height,
            exportselection=False,
            selectmode=tk.EXTENDED,
        )
        self._listbox.grid(row=0, column=0, rowspan=2, sticky="nsew")

        entry = ttk.Spinbox(
            self,
            textvariable=self._new_value,
            from_=spinbox_from,
            to=spinbox_to,
            increment=increment,
            width=12,
        )
        entry.grid(row=0, column=1, sticky="ew", padx=(8, 4))
        entry.bind("<Return>", self._add_from_event)
        ttk.Button(self, text="Add", command=self._add_from_entry).grid(
            row=0, column=2, sticky="ew"
        )
        ttk.Button(
            self, text="Remove", command=self.remove_selected
        ).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(8, 0),
            pady=(4, 0),
        )
        self._listbox.bind("<Delete>", self._remove_from_event)

        for value in initial_values:
            self._append_validated(value, select=False)

    def get(self) -> tuple[float, ...]:
        """Return the current values independently of their display strings."""

        return tuple(self._values)

    def append(self, value: float) -> None:
        """Validate and append one value."""

        self._append_validated(self._validated(value))

    def remove_selected(self) -> None:
        """Remove all values currently selected in the listbox."""

        for index in reversed(self._listbox.curselection()):
            del self._values[index]
            self._listbox.delete(index)

    def _validated(self, value: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError, tk.TclError) as error:
            raise ValueError("Enter a finite number.") from error
        if not math.isfinite(result):
            raise ValueError("Enter a finite number.")
        if self._validator is not None:
            self._validator(result)
        return result

    def _append_validated(self, value: float, *, select: bool = True) -> None:
        self._values.append(value)
        self._listbox.insert(tk.END, format(value, "g"))
        if not select:
            return
        last_index = len(self._values) - 1
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(last_index)
        self._listbox.see(last_index)

    def _add_from_entry(self) -> None:
        try:
            self.append(self._new_value.get())
        except (ValueError, tk.TclError) as error:
            invalid = (
                error
                if isinstance(error, ValueError)
                else ValueError("Enter a finite number.")
            )
            if self._on_invalid is not None:
                self._on_invalid(invalid)
            else:
                self.bell()

    def _add_from_event(self, _event: Any) -> None:
        self._add_from_entry()

    def _remove_from_event(self, _event: Any) -> None:
        self.remove_selected()
