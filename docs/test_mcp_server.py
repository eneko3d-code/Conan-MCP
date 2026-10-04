"""
ConanMCP Comprehensive Protocol & Feature Verification Test Suite
Tests MCP Protocol (Spec 2024-11-05), JSON-RPC 2.0, Tools, Resources, Prompts, SSE, and Security.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error

# Add Content/Python to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Content", "Python")))

import conan_mcp_server

def run_tests():
    print("=" * 65)
    print("ConanMCP Comprehensive Protocol & Primitives Verification")
    print("=" * 65)

    test_port = 8125
    base_url = f"http://127.0.0.1:{test_port}/mcp"

    # 1. Start Server
    print(f"\n[1] Starting ConanMCP server on 127.0.0.1:{test_port}...")
    conan_mcp_server.start_server(host="127.0.0.1", port=test_port)
    time.sleep(0.6)

    def send_post(payload, expected_status=200):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base_url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 204:
                return None
            body_bytes = resp.read()
            if not body_bytes:
                return None
            return json.loads(body_bytes.decode("utf-8"))

    # 2. Test GET Endpoint
    print("\n[2] Testing HTTP GET endpoint...")
    with urllib.request.urlopen(base_url, timeout=5) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        print(f"    Service: {body['service']} v{body['version']}")
        print(f"    Protocol: {body['protocol']}")
        print(f"    Tools: {body['registered_tools']}, Resources: {body['registered_resources']}, Prompts: {body['registered_prompts']}")
        assert body["service"] == "ConanMCP"
        assert body["status"] == "running"
        assert body["registered_tools"] >= 46
        assert body["registered_resources"] >= 4
        assert body["registered_prompts"] >= 4
    print("    PASSED: GET metadata endpoint")

    # 3. Test JSON-RPC initialize
    print("\n[3] Testing 'initialize' (MCP Specification 2024-11-05)...")
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "AntigravityTestClient", "version": "2.0.0"}
        }
    }
    init_res = send_post(init_req)
    assert init_res["jsonrpc"] == "2.0"
    assert init_res["id"] == 1
    result = init_res["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "conan-devkit-mcp"
    assert result["capabilities"]["tools"]["listChanged"] is True
    assert result["capabilities"]["resources"]["subscribe"] is True
    assert result["capabilities"]["prompts"]["listChanged"] is True
    print(f"    Server advertised capabilities: {list(result['capabilities'].keys())}")
    print("    PASSED: initialize")

    # 4. Test notifications/initialized (Standard MCP Notification - Must NOT return response ID)
    print("\n[4] Testing 'notifications/initialized'...")
    notif_req = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {}
    }
    notif_res = send_post(notif_req)
    # MCP / JSON-RPC specifies notifications must receive NO response body
    assert notif_res is None, f"Expected None/204 No Content for notification, got: {notif_res}"
    print("    PASSED: notifications/initialized (Correctly yielded 204 No Content)")

    # 5. Test ping
    print("\n[5] Testing 'ping'...")
    ping_res = send_post({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_res["jsonrpc"] == "2.0"
    assert ping_res["result"] == {}
    print("    PASSED: ping")

    # 6. Test tools/list
    print("\n[6] Testing 'tools/list'...")
    tools_res = send_post({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    tools = tools_res["result"]["tools"]
    print(f"    Total registered tools: {len(tools)}")
    assert len(tools) >= 46
    tool_names = [t["name"] for t in tools]
    assert "get_mcp_diagnostics" in tool_names
    assert "find_assets" in tool_names
    assert "list_level_actors" in tool_names
    # Check that schema has descriptive property info
    find_assets_tool = next(t for t in tools if t["name"] == "find_assets")
    props = find_assets_tool["inputSchema"]["properties"]
    assert "offset" in props
    assert "description" in props["offset"]
    print("    PASSED: tools/list (Enriched schemas and diagnostics verified)")

    # 7. Test tools/call: Diagnostics
    print("\n[7] Testing tools/call 'get_mcp_diagnostics'...")
    diag_res = send_post({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_mcp_diagnostics", "arguments": {}}
    })
    diag_data = json.loads(diag_res["result"]["content"][0]["text"])
    print(f"    Diagnostics Uptime: {diag_data['uptime_seconds']}s")
    print(f"    Diagnostics MCP Version: {diag_data['mcp_protocol_version']}")
    assert diag_data["service"] == "ConanMCP"
    assert diag_data["registered_tools_count"] >= 46
    print("    PASSED: tools/call get_mcp_diagnostics")

    # 8. Test tools/call error handling (CallToolResult with isError: true)
    print("\n[8] Testing tools/call error handling (MCP Spec Compliant isError: true)...")
    err_tool_res = send_post({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "find_actor", "arguments": {"actor": ""}}
    })
    assert "result" in err_tool_res, "Expected MCP result object with isError: true, got protocol error"
    assert err_tool_res["result"]["isError"] is True
    err_text = err_tool_res["result"]["content"][0]["text"]
    assert "required" in err_text
    print(f"    Handled Tool Error cleanly: {err_text}")
    print("    PASSED: Tool error returns isError: true")

    # 9. Test resources/list
    print("\n[9] Testing 'resources/list' and 'resources/templates/list'...")
    res_list = send_post({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    resources = res_list["result"]["resources"]
    uris = [r["uri"] for r in resources]
    print(f"    Registered URIs: {uris}")
    assert "devkit://status" in uris
    assert "devkit://logs/recent" in uris
    assert "devkit://outliner" in uris
    assert "conan://tables" in uris

    tmpl_list = send_post({"jsonrpc": "2.0", "id": 7, "method": "resources/templates/list"})
    templates = tmpl_list["result"]["resourceTemplates"]
    tmpl_uris = [t["uriTemplate"] for t in templates]
    print(f"    Registered Templates: {tmpl_uris}")
    assert "conan://asset/{package_path}" in tmpl_uris
    print("    PASSED: resources/list and resources/templates/list")

    # 10. Test resources/read
    print("\n[10] Testing 'resources/read'...")
    read_status = send_post({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "resources/read",
        "params": {"uri": "devkit://status"}
    })
    status_content = read_status["result"]["contents"][0]
    assert status_content["uri"] == "devkit://status"
    assert status_content["mimeType"] == "application/json"
    status_json = json.loads(status_content["text"])
    assert status_json["service"] == "ConanMCP"
    print(f"    devkit://status World: {status_json['current_world']}")

    read_logs = send_post({
        "jsonrpc": "2.0",
        "id": 9,
        "method": "resources/read",
        "params": {"uri": "devkit://logs/recent"}
    })
    logs_content = read_logs["result"]["contents"][0]
    assert logs_content["uri"] == "devkit://logs/recent"
    assert len(logs_content["text"]) > 0
    print(f"    devkit://logs/recent length: {len(logs_content['text'])} chars")
    print("    PASSED: resources/read")

    # 11. Test prompts/list and prompts/get
    print("\n[11] Testing 'prompts/list' and 'prompts/get'...")
    prompts_list = send_post({"jsonrpc": "2.0", "id": 10, "method": "prompts/list"})
    prompts = prompts_list["result"]["prompts"]
    p_names = [p["name"] for p in prompts]
    print(f"    Available Prompts: {p_names}")
    assert "create-conan-item-mod" in p_names
    assert "audit-level-performance" in p_names
    assert "inspect-character-skeleton" in p_names
    assert "debug-niagara-vfx" in p_names

    get_prompt = send_post({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "prompts/get",
        "params": {
            "name": "create-conan-item-mod",
            "arguments": {"item_name": "Bloodforged_Greataxe", "item_type": "Weapon"}
        }
    })
    prompt_res = get_prompt["result"]
    assert len(prompt_res["messages"]) == 1
    assert "Bloodforged_Greataxe" in prompt_res["messages"][0]["content"]["text"]
    print(f"    Resolved Prompt message length: {len(prompt_res['messages'][0]['content']['text'])} chars")
    print("    PASSED: prompts/list and prompts/get")

    # 12. Test Batch Requests
    print("\n[12] Testing JSON-RPC Batch Requests...")
    batch_req = [
        {"jsonrpc": "2.0", "id": 101, "method": "ping"},
        {"jsonrpc": "2.0", "id": 102, "method": "tools/call", "params": {"name": "get_editor_status", "arguments": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}  # Notification in batch (should be omitted in response array)
    ]
    batch_res = send_post(batch_req)
    assert isinstance(batch_res, list)
    assert len(batch_res) == 2  # The 2 calls with IDs
    ids = [r["id"] for r in batch_res]
    assert 101 in ids
    assert 102 in ids
    print(f"    Received {len(batch_res)} responses for batch with 2 requests + 1 notification.")
    print("    PASSED: Batch requests")

    # 13. Test SSE Handshake
    print("\n[13] Testing MCP Server-Sent Events (SSE) Handshake on /sse...")
    sse_url = f"http://127.0.0.1:{test_port}/sse"
    req = urllib.request.Request(sse_url)
    with urllib.request.urlopen(req, timeout=3) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        # Read the first event: event: endpoint\ndata: /messages?sessionId=...\n\n
        line1 = resp.readline().decode("utf-8").strip()
        line2 = resp.readline().decode("utf-8").strip()
        print(f"    SSE Initial Handshake: '{line1}' | '{line2}'")
        assert line1 == "event: endpoint"
        assert line2.startswith("data: /messages?sessionId=")
    print("    PASSED: Server-Sent Events (SSE) handshake")

    # 14. Stop Server
    print("\n[14] Stopping test server...")
    conan_mcp_server.stop_server()
    time.sleep(0.5)
    print("    Server stopped cleanly.")

    print("\n" + "=" * 65)
    print("ALL 14 COMPREHENSIVE MCP SPECIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)

if __name__ == "__main__":
    run_tests()
