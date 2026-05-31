import grpc

from simcore.execution import RetryHint, classify_grpc_error


class FakeRpcError(grpc.RpcError):
    def __init__(self, code: grpc.StatusCode, details: str):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


def test_classify_invalid_argument_as_logical_dont_retry() -> None:
    error = classify_grpc_error(FakeRpcError(grpc.StatusCode.INVALID_ARGUMENT, "map not found"))

    assert error.hint == RetryHint.DONT_RETRY
    assert error.skip_concrete is False


def test_classify_failed_precondition_as_concrete_skip() -> None:
    error = classify_grpc_error(
        FakeRpcError(grpc.StatusCode.FAILED_PRECONDITION, "fail to set route")
    )

    assert error.hint == RetryHint.DONT_RETRY
    assert error.skip_concrete is True


def test_classify_unavailable_as_retry() -> None:
    error = classify_grpc_error(FakeRpcError(grpc.StatusCode.UNAVAILABLE, "timed out"))

    assert error.hint == RetryHint.RETRY
    assert error.skip_concrete is False
