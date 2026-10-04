# Changelog

## 1.1.1 — Security & protocol hardening
### Security
- Reject requests with non-loopback `Origin`/`Host` headers; removed wildcard CORS (a web page could previously reach `execute_python`).
- `execute_python` is now `DESTRUCTIVE` and disabled unless `CONAN_MCP_ENABLE_DESTRUCTIVE=1`.
- Package-path validation (`/Game`, `/Engine`, `/ConanSandbox`, no traversal) on every tool and the `conan://asset/` resource.
- Bearer token compared in constant time; request bodies capped at 1 MB.
### Protocol
- SSE transport now follows the 2024-11-05 spec: `POST /messages?sessionId=` returns `202` and the reply is delivered on the SSE stream.
- Game Thread timeout unified at 30 s (`CONAN_MCP_TIMEOUT`); timed-out tasks are cancelled instead of running later.
- Thread-safe request/error counters; `init_unreal.py` honours `CONAN_MCP_HOST` / `CONAN_MCP_PORT`.
### Other
- The native C++ server no longer auto-starts by default (it shared port 8123 with the Python server).
- Added `pytest` suite (`tests/`) and GitHub Actions CI.
