import json
from pathlib import Path

import pytest

from simcore.concrete_result_store import (
    ConcreteResultStore,
    concrete_result_entry,
    entry_as_summary_row,
)
from simcore.monitor import Monitor


class FakeEndpoint:
    pass


def write_monitor_config(path: Path) -> Path:
    path.write_text(
        """
logging:
  enabled: true
  summary:
    include_basic: true
""",
        encoding="utf-8",
    )
    return path


def make_entry(concrete_key: str, *, status: str = "finished", outcome: str = "success"):
    return concrete_result_entry(
        concrete_key=concrete_key,
        sample_id=concrete_key.removeprefix("iteration_"),
        attempt=1,
        parameter_hash="hash-1",
        params={"speed": 10.0},
        status=status,
        test_outcome=outcome,
        stop_condition="goal",
        reason="completed",
        metrics={"ego_ttc.min_ttc_s": 1.25},
    )


def test_store_loads_latest_valid_entry_and_ignores_invalid_lines(tmp_path: Path) -> None:
    path = tmp_path / "concrete_result.jsonl"
    first = make_entry("iteration_1", outcome="success")
    latest = make_entry("iteration_1", outcome="fail")
    path.write_text(
        "\n".join(
            [
                json.dumps(first),
                "{truncated",
                json.dumps({**first, "schema_version": 99}),
                json.dumps(latest),
            ]
        ),
        encoding="utf-8",
    )

    store = ConcreteResultStore(tmp_path)

    assert store.latest("iteration_1")["test_outcome"] == "fail"


def test_store_rejects_non_terminal_results(tmp_path: Path) -> None:
    store = ConcreteResultStore(tmp_path)

    with pytest.raises(ValueError, match="non-terminal"):
        store.append(make_entry("iteration_1", status="error"))

    assert not store.path.exists()


def test_store_clear_removes_loaded_and_persisted_results(tmp_path: Path) -> None:
    store = ConcreteResultStore(tmp_path)
    store.append(make_entry("iteration_1"))

    store.clear()

    assert store.latest("iteration_1") is None
    assert not store.path.exists()


def test_entry_round_trips_as_feedback_summary_row() -> None:
    row = entry_as_summary_row(make_entry("iteration_1", outcome="fail"))

    assert row["run.status"] == "finished"
    assert row["run.test_outcome"] == "fail"
    assert row["run.parameter_hash"] == "hash-1"
    assert row["ego_ttc.min_ttc_s"] == 1.25


def test_monitor_appends_only_new_terminal_results(tmp_path: Path) -> None:
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(tmp_path / "outputs" / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset("iteration_1", params={"speed": 10.0}, parameter_hash="hash-1")
    monitor.finalize(status="error", reason="retry: unavailable")
    assert not (tmp_path / "outputs" / "concrete_result.jsonl").exists()

    monitor.reset("iteration_1", params={"speed": 10.0}, parameter_hash="hash-1")
    monitor.finalize(
        status="finished",
        reason="low TTC",
        test_outcome="fail",
        stop_condition="ttc_guard",
    )

    lines = (tmp_path / "outputs" / "concrete_result.jsonl").read_text().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["status"] == "finished"
    assert result["test_outcome"] == "fail"
    assert result["attempt"] == 2

    assert monitor.last_summary_status("iteration_1", parameter_hash="hash-1") == "finished"
    assert len((tmp_path / "outputs" / "concrete_result.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("status", ["finished", "skipped", "abort"])
def test_monitor_backfills_legacy_terminal_result(tmp_path: Path, status: str) -> None:
    output_base = tmp_path / "outputs"
    result_dir = output_base / "iteration_7" / "monitor"
    result_dir.mkdir(parents=True)
    (result_dir / "result.csv").write_text(
        "run.status,run.test_outcome,run.sample_id,run.attempt,run.parameter_hash,run.params,ego_ttc.min_ttc_s\n"
        f'{status},fail,7,1,hash-7,"{{""speed"": 12.0}}",0.8\n',
        encoding="utf-8",
    )
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    row = monitor.terminal_summary_row("iteration_7", "hash-7")

    assert row["run.status"] == status
    assert row["ego_ttc.min_ttc_s"] == "0.8"
    ledger_entry = json.loads((output_base / "concrete_result.jsonl").read_text())
    assert ledger_entry["concrete_key"] == "iteration_7"
    assert ledger_entry["params"] == {"speed": 12.0}


def test_monitor_rejects_terminal_result_for_different_parameters(tmp_path: Path) -> None:
    output_base = tmp_path / "outputs"
    store = ConcreteResultStore(output_base)
    store.append(make_entry("iteration_1"))
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    with pytest.raises(ValueError, match="regenerated sample"):
        monitor.terminal_summary_row("iteration_1", "different-hash")


def test_monitor_uses_loaded_ledger_without_opening_legacy_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_base = tmp_path / "outputs"
    store = ConcreteResultStore(output_base)
    store.append(make_entry("iteration_1"))
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )
    monkeypatch.setattr(
        monitor,
        "summary_rows",
        lambda output_related: pytest.fail("legacy result.csv should not be opened"),
    )

    row = monitor.terminal_summary_row("iteration_1", "hash-1")

    assert row["run.test_outcome"] == "success"
    assert row["ego_ttc.min_ttc_s"] == 1.25


def test_monitor_overwrite_rebuilds_ledger_from_new_results(tmp_path: Path) -> None:
    output_base = tmp_path / "outputs"
    store = ConcreteResultStore(output_base)
    store.append(make_entry("iteration_1", outcome="fail"))
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    monitor.reset(
        "iteration_1",
        params={"speed": 10.0},
        overwrite_summary=True,
        parameter_hash="hash-1",
    )
    monitor.finalize(status="finished", test_outcome="success", reason="completed")

    lines = (output_base / "concrete_result.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["test_outcome"] == "success"


def test_monitor_terminal_counts_use_ledger_without_legacy_result(tmp_path: Path) -> None:
    output_base = tmp_path / "outputs"
    store = ConcreteResultStore(output_base)
    store.append(make_entry("iteration_1", status="finished"))
    store.append(make_entry("iteration_2", status="skipped"))
    store.append(make_entry("iteration_3", status="abort"))
    monitor = Monitor(
        config_path=str(write_monitor_config(tmp_path / "monitor.yaml")),
        log_file=str(output_base / "monitor_log.csv"),
        av=FakeEndpoint(),
        sim=FakeEndpoint(),
    )

    assert monitor.logical_terminal_counts() == {
        "finished": 1,
        "skipped": 1,
        "abort": 1,
    }
