"""Models and helpers for comparing laps loaded from multiple saved files."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from gt7dashboard import gt7helper
from gt7dashboard.gt7lap import Lap


MAX_LAP_LENGTH_DIFFERENCE_RATIO = 0.15
"""Largest supported total-distance difference for a lap-to-lap comparison."""


@dataclass(frozen=True)
class ComparisonLap:
    """A lap together with the saved file it came from.

    Provenance belongs to the comparison UI rather than :class:`Lap`: this keeps
    existing JSON files compatible and avoids persisting UI-only fields.
    """

    identifier: str
    source_path: str
    source_name: str
    lap_index: int
    lap: Lap

    @property
    def distance_m(self) -> float:
        return get_lap_distance(self.lap)

    @property
    def has_telemetry(self) -> bool:
        return has_required_comparison_data(self.lap)

    @property
    def lap_time_text(self) -> str:
        lap_time = getattr(self.lap, "lap_finish_time", 0)
        if not lap_time:
            return "—"
        return gt7helper.seconds_to_lap_time(lap_time / 1000)

    @property
    def select_label(self) -> str:
        return (
            f"{self.source_name} · Lap {self.lap.number} · "
            f"Saved #{self.lap_index + 1} · {self.lap_time_text}"
        )


@dataclass(frozen=True)
class ComparisonLoadResult:
    records: list[ComparisonLap]
    errors: list[str]


@dataclass(frozen=True)
class LapCompatibility:
    """Whether two saved laps can be meaningfully shown on one distance scale."""

    compatible: bool
    shared_distance_m: float
    message: str
    warning: bool = False


def get_lap_distance(lap: Lap) -> float:
    """Return the greatest finite distance available for *lap*."""
    distances = gt7helper.get_x_axis_for_distance(lap)
    finite_distances = []
    for distance in distances:
        try:
            numeric_distance = float(distance)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric_distance) and numeric_distance >= 0:
            finite_distances.append(numeric_distance)
    return max(finite_distances, default=0.0)


def has_required_comparison_data(lap: Lap) -> bool:
    """Return whether a lap can provide both telemetry traces and a time delta."""
    return (
        len(getattr(lap, "data_speed", [])) > 1
        and len(getattr(lap, "data_time", [])) > 1
        and get_lap_distance(lap) > 0
    )


def _lap_edge_positions(lap: Lap):
    """Return the first and last finite x/z positions, if the lap has them."""
    positions = []
    for x, z in zip(
        getattr(lap, "data_position_x", []),
        getattr(lap, "data_position_z", []),
    ):
        try:
            x_value = float(x)
            z_value = float(z)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x_value) and math.isfinite(z_value):
            positions.append((x_value, z_value))

    if not positions:
        return None, None
    return positions[0], positions[-1]


def assess_lap_compatibility(
    reference_lap: Lap,
    comparison_lap: Lap,
    max_length_difference_ratio: float = MAX_LAP_LENGTH_DIFFERENCE_RATIO,
) -> LapCompatibility:
    """Assess whether two laps are suitable for a distance-based comparison.

    GT7 telemetry records do not currently include an explicit circuit id. A
    major length mismatch is therefore treated as an error, while a position
    mismatch remains a visible warning so manually finished laps can still be
    inspected deliberately.
    """
    reference_distance = get_lap_distance(reference_lap)
    comparison_distance = get_lap_distance(comparison_lap)

    if not (
        has_required_comparison_data(reference_lap)
        and has_required_comparison_data(comparison_lap)
    ):
        return LapCompatibility(
            compatible=False,
            shared_distance_m=0,
            message="Both selected laps need recorded telemetry.",
        )

    shared_distance = min(reference_distance, comparison_distance)
    length_difference_ratio = abs(reference_distance - comparison_distance) / max(
        reference_distance, comparison_distance
    )
    if length_difference_ratio > max_length_difference_ratio:
        return LapCompatibility(
            compatible=False,
            shared_distance_m=shared_distance,
            message=(
                "The selected laps differ too much in total distance "
                f"({reference_distance:,.0f} m vs {comparison_distance:,.0f} m)."
            ),
        )

    reference_start, reference_end = _lap_edge_positions(reference_lap)
    comparison_start, comparison_end = _lap_edge_positions(comparison_lap)
    if all(
        point is not None
        for point in (
            reference_start,
            reference_end,
            comparison_start,
            comparison_end,
        )
    ):
        start_gap = math.dist(reference_start, comparison_start)
        end_gap = math.dist(reference_end, comparison_end)
        endpoint_tolerance = max(50.0, min(250.0, shared_distance * 0.05))
        if start_gap > endpoint_tolerance or end_gap > endpoint_tolerance:
            return LapCompatibility(
                compatible=True,
                shared_distance_m=shared_distance,
                warning=True,
                message=(
                    "Lap lengths are similar, but their start or finish positions "
                    "differ. Confirm that both laps use the same course."
                ),
            )

    return LapCompatibility(
        compatible=True,
        shared_distance_m=shared_distance,
        message=f"Shared comparison distance: {shared_distance:,.0f} m.",
    )


def load_comparison_laps(paths: Iterable[str]) -> ComparisonLoadResult:
    """Load every selected JSON file and preserve per-lap file provenance."""
    records = []
    errors = []
    seen_paths = set()

    for path in paths:
        normalized_path = str(Path(path).expanduser().resolve())
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)

        try:
            laps = gt7helper.load_laps_from_json(normalized_path)
        except (OSError, ValueError, TypeError) as error:
            errors.append(f"{Path(path).name}: {error}")
            continue

        source_name = Path(normalized_path).name
        for lap_index, lap in enumerate(laps):
            records.append(
                ComparisonLap(
                    identifier=f"{normalized_path}::{lap_index}",
                    source_path=normalized_path,
                    source_name=source_name,
                    lap_index=lap_index,
                    lap=lap,
                )
            )

    return ComparisonLoadResult(records=records, errors=errors)


def comparison_table_data(records: Iterable[ComparisonLap]) -> dict[str, list]:
    """Build a Bokeh-friendly, source-aware table for comparison selection."""
    data = {
        "identifier": [],
        "source": [],
        "number": [],
        "time": [],
        "car_name": [],
        "timestamp": [],
        "distance": [],
        "status": [],
    }
    for record in records:
        timestamp = getattr(record.lap, "lap_start_timestamp", "")
        if hasattr(timestamp, "strftime"):
            timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        elif timestamp == -1:
            timestamp = ""
        else:
            timestamp = str(timestamp)

        data["identifier"].append(record.identifier)
        data["source"].append(record.source_name)
        data["number"].append(record.lap.number)
        data["time"].append(record.lap_time_text)
        data["car_name"].append(record.lap.car_name())
        data["timestamp"].append(timestamp)
        data["distance"].append(f"{record.distance_m:,.0f} m")
        data["status"].append("Ready" if record.has_telemetry else "No telemetry")

    return data
