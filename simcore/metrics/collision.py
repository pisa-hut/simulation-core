from __future__ import annotations

from typing import Any


def pair_collision_occurred(
    collisions: Any,
    actor_id_a: int,
    actor_id_b: int,
) -> bool:
    target_pair = tuple(sorted((int(actor_id_a), int(actor_id_b))))
    for collision in collisions or []:
        if not getattr(collision, "occurred", False):
            continue
        pair = collision_pair(collision)
        if pair == target_pair:
            return True
    return False


def collision_pair(collision: Any) -> tuple[int, int] | None:
    if not _has_field(collision, "actor_a") or not _has_field(collision, "actor_b"):
        return None
    return tuple(sorted((int(collision.actor_a), int(collision.actor_b))))


def _has_field(collision: Any, field_name: str) -> bool:
    has_field = getattr(collision, "HasField", None)
    if callable(has_field):
        try:
            return bool(has_field(field_name))
        except ValueError:
            return False
    return hasattr(collision, field_name)
