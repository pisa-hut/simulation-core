from types import SimpleNamespace

import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.kinematic_threshold import (
    KinematicThresholdCondition,
)


def make_object(actor_id: int, **kinematic_fields):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(**kinematic_fields),
    )


def make_runtime_frame(*objects):
    return SimpleNamespace(objects=list(objects))


def test_kinematic_threshold_triggers_for_specific_agent_between_rule() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": [1],
            "metric": "z",
            "rule": "between",
            "values": [-2, 2],
        }
    )

    condition.put((0, make_runtime_frame(make_object(1, z=1.5)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "Actor 1" in result.detail
    assert "kinematic.z" in result.detail


def test_kinematic_threshold_triggers_for_greater_than_rule() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "actor_id": 0,
            "metric": "x",
            "rule": ">",
            "value": 100,
        }
    )

    condition.put((0, make_runtime_frame(make_object(0, x=100.1)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "gt 100" in result.detail


def test_kinematic_threshold_triggers_for_not_between_rule() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": [1],
            "metric": "z",
            "rule": "not_between",
            "values": [-2, 2],
        }
    )

    condition.put((0, make_runtime_frame(make_object(1, z=2.1)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "not_between [-2, 2]" in result.detail


def test_kinematic_threshold_triggers_for_any_agent() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": "any",
            "metric": "y",
            "rule": "gt",
            "value": [10, 0],
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, y=3.0),
                make_object(7, y=10.5),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "Actor 7" in result.detail
    assert "agents=any" in result.detail


def test_kinematic_threshold_reports_latest_values_when_not_triggered() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": [1],
            "metric": "speed",
            "rule": "ge",
            "value": 12.0,
        }
    )

    condition.put((0, make_runtime_frame(make_object(1, speed=9.5)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED
    assert "latest values" in result.detail
    assert "speed=9.5" in result.detail


def test_kinematic_threshold_reports_unavailable_metric() -> None:
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": [1],
            "metric": "speed",
            "rule": "ge",
            "value": 12.0,
        }
    )

    condition.put((0, make_runtime_frame(make_object(1, z=0.0)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED
    assert "unavailable" in result.detail


def test_kinematic_threshold_requires_metric() -> None:
    with pytest.raises(ValueError, match="metric"):
        KinematicThresholdCondition(
            {
                "type": "kinematic_threshold",
                "rule": "gt",
                "value": 1,
            }
        )
