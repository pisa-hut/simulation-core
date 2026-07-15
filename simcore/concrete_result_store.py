from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONCRETE_RESULT_SCHEMA_VERSION = 1
CONCRETE_RESULT_FILENAME = "concrete_result.jsonl"
TERMINAL_CONCRETE_STATUSES = {"finished", "skipped", "abort"}


class ConcreteResultStore:
    """Append-only cache of terminal concrete results.

    Per-concrete ``result.csv`` files remain the source of truth. This store avoids
    reopening hundreds of small files while replaying adaptive sampler feedback.
    """

    def __init__(self, output_base: Path, filename: str = CONCRETE_RESULT_FILENAME) -> None:
        self.path = output_base / filename
        self._results: dict[str, dict[str, Any]] = {}
        self._load()

    def latest(self, concrete_key: str) -> dict[str, Any] | None:
        result = self._results.get(concrete_key)
        return dict(result) if result is not None else None

    def all_latest(self) -> dict[str, dict[str, Any]]:
        return {key: dict(value) for key, value in self._results.items()}

    def append(self, result: dict[str, Any]) -> None:
        normalized = self._validate(result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as file:
            file.write(payload)
            file.write("\n")
            file.flush()
        self._results[normalized["concrete_key"]] = normalized

    def clear(self) -> None:
        self._results.clear()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to remove stale concrete result ledger: %s", self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            logger.exception("Failed to read concrete result ledger: %s", self.path)
            return

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                normalized = self._validate(raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Ignoring invalid concrete result ledger entry %s:%d: %s",
                    self.path,
                    line_number,
                    exc,
                )
                continue
            self._results[normalized["concrete_key"]] = normalized

    @staticmethod
    def _validate(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise TypeError("concrete result ledger entry must be a mapping")
        schema_version = result.get("schema_version")
        if schema_version != CONCRETE_RESULT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported concrete result schema_version={schema_version!r}; "
                f"expected {CONCRETE_RESULT_SCHEMA_VERSION}"
            )
        concrete_key = result.get("concrete_key")
        if not isinstance(concrete_key, str) or not concrete_key:
            raise ValueError("concrete result ledger entry requires concrete_key")
        status = str(result.get("status", "")).strip().lower()
        if status not in TERMINAL_CONCRETE_STATUSES:
            raise ValueError(f"non-terminal concrete result status: {status!r}")
        params = result.get("params")
        metrics = result.get("metrics")
        if params is not None and not isinstance(params, dict):
            raise ValueError("concrete result params must be a mapping or null")
        if metrics is not None and not isinstance(metrics, dict):
            raise ValueError("concrete result metrics must be a mapping or null")

        normalized = dict(result)
        normalized["concrete_key"] = concrete_key
        normalized["status"] = status
        normalized["params"] = dict(params or {})
        normalized["metrics"] = dict(metrics or {})
        return normalized


def concrete_result_entry(
    *,
    concrete_key: str,
    sample_id: str,
    attempt: int,
    parameter_hash: str,
    params: dict[str, Any] | None,
    status: str,
    test_outcome: str,
    stop_condition: str,
    reason: str,
    metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": CONCRETE_RESULT_SCHEMA_VERSION,
        "concrete_key": concrete_key,
        "sample_id": sample_id,
        "attempt": attempt,
        "parameter_hash": parameter_hash,
        "params": dict(params or {}),
        "status": status,
        "test_outcome": test_outcome,
        "stop_condition": stop_condition,
        "reason": reason,
        "metrics": dict(metrics or {}),
    }


def entry_as_summary_row(entry: dict[str, Any]) -> dict[str, Any]:
    row = {
        "run.status": entry.get("status"),
        "run.test_outcome": entry.get("test_outcome", "unknown"),
        "run.stop_condition": entry.get("stop_condition", ""),
        "run.stop_reason": entry.get("reason", ""),
        "run.sample_id": entry.get("sample_id", ""),
        "run.attempt": entry.get("attempt", ""),
        "run.parameter_hash": entry.get("parameter_hash", ""),
        "run.params": json.dumps(entry.get("params") or {}, sort_keys=True),
    }
    row.update(entry.get("metrics") or {})
    return row
