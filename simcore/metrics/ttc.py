from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, sin
from typing import Any


@dataclass(frozen=True)
class PairTTCResult:
    actor_id_a: int
    actor_id_b: int
    distance_m: float
    closing_speed_mps: float | None
    ttc_s: float | None


def compute_pair_ttc(
    objects: Any,
    actor_id_a: int,
    actor_id_b: int,
) -> PairTTCResult | None:
    actor_a = find_actor(objects, actor_id_a)
    actor_b = find_actor(objects, actor_id_b)
    if actor_a is None or actor_b is None:
        return None

    kin_a = object_kinematic(actor_a)
    kin_b = object_kinematic(actor_b)
    ax = float_attr(kin_a, "x")
    ay = float_attr(kin_a, "y")
    bx = float_attr(kin_b, "x")
    by = float_attr(kin_b, "y")
    if ax is None or ay is None or bx is None or by is None:
        return None

    dx = bx - ax
    dy = by - ay
    distance_m = hypot(dx, dy)
    if distance_m == 0:
        return PairTTCResult(
            actor_id_a=actor_id_a,
            actor_id_b=actor_id_b,
            distance_m=0.0,
            closing_speed_mps=None,
            ttc_s=0.0,
        )

    avx, avy = velocity_xy(kin_a)
    bvx, bvy = velocity_xy(kin_b)
    rel_vx = bvx - avx
    rel_vy = bvy - avy
    closing_speed_mps = -((dx * rel_vx + dy * rel_vy) / distance_m)
    ttc_s = distance_m / closing_speed_mps if closing_speed_mps > 0 else None

    return PairTTCResult(
        actor_id_a=actor_id_a,
        actor_id_b=actor_id_b,
        distance_m=distance_m,
        closing_speed_mps=closing_speed_mps,
        ttc_s=ttc_s,
    )


def find_actor(objects: Any, actor_id: int):
    for index, obj in enumerate(objects or []):
        if object_actor_id(obj, index) == actor_id:
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
    return float(value)


def velocity_xy(kinematic: Any) -> tuple[float, float]:
    vx = float_attr(kinematic, "vx")
    vy = float_attr(kinematic, "vy")
    if vx is not None and vy is not None:
        return vx, vy

    speed = float_attr(kinematic, "speed") or 0.0
    yaw = float_attr(kinematic, "yaw") or 0.0
    return speed * cos(yaw), speed * sin(yaw)
