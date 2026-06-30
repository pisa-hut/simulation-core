from __future__ import annotations

import json
import logging

from simcore.monitoring.geometry import actor_geometry
from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .utils import object_actor_id, object_entity_name, object_sim_tracking_id

AGENT_GEOMETRY_FIELDS = (
    "step_index",
    "sim_time_ms",
    "agent_id",
    "sim_tracking_id",
    "entity_name",
    "is_ego",
    "shape_type",
    "length_m",
    "width_m",
    "height_m",
    "reference_point",
    "center_offset_x",
    "center_offset_y",
    "center_offset_z",
    "roll_offset",
    "pitch_offset",
    "yaw_offset",
    "footprint_json",
    "source",
)

logger = logging.getLogger(__name__)


class AgentGeometryRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.once = bool(config.get("once", True))
        self._seen_agents: set[int] = set()
        self._geometry_by_agent: dict[int, object] = {}

    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=AGENT_GEOMETRY_FIELDS,
            )
        ]

    def reset(self) -> None:
        self._seen_agents.clear()
        self._geometry_by_agent.clear()

    def record(self, sample: MonitorSample) -> list[LogRow]:
        rows = []
        objects = getattr(sample.runtime_frame, "objects", None) or []

        for obj in objects:
            agent_id = object_actor_id(obj)
            geometry = actor_geometry(obj)
            if self.once and agent_id in self._seen_agents:
                if geometry != self._geometry_by_agent.get(agent_id):
                    logger.warning(
                        "Actor %s geometry changed after first observation; keeping first record",
                        agent_id,
                    )
                continue
            self._seen_agents.add(agent_id)
            self._geometry_by_agent[agent_id] = geometry
            rows.append(
                LogRow(
                    stream=self.name,
                    row={
                        "step_index": sample.step_index,
                        "sim_time_ms": sample.sim_time_ms,
                        "agent_id": agent_id,
                        "sim_tracking_id": object_sim_tracking_id(obj),
                        "entity_name": object_entity_name(obj),
                        "is_ego": bool(getattr(obj, "is_ego", False)),
                        "shape_type": geometry.shape_type if geometry else None,
                        "length_m": geometry.length_m if geometry else None,
                        "width_m": geometry.width_m if geometry else None,
                        "height_m": geometry.height_m if geometry else None,
                        "reference_point": geometry.reference_point if geometry else None,
                        "center_offset_x": geometry.center_offset_x if geometry else None,
                        "center_offset_y": geometry.center_offset_y if geometry else None,
                        "center_offset_z": geometry.center_offset_z if geometry else None,
                        "roll_offset": geometry.roll_offset if geometry else None,
                        "pitch_offset": geometry.pitch_offset if geometry else None,
                        "yaw_offset": geometry.yaw_offset if geometry else None,
                        "footprint_json": json.dumps(
                            geometry.footprint or (),
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if geometry and geometry.footprint
                        else "",
                        "source": "observation" if geometry else "missing",
                    },
                )
            )

        return rows
