from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest

from simcore.engine import SimulationEngine
from simcore.execution import RetryHint, ScenarioExecutionError
from simcore.sampler import Sample


class FakeMonitor:
    def __init__(self, status: str | None):
        self.status = status
        self.retryable_failures = 0
        self.finalize_calls = []
        self.close_result = None
        self.current_summary_counts = {"finished": 0, "error": 0, "skipped": 0, "abort": 0}

    def has_finished_summary(self, output_related: str) -> bool:
        return self.status == "finished"

    def has_terminal_summary(self, output_related: str) -> bool:
        return self.status in {"finished", "skipped", "abort"}

    def last_summary_status(self, output_related: str) -> str | None:
        return self.status

    def count_retryable_failures(self, output_related: str) -> int:
        return self.retryable_failures

    def should_stop(self) -> bool:
        return False

    def reset(self, output_related, params=None, overwrite_summary=False):
        self.reset_call = (output_related, params, overwrite_summary)

    def finalize(self, status: str, reason: str = ""):
        self.finalize_calls.append((status, reason))
        if status in self.current_summary_counts:
            self.current_summary_counts[status] += 1

    def close(self, result=None):
        self.close_result = result

    def logical_terminal_counts(self) -> dict[str, int]:
        return {
            "finished": self.current_summary_counts["finished"],
            "abort": self.current_summary_counts["abort"],
            "skipped": self.current_summary_counts["skipped"],
        }


class FakeSampler:
    def __init__(self, samples):
        self.samples = [
            sample if isinstance(sample, Sample) else Sample(params=sample)
            for sample in samples
        ]
        self.index = 0

    def total_samples(self):
        return len(self.samples)

    def next(self):
        if self.index >= len(self.samples):
            return None
        sample = self.samples[self.index]
        self.index += 1
        return sample


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
    engine._last_skip_reason = ""
    engine._permutation = None
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


def test_concrete_wrapper_skips_previous_aborted_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="abort")
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_does_not_overwrite_previous_aborted_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="abort", overwrite=True)
    ran = False

    def run_concrete(output_related, sps, params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_reruns_previous_retryable_error(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="error")
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


def test_concrete_wrapper_aborts_after_too_many_retryable_failures(tmp_path: Path) -> None:
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
            "abort",
            "retry: exceeded max_concrete_retries=3; aborting concrete",
        ),
    ]


def test_exec_returns_retry_hint_for_transient_error(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.close = lambda result=None: None

    def concrete_wrapper(output_related, sps):
        raise ScenarioExecutionError(
            "av step failed: UNAVAILABLE - timed out",
            hint=RetryHint.RETRY,
            grpc_code=grpc.StatusCode.UNAVAILABLE,
        )

    engine.concrete_wrapper = concrete_wrapper

    result = engine.exec()

    assert result.hint == RetryHint.RETRY
    assert result.reason == "av step failed: UNAVAILABLE - timed out"
    assert result.finished_concrete_runs == 0
    assert result.aborted_concrete_runs == 0
    assert result.skipped_concrete_runs == 0


def test_exec_delegates_summary_to_monitor_close(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.sim = None
    engine.av = None
    engine.position_parser = SimpleNamespace(close=lambda: None)
    engine.monitor.current_summary_counts["finished"] = 1

    engine.concrete_wrapper = lambda output_related, sps: None

    result = engine.exec()

    assert result.hint == RetryHint.OK
    assert result.finished_concrete_runs == 1
    assert result.aborted_concrete_runs == 0
    assert result.skipped_concrete_runs == 0
    assert engine.monitor.close_result == result


def test_exec_returns_ok_when_only_concrete_was_skipped(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = None
    engine.sps = None
    engine._startup_error = None
    engine.close = lambda result=None: None

    def concrete_wrapper(output_related, sps):
        engine._record_skipped_concrete("dont_retry: scenario impossible")

    engine.concrete_wrapper = concrete_wrapper

    result = engine.exec()

    assert result.hint == RetryHint.OK
    assert result.reason == "completed"


def test_run_logical_runs_only_requested_permutation(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler(
        [
            {"speed": 10},
            {"speed": 20},
            {"speed": 30},
        ]
    )
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = 2
    calls = []

    def concrete_wrapper(output_related, sps, params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [("iteration_2", {"speed": 20})]
    assert engine.param_sampler.index == 2


def test_run_logical_without_permutation_runs_all_iterations(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler(
        [
            {"speed": 10},
            {"speed": 20},
            {"speed": 30},
        ]
    )
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    calls = []

    def concrete_wrapper(output_related, sps, params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [
        ("iteration_1", {"speed": 10}),
        ("iteration_2", {"speed": 20}),
        ("iteration_3", {"speed": 30}),
    ]


def test_run_logical_uses_explicit_sample_ids_for_iteration_folders(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler(
        [
            Sample(id="case_a", params={"speed": 10}),
            Sample(id="case_b", params={"offset": -1.5, "behavior": "cutin"}),
        ]
    )
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    calls = []

    def concrete_wrapper(output_related, sps, params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [
        ("iteration_case_a", {"speed": 10}),
        ("iteration_case_b", {"offset": -1.5, "behavior": "cutin"}),
    ]


def test_run_logical_permutation_uses_explicit_sample_id(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler(
        [
            Sample(id="case_a", params={"speed": 10}),
            Sample(id="case_b", params={"speed": 20}),
        ]
    )
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = 2
    calls = []

    def concrete_wrapper(output_related, sps, params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [("iteration_case_b", {"speed": 20})]


def test_run_logical_rejects_out_of_range_permutation(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler([{"speed": 10}])
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = 2

    with pytest.raises(ValueError, match="out of range"):
        engine.run_logical()


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
        ("error", "KeyboardInterrupt: interrupted by user"),
    ]


def test_run_concrete_stops_before_sim_reset_when_monitor_precheck_triggers(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path, finished=False)
    monitor = FakeMonitor(status=None)
    monitor.stop_reason = "Stop condition 'invalid_params' triggered"

    def should_stop():
        return True

    monitor.should_stop = should_stop
    engine.monitor = monitor

    def sim_reset(output_related, sps, params):
        raise AssertionError("sim.reset should not be called")

    engine.sim = SimpleNamespace(reset=sim_reset)
    engine.av = SimpleNamespace()

    engine.run_concrete("case_1", sps=None, params={"a": 1})

    assert monitor.reset_call == ("case_1", {"a": 1}, False)
    assert monitor.finalize_calls == [
        ("finished", "Stop condition 'invalid_params' triggered"),
    ]
