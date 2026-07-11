from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest

import simcore.engine as engine_module
from simcore.engine import (
    SimulationEngine,
    _resolve_scenario_relative_path,
    _scenario_source_base_path,
)
from simcore.execution import ConcreteOutcome, RetryHint, ScenarioExecutionError
from simcore.sampler import Sample


class FakeMonitor:
    def __init__(self, status: str | None):
        self.status = status
        self.retryable_failures = 0
        self.finalize_calls = []
        self.updates = []
        self.close_result = None
        self.final_sim_time_ns = 0
        self.stop_reason = ""
        self.current_summary_counts = {"finished": 0, "error": 0, "skipped": 0, "abort": 0}

    def has_finished_summary(self, output_related: str) -> bool:
        return self.status == "finished"

    def has_terminal_summary(self, output_related: str) -> bool:
        return self.status in {"finished", "skipped", "abort"}

    def last_summary_status(self, output_related: str) -> str | None:
        return self.status

    def count_retryable_failures(self, output_related: str) -> int:
        return self.retryable_failures

    def should_stop(self, check_external_quit: bool = True) -> bool:
        return False

    def reset(self, output_related, params=None, overwrite_summary=False):
        self.reset_call = (output_related, params, overwrite_summary)

    def update(self, sim_time_ns, runtime_frame, control):
        self.updates.append((sim_time_ns, runtime_frame, control))
        self.final_sim_time_ns = sim_time_ns

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

    def concrete_outcomes(self):
        return []


class FakeSampler:
    def __init__(self, samples):
        self.samples = [
            sample if isinstance(sample, Sample) else Sample(params=sample) for sample in samples
        ]
        self.index = 0
        self.updates = []

    def total_samples(self):
        return len(self.samples)

    def next(self):
        if self.index >= len(self.samples):
            return None
        sample = self.samples[self.index]
        self.index += 1
        return sample

    def update(self, sample, result):
        self.updates.append((sample, result))


def test_scenario_source_base_path_uses_scenario_folder(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()

    assert _scenario_source_base_path(scenario_dir) == scenario_dir


def test_scenario_source_base_path_uses_parent_for_scenario_file(tmp_path: Path) -> None:
    scenario_file = tmp_path / "scenario" / "case.xosc"

    assert _scenario_source_base_path(scenario_file) == scenario_file.parent


def test_scenario_relative_path_resolves_under_scenario_folder(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"

    assert _resolve_scenario_relative_path("stop_conditions.yaml", scenario_dir) == str(
        scenario_dir / "stop_conditions.yaml"
    )


def test_scenario_relative_path_preserves_absolute_path(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    absolute_path = tmp_path / "config" / "stop_conditions.yaml"

    assert _resolve_scenario_relative_path(absolute_path, scenario_dir) == str(absolute_path)


def test_scenario_relative_path_uses_existing_default_file(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    default_path = scenario_dir / "stop_conditions.yaml"
    default_path.write_text("condition:\n  type: timeout\n  timeout_ms: 1\n", encoding="utf-8")

    assert _resolve_scenario_relative_path(
        None,
        scenario_dir,
        default_filename="stop_conditions.yaml",
    ) == str(default_path)


def test_scenario_relative_path_ignores_missing_default_file(tmp_path: Path) -> None:
    scenario_dir = tmp_path / "scenario"

    assert (
        _resolve_scenario_relative_path(
            None,
            scenario_dir,
            default_filename="stop_conditions.yaml",
        )
        is None
    )


def test_engine_resolves_stop_condition_config_relative_to_scenario_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    captured = {}

    class FakePositionParser:
        def close(self):
            pass

    class CapturingMonitor:
        def __init__(self, *args, stop_condition_config_path=None, **kwargs):
            captured["stop_condition_config_path"] = stop_condition_config_path

    monkeypatch.setattr(
        engine_module.PositionParser,
        "from_specs",
        staticmethod(lambda scenario_spec, map_spec: FakePositionParser()),
    )
    monkeypatch.setattr(
        engine_module.ScenarioPack,
        "from_dict",
        staticmethod(lambda scenario_spec, map_spec, position_parser=None: object()),
    )
    identity = {"wrapper": {}, "component": {}}
    monkeypatch.setattr(
        engine_module, "SimWrapper", lambda *args, **kwargs: SimpleNamespace(identity=identity)
    )
    monkeypatch.setattr(
        engine_module, "AVWrapper", lambda *args, **kwargs: SimpleNamespace(identity=identity)
    )
    monkeypatch.setattr(engine_module, "Monitor", CapturingMonitor)

    engine_module.SimulationEngine(
        {
            "runtime": {"dt": 0.1},
            "task": {"output_dir": str(tmp_path / "outputs")},
            "simulator": {},
            "av": {},
            "map": {"name": "test_map"},
            "scenario": {
                "title": "test_scenario",
                "scenario_path": str(scenario_dir),
                "stop_condition_config_path": "stop_conditions.yaml",
            },
            "sampler": {},
            "monitor": {},
        }
    )

    assert captured["stop_condition_config_path"] == str(scenario_dir / "stop_conditions.yaml")


def test_engine_uses_default_stop_conditions_file_from_scenario_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_dir = tmp_path / "scenario"
    scenario_dir.mkdir()
    default_path = scenario_dir / "stop_conditions.yaml"
    default_path.write_text("condition:\n  type: timeout\n  timeout_ms: 1\n", encoding="utf-8")
    captured = {}

    class FakePositionParser:
        def close(self):
            pass

    class CapturingMonitor:
        def __init__(self, *args, stop_condition_config_path=None, **kwargs):
            captured["stop_condition_config_path"] = stop_condition_config_path

    monkeypatch.setattr(
        engine_module.PositionParser,
        "from_specs",
        staticmethod(lambda scenario_spec, map_spec: FakePositionParser()),
    )
    monkeypatch.setattr(
        engine_module.ScenarioPack,
        "from_dict",
        staticmethod(lambda scenario_spec, map_spec, position_parser=None: object()),
    )
    identity = {"wrapper": {}, "component": {}}
    monkeypatch.setattr(
        engine_module, "SimWrapper", lambda *args, **kwargs: SimpleNamespace(identity=identity)
    )
    monkeypatch.setattr(
        engine_module, "AVWrapper", lambda *args, **kwargs: SimpleNamespace(identity=identity)
    )
    monkeypatch.setattr(engine_module, "Monitor", CapturingMonitor)

    engine_module.SimulationEngine(
        {
            "runtime": {"dt": 0.1},
            "task": {"output_dir": str(tmp_path / "outputs")},
            "simulator": {},
            "av": {},
            "map": {"name": "test_map"},
            "scenario": {
                "title": "test_scenario",
                "scenario_path": str(scenario_dir),
            },
            "sampler": {},
            "monitor": {},
        }
    )

    assert captured["stop_condition_config_path"] == str(default_path)


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
    engine._progress_callback = None
    engine._emitted_outcomes = 0
    return engine


def test_concrete_wrapper_skips_finished_summary_without_status_dir(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=True)
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False
    assert not (tmp_path / "outputs" / "case_1" / "status").exists()


def test_concrete_wrapper_overwrite_reruns_finished_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=True, overwrite=True)
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is True


def test_concrete_wrapper_skips_previous_skipped_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="skipped")
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_skips_previous_aborted_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="abort")
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_does_not_overwrite_previous_aborted_summary(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="abort", overwrite=True)
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is False


def test_concrete_wrapper_reruns_previous_retryable_error(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, status="error")
    ran = False

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        nonlocal ran
        ran = True

    engine.run_concrete = run_concrete

    engine.concrete_wrapper("case_1", sps=None)

    assert ran is True


def test_concrete_wrapper_does_not_create_status_dir_on_failure(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
        raise RuntimeError("failed")

    engine.run_concrete = run_concrete

    with pytest.raises(RuntimeError, match="failed"):
        engine.concrete_wrapper("case_1", sps=None)

    assert not (tmp_path / "outputs" / "case_1" / "status").exists()


def test_concrete_wrapper_records_failed_precondition_skip(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
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

    def run_concrete(output_related, sps, params=None, *, sim_params=None):
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

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
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

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
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

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [
        ("iteration_case_a", {"speed": 10}),
        ("iteration_case_b", {"offset": -1.5, "behavior": "cutin"}),
    ]


def test_run_logical_passes_derived_sim_params_separately(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler(
        [
            Sample(
                id="cutin",
                params={"ego_s": 100, "relative_dist": 25},
                metadata={
                    "sim_params": {
                        "ego_s": 100,
                        "relative_dist": 25,
                        "agent_s": 125,
                    }
                },
            ),
        ]
    )
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    calls = []

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        calls.append((output_related, params, sim_params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [
        (
            "iteration_cutin",
            {"ego_s": 100, "relative_dist": 25},
            {"ego_s": 100, "relative_dist": 25, "agent_s": 125},
        )
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

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        calls.append((output_related, params))

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert calls == [("iteration_case_b", {"speed": 20})]


def test_run_logical_emits_growing_progress_with_total(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler([{"speed": 10}, {"speed": 20}, {"speed": 30}])
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    updates = []
    engine._progress_callback = updates.append

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        engine.monitor.current_summary_counts["finished"] += 1

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    # One emit before each concrete (0,1,2 done) plus a final emit (3 done).
    assert [(u.total, u.finished) for u in updates] == [(3, 0), (3, 1), (3, 2), (3, 3)]
    assert all(u.aborted == 0 and u.skipped == 0 for u in updates)
    # FakeMonitor exposes no outcomes, so every tick is count-only.
    assert all(u.outcome is None for u in updates)


def test_run_logical_emits_each_outcome_exactly_once(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine.param_sampler = FakeSampler([{"speed": 10}, {"speed": 20}])
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    outcomes: list[ConcreteOutcome] = []
    engine.monitor.concrete_outcomes = lambda: list(outcomes)
    updates = []
    engine._progress_callback = updates.append

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        engine.monitor.current_summary_counts["finished"] += 1
        outcomes.append(
            ConcreteOutcome(
                concrete_key=output_related,
                status="finished",
                test_outcome="success",
                reason="",
                stop_condition="",
                params=params,
                final_sim_time_ms=0.0,
                wall_time_ms=0.0,
                total_steps=0,
            )
        )

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    # Each finalised concrete is handed to the callback exactly once.
    emitted = [u.outcome.concrete_key for u in updates if u.outcome is not None]
    assert emitted == ["iteration_1", "iteration_2"]
    # The leading tick is the count-only "started, total=N" announcement.
    assert updates[0].outcome is None and updates[0].finished == 0


def test_run_logical_updates_sampler_with_concrete_outcome_metrics(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    sampler = FakeSampler([{"speed": 10}])
    engine.param_sampler = sampler
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    outcomes: list[ConcreteOutcome] = []
    engine.monitor.concrete_outcomes = lambda: list(outcomes)

    def concrete_wrapper(output_related, sps, params=None, *, sim_params=None):
        outcomes.append(
            ConcreteOutcome(
                concrete_key=output_related,
                status="finished",
                test_outcome="fail",
                reason="low TTC",
                stop_condition="ttc_guard",
                params=params,
                final_sim_time_ms=100.0,
                wall_time_ms=10.0,
                total_steps=10,
                metrics={"ego_ttc.min_ttc_s": 0.4},
            )
        )

    engine.concrete_wrapper = concrete_wrapper

    engine.run_logical()

    assert len(sampler.updates) == 1
    sample, result = sampler.updates[0]
    assert sample.params == {"speed": 10}
    assert result.status == "finished"
    assert result.test_outcome == "fail"
    assert result.metrics == {"ego_ttc.min_ttc_s": 0.4}


def test_run_logical_emits_total_none_for_open_ended_sampler(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)
    sampler = FakeSampler([{"speed": 10}])
    sampler.total_samples = lambda: None
    engine.param_sampler = sampler
    engine.max_sampler_iterations = None
    engine.sps = None
    engine._permutation = None
    updates = []
    engine._progress_callback = updates.append

    engine.concrete_wrapper = lambda output_related, sps, params=None, *, sim_params=None: None

    engine.run_logical()

    assert updates
    assert all(u.total is None for u in updates)


def test_emit_progress_swallows_callback_errors(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, finished=False)

    def boom(update):
        raise RuntimeError("reporting backend down")

    engine._progress_callback = boom

    # Must not raise — telemetry failure cannot abort a run.
    engine._emit_progress(5)


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

    def should_stop(check_external_quit=True):
        assert check_external_quit is False
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


def test_run_concrete_logs_sampled_params_but_resets_sim_with_sim_params(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine._dt_s = 0.1
    engine._speedup_ratio = 0
    monitor = FakeMonitor(status=None)
    engine.monitor = monitor
    engine.av = SimpleNamespace(reset=lambda output_related, sps, raw_obs: None)
    sim_calls = []

    def sim_reset(output_related, sps, params):
        sim_calls.append((output_related, params))
        return SimpleNamespace(objects=[])

    engine.sim = SimpleNamespace(reset=sim_reset)

    def should_stop(check_external_quit=True):
        return len(monitor.finalize_calls) == 0 and len(sim_calls) > 0

    monitor.should_stop = should_stop

    engine.run_concrete(
        "case_1",
        sps=None,
        params={"ego_s": 100, "relative_dist": 25},
        sim_params={"ego_s": 100, "relative_dist": 25, "agent_s": 125},
    )

    assert monitor.reset_call == ("case_1", {"ego_s": 100, "relative_dist": 25}, False)
    assert sim_calls == [("case_1", {"ego_s": 100, "relative_dist": 25, "agent_s": 125})]


def test_run_concrete_records_reset_frame_at_time_zero_before_stepping(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path, finished=False)
    engine._dt_s = 0.1
    engine._speedup_ratio = 0
    monitor = FakeMonitor(status=None)
    engine.monitor = monitor

    reset_frame = SimpleNamespace(objects=["initial"])
    step_frame = SimpleNamespace(objects=["after_step"])
    sim_step_times = []
    av_step_times = []

    def sim_step(ctrl_for_sim, sim_time_ns):
        sim_step_times.append((ctrl_for_sim, sim_time_ns))
        return step_frame

    def av_step(raw_obs, sim_time_ns):
        av_step_times.append((raw_obs, sim_time_ns))
        return "ctrl_after_step"

    engine.sim = SimpleNamespace(
        reset=lambda output_related, sps, params: reset_frame,
        step=sim_step,
    )
    engine.av = SimpleNamespace(
        reset=lambda output_related, sps, raw_obs: "ctrl_initial",
        step=av_step,
    )

    def should_stop(check_external_quit=True):
        if not check_external_quit:
            return False
        return len(monitor.updates) >= 2

    monitor.should_stop = should_stop

    engine.run_concrete("case_1", sps=None)

    assert monitor.updates == [
        (0, reset_frame, "ctrl_initial"),
        (100_000_000, step_frame, "ctrl_after_step"),
    ]
    assert sim_step_times == [("ctrl_initial", 100_000_000)]
    assert av_step_times == [(["after_step"], 100_000_000)]
    assert monitor.finalize_calls == [("finished", "monitor_stop")]
