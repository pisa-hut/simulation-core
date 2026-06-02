from math import pi
from types import SimpleNamespace

from simcore.metrics.relative_position import (
    angle_in_range,
    build_relative_position_selector,
    compute_relative_position,
    sector_from_relative_angle,
)


def make_object(actor_id: int, x: float, y: float, yaw: float = 0.0):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(x=x, y=y, yaw=yaw),
    )


def test_compute_relative_position_uses_source_yaw_as_zero_degrees() -> None:
    result = compute_relative_position(
        [
            make_object(1, 0.0, 0.0, yaw=pi / 2),
            make_object(2, 1.0, 0.0),
        ],
        source_actor_id=1,
        target_actor_id=2,
    )

    assert result is not None
    assert result.relative_angle_deg == -90.0
    assert result.sector == 6


def test_sector_from_relative_angle_uses_eight_forward_starting_sectors() -> None:
    assert sector_from_relative_angle(0.0) == 0
    assert sector_from_relative_angle(44.9) == 0
    assert sector_from_relative_angle(45.0) == 1
    assert sector_from_relative_angle(-0.1) == 7
    assert sector_from_relative_angle(-45.0) == 7
    assert sector_from_relative_angle(-90.0) == 6


def test_selector_supports_direction_and_one_based_sectors() -> None:
    selector = build_relative_position_selector(
        {
            "direction": "straight",
            "sectors": [3],
            "sector_index_base": 1,
        }
    )

    assert selector.sectors == frozenset({0, 2, 7})


def test_angle_range_supports_wraparound() -> None:
    assert angle_in_range(-170.0, 160.0, -160.0)
    assert angle_in_range(170.0, 160.0, -160.0)
    assert not angle_in_range(0.0, 160.0, -160.0)


def test_selector_supports_single_angle_range_list() -> None:
    selector = build_relative_position_selector({"angle_range_deg": [-45, 45]})

    assert selector.angle_ranges_deg == ((-45.0, 45.0),)
