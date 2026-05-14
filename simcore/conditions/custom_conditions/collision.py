from collections import deque

from simcore.conditions import (
    ConditionCode,
    ConditionNode,
    EvaluationResult,
)


class CollisionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.actor_id_a = self._parse_optional_actor_id(
            config,
            primary_key="actor_id_a",
            legacy_key="actor_id",
        )
        self.actor_id_b = self._parse_optional_actor_id(
            config,
            primary_key="actor_id_b",
        )

        try:
            max_buffer_size = int(config.get("max_buffer_size", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "CollisionCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        runtime_frame = data[1]
        self.buffer.append(getattr(runtime_frame, "collision", []))

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        for collisions in self.buffer:
            matched_pair = self._find_target_collision(collisions)
            if matched_pair is not None:
                return self.result(
                    ConditionCode.TRIGGERED,
                    self._triggered_detail(matched_pair),
                )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            self._not_triggered_detail(),
        )

    def reset(self):
        self.buffer.clear()

    def _find_target_collision(self, collisions) -> tuple[int, int] | None:
        if not collisions:
            return None

        for collision in collisions:
            if not getattr(collision, "occurred", False):
                continue
            if not self._has_actor(collision, "actor_a") or not self._has_actor(
                collision, "actor_b"
            ):
                continue

            actor_a = int(collision.actor_a)
            actor_b = int(collision.actor_b)
            if self._matches_target(actor_a, actor_b):
                return tuple(sorted((actor_a, actor_b)))

        return None

    def _matches_target(self, actor_a: int, actor_b: int) -> bool:
        actors = {actor_a, actor_b}

        if self.actor_id_a is None and self.actor_id_b is None:
            return True
        if self.actor_id_a is not None and self.actor_id_b is None:
            return self.actor_id_a in actors
        if self.actor_id_a is None and self.actor_id_b is not None:
            return self.actor_id_b in actors
        return actors == {self.actor_id_a, self.actor_id_b}

    @staticmethod
    def _triggered_detail(matched_pair: tuple[int, int]) -> str:
        return f"Collision detected between actor {matched_pair[0]} and actor {matched_pair[1]}"

    def _not_triggered_detail(self) -> str:
        if self.actor_id_a is None and self.actor_id_b is None:
            return "No collision detected between any actors"
        if self.actor_id_a is not None and self.actor_id_b is None:
            return f"No collision detected involving actor {self.actor_id_a}"
        if self.actor_id_a is None and self.actor_id_b is not None:
            return f"No collision detected involving actor {self.actor_id_b}"
        return f"No collision detected between actor {self.actor_id_a} and actor {self.actor_id_b}"

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
    def _parse_optional_actor_id(
        config: dict,
        primary_key: str,
        legacy_key: str | None = None,
    ) -> int | None:
        raw_value = config.get(primary_key)
        source_key = primary_key
        if raw_value is None and legacy_key is not None:
            raw_value = config.get(legacy_key)
            source_key = legacy_key

        if raw_value is None:
            return None

        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"CollisionCondition config '{source_key}' must be an integer, "
                f"but got: {config.get(source_key)}"
            ) from exc
