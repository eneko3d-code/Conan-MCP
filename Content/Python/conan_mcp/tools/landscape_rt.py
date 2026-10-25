"""Render-target landscape backend: read/write heights (and layer weights) without any C++.

Uses only engine Python APIs available in the Conan DevKit:
  LandscapeProxy.landscape_export_heightmap_to_render_target / landscape_import_heightmap_from_render_target /
  landscape_import_weightmap_from_render_target, RenderingLibrary.create_render_target2d / read_render_target_raw /
  import_buffer_as_texture2d / begin_draw_canvas_to_render_target.

Heights travel in Unreal's RG encoding (R = high byte, G = low byte) through RGBA8 targets, which is exact for
16-bit heights. Every write keeps a PNG backup of the whole landscape and is verified by re-exporting; if the
round-trip is not exact the backup is restored automatically.
"""

import os
import re
import time

from ..core import ue
from ..mapping.heightmap import (HeightGrid, LandscapeTransform, decode_png16, encode_png16, encode_png_rgba8,
                                 mask_rgba, pack_rg, unpack_rg)

LANDSCAPE_CLASSES = ("Landscape", "LandscapeProxy", "LandscapeStreamingProxy")
BACKUP_DIR = "heightmaps/backups"
MAX_BACKUPS = 20
MAX_PIXELS = 8193 * 8193

READ_APIS = ("LandscapeProxy.landscape_export_heightmap_to_render_target", "RenderingLibrary.create_render_target2d",
             "RenderingLibrary.read_render_target_raw")
WRITE_APIS = ("LandscapeProxy.landscape_import_heightmap_from_render_target", "RenderingLibrary.import_buffer_as_texture2d",
              "RenderingLibrary.begin_draw_canvas_to_render_target", "RenderingLibrary.end_draw_canvas_to_render_target")
PAINT_APIS = ("LandscapeProxy.landscape_import_weightmap_from_render_target",)


class RoundTripError(RuntimeError):
    pass


def supported() -> bool:
    return all(ue.has(a) for a in READ_APIS + WRITE_APIS)


def paint_supported() -> bool:
    return supported() and all(ue.has(a) for a in PAINT_APIS)


def missing_apis():
    return [a for a in READ_APIS + WRITE_APIS + PAINT_APIS if not ue.has(a)]


# ---------------------------------------------------------------------------
# Layout: the whole landscape (main actor + streaming proxies) as one pixel grid
# ---------------------------------------------------------------------------

def _guid(actor):
    try:
        return str(actor.get_editor_property("landscape_guid"))
    except Exception:
        return None


def layout(label=None) -> dict:
    """Grid that the render target covers: pixel (0,0) = world min corner of the landscape, 1 px per quad."""
    actors = [a for a in ue.all_actors() if ue.class_name(a) in LANDSCAPE_CLASSES]
    if not actors:
        raise ValueError("No Landscape or LandscapeStreamingProxy in the current level")
    target = None
    if label:
        target = next((a for a in actors if ue.actor_label(a).lower() == label.lower() or a.get_name().lower() == label.lower()), None)
        if target is None:
            raise ValueError(f"Landscape '{label}' not found. Available: {[ue.actor_label(a) for a in actors]}")
    else:
        target = next((a for a in actors if ue.class_name(a) == "Landscape"), actors[0])
    guid = _guid(target)
    group = [a for a in actors if guid is None or _guid(a) in (guid, None)]
    scale = target.get_actor_scale3d()
    sx, sy = max(float(scale.x), 1e-6), max(float(scale.y), 1e-6)
    boxes = []
    for a in group:
        origin, extent = ue.actor_bounds(a)
        if extent.x < sx * 0.5 and extent.y < sy * 0.5:
            continue  # e.g. a World Partition main Landscape actor without components
        boxes.append((origin.x - extent.x, origin.y - extent.y, origin.x + extent.x, origin.y + extent.y))
    if not boxes:
        raise ValueError("The landscape has no loaded components (load its World Partition cells first)")
    minx, miny = min(b[0] for b in boxes), min(b[1] for b in boxes)
    maxx, maxy = max(b[2] for b in boxes), max(b[3] for b in boxes)
    width = int(round((maxx - minx) / sx)) + 1
    height = int(round((maxy - miny) / sy)) + 1
    if width * height > MAX_PIXELS:
        raise ValueError(f"Landscape is {width}x{height}: too large for the render-target backend")
    main = next((a for a in group if ue.class_name(a) == "Landscape"), target)
    return {
        "actor": main, "label": ue.actor_label(main), "class": ue.class_name(main),
        "members": [ue.actor_label(a) for a in group],
        "origin": (minx, miny, float(main.get_actor_location().z)),
        "scale": (sx, sy, float(scale.z)), "width": width, "height": height,
    }


def transform(lay) -> LandscapeTransform:
    return LandscapeTransform(lay["origin"], lay["scale"])


def describe(lay) -> dict:
    return {k: v for k, v in lay.items() if k != "actor"}


# ---------------------------------------------------------------------------
# Render target I/O
# ---------------------------------------------------------------------------

def _new_rt(width, height):
    u = ue.require()
    return u.RenderingLibrary.create_render_target2d(ue.get_world(), int(width), int(height),
                                                     u.TextureRenderTargetFormat.RTF_RGBA8)


def read_heights(lay) -> HeightGrid:
    u = ue.require()
    rt = _new_rt(lay["width"], lay["height"])
    ok = lay["actor"].landscape_export_heightmap_to_render_target(rt, True, True)
    if ok is False:
        raise RuntimeError("landscape_export_heightmap_to_render_target returned False")
    pixels = list(u.RenderingLibrary.read_render_target_raw(ue.get_world(), rt, False))
    return unpack_rg(pixels, lay["width"], lay["height"])


def _draw_rgba_to_rt(width, height, rgba):
    """Puts exact RGBA8 bytes into a render target (linear, nearest, 1:1)."""
    u = ue.require()
    world = ue.get_world()
    png = encode_png_rgba8(width, height, rgba)
    tex = u.RenderingLibrary.import_buffer_as_texture2d(world, list(png))
    if tex is None:
        raise RuntimeError("import_buffer_as_texture2d failed")
    for prop, value in (("srgb", False), ("filter", getattr(getattr(u, "TextureFilter", None), "TF_NEAREST", None))):
        if value is None:
            continue
        try:
            tex.set_editor_property(prop, value)
        except Exception:
            pass
    if hasattr(tex, "update_resource"):
        tex.update_resource()
    rt = _new_rt(width, height)
    canvas, _size, ctx = u.RenderingLibrary.begin_draw_canvas_to_render_target(world, rt)
    try:
        canvas.draw_texture(tex, u.Vector2D(0.0, 0.0), u.Vector2D(float(width), float(height)), u.Vector2D(0.0, 0.0),
                            u.Vector2D(1.0, 1.0), u.LinearColor(1.0, 1.0, 1.0, 1.0), u.BlendMode.BLEND_OPAQUE, 0.0,
                            u.Vector2D(0.0, 0.0))
    finally:
        u.RenderingLibrary.end_draw_canvas_to_render_target(world, ctx)
    return rt


def _import_heights(lay, grid: HeightGrid):
    if (grid.width, grid.height) != (lay["width"], lay["height"]):
        raise ValueError(f"Heightmap is {grid.width}x{grid.height}, landscape needs {lay['width']}x{lay['height']}")
    rt = _draw_rgba_to_rt(grid.width, grid.height, pack_rg(grid))
    with ue.transaction("ConanMCP: Sculpt landscape"):
        try:
            lay["actor"].modify()
        except Exception:
            pass
        ok = lay["actor"].landscape_import_heightmap_from_render_target(rt, True)
    if ok is False:
        raise RuntimeError("landscape_import_heightmap_from_render_target returned False")


def compare(expected: HeightGrid, actual: HeightGrid) -> dict:
    diff = [abs(a - b) for a, b in zip(expected.data, actual.data) if a != b]
    return {"altered_heights": len(diff), "max_abs_diff_units": max(diff) if diff else 0}


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

def _safe_label(label):
    return re.sub(r"[^A-Za-z0-9_\-]", "_", label)[:40] or "Landscape"


def backup(lay, grid: HeightGrid) -> str:
    name = f"{_safe_label(lay['label'])}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.png"
    path = ue.safe_file(name, BACKUP_DIR)
    with open(path, "wb") as f:
        f.write(encode_png16(grid))
    prefix = _safe_label(lay["label"]) + "_"
    folder = os.path.dirname(path)
    mine = sorted((f for f in os.listdir(folder) if f.startswith(prefix) and f.endswith(".png")),
                  key=lambda f: os.path.getmtime(os.path.join(folder, f)))
    for old in mine[:-MAX_BACKUPS]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass
    return path


def list_backups(label=None):
    folder = ue.saved_dir(BACKUP_DIR)
    prefix = _safe_label(label) + "_" if label else ""
    items = []
    for f in os.listdir(folder):
        if f.endswith(".png") and f.startswith(prefix):
            p = os.path.join(folder, f)
            items.append({"file_name": f, "bytes": os.path.getsize(p),
                          "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))})
    return sorted(items, key=lambda i: i["modified"], reverse=True)


def load_backup(file_name) -> HeightGrid:
    with open(ue.safe_file(file_name, BACKUP_DIR), "rb") as f:
        return decode_png16(f.read())


# ---------------------------------------------------------------------------
# Safe write: backup -> import -> verify -> auto-restore on mismatch
# ---------------------------------------------------------------------------

def safe_write(lay, new: HeightGrid, before: HeightGrid, verify=True) -> dict:
    timings = {}
    t0 = time.time()
    backup_path = backup(lay, before)
    timings["backup_s"] = round(time.time() - t0, 3)
    t0 = time.time()
    _import_heights(lay, new)
    timings["write_s"] = round(time.time() - t0, 3)
    result = {"backup": os.path.basename(backup_path), "timings": timings, "verified": False}
    if verify:
        t0 = time.time()
        after = read_heights(lay)
        timings["verify_s"] = round(time.time() - t0, 3)
        cmp = compare(new, after)
        if cmp["altered_heights"]:
            _import_heights(lay, before)
            restored = compare(before, read_heights(lay))
            if restored["altered_heights"]:
                how = (f"Automatic restore ALSO failed ({restored['altered_heights']} differences): press Ctrl+Z, or import "
                       f"'{backup_path}' in Landscape mode (Manage > Import > Heightmap).")
            else:
                how = f"The landscape was restored exactly from backup '{os.path.basename(backup_path)}'."
            raise RoundTripError(
                f"Render-target round-trip is not exact on this DevKit ({cmp['altered_heights']} heights differ, "
                f"max {cmp['max_abs_diff_units']} units). {how} Use the heightmap_file workflow instead.")
        result["verified"] = True
    return result


def write_weights(lay, layer: str, weights) -> None:
    u = ue.require()
    rt = _draw_rgba_to_rt(lay["width"], lay["height"], mask_rgba(lay["width"], lay["height"], weights))
    name = u.Name(layer) if hasattr(u, "Name") else layer
    with ue.transaction(f"ConanMCP: Paint layer {layer}"):
        try:
            lay["actor"].modify()
        except Exception:
            pass
        ok = lay["actor"].landscape_import_weightmap_from_render_target(rt, name)
    if ok is False:
        raise RuntimeError("landscape_import_weightmap_from_render_target returned False (does the layer exist?)")
