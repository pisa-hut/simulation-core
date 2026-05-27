from __future__ import annotations

from abc import ABC, abstractmethod

from simcore.monitoring.log_manager import LogStream
from simcore.monitoring.sample import LogRow, MonitorSample


class Recorder(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name = str(config.get("name", config["type"]))
        self.every_n_steps = max(1, int(config.get("every_n_steps", 1)))
        self.output = str(config.get("output", f"{self.name}.csv"))

    @abstractmethod
    def streams(self) -> list[LogStream]:
        pass

    def reset(self) -> None:
        return None

    def update(self, sample: MonitorSample) -> list[LogRow]:
        if sample.step_index % self.every_n_steps != 0:
            return []
        return self.record(sample)

    def finalize(self) -> list[LogRow]:
        return []

    @abstractmethod
    def record(self, sample: MonitorSample) -> list[LogRow]:
        pass
