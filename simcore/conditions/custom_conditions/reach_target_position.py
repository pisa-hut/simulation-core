from __future__ import annotations

from collections import deque
from math import hypot
from typing import Any

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.utils.position import Position

DEFAULT_DISTANCE_THRESHOLD_M = 0.5
EGO_ACTOR_ID = 0


class ReachTargetPositionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.distance_threshold_m = self._parse_distance_threshold(config)
        self.actor_id = self._parse_actor_id(config)
        self.target_position = self._parse_target_position(config)

        if self.target_position is None:
            if self.actor_id != EGO_ACTOR_ID:
                raise ValueError(
                    "ReachTargetPositionCondition requires 'target_position' for non-ego agents"
                )
            self.target_position = self._target_position_from_sps(config)

        try:
            max_buffer_size = int(config.get("max_buffer_size", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ReachTargetPositionCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        runtime_frame = data[1]
        self.buffer.append(getattr(runtime_frame, "objects", []))

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        for objects in self.buffer:
            actor_position = self._find_actor_position(objects)
            if actor_position is None:
                continue

            distance_m = self._distance_xy(actor_position, self.target_position)
            if distance_m <= self.distance_threshold_m:
                return self.result(
                    ConditionCode.TRIGGERED,
                    (
                        f"Actor {self.actor_id} reached target position: "
                        f"distance={distance_m:.3f}m threshold={self.distance_threshold_m:.3f}m"
                    ),
                )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            (
                f"Actor {self.actor_id} has not reached target position "
                f"within {self.distance_threshold_m:.3f}m"
            ),
        )

    def reset(self):
        self.buffer.clear()

    @staticmethod
    def _parse_distance_threshold(config: dict) -> float:
        raw_value = config.get(
            "distance_threshold_m",
            config.get("threshold_m", config.get("radius_m", DEFAULT_DISTANCE_THRESHOLD_M)),
        )
        try:
            threshold = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ReachTargetPositionCondition config 'distance_threshold_m' must be a number, "
                f"but got: {raw_value}"
            ) from exc
        if threshold < 0:
            raise ValueError(
                "ReachTargetPositionCondition config 'distance_threshold_m' must be >= 0, "
                f"but got: {threshold}"
            )
        return threshold

    @staticmethod
    def _parse_actor_id(config: dict) -> int:
        target = config.get("target", config.get("target_agent"))
        if isinstance(target, str) and target.lower() == "ego":
            return EGO_ACTOR_ID

        raw_value = config.get("actor_id", config.get("agent_id"))
        if raw_value is None:
            raw_value = target
        if raw_value is None:
            return EGO_ACTOR_ID

        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ReachTargetPositionCondition target must be 'ego' or an integer actor/agent id, "
                f"but got: {raw_value}"
            ) from exc

    @classmethod
    def _parse_target_position(cls, config: dict) -> Position | None:
        raw_position = config.get("target_position", config.get("position"))
        if raw_position is None:
            return None

        position_parser = cls._position_parser_from_context(config)
        if position_parser is None:
            raise ValueError(
                "ReachTargetPositionCondition requires a PositionParser to parse target_position"
            )

        return position_parser.parse(raw_position, field_name="target_position")

    @staticmethod
    def _target_position_from_sps(config: dict) -> Position:
        context = config.get("_context", {})
        sps = context.get("sps") if isinstance(context, dict) else None
        goal = getattr(getattr(sps, "ego", None), "goal", None)
        goal_position = getattr(goal, "position", None)
        if goal_position is None:
            raise ValueError(
                "ReachTargetPositionCondition target_position is omitted for ego, "
                "but ScenarioPack ego goal position is unavailable"
            )

        return goal_position

    @staticmethod
    def _position_parser_from_context(config: dict):
        context = config.get("_context", {})
        if not isinstance(context, dict):
            return None
        return context.get("position_parser")

    def _find_actor_position(self, objects: Any) -> tuple[float, float, float] | None:
        if not objects:
            return None

        for index, obj in enumerate(objects):
            object_actor_id = self._object_actor_id(obj, index)
            if object_actor_id == self.actor_id:
                return self._object_position(obj)

        return None

    @staticmethod
    def _object_actor_id(obj: Any, fallback_index: int) -> int:
        for field_name in ("actor_id", "agent_id", "id", "object_id"):
            if hasattr(obj, field_name):
                try:
                    return int(getattr(obj, field_name))
                except TypeError, ValueError:
                    break
        return fallback_index

    @staticmethod
    def _object_position(obj: Any) -> tuple[float, float, float] | None:
        source = getattr(obj, "kinematic", obj)
        if not hasattr(source, "x") or not hasattr(source, "y"):
            return None
        return (
            float(source.x),
            float(source.y),
            float(getattr(source, "z", 0.0)),
        )

    @staticmethod
    def _distance_xy(
        actor_position: tuple[float, float, float],
        target_position: Position,
    ) -> float:
        return hypot(actor_position[0] - target_position.x, actor_position[1] - target_position.y)
