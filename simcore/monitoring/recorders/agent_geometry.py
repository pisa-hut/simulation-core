from __future__ import annotations

import json

from simcore.monitoring.geometry import actor_geometry
from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .utils import object_actor_id

AGENT_GEOMETRY_FIELDS = (
    "step_index",
    "sim_time_ms",
    "agent_id",
    "shape_type",
    "length_m",
    "width_m",
    "height_m",
    "reference_point",
    "footprint_json",
    "source",
)


class AgentGeometryRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.once = bool(config.get("once", True))
        self._seen_agents: set[int] = set()

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

    def record(self, sample: MonitorSample) -> list[LogRow]:
        rows = []
        objects = getattr(sample.runtime_frame, "objects", None) or []

        for index, obj in enumerate(objects):
            agent_id = object_actor_id(obj, index)
            if self.once and agent_id in self._seen_agents:
                continue
            self._seen_agents.add(agent_id)
            geometry = actor_geometry(obj)
            rows.append(
                LogRow(
                    stream=self.name,
                    row={
                        "step_index": sample.step_index,
                        "sim_time_ms": sample.sim_time_ms,
                        "agent_id": agent_id,
                        "shape_type": geometry.shape_type if geometry else None,
                        "length_m": geometry.length_m if geometry else None,
                        "width_m": geometry.width_m if geometry else None,
                        "height_m": geometry.height_m if geometry else None,
                        "reference_point": None,
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
