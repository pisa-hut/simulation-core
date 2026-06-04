from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, sin
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic

DEFAULT_TTC_MODE = "longitudinal"
DEFAULT_LATERAL_THRESHOLD_M = 2.0
TTC_MODES = {"longitudinal", "radial"}


@dataclass(frozen=True)
class PairTTCResult:
    actor_id_a: int
    actor_id_b: int
    distance_m: float
    closing_speed_mps: float | None
    ttc_s: float | None
    longitudinal_distance_m: float | None = None
    lateral_distance_m: float | None = None
    mode: str = DEFAULT_TTC_MODE


def compute_pair_ttc(
    objects: Any,
    actor_id_a: int,
    actor_id_b: int,
    mode: str = DEFAULT_TTC_MODE,
    lateral_threshold_m: float | None = DEFAULT_LATERAL_THRESHOLD_M,
) -> PairTTCResult | None:
    mode = normalize_ttc_mode(mode)
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
            longitudinal_distance_m=0.0,
            lateral_distance_m=0.0,
            mode=mode,
        )

    avx, avy = velocity_xy(kin_a)
    bvx, bvy = velocity_xy(kin_b)
    if mode == "longitudinal":
        yaw_a = float_attr(kin_a, "yaw") or 0.0
        forward_x = cos(yaw_a)
        forward_y = sin(yaw_a)
        side_x = -sin(yaw_a)
        side_y = cos(yaw_a)

        longitudinal_distance_m = dx * forward_x + dy * forward_y
        lateral_distance_m = dx * side_x + dy * side_y
        forward_speed_a = avx * forward_x + avy * forward_y
        forward_speed_b = bvx * forward_x + bvy * forward_y
        closing_speed_mps = forward_speed_a - forward_speed_b
        if longitudinal_distance_m <= 0 or (
            lateral_threshold_m is not None and abs(lateral_distance_m) > lateral_threshold_m
        ):
            ttc_s = None
        else:
            ttc_s = (
                longitudinal_distance_m / closing_speed_mps
                if closing_speed_mps > 0
                else None
            )

        return PairTTCResult(
            actor_id_a=actor_id_a,
            actor_id_b=actor_id_b,
            distance_m=distance_m,
            closing_speed_mps=closing_speed_mps,
            ttc_s=ttc_s,
            longitudinal_distance_m=longitudinal_distance_m,
            lateral_distance_m=lateral_distance_m,
            mode=mode,
        )

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
        longitudinal_distance_m=None,
        lateral_distance_m=None,
        mode=mode,
    )


def velocity_xy(kinematic: Any) -> tuple[float, float]:
    vx = float_attr(kinematic, "vx")
    vy = float_attr(kinematic, "vy")
    if vx is not None and vy is not None:
        return vx, vy

    speed = float_attr(kinematic, "speed") or 0.0
    yaw = float_attr(kinematic, "yaw") or 0.0
    return speed * cos(yaw), speed * sin(yaw)


def normalize_ttc_mode(mode: str | None) -> str:
    normalized = (mode or DEFAULT_TTC_MODE).lower()
    if normalized not in TTC_MODES:
        allowed = ", ".join(sorted(TTC_MODES))
        raise ValueError(f"Unsupported TTC mode {mode!r}; expected one of: {allowed}")
    return normalized
