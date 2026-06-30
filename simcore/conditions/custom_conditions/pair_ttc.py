from __future__ import annotations

from collections import deque

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.rules import NumericRule
from simcore.metrics.ttc import (
    PairTTCResult,
    compute_pair_ttc,
    parse_pair_ttc_options,
)
from simcore.runtime_actors import parse_actor_binding


class PairTTCCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)
        if "threshold_s" not in config:
            raise ValueError("PairTTCCondition requires threshold_s")

        self.actor_a = parse_actor_binding(
            config, selector_key="actor_a", legacy_keys=("actor_id_a",)
        )
        self.actor_b = parse_actor_binding(
            config, selector_key="actor_b", legacy_keys=("actor_id_b",)
        )
        self.threshold_s = float(config["threshold_s"])
        if self.threshold_s < 0:
            raise ValueError("PairTTCCondition threshold_s must be >= 0")
        self.rule = NumericRule.from_config("lt", self.threshold_s, field_name="threshold_s")
        options = parse_pair_ttc_options(config, owner="PairTTCCondition")
        self.mode = options.mode
        self.lateral_threshold_m = options.lateral_threshold_m

        try:
            max_buffer_size = int(config.get("max_buffer_size", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "PairTTCCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        runtime_frame = data[1]
        objects = getattr(runtime_frame, "objects", None) or []
        collisions = getattr(runtime_frame, "collision", None) or []
        actor_id_a = self.actor_a.resolve(runtime_frame)
        actor_id_b = self.actor_b.resolve(runtime_frame)
        if actor_id_a is None or actor_id_b is None:
            self.buffer.append(None)
            return
        self.buffer.append(
            compute_pair_ttc(
                objects,
                actor_id_a,
                actor_id_b,
                mode=self.mode,
                lateral_threshold_m=self.lateral_threshold_m,
                collisions=collisions,
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
            if result.ttc_s is not None and self.rule.matches(result.ttc_s):
                return self.result(
                    ConditionCode.TRIGGERED,
                    self._triggered_detail(result),
                )

        if latest_result is None:
            return self.result(
                ConditionCode.NOT_TRIGGERED,
                (f"Could not compute TTC for actor {self.actor_a.label} and actor {self.actor_b.label}"),
            )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            self._not_triggered_detail(latest_result),
        )

    def reset(self):
        self.buffer.clear()

    def _triggered_detail(self, result: PairTTCResult) -> str:
        return (
            f"TTC between actor {result.actor_id_a} and actor {result.actor_id_b} "
            f"is below threshold: ttc={result.ttc_s:.3f}s threshold={self.threshold_s:.3f}s"
        )

    def _not_triggered_detail(self, result: PairTTCResult) -> str:
        if result.ttc_s is None:
            if result.mode == "longitudinal" and result.lateral_distance_m is not None:
                if result.closing_speed_mps is not None and result.closing_speed_mps <= 0:
                    return (
                        f"Actors {result.actor_id_a} and {result.actor_id_b} are not closing: "
                        f"longitudinal_distance={result.longitudinal_distance_m:.3f}m "
                        f"lateral_distance={result.lateral_distance_m:.3f}m "
                        f"closing_speed={result.closing_speed_mps:.3f}m/s"
                    )
                return (
                    f"Actors {result.actor_id_a} and {result.actor_id_b} are not in a "
                    f"closing longitudinal TTC corridor: "
                    f"longitudinal_distance={result.longitudinal_distance_m:.3f}m "
                    f"lateral_distance={result.lateral_distance_m:.3f}m "
                    f"closing_speed={result.closing_speed_mps:.3f}m/s"
                )
            return (
                f"Actors {result.actor_id_a} and {result.actor_id_b} are not closing: "
                f"distance={result.distance_m:.3f}m"
            )
        return (
            f"TTC between actor {result.actor_id_a} and actor {result.actor_id_b} "
            f"is above threshold: ttc={result.ttc_s:.3f}s threshold={self.threshold_s:.3f}s"
        )
