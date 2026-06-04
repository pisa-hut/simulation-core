from collections.abc import Iterable

from simcore.sampler.derived import (
    OutputParameterSpec,
    apply_output_parameters,
    parse_output_parameters,
)
from simcore.sampler.space import (
    OUTPUT_PARAMETERS_METADATA_KEY,
    ParamDict,
    ParameterSpace,
    ParameterSpec,
    Sample,
    SampleResult,
    TestResult,
)


class Sampler:
    def __init__(
        self,
        parameter_space: ParameterSpace,
        output_parameters=None,
    ):
        self.parameter_space = parameter_space
        self.specs = list(parameter_space.parameters)
        raw_output_parameters = (
            output_parameters
            if output_parameters is not None
            else parameter_space.metadata.get(OUTPUT_PARAMETERS_METADATA_KEY)
        )
        self.output_parameters: tuple[OutputParameterSpec, ...] = parse_output_parameters(
            raw_output_parameters
        )

    def prepare_sample(self, sample: Sample) -> Sample:
        return apply_output_parameters(sample, self.output_parameters)

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
