from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from simcore.metrics.actors import find_actor, float_attr, object_kinematic
from simcore.metrics.pair_criticality import (
    compute_pair_criticality,
    parse_pair_criticality_options,
)
from simcore.metrics.relative_position import compute_relative_position
from simcore.metrics.ttc import compute_pair_ttc, parse_pair_ttc_options
from simcore.monitoring.sample import MonitorSample
from simcore.runtime_actors import parse_actor_binding

KINEMATIC_FIELDS = (
    "x",
    "y",
    "z",
    "yaw",
    "speed",
    "acceleration",
    "yaw_rate",
    "yaw_acceleration",
)
KINEMATIC_FIELD_ALIASES = {"acc": "acceleration"}
PAIR_TTC_FIELDS = (
    "ttc_s",
    "distance_m",
    "closing_speed_mps",
    "longitudinal_distance_m",
    "lateral_distance_m",
)
PAIR_CRITICALITY_FIELDS = (
    "distance_m",
    "longitudinal_distance_m",
    "lateral_distance_m",
    "closing_speed_mps",
    "relative_longitudinal_speed_mps",
    "relative_lateral_speed_mps",
    "relative_longitudinal_acceleration_mps2",
    "relative_lateral_acceleration_mps2",
    "thw_s",
    "drac_mps2",
)
RELATIVE_POSITION_FIELDS = (
    "relative_angle_deg",
    "sector",
    "distance_m",
    "source_x",
    "source_y",
    "target_x",
    "target_y",
    "source_yaw_rad",
)


class NumericValueSource(ABC):
    @abstractmethod
    def read(self, sample: MonitorSample) -> float | None:
        pass


class KinematicValueSource(NumericValueSource):
    def __init__(self, config: dict):
        self.actor = parse_actor_binding(config, selector_key="actor", legacy_keys=("actor_id",))
        raw_field = _required_field(config, "kinematic source")
        self.field = KINEMATIC_FIELD_ALIASES.get(raw_field, raw_field)
        _validate_field(self.field, KINEMATIC_FIELDS, "kinematic source")

    def read(self, sample: MonitorSample) -> float | None:
        actor_id = self.actor.resolve(sample.runtime_frame)
        actor = find_actor(_objects(sample), actor_id) if actor_id is not None else None
        if actor is None:
            return None
        return float_attr(object_kinematic(actor), self.field)


class PairTTCValueSource(NumericValueSource):
    def __init__(self, config: dict):
        self.actor_a = parse_actor_binding(
            config, selector_key="actor_a", legacy_keys=("actor_id_a",)
        )
        self.actor_b = parse_actor_binding(
            config, selector_key="actor_b", legacy_keys=("actor_id_b",)
        )
        self.field = _required_field(config, "pair_ttc source")
        _validate_field(self.field, PAIR_TTC_FIELDS, "pair_ttc source")
        options = parse_pair_ttc_options(config, owner="pair_ttc source")
        self.mode = options.mode
        self.lateral_threshold_m = options.lateral_threshold_m

    def read(self, sample: MonitorSample) -> float | None:
        runtime_frame = sample.runtime_frame
        actor_id_a = self.actor_a.resolve(runtime_frame)
        actor_id_b = self.actor_b.resolve(runtime_frame)
        if actor_id_a is None or actor_id_b is None:
            return None
        result = compute_pair_ttc(
            _objects(sample),
            actor_id_a,
            actor_id_b,
            mode=self.mode,
            lateral_threshold_m=self.lateral_threshold_m,
            collisions=getattr(runtime_frame, "collision", None) or [],
        )
        return _result_float(result, self.field)


class PairCriticalityValueSource(NumericValueSource):
    def __init__(self, config: dict):
        self.actor_a = parse_actor_binding(
            config, selector_key="actor_a", legacy_keys=("actor_id_a",)
        )
        self.actor_b = parse_actor_binding(
            config, selector_key="actor_b", legacy_keys=("actor_id_b",)
        )
        self.field = _required_field(config, "pair_criticality source")
        _validate_field(self.field, PAIR_CRITICALITY_FIELDS, "pair_criticality source")
        self.lateral_threshold_m = parse_pair_criticality_options(
            config, owner="pair_criticality source"
        )

    def read(self, sample: MonitorSample) -> float | None:
        actor_id_a = self.actor_a.resolve(sample.runtime_frame)
        actor_id_b = self.actor_b.resolve(sample.runtime_frame)
        if actor_id_a is None or actor_id_b is None:
            return None
        result = compute_pair_criticality(
            _objects(sample),
            actor_id_a,
            actor_id_b,
            lateral_threshold_m=self.lateral_threshold_m,
        )
        return _result_float(result, self.field)


class RelativePositionValueSource(NumericValueSource):
    def __init__(self, config: dict):
        self.source_actor = parse_actor_binding(
            config, selector_key="source_actor", legacy_keys=("source_actor_id",)
        )
        self.target_actor = parse_actor_binding(
            config, selector_key="target_actor", legacy_keys=("target_actor_id",)
        )
        self.field = _required_field(config, "relative_position source")
        _validate_field(self.field, RELATIVE_POSITION_FIELDS, "relative_position source")

    def read(self, sample: MonitorSample) -> float | None:
        source_actor_id = self.source_actor.resolve(sample.runtime_frame)
        target_actor_id = self.target_actor.resolve(sample.runtime_frame)
        if source_actor_id is None or target_actor_id is None:
            return None
        result = compute_relative_position(
            _objects(sample),
            source_actor_id,
            target_actor_id,
        )
        return _result_float(result, self.field)


SOURCE_BUILDERS = {
    "kinematic": KinematicValueSource,
    "pair_criticality": PairCriticalityValueSource,
    "pair_ttc": PairTTCValueSource,
    "relative_position": RelativePositionValueSource,
}


def build_numeric_value_source(config: Any) -> NumericValueSource:
    if not isinstance(config, dict):
        raise ValueError("numeric summary config 'source' must be a mapping")
    raw_type = config.get("type")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError("numeric summary source requires a non-empty 'type'")
    source_type = raw_type.strip().lower()
    try:
        builder = SOURCE_BUILDERS[source_type]
    except KeyError as exc:
        allowed = ", ".join(sorted(SOURCE_BUILDERS))
        raise ValueError(
            f"Unknown numeric summary source type {raw_type!r}; expected one of: {allowed}"
        ) from exc
    return builder(config)


def _objects(sample: MonitorSample) -> Any:
    return getattr(sample.runtime_frame, "objects", None) or []


def _required_field(config: dict, owner: str) -> str:
    raw_field = config.get("field")
    if not isinstance(raw_field, str) or not raw_field.strip():
        raise ValueError(f"{owner} requires a non-empty field")
    return raw_field.strip()


def _validate_field(field: str, available_fields: tuple[str, ...], owner: str) -> None:
    if field not in available_fields:
        allowed = ", ".join(available_fields)
        raise ValueError(f"Unknown field {field!r} for {owner}; expected one of: {allowed}")


def _result_float(result: Any, field: str) -> float | None:
    if result is None:
        return None
    value = getattr(result, field, None)
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
