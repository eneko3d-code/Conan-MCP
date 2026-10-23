"""Logging to the Unreal Output Log, the in-memory ring buffer and SSE clients."""

import time

from . import config, ue
from .sse import get_manager
from .state import STATE


def _append(level: str, msg: str):
    STATE.recent_logs.append(f"[{time.strftime('%H:%M:%S')}][{level.upper()}] {msg}")
    get_manager().broadcast_notification("notifications/message", {
        "level": level, "logger": "LogConanMCP", "data": msg
    })


def log_info(msg: str):
    _append("info", msg)
    if config.ENABLE_LOGGING:
        if ue.unreal:
            ue.unreal.log(f"LogConanMCP: {msg}")
        else:
            print(f"[ConanMCP] {msg}")


def log_warning(msg: str):
    _append("warning", msg)
    if ue.unreal:
        ue.unreal.log_warning(f"LogConanMCP: {msg}")
    else:
        print(f"[ConanMCP Warning] {msg}")


def log_error(msg: str):
    _append("error", msg)
    if ue.unreal:
        ue.unreal.log_error(f"LogConanMCP: {msg}")
    else:
        print(f"[ConanMCP Error] {msg}")
