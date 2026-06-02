from __future__ import annotations

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.expressions import evaluate_numeric_expression
from simcore.metrics.rules import NumericRule


class ParameterExpressionCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.expression = self._parse_expression(config)
        self.rule = self._parse_rule(config)
        self.context = config.get("_context", {})

    def put(self, data):
        return None

    def evaluate(self) -> EvaluationResult:
        params = self._params()
        if params is None:
            return self.result(ConditionCode.NOT_EVALUATED, "No parameters to evaluate")

        try:
            value = evaluate_numeric_expression(self.expression, params)
        except ValueError as exc:
            return self.result(
                ConditionCode.NOT_TRIGGERED,
                f"Could not evaluate parameter expression {self.expression!r}: {exc}",
            )

        if isinstance(value, bool):
            if value:
                return self.result(
                    ConditionCode.TRIGGERED,
                    f"Parameter expression {self.expression!r} evaluated to true",
                )
            return self.result(
                ConditionCode.NOT_TRIGGERED,
                f"Parameter expression {self.expression!r} evaluated to false",
            )

        if self.rule is None:
            raise ValueError(
                "ParameterExpressionCondition requires 'rule' for numeric expressions, "
                "or use a boolean comparison expression"
            )

        if self.rule.matches(value):
            return self.result(
                ConditionCode.TRIGGERED,
                (
                    f"Parameter expression {self.expression!r} matched rule "
                    f"{self.rule.describe()}: value={value:.6g}"
                ),
            )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            (
                f"Parameter expression {self.expression!r} did not match rule "
                f"{self.rule.describe()}: value={value:.6g}"
            ),
        )

    def reset(self):
        return None

    @staticmethod
    def _parse_expression(config: dict) -> str:
        raw_expression = config.get("expression", config.get("expr", config.get("parameter")))
        if not isinstance(raw_expression, str) or not raw_expression.strip():
            raise ValueError("ParameterExpressionCondition requires a non-empty 'expression'")
        return raw_expression.strip()

    @staticmethod
    def _parse_rule(config: dict) -> NumericRule | None:
        if "rule" not in config:
            return None
        return NumericRule.from_config(
            config["rule"],
            raw_value=config.get("value"),
            raw_values=config.get("values"),
            eps=config.get("eps"),
            field_name="value",
        )

    def _params(self) -> dict | None:
        if not isinstance(self.context, dict):
            return None
        params = self.context.get("params")
        return params if isinstance(params, dict) else None
