"""Server/editor capabilities, undo/redo and Output Log access."""

import glob
import os

from ..core import config, ue
from ..core.security import READ_ONLY, SAFE_WRITE

# Optional engine APIs the tools rely on, reported by get_server_capabilities
PROBES = {
    "editor_actor_subsystem": "EditorActorSubsystem",
    "unreal_editor_subsystem": "UnrealEditorSubsystem",
    "scoped_transactions": "ScopedEditorTransaction",
    "line_traces": "SystemLibrary.line_trace_single",
    "datatable_json": "DataTableFunctionLibrary.export_data_table_to_json_string",
    "datatable_fill_json": "DataTableFunctionLibrary.fill_data_table_from_json_string",
    "blueprint_editor_library": "BlueprintEditorLibrary",
    "blueprint_add_variable": "BlueprintEditorLibrary.add_member_variable",
    "subobject_data_subsystem": "SubobjectDataSubsystem",
    "editor_validator": "EditorValidatorSubsystem",
    "high_res_screenshot": "AutomationLibrary.take_high_res_screenshot",
    "scene_capture": "SceneCapture2D",
    "render_target_export": "RenderingLibrary.export_render_target",
    "dirty_packages": "EditorLoadingAndSavingUtils.get_dirty_content_packages",
    "landscape": "Landscape",
    "native_library": ue.NATIVE_LIBRARY_NAME,
    "control_rig_sequencer": "ControlRigSequencerLibrary",
    "fk_control_rig": "FKControlRig",
    "level_sequence": "LevelSequence",
    "sequencer_editor": "LevelSequenceEditorBlueprintLibrary.set_current_time",
    "export_anim_sequence": "SequencerTools.export_anim_sequence",
    "anim_notifies": "AnimationLibrary.add_animation_notify_event",
    "reference_pose": "AnimPoseExtensions.get_reference_pose",
    "montage_factory": "AnimMontageFactory",
    "niagara": "NiagaraFunctionLibrary.spawn_system_attached",
}


def tool_get_server_capabilities(args):
    caps = {k: ue.has(v) for k, v in PROBES.items()}
    lib = ue.native()
    native_fns = sorted(n for n in dir(lib) if not n.startswith("_")) if lib else []
    return {
        "server_version": config.SERVER_VERSION,
        "engine_available": ue.unreal is not None,
        "engine_version": ue.unreal.SystemLibrary.get_engine_version() if ue.has("SystemLibrary.get_engine_version") else None,
        "capabilities": caps,
        "native_library_functions": native_fns,
        "terrain_editing": ("native (in-editor sculpting & painting)" if lib else
                            "heightmap file workflow (export from Landscape mode, edit, re-import)"),
        "security": {
            "write_tools": config.ENABLE_WRITE_TOOLS,
            "destructive_tools": config.ENABLE_DESTRUCTIVE_TOOLS,
            "token_required": bool(config.CONAN_MCP_TOKEN),
            "max_actors_per_write": config.MAX_ACTORS_PER_WRITE,
        },
        "files_dir": ue.saved_dir() if ue.unreal is not None else None,
        "tripo": {
            "api_key_configured": bool(os.environ.get("TRIPO_API_KEY", "").strip()),
            "base_url": config.TRIPO_BASE_URL,
            "session_budget": config.TRIPO_BUDGET or None,
            "min_balance": config.TRIPO_MIN_BALANCE or None,
            "note": "Set TRIPO_API_KEY to enable the tripo_* tools; every spend needs confirm_spend=true.",
        },
    }


def _console(command: str) -> None:
    u = ue.require()
    u.SystemLibrary.execute_console_command(ue.get_world(), command)


def tool_undo(args):
    steps = int(args.get("steps", 1))
    lib = ue.native()
    done = 0
    for _ in range(steps):
        if lib and hasattr(lib, "undo_last_transaction"):
            if not lib.undo_last_transaction():
                break
        else:
            _console("TRANSACTION UNDO")
        done += 1
    return {"undone_steps": done}


def tool_redo(args):
    steps = int(args.get("steps", 1))
    lib = ue.native()
    done = 0
    for _ in range(steps):
        if lib and hasattr(lib, "redo_last_transaction"):
            if not lib.redo_last_transaction():
                break
        else:
            _console("TRANSACTION REDO")
        done += 1
    return {"redone_steps": done}


def _latest_log_file():
    files = glob.glob(os.path.join(ue.log_dir(), "*.log"))
    files = [f for f in files if "backup" not in os.path.basename(f).lower()]
    return max(files, key=os.path.getmtime) if files else None


def read_log_tail(max_lines: int = 200, contains: str = "", category: str = "", min_level: str = "") -> dict:
    path = _latest_log_file()
    if not path:
        return {"log_file": None, "lines": []}
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 2 * 1024 * 1024))  # last 2 MB is plenty
        lines = f.read().splitlines()
    level_words = {"error": ("Error:",), "warning": ("Error:", "Warning:")}.get(min_level.lower(), ())
    out = []
    for line in lines:
        if contains and contains.lower() not in line.lower():
            continue
        if category and f"{category}:" not in line:
            continue
        if level_words and not any(w in line for w in level_words):
            continue
        out.append(line)
    return {"log_file": os.path.basename(path), "total_matching": len(out), "lines": out[-max_lines:]}


def tool_get_output_log(args):
    return read_log_tail(
        max_lines=int(args.get("max_lines", 200)),
        contains=args.get("contains", ""),
        category=args.get("category", ""),
        min_level=args.get("min_level", ""),
    )


def register(registry):
    registry.register("get_server_capabilities", "System",
                      "Reports which engine APIs, native C++ helpers and security settings are available. Call this first.",
                      {"properties": {}}, READ_ONLY, tool_get_server_capabilities)
    registry.register("undo", "System", "Undoes the last editor transaction(s) (same as Ctrl+Z).",
                      {"properties": {"steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1}}},
                      SAFE_WRITE, tool_undo, idempotent=False)
    registry.register("redo", "System", "Redoes the last undone editor transaction(s) (same as Ctrl+Y).",
                      {"properties": {"steps": {"type": "integer", "minimum": 1, "maximum": 50, "default": 1}}},
                      SAFE_WRITE, tool_redo, idempotent=False)
    registry.register("get_output_log", "System",
                      "Reads the tail of the editor Output Log file (compile errors, warnings, cook messages), with filters.",
                      {"properties": {
                          "max_lines": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
                          "contains": {"type": "string", "description": "Case-insensitive substring filter"},
                          "category": {"type": "string", "description": "Log category, e.g. LogBlueprint, LogConanMCP"},
                          "min_level": {"type": "string", "enum": ["", "warning", "error"]},
                      }}, READ_ONLY, tool_get_output_log)
