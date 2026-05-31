import csv
from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest

from simcore.engine import SimulationEngine
from simcore.execution import RetryHint, ScenarioExecutionError


class FakeMonitor:
    def __init__(self, status: str | None):
        self.status = status
        self.retryable_failures = 0
        self.finalize_calls = []

    def has_finished_summary(self, output_related: str) -> bool:
        return self.status == "finished"

    def has_terminal_summary(self, output_related: str) -> bool:
        return self.status in {"finished", "skipped"}

    def count_retryable_failures(self, output_related: str) -> int:
        return self.retryable_failures

    def reset(self, output_related, params=None, overwrite_summary=False):
        self.reset_call = (output_related, params, overwrite_summary)

    def finalize(self, status: str, reason: str = ""):
        self.finalize_calls.append((status, reason))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def make_engine(
    tmp_path: Path,
    finished: bool = False,
    overwrite: bool = False,
    status: str | None = None,
) -> SimulationEngine:
    engine = SimulationEngine.__new__(SimulationEngine)
    engine.monitor = FakeMonitor(status or ("finished" if finished else None))
    engine.overwrite = overwrite
    engine.max_concrete_retries = 3
    engine.output_base = tmp_path / "outputs"
    engine.job_id = "test"
    engine.completed_concrete_runs = 0
    engine.failed_concrete_runs = 0
    engine.skipped_concrete_runs = 0
    engine._last_skip_reason = ""
    return engine


def test_concrete_wrapper_skips_finished_summary_without_status_dir(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=True)
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False
    assert not (tmp_path / "outputs" / "case_1" / "status").exists()


def test_concrete_wrapper_overwrite_reruns_finished_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=True, overwrite=True)
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is True


def test_concrete_wrapper_skips_previous_skipped_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="skipped")
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_reruns_previous_retryable_failure(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="fail")
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is True


def test_concrete_wrapper_does_not_create_status_dir_on_failure(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def run_concrete(output_related, sps, params=None):
        raise RuntimeError("failed")

    engine.run_concrete = run_concrete

    with pytest.raises(RuntimeError, match="failed"):
        engine.concrete_wrapper("case_1", sps=None)

    assert not (tmp_path / "outputs" / "case_1" / "status").exists()


def test_concrete_wrapper_records_failed_precondition_skip(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def run_concrete(output_related, sps, params=None):
        raise ScenarioExecutionError(
            "sim reset failed: FAILED_PRECONDITION - fail to set route",
            hint=RetryHint.DONT_RETRY,
            grpc_code=grpc.StatusCode.FAILED_PRECONDITION,
            skip_concrete=True,
        )

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None, params={"speed": 10})

    assert engine.monitor.reset_call == ("case_1", {"speed": 10}, False)
    assert engine.monitor.finalize_calls == [
        (
            "skipped",
            "dont_retry: sim reset failed: FAILED_PRECONDITION - fail to set route",
        ),
    ]


def test_concrete_wrapper_skips_after_too_many_retryable_failures(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.monitor.retryable_failures = 3
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False
    assert engine.monitor.finalize_calls == [
        (
            "skipped",
            "retry: exceeded max_concrete_retries=3; skipping concrete",
        ),
    ]


def test_exec_returns_retry_hint_for_transient_error(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.close = lambda: None

    def concrete_wrapper(output_related, sps):
        raise ScenarioExecutionError(
            "av step failed: UNAVAILABLE - timed out",
            hint=RetryHint.RETRY,
            grpc_code=grpc.StatusCode.UNAVAILABLE,
        )

    engine.concrete_wrapper = concrete_wrapper

    result = engine.exec()

    assert result.completed_concrete_runs == 0
    assert result.hint == RetryHint.RETRY
    assert result.reason == "av step failed: UNAVAILABLE - timed out"


def test_exec_writes_current_and_cumulative_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.output_base.mkdir(parents=True)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.close = lambda: None
    engine.completed_concrete_runs = 1
    engine.failed_concrete_runs = 1
    engine.skipped_concrete_runs = 1

    summary_dir = engine.output_base / "iteration_1" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary.csv").write_text("run.status,run.stop_reason\nfinished,completed\n")
    summary_dir = engine.output_base / "iteration_2" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary.csv").write_text("run.status,run.stop_reason\nfail,retry: timeout\n")
    summary_dir = engine.output_base / "iteration_3" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "summary.csv").write_text("run.status,run.stop_reason\nskipped,dont_retry\n")

    engine.concrete_wrapper = lambda output_related, sps: None

    result = engine.exec()

    assert result.hint == RetryHint.OK
    rows = read_csv(engine.output_base / "summary.csv")
    assert rows == [
        {
            "job_id": "test",
            "hint": "ok",
            "reason": "completed",
            "current_finished": "1",
            "current_failed": "1",
            "current_skipped": "1",
            "cumulative_finished": "1",
            "cumulative_failed": "1",
            "cumulative_skipped": "1",
        }
    ]


def test_exec_returns_ok_when_only_concrete_was_skipped(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.close = lambda: None

    def concrete_wrapper(output_related, sps):
        engine._record_skipped_concrete("dont_retry: scenario impossible")

    engine.concrete_wrapper = concrete_wrapper

    result = engine.exec()

    assert result.completed_concrete_runs == 0
    assert result.hint == RetryHint.OK
    assert result.reason == "completed"


class KeyboardInterruptMonitor(FakeMonitor):
    def __init__(self):
        super().__init__(status=None)
        self.finalize_calls = []

    def reset(self, output_related, params=None, overwrite_summary=False):
        return None

    def finalize(self, status: str, reason: str = ""):
        self.finalize_calls.append((status, reason))


def test_run_concrete_records_keyboard_interrupt_and_reraises(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    monitor = KeyboardInterruptMonitor()
    engine.monitor = monitor

    def sim_reset(output_related, sps, params):
        raise KeyboardInterrupt

    engine.sim = SimpleNamespace(reset=sim_reset)
    engine.av = SimpleNamespace()

    with pytest.raises(KeyboardInterrupt):
        engine.run_concrete("case_1", sps=None)

    assert monitor.finalize_calls == [
        ("fail", "KeyboardInterrupt: interrupted by user"),
    ]
