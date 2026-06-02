import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.parameter_expression import (
    ParameterExpressionCondition,
)
from simcore.metrics.expressions import evaluate_numeric_expression


def test_evaluate_numeric_expression_supports_arithmetic_and_functions() -> None:
    value = evaluate_numeric_expression(
        "abs(a_speed - b_speed) + c * 2",
        {"a_speed": 10, "b_speed": 3, "c": 1.5},
    )

    assert value == 10.0


def test_evaluate_numeric_expression_supports_boolean_comparison() -> None:
    value = evaluate_numeric_expression(
        "a * b + c < d",
        {"a": 2, "b": 3, "c": 1, "d": 8},
    )

    assert value is True


def test_evaluate_numeric_expression_rejects_unknown_variables() -> None:
    with pytest.raises(ValueError, match="Unknown expression variable"):
        evaluate_numeric_expression("a + missing", {"a": 1})


def test_parameter_expression_condition_triggers_with_numeric_rule() -> None:
    condition = ParameterExpressionCondition(
        {
            "type": "parameter_expression",
            "expression": "abs(a_speed - b_speed)",
            "rule": "gt",
            "value": 5,
            "_context": {"params": {"a_speed": 12, "b_speed": 3}},
        }
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "value=9" in result.detail


def test_parameter_expression_condition_supports_single_parameter_range_check() -> None:
    condition = ParameterExpressionCondition(
        {
            "type": "parameter_expression",
            "parameter": "a_speed",
            "rule": "between",
            "values": [5, 15],
            "_context": {"params": {"a_speed": 12}},
        }
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED


def test_parameter_expression_condition_triggers_with_boolean_expression() -> None:
    condition = ParameterExpressionCondition(
        {
            "type": "parameter_expression",
            "expression": "a * b + c < d",
            "_context": {"params": {"a": 2, "b": 3, "c": 1, "d": 8}},
        }
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
