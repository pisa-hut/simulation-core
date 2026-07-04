# AV And Simulator Wrappers

`SimWrapper` and `AVWrapper` isolate gRPC communication from the engine. The engine owns lifecycle sequencing; wrappers own service calls, config loading, and protobuf request/response handling.

## Simulator Config

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

`Reset` receives the concrete output suffix and sampled params. Params are stringified before being sent to the simulator.

## AV Config

```json
{
  "av": {
    "url": "localhost:9083",
    "timeout": 100.0,
    "config_path": "/path/to/av.yaml",
    "output_path": "/mnt/output",
    "observation_identity": "none",
    "observation_order": "stable"
  }
}
```

The AV wrapper follows the simulator wrapper lifecycle. After reset, the runner records the initial simulator frame at `t=0`. On every loop iteration, the runner sends the simulator observation to AV and receives the next control command.

`observation_identity` controls privileged identity disclosure: `none` (default),
`tracking_id`, or `full` (tracking ID plus XOSC entity name). `observation_order` is
`stable` by default and may be set to `shuffle` to expose accidental list-position tracking while
remaining reproducible for the same run/sample.

Simulator frames contain an explicit ego and an unordered actor map. Stable AV presentation is
derived from entity name/tracking ID by sim-core; protobuf map iteration order is never used.

All simulator and AV implementations must follow the normative [Runtime Data Contracts](../data-contracts/README.md),
including coordinate handedness, SI units, timestamps, actor identity, and shape-center transforms.
Wire compatibility alone is not sufficient for a conforming wrapper.

## Loop Data Flow

After `sim.reset()` and `av.reset()`, `monitor.update(0, ...)` records the initial runtime frame. Within each later concrete simulation step:

1. `sim.step()` consumes the previous AV control command.
2. Simulator returns the next observation/runtime frame.
3. `av.step()` consumes the simulator observation and returns the next control command.
4. `monitor.update()` receives runtime frame and control command for condition/logging updates.

## Stop And Cleanup

During engine shutdown, `close()` calls wrapper stop methods. Stop failures are logged as warnings so cleanup does not hide the primary execution result.

## Startup Errors

Wrapper initialization can raise `ScenarioExecutionError`. The engine records startup errors as execution `error` and closes initialized components.
