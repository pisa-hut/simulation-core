from __future__ import annotations

from typing import Any

from simcore.metrics.ttc import compute_pair_ttc
from simcore.monitoring.sample import MonitorSample

from .base import FrameRecorder

PAIR_TTC_FIELDS = (
    "distance_m",
    "closing_speed_mps",
    "ttc_s",
)


class PairTTCFrameRecorder(FrameRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("pair_ttc frame recorder requires actor_id_a and actor_id_b")
        self.actor_id_a = int(config["actor_id_a"])
        self.actor_id_b = int(config["actor_id_b"])
        self._fields = self._select_fields(config, PAIR_TTC_FIELDS)

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        result = compute_pair_ttc(objects, self.actor_id_a, self.actor_id_b)
        if result is None:
            return {}

        values = {
            "distance_m": result.distance_m,
            "closing_speed_mps": result.closing_speed_mps,
            "ttc_s": result.ttc_s,
        }
        return {field: values[field] for field in self._fields}
