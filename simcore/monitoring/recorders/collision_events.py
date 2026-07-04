from __future__ import annotations

import json

from simcore.monitoring.geometry import actor_box, estimate_contact
from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample
from simcore.runtime_actors import (
    ActorSelector,
    CollisionActorRef,
    NormalizedRuntimeFrame,
    collision_actor_ref,
    parse_actor_selector,
    selector_matches_ref,
)

from .base import Recorder
from .utils import float_attr, object_actor_id, object_kinematic

COLLISION_EVENT_FIELDS = (
    "step_index",
    "sim_time_ms",
    "actor_a",
    "actor_b",
    "actor_a_sim_tracking_id",
    "actor_b_sim_tracking_id",
    "actor_a_entity_name",
    "actor_b_entity_name",
    "x",
    "y",
    "z",
    "position_source",
    "contact_region_json",
)


class CollisionEventsRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id_a = self._parse_optional_actor_id(config, "actor_id_a")
        self.actor_id_b = self._parse_optional_actor_id(config, "actor_id_b")
        self.actor_a = self._parse_optional_selector(config, "actor_a")
        self.actor_b = self._parse_optional_selector(config, "actor_b")
        self.deduplicate = bool(config.get("deduplicate", False))
        self._seen_pairs: set[tuple[int, int]] = set()

    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=COLLISION_EVENT_FIELDS,
            )
        ]

    def reset(self) -> None:
        self._seen_pairs.clear()

    def record(self, sample: MonitorSample) -> list[LogRow]:
        rows = []
        collisions = getattr(sample.runtime_frame, "collision", None) or []

        for collision in collisions:
            pair = self._collision_pair(collision)
            if pair is None:
                continue
            if not self._matches_filter(pair):
                continue
            pair_key = tuple(sorted((pair[0].tracking_id, pair[1].tracking_id)))
            if self.deduplicate and pair_key in self._seen_pairs:
                continue

            self._seen_pairs.add(pair_key)
            runner_pair = self._runner_pair(sample, pair)
            x, y, z, position_source, contact_region_json = self._collision_position(
                collision,
                sample,
                runner_pair,
            )
            rows.append(
                LogRow(
                    stream=self.name,
                    row={
                        "step_index": sample.step_index,
                        "sim_time_ms": sample.sim_time_ms,
                        "actor_a": runner_pair[0] if runner_pair else None,
                        "actor_b": runner_pair[1] if runner_pair else None,
                        "actor_a_sim_tracking_id": pair[0].tracking_id,
                        "actor_b_sim_tracking_id": pair[1].tracking_id,
                        "actor_a_entity_name": pair[0].entity_name,
                        "actor_b_entity_name": pair[1].entity_name,
                        "x": x,
                        "y": y,
                        "z": z,
                        "position_source": position_source,
                        "contact_region_json": contact_region_json,
                    },
                )
            )

        return rows

    def _matches_filter(self, pair: tuple[CollisionActorRef, CollisionActorRef]) -> bool:
        if self.actor_a is not None or self.actor_b is not None:
            if self.actor_a is not None and self.actor_b is not None:
                return any(
                    selector_matches_ref(self.actor_a, first)
                    and selector_matches_ref(self.actor_b, second)
                    for first, second in (pair, tuple(reversed(pair)))
                )
            selector = self.actor_a or self.actor_b
            return any(selector_matches_ref(selector, ref) for ref in pair)
        actors = {ref.tracking_id for ref in pair}
        if self.actor_id_a is None and self.actor_id_b is None:
            return True
        if self.actor_id_a is not None and self.actor_id_b is None:
            return self.actor_id_a in actors
        if self.actor_id_a is None and self.actor_id_b is not None:
            return self.actor_id_b in actors
        return actors == {self.actor_id_a, self.actor_id_b}

    @classmethod
    def _collision_pair(cls, collision) -> tuple[CollisionActorRef, CollisionActorRef] | None:
        if not getattr(collision, "occurred", False):
            return None
        if not cls._has_actor(collision, "actor_a") or not cls._has_actor(collision, "actor_b"):
            return None
        actor_a = collision_actor_ref(collision.actor_a)
        actor_b = collision_actor_ref(collision.actor_b)
        return tuple(sorted((actor_a, actor_b), key=lambda ref: ref.tracking_id))

    @staticmethod
    def _has_actor(collision, field_name: str) -> bool:
        has_field = getattr(collision, "HasField", None)
        if callable(has_field):
            try:
                return bool(has_field(field_name))
            except ValueError:
                return False
        return hasattr(collision, field_name)

    @staticmethod
    def _parse_optional_actor_id(config: dict, key: str) -> int | None:
        raw_value = config.get(key)
        if raw_value is None:
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CollisionEventsRecorder config '{key}' must be an integer, but got: {raw_value}"
            ) from exc

    @staticmethod
    def _parse_optional_selector(config: dict, key: str) -> ActorSelector | None:
        if key not in config:
            return None
        return parse_actor_selector(config[key], field_name=key)

    @staticmethod
    def _runner_pair(
        sample: MonitorSample,
        pair: tuple[CollisionActorRef, CollisionActorRef],
    ) -> tuple[int, int] | None:
        if not isinstance(sample.runtime_frame, NormalizedRuntimeFrame):
            return pair[0].tracking_id, pair[1].tracking_id
        actors = getattr(sample.runtime_frame, "objects", ()) or ()
        runner_ids = {}
        for actor in actors:
            tracking_id = getattr(actor, "sim_tracking_id", None)
            if tracking_id is not None:
                runner_ids[int(tracking_id)] = object_actor_id(actor)
            else:
                actor_id = object_actor_id(actor)
                runner_ids[actor_id] = actor_id
        if any(ref.tracking_id not in runner_ids for ref in pair):
            return None
        return runner_ids[pair[0].tracking_id], runner_ids[pair[1].tracking_id]

    @classmethod
    def _collision_position(
        cls,
        collision,
        sample: MonitorSample,
        pair: tuple[int, int] | None,
    ) -> tuple[float | None, float | None, float | None, str, str]:
        direct = cls._direct_position(collision)
        if direct is not None:
            return (*direct, "collision", "")
        if pair is None:
            return None, None, None, "unavailable", ""
        bbox = cls._bbox_contact(sample, pair)
        if bbox is not None:
            x, y, source, region_json = bbox
            return x, y, cls._midpoint_z(sample, pair), source, region_json
        midpoint = cls._actor_midpoint(sample, pair)
        if midpoint is not None:
            return (*midpoint, "actor_midpoint", "")
        return None, None, None, "unavailable", ""

    @staticmethod
    def _direct_position(collision) -> tuple[float | None, float | None, float | None] | None:
        for field_name in ("position", "point", "location"):
            if not hasattr(collision, field_name):
                continue
            position = getattr(collision, field_name)
            x = float_attr(position, "x")
            y = float_attr(position, "y")
            if x is None or y is None:
                continue
            return x, y, float_attr(position, "z")
        x = float_attr(collision, "x")
        y = float_attr(collision, "y")
        if x is None or y is None:
            return None
        return x, y, float_attr(collision, "z")

    @staticmethod
    def _actor_midpoint(
        sample: MonitorSample,
        pair: tuple[int, int],
    ) -> tuple[float | None, float | None, float | None] | None:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        positions = {}
        for obj in objects:
            actor_id = object_actor_id(obj)
            if actor_id not in pair:
                continue
            kinematic = object_kinematic(obj)
            x = float_attr(kinematic, "x")
            y = float_attr(kinematic, "y")
            if x is None or y is None:
                continue
            positions[actor_id] = (x, y, float_attr(kinematic, "z"))
        if pair[0] not in positions or pair[1] not in positions:
            return None
        ax, ay, az = positions[pair[0]]
        bx, by, bz = positions[pair[1]]
        z = None if az is None or bz is None else (az + bz) / 2.0
        return (ax + bx) / 2.0, (ay + by) / 2.0, z

    @staticmethod
    def _bbox_contact(
        sample: MonitorSample,
        pair: tuple[int, int],
    ) -> tuple[float, float, str, str] | None:
        objects = getattr(sample.runtime_frame, "objects", None) or []
        boxes = {}
        for obj in objects:
            actor_id = object_actor_id(obj)
            if actor_id not in pair:
                continue
            box = actor_box(obj)
            if box is not None:
                boxes[actor_id] = box
        if pair[0] not in boxes or pair[1] not in boxes:
            return None
        estimate = estimate_contact(boxes[pair[0]], boxes[pair[1]])
        region_json = (
            json.dumps(
                [{"x": x, "y": y} for x, y in estimate.region],
                sort_keys=True,
                separators=(",", ":"),
            )
            if estimate.region
            else ""
        )
        return estimate.x, estimate.y, estimate.source, region_json

    @staticmethod
    def _midpoint_z(sample: MonitorSample, pair: tuple[int, int]) -> float | None:
        midpoint = CollisionEventsRecorder._actor_midpoint(sample, pair)
        if midpoint is None:
            return None
        return midpoint[2]
