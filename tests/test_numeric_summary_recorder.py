from math import nan
from types import SimpleNamespace

import pytest

from simcore.monitoring.sample import MonitorSample
from simcore.monitoring.summary_recorder_registry import build_summary_recorders
from simcore.monitoring.summary_recorders.numeric_aggregation import NumericAccumulator
from simcore.monitoring.summary_recorders.numeric_sources import (
    PairTTCValueSource,
    RelativePositionValueSource,
)
from simcore.monitoring.summary_recorders.numeric_summary import NumericSummaryRecorder


def make_object(actor_id: int, **kinematic_fields):
    return SimpleNamespace(
        actor_id=actor_id,
        kinematic=SimpleNamespace(**kinematic_fields),
    )


def make_sample(step_index: int, sim_time_ns: int, *objects) -> MonitorSample:
    return MonitorSample(
        step_index=step_index,
        sim_time_ns=sim_time_ns,
        runtime_frame=SimpleNamespace(objects=list(objects)),
        control=None,
    )


def test_numeric_summary_aggregates_transformed_kinematic_values() -> None:
    recorder = NumericSummaryRecorder(
        {
            "type": "numeric_summary",
            "name": "ego_deceleration",
            "source": {
                "type": "kinematic",
                "actor_id": 0,
                "field": "acc",
            },
            "transforms": ["negate", "positive_part"],
            "aggregations": ["max", "mean", "std"],
            "include_extrema_location": True,
        }
    )

    for step_index, acceleration in enumerate((-1.0, -3.0, 2.0)):
        recorder.update(
            make_sample(
                step_index,
                step_index * 1_000_000,
                make_object(0, acceleration=acceleration),
            )
        )

    values = recorder.accumulator.record()
    assert values["max"] == 3.0
    assert values["mean"] == pytest.approx(4.0 / 3.0)
    assert values["std"] == pytest.approx(1.247219128924647)
    assert values["count"] == 3
    assert values["max_step_index"] == 1
    assert values["max_sim_time_ms"] == 1.0


def test_numeric_accumulator_skips_invalid_values_and_keeps_first_extremum() -> None:
    accumulator = NumericAccumulator(["min", "max"], include_extrema_location=True)
    samples = [make_sample(index, index * 1_000_000) for index in range(5)]

    for value, sample in zip((None, nan, 4.0, 4.0, float("inf")), samples, strict=True):
        accumulator.update(value, sample)

    assert accumulator.record() == {
        "min": 4.0,
        "max": 4.0,
        "count": 2,
        "min_step_index": 2,
        "min_sim_time_ms": 2.0,
        "max_step_index": 2,
        "max_sim_time_ms": 2.0,
    }


def test_numeric_summary_with_no_valid_samples_outputs_empty_statistics() -> None:
    recorder = NumericSummaryRecorder(
        {
            "type": "numeric_summary",
            "source": {
                "type": "kinematic",
                "actor_id": 99,
                "field": "speed",
            },
            "aggregations": ["min", "std"],
            "include_extrema_location": True,
        }
    )

    recorder.update(make_sample(0, 0, make_object(0, speed=5.0)))

    assert recorder.accumulator.record() == {
        "min": None,
        "std": None,
        "count": 0,
        "min_step_index": None,
        "min_sim_time_ms": None,
    }


def test_metric_sources_expose_ttc_and_relative_position_fields() -> None:
    sample = make_sample(
        0,
        0,
        make_object(0, x=0.0, y=0.0, yaw=0.0, speed=4.0),
        make_object(1, x=10.0, y=0.0, yaw=0.0, speed=0.0),
    )
    ttc_source = PairTTCValueSource(
        {
            "actor_id_a": 0,
            "actor_id_b": 1,
            "field": "ttc_s",
            "lateral_threshold_m": 2.0,
        }
    )
    relative_source = RelativePositionValueSource(
        {
            "source_actor_id": 0,
            "target_actor_id": 1,
            "field": "distance_m",
        }
    )

    assert ttc_source.read(sample) == 2.5
    assert relative_source.read(sample) == 10.0


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            {
                "type": "numeric_summary",
                "source": {"type": "unknown", "field": "value"},
                "aggregations": ["max"],
            },
            "Unknown numeric summary source type",
        ),
        (
            {
                "type": "numeric_summary",
                "source": {"type": "kinematic", "actor_id": 0, "field": "velocity"},
                "aggregations": ["max"],
            },
            "Unknown field",
        ),
        (
            {
                "type": "numeric_summary",
                "source": {"type": "kinematic", "actor_id": 0, "field": "speed"},
                "aggregations": [],
            },
            "non-empty list",
        ),
        (
            {
                "type": "numeric_summary",
                "source": {"type": "kinematic", "actor_id": 0, "field": "speed"},
                "aggregations": ["max", "MAX"],
            },
            "duplicates",
        ),
        (
            {
                "type": "numeric_summary",
                "source": {"type": "kinematic", "actor_id": 0, "field": "speed"},
                "aggregations": ["max"],
                "transforms": ["square"],
            },
            "Unknown numeric summary transform",
        ),
    ],
)
def test_numeric_summary_rejects_invalid_config(config: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        NumericSummaryRecorder(config)


def test_summary_recorder_names_must_be_unique() -> None:
    config = {
        "type": "numeric_summary",
        "name": "duplicate",
        "source": {"type": "kinematic", "actor_id": 0, "field": "speed"},
        "aggregations": ["max"],
    }

    with pytest.raises(ValueError, match="names must be unique"):
        build_summary_recorders([config, config])
