"""Runtime configuration (environment variables CONAN_MCP_*).

Other modules read these as ``config.NAME`` at call time, so tests and the
editor can change them without restarting the server.
"""

import os

SERVER_NAME = "conan-devkit-mcp"
SERVER_VERSION = "2.0.0"
PROTOCOL_VERSION = "2024-11-05"

BIND_ADDRESS = os.environ.get("CONAN_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CONAN_MCP_PORT", 8123))
ENDPOINT_PATH = "/mcp"
CONAN_MCP_TOKEN = os.environ.get("CONAN_MCP_TOKEN", "")

# Security flags
ENABLE_WRITE_TOOLS = os.environ.get("CONAN_MCP_READONLY", "0") != "1"
# Destructive tools (execute_python, delete_asset) are opt-in
ENABLE_DESTRUCTIVE_TOOLS = os.environ.get("CONAN_MCP_ENABLE_DESTRUCTIVE", "0") == "1"
ENABLE_LOGGING = os.environ.get("CONAN_MCP_QUIET", "0") != "1"
MAX_RESULTS = 50

# Maximum seconds a tool may wait for the Game Thread
TOOL_TIMEOUT_SECONDS = float(os.environ.get("CONAN_MCP_TIMEOUT", 30))
# Maximum accepted HTTP request body (bytes)
MAX_REQUEST_BODY_BYTES = 1024 * 1024
# Package roots that tools are allowed to touch
ALLOWED_PACKAGE_ROOTS = ("/Game", "/Engine", "/ConanSandbox")
# Hosts allowed in the Host / Origin headers (anti DNS-rebinding / anti browser CSRF)
ALLOWED_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")

# Hard limits for bulk level operations
MAX_ACTORS_PER_WRITE = int(os.environ.get("CONAN_MCP_MAX_ACTORS", 200))
MAX_TRACE_SAMPLES = 16384
# Folder (inside the project's Saved/ dir) used for every file the server reads or writes
SAVED_SUBDIR = "ConanMCP"

# Optional extra sys.path entries (Unreal experimental toolsets), separated by os.pathsep
EXTRA_PYTHON_PATHS = [p for p in os.environ.get("CONAN_MCP_EXTRA_PATHS", "").split(os.pathsep) if p]
