"""JSON-RPC 2.0 / MCP (2024-11-05) request engine."""

import json
import time
from typing import Any, Dict, Optional

from . import config
from .dispatcher import execute_on_game_thread
from .log import log_error, log_info, log_warning
from .registry import prompt_registry, registry, resource_registry
from .results import ToolResult
from .security import check_level_allowed, validate_tool_arguments
from .state import STATE


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    STATE.count_error()
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_error(req_id, text):
    return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": True})


def call_tool(tool_name: str, tool_args: dict) -> Dict[str, Any]:
    """Runs a tool and returns an MCP CallToolResult dict (never raises)."""
    tool_def = registry.get_tool(tool_name)
    if not tool_def:
        raise KeyError(tool_name)
    denied = check_level_allowed(tool_def["security"])
    if denied:
        return {"content": [{"type": "text", "text": denied}], "isError": True}

    start = time.time()
    log_info(f"Tool called: {tool_name}")
    try:
        validate_tool_arguments(tool_args, tool_def.get("inputSchema"))
        result = execute_on_game_thread(tool_def["handler"], tool_args)
    except Exception as e:
        STATE.count_error()
        log_error(f"Tool error in '{tool_name}': {e}")
        return {"content": [{"type": "text", "text": f"Error executing tool '{tool_name}': {e}"}], "isError": True}

    log_info(f"Tool '{tool_name}' completed in {(time.time() - start) * 1000.0:.1f} ms")
    if isinstance(result, ToolResult):
        content = result.to_content()
    else:
        text = result if isinstance(result, str) else json.dumps(result, indent=2)
        content = [{"type": "text", "text": text}]
    return {"content": content, "isError": False}


def _initialize_result():
    return {
        "protocolVersion": config.PROTOCOL_VERSION,
        "serverInfo": {"name": config.SERVER_NAME, "version": config.SERVER_VERSION},
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "prompts": {"listChanged": True},
            "logging": {},
        },
        "instructions": (
            "ConanMCP controls the Conan Exiles DevKit editor. Start with get_server_capabilities, "
            "load the matching skill prompt (conan-map-design, conan-landscape-sculpting, conan-structures, "
            "conan-items-recipes, conan-blueprint-authoring, conan-animation-from-reference, conan-custom-attacks-vfx, "
            "conan-mod-release, conan-mcp-safety) "
            "and prefer dry_run=true before any write. Every write is undoable with the 'undo' tool."
        ),
    }


def process_single_request(req: Any) -> Optional[Dict[str, Any]]:
    """Processes one JSON-RPC request/notification. Returns None for notifications."""
    STATE.count_request()
    if not isinstance(req, dict):
        return _err(None, -32600, "Invalid Request: expected JSON object")

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if not method:
        return _err(req_id, -32600, "Invalid Request: missing 'method' field")
    if not isinstance(params, dict):
        return _err(req_id, -32602, "Invalid params: expected an object")

    # Notifications MUST NOT receive a response
    if method.startswith("notifications/"):
        if method == "notifications/initialized":
            log_info("MCP client initialized")
        elif method == "notifications/cancelled":
            log_warning(f"Client cancelled request: {params.get('requestId')}")
        return None

    if method == "initialize":
        return _ok(req_id, _initialize_result())
    if method == "ping":
        return _ok(req_id, {})
    if method == "logging/setLevel":
        log_info(f"Logging level set to: {params.get('level', 'info')}")
        return _ok(req_id, {})

    if method == "conan/reload":
        denied = check_level_allowed("SAFE_WRITE")
        if denied:
            return _err(req_id, -32000, denied)
        from .. import server
        return _ok(req_id, execute_on_game_thread(server.reload_server_module))

    if method == "tools/list":
        return _ok(req_id, {"tools": registry.list_tools_schema()})
    if method == "tools/call":
        name = params.get("name")
        if not name:
            return _err(req_id, -32602, "Invalid params: 'name' is required")
        try:
            return _ok(req_id, call_tool(name, params.get("arguments") or {}))
        except KeyError:
            return _err(req_id, -32601, f"Tool '{name}' not found")

    if method == "resources/list":
        return _ok(req_id, {"resources": resource_registry.list_resources_schema()})
    if method == "resources/templates/list":
        return _ok(req_id, {"resourceTemplates": resource_registry.list_templates_schema()})
    if method == "resources/read":
        uri = params.get("uri")
        if not uri:
            return _err(req_id, -32602, "Missing 'uri' parameter for resources/read")
        try:
            return _ok(req_id, {"contents": [resource_registry.read_resource(uri, execute_on_game_thread)]})
        except Exception as e:
            return _err(req_id, -32002, f"Resource error: {e}")
    if method == "resources/subscribe":
        if params.get("uri"):
            STATE.resource_subscriptions.add(params["uri"])
        return _ok(req_id, {})
    if method == "resources/unsubscribe":
        STATE.resource_subscriptions.discard(params.get("uri"))
        return _ok(req_id, {})

    if method == "prompts/list":
        return _ok(req_id, {"prompts": prompt_registry.list_prompts_schema()})
    if method == "prompts/get":
        name = params.get("name")
        if not name:
            return _err(req_id, -32602, "Missing 'name' parameter for prompts/get")
        try:
            return _ok(req_id, prompt_registry.get_prompt(name, params.get("arguments") or {}))
        except Exception as e:
            return _err(req_id, -32602, f"Prompt error: {e}")

    return _err(req_id, -32601, f"Method '{method}' not found")


def process_json_rpc(raw_json: str) -> Optional[str]:
    """Parses JSON input and routes single or batch requests."""
    try:
        parsed = json.loads(raw_json)
    except Exception as e:
        return json.dumps(_err(None, -32700, f"Parse error: {e}"))

    if isinstance(parsed, list):
        if not parsed:
            return json.dumps(_err(None, -32600, "Invalid Request: empty batch"))
        responses = [r for r in (process_single_request(req) for req in parsed) if r is not None]
        return json.dumps(responses) if responses else None
    resp = process_single_request(parsed)
    return json.dumps(resp) if resp is not None else None
