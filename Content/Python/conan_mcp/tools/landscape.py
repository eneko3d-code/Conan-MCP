"""Landscape editing: info, sculpting brushes, layer painting and heightmap export/import.

Two backends:
  * native  - the optional C++ library (Source/ConanMCPNative) reads/writes height
              regions in the editor, inside an undoable transaction.
  * file    - pure Python: edit a 16-bit PNG heightmap exported from Landscape mode
              (Saved/ConanMCP/heightmaps) and re-import it from Landscape mode.
"""

import base64
import json
import os
from array import array

from ..core import ue
from ..core.security import READ_ONLY, SAFE_WRITE
from ..mapping.heightmap import (HeightGrid, LandscapeTransform, apply_brush, brush_region, decode_png16,
                                 diff_stats, encode_png16)

MAX_REGION_VERTS = 1024 * 1024
HEIGHTMAP_DIR = "heightmaps"


# ---------------------------------------------------------------------------
# Landscape discovery
# ---------------------------------------------------------------------------

def _python_landscapes():
    out = []
    for a in ue.all_actors():
        cname = ue.class_name(a)
        if cname not in ("Landscape", "LandscapeProxy", "LandscapeStreamingProxy"):
            continue
        loc = a.get_actor_location()
        scale = a.get_actor_scale3d()
        origin, extent = ue.actor_bounds(a)
        info = {
            "label": ue.actor_label(a), "name": a.get_name(), "class": cname,
            "origin": ue.vec_to_dict(loc), "scale": ue.vec_to_dict(scale),
            "bounds": {"min": ue.vec_to_dict(ue.vec({"x": origin.x - extent.x, "y": origin.y - extent.y, "z": origin.z - extent.z})),
                       "max": ue.vec_to_dict(ue.vec({"x": origin.x + extent.x, "y": origin.y + extent.y, "z": origin.z + extent.z}))},
        }
        sx, sy = max(float(scale.x), 1e-6), max(float(scale.y), 1e-6)
        info["extent_quads"] = {
            "min_x": int(round((origin.x - extent.x - loc.x) / sx)), "min_y": int(round((origin.y - extent.y - loc.y) / sy)),
            "max_x": int(round((origin.x + extent.x - loc.x) / sx)), "max_y": int(round((origin.y + extent.y - loc.y) / sy)),
        }
        for prop in ("component_size_quads", "subsection_size_quads", "num_subsections"):
            try:
                info[prop] = int(a.get_editor_property(prop))
            except Exception:
                pass
        try:
            mat = a.get_editor_property("landscape_material")
            info["material"] = mat.get_path_name() if mat else None
        except Exception:
            pass
        out.append(info)
    return out


def landscapes():
    lib = ue.native()
    if lib and hasattr(lib, "get_landscape_info_json"):
        data = json.loads(lib.get_landscape_info_json() or "[]")
        for d in data:
            d["backend"] = "native"
        return data
    data = _python_landscapes()
    for d in data:
        d["backend"] = "python"
    return data


def pick_landscape(label=None):
    items = landscapes()
    if not items:
        raise ValueError("No Landscape actor found in the current level")
    # Prefer the main Landscape actor over streaming proxies
    if label:
        for d in items:
            if d["label"].lower() == label.lower() or d["name"].lower() == label.lower():
                return d
        raise ValueError(f"Landscape '{label}' not found. Available: {[d['label'] for d in items]}")
    main = [d for d in items if d.get("class") == "Landscape"] or items
    return main[0]


def transform_of(info) -> LandscapeTransform:
    o, s = info["origin"], info["scale"]
    return LandscapeTransform((o["x"], o["y"], o["z"]), (s["x"], s["y"], s["z"]))


def tool_get_landscape_info(args):
    ue.require()
    items = landscapes()
    return {"landscapes": items, "count": len(items),
            "editing_backend": "native" if ue.native() else "heightmap_file",
            "heightmap_folder": ue.saved_dir(HEIGHTMAP_DIR),
            "coordinates": "Brush coordinates are world cm. Height units: 1 unit = scale.z/128 cm; 32768 = landscape origin Z."}


# ---------------------------------------------------------------------------
# Native region I/O
# ---------------------------------------------------------------------------

def _native_get_region(label, x0, y0, x1, y1) -> HeightGrid:
    lib = ue.native()
    raw = json.loads(lib.get_height_region_json(label, x0, y0, x1, y1) or "{}")
    if not raw.get("ok"):
        raise RuntimeError(raw.get("error", "Native height read failed"))
    data = array("H")
    data.frombytes(base64.b64decode(raw["data_b64"]))
    return HeightGrid(raw["width"], raw["height"], data, raw["x0"], raw["y0"])


def _native_set_region(label, grid: HeightGrid):
    lib = ue.native()
    payload = base64.b64encode(grid.data.tobytes()).decode("ascii")
    raw = json.loads(lib.set_height_region_json(label, grid.x0, grid.y0, grid.x0 + grid.width - 1,
                                                grid.y0 + grid.height - 1, payload) or "{}")
    if not raw.get("ok"):
        raise RuntimeError(raw.get("error", "Native height write failed"))
    return raw


# ---------------------------------------------------------------------------
# Sculpting
# ---------------------------------------------------------------------------

def _brush_params(args, tr: LandscapeTransform):
    op = args.get("operation", "")
    c = args.get("center") or {}
    cx, cy = tr.world_to_grid(float(c.get("x", 0)), float(c.get("y", 0)))
    radius = float(args.get("radius", 1000.0)) / tr.sx
    params = {
        "amount": tr.cm_to_units(float(args.get("amount", 100.0))),
        "falloff": float(args.get("falloff", 0.5)),
        "falloff_kind": args.get("falloff_kind", "smooth"),
        "iterations": int(args.get("iterations", 3)),
        "seed": int(args.get("seed", 0)),
        "noise_scale": max(float(args.get("noise_scale", 2000.0)) / tr.sx, 1.0),
    }
    if args.get("target_z") is not None:
        params["target"] = tr.z_to_height(float(args["target_z"]))
    extra = 0.0
    if op == "ramp":
        e = args.get("end") or {}
        if "z" not in e:
            raise ValueError("ramp needs end {x, y, z} (world cm)")
        ex, ey = tr.world_to_grid(float(e["x"]), float(e["y"]))
        params["end"] = (ex, ey, tr.z_to_height(float(e["z"])))
        if args.get("start_z") is not None:
            params["start_height"] = tr.z_to_height(float(args["start_z"]))
        extra = max(abs(ex - cx), abs(ey - cy))
    return op, cx, cy, radius, extra, params


def _region_for(cx, cy, radius, extra, params, op):
    if op == "ramp":
        ex, ey, _ = params["end"]
        x0, y0 = int(min(cx, ex) - radius) - 1, int(min(cy, ey) - radius) - 1
        x1, y1 = int(max(cx, ex) + radius) + 1, int(max(cy, ey) + radius) + 1
        return x0, y0, x1, y1
    return brush_region(cx, cy, radius + (1 if op == "smooth" else 0))


def _clamp_region(region, info):
    ext = info.get("extent_quads")
    x0, y0, x1, y1 = region
    if ext:
        x0, y0 = max(x0, ext["min_x"]), max(y0, ext["min_y"])
        x1, y1 = min(x1, ext["max_x"]), min(y1, ext["max_y"])
    if x1 < x0 or y1 < y0:
        raise ValueError("The brush is outside the landscape")
    if (x1 - x0 + 1) * (y1 - y0 + 1) > MAX_REGION_VERTS:
        raise ValueError("Brush region too large (> 1M vertices); use a smaller radius or several strokes")
    return x0, y0, x1, y1


def _stats_cm(stats, tr):
    return {**stats,
            "min_delta_cm": round(tr.units_to_cm(stats["min_delta_units"]), 2),
            "max_delta_cm": round(tr.units_to_cm(stats["max_delta_units"]), 2),
            "mean_delta_cm": round(tr.units_to_cm(stats["mean_delta_units"]), 2)}


def tool_sculpt_terrain(args):
    ue.require()
    info = pick_landscape(args.get("landscape"))
    tr = transform_of(info)
    op, cx, cy, radius, extra, params = _brush_params(args, tr)
    mode = args.get("mode", "auto")
    use_native = (mode in ("auto", "native")) and ue.native() is not None and hasattr(ue.native(), "get_height_region_json")
    if mode == "native" and not use_native:
        raise ue.UnsupportedError("Native sculpting needs the ConanMCPNative C++ module (see docs/native_module.md)")
    dry = bool(args.get("dry_run"))

    if use_native and mode != "file":
        region = _clamp_region(_region_for(cx, cy, radius, extra, params, op), info)
        grid = _native_get_region(info["label"], *region)
        stats = apply_brush(grid, op, cx, cy, radius, **params)
        result = {"backend": "native", "operation": op, "region_quads": region, "stats": _stats_cm(stats, tr), "dry_run": dry}
        if not dry and stats["changed_vertices"]:
            _native_set_region(info["label"], grid)
            result["undo"] = "Undo with the 'undo' tool or Ctrl+Z."
        return result

    # Heightmap file workflow
    src_name = args.get("heightmap_file")
    if not src_name:
        raise ue.UnsupportedError(
            "No native sculpting available. Export the heightmap from Landscape mode (Manage > Export > Heightmap, "
            f"16-bit PNG) into '{ue.saved_dir(HEIGHTMAP_DIR)}' and pass heightmap_file='<name>.png'.")
    src = ue.safe_file(src_name, HEIGHTMAP_DIR, ".png")
    with open(src, "rb") as f:
        full = decode_png16(f.read())
    ext = info.get("extent_quads", {"min_x": 0, "min_y": 0})
    # PNG pixel (0,0) is the landscape's extent minimum
    full.x0, full.y0 = ext["min_x"], ext["min_y"]
    region = _region_for(cx, cy, radius, extra, params, op)
    sub = full.crop(*region)
    stats = apply_brush(sub, op, cx, cy, radius, **params)
    result = {"backend": "heightmap_file", "operation": op, "region_quads": region, "stats": _stats_cm(stats, tr), "dry_run": dry}
    if not dry:
        full.paste(sub)
        out_name = args.get("output_file") or src_name
        out = ue.safe_file(out_name, HEIGHTMAP_DIR, ".png")
        with open(out, "wb") as f:
            f.write(encode_png16(full))
        result["written"] = out
        result["next_step"] = ("Re-import in Landscape mode: Manage > Import > Heightmap, select this file "
                               "(keep the same resolution). Chain more strokes on the same file first.")
    return result


# ---------------------------------------------------------------------------
# Painting, export, import (native)
# ---------------------------------------------------------------------------

def _require_native(fn):
    lib = ue.native()
    if lib is None or not hasattr(lib, fn):
        raise ue.UnsupportedError(f"'{fn}' needs the ConanMCPNative C++ module (see docs/native_module.md)")
    return lib


def tool_paint_landscape_layer(args):
    ue.require()
    lib = _require_native("get_weight_region_json")
    info = pick_landscape(args.get("landscape"))
    tr = transform_of(info)
    layer = args.get("layer", "")
    if not layer:
        raise ValueError("'layer' is required (see get_landscape_info layers)")
    c = args.get("center") or {}
    cx, cy = tr.world_to_grid(float(c.get("x", 0)), float(c.get("y", 0)))
    radius = float(args.get("radius", 1000.0)) / tr.sx
    region = _clamp_region(brush_region(cx, cy, radius), info)
    raw = json.loads(lib.get_weight_region_json(info["label"], layer, *region) or "{}")
    if not raw.get("ok"):
        raise RuntimeError(raw.get("error", "Weight read failed"))
    weights = bytearray(base64.b64decode(raw["data_b64"]))
    width = raw["width"]
    strength = max(0.0, min(1.0, float(args.get("strength", 1.0))))
    erase = args.get("mode", "paint") == "erase"
    from ..mapping.heightmap import falloff_weight
    changed = 0
    for i in range(len(weights)):
        x, y = region[0] + i % width, region[1] + i // width
        w = falloff_weight(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5, radius, float(args.get("falloff", 0.5)))
        if w <= 0:
            continue
        target = 0 if erase else 255
        new = int(round(weights[i] + (target - weights[i]) * w * strength))
        if new != weights[i]:
            weights[i] = new
            changed += 1
    if args.get("dry_run"):
        return {"dry_run": True, "layer": layer, "changed_vertices": changed}
    res = json.loads(lib.set_weight_region_json(info["label"], layer, *region,
                                                base64.b64encode(bytes(weights)).decode("ascii")) or "{}")
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "Weight write failed"))
    return {"layer": layer, "changed_vertices": changed, "region_quads": region}


def tool_export_heightmap(args):
    ue.require()
    _require_native("get_height_region_json")
    info = pick_landscape(args.get("landscape"))
    ext = info["extent_quads"]
    grid = _native_get_region(info["label"], ext["min_x"], ext["min_y"], ext["max_x"], ext["max_y"])
    out = ue.safe_file(args.get("file_name") or "heightmap.png", HEIGHTMAP_DIR, ".png")
    with open(out, "wb") as f:
        f.write(encode_png16(grid))
    return {"written": out, "width": grid.width, "height": grid.height, "landscape": info["label"]}


def tool_import_heightmap(args):
    ue.require()
    _require_native("set_height_region_json")
    info = pick_landscape(args.get("landscape"))
    ext = info["extent_quads"]
    path = ue.safe_file(args.get("file_name", ""), HEIGHTMAP_DIR, ".png")
    with open(path, "rb") as f:
        grid = decode_png16(f.read())
    w, h = ext["max_x"] - ext["min_x"] + 1, ext["max_y"] - ext["min_y"] + 1
    if (grid.width, grid.height) != (w, h):
        raise ValueError(f"Heightmap is {grid.width}x{grid.height}, landscape needs {w}x{h}")
    grid.x0, grid.y0 = ext["min_x"], ext["min_y"]
    current = _native_get_region(info["label"], ext["min_x"], ext["min_y"], ext["max_x"], ext["max_y"])
    stats = _stats_cm(diff_stats(current, grid), transform_of(info))
    if args.get("dry_run"):
        return {"dry_run": True, "stats": stats}
    # Write in bands to keep payloads small
    band = max(1, 262144 // w)
    for y in range(ext["min_y"], ext["max_y"] + 1, band):
        _native_set_region(info["label"], grid.crop(ext["min_x"], y, ext["max_x"], min(y + band - 1, ext["max_y"])))
    return {"imported": os.path.basename(path), "stats": stats}


def register(registry):
    vec2 = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}}
    registry.register("get_landscape_info", "Landscape",
                      "Landscape actors with origin, scale, quad extent, components, material/layers and the editing backend available.",
                      {"properties": {}}, READ_ONLY, tool_get_landscape_info)
    registry.register("sculpt_terrain", "Landscape",
                      "Sculpts the landscape with a brush: raise, lower, flatten, smooth, noise or ramp (world cm). "
                      "Native backend edits in-editor (undoable); otherwise edits a 16-bit heightmap PNG. Always dry_run first.",
                      {"properties": {
                          "operation": {"type": "string", "enum": ["raise", "lower", "flatten", "smooth", "noise", "ramp"]},
                          "center": vec2, "radius": {"type": "number", "description": "Brush radius in cm (ramp: half width)"},
                          "amount": {"type": "number", "description": "cm for raise/lower, amplitude for noise"},
                          "target_z": {"type": "number", "description": "flatten: world Z to flatten to (default: height at centre)"},
                          "end": vec2, "start_z": {"type": "number"},
                          "falloff": {"type": "number", "minimum": 0, "maximum": 1},
                          "falloff_kind": {"type": "string", "enum": ["smooth", "linear", "none"]},
                          "iterations": {"type": "integer", "minimum": 1, "maximum": 20},
                          "noise_scale": {"type": "number", "description": "Noise wavelength in cm"},
                          "seed": {"type": "integer"}, "landscape": {"type": "string"},
                          "mode": {"type": "string", "enum": ["auto", "native", "file"]},
                          "heightmap_file": {"type": "string"}, "output_file": {"type": "string"},
                          "dry_run": {"type": "boolean"}},
                       "required": ["operation", "center"]},
                      SAFE_WRITE, tool_sculpt_terrain, idempotent=False)
    registry.register("paint_landscape_layer", "Landscape",
                      "Paints or erases a landscape material layer (grass, sand, rock...) with a soft brush. Native module required.",
                      {"properties": {"layer": {"type": "string"}, "center": vec2, "radius": {"type": "number"},
                                      "strength": {"type": "number", "minimum": 0, "maximum": 1},
                                      "falloff": {"type": "number", "minimum": 0, "maximum": 1},
                                      "mode": {"type": "string", "enum": ["paint", "erase"]},
                                      "landscape": {"type": "string"}, "dry_run": {"type": "boolean"}},
                       "required": ["layer", "center"]},
                      SAFE_WRITE, tool_paint_landscape_layer, idempotent=False)
    registry.register("export_heightmap", "Landscape", "Exports the whole landscape heightmap as a 16-bit PNG into Saved/ConanMCP/heightmaps (native module).",
                      {"properties": {"file_name": {"type": "string"}, "landscape": {"type": "string"}}},
                      READ_ONLY, tool_export_heightmap)
    registry.register("import_heightmap", "Landscape", "Applies a 16-bit PNG from Saved/ConanMCP/heightmaps to the landscape (native module, undoable).",
                      {"properties": {"file_name": {"type": "string"}, "landscape": {"type": "string"}, "dry_run": {"type": "boolean"}},
                       "required": ["file_name"]},
                      SAFE_WRITE, tool_import_heightmap, idempotent=False)
