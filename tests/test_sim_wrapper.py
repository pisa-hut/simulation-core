from simcore.sim_wrapper import stringify_params


def test_stringify_params_for_protobuf_map() -> None:
    assert stringify_params({"speed": 10.0, "enabled": True, "label": "case"}) == {
        "speed": "10.0",
        "enabled": "True",
        "label": "case",
    }


def test_stringify_params_handles_empty_values() -> None:
    assert stringify_params(None) == {}
    assert stringify_params({}) == {}
