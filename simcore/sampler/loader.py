from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simcore.sampler.base import Sampler, TestResult
from simcore.sampler.parsers.range_yaml import parse_parameter_range_file
from simcore.sampler.parsers.xosc import parse_parameter_value_distribution
from simcore.sampler.space import ParameterSpace
from simcore.utils.util import get_cfg

BUILTIN_SAMPLERS = {
    "grid": "simcore.sampler.grid_search_sampler:GridSearchSampler",
    "grid_search": "simcore.sampler.grid_search_sampler:GridSearchSampler",
    "lhs": "simcore.sampler.lhs_sampler:LHSSampler",
    "native": "simcore.sampler.openscenario_native_sampler:OpenScenarioNativeSampler",
    "openscenario_native": "simcore.sampler.openscenario_native_sampler:OpenScenarioNativeSampler",
    "sobol": "simcore.sampler.sobol_sampler:SobolSampler",
}


def import_from_path(module_path: str) -> type[Sampler]:
    try:
        module_name, class_name = module_path.split(":", maxsplit=1)
    except ValueError as exc:
        raise ValueError(
            f"Invalid sampler module_path {module_path!r}; expected 'module:Class'"
        ) from exc

    module = importlib.import_module(module_name)
    sampler_class = getattr(module, class_name)
    if not issubclass(sampler_class, Sampler):
        raise TypeError(f"Sampler class {module_path!r} must inherit from simcore.sampler.Sampler")
    return sampler_class


def infer_source_type(path: Path) -> str:
    if path.suffix.lower() in {".yaml", ".yml", ".json"}:
        return "param_range"
    return "openscenario"


def resolve_sampler_source(
    sampler_spec: dict[str, Any],
    fallback_param_range_file: Path | None = None,
) -> tuple[Path, str] | tuple[None, None]:
    source = sampler_spec.get("source") or {}
    if isinstance(source, str):
        source = {"path": source}

    source_path = source.get("path")
    if source_path is not None:
        path = Path(source_path).expanduser()
    elif fallback_param_range_file is not None:
        path = fallback_param_range_file
    else:
        return None, None

    source_type = source.get("type") or infer_source_type(path)
    return path, source_type


def load_parameter_space(source_path: Path, source_type: str = "openscenario") -> ParameterSpace:
    if source_type in {"openscenario", "xosc"}:
        return parse_parameter_value_distribution(source_path.read_text(encoding="utf-8"))
    if source_type in {"param_range", "yaml", "domain"}:
        return parse_parameter_range_file(source_path)
    raise ValueError(f"Unsupported sampler source type: {source_type}")


def _constructor_kwargs(sampler_class: type[Sampler], kwargs: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(sampler_class)
    parameters = signature.parameters.values()
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs

    accepted = set(signature.parameters)
    return {key: value for key, value in kwargs.items() if key in accepted}


def create_sampler(
    sampler_spec: dict[str, Any],
    parameter_space: ParameterSpace,
    past_results: Iterable[TestResult] | None = None,
) -> Sampler:
    name = sampler_spec.get("method") or sampler_spec.get("name") or "native"
    module_path = sampler_spec.get("module_path") or BUILTIN_SAMPLERS.get(name)
    if module_path is None:
        raise ValueError(f"Unknown sampler {name!r}; provide sampler.module_path")

    sampler_class = import_from_path(module_path)
    config_path = sampler_spec.get("config_path")
    if config_path is not None:
        config_path = Path(config_path).expanduser()
        config = get_cfg(config_path) or {}
    else:
        config = {}
    config.update(sampler_spec.get("config", {}))

    kwargs = _constructor_kwargs(
        sampler_class,
        {
            "parameter_space": parameter_space,
            "past_results": past_results,
            **config,
        },
    )
    return sampler_class(**kwargs)
