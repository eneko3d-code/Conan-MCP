"""Server lifecycle: registration, start/stop, hot reload."""

import importlib
import os
import sys

from .core import config, ue
from .core.dispatcher import ensure_ticker_registered, unregister_ticker
from .core.log import log_info, log_warning
from .core.registry import prompt_registry, registry, resource_registry
from .core.sse import get_manager
from .core.state import STATE

# Tool modules, in registration order. Later modules override same-named tools
# (e.g. datatables replaces the v1 get_datatable_row stub).
TOOL_MODULES = (
    "builtin", "system", "level", "mapping", "landscape", "capture", "datatables", "blueprints", "mod", "animation", "tripo",
)

# Modules reloaded by reload_server_module(), in dependency order. core.state is never reloaded.
_RELOAD_ORDER = (
    "core.config", "core.ue", "core.sse", "core.log", "core.security", "core.results", "core.registry",
    "core.dispatcher", "core.protocol", "core.transport",
    "mapping.heightmap", "mapping.terrain", "tools.landscape_rt", "mapping.placement", "mapping.classify",
    "animation.roles", "animation.pose", "animation.timing", "integrations.tripo",
) + tuple(f"tools.{m}" for m in TOOL_MODULES) + ("prompts",)


def _add_engine_toolset_paths():
    """Make Unreal's experimental Python toolsets importable, wherever the DevKit is installed."""
    paths = list(config.EXTRA_PYTHON_PATHS)
    u = ue.unreal
    if u is not None and hasattr(u, "Paths"):
        try:
            engine = u.Paths.convert_relative_path_to_full(u.Paths.engine_dir())
            for rel in ("Plugins/Experimental/ToolsetRegistry/Content/Python",
                        "Plugins/Experimental/Toolsets/EditorToolset/Content/Python",
                        "Plugins/Experimental/Toolsets/NiagaraToolsets/Content/Python"):
                paths.append(os.path.join(engine, rel))
        except Exception:
            pass
    for p in paths:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)


def _module(name):
    return importlib.import_module(f"{__package__}.{name}")


def register_everything():
    registry.clear()
    resource_registry.clear()
    prompt_registry.clear()
    builtin = _module("tools.builtin")
    builtin.register_resources(resource_registry)
    builtin.register_prompts(prompt_registry)
    for name in TOOL_MODULES:
        mod = _module(f"tools.{name}")
        if name == "builtin":
            mod.register_tools(registry)
        else:
            mod.register(registry)
    _module("prompts").register(prompt_registry)
    log_info(f"Registered {len(registry.tools)} tools, {len(resource_registry.resources)} resources, "
             f"{len(prompt_registry.prompts)} prompts")


def reload_server_module() -> dict:
    """Hot-reloads every module (state is preserved) and re-registers tools/resources/prompts."""
    for name in _RELOAD_ORDER:
        full = f"{__package__}.{name}"
        if full in sys.modules:
            importlib.reload(sys.modules[full])
    me = importlib.reload(sys.modules[__name__])
    me.register_everything()
    ensure_ticker_registered()
    get_manager().broadcast_notification("notifications/tools/list_changed", {})
    get_manager().broadcast_notification("notifications/prompts/list_changed", {})
    from .core.registry import prompt_registry as p, registry as r, resource_registry as rr
    return {"reloaded": True, "tools_count": len(r.tools), "resources_count": len(rr.resources),
            "prompts_count": len(p.prompts)}


def start_server(host=None, port=None):
    from .core.transport import ConanMCPServerThread
    if STATE.server_instance and STATE.server_instance.is_alive():
        log_warning("MCP server is already running")
        return STATE.server_instance
    _add_engine_toolset_paths()
    register_everything()
    ensure_ticker_registered()
    STATE.server_instance = ConanMCPServerThread(host, port)
    STATE.server_instance.start()
    return STATE.server_instance


def stop_server():
    if STATE.server_instance:
        STATE.server_instance.stop()
        STATE.server_instance = None
    unregister_ticker()


def get_server_status():
    inst = STATE.server_instance
    running = inst is not None and inst.is_alive()
    info = {
        "running": running,
        "host": inst.host if running else None,
        "port": inst.port if running else None,
        "tools_registered": len(registry.tools),
        "resources_registered": len(resource_registry.resources),
        "prompts_registered": len(prompt_registry.prompts),
    }
    log_info(f"Status: {info}")
    return info
