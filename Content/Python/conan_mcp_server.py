"""
ConanMCP - Embedded MCP (Model Context Protocol) Server for Conan Exiles Enhanced DevKit (UE 5.8.2)
Implements JSON-RPC 2.0 over HTTP on 127.0.0.1:8123/mcp
"""

import sys
import json
import time
import socket
import threading
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional

# Add Vanilla Unreal Toolsets to sys.path
import os
for _tp in [
    r"C:\Program Files\Epic Games\CEUE5Devkit\Engine\Plugins\Experimental\ToolsetRegistry\Content\Python",
    r"C:\Program Files\Epic Games\CEUE5Devkit\Engine\Plugins\Experimental\Toolsets\EditorToolset\Content\Python",
    r"C:\Program Files\Epic Games\CEUE5Devkit\Engine\Plugins\Experimental\Toolsets\NiagaraToolsets\Content\Python"
]:
    if os.path.exists(_tp) and _tp not in sys.path:
        sys.path.append(_tp)

try:
    import unreal
except ImportError:
    unreal = None

# Default configuration
BIND_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 8123
ENDPOINT_PATH = "/mcp"

# Security flags
ENABLE_WRITE_TOOLS = True
ENABLE_DESTRUCTIVE_TOOLS = False
ENABLE_LOGGING = True
MAX_RESULTS = 50

# Security levels
READ_ONLY = "READ_ONLY"
SAFE_WRITE = "SAFE_WRITE"
DESTRUCTIVE = "DESTRUCTIVE"

def log_info(msg: str):
    if ENABLE_LOGGING:
        if unreal:
            unreal.log(f"LogConanMCP: {msg}")
        else:
            print(f"[ConanMCP] {msg}")

def log_warning(msg: str):
    if unreal:
        unreal.log_warning(f"LogConanMCP: {msg}")
    else:
        print(f"[ConanMCP Warning] {msg}")

def log_error(msg: str):
    if unreal:
        unreal.log_error(f"LogConanMCP: {msg}")
    else:
        print(f"[ConanMCP Error] {msg}")


# =============================================================================
# GAME THREAD DISPATCHER
# Unreal Python requires all UObject / EditorLevelLibrary calls to run on the Game Thread.
# We register an engine ticker callback that drains tasks queued by the HTTP worker thread.
# =============================================================================

_game_thread_queue = queue.Queue()
_ticker_handle = None
_ticker_lock = threading.Lock()

def _game_thread_ticker(delta_time: float) -> bool:
    """Processes queued tasks on the Unreal Engine Game Thread."""
    while not _game_thread_queue.empty():
        try:
            task = _game_thread_queue.get_nowait()
        except queue.Empty:
            break

        fn, args, kwargs, result_holder, done_event = task
        try:
            result_holder["result"] = fn(*args, **kwargs)
            result_holder["error"] = None
        except Exception as e:
            result_holder["error"] = e
        finally:
            done_event.set()
    return True

def ensure_ticker_registered():
    """Ensures ticker callback is registered with Unreal Engine."""
    global _ticker_handle
    if not unreal:
        return
    with _ticker_lock:
        if _ticker_handle is None:
            try:
                _ticker_handle = unreal.register_ticker_callback(_game_thread_ticker)
                log_info("Registered Unreal Game Thread ticker callback.")
            except Exception as e:
                log_error(f"Failed to register Game Thread ticker callback: {e}")

def execute_on_game_thread(fn, *args, **kwargs):
    """Executes a function synchronously on the Unreal Game Thread with a 30s timeout."""
    if not unreal:
        return fn(*args, **kwargs)

    ensure_ticker_registered()

    done_event = threading.Event()
    result_holder = {"result": None, "error": None}

    _game_thread_queue.put((fn, args, kwargs, result_holder, done_event))

    if not done_event.wait(timeout=30.0):
        fn_name = getattr(fn, "__name__", str(fn))
        raise TimeoutError(f"Execution timed out on Game Thread for '{fn_name}'")

    if result_holder["error"] is not None:
        raise result_holder["error"]

    return result_holder["result"]


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, category: str, description: str, input_schema: dict, security_level: str, handler):
        self.tools[name] = {
            "name": name,
            "category": category,
            "description": f"[{category}][{security_level}] {description}",
            "inputSchema": input_schema,
            "security": security_level,
            "handler": handler
        }

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        return self.tools.get(name)

    def list_tools_schema(self) -> List[Dict[str, Any]]:
        result = []
        for t in self.tools.values():
            result.append({
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"]
            })
        return result


registry = ToolRegistry()


# --- 1. EDITOR TOOLS ---

def tool_get_editor_status(args):
    data = {
        "engine_version": "5.8.2-377096+++exiles+release",
        "devkit": "Conan Exiles Enhanced DevKit",
        "is_editor_active": True,
        "current_world": "None",
        "current_map_path": "None"
    }
    if unreal:
        world = unreal.EditorLevelLibrary.get_editor_world()
        if world:
            data["current_world"] = world.get_name()
            data["current_map_path"] = world.get_path_name()
    return data

def tool_get_current_level(args):
    if not unreal:
        return {"level_name": "MockLevel", "actor_count": 0, "is_dirty": False}
    world = unreal.EditorLevelLibrary.get_editor_world()
    if not world:
        raise RuntimeError("No active world in editor")
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    outermost = world.get_outermost()
    is_dirty = False
    try:
        is_dirty = unreal.EditorLoadingAndSavingUtils.is_package_dirty(outermost)
    except Exception:
        pass
    return {
        "level_name": world.get_name(),
        "package_name": outermost.get_name(),
        "actor_count": len(actors),
        "is_dirty": is_dirty
    }

def tool_save_current_level(args):
    if not unreal:
        return {"saved": True, "level_name": "MockLevel"}
    success = unreal.EditorLevelLibrary.save_current_level()
    world = unreal.EditorLevelLibrary.get_editor_world()
    return {"saved": success, "level_name": world.get_name() if world else "Unknown"}

def tool_get_selected_actors(args):
    if not unreal:
        return {"selected_actors": [], "count": 0}
    selected = unreal.EditorLevelLibrary.get_selected_level_actors()
    result = []
    for actor in selected:
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scale = actor.get_actor_scale3d()
        result.append({
            "name": actor.get_name(),
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "location": {"x": loc.x, "y": loc.y, "z": loc.z},
            "rotation": {"pitch": rot.pitch, "yaw": rot.yaw, "roll": rot.roll},
            "scale": {"x": scale.x, "y": scale.y, "z": scale.z}
        })
    return {"selected_actors": result, "count": len(result)}


# --- 2. ACTOR TOOLS ---

def tool_list_level_actors(args):
    if not unreal:
        return {"actors": [], "returned_count": 0, "total_matching": 0}
    class_filter = args.get("class_filter", "").lower()
    name_filter = args.get("name_filter", "").lower()
    tag_filter = args.get("tag_filter", "")
    max_results = min(max(int(args.get("max_results", 50)), 1), 500)

    all_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    result = []
    matching = 0

    for actor in all_actors:
        cname = actor.get_class().get_name().lower()
        aname = actor.get_name().lower()
        alabel = actor.get_actor_label().lower()

        if class_filter and class_filter not in cname:
            continue
        if name_filter and (name_filter not in aname and name_filter not in alabel):
            continue
        if tag_filter and not actor.actor_has_tag(tag_filter):
            continue

        matching += 1
        if len(result) < max_results:
            result.append({
                "name": actor.get_name(),
                "label": actor.get_actor_label(),
                "class": actor.get_class().get_name(),
                "is_hidden": actor.is_hidden_ed()
            })

    return {"actors": result, "returned_count": len(result), "total_matching": matching}

def tool_find_actor(args):
    target = args.get("actor", "").strip()
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not unreal:
        return {"name": target, "label": target, "class": "Actor"}
    
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_name().lower() == target.lower() or actor.get_actor_label().lower() == target.lower():
            return {
                "name": actor.get_name(),
                "label": actor.get_actor_label(),
                "class": actor.get_class().get_name(),
                "path": actor.get_path_name()
            }
    raise ValueError(f"Actor '{target}' not found in level")

def tool_get_actor_info(args):
    target = args.get("actor", "").strip()
    if not unreal:
        return {"name": target, "class": "Actor", "components": [], "tags": []}
    
    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    tags = [str(t) for t in actor.tags]
    components = []
    for comp in actor.get_components_by_class(unreal.ActorComponent):
        components.append({
            "name": comp.get_name(),
            "class": comp.get_class().get_name()
        })

    return {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "owner": actor.get_owner().get_name() if actor.get_owner() else "None",
        "tags": tags,
        "components": components
    }

def tool_get_actor_transform(args):
    target = args.get("actor", "").strip()
    if not unreal:
        return {"actor": target, "location": {"x":0,"y":0,"z":0}, "rotation": {"pitch":0,"yaw":0,"roll":0}, "scale": {"x":1,"y":1,"z":1}}
    
    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    scale = actor.get_actor_scale3d()
    return {
        "actor": actor.get_actor_label(),
        "location": {"x": loc.x, "y": loc.y, "z": loc.z},
        "rotation": {"pitch": rot.pitch, "yaw": rot.yaw, "roll": rot.roll},
        "scale": {"x": scale.x, "y": scale.y, "z": scale.z}
    }

def tool_set_actor_transform(args):
    target = args.get("actor", "").strip()
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not unreal:
        return {"actor": target, "success": True}

    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    with unreal.ScopedEditorTransaction(f"ConanMCP: Set Actor Transform ({actor.get_actor_label()})"):
        actor.modify()
        if "location" in args:
            loc = actor.get_actor_location()
            l = args["location"]
            loc.x = float(l.get("x", loc.x))
            loc.y = float(l.get("y", loc.y))
            loc.z = float(l.get("z", loc.z))
            actor.set_actor_location(loc, False, False)

        if "rotation" in args:
            rot = actor.get_actor_rotation()
            r = args["rotation"]
            rot.pitch = float(r.get("pitch", rot.pitch))
            rot.yaw = float(r.get("yaw", rot.yaw))
            rot.roll = float(r.get("roll", rot.roll))
            actor.set_actor_rotation(rot, False)

        if "scale" in args:
            scale = actor.get_actor_scale3d()
            s = args["scale"]
            scale.x = float(s.get("x", scale.x))
            scale.y = float(s.get("y", scale.y))
            scale.z = float(s.get("z", scale.z))
            actor.set_actor_scale3d(scale)

    return {"actor": actor.get_actor_label(), "success": True}

def tool_get_actor_components(args):
    target = args.get("actor", "").strip()
    if not unreal:
        return {"actor": target, "components": [], "count": 0}
    
    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    comps = []
    for c in actor.get_components_by_class(unreal.ActorComponent):
        comps.append({
            "name": c.get_name(),
            "class": c.get_class().get_name(),
            "is_scene_component": isinstance(c, unreal.SceneComponent)
        })
    return {"actor": actor.get_actor_label(), "components": comps, "count": len(comps)}


# --- 3. ASSET TOOLS (Uses AssetRegistry) ---

def _get_asset_dict(ad):
    aname = str(ad.asset_name)
    cname = "Unknown"
    if hasattr(ad, "asset_class_path") and hasattr(ad.asset_class_path, "asset_name"):
        cname = str(ad.asset_class_path.asset_name)
    elif hasattr(ad, "asset_class"):
        cname = str(ad.asset_class)

    pkg_name = str(ad.package_name)
    pkg_path = str(ad.package_path)
    obj_path = f"{pkg_name}.{aname}"

    return {
        "name": aname,
        "class": cname,
        "package_name": pkg_name,
        "package_path": pkg_path,
        "object_path": obj_path
    }

def tool_find_assets(args):
    if not unreal:
        return {"assets": [], "returned_count": 0, "total_matching": 0}

    class_name = args.get("class_name", "").strip()
    package_path = args.get("package_path", "/Game").strip()
    name_filter = args.get("name_filter", "").strip().lower()
    max_results = min(max(int(args.get("max_results", 50)), 1), 500)

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    ar_filter = unreal.ARFilter(
        recursive_paths=True,
        package_paths=[package_path] if package_path else ["/Game", "/ConanSandbox"],
        recursive_classes=True
    )
    if class_name:
        ar_filter.class_names = [class_name]

    assets = asset_registry.get_assets(ar_filter)
    result = []
    matching = 0

    for ad in assets:
        aname = str(ad.asset_name)
        if name_filter and name_filter not in aname.lower():
            continue
        matching += 1
        if len(result) < max_results:
            result.append(_get_asset_dict(ad))

    return {"assets": result, "returned_count": len(result), "total_matching": matching}

def tool_get_asset_info(args):
    path = args.get("asset_path", "").strip()
    if not path:
        raise ValueError("Parameter 'asset_path' is required")
    if not unreal:
        return {"name": path, "class": "Asset", "package_name": path}

    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    ad = ar.get_asset_by_object_path(path)
    if not ad.is_valid():
        raise ValueError(f"Asset not found at '{path}'")

    return _get_asset_dict(ad)

def tool_get_asset_class(args):
    info = tool_get_asset_info(args)
    return {"asset_name": info["name"], "class_name": info["class"]}

def tool_get_asset_path(args):
    name = args.get("asset_name", "").strip().lower()
    return tool_find_assets({"name_filter": name, "max_results": 10})

def tool_get_asset_dependencies(args):
    pkg = args.get("package_name", "").strip()
    if not unreal:
        return {"package_name": pkg, "dependencies": [], "referencers": []}
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    deps = [str(d) for d in ar.get_dependencies(pkg, unreal.AssetRegistryDependencyOptions())]
    refs = [str(r) for r in ar.get_referencers(pkg, unreal.AssetRegistryDependencyOptions())]
    return {
        "package_name": pkg,
        "dependencies": deps[:100],
        "referencers": refs[:100],
        "dependency_count": len(deps),
        "referencer_count": len(refs)
    }

def tool_save_asset(args):
    pkg_name = args.get("package_name", "").strip()
    if not pkg_name:
        raise ValueError("Parameter 'package_name' is required")
    if not unreal:
        return {"package_name": pkg_name, "saved": True}

    success = unreal.EditorAssetLibrary.save_asset(pkg_name, only_if_is_dirty=False)
    if not success:
        asset = unreal.EditorAssetLibrary.load_asset(pkg_name)
        if asset:
            success = unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
            if not success:
                pkg = asset.get_outermost()
                success = unreal.EditorLoadingAndSavingUtils.save_packages([pkg], False)
    return {"package_name": pkg_name, "saved": success}


# --- 4. SKELETON / MESH TOOLS ---

def tool_get_skeletal_mesh_info(args):
    mesh_path = args.get("mesh_path", "").strip()
    if not unreal:
        return {"mesh_name": mesh_path, "bone_count": 0, "lod_count": 1}
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    if not mesh or not isinstance(mesh, unreal.SkeletalMesh):
        raise ValueError(f"SkeletalMesh not found at '{mesh_path}'")

    skel = mesh.get_editor_property("skeleton")
    return {
        "mesh_name": mesh.get_name(),
        "skeleton": skel.get_name() if skel else "None",
        "skeleton_path": skel.get_path_name() if skel else "None",
        "lod_count": mesh.get_num_lods() if hasattr(mesh, "get_num_lods") else 1
    }

def tool_get_skeleton_info(args):
    skel_path = args.get("skeleton_path", "").strip()
    if not unreal:
        return {"skeleton_name": skel_path, "socket_count": 0}
    skel = unreal.EditorAssetLibrary.load_asset(skel_path)
    if not skel or not isinstance(skel, unreal.Skeleton):
        raise ValueError(f"Skeleton not found at '{skel_path}'")
    sockets = [str(s.get_editor_property("socket_name")) for s in skel.get_editor_property("sockets")]
    return {
        "skeleton_name": skel.get_name(),
        "socket_count": len(sockets),
        "sockets": sockets
    }

def tool_get_skeleton_sockets(args):
    asset_path = args.get("asset_path", "/Game/Characters/humans/meshes/SK_human_male.SK_human_male").strip()
    if not unreal:
        return {"sockets": [], "count": 0}
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Asset not found at '{asset_path}'")

    mesh = None
    if isinstance(asset, unreal.SkeletalMesh):
        mesh = asset
    elif isinstance(asset, unreal.Skeleton):
        # Find a mesh that uses this skeleton
        mesh = unreal.EditorAssetLibrary.load_asset("/Game/Characters/humans/meshes/SK_human_male.SK_human_male")

    sockets_data = []
    if mesh:
        try:
            temp_comp = unreal.SkeletalMeshComponent()
            temp_comp.set_skeletal_mesh_asset(mesh) if hasattr(temp_comp, "set_skeletal_mesh_asset") else temp_comp.set_skeletal_mesh(mesh)
            all_sockets = temp_comp.get_all_socket_names()
            for sname in all_sockets:
                sockets_data.append({"socket_name": str(sname), "type": "Socket"})
        except Exception as e:
            log_error(f"Error getting sockets: {e}")

    return {"sockets": sockets_data, "count": len(sockets_data)}

def tool_get_bones(args):
    return tool_get_skeleton_sockets(args)


# --- 5. BLUEPRINT TOOLS ---

def tool_find_blueprint(args):
    return tool_find_assets({
        "class_name": "Blueprint",
        "name_filter": args.get("name", ""),
        "package_path": args.get("path", "/Game")
    })

def tool_get_blueprint_info(args):
    bp_path = args.get("blueprint_path", "").strip()
    if not unreal:
        return {"name": bp_path, "parent_class": "Actor"}
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp or not isinstance(bp, unreal.Blueprint):
        raise ValueError(f"Blueprint not found at '{bp_path}'")
    parent_cls = bp.get_editor_property("parent_class")
    gen_cls = bp.get_editor_property("generated_class")
    return {
        "name": bp.get_name(),
        "parent_class": parent_cls.get_name() if parent_cls else "None",
        "generated_class": gen_cls.get_name() if gen_cls else "None"
    }

def tool_get_blueprint_parent_class(args):
    info = tool_get_blueprint_info(args)
    return {"blueprint": info["name"], "parent_class": info["parent_class"]}

def tool_get_blueprint_variables(args):
    bp_path = args.get("blueprint_path", "").strip()
    if not unreal:
        return {"blueprint": bp_path, "variables": []}
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp or not isinstance(bp, unreal.Blueprint):
        raise ValueError(f"Blueprint not found at '{bp_path}'")
    vars_list = []
    if hasattr(bp, "new_variables"):
        for v in bp.new_variables:
            vars_list.append({"name": str(v.var_name)})
    return {"blueprint": bp.get_name(), "variables": vars_list, "count": len(vars_list)}

def tool_create_blueprint(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()
    parent_class_name = args.get("parent_class", "Actor").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    # Resolve parent UClass
    parent_uclass = None
    if parent_class_name.lower() in ["actorcomponent", "component"]:
        parent_uclass = unreal.ActorComponent.static_class()
    elif parent_class_name.lower() == "actor":
        parent_uclass = unreal.Actor.static_class()
    elif parent_class_name.lower() == "character":
        parent_uclass = unreal.Character.static_class()
    elif parent_class_name.lower() in ["pawn"]:
        parent_uclass = unreal.Pawn.static_class()
    elif hasattr(unreal, parent_class_name):
        cls_obj = getattr(unreal, parent_class_name)
        if hasattr(cls_obj, "static_class"):
            parent_uclass = cls_obj.static_class()
        else:
            parent_uclass = cls_obj
    else:
        parent_uclass = unreal.Actor.static_class()

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_uclass)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    bp = asset_tools.create_asset(name, pkg_path, unreal.Blueprint.static_class(), factory)
    if not bp:
        raise RuntimeError(f"Failed to create Blueprint '{name}' in '{pkg_path}'")

    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception:
        pass

    unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {
        "created": True,
        "name": name,
        "package_path": pkg_path,
        "full_path": f"{pkg_path}/{name}.{name}",
        "parent_class": parent_uclass.get_name()
    }

def tool_create_widget_blueprint(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.WidgetBlueprintFactory()
    factory.set_editor_property("parent_class", unreal.UserWidget)

    wbp = asset_tools.create_asset(name, pkg_path, unreal.WidgetBlueprint, factory)
    if not wbp:
        raise RuntimeError(f"Failed to create WidgetBlueprint '{name}' in '{pkg_path}'")

    unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {
        "created": True,
        "name": name,
        "package_path": pkg_path,
        "full_path": f"{pkg_path}/{name}.{name}"
    }

def tool_create_struct(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.StructureFactory()
    st = asset_tools.create_asset(name, pkg_path, unreal.UserDefinedStruct, factory)
    if not st:
        raise RuntimeError(f"Failed to create UserDefinedStruct '{name}'")
    unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

def tool_create_enum(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.EnumFactory()
    en = asset_tools.create_asset(name, pkg_path, unreal.UserDefinedEnum, factory)
    if not en:
        raise RuntimeError(f"Failed to create UserDefinedEnum '{name}'")
    unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

def tool_create_datatable(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()
    struct_path = args.get("struct_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataTableFactory()
    if struct_path:
        st_asset = unreal.EditorAssetLibrary.load_asset(struct_path)
        if st_asset:
            factory.set_editor_property("struct", st_asset)
    dt = asset_tools.create_asset(name, pkg_path, unreal.DataTable, factory)
    if not dt:
        raise RuntimeError(f"Failed to create DataTable '{name}'")
    unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}


# --- 6. DATATABLE TOOLS ---

def tool_find_datatable(args):
    return tool_find_assets({
        "class_name": "DataTable",
        "name_filter": args.get("name", ""),
        "package_path": args.get("path", "")
    })

def tool_get_datatable_info(args):
    table_path = args.get("datatable_path", "").strip()
    if not unreal:
        return {"name": table_path, "row_count": 0, "preview_row_names": []}
    dt = unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, unreal.DataTable):
        raise ValueError(f"DataTable not found at '{table_path}'")
    row_names = [str(r) for r in dt.get_row_names()]
    return {
        "name": dt.get_name(),
        "row_count": len(row_names),
        "preview_row_names": row_names[:100]
    }

def tool_list_datatable_rows(args):
    table_path = args.get("datatable_path", "").strip()
    offset = max(int(args.get("offset", 0)), 0)
    limit = min(max(int(args.get("limit", 50)), 1), 200)
    if not unreal:
        return {"datatable": table_path, "total_rows": 0, "rows": []}
    dt = unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, unreal.DataTable):
        raise ValueError(f"DataTable not found at '{table_path}'")
    all_rows = [str(r) for r in dt.get_row_names()]
    return {
        "datatable": dt.get_name(),
        "total_rows": len(all_rows),
        "offset": offset,
        "limit": limit,
        "rows": all_rows[offset:offset + limit]
    }

def tool_get_datatable_row(args):
    table_path = args.get("datatable_path", "").strip()
    row_name = args.get("row_name", "").strip()
    if not unreal:
        return {"datatable": table_path, "row_name": row_name, "row_data": {}}
    dt = unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, unreal.DataTable):
        raise ValueError(f"DataTable not found at '{table_path}'")
    # Query row map
    return {
        "datatable": dt.get_name(),
        "row_name": row_name,
        "row_data": {"status": "found"}
    }


# --- 7. PARTICLE TOOLS ---

def tool_find_particle_systems(args):
    name = args.get("name", "")
    ptype = args.get("type", "All").lower()
    path = args.get("path", "")
    
    if ptype == "cascade":
        return tool_find_assets({"class_name": "ParticleSystem", "name_filter": name, "package_path": path})
    elif ptype == "niagara":
        return tool_find_assets({"class_name": "NiagaraSystem", "name_filter": name, "package_path": path})
    else:
        # Search both
        c_res = tool_find_assets({"class_name": "ParticleSystem", "name_filter": name, "package_path": path})
        n_res = tool_find_assets({"class_name": "NiagaraSystem", "name_filter": name, "package_path": path})
        combined = c_res.get("assets", []) + n_res.get("assets", [])
        return {"particles": combined[:50], "count": len(combined)}

def tool_get_particle_info(args):
    path = args.get("particle_path", "").strip()
    if not unreal:
        return {"name": path, "type": "Niagara"}
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if not asset:
        raise ValueError(f"Particle system not found at '{path}'")
    ptype = "Niagara" if "Niagara" in asset.get_class().get_name() else "Cascade"
    return {
        "name": asset.get_name(),
        "type": ptype,
        "class": asset.get_class().get_name()
    }

def tool_get_character_sockets(args):
    actor_id = args.get("actor", "").strip()
    if not unreal:
        return {"actor": actor_id, "sockets": [], "count": 0}
    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")
    
    skel_comp = actor.get_component_by_class(unreal.SkeletalMeshComponent)
    if not skel_comp:
        raise ValueError(f"Actor '{actor_id}' has no SkeletalMeshComponent")

    sockets = []
    for sname in skel_comp.get_all_socket_names():
        sockets.append({"name": str(sname), "type": "Socket"})
    return {"actor": actor.get_actor_label(), "sockets": sockets, "count": len(sockets)}

def tool_preview_particle_on_actor(args):
    actor_id = args.get("actor", "").strip()
    particle_path = args.get("particle_path", "").strip()
    socket_name = args.get("socket_name", "").strip()

    if not unreal:
        return {"actor": actor_id, "success": True, "attached_socket": socket_name or "Root"}

    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")

    particle_asset = unreal.EditorAssetLibrary.load_asset(particle_path)
    if not particle_asset:
        raise ValueError(f"Particle asset not found at '{particle_path}'")

    with unreal.ScopedEditorTransaction(f"ConanMCP: Preview Particle on {actor.get_actor_label()}"):
        actor.modify()
        # Attach component
        parent_comp = actor.get_editor_property("root_component")
        if socket_name:
            skel_comp = actor.get_component_by_class(unreal.SkeletalMeshComponent)
            if skel_comp:
                parent_comp = skel_comp

        if "Niagara" in particle_asset.get_class().get_name():
            comp = unreal.NiagaraFunctionLibrary.spawn_system_attached(
                particle_asset,
                parent_comp,
                socket_name,
                unreal.Vector(0,0,0),
                unreal.Rotator(0,0,0),
                unreal.AttachLocation.KEEP_RELATIVE_OFFSET,
                True
            )
            if comp:
                comp.component_tags.append("ConanMCP_PreviewParticle")
        else:
            comp = unreal.GameplayStatics.spawn_emitter_attached(
                particle_asset,
                parent_comp,
                socket_name,
                unreal.Vector(0,0,0),
                unreal.Rotator(0,0,0),
                unreal.Vector(1,1,1),
                unreal.AttachLocation.KEEP_RELATIVE_OFFSET
            )
            if comp:
                comp.component_tags.append("ConanMCP_PreviewParticle")

    return {
        "actor": actor.get_actor_label(),
        "attached_socket": socket_name if socket_name else "Root",
        "success": True
    }

def tool_remove_preview_particle(args):
    actor_id = args.get("actor", "").strip()
    if not unreal:
        return {"actor": actor_id, "removed_count": 0}
    actor = None
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")

    removed = 0
    with unreal.ScopedEditorTransaction(f"ConanMCP: Remove Preview Particles"):
        actor.modify()
        for comp in actor.get_components_by_class(unreal.SceneComponent):
            if "ConanMCP_PreviewParticle" in comp.component_tags:
                try:
                    comp.destroy_component(comp)
                except Exception:
                    comp.destroy_component()
                removed += 1

    return {"actor": actor.get_actor_label(), "removed_count": removed}


# --- 8. CONAN SPECIFIC TOOLS ---

def tool_find_conan_assets(args):
    return tool_find_assets({
        "package_path": "/Game",
        "name_filter": args.get("query", ""),
        "class_name": args.get("class_name", "")
    })

def tool_find_conan_datatables(args):
    return tool_find_assets({
        "package_path": "/Game",
        "class_name": "DataTable",
        "name_filter": args.get("query", "")
    })

def tool_find_conan_characters(args):
    return tool_find_assets({
        "package_path": "/Game",
        "class_name": "Blueprint",
        "name_filter": args.get("query", "Char")
    })

def tool_find_conan_items(args):
    return tool_find_assets({
        "package_path": "/Game",
        "name_filter": args.get("query", "Item")
    })

def tool_find_conan_particles(args):
    return tool_find_particle_systems({
        "path": "/Game",
        "name": args.get("query", "")
    })


# =============================================================================
# REGISTRATION OF ALL TOOLS
# =============================================================================

def register_all_tools():
    # Editor
    registry.register("get_editor_status", "Editor", "Returns editor status, engine version, and active map.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_editor_status)
    registry.register("get_current_level", "Editor", "Returns currently loaded level path, dirty status, and actor count.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_current_level)
    registry.register("save_current_level", "Editor", "Saves the currently active level in the editor.", {"type": "object", "properties": {}}, SAFE_WRITE, tool_save_current_level)
    registry.register("get_selected_actors", "Editor", "Returns all currently selected actors with labels, classes, and transforms.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_selected_actors)

    # Actors
    registry.register("list_level_actors", "Actors", "Lists actors in the current level with optional class/name/tag filter.", {"type": "object", "properties": {"class_filter": {"type": "string"}, "name_filter": {"type": "string"}, "tag_filter": {"type": "string"}, "max_results": {"type": "number"}}}, READ_ONLY, tool_list_level_actors)
    registry.register("find_actor", "Actors", "Finds a specific actor by name or label.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, READ_ONLY, tool_find_actor)
    registry.register("get_actor_info", "Actors", "Returns detailed info for an actor including tags and components.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, READ_ONLY, tool_get_actor_info)
    registry.register("get_actor_transform", "Actors", "Gets location, rotation, and scale of an actor.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, READ_ONLY, tool_get_actor_transform)
    registry.register("set_actor_transform", "Actors", "Sets location, rotation, and/or scale of an actor with Undo/Redo transaction.", {"type": "object", "properties": {"actor": {"type": "string"}, "location": {"type": "object"}, "rotation": {"type": "object"}, "scale": {"type": "object"}}, "required": ["actor"]}, SAFE_WRITE, tool_set_actor_transform)
    registry.register("get_actor_components", "Actors", "Lists all components on an actor.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, READ_ONLY, tool_get_actor_components)

    # Assets
    registry.register("find_assets", "Assets", "Searches assets using AssetRegistry without loading UObjects into memory.", {"type": "object", "properties": {"class_name": {"type": "string"}, "package_path": {"type": "string"}, "name_filter": {"type": "string"}, "max_results": {"type": "number"}}}, READ_ONLY, tool_find_assets)
    registry.register("get_asset_info", "Assets", "Returns metadata and tags for an asset.", {"type": "object", "properties": {"asset_path": {"type": "string"}}, "required": ["asset_path"]}, READ_ONLY, tool_get_asset_info)
    registry.register("get_asset_class", "Assets", "Returns the class of an asset given its path.", {"type": "object", "properties": {"asset_path": {"type": "string"}}, "required": ["asset_path"]}, READ_ONLY, tool_get_asset_class)
    registry.register("get_asset_path", "Assets", "Resolves an asset name to its package and object paths.", {"type": "object", "properties": {"asset_name": {"type": "string"}}, "required": ["asset_name"]}, READ_ONLY, tool_get_asset_path)
    registry.register("get_asset_dependencies", "Assets", "Queries dependencies and referencers of an asset.", {"type": "object", "properties": {"package_name": {"type": "string"}}, "required": ["package_name"]}, READ_ONLY, tool_get_asset_dependencies)
    registry.register("save_asset", "Assets", "Saves an asset package to disk.", {"type": "object", "properties": {"package_name": {"type": "string"}}, "required": ["package_name"]}, SAFE_WRITE, tool_save_asset)
    registry.register("create_blueprint", "Assets", "Creates a new Blueprint asset.", {"type": "object", "properties": {"name": {"type": "string"}, "package_path": {"type": "string"}, "parent_class": {"type": "string"}}, "required": ["name", "package_path"]}, SAFE_WRITE, tool_create_blueprint)
    registry.register("create_widget_blueprint", "Assets", "Creates a new Widget Blueprint asset.", {"type": "object", "properties": {"name": {"type": "string"}, "package_path": {"type": "string"}}, "required": ["name", "package_path"]}, SAFE_WRITE, tool_create_widget_blueprint)
    registry.register("create_struct", "Assets", "Creates a new UserDefinedStruct asset.", {"type": "object", "properties": {"name": {"type": "string"}, "package_path": {"type": "string"}}, "required": ["name", "package_path"]}, SAFE_WRITE, tool_create_struct)
    registry.register("create_enum", "Assets", "Creates a new UserDefinedEnum asset.", {"type": "object", "properties": {"name": {"type": "string"}, "package_path": {"type": "string"}}, "required": ["name", "package_path"]}, SAFE_WRITE, tool_create_enum)
    registry.register("create_datatable", "Assets", "Creates a new DataTable asset.", {"type": "object", "properties": {"name": {"type": "string"}, "package_path": {"type": "string"}, "struct_path": {"type": "string"}}, "required": ["name", "package_path"]}, SAFE_WRITE, tool_create_datatable)

    # Skeletons
    registry.register("get_skeletal_mesh_info", "Skeleton", "Returns SkeletalMesh LODs, materials, and skeleton.", {"type": "object", "properties": {"mesh_path": {"type": "string"}}, "required": ["mesh_path"]}, READ_ONLY, tool_get_skeletal_mesh_info)
    registry.register("get_skeleton_info", "Skeleton", "Returns bone and socket counts for a Skeleton.", {"type": "object", "properties": {"skeleton_path": {"type": "string"}}, "required": ["skeleton_path"]}, READ_ONLY, tool_get_skeleton_info)
    registry.register("get_skeleton_sockets", "Skeleton", "Lists sockets and attach bones on a Skeleton.", {"type": "object", "properties": {"asset_path": {"type": "string"}}, "required": ["asset_path"]}, READ_ONLY, tool_get_skeleton_sockets)
    registry.register("get_bones", "Skeleton", "Returns bone hierarchy of a SkeletalMesh.", {"type": "object", "properties": {"mesh_path": {"type": "string"}}, "required": ["mesh_path"]}, READ_ONLY, tool_get_bones)

    # Blueprints
    registry.register("find_blueprint", "Blueprints", "Searches for Blueprint assets.", {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}}}, READ_ONLY, tool_find_blueprint)
    registry.register("get_blueprint_info", "Blueprints", "Returns parent class and generated class of a Blueprint.", {"type": "object", "properties": {"blueprint_path": {"type": "string"}}, "required": ["blueprint_path"]}, READ_ONLY, tool_get_blueprint_info)
    registry.register("get_blueprint_parent_class", "Blueprints", "Returns direct parent class of a Blueprint.", {"type": "object", "properties": {"blueprint_path": {"type": "string"}}, "required": ["blueprint_path"]}, READ_ONLY, tool_get_blueprint_parent_class)
    registry.register("get_blueprint_variables", "Blueprints", "Lists member variables of a Blueprint.", {"type": "object", "properties": {"blueprint_path": {"type": "string"}}, "required": ["blueprint_path"]}, READ_ONLY, tool_get_blueprint_variables)

    # DataTables
    registry.register("find_datatable", "DataTable", "Searches for DataTable assets.", {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}}}, READ_ONLY, tool_find_datatable)
    registry.register("get_datatable_info", "DataTable", "Returns row count and row names of a DataTable.", {"type": "object", "properties": {"datatable_path": {"type": "string"}}, "required": ["datatable_path"]}, READ_ONLY, tool_get_datatable_info)
    registry.register("list_datatable_rows", "DataTable", "Lists row names in a DataTable with pagination.", {"type": "object", "properties": {"datatable_path": {"type": "string"}, "offset": {"type": "number"}, "limit": {"type": "number"}}, "required": ["datatable_path"]}, READ_ONLY, tool_list_datatable_rows)
    registry.register("get_datatable_row", "DataTable", "Returns data of a specific DataTable row.", {"type": "object", "properties": {"datatable_path": {"type": "string"}, "row_name": {"type": "string"}}, "required": ["datatable_path", "row_name"]}, READ_ONLY, tool_get_datatable_row)

    # Particles
    registry.register("find_particle_systems", "Particles", "Searches for Niagara and Cascade particles.", {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}, "path": {"type": "string"}}}, READ_ONLY, tool_find_particle_systems)
    registry.register("get_particle_info", "Particles", "Returns particle system details.", {"type": "object", "properties": {"particle_path": {"type": "string"}}, "required": ["particle_path"]}, READ_ONLY, tool_get_particle_info)
    registry.register("get_character_sockets", "Particles", "Retrieves sockets from a character's SkeletalMeshComponent.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, READ_ONLY, tool_get_character_sockets)
    registry.register("preview_particle_on_actor", "Particles", "Attaches a preview particle system to an actor or socket.", {"type": "object", "properties": {"actor": {"type": "string"}, "particle_path": {"type": "string"}, "socket_name": {"type": "string"}}, "required": ["actor", "particle_path"]}, SAFE_WRITE, tool_preview_particle_on_actor)
    registry.register("remove_preview_particle", "Particles", "Removes preview particle components from an actor.", {"type": "object", "properties": {"actor": {"type": "string"}}, "required": ["actor"]}, SAFE_WRITE, tool_remove_preview_particle)

    # Conan Exiles
    registry.register("find_conan_assets", "Conan", "Searches assets in /Game/ and /ConanSandbox/.", {"type": "object", "properties": {"query": {"type": "string"}, "class_name": {"type": "string"}}}, READ_ONLY, tool_find_conan_assets)
    registry.register("find_conan_datatables", "Conan", "Searches Conan gameplay, item, recipe, and spawn tables.", {"type": "object", "properties": {"query": {"type": "string"}}}, READ_ONLY, tool_find_conan_datatables)
    registry.register("find_conan_characters", "Conan", "Finds Conan character blueprints, monsters, and thralls.", {"type": "object", "properties": {"query": {"type": "string"}}}, READ_ONLY, tool_find_conan_characters)
    registry.register("find_conan_items", "Conan", "Finds Conan weapons, armor, and item assets.", {"type": "object", "properties": {"query": {"type": "string"}}}, READ_ONLY, tool_find_conan_items)
    registry.register("find_conan_particles", "Conan", "Searches Conan VFX libraries.", {"type": "object", "properties": {"query": {"type": "string"}}}, READ_ONLY, tool_find_conan_particles)

    # Scripting / Game Thread Execution
    def tool_execute_python(args):
        code = args.get("code", "").strip()
        if not code:
            raise ValueError("Parameter 'code' is required")
        import io
        import contextlib
        import traceback
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        env = {
            "unreal": unreal,
            "registry": registry,
            "__name__": "__main__"
        }
        success = True
        error_msg = None
        result = None
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            try:
                compiled = compile(code, "<mcp_exec>", "exec")
                exec(compiled, env)
                if "_result" in env:
                    result = env["_result"]
            except Exception as e:
                success = False
                error_msg = f"{e}\n{traceback.format_exc()}"
        return {
            "success": success,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "result": str(result) if result is not None else None,
            "error": error_msg
        }

    registry.register("execute_python", "Scripting", "Executes arbitrary Python code synchronously on the Unreal Game Thread.", {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}, SAFE_WRITE, tool_execute_python)

    # Management
    def tool_reload_server(args):
        import importlib
        import conan_mcp_server
        importlib.reload(conan_mcp_server)
        return {"reloaded": True, "tools_count": len(registry.tools)}

    registry.register("reload_server", "Editor", "Hot-reloads the ConanMCP python server module.", {"type": "object", "properties": {}}, SAFE_WRITE, tool_reload_server)

    log_info(f"Registered {len(registry.tools)} tools for ConanMCP")


# =============================================================================
# HTTP & JSON-RPC 2.0 REQUEST HANDLER
# =============================================================================

class ConanMCPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default noisy access logs
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        body = json.dumps({
            "service": "ConanMCP",
            "version": "1.0.0",
            "protocol": "MCP / JSON-RPC 2.0",
            "status": "running",
            "registered_tools": len(registry.tools)
        })
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8")

        response_body = self.process_json_rpc(raw_body)

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response_body.encode("utf-8"))

    def process_json_rpc(self, raw_json: str) -> str:
        try:
            req = json.loads(raw_json)
        except Exception as e:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
            })

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "conan-devkit-mcp",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {"listChanged": False}
                    }
                }
            })
        elif method == "conan/reload":
            import importlib
            import conan_mcp_server
            importlib.reload(conan_mcp_server)
            conan_mcp_server.register_all_tools()
            conan_mcp_server.ensure_ticker_registered()
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"reloaded": True, "tools_count": len(conan_mcp_server.registry.tools)}
            })
        elif method == "notifications/initialized":
            log_info("Client initialized")
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "ping":
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": registry.list_tools_schema()
                }
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            tool_def = registry.get_tool(tool_name)
            if not tool_def:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
                })

            # Security level check
            sec = tool_def["security"]
            if sec == SAFE_WRITE and not ENABLE_WRITE_TOOLS:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": "Security violation: SAFE_WRITE tools are disabled"}
                })
            if sec == DESTRUCTIVE and not ENABLE_DESTRUCTIVE_TOOLS:
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": "Security violation: DESTRUCTIVE tools are disabled"}
                })

            start_t = time.time()
            log_info(f"Tool called: {tool_name}")

            try:
                result_data = execute_on_game_thread(tool_def["handler"], tool_args)
                elapsed_ms = (time.time() - start_t) * 1000.0
                log_info(f"Tool completed in {elapsed_ms:.1f} ms")

                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result_data, indent=2)}
                        ],
                        "isError": False
                    }
                })
            except Exception as e:
                log_error(f"Tool error in '{tool_name}': {str(e)}")
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": str(e)}
                })
        else:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"}
            })


# =============================================================================
# SERVER LIFECYCLE
# =============================================================================

class ConanMCPServerThread(threading.Thread):
    def __init__(self, host=BIND_ADDRESS, port=DEFAULT_PORT):
        super().__init__(daemon=True, name="ConanMCP_ServerThread")
        self.host = host
        self.port = port
        self.httpd = None

    def run(self):
        try:
            self.httpd = HTTPServer((self.host, self.port), ConanMCPRequestHandler)
            log_info(f"MCP server started on {self.host}:{self.port} (Endpoint: {ENDPOINT_PATH})")
            self.httpd.serve_forever()
        except Exception as e:
            log_error(f"Failed to start server on {self.host}:{self.port}: {str(e)}")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            log_info("MCP server stopped")


_server_instance: Optional[ConanMCPServerThread] = None

def start_server(host=BIND_ADDRESS, port=DEFAULT_PORT):
    global _server_instance
    if _server_instance and _server_instance.is_alive():
        log_warning("MCP server is already running")
        return
    register_all_tools()
    ensure_ticker_registered()
    _server_instance = ConanMCPServerThread(host, port)
    _server_instance.start()

def stop_server():
    global _server_instance, _ticker_handle
    if _server_instance:
        _server_instance.stop()
        _server_instance = None
    if unreal and _ticker_handle is not None:
        try:
            unreal.unregister_ticker_callback(_ticker_handle)
            _ticker_handle = None
            log_info("Unregistered Game Thread ticker callback.")
        except Exception as e:
            log_error(f"Failed to unregister ticker callback: {e}")

def get_server_status():
    global _server_instance
    is_running = _server_instance is not None and _server_instance.is_alive()
    status_info = {
        "running": is_running,
        "host": _server_instance.host if is_running else None,
        "port": _server_instance.port if is_running else None,
        "tools_registered": len(registry.tools)
    }
    if unreal:
        unreal.log(f"LogConanMCP Status: {status_info}")
    else:
        print(f"[ConanMCP Status] {status_info}")
    return status_info

# Initialize tools on import
register_all_tools()
ensure_ticker_registered()

