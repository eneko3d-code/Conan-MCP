"""Rich tool results and deferred (multi-frame) work."""

import base64
import json
import time
from typing import Callable, List, Optional, Tuple


class ToolResult:
    """A tool result carrying JSON data plus optional images (MCP image content)."""

    def __init__(self, data=None, images: Optional[List[Tuple[bytes, str]]] = None):
        self.data = data if data is not None else {}
        self.images = images or []

    def to_content(self) -> list:
        text = self.data if isinstance(self.data, str) else json.dumps(self.data, indent=2)
        content = [{"type": "text", "text": text}]
        for raw, mime in self.images:
            content.append({"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mimeType": mime})
        return content


class Deferred:
    """Work that completes on a later frame (e.g. screenshots written on the next tick).

    ``poll()`` is called on the Game Thread once per tick and must return
    ``(done, value)``. When done, ``value`` becomes the tool result.
    """

    def __init__(self, poll: Callable[[], Tuple[bool, object]], timeout: float = 20.0, description: str = ""):
        self.poll = poll
        self.deadline = time.time() + timeout
        self.description = description

    def expired(self) -> bool:
        return time.time() > self.deadline


def wait_for_file(path: str, build_result: Callable[[str], object], timeout: float = 20.0, min_size: int = 1) -> Deferred:
    """Deferred that completes once ``path`` exists with a stable, non-zero size."""
    import os
    last = {"size": -1}

    def poll():
        if not os.path.exists(path):
            return False, None
        size = os.path.getsize(path)
        if size < min_size or size != last["size"]:
            last["size"] = size
            return False, None
        return True, build_result(path)

    return Deferred(poll, timeout=timeout, description=f"waiting for {os.path.basename(path)}")
