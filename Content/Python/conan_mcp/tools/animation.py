"""Animation tools: author attacks/abilities with Control Rig from references, bake, montage, notifies and VFX.

Workflow (see skills/conan-animation-from-reference and skills/conan-custom-attacks-vfx):
  create_animation_preview -> set_pose_keys / generate_attack_keys -> capture_animation_frames (compare with
  the reference, iterate) -> bake_animation -> create_montage -> copy_animation_notifies / add_animation_notify
  -> preview_ability.

Every authored animation keeps a JSON spec in Saved/ConanMCP/animations/<name>.json (bones, roles,
reference pose, additive keys). Keys are written to a Control Rig track when the engine supports it, and
the spec alone can be baked straight into an AnimSequence when it does not.
"""

import json
import math
import os

from ..animation.pose import clamp_offset, compose_additive, merge_keys, offset_from_absolute, rot_dict, sample_keys
from ..animation.roles import map_roles, resolve
from ..animation.timing import TEMPLATES, generate_keys
from ..core import ue
from ..core.results import Deferred, ToolResult
from ..core.security import READ_ONLY, SAFE_WRITE
from .builtin import tool_find_assets

SPEC_DIR = "animations"
CAPTURE_DIR = "captures"
MOD_ROOT = "/Game/Mods/"

# Friendly notify kinds -> (class name, is_state)
NOTIFY_KINDS = {
    "niagara": ("AnimNotify_PlayNiagaraEffect", False),
    "cascade": ("AnimNotify_PlayParticleEffect", False),
    "sound": ("AnimNotify_PlaySound", False),
    "niagara_timed": ("AnimNotifyState_TimedNiagaraEffect", True),
    "cascade_timed": ("AnimNotifyState_TimedParticleEffect", True),
    "trail": ("AnimNotifyState_Trail", True),
}
# Friendly property names -> real property per notify class
_PROP_ALIASES = {
    "system": {"AnimNotify_PlayNiagaraEffect": "template", "AnimNotifyState_TimedNiagaraEffect": "template",
               "AnimNotify_PlayParticleEffect": "ps_template", "AnimNotifyState_TimedParticleEffect": "ps_template",
               "AnimNotifyState_Trail": "ps_template"},
    "socket": {"AnimNotifyState_Trail": "first_socket_name", "AnimNotify_PlaySound": "attach_name", "*": "socket_name"},
    "second_socket": {"AnimNotifyState_Trail": "second_socket_name"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guard_mod(path: str, what: str = "Assets"):
    if not path.startswith(MOD_ROOT):
        raise PermissionError(f"{what} must be created/edited inside /Game/Mods/<YourMod>/ (got '{path}'). "
                              "Duplicate base-game assets into your mod with duplicate_asset first.")


def _folder(args, sub):
    if args.get("package_path"):
        path = args["package_path"].rstrip("/")
    elif args.get("mod_name"):
        path = f"/Game/Mods/{args['mod_name']}/Animations"
    else:
        raise ValueError("Provide mod_name (assets go to /Game/Mods/<mod_name>/Animations) or package_path")
    _guard_mod(path + "/")
    return f"{path}/{sub}" if sub else path


def _spec_path(name):
    return ue.safe_file(name, SPEC_DIR, ".json")


def load_spec(name):
    path = _spec_path(name)
    if not os.path.exists(path):
        raise ValueError(f"No animation '{name}'. Create it with create_animation_preview first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_spec(spec):
    with open(_spec_path(spec["name"]), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)


def _skeleton_of(mesh):
    try:
        return mesh.get_editor_property("skeleton")
    except Exception:
        return None


def reference_pose(mesh):
    """(bones in hierarchy order, {bone: local rotation dict}, {bone: local translation dict})."""
    u = ue.require()
    skel = _skeleton_of(mesh)
    if ue.has("AnimPoseExtensions.get_reference_pose") and skel is not None:
        pose = u.AnimPoseExtensions.get_reference_pose(skel)
        bones = [str(b) for b in u.AnimPoseExtensions.get_bone_names(pose)]
        rots, locs = {}, {}
        for b in bones:
            t = u.AnimPoseExtensions.get_bone_pose(pose, b, u.AnimPoseSpaces.LOCAL)
            r = t.rotation.rotator() if hasattr(t.rotation, "rotator") else t.rotation
            rots[b] = {"pitch": round(r.pitch, 4), "yaw": round(r.yaw, 4), "roll": round(r.roll, 4)}
            locs[b] = ue.vec_to_dict(t.translation)
        return bones, rots, locs
    # Fallback: names only (reference rotations unknown -> treated as zero)
    comp = u.SkeletalMeshComponent()
    (comp.set_skeletal_mesh_asset if hasattr(comp, "set_skeletal_mesh_asset") else comp.set_skeletal_mesh)(mesh)
    bones = [str(b) for b in comp.get_bone_names()]
    return bones, {}, {}


def _rig_lib():
    if not ue.has("ControlRigSequencerLibrary"):
        return None
    return ue.require().ControlRigSequencerLibrary


def _load_sequence(spec):
    return ue.load_asset(spec["sequence_path"]) if spec.get("sequence_path") else None


def _control_rig(seq):
    lib = _rig_lib()
    if lib is None or seq is None:
        return None
    proxies = lib.get_control_rigs(seq)
    return proxies[0].control_rig if proxies else None


def _write_control(seq, rig, control, frame, rotation, location=None):
    """Keys a control's local rotation (and optional location), whatever its control type."""
    u = ue.require()
    lib = _rig_lib()
    fn = u.FrameNumber(int(frame))
    unit = u.MovieSceneTimeUnit.DISPLAY_RATE
    rot = ue.rot(rotation)
    try:
        cur = lib.get_local_control_rig_euler_transform(seq, rig, control, fn, unit)
        cur.rotation = rot
        if location is not None:
            cur.location = ue.vec(location)
        lib.set_local_control_rig_euler_transform(seq, rig, control, fn, cur, unit, True)
        return "euler_transform"
    except Exception:
        pass
    try:
        cur = lib.get_local_control_rig_transform(seq, rig, control, fn, unit)
        cur.rotation = rot.quaternion()
        if location is not None:
            cur.translation = ue.vec(location)
        lib.set_local_control_rig_transform(seq, rig, control, fn, cur, unit, True)
        return "transform"
    except Exception:
        pass
    lib.set_local_control_rig_rotator(seq, rig, control, fn, rot, unit, True)
    return "rotator"


def _role_of(spec):
    return {bone: role for role, bone in spec.get("roles", {}).items()}


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

def tool_find_animations(args):
    kind = args.get("kind", "all")
    classes = {"sequence": ["AnimSequence"], "montage": ["AnimMontage"], "all": ["AnimMontage", "AnimSequence"]}[kind]
    results = []
    for cls in classes:
        res = tool_find_assets({"class_name": cls, "name_filter": args.get("query", ""),
                                "package_path": args.get("package_path", "/Game"), "limit": int(args.get("limit", 50))})
        results.extend(res.get("assets", res.get("results", [])))
    return {"count": len(results), "animations": results[: int(args.get("limit", 50))]}


def _notify_time(lib, ev, name):
    for fn in (f"get_anim_notify_event_{name}", f"get_animation_notify_event_{name}"):
        if hasattr(lib, fn):
            try:
                return float(getattr(lib, fn)(ev))
            except Exception:
                pass
    for prop in ({"trigger_time": ("trigger_time", "link_value", "display_time"), "duration": ("duration",)}[name]):
        try:
            return float(ev.get_editor_property(prop))
        except Exception:
            pass
    return None


def notify_events(anim):
    """Notifies of an animation as dicts (class, time, duration, track, object)."""
    u = ue.require()
    lib = u.AnimationLibrary
    events = list(lib.get_animation_notify_events(anim) or [])
    tracks = [str(t) for t in (lib.get_animation_notify_track_names(anim) or [])]
    out = []
    for ev in events:
        obj, is_state = None, False
        try:
            obj = ev.get_editor_property("notify")
        except Exception:
            pass
        if obj is None:
            try:
                obj = ev.get_editor_property("notify_state_class")
                is_state = obj is not None
            except Exception:
                pass
        try:
            track_idx = int(ev.get_editor_property("track_index"))
        except Exception:
            track_idx = 0
        try:
            nname = str(ev.get_editor_property("notify_name"))
        except Exception:
            nname = ""
        out.append({
            "name": nname,
            "class": ue.class_name(obj) if obj is not None else None,
            "is_state": is_state,
            "time": _notify_time(lib, ev, "trigger_time"),
            "duration": _notify_time(lib, ev, "duration") if is_state else 0.0,
            "track": tracks[track_idx] if 0 <= track_idx < len(tracks) else str(track_idx),
            "object": obj,
        })
    return out


def _notify_props(obj, limit=25):
    props = {}
    if obj is None:
        return props
    for name in dir(obj):
        if name.startswith("_") or len(props) >= limit:
            continue
        try:
            value = obj.get_editor_property(name)
        except Exception:
            continue
        if callable(value):
            continue
        props[name] = ue.to_json_value(value)
    return props


def _anim_length(anim):
    u = ue.require()
    for getter in (lambda: u.AnimationLibrary.get_sequence_length(anim), lambda: anim.get_play_length(),
                   lambda: anim.get_editor_property("sequence_length")):
        try:
            return float(getter())
        except Exception:
            continue
    return None


def tool_get_animation_info(args):
    u = ue.require()
    anim = ue.load_asset(args["anim_path"])
    info = {"name": anim.get_name(), "class": ue.class_name(anim), "length_s": _anim_length(anim)}
    try:
        info["frames"] = int(u.AnimationLibrary.get_num_frames(anim))
    except Exception:
        pass
    try:
        skel = anim.get_editor_property("skeleton")
        info["skeleton"] = skel.get_path_name() if skel else None
    except Exception:
        pass
    for prop in ("enable_root_motion", "rate_scale"):
        try:
            info[prop] = ue.to_json_value(anim.get_editor_property(prop))
        except Exception:
            pass
    if ue.has("AnimationLibrary.get_animation_notify_events"):
        events = notify_events(anim)
        info["notifies"] = [{**{k: v for k, v in e.items() if k != "object"},
                             "properties": _notify_props(e["object"]) if args.get("include_properties", True) else {}}
                            for e in events]
    if ue.class_name(anim) == "AnimMontage":
        try:
            info["sections"] = [{"name": str(s.get_editor_property("section_name")),
                                 "start": ue.to_json_value(s.get_editor_property("link_value"))}
                                for s in anim.get_editor_property("composite_sections")]
        except Exception:
            pass
        try:
            slots = []
            for track in anim.get_editor_property("slot_anim_tracks"):
                segs = track.get_editor_property("anim_track").get_editor_property("anim_segments")
                slots.append({"slot": str(track.get_editor_property("slot_name")),
                              "animations": [ue.to_json_value(sg.get_editor_property("anim_reference")) for sg in segs]})
            info["slots"] = slots
        except Exception:
            pass
    return info


def tool_get_skeleton_roles(args):
    ue.require()
    mesh = ue.load_asset(args["mesh_path"])
    bones, ref, _ = reference_pose(mesh)
    mapped = map_roles(bones)
    return {"mesh": mesh.get_name(), "bone_count": len(bones), **mapped,
            "reference_pose_known": bool(ref),
            "axis_hint": ("Axis directions differ between skeletons. Calibrate once: key +30 deg pitch, yaw and roll "
                          "on upperarm_r at frames 10/20/30 and look at capture_animation_frames before posing.")}


def tool_get_reference_pose(args):
    ue.require()
    mesh = ue.load_asset(args["mesh_path"])
    bones, ref, locs = reference_pose(mesh)
    wanted = args.get("bones")
    if wanted:
        roles = map_roles(bones)["roles"]
        sel = [resolve(b, roles, bones) or b for b in wanted]
    else:
        sel = bones
    return {"bones": {b: {"rotation": ref.get(b), "location": locs.get(b)} for b in sel[:300]}}


def tool_get_control_rig_controls(args):
    spec = load_spec(args["name"])
    rig = _control_rig(_load_sequence(spec))
    if rig is None:
        return {"rig": None, "controls": [f"{b}_CONTROL" for b in spec["bones"]],
                "note": "No live Control Rig: keys are stored in the spec and baked directly (FK naming shown)."}
    controls = []
    try:
        hierarchy = rig.get_hierarchy()
        for key in hierarchy.get_controls():
            controls.append(str(key.name))
    except Exception:
        controls = [str(c) for c in getattr(rig, "available_controls", lambda: [])()]
    return {"rig": ue.class_name(rig), "count": len(controls), "controls": controls[:500]}


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------

def _preview_location(args):
    if args.get("location"):
        return dict(args["location"])
    sub = ue.editor_subsystem("UnrealEditorSubsystem")
    if sub is not None and hasattr(sub, "get_level_viewport_camera_info"):
        try:
            loc, rot = sub.get_level_viewport_camera_info()
            yaw = math.radians(rot.yaw)
            return {"x": loc.x + math.cos(yaw) * 600, "y": loc.y + math.sin(yaw) * 600, "z": loc.z}
        except Exception:
            pass
    return {"x": 0.0, "y": 0.0, "z": 0.0}


def tool_create_animation_preview(args):
    u = ue.require()
    name = args["name"]
    ue.safe_file(name, SPEC_DIR, ".json")  # validates the name
    mesh = ue.load_asset(args["mesh_path"])
    fps = int(args.get("fps", 30))
    frames = max(1, int(round(float(args.get("duration", 1.0)) * fps)))
    folder = _folder(args, "Sequences")
    bones, ref, locs = reference_pose(mesh)
    roles = map_roles(bones)
    if args.get("dry_run"):
        return {"dry_run": True, "folder": folder, "bones": len(bones), "roles": roles["roles"]}

    from .level import _spawn_one
    loc = _preview_location(args)
    actor_info = _spawn_one({"asset_path": args["mesh_path"], "location": loc, "snap_to_ground": True,
                             "label": f"ConanMCP_AnimPreview_{name}", "folder": "ConanMCP/AnimPreview",
                             "rotation": {"yaw": float(args.get("yaw", 0.0))}})
    spec = {"name": name, "mesh_path": args["mesh_path"], "fps": fps, "frames": frames, "bones": bones,
            "roles": roles["roles"], "body_type": roles["body_type"], "reference": ref, "reference_locations": locs,
            "preview_actor": actor_info["label"], "rig": args.get("rig_path") or "FKControlRig", "keys": [],
            "sequence_path": None, "control_rig": False}
    skel = _skeleton_of(mesh)
    spec["skeleton_path"] = skel.get_path_name() if skel else None

    notes = []
    if ue.has("LevelSequence") and ue.has("AssetToolsHelpers"):
        tools = u.AssetToolsHelpers.get_asset_tools()
        seq = tools.create_asset(f"LS_{name}", folder, u.LevelSequence, u.LevelSequenceFactoryNew())
        seq.set_display_rate(u.FrameRate(fps, 1))
        seq.set_playback_start(0)
        seq.set_playback_end(frames)
        actor = ue.require_actor(actor_info["label"])
        binding = seq.add_possessable(actor)
        spec["sequence_path"] = seq.get_path_name().split(".")[0]
        try:
            spec["binding_name"] = str(binding.get_display_name())
        except Exception:
            spec["binding_name"] = actor_info["label"]
        lib = _rig_lib()
        if lib is not None:
            rig_class = (ue.resolve_class(args["rig_path"]) if args.get("rig_path") else getattr(u, "FKControlRig", None))
            if rig_class is None:
                notes.append("FKControlRig class not available: keys will be baked directly.")
            else:
                lib.find_or_create_control_rig_track(ue.get_world(), seq, rig_class, binding)
                spec["control_rig"] = _control_rig(seq) is not None
        else:
            notes.append("ControlRigSequencerLibrary not available (enable the Control Rig plugin); keys will be baked directly.")
        if ue.has("LevelSequenceEditorBlueprintLibrary.open_level_sequence"):
            u.LevelSequenceEditorBlueprintLibrary.open_level_sequence(seq)
    else:
        notes.append("LevelSequence API not available: spec-only authoring (bake_animation writes the AnimSequence directly).")
    save_spec(spec)
    return {"name": name, "preview_actor": actor_info, "sequence": spec["sequence_path"],
            "control_rig_track": spec["control_rig"], "fps": fps, "frames": frames, "body_type": spec["body_type"],
            "roles": spec["roles"], "reference_pose_known": bool(ref), "notes": notes,
            "next": "Calibrate axes (see get_skeleton_roles.axis_hint), then set_pose_keys or generate_attack_keys."}


def _normalize_keys(spec, keys, mode):
    roles_of = _role_of(spec)
    fps = spec["fps"]
    out, clamped, unresolved = [], [], []
    for k in keys:
        frame = int(k["frame"]) if "frame" in k else int(round(float(k.get("time", 0.0)) * fps))
        bones = {}
        for target, data in (k.get("pose") or k.get("bones") or {}).items():
            bone = resolve(target, spec["roles"], spec["bones"])
            if bone is None:
                unresolved.append(target)
                continue
            rotation = rot_dict((data or {}).get("rotation"))
            if mode == "absolute":
                rotation = offset_from_absolute(spec["reference"].get(bone, {}), rotation)
            rotation, was = clamp_offset(roles_of.get(bone), rotation)
            if was:
                clamped.append(f"{target}@{frame}")
            entry = {"rotation": rotation}
            if data and data.get("location") is not None:
                entry["location"] = data["location"]
            bones[bone] = entry
        out.append({"frame": frame, "bones": bones})
    return out, clamped, sorted(set(unresolved))


def apply_keys(spec, keys):
    """Writes normalized keys to the Control Rig track (if any). Returns number of control keys written."""
    seq = _load_sequence(spec)
    rig = _control_rig(seq) if spec.get("control_rig") else None
    if rig is None:
        return 0, "spec_only"
    fk = spec.get("rig") == "FKControlRig"
    written = 0
    with ue.transaction(f"ConanMCP: Pose keys for {spec['name']}"):
        for k in keys:
            for bone, data in k["bones"].items():
                control = f"{bone}_CONTROL" if fk else bone
                value = compose_additive(spec["reference"].get(bone, {}), data["rotation"]) if fk else data["rotation"]
                _write_control(seq, rig, control, k["frame"], value, data.get("location"))
                written += 1
        last = max((k["frame"] for k in keys), default=0)
        if last > spec["frames"]:
            seq.set_playback_end(last)
    return written, "control_rig"


def tool_set_pose_keys(args):
    spec = load_spec(args["name"])
    keys, clamped, unresolved = _normalize_keys(spec, args.get("keys") or [], args.get("mode", "additive"))
    if not keys:
        raise ValueError("'keys' must contain at least one {frame|time, pose:{target:{rotation}}}")
    if args.get("dry_run"):
        return {"dry_run": True, "keys": keys, "clamped": clamped, "unresolved_targets": unresolved}
    written, backend = apply_keys(spec, keys)
    spec["keys"] = merge_keys(spec["keys"], keys)
    spec["frames"] = max(spec["frames"], max(k["frame"] for k in keys))
    save_spec(spec)
    return {"keys_set": len(keys), "control_keys_written": written, "backend": backend, "clamped": clamped,
            "unresolved_targets": unresolved, "total_keyframes": len(spec["keys"]), "frames": spec["frames"]}


def tool_generate_attack_keys(args):
    spec = load_spec(args["name"])
    plan = generate_keys(args.get("poses") or {}, args.get("template", "light_attack"), args.get("duration"),
                         spec["fps"], float(args.get("overshoot", 0.12)), bool(args.get("settle", True)))
    keys = [{"frame": k["frame"], "pose": k["bones"]} for k in plan["keys"]]
    if args.get("replace", True) and not args.get("dry_run"):
        spec["keys"] = []
        save_spec(spec)
    res = tool_set_pose_keys({"name": args["name"], "keys": keys, "mode": "additive", "dry_run": args.get("dry_run")})
    spec = load_spec(args["name"])
    if not args.get("dry_run"):
        spec["frames"] = plan["frames"]
        spec["phases"] = plan["phases"]
        spec["impact_frame"] = plan["impact_frame"]
        save_spec(spec)
        seq = _load_sequence(spec)
        if seq is not None:
            seq.set_playback_end(plan["frames"])
    return {"template": args.get("template", "light_attack"), "phases": plan["phases"],
            "impact_frame": plan["impact_frame"], "impact_time_s": round(plan["impact_frame"] / spec["fps"], 3),
            "frames": plan["frames"], "keys": [{"frame": k["frame"], "phase": k["phase"]} for k in plan["keys"]], **res}


# ---------------------------------------------------------------------------
# Visual feedback
# ---------------------------------------------------------------------------

_VIEWS = {"front": 0.0, "three_quarter": 45.0, "side": 90.0, "back": 180.0, "other_side": -90.0}


def _aim_camera(actor, view, distance_scale=3.0):
    origin, extent = ue.actor_bounds(actor)
    size = max(extent.x, extent.y, extent.z, 50.0)
    yaw0 = actor.get_actor_rotation().yaw
    if view == "top":
        cam = {"x": origin.x, "y": origin.y, "z": origin.z + size * distance_scale}
        rot = {"pitch": -89.0, "yaw": yaw0, "roll": 0.0}
    else:
        a = math.radians(yaw0 + _VIEWS.get(view, 0.0))
        d = size * distance_scale
        cam = {"x": origin.x + math.cos(a) * d, "y": origin.y + math.sin(a) * d, "z": origin.z + extent.z * 0.15}
        rot = {"pitch": -5.0, "yaw": math.degrees(a) + 180.0, "roll": 0.0}
    sub = ue.editor_subsystem("UnrealEditorSubsystem")
    if sub is not None and hasattr(sub, "set_level_viewport_camera_info"):
        sub.set_level_viewport_camera_info(ue.vec(cam), ue.rot(rot))


def _set_frame(spec, frame, anim=None, actor=None):
    u = ue.require()
    if anim is not None and actor is not None:
        comp = actor.get_component_by_class(u.SkeletalMeshComponent)
        comp.override_animation_data(anim, False, False, frame / float(spec.get("fps", 30)), 0.0)
        return
    if ue.has("LevelSequenceEditorBlueprintLibrary.set_current_time"):
        u.LevelSequenceEditorBlueprintLibrary.set_current_time(int(frame))


def _frames_to_capture(args, total, impact=None):
    if args.get("frames"):
        return [int(f) for f in args["frames"]][:12]
    n = max(2, min(int(args.get("count", 6)), 12))
    picks = sorted({int(round(i * total / (n - 1))) for i in range(n)} | ({int(impact)} if impact is not None else set()))
    return picks[:12]


def capture_frames(spec, frames, view, width, height, anim=None, actor=None):
    """Deferred that captures each frame (2 ticks settle, screenshot, wait for file)."""
    u = ue.require()
    actor = actor or ue.require_actor(spec["preview_actor"])
    _aim_camera(actor, view, float(spec.get("distance_scale", 3.0)))
    state = {"i": 0, "phase": "set", "wait": 0, "path": None, "images": [], "files": []}

    def poll():
        if state["i"] >= len(frames):
            meta = {"name": spec["name"], "view": view, "frames": frames, "files": state["files"],
                    "fps": spec.get("fps", 30), "note": "Images are in frame order. Compare silhouette, line of action and arcs with the reference."}
            return True, ToolResult(meta, images=state["images"])
        f = frames[state["i"]]
        if state["phase"] == "set":
            _set_frame(spec, f, anim, actor)
            state["phase"], state["wait"] = "settle", 2
            return False, None
        if state["phase"] == "settle":
            state["wait"] -= 1
            if state["wait"] <= 0:
                path = ue.safe_file(f"{spec['name']}_{view}_f{f:03d}.png", CAPTURE_DIR)
                if os.path.exists(path):
                    os.remove(path)
                u.AutomationLibrary.take_high_res_screenshot(width, height, path)
                state["path"], state["phase"], state["wait"] = path, "file", 0
            return False, None
        if state["phase"] == "file":
            p = state["path"]
            if os.path.exists(p) and os.path.getsize(p) > 0:
                state["wait"] += 1
                if state["wait"] >= 2:  # size stable for a tick
                    with open(p, "rb") as fh:
                        state["images"].append((fh.read(), "image/png"))
                    state["files"].append(p)
                    state["i"] += 1
                    state["phase"] = "set"
            return False, None
        return False, None

    return Deferred(poll, timeout=8.0 * len(frames) + 5.0, description="animation frame captures")


def tool_capture_animation_frames(args):
    if not ue.has("AutomationLibrary.take_high_res_screenshot"):
        raise ue.UnsupportedError("AutomationLibrary.take_high_res_screenshot is not available in this DevKit")
    spec = load_spec(args["name"])
    anim = ue.load_asset(args["anim_path"]) if args.get("anim_path") else None
    if anim is None and not spec.get("sequence_path"):
        raise ue.UnsupportedError("No LevelSequence for this animation; bake it and pass anim_path to preview the baked result")
    if anim is None and ue.has("LevelSequenceEditorBlueprintLibrary.open_level_sequence"):
        ue.require().LevelSequenceEditorBlueprintLibrary.open_level_sequence(_load_sequence(spec))
    frames = _frames_to_capture(args, spec["frames"], spec.get("impact_frame"))
    return capture_frames(spec, frames, args.get("view", "side"), int(args.get("width", 640)),
                          int(args.get("height", 640)), anim=anim)


# ---------------------------------------------------------------------------
# Bake & montage
# ---------------------------------------------------------------------------

def _create_anim_asset(name, folder, skeleton):
    u = ue.require()
    factory = u.AnimSequenceFactory()
    factory.set_editor_property("target_skeleton", skeleton)
    anim = u.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, u.AnimSequence, factory)
    if anim is None:
        raise RuntimeError(f"Could not create AnimSequence {folder}/{name} (does it already exist?)")
    return anim


def _bake_from_spec(spec, anim):
    """Writes bone tracks straight from the spec (no Control Rig needed)."""
    u = ue.require()
    controller = getattr(anim, "controller", None) or anim.get_editor_property("controller")
    bones = sorted({b for k in spec["keys"] for b in k["bones"]})
    frames = int(spec["frames"])
    controller.open_bracket(u.Text("ConanMCP bake"), True)
    try:
        controller.set_frame_rate(u.FrameRate(int(spec["fps"]), 1), True)
        controller.set_number_of_frames(u.FrameNumber(frames), True)
        for bone in bones:
            ref = spec["reference"].get(bone, {})
            loc = spec.get("reference_locations", {}).get(bone, {"x": 0, "y": 0, "z": 0})
            positions, rotations, scales = [], [], []
            for f in range(frames + 1):
                off = sample_keys(spec["keys"], bone, f) or {}
                r = compose_additive(ref, off)
                positions.append(ue.vec(loc))
                rotations.append(ue.rot(r).quaternion())
                scales.append(ue.vec({"x": 1, "y": 1, "z": 1}))
            add = getattr(controller, "add_bone_curve", None) or getattr(controller, "add_bone_track")
            add(bone, True)
            controller.set_bone_track_keys(bone, positions, rotations, scales, True)
    finally:
        controller.close_bracket(True)
    return len(bones)


def tool_bake_animation(args):
    u = ue.require()
    spec = load_spec(args["name"])
    if not spec["keys"]:
        raise ValueError("Nothing to bake: add keys with set_pose_keys or generate_attack_keys")
    folder = _folder(args, "")
    anim_name = args.get("anim_name") or f"A_{spec['name']}"
    mesh = ue.load_asset(spec["mesh_path"])
    skeleton = _skeleton_of(mesh)
    if args.get("dry_run"):
        return {"dry_run": True, "would_create": f"{folder}/{anim_name}", "frames": spec["frames"], "fps": spec["fps"]}
    anim = _create_anim_asset(anim_name, folder, skeleton)
    backend, bones = None, None
    seq = _load_sequence(spec)
    if seq is not None and spec.get("control_rig") and ue.has("SequencerTools.export_anim_sequence") and args.get("method", "auto") != "direct":
        binding = None
        for b in seq.get_bindings():
            try:
                if str(b.get_display_name()) == spec.get("binding_name"):
                    binding = b
                    break
            except Exception:
                continue
        binding = binding or (seq.get_bindings() or [None])[0]
        ok = u.SequencerTools.export_anim_sequence(ue.get_world(), seq, anim, u.AnimSeqExportOption(), binding, False)
        if ok is False:
            raise RuntimeError("SequencerTools.export_anim_sequence failed; retry with method='direct'")
        backend = "control_rig_sequence"
    else:
        bones = _bake_from_spec(spec, anim)
        backend = "direct_bone_tracks"
    if args.get("enable_root_motion") is not None:
        anim.set_editor_property("enable_root_motion", bool(args["enable_root_motion"]))
    if args.get("save", True):
        u.EditorAssetLibrary.save_loaded_asset(anim, False)
    path = anim.get_path_name()
    spec["baked_anim"] = path
    save_spec(spec)
    return {"anim_path": path, "backend": backend, "bones_baked": bones, "frames": spec["frames"], "fps": spec["fps"],
            "impact_time_s": round(spec["impact_frame"] / spec["fps"], 3) if spec.get("impact_frame") is not None else None}


def _swap_montage_animation(montage, anim):
    tracks = montage.get_editor_property("slot_anim_tracks")
    track = tracks[0]
    anim_track = track.get_editor_property("anim_track")
    segments = anim_track.get_editor_property("anim_segments")
    seg = segments[0]
    seg.set_editor_property("anim_reference", anim)
    length = _anim_length(anim)
    if length is not None:
        for prop, value in (("anim_start_time", 0.0), ("anim_end_time", length)):
            try:
                seg.set_editor_property(prop, value)
            except Exception:
                pass
    segments[0] = seg
    anim_track.set_editor_property("anim_segments", segments)
    track.set_editor_property("anim_track", anim_track)
    tracks[0] = track
    montage.set_editor_property("slot_anim_tracks", tracks)


def tool_create_montage(args):
    u = ue.require()
    anim = ue.load_asset(args["anim_path"])
    folder = _folder(args, "Montages")
    name = args.get("montage_name") or f"AM_{anim.get_name().removeprefix('A_')}"
    dest = f"{folder}/{name}"
    if args.get("dry_run"):
        return {"dry_run": True, "would_create": dest, "template": args.get("template_montage")}
    if args.get("template_montage"):
        if not u.EditorAssetLibrary.duplicate_asset(args["template_montage"], dest):
            raise RuntimeError(f"Could not duplicate {args['template_montage']} to {dest}")
        montage = ue.load_asset(dest)
        with ue.transaction("ConanMCP: Swap montage animation"):
            montage.modify()
            _swap_montage_animation(montage, anim)
        tpl_len = _anim_length(ue.load_asset(args["template_montage"]))
        new_len = _anim_length(anim)
        note = None
        if tpl_len and new_len and abs(tpl_len - new_len) > 0.05:
            note = (f"Template is {tpl_len:.2f}s, new animation {new_len:.2f}s: notify windows were kept at their "
                    "original times. Re-time them (copy_animation_notifies with time_mode='scale') or match durations.")
    else:
        factory = u.AnimMontageFactory()
        factory.set_editor_property("source_animation", anim)
        montage = u.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, u.AnimMontage, factory)
        if montage is None:
            raise RuntimeError(f"Could not create montage {dest}")
        note = None
    if args.get("slot_name"):
        tracks = montage.get_editor_property("slot_anim_tracks")
        tracks[0].set_editor_property("slot_name", u.Name(args["slot_name"]))
        montage.set_editor_property("slot_anim_tracks", tracks)
    for prop in ("blend_in", "blend_out"):
        if args.get(f"{prop}_time") is not None:
            try:
                blend = montage.get_editor_property(prop)
                blend.set_editor_property("blend_time", float(args[f"{prop}_time"]))
                montage.set_editor_property(prop, blend)
            except Exception:
                pass
    if args.get("save", True):
        u.EditorAssetLibrary.save_loaded_asset(montage, False)
    return {"montage_path": montage.get_path_name(), "from_template": bool(args.get("template_montage")), "note": note}


# ---------------------------------------------------------------------------
# Notifies & VFX
# ---------------------------------------------------------------------------

def _ensure_track(anim, track):
    lib = ue.require().AnimationLibrary
    names = [str(t) for t in (lib.get_animation_notify_track_names(anim) or [])]
    if track not in names:
        lib.add_animation_notify_track(anim, track)


def _notify_class(kind, class_path):
    u = ue.require()
    if kind == "custom":
        if not class_path:
            raise ValueError("kind='custom' needs class_path (a notify class or Blueprint path)")
        return ue.resolve_class(class_path), bool(class_path and "State" in class_path)
    if kind not in NOTIFY_KINDS:
        raise ValueError(f"Unknown notify kind '{kind}'. Use one of {sorted(NOTIFY_KINDS) + ['custom']}")
    cls_name, is_state = NOTIFY_KINDS[kind]
    cls = getattr(u, cls_name, None)
    if cls is None:
        raise ue.UnsupportedError(f"{cls_name} is not available in this DevKit")
    return cls, is_state


def _set_notify_props(obj, props):
    cls = ue.class_name(obj)
    applied, failed = {}, {}
    for key, value in (props or {}).items():
        real = key
        alias = _PROP_ALIASES.get(key)
        if alias:
            real = alias.get(cls) or alias.get("*") or key
        try:
            current = obj.get_editor_property(real)
            conv = ue.from_json_value(value, current)
            if isinstance(value, str) and real.endswith(("socket_name", "attach_name")):
                conv = ue.require().Name(value)
            obj.set_editor_property(real, conv)
            applied[real] = value
        except Exception as e:
            failed[real] = str(e)
    return applied, failed


def tool_add_animation_notify(args):
    u = ue.require()
    path = args["anim_path"]
    _guard_mod(path, "Notifies")
    anim = ue.load_asset(path)
    cls, is_state = _notify_class(args.get("kind", "niagara"), args.get("class_path"))
    t = float(args["time"]) if args.get("time") is not None else None
    if t is None and args.get("frame") is not None:
        t = float(args["frame"]) / float(args.get("fps", 30))
    if t is None:
        raise ValueError("Provide 'time' (seconds) or 'frame' (+ fps)")
    track = args.get("track_name", "ConanMCP")
    if args.get("dry_run"):
        return {"dry_run": True, "class": ue.class_name(cls) if hasattr(cls, "get_class") else str(cls),
                "time": t, "track": track, "properties": args.get("properties")}
    lib = u.AnimationLibrary
    with ue.transaction("ConanMCP: Add notify"):
        anim.modify()
        _ensure_track(anim, track)
        if is_state:
            obj = lib.add_animation_notify_state_event(anim, track, t, float(args.get("duration", 0.3)), cls)
        else:
            obj = lib.add_animation_notify_event(anim, track, t, cls)
        if obj is None:
            raise RuntimeError("Unreal did not create the notify (check the time is inside the animation)")
        applied, failed = _set_notify_props(obj, args.get("properties"))
    if args.get("save", True):
        u.EditorAssetLibrary.save_loaded_asset(anim, False)
    return {"added": ue.class_name(obj), "time": t, "track": track, "applied": applied, "failed": failed}


def tool_copy_animation_notifies(args):
    u = ue.require()
    src = ue.load_asset(args["source_path"])
    dst_path = args["target_path"]
    _guard_mod(dst_path, "Notifies")
    dst = ue.load_asset(dst_path)
    events = notify_events(src)
    include = [c.lower() for c in args.get("include_classes") or []]
    exclude = [c.lower() for c in args.get("exclude_classes") or []]
    sel = [e for e in events if e["class"] and (not include or any(c in e["class"].lower() for c in include))
           and not any(c in e["class"].lower() for c in exclude)]
    src_len, dst_len = _anim_length(src), _anim_length(dst)
    mode = args.get("time_mode", "scale")
    ratio = (dst_len / src_len) if (mode == "scale" and src_len and dst_len) else 1.0
    offset = float(args.get("time_offset", 0.0))
    plan = [{"class": e["class"], "time": None if e["time"] is None else round(e["time"] * ratio + offset, 4),
             "duration": round((e["duration"] or 0.0) * ratio, 4), "track": e["track"], "is_state": e["is_state"]}
            for e in sel]
    if any(p["time"] is None for p in plan):
        raise ue.UnsupportedError("This engine does not expose notify trigger times to Python; copy them manually or use create_montage(template_montage=...)")
    if args.get("dry_run"):
        return {"dry_run": True, "time_ratio": round(ratio, 4), "notifies": plan}
    lib = u.AnimationLibrary
    copied, report = 0, []
    with ue.transaction("ConanMCP: Copy notifies"):
        dst.modify()
        for e, p in zip(sel, plan):
            track = args.get("track_name") or p["track"] or "ConanMCP"
            _ensure_track(dst, track)
            cls = e["object"].get_class()
            new = (lib.add_animation_notify_state_event(dst, track, p["time"], p["duration"], cls) if p["is_state"]
                   else lib.add_animation_notify_event(dst, track, p["time"], cls))
            if new is None:
                report.append({"class": p["class"], "error": "not created"})
                continue
            ok, bad = [], []
            for name in dir(e["object"]):
                if name.startswith("_"):
                    continue
                try:
                    value = e["object"].get_editor_property(name)
                except Exception:
                    continue
                if callable(value):
                    continue
                try:
                    new.set_editor_property(name, value)
                    ok.append(name)
                except Exception:
                    bad.append(name)
            copied += 1
            report.append({"class": p["class"], "time": p["time"], "properties_copied": len(ok), "properties_failed": bad[:10]})
    if args.get("save", True):
        u.EditorAssetLibrary.save_loaded_asset(dst, False)
    return {"copied": copied, "time_ratio": round(ratio, 4), "details": report}


def tool_remove_animation_notifies(args):
    u = ue.require()
    path = args["anim_path"]
    _guard_mod(path, "Notifies")
    anim = ue.load_asset(path)
    lib = u.AnimationLibrary
    if not args.get("track_name") and not args.get("notify_name"):
        raise ValueError("Provide track_name or notify_name")
    if args.get("dry_run"):
        events = notify_events(anim)
        hit = [e for e in events if (args.get("track_name") and e["track"] == args["track_name"])
               or (args.get("notify_name") and e["name"] == args["notify_name"])]
        return {"dry_run": True, "would_remove": [{k: v for k, v in e.items() if k != "object"} for e in hit]}
    removed = 0
    with ue.transaction("ConanMCP: Remove notifies"):
        anim.modify()
        if args.get("track_name"):
            removed += int(lib.remove_animation_notify_events_by_track(anim, args["track_name"]) or 0)
        if args.get("notify_name"):
            removed += int(lib.remove_animation_notify_events_by_name(anim, args["notify_name"]) or 0)
    if args.get("save", True):
        u.EditorAssetLibrary.save_loaded_asset(anim, False)
    return {"removed": removed}


def tool_duplicate_asset(args):
    u = ue.require()
    src, dst = args["source_path"], args["destination_path"]
    _guard_mod(dst, "Duplicates")
    if u.EditorAssetLibrary.does_asset_exist(dst):
        raise ValueError(f"'{dst}' already exists")
    if args.get("dry_run"):
        return {"dry_run": True, "from": src, "to": dst}
    if not u.EditorAssetLibrary.duplicate_asset(src, dst):
        raise RuntimeError(f"Could not duplicate {src} -> {dst}")
    return {"duplicated": dst, "from": src}


def tool_preview_ability(args):
    """Shows an animation/montage on the preview actor, spawns its particle notifies at their sockets and captures frames."""
    u = ue.require()
    spec = load_spec(args["name"])
    anim = ue.load_asset(args["anim_path"])
    actor = ue.require_actor(spec["preview_actor"])
    spawned = []
    if args.get("spawn_particles", True) and ue.has("AnimationLibrary.get_animation_notify_events"):
        comp = actor.get_component_by_class(u.SkeletalMeshComponent)
        for e in notify_events(anim):
            obj = e["object"]
            if obj is None or not e["class"] or not any(k in e["class"] for k in ("Niagara", "Particle", "Trail")):
                continue
            system = None
            for prop in ("template", "ps_template"):
                try:
                    system = obj.get_editor_property(prop)
                    if system:
                        break
                except Exception:
                    continue
            socket = ""
            for prop in ("socket_name", "first_socket_name"):
                try:
                    socket = str(obj.get_editor_property(prop))
                    break
                except Exception:
                    continue
            if system is None:
                continue
            if "Niagara" in ue.class_name(system) and ue.has("NiagaraFunctionLibrary.spawn_system_attached"):
                pc = u.NiagaraFunctionLibrary.spawn_system_attached(system, comp, socket, u.Vector(0, 0, 0), u.Rotator(),
                                                                    u.AttachLocation.SNAP_TO_TARGET, True)
            else:
                pc = u.GameplayStatics.spawn_emitter_attached(system, comp, socket)
            if pc is not None:
                try:
                    pc.component_tags.append("ConanMCP_PreviewParticle")
                except Exception:
                    pass
            spawned.append({"system": system.get_name(), "socket": socket, "time": e["time"]})
    length = _anim_length(anim) or spec["frames"] / spec["fps"]
    spec = {**spec, "frames": int(round(length * spec["fps"]))}
    frames = _frames_to_capture(args, spec["frames"], spec.get("impact_frame"))
    deferred = capture_frames(spec, frames, args.get("view", "three_quarter"), int(args.get("width", 640)),
                              int(args.get("height", 640)), anim=anim, actor=actor)
    inner = deferred.poll

    def poll():
        done, value = inner()
        if done:
            value.data["particles_spawned"] = spawned
            value.data["cleanup"] = f"remove_preview_particle(actor='{spec['preview_actor']}') removes the preview VFX"
        return done, value
    deferred.poll = poll
    return deferred


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry):
    name = {"name": {"type": "string", "description": "Animation work name (plain, e.g. 'overhead_slash')"}}
    mod = {"mod_name": {"type": "string"}, "package_path": {"type": "string", "description": "Folder under /Game/Mods"}}
    keys = {"type": "array", "maxItems": 400, "items": {"type": "object"},
            "description": "[{frame|time, pose: {<role|bone|control>: {rotation: {pitch,yaw,roll}, location?}}}]"}
    cap = {"view": {"type": "string", "enum": list(_VIEWS) + ["top"]}, "frames": {"type": "array", "items": {"type": "integer"}, "maxItems": 12},
           "count": {"type": "integer", "minimum": 2, "maximum": 12}, "width": {"type": "integer", "minimum": 128, "maximum": 1920},
           "height": {"type": "integer", "minimum": 128, "maximum": 1920}}

    registry.register("find_animations", "Animation", "Finds AnimSequences/AnimMontages by name (e.g. vanilla attacks to study or copy).",
                      {"properties": {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["all", "sequence", "montage"]},
                                      "package_path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
                      READ_ONLY, tool_find_animations)
    registry.register("get_animation_info", "Animation",
                      "Length, frames, skeleton, root motion, montage slots/sections and every notify (class, time, track, properties).",
                      {"properties": {"anim_path": {"type": "string"}, "include_properties": {"type": "boolean"}}, "required": ["anim_path"]},
                      READ_ONLY, tool_get_animation_info)
    registry.register("get_skeleton_roles", "Animation",
                      "Maps a skeleton's bones to roles (pelvis, spine_1, upperarm_r, thigh_l, tail_2, front_foot_l...) for posing.",
                      {"properties": {"mesh_path": {"type": "string"}}, "required": ["mesh_path"]}, READ_ONLY, tool_get_skeleton_roles)
    registry.register("get_reference_pose", "Animation", "Local reference-pose rotations/locations of bones (or roles).",
                      {"properties": {"mesh_path": {"type": "string"}, "bones": {"type": "array", "items": {"type": "string"}}},
                       "required": ["mesh_path"]}, READ_ONLY, tool_get_reference_pose)
    registry.register("get_control_rig_controls", "Animation", "Controls of the animation's Control Rig (FK: <bone>_CONTROL).",
                      {"properties": name, "required": ["name"]}, READ_ONLY, tool_get_control_rig_controls)
    registry.register("create_animation_preview", "Animation",
                      "Starts an animation: spawns a preview character, creates a LevelSequence with an FK (or custom) Control Rig track.",
                      {"properties": {**name, **mod, "mesh_path": {"type": "string"}, "rig_path": {"type": "string"},
                                      "fps": {"type": "integer", "minimum": 12, "maximum": 120},
                                      "duration": {"type": "number", "minimum": 0.1, "maximum": 30},
                                      "location": {"type": "object"}, "yaw": {"type": "number"}, "dry_run": {"type": "boolean"}},
                       "required": ["name", "mesh_path"]}, SAFE_WRITE, tool_create_animation_preview, idempotent=False)
    registry.register("set_pose_keys", "Animation",
                      "Keys poses: additive degrees over the reference pose (default) or absolute local rotations, per role/bone/control. Joint limits applied.",
                      {"properties": {**name, "keys": keys, "mode": {"type": "string", "enum": ["additive", "absolute"]},
                                      "dry_run": {"type": "boolean"}}, "required": ["name", "keys"]},
                      SAFE_WRITE, tool_set_pose_keys)
    registry.register("generate_attack_keys", "Animation",
                      f"Builds a full attack/ability from key poses (start, anticipation, impact, follow_through) and a timing template: {', '.join(TEMPLATES)}.",
                      {"properties": {**name, "template": {"type": "string", "enum": list(TEMPLATES)},
                                      "duration": {"type": "number", "minimum": 0.2, "maximum": 10},
                                      "poses": {"type": "object"}, "overshoot": {"type": "number", "minimum": 0, "maximum": 0.5},
                                      "settle": {"type": "boolean"}, "replace": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["name", "poses"]}, SAFE_WRITE, tool_generate_attack_keys)
    registry.register("capture_animation_frames", "Animation",
                      "Captures the posed preview at several frames (front/side/three_quarter/back/top) as images to compare with the reference.",
                      {"properties": {**name, **cap, "anim_path": {"type": "string"}}, "required": ["name"]},
                      READ_ONLY, tool_capture_animation_frames)
    registry.register("bake_animation", "Animation",
                      "Bakes the animation into an AnimSequence (from the Control Rig sequence, or directly from the keys).",
                      {"properties": {**name, **mod, "anim_name": {"type": "string"}, "method": {"type": "string", "enum": ["auto", "direct"]},
                                      "enable_root_motion": {"type": "boolean"}, "save": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["name"]}, SAFE_WRITE, tool_bake_animation, idempotent=False)
    registry.register("create_montage", "Animation",
                      "Creates an AnimMontage from an AnimSequence, or duplicates a vanilla montage (keeping its gameplay notifies) and swaps in the new animation.",
                      {"properties": {"anim_path": {"type": "string"}, **mod, "montage_name": {"type": "string"},
                                      "template_montage": {"type": "string"}, "slot_name": {"type": "string"},
                                      "blend_in_time": {"type": "number"}, "blend_out_time": {"type": "number"},
                                      "save": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["anim_path"]}, SAFE_WRITE, tool_create_montage, idempotent=False)
    registry.register("add_animation_notify", "Animation",
                      "Adds a notify to a sequence/montage: niagara, cascade, sound, niagara_timed, cascade_timed, trail or custom class. "
                      "Properties: system, socket, second_socket, location_offset, rotation_offset, scale, attached, sound...",
                      {"properties": {"anim_path": {"type": "string"}, "kind": {"type": "string", "enum": list(NOTIFY_KINDS) + ["custom"]},
                                      "class_path": {"type": "string"}, "time": {"type": "number"}, "frame": {"type": "integer"},
                                      "fps": {"type": "integer"}, "duration": {"type": "number"}, "track_name": {"type": "string"},
                                      "properties": {"type": "object"}, "save": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["anim_path"]}, SAFE_WRITE, tool_add_animation_notify, idempotent=False)
    registry.register("copy_animation_notifies", "Animation",
                      "Copies notifies (damage windows, weapon traces, sounds, VFX) from a vanilla attack to your animation, re-timed to its length.",
                      {"properties": {"source_path": {"type": "string"}, "target_path": {"type": "string"},
                                      "time_mode": {"type": "string", "enum": ["scale", "same"]}, "time_offset": {"type": "number"},
                                      "include_classes": {"type": "array", "items": {"type": "string"}},
                                      "exclude_classes": {"type": "array", "items": {"type": "string"}},
                                      "track_name": {"type": "string"}, "save": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["source_path", "target_path"]}, SAFE_WRITE, tool_copy_animation_notifies, idempotent=False)
    registry.register("remove_animation_notifies", "Animation", "Removes notifies by track or notify name.",
                      {"properties": {"anim_path": {"type": "string"}, "track_name": {"type": "string"}, "notify_name": {"type": "string"},
                                      "save": {"type": "boolean"}, "dry_run": {"type": "boolean"}}, "required": ["anim_path"]},
                      SAFE_WRITE, tool_remove_animation_notifies)
    registry.register("duplicate_asset", "Assets", "Duplicates any asset (montage, Niagara/Cascade system, mesh...) into your mod folder.",
                      {"properties": {"source_path": {"type": "string"}, "destination_path": {"type": "string"}, "dry_run": {"type": "boolean"}},
                       "required": ["source_path", "destination_path"]}, SAFE_WRITE, tool_duplicate_asset, idempotent=False)
    registry.register("preview_ability", "Animation",
                      "Plays an animation/montage on the preview character, spawns its particle notifies at their sockets and captures key frames.",
                      {"properties": {**name, "anim_path": {"type": "string"}, "spawn_particles": {"type": "boolean"}, **cap},
                       "required": ["name", "anim_path"]}, SAFE_WRITE, tool_preview_ability)

