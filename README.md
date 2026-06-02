# PISA SimCore Runner

`simcore` is the Python runner for PISA scenario execution. It connects to simulator and AV gRPC services through `pisa-api`, runs concrete or parameterized scenarios, evaluates stop conditions, and writes monitor logs and summaries.

The codebase is intentionally split by responsibility:

- `SimulationEngine` owns scenario lifecycle and retry/skip behavior.
- `SimWrapper` and `AVWrapper` own simulator/AV gRPC communication.
- `sampler` owns concrete parameter generation.
- `Monitor` owns stop-condition evaluation and logging.
- `metrics` contains shared calculations used by both conditions and recorders.

## Requirements

- Python `>=3.14`
- `uv`
- Reachable simulator gRPC service
- Reachable AV gRPC service

Install dependencies:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --locked
```

Run tests and lint:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
```

## Quick Start

Run a scenario from a runner spec:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python main.py --runner_spec specs/sakura.json
```

A runner spec configures runtime settings, output paths, simulator and AV endpoints, map/scenario metadata, optional parameter sampling, and monitor behavior.

## Documentation

- [Docs Overview](docs/README.md)
- [Engine](docs/engine/): runner spec, lifecycle, output layout, retry/skip behavior.
- [AV and Simulator Wrappers](docs/wrappers/): gRPC lifecycle and wrapper config.
- [Sampler](docs/sampler/): sampler config format, implemented sampler names, examples.
- [Monitor](docs/monitor/): stop conditions, logging pipelines, result status fields, extension notes.

## Repository Layout

```text
main.py                         # CLI entrypoint
simcore/engine.py               # SimulationEngine lifecycle
simcore/sim_wrapper.py          # Simulator gRPC wrapper
simcore/av_wrapper.py           # AV gRPC wrapper
simcore/monitor.py              # Stop condition + logging coordinator
simcore/conditions/             # Stop condition tree and condition implementations
simcore/monitoring/             # Frame/table/summary logging infrastructure
simcore/metrics/                # Shared domain metrics used by conditions and recorders
simcore/sampler/                # Parameter samplers
simcore/utils/                  # Scenario, object, control, position helpers
docs/                           # Detailed implementation and usage docs
specs/                          # Runner spec examples
tests/                          # Unit tests
```

## Development Commands

Run one test file:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_monitor_logging.py
```

Inspect sampler output without running simulator/AV:

```bash
python sampler_tester.py docs/sampler/examples/parameter_space.yaml --source-type param_range --method lhs --n-samples 8 --seed 42
```
