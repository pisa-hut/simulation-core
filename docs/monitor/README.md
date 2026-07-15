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
  actor_a: {role: ego}
```

See [logging_config_example.yaml](examples/logging_config_example.yaml) and
[stop_condition_config_example.yaml](examples/stop_condition_config_example.yaml) for complete
examples.

## Actor Identity And Selector Resolution

Reusable monitor configuration selects actors by semantic identity:

```yaml
actor_a: {role: ego}
actor_b: {entity_name: CutInVehicle}
```

The entity name must exactly match the OpenSCENARIO `ScenarioObject` name. The processing path is:

1. `parse_actor_selector()` validates `role` or `entity_name` and
   `parse_actor_binding()` stores the selector when the config is loaded.
2. At each frame, `EpisodeActorRegistry` normalizes simulator tracking IDs into runner-local
   `agent_id` values.
3. `ActorBinding.resolve()` finds the current actor by role/entity name and returns its runner-local
   ID to TTC, relative-position, clearance, and numeric metric code.
4. Collision conditions compare the same selector directly against structured collision
   `ActorRef` role/entity-name fields.

The implementation is in `simcore/runtime_actors.py`. Simulator tracking IDs are only stable within
one reset episode and must not be placed in reusable condition files. Numeric `actor_id`,
`actor_id_a`, and `actor_id_b` forms remain only for compatibility with legacy frame/config tests;
new-contract configurations must use semantic selectors.

`role` currently supports only `ego`. Although the collision API also labels non-ego actors as
`AGENT`, `{role: agent}` is not a supported selector because it does not uniquely identify one
actor. Use `entity_name` for a specific non-ego XOSC actor. Legacy integer IDs select runner-local
`agent_id` values (`ego = 0`) and are not stable across resets or simulators. Simulator
`tracking_id` is recorded for diagnostics but is not accepted as a condition/metric selector.

Selector field names depend on the component:

| Component | Selector fields |
| --- | --- |
| One actor | `actor` |
| A set of actors | `actors` or `actors: any` |
| Unordered/symmetric pair | `actor_a`, `actor_b` |
| Directed pair | `source_actor`, `target_actor` |

Canonical monitor configs use `actor` terminology consistently:

```yaml
actor: {role: ego}
actors:
  - {role: ego}
  - {entity_name: CutInVehicle}
actor_a: {role: ego}
actor_b: {entity_name: CutInVehicle}
source_actor: {role: ego}
target_actor: {entity_name: CutInVehicle}
```

`agents`, `actor_ids`, `agent_ids`, `actor_id`, `agent_id`, `target`, and `target_agent`
are legacy compatibility aliases. Do not use them in new configuration. In particular,
`reach_target_position.target` means the actor being checked, not its destination; use `actor`
for identity and `target_position` for the destination coordinate.

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
outputs/my_task/concrete_result.jsonl
outputs/my_task/iteration_1/monitor/
outputs/my_task/iteration_2/monitor/
```

`concrete_result.jsonl` is an append-only index of terminal concrete results
(`finished`, `skipped`, and `abort`). The per-iteration `result.csv` files remain
the source of truth and retain retry history. On resume, the runner loads the JSONL
index once; when an iteration is missing, it falls back to that iteration's
`result.csv` and backfills the index. Existing terminal results replayed during a
resume are not appended again.

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
  actor_a: {role: ego}

- type: reach_target_position
  name: ego_reaches_goal
  outcome: Success
  actor: {role: ego}
  distance_threshold_m: 2.0
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
    actor_a: {role: ego}
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

## Reach Target Position

Use `actor` to select who is checked and `target_position` to specify where that actor must go.
For ego, omitting `target_position` reuses `scenario.goal_config.position` from the runner spec:

```yaml
- type: reach_target_position
  name: ego_reaches_scenario_goal
  outcome: Success
  actor: {role: ego}
  distance_threshold_m: 2.0
```

An explicit world coordinate can be written as named fields or as
`value: [x, y, z, heading, pitch, roll]`:

```yaml
- type: reach_target_position
  name: cutin_reaches_merge_point
  outcome: Success
  actor: {entity_name: CutInVehicle}
  target_position:
    type: WorldPosition
    x: 82.36
    y: -59.56
    z: 0.0
  distance_threshold_m: 1.0
```

A lane coordinate accepts named fields or `value: [road_id, lane_id, s, offset]`:

```yaml
target_position:
  type: LanePosition
  road_id: 12
  lane_id: -1
  s: 14.0
  offset: 1.92
```

Lane positions are converted through the configured OpenDRIVE map. The condition compares XY
distance only; Z and orientation do not affect triggering. Non-ego actors must always provide an
explicit `target_position`.

## Stop Condition Delay

Every stop condition supports an optional simulation-time delay:

```yaml
- type: collision
  name: delayed_collision_guard
  outcome: Fail
  actor_a: {role: ego}
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
  name: low_ttc_ego_to_cutin
  outcome: Fail
  actor_a: {role: ego}
  actor_b: {entity_name: CutInVehicle}
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
  actor_a: {role: ego}
  actor_b: {entity_name: CutInVehicle}
  threshold_s: 1.5
  mode: radial
```

## Kinematic Threshold

```yaml
- type: kinematic_threshold
  name: any_actor_y_too_large
  actors: any
  metric: y
  rule: gt
  value: [10.0, 0.0]

- type: kinematic_threshold
  name: cutin_z_out_of_range
  actors:
    - entity_name: CutInVehicle
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
  name: ego_is_straight_ahead_of_cutin
  source_actor: {entity_name: CutInVehicle}
  target_actor: {role: ego}
  direction: straight

- type: relative_position
  name: target_in_custom_angle_range
  source_actor: {entity_name: SourceVehicle}
  target_actor: {entity_name: TargetVehicle}
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
        name: ego_to_cutin
        actor_a: {role: ego}
        actor_b: {entity_name: CutInVehicle}
      - type: pair_criticality
        name: ego_to_cutin_criticality
        actor_a: {role: ego}
        actor_b: {entity_name: CutInVehicle}
```

Built-in frame recorders:

| Type | Fields |
| --- | --- |
| `ego_state` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` |
| `pair_ttc` | `distance_m`, `closing_speed_mps`, `ttc_s`, `ttc_valid`, `ttc_status`, `in_lateral_conflict`; optional `longitudinal_distance_m`, `lateral_distance_m` |
| `pair_criticality` | `distance_m`, `longitudinal_distance_m`, `lateral_distance_m`, `closing_speed_mps`, `relative_longitudinal_speed_mps`, `relative_lateral_speed_mps`, `relative_longitudinal_acceleration_mps2`, `relative_lateral_acceleration_mps2`, `thw_s`, `drac_mps2` |
| `pair_clearance` | `center_distance_m`, `clearance_m`, `longitudinal_clearance_m`, `lateral_clearance_m`, `clearance_status` |

### Table Recorders

Table recorders write their own CSV streams. They are for variable-cardinality data, sparse events, or one-frame-many-row output.

| Type | Output |
| --- | --- |
| `agent_states` | One row per agent per logged frame. |
| `agent_geometry` | Agent shape and dimensions from observations; defaults to one row per agent per concrete run. |
| `collision_events` | One row per matching collision event. |
| `control_commands` | One row per logged AV control command. |
| `scenario_events` | Generic scenario event timeline for start, collision, stop, and end events. |

Actor selectors should use semantic identity rather than runtime IDs. Pair recorders and conditions
accept `actor_a`/`actor_b` mappings such as `{role: ego}` and
`{entity_name: CutInVehicle}`. Simulator tracking IDs are episode-local and are not reusable monitor
configuration values.

`agent_states.csv` records runner-local `agent_id`, `sim_tracking_id`, `entity_name`, and `is_ego`.
`agent_geometry.csv` additionally records the bounding-box center/rotation offset from the
kinematic reference point. Geometry is written once for every actor, including actors first seen
after reset.

### Summary Recorders

Summary recorders update during the scenario and write one merged row at finalize.

| Type | Fields |
| --- | --- |
| `basic_summary` | `status`, `test_outcome`, `stop_condition`, `stop_reason`, `total_steps`, `final_sim_time_ms`, `wall_time_ms`, `job_id`, `sample_id`, `attempt`, `parameter_hash`, `params` |
| `collision` | `collision` |
| `min_ttc` | `min_ttc_s` |
| `max_speed` | `max_speed_mps` |
| `numeric_summary` | Configurable `min`, `max`, `mean`, `std`, `count`, and optional extremum locations |

`basic_summary` is included by default as `run.*` unless `include_basic: false`.
The `collision` recorder accepts optional semantic `actor_a` and `actor_b` filters.
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
          actor: {role: ego}
          field: acceleration
        transforms: [negate, positive_part]
        aggregations: [max, mean, std]
        include_extrema_location: true

      - type: numeric_summary
        name: ego_to_cutin_ttc
        source:
          type: pair_ttc
          field: ttc_s
          actor_a: {role: ego}
          actor_b: {entity_name: CutInVehicle}
          mode: longitudinal
          lateral_threshold_m: 2.0
        aggregations: [min, mean]

      - type: numeric_summary
        name: ego_to_cutin_thw
        source:
          type: pair_criticality
          field: thw_s
          actor_a: {role: ego}
          actor_b: {entity_name: CutInVehicle}
        aggregations: [min]

      - type: numeric_summary
        name: ego_to_cutin_drac
        source:
          type: pair_criticality
          field: drac_mps2
          actor_a: {role: ego}
          actor_b: {entity_name: CutInVehicle}
          lateral_threshold_m: 2.0
        aggregations: [max]
```

Available sources:

| Source | Required parameters | Fields |
| --- | --- | --- |
| `kinematic` | `actor`, `field` | `x`, `y`, `z`, `yaw`, `speed`, `acceleration`, `yaw_rate`, `yaw_acceleration` |
| `pair_ttc` | `actor_a`, `actor_b`, `field` | `ttc_s`, `distance_m`, `closing_speed_mps`, `longitudinal_distance_m`, `lateral_distance_m` |
| `pair_criticality` | `actor_a`, `actor_b`, `field` | `distance_m`, `longitudinal_distance_m`, `lateral_distance_m`, `closing_speed_mps`, `relative_longitudinal_speed_mps`, `relative_lateral_speed_mps`, `relative_longitudinal_acceleration_mps2`, `relative_lateral_acceleration_mps2`, `thw_s`, `drac_mps2` |
| `relative_position` | `source_actor`, `target_actor`, `field` | `relative_angle_deg`, `sector`, `distance_m`, `source_x`, `source_y`, `target_x`, `target_y`, `source_yaw_rad` |

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
events. A matching collision between the resolved `actor_a` and `actor_b` reports
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
