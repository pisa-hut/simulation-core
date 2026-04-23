from dataclasses import dataclass
from enum import Enum, auto


class ConditionCode(Enum):
    TRIGGERED = auto()
    NOT_TRIGGERED = auto()
    NOT_EVALUATED = auto()


@dataclass
class EvaluationResult:
    condition_name: str
    code: ConditionCode
    detail: str = ""
