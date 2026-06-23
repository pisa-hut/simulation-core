from __future__ import annotations

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample

from .base import Recorder
from .utils import float_attr, object_actor_id, object_kinematic

COLLISION_EVENT_FIELDS = (
    "step_index",
    "sim_time_ms",
    "actor_a",
    "actor_b",
    "x",
    "y",
    "z",
    "position_source",
)


class CollisionEventsRecorder(Recorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id_a = self._parse_optional_actor_id(config, "actor_id_a")
        self.actor_id_b = self._parse_optional_actor_id(config, "actor_id_b")
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
            if self.deduplicate and pair in self._seen_pairs:
                continue

            self._seen_pairs.add(pair)
            x, y, z, position_source = self._collision_position(collision, sample, pair)
            rows.append(
                LogRow(
                    stream=self.name,
                    row={
                        "step_index": sample.step_index,
                        "sim_time_ms": sample.sim_time_ms,
                        "actor_a": pair[0],
                        "actor_b": pair[1],
                        "x": x,
                        "y": y,
                        "z": z,
                        "position_source": position_source,
                    },
                )
            )

        return rows

    def _matches_filter(self, pair: tuple[int, int]) -> bool:
        actors = set(pair)
        if self.actor_id_a is None and self.actor_id_b is None:
            return True
        if self.actor_id_a is not None and self.actor_id_b is None:
            return self.actor_id_a in actors
        if self.actor_id_a is None and self.actor_id_b is not None:
            return self.actor_id_b in actors
        return actors == {self.actor_id_a, self.actor_id_b}

    @classmethod
    def _collision_pair(cls, collision) -> tuple[int, int] | None:
        if not getattr(collision, "occurred", False):
            return None
        if not cls._has_actor(collision, "actor_a") or not cls._has_actor(collision, "actor_b"):
            return None
        actor_a = int(collision.actor_a)
        actor_b = int(collision.actor_b)
        return tuple(sorted((actor_a, actor_b)))

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

    @classmethod
    def _collision_position(
        cls,
        collision,
        sample: MonitorSample,
        pair: tuple[int, int],
    ) -> tuple[float | None, float | None, float | None, str]:
        direct = cls._direct_position(collision)
        if direct is not None:
            return (*direct, "collision")
        midpoint = cls._actor_midpoint(sample, pair)
        if midpoint is not None:
            return (*midpoint, "actor_midpoint")
        return None, None, None, "unavailable"

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
        for index, obj in enumerate(objects):
            actor_id = object_actor_id(obj, index)
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
