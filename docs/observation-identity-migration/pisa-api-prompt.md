# Prompt: implement the breaking pisa-api observation identity contract

Implement the following coordinated breaking change in the `pisa-api` repository. Do not retain a
runtime fallback to the old `repeated ObjectState objects` contract.

## Proto contract

1. Add simulator-only identity messages:
   - `SimulatorObject { ObjectState state; optional string entity_name; }`
   - `SimulatorEgo { uint64 tracking_id; SimulatorObject object; }`
2. Replace `RuntimeFrame.objects` with:
   - explicit `SimulatorEgo ego`
   - `map<uint64, SimulatorObject> agents`
   Reserve the old field name and number. Preserve simulation time, collision, and extras.
3. Add `ActorRole { ACTOR_ROLE_UNSPECIFIED, EGO, AGENT }` and
   `ActorRef { uint64 tracking_id; optional string entity_name; ActorRole role; }`.
   Change `CollisionInfo.actor_a/actor_b` to optional/message-presence `ActorRef` values. Reserve
   the old scalar field numbers rather than reusing their wire encoding.
4. Add AV observation messages:
   - `ObservedAgent { ObjectState state; optional uint64 tracking_id; optional string entity_name; }`
   - `Observation { ObjectState ego; repeated ObservedAgent agents; }`
   The repeated agent order is explicitly non-identity-bearing.
5. Change AV Reset and Step requests to contain the new `Observation` message. Reserve old repeated
   observation field numbers.
6. Extend `Shape` with a local six-degree pose for the shape center relative to the
   `ObjectKinematic` pose, plus a string `reference_point`. Use a nested `Shape.CenterPose center`
   with `x/y/z/roll/pitch/yaw`.

## Python API

- Add frozen dataclasses and conversions for every new message.
- Use `Dict[int, SimulatorObjectData]` for agent maps and optional Python values for optional proto
  fields.
- Update both shared and simulator/AV conversion modules; avoid leaving duplicated conversions out
  of sync.
- Regenerate protobuf, type hint, and gRPC outputs using the repository's established generator.
- Export all new types through `pisa_api.simulator` and `pisa_api.av`.

## Invariants and validation

- Tracking IDs are episode-local; the API must not claim cross-reset stability.
- `entity_name` may be absent for dynamically created non-XOSC actors.
- Ego is semantically explicit; clients must never infer ego from a map/list position.
- Map order and repeated AV agent order must not be documented as actor identity.

## Tests and completion

- Round-trip RuntimeFrame ego, agent map, entity names, shapes, and structured collision refs.
- Round-trip AV observations with no identity, tracking ID only, and full identity.
- Assert optional presence is preserved rather than converted to zero/empty values.
- Assert generated descriptors reserve obsolete names/numbers.
- Run the complete pisa-api test and lint suites and publish the next coordinated breaking version.
