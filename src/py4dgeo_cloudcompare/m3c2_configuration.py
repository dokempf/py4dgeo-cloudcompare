"""Configuration values shared by the M3C2 plugin and Tkinter dialog."""

from __future__ import annotations

from dataclasses import dataclass
import math


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
class CloudChoice:
    """A point cloud's display label and CloudCompare unique ID."""

    unique_id: int
    label: str


@dataclass(frozen=True)
class DialogRequest:
    """The current clouds and default selections for the dialog."""

    clouds: tuple[CloudChoice, ...]
    reference_cloud_id: int | None
    compared_cloud_id: int | None
    core_cloud_id: int | None


@dataclass(frozen=True)
class M3C2Configuration:
    """Complete M3C2 configuration returned by the dialog."""

    reference_cloud_id: int
    compared_cloud_id: int
    core_cloud_id: int
    parameters: M3C2Parameters
    output_name: str

    def validate(self) -> None:
        if self.reference_cloud_id == self.compared_cloud_id:
            raise ValueError("Reference and compared clouds must be different.")
        if not self.output_name.strip():
            raise ValueError("Specify a name for the output cloud.")

        parameters = self.parameters
        if not parameters.normal_radii or any(
            not math.isfinite(radius) or radius <= 0.0
            for radius in parameters.normal_radii
        ):
            raise ValueError("Normal radii must be finite and greater than zero.")
        if (
            not math.isfinite(parameters.cylinder_radius)
            or parameters.cylinder_radius <= 0.0
        ):
            raise ValueError(
                "The projection cylinder radius must be finite and greater than zero."
            )
        if (
            not math.isfinite(parameters.max_distance)
            or parameters.max_distance < 0.0
            or not math.isfinite(parameters.registration_error)
            or parameters.registration_error < 0.0
        ):
            raise ValueError(
                "Maximum depth and registration error must be finite and non-negative."
            )
        orientation = parameters.orientation_vector
        if len(orientation) != 3 or not all(
            math.isfinite(value) for value in orientation
        ):
            raise ValueError("The orientation vector must contain three finite values.")
        if not any(value != 0.0 for value in orientation):
            raise ValueError("The normal orientation vector must not be zero.")


def parse_normal_radii(value: str) -> tuple[float, ...]:
    """Parse a comma/semicolon/whitespace separated list of positive radii."""

    tokens = value.replace(";", " ").replace(",", " ").split()
    if not tokens:
        raise ValueError("Specify at least one normal radius.")
    radii = tuple(float(token) for token in tokens)
    if any(not math.isfinite(radius) or radius <= 0.0 for radius in radii):
        raise ValueError("Normal radii must be finite and greater than zero.")
    return radii
