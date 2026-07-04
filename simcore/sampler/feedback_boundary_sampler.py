from __future__ import annotations

import math
import operator
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from simcore.sampler.base import ParameterSpace, Sample, Sampler, SampleResult
from simcore.sampler.sequences import lhs_units, random_units, sobol_units, units_to_params

SUPPORTED_INITIAL_SAMPLERS = {"lhs", "random", "sobol"}
RULE_OPERATORS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


class FeedbackLabel(StrEnum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    INVALID = "INVALID"
    ERROR = "ERROR"


@dataclass(frozen=True)
class FeedbackRecord:
    sample: Sample
    result: SampleResult
    label: FeedbackLabel
    normalized_params: tuple[float | None, ...]


@dataclass(frozen=True)
class BoundaryCandidate:
    params: dict[str, Any]
    pair_distance: float


class FeedbackBoundarySampler(Sampler):
    def __init__(
        self,
        parameter_space: ParameterSpace,
        total_samples: int,
        initial_samples: int | None = None,
        initial_sampler: str = "sobol",
        min_ttc_threshold: float | None = None,
        unsafe_conditions: list[dict[str, Any]] | None = None,
        boundary_candidate_count: int = 32,
        opposite_neighbors: int = 3,
        candidates_per_pair: int = 2,
        uncertainty_weight: float = 0.35,
        novelty_weight: float = 0.25,
        coverage_weight: float = 0.4,
        perturbation_scale: float = 0.05,
        exploration_ratio: float = 0.2,
        random_seed: int | None = None,
        duplicate_tolerance: float = 1e-6,
        output_parameters: Any = None,
        **_: Any,
    ):
        super().__init__(parameter_space, output_parameters=output_parameters)
        effective_initial_samples = (
            min(8, int(total_samples)) if initial_samples is None else int(initial_samples)
        )
        self._validate_config(
            total_samples=total_samples,
            initial_samples=effective_initial_samples,
            initial_sampler=initial_sampler,
            boundary_candidate_count=boundary_candidate_count,
            opposite_neighbors=opposite_neighbors,
            candidates_per_pair=candidates_per_pair,
            uncertainty_weight=uncertainty_weight,
            novelty_weight=novelty_weight,
            coverage_weight=coverage_weight,
            perturbation_scale=perturbation_scale,
            exploration_ratio=exploration_ratio,
            duplicate_tolerance=duplicate_tolerance,
        )
        self._total_samples = int(total_samples)
        self._initial_samples = effective_initial_samples
        self._initial_sampler = initial_sampler.lower()
        self._min_ttc_threshold = (
            float(min_ttc_threshold) if min_ttc_threshold is not None else None
        )
        self._unsafe_conditions = self._parse_unsafe_conditions(unsafe_conditions or [])
        self._boundary_candidate_count = int(boundary_candidate_count)
        self._opposite_neighbors = int(opposite_neighbors)
        self._candidates_per_pair = int(candidates_per_pair)
        self._uncertainty_weight = float(uncertainty_weight)
        self._novelty_weight = float(novelty_weight)
        self._coverage_weight = float(coverage_weight)
        self._perturbation_scale = float(perturbation_scale)
        self._exploration_ratio = float(exploration_ratio)
        self._duplicate_tolerance = float(duplicate_tolerance)
        self._rng = random.Random(random_seed)
        self._numeric_bounds = tuple(self._numeric_bounds_for(spec) for spec in self.specs)
        if not any(
            bounds is not None and bounds[0] != bounds[1] for bounds in self._numeric_bounds
        ):
            raise ValueError(
                "FeedbackBoundarySampler requires at least one non-constant numeric parameter"
            )

        pool_size = max(self._total_samples * 8, self._initial_samples, 32)
        units = self._initial_units(pool_size, len(self.specs), random_seed)
        self._base_samples = [units_to_params(parameter_space, point) for point in units]
        self._base_index = 0
        self._emitted = 0
        self._issued: list[Sample] = []
        self._boundary_issued: list[Sample] = []
        self.history: list[FeedbackRecord] = []

    def next(self, past_results=None) -> Sample | None:
        if self._emitted >= self._total_samples:
            return None

        use_exploration = (
            self._emitted < self._initial_samples
            or not self._has_boundary_labels()
            or self._rng.random() < self._exploration_ratio
        )
        used_boundary = not use_exploration
        params = self._next_base_params() if use_exploration else self._boundary_params()
        if params is None:
            used_boundary = False
            params = self._next_base_params()
        if params is None:
            params = self._random_fallback_params()
        if params is None:
            return None

        sample = self.prepare_sample(Sample(params=params))
        self._issued.append(sample)
        if used_boundary:
            self._boundary_issued.append(sample)
        self._emitted += 1
        return sample

    def update(self, sample: Sample, result: SampleResult) -> None:
        self.history.append(
            FeedbackRecord(
                sample=sample,
                result=result,
                label=self.classify(result),
                normalized_params=self._normalize(sample.params),
            )
        )

    def classify(self, result: SampleResult) -> FeedbackLabel:
        status = str(result.status or "").strip().lower()
        outcome = str(result.test_outcome or "").strip().lower()
        if status in {"error", "failed", "abort", "aborted"} or not status:
            return FeedbackLabel.ERROR
        if outcome == "invalid" or status in {"invalid", "skip", "skipped"}:
            return FeedbackLabel.INVALID
        if outcome == "fail":
            return FeedbackLabel.UNSAFE
        if self._metric_is_true(result.metrics, ("collision", "collision_occurred")):
            return FeedbackLabel.UNSAFE

        min_ttc = self._metric_value(result.metrics, ("min_ttc", "min_ttc_s"))
        if (
            self._min_ttc_threshold is not None
            and min_ttc is not None
            and float(min_ttc) < self._min_ttc_threshold
        ):
            return FeedbackLabel.UNSAFE
        if any(self._rule_matches(rule, result.metrics) for rule in self._unsafe_conditions):
            return FeedbackLabel.UNSAFE
        if outcome == "success":
            return FeedbackLabel.SAFE

        configured_rules = self._min_ttc_threshold is not None or bool(self._unsafe_conditions)
        if status == "finished" and configured_rules:
            if self._min_ttc_threshold is not None and min_ttc is None:
                return FeedbackLabel.ERROR
            if any(
                self._metric_value(result.metrics, (rule["metric"].lower(),)) is None
                for rule in self._unsafe_conditions
            ):
                return FeedbackLabel.ERROR
            return FeedbackLabel.SAFE
        return FeedbackLabel.ERROR

    def total_samples(self) -> int:
        return self._total_samples

    def remaining_samples(self) -> int:
        return max(self._total_samples - self._emitted, 0)

    def _boundary_params(self) -> dict[str, Any] | None:
        safe = [record for record in self.history if record.label == FeedbackLabel.SAFE]
        unsafe = [record for record in self.history if record.label == FeedbackLabel.UNSAFE]
        pairs = self._opposite_label_pairs(safe, unsafe)
        candidates: list[BoundaryCandidate] = []
        for distance, safe_record, unsafe_record in pairs:
            midpoint = self._midpoint(safe_record.sample.params, unsafe_record.sample.params)
            if midpoint is None:
                continue
            pair_candidates = [midpoint]
            pair_candidates.extend(
                self._perturb(midpoint) for _ in range(self._candidates_per_pair - 1)
            )
            for params in pair_candidates:
                if self._is_duplicate(params) or self._contains_candidate(candidates, params):
                    continue
                candidates.append(BoundaryCandidate(params=params, pair_distance=distance))
                if len(candidates) >= self._boundary_candidate_count:
                    break
            if len(candidates) >= self._boundary_candidate_count:
                break

        if not candidates:
            return None
        return self._select_boundary_candidate(candidates).params

    def _opposite_label_pairs(
        self,
        safe: list[FeedbackRecord],
        unsafe: list[FeedbackRecord],
    ) -> list[tuple[float, FeedbackRecord, FeedbackRecord]]:
        pairs: dict[tuple[int, int], tuple[float, FeedbackRecord, FeedbackRecord]] = {}
        for safe_index, safe_record in enumerate(safe):
            neighbors = self._nearest_opposites(safe_record, unsafe)
            for distance, unsafe_index, unsafe_record in neighbors:
                pairs[(safe_index, unsafe_index)] = (distance, safe_record, unsafe_record)
        for unsafe_index, unsafe_record in enumerate(unsafe):
            neighbors = self._nearest_opposites(unsafe_record, safe)
            for distance, safe_index, safe_record in neighbors:
                pairs[(safe_index, unsafe_index)] = (distance, safe_record, unsafe_record)
        return sorted(pairs.values(), key=lambda item: item[0])

    def _nearest_opposites(
        self,
        record: FeedbackRecord,
        opposite_records: list[FeedbackRecord],
    ) -> list[tuple[float, int, FeedbackRecord]]:
        neighbors = []
        for index, opposite in enumerate(opposite_records):
            distance = self._distance(record, opposite)
            if distance is not None:
                neighbors.append((distance, index, opposite))
        neighbors.sort(key=lambda item: item[0])
        return neighbors[: self._opposite_neighbors]

    def _select_boundary_candidate(
        self,
        candidates: list[BoundaryCandidate],
    ) -> BoundaryCandidate:
        uncertainties = self._normalize_scores(
            [candidate.pair_distance for candidate in candidates]
        )
        novelties = self._normalize_scores(
            [
                self._nearest_sample_distance(candidate.params, self._issued)
                for candidate in candidates
            ]
        )
        coverages = self._normalize_scores(
            [
                self._nearest_sample_distance(candidate.params, self._boundary_issued)
                for candidate in candidates
            ]
        )
        scores = [
            self._uncertainty_weight * uncertainty
            + self._novelty_weight * novelty
            + self._coverage_weight * coverage
            for uncertainty, novelty, coverage in zip(
                uncertainties, novelties, coverages, strict=True
            )
        ]
        return candidates[max(range(len(candidates)), key=scores.__getitem__)]

    @staticmethod
    def _normalize_scores(values: list[float]) -> list[float]:
        lower = min(values)
        upper = max(values)
        if upper == lower:
            return [0.0] * len(values)
        return [(value - lower) / (upper - lower) for value in values]

    def _nearest_sample_distance(
        self,
        params: dict[str, Any],
        samples: list[Sample],
    ) -> float:
        if not samples:
            return 1.0
        normalized = self._normalize(params)
        distances = [
            self._point_distance(params, normalized, sample.params, self._normalize(sample.params))
            for sample in samples
        ]
        compatible = [distance for distance in distances if distance is not None]
        return min(compatible) if compatible else 1.0

    def _contains_candidate(
        self,
        candidates: list[BoundaryCandidate],
        params: dict[str, Any],
    ) -> bool:
        normalized = self._normalize(params)
        for candidate in candidates:
            distance = self._point_distance(
                params,
                normalized,
                candidate.params,
                self._normalize(candidate.params),
            )
            if distance is not None and distance <= self._duplicate_tolerance:
                return True
        return False

    def _next_base_params(self) -> dict[str, Any] | None:
        while self._base_index < len(self._base_samples):
            params = self._base_samples[self._base_index]
            self._base_index += 1
            if not self._is_duplicate(params):
                return params
        return None

    def _random_fallback_params(self) -> dict[str, Any] | None:
        for _ in range(max(100, self._boundary_candidate_count * 4)):
            params = units_to_params(
                self.parameter_space,
                [self._rng.random() for _ in self.specs],
            )
            if not self._is_duplicate(params):
                return params
        return None

    def _has_boundary_labels(self) -> bool:
        labels = {record.label for record in self.history}
        return FeedbackLabel.SAFE in labels and FeedbackLabel.UNSAFE in labels

    def _normalize(self, params: dict[str, Any]) -> tuple[float | None, ...]:
        normalized = []
        for spec, bounds in zip(self.specs, self._numeric_bounds, strict=True):
            if bounds is None:
                normalized.append(None)
                continue
            lower, upper = bounds
            if upper == lower:
                normalized.append(0.0)
                continue
            normalized.append((float(params[spec.name]) - lower) / (upper - lower))
        return tuple(normalized)

    def _distance(self, left: FeedbackRecord, right: FeedbackRecord) -> float | None:
        squared = 0.0
        used_dimension = False
        for index, spec in enumerate(self.specs):
            if self._numeric_bounds[index] is None:
                if left.sample.params[spec.name] != right.sample.params[spec.name]:
                    return None
                continue
            left_value = left.normalized_params[index]
            right_value = right.normalized_params[index]
            if left_value is None or right_value is None:
                continue
            squared += (left_value - right_value) ** 2
            used_dimension = True
        return math.sqrt(squared) if used_dimension else None

    def _midpoint(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
        params = {}
        for index, spec in enumerate(self.specs):
            if self._numeric_bounds[index] is None:
                if left[spec.name] != right[spec.name]:
                    return None
                params[spec.name] = left[spec.name]
            else:
                params[spec.name] = self._cast_candidate(
                    spec,
                    (float(left[spec.name]) + float(right[spec.name])) / 2.0,
                )
        return params

    def _perturb(self, params: dict[str, Any]) -> dict[str, Any]:
        candidate = dict(params)
        for spec, bounds in zip(self.specs, self._numeric_bounds, strict=True):
            if bounds is None:
                continue
            lower, upper = bounds
            width = upper - lower
            value = float(candidate[spec.name]) + self._rng.gauss(
                0.0, self._perturbation_scale * width
            )
            candidate[spec.name] = self._cast_candidate(spec, min(max(value, lower), upper))
        return candidate

    @staticmethod
    def _cast_candidate(spec, value: float) -> Any:
        if spec.values:
            return min(spec.values, key=lambda candidate: abs(float(candidate) - value))
        return spec.cast_value(value)

    def _is_duplicate(self, params: dict[str, Any]) -> bool:
        candidate = self._normalize(params)
        for sample in self._issued:
            if self._same_point(params, candidate, sample.params, self._normalize(sample.params)):
                return True
        return False

    def _same_point(self, left, left_norm, right, right_norm) -> bool:
        distance = self._point_distance(left, left_norm, right, right_norm)
        return distance is not None and distance <= self._duplicate_tolerance

    def _point_distance(self, left, left_norm, right, right_norm) -> float | None:
        squared = 0.0
        for index, spec in enumerate(self.specs):
            if self._numeric_bounds[index] is None:
                if left[spec.name] != right[spec.name]:
                    return None
                continue
            squared += (left_norm[index] - right_norm[index]) ** 2
        return math.sqrt(squared)

    def _initial_units(self, count: int, dimensions: int, seed: int | None):
        if self._initial_sampler == "lhs":
            return lhs_units(count, dimensions, seed)
        if self._initial_sampler == "random":
            return random_units(count, dimensions, seed)
        return sobol_units(count, dimensions, skip=1)

    @staticmethod
    def _numeric_bounds_for(spec) -> tuple[float, float] | None:
        if spec.bounds is not None and spec.param_type in {"double", "float", "int", "integer"}:
            return float(spec.bounds[0]), float(spec.bounds[1])
        if spec.values and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in spec.values
        ):
            return float(min(spec.values)), float(max(spec.values))
        return None

    @staticmethod
    def _metric_value(metrics: dict[str, Any], aliases: tuple[str, ...]) -> Any:
        for key, value in metrics.items():
            normalized = key.lower()
            if (
                (
                    normalized in aliases
                    or any(normalized.endswith(f".{alias}") for alias in aliases)
                )
                and value is not None
                and value != ""
            ):
                return value
        return None

    @classmethod
    def _metric_is_true(cls, metrics, aliases) -> bool:
        value = cls._metric_value(metrics, aliases)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @classmethod
    def _rule_matches(cls, rule, metrics) -> bool:
        value = cls._metric_value(metrics, (rule["metric"].lower(),))
        if value is None:
            return False
        try:
            return bool(RULE_OPERATORS[rule["operator"]](float(value), float(rule["value"])))
        except TypeError, ValueError:
            return False

    @staticmethod
    def _parse_unsafe_conditions(raw_conditions):
        parsed = []
        for condition in raw_conditions:
            if not isinstance(condition, dict):
                raise ValueError("unsafe_conditions entries must be mappings")
            metric = condition.get("metric")
            rule_operator = str(condition.get("operator", "")).lower()
            if not metric or rule_operator not in RULE_OPERATORS or "value" not in condition:
                raise ValueError(
                    "unsafe_conditions require metric, operator (eq/ne/lt/le/gt/ge), and value"
                )
            parsed.append(
                {"metric": str(metric), "operator": rule_operator, "value": condition["value"]}
            )
        return parsed

    @staticmethod
    def _validate_config(**config) -> None:
        if int(config["total_samples"]) <= 0:
            raise ValueError("total_samples must be positive")
        if not 0 <= int(config["initial_samples"]) <= int(config["total_samples"]):
            raise ValueError("initial_samples must be between 0 and total_samples")
        if str(config["initial_sampler"]).lower() not in SUPPORTED_INITIAL_SAMPLERS:
            raise ValueError("initial_sampler must be one of: lhs, random, sobol")
        if int(config["boundary_candidate_count"]) <= 0:
            raise ValueError("boundary_candidate_count must be positive")
        if int(config["opposite_neighbors"]) <= 0:
            raise ValueError("opposite_neighbors must be positive")
        if int(config["candidates_per_pair"]) <= 0:
            raise ValueError("candidates_per_pair must be positive")
        weights = (
            float(config["uncertainty_weight"]),
            float(config["novelty_weight"]),
            float(config["coverage_weight"]),
        )
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("boundary scoring weights must be non-negative with a positive sum")
        if float(config["perturbation_scale"]) < 0:
            raise ValueError("perturbation_scale must be non-negative")
        if not 0 <= float(config["exploration_ratio"]) <= 1:
            raise ValueError("exploration_ratio must be between 0 and 1")
        if float(config["duplicate_tolerance"]) < 0:
            raise ValueError("duplicate_tolerance must be non-negative")
