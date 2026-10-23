"""Thin, defensive helpers around the Unreal Engine Python API.

Every tool goes through ``ue.unreal`` (never ``import unreal`` directly) so the
test-suite can swap in a fake engine. Helpers probe for optional APIs and raise
clear errors instead of AttributeError when a DevKit build lacks them.
"""

import contextlib
import math
import os
import re

try:
    import unreal  # noqa: F401
except ImportError:
    unreal = None

NATIVE_LIBRARY_NAME = "ConanMCPEditorLibrary"


class UnsupportedError(RuntimeError):
    """Raised when the running DevKit does not expose an API a tool needs."""


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

def require():
    if unreal is None:
        raise UnsupportedError("Unreal Engine Python API not available: run this tool inside the DevKit editor")
    return unreal


def has(dotted: str) -> bool:
    """True if e.g. 'EditorActorSubsystem.spawn_actor_from_object' exists in the running engine."""
    if unreal is None:
        return False
    obj = unreal
    for part in dotted.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return False
    return True


def native():
    """The optional C++ helper library (Source/ConanMCPNative), or None."""
    return getattr(unreal, NATIVE_LIBRARY_NAME, None) if unreal else None


# ---------------------------------------------------------------------------
# Subsystems / world
# ---------------------------------------------------------------------------

def editor_subsystem(name: str):
    u = require()
    cls = getattr(u, name, None)
    if cls is None or not hasattr(u, "get_editor_subsystem"):
        return None
    try:
        return u.get_editor_subsystem(cls)
    except Exception:
        return None


def actor_subsystem():
    return editor_subsystem("EditorActorSubsystem")


def get_world():
    u = require()
    sub = editor_subsystem("UnrealEditorSubsystem")
    if sub is not None and hasattr(sub, "get_editor_world"):
        return sub.get_editor_world()
    return u.EditorLevelLibrary.get_editor_world()


def all_actors():
    u = require()
    sub = actor_subsystem()
    if sub is not None and hasattr(sub, "get_all_level_actors"):
        return list(sub.get_all_level_actors())
    return list(u.EditorLevelLibrary.get_all_level_actors())


def selected_actors():
    u = require()
    sub = actor_subsystem()
    if sub is not None and hasattr(sub, "get_selected_level_actors"):
        return list(sub.get_selected_level_actors())
    return list(u.EditorLevelLibrary.get_selected_level_actors())


@contextlib.contextmanager
def transaction(description: str):
    """Undoable editor transaction (Ctrl+Z) when the API is available."""
    u = require()
    if hasattr(u, "ScopedEditorTransaction"):
        with u.ScopedEditorTransaction(description):
            yield
    else:
        yield


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------

def actor_label(actor) -> str:
    try:
        return actor.get_actor_label()
    except Exception:
        return actor.get_name()


def class_name(obj) -> str:
    try:
        return obj.get_class().get_name()
    except Exception:
        return type(obj).__name__


def find_actor(name: str, actors=None):
    """Find an actor by exact label, name or path (case-insensitive)."""
    if not name:
        raise ValueError("Actor name/label is required")
    target = name.strip().lower()
    candidates = actors if actors is not None else all_actors()
    for a in candidates:
        if actor_label(a).lower() == target or a.get_name().lower() == target:
            return a
    for a in candidates:
        try:
            if a.get_path_name().lower() == target:
                return a
        except Exception:
            pass
    return None


def require_actor(name: str, actors=None):
    actor = find_actor(name, actors)
    if actor is None:
        raise ValueError(f"Actor '{name}' not found in the current level")
    return actor


def find_actors(names, actors=None):
    pool = actors if actors is not None else all_actors()
    found, missing = [], []
    for n in names or []:
        a = find_actor(str(n), pool)
        (found if a is not None else missing).append(a if a is not None else n)
    return found, missing


def actor_location(actor):
    return actor.get_actor_location()


def actor_bounds(actor):
    """(origin Vector, extent Vector) of the actor's bounding box."""
    try:
        origin, extent = actor.get_actor_bounds(False)
        return origin, extent
    except Exception:
        loc = actor.get_actor_location()
        return loc, require().Vector(0.0, 0.0, 0.0)


def actor_folder(actor) -> str:
    try:
        return str(actor.get_folder_path())
    except Exception:
        return ""


def actor_tags(actor):
    try:
        return [str(t) for t in actor.get_editor_property("tags")]
    except Exception:
        return []


def actor_summary(actor, with_bounds: bool = False) -> dict:
    loc = actor.get_actor_location()
    data = {
        "name": actor.get_name(),
        "label": actor_label(actor),
        "class": class_name(actor),
        "location": vec_to_dict(loc),
        "folder": actor_folder(actor),
    }
    try:
        data["rotation"] = rot_to_dict(actor.get_actor_rotation())
    except Exception:
        pass
    if with_bounds:
        origin, extent = actor_bounds(actor)
        data["bounds"] = {"origin": vec_to_dict(origin), "extent": vec_to_dict(extent)}
    return data


# ---------------------------------------------------------------------------
# Math types
# ---------------------------------------------------------------------------

def vec(d, default=(0.0, 0.0, 0.0)):
    u = require()
    if d is None:
        return u.Vector(*default)
    if isinstance(d, (list, tuple)):
        vals = list(d) + list(default[len(d):])
        return u.Vector(float(vals[0]), float(vals[1]), float(vals[2]))
    return u.Vector(float(d.get("x", default[0])), float(d.get("y", default[1])), float(d.get("z", default[2])))


def rot(d, default=(0.0, 0.0, 0.0)):
    """Rotator from {"pitch","yaw","roll"} or [pitch, yaw, roll].

    unreal.Rotator's positional order is (roll, pitch, yaw), so fields are set by name.
    """
    u = require()
    if d is None:
        d = {}
    if isinstance(d, (list, tuple)):
        vals = list(d) + list(default[len(d):])
        d = {"pitch": vals[0], "yaw": vals[1], "roll": vals[2]}
    r = u.Rotator()
    r.pitch = float(d.get("pitch", default[0]))
    r.yaw = float(d.get("yaw", default[1]))
    r.roll = float(d.get("roll", default[2]))
    return r


def vec_to_dict(v) -> dict:
    return {"x": round(float(v.x), 3), "y": round(float(v.y), 3), "z": round(float(v.z), 3)}


def rot_to_dict(r) -> dict:
    return {"pitch": round(float(r.pitch), 3), "yaw": round(float(r.yaw), 3), "roll": round(float(r.roll), 3)}


def to_json_value(value, depth: int = 0):
    """Best-effort conversion of an Unreal property value to JSON."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth > 3:
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [to_json_value(v, depth + 1) for v in list(value)[:200]]
    if isinstance(value, dict):
        return {str(k): to_json_value(v, depth + 1) for k, v in list(value.items())[:200]}
    if all(hasattr(value, a) for a in ("x", "y", "z")) and not hasattr(value, "w"):
        return vec_to_dict(value)
    if all(hasattr(value, a) for a in ("pitch", "yaw", "roll")):
        return rot_to_dict(value)
    if hasattr(value, "get_path_name"):
        try:
            return value.get_path_name()
        except Exception:
            pass
    if hasattr(value, "to_tuple"):
        try:
            return [to_json_value(v, depth + 1) for v in value.to_tuple()]
        except Exception:
            pass
    return str(value)


def from_json_value(value, current):
    """Convert a JSON value to the Unreal type of ``current`` (an existing property value)."""
    u = require()
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)
    if current is not None and all(hasattr(current, a) for a in ("pitch", "yaw", "roll")):
        return rot(value)
    if current is not None and all(hasattr(current, a) for a in ("x", "y", "z")):
        return vec(value)
    if isinstance(value, str) and value.startswith("/"):
        obj = u.EditorAssetLibrary.load_asset(value)
        if obj is None:
            raise ValueError(f"Asset '{value}' not found")
        return obj
    if hasattr(u, "Name") and type(current).__name__ == "Name":
        return u.Name(str(value))
    if hasattr(u, "Text") and type(current).__name__ == "Text":
        return u.Text(str(value))
    return value


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def load_asset(path: str):
    u = require()
    if not path:
        raise ValueError("Asset path is required")
    asset = u.EditorAssetLibrary.load_asset(path)
    if asset is None:
        raise ValueError(f"Asset not found at '{path}'")
    return asset


def resolve_class(name_or_path: str):
    """unreal class from 'PointLight', '/Script/Engine.PointLight' or a Blueprint asset path."""
    u = require()
    if not name_or_path:
        raise ValueError("Class name is required")
    if name_or_path.startswith("/Script/"):
        short = name_or_path.rsplit(".", 1)[-1]
        cls = getattr(u, short, None)
        if cls is not None:
            return cls
    if name_or_path.startswith("/"):
        asset = load_asset(name_or_path)
        if hasattr(asset, "generated_class"):
            return asset.generated_class()
        return asset
    cls = getattr(u, name_or_path, None)
    if cls is None:
        raise ValueError(f"Unknown class '{name_or_path}'")
    return cls


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

def _hit_fields(hit):
    """Extract (location, normal, actor) from a HitResult regardless of engine version."""
    u = require()
    parts = None
    if hasattr(u, "GameplayStatics") and hasattr(u.GameplayStatics, "break_hit_result"):
        try:
            parts = u.GameplayStatics.break_hit_result(hit)
        except Exception:
            parts = None
    if parts is None and hasattr(hit, "to_tuple"):
        parts = hit.to_tuple()
    if parts is None:
        return None
    vectors = [p for p in parts if all(hasattr(p, a) for a in ("x", "y", "z")) and not isinstance(p, (int, float))]
    actor_cls = getattr(u, "Actor", None)
    actors = [p for p in parts if actor_cls is not None and isinstance(p, actor_cls)]
    blocking = next((p for p in parts if isinstance(p, bool)), True)
    if not blocking or len(vectors) < 4:
        return None
    # BreakHitResult order: Location, ImpactPoint, Normal, ImpactNormal, TraceStart, TraceEnd
    return vectors[1], vectors[3], (actors[0] if actors else None)


def trace_down(x: float, y: float, z_top: float = 200000.0, z_bottom: float = -200000.0, ignore=None):
    """Vertical line trace. Returns dict(location, normal, slope_deg, actor_label, actor_class) or None."""
    u = require()
    world = get_world()
    start, end = u.Vector(float(x), float(y), float(z_top)), u.Vector(float(x), float(y), float(z_bottom))
    channel = u.TraceTypeQuery.TRACE_TYPE_QUERY1 if hasattr(u, "TraceTypeQuery") else 0
    draw = u.DrawDebugTrace.NONE if hasattr(u, "DrawDebugTrace") else 0
    hit = u.SystemLibrary.line_trace_single(world, start, end, channel, True, list(ignore or []), draw, True)
    if isinstance(hit, tuple):  # (bool, HitResult) on some versions
        hit = hit[-1] if (len(hit) > 1 and hit[0]) else None
    if hit is None:
        return None
    fields = _hit_fields(hit)
    if fields is None:
        return None
    loc, normal, actor = fields
    nz = max(-1.0, min(1.0, float(normal.z)))
    return {
        "location": vec_to_dict(loc),
        "normal": vec_to_dict(normal),
        "slope_deg": round(math.degrees(math.acos(abs(nz))), 2),
        "actor_label": actor_label(actor) if actor is not None else None,
        "actor_class": class_name(actor) if actor is not None else None,
    }


# ---------------------------------------------------------------------------
# Files (always confined to <Project>/Saved/ConanMCP)
# ---------------------------------------------------------------------------

_SAFE_FILE = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9]{1,8})?$")


def saved_dir(subdir: str = "") -> str:
    from . import config
    if unreal is not None and hasattr(unreal, "Paths"):
        base = unreal.Paths.project_saved_dir()
        base = unreal.Paths.convert_relative_path_to_full(base) if hasattr(unreal.Paths, "convert_relative_path_to_full") else base
    else:
        base = os.path.join(os.getcwd(), "Saved")
    path = os.path.join(base, config.SAVED_SUBDIR, subdir) if subdir else os.path.join(base, config.SAVED_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def safe_file(name: str, subdir: str = "", default_ext: str = "") -> str:
    """Absolute path of a file inside Saved/ConanMCP[/subdir]. Rejects anything but a plain file name."""
    if not name or not _SAFE_FILE.match(name):
        raise ValueError("File name must be a plain name like 'my_file.json' (letters, digits, _ and -)")
    if default_ext and "." not in name:
        name += default_ext
    return os.path.join(saved_dir(subdir), name)


def log_dir():
    if unreal is not None and hasattr(unreal, "Paths") and hasattr(unreal.Paths, "project_log_dir"):
        return unreal.Paths.project_log_dir()
    return os.path.join(os.getcwd(), "Saved", "Logs")
