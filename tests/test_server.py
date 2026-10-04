"""Unit/integration tests for the ConanMCP Python server (no Unreal Engine required)."""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Content", "Python"))
import conan_mcp_server as srv  # noqa: E402


def rpc(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        msg["id"] = req_id
    if params is not None:
        msg["params"] = params
    return json.loads(srv.process_json_rpc(json.dumps(msg)))


# --- JSON-RPC engine -------------------------------------------------------

def test_initialize_and_capabilities():
    res = rpc("initialize")["result"]
    assert res["protocolVersion"] == "2024-11-05"
    assert {"tools", "resources", "prompts"} <= set(res["capabilities"])


def test_notification_gets_no_response():
    assert srv.process_json_rpc(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None


def test_batch_skips_notifications():
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    out = json.loads(srv.process_json_rpc(json.dumps(batch)))
    assert len(out) == 1 and out[0]["id"] == 1


def test_parse_error_and_unknown_method():
    assert json.loads(srv.process_json_rpc("{nope"))["error"]["code"] == -32700
    assert rpc("does/not/exist")["error"]["code"] == -32601


def test_tools_list_matches_registry():
    tools = rpc("tools/list")["result"]["tools"]
    assert len(tools) == len(srv.registry.tools) >= 46


# --- Security policy -------------------------------------------------------

def test_execute_python_is_destructive_and_disabled_by_default(monkeypatch):
    assert srv.registry.get_tool("execute_python")["security"] == srv.DESTRUCTIVE
    monkeypatch.setattr(srv, "ENABLE_DESTRUCTIVE_TOOLS", False)
    res = rpc("tools/call", {"name": "execute_python", "arguments": {"code": "_result = 1"}})["result"]
    assert res["isError"] is True and "DESTRUCTIVE" in res["content"][0]["text"]


def test_execute_python_runs_when_enabled(monkeypatch):
    monkeypatch.setattr(srv, "ENABLE_DESTRUCTIVE_TOOLS", True)
    res = rpc("tools/call", {"name": "execute_python", "arguments": {"code": "_result = 2 + 2"}})["result"]
    assert res["isError"] is False
    assert json.loads(res["content"][0]["text"])["result"] == "4"


def test_write_tools_can_be_disabled(monkeypatch):
    monkeypatch.setattr(srv, "ENABLE_WRITE_TOOLS", False)
    res = rpc("tools/call", {"name": "save_current_level", "arguments": {}})["result"]
    assert res["isError"] is True


@pytest.mark.parametrize("bad", ["/Game/../Windows", "C:\\Windows", "/etc/passwd", "/Game//x", "Game/x"])
def test_path_validation_rejects(bad):
    with pytest.raises(ValueError):
        srv.validate_package_path(bad)


@pytest.mark.parametrize("good", ["/Game", "/Game/Mods/BP_X.BP_X", "/ConanSandbox/Items", "/Engine/Foo"])
def test_path_validation_accepts(good):
    srv.validate_package_path(good)


def test_tool_call_rejects_traversal():
    res = rpc("tools/call", {"name": "find_assets", "arguments": {"package_path": "/Game/../../x"}})["result"]
    assert res["isError"] is True and "traversal" in res["content"][0]["text"]


def test_resource_template_rejects_outside_roots():
    with pytest.raises(ValueError):
        srv.resource_template_conan_asset("conan://asset/x", "/etc/passwd")


# --- Game thread dispatcher ------------------------------------------------

def test_timeout_cancels_queued_task(monkeypatch):
    """A task that timed out must not run later."""
    ran = []
    monkeypatch.setattr(srv, "unreal", object())  # force the queue path
    monkeypatch.setattr(srv, "ensure_ticker_registered", lambda: None)
    monkeypatch.setattr(srv, "TOOL_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(TimeoutError):
        srv.execute_on_game_thread(lambda: ran.append(1))
    srv._game_thread_ticker(0.0)  # drain the queue as the engine tick would
    assert ran == []


# --- HTTP transport --------------------------------------------------------

@pytest.fixture()
def http_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.ConanMCPRequestHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def http(url, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_post_mcp_roundtrip(http_server):
    status, headers, body = http(http_server + "/mcp", "POST",
                                 {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                 {"Content-Type": "application/json"})
    assert status == 200 and json.loads(body)["result"] == {}
    assert "Access-Control-Allow-Origin" not in headers  # no wildcard CORS


def test_cross_origin_post_is_blocked(http_server):
    status, _, _ = http(http_server + "/mcp", "POST",
                        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                        {"Content-Type": "application/json", "Origin": "http://evil.example"})
    assert status == 403


def test_preflight_from_foreign_origin_is_blocked(http_server):
    status, headers, _ = http(http_server + "/mcp", "OPTIONS", headers={"Origin": "http://evil.example"})
    assert status == 403 and "Access-Control-Allow-Origin" not in headers


def test_localhost_origin_is_allowed(http_server):
    status, headers, _ = http(http_server + "/mcp", "OPTIONS", headers={"Origin": "http://localhost:5173"})
    assert status == 204 and headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_bad_host_header_is_blocked(http_server):
    status, _, _ = http(http_server + "/mcp", headers={"Host": "attacker.example"})
    assert status == 403


def test_oversized_body_rejected(http_server):
    req = urllib.request.Request(http_server + "/mcp", data=b"{}", method="POST",
                                 headers={"Content-Length": str(srv.MAX_REQUEST_BODY_BYTES + 1)})
    with pytest.raises((urllib.error.HTTPError, urllib.error.URLError, ConnectionError)):
        urllib.request.urlopen(req, timeout=5)


def test_token_enforced(http_server, monkeypatch):
    monkeypatch.setattr(srv, "CONAN_MCP_TOKEN", "s3cret")
    assert http(http_server + "/mcp")[0] == 401
    assert http(http_server + "/mcp", headers={"Authorization": "Bearer s3cret"})[0] == 200


def test_unknown_post_route_404(http_server):
    assert http(http_server + "/nope", "POST", {})[0] == 404


def test_messages_requires_valid_session(http_server):
    status, _, _ = http(http_server + "/messages?sessionId=bogus", "POST",
                        {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert status == 404


def test_sse_transport_replies_over_stream(http_server):
    """POST /messages -> 202, and the JSON-RPC reply arrives on the SSE stream."""
    stream = urllib.request.urlopen(http_server + "/sse", timeout=5)
    try:
        assert stream.readline().strip() == b"event: endpoint"
        endpoint = stream.readline().decode().split("data:", 1)[1].strip()
        stream.readline()  # blank line

        status, _, _ = http(http_server + endpoint, "POST", {"jsonrpc": "2.0", "id": 7, "method": "ping"})
        assert status == 202

        while True:
            line = stream.readline().decode()
            if line.startswith("data:") and '"id": 7' in line:
                assert json.loads(line[5:])["result"] == {}
                break
    finally:
        stream.close()
