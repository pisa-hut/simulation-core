from __future__ import annotations

from typing import Any


def object_actor_id(obj: Any, fallback_index: int) -> int:
    for field_name in ("actor_id", "agent_id", "id", "object_id"):
        if hasattr(obj, field_name):
            try:
                return int(getattr(obj, field_name))
            except TypeError, ValueError:
                break
    return fallback_index


def object_kinematic(obj: Any) -> Any | None:
    return getattr(obj, "kinematic", obj)


def float_attr(obj: Any, name: str) -> float | None:
    if obj is None or not hasattr(obj, name):
        return None
    value = getattr(obj, name)
    if value is None:
        return None
    return float(value)
