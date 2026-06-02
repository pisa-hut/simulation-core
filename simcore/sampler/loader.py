from __future__ import annotations

import importlib
import inspect
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from simcore.sampler.base import Sampler, TestResult
from simcore.sampler.parsers.explicit_yaml import parse_explicit_sample_file
from simcore.sampler.parsers.range_yaml import parse_parameter_range_file
from simcore.sampler.parsers.xosc import parse_parameter_value_distribution
from simcore.sampler.space import ParameterSpace
from simcore.utils.util import get_cfg

BUILTIN_SAMPLERS = {
    "explicit": "simcore.sampler.explicit_sampler:ExplicitSampler",
    "grid": "simcore.sampler.grid_search_sampler:GridSearchSampler",
    "grid_search": "simcore.sampler.grid_search_sampler:GridSearchSampler",
    "lhs": "simcore.sampler.lhs_sampler:LHSSampler",
    "native": "simcore.sampler.openscenario_native_sampler:OpenScenarioNativeSampler",
    "openscenario_native": "simcore.sampler.openscenario_native_sampler:OpenScenarioNativeSampler",
    "sobol": "simcore.sampler.sobol_sampler:SobolSampler",
}

SAMPLER_CONTROL_KEYS = {
    "_config_loaded",
    "config_path",
    "max_samples",
    "name",
    "source",
}
RUNTIME_SAMPLER_KEYS = {"name", "config_path"}


def load_sampler_spec(
    sampler_spec: dict[str, Any] | None,
    source_base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load sampler config into one effective sampler specification.

    Runner specs select only the sampler and config file:

        {"name": "lhs", "config_path": "./sampler/lhs.yaml"}

    The file referenced by ``config_path`` contains ``source``, ``max_samples``, and
    sampler-specific constructor kwargs. Relative ``source.path`` values are resolved
    against ``source_base_path`` when provided; otherwise they are resolved relative
    to the sampler config file for standalone sampler use.
    """
    sampler_spec = dict(sampler_spec or {})
    if sampler_spec.get("_config_loaded"):
        return sampler_spec

    if not sampler_spec:
        return {"_config_loaded": True}

    unknown_keys = set(sampler_spec) - RUNTIME_SAMPLER_KEYS
    if unknown_keys:
        keys = ", ".join(sorted(unknown_keys))
        allowed = ", ".join(sorted(RUNTIME_SAMPLER_KEYS))
        raise ValueError(f"sampler only supports key(s): {allowed}; got unsupported key(s): {keys}")

    name = sampler_spec.get("name")
    config_path = sampler_spec.get("config_path")
    if not name:
        raise ValueError("sampler.name is required when sampler is configured")
    if not config_path:
        raise ValueError("sampler.config_path is required when sampler is configured")
    if name not in BUILTIN_SAMPLERS:
        allowed = ", ".join(sorted(BUILTIN_SAMPLERS))
        raise ValueError(f"Unknown sampler name {name!r}. Built-in samplers: {allowed}")

    resolved_config_path = Path(config_path).expanduser()
    file_config = get_cfg(resolved_config_path) or {}
    if not isinstance(file_config, dict):
        raise ValueError(
            f"Sampler config file {resolved_config_path} must contain a mapping/object"
        )

    effective = _normalize_config_relative_paths(
        file_config,
        resolved_config_path,
        source_base_path=source_base_path,
    )
    if "name" in effective:
        raise ValueError("Sampler name must be defined in sampler.name, not config file")
    if "method" in effective:
        raise ValueError("Sampler config must not contain method; use sampler.name")

    effective["name"] = name
    effective["config_path"] = str(resolved_config_path)
    effective["_config_loaded"] = True
    return effective


def _normalize_config_relative_paths(
    config: dict[str, Any],
    config_path: Path,
    source_base_path: str | Path | None = None,
) -> dict[str, Any]:
    config = dict(config)
    base_path = (
        Path(source_base_path).expanduser() if source_base_path is not None else config_path.parent
    )
    source = config.get("source")
    if isinstance(source, str):
        config["source"] = str(_resolve_relative_path(source, base_path))
    elif isinstance(source, dict):
        source = dict(source)
        source_path = source.get("path")
        if source_path is not None:
            source["path"] = str(_resolve_relative_path(source_path, base_path))
        config["source"] = source
    return config


def _resolve_relative_path(path: str | Path, base_path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return base_path / path


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
) -> tuple[Path, str] | tuple[None, None]:
    sampler_spec = load_sampler_spec(sampler_spec)
    source = sampler_spec.get("source")
    if source is None:
        if sampler_spec.get("name"):
            raise ValueError("Sampler config must define source.path")
        return None, None
    if not isinstance(source, dict):
        raise ValueError("sampler config source must be a mapping/object")

    source_path = source.get("path")
    if source_path is not None:
        path = Path(source_path).expanduser()
    else:
        raise ValueError("Sampler config must define source.path")

    source_type = source.get("type") or infer_source_type(path)
    return path, source_type


def load_parameter_space(source_path: Path, source_type: str = "openscenario") -> ParameterSpace:
    if source_type in {"explicit", "sample_list", "samples"}:
        return parse_explicit_sample_file(source_path)
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
    sampler_spec = load_sampler_spec(sampler_spec)
    name = sampler_spec.get("name")
    if not name:
        raise ValueError("sampler.name is required")

    module_path = BUILTIN_SAMPLERS.get(name)
    if module_path is None:
        allowed = ", ".join(sorted(BUILTIN_SAMPLERS))
        raise ValueError(f"Unknown sampler name {name!r}. Built-in samplers: {allowed}")

    sampler_class = import_from_path(module_path)
    config = {key: value for key, value in sampler_spec.items() if key not in SAMPLER_CONTROL_KEYS}

    kwargs = _constructor_kwargs(
        sampler_class,
        {
            "parameter_space": parameter_space,
            "past_results": past_results,
            **config,
        },
    )
    return sampler_class(**kwargs)
