from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from simcore.sampler.space import ParameterSpace, Sample
from simcore.utils.util import get_cfg

EXPLICIT_SAMPLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
EXPLICIT_SAMPLES_METADATA_KEY = "explicit_samples"


def parse_explicit_sample_file(path: Path) -> ParameterSpace:
    data = get_cfg(path)
    if data is not None and not isinstance(data, dict):
        raise ValueError("Explicit sample config must be a mapping/object")
    return parse_explicit_sample_dict(data or {})


def parse_explicit_sample_dict(data: dict[str, Any]) -> ParameterSpace:
    if not isinstance(data, dict):
        raise ValueError("Explicit sample config must be a mapping/object")

    raw_samples = data.get("samples")
    if not isinstance(raw_samples, list):
        raise ValueError("Explicit sample config must contain a 'samples' list")

    samples: list[Sample] = []
    seen_ids: set[str] = set()
    for index, raw_sample in enumerate(raw_samples, start=1):
        if not isinstance(raw_sample, dict):
            raise ValueError(f"Explicit sample entry #{index} must be a mapping")

        sample_id = _parse_sample_id(raw_sample.get("id"), index)
        if sample_id in seen_ids:
            raise ValueError(f"Duplicate explicit sample id: {sample_id!r}")
        seen_ids.add(sample_id)

        raw_params = raw_sample.get("params")
        if not isinstance(raw_params, dict):
            raise ValueError(f"Explicit sample {sample_id!r} must contain a 'params' mapping")

        samples.append(
            Sample(
                id=sample_id,
                params=dict(raw_params),
                metadata={"source": "explicit", "index": index},
            )
        )

    return ParameterSpace(parameters=(), metadata={EXPLICIT_SAMPLES_METADATA_KEY: tuple(samples)})


def _parse_sample_id(raw_id: Any, index: int) -> str:
    if raw_id is None:
        raise ValueError(f"Explicit sample entry #{index} must define id")

    sample_id = str(raw_id)
    if not sample_id:
        raise ValueError(f"Explicit sample entry #{index} id must not be empty")
    if not EXPLICIT_SAMPLE_ID_PATTERN.fullmatch(sample_id):
        raise ValueError(
            f"Explicit sample id {sample_id!r} may only contain letters, numbers, '_', '.', or '-'"
        )
    return sample_id
