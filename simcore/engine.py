import importlib
import logging
from pathlib import Path
from time import time
from typing import Any, Optional

from simcore.av_wrapper import AVWrapper
from simcore.monitor import Monitor
from simcore.sim_wrapper import SimWrapper
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
        self.dry_run = runtime_spec.get("dry_run", False)

        self.job_id = task_spec.get("job_id", "unknown_job")
        self.output_base = (
            Path(task_spec.get("output_dir", "./outputs")).expanduser().resolve()
        )
        self.output_base.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output base directory set to: {self.output_base}")

        try:
            self.sps = ScenarioPack.from_dict(scenario_spec, map_spec)
        except Exception as exc:
            logger.exception(
                "Failed to create ScenarioPack from scenario and map specifications."
            )
            raise exc

        try:
            self.sim = SimWrapper(
                sim_spec=sim_spec,
                dt_ns=int(self._dt_s * 1e9),
            )
        except Exception as exc:
            logger.error("Simulator initialization failed")
            raise exc

        try:
            self.av = AVWrapper(
                av_spec=av_spec,
                dt_ns=int(self._dt_s * 1e9),
                map_name=map_spec.get("name", "unknown_map"),
            )
        except Exception as exc:
            logger.error("AV initialization failed")
            raise exc

        self.monitor = Monitor(
            config_path=monitor_spec.get("config_path", None),
            av=self.av,
            sim=self.sim,
        )

        if self.sps.param_range_file is not None:
            logger.debug("Parameter range file provided: %s", self.sps.param_range_file)
            # param_sampler
            module = importlib.import_module(sampler_spec["module_path"].split(":")[0])
            sampler_class = getattr(module, sampler_spec["module_path"].split(":")[1])
            self.param_sampler = sampler_class(
                param_range_file=self.sps.param_range_file,
                past_results=None,
            )
        else:
            logger.debug(
                "No parameter range file provided; seem as testing a concrete scenario; skipping parameter sampler."
            )
            self.param_sampler = None

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
                logger.info(
                    "Running single concrete scenario without parameter sampling."
                )
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
        total = self.param_sampler.total_permutations()

        logger.debug(f"Total parameter combinations: {total}")

        for i in range(total):
            logger.info(f"Sampling iteration {i+1}/{total}")
            params = self.param_sampler.next()

            if params is None:
                logger.debug("Parameter sampling completed.")
                break

            logger.debug(f"Running scenario with parameters: {params}")

            try:
                self.concrete_wrapper(f"iteration_{i+1}", self.sps, params)
            except RuntimeError as e:
                logger.error(
                    f"Scenario execution failed at iteration {i+1} with parameters: {params}"
                )
                raise e

        logger.info("Completed all parameter combinations.")

    def concrete_wrapper(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        status_dir = Path(self.output_base / output_related / "status")
        status_dir.mkdir(parents=True, exist_ok=True)

        completed_file = status_dir / "completed.txt"
        if completed_file.exists() and not self.dry_run:
            logger.warning(
                f"Completed file already exists for {output_related}. Skipping execution."
            )
            return

        try:
            self.run_concrete(output_related, sps, params)
        except Exception as e:
            logger.error(
                f"Error in concrete scenario execution for {output_related}: {e}"
            )
            with open(status_dir / "error.txt", "a") as f:
                f.write(
                    f"Error at {time()} by job {self.job_id}: {type(e).__name__}: {str(e)}\n"
                )
            raise e
        else:
            # Count the execution as soon as run_concrete returned cleanly,
            # before any IO that might fail. Dry runs still count — the
            # scenario did run, we're just not persisting completed.txt.
            self.completed_concrete_runs += 1
            if self.dry_run:
                logger.info(
                    f"Dry run mode enabled; skipping writing completed file for {output_related}."
                )
                return
            with open(completed_file, "w") as f:
                f.write(f"Completed at {time()} by job {self.job_id}\n")
            logger.info(f"Scenario {output_related} completed successfully.")

    def run_concrete(
        self,
        output_related: str,
        sps: ScenarioPack,
        params: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Run a single concrete scenario with the given parameters.
        """

        raw_obs = None

        logger.info(f"Resetting simulator...")
        raw_obs = self.sim.reset(output_related, sps, params)

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
        while True:
            if self.monitor.should_stop():
                logger.info("Monitor requested to stop the scenario.")
                break

            if use_real_time:
                t = time()
                dt_ns = int((t - prev) * 1e9)
                prev = t

            raw_obs = self.sim.step(ctrl_for_sim, sim_time_ns)
            ctrl_for_sim = self.av.step(raw_obs, sim_time_ns)
            self.monitor.update(sim_time_ns, raw_obs, ctrl_for_sim)

            sim_time_ns += dt_ns

            cur_time_s = time()
            time_use_s = cur_time_s - real_start_time_s

            print(
                f"time use = {time_use_s:.2f} s, sim_time = {sim_time_ns / 1e9:.2f} s",
                end="\r",
            )

            sim_time_need = time() - real_start_time_s

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
