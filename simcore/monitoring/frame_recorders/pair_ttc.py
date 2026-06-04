from __future__ import annotations

from typing import Any

from simcore.metrics.ttc import (
    DEFAULT_LATERAL_THRESHOLD_M,
    DEFAULT_TTC_MODE,
    compute_pair_ttc,
    normalize_ttc_mode,
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
        self.mode = normalize_ttc_mode(config.get("mode", config.get("ttc_mode", DEFAULT_TTC_MODE)))
        self.lateral_threshold_m = _parse_lateral_threshold(config)
        self._fields = self._select_fields(
            {"fields": config.get("fields", DEFAULT_PAIR_TTC_FIELDS)},
            PAIR_TTC_FIELDS,
        )

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        result = compute_pair_ttc(
            objects,
            self.actor_id_a,
            self.actor_id_b,
            mode=self.mode,
            lateral_threshold_m=self.lateral_threshold_m,
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


def _parse_lateral_threshold(config: dict) -> float | None:
    raw_value = config.get("lateral_threshold_m", DEFAULT_LATERAL_THRESHOLD_M)
    if raw_value is None:
        return None
    value = float(raw_value)
    if value < 0:
        raise ValueError("pair_ttc frame recorder lateral_threshold_m must be >= 0")
    return value
