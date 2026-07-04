from __future__ import annotations

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .utils import (
    float_attr,
    object_actor_id,
    object_entity_name,
    object_kinematic,
    object_sim_tracking_id,
)

AGENT_STATES_FIELDS = (
    "step_index",
    "sim_time_ms",
    "agent_id",
    "sim_tracking_id",
    "entity_name",
    "is_ego",
    "x",
    "y",
    "z",
    "yaw",
    "speed",
    "acceleration",
    "yaw_rate",
    "yaw_acceleration",
)


class AgentStatesRecorder(Recorder):
    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=AGENT_STATES_FIELDS,
            )
        ]

    def record(self, sample: MonitorSample) -> list[LogRow]:
        rows = []
        objects = getattr(sample.runtime_frame, "objects", None) or []

        for obj in objects:
            kinematic = object_kinematic(obj)
            rows.append(
                LogRow(
                    stream=self.name,
                    row={
                        "step_index": sample.step_index,
                        "sim_time_ms": sample.sim_time_ms,
                        "agent_id": object_actor_id(obj),
                        "sim_tracking_id": object_sim_tracking_id(obj),
                        "entity_name": object_entity_name(obj),
                        "is_ego": bool(getattr(obj, "is_ego", False)),
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
            )

        return rows
