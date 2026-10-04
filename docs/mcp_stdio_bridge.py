#!/usr/bin/env python3
"""
ConanMCP STDIO-to-HTTP Bridge
Universal adapter that translates MCP STDIO (standard input/output) messages 
to the ConanMCP HTTP JSON-RPC endpoint at http://127.0.0.1:8123/mcp.

Usage with Claude Desktop, Cursor, or custom MCP CLI:
  python mcp_stdio_bridge.py [--port 8123] [--host 127.0.0.1] [--token TOKEN]
"""

import sys
import os
import json
import urllib.request
import urllib.error
import argparse

def log_debug(msg: str):
    """Logs diagnostic info strictly to stderr to prevent corrupting stdout JSON-RPC framing."""
    sys.stderr.write(f"[ConanMCP Bridge] {msg}\n")
    sys.stderr.flush()

def main():
    parser = argparse.ArgumentParser(description="ConanMCP STDIO Bridge")
    parser.add_argument("--host", default=os.environ.get("CONAN_MCP_HOST", "127.0.0.1"), help="ConanMCP Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CONAN_MCP_PORT", 8123)), help="ConanMCP Port (default: 8123)")
    parser.add_argument("--token", default=os.environ.get("CONAN_MCP_TOKEN", ""), help="Optional Authorization Bearer token")
    args = parser.parse_args()

    endpoint = f"http://{args.host}:{args.port}/mcp"
    log_debug(f"Bridge initialized. Forwarding STDIO <-> {endpoint}")

    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            line = line.strip()
            if not line:
                continue

            # Parse incoming JSON-RPC
            try:
                rpc_req = json.loads(line)
            except json.JSONDecodeError:
                # Handle Content-Length header framing if client uses it
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":")[1].strip())
                    sys.stdin.readline()  # consume empty delimiter line
                    body = sys.stdin.read(length)
                    rpc_req = json.loads(body)
                else:
                    log_debug(f"Unrecognized framing: {line[:50]}")
                    continue

            req_data = json.dumps(rpc_req).encode("utf-8")
            http_req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers=headers
            )

            try:
                with urllib.request.urlopen(http_req, timeout=35) as resp:
                    resp_bytes = resp.read()
                    if resp.status == 204 or not resp_bytes:
                        # Notification received with No Content (204) - no output to stdout
                        continue
                    sys.stdout.write(resp_bytes.decode("utf-8") + "\n")
                    sys.stdout.flush()
            except urllib.error.HTTPError as e:
                resp_bytes = e.read()
                if resp_bytes:
                    sys.stdout.write(resp_bytes.decode("utf-8") + "\n")
                    sys.stdout.flush()
                else:
                    req_id = rpc_req.get("id") if isinstance(rpc_req, dict) else None
                    if req_id is not None:
                        err_resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32000,
                                "message": f"ConanMCP HTTP Error: {e.code} {e.reason}"
                            }
                        }
                        sys.stdout.write(json.dumps(err_resp) + "\n")
                        sys.stdout.flush()
            except urllib.error.URLError as e:
                # DevKit is likely not running or port is closed
                req_id = rpc_req.get("id") if isinstance(rpc_req, dict) else None
                if req_id is not None:
                    # Return informative message
                    method = rpc_req.get("method", "")
                    if method == "tools/call":
                        err_resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"ConanMCP Server is not reachable at {endpoint}. Ensure Conan Exiles DevKit is running with ConanMCP plugin active."
                                    }
                                ],
                                "isError": True
                            }
                        }
                    else:
                        err_resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32000,
                                "message": f"ConanMCP Server is not reachable at {endpoint}. Ensure Conan Exiles DevKit is running."
                            }
                        }
                    sys.stdout.write(json.dumps(err_resp) + "\n")
                    sys.stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as e:
            log_debug(f"Unhandled error: {e}")

if __name__ == "__main__":
    main()
