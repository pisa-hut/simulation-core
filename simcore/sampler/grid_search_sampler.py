from __future__ import annotations

from collections.abc import Iterable
from itertools import product
from logging import getLogger
from typing import Any

from .base import (
    ParameterSpace,
    ParameterSpec,
    Sample,
    Sampler,
    TestResult,
)

logger = getLogger(__name__)
GRID_PARAMETER_CONFIG_KEYS = {"values", "step", "n"}


class GridSearchSampler(Sampler):
    def __init__(
        self,
        parameter_space: ParameterSpace,
        past_results: Iterable[TestResult] | None = None,
        defaults: dict[str, Any] | None = None,
        parameters: dict[str, dict[str, Any]] | None = None,
        n: int | None = None,
        step: float | None = None,
        **_: Any,
    ):
        parameter_space = _discretize_parameter_space(
            parameter_space,
            defaults=defaults,
            parameters=parameters,
            n=n,
            step=step,
        )
        super().__init__(parameter_space)

        self._names = parameter_space.names
        self._grid = [spec.values for spec in parameter_space.parameters]
        self._combinations = product(*self._grid)
        self._emitted = 0

        logger.info(
            "GridSearchSampler initialized with %d parameters: %s",
            len(self._names),
            self._names,
        )

    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> Sample | None:
        for values in self._combinations:
            self._emitted += 1
            return Sample(params=dict(zip(self._names, values, strict=True)))

        return None

    def remaining_samples(self) -> int:
        total = self.total_samples()
        if total is None:
            return 0
        return max(total - self._emitted, 0)


def _discretize_parameter_space(
    parameter_space: ParameterSpace,
    defaults: dict[str, Any] | None = None,
    parameters: dict[str, dict[str, Any]] | None = None,
    n: int | None = None,
    step: float | None = None,
) -> ParameterSpace:
    defaults = defaults or {}
    parameters = parameters or {}
    parameter_names = set(parameter_space.names)
    unknown_parameters = set(parameters) - parameter_names
    if unknown_parameters:
        names = ", ".join(sorted(unknown_parameters))
        raise ValueError(f"Grid sampler config references unknown parameter(s): {names}")

    for parameter_name, config in parameters.items():
        _validate_parameter_config(parameter_name, config)

    global_n = n if n is not None else defaults.get("n")
    global_step = step if step is not None else defaults.get("step")

    specs = []
    for spec in parameter_space.parameters:
        config = parameters.get(spec.name, {})
        if "values" in config:
            grid_values = tuple(spec.cast_value(value) for value in config["values"])
            grid_config = {"values": config["values"]}
        elif "step" in config:
            grid_values = spec.grid_values(step=config["step"])
            grid_config = {"step": config["step"]}
        elif "n" in config:
            grid_values = spec.grid_values(n=config["n"])
            grid_config = {"n": config["n"]}
        elif global_step is not None:
            grid_values = spec.grid_values(step=global_step)
            grid_config = {"step": global_step}
        else:
            grid_count = global_n if global_n is not None else 2
            grid_values = spec.grid_values(n=grid_count)
            grid_config = {"n": grid_count}

        specs.append(
            ParameterSpec(
                name=spec.name,
                values=grid_values,
                metadata={**spec.metadata, "grid": grid_config},
                param_type=spec.param_type,
            )
        )

    return ParameterSpace.from_specs(specs)


def _validate_parameter_config(parameter_name: str, config: dict[str, Any]) -> None:
    unknown_keys = set(config) - GRID_PARAMETER_CONFIG_KEYS
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        allowed = ", ".join(sorted(GRID_PARAMETER_CONFIG_KEYS))
        raise ValueError(
            f"Grid sampler config for {parameter_name!r} contains unknown key(s): {keys}. "
            f"Allowed keys: {allowed}"
        )

    configured_methods = set(config) & GRID_PARAMETER_CONFIG_KEYS
    if len(configured_methods) > 1:
        methods = ", ".join(sorted(configured_methods))
        raise ValueError(
            f"Grid sampler config for {parameter_name!r} must use exactly one of "
            f"n, step, or values; got: {methods}"
        )
