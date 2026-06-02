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
EXECUTION_STATUSES = ("finished", "error", "skipped", "abort")
TEST_OUTCOMES = ("success", "fail", "invalid", "unknown")


class Monitor:
    def __init__(
        self,
        log_file: str,
        av: AVWrapper,
        sim: SimWrapper,
        logging_config_path: str | None = None,
        stop_condition_config_path: str | None = None,
        sps=None,
        position_parser=None,
        job_id: str = "unknown_job",
    ):
        self.log_file = log_file
        self.av = av
        self.sim = sim
        self.job_id = job_id

        self.logging_cfg: dict | None = None
        self.stop_condition_cfg: dict | list | None = None
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
        self.stop_condition_name = ""
        self.test_outcome = "unknown"
        self.params: dict[str, Any] = {}
        self.wall_start_time_s: float | None = None
        self.overwrite_summary = False
        self.current_summary_counts = {"finished": 0, "error": 0, "skipped": 0, "abort": 0}
        self.current_test_outcome_counts = {
            "success": 0,
            "fail": 0,
            "invalid": 0,
            "unknown": 0,
        }
        self.current_sim_time_ms = 0.0
        self.current_wall_time_ms = 0.0
        self.condition_context = {
            "sps": sps,
            "position_parser": position_parser,
            "params": self.params,
        }

        if logging_config_path:
            self.logging_cfg = self._load_mapping_config(logging_config_path, "monitor logging")
            if "logging" not in self.logging_cfg:
                raise ValueError("Monitor logging config must contain 'logging'")
            if any(
                key in self.logging_cfg
                for key in ("condition", "stop_condition", "stop_conditions")
            ):
                raise ValueError(
                    "Monitor logging config must not contain stop condition fields; "
                    "use monitor.stop_condition_config_path"
                )
            self._configure_logging()

        if stop_condition_config_path:
            self.stop_condition_cfg = self._load_stop_condition_config(stop_condition_config_path)
            if isinstance(self.stop_condition_cfg, dict) and "logging" in self.stop_condition_cfg:
                raise ValueError(
                    "Monitor stop condition config must not contain logging; "
                    "use monitor.logging_config_path"
                )

        condition_cfg = self._stop_condition_config()
        if condition_cfg is not None:
            if not isinstance(condition_cfg, dict):
                raise ValueError(
                    "Monitor config 'condition' must be a mapping describing a condition tree"
                )

            self.root = build_condition_tree(
                condition_cfg,
                context=self.condition_context,
            )
            logger.debug("Built condition tree: %s", self.root)
        elif not self.logging_enabled:
            logger.warning(
                "No monitor logging_config_path or stop_condition_config_path provided; "
                "monitoring is disabled."
            )

    @staticmethod
    def _load_mapping_config(path: str, config_name: str) -> dict:
        cfg = yaml.safe_load(Path(path).read_text())
        if cfg is None:
            return {}
        if not isinstance(cfg, dict):
            raise ValueError(
                f"{config_name} config at {path!r} must deserialize to a mapping, "
                f"got {type(cfg).__name__}"
            )
        return cfg

    @staticmethod
    def _load_stop_condition_config(path: str) -> dict | list | None:
        cfg = yaml.safe_load(Path(path).read_text())
        if cfg is None:
            return None
        if not isinstance(cfg, (dict, list)):
            raise ValueError(
                "Monitor stop condition config at "
                f"{path!r} must deserialize to a mapping or list, got {type(cfg).__name__}"
            )
        return cfg

    def _configure_logging(self) -> None:
        logging_cfg = self.logging_cfg.get("logging", {}) if self.logging_cfg else {}
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

    def should_stop(self, check_external_quit: bool = True) -> bool:
        if self.root:
            result = self.root.evaluate()
            if result.code == ConditionCode.TRIGGERED:
                self.stop_condition_name = result.trigger_name or result.condition_name
                self.test_outcome = result.test_outcome or "unknown"
                self.stop_reason = (
                    f"Stop condition '{self.stop_condition_name}' triggered: {result.detail}"
                )
                logger.info(
                    self.stop_reason,
                )
                return True
        if not check_external_quit:
            return False

        av_should_quit = self.av.should_quit()
        if av_should_quit:
            self.stop_condition_name = "av_should_quit"
            self.test_outcome = "unknown"
            self.stop_reason = self._should_quit_reason(
                "AV",
                getattr(av_should_quit, "message", ""),
            )
            return True
        sim_should_quit = self.sim.should_quit()
        if sim_should_quit:
            self.stop_condition_name = "sim_should_quit"
            self.test_outcome = "unknown"
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
        self.stop_condition_name = ""
        self.test_outcome = "unknown"
        self.params = dict(params or {})
        self.condition_context["params"] = self.params
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
        test_outcome: str | None = None,
        stop_condition: str | None = None,
    ) -> None:
        wall_time_ms = self._wall_time_ms()
        effective_status = self._normalize_execution_status(status)
        effective_test_outcome = self._normalize_test_outcome(
            test_outcome if test_outcome is not None else self.test_outcome
        )
        effective_stop_condition = (
            stop_condition if stop_condition is not None else self.stop_condition_name
        )
        self.current_summary_counts[effective_status] += 1
        self.current_test_outcome_counts[effective_test_outcome] += 1
        self.current_sim_time_ms += self.final_sim_time_ns / 1e6
        self.current_wall_time_ms += wall_time_ms
        if not self.log_manager:
            return

        try:
            for recorder in self.table_recorders:
                for row in recorder.finalize():
                    self.log_manager.write(row.stream, row.row)

            summary_row = self._summary_row(
                status=effective_status,
                reason=reason,
                test_outcome=effective_test_outcome,
                stop_condition=effective_stop_condition,
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

    def logical_terminal_counts(self) -> dict[str, int]:
        counts = self._cumulative_concrete_status_counts()
        return {
            "finished": counts["finished"],
            "abort": counts["abort"],
            "skipped": counts["skipped"],
        }

    def has_finished_summary(self, output_related: str) -> bool:
        rows = self.summary_rows(output_related)
        if not rows:
            return False

        return rows[-1].get("run.status") == "finished"

    def last_summary_status(self, output_related: str) -> str | None:
        rows = self.summary_rows(output_related)
        if not rows:
            return None

        return self._normalize_execution_status(rows[-1].get("run.status"))

    def has_terminal_summary(self, output_related: str) -> bool:
        return self.last_summary_status(output_related) in {"finished", "skipped", "abort"}

    def count_retryable_failures(self, output_related: str) -> int:
        return sum(
            1
            for row in self.summary_rows(output_related)
            if self._normalize_execution_status(row.get("run.status")) == "error"
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
        test_outcome: str = "unknown",
        stop_condition: str = "",
        wall_time_ms: float | None = None,
    ) -> dict[str, Any] | None:
        if not self.summary_logging_enabled:
            return None
        if wall_time_ms is None:
            wall_time_ms = self._wall_time_ms()

        context = SummaryContext(
            status=status,
            test_outcome=test_outcome,
            stop_condition=stop_condition,
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
            "current_error",
            "current_abort",
            "current_skipped",
            "current_success",
            "current_test_fail",
            "current_invalid",
            "current_unknown",
            "cumulative_finished",
            "cumulative_error",
            "cumulative_abort",
            "cumulative_skipped",
            "cumulative_success",
            "cumulative_test_fail",
            "cumulative_invalid",
            "cumulative_unknown",
            "reason",
        )
        try:
            cumulative = self._cumulative_concrete_status_counts()
            cumulative_outcomes = self._cumulative_concrete_test_outcome_counts()
            row = {
                "job_id": self.job_id,
                "hint": result.hint.value,
                "speedup": self._current_speedup(),
                "current_finished": self.current_summary_counts["finished"],
                "current_error": self.current_summary_counts["error"],
                "current_abort": self.current_summary_counts["abort"],
                "current_skipped": self.current_summary_counts["skipped"],
                "current_success": self.current_test_outcome_counts["success"],
                "current_test_fail": self.current_test_outcome_counts["fail"],
                "current_invalid": self.current_test_outcome_counts["invalid"],
                "current_unknown": self.current_test_outcome_counts["unknown"],
                "cumulative_finished": cumulative["finished"],
                "cumulative_error": cumulative["error"],
                "cumulative_abort": cumulative["abort"],
                "cumulative_skipped": cumulative["skipped"],
                "cumulative_success": cumulative_outcomes["success"],
                "cumulative_test_fail": cumulative_outcomes["fail"],
                "cumulative_invalid": cumulative_outcomes["invalid"],
                "cumulative_unknown": cumulative_outcomes["unknown"],
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

    def _cumulative_concrete_status_counts(self) -> dict[str, int]:
        counts = {"finished": 0, "error": 0, "skipped": 0, "abort": 0}
        for row in self._latest_concrete_summary_rows():
            status = self._normalize_execution_status(row.get("run.status"))
            counts[status] += 1
        return counts

    def _cumulative_concrete_test_outcome_counts(self) -> dict[str, int]:
        counts = {outcome: 0 for outcome in TEST_OUTCOMES}
        for row in self._latest_concrete_summary_rows():
            outcome = self._normalize_test_outcome(row.get("run.test_outcome", "unknown"))
            counts[outcome] += 1
        return counts

    def _latest_concrete_summary_rows(self) -> list[dict[str, str]]:
        rows_by_path = []
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
            rows_by_path.append(rows[-1])
        return rows_by_path

    def _stop_condition_config(self) -> dict | None:
        if self.stop_condition_cfg is None:
            return None

        condition_cfg = self.stop_condition_cfg
        if isinstance(condition_cfg, dict):
            wrapped_cfg = condition_cfg.get("stop_condition", condition_cfg.get("condition"))
            if wrapped_cfg is None:
                wrapped_cfg = condition_cfg.get("stop_conditions")
            if wrapped_cfg is not None:
                condition_cfg = wrapped_cfg

        if condition_cfg is None:
            return None
        if isinstance(condition_cfg, list):
            return {
                "type": "or",
                "name": "stop_conditions",
                "children": condition_cfg,
            }
        return condition_cfg

    @staticmethod
    def _normalize_test_outcome(raw_outcome: Any) -> str:
        normalized = str(raw_outcome or "unknown").strip().lower()
        return normalized if normalized in TEST_OUTCOMES else "unknown"

    @staticmethod
    def _normalize_execution_status(raw_status: Any) -> str:
        normalized = str(raw_status or "error").strip().lower()
        if normalized == "fail":
            return "error"
        if normalized in EXECUTION_STATUSES:
            return normalized
        return "error"

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
