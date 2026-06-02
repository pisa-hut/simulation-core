from abc import ABC, abstractmethod

from .evaluation import ConditionCode, EvaluationResult

TEST_OUTCOME_ALIASES = {
    "success": "success",
    "succeed": "success",
    "pass": "success",
    "passed": "success",
    "ok": "success",
    "fail": "fail",
    "failure": "fail",
    "failed": "fail",
    "invalid": "invalid",
}


class ConditionNode(ABC):
    def __init__(self, config: dict):
        if "type" not in config:
            raise ValueError(f"Missing 'type' in config: {config}")
        self.node_type = config["type"].lower()
        self.name = config.get("name", self.node_type)
        self.test_outcome = self._parse_test_outcome(config)

    @abstractmethod
    def put(self, data):
        pass

    @abstractmethod
    def evaluate(self) -> EvaluationResult:
        pass

    @abstractmethod
    def reset(self):
        pass

    def result(
        self,
        code: ConditionCode,
        detail: str = "",
        *,
        test_outcome: str | None = None,
        trigger_name: str | None = None,
    ) -> EvaluationResult:
        return EvaluationResult(
            condition_name=self.name,
            code=code,
            detail=detail,
            test_outcome=test_outcome if test_outcome is not None else self.test_outcome,
            trigger_name=trigger_name if trigger_name is not None else self.name,
        )

    @staticmethod
    def _parse_test_outcome(config: dict) -> str | None:
        raw_outcome = config.get(
            "test_outcome",
            config.get("outcome", config.get("result_status", config.get("result"))),
        )
        if raw_outcome is None:
            return None

        normalized = str(raw_outcome).strip().lower()
        try:
            return TEST_OUTCOME_ALIASES[normalized]
        except KeyError as exc:
            raise ValueError(
                "Condition result status must be one of Success, Fail, or Invalid, "
                f"but got: {raw_outcome!r}"
            ) from exc
