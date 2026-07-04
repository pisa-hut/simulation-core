from __future__ import annotations

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .utils import float_attr, object_actor_id, object_kinematic

EGO_ACTOR_ID = 0
EGO_STATE_FIELDS = (
    "step_index",
    "sim_time_ms",
    "x",
    "y",
    "z",
    "yaw",
    "speed",
    "acceleration",
    "yaw_rate",
    "yaw_acceleration",
)


class EgoStateRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id = int(config.get("actor_id", EGO_ACTOR_ID))

    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=EGO_STATE_FIELDS,
            )
        ]

    def record(self, sample: MonitorSample) -> list[LogRow]:
        obj = self._find_ego(sample)
        if obj is None:
            return []

        kinematic = object_kinematic(obj)
        return [
            LogRow(
                stream=self.name,
                row={
                    "step_index": sample.step_index,
                    "sim_time_ms": sample.sim_time_ms,
                    "x": float_attr(kinematic, "x"),
                    "y": float_attr(kinematic, "y"),
                    "z": float_attr(kinematic, "z"),
                    "yaw": float_attr(kinematic, "yaw"),
                    "speed": float_attr(kinematic, "speed"),
                    "acceleration": float_attr(kinematic, "acceleration"),
                    "yaw_rate": float_attr(kinematic, "yaw_rate"),
                    "yaw_acceleration": float_attr(kinematic, "yaw_acceleration"),
                },
            )
        ]

    def _find_ego(self, sample: MonitorSample):
        objects = getattr(sample.runtime_frame, "objects", None) or []
        for obj in objects:
            if object_actor_id(obj) == self.actor_id:
                return obj
        return None
