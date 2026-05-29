# PISA SimCore Runner

`simcore` is the Python runner for PISA scenario execution. It connects to a simulator service and an AV service through `pisa-api` gRPC stubs, runs concrete or parameterized scenarios, evaluates stop conditions, and writes monitor logs for frame-level metrics, event tables, and scenario summaries.

The runner is intentionally small: the engine owns scenario lifecycle, wrappers own gRPC communication, conditions own stop logic, recorders own logging rows, and shared metric code lives in `simcore.metrics`.

## Requirements

- Python `>=3.14`
- `uv`
- Reachable simulator gRPC service
- Reachable AV gRPC service
- PISA API dependency, installed from `pyproject.toml`

Install dependencies:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --locked
```

Run tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
```

## Quick Start

Run a scenario from a runner spec:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python main.py --runner_spec specs/autoware_esmini.json
```

The runner spec is a JSON file that configures runtime behavior, output paths, simulator and AV endpoints, map/scenario metadata, optional parameter sampling, and monitor behavior.

## Repository Layout

```text
main.py                         # CLI entrypoint
simcore/engine.py               # SimulationEngine lifecycle
simcore/sim_wrapper.py          # Simulator gRPC wrapper
simcore/av_wrapper.py           # AV gRPC wrapper
simcore/monitor.py              # Stop condition + logging coordinator
simcore/conditions/             # Stop condition tree and condition implementations
simcore/monitoring/             # Frame/table/summary logging infrastructure
simcore/metrics/                # Shared domain metrics used by conditions and recorders
simcore/sampler/                # Parameter samplers
simcore/utils/                  # Scenario, object, control, position helpers
specs/                          # Example runner and monitor configs
tests/                          # Unit tests
```

## Runner Spec

A runner spec has these top-level sections:

```json
{
  "runtime": {},
  "task": {},
  "simulator": {},
  "av": {},
  "map": {},
  "scenario": {},
  "sampler": {},
  "monitor": {}
}
```

### `runtime`

```json
{
  "runtime": {
    "dt": 0.01,
    "log_level": "info",
    "overwrite": false
  }
}
```

- `dt`: simulation step size in seconds. If omitted, defaults to `0.01`.
- `log_level`: Python logging level for the runner.
- `overwrite`: when `true`, run even if the last summary row is already `finished` and overwrite the previous `summary.csv` history for that concrete run. When `false`, finished runs are skipped and failed retries append new summary rows.

### `task`

```json
{
  "task": {
    "job_id": "0",
    "output_dir": "./outputs/my_task"
  }
}
```

- `job_id`: identifier written to `run.job_id` in `summary.csv`.
- `output_dir`: base directory for all concrete scenario outputs.

For a concrete scenario, output is written under:

```text
outputs/my_task/concrete/
```

For a parameterized scenario, each sampled case is written under:

```text
outputs/my_task/iteration_1/
outputs/my_task/iteration_2/
...
```

### `simulator`

```json
{
  "simulator": {
    "url": "localhost:8111",
    "timeout": 100.0,
    "config_path": "/path/to/sim.yaml",
    "output_path": "/mnt/output",
    "scenario": {
      "format": "OpenScenario1",
      "name": "my_scenario",
      "path": "/mnt/scenario"
    }
  }
}
```

The simulator wrapper:

1. Connects to `url`.
2. Calls `Ping` until the service is available.
3. Calls `Init`.
4. Calls `Reset` before each concrete run.
5. Calls `Step` every simulation step.
6. Calls `Stop` during engine shutdown.

### `av`

```json
{
  "av": {
    "url": "localhost:9083",
    "timeout": 100.0,
    "config_path": "/path/to/av.yaml",
    "output_path": "/mnt/output"
  }
}
```

The AV wrapper follows the same lifecycle as the simulator wrapper. On every loop iteration, the runner sends the simulator observation to AV and receives the next control command.

### `map` and `scenario`

```json
{
  "map": {
    "name": "tyms",
    "osm_path": "/path/to/osm",
    "xodr_path": "/path/to/xodr"
  },
  "scenario": {
    "title": "my_scenario",
    "scenario_path": "/path/to/scenario",
    "rmlib_path": "/path/to/libesminiRMLib.so",
    "goal_config": {
      "position": {
        "type": "LanePosition",
        "value": [25, 1, 62, 3.60488429838756, null, null]
      },
      "target_speed": 24.5
    }
  }
}
```

`ScenarioPack.from_dict()` builds the protobuf scenario pack passed to simulator and AV. Position fields are parsed by `PositionParser`, which supports configured map/scenario context.

### `sampler`

If the scenario directory contains a parameter range file named:

```text
<scenario_title>_param.xosc
```

the engine creates the configured sampler and runs all sampled concrete scenarios. OpenSCENARIO
parameter files are treated as native sample definitions; their `stepWidth` or predefined sets are
used as-is.

Built-in sampler methods include OpenSCENARIO native sampling, grid search, Latin hypercube
sampling, and Sobol sampling:

```json
{
  "sampler": {
    "method": "native"
  }
}
```

For LHS, Sobol, or domain-based grid search, use a separate YAML/JSON parameter range file that
describes the parameter domain, not the sampling plan. See `sampler_params_example.yaml`:

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

```json
{
  "sampler": {
    "source": {
      "type": "param_range",
      "path": "./sampler_params.yaml"
    },
    "method": "lhs",
    "config": {
      "n_samples": 50,
      "seed": 42
    }
  }
}
```

```json
{
  "sampler": {
    "source": {
      "type": "param_range",
      "path": "./sampler_params.yaml"
    },
    "method": "sobol",
    "config": {
      "n_samples": 50,
      "skip": 1
    }
  }
}
```

Domain-based grid search discretizes continuous ranges according to sampler config:

```json
{
  "sampler": {
    "source": {
      "type": "param_range",
      "path": "./sampler_params.yaml"
    },
    "method": "grid",
    "config": {
      "defaults": {
        "n": 5
      },
      "parameters": {
        "offset": {
          "step": 0.5
        }
      }
    }
  }
}
```

Built-in samplers are selected by `method`; the previous `name` field is still accepted for
compatibility. External samplers can still be loaded with
`"module_path": "package.module:SamplerClass"` if they inherit from `simcore.sampler.Sampler`.

Samplers return one parameter dictionary per iteration. Finite samplers can expose
`total_samples()` for progress reporting; adaptive samplers may return `None` when the total is
not known ahead of time.

Sampler config can be provided inline with `sampler.config` or through a YAML/JSON file via
`sampler.config_path`; inline config wins when both are present. LHS and Sobol default to at most
16 samples when `n_samples` is omitted.

To inspect sampler output without running a simulator:

```bash
python sampler_tester.py path/to/scenario_param.xosc --method native
python sampler_tester.py path/to/sampler_params.yaml --source-type param_range --method lhs --n-samples 8 --seed 42
python sampler_tester.py path/to/sampler_params.yaml --source-type param_range --method sobol --n-samples 8
```

### `monitor`

```json
{
  "monitor": {
    "module_path": "simcore.monitor:Monitor",
    "config_path": "./specs/monitor_config_example.yaml"
  }
}
```

`module_path` is present for compatibility with runner specs, but the current engine instantiates `simcore.monitor.Monitor` directly. `config_path` points to the YAML monitor config.

## Engine Lifecycle

For each concrete scenario, `SimulationEngine.run_concrete()` does:

1. `monitor.reset(output_related, params=params)`
2. `sim.reset(output_related, sps, params)`
3. `av.reset(output_related, sps, raw_obs)`
4. Loop:
   - `monitor.should_stop()`
   - `sim.step(ctrl_for_sim, sim_time_ns)`
   - `av.step(raw_obs, sim_time_ns)`
   - `monitor.update(sim_time_ns, runtime_frame, ctrl_for_sim)`
5. `monitor.finalize(status="finished", reason=...)`

If an exception occurs, the engine tries:

```python
monitor.finalize(status="fail", reason=f"{type(exc).__name__}: {exc}")
```

The original exception is re-raised even if monitor finalization fails. When `runtime.overwrite` is `false`, failed attempts and later successful retries remain visible in `summary.csv`. When `runtime.overwrite` is `true`, the new attempt replaces the previous summary history.

## Monitor Config

The monitor has two responsibilities:

- `condition`: decide when the scenario should stop.
- `logging`: write frame metrics, table logs, and summary metrics.

These are intentionally separate. Logging never controls scenario stop. If a metric should also stop the scenario, put the calculation in `simcore.metrics` and use it from both a condition and a recorder.

See [specs/monitor_config_example.yaml](specs/monitor_config_example.yaml) for a full example.

### Complete Monitor Example

```yaml
logging:
  enabled: true
  output_dir: monitor
  flush_every_n_rows: 100
  float_precision: 6

  frame:
    enabled: true
    every_n_steps: 1
    output: frame_metrics.csv
    recorders:
      - type: ego_state
        name: ego
        actor_id: 0
        fields: [x, y, z, yaw, speed, acceleration]

      - type: pair_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1

  tables:
    - type: agent_states
      name: agent_states
      every_n_steps: 1
      output: agent_states.csv

    - type: collision_events
      name: ego_collision_events
      output: collision_events.csv
      actor_id_a: 0
      deduplicate: true

  summary:
    output: summary.csv
    include_basic: true
    recorders:
      - type: min_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1

      - type: max_speed
        name: ego
        actor_id: 0

condition:
  type: or
  name: stop_conditions
  children:
    - type: collision
      name: collision_guard
      actor_id_a: 0

    - type: timeout
      name: timeout_30s
      timeout_ms: 30000

    - type: pair_ttc
      name: low_ttc_ego_to_agent_1
      actor_id_a: 0
      actor_id_b: 1
      threshold_s: 1.0
```

### Logging Output

For `output_dir = ./outputs/my_task` and one concrete run, monitor logs are written to:

```text
outputs/my_task/concrete/monitor/
  frame_metrics.csv
  agent_states.csv
  collision_events.csv
  summary.csv
```

For sampled runs:

```text
outputs/my_task/iteration_1/monitor/
outputs/my_task/iteration_2/monitor/
...
```

All logged simulation times use milliseconds:

```text
sim_time_ms
final_sim_time_ms
```

`logging.float_precision` controls float formatting. The default is `6`.

## Stop Conditions

Stop conditions are configured as a tree:

```yaml
condition:
  type: or
  name: stop_conditions
  children:
    - type: timeout
      name: timeout_30s
      timeout_ms: 30000
    - type: collision
      name: collision_guard
      actor_id_a: 0
```

Logical nodes:

- `and`
- `or`

Built-in leaf conditions:

| Type | File | Purpose |
| --- | --- | --- |
| `timeout` | `simcore/conditions/custom_conditions/timeout.py` | Stop after simulation time exceeds `timeout_ms`. |
| `collision` | `simcore/conditions/custom_conditions/collision.py` | Stop when simulator-reported collision matches optional actor filter. |
| `reach_target_position` | `simcore/conditions/custom_conditions/reach_target_position.py` | Stop when an actor reaches a configured target position. |
| `pair_ttc` | `simcore/conditions/custom_conditions/pair_ttc.py` | Stop when pair TTC falls below `threshold_s`. |

When a condition stops the scenario, `summary.csv` receives a detailed stop reason, for example:

```text
Stop condition 'low_ttc_ego_to_agent_1' triggered: TTC between actor 0 and actor 1 is below threshold: ttc=0.850s threshold=1.000s
```

## Logging Pipelines

Monitor logging is split by row cardinality.

### Frame Recorders

Frame recorders produce fixed columns and are merged into one row per logged frame.

Config:

```yaml
logging:
  frame:
    every_n_steps: 1
    output: frame_metrics.csv
    recorders:
      - type: ego_state
        name: ego
      - type: pair_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1
```

Output columns are prefixed by recorder name:

```csv
step_index,sim_time_ms,ego.x,ego.y,ego.speed,ego_to_agent_1.distance_m,ego_to_agent_1.ttc_s
```

Built-in frame recorders:

| Type | Fields | Notes |
| --- | --- | --- |
| `ego_state` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` | `actor_id` defaults to `0`. `fields` can limit output. |
| `pair_ttc` | `distance_m`, `closing_speed_mps`, `ttc_s` | Computes TTC for `actor_id_a` and `actor_id_b`. |

### Table Recorders

Table recorders write their own CSV streams. They are for variable-cardinality data, sparse events, or one-frame-many-row output.

Built-in table recorders:

| Type | Output | Notes |
| --- | --- | --- |
| `agent_states` | one row per agent per logged frame | Handles variable agent counts. |
| `collision_events` | one row per matching collision event | Sparse table; supports actor filters and `deduplicate`. |

`agent_states.csv` example:

```csv
step_index,sim_time_ms,agent_id,x,y,z,yaw,speed,acceleration,yaw_rate,yaw_acceleration
0,0.000000,0,1.000000,2.000000,0.000000,0.000000,4.000000,0.000000,0.000000,0.000000
0,0.000000,12,8.000000,3.000000,0.000000,0.000000,2.000000,0.000000,0.000000,0.000000
```

`collision_events.csv` example:

```csv
step_index,sim_time_ms,actor_a,actor_b
15,150.000000,0,12
```

Collision events currently use simulator-provided collision data from `runtime_frame.collision`. If the simulator does not provide collision data, an empty collision list and unavailable collision data may look the same depending on the API payload. Prefer explicit simulator/API capability metadata if strict validation is required.

### Summary Recorders

Summary recorders update during the scenario and write one merged row at finalize.

Config:

```yaml
logging:
  summary:
    output: summary.csv
    include_basic: true
    recorders:
      - type: min_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1
      - type: max_speed
        name: ego
        actor_id: 0
```

`basic_summary` is included by default as `run.*` unless `include_basic: false`.

Built-in summary recorders:

| Type | Fields | Notes |
| --- | --- | --- |
| `basic_summary` | `status`, `stop_reason`, `total_steps`, `final_sim_time_ms`, `wall_time_ms`, `job_id`, `params` | Added automatically by default as `run.*`. |
| `min_ttc` | `min_ttc_s` | Tracks minimum finite TTC for an actor pair. |
| `max_speed` | `max_speed_mps` | Tracks maximum speed for one actor. |

`summary.csv` example:

```csv
run.status,run.stop_reason,run.total_steps,run.final_sim_time_ms,run.wall_time_ms,run.job_id,run.params,ego_to_agent_1.min_ttc_s,ego.max_speed_mps
finished,completed,600,6000.000000,8100.000000,0,"{""speed"": ""10""}",1.250000,14.500000
```

## Built-in Metrics

Shared metric code lives in `simcore.metrics`.

Currently available:

- `compute_pair_ttc(objects, actor_id_a, actor_id_b)`

This is used by:

- `pair_ttc` frame recorder
- `pair_ttc` stop condition
- `min_ttc` summary recorder

The purpose is to avoid coupling conditions to logging while still sharing calculation logic.

## Output Status Files

Completion and failure history are tracked by `monitor/summary.csv`.

If the last `run.status` is `finished`, `concrete_wrapper()` skips the run when `runtime.overwrite` is `false`. If the last status is `fail`, the runner attempts the scenario again and appends another summary row. If `runtime.overwrite` is `true`, the runner ignores previous status and overwrites the existing `summary.csv` with the new attempt, whether that attempt finishes or fails.

The runner no longer creates `status/completed.txt` or `status/error.txt`. Existing status directories from older runs are not removed automatically.

## Extending Conditions

1. Create a condition class under `simcore/conditions/custom_conditions/`.
2. Inherit from `ConditionNode`.
3. Implement:
   - `put(data)`
   - `evaluate() -> EvaluationResult`
   - `reset()`
4. Register it in `simcore/conditions/condition_registry.py`.

Minimal shape:

```python
from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult


class MyCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

    def put(self, data):
        ...

    def evaluate(self) -> EvaluationResult:
        return self.result(ConditionCode.NOT_TRIGGERED, "not triggered")

    def reset(self):
        ...
```

Register:

```python
CONDITION_REGISTRY = {
    "my_condition": "simcore.conditions.custom_conditions.my_condition.MyCondition",
}
```

Use:

```yaml
condition:
  type: my_condition
  name: my_condition_1
```

## Extending Logging

Choose the recorder type based on output cardinality.

### Add a Frame Recorder

Use this when output is fixed columns and exactly one row per logged frame.

1. Create `simcore/monitoring/frame_recorders/my_metric.py`.
2. Inherit from `FrameRecorder`.
3. Implement `fields()` and `record(sample)`.
4. Register it in `simcore/monitoring/frame_recorder_registry.py`.

```python
from typing import Any

from simcore.monitoring.frame_recorders.base import FrameRecorder
from simcore.monitoring.sample import MonitorSample


class MyFrameRecorder(FrameRecorder):
    def fields(self) -> tuple[str, ...]:
        return ("value",)

    def record(self, sample: MonitorSample) -> dict[str, Any]:
        return {"value": 1.0}
```

### Add a Table Recorder

Use this when output may be zero, one, or many rows per frame.

1. Create `simcore/monitoring/recorders/my_events.py`.
2. Inherit from `Recorder`.
3. Implement `streams()` and `record(sample)`.
4. Register it in `simcore/monitoring/recorder_registry.py`.

```python
from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.recorders.base import Recorder
from simcore.monitoring.sample import LogRow, MonitorSample


class MyEventsRecorder(Recorder):
    def streams(self) -> list[LogStream]:
        return [
            LogStream(
                name=self.name,
                filename=self.output,
                fields=("step_index", "sim_time_ms", "event"),
            )
        ]

    def record(self, sample: MonitorSample) -> list[LogRow]:
        return [
            LogRow(
                stream=self.name,
                row={
                    "step_index": sample.step_index,
                    "sim_time_ms": sample.sim_time_ms,
                    "event": "example",
                },
            )
        ]
```

### Add a Summary Recorder

Use this when output is one scenario-level row written at finalize.

1. Create `simcore/monitoring/summary_recorders/my_summary.py`.
2. Inherit from `SummaryRecorder`.
3. Implement `fields()`, optionally `update(sample)`, and `record(context)`.
4. Register it in `simcore/monitoring/summary_recorder_registry.py`.

```python
from typing import Any

from simcore.monitoring.sample import MonitorSample
from simcore.monitoring.summary_recorders.base import SummaryContext, SummaryRecorder


class MySummaryRecorder(SummaryRecorder):
    def __init__(self, config: dict):
        super().__init__(config)
        self.count = 0

    def fields(self) -> tuple[str, ...]:
        return ("count",)

    def reset(self) -> None:
        self.count = 0

    def update(self, sample: MonitorSample) -> None:
        self.count += 1

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {"count": self.count}
```

## Design Notes

- Stop conditions do not depend on logging.
- Logging does not control scenario stop.
- Shared calculations belong in `simcore.metrics`, not in condition or recorder classes.
- Frame logs use one fixed row per frame.
- Table logs are for variable rows or sparse events.
- Summary logs are scenario-level metrics written at finalize.
- CSV schemas are fixed at reset time; unexpected fields raise an error.
- Multiple streams cannot share the same output filename.
- Float formatting is centralized in `LogManager`.

## Development Commands

Run all tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

Run lint:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
```

Run one test file:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_monitor_logging.py
```

## Known Limitations

- `monitor.module_path` in runner specs is not dynamically loaded by the current engine.
- Collision logging and collision stop conditions currently rely on simulator-provided collision fields.
- Bounding-box-derived collision is not implemented yet.
- Summary aggregation across multiple iterations is not implemented yet.
- Monitor logs are CSV only; JSONL or Parquet sinks are not implemented yet.
