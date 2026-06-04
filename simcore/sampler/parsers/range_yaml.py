from __future__ import annotations

from pathlib import Path
from typing import Any

from simcore.sampler.space import OUTPUT_PARAMETERS_METADATA_KEY, ParameterSpace, ParameterSpec
from simcore.utils.util import get_cfg


def parse_parameter_range_dict(data: dict[str, Any]) -> ParameterSpace:
    raw_parameters = data.get("parameters")
    if not isinstance(raw_parameters, list):
        raise ValueError("Parameter range config must contain a 'parameters' list")

    specs: list[ParameterSpec] = []
    for raw_parameter in raw_parameters:
        if not isinstance(raw_parameter, dict):
            raise ValueError("Each parameter entry must be a mapping")

        name = raw_parameter.get("name")
        param_type = raw_parameter.get("type", "double")
        values = raw_parameter.get("values")
        bounds = raw_parameter.get("range", raw_parameter.get("bounds"))

        if values is not None and bounds is not None:
            raise ValueError(f"Parameter {name!r} cannot define both values and range")
        if values is None and bounds is None:
            raise ValueError(f"Parameter {name!r} must define values or range")
        if values is not None and not isinstance(values, list):
            raise ValueError(f"Parameter {name!r} values must be a list")
        if bounds is not None and (not isinstance(bounds, list) or len(bounds) != 2):
            raise ValueError(f"Parameter {name!r} range must be a two-element list")

        specs.append(
            ParameterSpec(
                name=name,
                values=tuple(values or ()),
                bounds=tuple(bounds) if bounds is not None else None,
                param_type=param_type,
                metadata={"source": "param_range"},
            )
        )

    metadata = {}
    raw_outputs = _raw_output_parameters(data)
    if raw_outputs is not None:
        metadata[OUTPUT_PARAMETERS_METADATA_KEY] = raw_outputs

    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate parameter names in parameter space: {names}")
    return ParameterSpace(parameters=tuple(specs), metadata=metadata)


def _raw_output_parameters(data: dict[str, Any]) -> Any:
    configured_keys = [
        key for key in ("outputs", "output_parameters", "sim_parameters") if key in data
    ]
    if len(configured_keys) > 1:
        keys = ", ".join(configured_keys)
        raise ValueError(
            f"Parameter range config must use only one output mapping key; got: {keys}"
        )
    if not configured_keys:
        return None
    return data[configured_keys[0]]


def parse_parameter_range_file(path: Path) -> ParameterSpace:
    data = get_cfg(path)
    return parse_parameter_range_dict(data or {})
