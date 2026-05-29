from __future__ import annotations

import xml.etree.ElementTree as ET

from simcore.sampler.space import (
    ParameterSpace,
    ParameterSpec,
    numeric_range_inclusive,
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local_name(child.tag) == name]


def _find_descendant(element: ET.Element, name: str) -> ET.Element | None:
    for node in element.iter():
        if _local_name(node.tag) == name:
            return node
    return None


def parse_parameter_value_distribution(xml_str: str) -> ParameterSpace:
    root = ET.fromstring(xml_str)
    pvd = (
        root
        if _local_name(root.tag) == "ParameterValueDistribution"
        else _find_descendant(
            root,
            "ParameterValueDistribution",
        )
    )
    if pvd is None:
        raise ValueError("Cannot find ParameterValueDistribution element")

    deterministic = _first_child(pvd, "Deterministic")
    if deterministic is None:
        raise ValueError("Only <Deterministic> distributions are supported for now")

    specs: list[ParameterSpec] = []
    for elem in _children(deterministic, "DeterministicSingleParameterDistribution"):
        name = elem.attrib["parameterName"]
        dist_range = _first_child(elem, "DistributionRange")
        if dist_range is None:
            raise ValueError(f"Missing <DistributionRange> for parameter {name}")

        range_elem = _first_child(dist_range, "Range")
        if range_elem is None:
            raise ValueError(f"Missing <Range> for parameter {name}")

        values = numeric_range_inclusive(
            lower=float(range_elem.attrib["lowerLimit"]),
            upper=float(range_elem.attrib["upperLimit"]),
            step=float(dist_range.attrib["stepWidth"]),
        )
        specs.append(
            ParameterSpec(
                name=name,
                values=values,
                metadata={"source": "xosc", "distribution": "deterministic_range"},
            )
        )

    return ParameterSpace.from_specs(specs)
