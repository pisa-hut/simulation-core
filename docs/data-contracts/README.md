# PISA Runtime Data Contracts

This document is the normative interoperability contract for scenario-based testing between
simulator wrappers, sim-core, AV wrappers, and monitor consumers. It supplements the protobuf
schema: protobuf defines the wire fields, while this document defines their units, frames,
identity, lifecycle, and validity semantics.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative. A component that does
not satisfy a **MUST** is not contract-compatible even if protobuf deserialization succeeds.

## 1. Common Coordinate And Numeric Contract

All components MUST expose data to PISA in the following canonical convention. A simulator may
use a different native convention internally, but its wrapper MUST convert at the boundary.

| Quantity | Unit and convention |
| --- | --- |
| Position and distance | metre (`m`) |
| Time | integer nanosecond (`ns`) on RPC/frame fields; seconds only where a config field explicitly ends in `_s` |
| Linear speed | metres per second (`m/s`) |
| Linear acceleration | metres per second squared (`m/s^2`) |
| Angle | radian (`rad`) unless a field explicitly ends in `_deg` |
| Angular rate | radians per second (`rad/s`) |
| Angular acceleration | radians per second squared (`rad/s^2`) |
| World frame | right-handed Cartesian frame, `+z` up |
| Actor-local frame | `+x` forward, `+y` left, `+z` up |
| Positive yaw | counter-clockwise from `+x` toward `+y`, viewed from `+z` |
| Euler rotation order | intrinsic roll about local `x`, pitch about local `y`, yaw about local `z`; use rotation composition rather than component-wise addition for 3-D transforms |

All floating-point values that are required for a calculation MUST be finite. `NaN` and infinity
MUST NOT be used to mean unavailable. Most protobuf scalar fields do not carry presence, so a
numeric zero is a real value, not a missing-value marker. Optional message presence, an omitted
optional field, or a documented status field must represent unavailability.

World positions from every simulator MUST refer to the same map/world coordinate system used by
the scenario and map delivered at `Init`. Wrappers MUST NOT publish native screen, Unreal, sensor,
or geodetic coordinates without conversion. In particular, native handedness and yaw-sign
differences MUST be normalized before creating an `ObjectState`.

## 2. Simulator-Side Contract

### 2.1 Lifecycle And timestamps

`Init.dt` is in seconds. `ResetResponse.frame` is the initial state and MUST represent simulation
time zero. Each `StepRequest.timestamp_ns` is the requested absolute simulation timestamp, not a
wall-clock time or step duration. The returned frame MUST describe the state for that timestamp.

For every frame:

- `RuntimeFrame.sim_time_ns` MUST equal the state time represented by the frame.
- Every `ObjectKinematic.time_ns` MUST equal `RuntimeFrame.sim_time_ns`.
- Timestamps MUST be monotonic within an episode and restart at zero after `Reset`.
- A repeated run with the same scenario, parameters, seeds, configuration, and control sequence
  SHOULD produce the same values and actor presentation.

The runner currently advances timestamps by `dt` and expects the reset frame at `0 ns`.

### 2.2 RuntimeFrame structure

The simulator MUST populate exactly one explicit `RuntimeFrame.ego`. Non-ego actors MUST be in the
`RuntimeFrame.agents` map. Ego MUST NOT also appear in `agents`.

The `agents` map key and `ego.tracking_id` are simulator tracking IDs. Map/list iteration order has
no identity semantics. A consumer MUST NOT associate observations across frames by position in a
collection.

For each actor, `ObjectState` has:

- `type`: `RoadObjectType` classification;
- `kinematic`: pose and motion at the current frame timestamp;
- optional `shape`: geometry relative to the kinematic reference point.

### 2.3 Actor identity

There are three distinct ID/name domains and they MUST NOT be conflated:

| Identity | Scope | Required behavior |
| --- | --- | --- |
| `tracking_id` (`uint64`) | One simulator episode/reset | Unique among all current and previously seen actors; stable for the lifetime of that actor; MUST NOT be reused for a different actor before the next reset |
| `entity_name` | Scenario definition | Exact XOSC `ScenarioObject.name`; unique within the scenario; stable across frames and simulator implementations when the XOSC actor exists |
| runner `agent_id` | One runner episode | Assigned by sim-core; ego is `0`, other actors receive increasing IDs; simulator and AV MUST NOT generate or depend on it |

`entity_name` SHOULD be present for every actor originating from an XOSC `ScenarioObject`.
Dynamically created actors without an XOSC identity MAY omit it. Names are case-sensitive and MUST
not be rewritten, localized, or replaced with a simulator actor ID.

Sim-core rejects duplicate entity names, an ego duplicated in `agents`, and tracking-ID reuse with
a different identity. A simulator tracking ID is not suitable in reusable condition configuration.

### 2.4 Kinematic reference point

`ObjectKinematic.(x,y,z,yaw)` is the world pose of the actor's declared **reference point**. It is
not necessarily the bounding-box center, rear axle, vehicle center, or XOSC reference point.
Simulator wrappers MUST keep this reference point stable over the actor lifetime.

`Shape.reference_point` MUST identify what the kinematic origin represents. Recommended stable
values are implementation-qualified strings such as `carla_actor_origin` and
`esmini_object_reference_point`. The string is descriptive metadata; geometry conversion MUST use
`Shape.center`, not branch on this string.

`ObjectKinematic` scalar meanings are:

| Field | Meaning |
| --- | --- |
| `x`, `y`, `z` | World position of the kinematic reference point, metres |
| `yaw` | Reference-frame heading in canonical radians |
| `speed` | Signed longitudinal speed along actor-local `+x`, `m/s` |
| `acceleration` | Signed longitudinal acceleration along actor-local `+x`, `m/s^2` |
| `yaw_rate` | Positive counter-clockwise yaw rate, `rad/s` |
| `yaw_acceleration` | Positive counter-clockwise yaw acceleration, `rad/s^2` |

Wrappers MUST document any actor category for which signed longitudinal speed/acceleration cannot
be supplied. They MUST NOT silently substitute total 3-D velocity magnitude if reverse motion is
possible, because that loses sign.

### 2.5 Shape and bounding-box center

`Shape.center` is a relative transform **from the kinematic reference frame to the shape center**.
Its translation is expressed in the actor-local reference frame, not the world frame:

- `center.x`: forward offset;
- `center.y`: left offset;
- `center.z`: upward offset;
- `center.roll/pitch/yaw`: shape-frame rotation relative to the kinematic frame, in radians.

For `BOUNDING_BOX`, `Shape.dimensions` contains full extents:

- `dimensions.x`: length along shape-local `+x`;
- `dimensions.y`: width along shape-local `+y`;
- `dimensions.z`: height along shape-local `+z`.

Dimensions MUST be positive, finite metres. They are not half-extents. A centered box MUST still
populate `center` with a zero transform so its meaning is explicit.

Let the kinematic world pose be translation `p_actor` and rotation `R_actor`, and the center
relative pose be `o_center` and `R_offset`. The only valid general transform is:

```text
p_box = p_actor + R_actor * o_center
R_box = R_actor * R_offset
p_corner_world = p_box + R_box * p_corner_local
```

For a box, `p_corner_local` is each combination of:

```text
(+/- length/2, +/- width/2, +/- height/2)
```

For a 2-D top-down plot with actor pose `(x, y, yaw)` and center offset `(ox, oy, yaw_offset)`:

```text
center_x = x + ox*cos(yaw) - oy*sin(yaw)
center_y = y + ox*sin(yaw) + oy*cos(yaw)
box_yaw  = yaw + yaw_offset

corner_x = center_x + local_x*cos(box_yaw) - local_y*sin(box_yaw)
corner_y = center_y + local_x*sin(box_yaw) + local_y*cos(box_yaw)
```

The simple `box_yaw` addition is valid for the current planar calculation. A 3-D implementation
MUST compose rotation matrices or quaternions; it MUST NOT generally add Euler components.

For `POLYGON`, `Shape.vertices` MUST be finite points in the shape-local coordinate frame, relative
to `Shape.center`, and MUST be ordered around the boundary without self-intersection. Consumers
transform each vertex using the same `p_box + R_box * vertex` equation. A component profile MUST
state whether a closed polygon repeats its first vertex; PISA's recommended form does not repeat it.

### 2.6 Shape lifecycle

Shape is actor-static metadata. It MUST be supplied on the reset frame for all initial actors and
on the first frame containing a newly appearing actor. It SHOULD remain present and identical on
later frames; omission after first observation is allowed only when the receiver has already
cached it. If supplied again, it MUST be bitwise-equivalent or numerically equivalent within the
component's documented tolerance.

An actor must not first appear without shape and gain a shape later when monitor geometry logging
uses `once: true`; the first observation is the authoritative geometry record.

### 2.7 CollisionInfo

`CollisionInfo.actor_a` and `actor_b` are `ActorRef` values, never collection indices and never
runner `agent_id` values. Each reference MUST use the same episode-local `tracking_id` namespace as
`RuntimeFrame.ego/agents`. When available, it MUST also contain the exact `entity_name` and role.

Collision pair order has no semantic direction. Consumers may match `(A,B)` or `(B,A)`. A reported
collision MUST set `occurred=true`; details and contact information belong in `details` using a
simulator-specific, documented schema.

## 3. AV-Side Contract

### 3.1 Observation structure and ordering

`Observation.ego` is explicit and MUST be treated as ego. `Observation.agents` contains only
non-ego actors. Its list order is presentation only and MUST NOT be used as persistent identity.
The number, order, and membership of agents may change at any frame.

The AV must support the configured identity visibility:

| `av.observation_identity` | `ObservedAgent.tracking_id` | `ObservedAgent.entity_name` |
| --- | --- | --- |
| `none` | absent | absent |
| `tracking_id` | present | absent |
| `full` | present | present when simulator supplied it |

Presence matters: because these fields are optional, an absent ID is not ID zero and an absent
name is not an empty-name identity. Ego identity is structural and is not exposed through an
`ObservedAgent` wrapper.

`av.observation_order=stable` gives deterministic presentation sorted by entity name and then
tracking ID. `shuffle` gives deterministic per-frame shuffling for robustness tests. Neither mode
changes the contract: AV behavior MUST NOT accidentally depend on list position. When identity is
hidden, an AV may run its own perception/tracking, but must not receive simulator identity through
another undocumented channel.

### 3.2 State and geometry interpretation

AV MUST interpret `ObjectState.kinematic`, `Shape.center`, dimensions, vertices, frames, signs, and
units exactly as defined in Sections 1 and 2. AV MUST NOT assume `kinematic.(x,y)` is the box center
unless the center offset is zero. AV collision prediction using center positions without applying
the offset is contract-incompatible.

If AV converts observations into another internal coordinate system, conversion must be applied
consistently to position, yaw, rates, shape-center offset, shape orientation, and polygon vertices.
Converting only position or only yaw is invalid.

### 3.3 Reset and step behavior

`ResetRequest.initial_observation` is the state at simulation time zero and establishes the new
episode. AV MUST clear episode-local tracking and cached geometry at reset. It MUST return a control
command applicable to the first simulator step.

Each `StepRequest.timestamp_ns` is the absolute simulation timestamp of `observation`. AV MUST use
simulation timestamps, not message arrival or wall-clock time, for deterministic state estimation.
AV SHOULD produce identical controls for identical reset data, observations, timestamps,
configuration, and random seeds.

### 3.4 Canonical control contract

Control mode is selected by the AV on each returned `CtrlCmd`; it is not negotiated or fixed at
`Init`. An AV MAY use either supported mode and MAY change between supported modes during an
episode. A simulator wrapper MUST interpret both modes according to this section or fail explicitly
when it receives a mode it does not support.

The current wire representation remains `CtrlCmd.mode` plus `google.protobuf.Struct payload`.
Despite the untyped payload, field names and meanings are defined by sim-core and MUST NOT be
privately redefined by an AV/simulator pair. `NONE` is permitted as an explicit no-op. The only
action-producing modes currently in the canonical contract are `THROTTLE_STEER_BREAK` and
`ACKERMANN`. `TRAJECTORY`, `THROTTLE_STEER`, `WAYPOINTS`, and `POSITION` are legacy/reserved and
MUST NOT be emitted in a conforming scenario test.

The enum name `THROTTLE_STEER_BREAK` contains a historical spelling error. It remains the required
wire enum until a future protobuf migration; the payload field is correctly spelled `brake`.
`break` is not a conforming payload alias.

#### THROTTLE_STEER_BREAK

The payload MUST contain exactly these canonical action fields:

| Field | Unit/range | Meaning |
| --- | --- | --- |
| `throttle` | finite scalar in `[0, 1]` | Requested propulsion fraction |
| `brake` | finite scalar in `[0, 1]` | Requested service-brake fraction |
| `steer` | finite scalar in `[-1, 1]` | Normalized steering command; positive means left, negative means right |

All three fields are required. If both throttle and brake are positive, brake has priority and the
simulator MUST apply no positive propulsion for that command. AV implementations SHOULD normally
set throttle to zero while braking. Simulator wrappers MUST convert steering sign and scale to the
native simulator convention; they MUST NOT expose a native CARLA/esmini sign convention at the
PISA boundary. Values outside the canonical range are invalid and SHOULD cause an explicit error,
not silent clipping.

Example:

```text
mode = THROTTLE_STEER_BREAK
payload = {"throttle": 0.25, "brake": 0.0, "steer": -0.1}
```

#### ACKERMANN

The current canonical payload follows the field names already produced by the AV wrappers and
consumed by the simulator wrappers:

| Field | Requirement | Unit and meaning |
| --- | --- | --- |
| `steer` | required | Finite road-wheel steering angle in radians; positive means left |
| `speed` | required | Finite target forward speed in `m/s`, greater than or equal to zero |
| `steer_speed` | optional, default `0` | Finite non-negative steering-angle rate limit in `rad/s`; zero requests the implementation default/immediate behavior |
| `acceleration` | optional | Finite signed longitudinal acceleration target/limit in `m/s^2`; positive accelerates forward |
| `jerk` | optional | Finite longitudinal jerk target/limit in `m/s^3` |

`steer` is a physical angle, unlike normalized `THROTTLE_STEER_BREAK.steer`. The simulator wrapper
MUST convert it into its native Ackermann representation or into native low-level actuation while
preserving the requested target semantics. Simulator-specific controller gains, saturation limits,
and defaults for omitted optional fields MUST be documented in simulator configuration because
they can affect cross-simulator equivalence. A wrapper MUST NOT reinterpret `steer` as normalized
`[-1,1]` input.

Example:

```text
mode = ACKERMANN
payload = {
  "steer": 0.12,
  "steer_speed": 0.4,
  "speed": 8.0,
  "acceleration": 1.5,
  "jerk": 0.0
}
```

The ACKERMANN payload MUST NOT use alternate camelCase names or normalized steering values.
Unknown modes, unknown action fields, missing required fields, non-numeric/non-finite values, and
invalid ranges are contract violations. At present the runner forwards the protobuf command and
simulator wrappers perform most validation/conversion. Central sim-core validation and typed
protobuf `oneof` control messages are future work; this does not permit components to deviate from
the contract above.

## 4. Sim-Core Contract

Sim-core is the trust boundary between privileged simulator frames and AV-visible observations.
For each reset it:

1. clears the episode actor registry;
2. validates explicit ego, tracking-ID uniqueness/reuse, and entity-name uniqueness;
3. assigns runner-local `agent_id=0` to ego and increasing IDs to newly observed non-ego actors;
4. preserves the full normalized frame for monitor;
5. removes or includes privileged identity according to `observation_identity`;
6. presents agents in the configured deterministic order.

Runner-local IDs are convenience keys for one concrete execution only. Conditions SHOULD select
actors by `{role: ego}` or `{entity_name: ...}`. Reusable configuration MUST NOT contain simulator
tracking IDs or runner IDs.

Sim-core currently validates identity structure but does not yet reject every non-finite,
dimension, timestamp, or unit violation described here. Simulator conformance tests remain
required; successful runner execution alone is not proof of contract compliance.

## 5. Monitor And Analysis Contract

### 5.1 State/geometry join

`agent_states.csv` is a long table with one row per observed actor per recorded frame.
`agent_geometry.csv` records static shape information once per actor by default, including actors
first seen after reset.

Analysis within one concrete execution SHOULD join state and geometry by runner `agent_id`.
Cross-simulator or cross-run analysis SHOULD match by `entity_name`, falling back to tracking ID
only within the same episode when no name exists. Row order MUST NOT be used for joining.

Relevant columns and units are:

| File/column | Meaning |
| --- | --- |
| `agent_states.step_index` | Zero-based runner update index |
| `agent_states.sim_time_ms` | Simulation time in milliseconds |
| `agent_states.x/y/z` | Kinematic reference-point world position, metres |
| `agent_states.yaw` | Canonical yaw, radians |
| `agent_states.speed` | Signed longitudinal speed, `m/s` |
| `agent_states.acceleration` | Signed longitudinal acceleration, `m/s^2` |
| `agent_geometry.length_m/width_m/height_m` | Full shape dimensions, metres |
| `agent_geometry.center_offset_*` | Shape center relative to kinematic reference, actor-local metres |
| `agent_geometry.*_offset` | Relative shape rotation, radians |

CSV numeric formatting is decimal text with `logging.float_precision`; empty cells mean unavailable.
`sim_time_ms` is derived as `sim_time_ns / 1e6`. Consumers MUST parse by column name, not position.

To draw a trajectory box, select the actor's geometry record, take each state row's `(x,y,yaw)`,
and apply the formulas in Section 2.5. Drawing a rectangle centered directly at `(x,y)` is correct
only when both center offsets are zero.

### 5.2 Metric frames

Pair TTC and pair criticality use actor A as the reference frame and actor B as the target. They are
directional: swapping A and B can change or invalidate the result. Relative position similarly
uses `source_actor` as the reference pose and locates `target_actor` in its frame. Collision actor
pairs are unordered.

Current planar monitor geometry applies center `x/y` offsets rotated by actor yaw and adds the
shape yaw offset. Collision estimates and pair clearance are 2-D and do not apply `z`, roll, or
pitch.

### 5.3 Known implementation gap

The current pisa-api shape schema exposes polygon points as `Shape.vertices`, but the current
monitor `footprint_json` extraction still looks for the older `shape.footprint` representation.
Therefore polygon vertices are not reliably exported to `agent_geometry.csv` yet. Bounding-box
dimensions and center offsets are exported correctly. Until this gap is fixed, analysis MUST use
the bounding box for monitor-derived geometry and MUST NOT treat an empty `footprint_json` as proof
that the simulator supplied no polygon.

## 6. Conformance Checklist

### Simulator wrapper

- Reset frame and all object timestamps agree and start at zero.
- Canonical metres/radians/right-handed coordinates are verified with known poses.
- Ego is explicit and absent from `agents`.
- Tracking IDs are unique, stable, and never list indices.
- XOSC names are exact and stable.
- Shape center offsets are actor-local and dimensions are full extents.
- Geometry is present on first actor observation and remains invariant.
- Collision references use simulator tracking IDs plus semantic metadata.
- Repeated seeded runs produce equivalent frames and ordering.
- Both canonical action modes use the documented fields, units, sign, and brake-priority behavior.
- Native control conversion and simulator-specific Ackermann limits/defaults are documented.

### AV wrapper/agent

- Handles agent count and order changes without positional identity assumptions.
- Honors all identity visibility modes and optional-field presence.
- Clears identity/geometry caches on reset.
- Applies the same coordinate and shape transforms as the simulator contract.
- Uses simulation timestamps for estimation and deterministic behavior.
- Emits only canonical `THROTTLE_STEER_BREAK`, `ACKERMANN`, or explicit `NONE` commands.
- Uses the exact canonical payload names, units, ranges, and steering sign.

### Monitor/analysis

- Joins per-frame state to static geometry by identity, never row order.
- Uses entity name across runs/simulators and episode IDs only as fallback.
- Applies center and yaw offsets before drawing or clearance calculations.
- Treats A/B metrics as directional and collision pairs as unordered.
- Accounts for the current polygon-export limitation.
