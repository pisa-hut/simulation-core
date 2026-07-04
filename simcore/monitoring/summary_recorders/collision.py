from __future__ import annotations

from typing import Any

from simcore.metrics.collision import collision_pair
from simcore.monitoring.sample import MonitorSample
from simcore.runtime_actors import (
    ActorSelector,
    collision_actor_ref,
    parse_actor_selector,
    selector_matches_ref,
)

from .base import SummaryContext, SummaryRecorder

COLLISION_FIELDS = ("collision",)


class CollisionSummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.actor_id_a = self._parse_actor_id(config.get("actor_id_a"))
        self.actor_id_b = self._parse_actor_id(config.get("actor_id_b"))
        self.actor_a = self._parse_selector(config, "actor_a")
        self.actor_b = self._parse_selector(config, "actor_b")
        self.collision = False

    def fields(self) -> tuple[str, ...]:
        return COLLISION_FIELDS

    def reset(self) -> None:
        self.collision = False

    def update(self, sample: MonitorSample) -> None:
        for collision in getattr(sample.runtime_frame, "collision", None) or []:
            if not getattr(collision, "occurred", False):
                continue
            if self.actor_a is not None or self.actor_b is not None:
                if not hasattr(collision, "actor_a") or not hasattr(collision, "actor_b"):
                    continue
                refs = (
                    collision_actor_ref(collision.actor_a),
                    collision_actor_ref(collision.actor_b),
                )
                matched = self._matches_selectors(refs)
            else:
                pair = collision_pair(collision)
                matched = pair is not None and self._matches(pair)
            if matched:
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

    def _matches_selectors(self, refs) -> bool:
        if self.actor_a is not None and self.actor_b is not None:
            return any(
                selector_matches_ref(self.actor_a, first)
                and selector_matches_ref(self.actor_b, second)
                for first, second in (refs, tuple(reversed(refs)))
            )
        selector = self.actor_a or self.actor_b
        return any(selector_matches_ref(selector, ref) for ref in refs)

    @staticmethod
    def _parse_actor_id(raw_value: Any) -> int | None:
        if raw_value is None:
            return None
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"collision summary actor id must be an integer: {raw_value}") from exc

    @staticmethod
    def _parse_selector(config: dict, key: str) -> ActorSelector | None:
        if key not in config:
            return None
        return parse_actor_selector(config[key], field_name=key)
