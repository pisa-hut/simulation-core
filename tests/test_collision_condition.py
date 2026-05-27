from types import SimpleNamespace

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.collision import CollisionCondition


class FakeCollision:
    def __init__(
        self,
        *,
        occurred: bool,
        actor_a: int | None = None,
        actor_b: int | None = None,
    ) -> None:
        self.occurred = occurred
        if actor_a is not None:
            self.actor_a = actor_a
        if actor_b is not None:
            self.actor_b = actor_b

    def HasField(self, field_name: str) -> bool:
        return hasattr(self, field_name)


def make_runtime_frame(*collisions: FakeCollision) -> SimpleNamespace:
    return SimpleNamespace(collision=list(collisions))


def test_collision_condition_triggers_for_any_pair_when_no_target_is_set() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "name": "collision_guard",
        }
    )

    runtime_frame = make_runtime_frame(FakeCollision(occurred=True, actor_a=3, actor_b=7))
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert result.detail == "Collision detected between actor 3 and actor 7"


def test_collision_condition_triggers_when_any_actor_hits_target_actor() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_id_a": 7,
        }
    )

    runtime_frame = make_runtime_frame(FakeCollision(occurred=True, actor_a=2, actor_b=7))
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert result.detail == "Collision detected between actor 2 and actor 7"


def test_collision_condition_triggers_only_for_specific_pair_when_two_targets_are_set() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_id_a": 3,
            "actor_id_b": 7,
        }
    )

    runtime_frame = make_runtime_frame(
        FakeCollision(occurred=True, actor_a=2, actor_b=7),
        FakeCollision(occurred=True, actor_a=7, actor_b=3),
    )
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert result.detail == "Collision detected between actor 3 and actor 7"


def test_collision_condition_ignores_other_pairs_when_two_targets_are_set() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_id_a": 3,
            "actor_id_b": 7,
        }
    )

    runtime_frame = make_runtime_frame(
        FakeCollision(occurred=True, actor_a=2, actor_b=7),
        FakeCollision(occurred=True, actor_a=3, actor_b=5),
    )
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED


def test_collision_condition_ignores_incomplete_collision_entries() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_id_a": 7,
        }
    )

    runtime_frame = make_runtime_frame(
        FakeCollision(occurred=True, actor_a=7),
        FakeCollision(occurred=False, actor_a=2, actor_b=7),
    )
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.NOT_TRIGGERED


def test_collision_condition_supports_legacy_actor_id_alias() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_id": 7,
        }
    )

    runtime_frame = make_runtime_frame(FakeCollision(occurred=True, actor_a=1, actor_b=7))
    condition.put((0, runtime_frame, None))

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
