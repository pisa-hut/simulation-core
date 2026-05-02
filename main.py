import argparse
import json
import logging

from simcore.engine import SimulationEngine

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def get_args():
    parser = argparse.ArgumentParser(description="Run a scenario based on a runner specification.")
    parser.add_argument(
        "--runner_spec",
        type=str,
        required=True,
        help="Path to the runner specification JSON file.",
    )
    return parser.parse_args()


def main():
    args = get_args()

    with open(args.runner_spec) as f:
        runner_spec = json.load(f)

    engine = SimulationEngine(runner_spec)
    engine.exec()


if __name__ == "__main__":
    main()
