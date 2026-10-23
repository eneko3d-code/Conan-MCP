"""Map analysis: terrain sampling, terrain statistics and actor layout (the data behind map-design decisions)."""

import math

from ..core import config, ue
from ..core.security import READ_ONLY
from ..mapping.classify import classify
from ..mapping.placement import density_grid
from ..mapping.terrain import analyze_grid
from .level import AREA, _ground


def _area_bounds(area):
    """(min_x, min_y, max_x, max_y) from an area dict, or the landscape/level bounds when omitted."""
    if area:
        if "center" in area and area.get("radius") is not None:
            c, r = area["center"], float(area["radius"])
            return float(c.get("x", 0)) - r, float(c.get("y", 0)) - r, float(c.get("x", 0)) + r, float(c.get("y", 0)) + r
        if "min" in area and "max" in area:
            return float(area["min"]["x"]), float(area["min"]["y"]), float(area["max"]["x"]), float(area["max"]["y"])
        raise ValueError("area needs {center, radius} or {min, max}")
    return level_bounds()


def level_bounds(prefer_landscape=True):
    actors = ue.all_actors()
    boxes = []
    for a in actors:
        cname = ue.class_name(a)
        if prefer_landscape and not cname.startswith("Landscape"):
            continue
        origin, extent = ue.actor_bounds(a)
        boxes.append((origin.x - extent.x, origin.y - extent.y, origin.x + extent.x, origin.y + extent.y))
    if not boxes and prefer_landscape:
        return level_bounds(prefer_landscape=False)
    if not boxes:
        raise ValueError("The level has no actors to derive bounds from; pass an explicit area")
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def sample_grid(bounds, resolution):
    min_x, min_y, max_x, max_y = bounds
    n = int(resolution)
    if n * n > config.MAX_TRACE_SAMPLES:
        raise ValueError(f"resolution {n} exceeds the {config.MAX_TRACE_SAMPLES}-sample limit")
    dx = (max_x - min_x) / max(n - 1, 1)
    dy = (max_y - min_y) / max(n - 1, 1)
    rows = []
    for r in range(n):
        row = []
        for c in range(n):
            x, y = min_x + c * dx, min_y + r * dy
            hit = _ground(x, y)
            row.append(None if hit is None else {"x": round(x, 1), "y": round(y, 1),
                                                 "z": hit["location"]["z"], "slope": hit["slope_deg"],
                                                 "hit_class": hit.get("actor_class")})
        rows.append(row)
    return rows, max(dx, dy)


def tool_sample_terrain(args):
    ue.require()
    if args.get("points"):
        pts = args["points"]
        if len(pts) > 2000:
            raise ValueError("At most 2000 points per call")
        out = []
        for p in pts:
            hit = _ground(float(p["x"]), float(p["y"]))
            out.append({"x": p["x"], "y": p["y"], "hit": hit})
        return {"samples": out}
    bounds = _area_bounds(args.get("area"))
    rows, cell = sample_grid(bounds, int(args.get("resolution", 16)))
    return {"bounds": {"min_x": bounds[0], "min_y": bounds[1], "max_x": bounds[2], "max_y": bounds[3]},
            "cell_size_cm": round(cell, 1), "grid": rows}


def _recommend_terrain(stats, max_walk_slope):
    tips = []
    if not stats.get("samples"):
        return tips
    walk = stats["walkable_percent"]
    if walk < 50:
        tips.append(f"Only {walk}% of the area is walkable (<35 deg). Add ramps or smooth key routes before placing POIs.")
    cliff = stats["slope_histogram"]["cliff"]["percent"]
    if cliff > 15:
        tips.append(f"{cliff}% is cliff (>50 deg): good natural barriers, keep paths around them.")
    if stats["flat_regions"]:
        best = stats["flat_regions"][0]
        tips.append(f"Largest flat site ~{best['approx_area_m2']} m2 at ({best['center']['x']}, {best['center']['y']}): "
                    f"candidate for a settlement, camp or player build zone.")
    else:
        tips.append("No flat regions found: flatten pads with sculpt_terrain(operation='flatten') for structures.")
    if stats["height"]["range"] < 500:
        tips.append("Very little relief (<5 m): add hills or ridges with sculpt_terrain(raise/noise) for visual interest and sightline breaks.")
    return tips


def tool_analyze_terrain(args):
    ue.require()
    bounds = _area_bounds(args.get("area"))
    rows, cell = sample_grid(bounds, int(args.get("resolution", 32)))
    water_z = args.get("water_level")
    stats = analyze_grid(rows, cell, float(args.get("flat_max_slope", 10.0)),
                         int(args.get("min_flat_cells", 4)), float(water_z) if water_z is not None else None)
    stats["bounds"] = {"min_x": bounds[0], "min_y": bounds[1], "max_x": bounds[2], "max_y": bounds[3]}
    stats["recommendations"] = _recommend_terrain(stats, 35.0)
    return stats


def tool_get_map_layout(args):
    ue.require()
    bounds = _area_bounds(args.get("area"))
    cells = int(args.get("cells", 8))
    points, totals = [], {}
    for a in ue.all_actors():
        loc = a.get_actor_location()
        if not (bounds[0] <= loc.x <= bounds[2] and bounds[1] <= loc.y <= bounds[3]):
            continue
        cat = classify(ue.class_name(a), ue.actor_label(a))
        if cat in ("landscape", "atmosphere", "gameplay"):
            continue
        totals[cat] = totals.get(cat, 0) + 1
        points.append({"x": loc.x, "y": loc.y, "category": cat, "label": ue.actor_label(a)})
    grid = density_grid(points, bounds, cells)
    tips = []
    light_budget = int(args.get("max_lights_per_cell", 12))
    for h in grid["hotspots"]:
        lights = h["categories"].get("light", 0)
        if lights > light_budget:
            tips.append(f"Cell ({h['row']},{h['col']}) has {lights} lights (> {light_budget}): performance risk, merge or disable shadows.")
        if grid["mean_per_cell"] and h["count"] > 4 * grid["mean_per_cell"] and h["count"] > 20:
            tips.append(f"Dense cluster of {h['count']} actors around ({h['center']['x']}, {h['center']['y']}).")
    if grid["empty_cells"] > cells * cells * 0.4:
        tips.append(f"{grid['empty_cells']} of {cells * cells} cells are empty: consider points of interest, resources or landmarks there.")
    spawners = [p for p in points if p["category"] == "spawner"]
    structures = [p for p in points if p["category"] == "structure"]
    min_gap = float(args.get("spawn_clearance", 1500.0))
    for s in spawners[:200]:
        close = [t for t in structures if math.hypot(t["x"] - s["x"], t["y"] - s["y"]) < min_gap]
        if len(close) > 10:
            tips.append(f"Spawner '{s['label']}' has {len(close)} structures within {min_gap / 100:.0f} m: check NPC navigation and spawn safety.")
    return {"bounds": {"min_x": bounds[0], "min_y": bounds[1], "max_x": bounds[2], "max_y": bounds[3]},
            "totals_by_category": totals, "density": grid, "recommendations": tips[:30]}


def register(registry):
    registry.register("sample_terrain", "Mapping",
                      "Ground height, normal and slope at points or on a grid (line traces; includes structures on top of the landscape).",
                      {"properties": {"points": {"type": "array", "items": {"type": "object"}, "maxItems": 2000},
                                      "area": AREA, "resolution": {"type": "integer", "minimum": 2, "maximum": 128}}},
                      READ_ONLY, tool_sample_terrain)
    registry.register("analyze_terrain", "Mapping",
                      "Terrain statistics for an area: height range, slope histogram, walkable %, largest flat build sites and recommendations.",
                      {"properties": {"area": AREA, "resolution": {"type": "integer", "minimum": 4, "maximum": 128},
                                      "flat_max_slope": {"type": "number"}, "min_flat_cells": {"type": "integer", "minimum": 1},
                                      "water_level": {"type": "number", "description": "World Z of the water surface, if any"}}},
                      READ_ONLY, tool_analyze_terrain)
    registry.register("get_map_layout", "Mapping",
                      "Actor density grid by category (structures, spawners, resources, lights...), hotspots, empty zones and layout recommendations.",
                      {"properties": {"area": AREA, "cells": {"type": "integer", "minimum": 2, "maximum": 32},
                                      "max_lights_per_cell": {"type": "integer"}, "spawn_clearance": {"type": "number"}}},
                      READ_ONLY, tool_get_map_layout)
