from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")

from py4dgeo_cloudcompare.tkinter_widgets import FloatList


class Listbox:
    def __init__(self, values, selection=()):
        self.values = list(values)
        self.selection = tuple(selection)
        self.seen = None

    def insert(self, index, value):
        self.values.append(value)

    def delete(self, index):
        del self.values[index]

    def curselection(self):
        return self.selection

    def selection_clear(self, first, last):
        self.selection = ()

    def selection_set(self, index):
        self.selection = (index,)

    def see(self, index):
        self.seen = index


def float_list(values, *, validator=None, selection=()):
    widget = object.__new__(FloatList)
    widget._validator = validator
    widget._values = list(values)
    widget._listbox = Listbox(
        [format(value, "g") for value in values], selection
    )
    return widget


def test_float_list_owns_typed_values():
    widget = float_list([0.5, 1.0])

    widget.append(-2.5)

    assert widget.get() == (0.5, 1.0, -2.5)
    assert widget._listbox.values == ["0.5", "1", "-2.5"]
    assert widget._listbox.selection == (2,)


@pytest.mark.parametrize("value", ["invalid", float("nan"), float("inf")])
def test_float_list_rejects_non_finite_values(value):
    widget = float_list([0.5])

    with pytest.raises(ValueError, match="finite number"):
        widget.append(value)

    assert widget.get() == (0.5,)


def test_float_list_supports_domain_specific_validation():
    def positive(value):
        if value <= 0.0:
            raise ValueError("must be positive")

    widget = float_list([0.5], validator=positive)

    with pytest.raises(ValueError, match="must be positive"):
        widget.append(0.0)

    assert widget.get() == (0.5,)


def test_float_list_reports_invalid_entry_through_callback():
    errors = []
    widget = float_list([0.5])
    widget._new_value = SimpleNamespace(get=lambda: "invalid")
    widget._on_invalid = errors.append

    widget._add_from_entry()

    assert len(errors) == 1
    assert str(errors[0]) == "Enter a finite number."
    assert widget.get() == (0.5,)


def test_float_list_removes_selected_values():
    widget = float_list([0.5, 1.0, 2.0], selection=(0, 2))

    widget.remove_selected()

    assert widget.get() == (1.0,)
    assert widget._listbox.values == ["1"]
