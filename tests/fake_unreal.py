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

    def __dir__(self):
        # Like the real Python wrappers, reflected properties show up in dir()
        return sorted(set(super().__dir__()) | set(self._props))

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


# ---------------------------------------------------------------------------
# Animation APIs (Control Rig, sequencer, notifies)
# ---------------------------------------------------------------------------

import copy as _copy  # noqa: E402
import sys as _sys  # noqa: E402
import os as _os  # noqa: E402

_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "Content", "Python"))
from conan_mcp.animation import pose as _pose  # noqa: E402


class Quat:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x, self.y, self.z, self.w = x, y, z, w

    def rotator(self):
        r = _pose.quat_to_rotator((self.x, self.y, self.z, self.w))
        out = Rotator()
        out.pitch, out.yaw, out.roll = r["pitch"], r["yaw"], r["roll"]
        return out


def _rot_quat(self):
    return Quat(*_pose.rotator_to_quat(self.pitch, self.yaw, self.roll))


Rotator.quaternion = _rot_quat


class Transform:
    def __init__(self, translation=None, rotation=None, scale=None):
        self.translation = translation or Vector()
        self.rotation = rotation or Quat()
        self.scale3d = scale or Vector(1, 1, 1)


class EulerTransform:
    def __init__(self, location=None, rotation=None, scale=None):
        self.location = location or Vector()
        self.rotation = rotation or Rotator()
        self.scale = scale or Vector(1, 1, 1)


class FrameRate:
    def __init__(self, num=30, den=1):
        self.numerator, self.denominator = num, den


class FrameNumber:
    def __init__(self, value=0):
        self.value = int(value)


class MovieSceneTimeUnit:
    DISPLAY_RATE = 0


class AnimPoseSpaces:
    LOCAL = 0


class Skeleton(Object):
    def __init__(self, name, path, bones, ref=None):
        super().__init__(name, path)
        self.bones = bones
        self.ref = ref or {}


class SkeletalMesh(Object):
    def __init__(self, name, path, skeleton):
        super().__init__(name, path)
        self._props["skeleton"] = skeleton


class SkeletalMeshComponent(Object):
    def __init__(self):
        super().__init__()
        self.override = None

    def override_animation_data(self, anim, looping, playing, position, rate):
        self.override = (anim, position)


class SkeletalMeshActor(Actor):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mesh_component = SkeletalMeshComponent()

    def get_component_by_class(self, cls):
        return self.mesh_component if cls is SkeletalMeshComponent else None


class _Pose:
    def __init__(self, skel):
        self.skel = skel


class AnimPoseExtensions:
    @staticmethod
    def get_reference_pose(skel):
        return _Pose(skel)

    @staticmethod
    def get_bone_names(pose):
        return [Name(b) for b in pose.skel.bones]

    @staticmethod
    def get_bone_pose(pose, bone, space=0):
        r = pose.skel.ref.get(bone, {"pitch": 0, "yaw": 0, "roll": 0})
        rot = Rotator()
        rot.pitch, rot.yaw, rot.roll = r["pitch"], r["yaw"], r["roll"]
        return Transform(Vector(0, 0, 10), rot.quaternion())


class _Binding:
    def __init__(self, actor):
        self.actor = actor

    def get_display_name(self):
        return Text(self.actor.get_actor_label())


class LevelSequence(Object):
    def __init__(self, name, path):
        super().__init__(name, path)
        self.bindings, self.rig, self.end, self.rate = [], None, 0, None

    def set_display_rate(self, rate):
        self.rate = rate

    def set_playback_start(self, f):
        pass

    def set_playback_end(self, f):
        self.end = f

    def add_possessable(self, actor):
        b = _Binding(actor)
        self.bindings.append(b)
        return b

    def get_bindings(self):
        return list(self.bindings)


class FKControlRig(Object):
    pass


class _FakeRig(Object):
    def __init__(self, cls_name="FKControlRig"):
        super().__init__("Rig")
        self.keys = {}
        self._cls = cls_name

    def get_class(self):
        return _Cls(self._cls)


class _Proxy:
    def __init__(self, rig):
        self.control_rig = rig


class ControlRigSequencerLibrary:
    @staticmethod
    def find_or_create_control_rig_track(world, seq, cls, binding):
        seq.rig = _FakeRig()
        return object()

    @staticmethod
    def get_control_rigs(seq):
        return [_Proxy(seq.rig)] if seq.rig else []

    @staticmethod
    def get_local_control_rig_euler_transform(seq, rig, name, frame, unit):
        return EulerTransform()

    @staticmethod
    def set_local_control_rig_euler_transform(seq, rig, name, frame, value, unit, set_key):
        rig.keys[(str(name), frame.value)] = value.rotation


class LevelSequenceEditorBlueprintLibrary:
    current = None

    @staticmethod
    def open_level_sequence(seq):
        return True

    @staticmethod
    def set_current_time(frame):
        LevelSequenceEditorBlueprintLibrary.current = frame


class _Controller:
    def __init__(self):
        self.tracks, self.frames, self.brackets = {}, 0, 0

    def open_bracket(self, text, undo=True):
        self.brackets += 1

    def close_bracket(self, undo=True):
        self.brackets -= 1

    def set_frame_rate(self, rate, undo=True):
        self.rate = rate

    def set_number_of_frames(self, n, undo=True):
        self.frames = n.value

    def add_bone_curve(self, bone, undo=True):
        self.tracks.setdefault(bone, None)
        return True

    def set_bone_track_keys(self, bone, pos, rot, scale, undo=True):
        self.tracks[bone] = (pos, rot, scale)
        return True


class _NotifyEvent:
    def __init__(self, obj, track_index, time, duration, is_state):
        self.obj, self.track_index, self.time, self.duration, self.is_state = obj, track_index, time, duration, is_state

    def get_editor_property(self, name):
        if name == "notify":
            return None if self.is_state else self.obj
        if name == "notify_state_class":
            return self.obj if self.is_state else None
        if name == "track_index":
            return self.track_index
        if name == "notify_name":
            return Name(type(self.obj).__name__)
        raise AttributeError(name)


class AnimSequenceBase(Object):
    def __init__(self, name, path, length=1.0):
        super().__init__(name, path)
        self.length = length
        self.notify_tracks = []
        self.events = []

    def get_play_length(self):
        return self.length


class AnimSequence(AnimSequenceBase):
    def __init__(self, name, path, length=1.0):
        super().__init__(name, path, length)
        self.controller = _Controller()
        self.exported_from = None


class _Segment(Object):
    pass


class _AnimTrack(Object):
    pass


class _SlotTrack(Object):
    pass


class AnimMontage(AnimSequenceBase):
    def __init__(self, name, path, anim=None):
        super().__init__(name, path, anim.length if anim else 1.0)
        seg = _Segment()
        seg._props.update({"anim_reference": anim, "anim_start_time": 0.0, "anim_end_time": self.length})
        at = _AnimTrack()
        at._props["anim_segments"] = [seg]
        st = _SlotTrack()
        st._props.update({"slot_name": Name("DefaultSlot"), "anim_track": at})
        self._props["slot_anim_tracks"] = [st]


class AnimNotify(Object):
    pass


class AnimNotifyState(Object):
    pass


class AnimNotify_PlayNiagaraEffect(AnimNotify):
    def __init__(self):
        super().__init__()
        self._props.update({"template": None, "socket_name": Name(""), "location_offset": Vector(), "attached": True})


class AnimNotifyState_TimedNiagaraEffect(AnimNotifyState):
    def __init__(self):
        super().__init__()
        self._props.update({"template": None, "socket_name": Name("")})


class AnimNotifyState_ConanDamageWindow(AnimNotifyState):
    def __init__(self):
        super().__init__()
        self._props.update({"damage_multiplier": 1.0, "trace_socket": Name("weapon_r")})


class NiagaraSystem(Object):
    pass


class AnimationLibrary:
    @staticmethod
    def get_sequence_length(anim):
        return anim.length

    @staticmethod
    def get_num_frames(anim):
        return int(round(anim.length * 30))

    @staticmethod
    def get_animation_notify_track_names(anim):
        return [Name(t) for t in anim.notify_tracks]

    @staticmethod
    def add_animation_notify_track(anim, name, color=None):
        anim.notify_tracks.append(str(name))

    @staticmethod
    def add_animation_notify_event(anim, track, time, cls):
        if time < 0 or time > anim.length:
            return None
        cls = globals()[cls.get_name()] if isinstance(cls, _Cls) else cls
        obj = cls() if isinstance(cls, type) else None
        anim.events.append(_NotifyEvent(obj, anim.notify_tracks.index(track), time, 0.0, False))
        return obj

    @staticmethod
    def add_animation_notify_state_event(anim, track, time, duration, cls):
        cls = globals()[cls.get_name()] if isinstance(cls, _Cls) else cls
        obj = cls()
        anim.events.append(_NotifyEvent(obj, anim.notify_tracks.index(track), time, duration, True))
        return obj

    @staticmethod
    def get_animation_notify_events(anim):
        return list(anim.events)

    @staticmethod
    def get_anim_notify_event_trigger_time(ev):
        return ev.time

    @staticmethod
    def get_anim_notify_event_duration(ev):
        return ev.duration

    @staticmethod
    def remove_animation_notify_events_by_track(anim, track):
        idx = anim.notify_tracks.index(track)
        before = len(anim.events)
        anim.events = [e for e in anim.events if e.track_index != idx]
        return before - len(anim.events)


class LevelSequenceFactoryNew(Object):
    pass


class AnimSequenceFactory(Object):
    pass


class AnimMontageFactory(Object):
    pass


class AnimSeqExportOption(Object):
    pass


class _AssetTools:
    def create_asset(self, name, folder, cls, factory):
        path = f"{folder}/{name}"
        if path in ENGINE.assets:
            return None
        if cls is LevelSequence:
            asset = LevelSequence(name, path)
        elif cls is AnimSequence:
            asset = AnimSequence(name, path)
        elif cls is AnimMontage:
            asset = AnimMontage(name, path, factory.get_editor_property("source_animation"))
        else:
            asset = cls(name, path)
        return ENGINE.add_asset(path, asset)


class AssetToolsHelpers:
    @staticmethod
    def get_asset_tools():
        return _AssetTools()


class SequencerTools:
    @staticmethod
    def export_anim_sequence(world, seq, anim, opts, binding, link):
        anim.exported_from = seq
        anim.length = seq.end / 30.0
        return True


def _duplicate_asset(src, dst):
    a = ENGINE.assets.get(src.split(".")[0])
    if a is None or dst in ENGINE.assets:
        return False
    new = _copy.deepcopy(a)
    new._name, new._path = dst.rsplit("/", 1)[-1], dst
    ENGINE.assets[dst] = new
    return True


EditorAssetLibrary.duplicate_asset = staticmethod(_duplicate_asset)

_orig_spawn = EditorActorSubsystem.spawn_actor_from_object


def _spawn_from_object(self, obj, location, rotation=None, transient=False):
    if isinstance(obj, SkeletalMesh):
        a = SkeletalMeshActor(obj.get_name(), (location.x, location.y, location.z), extent=(40, 40, 90))
        if rotation is not None:
            a._rot = rotation
        return ENGINE.add_actor(a)
    return _orig_spawn(self, obj, location, rotation, transient)


EditorActorSubsystem.spawn_actor_from_object = _spawn_from_object
