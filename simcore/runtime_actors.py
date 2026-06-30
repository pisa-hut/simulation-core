from __future__ import annotations

import hashlib
import logging
import random
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


class RuntimeFrameContractError(ValueError):
    """Raised when a simulator frame violates the actor identity contract."""


@dataclass(frozen=True)
class ActorSnapshot:
    agent_id: int
    sim_tracking_id: int
    entity_name: str | None
    is_ego: bool
    state: Any

    @property
    def actor_id(self) -> int:
        """Runner-local ID used by existing metric code."""

        return self.agent_id

    @property
    def kinematic(self) -> Any:
        return getattr(self.state, "kinematic", self.state)

    @property
    def shape(self) -> Any | None:
        return getattr(self.state, "shape", None)

    @property
    def type(self) -> Any:
        return getattr(self.state, "type", None)


@dataclass(frozen=True)
class PreparedAgentObservation:
    state: Any
    tracking_id: int | None = None
    entity_name: str | None = None


@dataclass(frozen=True)
class PreparedObservation:
    ego: Any
    agents: tuple[PreparedAgentObservation, ...]


@dataclass(frozen=True)
class NormalizedRuntimeFrame:
    sim_time_ns: int
    ego: ActorSnapshot
    agents: Mapping[int, ActorSnapshot]
    collision: Any
    extras: Any
    source: Any

    @property
    def objects(self) -> tuple[ActorSnapshot, ...]:
        """Compatibility collection with explicit IDs; order has no identity semantics."""

        return (self.ego, *self.agents.values())


@dataclass(frozen=True)
class ActorSelector:
    role: Literal["ego"] | None = None
    entity_name: str | None = None

    def matches(self, actor: ActorSnapshot) -> bool:
        if self.role == "ego":
            return actor.is_ego
        return self.entity_name is not None and actor.entity_name == self.entity_name


@dataclass(frozen=True)
class ActorBinding:
    selector: ActorSelector | None = None
    runner_id: int | None = None

    def resolve(self, frame: Any) -> int | None:
        if self.selector is None:
            return self.runner_id
        actor = find_actor_by_selector(frame, self.selector)
        return actor.agent_id if actor is not None else None

    @property
    def label(self) -> str:
        if self.selector is not None:
            return self.selector.role or self.selector.entity_name or "unknown"
        return str(self.runner_id)


def parse_actor_binding(
    config: Mapping[str, Any],
    *,
    selector_key: str,
    legacy_keys: tuple[str, ...] = (),
) -> ActorBinding:
    if selector_key in config:
        return ActorBinding(
            selector=parse_actor_selector(config[selector_key], field_name=selector_key)
        )
    for key in legacy_keys:
        if key in config:
            if isinstance(config[key], str) and config[key].strip().lower() == "ego":
                return ActorBinding(runner_id=0)
            try:
                return ActorBinding(runner_id=int(config[key]))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a runner actor ID") from exc
    expected = ", ".join((selector_key, *legacy_keys))
    raise ValueError(f"missing actor selector; expected one of: {expected}")


@dataclass(frozen=True)
class CollisionActorRef:
    tracking_id: int
    entity_name: str | None
    is_ego: bool

    @property
    def label(self) -> str:
        if self.is_ego:
            return "ego"
        if self.entity_name is not None:
            return self.entity_name
        return str(self.tracking_id)


def collision_actor_ref(value: Any) -> CollisionActorRef:
    if isinstance(value, (int, str)):
        return CollisionActorRef(int(value), None, int(value) == 0)
    tracking_id = _required_int_attr(value, "tracking_id")
    entity_name = _optional_name(value)
    role = getattr(value, "role", None)
    role_name = str(getattr(role, "name", role)).lower()
    is_ego = bool(getattr(value, "is_ego", False)) or role_name in {"ego", "1"}
    return CollisionActorRef(tracking_id, entity_name, is_ego)


def selector_matches_ref(selector: ActorSelector, ref: CollisionActorRef) -> bool:
    if selector.role == "ego":
        return ref.is_ego
    return selector.entity_name is not None and selector.entity_name == ref.entity_name


def parse_actor_selector(value: Any, *, field_name: str) -> ActorSelector:
    if isinstance(value, str):
        if value.strip().lower() == "ego":
            return ActorSelector(role="ego")
        if value.strip():
            return ActorSelector(entity_name=value.strip())
    if isinstance(value, Mapping):
        role = value.get("role")
        entity_name = value.get("entity_name")
        if role is not None and entity_name is not None:
            raise ValueError(f"{field_name} must contain exactly one actor selector")
        if role is not None:
            if str(role).lower() != "ego":
                raise ValueError(f"{field_name}.role must be 'ego'")
            return ActorSelector(role="ego")
        if entity_name is not None and str(entity_name).strip():
            return ActorSelector(entity_name=str(entity_name).strip())
    raise ValueError(
        f"{field_name} must be 'ego', an entity name, or a mapping containing role/entity_name"
    )


def find_actor_by_selector(frame: Any, selector: ActorSelector) -> Any | None:
    normalized = frame if isinstance(frame, NormalizedRuntimeFrame) else None
    if normalized is None:
        return None
    for actor in normalized.objects:
        if selector.matches(actor):
            return actor
    return None


class EpisodeActorRegistry:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._next_agent_id = 1
        self._agent_id_by_tracking_id: dict[int, int] = {}
        self._identity_by_tracking_id: dict[int, tuple[str | None, bool]] = {}

    def normalize(self, frame: Any) -> NormalizedRuntimeFrame:
        if isinstance(frame, NormalizedRuntimeFrame):
            return frame

        raw_ego, raw_agents = _extract_simulator_objects(frame)
        ego_tracking_id, ego_name, ego_state = raw_ego
        ego = self._snapshot(
            tracking_id=ego_tracking_id,
            entity_name=ego_name,
            is_ego=True,
            state=ego_state,
        )

        agents: dict[int, ActorSnapshot] = {}
        names = {ego_name} if ego_name is not None else set()
        for tracking_id, entity_name, state in sorted(raw_agents, key=_presentation_key):
            if tracking_id == ego_tracking_id:
                raise RuntimeFrameContractError(
                    f"ego tracking ID {tracking_id} also appears in RuntimeFrame.agents"
                )
            if entity_name is not None and entity_name in names:
                raise RuntimeFrameContractError(
                    f"duplicate XOSC entity_name in RuntimeFrame: {entity_name!r}"
                )
            if entity_name is not None:
                names.add(entity_name)
            agents[tracking_id] = self._snapshot(
                tracking_id=tracking_id,
                entity_name=entity_name,
                is_ego=False,
                state=state,
            )

        return NormalizedRuntimeFrame(
            sim_time_ns=int(getattr(frame, "sim_time_ns", 0)),
            ego=ego,
            agents=agents,
            collision=getattr(frame, "collision", ()),
            extras=getattr(frame, "extras", None),
            source=frame,
        )

    def prepare_observation(
        self,
        frame: NormalizedRuntimeFrame,
        *,
        identity_visibility: str,
        observation_order: str,
        shuffle_key: str,
    ) -> PreparedObservation:
        visibility = identity_visibility.lower()
        if visibility not in {"none", "tracking_id", "full"}:
            raise ValueError(
                "av.observation_identity must be one of: none, tracking_id, full"
            )
        order = observation_order.lower()
        if order not in {"stable", "shuffle"}:
            raise ValueError("av.observation_order must be one of: stable, shuffle")

        actors = sorted(
            frame.agents.values(),
            key=lambda actor: (
                actor.entity_name is None,
                actor.entity_name or "",
                actor.sim_tracking_id,
            ),
        )
        if order == "shuffle":
            seed_payload = f"{shuffle_key}:{frame.sim_time_ns}".encode()
            seed = int.from_bytes(hashlib.sha256(seed_payload).digest()[:8], "big")
            random.Random(seed).shuffle(actors)

        agents = tuple(
            PreparedAgentObservation(
                state=actor.state,
                tracking_id=(
                    actor.sim_tracking_id if visibility in {"tracking_id", "full"} else None
                ),
                entity_name=actor.entity_name if visibility == "full" else None,
            )
            for actor in actors
        )
        return PreparedObservation(ego=frame.ego.state, agents=agents)

    def _snapshot(
        self,
        *,
        tracking_id: int,
        entity_name: str | None,
        is_ego: bool,
        state: Any,
    ) -> ActorSnapshot:
        previous = self._identity_by_tracking_id.get(tracking_id)
        identity = (entity_name, is_ego)
        if previous is not None and previous != identity:
            raise RuntimeFrameContractError(
                "simulator reused tracking ID "
                f"{tracking_id}: previous identity={previous}, current identity={identity}"
            )
        self._identity_by_tracking_id[tracking_id] = identity

        if is_ego:
            agent_id = 0
        else:
            agent_id = self._agent_id_by_tracking_id.get(tracking_id)
            if agent_id is None:
                agent_id = self._next_agent_id
                self._next_agent_id += 1
                self._agent_id_by_tracking_id[tracking_id] = agent_id
        return ActorSnapshot(
            agent_id=agent_id,
            sim_tracking_id=tracking_id,
            entity_name=entity_name,
            is_ego=is_ego,
            state=state,
        )


def iter_actor_snapshots(frame: Any) -> Iterator[ActorSnapshot]:
    if isinstance(frame, NormalizedRuntimeFrame):
        yield frame.ego
        yield from frame.agents.values()
        return
    raise RuntimeFrameContractError("runtime frame has not been normalized")


def _extract_simulator_objects(
    frame: Any,
) -> tuple[tuple[int, str | None, Any], list[tuple[int, str | None, Any]]]:
    if hasattr(frame, "ego") and hasattr(frame, "agents"):
        ego_wrapper = frame.ego
        ego_tracking_id = _required_int_attr(ego_wrapper, "tracking_id")
        ego_object = getattr(ego_wrapper, "object", ego_wrapper)
        ego_state = getattr(ego_object, "state", ego_object)
        ego_name = _optional_name(ego_object)

        agents = []
        raw_agents = frame.agents
        items = raw_agents.items() if hasattr(raw_agents, "items") else ()
        for raw_tracking_id, wrapper in items:
            tracking_id = int(raw_tracking_id)
            state = getattr(wrapper, "state", wrapper)
            agents.append((tracking_id, _optional_name(wrapper), state))
        return (ego_tracking_id, ego_name, ego_state), agents

    # Internal compatibility for existing tests and hand-written metric inputs. IDs must be
    # explicit; positional fallback is intentionally rejected.
    objects = list(getattr(frame, "objects", ()) or ())
    if not objects:
        raise RuntimeFrameContractError("RuntimeFrame must contain an explicit ego actor")
    extracted = [(_explicit_object_id(obj), _optional_name(obj), obj) for obj in objects]
    ego_candidates = [item for item in extracted if item[0] == 0 or getattr(item[2], "is_ego", False)]
    if len(ego_candidates) != 1:
        raise RuntimeFrameContractError(
            "legacy RuntimeFrame objects require exactly one explicit ego (actor_id=0 or is_ego)"
        )
    ego = ego_candidates[0]
    return ego, [item for item in extracted if item is not ego]


def _required_int_attr(value: Any, name: str) -> int:
    if not hasattr(value, name):
        raise RuntimeFrameContractError(f"RuntimeFrame ego is missing {name}")
    return int(getattr(value, name))


def _explicit_object_id(obj: Any) -> int:
    for field_name in ("sim_tracking_id", "tracking_id", "actor_id", "agent_id", "id", "object_id"):
        value = getattr(obj, field_name, None)
        if value is not None:
            return int(value)
    raise RuntimeFrameContractError("actor state is missing an explicit tracking ID")


def _optional_name(value: Any) -> str | None:
    raw = getattr(value, "entity_name", None)
    if raw is None:
        return None
    name = str(raw).strip()
    return name or None


def _presentation_key(item: tuple[int, str | None, Any]) -> tuple[bool, str, int]:
    tracking_id, entity_name, _ = item
    return entity_name is None, entity_name or "", tracking_id
