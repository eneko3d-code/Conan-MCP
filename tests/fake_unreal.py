"""A small fake of the Unreal Python API, enough to exercise ConanMCP tool logic without the editor.

It mirrors the real API names the tools call. It cannot prove the real engine
behaves the same way, but it catches logic, argument and data-flow bugs.
"""

import base64
import json
import math
from array import array


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __repr__(self):
        return f"Vector({self.x}, {self.y}, {self.z})"


class Rotator:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll, self.pitch, self.yaw = float(roll), float(pitch), float(yaw)


class Name(str):
    pass


class Text(str):
    pass


class _Cls:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class Object:
    _counter = 0

    def __init__(self, name=None, path=None):
        Object._counter += 1
        self._name = name or f"{type(self).__name__}_{Object._counter}"
        self._path = path or f"/Temp/{self._name}"
        self._props = {}

    def get_name(self):
        return self._name

    def get_path_name(self):
        return self._path

    def get_class(self):
        return _Cls(type(self).__name__)

    def get_editor_property(self, name):
        if name not in self._props:
            raise AttributeError(f"{type(self).__name__} has no property '{name}'")
        return self._props[name]

    def set_editor_property(self, name, value):
        self._props[name] = value

    def modify(self):
        return True


class Actor(Object):
    def __init__(self, label=None, location=(0, 0, 0), extent=(50, 50, 50), cls_name=None, folder=""):
        super().__init__(label)
        self._label = label or self._name
        self._loc = Vector(*location)
        self._rot = Rotator()
        self._scale = Vector(1, 1, 1)
        self._extent = Vector(*extent)
        self._folder = folder
        self._cls_name = cls_name
        self._props.update({"tags": [], "hidden": False})
        self._path = f"/Game/Maps/Test.Test:PersistentLevel.{self._name}"

    def get_class(self):
        return _Cls(self._cls_name or type(self).__name__)

    def get_actor_label(self):
        return self._label

    def set_actor_label(self, label):
        self._label = label

    def get_actor_location(self):
        return Vector(self._loc.x, self._loc.y, self._loc.z)

    def set_actor_location(self, v, sweep=False, teleport=True):
        self._loc = Vector(v.x, v.y, v.z)
        return True

    def get_actor_rotation(self):
        return self._rot

    def set_actor_rotation(self, r, teleport=False):
        self._rot = r
        return True

    def get_actor_scale3d(self):
        return self._scale

    def set_actor_scale3d(self, s):
        self._scale = s

    def get_actor_bounds(self, only_colliding=False):
        return self.get_actor_location(), Vector(self._extent.x * self._scale.x, self._extent.y * self._scale.y,
                                                 self._extent.z * self._scale.z)

    def get_folder_path(self):
        return Name(self._folder)

    def set_folder_path(self, folder):
        self._folder = str(folder)

    def get_components_by_class(self, cls):
        return []

    def is_hidden_ed(self):
        return False


class StaticMeshActor(Actor):
    pass


class PointLight(Actor):
    pass


class SceneCapture2D(Actor):
    pass


class Landscape(Actor):
    pass


class WorldSettings(Actor):
    pass


class ActorComponent(Object):
    pass


class StaticMesh(Object):
    pass


class Blueprint(Object):
    def __init__(self, name, path, parent="Actor"):
        super().__init__(name, path)
        self._props.update({"parent_class": _Cls(parent), "new_variables": [], "status": "BS_UP_TO_DATE"})

    def generated_class(self):
        return _Cls(self._name + "_C")


class DataTable(Object):
    def __init__(self, name, path, rows, columns):
        super().__init__(name, path)
        self.rows = rows
        self.columns = set(columns)


class World(Object):
    def __init__(self, height_fn):
        super().__init__("TestWorld")
        self.height_fn = height_fn


class HitResult:
    def __init__(self, loc, normal, actor):
        self.loc, self.normal, self.actor = loc, normal, actor


# ---------------------------------------------------------------------------
# Engine state + subsystems
# ---------------------------------------------------------------------------

class FakeEngine:
    def __init__(self, height_fn=None):
        self.world = World(height_fn or (lambda x, y: 0.0))
        self.actors = []
        self.assets = {}
        self.dirs = set()
        self.selected = []
        self.transactions = []
        self.console = []
        self.camera = None
        self.saved = []
        self.deps = {}

    def add_actor(self, actor):
        self.actors.append(actor)
        return actor

    def add_asset(self, path, asset):
        self.assets[path.split(".")[0]] = asset
        return asset


ENGINE = FakeEngine()


def reset(height_fn=None):
    global ENGINE
    ENGINE = FakeEngine(height_fn)
    return ENGINE


class EditorActorSubsystem:
    def get_all_level_actors(self):
        return list(ENGINE.actors)

    def get_selected_level_actors(self):
        return list(ENGINE.selected)

    def set_selected_level_actors(self, actors):
        ENGINE.selected = list(actors)

    def spawn_actor_from_object(self, obj, location, rotation=None, transient=False):
        a = StaticMeshActor(obj.get_name(), (location.x, location.y, location.z), extent=(100, 100, 100))
        a._props["static_mesh"] = obj
        if rotation is not None:
            a._rot = rotation
        return ENGINE.add_actor(a)

    def spawn_actor_from_class(self, cls, location, rotation=None, transient=False):
        if isinstance(cls, _Cls):
            a = Actor(cls.get_name(), (location.x, location.y, location.z), cls_name=cls.get_name())
        else:
            a = cls(None, (location.x, location.y, location.z))
        if rotation is not None:
            a._rot = rotation
        return ENGINE.add_actor(a)

    def destroy_actors(self, actors):
        for a in actors:
            ENGINE.actors.remove(a)
        return True

    def destroy_actor(self, actor):
        ENGINE.actors.remove(actor)
        return True

    def duplicate_actors(self, actors, world=None, offset=None):
        out = []
        for a in actors:
            loc = a.get_actor_location()
            d = type(a)(a._label + "_Copy", (loc.x + offset.x, loc.y + offset.y, loc.z + offset.z),
                        (a._extent.x, a._extent.y, a._extent.z), a._cls_name, a._folder)
            out.append(ENGINE.add_actor(d))
        return out


class UnrealEditorSubsystem:
    def get_editor_world(self):
        return ENGINE.world

    def set_level_viewport_camera_info(self, location, rotation):
        ENGINE.camera = (location, rotation)


_SUBSYSTEMS = {}


def get_editor_subsystem(cls):
    return _SUBSYSTEMS.setdefault(cls, cls())


class ScopedEditorTransaction:
    def __init__(self, description):
        self.description = description

    def __enter__(self):
        ENGINE.transactions.append(self.description)
        return self

    def __exit__(self, *exc):
        return False


class TraceTypeQuery:
    TRACE_TYPE_QUERY1 = 0


class DrawDebugTrace:
    NONE = 0


class SystemLibrary:
    @staticmethod
    def line_trace_single(world, start, end, channel, complex_, ignore, draw, ignore_self, *a):
        x, y = start.x, start.y
        z = world.height_fn(x, y)
        if z is None:
            return None
        e = 1.0
        dzdx = (world.height_fn(x + e, y) - world.height_fn(x - e, y)) / (2 * e)
        dzdy = (world.height_fn(x, y + e) - world.height_fn(x, y - e)) / (2 * e)
        n = Vector(-dzdx, -dzdy, 1.0)
        length = math.sqrt(n.x ** 2 + n.y ** 2 + n.z ** 2)
        n = Vector(n.x / length, n.y / length, n.z / length)
        land = next((a for a in ENGINE.actors if isinstance(a, Landscape)), None)
        return HitResult(Vector(x, y, z), n, land)

    @staticmethod
    def execute_console_command(world, command, player=None):
        ENGINE.console.append(command)

    @staticmethod
    def get_engine_version():
        return "5.8.2-fake"


class GameplayStatics:
    @staticmethod
    def break_hit_result(hit):
        return (True, False, 0.5, 10.0, hit.loc, hit.loc, hit.normal, hit.normal, None, hit.actor, None,
                Name(""), Name(""), 0, 0, 0, Vector(), Vector())


class EditorAssetLibrary:
    @staticmethod
    def load_asset(path):
        return ENGINE.assets.get(path.split(".")[0])

    @staticmethod
    def does_asset_exist(path):
        return path.split(".")[0] in ENGINE.assets

    @staticmethod
    def does_directory_exist(path):
        return path in ENGINE.dirs

    @staticmethod
    def make_directory(path):
        ENGINE.dirs.add(path)
        return True

    @staticmethod
    def save_loaded_asset(asset, only_if_dirty=True):
        ENGINE.saved.append(asset.get_name())
        return True

    @staticmethod
    def rename_asset(src, dst):
        a = ENGINE.assets.pop(src.split(".")[0], None)
        if a is None:
            return False
        ENGINE.assets[dst.split(".")[0]] = a
        return True

    @staticmethod
    def delete_asset(path):
        return ENGINE.assets.pop(path.split(".")[0], None) is not None


class DataTableFunctionLibrary:
    @staticmethod
    def export_data_table_to_json_string(dt):
        return json.dumps(dt.rows)

    @staticmethod
    def fill_data_table_from_json_string(dt, text, struct=None):
        rows = json.loads(text)
        for r in rows:
            if set(r) - dt.columns - {"Name"}:
                return False
        dt.rows = rows
        return True


class AssetData:
    def __init__(self, path, cls):
        self.package_name = Name(path.split(".")[0])
        self.asset_name = Name(path.split(".")[0].rsplit("/", 1)[-1])
        self.package_path = Name(path.split(".")[0].rsplit("/", 1)[0])
        self.asset_class = Name(cls)


class AssetRegistryDependencyOptions(Object):
    pass


class _Registry:
    def get_assets_by_path(self, path, recursive=True):
        return [AssetData(p, type(a).__name__) for p, a in ENGINE.assets.items() if p.startswith(path + "/")]

    def get_assets_by_package_name(self, pkg):
        return [AssetData(pkg, type(ENGINE.assets[pkg]).__name__)] if pkg in ENGINE.assets else []

    def get_dependencies(self, pkg, opts=None):
        return [Name(d) for d in ENGINE.deps.get(str(pkg), [])]

    def get_referencers(self, pkg, opts=None):
        return [Name(k) for k, v in ENGINE.deps.items() if str(pkg) in v]


class AssetRegistryHelpers:
    @staticmethod
    def get_asset_registry():
        return _Registry()


class _Pkg:
    def __init__(self, name):
        self._n = name

    def get_name(self):
        return self._n


class EditorLoadingAndSavingUtils:
    dirty = []

    @staticmethod
    def get_dirty_content_packages():
        return [_Pkg(p) for p in EditorLoadingAndSavingUtils.dirty]

    @staticmethod
    def get_dirty_map_packages():
        return []

    @staticmethod
    def save_dirty_packages(maps, content):
        EditorLoadingAndSavingUtils.dirty = []
        return True


def log(msg):
    pass


def log_warning(msg):
    pass


def log_error(msg):
    pass


# ---------------------------------------------------------------------------
# Optional native library (simulates Source/ConanMCPNative)
# ---------------------------------------------------------------------------

class FakeNativeLibrary:
    """Landscape of size x size vertices at origin with scale 100."""

    def __init__(self, size=64, label="Landscape"):
        self.size, self.label = size, label
        self.heights = array("H", [32768] * (size * size))
        self.writes = 0

    def get_landscape_info_json(self):
        return json.dumps([{"label": self.label, "name": self.label, "class": "Landscape",
                            "origin": {"x": 0, "y": 0, "z": 0}, "scale": {"x": 100, "y": 100, "z": 100},
                            "extent_quads": {"min_x": 0, "min_y": 0, "max_x": self.size - 1, "max_y": self.size - 1},
                            "layers": ["Grass", "Rock"]}])

    def get_height_region_json(self, label, x0, y0, x1, y1):
        w, h = x1 - x0 + 1, y1 - y0 + 1
        out = array("H")
        for y in range(y0, y1 + 1):
            out.extend(self.heights[y * self.size + x0: y * self.size + x1 + 1])
        return json.dumps({"ok": True, "x0": x0, "y0": y0, "width": w, "height": h,
                           "data_b64": base64.b64encode(out.tobytes()).decode()})

    def set_height_region_json(self, label, x0, y0, x1, y1, data_b64):
        data = array("H")
        data.frombytes(base64.b64decode(data_b64))
        w = x1 - x0 + 1
        for i, v in enumerate(data):
            self.heights[(y0 + i // w) * self.size + x0 + i % w] = v
        self.writes += 1
        return json.dumps({"ok": True})

    def undo_last_transaction(self):
        return True
