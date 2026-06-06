from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any

from simcore.monitoring.sample import MonitorSample

SUPPORTED_AGGREGATIONS = ("min", "max", "mean", "std")


@dataclass(frozen=True)
class Extremum:
    value: float
    step_index: int
    sim_time_ms: float


class NumericAccumulator:
    def __init__(
        self,
        aggregations: list[str] | tuple[str, ...],
        *,
        include_extrema_location: bool = False,
    ):
        self.aggregations = normalize_aggregations(aggregations)
        self.include_extrema_location = bool(include_extrema_location)
        self.reset()

    def fields(self) -> tuple[str, ...]:
        fields = list(self.aggregations)
        fields.append("count")
        if self.include_extrema_location:
            for aggregation in self.aggregations:
                if aggregation in {"min", "max"}:
                    fields.extend(
                        (
                            f"{aggregation}_step_index",
                            f"{aggregation}_sim_time_ms",
                        )
                    )
        return tuple(fields)

    def reset(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.minimum: Extremum | None = None
        self.maximum: Extremum | None = None

    def update(self, value: float | None, sample: MonitorSample) -> None:
        if value is None or not isfinite(value):
            return

        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

        location = Extremum(value, sample.step_index, sample.sim_time_ms)
        if self.minimum is None or value < self.minimum.value:
            self.minimum = location
        if self.maximum is None or value > self.maximum.value:
            self.maximum = location

    def record(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for aggregation in self.aggregations:
            values[aggregation] = self._aggregate(aggregation)
        values["count"] = self.count

        if self.include_extrema_location:
            for aggregation in self.aggregations:
                if aggregation not in {"min", "max"}:
                    continue
                extremum = self.minimum if aggregation == "min" else self.maximum
                values[f"{aggregation}_step_index"] = (
                    extremum.step_index if extremum is not None else None
                )
                values[f"{aggregation}_sim_time_ms"] = (
                    extremum.sim_time_ms if extremum is not None else None
                )
        return values

    def _aggregate(self, aggregation: str) -> float | None:
        if self.count == 0:
            return None
        if aggregation == "min":
            return self.minimum.value if self.minimum is not None else None
        if aggregation == "max":
            return self.maximum.value if self.maximum is not None else None
        if aggregation == "mean":
            return self.mean
        if aggregation == "std":
            return sqrt(max(0.0, self.m2 / self.count))
        raise AssertionError(f"Unsupported aggregation: {aggregation}")


def normalize_aggregations(raw_aggregations: Any) -> tuple[str, ...]:
    if not isinstance(raw_aggregations, (list, tuple)) or not raw_aggregations:
        raise ValueError(
            "numeric summary config 'aggregations' must be a non-empty list"
        )
    aggregations = tuple(str(value).strip().lower() for value in raw_aggregations)
    if any(not value for value in aggregations):
        raise ValueError("numeric summary aggregations must not contain empty values")
    if len(set(aggregations)) != len(aggregations):
        raise ValueError("numeric summary aggregations must not contain duplicates")
    unknown = sorted(set(aggregations) - set(SUPPORTED_AGGREGATIONS))
    if unknown:
        allowed = ", ".join(SUPPORTED_AGGREGATIONS)
        raise ValueError(
            f"Unknown numeric summary aggregation(s): {', '.join(unknown)}; "
            f"expected one of: {allowed}"
        )
    return aggregations


def parse_transforms(raw_transforms: Any) -> tuple[str, ...]:
    if raw_transforms is None:
        return ()
    if not isinstance(raw_transforms, (list, tuple)):
        raise ValueError("numeric summary config 'transforms' must be a list")
    transforms = tuple(str(value).strip().lower() for value in raw_transforms)
    unknown = sorted(set(transforms) - set(TRANSFORMS))
    if unknown:
        allowed = ", ".join(sorted(TRANSFORMS))
        raise ValueError(
            f"Unknown numeric summary transform(s): {', '.join(unknown)}; "
            f"expected one of: {allowed}"
        )
    return transforms


def apply_transforms(value: float | None, transforms: tuple[str, ...]) -> float | None:
    if value is None or not isfinite(value):
        return None
    transformed = value
    for transform in transforms:
        transformed = TRANSFORMS[transform](transformed)
        if not isfinite(transformed):
            return None
    return transformed


TRANSFORMS = {
    "abs": abs,
    "negate": lambda value: -value,
    "positive_part": lambda value: max(0.0, value),
}
