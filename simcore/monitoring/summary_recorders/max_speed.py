from __future__ import annotations

from typing import Any

from simcore.metrics.ttc import find_actor, float_attr, object_kinematic
from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder

MAX_SPEED_FIELDS = ("max_speed_mps",)


class MaxSpeedSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id" not in config:
            raise ValueError("max_speed summary recorder requires actor_id")
        self.actor_id = int(config["actor_id"])
        self.max_speed_mps: float | None = None

    def fields(self) -> tuple[str, ...]:
        return MAX_SPEED_FIELDS

    def reset(self) -> None:
        self.max_speed_mps = None

    def update(self, sample: MonitorSample) -> None:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        actor = find_actor(objects, self.actor_id)
        if actor is None:
            return

        speed = float_attr(object_kinematic(actor), "speed")
        if speed is None:
            return
        if self.max_speed_mps is None or speed > self.max_speed_mps:
            self.max_speed_mps = speed

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"max_speed_mps": self.max_speed_mps}
