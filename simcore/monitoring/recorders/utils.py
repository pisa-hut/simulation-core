from __future__ import annotations

from typing import Any


def object_actor_id(obj: Any) -> int:
    for field_name in ("actor_id", "agent_id", "id", "object_id"):
        if hasattr(obj, field_name):
            try:
                return int(getattr(obj, field_name))
            except TypeError, ValueError:
                break
    raise ValueError("actor state is missing an explicit actor/agent/tracking ID")


def object_sim_tracking_id(obj: Any) -> int | None:
    for field_name in ("sim_tracking_id", "tracking_id"):
        value = getattr(obj, field_name, None)
        if value is not None:
            return int(value)
    return None


def object_entity_name(obj: Any) -> str | None:
    value = getattr(obj, "entity_name", None)
    return str(value) if value not in (None, "") else None


def object_kinematic(obj: Any) -> Any | None:
    return getattr(obj, "kinematic", obj)


def float_attr(obj: Any, name: str) -> float | None:
    if obj is None or not hasattr(obj, name):
        return None
    value = getattr(obj, name)
    if value is None:
        return None
    return float(value)
