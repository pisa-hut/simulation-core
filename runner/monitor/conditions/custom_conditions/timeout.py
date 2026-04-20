from collections import deque

from runner.monitor.conditions.condition_node import ConditionNode
from runner.monitor.conditions.evaluation import ConditionCode, EvaluationResult


class TimeoutCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        if "timeout_ms" not in config:
            raise ValueError(
                f"TimeoutCondition config must have 'timeout_ms' key, but got: {config}"
            )

        try:
            self.timeout_threshold = float(config["timeout_ms"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "TimeoutCondition config 'timeout_ms' must be a number, "
                f"but got: {config.get('timeout_ms')}"
            ) from exc

        self.buffer = deque(maxlen=1)

    def put(self, data):
        self.buffer.append(data)

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        data_time = self.buffer[0][0] / 1e6

        if data_time > self.timeout_threshold:
            return self.result(
                ConditionCode.TRIGGERED,
                f"Timeout detected: {data_time} ms",
            )

        return self.result(ConditionCode.NOT_TRIGGERED, "No timeout detected")
