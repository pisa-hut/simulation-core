from collections import deque

from simcore.conditions import (
    ConditionCode,
    ConditionNode,
    EvaluationResult,
)
from simcore.runtime_actors import (
    ActorSelector,
    CollisionActorRef,
    collision_actor_ref,
    parse_actor_selector,
    selector_matches_ref,
)


class CollisionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.actor_a = self._parse_optional_selector(config, "actor_a")
        self.actor_b = self._parse_optional_selector(config, "actor_b")
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

    def _find_target_collision(
        self, collisions
    ) -> tuple[CollisionActorRef, CollisionActorRef] | None:
        if not collisions:
            return None

        for collision in collisions:
            if not getattr(collision, "occurred", False):
                continue
            if not self._has_actor(collision, "actor_a") or not self._has_actor(
                collision, "actor_b"
            ):
                continue

            actor_a = collision_actor_ref(collision.actor_a)
            actor_b = collision_actor_ref(collision.actor_b)
            if self._matches_target(actor_a, actor_b):
                return tuple(sorted((actor_a, actor_b), key=lambda ref: ref.tracking_id))

        return None

    def _matches_target(self, actor_a: CollisionActorRef, actor_b: CollisionActorRef) -> bool:
        refs = (actor_a, actor_b)

        if self.actor_a is not None or self.actor_b is not None:
            if self.actor_a is not None and not any(
                selector_matches_ref(self.actor_a, ref) for ref in refs
            ):
                return False
            if self.actor_b is not None and not any(
                selector_matches_ref(self.actor_b, ref) for ref in refs
            ):
                return False
            if self.actor_a is not None and self.actor_b is not None:
                return any(
                    selector_matches_ref(self.actor_a, first)
                    and selector_matches_ref(self.actor_b, second)
                    for first, second in ((actor_a, actor_b), (actor_b, actor_a))
                )
            return True

        actors = {actor_a.tracking_id, actor_b.tracking_id}

        if self.actor_id_a is None and self.actor_id_b is None:
            return True
        if self.actor_id_a is not None and self.actor_id_b is None:
            return self.actor_id_a in actors
        if self.actor_id_a is None and self.actor_id_b is not None:
            return self.actor_id_b in actors
        return actors == {self.actor_id_a, self.actor_id_b}

    @staticmethod
    def _triggered_detail(
        matched_pair: tuple[CollisionActorRef, CollisionActorRef],
    ) -> str:
        return (
            f"Collision detected between actor {matched_pair[0].label} "
            f"and actor {matched_pair[1].label}"
        )

    def _not_triggered_detail(self) -> str:
        if self.actor_a is not None or self.actor_b is not None:
            labels = [
                selector.role or selector.entity_name
                for selector in (self.actor_a, self.actor_b)
                if selector is not None
            ]
            return "No collision detected involving " + " and ".join(str(item) for item in labels)
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

    @staticmethod
    def _parse_optional_selector(config: dict, key: str) -> ActorSelector | None:
        if key not in config:
            return None
        return parse_actor_selector(config[key], field_name=key)
