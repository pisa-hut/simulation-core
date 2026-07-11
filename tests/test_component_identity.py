import pytest
from google.protobuf.struct_pb2 import Struct
from pisa_api.initialization_pb2 import InitResponse
from pisa_api.pong_pb2 import Pong

from simcore.av_wrapper import AVWrapper
from simcore.sim_wrapper import SimWrapper


@pytest.mark.parametrize("wrapper", [SimWrapper, AVWrapper])
def test_wrapper_parses_runtime_reported_identity(wrapper) -> None:
    metadata = Struct()
    metadata.update({"runtime": {"version": "1.0"}, "enabled": True})

    assert wrapper._identity_from_pong(Pong(name="example-wrapper", version="0.3.1")) == {
        "name": "example-wrapper",
        "version": "0.3.1",
    }
    assert wrapper._identity_from_init_response(
        InitResponse(name="example-component", metadata=metadata)
    ) == {
        "name": "example-component",
        "metadata": {"runtime": {"version": "1.0"}, "enabled": True},
    }


@pytest.mark.parametrize("wrapper", [SimWrapper, AVWrapper])
def test_wrapper_rejects_missing_runtime_identity(wrapper) -> None:
    with pytest.raises(RuntimeError, match="incomplete wrapper identity"):
        wrapper._identity_from_pong(Pong(name="example-wrapper"))
    with pytest.raises(RuntimeError, match="empty component name"):
        wrapper._identity_from_init_response(InitResponse())
