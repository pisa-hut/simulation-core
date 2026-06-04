from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simcore.metrics.expressions import evaluate_numeric_expression
from simcore.sampler.space import SIM_PARAMS_METADATA_KEY, Sample


@dataclass(frozen=True)
class OutputParameterSpec:
    name: str
    expression: str
    param_type: str = "double"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Derived parameter name must be a non-empty string")
        if not isinstance(self.expression, str) or not self.expression.strip():
            raise ValueError(f"Derived parameter {self.name!r} requires a non-empty expression")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "expression", self.expression.strip())
        object.__setattr__(self, "param_type", self.param_type.lower())


def parse_output_parameters(raw: Any) -> tuple[OutputParameterSpec, ...]:
    if raw is None:
        return ()
    if isinstance(raw, dict):
        specs = [_parse_mapping_entry(name, config) for name, config in raw.items()]
    elif isinstance(raw, list):
        specs = [_parse_list_entry(entry, index) for index, entry in enumerate(raw, start=1)]
    else:
        raise ValueError("output parameters must be a mapping or list")

    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate output parameter names: {names}")
    return tuple(specs)


def apply_output_parameters(
    sample: Sample,
    specs: tuple[OutputParameterSpec, ...],
) -> Sample:
    if not specs:
        return sample

    sample_params = dict(sample.params)
    expression_context = dict(sample.params)
    sim_params = {}
    for spec in specs:
        raw_value = evaluate_numeric_expression(spec.expression, expression_context)
        value = _cast_value(raw_value, spec.param_type, spec.name)
        sim_params[spec.name] = value
        expression_context[spec.name] = value

    metadata = {
        **sample.metadata,
        SIM_PARAMS_METADATA_KEY: sim_params,
        "output_parameters": tuple(spec.name for spec in specs),
    }
    return Sample(id=sample.id, params=sample_params, metadata=metadata)


def _parse_mapping_entry(name: Any, config: Any) -> OutputParameterSpec:
    if isinstance(config, str):
        return OutputParameterSpec(name=str(name), expression=config)
    if isinstance(config, dict):
        expression = config.get("expression", config.get("expr"))
        param_type = config.get("type", "double")
        return OutputParameterSpec(
            name=str(name),
            expression=expression,
            param_type=str(param_type),
        )
    raise ValueError(f"Derived parameter {name!r} must be an expression string or mapping/object")


def _parse_list_entry(entry: Any, index: int) -> OutputParameterSpec:
    if not isinstance(entry, dict):
        raise ValueError(f"Derived parameter entry #{index} must be a mapping/object")
    name = entry.get("name")
    expression = entry.get("expression", entry.get("expr"))
    param_type = entry.get("type", "double")
    return OutputParameterSpec(
        name=str(name) if name is not None else "",
        expression=expression,
        param_type=str(param_type),
    )


def _cast_value(value: float | bool, param_type: str, name: str) -> Any:
    if isinstance(value, bool):
        if param_type in {"bool", "boolean"}:
            return value
        raise ValueError(f"Derived parameter {name!r} expression evaluated to boolean")
    if param_type in {"double", "float"}:
        return float(value)
    if param_type in {"int", "integer"}:
        return int(round(float(value)))
    if param_type in {"bool", "boolean"}:
        return bool(value)
    if param_type in {"str", "string"}:
        return str(value)
    raise ValueError(f"Unsupported derived parameter type for {name!r}: {param_type}")
