"""Serializable messages shared by the M3C2 plugin and its GUI process.

This module deliberately has no dependencies on CloudCompare, Qt, numpy, or
py4dgeo.  Keeping the wire types here makes it difficult to accidentally pass
point-cloud objects or coordinate arrays across the process boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class M3C2Parameters:
    """Parameters exposed by the M3C2 dialog, in py4dgeo units."""

    normal_radii: tuple[float, ...] = (0.5, 1.0, 2.0)
    cylinder_radius: float = 1.0
    max_distance: float = 0.0
    registration_error: float = 0.0
    orientation_vector: tuple[float, float, float] = (0.0, 0.0, 1.0)
    robust_aggregation: bool = False

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> M3C2Parameters:
        return cls(
            normal_radii=tuple(float(value) for value in payload["normal_radii"]),
            cylinder_radius=float(payload["cylinder_radius"]),
            max_distance=float(payload["max_distance"]),
            registration_error=float(payload["registration_error"]),
            orientation_vector=tuple(
                float(value) for value in payload["orientation_vector"]
            ),
            robust_aggregation=bool(payload["robust_aggregation"]),
        )


@dataclass(frozen=True)
class CloudChoice:
    """The metadata needed to select a cloud without transferring the cloud."""

    unique_id: int
    label: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CloudChoice:
        return cls(unique_id=int(payload["unique_id"]), label=str(payload["label"]))


@dataclass(frozen=True)
class DialogRequest:
    """Configuration context sent from CloudCompare to the GUI process."""

    clouds: tuple[CloudChoice, ...]
    reference_cloud_id: int | None
    compared_cloud_id: int | None
    core_cloud_id: int | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "clouds": [cloud.to_payload() for cloud in self.clouds],
            "reference_cloud_id": self.reference_cloud_id,
            "compared_cloud_id": self.compared_cloud_id,
            "core_cloud_id": self.core_cloud_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> DialogRequest:
        return cls(
            clouds=tuple(
                CloudChoice.from_payload(cloud) for cloud in payload["clouds"]
            ),
            reference_cloud_id=_optional_cloud_id(payload["reference_cloud_id"]),
            compared_cloud_id=_optional_cloud_id(payload["compared_cloud_id"]),
            core_cloud_id=_optional_cloud_id(payload["core_cloud_id"]),
        )


@dataclass(frozen=True)
class M3C2Configuration:
    """Complete configuration returned by the GUI process."""

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

    def to_payload(self) -> dict[str, Any]:
        return {
            "reference_cloud_id": self.reference_cloud_id,
            "compared_cloud_id": self.compared_cloud_id,
            "core_cloud_id": self.core_cloud_id,
            "parameters": self.parameters.to_payload(),
            "output_name": self.output_name,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> M3C2Configuration:
        configuration = cls(
            reference_cloud_id=int(payload["reference_cloud_id"]),
            compared_cloud_id=int(payload["compared_cloud_id"]),
            core_cloud_id=int(payload["core_cloud_id"]),
            parameters=M3C2Parameters.from_payload(payload["parameters"]),
            output_name=str(payload["output_name"]),
        )
        configuration.validate()
        return configuration


def parse_normal_radii(value: str) -> tuple[float, ...]:
    """Parse a comma/semicolon/whitespace separated list of positive radii."""

    tokens = value.replace(";", " ").replace(",", " ").split()
    if not tokens:
        raise ValueError("Specify at least one normal radius.")
    radii = tuple(float(token) for token in tokens)
    if any(not math.isfinite(radius) or radius <= 0.0 for radius in radii):
        raise ValueError("Normal radii must be finite and greater than zero.")
    return radii


def _optional_cloud_id(value: Any) -> int | None:
    return None if value is None else int(value)
