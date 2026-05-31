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

    def should_quit(self) -> ShouldQuitResult:
        return self.result


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "monitor.yaml"
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
            ]
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
    assert rows[0]["ego_to_agent_1.min_ttc_s"] == "1.250000"
    assert rows[0]["ego.max_speed_mps"] == "4.000000"


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
    monitor.finalize(status="fail", reason="RuntimeError: failed once")
    assert monitor.has_finished_summary("case_1") is False

    monitor.reset("case_1")
    monitor.finalize(status="finished", reason="completed")
    assert monitor.has_finished_summary("case_1") is True

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert [row["run.status"] for row in rows] == ["fail", "finished"]
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
    monitor.finalize(status="fail", reason="RuntimeError: failed overwrite")

    rows = read_csv(output_base / "case_1" / "monitor" / "result.csv")
    assert [row["run.status"] for row in rows] == ["fail"]
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
    monitor.current_summary_counts = {"finished": 1, "fail": 1, "skipped": 1}
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

    monitor.close(ExecResult(1, RetryHint.OK, "completed"))

    rows = read_csv(output_base / "summary.csv")
    assert rows == [
        {
            "job_id": "test",
            "hint": "ok",
            "speedup": "2.0",
            "current_finished": "1",
            "current_failed": "1",
            "current_skipped": "1",
            "cumulative_finished": "1",
            "cumulative_failed": "1",
            "cumulative_skipped": "1",
            "reason": "completed",
        }
    ]


def test_monitor_logging_disabled_does_not_create_monitor_output(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
condition:
  type: timeout
  timeout_ms: 1000
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
    monitor.update(0, SimpleNamespace(objects=[]), None)
    monitor.finalize(status="finished", reason="completed")

    assert not (output_base / "case_1" / "monitor").exists()


def test_monitor_stop_reason_includes_condition_detail(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
condition:
  type: timeout
  name: timeout_guard
  timeout_ms: 1
""",
    )
    monitor = Monitor(
        config_path=str(config_path),
        log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("case_1")
    monitor.update(2_000_000, SimpleNamespace(objects=[]), None)

    assert monitor.should_stop() is True
    assert monitor.stop_reason.startswith("Stop condition 'timeout_guard' triggered:")
    assert "Timeout detected" in monitor.stop_reason


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
