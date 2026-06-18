from __future__ import annotations

from types import SimpleNamespace

from simcore.metrics.ttc import compute_pair_ttc


class FakeCollision:
    def __init__(self, *, occurred: bool, actor_a: int, actor_b: int) -> None:
        self.occurred = occurred
        self.actor_a = actor_a
        self.actor_b = actor_b

    def HasField(self, field_name: str) -> bool:
        return hasattr(self, field_name)


def make_object(actor_id: int, x: float, y: float, speed: float):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(x=x, y=y, yaw=0.0, speed=speed),
    )


def test_pair_ttc_is_zero_for_matching_collision_even_when_centers_differ() -> None:
    result = compute_pair_ttc(
        [
            make_object(0, 0.0, 0.0, speed=0.0),
            make_object(1, 5.0, 0.0, speed=10.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
        collisions=[FakeCollision(occurred=True, actor_a=1, actor_b=0)],
    )

    assert result is not None
    assert result.distance_m == 5.0
    assert result.ttc_s == 0.0


def test_pair_ttc_ignores_non_matching_collision() -> None:
    result = compute_pair_ttc(
        [
            make_object(0, 0.0, 0.0, speed=0.0),
            make_object(1, 5.0, 0.0, speed=10.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
        collisions=[FakeCollision(occurred=True, actor_a=3, actor_b=4)],
    )

    assert result is not None
    assert result.ttc_s is None


def test_pair_ttc_collision_without_objects_returns_zero_ttc() -> None:
    result = compute_pair_ttc(
        [],
        actor_id_a=0,
        actor_id_b=1,
        collisions=[FakeCollision(occurred=True, actor_a=0, actor_b=1)],
    )

    assert result is not None
    assert result.distance_m is None
    assert result.ttc_s == 0.0
