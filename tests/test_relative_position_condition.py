from types import SimpleNamespace

import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.relative_position import RelativePositionCondition


def make_object(actor_id: int, x: float, y: float, yaw: float = 0.0):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(x=x, y=y, yaw=yaw),
    )


def make_runtime_frame(*objects):
    return SimpleNamespace(objects=list(objects))


def test_relative_position_condition_triggers_for_straight_direction() -> None:
    condition = RelativePositionCondition(
        {
            "type": "relative_position",
            "source_actor_id": 1,
            "target_actor_id": 0,
            "direction": "straight",
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(1, 0.0, 0.0),
                make_object(0, 10.0, -1.0),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "sector=7" in result.detail
    assert "angle=-5.711deg" in result.detail


def test_relative_position_condition_does_not_trigger_for_wrong_direction() -> None:
    condition = RelativePositionCondition(
        {
            "type": "relative_position",
            "source": 1,
            "target": 0,
            "direction": "rear",
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(1, 0.0, 0.0),
                make_object(0, 10.0, 0.0),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED
    assert "sector=0" in result.detail
    assert "selector=directions=rear" in result.detail


def test_relative_position_condition_triggers_for_angle_range() -> None:
    condition = RelativePositionCondition(
        {
            "type": "relative_position",
            "source": "ego",
            "target": 2,
            "angle_range_deg": [80, 100],
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0),
                make_object(2, 0.0, 5.0),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "angle=90.000deg" in result.detail


def test_relative_position_condition_requires_selector() -> None:
    with pytest.raises(ValueError, match="direction, sector"):
        RelativePositionCondition(
            {
                "type": "relative_position",
                "source": 1,
                "target": 2,
            }
        )
