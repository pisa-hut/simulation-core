from __future__ import annotations

from collections import deque

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.ttc import PairTTCResult, compute_pair_ttc


class PairTTCCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)
        if "actor_id_a" not in config or "actor_id_b" not in config:
            raise ValueError("PairTTCCondition requires actor_id_a and actor_id_b")
        if "threshold_s" not in config:
            raise ValueError("PairTTCCondition requires threshold_s")

        self.actor_id_a = int(config["actor_id_a"])
        self.actor_id_b = int(config["actor_id_b"])
        self.threshold_s = float(config["threshold_s"])
        if self.threshold_s < 0:
            raise ValueError("PairTTCCondition threshold_s must be >= 0")

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
        self.buffer.append(compute_pair_ttc(objects, self.actor_id_a, self.actor_id_b))

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        latest_result = None
        for result in self.buffer:
            if result is None:
                continue
            latest_result = result
            if result.ttc_s is not None and result.ttc_s < self.threshold_s:
                return self.result(
                    ConditionCode.TRIGGERED,
                    self._triggered_detail(result),
                )

        if latest_result is None:
            return self.result(
                ConditionCode.NOT_TRIGGERED,
                (f"Could not compute TTC for actor {self.actor_id_a} and actor {self.actor_id_b}"),
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
            return (
                f"Actors {result.actor_id_a} and {result.actor_id_b} are not closing: "
                f"distance={result.distance_m:.3f}m"
            )
        return (
            f"TTC between actor {result.actor_id_a} and actor {result.actor_id_b} "
            f"is above threshold: ttc={result.ttc_s:.3f}s threshold={self.threshold_s:.3f}s"
        )
