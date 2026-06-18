from __future__ import annotations

from typing import Any

from simcore.metrics.ttc import (
    compute_pair_ttc,
    parse_pair_ttc_options,
)
from simcore.monitoring.sample import MonitorSample

from .base import FrameRecorder

PAIR_TTC_FIELDS = (
    "distance_m",
    "longitudinal_distance_m",
    "lateral_distance_m",
    "closing_speed_mps",
    "ttc_s",
)
DEFAULT_PAIR_TTC_FIELDS = (
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
        options = parse_pair_ttc_options(config, owner="pair_ttc frame recorder")
        self.mode = options.mode
        self.lateral_threshold_m = options.lateral_threshold_m
        self._fields = self._select_fields(
            {"fields": config.get("fields", DEFAULT_PAIR_TTC_FIELDS)},
            PAIR_TTC_FIELDS,
        )

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        collisions = getattr(sample.runtime_frame, "collision", None) or []
        result = compute_pair_ttc(
            objects,
            self.actor_id_a,
            self.actor_id_b,
            mode=self.mode,
            lateral_threshold_m=self.lateral_threshold_m,
            collisions=collisions,
        )
        if result is None:
            return {}

        values = {
            "distance_m": result.distance_m,
            "longitudinal_distance_m": result.longitudinal_distance_m,
            "lateral_distance_m": result.lateral_distance_m,
            "closing_speed_mps": result.closing_speed_mps,
            "ttc_s": result.ttc_s,
        }
        return {field: values[field] for field in self._fields}
