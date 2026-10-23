"""Mod workflow: folder structure, broken references, dirty packages, rename/move/delete, release audit."""

import re

from ..core import ue
from ..core.security import DESTRUCTIVE, READ_ONLY, SAFE_WRITE
from .builtin import _get_asset_dict

MOD_ROOT = "/Game/Mods"
MOD_FOLDERS = ("Blueprints", "DataTables", "Items", "Icons", "Maps", "Meshes", "Materials", "Textures", "VFX", "Audio", "UI")
_MOD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")

# Unreal / Conan modding naming conventions (warnings only)
NAMING = {
    "Blueprint": ("BP_",), "WidgetBlueprint": ("WBP_", "W_"), "DataTable": ("DT_",), "UserDefinedStruct": ("S_", "F_", "ST_"),
    "UserDefinedEnum": ("E_",), "Texture2D": ("T_",), "Material": ("M_",), "MaterialInstanceConstant": ("MI_",),
    "StaticMesh": ("SM_",), "SkeletalMesh": ("SK_",), "AnimSequence": ("A_", "AS_"), "AnimMontage": ("AM_",),
    "NiagaraSystem": ("NS_",), "ParticleSystem": ("P_", "PS_"), "SoundWave": ("SW_", "S_"), "SoundCue": ("SC_",),
}


def _ar():
    return ue.require().AssetRegistryHelpers.get_asset_registry()


def _dep_options():
    u = ue.require()
    opts = u.AssetRegistryDependencyOptions()
    for flag in ("include_soft_package_references", "include_hard_package_references"):
        try:
            opts.set_editor_property(flag, True)
        except Exception:
            pass
    return opts


def _assets_in(path):
    return list(_ar().get_assets_by_path(path, recursive=True) or [])


def _package_exists(pkg):
    u = ue.require()
    if pkg.startswith("/Script/"):
        return True
    if u.EditorAssetLibrary.does_asset_exist(pkg):
        return True
    return bool(_ar().get_assets_by_package_name(pkg))


def broken_references(path, limit=500):
    """Assets under ``path`` whose dependencies no longer exist."""
    broken, checked = [], 0
    cache = {}
    for ad in _assets_in(path)[:limit]:
        checked += 1
        pkg = str(ad.package_name)
        missing = []
        for dep in _ar().get_dependencies(pkg, _dep_options()) or []:
            dep = str(dep)
            if dep not in cache:
                cache[dep] = _package_exists(dep)
            if not cache[dep]:
                missing.append(dep)
        if missing:
            broken.append({"asset": pkg, "missing_dependencies": missing})
    return checked, broken


def _mod_path(args):
    if args.get("mod_path"):
        return args["mod_path"].rstrip("/")
    name = args.get("mod_name", "")
    if not _MOD_NAME.match(name or ""):
        raise ValueError("mod_name must start with a letter and contain only letters, digits and _ (2-64 chars)")
    return f"{MOD_ROOT}/{name}"


def tool_create_mod_structure(args):
    u = ue.require()
    root = _mod_path(args)
    folders = [root] + [f"{root}/{f}" for f in (args.get("folders") or MOD_FOLDERS)]
    if args.get("dry_run"):
        return {"dry_run": True, "would_create": folders}
    created = []
    for f in folders:
        if not u.EditorAssetLibrary.does_directory_exist(f):
            u.EditorAssetLibrary.make_directory(f)
            created.append(f)
    return {"mod_root": root, "created": created, "existing": [f for f in folders if f not in created],
            "next": "Register the mod with the DevKit's Mod tools (Mod Manager / Create Mod) if you have not yet."}


def tool_validate_assets(args):
    path = args.get("package_path") or MOD_ROOT
    checked, broken = broken_references(path, int(args.get("limit", 500)))
    result = {"path": path, "checked": checked, "broken_count": len(broken), "broken": broken[:100]}
    u = ue.require()
    if args.get("run_data_validation") and ue.has("EditorValidatorSubsystem"):
        sub = ue.editor_subsystem("EditorValidatorSubsystem")
        try:
            datas = _assets_in(path)[:200]
            settings = u.ValidateAssetsSettings() if hasattr(u, "ValidateAssetsSettings") else None
            res = (sub.validate_assets_with_settings(datas, settings) if settings is not None and hasattr(sub, "validate_assets_with_settings")
                   else sub.validate_assets(datas))
            result["data_validation"] = ue.to_json_value(res)
        except Exception as e:
            result["data_validation_error"] = str(e)
    return result


def tool_get_asset_referencers(args):
    pkg = args["package_path"].split(".")[0]
    refs = [str(r) for r in _ar().get_referencers(pkg, _dep_options()) or []]
    return {"package": pkg, "referencer_count": len(refs), "referencers": refs[:300]}


def _dirty():
    u = ue.require()
    lib = u.EditorLoadingAndSavingUtils
    content = [p.get_name() for p in lib.get_dirty_content_packages()]
    maps = [p.get_name() for p in lib.get_dirty_map_packages()]
    return content, maps


def tool_list_dirty_packages(args):
    content, maps = _dirty()
    return {"content_packages": content, "map_packages": maps, "total": len(content) + len(maps)}


def tool_save_all_dirty(args):
    u = ue.require()
    content, maps = _dirty()
    if args.get("dry_run"):
        return {"dry_run": True, "would_save": content + (maps if args.get("include_maps", True) else [])}
    ok = u.EditorLoadingAndSavingUtils.save_dirty_packages(bool(args.get("include_maps", True)), True)
    return {"saved": ok is not False, "content_packages": content, "map_packages": maps if args.get("include_maps", True) else []}


def tool_rename_asset(args):
    u = ue.require()
    src, dst = args["source_path"], args["destination_path"]
    pkg = src.split(".")[0]
    refs = [str(r) for r in _ar().get_referencers(pkg, _dep_options()) or []]
    if args.get("dry_run"):
        return {"dry_run": True, "from": src, "to": dst, "referencers_to_fix": refs[:100]}
    if u.EditorAssetLibrary.does_asset_exist(dst):
        raise ValueError(f"'{dst}' already exists")
    if not u.EditorAssetLibrary.rename_asset(src, dst):
        raise RuntimeError(f"Rename failed: {src} -> {dst}")
    fixed = False
    if args.get("fixup_redirectors", True) and ue.has("AssetToolsHelpers"):
        try:
            tools = u.AssetToolsHelpers.get_asset_tools()
            folder = src.rsplit("/", 1)[0]
            redirectors = [ad.get_asset() for ad in _ar().get_assets_by_path(folder, recursive=False)
                           if "ObjectRedirector" in _get_asset_dict(ad)["class"]]
            if redirectors:
                tools.fixup_referencers(redirectors)
                fixed = True
        except Exception:
            pass
    return {"renamed": True, "from": src, "to": dst, "referencers_updated": len(refs), "redirectors_fixed": fixed}


def tool_delete_asset(args):
    u = ue.require()
    path = args["asset_path"]
    if not path.startswith(MOD_ROOT + "/") and not args.get("allow_outside_mods"):
        raise PermissionError("Only assets under /Game/Mods can be deleted (pass allow_outside_mods=true to override)")
    refs = [str(r) for r in _ar().get_referencers(path.split(".")[0], _dep_options()) or []]
    if refs and not args.get("force"):
        raise ValueError(f"'{path}' is referenced by {len(refs)} packages ({refs[:10]}); fix them or pass force=true")
    if args.get("dry_run"):
        return {"dry_run": True, "would_delete": path, "referencers": refs}
    if not u.EditorAssetLibrary.delete_asset(path):
        raise RuntimeError(f"Could not delete '{path}'")
    return {"deleted": path, "note": "Asset deletion cannot be undone with Ctrl+Z; restore it from source control if needed."}


def tool_audit_mod(args):
    root = _mod_path(args)
    assets = _assets_in(root)
    by_class, naming = {}, []
    for ad in assets:
        d = _get_asset_dict(ad)
        by_class[d["class"]] = by_class.get(d["class"], 0) + 1
        prefixes = NAMING.get(d["class"])
        if prefixes and not d["name"].startswith(prefixes):
            naming.append({"asset": d["object_path"], "class": d["class"], "expected_prefix": "/".join(prefixes)})
    checked, broken = broken_references(root, 2000)
    cross_mod = []
    for ad in assets[:1000]:
        pkg = str(ad.package_name)
        for dep in _ar().get_dependencies(pkg, _dep_options()) or []:
            dep = str(dep)
            if dep.startswith(MOD_ROOT + "/") and not dep.startswith(root + "/"):
                cross_mod.append({"asset": pkg, "depends_on_other_mod": dep})
    content, maps = _dirty()
    dirty_in_mod = [p for p in content + maps if p.startswith(root + "/")]
    checks = {
        "has_assets": len(assets) > 0,
        "no_broken_references": not broken,
        "no_cross_mod_dependencies": not cross_mod,
        "everything_saved": not dirty_in_mod,
        "naming_conventions": not naming,
    }
    score = round(100.0 * sum(checks.values()) / len(checks))
    todo = []
    if broken:
        todo.append(f"Fix {len(broken)} assets with missing dependencies (validate_assets for details).")
    if cross_mod:
        todo.append(f"{len(cross_mod)} dependencies point into other mods: your mod would require them to load.")
    if dirty_in_mod:
        todo.append(f"Save {len(dirty_in_mod)} unsaved packages (save_all_dirty).")
    if naming:
        todo.append(f"{len(naming)} assets do not follow naming conventions (optional, improves maintainability).")
    todo.append("Test in PIE / a dedicated test server, then cook and upload with the DevKit's mod tools.")
    return {"mod_root": root, "asset_count": len(assets), "by_class": by_class, "checks": checks, "score": score,
            "broken_references": broken[:50], "cross_mod_dependencies": cross_mod[:50], "unsaved": dirty_in_mod,
            "naming_issues": naming[:50], "todo": todo}


def register(registry):
    mod = {"mod_name": {"type": "string"}, "mod_path": {"type": "string"}}
    registry.register("create_mod_structure", "Mod", "Creates the standard folder layout under /Game/Mods/<mod_name>.",
                      {"properties": {**mod, "folders": {"type": "array", "items": {"type": "string"}}, "dry_run": {"type": "boolean"}}},
                      SAFE_WRITE, tool_create_mod_structure)
    registry.register("validate_assets", "Mod",
                      "Finds assets with missing (broken) dependencies under a path; optionally runs Unreal data validation.",
                      {"properties": {"package_path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                                      "run_data_validation": {"type": "boolean"}}}, READ_ONLY, tool_validate_assets)
    registry.register("get_asset_referencers", "Mod", "Packages that reference an asset (who breaks if it moves or is deleted).",
                      {"properties": {"package_path": {"type": "string"}}, "required": ["package_path"]},
                      READ_ONLY, tool_get_asset_referencers)
    registry.register("list_dirty_packages", "Mod", "Unsaved content and map packages.", {"properties": {}},
                      READ_ONLY, tool_list_dirty_packages)
    registry.register("save_all_dirty", "Mod", "Saves every unsaved content package (and maps by default).",
                      {"properties": {"include_maps": {"type": "boolean"}, "dry_run": {"type": "boolean"}}},
                      SAFE_WRITE, tool_save_all_dirty)
    registry.register("rename_asset", "Mod", "Renames/moves an asset, updating references and fixing redirectors.",
                      {"properties": {"source_path": {"type": "string"}, "destination_path": {"type": "string"},
                                      "fixup_redirectors": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["source_path", "destination_path"]}, SAFE_WRITE, tool_rename_asset, idempotent=False)
    registry.register("delete_asset", "Mod", "Deletes an asset from disk (only under /Game/Mods, refuses if referenced). NOT undoable.",
                      {"properties": {"asset_path": {"type": "string"}, "force": {"type": "boolean"},
                                      "allow_outside_mods": {"type": "boolean"}, "dry_run": {"type": "boolean"}},
                       "required": ["asset_path"]}, DESTRUCTIVE, tool_delete_asset, idempotent=False)
    registry.register("audit_mod", "Mod",
                      "Release checklist for a mod: broken refs, cross-mod dependencies, unsaved packages, naming, score and to-do list.",
                      {"properties": mod}, READ_ONLY, tool_audit_mod)
