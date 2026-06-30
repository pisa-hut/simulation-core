# Prompt: update AV wrappers for v2 Observation

Update each AV wrapper to consume pisa-api `Observation { ego, agents }`. Remove every assumption
that ego is `observation[0]` or that non-ego identity equals a list index.

## Common behavior

- Read ego only from `observation.ego`.
- Treat `observation.agents` order as presentation order, never as identity.
- If an ObservedAgent has `tracking_id`, it may be used to retain wrapper-side actor state across
  steps. If absent, use stateless behavior or the AV system's own tracker.
- `entity_name` is optional privileged scenario information. Do not require it in normal mode.
- Consume `Shape.center` offset/reference metadata when converting bounding boxes; do not assume the
  kinematic pose is the box center.
- Reset all tracking state on every AV Reset.

## CARLA-agent and PCLA wrappers

- Replace `obs[0]`/`obs[1:]` with explicit ego/agent fields.
- Remove reflection over guessed fields (`id`, `object_id`, `track_id`, `external_id`, `name`) and
  remove index identity mode.
- When every relevant agent carries a tracking ID, key `_other_actors_by_key` by that ID, retain
  actors through presentation reorder, and remove actors no longer observed.
- Without tracking IDs, use the existing stateless destroy/recreate behavior. Never silently fall
  back to list position.

## Simple AV

- Use explicit ego and agent states; ignore identity fields unless a future algorithm needs them.
- Add a test showing that permuting agents does not change the selected lead vehicle/control.

## Autoware wrapper

- Adapt only the gRPC boundary in this change: explicit ego and agent states, shape offset honored.
- Continue publishing the current `DetectedObjects` topic and do not claim simulator tracking IDs
  are delivered into Autoware's tracking graph.
- Publishing `TrackedObjects` with UUID mapping and updating the launch/topic graph is a separate
  feature requiring dedicated integration validation.

## Tests and completion

- None-mode observations contain no usable simulator identity and do not trigger index tracking.
- Tracking-ID mode preserves wrapper-side actor identity across arbitrary presentation reorder.
- Full mode accepts entity names without requiring them.
- New/disappearing actors are created/removed correctly.
- Ego behavior is independent of any agent order.
- Run all wrapper tests against the breaking pisa-api release and update package/image pins.
