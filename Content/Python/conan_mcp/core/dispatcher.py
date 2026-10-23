"""Game Thread dispatcher.

Unreal Python requires UObject / editor calls on the Game Thread. HTTP worker
threads queue work here; an engine ticker drains the queue every frame. A task
may return a ``Deferred`` that is polled on following frames.
"""

import queue
import threading
import time

from . import config, ue
from .results import Deferred
from .state import STATE


def _finish(holder, event, value=None, error=None):
    holder["result"] = value
    holder["error"] = error
    event.set()


def _game_thread_ticker(delta_time: float) -> bool:
    """Processes queued tasks and pending deferred work on the Game Thread."""
    STATE.game_thread_ident = threading.get_ident()
    q = STATE.game_thread_queue
    while True:
        try:
            fn, args, kwargs, holder, event = q.get_nowait()
        except queue.Empty:
            break
        if holder.get("cancelled"):
            event.set()  # caller already timed out; never run stale work
            continue
        try:
            value = fn(*args, **kwargs)
            if isinstance(value, Deferred):
                STATE.pending_deferred.append((value, holder, event))
            else:
                _finish(holder, event, value)
        except Exception as e:
            _finish(holder, event, error=e)

    still_pending = []
    for deferred, holder, event in STATE.pending_deferred:
        if holder.get("cancelled"):
            event.set()
            continue
        try:
            done, value = deferred.poll()
        except Exception as e:
            _finish(holder, event, error=e)
            continue
        if done:
            _finish(holder, event, value)
        elif deferred.expired():
            _finish(holder, event, error=TimeoutError(f"Deferred work timed out ({deferred.description})"))
        else:
            still_pending.append((deferred, holder, event))
    STATE.pending_deferred = still_pending
    return True


def ensure_ticker_registered():
    """Registers the ticker callback with Unreal Engine (no-op outside the editor)."""
    u = ue.unreal
    if not u or not hasattr(u, "register_ticker_callback"):
        return
    with STATE.ticker_lock:
        if STATE.ticker_handle is None:
            try:
                STATE.ticker_handle = u.register_ticker_callback(_game_thread_ticker)
            except Exception as e:
                from .log import log_error
                log_error(f"Failed to register Game Thread ticker callback: {e}")


def unregister_ticker():
    u = ue.unreal
    with STATE.ticker_lock:
        if u and STATE.ticker_handle is not None:
            try:
                u.unregister_ticker_callback(STATE.ticker_handle)
            finally:
                STATE.ticker_handle = None


def _run_inline(fn, args, kwargs):
    """Used outside the editor (tests) or when already on the Game Thread."""
    value = fn(*args, **kwargs)
    if isinstance(value, Deferred):
        while True:
            done, result = value.poll()
            if done:
                return result
            if value.expired():
                raise TimeoutError(f"Deferred work timed out ({value.description})")
            time.sleep(0.02)
    return value


def execute_on_game_thread(fn, *args, **kwargs):
    """Runs ``fn`` on the Game Thread and waits up to TOOL_TIMEOUT_SECONDS for the result."""
    if STATE.ticker_handle is None:
        ensure_ticker_registered()
    if STATE.ticker_handle is None or threading.get_ident() == STATE.game_thread_ident:
        return _run_inline(fn, args, kwargs)

    event = threading.Event()
    holder = {"result": None, "error": None, "cancelled": False}
    STATE.game_thread_queue.put((fn, args, kwargs, holder, event))

    timeout = config.TOOL_TIMEOUT_SECONDS
    if not event.wait(timeout=timeout):
        holder["cancelled"] = True
        name = getattr(fn, "__name__", str(fn))
        raise TimeoutError(f"Execution timed out after {timeout:.0f}s on Game Thread for '{name}'")
    if holder["error"] is not None:
        raise holder["error"]
    return holder["result"]
