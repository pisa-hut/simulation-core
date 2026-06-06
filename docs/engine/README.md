# Engine

`SimulationEngine` is the runner coordinator. It reads the runner spec, creates the scenario pack, initializes wrappers, creates the monitor, optionally creates a sampler, and runs concrete scenarios.

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

`sampler` is optional. An empty sampler means the engine runs one concrete scenario.

## Runtime

```json
{
  "runtime": {
    "dt": 0.01,
    "log_level": "info",
    "overwrite": false,
    "max_concrete_retries": 3,
    "permutation": null
  }
}
```

- `dt`: simulation step size in seconds. It must be positive.
- `log_level`: Python logging level for the runner.
- `overwrite`: when `true`, run even if previous summaries exist and replace current concrete summary history.
- `max_concrete_retries`: retry cap for retryable concrete errors.
- `permutation`: optional 1-based sampler index to run only one sampled concrete scenario.

## Task

```json
{
  "task": {
    "job_id": "0",
    "output_dir": "./outputs/my_task"
  }
}
```

- `job_id`: written to `run.job_id` in the monitor summary.
- `output_dir`: base directory for concrete scenario outputs and logical scenario summary.

For a concrete scenario:

```text
outputs/my_task/concrete/
```

For sampled scenarios:

```text
outputs/my_task/iteration_1/
outputs/my_task/iteration_2/
```

For explicit samples with ids:

```text
outputs/my_task/iteration_case_001/
outputs/my_task/iteration_cutin_fast/
```

## Map And Scenario

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
    "stop_condition_config_path": "stop_conditions.yaml",
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

`ScenarioPack.from_dict()` builds the protobuf scenario pack passed to simulator and AV. Position fields are parsed by `PositionParser`, which supports `LanePosition` and `WorldPosition` through configured map/scenario context.

## Lifecycle

For each concrete scenario, `SimulationEngine.run_concrete()` does:

1. `monitor.reset(output_related, params=params)`
2. Check parameter-only stop conditions before simulator reset.
3. `sim.reset(output_related, sps, params)`
4. `av.reset(output_related, sps, raw_obs)`
5. `monitor.update(0, runtime_frame, ctrl_for_sim)` records the reset frame at `t=0`.
6. Loop:
   - `monitor.should_stop()`
   - `sim.step(ctrl_for_sim, sim_time_ns)`
   - `av.step(raw_obs, sim_time_ns)`
   - `monitor.update(sim_time_ns, runtime_frame, ctrl_for_sim)`
7. `monitor.finalize(status="finished", reason=...)`

If an exception occurs, the engine tries:

```python
monitor.finalize(status="error", reason=f"{type(exc).__name__}: {exc}")
```

The original exception is re-raised even if monitor finalization fails.

## Execution Status And Test Outcome

`run.status` is runner execution status:

- `finished`
- `error`
- `skipped`
- `abort`

`run.test_outcome` is test semantics:

- `success`
- `fail`
- `invalid`
- `unknown`

Use `error` for runner/system failures. Use `fail` for a completed test where ego behavior failed the scenario objective, such as collision or leaving a required range.

## Retry And Skip Behavior

Completion and failure history are tracked by `monitor/summary.csv` for each concrete run.

If the last `run.status` is `finished`, `concrete_wrapper()` skips the run when `runtime.overwrite` is `false`. If the last status is `error`, the runner retries until `max_concrete_retries` is reached. Legacy rows with `run.status=fail` are treated as `error` for retry and aggregation.

The runner no longer creates `status/completed.txt` or `status/error.txt`. Existing status directories from older runs are not removed automatically.

## Logical Scenario Summary

The logical scenario summary at `outputs/<task>/summary.csv` aggregates both execution statuses and test outcomes with fields such as:

- `current_finished`
- `current_error`
- `current_success`
- `current_test_fail`
- `current_invalid`
- cumulative counterparts for the same categories
