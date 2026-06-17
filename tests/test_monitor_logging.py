import csv
import json
from pathlib import Path
from types import SimpleNamespace

from simcore.execution import ExecResult, RetryHint, ShouldQuitResult
from simcore.monitor import Monitor


class FakeEndpoint:
    def should_quit(self) -> bool:
        return False


class FakeShouldQuitEndpoint:
    def __init__(self, *, should_quit: bool, message: str = "") -> None:
        self.result = ShouldQuitResult(should_quit, message)
        self.calls = 0

    def should_quit(self) -> ShouldQuitResult:
        self.calls += 1
        return self.result


def write_config(tmp_path: Path, content: str, name: str = "monitor.yaml") -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def make_object(
    actor_id: int | None,
    x: float,
    y: float,
    *,
    yaw: float = 0.0,
    speed: float = 2.0,
):
    obj = SimpleNamespace(
        kinematic=SimpleNamespace(
            x=x,
            y=y,
            z=0.0,
            yaw=yaw,
            speed=speed,
            acceleration=0.5,
            yaw_rate=0.1,
            yaw_acceleration=0.01,
        )
    )
    if actor_id is not None:
        obj.actor_id = actor_id
    return obj


class FakeCollision:
    def __init__(
        self,
        *,
        occurred: bool,
        actor_a: int | None = None,
        actor_b: int | None = None,
    ) -> None:
        self.occurred = occurred
        if actor_a is not None:
            self.actor_a = actor_a
        if actor_b is not None:
            self.actor_b = actor_b

    def HasField(self, field_name: str) -> bool:
        return hasattr(self, field_name)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def assert_basic_summary_fields(row: dict[str, str], *, status: str, reason: str) -> None:
    assert row["run.status"] == status
    assert row["run.test_outcome"] == "unknown"
    assert row["run.stop_condition"] == ""
    assert row["run.stop_reason"] == reason
    assert row["run.job_id"] == "unknown_job"
    assert float(row["run.wall_time_ms"]) >= 0
    assert float(row["run.speedup"]) >= 0


def test_monitor_merges_frame_recorders_every_n_steps(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  float_precision: 6
  frame:
    every_n_steps: 2
    output: frame_metrics.csv
    recorders:
      - type: ego_state
        name: ego
        actor_id: 0
        fields: [x, y, speed]

      - type: pair_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(
        0,
        SimpleNamespace(
            objects=[
                make_object(0, 0.0, 0.0, speed=1.0),
                make_object(1, 10.0, 0.0, speed=0.0),
            ]
        ),
        None,
    )
    monitor.update(10_000_000, SimpleNamespace(objects=[make_object(0, 3.0, 4.0)]), None)
    monitor.update(
        20_000_000,
        SimpleNamespace(
            objects=[
                make_object(0, 2.0, 0.0, speed=1.0),
                make_object(1, 10.0, 0.0, speed=0.0),
            ]
        ),
        None,
    )
    monitor.finalize(status="finished", reason="condition:timeout")

    rows = read_csv(output_base / "case_1" / "monitor" / "frame_metrics.csv")
    assert [row["step_index"] for row in rows] == ["0", "2"]
    assert [row["sim_time_ms"] for row in rows] == ["0.000000", "20.000000"]
    assert [row["ego.x"] for row in rows] == ["0.000000", "2.000000"]
    assert [row["ego.speed"] for row in rows] == ["1.000000", "1.000000"]
    assert [row["ego_to_agent_1.distance_m"] for row in rows] == [
        "10.000000",
        "8.000000",
    ]
    assert [row["ego_to_agent_1.ttc_s"] for row in rows] == ["10.000000", "8.000000"]

    summary_rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert len(summary_rows) == 1
    assert_basic_summary_fields(summary_rows[0], status="finished", reason="condition:timeout")
    assert summary_rows[0]["run.total_steps"] == "3"
    assert summary_rows[0]["run.final_sim_time_ms"] == "20.000000"
    assert summary_rows[0]["run.params"] == "{}"

    outcomes = monitor.concrete_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].concrete_key == "case_1"
    assert outcomes[0].status == "finished"
    assert outcomes[0].test_outcome == "unknown"
    assert outcomes[0].reason == "condition:timeout"
    assert outcomes[0].total_steps == 3


def test_monitor_writes_agent_states_as_long_table(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  tables:
    - type: agent_states
      name: agent_states
      output: agent_states.csv
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(
        0,
        SimpleNamespace(
            objects=[
                make_object(0, 1.0, 2.0),
                make_object(12, 3.0, 4.0),
            ]
        ),
        None,
    )
    monitor.update(10_000_000, SimpleNamespace(objects=[make_object(12, 5.0, 6.0)]), None)
    monitor.finalize(status="finished", reason="sim_quit")

    rows = read_csv(output_base / "case_1" / "monitor" / "agent_states.csv")
    assert [(row["step_index"], row["agent_id"], row["x"]) for row in rows] == [
        ("0", "0", "1.000000"),
        ("0", "12", "3.000000"),
        ("1", "12", "5.000000"),
    ]


def test_monitor_writes_collision_events_as_sparse_table(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  tables:
    - type: collision_events
      name: collision_events
      output: collision_events.csv
      actor_id_a: 0
      deduplicate: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(
        0,
        SimpleNamespace(
            objects=[],
            collision=[
                FakeCollision(occurred=False, actor_a=0, actor_b=12),
                FakeCollision(occurred=True, actor_a=0, actor_b=12),
                FakeCollision(occurred=True, actor_a=3, actor_b=8),
            ],
        ),
        None,
    )
    monitor.update(
        10_000_000,
        SimpleNamespace(
            objects=[],
            collision=[
                FakeCollision(occurred=True, actor_a=12, actor_b=0),
                FakeCollision(occurred=True, actor_a=0, actor_b=7),
            ],
        ),
        None,
    )
    monitor.finalize(status="finished", reason="completed")

    rows = read_csv(output_base / "case_1" / "monitor" / "collision_events.csv")
    assert [(row["step_index"], row["actor_a"], row["actor_b"]) for row in rows] == [
        ("0", "0", "12"),
        ("1", "0", "7"),
    ]


def test_monitor_writes_summary_recorders(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    recorders:
      - type: collision
        name: ego_collision
        actor_id_a: 0

      - type: min_ttc
        name: ego_to_agent_1
        actor_id_a: 0
        actor_id_b: 1

      - type: max_speed
        name: ego
        actor_id: 0
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1", params={"speed": "10", "weather": "clear"})
    monitor.update(
        0,
        SimpleNamespace(
            objects=[
                make_object(0, 0.0, 0.0, speed=2.0),
                make_object(1, 10.0, 0.0, speed=0.0),
            ]
        ),
        None,
    )
    monitor.update(
        1_000_000,
        SimpleNamespace(
            objects=[
                make_object(0, 5.0, 0.0, speed=4.0),
                make_object(1, 10.0, 0.0, speed=0.0),
            ],
            collision=[FakeCollision(occurred=True, actor_a=0, actor_b=1)],
        ),
        None,
    )
    monitor.finalize(status="finished", reason="completed")

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert len(rows) == 1
    assert_basic_summary_fields(rows[0], status="finished", reason="completed")
    assert rows[0]["run.total_steps"] == "2"
    assert rows[0]["run.final_sim_time_ms"] == "1.000000"
    assert rows[0]["run.params"] == json.dumps({"speed": "10", "weather": "clear"}, sort_keys=True)
    assert rows[0]["ego_collision.collision"] == "True"
    assert rows[0]["ego_to_agent_1.min_ttc_s"] == "1.250000"
    assert rows[0]["ego.max_speed_mps"] == "4.000000"
    outcome = monitor.concrete_outcomes()[0]
    assert outcome.metrics == {
        "ego_collision.collision": True,
        "ego_to_agent_1.min_ttc_s": 1.25,
        "ego.max_speed_mps": 4.0,
    }


def test_monitor_writes_generic_numeric_summaries(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    recorders:
      - type: numeric_summary
        name: ego_deceleration
        source:
          type: kinematic
          actor_id: 0
          field: acceleration
        transforms: [negate, positive_part]
        aggregations: [max, mean, std]
        include_extrema_location: true

      - type: numeric_summary
        name: ego_to_agent_1_ttc
        source:
          type: pair_ttc
          field: ttc_s
          actor_id_a: 0
          actor_id_b: 1
        aggregations: [min]

      - type: numeric_summary
        name: ego_to_agent_1_distance
        source:
          type: relative_position
          field: distance_m
          source_actor_id: 0
          target_actor_id: 1
        aggregations: [min, max, mean]
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(
        0,
        SimpleNamespace(
            objects=[
                SimpleNamespace(
                    actor_id=0,
                    kinematic=SimpleNamespace(
                        x=0.0,
                        y=0.0,
                        yaw=0.0,
                        speed=4.0,
                        acceleration=-1.0,
                    ),
                ),
                make_object(1, 10.0, 0.0, speed=0.0),
            ]
        ),
        None,
    )
    monitor.update(
        1_000_000,
        SimpleNamespace(
            objects=[
                SimpleNamespace(
                    actor_id=0,
                    kinematic=SimpleNamespace(
                        x=4.0,
                        y=0.0,
                        yaw=0.0,
                        speed=2.0,
                        acceleration=-3.0,
                    ),
                ),
                make_object(1, 10.0, 0.0, speed=0.0),
            ]
        ),
        None,
    )
    monitor.finalize(status="finished", reason="completed")

    row = read_csv(output_base / "case_1" / "monitor" / "result.csv")[0]
    assert row["ego_deceleration.max"] == "3.000000"
    assert row["ego_deceleration.mean"] == "2.000000"
    assert row["ego_deceleration.std"] == "1.000000"
    assert row["ego_deceleration.count"] == "2"
    assert row["ego_deceleration.max_step_index"] == "1"
    assert row["ego_deceleration.max_sim_time_ms"] == "1.000000"
    assert row["ego_to_agent_1_ttc.min"] == "2.500000"
    assert row["ego_to_agent_1_ttc.count"] == "2"
    assert row["ego_to_agent_1_distance.min"] == "6.000000"
    assert row["ego_to_agent_1_distance.max"] == "10.000000"
    assert row["ego_to_agent_1_distance.mean"] == "8.000000"


def test_monitor_appends_summary_and_checks_last_finished_status(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.finalize(status="error", reason="RuntimeError: failed once")
    assert monitor.has_finished_summary("case_1") is False

    monitor.reset("case_1")
    monitor.finalize(status="finished", reason="completed")
    assert monitor.has_finished_summary("case_1") is True

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert [row["run.status"] for row in rows] == ["error", "finished"]
    assert [row["run.stop_reason"] for row in rows] == [
        "RuntimeError: failed once",
        "completed",
    ]


def test_monitor_overwrite_summary_replaces_previous_history(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.finalize(status="finished", reason="first run")

    monitor.reset("case_1", overwrite_summary=True)
    monitor.finalize(status="error", reason="RuntimeError: failed overwrite")

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert [row["run.status"] for row in rows] == ["error"]
    assert [row["run.stop_reason"] for row in rows] == ["RuntimeError: failed overwrite"]


def test_monitor_close_writes_current_and_cumulative_summary(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
        job_id="test",
    )
    monitor.current_summary_counts = {"finished": 1, "error": 1, "skipped": 1, "abort": 1}
    monitor.current_sim_time_ms = 1000.0
    monitor.current_wall_time_ms = 500.0

    summary_dir = output_base / "iteration_1" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "result.csv").write_text("run.status,run.stop_reason\nfinished,completed\n")
    summary_dir = output_base / "iteration_2" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "result.csv").write_text("run.status,run.stop_reason\nfail,retry: timeout\n")
    summary_dir = output_base / "iteration_3" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "result.csv").write_text("run.status,run.stop_reason\nskipped,dont_retry\n")
    summary_dir = output_base / "iteration_4" / "monitor"
    summary_dir.mkdir(parents=True)
    (summary_dir / "result.csv").write_text("run.status,run.stop_reason\nabort,retry limit\n")

    monitor.close(ExecResult(RetryHint.OK, "completed", 1, 1, 1, []))

    rows = read_csv(output_base / "summary.csv")
    assert rows == [
        {
            "job_id": "test",
            "hint": "ok",
            "speedup": "2.0",
            "current_finished": "1",
            "current_error": "1",
            "current_abort": "1",
            "current_skipped": "1",
            "current_success": "0",
            "current_test_fail": "0",
            "current_invalid": "0",
            "current_unknown": "0",
            "cumulative_finished": "1",
            "cumulative_error": "1",
            "cumulative_abort": "1",
            "cumulative_skipped": "1",
            "cumulative_success": "0",
            "cumulative_test_fail": "0",
            "cumulative_invalid": "0",
            "cumulative_unknown": "4",
            "reason": "completed",
        }
    ]


def test_monitor_logging_disabled_does_not_create_monitor_output(tmp_path: Path) -> None:
    stop_condition_config_path = write_config(
        tmp_path,
        """
type: timeout
timeout_ms: 1000
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        stop_condition_config_path=str(stop_condition_config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(0, SimpleNamespace(objects=[]), None)
    monitor.finalize(status="finished", reason="completed")

    assert not (output_base / "case_1" / "monitor").exists()


def test_monitor_stop_reason_includes_condition_detail(tmp_path: Path) -> None:
    stop_condition_config_path = write_config(
        tmp_path,
        """
type: timeout
name: timeout_guard
timeout_ms: 1
""",
    )
    monitor = Monitor(
        stop_condition_config_path=str(stop_condition_config_path),
        log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(2_000_000, SimpleNamespace(objects=[]), None)

    assert monitor.should_stop() is True
    assert monitor.stop_reason.startswith("Stop condition 'timeout_guard' triggered:")
    assert "Timeout detected" in monitor.stop_reason


def test_monitor_rejects_stop_condition_in_logging_config(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
condition:
  type: timeout
  timeout_ms: 1
""",
    )

    try:
        Monitor(
            config_path=str(config_path),
            log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
            av=FakeEndpoint(),
            sim=FakeEndpoint(),
        )
    except ValueError as exc:
        assert "stop condition fields" in str(exc)
    else:
        raise AssertionError("expected monitor logging config with condition to be rejected")


def test_monitor_rejects_logging_config_without_logging_key(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
frame:
  recorders: []
""",
    )

    try:
        Monitor(
            config_path=str(config_path),
            log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
            av=FakeEndpoint(),
            sim=FakeEndpoint(),
        )
    except ValueError as exc:
        assert "must contain 'logging'" in str(exc)
    else:
        raise AssertionError("expected monitor logging config without logging to be rejected")


def test_monitor_rejects_logging_in_stop_condition_config(tmp_path: Path) -> None:
    stop_condition_config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
stop_condition:
  type: timeout
  timeout_ms: 1
""",
    )

    try:
        Monitor(
            stop_condition_config_path=str(stop_condition_config_path),
            log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
            av=FakeEndpoint(),
            sim=FakeEndpoint(),
        )
    except ValueError as exc:
        assert "must not contain logging" in str(exc)
    else:
        raise AssertionError("expected monitor stop condition config with logging to be rejected")


def test_monitor_condition_list_defaults_to_or_and_records_test_outcome(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
        name="logging.yaml",
    )
    stop_condition_config_path = write_config(
        tmp_path,
        """
- type: timeout
  name: timeout_guard
  outcome: Fail
  timeout_ms: 1
- type: collision
  name: collision_guard
  outcome: Invalid
""",
        name="stop_condition.yaml",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        stop_condition_config_path=str(stop_condition_config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(2_000_000, SimpleNamespace(objects=[]), None)

    assert monitor.should_stop() is True
    assert monitor.stop_condition_name == "timeout_guard"
    assert monitor.test_outcome == "fail"

    monitor.finalize(status="finished", reason=monitor.stop_reason)
    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")

    assert rows[0]["run.status"] == "finished"
    assert rows[0]["run.test_outcome"] == "fail"
    assert rows[0]["run.stop_condition"] == "timeout_guard"
    assert rows[0]["run.stop_reason"].startswith("Stop condition 'timeout_guard' triggered:")


def test_monitor_records_outcome_from_top_level_compound_condition(
    tmp_path: Path,
) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
        name="logging.yaml",
    )
    stop_condition_config_path = write_config(
        tmp_path,
        """
- type: and
  name: invalid_cut_in_setup
  outcome: Invalid
  children:
    - type: timeout
      name: timeout_a
      timeout_ms: 1
    - type: timeout
      name: timeout_b
      timeout_ms: 1
""",
        name="stop_condition.yaml",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        stop_condition_config_path=str(stop_condition_config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(2_000_000, SimpleNamespace(objects=[]), None)

    assert monitor.should_stop() is True
    assert monitor.stop_condition_name == "invalid_cut_in_setup"
    assert monitor.test_outcome == "invalid"

    monitor.finalize(status="finished", reason=monitor.stop_reason)
    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")

    assert rows[0]["run.test_outcome"] == "invalid"
    assert rows[0]["run.stop_condition"] == "invalid_cut_in_setup"


def test_monitor_parameter_expression_uses_reset_params(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
        name="logging.yaml",
    )
    stop_condition_config_path = write_config(
        tmp_path,
        """
- type: parameter_expression
  name: invalid_speed_gap
  outcome: Invalid
  expression: "abs(a_speed - b_speed)"
  rule: le
  value: 5
""",
        name="stop_condition.yaml",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        stop_condition_config_path=str(stop_condition_config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1", params={"a_speed": 10, "b_speed": 7})

    assert monitor.should_stop() is True
    assert monitor.stop_condition_name == "invalid_speed_gap"
    assert monitor.test_outcome == "invalid"

    monitor.finalize(status="finished", reason=monitor.stop_reason)
    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")

    assert rows[0]["run.test_outcome"] == "invalid"
    assert rows[0]["run.stop_condition"] == "invalid_speed_gap"


def test_monitor_stop_condition_delay_records_clear_summary_reason(tmp_path: Path) -> None:
    logging_config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
        name="monitor.yaml",
    )
    stop_config_path = write_config(
        tmp_path,
        """
- type: kinematic_threshold
  name: delayed_speed_guard
  outcome: Fail
  actor_id: 0
  metric: speed
  rule: gt
  value: 5.0
  delay_ms: 100
""",
        name="stop_conditions.yaml",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(logging_config_path),
        stop_condition_config_path=str(stop_config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(0, SimpleNamespace(objects=[make_object(0, 0.0, 0.0, speed=10.0)]), None)

    assert monitor.should_stop(check_external_quit=False) is False

    monitor.update(
        50_000_000,
        SimpleNamespace(objects=[make_object(0, 0.0, 0.0, speed=0.0)]),
        None,
    )

    assert monitor.should_stop(check_external_quit=False) is False

    monitor.update(
        100_000_000,
        SimpleNamespace(objects=[make_object(0, 0.0, 0.0, speed=0.0)]),
        None,
    )

    assert monitor.should_stop(check_external_quit=False) is True
    assert monitor.stop_condition_name == "delayed_speed_guard"
    assert monitor.test_outcome == "fail"
    assert "Delay satisfied after 100.000 ms" in monitor.stop_reason
    assert "Original trigger:" in monitor.stop_reason

    monitor.finalize(status="finished", reason=monitor.stop_reason)

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert rows[0]["run.stop_condition"] == "delayed_speed_guard"
    assert rows[0]["run.test_outcome"] == "fail"
    assert "Delay satisfied after 100.000 ms" in rows[0]["run.stop_reason"]


def test_monitor_stop_reason_includes_av_should_quit_message(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeShouldQuitEndpoint(should_quit=True, message="route complete"),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")

    assert monitor.should_stop() is True
    assert monitor.stop_reason == "AV requested to stop: route complete"


def test_monitor_can_skip_external_should_quit_check(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    av = FakeShouldQuitEndpoint(should_quit=True, message="route complete")
    sim = FakeShouldQuitEndpoint(should_quit=True, message="simulation complete")
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=av,
        sim=sim,
    )

    monitor.reset("case_1")

    assert monitor.should_stop(check_external_quit=False) is False
    assert monitor.stop_reason == ""
    assert av.calls == 0
    assert sim.calls == 0


def test_monitor_stop_reason_includes_sim_should_quit_message(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
    )
    output_base = tmp_path / "outputs"
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeShouldQuitEndpoint(should_quit=True, message="simulation complete"),
    )

    monitor.reset("case_1")

    assert monitor.should_stop() is True
    assert monitor.stop_reason == "Simulator requested to stop: simulation complete"
