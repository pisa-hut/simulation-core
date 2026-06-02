from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from simcore.sampler.base import ParameterSpace, Sample, Sampler, TestResult
from simcore.sampler.sequences import default_sample_count, lhs_units, units_to_params


class LHSSampler(Sampler):
    def __init__(
        self,
        parameter_space: ParameterSpace,
        past_results: Iterable[TestResult] | None = None,
        n_samples: int | None = None,
        seed: int | None = None,
        **_: Any,
    ):
        super().__init__(parameter_space)
        self._n_samples = (
            n_samples if n_samples is not None else default_sample_count(parameter_space)
        )
        self._samples = [
            units_to_params(parameter_space, units)
            for units in lhs_units(self._n_samples, len(parameter_space.parameters), seed)
        ]
        self._index = 0

    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> Sample | None:
        if self._index < self._n_samples:
            params = self._samples[self._index]
            self._index += 1
            return Sample(params=params)

        return None

    def total_samples(self) -> int:
        return self._n_samples

    def remaining_samples(self) -> int:
        return max(self._n_samples - self._index, 0)
