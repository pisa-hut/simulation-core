from __future__ import annotations

from pathlib import Path

from sampler_tester import collect_samples

PVD_XML = """\
<OpenSCENARIO>
  <ParameterValueDistribution>
    <Deterministic>
      <DeterministicSingleParameterDistribution parameterName="speed">
        <DistributionRange stepWidth="10">
          <Range lowerLimit="10" upperLimit="30" />
        </DistributionRange>
      </DeterministicSingleParameterDistribution>
    </Deterministic>
  </ParameterValueDistribution>
</OpenSCENARIO>
"""


def test_collect_samples_from_parameter_range_file(tmp_path: Path) -> None:
    param_file = tmp_path / "scenario_param.xosc"
    param_file.write_text(PVD_XML, encoding="utf-8")

    total, samples = collect_samples(
        source_file=param_file,
        sampler_name="lhs",
        config={"n_samples": 3, "seed": 1},
    )

    assert total == 3
    assert len(samples) == 3
    assert all("speed" in sample for sample in samples)


def test_collect_samples_from_yaml_domain_file(tmp_path: Path) -> None:
    param_file = tmp_path / "params.yaml"
    param_file.write_text(
        """
parameters:
  - name: speed
    type: double
    range: [10.0, 30.0]
  - name: mode
    type: categorical
    values: [cutin, brake]
""",
        encoding="utf-8",
    )

    total, samples = collect_samples(
        source_file=param_file,
        sampler_name="grid",
        source_type="param_range",
        config={"defaults": {"n": 3}},
    )

    assert total == 6
    assert samples[0] == {"speed": 10.0, "mode": "cutin"}
