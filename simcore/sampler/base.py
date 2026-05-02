from __future__ import annotations

import logging
import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

ParamDict = dict[str, Any]
TestResult = dict[str, Any]


class Sampler:
    def next(
        self,
        past_results: Iterable[TestResult] | None = None,
    ) -> ParamDict | None:
        raise NotImplementedError


@dataclass
class ParameterSpec:
    name: str
    values: list[float]


def frange_inclusive(lower: float, upper: float, step: float, tol: float = 1e-9) -> list[float]:
    if (step <= 0 and upper > lower) or (step >= 0 and upper < lower):
        raise ValueError(f"Invalid step {step} for range [{lower}, {upper}]")

    n_steps = int(math.floor((upper - lower) / step + tol)) if step != 0 else 0
    vals = []
    for i in range(n_steps + 1):
        val = lower + i * step
        if (step > 0 and val > upper + tol) or (step < 0 and val < upper - tol):
            break
        vals.append(val)

    logger.info(
        f"vals: {vals}, upper: {upper}, tol: {tol}, last_val: {vals[-1] if vals else 'N/A'}"
    )

    # if vals and upper - vals[-1] > tol:
    #     vals.append(upper)

    return vals


def parse_parameter_value_distribution(xml_str: str) -> list[ParameterSpec]:
    root = ET.fromstring(xml_str)
    pvd = (
        root
        if root.tag == "ParameterValueDistribution"
        else root.find(".//ParameterValueDistribution")
    )
    if pvd is None:
        raise ValueError("Cannot find ParameterValueDistribution element")

    det = pvd.find("Deterministic")
    if det is None:
        raise ValueError("Only <Deterministic> distributions are supported for now")

    specs: list[ParameterSpec] = []

    for elem in det.findall("DeterministicSingleParameterDistribution"):
        name = elem.attrib["parameterName"]

        dist_range = elem.find("DistributionRange")
        if dist_range is None:
            raise ValueError(f"Missing <DistributionRange> for parameter {name}")

        step = float(dist_range.attrib["stepWidth"])

        range_elem = dist_range.find("Range")
        if range_elem is None:
            raise ValueError(f"Missing <Range> for parameter {name}")

        lower = float(range_elem.attrib["lowerLimit"])
        upper = float(range_elem.attrib["upperLimit"])

        values = frange_inclusive(lower, upper, step)
        specs.append(ParameterSpec(name=name, values=values))

    return specs


class BaseSampler(Sampler):
    def __init__(self, specs: list[ParameterSpec]):
        self.specs = specs

    def update_with_results(self, past_results: Iterable[TestResult] | None):
        if not past_results:
            return
