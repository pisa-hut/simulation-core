from __future__ import annotations

from pathlib import Path

import pytest

from simcore.sampler import (
    ExplicitSampler,
    LHSSampler,
    OpenScenarioNativeSampler,
    ParameterSpace,
    ParameterSpec,
    Sample,
    SobolSampler,
    create_sampler,
    load_parameter_space,
)
from simcore.sampler.grid_search_sampler import GridSearchSampler
from simcore.sampler.loader import import_from_path, load_sampler_spec, resolve_sampler_source
from simcore.sampler.parsers.range_yaml import parse_parameter_range_file

PVD_XML = """\
<OpenSCENARIO>
  <ParameterValueDistribution>
    <Deterministic>
      <DeterministicSingleParameterDistribution parameterName="speed">
        <DistributionRange stepWidth="5">
          <Range lowerLimit="10" upperLimit="20" />
        </DistributionRange>
      </DeterministicSingleParameterDistribution>
      <DeterministicSingleParameterDistribution parameterName="offset">
        <DistributionRange stepWidth="1">
          <Range lowerLimit="-1" upperLimit="0" />
        </DistributionRange>
      </DeterministicSingleParameterDistribution>
    </Deterministic>
  </ParameterValueDistribution>
</OpenSCENARIO>
"""


def _effective_sampler_spec(name: str, **config):
    return {"name": name, **config}


def _params(sample: Sample | None):
    assert sample is not None
    return sample.params


def test_load_parameter_space_from_xosc(tmp_path: Path) -> None:
    param_file = tmp_path / "scenario_param.xosc"
    param_file.write_text(PVD_XML, encoding="utf-8")

    space = load_parameter_space(param_file)

    assert space.names == ("speed", "offset")
    assert space.total_combinations() == 6
    assert space.parameters[0].values == (10.0, 15.0, 20.0)


def test_grid_search_sampler_iterates_cartesian_product() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0)),
            ParameterSpec("offset", (-1.0, 0.0)),
        ]
    )
    sampler = GridSearchSampler(parameter_space=space)

    assert sampler.total_samples() == 4
    assert _params(sampler.next()) == {"speed": 10.0, "offset": -1.0}
    assert _params(sampler.next()) == {"speed": 10.0, "offset": 0.0}
    assert _params(sampler.next()) == {"speed": 20.0, "offset": -1.0}
    assert _params(sampler.next()) == {"speed": 20.0, "offset": 0.0}
    assert sampler.next() is None


def test_grid_search_sampler_ignores_past_results_for_now() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0)),
            ParameterSpec("offset", (-1.0, 0.0)),
        ]
    )
    sampler = GridSearchSampler(
        parameter_space=space,
        past_results=[{"params": {"speed": "10.0", "offset": "-1.0"}}],
    )

    assert _params(sampler.next()) == {"speed": 10.0, "offset": -1.0}
    assert _params(sampler.next([{"speed": 20.0, "offset": -1.0}])) == {
        "speed": 10.0,
        "offset": 0.0,
    }


def test_create_sampler_uses_builtin_registry() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0,))])

    sampler = create_sampler(_effective_sampler_spec("grid"), space)

    assert isinstance(sampler, GridSearchSampler)
    assert _params(sampler.next()) == {"speed": 10.0}


def test_create_sampler_supports_lhs_registry() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0, 30.0)),
            ParameterSpec("offset", (-1.0, 0.0, 1.0)),
        ]
    )

    sampler = create_sampler(_effective_sampler_spec("lhs", n_samples=4, seed=7), space)

    assert isinstance(sampler, LHSSampler)
    assert sampler.total_samples() == 4
    assert len([sampler.next() for _ in range(4)]) == 4
    assert sampler.next() is None


def test_lhs_sampler_maps_continuous_domain_values() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(10.0, 30.0), param_type="double"),
            ParameterSpec("count", bounds=(1, 5), param_type="int"),
        ]
    )

    sampler = create_sampler(_effective_sampler_spec("lhs", n_samples=5, seed=7), space)
    samples = [_params(sampler.next()) for _ in range(5)]

    assert all(10.0 <= sample["speed"] <= 30.0 for sample in samples)
    assert all(isinstance(sample["count"], int) for sample in samples)


def test_create_sampler_supports_sobol_registry() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0, 30.0, 40.0)),
            ParameterSpec("offset", (-1.0, 0.0, 1.0, 2.0)),
        ]
    )

    sampler = create_sampler(_effective_sampler_spec("sobol", n_samples=3), space)

    assert isinstance(sampler, SobolSampler)
    assert sampler.total_samples() == 3
    assert _params(sampler.next()) == {"speed": 40.0, "offset": 0.0}


def test_sobol_sampler_maps_continuous_domain_values() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(10.0, 30.0))])

    sampler = create_sampler(_effective_sampler_spec("sobol", n_samples=3), space)
    samples = [_params(sampler.next()) for _ in range(3)]

    assert samples == [{"speed": 25.0}, {"speed": 15.0}, {"speed": 17.5}]


def test_grid_sampler_discretizes_domain_with_config() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(10.0, 30.0)),
            ParameterSpec("offset", bounds=(-1.0, 1.0)),
        ]
    )

    sampler = create_sampler(
        _effective_sampler_spec(
            "grid",
            defaults={"n": 3},
            parameters={"offset": {"step": 1.0}},
        ),
        space,
    )

    assert sampler.total_samples() == 9
    assert _params(sampler.next()) == {"speed": 10.0, "offset": -1.0}
    assert _params(sampler.next()) == {"speed": 10.0, "offset": 0.0}


def test_grid_sampler_parameter_config_overrides_global_config() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(0.0, 20.0)),
            ParameterSpec("duration", bounds=(0.0, 1.0)),
        ]
    )

    sampler = create_sampler(
        _effective_sampler_spec(
            "grid",
            step=10,
            parameters={
                "duration": {
                    "n": 3,
                }
            },
        ),
        space,
    )

    assert sampler.total_samples() == 9
    assert _params(sampler.next()) == {"speed": 0.0, "duration": 0.0}
    assert _params(sampler.next()) == {"speed": 0.0, "duration": 0.5}
    assert _params(sampler.next()) == {"speed": 0.0, "duration": 1.0}


def test_grid_sampler_rejects_unknown_parameter_config() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="unknown parameter"):
        create_sampler(
            _effective_sampler_spec(
                "grid",
                parameters={
                    "speeed": {
                        "n": 3,
                    }
                },
            ),
            space,
        )


def test_grid_sampler_rejects_unknown_parameter_config_key() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="unknown key"):
        create_sampler(
            _effective_sampler_spec(
                "grid",
                parameters={
                    "speed": {
                        "value": [0.0, 10.0],
                    }
                },
            ),
            space,
        )


def test_grid_sampler_rejects_multiple_parameter_discretization_methods() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="exactly one"):
        create_sampler(
            _effective_sampler_spec(
                "grid",
                parameters={
                    "speed": {
                        "n": 3,
                        "step": 10,
                    }
                },
            ),
            space,
        )


def test_native_sampler_uses_openscenario_parameter_values() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0, 20.0))])

    sampler = create_sampler(_effective_sampler_spec("native"), space)

    assert isinstance(sampler, OpenScenarioNativeSampler)
    assert _params(sampler.next()) == {"speed": 10.0}


def test_parse_parameter_range_yaml(tmp_path: Path) -> None:
    range_file = tmp_path / "params.yaml"
    range_file.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 30.0]
  - name: behavior
    type: categorical
    values: [cutin, brake]
""",
        encoding="utf-8",
    )

    space = parse_parameter_range_file(range_file)

    assert space.total_combinations() is None
    assert space.parameters[0].bounds == (10.0, 30.0)
    assert space.parameters[1].values == ("cutin", "brake")


def test_load_parameter_space_supports_source_type(tmp_path: Path) -> None:
    range_file = tmp_path / "params.yaml"
    range_file.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 30.0]
""",
        encoding="utf-8",
    )

    space = load_parameter_space(range_file, "param_range")

    assert space.names == ("speed",)
    assert space.total_combinations() is None


def test_load_parameter_space_supports_explicit_samples(tmp_path: Path) -> None:
    samples_path = tmp_path / "samples.yaml"
    samples_path.write_text(
        """
samples:
  - id: case_a
    params:
      speed: 10
      behavior: cutin
  - id: case_b
    params:
      offset: -1.5
""",
        encoding="utf-8",
    )

    space = load_parameter_space(samples_path, "explicit")
    sampler = create_sampler(_effective_sampler_spec("explicit"), space)

    assert isinstance(sampler, ExplicitSampler)
    assert sampler.total_samples() == 2
    assert sampler.next() == Sample(
        id="case_a",
        params={"speed": 10, "behavior": "cutin"},
        metadata={"source": "explicit", "index": 1},
    )
    assert sampler.next() == Sample(
        id="case_b",
        params={"offset": -1.5},
        metadata={"source": "explicit", "index": 2},
    )
    assert sampler.next() is None


def test_explicit_samples_reject_duplicate_ids(tmp_path: Path) -> None:
    samples_path = tmp_path / "samples.yaml"
    samples_path.write_text(
        """
samples:
  - id: duplicate
    params:
      speed: 10
  - id: duplicate
    params:
      speed: 20
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate explicit sample id"):
        load_parameter_space(samples_path, "explicit")


def test_create_sampler_rejects_unloaded_runtime_spec(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("n_samples: 2\nseed: 1\n", encoding="utf-8")
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0, 20.0, 30.0))])

    with pytest.raises(ValueError, match="load_sampler_spec"):
        create_sampler({"name": "lhs", "config_path": str(config_path)}, space)


def test_resolve_sampler_source_rejects_unloaded_runtime_spec(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text(
        """
source:
  type: param_range
  path: params.yaml
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="load_sampler_spec"):
        resolve_sampler_source({"name": "lhs", "config_path": str(config_path)})


def test_resolve_sampler_source_rejects_unloaded_native_runtime_spec(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("max_samples: null\n", encoding="utf-8")

    with pytest.raises(ValueError, match="load_sampler_spec"):
        resolve_sampler_source({"name": "native", "config_path": str(config_path)})


def test_sampler_config_path_can_hold_full_sampler_spec(tmp_path: Path) -> None:
    params_path = tmp_path / "params.yaml"
    params_path.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 20.0]
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text(
        """
source:
  type: param_range
  path: params.yaml
n_samples: 3
seed: 11
max_samples: 2
""",
        encoding="utf-8",
    )
    runtime_spec = {"name": "lhs", "config_path": str(config_path)}

    effective_spec = load_sampler_spec(runtime_spec)
    source_path, source_type = resolve_sampler_source(effective_spec)
    space = load_parameter_space(source_path, source_type)
    sampler = create_sampler(effective_spec, space)

    assert source_path == params_path
    assert source_type == "param_range"
    assert effective_spec["max_samples"] == 2
    assert isinstance(sampler, LHSSampler)
    assert sampler.total_samples() == 3


def test_sampler_source_path_resolves_relative_to_scenario_folder(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    scenario_dir.mkdir()
    config_dir.mkdir()
    params_path = scenario_dir / "params.yaml"
    params_path.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 20.0]
""",
        encoding="utf-8",
    )
    config_path = config_dir / "sampler.yaml"
    config_path.write_text(
        """
source:
  type: param_range
  path: params.yaml
n_samples: 3
""",
        encoding="utf-8",
    )

    effective_spec = load_sampler_spec(
        {"name": "lhs", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )
    source_path, source_type = resolve_sampler_source(effective_spec)

    assert source_path == params_path
    assert source_type == "param_range"


def test_sampler_source_absolute_path_is_preserved(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    absolute_source_dir = tmp_path / "absolute"
    scenario_dir.mkdir()
    config_dir.mkdir()
    absolute_source_dir.mkdir()
    params_path = absolute_source_dir / "params.yaml"
    params_path.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 20.0]
""",
        encoding="utf-8",
    )
    config_path = config_dir / "sampler.yaml"
    config_path.write_text(
        f"""
source:
  type: param_range
  path: {params_path}
n_samples: 3
""",
        encoding="utf-8",
    )

    effective_spec = load_sampler_spec(
        {"name": "lhs", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )
    source_path, _ = resolve_sampler_source(effective_spec)

    assert source_path == params_path


def test_sampler_config_rejects_source_string(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("source: params.yaml\nn_samples: 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source must be a mapping"):
        load_sampler_spec({"name": "lhs", "config_path": str(config_path)})


def test_native_sampler_defaults_to_param_xosc_when_present(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    scenario_dir.mkdir()
    config_dir.mkdir()
    param_path = scenario_dir / "param.xosc"
    param_path.write_text(PVD_XML, encoding="utf-8")
    config_path = config_dir / "native.yaml"
    config_path.write_text("max_samples: null\n", encoding="utf-8")

    effective_spec = load_sampler_spec(
        {"name": "native", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )
    source_path, source_type = resolve_sampler_source(effective_spec)

    assert source_path == param_path
    assert source_type == "openscenario"


def test_native_sampler_missing_default_param_xosc_runs_as_concrete(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    scenario_dir.mkdir()
    config_dir.mkdir()
    config_path = config_dir / "native.yaml"
    config_path.write_text("max_samples: null\n", encoding="utf-8")

    effective_spec = load_sampler_spec(
        {"name": "native", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )

    assert resolve_sampler_source(effective_spec) == (None, None)


def test_native_sampler_missing_configured_source_runs_as_concrete(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    scenario_dir.mkdir()
    config_dir.mkdir()
    config_path = config_dir / "native.yaml"
    config_path.write_text(
        """
source:
  type: openscenario
  path: param.xosc
""",
        encoding="utf-8",
    )

    effective_spec = load_sampler_spec(
        {"name": "native", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )

    assert resolve_sampler_source(effective_spec) == (None, None)


def test_non_native_sampler_missing_source_file_raises(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    config_dir = tmp_path / "config"
    scenario_dir.mkdir()
    config_dir.mkdir()
    config_path = config_dir / "lhs.yaml"
    config_path.write_text(
        """
source:
  type: param_range
  path: range.yaml
n_samples: 2
""",
        encoding="utf-8",
    )

    effective_spec = load_sampler_spec(
        {"name": "lhs", "config_path": str(config_path)},
        source_base_path=scenario_dir,
    )

    with pytest.raises(FileNotFoundError, match="Sampler source file not found"):
        resolve_sampler_source(effective_spec)


def test_runtime_sampler_spec_rejects_inline_config(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("n_samples: 2\nseed: 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported key"):
        load_sampler_spec(
            {
                "name": "lhs",
                "config_path": str(config_path),
                "config": {"n_samples": 4},
            }
        )


def test_runtime_sampler_spec_rejects_method_alias(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("n_samples: 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported key"):
        load_sampler_spec({"method": "lhs", "config_path": str(config_path)})


def test_runtime_sampler_spec_requires_config_path() -> None:
    with pytest.raises(ValueError, match="config_path"):
        load_sampler_spec({"name": "lhs"})


def test_sampler_config_rejects_sampler_name_in_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("name: sobol\nn_samples: 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sampler.name"):
        load_sampler_spec({"name": "lhs", "config_path": str(config_path)})


def test_sampler_config_rejects_method_in_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("method: sobol\nn_samples: 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must not contain method"):
        load_sampler_spec({"name": "lhs", "config_path": str(config_path)})


def test_sampler_config_rejects_module_path_in_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text(
        "module_path: tests.test_sampler:DummyExternalSampler\nn_samples: 2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not contain module_path"):
        load_sampler_spec({"name": "lhs", "config_path": str(config_path)})


def test_import_from_path_validates_sampler_api() -> None:
    with pytest.raises(TypeError):
        import_from_path("pathlib:Path")
