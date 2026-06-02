from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_actor_states(objects: Any) -> Iterator[tuple[int, Any]]:
    for index, obj in enumerate(objects or []):
        yield object_actor_id(obj, index), obj


def find_actor(objects: Any, actor_id: int):
    for object_id, obj in iter_actor_states(objects):
        if object_id == actor_id:
            return obj
    return None


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
    try:
        return float(value)
    except TypeError, ValueError:
        return None
