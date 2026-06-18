from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, sin
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic

DEFAULT_LATERAL_THRESHOLD_M = 2.0


@dataclass(frozen=True)
class PairCriticalityResult:
    actor_id_a: int
    actor_id_b: int
    distance_m: float
    longitudinal_distance_m: float
    lateral_distance_m: float
    closing_speed_mps: float
    relative_longitudinal_speed_mps: float
    relative_lateral_speed_mps: float
    relative_longitudinal_acceleration_mps2: float
    relative_lateral_acceleration_mps2: float
    thw_s: float | None
    drac_mps2: float | None


def compute_pair_criticality(
    objects: Any,
    actor_id_a: int,
    actor_id_b: int,
    lateral_threshold_m: float | None = DEFAULT_LATERAL_THRESHOLD_M,
) -> PairCriticalityResult | None:
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

    yaw_a = float_attr(kin_a, "yaw") or 0.0
    forward_x = cos(yaw_a)
    forward_y = sin(yaw_a)
    side_x = -sin(yaw_a)
    side_y = cos(yaw_a)

    dx = bx - ax
    dy = by - ay
    avx, avy = velocity_xy(kin_a)
    bvx, bvy = velocity_xy(kin_b)
    aax, aay = acceleration_xy(kin_a)
    bax, bay = acceleration_xy(kin_b)

    source_forward_speed = avx * forward_x + avy * forward_y
    target_forward_speed = bvx * forward_x + bvy * forward_y
    source_lateral_speed = avx * side_x + avy * side_y
    target_lateral_speed = bvx * side_x + bvy * side_y
    source_forward_acceleration = aax * forward_x + aay * forward_y
    target_forward_acceleration = bax * forward_x + bay * forward_y
    source_lateral_acceleration = aax * side_x + aay * side_y
    target_lateral_acceleration = bax * side_x + bay * side_y

    longitudinal_distance_m = dx * forward_x + dy * forward_y
    lateral_distance_m = dx * side_x + dy * side_y
    closing_speed_mps = source_forward_speed - target_forward_speed
    in_longitudinal_corridor = (
        lateral_threshold_m is None or abs(lateral_distance_m) <= lateral_threshold_m
    )
    thw_s = (
        longitudinal_distance_m / source_forward_speed
        if in_longitudinal_corridor and longitudinal_distance_m > 0 and source_forward_speed > 0
        else None
    )
    drac_mps2 = (
        closing_speed_mps**2 / (2.0 * longitudinal_distance_m)
        if in_longitudinal_corridor and longitudinal_distance_m > 0 and closing_speed_mps > 0
        else None
    )

    return PairCriticalityResult(
        actor_id_a=actor_id_a,
        actor_id_b=actor_id_b,
        distance_m=hypot(dx, dy),
        longitudinal_distance_m=longitudinal_distance_m,
        lateral_distance_m=lateral_distance_m,
        closing_speed_mps=closing_speed_mps,
        relative_longitudinal_speed_mps=target_forward_speed - source_forward_speed,
        relative_lateral_speed_mps=target_lateral_speed - source_lateral_speed,
        relative_longitudinal_acceleration_mps2=(
            target_forward_acceleration - source_forward_acceleration
        ),
        relative_lateral_acceleration_mps2=(
            target_lateral_acceleration - source_lateral_acceleration
        ),
        thw_s=thw_s,
        drac_mps2=drac_mps2,
    )


def velocity_xy(kinematic: Any) -> tuple[float, float]:
    vx = float_attr(kinematic, "vx")
    vy = float_attr(kinematic, "vy")
    if vx is not None and vy is not None:
        return vx, vy

    speed = float_attr(kinematic, "speed") or 0.0
    yaw = float_attr(kinematic, "yaw") or 0.0
    return speed * cos(yaw), speed * sin(yaw)


def acceleration_xy(kinematic: Any) -> tuple[float, float]:
    ax = float_attr(kinematic, "ax")
    ay = float_attr(kinematic, "ay")
    if ax is not None and ay is not None:
        return ax, ay

    acceleration = float_attr(kinematic, "acceleration") or 0.0
    yaw = float_attr(kinematic, "yaw") or 0.0
    return acceleration * cos(yaw), acceleration * sin(yaw)


def parse_pair_criticality_options(
    config: dict,
    *,
    owner: str = "pair_criticality",
) -> float | None:
    raw_threshold = config.get("lateral_threshold_m", DEFAULT_LATERAL_THRESHOLD_M)
    if raw_threshold is None:
        return None
    lateral_threshold_m = float(raw_threshold)
    if lateral_threshold_m < 0:
        raise ValueError(f"{owner} lateral_threshold_m must be >= 0")
    return lateral_threshold_m
