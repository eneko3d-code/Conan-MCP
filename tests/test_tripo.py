"""Tripo AI integration tests against a local fake of the Tripo v3 API (no real credits are spent)."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "Content", "Python"))
sys.path.insert(0, HERE)

import fake_unreal as fu  # noqa: E402
import conan_mcp_server  # noqa: E402,F401
from conan_mcp.core import config, ue  # noqa: E402
from conan_mcp.core.protocol import call_tool  # noqa: E402
from conan_mcp.core.state import STATE  # noqa: E402
import conan_mcp.integrations.tripo as tripo_mod  # noqa: E402
from conan_mcp.integrations.tripo import host_allowed  # noqa: E402

KEY = "tsk_secret_test_key_123"


class FakeTripo:
    """In-memory Tripo v3 behaviour."""

    def __init__(self):
        self.balance = 500.0
        self.cost = 30.0
        self.tasks = {}
        self.requests = []
        self.uploads = []
        self.fail_next_with_429 = 0
        self.port = None

    def handler(tripo):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, headers=None):
                raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self):
                if self.headers.get("Authorization") != f"Bearer {KEY}":
                    self._send(401, {"code": 1000, "message": "invalid key"})
                    return False
                return True

            def do_GET(self):
                tripo.requests.append(("GET", self.path, None))
                if self.path.startswith("/files/"):
                    return self._send(200, b"glTF-binary-model-bytes")
                if not self._auth():
                    return
                if self.path == "/v3/account/balance":
                    return self._send(200, {"code": 0, "data": {"balance": tripo.balance, "frozen": 0.0}})
                if self.path.startswith("/v3/tasks/"):
                    tid = self.path.rsplit("/", 1)[-1]
                    t = tripo.tasks.get(tid)
                    if t is None:
                        return self._send(404, {"code": 2002, "message": "no task"})
                    t["polls"] += 1
                    if t["polls"] >= 2 and t["status"] != "success":
                        t["status"] = "success"
                        tripo.balance -= tripo.cost
                    data = {"task_id": tid, "type": t["type"], "status": t["status"],
                            "progress": 100 if t["status"] == "success" else 40}
                    if t["status"] == "success":
                        data["credits_consumed"] = tripo.cost
                        data["output"] = {"model_url": f"http://127.0.0.1:{tripo.port}/files/{tid}.glb",
                                          "rendered_image_url": f"http://127.0.0.1:{tripo.port}/files/{tid}.webp"}
                    return self._send(200, {"code": 0, "data": data})
                self._send(404, {"code": 2002})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                ctype = self.headers.get("Content-Type", "")
                body = json.loads(raw) if ctype.startswith("application/json") else None
                tripo.requests.append(("POST", self.path, body))
                if not self._auth():
                    return
                if tripo.fail_next_with_429:
                    tripo.fail_next_with_429 -= 1
                    return self._send(429, {"code": 2000, "message": "busy"}, {"Retry-After": "0"})
                if self.path == "/v3/files":
                    assert ctype.startswith("multipart/form-data") and b'name="file"' in raw
                    tripo.uploads.append(len(raw))
                    return self._send(200, {"code": 0, "data": {"file_token": f"file_up{len(tripo.uploads)}"}})
                if tripo.balance < tripo.cost:
                    return self._send(403, {"code": 2010, "message": "insufficient credits"})
                tid = f"task_{len(tripo.tasks) + 1:04d}"
                ttype = {"/v3/generation/text-to-model": "text_to_model", "/v3/models/texture": "texture_model",
                         "/v3/generation/image-to-model": "image_to_model", "/v3/animations/rig": "animate_rig"}.get(self.path, "other")
                tripo.tasks[tid] = {"type": ttype, "status": "queued", "polls": 0, "body": body}
                self._send(200, {"code": 0, "data": {"task_id": tid}})
        return H


@pytest.fixture()
def tripo(monkeypatch, tmp_path):
    fake = FakeTripo()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    fake.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("TRIPO_API_KEY", KEY)
    monkeypatch.setattr(config, "TRIPO_BASE_URL", f"http://127.0.0.1:{fake.port}/v3")
    monkeypatch.setattr(config, "TRIPO_BUDGET", 0.0)
    monkeypatch.setattr(config, "TRIPO_MIN_BALANCE", 0.0)
    monkeypatch.setattr(config, "ENABLE_WRITE_TOOLS", True)
    monkeypatch.setattr(STATE, "tripo", {"spent": 0.0, "by_type": {}, "tasks": {}, "uploads": {}}, raising=False)
    fu.reset()
    monkeypatch.setattr(ue, "unreal", fu)
    monkeypatch.chdir(tmp_path)
    yield fake
    srv.shutdown()
    srv.server_close()


def call(_tool, **args):
    res = call_tool(_tool, args)
    text = res["content"][0]["text"]
    assert KEY not in text  # the key never leaks
    if res["isError"]:
        raise AssertionError(text)
    return json.loads(text)


def call_err(_tool, **args):
    res = call_tool(_tool, args)
    assert res["isError"], res
    assert KEY not in res["content"][0]["text"]
    return res["content"][0]["text"]


def test_balance(tripo):
    out = call("tripo_get_balance")
    assert out["balance"] == 500.0 and out["session_spent"] == 0


def test_no_key_explains(tripo, monkeypatch):
    monkeypatch.delenv("TRIPO_API_KEY")
    assert "TRIPO_API_KEY" in call_err("tripo_get_balance")


def test_plan_without_confirmation_spends_nothing(tripo):
    plan = call("tripo_text_to_model", prompt="barbarian war axe, iron and leather")
    assert plan["needs_confirmation"] and plan["balance"] == 500.0
    assert plan["parameters"]["auto_size"] is True
    assert not any(r[0] == "POST" for r in tripo.requests)


def test_full_generate_texture_import_flow(tripo):
    sub = call("tripo_text_to_model", prompt="barbarian war axe", face_limit=8000, confirm_spend=True, name="SM_WarAxe")
    tid = sub["task_id"]
    body = tripo.tasks[tid]["body"]
    assert body["prompt"] == "barbarian war axe" and body["face_limit"] == 8000
    first = call("tripo_get_task", task_id=tid)
    assert first["status"] == "queued" or first["status"] == "success"
    done = call("tripo_get_task", task_id=tid, wait_seconds=5)
    assert done["status"] == "success" and done["credits_consumed"] == 30.0
    assert done["session"]["session_spent"] == 30.0
    call("tripo_get_task", task_id=tid)  # credits are counted only once
    assert call("tripo_get_balance")["session_spent"] == 30.0

    # the next plan of the same task type shows the observed cost
    plan = call("tripo_text_to_model", prompt="another axe")
    assert plan["estimated_credits"] == 30.0
    assert call("tripo_texture_model", input=tid, texture_text="runes")["estimated_credits"] is None
    tex = call("tripo_texture_model", input=tid, texture_text="weathered iron", confirm_spend=True)
    assert tripo.tasks[tex["task_id"]]["body"]["texture_prompt"] == {"text": "weathered iron"}

    imp = call("tripo_import_result", task_id=tid, mod_name="MyMod")
    assert imp["imported"] == ["/Game/Mods/MyMod/Tripo/SM_WarAxe/SM_WarAxe.SM_WarAxe"]
    assert os.path.getsize(imp["downloaded"]) > 0


def test_insufficient_balance_blocks_before_sending(tripo):
    tripo.balance = 0.0
    err = call_err("tripo_text_to_model", prompt="rock", confirm_spend=True)
    assert "balance" in err.lower() and not any(r[0] == "POST" for r in tripo.requests)


def test_server_side_2010_is_not_retried(tripo):
    tripo.balance = 10.0  # below the task cost: the fake API answers 2010
    err = call_err("tripo_text_to_model", prompt="rock", confirm_spend=True)
    assert "Insufficient Tripo credits" in err
    assert sum(1 for r in tripo.requests if r[0] == "POST") == 1


def test_session_budget(tripo, monkeypatch):
    monkeypatch.setattr(config, "TRIPO_BUDGET", 40.0)
    tid = call("tripo_text_to_model", prompt="rock", confirm_spend=True)["task_id"]
    call("tripo_get_task", task_id=tid, wait_seconds=5)  # spent 30, observed cost 30 > remaining 10
    assert "budget" in call_err("tripo_text_to_model", prompt="another rock", confirm_spend=True).lower()


def test_rate_limit_retry(tripo):
    tripo.fail_next_with_429 = 2
    out = call("tripo_text_to_model", prompt="rock", confirm_spend=True)
    assert out["task_id"]


def test_local_image_upload_and_cache(tripo):
    folder = ue.saved_dir("captures")
    with open(os.path.join(folder, "ref.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    call("tripo_image_to_model", image="ref.png", confirm_spend=True)
    call("tripo_image_to_model", image="ref.png", confirm_spend=True)
    assert len(tripo.uploads) == 1  # cached file_token
    assert tripo.tasks["task_0001"]["body"]["input"] == "file_up1"
    assert "plain file names" in call_err("tripo_image_to_model", image="../../secret.png", confirm_spend=True)


def test_rig_uses_unreal_spec_and_imports_skeletal(tripo):
    rig = call("tripo_rig", input="task_abc", confirm_spend=True)
    body = tripo.tasks[rig["task_id"]]["body"]
    assert body["spec"] == "unreal" and body["out_format"] == "fbx"
    call("tripo_get_task", task_id=rig["task_id"], wait_seconds=5)
    imp = call("tripo_import_result", task_id=rig["task_id"], mod_name="MyMod", asset_name="SK_Golem")
    assert imp["skeletal"] is True


def test_imports_stay_in_mods(tripo):
    tid = call("tripo_text_to_model", prompt="rock", confirm_spend=True)["task_id"]
    call("tripo_get_task", task_id=tid, wait_seconds=5)
    assert "/Game/Mods" in call_err("tripo_import_result", task_id=tid, package_path="/Game/Characters")


def test_download_host_allowlist():
    assert host_allowed("https://cdn.tripo3d.ai/x.glb", ("tripo3d.ai", "tripo3d.com"))
    assert host_allowed("https://tripo-data.rg1.data.tripo3d.com/a.glb", ("tripo3d.ai", "tripo3d.com"))
    assert not host_allowed("https://evil.com/x.glb", ("tripo3d.ai",))
    assert not host_allowed("http://cdn.tripo3d.ai/x.glb", ("tripo3d.ai",))  # https only
    assert not host_allowed("https://tripo3d.ai.evil.com/x", ("tripo3d.ai",))
    c = tripo_mod.TripoClient("k", base_url="https://openapi.tripo3d.com/v3")
    with pytest.raises(Exception):
        c.download("https://evil.com/x.glb", "/tmp/never")


def test_error_mapping_scrubs_key(tripo):
    # look classes up at call time: other tests hot-reload the package
    c = sys.modules["conan_mcp.integrations.tripo"].TripoClient(KEY, base_url=f"http://127.0.0.1:{tripo.port}/v3", sleep=lambda s: None)
    tripo.balance = 0.0
    with pytest.raises(sys.modules["conan_mcp.integrations.tripo"].TripoInsufficientCredits) as e:
        c.create_task("/generation/text-to-model", {"prompt": "x"})
    assert KEY not in str(e.value)


def test_tripo_tools_are_off_game_thread_and_open_world():
    from conan_mcp.core.registry import registry
    t = registry.get_tool("tripo_text_to_model")
    assert t["off_game_thread"] and t["open_world"]
    assert next(x for x in registry.list_tools_schema() if x["name"] == "tripo_text_to_model")["annotations"]["openWorldHint"]
