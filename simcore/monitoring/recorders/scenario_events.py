from __future__ import annotations

import json
from typing import Any

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .collision_events import CollisionEventsRecorder

SCENARIO_EVENT_FIELDS = (
    "step_index",
    "sim_time_ms",
    "event_type",
    "actor_id",
    "actor_id_b",
    "x",
    "y",
    "z",
    "source",
    "details_json",
)


class ScenarioEventsRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self._collision_helper = CollisionEventsRecorder({**config, "type": "collision_events"})
        self._started = False
        self._last_sample: MonitorSample | None = None

    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=SCENARIO_EVENT_FIELDS,
            )
        ]

    def reset(self) -> None:
        self._started = False
        self._last_sample = None
        self._collision_helper.reset()

    def record(self, sample: MonitorSample) -> list[LogRow]:
        self._last_sample = sample
        rows = []
        if not self._started:
            self._started = True
            rows.append(self._event_row(sample, "scenario_start", source="runner"))

        for collision_row in self._collision_helper.record(sample):
            row = collision_row.row
            rows.append(
                self._event_row(
                    sample,
                    "collision",
                    actor_id=row.get("actor_a"),
                    actor_id_b=row.get("actor_b"),
                    x=row.get("x"),
                    y=row.get("y"),
                    z=row.get("z"),
                    source=row.get("position_source") or "runner",
                )
            )
        return rows

    def scenario_end_events(
        self,
        *,
        status: str,
        stop_condition: str,
        reason: str,
    ) -> list[LogRow]:
        if self._last_sample is None:
            return []
        rows = []
        if stop_condition:
            rows.append(
                self._event_row(
                    self._last_sample,
                    "stop_condition",
                    source="runner",
                    details={"stop_condition": stop_condition, "reason": reason},
                )
            )
        rows.append(
            self._event_row(
                self._last_sample,
                "scenario_end",
                source="runner",
                details={"status": status, "reason": reason},
            )
        )
        return rows

    def _event_row(
        self,
        sample: MonitorSample,
        event_type: str,
        *,
        actor_id: Any = None,
        actor_id_b: Any = None,
        x: Any = None,
        y: Any = None,
        z: Any = None,
        source: str,
        details: dict[str, Any] | None = None,
    ) -> LogRow:
        return LogRow(
            stream=self.name,
            row={
                "step_index": sample.step_index,
                "sim_time_ms": sample.sim_time_ms,
                "event_type": event_type,
                "actor_id": actor_id,
                "actor_id_b": actor_id_b,
                "x": x,
                "y": y,
                "z": z,
                "source": source,
                "details_json": json.dumps(
                    details or {},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            },
        )
