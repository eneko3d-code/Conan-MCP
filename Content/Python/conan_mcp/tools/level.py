"""Level & actor tools: identify, place, move, duplicate, remove and validate structures."""

import json
import math
import random

from ..core import config, ue
from ..core.security import READ_ONLY, SAFE_WRITE
from ..mapping.classify import CATEGORIES, classify, is_protected
from ..mapping.placement import bbox_overlaps, evaluate_placement, path_points, scatter_points

# ---------------------------------------------------------------------------
# Shared schema fragments
# ---------------------------------------------------------------------------

VEC = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}}
ROT = {"type": "object", "properties": {"pitch": {"type": "number"}, "yaw": {"type": "number"}, "roll": {"type": "number"}}}
AREA = {
    "type": "object",
    "description": "Area filter: {center:{x,y,z?}, radius} (sphere/cylinder) or {min:{x,y,z?}, max:{x,y,z?}} (box). Z optional.",
    "properties": {"center": VEC, "radius": {"type": "number"}, "min": VEC, "max": VEC},
}
FILTERS = {
    "class_filter": {"type": "string", "description": "Substring of the actor class name"},
    "name_filter": {"type": "string", "description": "Substring of the actor name or label"},
    "category": {"type": "string", "enum": list(CATEGORIES)},
    "folder": {"type": "string", "description": "Outliner folder prefix"},
    "tag": {"type": "string"},
    "area": AREA,
}
DRY_RUN = {"type": "boolean", "default": False, "description": "Preview the change without modifying the level"}


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

def _in_area(loc, area) -> bool:
    if not area:
        return True
    if "center" in area and area.get("radius") is not None:
        c = area["center"]
        dx, dy = loc.x - float(c.get("x", 0)), loc.y - float(c.get("y", 0))
        if "z" in c:
            return math.sqrt(dx * dx + dy * dy + (loc.z - float(c["z"])) ** 2) <= float(area["radius"])
        return math.hypot(dx, dy) <= float(area["radius"])
    if "min" in area and "max" in area:
        mn, mx = area["min"], area["max"]
        for axis in ("x", "y", "z"):
            if axis in mn and getattr(loc, axis) < float(mn[axis]):
                return False
            if axis in mx and getattr(loc, axis) > float(mx[axis]):
                return False
        return True
    raise ValueError("area needs {center, radius} or {min, max}")


def select(args, actors=None):
    """Actors matching explicit names and/or the filter arguments."""
    actors = actors if actors is not None else ue.all_actors()
    names = args.get("actors") or []
    if names:
        found, missing = ue.find_actors(names, actors)
        if missing:
            raise ValueError(f"Actors not found: {', '.join(map(str, missing[:20]))}")
        pool = found
    else:
        pool = actors
    cls_f = (args.get("class_filter") or "").lower()
    name_f = (args.get("name_filter") or "").lower()
    cat = args.get("category") or ""
    folder = args.get("folder") or ""
    tag = args.get("tag") or ""
    area = args.get("area")
    out = []
    for a in pool:
        cname = ue.class_name(a)
        label = ue.actor_label(a)
        if cls_f and cls_f not in cname.lower():
            continue
        if name_f and name_f not in label.lower() and name_f not in a.get_name().lower():
            continue
        if cat and classify(cname, label) != cat:
            continue
        if folder and not ue.actor_folder(a).startswith(folder):
            continue
        if tag and tag not in ue.actor_tags(a):
            continue
        if area and not _in_area(a.get_actor_location(), area):
            continue
        out.append(a)
    return out


def _has_filter(args) -> bool:
    return bool(args.get("actors")) or any(args.get(k) for k in FILTERS)


def _limit_check(actors, args):
    limit = min(int(args.get("max_count", 50)), config.MAX_ACTORS_PER_WRITE)
    if len(actors) > limit:
        raise ValueError(f"{len(actors)} actors match, more than max_count={limit}. Narrow the filter or raise max_count "
                         f"(hard limit {config.MAX_ACTORS_PER_WRITE}).")


def _ground(x, y, ignore=None, top=None):
    """Ground hit below (x, y): native C++ trace when available, else a Python line trace."""
    top = float(top if top is not None else 200000.0)
    lib = ue.native()
    if lib and hasattr(lib, "trace_ground_json") and not ignore:
        try:
            raw = lib.trace_ground_json(float(x), float(y), top, -200000.0)
            return json.loads(raw) if raw else None
        except Exception:
            pass
    return ue.trace_down(x, y, z_top=top, ignore=ignore)


def _align_rotation(base_yaw: float, normal: dict, base_rot=None):
    """Pitch/roll that align the actor's up vector with the ground normal, keeping yaw."""
    nx, ny, nz = normal["x"], normal["y"], normal["z"]
    yaw = math.radians(base_yaw)
    # Normal expressed in the actor's yaw frame
    fx = nx * math.cos(yaw) + ny * math.sin(yaw)
    fy = -nx * math.sin(yaw) + ny * math.cos(yaw)
    pitch = -math.degrees(math.atan2(fx, nz))
    roll = math.degrees(math.atan2(fy, nz))
    return {"pitch": pitch, "yaw": base_yaw, "roll": roll}


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

def tool_classify_level_actors(args):
    ue.require()
    actors = select(args)
    summary = {c: 0 for c in CATEGORIES}
    examples = {}
    include = int(args.get("examples_per_category", 5))
    for a in actors:
        cat = classify(ue.class_name(a), ue.actor_label(a))
        summary[cat] += 1
        ex = examples.setdefault(cat, [])
        if len(ex) < include:
            ex.append(ue.actor_summary(a))
    return {
        "total_actors": len(actors),
        "by_category": {k: v for k, v in summary.items() if v},
        "examples": examples,
        "note": "Categories are heuristics based on class and label names; check examples before bulk edits.",
    }


def tool_find_actors_in_area(args):
    ue.require()
    actors = select(args)
    offset = max(int(args.get("offset", 0)), 0)
    limit = min(max(int(args.get("limit", 100)), 1), 500)
    page = actors[offset:offset + limit]
    with_bounds = bool(args.get("include_bounds", False))
    rows = []
    for a in page:
        row = ue.actor_summary(a, with_bounds=with_bounds)
        row["category"] = classify(row["class"], row["label"])
        rows.append(row)
    return {"total_matching": len(actors), "offset": offset, "returned": len(rows),
            "has_more": offset + len(rows) < len(actors), "actors": rows}


DEFAULT_PROPS = ("hidden", "actor_hidden_in_game", "mobility", "tags", "can_be_damaged")


def tool_get_actor_properties(args):
    actor = ue.require_actor(args.get("actor", ""))
    target = actor
    comp_name = args.get("component")
    if comp_name:
        target = _find_component(actor, comp_name)
    props = args.get("properties") or list(DEFAULT_PROPS)
    values, errors = {}, {}
    for p in props:
        try:
            values[p] = ue.to_json_value(target.get_editor_property(p))
        except Exception as e:
            errors[p] = str(e)
    return {"actor": ue.actor_label(actor), "component": comp_name, "properties": values, "errors": errors,
            "summary": ue.actor_summary(actor, with_bounds=True)}


def _find_component(actor, name):
    u = ue.require()
    for comp in actor.get_components_by_class(u.ActorComponent):
        if comp.get_name().lower() == name.lower():
            return comp
    raise ValueError(f"Component '{name}' not found on '{ue.actor_label(actor)}'")


def tool_validate_placement(args):
    """Detects floating, buried, steep-ground and overlapping actors."""
    ue.require()
    actors = select(args)
    if not _has_filter(args):
        actors = [a for a in actors if classify(ue.class_name(a), ue.actor_label(a)) in ("structure", "static_mesh", "blueprint", "resource")]
    max_check = min(int(args.get("max_count", 300)), 1000)
    actors = actors[:max_check]
    tol = float(args.get("float_tolerance", 30.0))
    max_slope = float(args.get("max_slope", 35.0))
    issues, boxes = [], []
    for a in actors:
        origin, extent = ue.actor_bounds(a)
        bottom = origin.z - extent.z
        hit = _ground(origin.x, origin.y, ignore=[a], top=origin.z + extent.z + 5000.0)
        ground_z = hit["location"]["z"] if hit else None
        slope = hit["slope_deg"] if hit else None
        found = evaluate_placement(bottom, extent.z, ground_z, slope, tol, 0.5, max_slope)
        if found:
            issues.append({"actor": ue.actor_label(a), "class": ue.class_name(a), "issues": found,
                           "bottom_z": round(bottom, 1), "ground_z": ground_z, "ground_slope": slope})
        boxes.append({"id": ue.actor_label(a),
                      "min": (origin.x - extent.x, origin.y - extent.y, origin.z - extent.z),
                      "max": (origin.x + extent.x, origin.y + extent.y, origin.z + extent.z)})
    overlaps = bbox_overlaps(boxes, float(args.get("min_overlap_ratio", 0.5))) if args.get("check_overlaps", True) else []
    return {
        "checked": len(actors),
        "issues_found": len(issues),
        "issues": issues[:200],
        "overlapping_pairs": [{"a": a, "b": b, "overlap_ratio": r} for a, b, r in overlaps[:100]],
        "hint": "Fix floating/buried actors with snap_actors_to_ground; review overlaps visually with capture_map_overview.",
    }


# ---------------------------------------------------------------------------
# Write tools
# ---------------------------------------------------------------------------

def _set_folder(actor, folder):
    if folder:
        try:
            actor.set_folder_path(folder)
        except Exception:
            pass


def _apply_spec(actor, spec):
    if spec.get("scale") is not None:
        actor.set_actor_scale3d(ue.vec(spec["scale"], (1.0, 1.0, 1.0)))
    if spec.get("label"):
        actor.set_actor_label(str(spec["label"]))
    _set_folder(actor, spec.get("folder") or "ConanMCP")
    if spec.get("tags"):
        u = ue.require()
        try:
            actor.set_editor_property("tags", [u.Name(t) for t in spec["tags"]])
        except Exception:
            pass


def _resolve_spawn_source(spec):
    u = ue.require()
    if spec.get("asset_path"):
        asset = ue.load_asset(spec["asset_path"])
        if hasattr(asset, "generated_class") and isinstance(asset, getattr(u, "Blueprint", ())):
            return "class", asset.generated_class()
        return "object", asset
    if spec.get("class_name"):
        return "class", ue.resolve_class(spec["class_name"])
    raise ValueError("Each spawn needs 'asset_path' (StaticMesh/Blueprint/...) or 'class_name'")


def _spawn_one(spec, dry_run=False):
    u = ue.require()
    loc = dict(spec.get("location") or {})
    rotation = dict(spec.get("rotation") or {})
    ground = None
    if spec.get("snap_to_ground"):
        ground = _ground(float(loc.get("x", 0)), float(loc.get("y", 0)))
        if ground is None:
            raise ValueError(f"No ground found below ({loc.get('x', 0)}, {loc.get('y', 0)})")
        loc["z"] = ground["location"]["z"] + float(spec.get("ground_offset", 0.0))
        if spec.get("align_to_ground"):
            rotation = _align_rotation(float(rotation.get("yaw", 0.0)), ground["normal"])
    plan = {"location": {k: round(float(v), 2) for k, v in loc.items()}, "rotation": rotation,
            "source": spec.get("asset_path") or spec.get("class_name"),
            "ground_slope": ground["slope_deg"] if ground else None}
    if dry_run:
        return plan
    kind, src = _resolve_spawn_source(spec)
    sub = ue.actor_subsystem()
    location, rot = ue.vec(loc), ue.rot(rotation)
    if sub is not None:
        actor = (sub.spawn_actor_from_object(src, location, rot) if kind == "object"
                 else sub.spawn_actor_from_class(src, location, rot))
    else:
        actor = (u.EditorLevelLibrary.spawn_actor_from_object(src, location, rot) if kind == "object"
                 else u.EditorLevelLibrary.spawn_actor_from_class(src, location, rot))
    if actor is None:
        raise RuntimeError(f"Spawn failed for {plan['source']}")
    _apply_spec(actor, spec)
    if spec.get("snap_to_ground") and spec.get("bottom_to_ground", True):
        _snap(actor, float(spec.get("ground_offset", 0.0)), align=False)
    out = ue.actor_summary(actor)
    out["ground_slope"] = plan["ground_slope"]
    return out


def tool_spawn_actor(args):
    dry = bool(args.get("dry_run"))
    if dry:
        return {"dry_run": True, "would_spawn": _spawn_one(args, True)}
    with ue.transaction("ConanMCP: Spawn actor"):
        return {"spawned": _spawn_one(args)}


def tool_spawn_actors_batch(args):
    specs = args.get("actors") or []
    if not specs:
        raise ValueError("'actors' must be a non-empty list of spawn specs")
    if len(specs) > config.MAX_ACTORS_PER_WRITE:
        raise ValueError(f"At most {config.MAX_ACTORS_PER_WRITE} actors per call")
    defaults = {k: v for k, v in args.items() if k not in ("actors", "dry_run")}
    dry = bool(args.get("dry_run"))
    results, errors = [], []
    ctx = ue.transaction(f"ConanMCP: Spawn {len(specs)} actors") if not dry else _null()
    with ctx:
        for i, spec in enumerate(specs):
            try:
                results.append(_spawn_one({**defaults, **spec}, dry))
            except Exception as e:
                errors.append({"index": i, "error": str(e)})
    return {"dry_run": dry, "count": len(results), "results": results, "errors": errors}


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def tool_scatter_actors(args):
    """Scatter assets over an area following terrain rules (spacing, slope, height range)."""
    ue.require()
    sources = args.get("asset_paths") or ([args["asset_path"]] if args.get("asset_path") else [])
    if not sources and not args.get("class_name"):
        raise ValueError("Provide asset_paths (list) or asset_path or class_name")
    count = int(args.get("count", 10))
    if count > config.MAX_ACTORS_PER_WRITE:
        raise ValueError(f"count must be <= {config.MAX_ACTORS_PER_WRITE}")
    area = args.get("area") or {}
    rng = random.Random(int(args.get("seed", 1)))
    if "center" in area and area.get("radius"):
        c = area["center"]
        cx, cy, r = float(c.get("x", 0)), float(c.get("y", 0)), float(area["radius"])
        candidates = scatter_points(rng, (cx - r, cy - r, cx + r, cy + r), count * 3,
                                    float(args.get("min_distance", 0)), center=(cx, cy), radius=r)
    elif "min" in area and "max" in area:
        mn, mx = area["min"], area["max"]
        candidates = scatter_points(rng, (float(mn["x"]), float(mn["y"]), float(mx["x"]), float(mx["y"])), count * 3,
                                    float(args.get("min_distance", 0)))
    else:
        raise ValueError("area must be {center, radius} or {min, max}")
    max_slope = float(args.get("max_slope", 30.0))
    zmin, zmax = args.get("min_height"), args.get("max_height")
    yaw_rand = bool(args.get("random_yaw", True))
    smin, smax = float(args.get("scale_min", 1.0)), float(args.get("scale_max", 1.0))
    accepted, rejected = [], {"slope": 0, "height": 0, "no_ground": 0}
    for x, y in candidates:
        if len(accepted) >= count:
            break
        hit = _ground(x, y)
        if hit is None:
            rejected["no_ground"] += 1
            continue
        if hit["slope_deg"] > max_slope:
            rejected["slope"] += 1
            continue
        z = hit["location"]["z"]
        if (zmin is not None and z < float(zmin)) or (zmax is not None and z > float(zmax)):
            rejected["height"] += 1
            continue
        s = rng.uniform(smin, smax)
        yaw = rng.uniform(0, 360) if yaw_rand else 0.0
        rotation = _align_rotation(yaw, hit["normal"]) if args.get("align_to_ground") else {"pitch": 0, "yaw": yaw, "roll": 0}
        spec = {"location": {"x": x, "y": y, "z": z + float(args.get("ground_offset", 0.0))},
                "rotation": rotation, "scale": {"x": s, "y": s, "z": s},
                "folder": args.get("folder") or "ConanMCP/Scatter",
                "label": f"{args.get('label_prefix', 'Scatter')}_{len(accepted) + 1:03d}"}
        if sources:
            spec["asset_path"] = sources[rng.randrange(len(sources))]
        else:
            spec["class_name"] = args["class_name"]
        accepted.append(spec)
    if args.get("dry_run"):
        return {"dry_run": True, "planned": len(accepted), "rejected": rejected,
                "points": [{"location": s["location"], "source": s.get("asset_path") or s.get("class_name")} for s in accepted]}
    spawned = []
    with ue.transaction(f"ConanMCP: Scatter {len(accepted)} actors"):
        for spec in accepted:
            spawned.append(_spawn_one(spec))
    return {"spawned": len(spawned), "requested": count, "rejected": rejected, "actors": spawned}


def tool_place_actors_along_path(args):
    pts = [(float(p["x"]), float(p["y"])) for p in args.get("path") or []]
    spacing = float(args.get("spacing", 500.0))
    rng = random.Random(int(args.get("seed", 1)))
    placements = path_points(pts, spacing, float(args.get("jitter", 0.0)), rng)
    if len(placements) > config.MAX_ACTORS_PER_WRITE:
        raise ValueError(f"Path would place {len(placements)} actors (> {config.MAX_ACTORS_PER_WRITE}); increase spacing")
    yaw_offset = float(args.get("yaw_offset", 0.0))
    specs = []
    for i, (x, y, yaw) in enumerate(placements):
        spec = {"location": {"x": x, "y": y, "z": float(args.get("z", 0.0))},
                "rotation": {"pitch": 0, "yaw": (yaw + yaw_offset) if args.get("face_path", True) else yaw_offset, "roll": 0},
                "snap_to_ground": args.get("snap_to_ground", True), "align_to_ground": args.get("align_to_ground", False),
                "folder": args.get("folder") or "ConanMCP/Path", "label": f"{args.get('label_prefix', 'PathItem')}_{i + 1:03d}"}
        if args.get("asset_path"):
            spec["asset_path"] = args["asset_path"]
        else:
            spec["class_name"] = args.get("class_name")
        specs.append(spec)
    return tool_spawn_actors_batch({"actors": specs, "dry_run": args.get("dry_run", False)})


def tool_duplicate_actors(args):
    actors = select(args)
    if not actors:
        raise ValueError("No actors matched")
    _limit_check(actors, args)
    offset = ue.vec(args.get("offset"), (0.0, 0.0, 0.0))
    if args.get("dry_run"):
        return {"dry_run": True, "would_duplicate": [ue.actor_label(a) for a in actors]}
    sub = ue.actor_subsystem()
    with ue.transaction(f"ConanMCP: Duplicate {len(actors)} actors"):
        if sub is not None and hasattr(sub, "duplicate_actors"):
            new = list(sub.duplicate_actors(actors, None, offset))
        else:
            new = [ue.require().EditorLevelLibrary.duplicate_actor(a, None, offset) for a in actors]
        for a in new:
            _set_folder(a, args.get("folder"))
    return {"duplicated": [ue.actor_summary(a) for a in new if a is not None]}


def tool_delete_actors(args):
    if not _has_filter(args):
        raise ValueError("Refusing to delete without 'actors' or at least one filter (class_filter, category, area, ...)")
    actors = select(args)
    allow_protected = bool(args.get("allow_protected", False))
    protected = [a for a in actors if is_protected(ue.class_name(a))]
    if protected and not allow_protected:
        actors = [a for a in actors if not is_protected(ue.class_name(a))]
    _limit_check(actors, args)
    plan = [{"label": ue.actor_label(a), "class": ue.class_name(a),
             "category": classify(ue.class_name(a), ue.actor_label(a))} for a in actors]
    skipped = [ue.actor_label(a) for a in protected] if not allow_protected else []
    if args.get("dry_run"):
        return {"dry_run": True, "would_delete": plan, "count": len(plan), "skipped_protected": skipped}
    sub = ue.actor_subsystem()
    deleted = 0
    with ue.transaction(f"ConanMCP: Delete {len(actors)} actors"):
        if sub is not None and hasattr(sub, "destroy_actors"):
            sub.destroy_actors(actors)
            deleted = len(actors)
        else:
            for a in actors:
                ok = sub.destroy_actor(a) if sub is not None else ue.require().EditorLevelLibrary.destroy_actor(a)
                deleted += 1 if ok is not False else 0
    return {"deleted": deleted, "actors": plan, "skipped_protected": skipped,
            "undo": "Call the 'undo' tool (or Ctrl+Z in the editor) to restore them."}


def tool_set_actor_transform(args):
    actor = ue.require_actor(args.get("actor", ""))
    relative = bool(args.get("relative", False))
    with ue.transaction(f"ConanMCP: Transform {ue.actor_label(actor)}"):
        actor.modify()
        if args.get("location") is not None:
            loc = ue.vec(args["location"])
            if relative:
                cur = actor.get_actor_location()
                loc = ue.vec({"x": cur.x + loc.x, "y": cur.y + loc.y, "z": cur.z + loc.z})
            actor.set_actor_location(loc, False, True)
        if args.get("rotation") is not None:
            r = dict(args["rotation"])
            if relative:
                cur = actor.get_actor_rotation()
                r = {"pitch": cur.pitch + float(r.get("pitch", 0)), "yaw": cur.yaw + float(r.get("yaw", 0)),
                     "roll": cur.roll + float(r.get("roll", 0))}
            actor.set_actor_rotation(ue.rot(r), False)
        if args.get("scale") is not None:
            actor.set_actor_scale3d(ue.vec(args["scale"], (1.0, 1.0, 1.0)))
    return {"updated": ue.actor_summary(actor)}


def tool_set_actor_property(args):
    actor = ue.require_actor(args.get("actor", ""))
    target = _find_component(actor, args["component"]) if args.get("component") else actor
    prop = args.get("property", "")
    if not prop:
        raise ValueError("'property' is required")
    try:
        current = target.get_editor_property(prop)
    except Exception as e:
        raise ValueError(f"Property '{prop}' not readable: {e}")
    value = ue.from_json_value(args.get("value"), current)
    if args.get("dry_run"):
        return {"dry_run": True, "property": prop, "current": ue.to_json_value(current), "new": args.get("value")}
    with ue.transaction(f"ConanMCP: Set {prop} on {ue.actor_label(actor)}"):
        target.modify()
        target.set_editor_property(prop, value)
    return {"actor": ue.actor_label(actor), "property": prop, "old": ue.to_json_value(current),
            "new": ue.to_json_value(target.get_editor_property(prop))}


def _snap(actor, offset=0.0, align=False):
    origin, extent = ue.actor_bounds(actor)
    hit = _ground(origin.x, origin.y, ignore=[actor], top=origin.z + extent.z + 5000.0)
    if hit is None:
        return None
    bottom = origin.z - extent.z
    loc = actor.get_actor_location()
    dz = hit["location"]["z"] + offset - bottom
    actor.set_actor_location(ue.vec({"x": loc.x, "y": loc.y, "z": loc.z + dz}), False, True)
    if align:
        actor.set_actor_rotation(ue.rot(_align_rotation(actor.get_actor_rotation().yaw, hit["normal"])), False)
    return {"actor": ue.actor_label(actor), "moved_z": round(dz, 2), "ground_slope": hit["slope_deg"]}


def tool_snap_actors_to_ground(args):
    if not _has_filter(args):
        raise ValueError("Provide 'actors' or a filter")
    actors = select(args)
    _limit_check(actors, args)
    offset = float(args.get("offset", 0.0))
    align = bool(args.get("align_to_ground", False))
    if args.get("dry_run"):
        return {"dry_run": True, "would_snap": [ue.actor_label(a) for a in actors]}
    results, failed = [], []
    with ue.transaction(f"ConanMCP: Snap {len(actors)} actors to ground"):
        for a in actors:
            a.modify()
            r = _snap(a, offset, align)
            (results if r else failed).append(r or ue.actor_label(a))
    return {"snapped": results, "no_ground_found": failed}


def tool_set_actor_folder(args):
    if not _has_filter(args):
        raise ValueError("Provide 'actors' or a filter")
    actors = select(args)
    _limit_check(actors, args)
    folder = args.get("new_folder", "")
    with ue.transaction("ConanMCP: Set outliner folder"):
        for a in actors:
            a.modify()
            a.set_folder_path(folder)
    return {"moved": len(actors), "folder": folder}


def tool_select_actors(args):
    actors = select(args) if _has_filter(args) else []
    sub = ue.actor_subsystem()
    if sub is not None:
        sub.set_selected_level_actors(actors)
    else:
        ue.require().EditorLevelLibrary.set_selected_level_actors(actors)
    return {"selected": [ue.actor_label(a) for a in actors[:200]], "count": len(actors)}


def tool_focus_viewport(args):
    u = ue.require()
    if args.get("actor"):
        actor = ue.require_actor(args["actor"])
        origin, extent = ue.actor_bounds(actor)
        target = {"x": origin.x, "y": origin.y, "z": origin.z}
        size = max(extent.x, extent.y, extent.z, 100.0)
    elif args.get("location"):
        target = args["location"]
        size = float(args.get("distance", 2000.0)) / 3.0
    else:
        raise ValueError("Provide 'actor' or 'location'")
    dist = float(args.get("distance", size * 3.0))
    pitch = float(args.get("pitch", -35.0))
    yaw = float(args.get("yaw", 45.0))
    pr, yr = math.radians(pitch), math.radians(yaw)
    cam = {"x": float(target["x"]) - dist * math.cos(pr) * math.cos(yr),
           "y": float(target["y"]) - dist * math.cos(pr) * math.sin(yr),
           "z": float(target.get("z", 0)) - dist * math.sin(pr)}
    sub = ue.editor_subsystem("UnrealEditorSubsystem")
    rot = ue.rot({"pitch": pitch, "yaw": yaw, "roll": 0})
    if sub is not None and hasattr(sub, "set_level_viewport_camera_info"):
        sub.set_level_viewport_camera_info(ue.vec(cam), rot)
    else:
        u.EditorLevelLibrary.set_level_viewport_camera_info(ue.vec(cam), rot)
    return {"camera_location": {k: round(v, 1) for k, v in cam.items()}, "camera_rotation": {"pitch": pitch, "yaw": yaw}}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry):
    filt = dict(FILTERS)
    names = {"actors": {"type": "array", "items": {"type": "string"}, "description": "Actor labels/names"}}
    limits = {"max_count": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50}}

    registry.register("classify_level_actors", "Level",
                      "Groups level actors into map categories (structure, spawner, resource, foliage, light, water...) with examples.",
                      {"properties": {**filt, "examples_per_category": {"type": "integer", "minimum": 0, "maximum": 50}}},
                      READ_ONLY, tool_classify_level_actors)
    registry.register("find_actors_in_area", "Level",
                      "Lists actors inside a radius or box, optionally filtered by category/class/name/folder/tag.",
                      {"properties": {**filt, "include_bounds": {"type": "boolean"},
                                      "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}},
                      READ_ONLY, tool_find_actors_in_area)
    registry.register("get_actor_properties", "Level", "Reads editor properties of an actor or one of its components.",
                      {"properties": {"actor": {"type": "string"}, "component": {"type": "string"},
                                      "properties": {"type": "array", "items": {"type": "string"}}}, "required": ["actor"]},
                      READ_ONLY, tool_get_actor_properties)
    registry.register("validate_placement", "Level",
                      "Finds floating, buried, steep-ground and overlapping structures (defaults to structures/meshes/blueprints).",
                      {"properties": {**filt, **names, "max_count": {"type": "integer", "minimum": 1, "maximum": 1000},
                                      "float_tolerance": {"type": "number"}, "max_slope": {"type": "number"},
                                      "check_overlaps": {"type": "boolean"}, "min_overlap_ratio": {"type": "number"}}},
                      READ_ONLY, tool_validate_placement)

    spawn_props = {
        "asset_path": {"type": "string", "description": "StaticMesh, Blueprint or other placeable asset"},
        "class_name": {"type": "string", "description": "Native class, e.g. PointLight, or /Script/... path"},
        "location": VEC, "rotation": ROT, "scale": VEC,
        "snap_to_ground": {"type": "boolean"}, "align_to_ground": {"type": "boolean"},
        "ground_offset": {"type": "number"}, "label": {"type": "string"},
        "folder": {"type": "string", "description": "Outliner folder (default ConanMCP)"},
        "tags": {"type": "array", "items": {"type": "string"}}, "dry_run": DRY_RUN,
    }
    registry.register("spawn_actor", "Level", "Places one asset/class in the level, optionally snapped and aligned to the ground. Undoable.",
                      {"properties": spawn_props}, SAFE_WRITE, tool_spawn_actor, idempotent=False)
    registry.register("spawn_actors_batch", "Level",
                      "Places many actors in one undoable transaction. Top-level fields act as defaults for each spec.",
                      {"properties": {**spawn_props, "actors": {"type": "array", "items": {"type": "object"},
                                                                "maxItems": 1000}}, "required": ["actors"]},
                      SAFE_WRITE, tool_spawn_actors_batch, idempotent=False)
    registry.register("scatter_actors", "Level",
                      "Scatters assets over an area with min spacing, max slope, height range, random yaw/scale (seeded). Use dry_run first.",
                      {"properties": {
                          "asset_paths": {"type": "array", "items": {"type": "string"}}, "asset_path": {"type": "string"},
                          "class_name": {"type": "string"}, "area": AREA,
                          "count": {"type": "integer", "minimum": 1, "maximum": 1000},
                          "min_distance": {"type": "number"}, "max_slope": {"type": "number"},
                          "min_height": {"type": "number"}, "max_height": {"type": "number"},
                          "random_yaw": {"type": "boolean"}, "scale_min": {"type": "number"}, "scale_max": {"type": "number"},
                          "align_to_ground": {"type": "boolean"}, "ground_offset": {"type": "number"},
                          "seed": {"type": "integer"}, "folder": {"type": "string"}, "label_prefix": {"type": "string"},
                          "dry_run": DRY_RUN}, "required": ["area"]},
                      SAFE_WRITE, tool_scatter_actors, idempotent=False)
    registry.register("place_actors_along_path", "Level",
                      "Places an asset every N cm along a polyline (walls, fences, torches, road props), facing the path.",
                      {"properties": {"path": {"type": "array", "items": VEC}, "spacing": {"type": "number"},
                                      "asset_path": {"type": "string"}, "class_name": {"type": "string"},
                                      "jitter": {"type": "number"}, "yaw_offset": {"type": "number"},
                                      "face_path": {"type": "boolean"}, "snap_to_ground": {"type": "boolean"},
                                      "align_to_ground": {"type": "boolean"}, "seed": {"type": "integer"},
                                      "folder": {"type": "string"}, "label_prefix": {"type": "string"}, "dry_run": DRY_RUN},
                       "required": ["path", "spacing"]},
                      SAFE_WRITE, tool_place_actors_along_path, idempotent=False)
    registry.register("duplicate_actors", "Level", "Duplicates actors with an offset. Undoable.",
                      {"properties": {**filt, **names, **limits, "offset": VEC, "folder": {"type": "string"}, "dry_run": DRY_RUN}},
                      SAFE_WRITE, tool_duplicate_actors, idempotent=False)
    registry.register("delete_actors", "Level",
                      "Removes actors by name or filter inside one undoable transaction. Landscape/WorldSettings/foliage are protected. Use dry_run first.",
                      {"properties": {**filt, **names, **limits, "allow_protected": {"type": "boolean"}, "dry_run": DRY_RUN}},
                      SAFE_WRITE, tool_delete_actors, idempotent=False)
    registry.register("set_actor_transform", "Actors",
                      "Sets location/rotation/scale of an actor (absolute or relative). Undoable.",
                      {"properties": {"actor": {"type": "string"}, "location": VEC, "rotation": ROT, "scale": VEC,
                                      "relative": {"type": "boolean"}}, "required": ["actor"]},
                      SAFE_WRITE, tool_set_actor_transform)
    registry.register("set_actor_property", "Level", "Sets an editor property on an actor or component (type inferred from the current value). Undoable.",
                      {"properties": {"actor": {"type": "string"}, "component": {"type": "string"},
                                      "property": {"type": "string"}, "value": {}, "dry_run": DRY_RUN},
                       "required": ["actor", "property"]},
                      SAFE_WRITE, tool_set_actor_property)
    registry.register("snap_actors_to_ground", "Level", "Drops actors so their bounds rest on the ground below (optionally aligned to its normal). Undoable.",
                      {"properties": {**filt, **names, **limits, "offset": {"type": "number"},
                                      "align_to_ground": {"type": "boolean"}, "dry_run": DRY_RUN}},
                      SAFE_WRITE, tool_snap_actors_to_ground)
    registry.register("set_actor_folder", "Level", "Moves actors into an Outliner folder. Undoable.",
                      {"properties": {**filt, **names, **limits, "new_folder": {"type": "string"}}, "required": ["new_folder"]},
                      SAFE_WRITE, tool_set_actor_folder)
    registry.register("select_actors", "Level", "Selects actors in the editor (empty filter clears the selection).",
                      {"properties": {**filt, **names}}, READ_ONLY, tool_select_actors, idempotent=True)
    registry.register("focus_viewport", "Level", "Moves the editor camera to look at an actor or location.",
                      {"properties": {"actor": {"type": "string"}, "location": VEC, "distance": {"type": "number"},
                                      "pitch": {"type": "number"}, "yaw": {"type": "number"}}},
                      READ_ONLY, tool_focus_viewport, idempotent=True)
