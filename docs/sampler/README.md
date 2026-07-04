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

Programmatic sampler setup should follow the same order as the engine:

```python
sampler_spec = load_sampler_spec(runtime_sampler_spec, source_base_path=scenario_folder)
source_path, source_type = resolve_sampler_source(sampler_spec)
parameter_space = load_parameter_space(source_path, source_type)
sampler = create_sampler(sampler_spec, parameter_space)
```

Only `load_sampler_spec()` reads `sampler.config_path` and normalizes `source.path`.
`resolve_sampler_source()` and `create_sampler()` expect the effective spec returned by
`load_sampler_spec()`.

## Sampler Config

```yaml
source:
  type: param_range
  path: range.yaml
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

`Sample.params` is the sampled parameter set and is what monitor summaries record.
When parameter-range `outputs` are configured, `Sample.sim_params` contains those
mapped output fields; the engine sends `Sample.sim_params` to the simulator.

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
- `random`: seeded uniform random sampling.
- `sobol`: Sobol sequence sampling.
- `feedback_boundary` / `adaptive_boundary`: feedback-driven boundary refinement.

## Source Types

### OpenSCENARIO

Use for native OpenSCENARIO parameter distributions:

```yaml
source:
  type: openscenario
  path: param.xosc
```

The native sampler uses `stepWidth` or deterministic sets as concrete values.
For `native` / `openscenario_native`, `source.path` is optional. When omitted, the
engine looks for `param.xosc` in the scenario folder. If the native source file is
not present, the runner treats the scenario as a single concrete run. Other samplers
must provide an existing `source.path`.

### Parameter Range

Use for domain-based `grid`, `lhs`, and `sobol`:

```yaml
parameters:
  - name: Ego_S
    type: double
    range: [80.0, 120.0]
  - name: Relative_Dist
    type: double
    range: [10.0, 40.0]
  - name: Ego_Speed
    type: double
    range: [8.0, 30.0]

outputs:
  Ego_S: Ego_S
  Agent_S: Ego_S + Relative_Dist
  Agent_Speed: Ego_Speed / 2
```

Supported source aliases:

- `param_range`
- `yaml`
- `domain`

### Output Mapping

Use `outputs` in a parameter range source when the simulator cannot evaluate nested
OpenSCENARIO expressions such as `${$Ego_S + $Relative_Dist}`. The sampler samples
only the `parameters` entries, then maps each sample into the final simulator
parameter interface described by `outputs`.

```yaml
parameters:
  - name: Ego_S
    type: double
    range: [80.0, 120.0]
  - name: Relative_Dist
    type: double
    range: [10.0, 40.0]
  - name: Ego_Speed
    type: double
    range: [8.0, 30.0]

outputs:
  Ego_S: Ego_S
  Agent_S: Ego_S + Relative_Dist
  Agent_Speed:
    expression: Ego_Speed / 2
    type: double
```

Given a sampled parameter set:

```yaml
Ego_S: 100.0
Relative_Dist: 25.0
Ego_Speed: 20.0
```

the monitor summary records only:

```yaml
Ego_S: 100.0
Relative_Dist: 25.0
Ego_Speed: 20.0
```

and the simulator receives:

```yaml
Ego_S: 100.0
Agent_S: 125.0
Agent_Speed: 10.0
```

Output expressions may reference sampled parameters and earlier output fields.
Allowed expression syntax is numeric constants, parameter names, `+ - * / % **`,
parentheses, and `abs()`, `min()`, `max()`, `round()`. The aliases
`output_parameters` and `sim_parameters` are also accepted for the same section,
but only one output mapping key may be used.

The `native` / `openscenario_native` sampler keeps the original OpenSCENARIO
parameter distribution behavior and ignores output mappings.

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
  path: range.yaml
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
  path: range.yaml
n_samples: 50
seed: 42
```

### Sobol

```yaml
source:
  type: param_range
  path: range.yaml
n_samples: 64
skip: 1
```

LHS and Sobol default to at most 16 samples when `n_samples` is omitted.

### Random

```yaml
source:
  type: param_range
  path: range.yaml
n_samples: 50
seed: 42
```

### Feedback Boundary

```yaml
source:
  type: param_range
  path: range.yaml
total_samples: 64
initial_samples: 12
initial_sampler: sobol
min_ttc_threshold: 1.5
boundary_candidate_count: 32
opposite_neighbors: 3
candidates_per_pair: 2
uncertainty_weight: 0.35
novelty_weight: 0.25
coverage_weight: 0.40
perturbation_scale: 0.05
exploration_ratio: 0.2
random_seed: 42
duplicate_tolerance: 1.0e-6
unsafe_conditions:
  - metric: ego_clearance.min
    operator: lt
    value: 1.0
```

The first samples come from `sobol`, `lhs`, or `random`. Once both SAFE and UNSAFE
results exist, each sample selects its nearest opposite-label neighbors in normalized
parameter space. The sampler generates a small number of midpoint candidates per local
pair, then scores the complete pool using:

```text
score =
    uncertainty_weight * transition_width
  + novelty_weight * distance_from_existing_samples
  + coverage_weight * distance_from_previous_boundary_samples
```

Each score component is min-max normalized within the current candidate pool. This
keeps refinement focused on uncertain transitions while spreading samples across
different sections or disconnected components of the boundary. A configurable
fraction remains global exploration.

Classification precedence is execution error, invalid outcome, explicit fail outcome,
collision, minimum TTC/custom unsafe rules, then explicit success. A normally finished
scenario with an unknown outcome is SAFE only when every configured metric rule can be
evaluated and none is unsafe.

Feedback metrics come from monitor summary recorders. For collision and TTC rules,
configure summary recorders such as:

```yaml
logging:
  summary:
    recorders:
      - type: collision
        name: ego_collision
        actor_id_a: 0
      - type: min_ttc
        name: ego_ttc
        actor_id_a: 0
        actor_id_b: 1
```

Numeric parameters participate in normalized boundary distance. Categorical parameters
must have the same value on a SAFE/UNSAFE pair; otherwise that pair is not interpolated.
`runtime.permutation` is not supported because adaptive sample N depends on results from
the preceding samples.

## Examples

Detailed sampler config examples are in [examples](sampler/examples/).
