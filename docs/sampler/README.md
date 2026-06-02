# Sampler

Samplers create concrete parameter sets for logical scenarios. Runtime specs only select the sampler name and point to a sampler config file.

## Runtime Spec

```json
{
  "sampler": {
    "name": "lhs",
    "config_path": "./docs/sampler/examples/lhs.yaml"
  }
}
```

If `sampler` is omitted or `{}`, the engine runs one concrete scenario without sampling.

Runtime `sampler` only accepts:

- `name`
- `config_path`

Put `source`, `max_samples`, and sampler-specific settings in the sampler config file.

## Sampler Config

```yaml
source:
  type: param_range
  path: parameter_space.yaml
max_samples: null
n_samples: 50
seed: 42
```

- `source.type`: source parser type.
- `source.path`: parameter source path. In engine runs, relative paths are resolved
  relative to the folder from `scenario.scenario_path`. When using sampler utilities
  standalone without a scenario base, relative paths are resolved relative to the
  sampler config file.
- `max_samples`: optional engine-side cap on samples to execute.
- Remaining fields are passed to the selected sampler constructor.

## Sample Contract

Every sampler returns:

```python
Sample(id: str | None, params: dict, metadata: dict)
```

When `Sample.id` is omitted, output folders use the 1-based sequence:

```text
iteration_1/
iteration_2/
```

When `Sample.id` is set, output folders use:

```text
iteration_<id>/
```

## Implemented Sampler Names

- `native` / `openscenario_native`: uses OpenSCENARIO parameter distributions as-is.
- `explicit`: runs exact listed sample ids and parameter changes.
- `grid` / `grid_search`: enumerates a Cartesian product.
- `lhs`: Latin hypercube sampling.
- `sobol`: Sobol sequence sampling.

## Source Types

### OpenSCENARIO

Use for native OpenSCENARIO parameter distributions:

```yaml
source:
  type: openscenario
  path: sample_param_distribution.xosc
```

The native sampler uses `stepWidth` or deterministic sets as concrete values.

### Parameter Range

Use for domain-based `grid`, `lhs`, and `sobol`:

```yaml
parameters:
  - name: speed
    type: double
    range: [10.0, 30.0]
  - name: offset
    type: double
    range: [-2.0, 2.0]
  - name: behavior
    type: categorical
    values: [cutin, brake]
```

Supported source aliases:

- `param_range`
- `yaml`
- `domain`

### Explicit Samples

Use when every concrete test case should be named and configured directly:

```json
{
  "sampler": {
    "name": "explicit",
    "config_path": "./docs/sampler/examples/explicit.yaml"
  }
}
```

`explicit.yaml`:

```yaml
source:
  type: explicit
  path: explicit_samples.yaml
max_samples: null
```

`explicit_samples.yaml`:

```yaml
samples:
  - id: case_001
    params:
      ego_speed: 10.0
      agent0_speed: 15.0
      behavior: keep_lane

  - id: cutin_fast
    params:
      ego_speed: 22.5
      cutin_offset: -1.2
      behavior: cut_in

  - id: agent_brake
    params:
      agent0_speed: 8.0
      behavior: brake
```

Each explicit sample must have a unique `id` and a `params` mapping. Samples do not need to modify the same parameter names. Sample ids may contain letters, numbers, `_`, `.`, and `-`.

## Method Config

### Grid

```yaml
source:
  type: param_range
  path: parameter_space.yaml
defaults:
  n: 3
parameters:
  ego_speed:
    values: [10.0, 15.0, 20.0]
  cutin_offset:
    step: 0.5
```

Grid settings:

- `defaults.n`: default number of grid points for continuous parameters.
- `defaults.step`: default grid step for continuous parameters.
- `parameters.<name>.values`: explicit values for one parameter.
- `parameters.<name>.n`: number of grid points for one continuous parameter.
- `parameters.<name>.step`: grid step for one continuous parameter.

### LHS

```yaml
source:
  type: param_range
  path: parameter_space.yaml
n_samples: 50
seed: 42
```

### Sobol

```yaml
source:
  type: param_range
  path: parameter_space.yaml
n_samples: 64
skip: 1
```

LHS and Sobol default to at most 16 samples when `n_samples` is omitted.

## Examples

Detailed sampler config examples are in [examples](sampler/examples/).

Inspect sampler output without running simulator/AV:

```bash
python sampler_tester.py docs/sampler/examples/parameter_space.yaml --source-type param_range --method lhs --n-samples 8 --seed 42
python sampler_tester.py docs/sampler/examples/parameter_space.yaml --source-type param_range --method sobol --n-samples 8
python sampler_tester.py docs/sampler/examples/sample_param_distribution.xosc --method native
```
