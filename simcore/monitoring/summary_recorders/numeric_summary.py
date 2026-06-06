from __future__ import annotations

from typing import Any

from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder
from .numeric_aggregation import NumericAccumulator, apply_transforms, parse_transforms
from .numeric_sources import build_numeric_value_source


class NumericSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.source = build_numeric_value_source(config.get("source"))
        self.transforms = parse_transforms(config.get("transforms"))
        include_extrema_location = config.get("include_extrema_location", False)
        if not isinstance(include_extrema_location, bool):
            raise ValueError("numeric summary config 'include_extrema_location' must be a boolean")
        self.accumulator = NumericAccumulator(
            config.get("aggregations"),
            include_extrema_location=include_extrema_location,
        )

    def fields(self) -> tuple[str, ...]:
        return self.accumulator.fields()

    def reset(self) -> None:
        self.accumulator.reset()

    def update(self, sample: MonitorSample) -> None:
        value = apply_transforms(self.source.read(sample), self.transforms)
        self.accumulator.update(value, sample)

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return self.accumulator.record()
