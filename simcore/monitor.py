import logging
from pathlib import Path
import yaml

from simcore.av_wrapper import AVWrapper
from simcore.sim_wrapper import SimWrapper
from simcore.conditions.condition import ConditionCode, ConditionNode


logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, config_path: str, av: AVWrapper, sim: SimWrapper):
        self.av = av
        self.sim = sim

        self.cfg = None
        self.root: ConditionNode = None

        self._load_config(config_path)
        assert "condition" in self.cfg, "Monitor config must contain 'condition' key"

        condition_cfg = self.cfg.get("condition")
        if not isinstance(condition_cfg, dict):
            raise ValueError(
                "Monitor config 'condition' must be a mapping describing an and/or condition tree"
            )
        condition_type = condition_cfg.get("type").lower()
        if condition_type not in {"and", "or"}:
            raise ValueError(
                "Monitor root condition must be a composite 'and' or 'or' node; "
                f"got {condition_type!r}"
            )
        self.root = ConditionNode(condition_cfg)

        logger.debug("Built condition tree: %s", self.root)

    def _load_config(self, path: str) -> None:
        self.cfg = yaml.safe_load(Path(path).read_text())

    def update(self, sim_time_ns: int, observation: dict, control: dict) -> None:
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
                    f"Condition {result.condition_name} triggered: {result.detail}"
                )
                return True
        return False
