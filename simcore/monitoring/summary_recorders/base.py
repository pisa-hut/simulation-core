from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from simcore.monitoring.sample import MonitorSample


@dataclass(frozen=True)
class SummaryContext:
    status: str
    test_outcome: str
    stop_condition: str
    stop_reason: str
    total_steps: int
    final_sim_time_ms: float
    wall_time_ms: float
    speedup: float
    params: dict[str, Any]
    job_id: str


class SummaryRecorder(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name = str(config.get("name", config["type"]))

    @abstractmethod
    def fields(self) -> tuple[str, ...]:
        pass

    def reset(self) -> None:
        return None

    def update(self, sample: MonitorSample) -> None:
        return None

    @abstractmethod
    def record(self, context: SummaryContext) -> dict[str, Any]:
        pass
