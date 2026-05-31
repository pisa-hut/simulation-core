from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import grpc


class RetryHint(Enum):
    OK = "ok"
    RETRY = "retry"
    DONT_RETRY = "dont_retry"


@dataclass(frozen=True)
class ExecResult:
    hint: RetryHint
    reason: str
    finished_concrete_runs: int
    aborted_concrete_runs: int
    skipped_concrete_runs: int


@dataclass(frozen=True)
class ShouldQuitResult:
    should_quit: bool
    message: str = ""

    def __bool__(self) -> bool:
        return self.should_quit


class ScenarioExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        hint: RetryHint,
        grpc_code: grpc.StatusCode | None = None,
        skip_concrete: bool = False,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.grpc_code = grpc_code
        self.skip_concrete = skip_concrete
        self.summary_recorded = False


def classify_grpc_error(error: grpc.RpcError) -> ScenarioExecutionError:
    code = error.code()
    details = error.details()
    reason = f"{code.name} - {details}"

    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return ScenarioExecutionError(
            reason,
            hint=RetryHint.DONT_RETRY,
            grpc_code=code,
        )
    if code == grpc.StatusCode.FAILED_PRECONDITION:
        return ScenarioExecutionError(
            reason,
            hint=RetryHint.DONT_RETRY,
            grpc_code=code,
            skip_concrete=True,
        )
    if code == grpc.StatusCode.UNAVAILABLE:
        return ScenarioExecutionError(
            reason,
            hint=RetryHint.RETRY,
            grpc_code=code,
        )
    return ScenarioExecutionError(
        reason,
        hint=RetryHint.RETRY,
        grpc_code=code,
    )
