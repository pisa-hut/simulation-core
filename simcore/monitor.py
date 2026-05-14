import logging
from pathlib import Path

import yaml

from simcore.av_wrapper import AVWrapper
from simcore.conditions import ConditionCode, ConditionNode, build_condition_tree
from simcore.sim_wrapper import SimWrapper

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config_path: str | None, log_file: str, av: AVWrapper, sim: SimWrapper):
        self.log_file = log_file
        # self.csv_writer = csv.writer(open(self.log_file, "w", newline=""))
        # header
        # self.csv_writer.writerow(["sim_time_ns", "observation", "control"])

        self.av = av
        self.sim = sim

        self.cfg: dict | None = None
        self.root: ConditionNode | None = None

        if not config_path:
            logger.warning("No monitor config_path provided; condition monitoring is disabled.")
            return

        self._load_config(config_path)
        if "condition" not in self.cfg:
            raise ValueError("Monitor config must contain 'condition' key")

        condition_cfg = self.cfg.get("condition")
        if not isinstance(condition_cfg, dict):
            raise ValueError(
                "Monitor config 'condition' must be a mapping describing a condition tree"
            )

        self.root = build_condition_tree(condition_cfg)
        logger.debug("Built condition tree: %s", self.root)

    def _load_config(self, path: str) -> None:
        self.cfg = yaml.safe_load(Path(path).read_text())
        if not isinstance(self.cfg, dict):
            raise ValueError(
                f"Monitor config at {path!r} must deserialize to a mapping, got {type(self.cfg).__name__}"
            )

    def log(self):
        # self.csv_writer.writerow(
        #     [self.sim.get_time_ns(), self.av.get_observation(), self.av.get_control()]
        # )
        pass

    def update(self, sim_time_ns: int, runtime_frame: dict, control: dict) -> None:
        if self.root:
            self.root.put((sim_time_ns, runtime_frame, control))

    def should_stop(self) -> bool:
        if self.av.should_quit():
            logger.info("AV requested to quit")
            return True
        if self.sim.should_quit():
            logger.info("Simulator requested to quit")
            return True
        if self.root:
            result = self.root.evaluate()
            if result.code == ConditionCode.TRIGGERED:
                logger.info(
                    "Condition %s triggered: %s",
                    result.condition_name,
                    result.detail,
                )
                return True
        return False

    def reset(self, output_related: str):
        # Clear all buffers in the condition tree
        if self.root:
            self.root.reset()
