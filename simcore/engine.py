import logging
from pathlib import Path
from time import time
from typing import Any

from simcore.av_wrapper import AVWrapper
from simcore.monitor import Monitor
from simcore.sampler import create_sampler, load_parameter_space
from simcore.sampler.loader import resolve_sampler_source
from simcore.sim_wrapper import SimWrapper
from simcore.utils.position_parser import PositionParser
from simcore.utils.sps import ScenarioPack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
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
        self._dt_s = runtime_spec.get("dt", None)
        if self._dt_s is None:
            logger.warning("No 'dt' specified in runtime_spec; defaulting to 0.01s")
            self._dt_s = 0.01
        self.overwrite = bool(runtime_spec.get("overwrite", False))

        self.job_id = task_spec.get("job_id", "unknown_job")
        self.output_base = Path(task_spec.get("output_dir", "./outputs")).expanduser().resolve()
        self.output_base.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output base directory set to: {self.output_base}")

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

        # Count of concrete-scenario executions that actually ran to
        # completion during this engine lifetime. The executor reads this
        # after exec() (regardless of whether it raised) to tell the
        # manager whether the run was "useful" — a run with zero finished
        # concretes counts toward the permanent-fail streak.
        self.completed_concrete_runs = 0

    def exec(self) -> None:
        """
        Run the scenario(s) according to the provided specifications.
        If a parameter sampler is provided, it will iterate through all parameter combinations;
        otherwise, it will run a single concrete scenario.
        """
        try:
            if self.param_sampler is not None:
                logger.info("Running logical scenario with parameter sampling.")
                self.run_logical()
            else:
                logger.info("Running single concrete scenario without parameter sampling.")
                self.concrete_wrapper("concrete", self.sps)
        except Exception as e:
            logger.error(f"Error during scenario execution: {e}")
            raise e
        else:
            logger.info("Scenario execution completed successfully.")
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

            logger.info(f"Sampling iteration {i + 1}/{progress_total} : {params}")

            try:
                self.concrete_wrapper(f"iteration_{i + 1}", self.sps, params)
            except RuntimeError as e:
                logger.error(
                    f"Scenario execution failed at iteration {i + 1} with parameters: {params}"
                )
                raise e
            i += 1

        logger.info("Completed all parameter combinations.")

    def concrete_wrapper(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: dict[str, Any] | None = None,
    ) -> None:
        if self.monitor.has_finished_summary(output_related) and not self.overwrite:
            logger.warning(
                f"Finished summary already exists for {output_related}. Skipping execution."
            )
            return

        try:
            self.run_concrete(output_related, sps, params)
        except Exception as e:
            logger.error(f"Error in concrete scenario execution for {output_related}: {e}")
            raise e
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
            logger.info("Resetting monitor...")
            self.monitor.reset(
                output_related,
                params=params,
                overwrite_summary=self.overwrite,
            )

            logger.info("Resetting simulator...")
            runtime_frame = self.sim.reset(output_related, sps, params)
            raw_obs = runtime_frame.objects if runtime_frame.objects else []

            logger.info("Resetting AV...")
            ctrl_for_sim = self.av.reset(output_related, sps, raw_obs)

            dt_s = self._dt_s
            dt_ns = int(dt_s * 1e9)

            use_real_time = False
            if dt_ns <= 0:  # use real-time stepping
                dt_ns = 0
                use_real_time = True
                prev = time()

            sim_time_ns = 0  # Simulation time in nanoseconds
            logger.info("Starting execution loop. using dt_s=%.3f", dt_s)

            real_start_time_s = time()
            sim_time_need = 0
            while True:
                if self.monitor.should_stop():
                    stop_reason = self.monitor.stop_reason or "monitor_stop"
                    logger.info(f"Monitor requested to stop ({stop_reason})")
                    break

                if use_real_time:
                    t = time()
                    dt_ns = int((t - prev) * 1e9)
                    prev = t

                runtimeFrame = self.sim.step(ctrl_for_sim, sim_time_ns)
                raw_obs = runtimeFrame.objects if runtimeFrame.objects else []
                ctrl_for_sim = self.av.step(raw_obs, sim_time_ns)
                self.monitor.update(sim_time_ns, runtimeFrame, ctrl_for_sim)

                sim_time_ns += dt_ns

                cur_time_s = time()
                time_use_s = cur_time_s - real_start_time_s

                print(
                    f"time use = {time_use_s:.2f} s, sim_time = {sim_time_ns / 1e9:.2f} s",
                    end="\r",
                )

                sim_time_need = time() - real_start_time_s

                ### sleep to sync with real time if we're running faster than real time
                # if sim_time_need < sim_time_ns / 1e9:
                #     time_to_sleep_s = (sim_time_ns / 1e9) - sim_time_need
                #     sleep(time_to_sleep_s/2)

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
            except Exception:
                logger.exception("monitor.finalize() failed after keyboard interrupt")
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

        logger.info(
            f"Completed {sim_time_ns / 1e9:.2f} seconds scenario, using {sim_time_need:.2f} sec."
        )

    def close(self):
        try:
            self.av.stop()
        except Exception:
            logger.exception("av.stop() failed")
        try:
            self.sim.stop()
        except Exception:
            logger.exception("sim.stop() failed")
        try:
            self.position_parser.close()
        except Exception:
            logger.exception("position_parser.close() failed")
