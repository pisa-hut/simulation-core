from __future__ import annotations

from math import cos, hypot, sin
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic
from simcore.monitoring.geometry import actor_geometry
from simcore.monitoring.sample import MonitorSample

from .base import FrameRecorder

PAIR_CLEARANCE_FIELDS = (
    "center_distance_m",
    "clearance_m",
    "longitudinal_clearance_m",
    "lateral_clearance_m",
    "clearance_status",
)


class PairClearanceFrameRecorder(FrameRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("pair_clearance frame recorder requires actor_id_a and actor_id_b")
        self.actor_id_a = int(config["actor_id_a"])
        self.actor_id_b = int(config["actor_id_b"])
        self._fields = self._select_fields(
            {"fields": config.get("fields", PAIR_CLEARANCE_FIELDS)},
            PAIR_CLEARANCE_FIELDS,
        )

    def fields(self) -> tuple[str, ...]:
        return self._fields

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        actor_a = find_actor(objects, self.actor_id_a)
        actor_b = find_actor(objects, self.actor_id_b)
        if actor_a is None or actor_b is None:
            return {field: _value_for_missing_actor(field) for field in self._fields}

        kin_a = object_kinematic(actor_a)
        kin_b = object_kinematic(actor_b)
        ax = float_attr(kin_a, "x")
        ay = float_attr(kin_a, "y")
        bx = float_attr(kin_b, "x")
        by = float_attr(kin_b, "y")
        if ax is None or ay is None or bx is None or by is None:
            return {field: _value_for_invalid_geometry(field) for field in self._fields}

        dx = bx - ax
        dy = by - ay
        center_distance_m = hypot(dx, dy)
        dims_a = _dimensions(actor_a)
        dims_b = _dimensions(actor_b)
        if dims_a is None or dims_b is None:
            values = {
                "center_distance_m": center_distance_m,
                "clearance_m": None,
                "longitudinal_clearance_m": None,
                "lateral_clearance_m": None,
                "clearance_status": "missing_geometry",
            }
            return {field: values[field] for field in self._fields}

        yaw_a = float_attr(kin_a, "yaw") or 0.0
        forward_x = cos(yaw_a)
        forward_y = sin(yaw_a)
        side_x = -sin(yaw_a)
        side_y = cos(yaw_a)
        longitudinal_distance_m = dx * forward_x + dy * forward_y
        lateral_distance_m = dx * side_x + dy * side_y
        longitudinal_clearance_m = abs(longitudinal_distance_m) - (dims_a[0] + dims_b[0]) / 2.0
        lateral_clearance_m = abs(lateral_distance_m) - (dims_a[1] + dims_b[1]) / 2.0
        clearance_m = max(longitudinal_clearance_m, lateral_clearance_m)
        values = {
            "center_distance_m": center_distance_m,
            "clearance_m": clearance_m,
            "longitudinal_clearance_m": longitudinal_clearance_m,
            "lateral_clearance_m": lateral_clearance_m,
            "clearance_status": "valid",
        }
        return {field: values[field] for field in self._fields}


def _dimensions(actor: Any) -> tuple[float, float, float] | None:
    geometry = actor_geometry(actor)
    if geometry is None or geometry.length_m is None or geometry.width_m is None:
        return None
    return geometry.length_m, geometry.width_m, geometry.height_m or 0.0


def _value_for_missing_actor(field: str) -> Any:
    return "missing_actor" if field == "clearance_status" else None


def _value_for_invalid_geometry(field: str) -> Any:
    return "invalid_geometry" if field == "clearance_status" else None
