from __future__ import annotations

from typing import Any

from simcore.metrics.pair_criticality import (
    compute_pair_criticality,
    parse_pair_criticality_options,
)
from simcore.monitoring.sample import MonitorSample

from .base import FrameRecorder

PAIR_CRITICALITY_FIELDS = (
    "distance_m",
    "longitudinal_distance_m",
    "lateral_distance_m",
    "closing_speed_mps",
    "relative_longitudinal_speed_mps",
    "relative_lateral_speed_mps",
    "relative_longitudinal_acceleration_mps2",
    "relative_lateral_acceleration_mps2",
    "thw_s",
    "drac_mps2",
)
DEFAULT_PAIR_CRITICALITY_FIELDS = (
    "longitudinal_distance_m",
    "lateral_distance_m",
    "closing_speed_mps",
    "thw_s",
    "drac_mps2",
)


class PairCriticalityFrameRecorder(FrameRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("pair_criticality frame recorder requires actor_id_a and actor_id_b")
        self.actor_id_a = int(config["actor_id_a"])
        self.actor_id_b = int(config["actor_id_b"])
        self.lateral_threshold_m = parse_pair_criticality_options(
            config, owner="pair_criticality frame recorder"
        )
        self._fields = self._select_fields(
            {"fields": config.get("fields", DEFAULT_PAIR_CRITICALITY_FIELDS)},
            PAIR_CRITICALITY_FIELDS,
        )

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        result = compute_pair_criticality(
            getattr(sample.runtime_frame, "objects", None) or [],
            self.actor_id_a,
            self.actor_id_b,
            lateral_threshold_m=self.lateral_threshold_m,
        )
        if result is None:
            return {}
        return {field: getattr(result, field) for field in self._fields}
