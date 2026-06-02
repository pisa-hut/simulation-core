from __future__ import annotations

from collections import deque
from typing import Any

from simcore.conditions import ConditionCode, ConditionNode, EvaluationResult
from simcore.metrics.actors import float_attr, iter_actor_states, object_kinematic
from simcore.metrics.rules import NumericRule


class KinematicThresholdCondition(ConditionNode):
    def __init__(self, config: dict):
        super().__init__(config)

        self.actor_ids = self._parse_actor_ids(config)
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
        self.buffer.append(getattr(runtime_frame, "objects", None) or [])

    def evaluate(self) -> EvaluationResult:
        if not self.buffer:
            return self.result(ConditionCode.NOT_EVALUATED, "No data to evaluate")

        latest_values: list[tuple[int, float]] = []
        matched_actor_count = 0

        for objects in self.buffer:
            for actor_id, obj in iter_actor_states(objects):
                if not self._matches_actor_filter(actor_id):
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
    def _parse_actor_ids(config: dict) -> frozenset[int] | None:
        raw_agents = config.get("agents", config.get("actor_ids", config.get("agent_ids")))
        if raw_agents is None:
            raw_agents = config.get("actor_id", config.get("agent_id"))

        if raw_agents is None or _is_any_agent(raw_agents):
            return None

        if isinstance(raw_agents, int):
            return frozenset({raw_agents})

        if isinstance(raw_agents, str):
            return frozenset({int(raw_agents)})

        if not isinstance(raw_agents, (list, tuple, set)):
            raise ValueError(
                "KinematicThresholdCondition 'agents' must be 'any', an integer, "
                "or a list of integers"
            )

        actor_ids = set()
        for raw_agent in raw_agents:
            if _is_any_agent(raw_agent):
                return None
            actor_ids.add(int(raw_agent))
        if not actor_ids:
            raise ValueError("KinematicThresholdCondition 'agents' must not be empty")
        return frozenset(actor_ids)

    def _matches_actor_filter(self, actor_id: int) -> bool:
        return self.actor_ids is None or actor_id in self.actor_ids

    def _triggered_detail(self, actor_id: int, metric_value: float) -> str:
        return (
            f"Actor {actor_id} kinematic.{self.metric} matched rule {self.rule.describe()}: "
            f"value={metric_value:.6g}; agents={self._agent_description()}"
        )

    def _not_triggered_detail(
        self,
        matched_actor_count: int,
        latest_values: list[tuple[int, float]],
    ) -> str:
        if matched_actor_count == 0:
            return (
                f"No actors matched agents={self._agent_description()} while checking "
                f"kinematic.{self.metric} rule {self.rule.describe()}"
            )
        if not latest_values:
            return (
                f"Metric kinematic.{self.metric} was unavailable for "
                f"{matched_actor_count} matching actor(s); rule={self.rule.describe()}"
            )

        values = ", ".join(
            f"actor {actor_id}: {self.metric}={value:.6g}"
            for actor_id, value in latest_values[-5:]
        )
        return (
            f"No matching actor satisfied kinematic.{self.metric} rule {self.rule.describe()}; "
            f"latest values: {values}"
        )

    def _agent_description(self) -> str:
        if self.actor_ids is None:
            return "any"
        return "[" + ", ".join(str(actor_id) for actor_id in sorted(self.actor_ids)) + "]"


def _is_any_agent(raw_value: Any) -> bool:
    return isinstance(raw_value, str) and raw_value.strip().lower() in {"any", "*", "all"}
