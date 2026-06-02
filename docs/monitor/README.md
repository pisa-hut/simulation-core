# Monitor

`Monitor` owns stop-condition evaluation and logging. Stop logic and logging are intentionally separate: logging never controls scenario stop.

## Runner Spec

```json
{
  "monitor": {
    "config_path": "./docs/monitor/examples/monitor_config_example.yaml"
  }
}
```

The current engine instantiates `simcore.monitor.Monitor` directly.

## Config Shape

```yaml
logging:
  enabled: true
  output_dir: monitor
  flush_every_n_rows: 100
  float_precision: 6

stop_condition:
  - type: collision
    name: ego_collision
    outcome: Fail
    actor_id_a: 0
```

See [monitor_config_example.yaml](monitor/examples/monitor_config_example.yaml) for a complete example.

## Logging Output

For `output_dir = ./outputs/my_task` and one concrete run:

```text
outputs/my_task/concrete/monitor/
  frame_metrics.csv
  agent_states.csv
  collision_events.csv
  result.csv
```

For sampled runs:

```text
outputs/my_task/iteration_1/monitor/
outputs/my_task/iteration_2/monitor/
```

All logged simulation times use milliseconds:

```text
sim_time_ms
final_sim_time_ms
```

`logging.float_precision` controls float formatting. The default is `6`.

## Stop Conditions

Stop conditions can be configured as a list. The monitor wraps the list in a default top-level `or`, so each listed item is an alternative stop condition:

```yaml
stop_condition:
  - type: collision
    name: ego_collision
    outcome: Fail
    actor_id_a: 0

  - type: reach_target_position
    name: ego_reaches_goal
    outcome: Success
    target: ego
```

Top-level stop conditions should set `outcome`:

- `Success`
- `Fail`
- `Invalid`

Nested conditions inside top-level `and`/`or` can omit `outcome`; the outer child condition owns the recorded test outcome. `Invalid` is intended for valid executions that do not represent the intended test situation, such as sampled parameters producing an impossible or irrelevant maneuver.

For more complex logic, use an explicit tree:

```yaml
stop_condition:
  type: or
  name: stop_conditions
  children:
    - type: timeout
      name: timeout_30s
      outcome: Success
      timeout_ms: 30000
    - type: collision
      name: collision_guard
      outcome: Fail
      actor_id_a: 0
```

Logical nodes:

- `and`
- `or`

## Built-in Conditions

| Type | Purpose |
| --- | --- |
| `timeout` | Stop after simulation time exceeds `timeout_ms`. |
| `collision` | Stop when simulator-reported collision matches optional actor filter. |
| `reach_target_position` | Stop when an actor reaches a configured target position. |
| `kinematic_threshold` | Stop when selected actor kinematic fields satisfy a numeric rule. |
| `parameter_expression` | Stop when sampled parameters satisfy a numeric or boolean expression. |
| `relative_position` | Stop when a target actor is in a selected relative direction from a source actor. |
| `pair_ttc` | Stop when pair TTC falls below `threshold_s`. |

When a condition stops the scenario, the summary receives `run.stop_condition`, `run.test_outcome`, and detailed `run.stop_reason`.

## Kinematic Threshold

```yaml
- type: kinematic_threshold
  name: any_agent_y_too_large
  agents: any
  metric: y
  rule: gt
  value: [10.0, 0.0]

- type: kinematic_threshold
  name: agent1_z_out_of_range
  agents: [1]
  metric: z
  rule: not_between
  values: [-2.0, 2.0]
```

Supported numeric rules:

- `gt` / `>`
- `ge` / `>=`
- `lt` / `<`
- `le` / `<=`
- `eq` / `==`
- `between`
- `not_between`

## Parameter Expression

`parameter_expression` evaluates sampled parameters before simulator reset, so invalid parameter sets can be recorded without launching the concrete run.

```yaml
- type: parameter_expression
  name: invalid_speed_gap
  outcome: Invalid
  expression: "abs(a_speed - b_speed)"
  rule: le
  value: 5.0
```

For full boolean expressions:

```yaml
- type: parameter_expression
  name: invalid_formula
  outcome: Invalid
  expression: "a * b + c >= d"
```

Allowed expression syntax is numeric constants, parameter names, `+ - * / % **`, comparisons, parentheses, and `abs()`, `min()`, `max()`, `round()`.

## Relative Position

`relative_position` uses the source actor's yaw as 0 degrees. Positive angles are counter-clockwise, so target on the source actor's left side has positive angle.

Eight sectors split 360 degrees into 45-degree bins starting from source-forward:

```text
sector 0: [0, 45)       sector 1: [45, 90)
sector 2: [90, 135)     sector 3: [135, 180)
sector 4: [-180, -135)  sector 5: [-135, -90)
sector 6: [-90, -45)    sector 7: [-45, 0)
```

```yaml
- type: relative_position
  name: ego_is_straight_ahead_of_agent_1
  source_actor_id: 1
  target_actor_id: 0
  direction: straight

- type: relative_position
  name: target_in_custom_angle_range
  source: 1
  target: 2
  angle_range_deg: [-30, 30]
```

Direction aliases include `straight`, `front`, `left`, `right`, `rear`, `front_left`, `front_right`, `rear_left`, and `rear_right`. You can also use `sectors: [0, 7]`, or set `sector_index_base: 1` to write sectors as `1..8`.

## Logging Pipelines

Monitor logging is split by row cardinality.

### Frame Recorders

Frame recorders produce fixed columns and are merged into one row per logged frame.

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

Built-in frame recorders:

| Type | Fields |
| --- | --- |
| `ego_state` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` |
| `pair_ttc` | `distance_m`, `closing_speed_mps`, `ttc_s` |

### Table Recorders

Table recorders write their own CSV streams. They are for variable-cardinality data, sparse events, or one-frame-many-row output.

| Type | Output |
| --- | --- |
| `agent_states` | One row per agent per logged frame. |
| `collision_events` | One row per matching collision event. |

### Summary Recorders

Summary recorders update during the scenario and write one merged row at finalize.

| Type | Fields |
| --- | --- |
| `basic_summary` | `status`, `test_outcome`, `stop_condition`, `stop_reason`, `total_steps`, `final_sim_time_ms`, `wall_time_ms`, `job_id`, `params` |
| `min_ttc` | `min_ttc_s` |
| `max_speed` | `max_speed_mps` |

`basic_summary` is included by default as `run.*` unless `include_basic: false`.

## Built-in Metrics

Shared metric code lives in `simcore.metrics`.

Currently available:

- `compute_pair_ttc(objects, actor_id_a, actor_id_b)`

This is used by:

- `pair_ttc` frame recorder
- `pair_ttc` stop condition
- `min_ttc` summary recorder

## Extending Conditions

1. Create a condition class under `simcore/conditions/custom_conditions/`.
2. Inherit from `ConditionNode`.
3. Implement `put(data)`, `evaluate()`, and `reset()`.
4. Register it in `simcore/conditions/condition_registry.py`.

Use shared calculations from `simcore.metrics` when the same value is needed by conditions and recorders.

## Extending Logging

Choose recorder type based on output cardinality:

- Frame recorder: fixed columns, one row per logged frame.
- Table recorder: zero, one, or many rows per frame.
- Summary recorder: one scenario-level row written at finalize.

Register new recorders in the matching registry:

- `simcore/monitoring/frame_recorder_registry.py`
- `simcore/monitoring/recorder_registry.py`
- `simcore/monitoring/summary_recorder_registry.py`

## Design Notes

- Stop conditions do not depend on logging.
- Logging does not control scenario stop.
- Shared calculations belong in `simcore.metrics`.
- CSV schemas are fixed at reset time; unexpected fields raise an error.
- Multiple streams cannot share the same output filename.
- Collision data currently relies on simulator-provided collision fields.
