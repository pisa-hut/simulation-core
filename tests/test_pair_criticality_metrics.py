from __future__ import annotations

from math import pi
from types import SimpleNamespace

import pytest

from simcore.metrics.pair_criticality import compute_pair_criticality


def make_object(
    actor_id: int,
    x: float,
    y: float,
    *,
    yaw: float = 0.0,
    speed: float = 0.0,
    acceleration: float = 0.0,
):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(
            x=x,
            y=y,
            yaw=yaw,
            speed=speed,
            acceleration=acceleration,
        ),
    )


def test_pair_criticality_for_leading_vehicle_braking() -> None:
    result = compute_pair_criticality(
        [
            make_object(0, 0.0, 0.0, speed=20.0, acceleration=-1.0),
            make_object(1, 40.0, 0.0, speed=10.0, acceleration=-4.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
    )

    assert result is not None
    assert result.longitudinal_distance_m == pytest.approx(40.0)
    assert result.lateral_distance_m == pytest.approx(0.0)
    assert result.closing_speed_mps == pytest.approx(10.0)
    assert result.relative_longitudinal_speed_mps == pytest.approx(-10.0)
    assert result.relative_longitudinal_acceleration_mps2 == pytest.approx(-3.0)
    assert result.thw_s == pytest.approx(2.0)
    assert result.drac_mps2 == pytest.approx(1.25)


def test_pair_criticality_for_cut_in_lateral_motion() -> None:
    result = compute_pair_criticality(
        [
            make_object(0, 0.0, 0.0, speed=15.0),
            make_object(1, 20.0, 3.0, yaw=-pi / 2, speed=2.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
    )

    assert result is not None
    assert result.longitudinal_distance_m == pytest.approx(20.0)
    assert result.lateral_distance_m == pytest.approx(3.0)
    assert result.relative_lateral_speed_mps == pytest.approx(-2.0)


def test_pair_criticality_invalidates_thw_and_drac_when_target_is_behind() -> None:
    result = compute_pair_criticality(
        [
            make_object(0, 10.0, 0.0, speed=15.0),
            make_object(1, 0.0, 0.0, speed=5.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
    )

    assert result is not None
    assert result.longitudinal_distance_m == pytest.approx(-10.0)
    assert result.thw_s is None
    assert result.drac_mps2 is None


def test_pair_criticality_gates_thw_and_drac_by_lateral_threshold() -> None:
    result = compute_pair_criticality(
        [
            make_object(0, 0.0, 0.0, speed=20.0),
            make_object(1, 40.0, 3.5, speed=10.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
    )

    assert result is not None
    assert result.lateral_distance_m == pytest.approx(3.5)
    assert result.thw_s is None
    assert result.drac_mps2 is None


def test_pair_criticality_can_disable_lateral_threshold_for_thw_and_drac() -> None:
    result = compute_pair_criticality(
        [
            make_object(0, 0.0, 0.0, speed=20.0),
            make_object(1, 40.0, 3.5, speed=10.0),
        ],
        actor_id_a=0,
        actor_id_b=1,
        lateral_threshold_m=None,
    )

    assert result is not None
    assert result.thw_s == pytest.approx(2.0)
    assert result.drac_mps2 == pytest.approx(1.25)
