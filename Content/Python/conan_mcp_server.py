"""
ConanMCP - MCP (Model Context Protocol) server for the Conan Exiles Enhanced DevKit.

Compatibility entry point: the implementation lives in the ``conan_mcp`` package.
Existing scripts can keep calling ``conan_mcp_server.start_server()``.
"""

from conan_mcp.core import config
from conan_mcp.core.protocol import call_tool, process_json_rpc, process_single_request  # noqa: F401
from conan_mcp.core.registry import prompt_registry, registry, resource_registry  # noqa: F401
from conan_mcp.server import (get_server_status, register_everything, reload_server_module,  # noqa: F401
                              start_server, stop_server)

BIND_ADDRESS = config.BIND_ADDRESS
DEFAULT_PORT = config.DEFAULT_PORT

register_everything()
