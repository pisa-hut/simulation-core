from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic

EGO_ACTOR_ID = 0
SECTOR_COUNT = 8
SECTOR_WIDTH_DEG = 360.0 / SECTOR_COUNT

DIRECTION_SECTORS: dict[str, frozenset[int]] = {
    "straight": frozenset({0, 7}),
    "ahead": frozenset({0, 7}),
    "front": frozenset({0, 1, 6, 7}),
    "left": frozenset({0, 1, 2, 3}),
    "right": frozenset({4, 5, 6, 7}),
    "rear": frozenset({2, 3, 4, 5}),
    "back": frozenset({2, 3, 4, 5}),
    "front_left": frozenset({0, 1}),
    "front_right": frozenset({6, 7}),
    "rear_left": frozenset({2, 3}),
    "rear_right": frozenset({4, 5}),
}


@dataclass(frozen=True)
class RelativePositionResult:
    source_actor_id: int
    target_actor_id: int
    relative_angle_deg: float
    sector: int
    distance_m: float
    source_x: float
    source_y: float
    target_x: float
    target_y: float
    source_yaw_rad: float


@dataclass(frozen=True)
class RelativePositionSelector:
    sectors: frozenset[int] = frozenset()
    angle_ranges_deg: tuple[tuple[float, float], ...] = ()
    labels: tuple[str, ...] = ()

    def matches(self, result: RelativePositionResult) -> bool:
        return (
            result.sector in self.sectors
            or any(
                angle_in_range(result.relative_angle_deg, start_deg, end_deg)
                for start_deg, end_deg in self.angle_ranges_deg
            )
        )

    def describe(self) -> str:
        parts = []
        if self.labels:
            parts.append("directions=" + ",".join(self.labels))
        if self.sectors:
            parts.append("sectors=[" + ",".join(str(sector) for sector in sorted(self.sectors)) + "]")
        if self.angle_ranges_deg:
            ranges = ",".join(
                f"[{start_deg:.6g},{end_deg:.6g}]"
                for start_deg, end_deg in self.angle_ranges_deg
            )
            parts.append(f"angle_ranges_deg={ranges}")
        return "; ".join(parts)


def compute_relative_position(
    objects: Any,
    source_actor_id: int,
    target_actor_id: int,
) -> RelativePositionResult | None:
    source = find_actor(objects, source_actor_id)
    target = find_actor(objects, target_actor_id)
    if source is None or target is None:
        return None

    source_kinematic = object_kinematic(source)
    target_kinematic = object_kinematic(target)
    source_x = float_attr(source_kinematic, "x")
    source_y = float_attr(source_kinematic, "y")
    target_x = float_attr(target_kinematic, "x")
    target_y = float_attr(target_kinematic, "y")
    if source_x is None or source_y is None or target_x is None or target_y is None:
        return None

    source_yaw_rad = float_attr(source_kinematic, "yaw") or 0.0
    dx = target_x - source_x
    dy = target_y - source_y
    absolute_angle_deg = degrees(atan2(dy, dx))
    source_yaw_deg = degrees(source_yaw_rad)
    relative_angle_deg = normalize_signed_degrees(absolute_angle_deg - source_yaw_deg)

    return RelativePositionResult(
        source_actor_id=source_actor_id,
        target_actor_id=target_actor_id,
        relative_angle_deg=relative_angle_deg,
        sector=sector_from_relative_angle(relative_angle_deg),
        distance_m=hypot(dx, dy),
        source_x=source_x,
        source_y=source_y,
        target_x=target_x,
        target_y=target_y,
        source_yaw_rad=source_yaw_rad,
    )


def build_relative_position_selector(config: dict) -> RelativePositionSelector:
    sectors = set()
    labels = []

    sector_index_base = int(config.get("sector_index_base", config.get("sector_base", 0)))
    if sector_index_base not in {0, 1}:
        raise ValueError("relative position sector_index_base must be 0 or 1")

    for raw_sector in _as_list(config.get("sector")) + _as_list(config.get("sectors")):
        sectors.add(_parse_sector(raw_sector, sector_index_base))

    for raw_direction in _as_list(config.get("direction")) + _as_list(config.get("directions")):
        direction = _normalize_direction(raw_direction)
        labels.append(direction)
        sectors.update(DIRECTION_SECTORS[direction])

    angle_ranges = tuple(
        _parse_angle_range(raw_range)
        for raw_range in (
            _as_angle_ranges(config.get("angle_range_deg"))
            + _as_angle_ranges(config.get("angle_ranges_deg"))
            + _as_angle_ranges(config.get("angle_range"))
            + _as_angle_ranges(config.get("angle_ranges"))
        )
    )

    if not sectors and not angle_ranges:
        raise ValueError(
            "relative position condition requires direction, sector(s), or angle_range_deg"
        )

    return RelativePositionSelector(
        sectors=frozenset(sectors),
        angle_ranges_deg=angle_ranges,
        labels=tuple(labels),
    )


def parse_actor_id(config: dict, *keys: str) -> int:
    raw_value = None
    for key in keys:
        if key in config:
            raw_value = config[key]
            break

    if raw_value is None:
        raise ValueError(f"relative position condition requires one of: {', '.join(keys)}")
    if isinstance(raw_value, str) and raw_value.strip().lower() == "ego":
        return EGO_ACTOR_ID
    return int(raw_value)


def sector_from_relative_angle(relative_angle_deg: float) -> int:
    normalized = normalize_positive_degrees(relative_angle_deg)
    sector = int(normalized // SECTOR_WIDTH_DEG)
    return min(SECTOR_COUNT - 1, sector)


def angle_in_range(angle_deg: float, start_deg: float, end_deg: float) -> bool:
    angle = normalize_signed_degrees(angle_deg)
    start = normalize_signed_degrees(start_deg)
    end = normalize_signed_degrees(end_deg)
    if start <= end:
        return start <= angle <= end
    return angle >= start or angle <= end


def normalize_signed_degrees(angle_deg: float) -> float:
    normalized = normalize_positive_degrees(angle_deg)
    if normalized >= 180.0:
        normalized -= 360.0
    return normalized


def normalize_positive_degrees(angle_deg: float) -> float:
    return float(angle_deg) % 360.0


def _as_list(raw_value: Any) -> list[Any]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return raw_value
    return [raw_value]


def _as_angle_ranges(raw_value: Any) -> list[Any]:
    if raw_value is None:
        return []
    if (
        isinstance(raw_value, list)
        and len(raw_value) == 2
        and not any(isinstance(item, (list, tuple)) for item in raw_value)
    ):
        return [raw_value]
    if isinstance(raw_value, list):
        return raw_value
    return [raw_value]


def _parse_sector(raw_sector: Any, sector_index_base: int) -> int:
    sector = int(raw_sector)
    if sector_index_base == 1:
        sector -= 1
    if sector < 0 or sector >= SECTOR_COUNT:
        raise ValueError(
            f"relative position sector must be in "
            f"{'1..8' if sector_index_base == 1 else '0..7'}, got: {raw_sector}"
        )
    return sector


def _normalize_direction(raw_direction: Any) -> str:
    direction = str(raw_direction).strip().lower().replace("-", "_")
    try:
        DIRECTION_SECTORS[direction]
    except KeyError as exc:
        valid = ", ".join(sorted(DIRECTION_SECTORS))
        raise ValueError(f"unsupported relative position direction {raw_direction!r}; valid: {valid}") from exc
    return direction


def _parse_angle_range(raw_range: Any) -> tuple[float, float]:
    if not isinstance(raw_range, (list, tuple)) or len(raw_range) != 2:
        raise ValueError("relative position angle ranges must be [start_deg, end_deg]")
    return float(raw_range[0]), float(raw_range[1])
