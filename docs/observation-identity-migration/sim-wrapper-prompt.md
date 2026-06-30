# Prompt: update simulator wrappers for explicit actor identity

Implement the new pisa-api RuntimeFrame contract in each simulator wrapper. The wrapper must return
an explicit ego and an unordered non-ego map; do not populate legacy ordered object lists or encode
parallel IDs in `extras`.

## Common requirements

- Use the simulator's native unsigned actor/object ID as `tracking_id`.
- Guarantee that an ID is stable and unique within one reset episode and is never reused for a
  different actor during that episode.
- Populate `entity_name` only with the actual XOSC `ScenarioObject` name. Do not treat duplicate
  generic labels such as `background` as entity names.
- Return shape on reset and every step. Populate `Shape.center` with the local center
  offset/rotation, include dimensions, and set a source-specific `reference_point` label.
- Populate `CollisionInfo.actor_a/b` as structured ActorRefs containing tracking ID, entity name
  when available, and role. Do not translate collision actors into list indexes.
- Actor additions and removals must be reflected in the current frame map.

## CARLA wrapper

- Use `actor.id` as tracking ID and the scenario actor's unique `role_name` as XOSC entity name.
- Use the existing `_ego_vehicle` reference for explicit ego.
- Stop sorting actors for identity purposes. Deterministic AV presentation is owned by sim-core.
- Convert `actor.bounding_box.extent * 2` to dimensions.
- Record `bounding_box.location` as center offset relative to `actor.get_transform()` and
  `bounding_box.rotation` as rotation offset. Apply the wrapper's CARLA-left-handed to PISA
  coordinate conversion to local Y and yaw as well as world pose.
- Set `reference_point = "carla_actor_origin"`.
- Remove `object_index_by_actor_id` and index-based collision conversion. Preserve native CARLA IDs
  in collision details only as optional diagnostics, not as a second identity system.

## esmini wrapper

- Use `SE_GetId(index)` as tracking ID and bind `SE_GetObjectName(object_id)` for entity name.
- Use the wrapper's externally controlled object as explicit ego; document how it is selected
  internally instead of exposing a first-list-item contract.
- Refresh the current object ID set each frame so AddEntity/DeleteEntity actions are represented.
- Use `SE_ScenarioObjectState.centerOffsetX/Y/Z` as shape center offset, dimensions from
  length/width/height, zero relative rotation, and
  `reference_point = "esmini_object_reference_point"`.
- Remove `extras.object_ids`; esmini collision APIs already return native object IDs and should feed
  ActorRefs directly.

## Tests and completion

- Reset frame contains explicit ego and all non-ego map entries with names and shapes.
- Reordered simulator enumeration produces the same actor IDs/names.
- Add/remove actor actions update the map without ID reuse.
- Non-zero CARLA/esmini shape center offsets survive conversion.
- Collision refs identify the same actors regardless of enumeration order.
- Run each wrapper's unit/integration suite against the breaking pisa-api release and update its
  image/package pin.
