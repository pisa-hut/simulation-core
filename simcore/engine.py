import json
import logging
import time
from pathlib import Path
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
        self.max_concrete_retries = int(runtime_spec.get("max_concrete_retries", 3))
        self._speedup_ratio = runtime_spec.get("speedup_ratio", 0)
        value = runtime_spec.get("permutation")
        self._permutation = int(value) if value is not None else None
        if self._permutation is not None and self._permutation < 1:
            raise ValueError("runtime.permutation must be a positive 1-based index")
        self._dt_s = runtime_spec.get("dt", None)
        if self._dt_s is None or self._dt_s <= 0:
            raise ValueError(f"Invalid dt value: {self._dt_s}. dt must be a positive number.")

        self.job_id = task_spec.get("job_id", "unknown_job")
        self.output_base = Path(task_spec.get("output_dir", "./outputs")).expanduser().resolve()
        self.output_base.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output base directory set to: {self.output_base}")
        self._startup_error: ScenarioExecutionError | None = None
        self.av: AVWrapper | None = None
        self.sim: SimWrapper | None = None
        self.monitor: Monitor | None = None
        self.param_sampler = None
        self.max_sampler_iterations = None
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
            if self._permutation not in (None, 1):
                raise ValueError("runtime.permutation can only be 1 for a concrete scenario")

    def exec(self) -> ExecResult:
        """
        Run the scenario(s) according to the provided specifications.
        If a parameter sampler is provided, it will iterate through all parameter combinations;
        otherwise, it will run a single concrete scenario.
        """
        result: ExecResult
        if self._startup_error is not None:
            logical_counts = self._logical_terminal_counts()
            result = ExecResult(
                hint=self._startup_error.hint,
                reason=str(self._startup_error),
                finished_concrete_runs=logical_counts["finished"],
                aborted_concrete_runs=logical_counts["abort"],
                skipped_concrete_runs=logical_counts["skipped"],
            )
            self.close(result)
            return result

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
                hint=e.hint,
                reason=str(e),
                **self._exec_result_terminal_counts(),
            )
        except Exception as e:
            logger.error(f"Error during scenario execution: {e}")
            result = ExecResult(
                hint=RetryHint.RETRY,
                reason=f"{type(e).__name__}: {e}",
                **self._exec_result_terminal_counts(),
            )
        else:
            logger.info("Scenario execution completed successfully.")
            result = ExecResult(
                hint=RetryHint.OK,
                reason="completed",
                **self._exec_result_terminal_counts(),
            )
        finally:
            self.close(result if "result" in locals() else None)
        return result

    def run_logical(self):
        logger.debug("Starting parameter sampling execution.")
        total = self.param_sampler.total_samples()

        logger.debug(f"Total parameter combinations: {total}")

        if self._permutation is not None:
            self._run_logical_permutation(total)
            return

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

            logger.info(f"Sampled parameters: {json.dumps(params)}")

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

    def _run_logical_permutation(self, total: int | None) -> None:
        permutation = self._permutation
        if total is not None and permutation > total:
            raise ValueError(
                f"runtime.permutation={permutation} is out of range; sampler has {total} sample(s)"
            )

        logger.info("Running only permutation %s/%s", permutation, total or "unknown")
        params = None
        for index in range(1, permutation + 1):
            params = self.param_sampler.next()
            if params is None:
                raise ValueError(
                    f"runtime.permutation={permutation} is out of range; sampler ended at {index - 1}"
                )

        logger.info(
            "====================== Sampling iteration %s/%s ======================",
            permutation,
            total or "unknown",
        )
        logger.info(f"Sampled parameters: {json.dumps(params)}")
        self.concrete_wrapper(f"iteration_{permutation}", self.sps, params)

    def concrete_wrapper(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: dict[str, Any] | None = None,
    ) -> None:
        last_status = self.monitor.last_summary_status(output_related)
        if last_status in {"skipped", "abort"}:
            logger.info(
                f"Concrete {output_related} already has terminal status '{last_status}'. Skipping execution."
            )
            return
        if last_status == "finished" and not self.overwrite:
            logger.info(
                f"Finished summary already exists for {output_related}. Skipping execution."
            )
            return
        if (
            not self.overwrite
            and self.max_concrete_retries > 0
            and self.monitor.count_retryable_failures(output_related) >= self.max_concrete_retries
        ):
            reason = (
                f"retry: exceeded max_concrete_retries={self.max_concrete_retries}; "
                "aborting concrete"
            )
            logger.warning("%s for %s", reason, output_related)
            self._finalize_aborted_concrete(output_related, params, reason)
            return

        try:
            self.run_concrete(output_related, sps, params)
        except ScenarioExecutionError as e:
            if e.skip_concrete:
                logger.warning(
                    "Skipping concrete scenario %s because it is not runnable",
                    output_related,
                )
                logger.warning(f"reason: {e}")
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
                        f"sim_time = {sim_time_ns / 1e9:.2f} s, time use = {time_use_s:.2f} s",
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
            wall_elapsed_s = time.monotonic() - wall_start
        except KeyboardInterrupt:
            try:
                self.monitor.finalize(
                    status="fail",
                    reason="KeyboardInterrupt: interrupted by user",
                )
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
            except Exception:
                logger.exception("monitor.finalize() failed after scenario error")
            raise
        except Exception as exc:
            try:
                self.monitor.finalize(
                    status="fail",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                logger.exception("monitor.finalize() failed after scenario error")
            raise

        completed_sim_time_s = self.monitor.final_sim_time_ns / 1e9
        achieved_speedup = completed_sim_time_s / wall_elapsed_s if wall_elapsed_s > 0 else 0.0
        logger.info(
            f"Completed {completed_sim_time_s:.2f} seconds scenario, using {wall_elapsed_s:.2f} sec, speedup: {achieved_speedup:.2f}x"
        )

    def close(self, result: ExecResult | None = None):
        if self.monitor is not None:
            try:
                self.monitor.close(result)
            except Exception:
                logger.exception("monitor.close() failed")
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
        self._last_skip_reason = reason

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

    def _finalize_aborted_concrete(
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
            self.monitor.finalize(status="abort", reason=reason)
        except Exception:
            logger.exception("monitor.finalize() failed while recording aborted concrete")

    def _logical_terminal_counts(self) -> dict[str, int]:
        if self.monitor is None:
            return {"finished": 0, "abort": 0, "skipped": 0}
        return self.monitor.logical_terminal_counts()

    def _exec_result_terminal_counts(self) -> dict[str, int]:
        counts = self._logical_terminal_counts()
        return {
            "finished_concrete_runs": counts["finished"],
            "aborted_concrete_runs": counts["abort"],
            "skipped_concrete_runs": counts["skipped"],
        }
