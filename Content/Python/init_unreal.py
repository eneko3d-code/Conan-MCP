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
    conan_mcp_server.start_server(host="127.0.0.1", port=8123)
    if unreal:
        unreal.log("LogConanMCP: MCP server started on 127.0.0.1:8123 (Endpoint: /mcp)")
except Exception as e:
    if unreal:
        unreal.log_error(f"LogConanMCP: Failed to auto-start MCP server: {e}")
    else:
        print(f"Failed to auto-start MCP server: {e}")
