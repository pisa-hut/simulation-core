import argparse
import json
import logging
import sys

from simcore.engine import SimulationEngine
from simcore.execution import RetryHint

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

    engine = SimulationEngine(runner_spec, runner_spec_path=args.runner_spec)
    result = engine.exec()

    logger.info(
        "Engine finished: hint=%s, reason=%s, finished_concrete_runs=%d, aborted_concrete_runs=%d, skipped_concrete_runs=%d",
        result.hint.value,
        result.reason,
        result.finished_concrete_runs,
        result.aborted_concrete_runs,
        result.skipped_concrete_runs,
    )
    # OK = clean completion. Anything else exits non-zero so callers
    # (CI, ad-hoc shell loops) can tell a failed run from a successful
    # one without parsing the log.
    sys.exit(0 if result.hint is RetryHint.OK else 1)


if __name__ == "__main__":
    main()
