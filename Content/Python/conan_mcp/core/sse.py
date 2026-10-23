"""Server-Sent Events session manager (MCP SSE transport, spec 2024-11-05)."""

import json
import queue
import threading
import uuid
from typing import Dict

from .state import STATE


class SSESessionManager:
    def __init__(self):
        self.sessions: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self.lock:
            self.sessions[session_id] = queue.Queue(maxsize=100)
        return session_id

    def get_queue(self, session_id: str):
        with self.lock:
            return self.sessions.get(session_id)

    def remove_session(self, session_id: str):
        with self.lock:
            self.sessions.pop(session_id, None)

    def has_session(self, session_id: str) -> bool:
        with self.lock:
            return session_id in self.sessions

    def broadcast_notification(self, method: str, params: dict):
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        with self.lock:
            for q in list(self.sessions.values()):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def send_to_session(self, session_id: str, message: str):
        with self.lock:
            q = self.sessions.get(session_id)
            if q is not None:
                try:
                    q.put_nowait(message)
                except queue.Full:
                    pass


def get_manager() -> SSESessionManager:
    if STATE.sse_manager is None:
        STATE.sse_manager = SSESessionManager()
    return STATE.sse_manager
