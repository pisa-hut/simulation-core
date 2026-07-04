from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import reduce
from operator import mul
from typing import Any

ParamDict = dict[str, Any]
TestResult = dict[str, Any]
OUTPUT_PARAMETERS_METADATA_KEY = "output_parameters"
SIM_PARAMS_METADATA_KEY = "sim_params"


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    values: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    param_type: str = "double"
    bounds: tuple[Any, Any] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ParameterSpec.name must not be empty")
        object.__setattr__(self, "param_type", self.param_type.lower())
        object.__setattr__(self, "values", tuple(self.values))
        if self.bounds is not None:
            object.__setattr__(self, "bounds", tuple(self.bounds))
        if not self.values and self.bounds is None:
            raise ValueError(
                f"ParameterSpec {self.name!r} must contain discrete values or range bounds"
            )

    @property
    def is_discrete(self) -> bool:
        return bool(self.values)

    @property
    def is_continuous(self) -> bool:
        return self.bounds is not None and self.param_type in {"double", "float", "int", "integer"}

    def cast_value(self, value: Any) -> Any:
        if self.param_type in {"double", "float"}:
            return float(value)
        if self.param_type in {"int", "integer"}:
            return int(round(float(value)))
        if self.param_type in {"bool", "boolean"}:
            if isinstance(value, str):
                return value.lower() in {"1", "true", "yes", "on"}
            return bool(value)
        return value

    def value_from_unit(self, unit: float) -> Any:
        unit = min(max(unit, 0.0), 1.0)
        if self.values:
            index = min(int(unit * len(self.values)), len(self.values) - 1)
            return self.values[index]
        if self.bounds is None:
            raise ValueError(f"ParameterSpec {self.name!r} cannot map unit value without bounds")

        lower, upper = self.bounds
        value = float(lower) + unit * (float(upper) - float(lower))
        return self.cast_value(value)

    def grid_values(self, n: int | None = None, step: float | None = None) -> tuple[Any, ...]:
        if self.values:
            return self.values
        if self.bounds is None:
            raise ValueError(
                f"ParameterSpec {self.name!r} cannot produce grid values without bounds"
            )
        lower, upper = float(self.bounds[0]), float(self.bounds[1])
        if step is not None:
            return tuple(
                self.cast_value(value) for value in numeric_range_inclusive(lower, upper, step)
            )

        count = n or 2
        if count <= 0:
            raise ValueError(f"Grid count for parameter {self.name!r} must be positive")
        if count == 1:
            return (self.cast_value(lower),)
        width = (upper - lower) / (count - 1)
        return tuple(self.cast_value(lower + width * index) for index in range(count))


@dataclass(frozen=True)
class ParameterSpace:
    parameters: tuple[ParameterSpec, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_specs(cls, specs: list[ParameterSpec] | tuple[ParameterSpec, ...]) -> ParameterSpace:
        names = [spec.name for spec in specs]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate parameter names in parameter space: {names}")
        return cls(parameters=tuple(specs))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.parameters)

    def total_combinations(self) -> int | None:
        if any(not spec.values for spec in self.parameters):
            return None
        if not self.parameters:
            return 1
        return reduce(mul, (len(spec.values) for spec in self.parameters), 1)


@dataclass(frozen=True)
class Sample:
    params: ParamDict
    id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def sim_params(self) -> ParamDict:
        params = self.metadata.get(SIM_PARAMS_METADATA_KEY)
        if isinstance(params, dict):
            return dict(params)
        return dict(self.params)


@dataclass(frozen=True)
class SampleResult:
    params: ParamDict
    status: str | None = None
    test_outcome: str | None = None
    stop_condition: str | None = None
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def numeric_range_inclusive(
    lower: float,
    upper: float,
    step: float,
    tol: float = 1e-9,
) -> tuple[float, ...]:
    if step == 0:
        raise ValueError("step must not be zero")
    if (step > 0 and upper < lower) or (step < 0 and upper > lower):
        raise ValueError(f"Invalid step {step} for range [{lower}, {upper}]")

    n_steps = int(math.floor((upper - lower) / step + tol))
    values: list[float] = []
    for i in range(n_steps + 1):
        value = lower + i * step
        if (step > 0 and value > upper + tol) or (step < 0 and value < upper - tol):
            break
        values.append(value)

    return tuple(values)
