import pytest

from simcore.metrics.rules import NumericRule


@pytest.mark.parametrize(
    ("rule", "value", "actual", "expected"),
    [
        ("gt", 10, 10.1, True),
        (">=", 10, 10.0, True),
        ("lt", 10, 9.9, True),
        ("<=", 10, 10.0, True),
        ("eq", [10, 0.2], 10.1, True),
        ("between", [-2, 2], -2.0, True),
        ("between", [-2, 2], 2.1, False),
        ("not_between", [-2, 2], 2.1, True),
        ("not_between", [-2, 2], 2.0, False),
        ("outside", [-2, 2], -2.1, True),
    ],
)
def test_numeric_rule_matches(rule, value, actual, expected) -> None:
    assert NumericRule.from_config(rule, value).matches(actual) is expected


def test_numeric_rule_rejects_invalid_between_range() -> None:
    with pytest.raises(ValueError, match="min_value"):
        NumericRule.from_config("between", [2, -2])
