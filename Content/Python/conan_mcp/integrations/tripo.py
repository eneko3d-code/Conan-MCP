"""Minimal Tripo AI v3 API client (https://developers.tripo3d.com), standard library only.

- Auth: ``Authorization: Bearer <TRIPO_API_KEY>``. The key is never logged nor echoed back.
- Every response is ``{"code": 0, "data": {...}}``; non-zero codes raise typed errors.
- 429/5xx are retried with exponential backoff (1, 2, 4 s; honours Retry-After). 2010
  (insufficient credits) and other 4xx are never retried.
- Downloads are restricted to Tripo hosts and to a destination chosen by the caller.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable, Optional, Sequence

DEFAULT_BASE_URL = "https://openapi.tripo3d.com/v3"
MAX_UPLOAD_BYTES = {"image": 20 * 1024 * 1024, "model": 150 * 1024 * 1024}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MODEL_EXT = {".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".fbx": "application/octet-stream",
             ".obj": "text/plain", ".stl": "model/stl"}
TERMINAL_STATUSES = {"success", "failed", "cancelled", "banned", "expired"}


class TripoError(RuntimeError):
    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code, self.http_status = code, http_status


class TripoAuthError(TripoError):
    pass


class TripoInsufficientCredits(TripoError):
    pass


class TripoRateLimited(TripoError):
    pass


class TripoInvalidParams(TripoError):
    pass


class TripoContentPolicy(TripoError):
    pass


_CODE_MAP = {
    1000: (TripoAuthError, "Invalid Tripo API key"),
    1001: (TripoAuthError, "Missing/unauthorized Tripo API key"),
    1004: (TripoInvalidParams, "Invalid parameter combination"),
    1007: (TripoRateLimited, "Tripo rate limit exceeded"),
    2000: (TripoRateLimited, "Tripo concurrency limit exceeded (wait for a running task to finish)"),
    2002: (TripoInvalidParams, "Unsupported request parameter"),
    2003: (TripoInvalidParams, "Empty input file"),
    2004: (TripoInvalidParams, "Unsupported file type"),
    2008: (TripoContentPolicy, "Content policy violation: change the prompt or image"),
    2010: (TripoInsufficientCredits, "Insufficient Tripo credits: top up in the Tripo console"),
    2015: (TripoInvalidParams, "API/model version deprecated"),
    2018: (TripoInvalidParams, "Model too complex: reduce polycount"),
}


def _raise_for(code, message, http_status=None):
    cls, default = _CODE_MAP.get(code, (TripoError, "Tripo API error"))
    raise cls(f"{default} (code {code}){': ' + message if message and message != default else ''}", code, http_status)


def host_allowed(url: str, allowed_suffixes: Sequence[str], extra_hosts: Sequence[str] = ()) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {h.lower() for h in extra_hosts}:
        return True
    if parsed.scheme != "https":
        return False
    return any(host == s or host.endswith("." + s) for s in allowed_suffixes)


class TripoClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 60.0, max_retries: int = 3,
                 sleep: Callable[[float], None] = time.sleep, download_hosts: Sequence[str] = ("tripo3d.ai", "tripo3d.com")):
        if not api_key:
            raise TripoAuthError("TRIPO_API_KEY is not set. Create a key at https://developers.tripo3d.com/en/keys "
                                 "and set it as an environment variable before starting the DevKit.")
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep
        self.download_hosts = tuple(download_hosts)
        base_host = urllib.parse.urlparse(self.base_url).hostname or ""
        # The API host itself may serve files; plain-http hosts are only allowed when the API is local (tests)
        self._extra_hosts = (base_host,) if base_host in ("127.0.0.1", "localhost") else ()

    # -- low level ----------------------------------------------------------

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text

    def _request(self, method: str, path: str, body: Optional[dict] = None, data: Optional[bytes] = None,
                 content_type: Optional[str] = None) -> dict:
        url = self.base_url + path
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            payload = data
            headers["Content-Type"] = content_type or "application/octet-stream"
        attempt = 0
        while True:
            req = urllib.request.Request(url, data=payload, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    parsed = json.loads(resp.read().decode("utf-8") or "{}")
                break
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = {"code": None, "message": raw[:300]}
                code = parsed.get("code")
                retryable = e.code == 429 or e.code >= 500
                if retryable and attempt < self.max_retries and code != 2010:
                    wait = 2 ** attempt
                    ra = e.headers.get("Retry-After") if e.headers else None
                    if ra:
                        try:
                            wait = max(wait, float(ra))
                        except ValueError:
                            pass
                    self.sleep(min(wait, 30.0))
                    attempt += 1
                    continue
                if code:
                    _raise_for(code, self._scrub(str(parsed.get("message", ""))), e.code)
                if e.code in (401,):
                    raise TripoAuthError("Tripo rejected the API key (HTTP 401)", None, e.code)
                raise TripoError(f"Tripo HTTP {e.code}: {self._scrub(str(parsed.get('message', raw))[:300])}", None, e.code)
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    self.sleep(min(2 ** attempt, 30.0))
                    attempt += 1
                    continue
                raise TripoError(f"Cannot reach Tripo API: {self._scrub(str(e.reason))}")
        code = parsed.get("code", 0)
        if code not in (0, None):
            _raise_for(code, self._scrub(str(parsed.get("message", ""))))
        return parsed.get("data", parsed)

    # -- account ------------------------------------------------------------

    def get_balance(self) -> dict:
        data = self._request("GET", "/account/balance")
        return {"balance": float(data.get("balance", 0) or 0), "frozen": float(data.get("frozen", 0) or 0)}

    def get_usage(self) -> list:
        data = self._request("GET", "/account/usage")
        return data if isinstance(data, list) else data.get("items", data.get("list", []))

    # -- tasks --------------------------------------------------------------

    def create_task(self, endpoint: str, payload: dict) -> str:
        data = self._request("POST", endpoint, body=payload)
        task_id = data.get("task_id")
        if not task_id:
            raise TripoError(f"Tripo did not return a task_id for {endpoint}")
        return task_id

    def get_task(self, task_id: str) -> dict:
        return self._request("GET", f"/tasks/{urllib.parse.quote(task_id)}")

    def wait_task(self, task_id: str, max_seconds: float, interval: float = 2.0) -> dict:
        deadline = time.time() + max_seconds
        while True:
            task = self.get_task(task_id)
            if task.get("status") in TERMINAL_STATUSES or time.time() >= deadline:
                return task
            self.sleep(interval)

    # -- files --------------------------------------------------------------

    def upload(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        kind = "image" if ext in IMAGE_EXT else "model" if ext in MODEL_EXT else None
        if kind is None:
            raise TripoInvalidParams(f"Unsupported upload type '{ext}' (images: png/jpg/webp, models: glb/gltf/fbx/obj/stl)")
        size = os.path.getsize(path)
        if size == 0:
            raise TripoInvalidParams("File is empty")
        if size > MAX_UPLOAD_BYTES[kind]:
            raise TripoInvalidParams(f"File is {size // (1024 * 1024)} MB; Tripo accepts up to {MAX_UPLOAD_BYTES[kind] // (1024 * 1024)} MB for {kind}s")
        boundary = "----ConanMCP" + uuid.uuid4().hex
        with open(path, "rb") as f:
            content = f.read()
        mime = IMAGE_EXT.get(ext) or MODEL_EXT.get(ext)
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(path)}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        data = self._request("POST", "/files", data=body, content_type=f"multipart/form-data; boundary={boundary}")
        token = data.get("file_token") or data.get("image_token")
        if not token:
            raise TripoError("Tripo did not return a file_token")
        return token

    def download(self, url: str, dest_path: str, max_bytes: int = 500 * 1024 * 1024) -> int:
        if not host_allowed(url, self.download_hosts, self._extra_hosts):
            host = urllib.parse.urlparse(url).hostname
            raise TripoError(f"Refusing to download from '{host}': not a Tripo host. If Tripo serves files from a new "
                             "CDN, add it to CONAN_MCP_TRIPO_DOWNLOAD_HOSTS.")
        req = urllib.request.Request(url, headers={"User-Agent": "ConanMCP"})  # signed URLs: no auth header
        written = 0
        tmp = dest_path + ".part"
        with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    os.remove(tmp)
                    raise TripoError("Download exceeds the size limit")
                out.write(chunk)
        os.replace(tmp, dest_path)
        return written
