from __future__ import annotations

from typing import Any

from simcore.metrics.ttc import compute_pair_ttc
from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder

MIN_TTC_FIELDS = ("min_ttc_s",)


class MinTTCSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("min_ttc summary recorder requires actor_id_a and actor_id_b")
        self.actor_id_a = int(config["actor_id_a"])
        self.actor_id_b = int(config["actor_id_b"])
        self.min_ttc_s: float | None = None

    def fields(self) -> tuple[str, ...]:
        return MIN_TTC_FIELDS

    def reset(self) -> None:
        self.min_ttc_s = None

    def update(self, sample: MonitorSample) -> None:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        result = compute_pair_ttc(objects, self.actor_id_a, self.actor_id_b)
        if result is None or result.ttc_s is None:
            return
        if self.min_ttc_s is None or result.ttc_s < self.min_ttc_s:
            self.min_ttc_s = result.ttc_s

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"min_ttc_s": self.min_ttc_s}
