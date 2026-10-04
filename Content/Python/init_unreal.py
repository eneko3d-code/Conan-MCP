"""
ConanMCP Unreal Startup Script
Automatically executed by PythonScriptPlugin when the Conan Exiles DevKit launches.
"""

import sys
import os

try:
    import unreal
    unreal.log("LogConanMCP: Starting ConanMCP auto-initializer...")
except ImportError:
    unreal = None

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import conan_mcp_server
    # Host/port come from CONAN_MCP_HOST / CONAN_MCP_PORT (defaults: 127.0.0.1:8123)
    conan_mcp_server.start_server()
    if unreal:
        unreal.log(
            f"LogConanMCP: MCP server started on "
            f"{conan_mcp_server.BIND_ADDRESS}:{conan_mcp_server.DEFAULT_PORT} (Endpoint: /mcp)"
        )
except Exception as e:
    if unreal:
        unreal.log_error(f"LogConanMCP: Failed to auto-start MCP server: {e}")
    else:
        print(f"Failed to auto-start MCP server: {e}")
