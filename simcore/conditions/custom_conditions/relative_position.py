from __future__ import annotations

from collections import deque

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.relative_position import (
    RelativePositionResult,
    RelativePositionSelector,
    build_relative_position_selector,
    compute_relative_position,
    parse_actor_id,
)


class RelativePositionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.source_actor_id = parse_actor_id(
            config,
            "source_actor_id",
            "source_agent_id",
            "source",
        )
        self.target_actor_id = parse_actor_id(
            config,
            "target_actor_id",
            "target_agent_id",
            "target",
        )
        self.selector = build_relative_position_selector(config)

        try:
            max_buffer_size = int(config.get("max_buffer_size", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "RelativePositionCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        runtime_frame = data[1]
        objects = getattr(runtime_frame, "objects", None) or []
        self.buffer.append(
            compute_relative_position(
                objects,
                self.source_actor_id,
                self.target_actor_id,
            )
        )

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        latest_result = None
        for result in self.buffer:
            if result is None:
                continue
            latest_result = result
            if self.selector.matches(result):
                return self.result(
                    ConditionCode.TRIGGERED,
                    self._triggered_detail(result, self.selector),
                )

        if latest_result is None:
            return self.result(
                ConditionCode.NOT_TRIGGERED,
                (
                    f"Could not compute relative position for source actor "
                    f"{self.source_actor_id} and target actor {self.target_actor_id}"
                ),
            )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            self._not_triggered_detail(latest_result, self.selector),
        )

    def reset(self):
        self.buffer.clear()

    @staticmethod
    def _triggered_detail(
        result: RelativePositionResult,
        selector: RelativePositionSelector,
    ) -> str:
        return (
            f"Target actor {result.target_actor_id} is in selected relative position from "
            f"source actor {result.source_actor_id}: sector={result.sector} "
            f"angle={result.relative_angle_deg:.3f}deg distance={result.distance_m:.3f}m; "
            f"selector={selector.describe()}"
        )

    @staticmethod
    def _not_triggered_detail(
        result: RelativePositionResult,
        selector: RelativePositionSelector,
    ) -> str:
        return (
            f"Target actor {result.target_actor_id} is not in selected relative position from "
            f"source actor {result.source_actor_id}: sector={result.sector} "
            f"angle={result.relative_angle_deg:.3f}deg distance={result.distance_m:.3f}m; "
            f"selector={selector.describe()}"
        )
