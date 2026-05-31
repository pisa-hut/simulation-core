from __future__ import annotations

import json
from typing import Any

from .base import SummaryContext, SummaryRecorder

BASIC_SUMMARY_FIELDS = (
    "status",
    "total_steps",
    "final_sim_time_ms",
    "wall_time_ms",
    "speedup",
    "job_id",
    "params",
    "stop_reason",
)


class BasicSummaryRecorder(SummaryRecorder):
    def fields(self) -> tuple[str, ...]:
        return BASIC_SUMMARY_FIELDS

    def record(self, context: SummaryContext) -> dict[str, Any]:
        return {
            "status": context.status,
            "stop_reason": context.stop_reason,
            "total_steps": context.total_steps,
            "final_sim_time_ms": context.final_sim_time_ms,
            "wall_time_ms": context.wall_time_ms,
            "speedup": context.speedup,
            "job_id": context.job_id,
            "params": json.dumps(context.params, sort_keys=True),
        }
