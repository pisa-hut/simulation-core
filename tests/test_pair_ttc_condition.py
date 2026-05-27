from types import SimpleNamespace

import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.pair_ttc import PairTTCCondition


def make_object(actor_id: int, x: float, y: float, speed: float, yaw: float = 0.0):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(
            x=x,
            y=y,
            z=0.0,
            yaw=yaw,
            speed=speed,
        ),
    )


def make_runtime_frame(*objects):
    return SimpleNamespace(objects=list(objects))


def test_pair_ttc_condition_triggers_below_threshold() -> None:
    condition = PairTTCCondition(
        {
            "type": "pair_ttc",
            "actor_id_a": 0,
            "actor_id_b": 12,
            "threshold_s": 1.0,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0, speed=10.0),
                make_object(12, 5.0, 0.0, speed=0.0),
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "below threshold" in result.detail


def test_pair_ttc_condition_does_not_trigger_when_not_closing() -> None:
    condition = PairTTCCondition(
        {
            "type": "pair_ttc",
            "actor_id_a": 0,
            "actor_id_b": 12,
            "threshold_s": 1.0,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0, speed=0.0),
                make_object(12, 5.0, 0.0, speed=10.0),
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED
    assert "not closing" in result.detail


def test_pair_ttc_condition_requires_threshold() -> None:
    with pytest.raises(ValueError, match="threshold_s"):
        PairTTCCondition(
            {
                "type": "pair_ttc",
                "actor_id_a": 0,
                "actor_id_b": 12,
            }
        )
