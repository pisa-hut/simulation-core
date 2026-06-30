# Observation identity migration

This directory is the handoff contract for the coordinated breaking change across PISA API,
simulator wrappers, AV wrappers, and sim-core. The prompts are intentionally self-contained so
they can be given directly to Codex agents responsible for the other repositories.

## Contract implemented by sim-core

- A simulator frame has one explicit ego and an unordered map of non-ego actors keyed by a
  simulator tracking ID.
- A tracking ID is an unsigned 64-bit value, unique and stable for one reset episode, and is not
  reused after an actor disappears.
- `entity_name` is the OpenSCENARIO `ScenarioObject` name when one exists. It is the reusable
  selector used by monitor configuration. Runtime tracking IDs are not valid reusable selectors.
- sim-core assigns its own `agent_id`: ego is `0`; non-ego actors receive monotonically increasing
  IDs on first observation in deterministic entity-name order.
- `av.observation_identity` is `none`, `tracking_id`, or `full`. The default is `none`.
- `av.observation_order` is `stable` or `shuffle`. The default is `stable`. Stable order is entity
  name first and simulator tracking ID second. Shuffle is deterministic for a run/sample/time.
- Shapes remain present in every simulator frame and every AV observation. CSV recording is
  deduplicated per actor.
- Shape position is not assumed to equal the kinematic reference point. `Shape.center`
  describes the local transform from the kinematic object origin to the shape center.

## Runner outputs

`agent_states.csv` includes `agent_id`, `sim_tracking_id`, `entity_name`, and `is_ego`.
`agent_geometry.csv` includes the same identity columns plus dimensions, reference-point label,
shape-center offset, and rotation offset. `collision_events.csv` records runner IDs, simulator
tracking IDs, and entity names for both actors.

## Recommended implementation order

1. Implement and release the breaking pisa-api contract.
2. Update simulator wrappers to produce the contract.
3. Update AV wrappers to consume the contract.
4. Pin sim-core and all images to the new pisa-api release, then run the cross-wrapper matrix.

There is no compatibility fallback for production traffic. A missing v2 Observation message must
fail clearly instead of silently rebuilding identities from list positions.
