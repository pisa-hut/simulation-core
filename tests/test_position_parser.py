from types import SimpleNamespace

from simcore.utils.position_parser import PositionParser


class FakePositionFactory:
    def __init__(self) -> None:
        self.calls = []

    def from_lane(self, *, road_id: int, lane_id: int, s: float, offset: float):
        self.calls.append(("lane", road_id, lane_id, s, offset))
        return SimpleNamespace(x=road_id, y=lane_id, z=s)

    def from_world(self, *, x: float, y: float, z: float, h: float, p: float, r: float):
        self.calls.append(("world", x, y, z, h, p, r))
        return SimpleNamespace(x=x, y=y, z=z)

    def close(self) -> None:
        self.calls.append(("close",))


def test_position_parser_parses_lane_position_value_schema() -> None:
    factory = FakePositionFactory()
    parser = PositionParser(factory)

    position = parser.parse(
        {
            "type": "LanePosition",
            "value": [12, -2, 34.5, 0.75],
        }
    )

    assert factory.calls == [("lane", 12, -2, 34.5, 0.75)]
    assert position.x == 12


def test_position_parser_parses_world_position_mapping_schema() -> None:
    factory = FakePositionFactory()
    parser = PositionParser(factory)

    position = parser.parse(
        {
            "type": "world_position",
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
            "h": 0.1,
        }
    )

    assert factory.calls == [("world", 1.0, 2.0, 3.0, 0.1, 0.0, 0.0)]
    assert position.y == 2.0
