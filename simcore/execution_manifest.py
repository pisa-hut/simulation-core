from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from simcore.execution import ExecResult

SCHEMA_VERSION = 1
INCOMPATIBLE_FIELDS = (
    "dt",
    "seed",
    "scenario_name",
    "resolved_inputs",
    "execution",
)
ANALYSIS_POLICY_KEYS = {
    "av_comparison_group",
    "paper_baseline",
    "representative_case",
    "near_critical_threshold",
    "sampler_rank",
}


def build_execution_manifest(
    spec: dict,
    *,
    output_base: Path,
    resolved_inputs: dict[str, Path | None],
    runner_spec_path: Path | None = None,
) -> dict:
    runtime_spec = spec.get("runtime", {}) or {}
    task_spec = spec.get("task", {}) or {}
    scenario_spec = spec.get("scenario", {}) or {}
    sampler_spec = spec.get("sampler", {}) or {}
    simulator_spec = spec.get("simulator", {}) or {}
    av_spec = spec.get("av", {}) or {}
    map_spec = spec.get("map", {}) or {}

    resolved = dict(resolved_inputs)
    resolved.setdefault("runner_spec", runner_spec_path)
    runner_version = _package_version("simcore")
    pisa_api_version = _package_version("pisa-api")
    runner_git_sha = _git_short_sha()

    return {
        "schema_version": SCHEMA_VERSION,
        "execution_id": str(runtime_spec.get("execution_id") or uuid.uuid4()),
        "created_at": _utc_now(),
        "completed_at": None,
        "dt": runtime_spec.get("dt"),
        "seed": _effective_seed(sampler_spec),
        "sampler_seed": _seed_from(sampler_spec, "seed", "random_seed"),
        "simulator_seed": _seed_from(simulator_spec, "seed", "random_seed"),
        "av_seed": _seed_from(av_spec, "seed", "random_seed"),
        "execution_seed": _seed_from(runtime_spec, "seed", "execution_seed", "random_seed"),
        "scenario_name": scenario_spec.get("title"),
        "runner_version": runner_version,
        "pisa_api_version": pisa_api_version,
        "runner_git_sha": runner_git_sha,
        "runner_spec_sha256": _sha256_file(runner_spec_path),
        "resolved_inputs": _resolved_input_values(resolved),
        "resolved_input_sha256": _resolved_input_hashes(resolved),
        "execution": {
            "job_id": str(task_spec.get("job_id", "unknown_job")),
            "permutation": runtime_spec.get("permutation"),
            "overwrite": bool(runtime_spec.get("overwrite", False)),
            "max_concrete_retries": int(runtime_spec.get("max_concrete_retries", 3)),
        },
        "software": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "platform_detail": platform.platform(),
            "runner_version": runner_version,
            "runner_git_sha": runner_git_sha,
            "pisa_api_version": pisa_api_version,
            "simulator_version": simulator_spec.get("version"),
            "av_version": av_spec.get("version"),
            "simulator_image": simulator_spec.get("image"),
            "av_image": av_spec.get("image"),
        },
        "summary": {
            "finished": 0,
            "failed": 0,
            "skipped": 0,
            "aborted": 0,
        },
        "metadata": _execution_metadata(spec, map_spec),
        "actors": _actors_metadata(spec),
        "output_base": str(output_base),
    }


def validate_existing_manifest(existing: dict, expected: dict) -> None:
    if existing.get("schema_version") != expected.get("schema_version"):
        raise ValueError(
            "Existing execution_manifest.yaml has incompatible schema_version: "
            f"{existing.get('schema_version')!r}"
        )
    for field in INCOMPATIBLE_FIELDS:
        if not _compatible_value(existing.get(field), expected.get(field)):
            raise ValueError(
                "Existing execution_manifest.yaml is incompatible for this output root: "
                f"{field} differs"
            )


def write_execution_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def finalize_execution_manifest(
    path: Path,
    *,
    result: ExecResult,
    monitor_counts: dict,
) -> None:
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(existing, dict):
        existing = {}

    summary = {
        "finished": int(monitor_counts.get("finished", result.finished_concrete_runs)),
        "failed": int(monitor_counts.get("failed", 0)),
        "skipped": int(monitor_counts.get("skipped", result.skipped_concrete_runs)),
        "aborted": int(monitor_counts.get("aborted", result.aborted_concrete_runs)),
    }
    manifest = {
        **existing,
        "completed_at": _utc_now(),
        "summary": summary,
    }
    write_execution_manifest(path, manifest)


def load_execution_manifest(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Execution manifest must be a mapping: {path}")
    return loaded


def _compatible_value(existing: Any, expected: Any) -> bool:
    if isinstance(existing, dict) and isinstance(expected, dict):
        for key, existing_value in existing.items():
            if key not in expected:
                continue
            if not _compatible_value(existing_value, expected[key]):
                return False
        return True
    return existing == expected


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _effective_seed(sampler_spec: dict[str, Any]) -> Any:
    for key in ("seed", "random_seed"):
        if key in sampler_spec:
            return sampler_spec[key]
    return None


def _seed_from(config: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in config:
            return config[key]
    nested = config.get("metadata")
    if isinstance(nested, dict):
        for key in keys:
            if key in nested:
                return nested[key]
    return None


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _git_short_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def _resolved_input_values(resolved_inputs: dict[str, Path | None]) -> dict[str, str | None]:
    return {key: _path_value(path) for key, path in resolved_inputs.items()}


def _resolved_input_hashes(resolved_inputs: dict[str, Path | None]) -> dict[str, str | None]:
    return {key: _sha256_file(path) for key, path in resolved_inputs.items()}


def _path_value(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path.expanduser().resolve())


def _sha256_file(path: Path | None) -> str | None:
    if path is None:
        return None
    path = path.expanduser()
    if path.is_dir():
        return _sha256_directory(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    ignored_dirs = {".git", "__pycache__", ".pytest_cache"}
    files = sorted(
        file
        for file in path.rglob("*")
        if file.is_file() and not any(part in ignored_dirs for part in file.relative_to(path).parts)
    )
    for file in files:
        relative = file.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _execution_metadata(spec: dict[str, Any], map_spec: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(spec.get("metadata", {}) or {})
    metadata.update(spec.get("task", {}).get("metadata", {}) or {})
    metadata = {
        key: value for key, value in metadata.items() if key not in ANALYSIS_POLICY_KEYS
    }
    metadata.setdefault("map_name", map_spec.get("name"))
    metadata["ego_agent_id"] = _ego_agent_id(spec, metadata)
    return metadata


def _ego_agent_id(spec: dict[str, Any], metadata: dict[str, Any]) -> int:
    if metadata.get("ego_agent_id") is not None:
        return int(metadata["ego_agent_id"])
    monitor_path = (spec.get("monitor", {}) or {}).get("config_path")
    inferred = _ego_agent_id_from_monitor_config(monitor_path)
    return 0 if inferred is None else inferred


def _ego_agent_id_from_monitor_config(path: str | Path | None) -> int | None:
    if path is None:
        return None
    path = Path(path).expanduser()
    if not path.is_file():
        return None
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    logging_cfg = config.get("logging", {}) if isinstance(config, dict) else {}
    frame_cfg = logging_cfg.get("frame", {}) if isinstance(logging_cfg, dict) else {}
    recorders = frame_cfg.get("recorders", []) if isinstance(frame_cfg, dict) else []
    if not isinstance(recorders, list):
        return None
    for recorder in recorders:
        if not isinstance(recorder, dict):
            continue
        if str(recorder.get("type", "")).lower() != "ego_state":
            continue
        actor_id = recorder.get("actor_id", recorder.get("agent_id"))
        if actor_id is not None:
            return int(actor_id)
    return None


def _actors_metadata(spec: dict[str, Any]) -> list[dict[str, Any]]:
    raw_actors = []
    for section_name in ("metadata", "scenario"):
        section = spec.get(section_name, {}) or {}
        actors = section.get("actors") if isinstance(section, dict) else None
        if isinstance(actors, list):
            raw_actors.extend(actor for actor in actors if isinstance(actor, dict))
    ego_id = _ego_agent_id(spec, dict(spec.get("metadata", {}) or {}))
    normalized = []
    seen = set()
    for actor in raw_actors:
        if "id" not in actor:
            continue
        actor_id = int(actor["id"])
        if actor_id in seen:
            continue
        seen.add(actor_id)
        normalized.append(
            {
                "id": actor_id,
                "role": actor.get("role", "ego" if actor_id == ego_id else None),
                "length_m": actor.get("length_m"),
                "width_m": actor.get("width_m"),
                "height_m": actor.get("height_m"),
                "reference_point": actor.get("reference_point"),
                "source": actor.get("source", "spec"),
            }
        )
    if ego_id not in seen:
        normalized.insert(
            0,
            {
                "id": ego_id,
                "role": "ego",
                "length_m": None,
                "width_m": None,
                "height_m": None,
                "reference_point": None,
                "source": "inferred",
            },
        )
    return normalized
