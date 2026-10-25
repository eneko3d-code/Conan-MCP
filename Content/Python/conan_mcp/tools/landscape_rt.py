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

def _owner(actor):
    """The ALandscape that owns a proxy (itself for a Landscape), or None when not available/loaded."""
    try:
        return actor.get_landscape_actor()
    except Exception:
        return None


def _key(actor):
    owner = _owner(actor) or actor
    try:
        return owner.get_path_name()
    except Exception:
        return id(owner)


def layout(label=None) -> dict:
    """Grid that the render target covers: pixel (0,0) = world min corner of the landscape, 1 px per quad.

    Only actors that belong to the same landscape (same get_landscape_actor()) are grouped, so separate
    landscapes or tiles in one level are never merged into one grid.
    """
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
    key = _key(target)
    group = [a for a in actors if _key(a) == key]
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
    owner = _owner(target)
    main = owner if owner is not None and owner in group else next((a for a in group if ue.class_name(a) == "Landscape"), target)
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


class NotReadyError(RuntimeError):
    """The render-target export did not produce a usable heightmap (yet)."""


class ReadMismatchError(RuntimeError):
    """The exported heights disagree with the real terrain (line traces): nothing was written."""


def read_heights_raw(lay):
    """(HeightGrid, alpha bytes) from one export. No validation."""
    u = ue.require()
    rt = _new_rt(lay["width"], lay["height"])
    ok = lay["actor"].landscape_export_heightmap_to_render_target(rt, True, True)
    if ok is False:
        raise NotReadyError("landscape_export_heightmap_to_render_target returned False")
    pixels = list(u.RenderingLibrary.read_render_target_raw(ue.get_world(), rt, False))
    grid = unpack_rg(pixels, lay["width"], lay["height"])
    scale = 1.0 if any(float(p.a) > 1.0001 for p in pixels[:4096]) else 255.0
    alphas = bytes(min(255, max(0, int(round(float(p.a) * scale)))) for p in pixels)
    return grid, alphas


def validate_read(grid: HeightGrid, alphas: bytes, allow_zero_heights=False):
    """None if the read looks complete, else the reason it is rejected."""
    zeros = grid.data.count(0)
    if zeros == len(grid.data):
        return "every height is 0 (the export has not rendered yet)"
    if zeros and not allow_zero_heights:
        return f"{zeros} heights are exactly 0 (-256 m at scale 100): incomplete export"
    if alphas and max(alphas) > 0:
        holes = alphas.count(0)
        if holes:
            return f"{holes} pixels have alpha 0: incomplete export"
    return None


def read_heights(lay, tries=3, allow_zero_heights=False) -> HeightGrid:
    """Validated read without waiting for new frames (used once the export is known to work)."""
    reason = None
    for _ in range(max(1, tries)):
        grid, alphas = read_heights_raw(lay)
        reason = validate_read(grid, alphas, allow_zero_heights)
        if reason is None:
            return grid
    raise NotReadyError(f"Heightmap read rejected: {reason}")


def ready_heights(lay, then, max_wait_s=10.0, min_interval_s=0.4, allow_zero_heights=False):
    """Deferred: re-exports once per tick (spaced) until the read validates, then returns then(grid, attempts).

    Waiting across ticks lets the editor finish compiling the export shader. Nothing is written when it
    never validates.
    """
    from ..core.results import Deferred
    state = {"attempts": 0, "last": 0.0, "reason": None, "start": time.time()}

    def poll():
        now = time.time()
        if state["attempts"] and now - state["last"] < min_interval_s:
            return False, None
        state["attempts"] += 1
        state["last"] = now
        grid, alphas = read_heights_raw(lay)
        state["reason"] = validate_read(grid, alphas, allow_zero_heights)
        if state["reason"] is None:
            return True, then(grid, state["attempts"])
        if now - state["start"] >= max_wait_s:
            raise NotReadyError(f"Heightmap export still invalid after {state['attempts']} attempts "
                                f"({state['reason']}). Nothing was written; open the level in the viewport and retry.")
        return False, None

    return Deferred(poll, timeout=max_wait_s + 5.0, description="landscape heightmap export")


def trace_points(lay, center=None):
    """Up to 5 grid vertices for line-trace checks: the brush centre plus 4 spread points away from edges."""
    w, h = lay["width"], lay["height"]
    pts = []
    if center is not None:
        pts.append((min(w - 2, max(1, int(round(center[0])))), min(h - 2, max(1, int(round(center[1]))))))
    for fx, fy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
        pts.append((int(w * fx), int(h * fy)))
    seen, out = set(), []
    for p in pts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def trace_check(lay, grid: HeightGrid, points) -> dict:
    """Compares grid heights with line traces on the landscape itself (an independent signal)."""
    from ..core import config
    tol = float(getattr(config, "TRACE_TOLERANCE_CM", 20.0))
    tr = transform(lay)
    members = set(lay["members"])
    rows, worst = [], 0.0
    for gx, gy in points:
        wx, wy = tr.grid_to_world(gx, gy)
        expected = tr.height_to_z(grid.get(gx, gy))
        hit = ue.trace_down(wx, wy)
        if not hit or not str(hit.get("actor_class") or "").startswith("Landscape") or \
                (hit.get("actor_label") and hit["actor_label"] not in members):
            rows.append({"grid": [gx, gy], "comparable": False})
            continue
        diff = abs(hit["location"]["z"] - expected)
        worst = max(worst, diff)
        rows.append({"grid": [gx, gy], "comparable": True, "expected_z": round(expected, 1),
                     "trace_z": round(hit["location"]["z"], 1), "diff_cm": round(diff, 1)})
    comparable = [r for r in rows if r["comparable"]]
    if len(comparable) < 3:
        status = "insufficient"
    else:
        status = "ok" if worst <= tol else "mismatch"
    return {"status": status, "comparable_points": len(comparable), "max_diff_cm": round(worst, 1),
            "tolerance_cm": tol, "points": rows}


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

def safe_write(lay, new: HeightGrid, before: HeightGrid, verify=True, center=None) -> dict:
    """Trace-check the read, back up, import, verify by re-export and by traces; restore on mismatch."""
    timings = {}
    points = trace_points(lay, center)
    pre = trace_check(lay, before, points)
    if pre["status"] == "mismatch":
        raise ReadMismatchError(
            f"The exported heights do not match the real terrain (line traces differ by up to {pre['max_diff_cm']} cm "
            f"> {pre['tolerance_cm']} cm). Nothing was written. Details: {pre['points']}")
    t0 = time.time()
    backup_path = backup(lay, before)
    timings["backup_s"] = round(time.time() - t0, 3)
    t0 = time.time()
    _import_heights(lay, new)
    timings["write_s"] = round(time.time() - t0, 3)
    result = {"backup": os.path.basename(backup_path), "timings": timings, "verified": False,
              "trace_check": pre["status"], "trace_check_details": pre}

    def restore_and_raise(problem):
        _import_heights(lay, before)
        try:
            restored = compare(before, read_heights(lay))["altered_heights"]
        except NotReadyError:
            restored = None
        if restored == 0:
            how = f"The landscape was restored exactly from backup '{os.path.basename(backup_path)}'."
        else:
            how = (f"Automatic restore could not be confirmed ({restored if restored is not None else 'unreadable'}): press "
                   f"Ctrl+Z, or import '{backup_path}' in Landscape mode (Manage > Import > Heightmap).")
        raise RoundTripError(f"{problem} {how} Use the heightmap_file workflow instead.")

    if verify:
        t0 = time.time()
        try:
            after = read_heights(lay)
        except NotReadyError as e:
            result["verified"] = "inconclusive"
            result["warning"] = (f"Could not re-read the landscape to verify ({e}). Nothing was restored automatically; "
                                 f"check it and use restore_heightmap_backup('{os.path.basename(backup_path)}') if needed.")
            return result
        timings["verify_s"] = round(time.time() - t0, 3)
        cmp = compare(new, after)
        if cmp["altered_heights"]:
            restore_and_raise(f"Render-target round-trip is not exact on this DevKit ({cmp['altered_heights']} heights "
                              f"differ, max {cmp['max_abs_diff_units']} units).")
        post = trace_check(lay, new, points)
        result["trace_check_after"] = post["status"]
        if post["status"] == "mismatch":
            restore_and_raise(f"After writing, line traces disagree with the expected heights by up to "
                              f"{post['max_diff_cm']} cm.")
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
