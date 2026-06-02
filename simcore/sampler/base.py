from collections.abc import Iterable

from simcore.sampler.space import (
    ParamDict,
    ParameterSpace,
    ParameterSpec,
    Sample,
    SampleResult,
    TestResult,
)


class Sampler:
    def __init__(self, parameter_space: ParameterSpace):
        self.parameter_space = parameter_space
        self.specs = list(parameter_space.parameters)

    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> Sample | None:
        raise NotImplementedError

    def total_samples(self) -> int | None:
        return self.parameter_space.total_combinations()

    def remaining_samples(self) -> int | None:
        return None


__all__ = [
    "ParamDict",
    "ParameterSpace",
    "ParameterSpec",
    "Sample",
    "SampleResult",
    "Sampler",
    "TestResult",
]
