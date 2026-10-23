"""Terrain analysis on a sampled grid of heights/slopes (pure Python)."""

from typing import List, Optional

SLOPE_BANDS = ((0, 10, "flat"), (10, 20, "gentle"), (20, 35, "walkable"), (35, 50, "steep"), (50, 91, "cliff"))


def slope_band(slope: float) -> str:
    for lo, hi, name in SLOPE_BANDS:
        if lo <= slope < hi:
            return name
    return "cliff"


def analyze_grid(samples: List[List[Optional[dict]]], cell_size: float, flat_max_slope: float = 10.0,
                 min_flat_cells: int = 4, water_z: Optional[float] = None, top_n: int = 8) -> dict:
    """``samples[row][col]`` = {"x","y","z","slope"} or None (no ground hit).

    Returns height/slope statistics, a slope histogram and the largest connected
    flat regions (good build sites / POI candidates).
    """
    rows = len(samples)
    cols = len(samples[0]) if rows else 0
    heights, hist, missing = [], {name: 0 for _, _, name in SLOPE_BANDS}, 0
    below_water = 0
    for row in samples:
        for s in row:
            if s is None:
                missing += 1
                continue
            heights.append(s["z"])
            hist[slope_band(s["slope"])] += 1
            if water_z is not None and s["z"] < water_z:
                below_water += 1
    total = len(heights)
    if not total:
        return {"samples": 0, "missing": missing, "note": "No ground was hit in the sampled area"}

    seen = [[False] * cols for _ in range(rows)]
    regions = []
    for r in range(rows):
        for c in range(cols):
            s = samples[r][c]
            if seen[r][c] or s is None or s["slope"] > flat_max_slope or (water_z is not None and s["z"] < water_z):
                continue
            stack, cells = [(r, c)], []
            seen[r][c] = True
            while stack:
                cr, cc = stack.pop()
                cells.append(samples[cr][cc])
                for nr, nc in ((cr + 1, cc), (cr - 1, cc), (cr, cc + 1), (cr, cc - 1)):
                    if 0 <= nr < rows and 0 <= nc < cols and not seen[nr][nc]:
                        n = samples[nr][nc]
                        if n is not None and n["slope"] <= flat_max_slope and (water_z is None or n["z"] >= water_z):
                            seen[nr][nc] = True
                            stack.append((nr, nc))
            if len(cells) >= min_flat_cells:
                zs = [c_["z"] for c_ in cells]
                regions.append({
                    "center": {"x": round(sum(c_["x"] for c_ in cells) / len(cells), 1),
                               "y": round(sum(c_["y"] for c_ in cells) / len(cells), 1),
                               "z": round(sum(zs) / len(zs), 1)},
                    "cells": len(cells),
                    "approx_area_m2": round(len(cells) * (cell_size / 100.0) ** 2, 1),
                    "height_range_cm": round(max(zs) - min(zs), 1),
                })
    regions.sort(key=lambda g: g["cells"], reverse=True)

    mean = sum(heights) / total
    return {
        "samples": total,
        "missing": missing,
        "cell_size_cm": cell_size,
        "height": {"min": round(min(heights), 1), "max": round(max(heights), 1), "mean": round(mean, 1),
                   "range": round(max(heights) - min(heights), 1)},
        "slope_histogram": {k: {"cells": v, "percent": round(100.0 * v / total, 1)} for k, v in hist.items()},
        "walkable_percent": round(100.0 * (hist["flat"] + hist["gentle"] + hist["walkable"]) / total, 1),
        "below_water_percent": round(100.0 * below_water / total, 1) if water_z is not None else None,
        "flat_regions": regions[:top_n],
    }
