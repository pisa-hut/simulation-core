from __future__ import annotations

from typing import Any

from simcore.monitoring.sample import MonitorSample

from .base import SummaryContext, SummaryRecorder

COLLISION_FIELDS = ("collision",)


class CollisionSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id_a = self._parse_actor_id(config.get("actor_id_a"))
        self.actor_id_b = self._parse_actor_id(config.get("actor_id_b"))
        self.collision = False

    def fields(self) -> tuple[str, ...]:
        return COLLISION_FIELDS

    def reset(self) -> None:
        self.collision = False

    def update(self, sample: MonitorSample) -> None:
        for collision in getattr(sample.runtime_frame, "collision", None) or []:
            if not getattr(collision, "occurred", False):
                continue
            pair = self._pair(collision)
            if pair is not None and self._matches(pair):
                self.collision = True
                return

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"collision": self.collision}

    def _matches(self, pair: tuple[int, int]) -> bool:
        actors = set(pair)
        if self.actor_id_a is None and self.actor_id_b is None:
            return True
        if self.actor_id_a is not None and self.actor_id_b is None:
            return self.actor_id_a in actors
        if self.actor_id_a is None and self.actor_id_b is not None:
            return self.actor_id_b in actors
        return actors == {self.actor_id_a, self.actor_id_b}

    @classmethod
    def _pair(cls, collision) -> tuple[int, int] | None:
        if not cls._has_field(collision, "actor_a") or not cls._has_field(
            collision, "actor_b"
        ):
            return None
        return tuple(sorted((int(collision.actor_a), int(collision.actor_b))))

    @staticmethod
    def _has_field(collision, field_name: str) -> bool:
        has_field = getattr(collision, "HasField", None)
        if callable(has_field):
            try:
                return bool(has_field(field_name))
            except ValueError:
                return False
        return hasattr(collision, field_name)

    @staticmethod
    def _parse_actor_id(raw_value: Any) -> int | None:
        if raw_value is None:
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"collision summary actor id must be an integer: {raw_value}") from exc
