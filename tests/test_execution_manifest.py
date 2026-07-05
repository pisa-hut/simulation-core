from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from simcore.execution import ExecResult, RetryHint
from simcore.execution_manifest import (
    build_execution_manifest,
    finalize_execution_manifest,
    validate_existing_manifest,
    write_execution_manifest,
)


def test_execution_manifest_contains_execution_provenance(tmp_path: Path) -> None:
    runner_spec = tmp_path / "spec.json"
    runner_spec.write_text('{"runtime":{"dt":0.05}}\n', encoding="utf-8")
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    sim_config = tmp_path / "sim.yaml"
    sim_config.write_text("sim: true\n", encoding="utf-8")

    spec = {
        "runtime": {"dt": 0.05, "overwrite": True, "max_concrete_retries": 2},
        "task": {"job_id": "7"},
        "scenario": {"title": "sakura_cutin"},
        "sampler": {"name": "lhs", "seed": 11},
        "map": {"name": "straight_3000m"},
        "metadata": {
            "ego_agent_id": 0,
            "paper_baseline": "must_not_be_written",
        },
    }

    manifest = build_execution_manifest(
        spec,
        output_base=tmp_path / "outputs",
        resolved_inputs={
            "runner_spec": runner_spec,
            "scenario": scenario,
            "simulator_config": sim_config,
            "av_config": None,
            "sampler_config": None,
            "monitor_config": None,
            "stop_conditions": None,
        },
        runner_spec_path=runner_spec,
    )

    assert manifest["schema_version"] == 1
    assert manifest["dt"] == 0.05
    assert manifest["seed"] == 11
    assert manifest["scenario_name"] == "sakura_cutin"
    assert manifest["execution"]["job_id"] == "7"
    assert manifest["execution"]["overwrite"] is True
    assert manifest["execution"]["max_concrete_retries"] == 2
    assert manifest["metadata"]["map_name"] == "straight_3000m"
    assert manifest["metadata"]["ego_agent_id"] == 0
    assert "paper_baseline" not in manifest["metadata"]
    assert manifest["resolved_inputs"]["runner_spec"] == str(runner_spec.resolve())
    assert manifest["resolved_inputs"]["scenario"] == str(scenario.resolve())
    assert manifest["resolved_input_sha256"]["simulator_config"]
    assert manifest["runner_spec_sha256"]
    assert manifest["sampler_seed"] == 11
    assert manifest["simulator_seed"] is None
    assert manifest["av_seed"] is None
    assert manifest["execution_seed"] is None
    assert manifest["actors"][0]["role"] == "ego"


def test_existing_compatible_manifest_supports_restart(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "dt": 0.1,
        "seed": None,
        "scenario_name": "case",
        "resolved_inputs": {"runner_spec": None},
        "execution": {
            "job_id": "0",
            "permutation": None,
            "overwrite": False,
            "max_concrete_retries": 3,
        },
    }
    existing = {**expected, "execution_id": "existing-lineage"}

    validate_existing_manifest(existing, expected)


def test_existing_legacy_manifest_may_omit_new_resolved_inputs(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "dt": 0.1,
        "seed": None,
        "scenario_name": "case",
        "resolved_inputs": {
            "runner_spec": "/repo/spec.json",
            "sampler_source": "/scenario/range.yaml",
            "map_xodr": "/map/xodr",
        },
        "execution": {
            "job_id": "0",
            "permutation": None,
            "overwrite": False,
            "max_concrete_retries": 3,
        },
    }
    existing = {
        **expected,
        "resolved_inputs": {
            "runner_spec": "/repo/spec.json",
        },
    }

    validate_existing_manifest(existing, expected)


def test_existing_manifest_allows_overwrite_policy_change(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "dt": 0.1,
        "seed": None,
        "scenario_name": "case",
        "resolved_inputs": {"runner_spec": "/repo/spec.json"},
        "execution": {
            "job_id": "0",
            "permutation": None,
            "overwrite": False,
            "max_concrete_retries": 3,
        },
    }
    existing = {
        **expected,
        "execution": {
            "job_id": "0",
            "permutation": None,
            "overwrite": True,
            "max_concrete_retries": 3,
        },
    }

    validate_existing_manifest(existing, expected)


def test_existing_manifest_allows_worker_and_retry_policy_change(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "dt": 0.1,
        "seed": None,
        "scenario_name": "case",
        "resolved_inputs": {"runner_spec": "/new-worker/spec.json"},
        "execution": {
            "job_id": "slurm-2002",
            "permutation": 7,
            "overwrite": False,
            "max_concrete_retries": 5,
        },
    }
    existing = {
        **expected,
        "resolved_inputs": {"runner_spec": "/old-worker/spec.json"},
        "execution": {
            "job_id": "slurm-1001",
            "permutation": 7,
            "overwrite": True,
            "max_concrete_retries": 2,
        },
    }

    validate_existing_manifest(existing, expected)


def test_existing_manifest_compares_resolved_input_content_not_mount_path(
    tmp_path: Path,
) -> None:
    old_config = tmp_path / "old-mount" / "sim.yaml"
    new_config = tmp_path / "new-mount" / "sim.yaml"
    old_config.parent.mkdir()
    new_config.parent.mkdir()
    old_config.write_text("seed: 42\n", encoding="utf-8")
    new_config.write_text("seed: 42\n", encoding="utf-8")

    base_spec = {"runtime": {"dt": 0.1}, "scenario": {"title": "case"}}
    existing = build_execution_manifest(
        base_spec,
        output_base=tmp_path / "output",
        resolved_inputs={"simulator_config": old_config},
    )
    expected = build_execution_manifest(
        base_spec,
        output_base=tmp_path / "output",
        resolved_inputs={"simulator_config": new_config},
    )

    validate_existing_manifest(existing, expected)


def test_existing_manifest_rejects_changed_resolved_input_content(tmp_path: Path) -> None:
    old_config = tmp_path / "old-mount" / "sim.yaml"
    new_config = tmp_path / "new-mount" / "sim.yaml"
    old_config.parent.mkdir()
    new_config.parent.mkdir()
    old_config.write_text("seed: 42\n", encoding="utf-8")
    new_config.write_text("seed: 43\n", encoding="utf-8")

    base_spec = {"runtime": {"dt": 0.1}, "scenario": {"title": "case"}}
    existing = build_execution_manifest(
        base_spec,
        output_base=tmp_path / "output",
        resolved_inputs={"simulator_config": old_config},
    )
    expected = build_execution_manifest(
        base_spec,
        output_base=tmp_path / "output",
        resolved_inputs={"simulator_config": new_config},
    )

    with pytest.raises(ValueError, match="resolved input content differs for simulator_config"):
        validate_existing_manifest(existing, expected)


def test_existing_incompatible_manifest_is_rejected(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "dt": 0.1,
        "seed": None,
        "scenario_name": "case",
        "resolved_inputs": {"runner_spec": None},
        "execution": {
            "job_id": "0",
            "permutation": None,
            "overwrite": False,
            "max_concrete_retries": 3,
        },
    }
    existing = {**expected, "dt": 0.2}

    with pytest.raises(ValueError, match="dt differs"):
        validate_existing_manifest(existing, expected)


def test_write_execution_manifest_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "execution_manifest.yaml"

    write_execution_manifest(path, {"schema_version": 1, "execution_id": "abc"})

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["execution_id"] == "abc"
    assert not (tmp_path / "execution_manifest.yaml.tmp").exists()


def test_finalize_execution_manifest_preserves_initial_provenance(tmp_path: Path) -> None:
    path = tmp_path / "execution_manifest.yaml"
    initial = {
        "schema_version": 1,
        "execution_id": "abc",
        "created_at": "2026-06-15T12:00:00Z",
        "dt": 0.05,
        "summary": {"finished": 0, "failed": 0, "skipped": 0, "aborted": 0},
    }
    write_execution_manifest(path, initial)

    finalize_execution_manifest(
        path,
        result=ExecResult(
            hint=RetryHint.OK,
            reason="completed",
            finished_concrete_runs=1,
            aborted_concrete_runs=0,
            skipped_concrete_runs=0,
            concrete_outcomes=[],
        ),
        monitor_counts={"finished": 1, "failed": 2, "skipped": 3, "aborted": 4},
    )

    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert manifest["execution_id"] == "abc"
    assert manifest["created_at"] == "2026-06-15T12:00:00Z"
    assert manifest["dt"] == 0.05
    assert manifest["completed_at"]
    assert manifest["summary"] == {
        "finished": 1,
        "failed": 2,
        "skipped": 3,
        "aborted": 4,
    }


def test_execution_manifest_infers_ego_agent_id_from_monitor_config(tmp_path: Path) -> None:
    monitor_config = tmp_path / "monitor.yaml"
    monitor_config.write_text(
        """
logging:
  frame:
    recorders:
      - type: ego_state
        actor_id: 7
""",
        encoding="utf-8",
    )

    manifest = build_execution_manifest(
        {
            "runtime": {"dt": 0.1},
            "scenario": {"title": "case"},
            "monitor": {"config_path": str(monitor_config)},
            "map": {"name": "map"},
        },
        output_base=tmp_path / "outputs",
        resolved_inputs={"monitor_config": monitor_config},
    )

    assert manifest["metadata"]["ego_agent_id"] == 7
    assert manifest["actors"][0]["id"] == 7
    assert manifest["actors"][0]["role"] == "ego"


def test_execution_manifest_hashes_directory_deterministically(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    (scenario / "b.txt").write_text("b", encoding="utf-8")
    (scenario / "a.txt").write_text("a", encoding="utf-8")
    (scenario / "__pycache__").mkdir()
    (scenario / "__pycache__" / "ignored.pyc").write_text("ignored", encoding="utf-8")

    manifest_a = build_execution_manifest(
        {"runtime": {"dt": 0.1}, "scenario": {"title": "case"}},
        output_base=tmp_path / "outputs_a",
        resolved_inputs={"scenario": scenario},
    )
    manifest_b = build_execution_manifest(
        {"runtime": {"dt": 0.1}, "scenario": {"title": "case"}},
        output_base=tmp_path / "outputs_b",
        resolved_inputs={"scenario": scenario},
    )

    assert manifest_a["resolved_input_sha256"]["scenario"]
    assert (
        manifest_a["resolved_input_sha256"]["scenario"]
        == manifest_b["resolved_input_sha256"]["scenario"]
    )
