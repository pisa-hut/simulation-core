from __future__ import annotations

from typing import Any

from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder
from .numeric_aggregation import NumericAccumulator
from .numeric_sources import KinematicValueSource

MAX_SPEED_FIELDS = ("max_speed_mps",)


class MaxSpeedSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id" not in config:
            raise ValueError("max_speed summary recorder requires actor_id")
        self.source = KinematicValueSource({"actor_id": config["actor_id"], "field": "speed"})
        self.accumulator = NumericAccumulator(["max"])

    def fields(self) -> tuple[str, ...]:
        return MAX_SPEED_FIELDS

    def reset(self) -> None:
        self.accumulator.reset()

    def update(self, sample: MonitorSample) -> None:
        self.accumulator.update(self.source.read(sample), sample)

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"max_speed_mps": self.accumulator.record()["max"]}
