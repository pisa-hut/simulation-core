from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pisa_api import path_pb2, scenario_pb2

from simcore.utils.position import Position
from simcore.utils.position_parser import PositionParser


@dataclass
class SpawnConfig:
    position: Position
    speed: float

    def to_protobuf(self) -> scenario_pb2.SpawnConfig:
        return scenario_pb2.SpawnConfig(
            position=self.position.to_protobuf(),
            speed=self.speed,
        )


@dataclass
class GoalConfig:
    position: Position
    # speed: float

    def to_protobuf(self) -> scenario_pb2.GoalConfig:
        return scenario_pb2.GoalConfig(
            position=self.position.to_protobuf(),
            # speed=self.speed,
        )


@dataclass
class EgoConfig:
    target_speed: float
    goal: GoalConfig
    spawn: SpawnConfig = field(default=None)

    @classmethod
    def from_dict(cls, ego: dict[str, Any], position_parser: PositionParser) -> EgoConfig:
        try:
            target_speed = float(ego["target_speed"])
        except KeyError as exc:
            raise ValueError("ego.target_speed not defined") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"ego.target_speed must be a number, got {ego.get('target_speed')!r}"
            ) from exc

        try:
            goal_raw = ego["position"]
        except KeyError as exc:
            raise ValueError("ego.position not defined") from exc

        goal_pos = position_parser.parse(goal_raw, field_name="ego.position")
        goal = GoalConfig(position=goal_pos)

        return cls(
            target_speed=target_speed,
            # spawn=spawn,
            # check_points=check_points,
            goal=goal,
        )

    @classmethod
    def from_yaml(cls, path: str) -> EgoConfig:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def to_protobuf(self) -> scenario_pb2.EgoConfig:
        return scenario_pb2.EgoConfig(
            target_speed=self.target_speed,
            # spawn_config=self.spawn.to_protobuf(),
            # check_points=[cp.to_protobuf() for cp in self.check_points],
            goal_config=self.goal.to_protobuf(),
        )


@dataclass
class ScenarioPack:
    name: str
    map_name: str
    param_range_file: Path | None
    ego: EgoConfig
    timeout_ns: int = field(default=int(3e11))  # default 300 seconds

    @classmethod
    def from_dict(
        cls,
        scenario_spec: dict[str, Any],
        map_spec: dict[str, Any],
        position_parser: PositionParser | None = None,
    ) -> ScenarioPack:
        name = scenario_spec["title"]
        scenario_folder = scenario_spec["scenario_path"]
        map_name = map_spec["name"]
        owns_position_parser = position_parser is None
        if position_parser is None:
            position_parser = PositionParser.from_specs(scenario_spec, map_spec)
        try:
            ego = EgoConfig.from_dict(
                scenario_spec["goal_config"],
                position_parser=position_parser,
            )
        finally:
            if owns_position_parser:
                position_parser.close()

        pr_fname = Path(scenario_folder) / f"{name}_param.xosc"
        param_range_file = pr_fname if pr_fname.exists() else None

        return cls(
            name=name,
            map_name=map_name,
            ego=ego,
            param_range_file=param_range_file,
        )

    @classmethod
    def from_yaml(cls, path: str) -> ScenarioPack:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)

    def to_protobuf(self):
        return scenario_pb2.ScenarioPack(
            name=self.name,
            map_name=self.map_name,
            param_range_file=(
                path_pb2.Path(path=str(self.param_range_file)) if self.param_range_file else None
            ),
            ego=self.ego.to_protobuf(),
            timeout_ns=self.timeout_ns,
        )
