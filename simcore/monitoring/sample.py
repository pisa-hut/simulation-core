from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MonitorSample:
    step_index: int
    sim_time_ns: int
    runtime_frame: Any
    control: Any

    @property
    def sim_time_ms(self) -> float:
        return self.sim_time_ns / 1e6

    def __getitem__(self, index: int) -> Any:
        return (self.sim_time_ns, self.runtime_frame, self.control)[index]


@dataclass(frozen=True)
class LogRow:
    stream: str
    row: dict[str, Any]
