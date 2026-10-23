"""Blueprint tools: deep inspection, compile with errors, variables, defaults, components, reparenting.

Uses the native C++ helpers when present (exact types and compiler messages),
otherwise the Python editor APIs (BlueprintEditorLibrary, SubobjectDataSubsystem).
Wiring graph nodes is not exposed: Unreal's Python API cannot do it reliably.
"""

import json

from ..core import ue
from ..core.security import READ_ONLY, SAFE_WRITE
from .system import read_log_tail

BASIC_TYPES = ("bool", "byte", "int", "int64", "float", "double", "real", "string", "name", "text",
               "vector", "rotator", "transform", "object", "class", "struct", "soft_object", "soft_class")


def _load_bp(path):
    u = ue.require()
    bp = ue.load_asset(path)
    if not isinstance(bp, u.Blueprint):
        raise ValueError(f"'{path}' is not a Blueprint (it is a {ue.class_name(bp)})")
    return bp


def _cdo(bp):
    """Class Default Object of the Blueprint's generated class, or None if unavailable."""
    u = ue.require()
    try:
        gen = bp.generated_class() if hasattr(bp, "generated_class") else bp.get_editor_property("generated_class")
        return u.get_default_object(gen) if gen and hasattr(u, "get_default_object") else None
    except Exception:
        return None


def _variables(bp):
    out = []
    try:
        new_vars = bp.get_editor_property("new_variables")
    except Exception:
        new_vars = getattr(bp, "new_variables", []) or []
    cdo = _cdo(bp)
    for v in new_vars:
        entry = {"name": str(v.get_editor_property("var_name")) if hasattr(v, "get_editor_property") else str(v.var_name)}
        try:
            pin = v.get_editor_property("var_type")
            entry["type"] = str(pin.get_editor_property("pin_category"))
            sub = pin.get_editor_property("pin_sub_category_object")
            if sub:
                entry["sub_type"] = sub.get_path_name()
            entry["container"] = str(pin.get_editor_property("container_type"))
        except Exception:
            pass
        for key in ("category", "default_value", "friendly_name"):
            try:
                entry[key] = str(v.get_editor_property(key))
            except Exception:
                pass
        if cdo is not None:
            try:
                entry["value"] = ue.to_json_value(cdo.get_editor_property(entry["name"]))
            except Exception:
                pass
        out.append(entry)
    return out


def _components(bp):
    u = ue.require()
    sds = u.get_engine_subsystem(u.SubobjectDataSubsystem) if ue.has("SubobjectDataSubsystem") else None
    if sds is None:
        return []
    lib = getattr(u, "SubobjectDataBlueprintFunctionLibrary", None)
    out = []
    for handle in sds.k2_gather_subobject_data_for_blueprint(bp):
        data = sds.k2_find_subobject_data_from_handle(handle)
        try:
            obj = lib.get_object(data) if lib else None
            name = str(lib.get_variable_name(data)) if lib else ""
        except Exception:
            obj, name = None, ""
        if obj is None:
            continue
        out.append({"name": name or obj.get_name(), "class": ue.class_name(obj)})
    return out


def _graphs(bp):
    graphs = {}
    for prop in ("ubergraph_pages", "function_graphs", "macro_graphs"):
        try:
            graphs[prop] = [g.get_name() for g in bp.get_editor_property(prop)]
        except Exception:
            pass
    return graphs


def tool_get_blueprint_info(args):
    path = args["blueprint_path"]
    bp = _load_bp(path)
    lib = ue.native()
    if lib and hasattr(lib, "get_blueprint_details_json"):
        details = json.loads(lib.get_blueprint_details_json(bp) or "{}")
        if details:
            return details
    parent = bp.get_editor_property("parent_class")
    info = {
        "name": bp.get_name(), "path": path,
        "parent_class": parent.get_name() if parent else None,
        "variables": _variables(bp),
        "components": _components(bp),
        "graphs": _graphs(bp),
        "backend": "python",
    }
    try:
        info["interfaces"] = [str(i) for i in bp.get_editor_property("implemented_interfaces")]
    except Exception:
        pass
    try:
        info["status"] = str(bp.get_editor_property("status"))
    except Exception:
        pass
    return info


def tool_get_blueprint_variables(args):
    info = tool_get_blueprint_info(args)
    return {"blueprint": info.get("name"), "variables": info.get("variables", []),
            "count": len(info.get("variables", []))}


def compile_bp(bp):
    lib = ue.native()
    if lib and hasattr(lib, "compile_blueprint_json"):
        return json.loads(lib.compile_blueprint_json(bp) or "{}")
    u = ue.require()
    u.BlueprintEditorLibrary.compile_blueprint(bp)
    result = {"compiled": True, "backend": "python"}
    try:
        result["status"] = str(bp.get_editor_property("status"))
    except Exception:
        pass
    log = read_log_tail(max_lines=40, contains=bp.get_name())
    result["log"] = [line for line in log["lines"] if "Error" in line or "Warning" in line][-20:]
    result["has_errors"] = any("Error" in line for line in result["log"]) or "ERROR" in result.get("status", "").upper()
    return result


def tool_compile_blueprint(args):
    bp = _load_bp(args["blueprint_path"])
    result = compile_bp(bp)
    if args.get("save") and not result.get("has_errors"):
        ue.require().EditorAssetLibrary.save_loaded_asset(bp, False)
        result["saved"] = True
    return result


def _pin_type(type_name, sub_type=None, container="none"):
    u = ue.require()
    lib = u.BlueprintEditorLibrary
    t = type_name.lower()
    if t in ("object", "class", "soft_object", "soft_class", "struct"):
        if not sub_type:
            raise ValueError(f"Type '{type_name}' needs 'sub_type' (class or struct path)")
        target = ue.load_asset(sub_type) if sub_type.startswith("/Game") else ue.resolve_class(sub_type)
        fn = {"object": "get_object_reference_type", "class": "get_class_reference_type",
              "soft_object": "get_soft_object_reference_type", "soft_class": "get_soft_class_reference_type",
              "struct": "get_struct_type"}[t]
        if not hasattr(lib, fn):
            raise ue.UnsupportedError(f"BlueprintEditorLibrary.{fn} is not available")
        pin = getattr(lib, fn)(target)
    else:
        if not hasattr(lib, "get_basic_type_by_name"):
            raise ue.UnsupportedError("BlueprintEditorLibrary.get_basic_type_by_name is not available")
        mapping = {"float": "real", "double": "real"}
        if t in ("vector", "rotator", "transform"):
            pin = lib.get_struct_type(getattr(u, t.capitalize()).static_struct())
        else:
            pin = lib.get_basic_type_by_name(mapping.get(t, t))
    if container == "array" and hasattr(lib, "get_array_type"):
        pin = lib.get_array_type(pin)
    return pin


def tool_add_blueprint_variable(args):
    bp = _load_bp(args["blueprint_path"])
    name = args["name"]
    vtype = args.get("type", "bool")
    if args.get("dry_run"):
        return {"dry_run": True, "would_add": {"name": name, "type": vtype, "sub_type": args.get("sub_type")}}
    lib = ue.native()
    if lib and hasattr(lib, "add_blueprint_variable_json"):
        native_type = ("array:" if args.get("container") == "array" else "") + vtype
        res = json.loads(lib.add_blueprint_variable_json(bp, name, native_type, args.get("sub_type", ""),
                                                         args.get("default_value", ""), args.get("category", "")) or "{}")
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "Native add variable failed"))
    else:
        u = ue.require()
        if not ue.has("BlueprintEditorLibrary.add_member_variable"):
            raise ue.UnsupportedError("BlueprintEditorLibrary.add_member_variable is not available; enable the native module")
        pin = _pin_type(vtype, args.get("sub_type"), args.get("container", "none"))
        with ue.transaction(f"ConanMCP: Add variable {name}"):
            if not u.BlueprintEditorLibrary.add_member_variable(bp, name, pin):
                raise RuntimeError(f"Could not add variable '{name}' (does it already exist?)")
    compiled = compile_bp(bp) if args.get("compile", True) else None
    if args.get("default_value") not in (None, "") and not (lib and hasattr(lib, "add_blueprint_variable_json")):
        _set_default(bp, name, args["default_value"])
    return {"added": name, "type": vtype, "compile": compiled}


def _set_default(bp, prop, value):
    cdo = _cdo(bp)
    if cdo is None:
        raise RuntimeError("Blueprint has no generated class yet; compile it first")
    current = cdo.get_editor_property(prop)
    with ue.transaction(f"ConanMCP: Set default {prop}"):
        cdo.modify()
        cdo.set_editor_property(prop, ue.from_json_value(value, current))
    return ue.to_json_value(current), ue.to_json_value(cdo.get_editor_property(prop))


def tool_set_blueprint_default(args):
    bp = _load_bp(args["blueprint_path"])
    values = dict(args.get("values") or {})
    if args.get("property"):
        values[args["property"]] = args.get("value")
    if not values:
        raise ValueError("Provide 'property' + 'value' or a 'values' object")
    if args.get("dry_run"):
        cdo = _cdo(bp)
        return {"dry_run": True, "current": {k: ue.to_json_value(cdo.get_editor_property(k)) for k in values}, "new": values}
    changes = {}
    for prop, value in values.items():
        old, new = _set_default(bp, prop, value)
        changes[prop] = {"old": old, "new": new}
    compiled = compile_bp(bp) if args.get("compile", True) else None
    return {"changes": changes, "compile": compiled}


def tool_add_blueprint_component(args):
    u = ue.require()
    bp = _load_bp(args["blueprint_path"])
    comp_class = ue.resolve_class(args["component_class"])
    if not ue.has("SubobjectDataSubsystem"):
        raise ue.UnsupportedError("SubobjectDataSubsystem is not available in this DevKit")
    if args.get("dry_run"):
        return {"dry_run": True, "would_add": args["component_class"], "name": args.get("name")}
    sds = u.get_engine_subsystem(u.SubobjectDataSubsystem)
    handles = sds.k2_gather_subobject_data_for_blueprint(bp)
    if not handles:
        raise RuntimeError("Blueprint has no subobject root")
    parent = handles[0]
    if args.get("parent"):
        lib = getattr(u, "SubobjectDataBlueprintFunctionLibrary", None)
        for h in handles:
            data = sds.k2_find_subobject_data_from_handle(h)
            if lib and str(lib.get_variable_name(data)).lower() == args["parent"].lower():
                parent = h
                break
    params = u.AddNewSubobjectParams(parent_handle=parent, new_class=comp_class, blueprint_context=bp)
    with ue.transaction(f"ConanMCP: Add component to {bp.get_name()}"):
        result = sds.add_new_subobject(params)
        handle, fail = (result if isinstance(result, tuple) else (result, ""))
        if fail and str(fail):
            raise RuntimeError(f"add_new_subobject failed: {fail}")
        if args.get("name"):
            sds.rename_subobject(handle, u.Text(args["name"]))
    compiled = compile_bp(bp) if args.get("compile", True) else None
    return {"added": args["component_class"], "name": args.get("name"), "compile": compiled}


def tool_reparent_blueprint(args):
    u = ue.require()
    bp = _load_bp(args["blueprint_path"])
    new_parent = ue.resolve_class(args["new_parent_class"])
    if args.get("dry_run"):
        old = bp.get_editor_property("parent_class")
        return {"dry_run": True, "old_parent": old.get_name() if old else None, "new_parent": args["new_parent_class"]}
    with ue.transaction(f"ConanMCP: Reparent {bp.get_name()}"):
        u.BlueprintEditorLibrary.reparent_blueprint(bp, new_parent)
    return {"reparented": bp.get_name(), "new_parent": args["new_parent_class"], "compile": compile_bp(bp)}


def tool_list_blueprint_graphs(args):
    bp = _load_bp(args["blueprint_path"])
    return {"blueprint": bp.get_name(), "graphs": _graphs(bp)}


def register(registry):
    bp = {"blueprint_path": {"type": "string"}}
    common = {"dry_run": {"type": "boolean"}, "compile": {"type": "boolean", "default": True}}
    registry.register("get_blueprint_info", "Blueprints",
                      "Deep Blueprint inspection: parent, variables (type, default, CDO value), components, graphs, interfaces, status.",
                      {"properties": bp, "required": ["blueprint_path"]}, READ_ONLY, tool_get_blueprint_info)
    registry.register("get_blueprint_variables", "Blueprints", "Member variables with types and default values.",
                      {"properties": bp, "required": ["blueprint_path"]}, READ_ONLY, tool_get_blueprint_variables)
    registry.register("list_blueprint_graphs", "Blueprints", "Event graphs, functions and macros of a Blueprint.",
                      {"properties": bp, "required": ["blueprint_path"]}, READ_ONLY, tool_list_blueprint_graphs)
    registry.register("compile_blueprint", "Blueprints", "Compiles a Blueprint and returns status plus compiler errors/warnings.",
                      {"properties": {**bp, "save": {"type": "boolean"}}, "required": ["blueprint_path"]},
                      SAFE_WRITE, tool_compile_blueprint)
    registry.register("add_blueprint_variable", "Blueprints",
                      f"Adds a member variable. type: {', '.join(BASIC_TYPES)}; object/class/struct need sub_type.",
                      {"properties": {**bp, "name": {"type": "string"}, "type": {"type": "string"},
                                      "sub_type": {"type": "string"}, "container": {"type": "string", "enum": ["none", "array"]},
                                      "default_value": {}, "category": {"type": "string"}, **common},
                       "required": ["blueprint_path", "name", "type"]}, SAFE_WRITE, tool_add_blueprint_variable, idempotent=False)
    registry.register("set_blueprint_default", "Blueprints", "Sets class default values (CDO) of variables/properties, then compiles.",
                      {"properties": {**bp, "property": {"type": "string"}, "value": {}, "values": {"type": "object"}, **common},
                       "required": ["blueprint_path"]}, SAFE_WRITE, tool_set_blueprint_default)
    registry.register("add_blueprint_component", "Blueprints",
                      "Adds a component (e.g. StaticMeshComponent, PointLightComponent, BoxComponent) to a Blueprint.",
                      {"properties": {**bp, "component_class": {"type": "string"}, "name": {"type": "string"},
                                      "parent": {"type": "string"}, **common},
                       "required": ["blueprint_path", "component_class"]}, SAFE_WRITE, tool_add_blueprint_component, idempotent=False)
    registry.register("reparent_blueprint", "Blueprints", "Changes a Blueprint's parent class and recompiles.",
                      {"properties": {**bp, "new_parent_class": {"type": "string"}, "dry_run": {"type": "boolean"}},
                       "required": ["blueprint_path", "new_parent_class"]}, SAFE_WRITE, tool_reparent_blueprint)
