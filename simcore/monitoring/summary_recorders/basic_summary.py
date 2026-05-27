from __future__ import annotations

from typing import Any

from .base import SummaryContext, SummaryRecorder

BASIC_SUMMARY_FIELDS = (
    "status",
    "stop_reason",
    "total_steps",
    "final_sim_time_ms",
    "error_type",
    "error_message",
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
            "error_type": type(context.error).__name__ if context.error else "",
            "error_message": str(context.error) if context.error else "",
        }
