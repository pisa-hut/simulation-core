from __future__ import annotations

from pathlib import Path

import pytest

from simcore.sampler import (
    LHSSampler,
    OpenScenarioNativeSampler,
    ParameterSpace,
    ParameterSpec,
    SobolSampler,
    create_sampler,
    load_parameter_space,
)
from simcore.sampler.base import Sampler
from simcore.sampler.grid_search_sampler import GridSearchSampler
from simcore.sampler.loader import import_from_path
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
    assert sampler.next() == {"speed": 10.0, "offset": -1.0}
    assert sampler.next() == {"speed": 10.0, "offset": 0.0}
    assert sampler.next() == {"speed": 20.0, "offset": -1.0}
    assert sampler.next() == {"speed": 20.0, "offset": 0.0}
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

    assert sampler.next() == {"speed": 10.0, "offset": -1.0}
    assert sampler.next([{"speed": 20.0, "offset": -1.0}]) == {"speed": 10.0, "offset": 0.0}


def test_create_sampler_uses_builtin_registry() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0,))])

    sampler = create_sampler({"name": "grid"}, space)

    assert isinstance(sampler, GridSearchSampler)
    assert sampler.next() == {"speed": 10.0}


def test_create_sampler_supports_lhs_registry() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0, 30.0)),
            ParameterSpec("offset", (-1.0, 0.0, 1.0)),
        ]
    )

    sampler = create_sampler({"name": "lhs", "config": {"n_samples": 4, "seed": 7}}, space)

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

    sampler = create_sampler({"method": "lhs", "config": {"n_samples": 5, "seed": 7}}, space)
    samples = [sampler.next() for _ in range(5)]

    assert all(10.0 <= sample["speed"] <= 30.0 for sample in samples if sample is not None)
    assert all(isinstance(sample["count"], int) for sample in samples if sample is not None)


def test_create_sampler_supports_sobol_registry() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", (10.0, 20.0, 30.0, 40.0)),
            ParameterSpec("offset", (-1.0, 0.0, 1.0, 2.0)),
        ]
    )

    sampler = create_sampler({"name": "sobol", "config": {"n_samples": 3}}, space)

    assert isinstance(sampler, SobolSampler)
    assert sampler.total_samples() == 3
    assert sampler.next() == {"speed": 40.0, "offset": 0.0}


def test_sobol_sampler_maps_continuous_domain_values() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(10.0, 30.0))])

    sampler = create_sampler({"method": "sobol", "config": {"n_samples": 3}}, space)
    samples = [sampler.next() for _ in range(3)]

    assert samples == [{"speed": 25.0}, {"speed": 15.0}, {"speed": 17.5}]


def test_grid_sampler_discretizes_domain_with_config() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(10.0, 30.0)),
            ParameterSpec("offset", bounds=(-1.0, 1.0)),
        ]
    )

    sampler = create_sampler(
        {
            "method": "grid",
            "config": {
                "defaults": {"n": 3},
                "parameters": {"offset": {"step": 1.0}},
            },
        },
        space,
    )

    assert sampler.total_samples() == 9
    assert sampler.next() == {"speed": 10.0, "offset": -1.0}
    assert sampler.next() == {"speed": 10.0, "offset": 0.0}


def test_grid_sampler_parameter_config_overrides_global_config() -> None:
    space = ParameterSpace.from_specs(
        [
            ParameterSpec("speed", bounds=(0.0, 20.0)),
            ParameterSpec("duration", bounds=(0.0, 1.0)),
        ]
    )

    sampler = create_sampler(
        {
            "method": "grid",
            "config": {
                "step": 10,
                "parameters": {
                    "duration": {
                        "n": 3,
                    }
                },
            },
        },
        space,
    )

    assert sampler.total_samples() == 9
    assert sampler.next() == {"speed": 0.0, "duration": 0.0}
    assert sampler.next() == {"speed": 0.0, "duration": 0.5}
    assert sampler.next() == {"speed": 0.0, "duration": 1.0}


def test_grid_sampler_rejects_unknown_parameter_config() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="unknown parameter"):
        create_sampler(
            {
                "method": "grid",
                "config": {
                    "parameters": {
                        "speeed": {
                            "n": 3,
                        }
                    }
                },
            },
            space,
        )


def test_grid_sampler_rejects_unknown_parameter_config_key() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="unknown key"):
        create_sampler(
            {
                "method": "grid",
                "config": {
                    "parameters": {
                        "speed": {
                            "value": [0.0, 10.0],
                        }
                    }
                },
            },
            space,
        )


def test_grid_sampler_rejects_multiple_parameter_discretization_methods() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", bounds=(0.0, 20.0))])

    with pytest.raises(ValueError, match="exactly one"):
        create_sampler(
            {
                "method": "grid",
                "config": {
                    "parameters": {
                        "speed": {
                            "n": 3,
                            "step": 10,
                        }
                    }
                },
            },
            space,
        )


def test_native_sampler_uses_openscenario_parameter_values() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0, 20.0))])

    sampler = create_sampler({"method": "native"}, space)

    assert isinstance(sampler, OpenScenarioNativeSampler)
    assert sampler.next() == {"speed": 10.0}


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


def test_create_sampler_merges_config_path(tmp_path: Path) -> None:
    config_path = tmp_path / "sampler.yaml"
    config_path.write_text("n_samples: 2\nseed: 1\n", encoding="utf-8")
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0, 20.0, 30.0))])

    sampler = create_sampler({"name": "lhs", "config_path": str(config_path)}, space)

    assert sampler.total_samples() == 2


def test_import_from_path_validates_sampler_api() -> None:
    with pytest.raises(TypeError):
        import_from_path("pathlib:Path")


class MinimalSampler(Sampler):
    def __init__(self, parameter_space: ParameterSpace):
        super().__init__(parameter_space)

    def next(self, past_results=None):
        return None


def test_create_sampler_filters_unsupported_constructor_kwargs() -> None:
    space = ParameterSpace.from_specs([ParameterSpec("speed", (10.0,))])

    sampler = create_sampler(
        {"module_path": "tests.test_sampler:MinimalSampler", "config": {"ignored": True}},
        space,
    )

    assert isinstance(sampler, MinimalSampler)
