# Sampler Config Examples

Runner specs can keep sampler selection small:

```json
{
  "sampler": {
    "name": "lhs",
    "config_path": "./docs/sampler/examples/lhs.yaml"
  }
}
```

The config file contains the sampler source, optional engine iteration limit, and the
sampler-specific settings.

## Implemented Sampler Names

- `native` / `openscenario_native`: uses OpenSCENARIO parameter distributions as-is.
- `explicit`: runs the exact listed sample ids and parameter changes from a YAML/JSON file.
- `grid` / `grid_search`: enumerates the Cartesian product of discrete parameter values.
- `lhs`: Latin hypercube sampling over the configured parameter space.
- `sobol`: Sobol sequence sampling over the configured parameter space.

## Common Fields

- `source.type`: `openscenario`/`xosc` for OpenSCENARIO parameter files, or
  `param_range`/`yaml`/`domain` for YAML/JSON parameter-domain files.
- `source.path`: parameter source file path. Relative paths are resolved relative to the
  sampler config file.
- `max_samples`: optional engine-side cap on how many samples to execute.

## Sampler-Specific Fields

`grid` / `grid_search`:

- `defaults.n`: default number of grid points for continuous parameters.
- `defaults.step`: default grid step for continuous parameters.
- `parameters.<name>.values`: explicit values for one parameter.
- `parameters.<name>.n`: number of grid points for one continuous parameter.
- `parameters.<name>.step`: grid step for one continuous parameter.

`lhs`:

- `n_samples`: number of generated samples.
- `seed`: optional deterministic random seed.

`sobol`:

- `n_samples`: number of generated samples.
- `skip`: number of initial Sobol points to skip. Default is `1`.

`native` / `openscenario_native`:

- No required sampler-specific fields. The OpenSCENARIO parameter distribution defines
  the concrete values.

`explicit`:

- No required sampler-specific fields. The `source.path` file must contain a `samples` list.
- Each sample must have a unique `id` and a `params` mapping.
- Output folders are named `iteration_<id>`.
- Each sample can modify a different set of parameters.
