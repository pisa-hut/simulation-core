from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, sin
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic
from simcore.metrics.collision import pair_collision_occurred
from simcore.metrics.pair_criticality import velocity_xy

DEFAULT_TTC_MODE = "longitudinal"
DEFAULT_LATERAL_THRESHOLD_M = 2.0
TTC_MODES = {"longitudinal", "radial"}


@dataclass(frozen=True)
class PairTTCOptions:
    mode: str = DEFAULT_TTC_MODE
    lateral_threshold_m: float | None = DEFAULT_LATERAL_THRESHOLD_M


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
    ttc_valid: bool = False
    ttc_status: str = "invalid_geometry"
    in_lateral_conflict: bool | None = None


def compute_pair_ttc(
    objects: Any,
    actor_id_a: int,
    actor_id_b: int,
    mode: str = DEFAULT_TTC_MODE,
    lateral_threshold_m: float | None = DEFAULT_LATERAL_THRESHOLD_M,
    collisions: Any = None,
) -> PairTTCResult | None:
    mode = normalize_ttc_mode(mode)
    actor_a = find_actor(objects, actor_id_a)
    actor_b = find_actor(objects, actor_id_b)
    collision_id_a = int(getattr(actor_a, "sim_tracking_id", actor_id_a))
    collision_id_b = int(getattr(actor_b, "sim_tracking_id", actor_id_b))
    has_collision = pair_collision_occurred(collisions, collision_id_a, collision_id_b)
    if actor_a is None or actor_b is None:
        if has_collision:
            return PairTTCResult(
                actor_id_a=actor_id_a,
                actor_id_b=actor_id_b,
                distance_m=None,
                closing_speed_mps=None,
                ttc_s=0.0,
                longitudinal_distance_m=None,
                lateral_distance_m=None,
                mode=mode,
                ttc_valid=True,
                ttc_status="collision",
                in_lateral_conflict=None,
            )
        return PairTTCResult(
            actor_id_a=actor_id_a,
            actor_id_b=actor_id_b,
            distance_m=None,
            closing_speed_mps=None,
            ttc_s=None,
            longitudinal_distance_m=None,
            lateral_distance_m=None,
            mode=mode,
            ttc_valid=False,
            ttc_status="missing_actor",
            in_lateral_conflict=None,
        )

    kin_a = object_kinematic(actor_a)
    kin_b = object_kinematic(actor_b)
    ax = float_attr(kin_a, "x")
    ay = float_attr(kin_a, "y")
    bx = float_attr(kin_b, "x")
    by = float_attr(kin_b, "y")
    if ax is None or ay is None or bx is None or by is None:
        if has_collision:
            return PairTTCResult(
                actor_id_a=actor_id_a,
                actor_id_b=actor_id_b,
                distance_m=None,
                closing_speed_mps=None,
                ttc_s=0.0,
                longitudinal_distance_m=None,
                lateral_distance_m=None,
                mode=mode,
                ttc_valid=True,
                ttc_status="collision",
                in_lateral_conflict=None,
            )
        return PairTTCResult(
            actor_id_a=actor_id_a,
            actor_id_b=actor_id_b,
            distance_m=None,
            closing_speed_mps=None,
            ttc_s=None,
            longitudinal_distance_m=None,
            lateral_distance_m=None,
            mode=mode,
            ttc_valid=False,
            ttc_status="invalid_geometry",
            in_lateral_conflict=None,
        )

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
            ttc_valid=True,
            ttc_status="collision" if has_collision else "valid",
            in_lateral_conflict=True,
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
        in_lateral_conflict = (
            lateral_threshold_m is None or abs(lateral_distance_m) <= lateral_threshold_m
        )
        if longitudinal_distance_m <= 0:
            ttc_status = "not_ahead"
            ttc_s = None
        elif not in_lateral_conflict:
            ttc_status = "outside_lateral_threshold"
            ttc_s = None
        else:
            if closing_speed_mps > 0:
                ttc_status = "valid"
                ttc_s = longitudinal_distance_m / closing_speed_mps
            else:
                ttc_status = "non_closing"
                ttc_s = None

        return PairTTCResult(
            actor_id_a=actor_id_a,
            actor_id_b=actor_id_b,
            distance_m=distance_m,
            closing_speed_mps=closing_speed_mps,
            ttc_s=0.0 if has_collision else ttc_s,
            longitudinal_distance_m=longitudinal_distance_m,
            lateral_distance_m=lateral_distance_m,
            mode=mode,
            ttc_valid=has_collision or ttc_s is not None,
            ttc_status="collision" if has_collision else ttc_status,
            in_lateral_conflict=in_lateral_conflict,
        )

    rel_vx = bvx - avx
    rel_vy = bvy - avy
    closing_speed_mps = -((dx * rel_vx + dy * rel_vy) / distance_m)
    if closing_speed_mps > 0:
        ttc_status = "valid"
        ttc_s = distance_m / closing_speed_mps
    else:
        ttc_status = "non_closing"
        ttc_s = None

    return PairTTCResult(
        actor_id_a=actor_id_a,
        actor_id_b=actor_id_b,
        distance_m=distance_m,
        closing_speed_mps=closing_speed_mps,
        ttc_s=0.0 if has_collision else ttc_s,
        longitudinal_distance_m=None,
        lateral_distance_m=None,
        mode=mode,
        ttc_valid=has_collision or ttc_s is not None,
        ttc_status="collision" if has_collision else ttc_status,
        in_lateral_conflict=None,
    )


def normalize_ttc_mode(mode: str | None) -> str:
    normalized = (mode or DEFAULT_TTC_MODE).lower()
    if normalized not in TTC_MODES:
        allowed = ", ".join(sorted(TTC_MODES))
        raise ValueError(f"Unsupported TTC mode {mode!r}; expected one of: {allowed}")
    return normalized


def parse_pair_ttc_options(config: dict, *, owner: str = "pair_ttc") -> PairTTCOptions:
    mode = normalize_ttc_mode(config.get("mode", config.get("ttc_mode", DEFAULT_TTC_MODE)))
    raw_threshold = config.get("lateral_threshold_m", DEFAULT_LATERAL_THRESHOLD_M)
    if raw_threshold is None:
        lateral_threshold_m = None
    else:
        lateral_threshold_m = float(raw_threshold)
        if lateral_threshold_m < 0:
            raise ValueError(f"{owner} lateral_threshold_m must be >= 0")
    return PairTTCOptions(mode=mode, lateral_threshold_m=lateral_threshold_m)
