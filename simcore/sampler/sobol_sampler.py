from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from simcore.sampler.base import ParamDict, ParameterSpace, Sampler, TestResult
from simcore.sampler.sequences import default_sample_count, sobol_units, units_to_params


class SobolSampler(Sampler):
    def __init__(
        self,
        parameter_space: ParameterSpace,
        past_results: Iterable[TestResult] | None = None,
        n_samples: int | None = None,
        skip: int = 1,
        **_: Any,
    ):
        super().__init__(parameter_space)
        self._n_samples = (
            n_samples if n_samples is not None else default_sample_count(parameter_space)
        )
        self._samples = [
            units_to_params(parameter_space, units)
            for units in sobol_units(self._n_samples, len(parameter_space.parameters), skip=skip)
        ]
        self._index = 0

    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> ParamDict | None:
        if self._index < self._n_samples:
            sample = self._samples[self._index]
            self._index += 1
            return sample

        return None

    def total_samples(self) -> int:
        return self._n_samples

    def remaining_samples(self) -> int:
        return max(self._n_samples - self._index, 0)
