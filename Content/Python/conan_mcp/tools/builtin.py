"""The original 46 ConanMCP tools, resources and prompts (v1.x), ported to the package layout.

Several of these are superseded by richer implementations in the domain
modules (datatables, blueprints, level ...); those register afterwards and
replace the entries of the same name.
"""

import time
import urllib.parse

from ..core import config, ue
from ..core.log import log_error
from ..core.registry import registry as _registry, resource_registry as _resource_registry, prompt_registry as _prompt_registry
from ..core.security import READ_ONLY, SAFE_WRITE, DESTRUCTIVE, validate_package_path
from ..core.sse import get_manager
from ..core.state import STATE

registry = _registry
resource_registry = _resource_registry
prompt_registry = _prompt_registry


# --- 1. EDITOR TOOLS ---

def tool_get_editor_status(args):
    data = {
        "engine_version": "5.8.2-377096+++exiles+release",
        "devkit": "Conan Exiles Enhanced DevKit",
        "is_editor_active": True,
        "current_world": "None",
        "current_map_path": "None"
    }
    if ue.unreal:
        world = ue.unreal.EditorLevelLibrary.get_editor_world()
        if world:
            data["current_world"] = world.get_name()
            data["current_map_path"] = world.get_path_name()
    return data

def tool_get_current_level(args):
    if not ue.unreal:
        return {"level_name": "MockLevel", "actor_count": 0, "is_dirty": False}
    world = ue.unreal.EditorLevelLibrary.get_editor_world()
    if not world:
        raise RuntimeError("No active world in editor")
    actors = ue.unreal.EditorLevelLibrary.get_all_level_actors()
    outermost = world.get_outermost()
    is_dirty = False
    try:
        is_dirty = ue.unreal.EditorLoadingAndSavingUtils.is_package_dirty(outermost)
    except Exception:
        pass
    return {
        "level_name": world.get_name(),
        "package_name": outermost.get_name(),
        "actor_count": len(actors),
        "is_dirty": is_dirty
    }

def tool_save_current_level(args):
    if not ue.unreal:
        return {"saved": True, "level_name": "MockLevel"}
    success = ue.unreal.EditorLevelLibrary.save_current_level()
    world = ue.unreal.EditorLevelLibrary.get_editor_world()
    return {"saved": success, "level_name": world.get_name() if world else "Unknown"}

def tool_get_selected_actors(args):
    if not ue.unreal:
        return {"selected_actors": [], "count": 0}
    selected = ue.unreal.EditorLevelLibrary.get_selected_level_actors()
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
    if not ue.unreal:
        return {"actors": [], "returned_count": 0, "total_matching": 0, "offset": 0, "limit": 50, "has_more": False}
    class_filter = args.get("class_filter", "").lower()
    name_filter = args.get("name_filter", "").lower()
    tag_filter = args.get("tag_filter", "")
    offset = max(int(args.get("offset", 0)), 0)
    limit = min(max(int(args.get("limit", args.get("max_results", 50))), 1), 500)

    all_actors = ue.unreal.EditorLevelLibrary.get_all_level_actors()
    matching_actors = []

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

        matching_actors.append(actor)

    total_matching = len(matching_actors)
    paged = matching_actors[offset:offset + limit]
    result = []
    for actor in paged:
        result.append({
            "name": actor.get_name(),
            "label": actor.get_actor_label(),
            "class": actor.get_class().get_name(),
            "is_hidden": actor.is_hidden_ed()
        })

    return {
        "actors": result,
        "returned_count": len(result),
        "total_matching": total_matching,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(result)) < total_matching
    }

def tool_find_actor(args):
    target = args.get("actor", "").strip()
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not ue.unreal:
        return {"name": target, "label": target, "class": "Actor"}
    
    for actor in ue.unreal.EditorLevelLibrary.get_all_level_actors():
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
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not ue.unreal:
        return {"name": target, "class": "Actor", "components": [], "tags": []}
    
    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    tags = [str(t) for t in actor.tags]
    components = []
    for comp in actor.get_components_by_class(ue.unreal.ActorComponent):
        components.append({
            "name": comp.get_name(),
            "class": comp.get_class().get_name()
        })

    return {
        "name": actor.get_name(),
        "label": actor.get_actor_label(),
        "class": actor.get_class().get_name(),
        "tags": tags,
        "component_count": len(components),
        "components": components
    }

def tool_get_actor_transform(args):
    target = args.get("actor", "").strip()
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not ue.unreal:
        return {
            "actor": target,
            "location": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
        }
    
    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
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
    if not ue.unreal:
        return {"actor": target, "updated": True}

    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    with ue.unreal.ScopedEditorTransaction(f"ConanMCP: Set Transform of {actor.get_actor_label()}"):
        actor.modify()
        if "location" in args:
            loc = args["location"]
            actor.set_actor_location(ue.unreal.Vector(float(loc.get("x", 0)), float(loc.get("y", 0)), float(loc.get("z", 0))), False, True)
        if "rotation" in args:
            rot = args["rotation"]
            actor.set_actor_rotation(ue.unreal.Rotator(float(rot.get("pitch", 0)), float(rot.get("yaw", 0)), float(rot.get("roll", 0))), False)
        if "scale" in args:
            scale = args["scale"]
            actor.set_actor_scale3d(ue.unreal.Vector(float(scale.get("x", 1)), float(scale.get("y", 1)), float(scale.get("z", 1))))

    return {"actor": actor.get_actor_label(), "updated": True}

def tool_get_actor_components(args):
    target = args.get("actor", "").strip()
    if not target:
        raise ValueError("Parameter 'actor' is required")
    if not ue.unreal:
        return {"actor": target, "components": [], "count": 0}
    
    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == target.lower() or a.get_actor_label().lower() == target.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{target}' not found")

    comps = []
    for c in actor.get_components_by_class(ue.unreal.ActorComponent):
        comps.append({
            "name": c.get_name(),
            "class": c.get_class().get_name(),
            "is_scene_component": isinstance(c, ue.unreal.SceneComponent)
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
    if not ue.unreal:
        return {"assets": [], "returned_count": 0, "total_matching": 0, "offset": 0, "limit": 50, "has_more": False}

    class_name = args.get("class_name", "").strip()
    package_path = args.get("package_path", "/Game").strip()
    name_filter = args.get("name_filter", "").strip().lower()
    offset = max(int(args.get("offset", 0)), 0)
    limit = min(max(int(args.get("limit", args.get("max_results", 50))), 1), 500)

    asset_registry = ue.unreal.AssetRegistryHelpers.get_asset_registry()
    ar_filter = ue.unreal.ARFilter(
        recursive_paths=True,
        package_paths=[package_path] if package_path else ["/Game", "/ConanSandbox"],
        recursive_classes=True
    )
    if class_name:
        ar_filter.class_names = [class_name]

    assets = asset_registry.get_assets(ar_filter)
    matching_ads = []

    for ad in assets:
        aname = str(ad.asset_name)
        if name_filter and name_filter not in aname.lower():
            continue
        matching_ads.append(ad)

    total_matching = len(matching_ads)
    paged_ads = matching_ads[offset:offset + limit]
    result = [_get_asset_dict(ad) for ad in paged_ads]

    return {
        "assets": result,
        "returned_count": len(result),
        "total_matching": total_matching,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(result)) < total_matching
    }

def tool_get_asset_info(args):
    path = args.get("asset_path", "").strip()
    if not path:
        raise ValueError("Parameter 'asset_path' is required")
    if not ue.unreal:
        return {"name": path, "class": "Asset", "package_name": path}

    ar = ue.unreal.AssetRegistryHelpers.get_asset_registry()
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
    if not ue.unreal:
        return {"package_name": pkg, "dependencies": [], "referencers": []}
    ar = ue.unreal.AssetRegistryHelpers.get_asset_registry()
    deps = [str(d) for d in ar.get_dependencies(pkg, ue.unreal.AssetRegistryDependencyOptions())]
    refs = [str(r) for r in ar.get_referencers(pkg, ue.unreal.AssetRegistryDependencyOptions())]
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
    if not ue.unreal:
        return {"package_name": pkg_name, "saved": True}

    success = ue.unreal.EditorAssetLibrary.save_asset(pkg_name, only_if_is_dirty=False)
    if not success:
        asset = ue.unreal.EditorAssetLibrary.load_asset(pkg_name)
        if asset:
            success = ue.unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
            if not success:
                pkg = asset.get_outermost()
                success = ue.unreal.EditorLoadingAndSavingUtils.save_packages([pkg], False)
    return {"package_name": pkg_name, "saved": success}


# --- 4. SKELETON / MESH TOOLS ---

def tool_get_skeletal_mesh_info(args):
    mesh_path = args.get("mesh_path", "").strip()
    if not ue.unreal:
        return {"mesh_name": mesh_path, "bone_count": 0, "lod_count": 1}
    mesh = ue.unreal.EditorAssetLibrary.load_asset(mesh_path)
    if not mesh or not isinstance(mesh, ue.unreal.SkeletalMesh):
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
    if not ue.unreal:
        return {"skeleton_name": skel_path, "socket_count": 0}
    skel = ue.unreal.EditorAssetLibrary.load_asset(skel_path)
    if not skel or not isinstance(skel, ue.unreal.Skeleton):
        raise ValueError(f"Skeleton not found at '{skel_path}'")
    sockets = [str(s.get_editor_property("socket_name")) for s in skel.get_editor_property("sockets")]
    return {
        "skeleton_name": skel.get_name(),
        "socket_count": len(sockets),
        "sockets": sockets
    }

def tool_get_skeleton_sockets(args):
    asset_path = args.get("asset_path", "/Game/Characters/humans/meshes/SK_human_male.SK_human_male").strip()
    if not ue.unreal:
        return {"sockets": [], "count": 0}
    asset = ue.unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        raise ValueError(f"Asset not found at '{asset_path}'")

    mesh = None
    if isinstance(asset, ue.unreal.SkeletalMesh):
        mesh = asset
    elif isinstance(asset, ue.unreal.Skeleton):
        mesh = ue.unreal.EditorAssetLibrary.load_asset("/Game/Characters/humans/meshes/SK_human_male.SK_human_male")

    sockets_data = []
    if mesh:
        try:
            temp_comp = ue.unreal.SkeletalMeshComponent()
            temp_comp.set_skeletal_mesh_asset(mesh) if hasattr(temp_comp, "set_skeletal_mesh_asset") else temp_comp.set_skeletal_mesh(mesh)
            all_sockets = temp_comp.get_all_socket_names()
            for sname in all_sockets:
                sockets_data.append({"socket_name": str(sname), "type": "Socket"})
        except Exception as e:
            log_error(f"Error getting sockets: {e}")

    return {"sockets": sockets_data, "count": len(sockets_data)}

def tool_get_bones(args):
    mesh_path = args.get("mesh_path", "/Game/Characters/humans/meshes/SK_human_male.SK_human_male").strip()
    if not ue.unreal:
        return {"mesh_path": mesh_path, "bones": [], "bone_count": 0}
    mesh = ue.unreal.EditorAssetLibrary.load_asset(mesh_path)
    if not mesh:
        raise ValueError(f"Mesh not found at '{mesh_path}'")
    bones_list = []
    try:
        temp_comp = ue.unreal.SkeletalMeshComponent()
        temp_comp.set_skeletal_mesh_asset(mesh) if hasattr(temp_comp, "set_skeletal_mesh_asset") else temp_comp.set_skeletal_mesh(mesh)
        for bname in temp_comp.get_bone_names():
            bones_list.append(str(bname))
    except Exception:
        # Fallback to sockets if bone enumeration is unavailable
        return tool_get_skeleton_sockets(args)
    return {"mesh_path": mesh_path, "bones": bones_list[:100], "bone_count": len(bones_list)}


# --- 5. BLUEPRINT TOOLS ---

def tool_find_blueprint(args):
    return tool_find_assets({
        "class_name": "Blueprint",
        "name_filter": args.get("name", ""),
        "package_path": args.get("path", "/Game"),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_get_blueprint_info(args):
    bp_path = args.get("blueprint_path", "").strip()
    if not ue.unreal:
        return {"name": bp_path, "parent_class": "Actor"}
    bp = ue.unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp or not isinstance(bp, ue.unreal.Blueprint):
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
    if not ue.unreal:
        return {"blueprint": bp_path, "variables": []}
    bp = ue.unreal.EditorAssetLibrary.load_asset(bp_path)
    if not bp or not isinstance(bp, ue.unreal.Blueprint):
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
    if not ue.unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    parent_uclass = None
    if parent_class_name.startswith("/"):
        # Blueprint asset path or /Script/Module.Class: subclass existing (e.g. Conan) content
        parent_uclass = ue.resolve_class(parent_class_name)
    elif parent_class_name.lower() in ["actorcomponent", "component"]:
        parent_uclass = ue.unreal.ActorComponent.static_class()
    elif parent_class_name.lower() == "actor":
        parent_uclass = ue.unreal.Actor.static_class()
    elif parent_class_name.lower() == "character":
        parent_uclass = ue.unreal.Character.static_class()
    elif parent_class_name.lower() in ["pawn"]:
        parent_uclass = ue.unreal.Pawn.static_class()
    elif hasattr(ue.unreal, parent_class_name):
        cls_obj = getattr(ue.unreal, parent_class_name)
        if hasattr(cls_obj, "static_class"):
            parent_uclass = cls_obj.static_class()
        else:
            parent_uclass = cls_obj
    else:
        parent_uclass = ue.unreal.Actor.static_class()

    factory = ue.unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_uclass)

    asset_tools = ue.unreal.AssetToolsHelpers.get_asset_tools()
    bp = asset_tools.create_asset(name, pkg_path, ue.unreal.Blueprint.static_class(), factory)
    if not bp:
        raise RuntimeError(f"Failed to create Blueprint '{name}' in '{pkg_path}'")

    try:
        ue.unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception:
        pass

    ue.unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
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
    if not ue.unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = ue.unreal.AssetToolsHelpers.get_asset_tools()
    factory = ue.unreal.WidgetBlueprintFactory()
    factory.set_editor_property("parent_class", ue.unreal.UserWidget)

    wbp = asset_tools.create_asset(name, pkg_path, ue.unreal.WidgetBlueprint, factory)
    if not wbp:
        raise RuntimeError(f"Failed to create WidgetBlueprint '{name}' in '{pkg_path}'")

    ue.unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
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
    if not ue.unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = ue.unreal.AssetToolsHelpers.get_asset_tools()
    factory = ue.unreal.StructureFactory()
    st = asset_tools.create_asset(name, pkg_path, ue.unreal.UserDefinedStruct, factory)
    if not st:
        raise RuntimeError(f"Failed to create UserDefinedStruct '{name}'")
    ue.unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

def tool_create_enum(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not ue.unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = ue.unreal.AssetToolsHelpers.get_asset_tools()
    factory = ue.unreal.EnumFactory()
    en = asset_tools.create_asset(name, pkg_path, ue.unreal.UserDefinedEnum, factory)
    if not en:
        raise RuntimeError(f"Failed to create UserDefinedEnum '{name}'")
    ue.unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

def tool_create_datatable(args):
    name = args.get("name", "").strip()
    pkg_path = args.get("package_path", "").strip()
    struct_path = args.get("struct_path", "").strip()

    if not name or not pkg_path:
        raise ValueError("'name' and 'package_path' are required")
    if not ue.unreal:
        return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}

    asset_tools = ue.unreal.AssetToolsHelpers.get_asset_tools()
    factory = ue.unreal.DataTableFactory()
    row_struct = None
    if args.get("copy_struct_from"):
        src = ue.unreal.EditorAssetLibrary.load_asset(args["copy_struct_from"])
        if not src or not isinstance(src, ue.unreal.DataTable):
            raise ValueError(f"DataTable '{args['copy_struct_from']}' not found")
        row_struct = src.get_editor_property("row_struct")
    elif struct_path:
        if struct_path.startswith("/Script/") and hasattr(ue.unreal, "load_object"):
            row_struct = ue.unreal.load_object(None, struct_path)
        else:
            row_struct = ue.unreal.EditorAssetLibrary.load_asset(struct_path)
        if not row_struct:
            raise ValueError(f"Row struct '{struct_path}' not found")
    if row_struct:
        factory.set_editor_property("struct", row_struct)
    dt = asset_tools.create_asset(name, pkg_path, ue.unreal.DataTable, factory)
    if not dt:
        raise RuntimeError(f"Failed to create DataTable '{name}'")
    ue.unreal.EditorAssetLibrary.save_asset(f"{pkg_path}/{name}", only_if_is_dirty=False)
    return {"created": True, "name": name, "full_path": f"{pkg_path}/{name}.{name}"}


# --- 6. DATATABLE TOOLS ---

def tool_find_datatable(args):
    return tool_find_assets({
        "class_name": "DataTable",
        "name_filter": args.get("name", ""),
        "package_path": args.get("path", ""),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_get_datatable_info(args):
    table_path = args.get("datatable_path", "").strip()
    if not ue.unreal:
        return {"name": table_path, "row_count": 0, "preview_row_names": []}
    dt = ue.unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, ue.unreal.DataTable):
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
    if not ue.unreal:
        return {"datatable": table_path, "total_rows": 0, "rows": []}
    dt = ue.unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, ue.unreal.DataTable):
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
    if not ue.unreal:
        return {"datatable": table_path, "row_name": row_name, "row_data": {}}
    dt = ue.unreal.EditorAssetLibrary.load_asset(table_path)
    if not dt or not isinstance(dt, ue.unreal.DataTable):
        raise ValueError(f"DataTable not found at '{table_path}'")
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
    offset = args.get("offset", 0)
    limit = args.get("limit", 50)
    
    if ptype == "cascade":
        return tool_find_assets({"class_name": "ParticleSystem", "name_filter": name, "package_path": path, "offset": offset, "limit": limit})
    elif ptype == "niagara":
        return tool_find_assets({"class_name": "NiagaraSystem", "name_filter": name, "package_path": path, "offset": offset, "limit": limit})
    else:
        c_res = tool_find_assets({"class_name": "ParticleSystem", "name_filter": name, "package_path": path, "limit": 200})
        n_res = tool_find_assets({"class_name": "NiagaraSystem", "name_filter": name, "package_path": path, "limit": 200})
        combined = c_res.get("assets", []) + n_res.get("assets", [])
        paged = combined[offset:offset + limit]
        return {
            "particles": paged,
            "returned_count": len(paged),
            "total_matching": len(combined),
            "offset": offset,
            "limit": limit,
            "has_more": (offset + len(paged)) < len(combined)
        }

def tool_get_particle_info(args):
    path = args.get("particle_path", "").strip()
    if not ue.unreal:
        return {"name": path, "type": "Niagara"}
    asset = ue.unreal.EditorAssetLibrary.load_asset(path)
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
    if not ue.unreal:
        return {"actor": actor_id, "sockets": [], "count": 0}
    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")
    
    skel_comp = actor.get_component_by_class(ue.unreal.SkeletalMeshComponent)
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

    if not ue.unreal:
        return {"actor": actor_id, "success": True, "attached_socket": socket_name or "Root"}

    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")

    particle_asset = ue.unreal.EditorAssetLibrary.load_asset(particle_path)
    if not particle_asset:
        raise ValueError(f"Particle asset not found at '{particle_path}'")

    with ue.unreal.ScopedEditorTransaction(f"ConanMCP: Preview Particle on {actor.get_actor_label()}"):
        actor.modify()
        parent_comp = actor.get_editor_property("root_component")
        if socket_name:
            skel_comp = actor.get_component_by_class(ue.unreal.SkeletalMeshComponent)
            if skel_comp:
                parent_comp = skel_comp

        if "Niagara" in particle_asset.get_class().get_name():
            comp = ue.unreal.NiagaraFunctionLibrary.spawn_system_attached(
                particle_asset,
                parent_comp,
                socket_name,
                ue.unreal.Vector(0,0,0),
                ue.unreal.Rotator(0,0,0),
                ue.unreal.AttachLocation.KEEP_RELATIVE_OFFSET,
                True
            )
            if comp:
                comp.component_tags.append("ConanMCP_PreviewParticle")
        else:
            comp = ue.unreal.GameplayStatics.spawn_emitter_attached(
                particle_asset,
                parent_comp,
                socket_name,
                ue.unreal.Vector(0,0,0),
                ue.unreal.Rotator(0,0,0),
                ue.unreal.Vector(1,1,1),
                ue.unreal.AttachLocation.KEEP_RELATIVE_OFFSET
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
    if not ue.unreal:
        return {"actor": actor_id, "removed_count": 0}
    actor = None
    for a in ue.unreal.EditorLevelLibrary.get_all_level_actors():
        if a.get_name().lower() == actor_id.lower() or a.get_actor_label().lower() == actor_id.lower():
            actor = a
            break
    if not actor:
        raise ValueError(f"Actor '{actor_id}' not found")

    removed = 0
    with ue.unreal.ScopedEditorTransaction("ConanMCP: Remove Preview Particles"):
        actor.modify()
        for comp in actor.get_components_by_class(ue.unreal.SceneComponent):
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
        "class_name": args.get("class_name", ""),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_find_conan_datatables(args):
    return tool_find_assets({
        "package_path": "/Game",
        "class_name": "DataTable",
        "name_filter": args.get("query", ""),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_find_conan_characters(args):
    return tool_find_assets({
        "package_path": "/Game",
        "class_name": "Blueprint",
        "name_filter": args.get("query", "Char"),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_find_conan_items(args):
    return tool_find_assets({
        "package_path": "/Game",
        "name_filter": args.get("query", "Item"),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })

def tool_find_conan_particles(args):
    return tool_find_particle_systems({
        "path": "/Game",
        "name": args.get("query", ""),
        "offset": args.get("offset", 0),
        "limit": args.get("limit", 50)
    })


# --- 9. SCRIPTING, DIAGNOSTICS & MANAGEMENT TOOLS ---

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
        "unreal": ue.unreal,
        "registry": registry,
        "resource_registry": resource_registry,
        "prompt_registry": prompt_registry,
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

def tool_get_mcp_diagnostics(args):
    now = time.time()
    uptime = round(now - STATE.server_start_time, 2)
    return {
        "mcp_protocol_version": config.PROTOCOL_VERSION,
        "server_version": config.SERVER_VERSION,
        "service": "ConanMCP",
        "uptime_seconds": uptime,
        "total_requests": STATE.request_counter,
        "total_errors": STATE.error_counter,
        "registered_tools_count": len(registry.tools),
        "registered_resources_count": len(resource_registry.resources),
        "registered_resource_templates_count": len(resource_registry.templates),
        "registered_prompts_count": len(prompt_registry.prompts),
        "active_sse_sessions": len(get_manager().sessions),
        "game_thread_queue_pending": STATE.game_thread_queue.qsize(),
        "recent_logs_buffered": len(STATE.recent_logs),
        "engine_active": ue.unreal is not None
    }

def tool_reload_server(args):
    from .. import server
    return server.reload_server_module()


# =============================================================================
# RESOURCE HANDLERS
# =============================================================================

def resource_devkit_status(uri: str) -> dict:
    world_name = "None"
    map_path = "None"
    actor_count = 0
    is_dirty = False
    if ue.unreal:
        world = ue.unreal.EditorLevelLibrary.get_editor_world()
        if world:
            world_name = world.get_name()
            map_path = world.get_path_name()
            actors = ue.unreal.EditorLevelLibrary.get_all_level_actors()
            actor_count = len(actors)
            try:
                is_dirty = ue.unreal.EditorLoadingAndSavingUtils.is_package_dirty(world.get_outermost())
            except Exception:
                pass
    return {
        "service": "ConanMCP",
        "engine_version": "5.8.2-377096+++exiles+release",
        "devkit": "Conan Exiles Enhanced DevKit",
        "is_editor_active": True if ue.unreal else False,
        "current_world": world_name,
        "current_map_path": map_path,
        "actor_count": actor_count,
        "is_dirty": is_dirty,
        "uptime_seconds": round(time.time() - STATE.server_start_time, 1),
        "registered_tools": len(registry.tools),
        "registered_resources": len(resource_registry.resources),
        "registered_prompts": len(prompt_registry.prompts)
    }

def resource_devkit_logs(uri: str) -> str:
    if not STATE.recent_logs:
        return "[ConanMCP] No logs recorded in buffer."
    return "\n".join(list(STATE.recent_logs))

def resource_devkit_outliner(uri: str) -> dict:
    if not ue.unreal:
        return {"actors": [], "count": 0}
    actors = ue.unreal.EditorLevelLibrary.get_all_level_actors()
    items = []
    for a in actors[:200]:
        items.append({
            "name": a.get_name(),
            "label": a.get_actor_label(),
            "class": a.get_class().get_name(),
            "hidden": a.is_hidden_ed()
        })
    return {"total_in_level": len(actors), "count": len(items), "actors": items}

def resource_conan_tables(uri: str) -> dict:
    if not ue.unreal:
        return {"tables": [], "count": 0}
    ar = ue.unreal.AssetRegistryHelpers.get_asset_registry()
    ar_filter = ue.unreal.ARFilter(
        recursive_paths=True,
        package_paths=["/Game", "/ConanSandbox"],
        recursive_classes=True,
        class_names=["DataTable"]
    )
    assets = ar.get_assets(ar_filter)
    tables = []
    for ad in assets[:100]:
        tables.append({
            "name": str(ad.asset_name),
            "package": str(ad.package_name)
        })
    return {"tables": tables, "count": len(tables)}

def resource_template_conan_asset(uri: str, package_path: str) -> dict:
    package_path = urllib.parse.unquote(package_path)
    if not package_path.startswith("/"):
        package_path = "/" + package_path
    validate_package_path(package_path, "package_path")
    if not ue.unreal:
        return {"package_path": package_path, "status": "Mock asset metadata"}
    ar = ue.unreal.AssetRegistryHelpers.get_asset_registry()
    ad = ar.get_asset_by_object_path(package_path)
    if not ad.is_valid():
        assets = ar.get_assets_by_package_name(package_path)
        if assets:
            ad = assets[0]
    if not ad.is_valid():
        raise ValueError(f"Asset not found at '{package_path}'")
    return _get_asset_dict(ad)


# =============================================================================
# PROMPT HANDLERS
# =============================================================================

def prompt_create_conan_item(args: dict) -> dict:
    item_name = args.get("item_name", "MyCustomSword")
    item_type = args.get("item_type", "Weapon")
    description = args.get("description", "A custom weapon for Conan Exiles")
    prompt_text = f"""You are an expert Conan Exiles DevKit modder and Unreal Engine 5 developer.
Help the user create a new {item_type} mod named '{item_name}'.
Item Description: {description}

Recommended Step-by-Step Workflow using ConanMCP:
1. Query Conan DataTables using `find_conan_datatables(query='ItemTable')` to locate the primary ItemTable.
2. Search existing {item_type} assets using `find_conan_items(query='{item_name}')` or similar archetypes to inspect their property structure.
3. If creating a new Blueprint, use `create_blueprint(name='BP_{item_name}', package_path='/Game/Mods/{item_name}', parent_class='Item')`.
4. Inspect character sockets using `get_character_sockets()` to verify hand/sheath attach points.
5. If particle effects (blood, flame, glow) are needed, search VFX using `find_conan_particles` and preview on actor sockets using `preview_particle_on_actor`.
6. Save all new assets using `save_asset(package_name=...)`.

Begin by inspecting the Conan ItemTable and archetypes for this item."""
    return {
        "description": f"Workflow for creating a custom Conan Exiles {item_type}: {item_name}",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": prompt_text}}
        ]
    }

def prompt_audit_level_performance(args: dict) -> dict:
    prompt_text = """You are an Unreal Engine 5 performance optimization expert for Conan Exiles.
Perform a performance audit of the currently active level in the Conan Exiles DevKit.

Instructions:
1. Call `get_current_level` and `get_editor_status` to determine the active map and actor count.
2. Call `list_level_actors(limit=100)` to analyze actor types and identify potential bottlenecks:
   - High density of dynamic/stationary lights.
   - Large numbers of unbatched StaticMeshActors.
   - Active preview particles or spawning emitters.
3. Review actor components and transforms using `get_actor_components` and `get_actor_transform`.
4. Summarize your findings with actionable recommendations to improve frame rate and memory footprint."""
    return {
        "description": "Audit performance and actor density of the active level",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": prompt_text}}
        ]
    }

def prompt_inspect_character_skeleton(args: dict) -> dict:
    mesh_path = args.get("mesh_path", "/Game/Characters/humans/meshes/SK_human_male.SK_human_male")
    prompt_text = f"""You are a character technical artist for Conan Exiles.
Inspect the skeletal mesh and socket structure at: '{mesh_path}'.

Instructions:
1. Call `get_skeletal_mesh_info(mesh_path='{mesh_path}')` to inspect LOD counts, skeleton bindings, and materials.
2. Call `get_skeleton_sockets(asset_path='{mesh_path}')` to list all weapon attach, armor, and VFX sockets.
3. Verify critical Conan sockets:
   - Hand_R, Hand_L (Weapons/Shields)
   - Spine2, Pelvis (Back/Sheaths/Quivers)
   - Head, Foot_L, Foot_R (Armor & Footstep VFX)
4. Report socket names and advise how to attach gear or Niagara emitters cleanly."""
    return {
        "description": f"Inspect skeleton, bones and sockets for {mesh_path}",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": prompt_text}}
        ]
    }

def prompt_debug_niagara_vfx(args: dict) -> dict:
    vfx_query = args.get("vfx_query", "Blood")
    prompt_text = f"""You are a visual effects (VFX) technical artist for Unreal Engine 5.
Search, inspect, and test particle systems matching '{vfx_query}' in the Conan DevKit.

Instructions:
1. Call `find_particle_systems(name='{vfx_query}')` to discover matching Cascade and Niagara systems.
2. For top results, call `get_particle_info(particle_path=...)` to check system type and class.
3. Check selected actor or active character in level using `get_selected_actors` or `get_character_sockets`.
4. Preview the effect on an actor socket using `preview_particle_on_actor`.
5. Once tested, remove preview particles using `remove_preview_particle`."""
    return {
        "description": f"Diagnose and preview particle systems matching '{vfx_query}'",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": prompt_text}}
        ]
    }


# =============================================================================
# REGISTRATION OF ALL TOOLS, RESOURCES & PROMPTS
# =============================================================================

def register_tools(registry):
    # Editor
    registry.register("get_editor_status", "Editor", "Returns editor status, engine version, and active map.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_editor_status)
    registry.register("get_current_level", "Editor", "Returns currently loaded level path, dirty status, and actor count.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_current_level)
    registry.register("save_current_level", "Editor", "Saves the currently active level in the editor.", {"type": "object", "properties": {}}, SAFE_WRITE, tool_save_current_level)
    registry.register("get_selected_actors", "Editor", "Returns all currently selected actors with labels, classes, and transforms.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_selected_actors)
    registry.register("get_mcp_diagnostics", "Editor", "Returns detailed MCP server diagnostics, protocol version, uptime, and queue stats.", {"type": "object", "properties": {}}, READ_ONLY, tool_get_mcp_diagnostics)

    # Actors
    registry.register("list_level_actors", "Actors", "Lists actors in the current level with pagination and optional class/name/tag filters.", {
        "type": "object",
        "properties": {
            "class_filter": {"type": "string", "description": "Optional substring to filter actor class names"},
            "name_filter": {"type": "string", "description": "Optional substring to filter actor name or label"},
            "tag_filter": {"type": "string", "description": "Optional actor gameplay tag"},
            "offset": {"type": "integer", "description": "Pagination offset (default: 0)"},
            "limit": {"type": "integer", "description": "Max results to return (default: 50, max: 500)"},
            "max_results": {"type": "integer", "description": "Legacy alias for limit"}
        }
    }, READ_ONLY, tool_list_level_actors)
    registry.register("find_actor", "Actors", "Finds a specific actor by name or label.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Exact name or label of the actor to find"}
        },
        "required": ["actor"]
    }, READ_ONLY, tool_find_actor)
    registry.register("get_actor_info", "Actors", "Returns detailed info for an actor including tags and components.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Actor name or label"}
        },
        "required": ["actor"]
    }, READ_ONLY, tool_get_actor_info)
    registry.register("get_actor_transform", "Actors", "Gets location, rotation, and scale of an actor.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Actor name or label"}
        },
        "required": ["actor"]
    }, READ_ONLY, tool_get_actor_transform)
    registry.register("set_actor_transform", "Actors", "Sets location, rotation, and/or scale of an actor with Undo/Redo transaction.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Actor name or label"},
            "location": {"type": "object", "description": "Dict with x, y, z coordinates"},
            "rotation": {"type": "object", "description": "Dict with pitch, yaw, roll angles in degrees"},
            "scale": {"type": "object", "description": "Dict with x, y, z scale factors"}
        },
        "required": ["actor"]
    }, SAFE_WRITE, tool_set_actor_transform)
    registry.register("get_actor_components", "Actors", "Lists all components on an actor.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Actor name or label"}
        },
        "required": ["actor"]
    }, READ_ONLY, tool_get_actor_components)

    # Assets
    registry.register("find_assets", "Assets", "Searches assets using AssetRegistry with pagination without loading UObjects into memory.", {
        "type": "object",
        "properties": {
            "class_name": {"type": "string", "description": "Unreal asset class name, e.g. 'Blueprint', 'StaticMesh', 'NiagaraSystem'"},
            "package_path": {"type": "string", "description": "Root package directory to search (e.g. '/Game', '/ConanSandbox')"},
            "name_filter": {"type": "string", "description": "Substring to search in asset name"},
            "offset": {"type": "integer", "description": "Pagination offset (default: 0)"},
            "limit": {"type": "integer", "description": "Max results to return (default: 50, max: 500)"},
            "max_results": {"type": "integer", "description": "Legacy alias for limit"}
        }
    }, READ_ONLY, tool_find_assets)
    registry.register("get_asset_info", "Assets", "Returns metadata and tags for an asset.", {
        "type": "object",
        "properties": {
            "asset_path": {"type": "string", "description": "Object path or package path of the asset"}
        },
        "required": ["asset_path"]
    }, READ_ONLY, tool_get_asset_info)
    registry.register("get_asset_class", "Assets", "Returns the class of an asset given its path.", {
        "type": "object",
        "properties": {
            "asset_path": {"type": "string", "description": "Asset object path"}
        },
        "required": ["asset_path"]
    }, READ_ONLY, tool_get_asset_class)
    registry.register("get_asset_path", "Assets", "Resolves an asset name to its package and object paths.", {
        "type": "object",
        "properties": {
            "asset_name": {"type": "string", "description": "Name of the asset"}
        },
        "required": ["asset_name"]
    }, READ_ONLY, tool_get_asset_path)
    registry.register("get_asset_dependencies", "Assets", "Queries dependencies and referencers of an asset.", {
        "type": "object",
        "properties": {
            "package_name": {"type": "string", "description": "Package name, e.g. '/Game/Characters/Player'"}
        },
        "required": ["package_name"]
    }, READ_ONLY, tool_get_asset_dependencies)
    registry.register("save_asset", "Assets", "Saves an asset package to disk.", {
        "type": "object",
        "properties": {
            "package_name": {"type": "string", "description": "Package name to save"}
        },
        "required": ["package_name"]
    }, SAFE_WRITE, tool_save_asset)
    registry.register("create_blueprint", "Assets", "Creates a new Blueprint asset.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the new Blueprint"},
            "package_path": {"type": "string", "description": "Destination package directory (e.g. '/Game/Mods')"},
            "parent_class": {"type": "string", "description": "Parent: class name (Actor, Character...), /Script/Module.Class or a Blueprint asset path to subclass (default: Actor)"}
        },
        "required": ["name", "package_path"]
    }, SAFE_WRITE, tool_create_blueprint)
    registry.register("create_widget_blueprint", "Assets", "Creates a new Widget Blueprint asset.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the new Widget Blueprint"},
            "package_path": {"type": "string", "description": "Destination package directory"}
        },
        "required": ["name", "package_path"]
    }, SAFE_WRITE, tool_create_widget_blueprint)
    registry.register("create_struct", "Assets", "Creates a new UserDefinedStruct asset.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the new Struct"},
            "package_path": {"type": "string", "description": "Destination package directory"}
        },
        "required": ["name", "package_path"]
    }, SAFE_WRITE, tool_create_struct)
    registry.register("create_enum", "Assets", "Creates a new UserDefinedEnum asset.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the new Enum"},
            "package_path": {"type": "string", "description": "Destination package directory"}
        },
        "required": ["name", "package_path"]
    }, SAFE_WRITE, tool_create_enum)
    registry.register("create_datatable", "Assets", "Creates a new DataTable asset.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the new DataTable"},
            "package_path": {"type": "string", "description": "Destination package directory"},
            "struct_path": {"type": "string", "description": "Row struct: user struct asset path or /Script/Module.StructName"},
            "copy_struct_from": {"type": "string", "description": "Reuse the row struct of this DataTable (e.g. a base-game ItemTable)"}
        },
        "required": ["name", "package_path"]
    }, SAFE_WRITE, tool_create_datatable)

    # Skeletons
    registry.register("get_skeletal_mesh_info", "Skeletons", "Returns SkeletalMesh LODs, materials, and skeleton.", {
        "type": "object",
        "properties": {
            "mesh_path": {"type": "string", "description": "Object path of the SkeletalMesh"}
        },
        "required": ["mesh_path"]
    }, READ_ONLY, tool_get_skeletal_mesh_info)
    registry.register("get_skeleton_info", "Skeletons", "Returns bone and socket counts for a Skeleton.", {
        "type": "object",
        "properties": {
            "skeleton_path": {"type": "string", "description": "Object path of the Skeleton"}
        },
        "required": ["skeleton_path"]
    }, READ_ONLY, tool_get_skeleton_info)
    registry.register("get_skeleton_sockets", "Skeletons", "Lists sockets and attach bones on a Skeleton.", {
        "type": "object",
        "properties": {
            "asset_path": {"type": "string", "description": "Object path of the SkeletalMesh or Skeleton"}
        },
        "required": ["asset_path"]
    }, READ_ONLY, tool_get_skeleton_sockets)
    registry.register("get_bones", "Skeletons", "Returns bone hierarchy of a SkeletalMesh.", {
        "type": "object",
        "properties": {
            "mesh_path": {"type": "string", "description": "Object path of the SkeletalMesh"}
        },
        "required": ["mesh_path"]
    }, READ_ONLY, tool_get_bones)

    # Blueprints
    registry.register("find_blueprint", "Blueprints", "Searches for Blueprint assets.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Substring to search in Blueprint name"},
            "path": {"type": "string", "description": "Search directory (default: '/Game')"}
        }
    }, READ_ONLY, tool_find_blueprint)
    registry.register("get_blueprint_info", "Blueprints", "Returns parent class and generated class of a Blueprint.", {
        "type": "object",
        "properties": {
            "blueprint_path": {"type": "string", "description": "Object path of the Blueprint"}
        },
        "required": ["blueprint_path"]
    }, READ_ONLY, tool_get_blueprint_info)
    registry.register("get_blueprint_parent_class", "Blueprints", "Returns direct parent class of a Blueprint.", {
        "type": "object",
        "properties": {
            "blueprint_path": {"type": "string", "description": "Object path of the Blueprint"}
        },
        "required": ["blueprint_path"]
    }, READ_ONLY, tool_get_blueprint_parent_class)
    registry.register("get_blueprint_variables", "Blueprints", "Lists member variables of a Blueprint.", {
        "type": "object",
        "properties": {
            "blueprint_path": {"type": "string", "description": "Object path of the Blueprint"}
        },
        "required": ["blueprint_path"]
    }, READ_ONLY, tool_get_blueprint_variables)

    # DataTables
    registry.register("find_datatable", "DataTables", "Searches for DataTable assets.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Substring to search in DataTable name"},
            "path": {"type": "string", "description": "Search directory"}
        }
    }, READ_ONLY, tool_find_datatable)
    registry.register("get_datatable_info", "DataTables", "Returns row count and row names of a DataTable.", {
        "type": "object",
        "properties": {
            "datatable_path": {"type": "string", "description": "Object path of the DataTable"}
        },
        "required": ["datatable_path"]
    }, READ_ONLY, tool_get_datatable_info)
    registry.register("list_datatable_rows", "DataTables", "Lists row names in a DataTable with pagination.", {
        "type": "object",
        "properties": {
            "datatable_path": {"type": "string", "description": "Object path of the DataTable"},
            "offset": {"type": "number", "description": "Row offset (default: 0)"},
            "limit": {"type": "number", "description": "Number of rows to return (default: 50, max: 200)"}
        },
        "required": ["datatable_path"]
    }, READ_ONLY, tool_list_datatable_rows)
    registry.register("get_datatable_row", "DataTables", "Returns data of a specific DataTable row.", {
        "type": "object",
        "properties": {
            "datatable_path": {"type": "string", "description": "Object path of the DataTable"},
            "row_name": {"type": "string", "description": "Row identifier name"}
        },
        "required": ["datatable_path", "row_name"]
    }, READ_ONLY, tool_get_datatable_row)

    # Particles
    registry.register("find_particle_systems", "Particles", "Searches for Niagara and Cascade particles.", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Substring to search in particle system name"},
            "type": {"type": "string", "description": "'Niagara', 'Cascade', or 'All' (default: 'All')"},
            "path": {"type": "string", "description": "Search package directory"}
        }
    }, READ_ONLY, tool_find_particle_systems)
    registry.register("get_particle_info", "Particles", "Returns particle system details.", {
        "type": "object",
        "properties": {
            "particle_path": {"type": "string", "description": "Object path of the particle system"}
        },
        "required": ["particle_path"]
    }, READ_ONLY, tool_get_particle_info)
    registry.register("get_character_sockets", "Particles", "Retrieves sockets from a character's SkeletalMeshComponent.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Actor label or name"}
        },
        "required": ["actor"]
    }, READ_ONLY, tool_get_character_sockets)
    registry.register("preview_particle_on_actor", "Particles", "Attaches a preview particle system to an actor or socket.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Target actor label or name"},
            "particle_path": {"type": "string", "description": "Object path of the particle system"},
            "socket_name": {"type": "string", "description": "Socket name to attach to (e.g. 'Hand_R', or Root if omitted)"}
        },
        "required": ["actor", "particle_path"]
    }, SAFE_WRITE, tool_preview_particle_on_actor)
    registry.register("remove_preview_particle", "Particles", "Removes preview particle components from an actor.", {
        "type": "object",
        "properties": {
            "actor": {"type": "string", "description": "Target actor label or name"}
        },
        "required": ["actor"]
    }, SAFE_WRITE, tool_remove_preview_particle)

    # Conan Exiles
    registry.register("find_conan_assets", "Conan", "Searches assets in /Game/ and /ConanSandbox/.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to search in asset names"},
            "class_name": {"type": "string", "description": "Optional class name filter (e.g. 'Blueprint', 'StaticMesh')"}
        }
    }, READ_ONLY, tool_find_conan_assets)
    registry.register("find_conan_datatables", "Conan", "Searches Conan gameplay, item, recipe, and spawn tables.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to search in DataTable names"}
        }
    }, READ_ONLY, tool_find_conan_datatables)
    registry.register("find_conan_characters", "Conan", "Finds Conan character blueprints, monsters, and thralls.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to search in Character names"}
        }
    }, READ_ONLY, tool_find_conan_characters)
    registry.register("find_conan_items", "Conan", "Finds Conan weapons, armor, and item assets.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to search in Item names"}
        }
    }, READ_ONLY, tool_find_conan_items)
    registry.register("find_conan_particles", "Conan", "Searches Conan VFX libraries.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to search in VFX names"}
        }
    }, READ_ONLY, tool_find_conan_particles)

    # Scripting
    registry.register("execute_python", "Scripting", "Executes arbitrary Python code synchronously on the Unreal Game Thread. Disabled unless CONAN_MCP_ENABLE_DESTRUCTIVE=1.", {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Valid Python 3 script to execute"}
        },
        "required": ["code"]
    }, DESTRUCTIVE, tool_execute_python)

    # Management
    registry.register("reload_server", "Editor", "Hot-reloads the ConanMCP python server module, tools, resources and prompts.", {"type": "object", "properties": {}}, SAFE_WRITE, tool_reload_server)



def register_resources(resource_registry):
    resource_registry.register(
        uri="devkit://status",
        name="DevKit Status",
        mime_type="application/json",
        description="Live editor status, engine version, active level, and dirty package status.",
        handler=resource_devkit_status
    )
    resource_registry.register(
        uri="devkit://logs/recent",
        name="Recent DevKit Logs",
        mime_type="text/plain",
        description="Ring buffer of the latest Output Log entries recorded by ConanMCP.",
        handler=resource_devkit_logs
    )
    resource_registry.register(
        uri="devkit://outliner",
        name="Level World Outliner",
        mime_type="application/json",
        description="Structured hierarchical list of all actors in the currently loaded level.",
        handler=resource_devkit_outliner
    )
    resource_registry.register(
        uri="conan://tables",
        name="Conan DataTables Catalog",
        mime_type="application/json",
        description="Catalog of all Conan Exiles item, recipe, spawn, and gameplay DataTables.",
        handler=resource_conan_tables
    )
    resource_registry.register_template(
        uri_template="conan://asset/{package_path}",
        name="Conan Asset Inspector",
        mime_type="application/json",
        description="Inspect metadata, class, dependencies, and referencers of any asset by package path.",
        handler=resource_template_conan_asset
    )


def register_prompts(prompt_registry):
    prompt_registry.register(
        name="create-conan-item-mod",
        description="Step-by-step workflow to design, create, and configure a new item, weapon, or armor in Conan Exiles DevKit.",
        arguments=[
            {"name": "item_name", "description": "Name of the new item", "required": True},
            {"name": "item_type", "description": "Type of item (Weapon, Armor, Placeable, Consumable)", "required": False},
            {"name": "description", "description": "Brief description of the item's purpose and appearance", "required": False}
        ],
        handler=prompt_create_conan_item
    )
    prompt_registry.register(
        name="audit-level-performance",
        description="Analyzes the active level for performance bottlenecks, unbatched actors, excessive dynamic lights, and particle previews.",
        arguments=[],
        handler=prompt_audit_level_performance
    )
    prompt_registry.register(
        name="inspect-character-skeleton",
        description="Inspects bone hierarchy, socket attach points, and attachment compatibility for character and thrall skeletal meshes.",
        arguments=[
            {"name": "mesh_path", "description": "Object path of the SkeletalMesh", "required": False}
        ],
        handler=prompt_inspect_character_skeleton
    )
    prompt_registry.register(
        name="debug-niagara-vfx",
        description="Diagnoses, searches, and previews Niagara and Cascade particle systems on level actors or character sockets.",
        arguments=[
            {"name": "vfx_query", "description": "Keyword to search particle libraries (e.g. Fire, Blood, Sandstorm)", "required": False}
        ],
        handler=prompt_debug_niagara_vfx
    )
