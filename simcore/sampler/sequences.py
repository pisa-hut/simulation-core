from __future__ import annotations

import random
from collections.abc import Sequence

from simcore.sampler.space import ParamDict, ParameterSpace

DEFAULT_SAMPLE_COUNT = 16
SOBOL_BITS = 32

SOBOL_DIRECTION_PARAMS = {
    2: (1, 0, (1,)),
    3: (2, 1, (1, 3)),
    4: (3, 1, (1, 3, 1)),
    5: (3, 2, (1, 1, 3)),
    6: (4, 1, (1, 3, 5, 13)),
    7: (4, 4, (1, 1, 5, 5)),
    8: (5, 2, (1, 3, 3, 9, 7)),
    9: (5, 4, (1, 3, 7, 13, 3)),
    10: (5, 7, (1, 1, 5, 11, 27)),
}


def default_sample_count(parameter_space: ParameterSpace) -> int:
    total = parameter_space.total_combinations()
    if total is None:
        return DEFAULT_SAMPLE_COUNT
    return min(total, DEFAULT_SAMPLE_COUNT)


def units_to_params(parameter_space: ParameterSpace, units: Sequence[float]) -> ParamDict:
    return {
        spec.name: spec.value_from_unit(unit)
        for spec, unit in zip(parameter_space.parameters, units, strict=True)
    }


def lhs_units(
    n_samples: int, n_dimensions: int, seed: int | None = None
) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    columns: list[list[float]] = []
    for _ in range(n_dimensions):
        column = [(index + rng.random()) / n_samples for index in range(n_samples)]
        rng.shuffle(column)
        columns.append(column)

    return [
        tuple(columns[dimension][row] for dimension in range(n_dimensions))
        for row in range(n_samples)
    ]


def _trailing_zero_count(value: int) -> int:
    count = 0
    while value & 1 == 0:
        value >>= 1
        count += 1
    return count


def _direction_numbers(dimension: int, bits: int) -> list[int]:
    if dimension == 1:
        return [1 << (bits - index) for index in range(1, bits + 1)]
    if dimension not in SOBOL_DIRECTION_PARAMS:
        max_dim = max(SOBOL_DIRECTION_PARAMS)
        raise ValueError(f"SobolSampler supports up to {max_dim} dimensions")

    degree, coefficient, initial_numbers = SOBOL_DIRECTION_PARAMS[dimension]
    directions = [0] * bits
    for index, initial in enumerate(initial_numbers, start=1):
        directions[index - 1] = initial << (bits - index)

    for index in range(degree + 1, bits + 1):
        value = directions[index - degree - 1] ^ (directions[index - degree - 1] >> degree)
        for offset in range(1, degree):
            if (coefficient >> (degree - 1 - offset)) & 1:
                value ^= directions[index - offset - 1]
        directions[index - 1] = value

    return directions


def sobol_units(
    n_samples: int,
    n_dimensions: int,
    skip: int = 1,
    bits: int = SOBOL_BITS,
) -> list[tuple[float, ...]]:
    if n_samples < 0:
        raise ValueError("n_samples must be non-negative")
    if n_dimensions < 1:
        return [tuple() for _ in range(n_samples)]

    direction_numbers = [
        _direction_numbers(dimension, bits) for dimension in range(1, n_dimensions + 1)
    ]
    state = [0] * n_dimensions
    points: list[tuple[float, ...]] = []
    denominator = float(1 << bits)

    for index in range(1, n_samples + skip + 1):
        direction_index = _trailing_zero_count(index)
        for dimension in range(n_dimensions):
            state[dimension] ^= direction_numbers[dimension][direction_index]
        if index > skip:
            points.append(tuple(value / denominator for value in state))

    return points
