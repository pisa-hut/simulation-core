from types import SimpleNamespace

import pytest

from simcore.conditions import ConditionCode
from simcore.conditions.custom_conditions.collision import CollisionCondition
from simcore.conditions.custom_conditions.kinematic_threshold import KinematicThresholdCondition
from simcore.monitoring.frame_recorders.pair_clearance import PairClearanceFrameRecorder
from simcore.monitoring.geometry import actor_box, actor_geometry
from simcore.monitoring.recorders.agent_geometry import AgentGeometryRecorder
from simcore.monitoring.recorders.agent_states import AgentStatesRecorder
from simcore.monitoring.recorders.collision_events import CollisionEventsRecorder
from simcore.monitoring.sample import MonitorSample
from simcore.runtime_actors import (
    EpisodeActorRegistry,
    RuntimeFrameContractError,
)


def state(x: float, *, shape=None):
    return SimpleNamespace(
        kinematic=SimpleNamespace(x=x, y=0.0, z=0.0, yaw=0.0, speed=0.0),
        shape=shape,
        type="car",
    )


def wrapped(entity_name: str | None, actor_state):
    return SimpleNamespace(entity_name=entity_name or "", state=actor_state)


def frame(*, agents, time_ns: int = 0, ego_id: int = 900):
    ego_object = wrapped("EgoVehicle", state(0.0))
    return SimpleNamespace(
        sim_time_ns=time_ns,
        ego=SimpleNamespace(tracking_id=ego_id, object=ego_object),
        agents=agents,
        collision=[],
        extras={},
    )


def test_registry_assigns_runner_ids_by_stable_entity_order_and_keeps_them() -> None:
    registry = EpisodeActorRegistry()
    first = registry.normalize(
        frame(
            agents={
                91: wrapped("Zulu", state(9.0)),
                44: wrapped("Alpha", state(4.0)),
            }
        )
    )

    assert first.ego.agent_id == 0
    assert first.agents[44].agent_id == 1
    assert first.agents[91].agent_id == 2

    second = registry.normalize(
        frame(
            time_ns=10,
            agents={
                44: wrapped("Alpha", state(5.0)),
                91: wrapped("Zulu", state(10.0)),
                77: wrapped("NewActor", state(7.0)),
            },
        )
    )
    assert second.agents[44].agent_id == 1
    assert second.agents[91].agent_id == 2
    assert second.agents[77].agent_id == 3


@pytest.mark.parametrize(
    ("visibility", "expected_ids", "expected_names"),
    [
        ("none", [None, None], [None, None]),
        ("tracking_id", [44, 91], [None, None]),
        ("full", [44, 91], ["Alpha", "Zulu"]),
    ],
)
def test_observation_identity_disclosure(visibility, expected_ids, expected_names) -> None:
    registry = EpisodeActorRegistry()
    normalized = registry.normalize(
        frame(
            agents={
                91: wrapped("Zulu", state(9.0)),
                44: wrapped("Alpha", state(4.0)),
            }
        )
    )

    observation = registry.prepare_observation(
        normalized,
        identity_visibility=visibility,
        observation_order="stable",
        shuffle_key="case-1",
    )

    assert [agent.tracking_id for agent in observation.agents] == expected_ids
    assert [agent.entity_name for agent in observation.agents] == expected_names
    assert [agent.state.kinematic.x for agent in observation.agents] == [4.0, 9.0]


def test_shuffle_order_is_reproducible() -> None:
    registry = EpisodeActorRegistry()
    normalized = registry.normalize(
        frame(
            time_ns=20,
            agents={index: wrapped(f"Actor{index}", state(float(index))) for index in range(8)},
        )
    )
    first = registry.prepare_observation(
        normalized,
        identity_visibility="tracking_id",
        observation_order="shuffle",
        shuffle_key="case-1",
    )
    second = registry.prepare_observation(
        normalized,
        identity_visibility="tracking_id",
        observation_order="shuffle",
        shuffle_key="case-1",
    )
    assert [item.tracking_id for item in first.agents] == [
        item.tracking_id for item in second.agents
    ]


def test_registry_rejects_tracking_id_reuse() -> None:
    registry = EpisodeActorRegistry()
    registry.normalize(frame(agents={5: wrapped("First", state(1.0))}))
    with pytest.raises(RuntimeFrameContractError, match="reused tracking ID"):
        registry.normalize(frame(agents={5: wrapped("Second", state(2.0))}, time_ns=10))


def test_geometry_applies_shape_center_and_yaw_offset() -> None:
    shape_data = SimpleNamespace(
        type="bounding_box",
        dimensions=(4.0, 2.0, 1.5),
        center=SimpleNamespace(x=2.0, y=1.0, z=0.5, yaw=0.25, pitch=0.0, roll=0.0),
        reference_point="carla_actor_origin",
    )
    actor = state(10.0, shape=shape_data)
    actor.kinematic.y = 5.0
    actor.kinematic.yaw = 0.0

    geometry = actor_geometry(actor)
    box = actor_box(actor)

    assert geometry.reference_point == "carla_actor_origin"
    assert geometry.center_offset_x == 2.0
    assert geometry.center_offset_y == 1.0
    assert box.center_x == 12.0
    assert box.center_y == 6.0
    assert box.yaw == 0.25


def test_collision_condition_matches_entity_name_across_tracking_ids() -> None:
    condition = CollisionCondition(
        {
            "type": "collision",
            "actor_a": {"role": "ego"},
            "actor_b": {"entity_name": "CutInVehicle"},
        }
    )
    collision = SimpleNamespace(
        occurred=True,
        actor_a=SimpleNamespace(tracking_id=800, entity_name="EgoVehicle", role="EGO"),
        actor_b=SimpleNamespace(tracking_id=991, entity_name="CutInVehicle", role="AGENT"),
    )
    collision.HasField = lambda name: hasattr(collision, name)
    condition.put((0, SimpleNamespace(collision=[collision]), None))

    result = condition.evaluate()

    assert result.code == ConditionCode.TRIGGERED
    assert "CutInVehicle" in result.detail


def test_kinematic_condition_resolves_entity_name_to_runner_actor() -> None:
    registry = EpisodeActorRegistry()
    target = state(4.0)
    target.kinematic.speed = 12.0
    normalized = registry.normalize(frame(agents={44: wrapped("TargetVehicle", target)}))
    condition = KinematicThresholdCondition(
        {
            "type": "kinematic_threshold",
            "agents": [{"entity_name": "TargetVehicle"}],
            "metric": "speed",
            "rule": "gt",
            "value": 10.0,
        }
    )

    condition.put((0, normalized, None))

    assert condition.evaluate().code == ConditionCode.TRIGGERED


def test_identity_columns_use_runner_id_and_preserve_simulator_identity() -> None:
    registry = EpisodeActorRegistry()
    normalized = registry.normalize(
        frame(agents={44: wrapped("CutInVehicle", state(4.0))})
    )
    recorder = AgentStatesRecorder({"type": "agent_states", "name": "states"})

    rows = recorder.record(MonitorSample(0, 0, normalized, None))

    assert rows[0].row["agent_id"] == 0
    assert rows[0].row["sim_tracking_id"] == 900
    assert rows[0].row["entity_name"] == "EgoVehicle"
    assert rows[0].row["is_ego"] is True
    assert rows[1].row["agent_id"] == 1
    assert rows[1].row["sim_tracking_id"] == 44
    assert rows[1].row["entity_name"] == "CutInVehicle"


def test_geometry_recorder_writes_each_late_actor_once() -> None:
    shape_data = SimpleNamespace(
        type="bounding_box",
        dimensions=(4.0, 2.0, 1.5),
        center=SimpleNamespace(x=1.0, y=0.0, z=0.5, yaw=0.0, pitch=0.0, roll=0.0),
        reference_point="esmini_object_reference_point",
    )
    registry = EpisodeActorRegistry()
    recorder = AgentGeometryRecorder({"type": "agent_geometry", "name": "geometry"})
    first = registry.normalize(frame(agents={44: wrapped("First", state(4.0, shape=shape_data))}))
    second = registry.normalize(
        frame(
            time_ns=10,
            agents={
                44: wrapped("First", state(5.0, shape=shape_data)),
                55: wrapped("Late", state(6.0, shape=shape_data)),
            },
        )
    )

    initial_rows = recorder.record(MonitorSample(0, 0, first, None))
    late_rows = recorder.record(MonitorSample(1, 10, second, None))

    assert [row.row["agent_id"] for row in initial_rows] == [0, 1]
    assert [row.row["agent_id"] for row in late_rows] == [2]
    assert late_rows[0].row["entity_name"] == "Late"
    assert late_rows[0].row["reference_point"] == "esmini_object_reference_point"
    assert late_rows[0].row["center_offset_x"] == 1.0


def test_pair_clearance_uses_shape_centers_instead_of_actor_origins() -> None:
    centered = SimpleNamespace(
        type="bounding_box",
        dimensions=(4.0, 2.0, 1.5),
        center=SimpleNamespace(x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0),
    )
    offset = SimpleNamespace(
        type="bounding_box",
        dimensions=(4.0, 2.0, 1.5),
        center=SimpleNamespace(x=2.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0),
    )
    registry = EpisodeActorRegistry()
    ego_state = state(0.0, shape=centered)
    runtime_frame = frame(agents={44: wrapped("Target", state(10.0, shape=offset))})
    runtime_frame.ego.object.state = ego_state
    normalized = registry.normalize(runtime_frame)
    recorder = PairClearanceFrameRecorder(
        {"type": "pair_clearance", "actor_id_a": 0, "actor_id_b": 1}
    )

    values = recorder.record(MonitorSample(0, 0, normalized, None))

    assert values["center_distance_m"] == 12.0
    assert values["longitudinal_clearance_m"] == 8.0


def test_collision_recorder_preserves_all_identity_layers() -> None:
    registry = EpisodeActorRegistry()
    runtime_frame = frame(agents={44: wrapped("CutInVehicle", state(4.0))})
    collision = SimpleNamespace(
        occurred=True,
        actor_a=SimpleNamespace(tracking_id=900, entity_name="EgoVehicle", role="EGO"),
        actor_b=SimpleNamespace(tracking_id=44, entity_name="CutInVehicle", role="AGENT"),
    )
    collision.HasField = lambda name: hasattr(collision, name)
    runtime_frame.collision = [collision]
    normalized = registry.normalize(runtime_frame)
    recorder = CollisionEventsRecorder(
        {
            "type": "collision_events",
            "actor_a": {"role": "ego"},
            "actor_b": {"entity_name": "CutInVehicle"},
        }
    )

    rows = recorder.record(MonitorSample(0, 0, normalized, None))

    assert len(rows) == 1
    assert rows[0].row["actor_a"] == 1
    assert rows[0].row["actor_b"] == 0
    by_tracking_id = {
        rows[0].row["actor_a_sim_tracking_id"]: rows[0].row["actor_a"],
        rows[0].row["actor_b_sim_tracking_id"]: rows[0].row["actor_b"],
    }
    assert by_tracking_id == {44: 1, 900: 0}
    assert rows[0].row["actor_a_entity_name"] == "CutInVehicle"
    assert rows[0].row["actor_b_entity_name"] == "EgoVehicle"
