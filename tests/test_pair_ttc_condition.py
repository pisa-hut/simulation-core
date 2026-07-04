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


class FakeCollision:
    def __init__(self, *, occurred: bool, actor_a: int, actor_b: int) -> None:
        self.occurred = occurred
        self.actor_a = actor_a
        self.actor_b = actor_b

    def HasField(self, field_name: str) -> bool:
        return hasattr(self, field_name)


def make_runtime_frame(*objects, collision=None):
    return SimpleNamespace(objects=list(objects), collision=list(collision or []))


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


def test_pair_ttc_condition_does_not_trigger_for_adjacent_lane_overtake() -> None:
    condition = PairTTCCondition(
        {
            "type": "pair_ttc",
            "actor_id_a": 0,
            "actor_id_b": 12,
            "threshold_s": 2.0,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0, speed=30.0),
                make_object(12, 20.0, 3.5, speed=10.0),
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED
    assert "not in a closing longitudinal TTC corridor" in result.detail


def test_pair_ttc_condition_radial_mode_preserves_point_closing_behavior() -> None:
    condition = PairTTCCondition(
        {
            "type": "pair_ttc",
            "actor_id_a": 0,
            "actor_id_b": 12,
            "threshold_s": 2.0,
            "mode": "radial",
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0, speed=30.0),
                make_object(12, 20.0, 3.5, speed=10.0),
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "below threshold" in result.detail


def test_pair_ttc_condition_uses_configured_lateral_threshold() -> None:
    condition = PairTTCCondition(
        {
            "type": "pair_ttc",
            "actor_id_a": 0,
            "actor_id_b": 12,
            "threshold_s": 2.0,
            "lateral_threshold_m": 4.0,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0, 0.0, 0.0, speed=30.0),
                make_object(12, 20.0, 3.5, speed=10.0),
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED


def test_pair_ttc_condition_requires_threshold() -> None:
    with pytest.raises(ValueError, match="threshold_s"):
        PairTTCCondition(
            {
                "type": "pair_ttc",
                "actor_id_a": 0,
                "actor_id_b": 12,
            }
        )


def test_pair_ttc_condition_triggers_when_matching_collision_occurs() -> None:
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
                collision=[FakeCollision(occurred=True, actor_a=12, actor_b=0)],
            ),
            None,
        )
    )

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "ttc=0.000s" in result.detail
