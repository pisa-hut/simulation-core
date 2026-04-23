import logging
from pathlib import Path

import yaml

from simcore.av_wrapper import AVWrapper
from simcore.sim_wrapper import SimWrapper

from simcore.conditions import ConditionNode, ConditionCode, build_condition_tree

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config_path: str | None, av: AVWrapper, sim: SimWrapper):
        self.av = av
        self.sim = sim

        self.cfg: dict | None = None
        self.root: ConditionNode | None = None

        if not config_path:
            logger.warning(
                "No monitor config_path provided; condition monitoring is disabled."
            )
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

    def update(self, sim_time_ns: int, observation: dict, control: dict) -> None:
        if self.root is None:
            return
        self.root.put((sim_time_ns, observation, control))

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
