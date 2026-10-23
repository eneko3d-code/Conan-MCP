"""Point generation and placement checks used by the level tools (pure Python)."""

import math
import random
from typing import Dict, List, Optional, Sequence, Tuple


def scatter_points(rng: random.Random, bounds: Tuple[float, float, float, float], count: int,
                   min_distance: float = 0.0, max_attempts: int = 30,
                   center: Optional[Tuple[float, float]] = None, radius: Optional[float] = None,
                   existing: Sequence[Tuple[float, float]] = ()) -> List[Tuple[float, float]]:
    """Dart-throwing (Poisson-disc style) points inside a rectangle or circle.

    ``bounds`` = (min_x, min_y, max_x, max_y). ``existing`` points are respected for spacing.
    """
    min_x, min_y, max_x, max_y = bounds
    cell = min_distance / math.sqrt(2) if min_distance > 0 else 0
    grid: Dict[Tuple[int, int], Tuple[float, float]] = {}

    def key(p):
        return (int(p[0] // cell), int(p[1] // cell)) if cell else (0, 0)

    def ok(p):
        if not cell:
            return True
        kx, ky = key(p)
        for gx in range(kx - 2, kx + 3):
            for gy in range(ky - 2, ky + 3):
                q = grid.get((gx, gy))
                if q is not None and math.hypot(p[0] - q[0], p[1] - q[1]) < min_distance:
                    return False
        return True

    for p in existing:
        if cell:
            grid[key(p)] = tuple(p)
    points = []
    attempts = 0
    while len(points) < count and attempts < count * max_attempts:
        attempts += 1
        if center is not None and radius:
            a, r = rng.uniform(0, 2 * math.pi), radius * math.sqrt(rng.random())
            p = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        else:
            p = (rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
        if ok(p):
            points.append(p)
            if cell:
                grid[key(p)] = p
    return points


def path_points(path: Sequence[Tuple[float, float]], spacing: float, jitter: float = 0.0,
                rng: Optional[random.Random] = None) -> List[Tuple[float, float, float]]:
    """Points every ``spacing`` cm along a polyline as (x, y, yaw_degrees_of_tangent)."""
    if len(path) < 2:
        raise ValueError("A path needs at least two points")
    if spacing <= 0:
        raise ValueError("spacing must be > 0")
    rng = rng or random.Random(0)
    out, carry = [], 0.0
    for (x0, y0), (x1, y1) in zip(path[:-1], path[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        yaw = math.degrees(math.atan2(y1 - y0, x1 - x0))
        d = carry
        while d <= seg:
            t = d / seg
            px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if jitter:
                nx, ny = -(y1 - y0) / seg, (x1 - x0) / seg
                off = rng.uniform(-jitter, jitter)
                px, py = px + nx * off, py + ny * off
            out.append((px, py, yaw))
            d += spacing
        carry = d - seg
    return out


def evaluate_placement(bottom_z: float, extent_z: float, ground_z: Optional[float], slope: Optional[float],
                       float_tolerance: float = 30.0, bury_ratio: float = 0.5, max_slope: float = 35.0) -> List[str]:
    """Issues for one actor given its bounds bottom, half-height and the ground below it."""
    issues = []
    if ground_z is None:
        return ["no_ground"]
    gap = bottom_z - ground_z
    if gap > float_tolerance:
        issues.append("floating")
    if -gap > max(extent_z * 2.0 * bury_ratio, float_tolerance):
        issues.append("buried")
    if slope is not None and slope > max_slope:
        issues.append("steep_ground")
    return issues


def bbox_overlaps(boxes: List[dict], min_overlap_ratio: float = 0.25) -> List[Tuple[str, str, float]]:
    """Pairs of boxes ({"id","min":(x,y,z),"max":(x,y,z)}) whose overlap volume exceeds the ratio of the smaller."""
    cell = max(max(b["max"][0] - b["min"][0], b["max"][1] - b["min"][1]) for b in boxes) if boxes else 1.0
    cell = max(cell, 1.0)
    buckets: Dict[Tuple[int, int], List[int]] = {}
    for i, b in enumerate(boxes):
        for gx in range(int(b["min"][0] // cell), int(b["max"][0] // cell) + 1):
            for gy in range(int(b["min"][1] // cell), int(b["max"][1] // cell) + 1):
                buckets.setdefault((gx, gy), []).append(i)
    pairs, seen = [], set()
    for members in buckets.values():
        for ai in range(len(members)):
            for bi in range(ai + 1, len(members)):
                i, j = members[ai], members[bi]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                a, b = boxes[i], boxes[j]
                dims = [min(a["max"][k], b["max"][k]) - max(a["min"][k], b["min"][k]) for k in range(3)]
                if min(dims) <= 0:
                    continue
                inter = dims[0] * dims[1] * dims[2]
                vol = lambda bx: max((bx["max"][0] - bx["min"][0]) * (bx["max"][1] - bx["min"][1]) * (bx["max"][2] - bx["min"][2]), 1e-6)  # noqa: E731
                ratio = inter / min(vol(a), vol(b))
                if ratio >= min_overlap_ratio:
                    pairs.append((a["id"], b["id"], round(ratio, 2)))
    return pairs


def density_grid(points: List[dict], bounds: Tuple[float, float, float, float], cells: int) -> dict:
    """Bins points ({"x","y","category"}) into a cells x cells grid over bounds."""
    min_x, min_y, max_x, max_y = bounds
    w = max((max_x - min_x) / cells, 1e-6)
    h = max((max_y - min_y) / cells, 1e-6)
    grid = [[{"count": 0, "categories": {}} for _ in range(cells)] for _ in range(cells)]
    for p in points:
        cx = min(cells - 1, max(0, int((p["x"] - min_x) / w)))
        cy = min(cells - 1, max(0, int((p["y"] - min_y) / h)))
        cell = grid[cy][cx]
        cell["count"] += 1
        cat = p.get("category", "other")
        cell["categories"][cat] = cell["categories"].get(cat, 0) + 1
    flat = []
    for r in range(cells):
        for c in range(cells):
            g = grid[r][c]
            flat.append({"row": r, "col": c,
                         "center": {"x": round(min_x + (c + 0.5) * w, 1), "y": round(min_y + (r + 0.5) * h, 1)},
                         "count": g["count"], "categories": g["categories"]})
    counts = [f["count"] for f in flat]
    mean = sum(counts) / len(counts) if counts else 0
    return {
        "cells": cells,
        "cell_size_cm": {"x": round(w, 1), "y": round(h, 1)},
        "counts": [[grid[r][c]["count"] for c in range(cells)] for r in range(cells)],
        "mean_per_cell": round(mean, 2),
        "hotspots": sorted([f for f in flat if f["count"] > 0], key=lambda f: f["count"], reverse=True)[:10],
        "empty_cells": sum(1 for c in counts if c == 0),
    }
