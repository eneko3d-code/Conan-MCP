"""Tripo AI tools: generate, texture, retopologize, rig/animate 3D models and import them into the mod.

Spending policy (every tool that creates a Tripo task):
  1. The account balance is checked first; no balance (or below CONAN_MCP_TRIPO_MIN_BALANCE) -> refused.
  2. Without ``confirm_spend: true`` the tool only returns a plan (balance, task, parameters, last observed
     cost of that task type). The agent must ask the user before confirming.
  3. CONAN_MCP_TRIPO_BUDGET caps the credits spent in this editor session (0 = no cap).
Network work runs on the request thread (never blocking the editor); only imports touch the Game Thread.
"""

import os
import re
import threading
import time
import urllib.parse

from ..core import config, ue
from ..core.dispatcher import execute_on_game_thread
from ..core.log import log_info
from ..core.security import READ_ONLY, SAFE_WRITE
from ..core.state import STATE
from ..integrations.tripo import TERMINAL_STATUSES, TripoClient, TripoError, TripoInsufficientCredits

MOD_ROOT = "/Game/Mods/"
WORK_DIR = "tripo"
INPUT_SUBDIRS = ("tripo/inputs", "captures", "tripo", "")
_lock = threading.Lock()


class BudgetExceeded(TripoError):
    pass


# ---------------------------------------------------------------------------
# Session state & client
# ---------------------------------------------------------------------------

def _session():
    if not hasattr(STATE, "tripo"):
        STATE.tripo = {"spent": 0.0, "by_type": {}, "tasks": {}, "uploads": {}}
    return STATE.tripo


def api_key():
    return os.environ.get("TRIPO_API_KEY", "").strip()


def client() -> TripoClient:
    return TripoClient(api_key(), base_url=config.TRIPO_BASE_URL, download_hosts=config.TRIPO_DOWNLOAD_HOSTS)


def _observed_cost(task_type):
    costs = _session()["by_type"].get(task_type) or []
    return round(sum(costs) / len(costs), 2) if costs else None


def _pending_estimate():
    total = 0.0
    for t in _session()["tasks"].values():
        if not t.get("counted"):
            total += _observed_cost(t["type"]) or 0.0
    return total


def _account_task(task_id, task):
    """Adds credits of a finished task to the session (once)."""
    with _lock:
        rec = _session()["tasks"].get(task_id)
        if rec is None:
            rec = _session()["tasks"].setdefault(task_id, {"type": task.get("type", "unknown"), "name": None})
        rec["status"] = task.get("status")
        if rec.get("counted") or task.get("status") not in TERMINAL_STATUSES:
            return
        credits = float(task.get("credits_consumed") or 0.0) if task.get("status") == "success" else 0.0
        rec["credits"] = credits
        rec["counted"] = True
        _session()["spent"] += credits
        if task.get("status") == "success" and credits:
            _session()["by_type"].setdefault(rec["type"], []).append(credits)


def _budget_view(balance=None):
    budget = config.TRIPO_BUDGET
    spent = round(_session()["spent"], 2)
    view = {"session_spent": spent, "session_budget": budget or None,
            "session_remaining": round(budget - spent - _pending_estimate(), 2) if budget else None,
            "observed_cost_by_type": {k: _observed_cost(k) for k in _session()["by_type"]}}
    if balance is not None:
        view.update(balance)
    return view


def guard_spend(cli, task_type, endpoint, payload, args):
    """Checks balance and budget. Returns a plan dict when the spend is not confirmed, else None."""
    bal = cli.get_balance()
    est = _observed_cost(task_type)
    if bal["balance"] <= 0:
        raise TripoInsufficientCredits(f"Your Tripo balance is {bal['balance']} credits: nothing was sent. Top up in the Tripo console.")
    if config.TRIPO_MIN_BALANCE and bal["balance"] < config.TRIPO_MIN_BALANCE:
        raise TripoInsufficientCredits(f"Balance {bal['balance']} is below CONAN_MCP_TRIPO_MIN_BALANCE={config.TRIPO_MIN_BALANCE}.")
    if est is not None and est > bal["balance"]:
        raise TripoInsufficientCredits(f"A {task_type} task cost ~{est} credits last time; balance is {bal['balance']}.")
    if config.TRIPO_BUDGET:
        remaining = config.TRIPO_BUDGET - _session()["spent"] - _pending_estimate()
        if remaining <= 0 or (est is not None and est > remaining):
            raise BudgetExceeded(f"Session budget CONAN_MCP_TRIPO_BUDGET={config.TRIPO_BUDGET} would be exceeded "
                                 f"(spent {round(_session()['spent'], 2)}, remaining {round(remaining, 2)}).")
    if not args.get("confirm_spend"):
        return {
            "needs_confirmation": True,
            "task_type": task_type, "endpoint": endpoint, "parameters": payload,
            "estimated_credits": est,
            "estimate_note": ("Observed cost of this task type in this session." if est is not None else
                              "Tripo does not publish prices; the real cost is shown after the task finishes."),
            **_budget_view(bal),
            "next": "Ask the user to approve the spend, then call again with confirm_spend=true.",
        }
    return None


def _submit(task_type, endpoint, payload, args):
    cli = client()
    plan = guard_spend(cli, task_type, endpoint, payload, args)
    if plan is not None:
        return plan
    task_id = cli.create_task(endpoint, payload)
    with _lock:
        _session()["tasks"][task_id] = {"type": task_type, "name": args.get("name"), "created": time.time(),
                                        "status": "queued", "counted": False}
    log_info(f"Tripo task {task_id} created ({task_type})")
    result = {"task_id": task_id, "task_type": task_type, "status": "queued",
              "next": "Poll with tripo_get_task(task_id, wait_seconds=20); import with tripo_import_result when status is success."}
    if args.get("wait_seconds"):
        task = cli.wait_task(task_id, min(float(args["wait_seconds"]), 25.0))
        _account_task(task_id, task)
        result.update(_task_view(task))
    return result


def _clean(payload):
    return {k: v for k, v in payload.items() if v is not None}


def _pick(args, keys):
    return {k: args[k] for k in keys if k in args and args[k] is not None}


# ---------------------------------------------------------------------------
# Inputs (local files are uploaded once; only files under Saved/ConanMCP are allowed)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"^(task|file)_[A-Za-z0-9_\-]+$|^[0-9a-fA-F\-]{32,36}$")


def _local_file(name):
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Local inputs must be plain file names stored in Saved/ConanMCP/tripo/inputs or Saved/ConanMCP/captures")
    for sub in INPUT_SUBDIRS:
        path = execute_on_game_thread(ue.safe_file, name, sub)
        if os.path.isfile(path):
            return path
    raise ValueError(f"'{name}' not found in Saved/ConanMCP/tripo/inputs, Saved/ConanMCP/captures or Saved/ConanMCP")


def resolve_input(cli, ref):
    """file token / task id / https URL / local file name -> value for Tripo's ``input`` field."""
    if not ref or not isinstance(ref, str):
        raise ValueError("An input (file name, URL, task_id or file token) is required")
    ref = ref.strip()
    if _TOKEN.match(ref):
        return ref
    if ref.startswith("https://"):
        return ref
    if ref.startswith("http://"):
        raise ValueError("Only https URLs are accepted")
    path = _local_file(ref)
    key = (path, os.path.getmtime(path))
    cached = _session()["uploads"].get(key)
    if cached:
        return cached
    token = cli.upload(path)
    _session()["uploads"][key] = token
    return token


# ---------------------------------------------------------------------------
# Tools: account & tasks
# ---------------------------------------------------------------------------

def tool_tripo_get_balance(args):
    bal = client().get_balance()
    return {**_budget_view(bal), "api_key_configured": True}


def _task_view(task):
    out = task.get("output") or {}
    return {"task_id": task.get("task_id"), "type": task.get("type"), "status": task.get("status"),
            "progress": task.get("progress"), "credits_consumed": task.get("credits_consumed"),
            "outputs": {k: v for k, v in out.items() if isinstance(v, (str, int, float, bool, dict, list))},
            "preview_image_url": out.get("rendered_image_url") or out.get("generated_image_url")}


def tool_tripo_get_task(args):
    cli = client()
    wait = min(float(args.get("wait_seconds", 0) or 0), 25.0)
    task = cli.wait_task(args["task_id"], wait) if wait else cli.get_task(args["task_id"])
    _account_task(args["task_id"], task)
    view = _task_view(task)
    view["session"] = _budget_view()
    if view["status"] not in TERMINAL_STATUSES:
        view["next"] = "Still running: call tripo_get_task again (typical 10-120 s)."
    elif view["status"] == "success":
        view["next"] = "Import with tripo_import_result, or chain tripo_texture_model / tripo_retopology / tripo_rig with input=task_id."
    return view


def tool_tripo_list_tasks(args):
    tasks = [{"task_id": k, **{kk: vv for kk, vv in v.items() if kk != "counted"}} for k, v in _session()["tasks"].items()]
    return {"tasks": sorted(tasks, key=lambda t: t.get("created") or 0, reverse=True), **_budget_view()}


def tool_tripo_upload_file(args):
    cli = client()
    return {"file_token": resolve_input(cli, args["file_name"])}


# ---------------------------------------------------------------------------
# Tools: generation & processing
# ---------------------------------------------------------------------------

GEN_KEYS = ("model", "negative_prompt", "model_seed", "image_seed", "texture_seed", "face_limit", "texture", "pbr",
            "texture_quality", "texture_version", "delight", "geometry_quality", "auto_size", "quad",
            "smart_low_poly", "generate_parts", "compress", "export_orientation", "export_uv")
IMG_KEYS = GEN_KEYS + ("enable_image_autofix", "texture_alignment", "orientation")


def tool_tripo_text_to_model(args):
    payload = _clean({"prompt": args["prompt"], **_pick(args, GEN_KEYS)})
    payload.setdefault("auto_size", True)  # real-world meters -> correct Unreal scale on import
    return _submit("text_to_model", "/generation/text-to-model", payload, args)


def tool_tripo_image_to_model(args):
    cli = client()
    payload = _clean({"input": resolve_input(cli, args["image"]), **_pick(args, IMG_KEYS)})
    payload.setdefault("auto_size", True)
    return _submit("image_to_model", "/generation/image-to-model", payload, args)


def tool_tripo_multiview_to_model(args):
    cli = client()
    views = args.get("views") or {}
    if "front" not in views or len([v for v in views.values() if v]) < 2:
        raise ValueError("views needs 'front' plus at least one of left/back/right")
    inputs = [{k: resolve_input(cli, v)} for k, v in views.items() if k in ("front", "left", "back", "right") and v]
    payload = _clean({"inputs": inputs, **_pick(args, IMG_KEYS)})
    payload.setdefault("auto_size", True)
    return _submit("multiview_to_model", "/generation/multiview-to-model", payload, args)


def tool_tripo_text_to_image(args):
    payload = _clean({"prompt": args["prompt"], **_pick(args, ("model", "size", "quality", "background",
                                                                "aspect_ratio", "output_format", "template"))})
    return _submit("text_to_image", "/generation/text-to-image", payload, args)


def tool_tripo_texture_model(args):
    cli = client()
    tp = {}
    if args.get("texture_text"):
        tp["text"] = args["texture_text"]
    if args.get("style_image"):
        tp["style_image"] = resolve_input(cli, args["style_image"])
    if args.get("reference_image"):
        tp["image"] = resolve_input(cli, args["reference_image"])
    if args.get("reference_views"):
        tp["images"] = [{k: resolve_input(cli, v)} for k, v in args["reference_views"].items() if v]
    payload = _clean({"input": resolve_input(cli, args["input"]), "texture_prompt": tp or None,
                      **_pick(args, ("model", "pbr", "texture_seed", "texture_alignment", "texture_quality",
                                     "part_names", "compress", "bake", "delight"))})
    return _submit("texture_model", "/models/texture", payload, args)


def tool_tripo_retopology(args):
    cli = client()
    payload = _clean({"input": resolve_input(cli, args["input"]),
                      **_pick(args, ("model", "face_limit", "quad", "smart_uv", "bake", "part_names"))})
    return _submit("mesh_decimate", "/mesh/decimate", payload, args)


def tool_tripo_convert(args):
    cli = client()
    payload = _clean({"input": resolve_input(cli, args["input"]), "format": args.get("format", "FBX"),
                      **_pick(args, ("quad", "face_limit", "flatten_bottom", "texture_size", "texture_format", "bake",
                                     "pack_uv", "pivot_to_center_bottom", "scale_factor", "with_animation",
                                     "animate_in_place", "part_names", "export_orientation", "fbx_preset"))})
    return _submit("convert_model", "/models/convert", payload, args)


def tool_tripo_rig_check(args):
    cli = client()
    payload = {"input": resolve_input(cli, args["input"])}
    return _submit("rig_check", "/animations/rig-check", payload, args)


def tool_tripo_rig(args):
    cli = client()
    payload = _clean({"input": resolve_input(cli, args["input"]), "rig_type": args.get("rig_type", "biped"),
                      "spec": args.get("spec", "unreal") if args.get("rig_type", "biped") == "biped" else None,
                      "out_format": args.get("out_format", "fbx"), **_pick(args, ("model",))})
    return _submit("animate_rig", "/animations/rig", payload, args)


def tool_tripo_retarget(args):
    anims = args.get("animations") or ([args["animation"]] if args.get("animation") else [])
    if not anims or len(anims) > 5:
        raise ValueError("Give 1-5 animations, e.g. ['preset:idle', 'preset:walk', 'preset:slash']")
    if not str(args.get("input", "")).startswith("task_") and not _TOKEN.match(str(args.get("input", ""))):
        raise ValueError("input must be the task_id of a successful tripo_rig task")
    payload = _clean({"input": args["input"], ("animation" if len(anims) == 1 else "animations"): anims[0] if len(anims) == 1 else anims,
                      "out_format": args.get("out_format", "fbx"),
                      **_pick(args, ("export_with_geometry", "animate_in_place"))})
    return _submit("animate_retarget", "/animations/retarget", payload, args)


# ---------------------------------------------------------------------------
# Import into Unreal
# ---------------------------------------------------------------------------

_SAFE_ASSET = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _import_on_game_thread(path, dest, name, skeletal, scale, replace):
    u = ue.require()
    task = u.AssetImportTask()
    for prop, value in (("filename", path), ("destination_path", dest), ("destination_name", name),
                        ("automated", True), ("replace_existing", replace), ("save", True)):
        task.set_editor_property(prop, value)
    if path.lower().endswith(".fbx") and hasattr(u, "FbxImportUI"):
        opts = u.FbxImportUI()
        for prop, value in (("import_mesh", True), ("import_materials", True), ("import_textures", True),
                            ("import_as_skeletal", bool(skeletal)), ("import_animations", bool(skeletal))):
            try:
                opts.set_editor_property(prop, value)
            except Exception:
                pass
        try:
            data = opts.get_editor_property("skeletal_mesh_import_data" if skeletal else "static_mesh_import_data")
            data.set_editor_property("import_uniform_scale", float(scale))
            if not skeletal:
                data.set_editor_property("combine_meshes", True)
        except Exception:
            pass
        task.set_editor_property("options", opts)
    u.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    try:
        imported = [str(p) for p in task.get_editor_property("imported_object_paths")]
    except Exception:
        imported = []
    if not imported:
        raise RuntimeError("Unreal imported nothing. GLB needs the glTF/Interchange importer; retry with "
                           "tripo_convert(format='FBX') and import that task.")
    return imported


def _output_url(task, key):
    out = task.get("output") or {}
    if key and out.get(key):
        return out[key], key
    for k in ("pbr_model_url", "model_url", "base_model_url", "generated_image_url"):
        if out.get(k):
            return out[k], k
    raise TripoError(f"Task has no downloadable output (outputs: {sorted(out)})")


def tool_tripo_import_result(args):
    mod = args.get("mod_name")
    dest = args.get("package_path") or (f"/Game/Mods/{mod}/Tripo" if mod else None)
    if not dest or not dest.startswith(MOD_ROOT):
        raise PermissionError("Imports go into /Game/Mods/<YourMod>/...: pass mod_name or a package_path under /Game/Mods")
    cli = client()
    task_id = args["task_id"]
    task = cli.get_task(task_id)
    _account_task(task_id, task)
    if task.get("status") != "success":
        raise TripoError(f"Task {task_id} is '{task.get('status')}', not 'success' yet")
    url, key = _output_url(task, args.get("output"))
    rec = _session()["tasks"].get(task_id, {})
    name = args.get("asset_name") or rec.get("name") or f"SM_Tripo_{task_id[-8:]}"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not _SAFE_ASSET.match(name):
        raise ValueError("asset_name must start with a letter and use letters, digits and _ only")
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or ".glb"
    if ext not in (".glb", ".gltf", ".fbx", ".obj", ".png", ".jpg", ".jpeg", ".webp"):
        raise TripoError(f"Unsupported output type '{ext}'")
    local = execute_on_game_thread(ue.safe_file, f"{name}_{task_id[-8:]}{ext}", WORK_DIR)
    size = cli.download(url, local)
    if args.get("download_only"):
        return {"downloaded": local, "bytes": size, "output": key}
    skeletal = args.get("skeletal")
    if skeletal is None:
        skeletal = (task.get("type") or rec.get("type", "")).startswith("animate")
    folder = f"{dest.rstrip('/')}/{name}"
    imported = execute_on_game_thread(_import_on_game_thread, local, folder, name, skeletal,
                                      float(args.get("import_scale", 1.0)), bool(args.get("replace_existing", False)))
    return {"imported": imported, "folder": folder, "downloaded": local, "bytes": size, "output": key,
            "skeletal": bool(skeletal),
            "next": "Place it with spawn_actor(asset_path=<imported mesh>, snap_to_ground=true); add collision/LODs in the mesh editor if needed."}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(registry):
    spend = {"confirm_spend": {"type": "boolean", "description": "Required to actually spend credits (ask the user first)"},
             "wait_seconds": {"type": "number", "minimum": 0, "maximum": 25, "description": "Optionally wait for the result"},
             "name": {"type": "string", "description": "Name used when importing the result"}}
    gen = {
        "model": {"type": "string", "description": "e.g. v3.1-20260211 (default), v3.0-20250812, v2.5-20250123"},
        "negative_prompt": {"type": "string"}, "face_limit": {"type": "integer", "minimum": 500, "maximum": 2000000},
        "texture": {"type": "boolean"}, "pbr": {"type": "boolean"},
        "texture_quality": {"type": "string", "enum": ["fast", "standard", "detailed", "extreme"]},
        "texture_version": {"type": "string"}, "geometry_quality": {"type": "string", "enum": ["standard", "detailed"]},
        "auto_size": {"type": "boolean"}, "quad": {"type": "boolean"}, "smart_low_poly": {"type": "boolean"},
        "generate_parts": {"type": "boolean"}, "model_seed": {"type": "integer"}, "texture_seed": {"type": "integer"},
        "export_orientation": {"type": "string", "enum": ["+x", "-x", "+y", "-y"]},
    }
    reg = lambda n, d, props, req, fn, level=SAFE_WRITE: registry.register(  # noqa: E731
        n, "Tripo", d, {"properties": props, **({"required": req} if req else {})}, level, fn,
        idempotent=level == READ_ONLY, off_game_thread=True, open_world=True)

    reg("tripo_get_balance", "Tripo account balance, frozen credits, credits spent this session, budget left and observed cost per task type.",
        {}, None, tool_tripo_get_balance, READ_ONLY)
    reg("tripo_get_task", "Status/progress/outputs/credits of a Tripo task (optionally waits up to 25 s). Accounts the credits when finished.",
        {"task_id": {"type": "string"}, "wait_seconds": {"type": "number", "minimum": 0, "maximum": 25}}, ["task_id"],
        tool_tripo_get_task, READ_ONLY)
    reg("tripo_list_tasks", "Tripo tasks created in this editor session with status and credits.", {}, None, tool_tripo_list_tasks, READ_ONLY)
    reg("tripo_upload_file", "Uploads an image/model from Saved/ConanMCP (tripo/inputs or captures) and returns a file_token.",
        {"file_name": {"type": "string"}}, ["file_name"], tool_tripo_upload_file)
    reg("tripo_text_to_model", "Generates a 3D model from text (spends credits; plan only unless confirm_spend=true).",
        {"prompt": {"type": "string"}, **gen, **spend}, ["prompt"], tool_tripo_text_to_model)
    reg("tripo_image_to_model", "Generates a 3D model from one image: file in Saved/ConanMCP (e.g. a capture), https URL, file token or task_id.",
        {"image": {"type": "string"}, **gen, "enable_image_autofix": {"type": "boolean"},
         "texture_alignment": {"type": "string", "enum": ["original_image", "geometry"]}, **spend}, ["image"], tool_tripo_image_to_model)
    reg("tripo_multiview_to_model", "Generates a 3D model from 2-4 views {front (required), left, back, right}.",
        {"views": {"type": "object"}, **gen, **spend}, ["views"], tool_tripo_multiview_to_model)
    reg("tripo_text_to_image", "Generates a concept/reference image (e.g. template t_pose or asset_extraction) to feed image_to_model.",
        {"prompt": {"type": "string"}, "model": {"type": "string"}, "size": {"type": "string"},
         "template": {"type": "string", "enum": ["asset_extraction", "character_completion", "t_pose", "variants", "figure"]},
         "background": {"type": "string", "enum": ["auto", "opaque", "transparent"]}, **spend}, ["prompt"], tool_tripo_text_to_image)
    reg("tripo_texture_model", "Re-textures a model (task_id, file or URL) from a text style, reference image or multi-view references; PBR.",
        {"input": {"type": "string"}, "texture_text": {"type": "string"}, "style_image": {"type": "string"},
         "reference_image": {"type": "string"}, "reference_views": {"type": "object"},
         "model": {"type": "string"}, "pbr": {"type": "boolean"},
         "texture_quality": {"type": "string", "enum": ["fast", "standard", "detailed", "extreme"]},
         "texture_alignment": {"type": "string", "enum": ["original_image", "geometry"]}, "texture_seed": {"type": "integer"},
         **spend}, ["input"], tool_tripo_texture_model)
    reg("tripo_retopology", "Retopology/decimation to a polygon budget (quad optional, smart UVs on v3.0).",
        {"input": {"type": "string"}, "face_limit": {"type": "integer", "minimum": 100}, "quad": {"type": "boolean"},
         "model": {"type": "string", "enum": ["v1.0", "v2.0", "v3.0"]}, "smart_uv": {"type": "boolean"}, "bake": {"type": "boolean"},
         **spend}, ["input", "face_limit"], tool_tripo_retopology)
    reg("tripo_convert", "Converts a model (FBX/GLTF/OBJ/STL/USDZ/3MF), with face limit, texture size, pivot and scale options.",
        {"input": {"type": "string"}, "format": {"type": "string", "enum": ["FBX", "GLTF", "OBJ", "STL", "USDZ", "3MF"]},
         "face_limit": {"type": "integer"}, "texture_size": {"type": "integer"}, "pivot_to_center_bottom": {"type": "boolean"},
         "scale_factor": {"type": "number"}, "fbx_preset": {"type": "string", "enum": ["blender", "3dsmax", "mixamo", "bake_scale"]},
         "quad": {"type": "boolean"}, **spend}, ["input"], tool_tripo_convert)
    reg("tripo_rig_check", "Checks whether a model can be auto-rigged and the recommended rig type.",
        {"input": {"type": "string"}, **spend}, ["input"], tool_tripo_rig_check)
    reg("tripo_rig", "Auto-rigs a model (biped spec 'unreal' by default; quadruped, avian, serpentine...). Output FBX.",
        {"input": {"type": "string"}, "rig_type": {"type": "string", "enum": ["biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic", "others"]},
         "spec": {"type": "string", "enum": ["tripo", "mixamo", "actorcore", "unity", "unreal", "vrm"]},
         "model": {"type": "string"}, "out_format": {"type": "string", "enum": ["glb", "fbx"]}, **spend}, ["input"], tool_tripo_rig)
    reg("tripo_retarget", "Applies 1-5 preset animations (preset:idle, preset:walk, preset:run, preset:slash, ...) to a rigged task.",
        {"input": {"type": "string"}, "animation": {"type": "string"}, "animations": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
         "out_format": {"type": "string", "enum": ["glb", "fbx"]}, "animate_in_place": {"type": "boolean"}, **spend}, ["input"], tool_tripo_retarget)
    reg("tripo_import_result", "Downloads a finished task's model (Tripo hosts only) and imports it into /Game/Mods/<mod>/Tripo/<name>.",
        {"task_id": {"type": "string"}, "mod_name": {"type": "string"}, "package_path": {"type": "string"},
         "asset_name": {"type": "string"}, "output": {"type": "string", "description": "Output key, e.g. pbr_model_url or model_url"},
         "skeletal": {"type": "boolean"}, "import_scale": {"type": "number"}, "replace_existing": {"type": "boolean"},
         "download_only": {"type": "boolean"}}, ["task_id"], tool_tripo_import_result)
