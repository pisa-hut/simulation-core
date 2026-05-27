from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from simcore.monitoring.sample import MonitorSample


class FrameRecorder(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name = str(config.get("name", config["type"]))

    @abstractmethod
    def fields(self) -> tuple[str, ...]:
        pass

    def reset(self) -> None:
        return None

    @abstractmethod
    def record(self, sample: MonitorSample) -> dict[str, Any]:
        pass

    def _select_fields(
        self,
        config: dict,
        available_fields: tuple[str, ...],
    ) -> tuple[str, ...]:
        selected_fields = config.get("fields", available_fields)
        if not isinstance(selected_fields, list | tuple):
            raise ValueError(f"Frame recorder {self.name!r} config 'fields' must be a list")

        unknown_fields = sorted(set(selected_fields) - set(available_fields))
        if unknown_fields:
            raise ValueError(
                f"Unknown field(s) for frame recorder {self.name!r}: {', '.join(unknown_fields)}"
            )

        return tuple(str(field) for field in selected_fields)
