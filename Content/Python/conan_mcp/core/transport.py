"""HTTP + SSE transport for the MCP server (binds to loopback only)."""

import hmac
import json
import queue
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from . import config, sse
from .log import log_error, log_info
from .protocol import process_json_rpc
from .registry import prompt_registry, registry, resource_registry
from .state import STATE


class ConanMCPRequestHandler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, socket.error):
            pass

    def log_message(self, format, *args):
        # Suppress default noisy access logs
        pass

    def _send_json(self, status: int, payload: Any, extra_headers: Optional[Dict[str, str]] = None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _is_local_host(value: str) -> bool:
        """True if a Host header value or an Origin URL points at the loopback interface."""
        value = value.strip().lower()
        if "://" in value:
            value = value.split("://", 1)[1]
        value = value.split("/", 1)[0]
        if value.startswith("["):  # IPv6 literal, e.g. [::1]:8123
            host = value.split("]", 1)[0] + "]"
        else:
            host = value.split(":", 1)[0]
        return host in config.ALLOWED_LOCAL_HOSTS

    def _send_cors_headers(self):
        # Only echo back loopback origins; never a wildcard.
        origin = self.headers.get("Origin", "")
        if origin and self._is_local_host(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def check_security(self) -> bool:
        # 1. Host header validation against DNS rebinding
        host = self.headers.get("Host", "")
        if host and not self._is_local_host(host):
            self._send_json(403, {
                "error": "Forbidden: Host header blocked for localhost security (Anti-DNS Rebinding)"
            })
            return False

        # 2. Origin validation: browsers always send Origin on cross-site requests.
        #    Native MCP clients do not send it, so a non-local Origin means a web page is attacking us.
        origin = self.headers.get("Origin", "")
        if origin and not self._is_local_host(origin):
            self._send_json(403, {
                "error": "Forbidden: cross-origin requests are not allowed"
            })
            return False

        # 3. Bearer token validation if configured (constant-time comparison)
        if config.CONAN_MCP_TOKEN:
            auth_header = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth_header, f"Bearer {config.CONAN_MCP_TOKEN}"):
                self._send_json(401, {
                    "error": "Unauthorized: Valid Authorization Bearer token required"
                })
                return False

        return True

    def do_OPTIONS(self):
        # CORS preflight: answer only for loopback hosts/origins.
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if (host and not self._is_local_host(host)) or (origin and not self._is_local_host(origin)):
            self._send_json(403, {"error": "Forbidden"})
            return
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.check_security():
            return

        path = self.path.split("?")[0]

        # Standard MCP Server-Sent Events (SSE) Transport
        if path == "/sse":
            session_id = sse.get_manager().create_session()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self._send_cors_headers()
            self.end_headers()

            # MCP SSE Handshake: send initial endpoint event
            endpoint_event = f"event: endpoint\ndata: /messages?sessionId={session_id}\n\n"
            self.wfile.write(endpoint_event.encode("utf-8"))
            self.wfile.flush()

            session_queue = sse.get_manager().get_queue(session_id)
            try:
                while STATE.server_running and sse.get_manager().has_session(session_id):
                    try:
                        msg = session_queue.get(timeout=2.0)
                        evt = f"event: message\ndata: {msg}\n\n"
                        self.wfile.write(evt.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error):
                pass
            finally:
                sse.get_manager().remove_session(session_id)
            return

        elif path in [config.ENDPOINT_PATH, "/", "/health", "/status"]:
            body_obj = {
                "service": "ConanMCP",
                "version": config.SERVER_VERSION,
                "protocol": f"MCP / JSON-RPC 2.0 ({config.PROTOCOL_VERSION})",
                "status": "running",
                "registered_tools": len(registry.tools),
                "registered_resources": len(resource_registry.resources),
                "registered_resource_templates": len(resource_registry.templates),
                "registered_prompts": len(prompt_registry.prompts),
                "sse_endpoint": "/sse",
                "messages_endpoint": "/messages"
            }
            self._send_json(200, body_obj)
        else:
            self.send_error(404, f"Endpoint '{self.path}' not found")

    def do_POST(self):
        if not self.check_security():
            return

        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route not in (config.ENDPOINT_PATH, "/messages"):
            self._send_json(404, {"error": f"Endpoint '{route}' not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length"})
            return
        if content_length < 0 or content_length > config.MAX_REQUEST_BODY_BYTES:
            self._send_json(413, {"error": f"Request body exceeds {config.MAX_REQUEST_BODY_BYTES} bytes"})
            return

        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
        except UnicodeDecodeError:
            self._send_json(400, {"error": "Request body must be UTF-8"})
            return

        # SSE transport: POST /messages?sessionId=... -> 202 Accepted, reply travels over the SSE stream.
        if route == "/messages":
            session_id = urllib.parse.parse_qs(parsed.query).get("sessionId", [""])[0]
            if not sse.get_manager().has_session(session_id):
                self._send_json(404, {"error": "Unknown or expired sessionId"})
                return
            self.send_response(202)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
            # Tools may take seconds on the Game Thread: do not hold the POST open.
            threading.Thread(
                target=_process_sse_message,
                args=(session_id, raw_body),
                daemon=True,
                name="ConanMCP_SSEWorker",
            ).start()
            return

        # Streamable HTTP-style transport: reply in the response body.
        response_body = process_json_rpc(raw_body)
        if response_body is None or response_body == "":
            self.send_response(204)  # No Content for notifications
            self._send_cors_headers()
            self.end_headers()
        else:
            payload = response_body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)


def _process_sse_message(session_id: str, raw_body: str):
    """Runs a JSON-RPC message and pushes the reply to the client's SSE stream."""
    try:
        response_body = process_json_rpc(raw_body)
    except Exception as e:  # never let a worker thread die silently
        STATE.count_error()
        log_error(f"SSE worker failed: {e}")
        response_body = json.dumps({
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32603, "message": f"Internal error: {e}"}
        })
    if response_body:
        sse.get_manager().send_to_session(session_id, response_body)


# =============================================================================
# SERVER LIFECYCLE
# =============================================================================

class ConanMCPServerThread(threading.Thread):
    def __init__(self, host=None, port=None):
        super().__init__(daemon=True, name="ConanMCP_ServerThread")
        self.host = host or config.BIND_ADDRESS
        self.port = int(port or config.DEFAULT_PORT)
        self.httpd = None

    def run(self):
        STATE.server_running = True
        try:
            self.httpd = ThreadingHTTPServer((self.host, self.port), ConanMCPRequestHandler)
            self.httpd.daemon_threads = True
            log_info(f"MCP server started on {self.host}:{self.port} (Endpoints: {config.ENDPOINT_PATH}, /sse, /messages)")
            self.httpd.serve_forever()
        except Exception as e:
            log_error(f"Failed to start server on {self.host}:{self.port}: {str(e)}")

    def stop(self):
        STATE.server_running = False
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            log_info("MCP server stopped")
