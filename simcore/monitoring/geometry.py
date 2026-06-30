from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin
from typing import Any

from simcore.metrics.actors import float_attr, object_kinematic

EPSILON = 1e-9


@dataclass(frozen=True)
class ActorGeometry:
    shape_type: str
    length_m: float | None
    width_m: float | None
    height_m: float | None
    footprint: tuple[tuple[float, float], ...] | None = None
    reference_point: str | None = None
    center_offset_x: float = 0.0
    center_offset_y: float = 0.0
    center_offset_z: float = 0.0
    roll_offset: float = 0.0
    pitch_offset: float = 0.0
    yaw_offset: float = 0.0


@dataclass(frozen=True)
class OrientedBox:
    center_x: float
    center_y: float
    yaw: float
    length_m: float
    width_m: float


@dataclass(frozen=True)
class ContactEstimate:
    x: float
    y: float
    source: str
    region: tuple[tuple[float, float], ...] | None = None


def actor_geometry(actor: Any) -> ActorGeometry | None:
    shape = _shape(actor)
    if shape is None:
        return None
    dimensions = getattr(shape, "dimensions", None)
    if dimensions is None:
        return None

    if isinstance(dimensions, tuple | list) and len(dimensions) >= 2:
        length = _positive_float(dimensions[0])
        width = _positive_float(dimensions[1])
        height = _positive_float(dimensions[2]) if len(dimensions) > 2 else None
    else:
        length = _positive_float(getattr(dimensions, "x", None))
        width = _positive_float(getattr(dimensions, "y", None))
        height = _positive_float(getattr(dimensions, "z", None))

    shape_type = _shape_type_name(getattr(shape, "type", None))
    footprint = _footprint(shape)
    pose = getattr(shape, "center", shape)
    return ActorGeometry(
        shape_type=shape_type,
        length_m=length,
        width_m=width,
        height_m=height,
        footprint=footprint,
        reference_point=_optional_text(getattr(shape, "reference_point", None)),
        center_offset_x=_float_or_zero(pose, "center_offset_x", "x"),
        center_offset_y=_float_or_zero(pose, "center_offset_y", "y"),
        center_offset_z=_float_or_zero(pose, "center_offset_z", "z"),
        roll_offset=_float_or_zero(pose, "roll_offset", "roll"),
        pitch_offset=_float_or_zero(pose, "pitch_offset", "pitch"),
        yaw_offset=_float_or_zero(pose, "yaw_offset", "yaw"),
    )


def actor_box(actor: Any) -> OrientedBox | None:
    geometry = actor_geometry(actor)
    if geometry is None or geometry.length_m is None or geometry.width_m is None:
        return None

    kinematic = object_kinematic(actor)
    x = float_attr(kinematic, "x")
    y = float_attr(kinematic, "y")
    if x is None or y is None:
        return None
    actor_yaw = float_attr(kinematic, "yaw") or 0.0
    cos_yaw = cos(actor_yaw)
    sin_yaw = sin(actor_yaw)
    return OrientedBox(
        center_x=x + geometry.center_offset_x * cos_yaw - geometry.center_offset_y * sin_yaw,
        center_y=y + geometry.center_offset_x * sin_yaw + geometry.center_offset_y * cos_yaw,
        yaw=actor_yaw + geometry.yaw_offset,
        length_m=geometry.length_m,
        width_m=geometry.width_m,
    )


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _float_or_zero(value: Any, *names: str) -> float:
    for name in names:
        raw = getattr(value, name, None)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def estimate_contact(box_a: OrientedBox, box_b: OrientedBox) -> ContactEstimate:
    polygon_a = box_corners(box_a)
    polygon_b = box_corners(box_b)
    overlap = polygon_clip(polygon_a, polygon_b)
    if len(overlap) >= 3:
        x, y = polygon_centroid(overlap)
        return ContactEstimate(
            x=zero_small(x),
            y=zero_small(y),
            source="derived_bbox_overlap",
            region=tuple((zero_small(px), zero_small(py)) for px, py in overlap),
        )

    ax, ay, bx, by = closest_points_between_polygons(polygon_a, polygon_b)
    return ContactEstimate(
        x=zero_small((ax + bx) / 2.0),
        y=zero_small((ay + by) / 2.0),
        source="derived_bbox_closest",
        region=None,
    )


def box_corners(box: OrientedBox) -> list[tuple[float, float]]:
    half_l = box.length_m / 2.0
    half_w = box.width_m / 2.0
    local = (
        (half_l, half_w),
        (half_l, -half_w),
        (-half_l, -half_w),
        (-half_l, half_w),
    )
    cos_yaw = cos(box.yaw)
    sin_yaw = sin(box.yaw)
    return [
        (
            box.center_x + x * cos_yaw - y * sin_yaw,
            box.center_y + x * sin_yaw + y * cos_yaw,
        )
        for x, y in local
    ]


def polygon_clip(
    subject_polygon: list[tuple[float, float]],
    clip_polygon: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    output = subject_polygon
    orientation = polygon_orientation(clip_polygon)
    for index, clip_start in enumerate(clip_polygon):
        clip_end = clip_polygon[(index + 1) % len(clip_polygon)]
        input_list = output
        output = []
        if not input_list:
            break
        previous = input_list[-1]
        for current in input_list:
            if _inside(current, clip_start, clip_end, orientation):
                if not _inside(previous, clip_start, clip_end, orientation):
                    output.append(line_intersection(previous, current, clip_start, clip_end))
                output.append(current)
            elif _inside(previous, clip_start, clip_end, orientation):
                output.append(line_intersection(previous, current, clip_start, clip_end))
            previous = current
    return output


def polygon_orientation(polygon: list[tuple[float, float]]) -> float:
    area = 0.0
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        area += x1 * y2 - x2 * y1
    return 1.0 if area >= 0 else -1.0


def polygon_centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    signed_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        cross = x1 * y2 - x2 * y1
        signed_area += cross
        centroid_x += (x1 + x2) * cross
        centroid_y += (y1 + y2) * cross
    if abs(signed_area) < EPSILON:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
    factor = 1.0 / (3.0 * signed_area)
    return centroid_x * factor, centroid_y * factor


def closest_points_between_polygons(
    polygon_a: list[tuple[float, float]],
    polygon_b: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    segment_pair = closest_segments_between_polygons(polygon_a, polygon_b)
    if segment_pair is not None:
        segment_a, segment_b = segment_pair
        mid_a = ((segment_a[0][0] + segment_a[1][0]) / 2.0, (segment_a[0][1] + segment_a[1][1]) / 2.0)
        mid_b = ((segment_b[0][0] + segment_b[1][0]) / 2.0, (segment_b[0][1] + segment_b[1][1]) / 2.0)
        return mid_a[0], mid_a[1], mid_b[0], mid_b[1]

    best = None
    for point in polygon_a:
        closest = closest_point_on_polygon(point, polygon_b)
        distance = squared_distance(point, closest)
        if best is None or distance < best[0]:
            best = (distance, point, closest)
    for point in polygon_b:
        closest = closest_point_on_polygon(point, polygon_a)
        distance = squared_distance(point, closest)
        if best is None or distance < best[0]:
            best = (distance, closest, point)
    _, point_a, point_b = best
    return point_a[0], point_a[1], point_b[0], point_b[1]


def closest_segments_between_polygons(
    polygon_a: list[tuple[float, float]],
    polygon_b: list[tuple[float, float]],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], tuple[tuple[float, float], tuple[float, float]]] | None:
    best = None
    for segment_a in polygon_segments(polygon_a):
        for segment_b in polygon_segments(polygon_b):
            candidate = parallel_overlap_segments(segment_a, segment_b)
            if candidate is None:
                continue
            overlap_a, overlap_b = candidate
            distance = squared_distance(
                ((overlap_a[0][0] + overlap_a[1][0]) / 2.0, (overlap_a[0][1] + overlap_a[1][1]) / 2.0),
                ((overlap_b[0][0] + overlap_b[1][0]) / 2.0, (overlap_b[0][1] + overlap_b[1][1]) / 2.0),
            )
            if best is None or distance < best[0]:
                best = (distance, overlap_a, overlap_b)
    if best is None:
        return None
    return best[1], best[2]


def polygon_segments(
    polygon: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(point, polygon[(index + 1) % len(polygon)]) for index, point in enumerate(polygon)]


def parallel_overlap_segments(
    segment_a: tuple[tuple[float, float], tuple[float, float]],
    segment_b: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[
    tuple[tuple[float, float], tuple[float, float]],
    tuple[tuple[float, float], tuple[float, float]],
] | None:
    (a1, a2), (b1, b2) = segment_a, segment_b
    ax = a2[0] - a1[0]
    ay = a2[1] - a1[1]
    bx = b2[0] - b1[0]
    by = b2[1] - b1[1]
    if abs(ax * by - ay * bx) > EPSILON:
        return None
    length = (ax * ax + ay * ay) ** 0.5
    if length < EPSILON:
        return None
    ux = ax / length
    uy = ay / length
    a_min, a_max = sorted((a1[0] * ux + a1[1] * uy, a2[0] * ux + a2[1] * uy))
    b_min, b_max = sorted((b1[0] * ux + b1[1] * uy, b2[0] * ux + b2[1] * uy))
    start = max(a_min, b_min)
    end = min(a_max, b_max)
    if end < start - EPSILON:
        return None
    nx = -uy
    ny = ux
    a_normal = a1[0] * nx + a1[1] * ny
    b_normal = b1[0] * nx + b1[1] * ny
    overlap_a = (
        (start * ux + a_normal * nx, start * uy + a_normal * ny),
        (end * ux + a_normal * nx, end * uy + a_normal * ny),
    )
    overlap_b = (
        (start * ux + b_normal * nx, start * uy + b_normal * ny),
        (end * ux + b_normal * nx, end * uy + b_normal * ny),
    )
    return overlap_a, overlap_b


def closest_point_on_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> tuple[float, float]:
    best_point = polygon[0]
    best_distance = squared_distance(point, best_point)
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        candidate = closest_point_on_segment(point, start, end)
        distance = squared_distance(point, candidate)
        if distance < best_distance:
            best_point = candidate
            best_distance = distance
    return best_point


def closest_point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length_squared = dx * dx + dy * dy
    if length_squared < EPSILON:
        return start
    ratio = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_squared))
    return sx + ratio * dx, sy + ratio * dy


def squared_distance(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
) -> float:
    dx = point_a[0] - point_b[0]
    dy = point_a[1] - point_b[1]
    return dx * dx + dy * dy


def zero_small(value: float) -> float:
    return 0.0 if abs(value) < EPSILON else value


def line_intersection(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float]:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < EPSILON:
        return p2
    px = (
        (x1 * y2 - y1 * x2) * (x3 - x4)
        - (x1 - x2) * (x3 * y4 - y3 * x4)
    ) / denominator
    py = (
        (x1 * y2 - y1 * x2) * (y3 - y4)
        - (y1 - y2) * (x3 * y4 - y3 * x4)
    ) / denominator
    return px, py


def _inside(
    point: tuple[float, float],
    clip_start: tuple[float, float],
    clip_end: tuple[float, float],
    orientation: float,
) -> bool:
    cross = (
        (clip_end[0] - clip_start[0]) * (point[1] - clip_start[1])
        - (clip_end[1] - clip_start[1]) * (point[0] - clip_start[0])
    )
    return orientation * cross >= -EPSILON


def _shape(actor: Any) -> Any:
    shape = getattr(actor, "shape", None)
    if callable(shape):
        return shape()
    if shape is not None:
        return shape
    return getattr(actor, "_shape", None)


def _shape_type_name(shape_type: Any) -> str | None:
    if shape_type is None:
        return None
    name = getattr(shape_type, "name", None)
    if name is not None:
        return str(name).lower()
    return str(shape_type).lower()


def _footprint(shape: Any) -> tuple[tuple[float, float], ...] | None:
    raw = getattr(shape, "footprint", None)
    if raw is None:
        return None
    points = getattr(raw, "points", raw)
    footprint = []
    for point in points or []:
        if isinstance(point, tuple | list) and len(point) >= 2:
            x = _finite_float(point[0])
            y = _finite_float(point[1])
        else:
            x = _finite_float(getattr(point, "x", None))
            y = _finite_float(getattr(point, "y", None))
        if x is None or y is None:
            continue
        footprint.append((x, y))
    return tuple(footprint) or None


def _positive_float(value: Any) -> float | None:
    parsed = _finite_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed
