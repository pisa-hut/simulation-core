from runner.monitor.conditions.condition import (
    ConditionCode,
    ConditionNode,
    EvaluationResult,
)


class TimeoutCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        if "timeout_ms" not in config:
            raise ValueError(
                f"TimeoutCondition config must have 'timeout_ms' key, but got: {config}"
            )
        try:
            self.timeout_threshold = float(config["timeout_ms"])  # in milliseconds
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"TimeoutCondition config 'timeout_ms' must be a number, but got: {config.get('timeout_ms')}"
            ) from exc

    def put(self, data):
        self.buffer.append(data)
        if len(self.buffer) > 1:
            self.buffer.pop(0)

    def evaluate(self) -> EvaluationResult:
        if len(self.buffer) < 1:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")
        data_time = self.buffer[0][0] / 1e6  # Convert ns to ms

        if data_time > self.timeout_threshold:
            return self.result(
                ConditionCode.TRIGGERED,
                f"Timeout detected: {data_time} ms",
            )
        return self.result(ConditionCode.NOT_TRIGGERED, "No timeout detected")
