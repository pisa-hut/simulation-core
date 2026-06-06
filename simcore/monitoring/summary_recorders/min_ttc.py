from __future__ import annotations

from typing import Any

from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder
from .numeric_aggregation import NumericAccumulator
from .numeric_sources import PairTTCValueSource

MIN_TTC_FIELDS = ("min_ttc_s",)


class MinTTCSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("min_ttc summary recorder requires actor_id_a and actor_id_b")
        self.source = PairTTCValueSource({**config, "field": "ttc_s"})
        self.accumulator = NumericAccumulator(["min"])

    def fields(self) -> tuple[str, ...]:
        return MIN_TTC_FIELDS

    def reset(self) -> None:
        self.accumulator.reset()

    def update(self, sample: MonitorSample) -> None:
        self.accumulator.update(self.source.read(sample), sample)

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"min_ttc_s": self.accumulator.record()["min"]}
