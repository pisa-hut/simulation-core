from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import grpc


class RetryHint(Enum):
    OK = "ok"
    RETRY = "retry"
    DONT_RETRY = "dont_retry"


@dataclass(frozen=True)
class ConcreteOutcome:
    concrete_key: str
    status: str
    test_outcome: str
    reason: str
    stop_condition: str
    params: dict[str, Any] | None
    final_sim_time_ms: float
    wall_time_ms: float
    total_steps: int
    metrics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecResult:
    hint: RetryHint
    reason: str
    finished_concrete_runs: int
    aborted_concrete_runs: int
    skipped_concrete_runs: int
    concrete_outcomes: list[ConcreteOutcome]


@dataclass(frozen=True)
class ProgressUpdate:
    """Live, mid-run snapshot pushed to an optional progress callback. ``total``
    is the sampler's reported sample count, or ``None`` when open-ended.
    ``outcome`` is the concrete that just finalised on this tick (so consumers
    can persist it incrementally), or ``None`` for count-only ticks such as the
    initial "started, total=N" announcement."""

    total: int | None
    finished: int
    aborted: int
    skipped: int
    outcome: ConcreteOutcome | None = None


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
