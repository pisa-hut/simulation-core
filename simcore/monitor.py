import csv
import logging
from pathlib import Path
from time import monotonic
from typing import Any

import yaml

from simcore.av_wrapper import AVWrapper
from simcore.conditions import ConditionCode, ConditionNode, build_condition_tree
from simcore.execution import ExecResult
from simcore.monitoring.frame_recorder_registry import build_frame_recorders
from simcore.monitoring.log_manager import LogManager, LogStream
from simcore.monitoring.recorder_registry import build_recorders
from simcore.monitoring.sample import MonitorSample
from simcore.monitoring.summary_recorder_registry import build_summary_recorders
from simcore.monitoring.summary_recorders import SummaryContext
from simcore.sim_wrapper import SimWrapper

logger = logging.getLogger(__name__)

SUMMARY_STREAM = "summary"
FRAME_STREAM = "frame"


class Monitor:
    def __init__(
        self,
        config_path: str | None,
        log_file: str,
        av: AVWrapper,
        sim: SimWrapper,
        sps=None,
        position_parser=None,
        job_id: str = "unknown_job",
    ):
        self.log_file = log_file
        self.av = av
        self.sim = sim
        self.job_id = job_id

        self.cfg: dict | None = None
        self.root: ConditionNode | None = None
        self.frame_recorders = []
        self.table_recorders = []
        self.summary_recorders = []
        self.log_manager: LogManager | None = None
        self.logging_enabled = False
        self.frame_logging_enabled = False
        self.summary_logging_enabled = False
        self.frame_output = "frame_metrics.csv"
        self.summary_output = "result.csv"
        self.frame_every_n_steps = 1
        self.logging_output_dir = "monitor"
        self.flush_every_n_rows = 100
        self.float_precision = 6
        self.step_index = 0
        self.final_sim_time_ns = 0
        self.stop_reason = ""
        self.params: dict[str, Any] = {}
        self.wall_start_time_s: float | None = None
        self.overwrite_summary = False
        self.current_summary_counts = {"finished": 0, "fail": 0, "skipped": 0}
        self.current_sim_time_ms = 0.0
        self.current_wall_time_ms = 0.0

        if not config_path:
            logger.warning("No monitor config_path provided; condition monitoring is disabled.")
            return

        self._load_config(config_path)
        self._configure_logging()

        condition_cfg = self.cfg.get("condition", self.cfg.get("stop_condition"))
        if condition_cfg is not None:
            if not isinstance(condition_cfg, dict):
                raise ValueError(
                    "Monitor config 'condition' must be a mapping describing a condition tree"
                )

            self.root = build_condition_tree(
                condition_cfg,
                context={
                    "sps": sps,
                    "position_parser": position_parser,
                },
            )
            logger.debug("Built condition tree: %s", self.root)
        elif not self.logging_enabled:
            raise ValueError(
                "Monitor config must contain 'condition', 'logging.frame.recorders', "
                "'logging.tables', or 'logging.summary.recorders'"
            )

    def _load_config(self, path: str) -> None:
        self.cfg = yaml.safe_load(Path(path).read_text())
        if not isinstance(self.cfg, dict):
            raise ValueError(
                f"Monitor config at {path!r} must deserialize to a mapping, got {type(self.cfg).__name__}"
            )

    def _configure_logging(self) -> None:
        logging_cfg = self.cfg.get("logging", {}) if self.cfg else {}
        if logging_cfg is None:
            logging_cfg = {}
        if not isinstance(logging_cfg, dict):
            raise ValueError("Monitor config 'logging' must be a mapping")

        frame_cfg = logging_cfg.get("frame", {})
        if frame_cfg is None:
            frame_cfg = {}
        if not isinstance(frame_cfg, dict):
            raise ValueError("Monitor config 'logging.frame' must be a mapping")

        frame_recorder_configs = frame_cfg.get("recorders", [])
        if frame_recorder_configs is None:
            frame_recorder_configs = []
        if not isinstance(frame_recorder_configs, list):
            raise ValueError("Monitor config 'logging.frame.recorders' must be a list")

        summary_cfg = logging_cfg.get("summary", {})
        if summary_cfg is None:
            summary_cfg = {}
        if not isinstance(summary_cfg, dict):
            raise ValueError("Monitor config 'logging.summary' must be a mapping")

        summary_recorder_configs = summary_cfg.get("recorders", [])
        if summary_recorder_configs is None:
            summary_recorder_configs = []
        if not isinstance(summary_recorder_configs, list):
            raise ValueError("Monitor config 'logging.summary.recorders' must be a list")

        table_recorder_configs = logging_cfg.get("tables", logging_cfg.get("recorders", []))
        if table_recorder_configs is None:
            table_recorder_configs = []
        if not isinstance(table_recorder_configs, list):
            raise ValueError("Monitor config 'logging.tables' must be a list")

        has_logging_config = bool(
            frame_recorder_configs or table_recorder_configs or summary_recorder_configs
        )
        self.logging_enabled = bool(logging_cfg.get("enabled", has_logging_config))
        self.logging_output_dir = str(logging_cfg.get("output_dir", "monitor"))
        self.flush_every_n_rows = int(logging_cfg.get("flush_every_n_rows", 100))
        self.float_precision = int(logging_cfg.get("float_precision", 6))
        self.frame_logging_enabled = bool(
            self.logging_enabled
            and frame_cfg.get("enabled", bool(frame_recorder_configs))
            and frame_recorder_configs
        )
        self.summary_logging_enabled = bool(
            self.logging_enabled and summary_cfg.get("enabled", True)
        )
        self.frame_output = str(frame_cfg.get("output", "frame_metrics.csv"))
        self.summary_output = str(summary_cfg.get("output", "result.csv"))
        self.frame_every_n_steps = max(1, int(frame_cfg.get("every_n_steps", 1)))
        self.frame_recorders = (
            build_frame_recorders(frame_recorder_configs) if self.frame_logging_enabled else []
        )
        self.table_recorders = (
            build_recorders(table_recorder_configs) if self.logging_enabled else []
        )
        if self.summary_logging_enabled:
            summary_recorder_configs = self._summary_recorder_configs(
                summary_recorder_configs,
                include_basic=bool(summary_cfg.get("include_basic", True)),
            )
            self.summary_recorders = build_summary_recorders(summary_recorder_configs)

    def update(self, sim_time_ns: int, runtime_frame: Any, control: Any) -> None:
        sample = MonitorSample(
            step_index=self.step_index,
            sim_time_ns=sim_time_ns,
            runtime_frame=runtime_frame,
            control=control,
        )
        if self.root:
            self.root.put(sample)

        self.final_sim_time_ns = sim_time_ns
        if self.log_manager:
            frame_row = self._frame_row(sample)
            if frame_row is not None:
                self.log_manager.write(FRAME_STREAM, frame_row)

            for recorder in self.table_recorders:
                for row in recorder.update(sample):
                    self.log_manager.write(row.stream, row.row)
            for recorder in self.summary_recorders:
                recorder.update(sample)

        self.step_index += 1

    def should_stop(self) -> bool:
        if self.root:
            result = self.root.evaluate()
            if result.code == ConditionCode.TRIGGERED:
                self.stop_reason = (
                    f"Stop condition '{result.condition_name}' triggered: {result.detail}"
                )
                logger.info(
                    self.stop_reason,
                )
                return True
        av_should_quit = self.av.should_quit()
        if av_should_quit:
            self.stop_reason = self._should_quit_reason(
                "AV",
                getattr(av_should_quit, "message", ""),
            )
            return True
        sim_should_quit = self.sim.should_quit()
        if sim_should_quit:
            self.stop_reason = self._should_quit_reason(
                "Simulator",
                getattr(sim_should_quit, "message", ""),
            )
            return True
        return False

    def reset(
        self,
        output_related: str,
        params: dict[str, Any] | None = None,
        overwrite_summary: bool = False,
    ):
        self._close_log_manager()
        self.step_index = 0
        self.final_sim_time_ns = 0
        self.stop_reason = ""
        self.params = dict(params or {})
        self.wall_start_time_s = monotonic()
        self.overwrite_summary = overwrite_summary

        if self.root:
            self.root.reset()
        for recorder in self.frame_recorders:
            recorder.reset()
        for recorder in self.table_recorders:
            recorder.reset()
        for recorder in self.summary_recorders:
            recorder.reset()

        if self.logging_enabled:
            output_dir = Path(self.log_file).parent / output_related / self.logging_output_dir
            streams = self._log_streams()
            self.log_manager = LogManager(
                output_dir=output_dir,
                streams=streams,
                flush_every_n_rows=self.flush_every_n_rows,
                float_precision=self.float_precision,
            )

    def finalize(
        self,
        status: str,
        reason: str = "",
    ) -> None:
        wall_time_ms = self._wall_time_ms()
        if status in self.current_summary_counts:
            self.current_summary_counts[status] += 1
        self.current_sim_time_ms += self.final_sim_time_ns / 1e6
        self.current_wall_time_ms += wall_time_ms
        if not self.log_manager:
            return

        try:
            for recorder in self.table_recorders:
                for row in recorder.finalize():
                    self.log_manager.write(row.stream, row.row)

            summary_row = self._summary_row(
                status=status,
                reason=reason,
                wall_time_ms=wall_time_ms,
            )
            if summary_row is not None:
                self.log_manager.write(SUMMARY_STREAM, summary_row)
        finally:
            self._close_log_manager()

    def close(self, result: ExecResult | None = None) -> None:
        self._close_log_manager()
        if result is not None:
            self._write_exec_summary(result)

    def has_finished_summary(self, output_related: str) -> bool:
        rows = self.summary_rows(output_related)
        if not rows:
            return False

        return rows[-1].get("run.status") == "finished"

    def has_terminal_summary(self, output_related: str) -> bool:
        rows = self.summary_rows(output_related)
        if not rows:
            return False

        return rows[-1].get("run.status") in {"finished", "skipped"}

    def count_retryable_failures(self, output_related: str) -> int:
        return sum(
            1
            for row in self.summary_rows(output_related)
            if row.get("run.status") == "fail"
            and row.get("run.stop_reason", "").startswith("retry:")
        )

    def summary_rows(self, output_related: str) -> list[dict[str, str]]:
        summary_path = self.summary_path(output_related)
        if summary_path is None or not summary_path.exists():
            return []

        with summary_path.open(newline="") as file:
            return list(csv.DictReader(file))

    def summary_path(self, output_related: str) -> Path | None:
        if not self.summary_logging_enabled:
            return None
        return (
            Path(self.log_file).parent
            / output_related
            / self.logging_output_dir
            / self.summary_output
        )

    def _log_streams(self) -> list[LogStream]:
        streams = []
        if self.summary_logging_enabled:
            streams.append(
                LogStream(
                    name=SUMMARY_STREAM,
                    filename=self.summary_output,
                    fields=self._summary_fields(),
                    append=not self.overwrite_summary,
                )
            )
        if self.frame_logging_enabled:
            streams.append(
                LogStream(
                    name=FRAME_STREAM,
                    filename=self.frame_output,
                    fields=self._frame_fields(),
                )
            )
        for recorder in self.table_recorders:
            streams.extend(recorder.streams())
        return streams

    def _summary_fields(self) -> tuple[str, ...]:
        fields = []
        for recorder in self.summary_recorders:
            fields.extend(f"{recorder.name}.{field}" for field in recorder.fields())
        return tuple(fields)

    def _summary_row(
        self,
        status: str,
        reason: str,
        wall_time_ms: float | None = None,
    ) -> dict[str, Any] | None:
        if not self.summary_logging_enabled:
            return None
        if wall_time_ms is None:
            wall_time_ms = self._wall_time_ms()

        context = SummaryContext(
            status=status,
            stop_reason=reason or self.stop_reason,
            total_steps=self.step_index,
            final_sim_time_ms=self.final_sim_time_ns / 1e6,
            wall_time_ms=wall_time_ms,
            speedup=self._speedup(wall_time_ms),
            params=self.params,
            job_id=self.job_id,
        )
        row = {field: None for field in self._summary_fields()}
        for recorder in self.summary_recorders:
            values = recorder.record(context)
            unexpected_fields = sorted(set(values) - set(recorder.fields()))
            if unexpected_fields:
                raise ValueError(
                    f"Summary recorder {recorder.name!r} returned unexpected field(s): "
                    f"{', '.join(unexpected_fields)}"
                )
            for field in recorder.fields():
                row[f"{recorder.name}.{field}"] = values.get(field)
        return row

    def _frame_fields(self) -> tuple[str, ...]:
        fields = ["step_index", "sim_time_ms"]
        for recorder in self.frame_recorders:
            fields.extend(f"{recorder.name}.{field}" for field in recorder.fields())
        return tuple(fields)

    def _frame_row(self, sample: MonitorSample) -> dict[str, Any] | None:
        if not self.frame_logging_enabled:
            return None
        if sample.step_index % self.frame_every_n_steps != 0:
            return None

        row = {field: None for field in self._frame_fields()}
        row["step_index"] = sample.step_index
        row["sim_time_ms"] = sample.sim_time_ms

        for recorder in self.frame_recorders:
            values = recorder.record(sample)
            unexpected_fields = sorted(set(values) - set(recorder.fields()))
            if unexpected_fields:
                raise ValueError(
                    f"Frame recorder {recorder.name!r} returned unexpected field(s): "
                    f"{', '.join(unexpected_fields)}"
                )
            for field in recorder.fields():
                row[f"{recorder.name}.{field}"] = values.get(field)

        return row

    def _close_log_manager(self) -> None:
        if self.log_manager:
            self.log_manager.close()
            self.log_manager = None

    def _write_exec_summary(self, result: ExecResult) -> None:
        fields = (
            "job_id",
            "hint",
            "speedup",
            "current_finished",
            "current_failed",
            "current_skipped",
            "cumulative_finished",
            "cumulative_failed",
            "cumulative_skipped",
            "reason",
        )
        try:
            cumulative = self._cumulative_concrete_summary_counts()
            row = {
                "job_id": self.job_id,
                "hint": result.hint.value,
                "speedup": self._current_speedup(),
                "current_finished": self.current_summary_counts["finished"],
                "current_failed": self.current_summary_counts["fail"],
                "current_skipped": self.current_summary_counts["skipped"],
                "cumulative_finished": cumulative["finished"],
                "cumulative_failed": cumulative["fail"],
                "cumulative_skipped": cumulative["skipped"],
                "reason": result.reason,
            }
            path = Path(self.log_file).parent / "summary.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            should_write_header = not path.exists() or path.stat().st_size == 0
            with path.open("a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                if should_write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            logger.exception("Failed to write execution summary")

    def _cumulative_concrete_summary_counts(self) -> dict[str, int]:
        counts = {"finished": 0, "fail": 0, "skipped": 0}
        output_base = Path(self.log_file).parent

        for summary_path in output_base.glob(f"*/{self.logging_output_dir}/*.csv"):
            if summary_path.name != self.summary_output:
                continue
            try:
                with summary_path.open(newline="") as file:
                    rows = list(csv.DictReader(file))
            except Exception:
                logger.exception("Failed to read concrete summary: %s", summary_path)
                continue
            if not rows:
                continue
            status = rows[-1].get("run.status")
            if status in counts:
                counts[status] += 1
        return counts

    @staticmethod
    def _should_quit_reason(component: str, message: str) -> str:
        reason = f"{component} requested to stop"
        if message:
            return f"{reason}: {message}"
        return reason

    def _wall_time_ms(self) -> float:
        if self.wall_start_time_s is None:
            return 0.0
        return (monotonic() - self.wall_start_time_s) * 1000.0

    def _speedup(self, wall_time_ms: float | None = None) -> float:
        if wall_time_ms is None:
            wall_time_ms = self._wall_time_ms()
        if wall_time_ms <= 0:
            return 0.0
        return (self.final_sim_time_ns / 1e6) / wall_time_ms

    def _current_speedup(self) -> float:
        if self.current_wall_time_ms <= 0:
            return 0.0
        return self.current_sim_time_ms / self.current_wall_time_ms

    @staticmethod
    def _summary_recorder_configs(
        configs: list[dict],
        include_basic: bool,
    ) -> list[dict]:
        if not include_basic:
            return configs
        if any(config.get("type") == "basic_summary" for config in configs):
            return configs
        return [{"type": "basic_summary", "name": "run"}, *configs]
