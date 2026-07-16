from __future__ import annotations

import pytest

from simcore.sampler import (
    FeedbackBoundarySampler,
    FeedbackLabel,
    ParameterSpace,
    ParameterSpec,
    RandomSampler,
    Sample,
    SampleResult,
    create_sampler,
)


def _space() -> ParameterSpace:
    return ParameterSpace.from_specs(
        [
            ParameterSpec("agent_speed", bounds=(0.0, 10.0), param_type="double"),
            ParameterSpec("cut_in_distance", bounds=(0.0, 20.0), param_type="double"),
        ]
    )


def test_feedback_sampler_uses_boundary_midpoint_after_initial_feedback() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=3,
        initial_samples=2,
        initial_sampler="sobol",
        exploration_ratio=0,
        perturbation_scale=0,
        random_seed=7,
    )

    safe = sampler.next()
    unsafe = sampler.next()
    assert safe is not None and unsafe is not None
    sampler.update(
        safe,
        SampleResult(params=safe.params, status="finished", test_outcome="success"),
    )
    sampler.update(
        unsafe,
        SampleResult(params=unsafe.params, status="finished", test_outcome="fail"),
    )

    boundary = sampler.next()

    assert boundary is not None
    assert boundary.params == pytest.approx(
        {
            "agent_speed": (safe.params["agent_speed"] + unsafe.params["agent_speed"]) / 2,
            "cut_in_distance": (safe.params["cut_in_distance"] + unsafe.params["cut_in_distance"])
            / 2,
        }
    )
    assert sampler.remaining_samples() == 0


def test_feedback_sampler_falls_back_to_exploration_without_both_labels() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=4,
        initial_samples=1,
        exploration_ratio=0,
        random_seed=11,
    )

    first = sampler.next()
    assert first is not None
    sampler.update(
        first,
        SampleResult(params=first.params, status="finished", test_outcome="success"),
    )

    remaining = [sampler.next(), sampler.next(), sampler.next()]

    assert all(sample is not None for sample in remaining)
    assert len({tuple(sample.params.values()) for sample in [first, *remaining]}) == 4


@pytest.mark.parametrize(
    ("boundary_pair", "left_result", "right_result"),
    [
        (
            ["safe", "invalid"],
            SampleResult(params={}, status="finished", test_outcome="success"),
            SampleResult(params={}, status="finished", test_outcome="invalid"),
        ),
        (
            ["unsafe", "invalid"],
            SampleResult(params={}, status="finished", test_outcome="fail"),
            SampleResult(params={}, status="finished", test_outcome="invalid"),
        ),
    ],
)
def test_feedback_sampler_supports_configured_semantic_boundary(
    boundary_pair,
    left_result,
    right_result,
) -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=1,
        initial_samples=0,
        boundary_pairs=[boundary_pair],
        candidates_per_pair=1,
        exploration_ratio=0,
        perturbation_scale=0,
    )
    left = Sample(params={"agent_speed": 2.0, "cut_in_distance": 4.0})
    right = Sample(params={"agent_speed": 8.0, "cut_in_distance": 16.0})
    sampler.update(left, left_result)
    sampler.update(right, right_result)

    boundary = sampler.next()

    assert boundary is not None
    assert boundary.params == {
        "agent_speed": 5.0,
        "cut_in_distance": 10.0,
    }


def test_feedback_sampler_round_robins_candidates_across_boundary_pairs() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=3,
        initial_samples=0,
        boundary_pairs=[
            ["safe", "unsafe"],
            ["safe", "invalid"],
            ["unsafe", "invalid"],
        ],
        boundary_candidate_count=3,
        candidates_per_pair=1,
        exploration_ratio=0,
        perturbation_scale=0,
    )
    observations = [
        (
            Sample(params={"agent_speed": 0.0, "cut_in_distance": 0.0}),
            SampleResult(params={}, status="finished", test_outcome="success"),
        ),
        (
            Sample(params={"agent_speed": 4.0, "cut_in_distance": 0.0}),
            SampleResult(params={}, status="finished", test_outcome="fail"),
        ),
        (
            Sample(params={"agent_speed": 8.0, "cut_in_distance": 0.0}),
            SampleResult(params={}, status="finished", test_outcome="invalid"),
        ),
    ]
    for sample, result in observations:
        sampler.update(sample, result)

    candidates = sampler._boundary_candidates()

    assert [candidate.label_pair for candidate in candidates] == [
        (FeedbackLabel.SAFE, FeedbackLabel.UNSAFE),
        (FeedbackLabel.SAFE, FeedbackLabel.INVALID),
        (FeedbackLabel.UNSAFE, FeedbackLabel.INVALID),
    ]


def test_feedback_sampler_explores_until_a_configured_pair_is_active() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=2,
        initial_samples=0,
        boundary_pairs=[["safe", "invalid"]],
        exploration_ratio=0,
    )
    safe = Sample(params={"agent_speed": 0.0, "cut_in_distance": 0.0})
    unsafe = Sample(params={"agent_speed": 10.0, "cut_in_distance": 20.0})
    sampler.update(
        safe,
        SampleResult(params=safe.params, status="finished", test_outcome="success"),
    )
    sampler.update(
        unsafe,
        SampleResult(params=unsafe.params, status="finished", test_outcome="fail"),
    )

    assert sampler._has_boundary_labels() is False
    assert sampler.next() is not None


@pytest.mark.parametrize(
    ("boundary_pairs", "message"),
    [
        ([], "non-empty"),
        ([["safe"]], "exactly two"),
        ([["safe", "safe"]], "different labels"),
        ([["safe", "error"]], "cannot include ERROR"),
        ([["safe", "unknown"]], "unsupported"),
        ([["safe", "unsafe"], ["unsafe", "safe"]], "duplicate"),
    ],
)
def test_feedback_sampler_rejects_invalid_boundary_pairs(boundary_pairs, message) -> None:
    with pytest.raises(ValueError, match=message):
        FeedbackBoundarySampler(
            _space(),
            total_samples=4,
            boundary_pairs=boundary_pairs,
        )


def test_feedback_sampler_requires_candidate_capacity_for_each_boundary_pair() -> None:
    with pytest.raises(ValueError, match="at least the number"):
        FeedbackBoundarySampler(
            _space(),
            total_samples=4,
            boundary_pairs=[
                ["safe", "unsafe"],
                ["safe", "invalid"],
            ],
            boundary_candidate_count=1,
        )


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            SampleResult(params={}, status="failed", test_outcome="success"),
            FeedbackLabel.ERROR,
        ),
        (
            SampleResult(params={}, status="skipped", test_outcome="unknown"),
            FeedbackLabel.INVALID,
        ),
        (
            SampleResult(params={}, status="finished", test_outcome="invalid"),
            FeedbackLabel.INVALID,
        ),
        (
            SampleResult(
                params={},
                status="finished",
                test_outcome="success",
                metrics={"collision.collision": True},
            ),
            FeedbackLabel.UNSAFE,
        ),
        (
            SampleResult(
                params={},
                status="finished",
                metrics={"ego_ttc.min_ttc_s": 0.5},
            ),
            FeedbackLabel.UNSAFE,
        ),
        (
            SampleResult(
                params={},
                status="finished",
                metrics={"ego_ttc.min_ttc_s": 2.5},
            ),
            FeedbackLabel.SAFE,
        ),
    ],
)
def test_feedback_sampler_classification_precedence(result, expected) -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=2,
        min_ttc_threshold=1.0,
    )

    assert sampler.classify(result) == expected


def test_feedback_sampler_custom_metric_requires_present_result() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=2,
        unsafe_conditions=[{"metric": "clearance.min", "operator": "lt", "value": 1.0}],
    )

    assert (
        sampler.classify(SampleResult(params={}, status="finished", metrics={}))
        == FeedbackLabel.ERROR
    )
    assert (
        sampler.classify(
            SampleResult(
                params={},
                status="finished",
                metrics={"clearance.min": 0.5},
            )
        )
        == FeedbackLabel.UNSAFE
    )


def test_feedback_sampler_keeps_categorical_values_within_matching_pair() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(0.0, 10.0), param_type="double"),
            ParameterSpec("maneuver", values=("left", "right"), param_type="string"),
        ]
    )
    sampler = FeedbackBoundarySampler(
        space,
        total_samples=3,
        initial_samples=0,
        exploration_ratio=0,
        perturbation_scale=0,
    )
    safe = sampler.next()
    assert safe is not None
    unsafe = sampler.next()
    assert unsafe is not None
    if unsafe.params["maneuver"] != safe.params["maneuver"]:
        unsafe = type(unsafe)(
            params={**unsafe.params, "maneuver": safe.params["maneuver"]},
            id=unsafe.id,
            metadata=unsafe.metadata,
        )
    sampler.update(
        safe,
        SampleResult(params=safe.params, status="finished", test_outcome="success"),
    )
    sampler.update(
        unsafe,
        SampleResult(params=unsafe.params, status="finished", test_outcome="fail"),
    )

    boundary = sampler.next()

    assert boundary is not None
    assert boundary.params["maneuver"] == safe.params["maneuver"]


def test_feedback_sampler_keeps_numeric_discrete_candidates_in_domain() -> None:
    space = ParameterSpace.from_specs(
        [ParameterSpec("speed", values=(0.0, 4.0, 10.0), param_type="double")]
    )
    sampler = FeedbackBoundarySampler(
        space,
        total_samples=3,
        initial_samples=0,
        exploration_ratio=0,
        perturbation_scale=0,
    )
    safe = sampler.next()
    unsafe = sampler.next()
    assert safe is not None and unsafe is not None
    sampler.update(
        safe,
        SampleResult(params=safe.params, status="finished", test_outcome="success"),
    )
    sampler.update(
        unsafe,
        SampleResult(params=unsafe.params, status="finished", test_outcome="fail"),
    )

    candidate = sampler.next()

    assert candidate is not None
    assert candidate.params["speed"] in {0.0, 4.0, 10.0}


def test_feedback_sampler_spreads_boundary_samples_across_components() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=2,
        initial_samples=0,
        exploration_ratio=0,
        opposite_neighbors=1,
        candidates_per_pair=2,
        boundary_candidate_count=8,
        uncertainty_weight=0,
        novelty_weight=0,
        coverage_weight=1,
        perturbation_scale=0.01,
        random_seed=3,
    )
    observations = [
        (Sample(params={"agent_speed": 0.0, "cut_in_distance": 0.0}), "success"),
        (Sample(params={"agent_speed": 2.0, "cut_in_distance": 0.0}), "fail"),
        (Sample(params={"agent_speed": 8.0, "cut_in_distance": 20.0}), "success"),
        (Sample(params={"agent_speed": 10.0, "cut_in_distance": 20.0}), "fail"),
    ]
    for sample, outcome in observations:
        sampler.update(
            sample,
            SampleResult(params=sample.params, status="finished", test_outcome=outcome),
        )

    first = sampler.next()
    assert first is not None
    sampler.update(
        first,
        SampleResult(params=first.params, status="finished", test_outcome="invalid"),
    )
    second = sampler.next()

    assert second is not None
    assert (first.params["agent_speed"] < 5) != (second.params["agent_speed"] < 5)


def test_feedback_sampler_uses_local_opposite_label_neighbors() -> None:
    sampler = FeedbackBoundarySampler(
        _space(),
        total_samples=2,
        initial_samples=0,
        opposite_neighbors=1,
    )
    observations = [
        (Sample(params={"agent_speed": 0.0, "cut_in_distance": 0.0}), "success"),
        (Sample(params={"agent_speed": 2.0, "cut_in_distance": 0.0}), "fail"),
        (Sample(params={"agent_speed": 8.0, "cut_in_distance": 20.0}), "success"),
        (Sample(params={"agent_speed": 10.0, "cut_in_distance": 20.0}), "fail"),
    ]
    for sample, outcome in observations:
        sampler.update(
            sample,
            SampleResult(params=sample.params, status="finished", test_outcome=outcome),
        )
    safe = [record for record in sampler.history if record.label == FeedbackLabel.SAFE]
    unsafe = [record for record in sampler.history if record.label == FeedbackLabel.UNSAFE]

    pairs = sampler._opposite_label_pairs(safe, unsafe)

    assert len(pairs) == 2


def test_random_sampler_is_available_from_registry() -> None:
    sampler = create_sampler(
        {"name": "random", "n_samples": 3, "seed": 4},
        _space(),
    )

    assert isinstance(sampler, RandomSampler)
    assert [sampler.next() for _ in range(3)]
    assert sampler.next() is None
