from abc import ABC, abstractmethod

from .evaluation import ConditionCode, EvaluationResult


class ConditionNode(ABC):
    def __init__(self, config: dict):
        if "type" not in config:
            raise ValueError(f"Missing 'type' in config: {config}")
        self.node_type = config["type"].lower()
        self.name = config.get("name", self.node_type)

    @abstractmethod
    def put(self, data):
        pass

    @abstractmethod
    def evaluate(self) -> EvaluationResult:
        pass

    def result(self, code: ConditionCode, detail: str = "") -> EvaluationResult:
        return EvaluationResult(
            condition_name=self.name,
            code=code,
            detail=detail,
        )
