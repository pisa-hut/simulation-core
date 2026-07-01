from __future__ import annotations

import json
import math
from typing import Any

from google.protobuf.json_format import MessageToDict
from pisa_api import control_pb2

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder

FIELDS = (
    "step_index",
    "sim_time_ms",
    "control_type",
    "throttle",
    "brake",
    "steer",
    "speed",
    "acceleration",
    "steering_angle",
    "steering_angle_velocity",
    "jerk",
    "payload_json",
)

ALIASES = {
    "brake": ("brake", "break"),
    "steer": ("steer", "steering"),
    "steering_angle": ("steering_angle", "steeringAngle"),
    "steering_angle_velocity": (
        "steering_angle_velocity",
        "steeringAngleVelocity",
    ),
}


class ControlCommandsRecorder(Recorder):
    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=FIELDS,
            )
        ]

    def record(self, sample: MonitorSample) -> list[LogRow]:
        mode, payload = control_parts(sample.control)
        row = {
            "step_index": sample.step_index,
            "sim_time_ms": sample.sim_time_ms,
            "control_type": mode,
            "payload_json": json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for field in FIELDS:
            if field in row:
                continue
            row[field] = first_finite(
                payload,
                ALIASES.get(field, (field,)),
            )
        return [LogRow(stream=self.name, row=row)]


def control_parts(control: Any) -> tuple[str, dict[str, Any]]:
    if control is None:
        return "none", {}
    if hasattr(control, "mode") and hasattr(control, "payload"):
        try:
            mode = control_pb2.CtrlMode.Name(int(control.mode)).lower()
        except TypeError, ValueError:
            mode = str(control.mode).lower()
        try:
            payload = MessageToDict(
                control.payload,
                preserving_proto_field_name=True,
            )
        except Exception:
            payload = {}
        return mode, payload if isinstance(payload, dict) else {}
    return "unknown", {}


def first_finite(
    payload: dict[str, Any],
    aliases: tuple[str, ...],
) -> float | None:
    for name in aliases:
        try:
            value = float(payload[name])
        except KeyError, TypeError, ValueError:
            continue
        if math.isfinite(value):
            return value
    return None
