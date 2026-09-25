#!/usr/bin/env python3
"""
ConanMCP STDIO-to-HTTP Bridge
Universal adapter that translates MCP STDIO (standard input/output) messages 
to the ConanMCP HTTP JSON-RPC endpoint at http://127.0.0.1:8123/mcp.

Usage with Claude Desktop, Cursor, or custom MCP CLI:
  python mcp_stdio_bridge.py [--port 8123] [--host 127.0.0.1]
"""

import sys
import json
import urllib.request
import urllib.error
import argparse

def main():
    parser = argparse.ArgumentParser(description="ConanMCP STDIO Bridge")
    parser.add_argument("--host", default="127.0.0.1", help="ConanMCP Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8123, help="ConanMCP Port (default: 8123)")
    args = parser.parse_args()

    endpoint = f"http://{args.host}:{args.port}/mcp"

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
                    sys.stdin.readline()  # consume empty line
                    body = sys.stdin.read(length)
                    rpc_req = json.loads(body)
                else:
                    continue

            # Forward to HTTP endpoint
            req_data = json.dumps(rpc_req).encode("utf-8")
            http_req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )

            try:
                with urllib.request.urlopen(http_req, timeout=30) as resp:
                    resp_bytes = resp.read()
                    sys.stdout.write(resp_bytes.decode("utf-8") + "\n")
                    sys.stdout.flush()
            except urllib.error.URLError as e:
                # DevKit is likely not running or port is closed
                req_id = rpc_req.get("id")
                if req_id is not None:
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
            sys.stderr.write(f"[ConanMCP Bridge Error] {e}\n")
            sys.stderr.flush()

if __name__ == "__main__":
    main()
