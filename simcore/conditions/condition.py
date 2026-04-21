from dataclasses import dataclass
from enum import Enum, auto
import importlib
import logging

CONDITION_REGISTRY = {
    "timeout": f"{__name__.rsplit('.', 1)[0]}.timeout.TimeoutCondition",
}

logger = logging.getLogger(__name__)


class ConditionCode(Enum):
    TRIGGERED = auto()
    NOT_TRIGGERED = auto()
    NOT_EVALUATED = auto()


@dataclass
class EvaluationResult:
    condition_name: str
    code: ConditionCode
    detail: str = ""


class ConditionNode:
    def __init__(self, config: dict):
        if "type" not in config:
            raise ValueError(
                f"Condition node config must have 'type' key, but got: {config}"
            )
        self.node_type = config.get("type").lower()  # "and" or "or"
        self.name = config.get("name", self.node_type)
        self.children = []
        for child in config.get("children", []):
            if "type" not in child:
                raise ValueError(
                    f"Child condition config must have 'type' key, but got: {child}"
                )
            child_type = child["type"]
            if child_type in CONDITION_REGISTRY:
                module_path = CONDITION_REGISTRY[child_type]
                module_name, class_name = module_path.rsplit(".", 1)
                module = importlib.import_module(module_name)
                condition_class = getattr(module, class_name)
                self.children.append(condition_class(child))
            elif child_type.lower() in ["and", "or"]:
                self.children.append(ConditionNode(child))
            else:
                raise ValueError(
                    f"Unknown condition type: {child_type} in config: {child}"
                )
        if self.node_type.lower() in ["and", "or"] and len(self.children) == 0:
            raise ValueError("Non-leaf nodes must have children")

        if self.node_type.lower() in CONDITION_REGISTRY:
            self.buffer = []

    def __str__(self):
        if self.node_type.lower() in ["and", "or"]:
            return f"{self.node_type}:{self.name}({', '.join(str(child) for child in self.children)})"
        else:
            return f"{self.node_type}:{self.name}"

    def put(self, data):
        for child in self.children:
            child.put(data)

    def evaluate(self) -> EvaluationResult:
        if self.node_type.lower() == "and":
            for child in self.children:
                result = child.evaluate()
                if result.code != ConditionCode.TRIGGERED:
                    return self.result(
                        ConditionCode.NOT_TRIGGERED,
                        f"{result.condition_name} not triggered: {result.detail}",
                    )
            return self.result(ConditionCode.TRIGGERED, "All conditions triggered")
        elif self.node_type.lower() == "or":
            for child in self.children:
                result = child.evaluate()
                if result.code == ConditionCode.TRIGGERED:
                    # show detail in log
                    return self.result(
                        ConditionCode.TRIGGERED,
                        f"{result.condition_name} triggered: {result.detail}",
                    )
            return self.result(ConditionCode.NOT_TRIGGERED, "No conditions triggered")
        else:
            logger.warning(f"Evaluating leaf node {self.name} of type {self.node_type}")
            return self.result(ConditionCode.NOT_EVALUATED, "Invalid node type")

    def result(self, code: ConditionCode, detail: str = "") -> EvaluationResult:
        return EvaluationResult(self.name, code, detail)
