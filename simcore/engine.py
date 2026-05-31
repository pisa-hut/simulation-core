import csv
import logging
from pathlib import Path
import time
from typing import Any

from rich.logging import RichHandler

from simcore.av_wrapper import AVWrapper
from simcore.execution import ExecResult, RetryHint, ScenarioExecutionError
from simcore.monitor import Monitor
from simcore.sampler import create_sampler, load_parameter_space
from simcore.sampler.loader import resolve_sampler_source
from simcore.sim_wrapper import SimWrapper
from simcore.utils.position_parser import PositionParser
from simcore.utils.sps import ScenarioPack

logging.basicConfig(
    level=logging.INFO,
    datefmt="%H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True)],
)

logger = logging.getLogger(__name__)


class SimulationEngine:
    def __init__(self, spec: dict[str, Any]):
        runtime_spec = spec.get("runtime", {})
        task_spec = spec.get("task", {})
        sim_spec = spec.get("simulator", {})
        av_spec = spec.get("av", {})
        sampler_spec = spec.get("sampler", {})
        scenario_spec = spec.get("scenario", {})
        monitor_spec = spec.get("monitor", {})
        map_spec = spec.get("map", {})

        self.log_level = runtime_spec.get("log_level", "info").upper()
        logger.setLevel(getattr(logging, self.log_level, logging.INFO))
        self.overwrite = bool(runtime_spec.get("overwrite", False))
        self.max_concrete_retries = int(runtime_spec.get("max_concrete_retries", 1))
        self._speedup_ratio = runtime_spec.get("speedup_ratio", 0)
        self._dt_s = runtime_spec.get("dt", None)
        if self._dt_s is None or self._dt_s <= 0:
            raise ValueError(f"Invalid dt value: {self._dt_s}. dt must be a positive number.")

        self.job_id = task_spec.get("job_id", "unknown_job")
        self.output_base = Path(task_spec.get("output_dir", "./outputs")).expanduser().resolve()
        self.output_base.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output base directory set to: {self.output_base}")
        self._startup_error: ScenarioExecutionError | None = None
        self.av: AVWrapper
        self.sim: SimWrapper
        self.monitor: Monitor
        self.param_sampler = None
        self.max_sampler_iterations = None
        self.completed_concrete_runs = 0
        self.failed_concrete_runs = 0
        self.skipped_concrete_runs = 0
        self._last_skip_reason = ""

        self.position_parser = PositionParser.from_specs(scenario_spec, map_spec)
        try:
            self.sps = ScenarioPack.from_dict(
                scenario_spec,
                map_spec,
                position_parser=self.position_parser,
            )
        except Exception as exc:
            logger.exception("Failed to create ScenarioPack from scenario and map specifications.")
            self.position_parser.close()
            raise exc

        try:
            self.sim = SimWrapper(
                sim_spec=sim_spec,
                dt_ns=int(self._dt_s * 1e9),
            )
        except ScenarioExecutionError as exc:
            logger.error("Simulator initialization failed: %s", exc)
            self._startup_error = exc
            return
        except Exception as exc:
            logger.error("Simulator initialization failed")
            self.position_parser.close()
            raise exc

        try:
            self.av = AVWrapper(
                av_spec=av_spec,
                dt_ns=int(self._dt_s * 1e9),
                map_name=map_spec.get("name", "unknown_map"),
            )
        except ScenarioExecutionError as exc:
            logger.error("AV initialization failed: %s", exc)
            self._startup_error = exc
            return
        except Exception as exc:
            logger.error("AV initialization failed")
            self.position_parser.close()
            raise exc

        self.monitor = Monitor(
            config_path=monitor_spec.get("config_path", None),
            log_file=str(self.output_base / "monitor_log.csv"),
            av=self.av,
            sim=self.sim,
            sps=self.sps,
            position_parser=self.position_parser,
            job_id=self.job_id,
        )

        sampler_source_path, sampler_source_type = resolve_sampler_source(
            sampler_spec,
            fallback_param_range_file=self.sps.param_range_file,
        )
        if sampler_source_path is not None:
            logger.debug(
                "Sampler source provided: %s (%s)", sampler_source_path, sampler_source_type
            )
            parameter_space = load_parameter_space(sampler_source_path, sampler_source_type)
            self.param_sampler = create_sampler(
                sampler_spec=sampler_spec,
                parameter_space=parameter_space,
            )
            self.max_sampler_iterations = sampler_spec.get("max_samples")
        else:
            logger.debug(
                "No parameter range file provided; seem as testing a concrete scenario; skipping parameter sampler."
            )
            self.param_sampler = None
            self.max_sampler_iterations = None

    def exec(self) -> ExecResult:
        """
        Run the scenario(s) according to the provided specifications.
        If a parameter sampler is provided, it will iterate through all parameter combinations;
        otherwise, it will run a single concrete scenario.
        """
        if self._startup_error is not None:
            try:
                result = ExecResult(
                    completed_concrete_runs=self.completed_concrete_runs,
                    hint=self._startup_error.hint,
                    reason=str(self._startup_error),
                )
                self._write_exec_summary(result)
                return result
            finally:
                self.close()

        try:
            if self.param_sampler is not None:
                logger.info("Running logical scenario with parameter sampling.")
                self.run_logical()
            else:
                logger.info("Running single concrete scenario without parameter sampling.")
                self.concrete_wrapper("concrete", self.sps)
        except ScenarioExecutionError as e:
            logger.error(f"Error during scenario execution: {e}")
            result = ExecResult(
                completed_concrete_runs=self.completed_concrete_runs,
                hint=e.hint,
                reason=str(e),
            )
            self._write_exec_summary(result)
            return result
        except Exception as e:
            logger.error(f"Error during scenario execution: {e}")
            result = ExecResult(
                completed_concrete_runs=self.completed_concrete_runs,
                hint=RetryHint.RETRY,
                reason=f"{type(e).__name__}: {e}",
            )
            self._write_exec_summary(result)
            return result
        else:
            logger.info("Scenario execution completed successfully.")
            result = ExecResult(
                completed_concrete_runs=self.completed_concrete_runs,
                hint=RetryHint.OK,
                reason="completed",
            )
            self._write_exec_summary(result)
            return result
        finally:
            self.close()

    def run_logical(self):
        logger.debug("Starting parameter sampling execution.")
        total = self.param_sampler.total_samples()

        logger.debug(f"Total parameter combinations: {total}")

        i = 0
        while self.max_sampler_iterations is None or i < self.max_sampler_iterations:
            progress_total = total if total is not None else "unknown"
            params = self.param_sampler.next()

            if params is None:
                logger.debug("Parameter sampling completed.")
                break

            logger.info(
                f"====================== Sampling iteration {i + 1}/{progress_total} ======================"
            )
            logger.info(f"Sampled parameters: {params}")

            try:
                self.concrete_wrapper(f"iteration_{i + 1}", self.sps, params)
            except ScenarioExecutionError as e:
                if e.skip_concrete:
                    logger.warning(
                        "Skipping concrete scenario at iteration %s because it is not runnable: %s",
                        i + 1,
                        e,
                    )
                    i += 1
                    continue
                logger.error(
                    f"Scenario execution failed at iteration {i + 1} with parameters: {params}"
                )
                raise
            i += 1

        logger.info("Completed all parameter combinations.")

    def concrete_wrapper(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: dict[str, Any] | None = None,
    ) -> None:
        if self.monitor.has_terminal_summary(output_related) and not self.overwrite:
            logger.info(
                f"Terminal summary already exists for {output_related}. Skipping execution."
            )
            return
        if (
            not self.overwrite
            and self.max_concrete_retries > 0
            and self.monitor.count_retryable_failures(output_related) >= self.max_concrete_retries
        ):
            reason = (
                f"retry: exceeded max_concrete_retries={self.max_concrete_retries}; "
                "skipping concrete"
            )
            logger.warning("%s for %s", reason, output_related)
            self._finalize_skipped_concrete(output_related, params, reason)
            self._record_skipped_concrete(reason)
            return

        try:
            self.run_concrete(output_related, sps, params)
        except ScenarioExecutionError as e:
            if e.skip_concrete:
                logger.warning(
                    "Skipping concrete scenario %s because it is not runnable: %s",
                    output_related,
                    e,
                )
                if not e.summary_recorded:
                    self._finalize_skipped_concrete(
                        output_related,
                        params,
                        f"dont_retry: {e}",
                    )
                self._record_skipped_concrete(f"dont_retry: {e}")
                return
            logger.error(f"Error in concrete scenario execution for {output_related}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in concrete scenario execution for {output_related}: {e}")
            raise
        else:
            # Count the execution as soon as run_concrete returned cleanly.
            # Dry runs still count because the scenario did run.
            self.completed_concrete_runs += 1
            logger.info(f"Scenario {output_related} completed successfully.")

    def run_concrete(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: dict[str, Any] | None = None,
    ) -> None:
        """
        Run a single concrete scenario with the given parameters.
        """

        stop_reason = ""
        try:
            logger.debug("Resetting monitor...")
            self.monitor.reset(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
            )

            logger.debug("Resetting simulator...")
            runtime_frame = self.sim.reset(output_related, sps, params)
            raw_obs = runtime_frame.objects if runtime_frame.objects else []

            logger.debug("Resetting AV...")
            ctrl_for_sim = self.av.reset(output_related, sps, raw_obs)

            dt_s = self._dt_s
            dt_ns = int(dt_s * 1e9)

            sim_time_ns = 0  # Simulation time in nanoseconds

            wall_start = time.monotonic()
            sim_time_need = 0
            while True:
                if self.monitor.should_stop():
                    stop_reason = self.monitor.stop_reason or "monitor_stop"
                    logger.info(f"Monitor requested to stop ({stop_reason})")
                    break

                runtime_frame = self.sim.step(ctrl_for_sim, sim_time_ns)
                raw_obs = runtime_frame.objects if runtime_frame.objects else []
                ctrl_for_sim = self.av.step(raw_obs, sim_time_ns)
                self.monitor.update(sim_time_ns, runtime_frame, ctrl_for_sim)

                sim_time_ns += dt_ns

                cur_time_s = time.monotonic()
                time_use_s = cur_time_s - wall_start

                if self._speedup_ratio > 0:
                    print(
                        f"time use = {time_use_s:.2f} s, sim_time = {sim_time_ns / 1e9:.2f} s",
                        end="\r",
                    )

                ### sleep to sync with real time if we're running faster than real time
                if self._speedup_ratio > 0:
                    time.sleep(
                        max(
                            0,
                            wall_start + sim_time_ns / self._speedup_ratio / 1e9 - time.monotonic(),
                        )
                    )

            self.monitor.finalize(
                status="finished",
                reason=stop_reason or "completed",
            )
        except KeyboardInterrupt:
            try:
                self.monitor.finalize(
                    status="fail",
                    reason="KeyboardInterrupt: interrupted by user",
                )
                self._record_failed_concrete()
            except Exception:
                logger.exception("monitor.finalize() failed after keyboard interrupt")
            raise
        except ScenarioExecutionError as exc:
            reason = str(exc)
            status = "fail"
            if exc.skip_concrete:
                status = "skipped"
                reason = f"dont_retry: {reason}"
            if exc.hint == RetryHint.RETRY:
                reason = f"retry: {reason}"
            try:
                self.monitor.finalize(
                    status=status,
                    reason=reason,
                )
                exc.summary_recorded = True
                if status == "fail":
                    self._record_failed_concrete()
            except Exception:
                logger.exception("monitor.finalize() failed after scenario error")
            raise
        except Exception as exc:
            try:
                self.monitor.finalize(
                    status="fail",
                    reason=f"{type(exc).__name__}: {exc}",
                )
                self._record_failed_concrete()
            except Exception:
                logger.exception("monitor.finalize() failed after scenario error")
            raise

        logger.info(
            f"Completed {sim_time_ns / 1e9:.2f} seconds scenario, using {sim_time_need:.2f} sec."
        )

    def close(self):
        if self.av is not None:
            try:
                self.av.stop()
            except Exception:
                logger.exception("av.stop() failed")
        if self.sim is not None:
            try:
                self.sim.stop()
            except Exception:
                logger.exception("sim.stop() failed")
        try:
            self.position_parser.close()
        except Exception:
            logger.exception("position_parser.close() failed")

    def _record_skipped_concrete(self, reason: str) -> None:
        self.skipped_concrete_runs += 1
        self._last_skip_reason = reason

    def _record_failed_concrete(self) -> None:
        self.failed_concrete_runs += 1

    def _finalize_skipped_concrete(
        self,
        output_related: str,
        params: dict[str, Any] | None,
        reason: str,
    ) -> None:
        try:
            self.monitor.reset(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
            )
            self.monitor.finalize(status="skipped", reason=reason)
        except Exception:
            logger.exception("monitor.finalize() failed while recording skipped concrete")

    def _write_exec_summary(self, result: ExecResult) -> None:
        fields = (
            "job_id",
            "hint",
            "reason",
            "current_finished",
            "current_failed",
            "current_skipped",
            "cumulative_finished",
            "cumulative_failed",
            "cumulative_skipped",
        )
        try:
            cumulative = self._cumulative_concrete_summary_counts()
            row = {
                "job_id": self.job_id,
                "hint": result.hint.value,
                "reason": result.reason,
                "current_finished": self.completed_concrete_runs,
                "current_failed": self.failed_concrete_runs,
                "current_skipped": self.skipped_concrete_runs,
                "cumulative_finished": cumulative["finished"],
                "cumulative_failed": cumulative["fail"],
                "cumulative_skipped": cumulative["skipped"],
            }
            path = self.output_base / "summary.csv"
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
        logging_output_dir = getattr(self.monitor, "logging_output_dir", "monitor")
        summary_output = getattr(self.monitor, "summary_output", "summary.csv")

        for summary_path in self.output_base.glob(f"*/{logging_output_dir}/*.csv"):
            if summary_path.name != summary_output:
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
