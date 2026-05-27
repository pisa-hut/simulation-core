from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LogStream:
    name: str
    filename: str
    fields: tuple[str, ...]


class LogManager:
    def __init__(
        self,
        output_dir: Path,
        streams: list[LogStream],
        flush_every_n_rows: int = 100,
        float_precision: int = 6,
    ) -> None:
        self.output_dir = output_dir
        self.flush_every_n_rows = max(1, int(flush_every_n_rows))
        self.float_precision = max(0, int(float_precision))
        self._files = {}
        self._writers = {}
        self._fields_by_stream = {}
        self._row_counts = {}

        self.output_dir.mkdir(parents=True, exist_ok=True)
        filenames = [stream.filename for stream in streams]
        if len(set(filenames)) != len(filenames):
            raise ValueError("Monitor log streams must not share the same filename")
        for stream in streams:
            self._open_stream(stream)

    def write(self, stream_name: str, row: dict[str, Any]) -> None:
        if stream_name not in self._writers:
            raise ValueError(f"Unknown monitor log stream: {stream_name}")

        fields = self._fields_by_stream[stream_name]
        unexpected_fields = sorted(set(row) - set(fields))
        if unexpected_fields:
            raise ValueError(
                f"Unexpected field(s) for monitor log stream {stream_name!r}: "
                f"{', '.join(unexpected_fields)}"
            )

        self._writers[stream_name].writerow(
            {field: self._format_value(row.get(field)) for field in fields}
        )
        self._row_counts[stream_name] += 1
        if self._row_counts[stream_name] % self.flush_every_n_rows == 0:
            self._files[stream_name].flush()

    def close(self) -> None:
        for file in self._files.values():
            file.flush()
            file.close()
        self._files.clear()
        self._writers.clear()
        self._fields_by_stream.clear()
        self._row_counts.clear()

    def _open_stream(self, stream: LogStream) -> None:
        if stream.name in self._writers:
            raise ValueError(f"Duplicate monitor log stream name: {stream.name}")
        if len(set(stream.fields)) != len(stream.fields):
            raise ValueError(f"Duplicate field in monitor log stream: {stream.name}")

        path = self.output_dir / stream.filename
        file = path.open("w", newline="")
        writer = csv.DictWriter(file, fieldnames=list(stream.fields), extrasaction="raise")
        writer.writeheader()

        self._files[stream.name] = file
        self._writers[stream.name] = writer
        self._fields_by_stream[stream.name] = stream.fields
        self._row_counts[stream.name] = 0

    def _format_value(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.{self.float_precision}f}"
        return value
