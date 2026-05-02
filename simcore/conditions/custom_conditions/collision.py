from collections import deque
from collections.abc import Mapping

from simcore.conditions import (
    ConditionCode,
    ConditionNode,
    EvaluationResult,
)

COLLISION_KEYS = ("collision", "collided", "has_collision")


class CollisionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        try:
            max_buffer_size = int(config.get("max_buffer_size", 10))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "CollisionCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        self.buffer.append(data)

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        for snapshot in self.buffer:
            if self._contains_collision(snapshot):
                return self.result(ConditionCode.TRIGGERED, "Collision detected")

        return self.result(ConditionCode.NOT_TRIGGERED, "No collision detected")

    def _contains_collision(self, payload, depth: int = 0) -> bool:
        if payload is None or depth > 4:
            return False

        if isinstance(payload, Mapping):
            for key in COLLISION_KEYS:
                if key in payload and bool(payload[key]):
                    return True
            return any(self._contains_collision(value, depth + 1) for value in payload.values())

        if isinstance(payload, (list, tuple, set, deque)):
            return any(self._contains_collision(value, depth + 1) for value in payload)

        return any(hasattr(payload, key) and bool(getattr(payload, key)) for key in COLLISION_KEYS)
