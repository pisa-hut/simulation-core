from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from simcore.sampler.base import ParameterSpace, Sample, Sampler, TestResult
from simcore.sampler.parsers.explicit_yaml import EXPLICIT_SAMPLES_METADATA_KEY


class ExplicitSampler(Sampler):
    def __init__(
        self,
        parameter_space: ParameterSpace,
        past_results: Iterable[TestResult] | None = None,
        output_parameters: Any = None,
        **_: Any,
    ):
        super().__init__(parameter_space, output_parameters=output_parameters)
        samples = parameter_space.metadata.get(EXPLICIT_SAMPLES_METADATA_KEY)
        if not isinstance(samples, tuple) or not all(
            isinstance(sample, Sample) for sample in samples
        ):
            raise ValueError("ExplicitSampler requires a parameter source of type 'explicit'")

        self._samples = samples
        self._index = 0

    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> Sample | None:
        if self._index >= len(self._samples):
            return None

        sample = self._samples[self._index]
        self._index += 1
        return self.prepare_sample(sample)

    def total_samples(self) -> int:
        return len(self._samples)

    def remaining_samples(self) -> int:
        return max(len(self._samples) - self._index, 0)
