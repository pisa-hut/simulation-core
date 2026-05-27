from __future__ import annotations

from pathlib import Path
from typing import Any

from simcore.utils.position import Position, PositionFactory


class PositionParser:
    def __init__(self, position_factory: PositionFactory):
        self._position_factory = position_factory

    @classmethod
    def from_specs(
        cls,
        scenario_spec: dict[str, Any],
        map_spec: dict[str, Any],
    ) -> PositionParser:
        map_name = map_spec["name"]
        xodr_path = (Path(map_spec["xodr_path"]) / f"{map_name}.xodr").resolve()
        rmlib_path = Path(scenario_spec.get("rmlib_path", "libesminiRMLib.so")).resolve()
        return cls(
            PositionFactory(
                lib_path=rmlib_path,
                xodr_path=xodr_path,
            )
        )

    def close(self) -> None:
        self._position_factory.close()

    def parse(self, raw_position: dict[str, Any], field_name: str = "position") -> Position:
        if not isinstance(raw_position, dict):
            raise ValueError(f"{field_name} must be a mapping, got: {raw_position!r}")

        position_type = self._normalize_position_type(raw_position.get("type", "WorldPosition"))
        if position_type == "lane":
            return self._parse_lane(raw_position, field_name)
        if position_type == "world":
            return self._parse_world(raw_position, field_name)

        raise ValueError(
            f"{field_name}.type must be LanePosition or WorldPosition, "
            f"got: {raw_position.get('type')!r}"
        )

    def _parse_lane(self, raw_position: dict[str, Any], field_name: str) -> Position:
        if "value" in raw_position:
            values = raw_position["value"]
            if len(values) < 3:
                raise ValueError(
                    f"{field_name}.value for LanePosition must include road_id, lane_id, s"
                )
            road_id = int(values[0])
            lane_id = int(values[1])
            s = float(values[2])
            offset = float(values[3]) if len(values) > 3 else 0.0
        else:
            road_id = self._require_int(raw_position, "road_id", field_name)
            lane_id = self._require_int(raw_position, "lane_id", field_name)
            s = self._require_float(raw_position, "s", field_name)
            offset = float(raw_position.get("offset", 0.0))

        return self._position_factory.from_lane(
            road_id=road_id,
            lane_id=lane_id,
            s=s,
            offset=offset,
        )

    def _parse_world(self, raw_position: dict[str, Any], field_name: str) -> Position:
        if "value" in raw_position:
            values = raw_position["value"]
            if len(values) < 2:
                raise ValueError(f"{field_name}.value for WorldPosition must include x and y")
            x = float(values[0])
            y = float(values[1])
            z = float(values[2]) if len(values) > 2 else 0.0
            h = float(values[3]) if len(values) > 3 else 0.0
            p = float(values[4]) if len(values) > 4 else 0.0
            r = float(values[5]) if len(values) > 5 else 0.0
        else:
            x = self._require_float(raw_position, "x", field_name)
            y = self._require_float(raw_position, "y", field_name)
            z = float(raw_position.get("z", 0.0))
            h = float(raw_position.get("h", 0.0))
            p = float(raw_position.get("p", 0.0))
            r = float(raw_position.get("r", 0.0))

        return self._position_factory.from_world(
            x=x,
            y=y,
            z=z,
            h=h,
            p=p,
            r=r,
        )

    @staticmethod
    def _normalize_position_type(position_type: Any) -> str:
        normalized = str(position_type).replace("_", "").lower()
        if normalized == "laneposition":
            return "lane"
        if normalized == "worldposition":
            return "world"
        return normalized

    @staticmethod
    def _require_int(raw_position: dict[str, Any], key: str, field_name: str) -> int:
        if key not in raw_position:
            raise ValueError(f"{field_name}.{key} is required")
        try:
            return int(raw_position[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}.{key} must be an integer") from exc

    @staticmethod
    def _require_float(raw_position: dict[str, Any], key: str, field_name: str) -> float:
        if key not in raw_position:
            raise ValueError(f"{field_name}.{key} is required")
        try:
            return float(raw_position[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}.{key} must be a number") from exc
