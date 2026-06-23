import hashlib
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

from simcore.av_wrapper import AVWrapper
from simcore.execution import (
    ExecResult,
    ProgressUpdate,
    RetryHint,
    ScenarioExecutionError,
)
from simcore.execution_manifest import (
    build_execution_manifest,
    finalize_execution_manifest,
    load_execution_manifest,
    validate_existing_manifest,
    write_execution_manifest,
)
from simcore.monitor import Monitor
from simcore.sampler import Sample, SampleResult, create_sampler, load_parameter_space
from simcore.sampler.loader import load_sampler_spec, resolve_sampler_source
from simcore.sim_wrapper import SimWrapper
from simcore.utils.position_parser import PositionParser
from simcore.utils.sps import ScenarioPack

logging.basicConfig(
    level=logging.INFO,
    datefmt="%H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True)],
)

logger = logging.getLogger(__name__)


def _sample_output_and_params(sample: Sample, index: int) -> tuple[str, dict, dict]:
    sample_id = sample.id if sample.id is not None else str(index)
    return f"iteration_{sample_id}", dict(sample.params), sample.sim_params


def _sample_id_from_output(output_related: str) -> str:
    if output_related.startswith("iteration_"):
        return output_related.removeprefix("iteration_")
    return output_related


def _parameter_hash(params: dict[str, Any] | None) -> str:
    payload = json.dumps(
        params or {},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scenario_source_base_path(scenario_path: str | Path | None) -> Path | None:
    if scenario_path is None:
        return None
    path = Path(scenario_path).expanduser()
    if path.exists():
        return path if path.is_dir() else path.parent
    if path.suffix:
        return path.parent
    return path


def _resolve_scenario_relative_path(
    path: str | Path | None,
    scenario_base_path: Path | None,
    default_filename: str | None = None,
) -> str | None:
    if path is None:
        if scenario_base_path is None or default_filename is None:
            return None
        default_path = scenario_base_path / default_filename
        return str(default_path) if default_path.exists() else None

    if not isinstance(path, (str, Path)):
        raise TypeError(
            f"scenario-relative path must be a string or path, got {type(path).__name__}"
        )

    if str(path) == "":
        return None
    resolved_path = Path(path).expanduser()
    if resolved_path.is_absolute() or scenario_base_path is None:
        return str(resolved_path)
    return str(scenario_base_path / resolved_path)


class SimulationEngine:
    def __init__(
        self,
        spec: dict[str, Any],
        progress_callback: Callable[[ProgressUpdate], None] | None = None,
        runner_spec_path: str | Path | None = None,
    ):
        self.spec = spec
        self.runner_spec_path = (
            Path(runner_spec_path).expanduser().resolve() if runner_spec_path else None
        )
        # Best-effort, transport-agnostic hook: simcore emits ProgressUpdate
        # snapshots; the caller decides what to do with them. None = disabled.
        self._progress_callback = progress_callback
        # How many concrete outcomes have already been handed to the
        # callback, so each is emitted exactly once as it finalises.
        self._emitted_outcomes = 0
        runtime_spec = spec.get("runtime", {})
        task_spec = spec.get("task", {})
        sim_spec = spec.get("simulator", {})
        av_spec = spec.get("av", {})
        scenario_spec = spec.get("scenario", {})
        scenario_base_path = _scenario_source_base_path(scenario_spec.get("scenario_path"))
        sampler_spec = load_sampler_spec(
            spec.get("sampler", {}),
            source_base_path=scenario_base_path,
        )
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
        self._stop_condition_config_path = _resolve_scenario_relative_path(
            scenario_spec.get("stop_condition_config_path"),
            scenario_base_path,
            default_filename="stop_conditions.yaml",
        )
        self._execution_manifest_path = self.output_base / "execution_manifest.yaml"
        self._initialize_execution_manifest(
            sampler_spec=sampler_spec,
            scenario_spec=scenario_spec,
            sim_spec=sim_spec,
            av_spec=av_spec,
            monitor_spec=monitor_spec,
        )
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
            log_file=str(self.output_base / "monitor_log.csv"),
            av=self.av,
            sim=self.sim,
            config_path=monitor_spec.get("config_path", None),
            stop_condition_config_path=self._stop_condition_config_path,
            sps=self.sps,
            position_parser=self.position_parser,
            job_id=self.job_id,
        )

        sampler_source_path, sampler_source_type = resolve_sampler_source(sampler_spec)
        if sampler_source_path is not None:
            logger.debug(
                "Sampler source provided: %s (%s)", sampler_source_path, sampler_source_type
            )
            parameter_space = load_parameter_space(sampler_source_path, sampler_source_type)
            self.param_sampler = create_sampler(
                sampler_spec=sampler_spec,
                parameter_space=parameter_space,
            )
            if (
                sampler_spec.get("name") in {"adaptive_boundary", "feedback_boundary"}
                and self._permutation is not None
            ):
                raise ValueError(
                    "runtime.permutation is not supported by feedback-aware samplers"
                )
            self.max_sampler_iterations = sampler_spec.get("max_samples")
        else:
            logger.debug("No sampler source resolved; running as a single concrete scenario.")
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
                concrete_outcomes=self._concrete_outcomes(),
            )
            self.close(result)
            return result

        try:
            if self.param_sampler is not None:
                logger.info("Running logical scenario with parameter sampling.")
                self.run_logical()
            else:
                logger.info("Running single concrete scenario without parameter sampling.")
                self._emit_progress(1)
                self.concrete_wrapper("concrete", self.sps)
                self._emit_progress(1)
        except ScenarioExecutionError as e:
            logger.error(f"Error during scenario execution: {e}")
            result = ExecResult(
                hint=e.hint,
                reason=str(e),
                concrete_outcomes=self._concrete_outcomes(),
                **self._exec_result_terminal_counts(),
            )
        except Exception as e:
            logger.error(f"Error during scenario execution: {e}")
            result = ExecResult(
                hint=RetryHint.RETRY,
                reason=f"{type(e).__name__}: {e}",
                concrete_outcomes=self._concrete_outcomes(),
                **self._exec_result_terminal_counts(),
            )
        else:
            logger.info("Scenario execution completed successfully.")
            result = ExecResult(
                hint=RetryHint.OK,
                reason="completed",
                concrete_outcomes=self._concrete_outcomes(),
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
            sample = self.param_sampler.next()

            if sample is None:
                logger.debug("Parameter sampling completed.")
                break
            # Snapshot before running concrete i+1: counts reflect the i already
            # done, so the i==0 emit doubles as the "started, total=N" event.
            self._emit_progress(total)
            output_related, params, sim_params = _sample_output_and_params(sample, i + 1)

            logger.info(
                f"====================== Sampling iteration {i + 1}/{progress_total} ======================"
            )

            logger.info(f"Sampled parameters: {json.dumps(params)}")
            if sim_params != params:
                logger.info(f"Simulator parameters: {json.dumps(sim_params)}")

            outcome_count = len(self.monitor.concrete_outcomes())
            try:
                self.concrete_wrapper(
                    output_related,
                    self.sps,
                    params,
                    sim_params=sim_params,
                )
            except ScenarioExecutionError as e:
                self._update_sampler(sample, output_related, outcome_count)
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
            except Exception:
                self._update_sampler(sample, output_related, outcome_count)
                raise
            else:
                self._update_sampler(sample, output_related, outcome_count)
            i += 1

        self._emit_progress(total)
        logger.info("Completed all parameter combinations.")

    def _run_logical_permutation(self, total: int | None) -> None:
        permutation = self._permutation
        if total is not None and permutation > total:
            raise ValueError(
                f"runtime.permutation={permutation} is out of range; sampler has {total} sample(s)"
            )

        logger.info("Running only permutation %s/%s", permutation, total or "unknown")
        sample = None
        for index in range(1, permutation + 1):
            sample = self.param_sampler.next()
            if sample is None:
                raise ValueError(
                    f"runtime.permutation={permutation} is out of range; sampler ended at {index - 1}"
                )
        output_related, params, sim_params = _sample_output_and_params(sample, permutation)

        logger.info(
            "====================== Sampling iteration %s/%s ======================",
            permutation,
            total or "unknown",
        )
        logger.info(f"Sampled parameters: {json.dumps(params)}")
        if sim_params != params:
            logger.info(f"Simulator parameters: {json.dumps(sim_params)}")
        self._emit_progress(total)
        self.concrete_wrapper(
            output_related,
            self.sps,
            params,
            sim_params=sim_params,
        )
        self._emit_progress(total)

    def concrete_wrapper(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: dict[str, Any] | None = None,
        *,
        sim_params: dict[str, Any] | None = None,
        sample_id: str | None = None,
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
            self._finalize_aborted_concrete(output_related, params, reason, sample_id=sample_id)
            return

        try:
            if sample_id is None:
                self.run_concrete(output_related, sps, params, sim_params=sim_params)
            else:
                self.run_concrete(
                    output_related,
                    sps,
                    params,
                    sim_params=sim_params,
                    sample_id=sample_id,
                )
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
                        sample_id=sample_id,
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
        *,
        sim_params: dict[str, Any] | None = None,
        sample_id: str | None = None,
    ) -> None:
        """
        Run a single concrete scenario with the given parameters.
        """

        stop_reason = ""
        try:
            logger.debug("Resetting monitor...")
            self._reset_monitor(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
                sample_id=sample_id or _sample_id_from_output(output_related),
                attempt=self._next_summary_attempt(output_related),
                parameter_hash=_parameter_hash(params),
            )
            if self.monitor.should_stop(check_external_quit=False):
                stop_reason = self.monitor.stop_reason or "monitor_stop"
                logger.info(f"Monitor requested to stop before simulator reset ({stop_reason})")
                self.monitor.finalize(
                    status="finished",
                    reason=stop_reason,
                )
                return

            logger.debug("Resetting simulator...")
            runtime_frame = self.sim.reset(
                output_related,
                sps,
                sim_params if sim_params is not None else params,
            )
            raw_obs = runtime_frame.objects if runtime_frame.objects else []

            logger.debug("Resetting AV...")
            ctrl_for_sim = self.av.reset(output_related, sps, raw_obs)

            dt_s = self._dt_s
            dt_ns = int(dt_s * 1e9)

            sim_time_ns = 0  # Simulation time in nanoseconds
            self.monitor.update(sim_time_ns, runtime_frame, ctrl_for_sim)

            wall_start = time.monotonic()
            while True:
                if self.monitor.should_stop():
                    stop_reason = self.monitor.stop_reason or "monitor_stop"
                    logger.info(f"Monitor requested to stop ({stop_reason})")
                    break

                sim_time_ns += dt_ns
                runtime_frame = self.sim.step(ctrl_for_sim, sim_time_ns)
                raw_obs = runtime_frame.objects if runtime_frame.objects else []
                ctrl_for_sim = self.av.step(raw_obs, sim_time_ns)
                self.monitor.update(sim_time_ns, runtime_frame, ctrl_for_sim)

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
                    status="error",
                    reason="KeyboardInterrupt: interrupted by user",
                )
            except Exception:
                logger.exception("monitor.finalize() failed after keyboard interrupt")
            raise
        except ScenarioExecutionError as exc:
            reason = str(exc)
            status = "error"
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
                    status="error",
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
        if result is not None:
            try:
                if hasattr(self, "_execution_manifest_path"):
                    finalize_execution_manifest(
                        self._execution_manifest_path,
                        result=result,
                        monitor_counts=self._manifest_monitor_counts(),
                    )
            except Exception:
                logger.exception("execution_manifest finalization failed")
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
        *,
        sample_id: str | None = None,
    ) -> None:
        try:
            self._reset_monitor(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
                sample_id=sample_id or _sample_id_from_output(output_related),
                attempt=self._next_summary_attempt(output_related),
                parameter_hash=_parameter_hash(params),
            )
            self.monitor.finalize(status="skipped", reason=reason)
        except Exception:
            logger.exception("monitor.finalize() failed while recording skipped concrete")

    def _finalize_aborted_concrete(
        self,
        output_related: str,
        params: dict[str, Any] | None,
        reason: str,
        *,
        sample_id: str | None = None,
    ) -> None:
        try:
            self._reset_monitor(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
                sample_id=sample_id or _sample_id_from_output(output_related),
                attempt=self._next_summary_attempt(output_related),
                parameter_hash=_parameter_hash(params),
            )
            self.monitor.finalize(status="abort", reason=reason)
        except Exception:
            logger.exception("monitor.finalize() failed while recording aborted concrete")

    def _emit_progress(self, total: int | None) -> None:
        if self._progress_callback is None:
            return
        counts = self._logical_terminal_counts()
        outcomes = self.monitor.concrete_outcomes() if self.monitor is not None else []
        # Concretes finalised since the previous tick — usually one, zero for a
        # count-only tick (the start announcement or a skipped-before-run
        # concrete). Each new outcome rides its own update so a consumer can
        # persist it incrementally; with none, emit one count-only update.
        new_outcomes = outcomes[self._emitted_outcomes :]
        self._emitted_outcomes = len(outcomes)
        for outcome in new_outcomes or [None]:
            update = ProgressUpdate(
                total=total,
                finished=counts["finished"],
                aborted=counts["abort"],
                skipped=counts["skipped"],
                outcome=outcome,
            )
            # A reporting failure must never abort a simulation.
            try:
                self._progress_callback(update)
            except Exception:
                logger.exception("progress_callback failed; continuing run")

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

    def _concrete_outcomes(self):
        if self.monitor is None:
            return []
        return self.monitor.concrete_outcomes()

    def _update_sampler(
        self,
        sample: Sample,
        output_related: str,
        previous_outcome_count: int,
    ) -> None:
        update = getattr(self.param_sampler, "update", None)
        if not callable(update):
            return
        result = self._sample_result(output_related, sample, previous_outcome_count)
        update(sample, result)

    def _sample_result(
        self,
        output_related: str,
        sample: Sample,
        previous_outcome_count: int,
    ) -> SampleResult:
        outcomes = self.monitor.concrete_outcomes()
        if len(outcomes) > previous_outcome_count:
            outcome = outcomes[-1]
            return SampleResult(
                params=dict(sample.params),
                status=outcome.status,
                test_outcome=outcome.test_outcome,
                stop_condition=outcome.stop_condition,
                reason=outcome.reason,
                metrics=dict(outcome.metrics or {}),
                metadata={"concrete_key": outcome.concrete_key},
            )

        summary_rows = getattr(self.monitor, "summary_rows", None)
        if callable(summary_rows):
            rows = summary_rows(output_related)
            if rows:
                row = rows[-1]
                return SampleResult(
                    params=dict(sample.params),
                    status=row.get("run.status"),
                    test_outcome=row.get("run.test_outcome"),
                    stop_condition=row.get("run.stop_condition"),
                    reason=row.get("run.stop_reason", ""),
                    metrics={
                        key: self._parse_summary_value(value)
                        for key, value in row.items()
                        if not key.startswith("run.")
                    },
                    metadata={"concrete_key": output_related, "resumed": True},
                )

        return SampleResult(
            params=dict(sample.params),
            status="error",
            reason="Scenario result missing",
            metadata={"concrete_key": output_related},
        )

    @staticmethod
    def _parse_summary_value(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if normalized in {"true", "false"}:
            return normalized == "true"
        if normalized == "":
            return None
        try:
            return float(value)
        except ValueError:
            return value

    def _initialize_execution_manifest(
        self,
        *,
        sampler_spec: dict[str, Any],
        scenario_spec: dict[str, Any],
        sim_spec: dict[str, Any],
        av_spec: dict[str, Any],
        monitor_spec: dict[str, Any],
    ) -> None:
        resolved_inputs = {
            "runner_spec": self.runner_spec_path,
            "scenario": _path_or_none(scenario_spec.get("scenario_path")),
            "simulator_config": _path_or_none(sim_spec.get("config_path")),
            "av_config": _path_or_none(av_spec.get("config_path")),
            "sampler_config": _path_or_none(sampler_spec.get("config_path")),
            "sampler_source": _path_or_none(
                sampler_spec.get("source", {}).get("path")
                if isinstance(sampler_spec.get("source"), dict)
                else None
            ),
            "monitor_config": _path_or_none(monitor_spec.get("config_path")),
            "stop_conditions": _path_or_none(self._stop_condition_config_path),
            "map_osm": _path_or_none(self.spec.get("map", {}).get("osm_path")),
            "map_xodr": _path_or_none(self.spec.get("map", {}).get("xodr_path")),
        }
        effective_spec = {
            **self.spec,
            "sampler": sampler_spec,
        }
        expected = build_execution_manifest(
            effective_spec,
            output_base=self.output_base,
            resolved_inputs=resolved_inputs,
            runner_spec_path=self.runner_spec_path,
        )
        if self._execution_manifest_path.exists():
            existing = load_execution_manifest(self._execution_manifest_path)
            validate_existing_manifest(existing, expected)
            return
        write_execution_manifest(self._execution_manifest_path, expected)

    def _manifest_monitor_counts(self) -> dict[str, int]:
        if self.monitor is None:
            return {}
        cumulative = getattr(self.monitor, "_cumulative_concrete_status_counts", None)
        if callable(cumulative):
            counts = cumulative()
            return {
                "finished": counts.get("finished", 0),
                "failed": counts.get("error", 0),
                "skipped": counts.get("skipped", 0),
                "aborted": counts.get("abort", 0),
            }
        counts = getattr(self.monitor, "current_summary_counts", {})
        return {
            "finished": counts.get("finished", 0),
            "failed": counts.get("error", 0),
            "skipped": counts.get("skipped", 0),
            "aborted": counts.get("abort", 0),
        }

    def _next_summary_attempt(self, output_related: str) -> int:
        next_attempt = getattr(self.monitor, "next_summary_attempt", None)
        if callable(next_attempt):
            return int(next_attempt(output_related))
        return 1

    def _reset_monitor(
        self,
        output_related: str,
        *,
        params: dict[str, Any] | None,
        overwrite_summary: bool,
        sample_id: str,
        attempt: int,
        parameter_hash: str,
    ) -> None:
        try:
            self.monitor.reset(
                output_related,
                params=params,
                overwrite_summary=overwrite_summary,
                sample_id=sample_id,
                attempt=attempt,
                parameter_hash=parameter_hash,
            )
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            self.monitor.reset(
                output_related,
                params=params,
                overwrite_summary=overwrite_summary,
            )


def _path_or_none(path: str | Path | None) -> Path | None:
    if path is None or str(path) == "":
        return None
    return Path(path).expanduser()
