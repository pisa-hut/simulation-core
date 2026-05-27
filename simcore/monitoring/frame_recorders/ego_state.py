from __future__ import annotations

from typing import Any

from simcore.monitoring.recorders.utils import float_attr, object_actor_id, object_kinematic
from simcore.monitoring.sample import MonitorSample

from .base import FrameRecorder

EGO_ACTOR_ID = 0
EGO_STATE_FIELDS = (
    "x",
    "y",
    "z",
    "yaw",
    "speed",
    "acceleration",
    "yaw_rate",
    "yaw_acceleration",
)


class EgoStateFrameRecorder(FrameRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id = int(config.get("actor_id", EGO_ACTOR_ID))
        self._fields = self._select_fields(config, EGO_STATE_FIELDS)

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        obj = self._find_actor(sample)
        if obj is None:
            return {}

        kinematic = object_kinematic(obj)
        values = {
            "x": float_attr(kinematic, "x"),
            "y": float_attr(kinematic, "y"),
            "z": float_attr(kinematic, "z"),
            "yaw": float_attr(kinematic, "yaw"),
            "speed": float_attr(kinematic, "speed"),
            "acceleration": float_attr(kinematic, "acceleration"),
            "yaw_rate": float_attr(kinematic, "yaw_rate"),
            "yaw_acceleration": float_attr(kinematic, "yaw_acceleration"),
        }
        return {field: values[field] for field in self._fields}

    def _find_actor(self, sample: MonitorSample):
        objects = getattr(sample.runtime_frame, "objects", None) or []
        for index, obj in enumerate(objects):
            if object_actor_id(obj, index) == self.actor_id:
                return obj
        return None
