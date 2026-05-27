from types import SimpleNamespace

import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.reach_target_position import (
    ReachTargetPositionCondition,
)


def make_object(x: float, y: float, z: float = 0.0, actor_id: int | None = None):
    obj = SimpleNamespace(kinematic=SimpleNamespace(x=x, y=y, z=z))
    if actor_id is not None:
        obj.actor_id = actor_id
    return obj


def make_runtime_frame(*objects):
    return SimpleNamespace(objects=list(objects))


class FakePositionParser:
    def __init__(self) -> None:
        self.parsed_positions = []

    def parse(self, raw_position, field_name: str):
        self.parsed_positions.append((raw_position, field_name))
        position_type = raw_position.get("type", "WorldPosition")
        if position_type == "LanePosition":
            return SimpleNamespace(x=10.0, y=20.0, z=0.0)
        if "value" in raw_position:
            return SimpleNamespace(
                x=float(raw_position["value"][0]),
                y=float(raw_position["value"][1]),
                z=float(raw_position["value"][2]) if len(raw_position["value"]) > 2 else 0.0,
            )
        return SimpleNamespace(
            x=float(raw_position["x"]),
            y=float(raw_position["y"]),
            z=float(raw_position.get("z", 0.0)),
        )


def test_reach_target_position_triggers_for_ego_with_sps_goal() -> None:
    sps = SimpleNamespace(
        ego=SimpleNamespace(goal=SimpleNamespace(position=SimpleNamespace(x=10.0, y=20.0, z=0.0)))
    )
    condition = ReachTargetPositionCondition(
        {
            "type": "reach_target_position",
            "_context": {"sps": sps},
        }
    )

    condition.put((0, make_runtime_frame(make_object(10.3, 20.4)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED


def test_reach_target_position_uses_configured_world_position_for_agent() -> None:
    position_parser = FakePositionParser()
    condition = ReachTargetPositionCondition(
        {
            "type": "reach_target_position",
            "actor_id": 7,
            "_context": {"position_parser": position_parser},
            "target_position": {
                "type": "WorldPosition",
                "value": [10.0, 20.0, 0.0],
            },
            "distance_threshold_m": 1.0,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(10.0, 20.0, actor_id=3),
                make_object(10.6, 20.0, actor_id=7),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert position_parser.parsed_positions[0][1] == "target_position"


def test_reach_target_position_defaults_actor_id_to_object_index() -> None:
    condition = ReachTargetPositionCondition(
        {
            "type": "reach_target_position",
            "agent_id": 1,
            "_context": {"position_parser": FakePositionParser()},
            "target_position": {"x": 5.0, "y": 5.0},
            "distance_threshold_m": 0.25,
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(
                make_object(0.0, 0.0),
                make_object(5.1, 5.1),
            ),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED


def test_reach_target_position_does_not_trigger_outside_threshold() -> None:
    condition = ReachTargetPositionCondition(
        {
            "type": "reach_target_position",
            "target": "ego",
            "_context": {"position_parser": FakePositionParser()},
            "target_position": {"x": 10.0, "y": 20.0},
            "distance_threshold_m": 0.5,
        }
    )

    condition.put((0, make_runtime_frame(make_object(9.0, 20.0)), None))
    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED


def test_reach_target_position_requires_position_for_non_ego_agent() -> None:
    with pytest.raises(ValueError, match="requires 'target_position'"):
        ReachTargetPositionCondition(
            {
                "type": "reach_target_position",
                "actor_id": 3,
            }
        )


def test_reach_target_position_supports_lane_position_in_monitor_config() -> None:
    position_parser = FakePositionParser()
    condition = ReachTargetPositionCondition(
        {
            "type": "reach_target_position",
            "actor_id": 3,
            "_context": {"position_parser": position_parser},
            "target_position": {
                "type": "LanePosition",
                "value": [1, -1, 10.0, 0.0],
            },
        }
    )

    condition.put(
        (
            0,
            make_runtime_frame(make_object(10.2, 20.2, actor_id=3)),
            None,
        )
    )
    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert position_parser.parsed_positions[0][0]["type"] == "LanePosition"
