from types import SimpleNamespace

import pytest

from simcore.av_wrapper import AVWrapper
from simcore.runtime_actors import PreparedAgentObservation, PreparedObservation


class CopyField:
    def __init__(self) -> None:
        self.value = None

    def CopyFrom(self, value) -> None:
        self.value = value


class AgentEntry:
    def __init__(self) -> None:
        self.state = CopyField()
        self.tracking_id = None
        self.entity_name = None


class AgentEntries(list):
    def add(self) -> AgentEntry:
        entry = AgentEntry()
        self.append(entry)
        return entry


def test_copy_observation_populates_v2_proto_shape() -> None:
    ego = SimpleNamespace(name="ego-state")
    agent_state = SimpleNamespace(name="agent-state")
    observation = PreparedObservation(
        ego=ego,
        agents=(
            PreparedAgentObservation(
                state=agent_state,
                tracking_id=42,
                entity_name="CutInVehicle",
            ),
        ),
    )
    target = SimpleNamespace(ego=CopyField(), agents=AgentEntries())

    AVWrapper._copy_observation(target, observation)

    assert target.ego.value is ego
    assert target.agents[0].state.value is agent_state
    assert target.agents[0].tracking_id == 42
    assert target.agents[0].entity_name == "CutInVehicle"


def test_copy_observation_rejects_legacy_pisa_api() -> None:
    observation = PreparedObservation(ego=SimpleNamespace(), agents=())

    with pytest.raises(RuntimeError, match="does not provide the v2 Observation contract"):
        AVWrapper._copy_observation([], observation)
