from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SINGLE_VALUE_OPERATORS = {"gt", "ge", "lt", "le", "eq"}
DEFAULT_EQ_EPS = 1e-6

OPERATOR_ALIASES = {
    ">": "gt",
    "gt": "gt",
    "greater_than": "gt",
    "greater": "gt",
    ">=": "ge",
    "ge": "ge",
    "gte": "ge",
    "greater_equal": "ge",
    "greater_than_or_equal": "ge",
    "<": "lt",
    "lt": "lt",
    "less_than": "lt",
    "less": "lt",
    "<=": "le",
    "le": "le",
    "lte": "le",
    "less_equal": "le",
    "less_than_or_equal": "le",
    "=": "eq",
    "==": "eq",
    "eq": "eq",
    "equal": "eq",
    "equals": "eq",
    "between": "between",
    "range": "between",
    "not_between": "not_between",
    "outside": "not_between",
    "out_of_range": "not_between",
}


@dataclass(frozen=True)
class NumericRule:
    operator: str
    threshold: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    eps: float = 0.0

    @classmethod
    def from_config(
        cls,
        rule: Any,
        raw_value: Any = None,
        *,
        raw_values: Any = None,
        eps: Any = None,
        field_name: str = "value",
    ) -> NumericRule:
        operator = normalize_operator(rule)
        values = raw_values if raw_values is not None else raw_value

        if operator in {"between", "not_between"}:
            min_value, max_value = _parse_between_values(values, field_name)
            return cls(operator=operator, min_value=min_value, max_value=max_value)

        if operator not in SINGLE_VALUE_OPERATORS:
            raise ValueError(f"Unsupported numeric rule operator: {rule!r}")

        threshold, parsed_eps = _parse_single_value(values, eps, field_name)
        if operator == "eq" and parsed_eps is None:
            parsed_eps = DEFAULT_EQ_EPS
        return cls(operator=operator, threshold=threshold, eps=float(parsed_eps or 0.0))

    def matches(self, actual: float) -> bool:
        if self.operator == "gt":
            return actual > self._threshold()
        if self.operator == "ge":
            return actual >= self._threshold()
        if self.operator == "lt":
            return actual < self._threshold()
        if self.operator == "le":
            return actual <= self._threshold()
        if self.operator == "eq":
            return abs(actual - self._threshold()) <= self.eps
        if self.operator == "between":
            return self._min_value() <= actual <= self._max_value()
        if self.operator == "not_between":
            return actual < self._min_value() or actual > self._max_value()
        raise ValueError(f"Unsupported numeric rule operator: {self.operator!r}")

    def describe(self) -> str:
        if self.operator == "between":
            return f"between [{self._min_value():.6g}, {self._max_value():.6g}]"
        if self.operator == "not_between":
            return f"not_between [{self._min_value():.6g}, {self._max_value():.6g}]"
        if self.operator == "eq":
            return f"eq {self._threshold():.6g} eps={self.eps:.6g}"
        return f"{self.operator} {self._threshold():.6g}"

    def _threshold(self) -> float:
        if self.threshold is None:
            raise ValueError(f"NumericRule {self.operator!r} has no threshold")
        return self.threshold

    def _min_value(self) -> float:
        if self.min_value is None:
            raise ValueError(f"NumericRule {self.operator!r} has no min_value")
        return self.min_value

    def _max_value(self) -> float:
        if self.max_value is None:
            raise ValueError(f"NumericRule {self.operator!r} has no max_value")
        return self.max_value


def normalize_operator(rule: Any) -> str:
    normalized = str(rule).strip().lower()
    try:
        return OPERATOR_ALIASES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported numeric rule operator: {rule!r}") from exc


def _parse_single_value(values: Any, eps: Any, field_name: str) -> tuple[float, float | None]:
    if values is None:
        raise ValueError(f"{field_name} is required for single-value numeric rules")

    if isinstance(values, (list, tuple)):
        if len(values) not in {1, 2}:
            raise ValueError(f"{field_name} must be [value] or [value, eps]")
        threshold = float(values[0])
        parsed_eps = float(values[1]) if len(values) == 2 else None
    else:
        threshold = float(values)
        parsed_eps = None

    if eps is not None:
        parsed_eps = float(eps)
    if parsed_eps is not None and parsed_eps < 0:
        raise ValueError(f"{field_name} eps must be >= 0")
    return threshold, parsed_eps


def _parse_between_values(values: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        raise ValueError(f"{field_name} must be [min_value, max_value] for between rules")

    min_value = float(values[0])
    max_value = float(values[1])
    if min_value > max_value:
        raise ValueError(f"{field_name} min_value must be <= max_value")
    return min_value, max_value
