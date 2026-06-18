# Monitor

`Monitor` owns stop-condition evaluation and logging. Stop logic and logging are intentionally separate: logging never controls scenario stop.

## Runner Spec

```json
{
  "scenario": {
    "scenario_path": "/path/to/scenario",
    "stop_condition_config_path": "stop_conditions.yaml"
  },
  "monitor": {
    "config_path": "./docs/monitor/examples/logging_config_example.yaml"
  }
}
```

The current engine instantiates `simcore.monitor.Monitor` directly.

`monitor.config_path` points to reusable logging config. `scenario.stop_condition_config_path`
points to scenario-specific stop logic. Relative stop-condition paths are resolved under
the folder from `scenario.scenario_path`; absolute paths are used as-is. If
`scenario.stop_condition_config_path` is omitted, the engine uses
`stop_conditions.yaml` from the scenario folder when that file exists.

## Config Shape

Logging config:

```yaml
logging:
  enabled: true
  output_dir: monitor
  flush_every_n_rows: 100
  float_precision: 6
```

Stop condition config:

```yaml
- type: collision
  name: ego_collision
  outcome: Fail
  actor_id_a: 0
```

See [logging_config_example.yaml](examples/logging_config_example.yaml) and
[stop_condition_config_example.yaml](examples/stop_condition_config_example.yaml) for complete
examples.

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

## Stop Condition Delay

Every stop condition supports an optional simulation-time delay:

```yaml
- type: collision
  name: delayed_collision_guard
  outcome: Fail
  actor_id_a: 0
  delay_ms: 500
```

Supported delay keys are `delay_ms`, `delay_s`, and `delay_ns`; use only one per
condition. When the raw condition first triggers, the monitor latches that event
and waits for the configured amount of simulation time before reporting the stop.
The original trigger does not need to remain true during the delay. This is useful
for instantaneous events such as collisions as well as sustained threshold checks.

The final `run.stop_reason` includes the configured delay, the simulation time when
the delay started, the time when it completed, and the original trigger detail.

## Pair TTC

`pair_ttc` uses actor A as the ego/reference actor. By default it computes
longitudinal TTC in actor A's heading frame and ignores actors outside a lateral
corridor:

```yaml
- type: pair_ttc
  name: low_ttc_ego_to_agent_1
  outcome: Fail
  actor_id_a: 0
  actor_id_b: 1
  threshold_s: 1.5
  lateral_threshold_m: 2.0
```

The default calculation is:

```text
longitudinal_distance = dot(position_b - position_a, forward_a)
lateral_distance = dot(position_b - position_a, side_a)
closing_speed = forward_speed_a - forward_speed_b
TTC = longitudinal_distance / closing_speed
```

TTC is only valid when actor B is ahead of actor A, `abs(lateral_distance)` is
within `lateral_threshold_m`, and `closing_speed > 0`. This avoids false low-TTC
events when ego quickly overtakes a slower actor in an adjacent lane. Set
`lateral_threshold_m: null` to disable the lateral gate.

For the previous point-to-point radial closing behavior:

```yaml
- type: pair_ttc
  name: low_radial_ttc
  outcome: Fail
  actor_id_a: 0
  actor_id_b: 1
  threshold_s: 1.5
  mode: radial
```

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
      - type: pair_criticality
        name: ego_to_agent_1_criticality
        actor_id_a: 0
        actor_id_b: 1
```

Built-in frame recorders:

| Type | Fields |
| --- | --- |
| `ego_state` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` |
| `pair_ttc` | `distance_m`, `closing_speed_mps`, `ttc_s`; optional `longitudinal_distance_m`, `lateral_distance_m` |
| `pair_criticality` | `distance_m`, `longitudinal_distance_m`, `lateral_distance_m`, `closing_speed_mps`, `relative_longitudinal_speed_mps`, `relative_lateral_speed_mps`, `relative_longitudinal_acceleration_mps2`, `relative_lateral_acceleration_mps2`, `thw_s`, `drac_mps2` |

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
| `collision` | `collision` |
| `min_ttc` | `min_ttc_s` |
| `max_speed` | `max_speed_mps` |
| `numeric_summary` | Configurable `min`, `max`, `mean`, `std`, `count`, and optional extremum locations |

`basic_summary` is included by default as `run.*` unless `include_basic: false`.
The `collision` recorder accepts optional `actor_id_a` and `actor_id_b` filters.
Summary values are also retained in memory and attached to each concrete outcome,
so feedback-aware samplers do not need to parse frame logs or CSV files.

### Numeric Summary

`numeric_summary` aggregates one scalar source over all simulation steps. One
recorder may request multiple aggregations:

```yaml
logging:
  summary:
    recorders:
      - type: numeric_summary
        name: ego_deceleration
        source:
          type: kinematic
          actor_id: 0
          field: acceleration
        transforms: [negate, positive_part]
        aggregations: [max, mean, std]
        include_extrema_location: true

      - type: numeric_summary
        name: ego_to_agent_1_ttc
        source:
          type: pair_ttc
          field: ttc_s
          actor_id_a: 0
          actor_id_b: 1
          mode: longitudinal
          lateral_threshold_m: 2.0
        aggregations: [min, mean]

      - type: numeric_summary
        name: ego_to_agent_1_thw
        source:
          type: pair_criticality
          field: thw_s
          actor_id_a: 0
          actor_id_b: 1
        aggregations: [min]

      - type: numeric_summary
        name: ego_to_agent_1_drac
        source:
          type: pair_criticality
          field: drac_mps2
          actor_id_a: 0
          actor_id_b: 1
          lateral_threshold_m: 2.0
        aggregations: [max]
```

Available sources:

| Source | Required parameters | Fields |
| --- | --- | --- |
| `kinematic` | `actor_id`, `field` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` |
| `pair_ttc` | `actor_id_a`, `actor_id_b`, `field` | `ttc_s`, `distance_m`, `closing_speed_mps`, `longitudinal_distance_m`, `lateral_distance_m` |
| `pair_criticality` | `actor_id_a`, `actor_id_b`, `field` | `distance_m`, `longitudinal_distance_m`, `lateral_distance_m`, `closing_speed_mps`, `relative_longitudinal_speed_mps`, `relative_lateral_speed_mps`, `relative_longitudinal_acceleration_mps2`, `relative_lateral_acceleration_mps2`, `thw_s`, `drac_mps2` |
| `relative_position` | `source_actor_id`, `target_actor_id`, `field` | `relative_angle_deg`, `sector`, `distance_m`, `source_x`, `source_y`, `target_x`, `target_y`, `source_yaw_rad` |

`acc` is accepted as an alias for the canonical `acceleration` field. Available
transforms are `negate`, `abs`, and `positive_part`; they run in configured
order. Available aggregations are `min`, `max`, `mean`, and population standard
deviation `std`. Every recorder also outputs `count`.

When `include_extrema_location: true`, selected `min` and `max` aggregations add
`<aggregation>_step_index` and `<aggregation>_sim_time_ms`. Ties retain the first
location. Missing actors, unavailable metric results, nulls, NaN, and infinity
are skipped. With no valid samples, `count` is zero and other fields are empty.

## Built-in Metrics

Shared metric code lives in `simcore.metrics`.

Currently available:

- `compute_pair_ttc(objects, actor_id_a, actor_id_b)`
- `compute_pair_criticality(objects, actor_id_a, actor_id_b)`
- `compute_relative_position(objects, source_actor_id, target_actor_id)`

This is used by:

- `pair_ttc` frame recorder
- `pair_ttc` stop condition
- `min_ttc` summary recorder
- `pair_criticality` frame recorder
- `pair_criticality` numeric summary source

`pair_ttc` is collision-aware when runtime frames include simulator collision
events. A matching collision between `actor_id_a` and `actor_id_b` reports
`ttc_s = 0.0` even when actor center points are not colocated.
`pair_criticality` uses the same default lateral corridor width as longitudinal
TTC (`lateral_threshold_m: 2.0`) for THW and DRAC. Set
`lateral_threshold_m: null` to compute those values regardless of lateral offset.

For leading-vehicle braking, useful summary metrics are minimum THW
(`pair_criticality.thw_s`), maximum DRAC (`pair_criticality.drac_mps2`), minimum
TTC, and maximum ego deceleration. For cut-in scenarios, useful metrics include
minimum lateral/longitudinal gap, relative lateral speed, relative longitudinal
speed, minimum TTC, and collision.

## Extending Conditions

1. Create a condition class under `simcore/conditions/custom_conditions/`.
2. Inherit from `ConditionNode`.
3. Implement `put(data)`, `evaluate()`, and `reset()`.
4. Register it in `simcore/conditions/condition_registry.py`.

Use shared calculations from `simcore.metrics` when the same value is needed by conditions and recorders.

To expose a new scalar metric to `numeric_summary`, add a `NumericValueSource`
adapter in `summary_recorders/numeric_sources.py`, declare its allowed result
fields, validate metric-specific parameters in its constructor, and register it
in `SOURCE_BUILDERS`. Aggregation and CSV behavior then require no new recorder.

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
