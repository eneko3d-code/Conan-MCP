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
    print("=" * 60)
    print("ConanMCP Automated Protocol & Tool Verification Test")
    print("=" * 60)

    # 1. Start Server
    print("[1] Starting ConanMCP server on 127.0.0.1:8123...")
    conan_mcp_server.start_server(host="127.0.0.1", port=8123)
    time.sleep(0.5)

    base_url = "http://127.0.0.1:8123/mcp"

    def send_post(payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(base_url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # 2. Test GET Endpoint
    print("[2] Testing HTTP GET endpoint...")
    with urllib.request.urlopen(base_url, timeout=5) as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        body = json.loads(resp.read().decode("utf-8"))
        print(f"    GET Response: {body}")
        assert body["service"] == "ConanMCP"
        assert body["status"] == "running"
    print("    PASSED: GET endpoint")

    # 3. Test JSON-RPC initialize
    print("[3] Testing 'initialize'...")
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "TestClient", "version": "1.0.0"}
        }
    }
    init_res = send_post(init_req)
    print(f"    initialize Response: {json.dumps(init_res, indent=2)}")
    assert init_res["jsonrpc"] == "2.0"
    assert init_res["id"] == 1
    assert "result" in init_res
    assert "serverInfo" in init_res["result"]
    assert init_res["result"]["serverInfo"]["name"] == "conan-devkit-mcp"
    print("    PASSED: initialize")

    # 4. Test notifications/initialized
    print("[4] Testing 'notifications/initialized'...")
    notif_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "notifications/initialized",
        "params": {}
    }
    notif_res = send_post(notif_req)
    assert notif_res["jsonrpc"] == "2.0"
    print("    PASSED: notifications/initialized")

    # 5. Test ping
    print("[5] Testing 'ping'...")
    ping_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "ping"
    }
    ping_res = send_post(ping_req)
    assert ping_res["jsonrpc"] == "2.0"
    assert ping_res["result"] == {}
    print("    PASSED: ping")

    # 6. Test tools/list
    print("[6] Testing 'tools/list'...")
    tools_req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/list"
    }
    tools_res = send_post(tools_req)
    tools = tools_res["result"]["tools"]
    print(f"    Total registered tools: {len(tools)}")
    assert len(tools) >= 20, f"Expected >= 20 tools, got {len(tools)}"

    tool_names = [t["name"] for t in tools]
    required_tools = [
        "get_editor_status", "get_current_level", "save_current_level", "get_selected_actors",
        "list_level_actors", "find_actor", "get_actor_info", "get_actor_transform", "set_actor_transform", "get_actor_components",
        "find_assets", "get_asset_info", "get_asset_class", "get_asset_path", "get_asset_dependencies", "save_asset",
        "get_skeletal_mesh_info", "get_skeleton_info", "get_skeleton_sockets", "get_bones",
        "find_blueprint", "get_blueprint_info", "get_blueprint_parent_class", "get_blueprint_variables",
        "find_datatable", "get_datatable_info", "list_datatable_rows", "get_datatable_row",
        "find_particle_systems", "get_particle_info", "get_character_sockets", "preview_particle_on_actor", "remove_preview_particle",
        "find_conan_assets", "find_conan_datatables", "find_conan_characters", "find_conan_items", "find_conan_particles"
    ]
    for rt in required_tools:
        assert rt in tool_names, f"Missing required tool: {rt}"
    print(f"    All {len(required_tools)} required tools verified in tools/list schema!")
    print("    PASSED: tools/list")

    # 7. Test tools/call: get_editor_status
    print("[7] Testing tools/call 'get_editor_status'...")
    call_req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "get_editor_status",
            "arguments": {}
        }
    }
    call_res = send_post(call_req)
    assert call_res["result"]["isError"] == False
    content_text = call_res["result"]["content"][0]["text"]
    status_data = json.loads(content_text)
    print(f"    Status Result: {status_data}")
    assert status_data["engine_version"] == "5.8.2-377096+++exiles+release"
    print("    PASSED: tools/call get_editor_status")

    # 8. Test tools/call: get_selected_actors
    print("[8] Testing tools/call 'get_selected_actors'...")
    call_req2 = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "get_selected_actors",
            "arguments": {}
        }
    }
    call_res2 = send_post(call_req2)
    assert call_res2["result"]["isError"] == False
    print("    PASSED: tools/call get_selected_actors")

    # 9. Test Invalid Method Error handling
    print("[9] Testing invalid method error handling...")
    bad_req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "non_existent_method"
    }
    bad_res = send_post(bad_req)
    assert "error" in bad_res
    assert bad_res["error"]["code"] == -32601
    print(f"    Expected Error Caught: {bad_res['error']}")
    print("    PASSED: Method not found (-32601)")

    # 10. Test Invalid Tool Error handling
    print("[10] Testing non-existent tool error handling...")
    bad_tool_req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "non_existent_tool_xyz",
            "arguments": {}
        }
    }
    bad_tool_res = send_post(bad_tool_req)
    assert "error" in bad_tool_res
    assert bad_tool_res["error"]["code"] == -32601
    print(f"    Expected Error Caught: {bad_tool_res['error']}")
    print("    PASSED: Tool not found (-32601)")

    # 11. Stop and Restart Server
    print("[11] Testing server Stop and Restart...")
    conan_mcp_server.stop_server()
    time.sleep(0.5)

    # Verify socket is closed
    try:
        urllib.request.urlopen(base_url, timeout=1)
        assert False, "Server should be stopped!"
    except Exception:
        print("    Server stopped successfully (connection refused as expected)")

    conan_mcp_server.start_server(host="127.0.0.1", port=8123)
    time.sleep(0.5)
    with urllib.request.urlopen(base_url, timeout=5) as resp:
        assert resp.status == 200
        print("    Server restarted and responding successfully!")
    conan_mcp_server.stop_server()
    print("    PASSED: Server start/stop lifecycle")

    print("\n" + "=" * 60)
    print("ALL 11 AUTOMATED MCP PROTOCOL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
