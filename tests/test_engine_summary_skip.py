from pathlib import Path
from types import SimpleNamespace

import pytest

from simcore.engine import SimulationEngine


class FakeMonitor:
    def __init__(self, finished: bool):
        self.finished = finished

    def has_finished_summary(self, output_related: str) -> bool:
        return self.finished


def make_engine(tmp_path: Path, finished: bool, overwrite: bool = False) -> SimulationEngine:
    engine = SimulationEngine.__new__(SimulationEngine)
    engine.monitor = FakeMonitor(finished)
    engine.overwrite = overwrite
    engine.output_base = tmp_path / "outputs"
    engine.job_id = "test"
    engine.completed_concrete_runs = 0
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


def test_concrete_wrapper_does_not_create_status_dir_on_failure(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def run_concrete(output_related, sps, params=None):
        raise RuntimeError("failed")

    engine.run_concrete = run_concrete

    with pytest.raises(RuntimeError, match="failed"):
        engine.concrete_wrapper("case_1", sps=None)

    assert not (tmp_path / "outputs" / "case_1" / "status").exists()


class KeyboardInterruptMonitor(FakeMonitor):
    def __init__(self):
        super().__init__(finished=False)
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
