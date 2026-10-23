"""Visual feedback for the AI: viewport screenshots and top-down map captures returned as MCP images."""

import os
import time

from ..core import ue
from ..core.results import ToolResult, wait_for_file
from ..core.security import READ_ONLY

CAPTURE_DIR = "captures"
MAX_IMAGE_BYTES = 6 * 1024 * 1024

_SOURCES = {
    "final": "SCS_FINAL_COLOR_LDR",
    "base_color": "SCS_BASE_COLOR",
    "normal": "SCS_NORMAL",
    "depth": "SCS_SCENE_DEPTH",
}


def _image_result(path, meta):
    size = os.path.getsize(path)
    meta = {**meta, "file": path, "bytes": size}
    if size > MAX_IMAGE_BYTES:
        meta["note"] = "Image too large to inline; open the file instead or lower the resolution."
        return ToolResult(meta)
    with open(path, "rb") as f:
        data = f.read()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return ToolResult(meta, images=[(data, mime)])


def _file_name(args, prefix):
    name = args.get("file_name") or f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    return ue.safe_file(name, CAPTURE_DIR, ".png")


def tool_capture_viewport(args):
    u = ue.require()
    if not ue.has("AutomationLibrary.take_high_res_screenshot"):
        raise ue.UnsupportedError("AutomationLibrary.take_high_res_screenshot is not available in this DevKit")
    w, h = int(args.get("width", 1280)), int(args.get("height", 720))
    path = _file_name(args, "viewport")
    if os.path.exists(path):
        os.remove(path)
    u.AutomationLibrary.take_high_res_screenshot(w, h, path)
    return wait_for_file(path, lambda p: _image_result(p, {"width": w, "height": h, "kind": "viewport"}), timeout=20.0)


def tool_capture_map_overview(args):
    """Orthographic top-down capture of an area; returns the image plus the pixel->world mapping."""
    u = ue.require()
    for api in ("SceneCapture2D", "RenderingLibrary.create_render_target2d", "RenderingLibrary.export_render_target"):
        if not ue.has(api):
            raise ue.UnsupportedError(f"{api} is not available in this DevKit")
    from .mapping import _area_bounds
    bounds = _area_bounds(args.get("area"))
    cx, cy = (bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0
    half = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 2.0
    res = int(args.get("resolution", 1024))
    top_z = float(args.get("camera_z", 0.0)) or _scene_top_z() + 5000.0
    world = ue.get_world()

    sub = ue.actor_subsystem()
    rot = ue.rot({"pitch": -90.0, "yaw": 0.0, "roll": 0.0})
    loc = ue.vec({"x": cx, "y": cy, "z": top_z})
    actor = (sub.spawn_actor_from_class(u.SceneCapture2D, loc, rot, True) if sub is not None
             else u.EditorLevelLibrary.spawn_actor_from_class(u.SceneCapture2D, loc, rot))
    path = _file_name(args, "map")
    try:
        comp = actor.get_editor_property("capture_component2d")
        comp.set_editor_property("projection_type", u.CameraProjectionMode.ORTHOGRAPHIC)
        comp.set_editor_property("ortho_width", half * 2.0)
        source = getattr(u.SceneCaptureSource, _SOURCES.get(args.get("mode", "final"), "SCS_FINAL_COLOR_LDR"))
        comp.set_editor_property("capture_source", source)
        comp.set_editor_property("capture_every_frame", False)
        rt = u.RenderingLibrary.create_render_target2d(world, res, res, u.TextureRenderTargetFormat.RTF_RGBA8)
        comp.set_editor_property("texture_target", rt)
        comp.capture_scene()
        if os.path.exists(path):
            os.remove(path)
        u.RenderingLibrary.export_render_target(world, rt, os.path.dirname(path), os.path.basename(path))
    finally:
        try:
            (sub.destroy_actor(actor) if sub is not None else u.EditorLevelLibrary.destroy_actor(actor))
        except Exception:
            pass

    wpp = (half * 2.0) / res
    meta = {
        "kind": "map_overview", "resolution": res,
        "world_bounds": {"min_x": cx - half, "min_y": cy - half, "max_x": cx + half, "max_y": cy + half},
        "orientation": "Image top = +X (north), image right = +Y (east)",
        "world_per_pixel_cm": round(wpp, 3),
        "pixel_to_world": f"x = {cx + half:.1f} - (row + 0.5) * {wpp:.3f};  y = {cy - half:.1f} + (col + 0.5) * {wpp:.3f}",
    }
    return wait_for_file(path, lambda p: _image_result(p, meta), timeout=20.0)


def _scene_top_z():
    top = 0.0
    for a in ue.all_actors():
        if ue.class_name(a).startswith("Landscape"):
            origin, extent = ue.actor_bounds(a)
            top = max(top, origin.z + extent.z)
    return top or 50000.0


def register(registry):
    from .level import AREA
    registry.register("capture_viewport", "Capture",
                      "Screenshot of the active editor viewport, returned as an image so you can see the result of your changes.",
                      {"properties": {"width": {"type": "integer", "minimum": 64, "maximum": 3840},
                                      "height": {"type": "integer", "minimum": 64, "maximum": 2160},
                                      "file_name": {"type": "string"}}},
                      READ_ONLY, tool_capture_viewport)
    registry.register("capture_map_overview", "Capture",
                      "Top-down orthographic image of an area (default: whole landscape) with the pixel->world mapping, to plan and review map layouts.",
                      {"properties": {"area": AREA, "resolution": {"type": "integer", "minimum": 128, "maximum": 4096},
                                      "mode": {"type": "string", "enum": list(_SOURCES)},
                                      "camera_z": {"type": "number"}, "file_name": {"type": "string"}}},
                      READ_ONLY, tool_capture_map_overview)
