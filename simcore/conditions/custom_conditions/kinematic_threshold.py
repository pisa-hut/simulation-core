from __future__ import annotations

from collections import deque
from typing import Any

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.actors import float_attr, iter_actor_states, object_kinematic
from simcore.metrics.rules import NumericRule
from simcore.runtime_actors import ActorSelector, find_actor_by_selector, parse_actor_selector


class KinematicThresholdCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.actor_ids, self.actor_selectors = self._parse_actor_filters(config)
        self.metric = self._parse_metric(config)
        self.rule = self._parse_rule(config)

        try:
            max_buffer_size = int(config.get("max_buffer_size", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "KinematicThresholdCondition config 'max_buffer_size' must be an integer, "
                f"but got: {config.get('max_buffer_size')}"
            ) from exc

        self.buffer = deque(maxlen=max(1, max_buffer_size))

    def put(self, data):
        runtime_frame = data[1]
        actor_ids = self.actor_ids
        if self.actor_selectors:
            resolved = {
                actor.agent_id
                for selector in self.actor_selectors
                if (actor := find_actor_by_selector(runtime_frame, selector)) is not None
            }
            actor_ids = frozenset((*self.actor_ids, *resolved))
        self.buffer.append((getattr(runtime_frame, "objects", None) or [], actor_ids))

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        latest_values: list[tuple[int, float]] = []
        matched_actor_count = 0

        for objects, actor_ids in self.buffer:
            for actor_id, obj in iter_actor_states(objects):
                if actor_ids is not None and actor_id not in actor_ids:
                    continue

                matched_actor_count += 1
                metric_value = float_attr(object_kinematic(obj), self.metric)
                if metric_value is None:
                    continue

                latest_values.append((actor_id, metric_value))
                if self.rule.matches(metric_value):
                    return self.result(
                        ConditionCode.TRIGGERED,
                        self._triggered_detail(actor_id, metric_value),
                    )

        return self.result(
            ConditionCode.NOT_TRIGGERED,
            self._not_triggered_detail(matched_actor_count, latest_values),
        )

    def reset(self):
        self.buffer.clear()

    @staticmethod
    def _parse_metric(config: dict) -> str:
        raw_metric = config.get("metric", config.get("kinematic_metric", config.get("field")))
        if not isinstance(raw_metric, str) or not raw_metric.strip():
            raise ValueError("KinematicThresholdCondition requires a non-empty 'metric'")
        return raw_metric.strip()

    @staticmethod
    def _parse_rule(config: dict) -> NumericRule:
        if "rule" not in config:
            raise ValueError("KinematicThresholdCondition requires 'rule'")
        return NumericRule.from_config(
            config["rule"],
            raw_value=config.get("value"),
            raw_values=config.get("values"),
            eps=config.get("eps"),
            field_name="value",
        )

    @staticmethod
    def _parse_actor_filters(
        config: dict,
    ) -> tuple[frozenset[int] | None, tuple[ActorSelector, ...]]:
        raw_actors = config.get(
            "actors",
            config.get("agents", config.get("actor_ids", config.get("agent_ids"))),
        )
        if raw_actors is None:
            raw_actors = config.get("actor_id", config.get("agent_id"))

        if raw_actors is None or _is_any_actor(raw_actors):
            return None, ()

        if isinstance(raw_actors, int):
            return frozenset({raw_actors}), ()

        if isinstance(raw_actors, str):
            try:
                return frozenset({int(raw_actors)}), ()
            except ValueError:
                return frozenset(), (parse_actor_selector(raw_actors, field_name="actors"),)

        if not isinstance(raw_actors, (list, tuple, set)):
            raise ValueError(
                "KinematicThresholdCondition 'actors' must be 'any', an actor selector, "
                "an integer legacy actor ID, or a list of those values"
            )

        actor_ids = set()
        selectors = []
        for raw_actor in raw_actors:
            if _is_any_actor(raw_actor):
                return None, ()
            try:
                actor_ids.add(int(raw_actor))
            except TypeError, ValueError:
                selectors.append(parse_actor_selector(raw_actor, field_name="actors"))
        if not actor_ids and not selectors:
            raise ValueError("KinematicThresholdCondition 'actors' must not be empty")
        return frozenset(actor_ids), tuple(selectors)

    def _triggered_detail(self, actor_id: int, metric_value: float) -> str:
        return (
            f"Actor {actor_id} kinematic.{self.metric} matched rule {self.rule.describe()}: "
            f"value={metric_value:.6g}; actors={self._actor_description()}"
        )

    def _not_triggered_detail(
        self,
        matched_actor_count: int,
        latest_values: list[tuple[int, float]],
    ) -> str:
        if matched_actor_count == 0:
            return (
                f"No actors matched actors={self._actor_description()} while checking "
                f"kinematic.{self.metric} rule {self.rule.describe()}"
            )
        if not latest_values:
            return (
                f"Metric kinematic.{self.metric} was unavailable for "
                f"{matched_actor_count} matching actor(s); rule={self.rule.describe()}"
            )

        values = ", ".join(
            f"actor {actor_id}: {self.metric}={value:.6g}" for actor_id, value in latest_values[-5:]
        )
        return (
            f"No matching actor satisfied kinematic.{self.metric} rule {self.rule.describe()}; "
            f"latest values: {values}"
        )

    def _actor_description(self) -> str:
        if self.actor_ids is None:
            return "any"
        values = [str(actor_id) for actor_id in sorted(self.actor_ids)]
        values.extend(
            selector.role or selector.entity_name or "unknown" for selector in self.actor_selectors
        )
        return "[" + ", ".join(values) + "]"


def _is_any_actor(raw_value: Any) -> bool:
    return isinstance(raw_value, str) and raw_value.strip().lower() in {"any", "*", "all"}
