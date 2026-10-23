"""Process-wide runtime state that must survive a hot reload.

This module is deliberately never passed to importlib.reload(): counters, SSE
sessions, the Game Thread queue and the ticker handle live here so a reload of
any other module keeps clients connected and work flowing.
"""

import collections
import queue
import threading
import time


class _State:
    def __init__(self):
        self.server_start_time = time.time()
        self.request_counter = 0
        self.error_counter = 0
        self.counter_lock = threading.Lock()
        self.recent_logs = collections.deque(maxlen=500)
        self.game_thread_queue = queue.Queue()
        self.pending_deferred = []          # Deferred tasks polled every tick
        self.ticker_handle = None
        self.ticker_lock = threading.Lock()
        self.game_thread_ident = None       # thread id of the Game Thread, once seen
        self.sse_manager = None             # created lazily by core.sse
        self.server_instance = None
        self.server_running = True
        self.resource_subscriptions = set()

    def count_request(self):
        with self.counter_lock:
            self.request_counter += 1

    def count_error(self):
        with self.counter_lock:
            self.error_counter += 1


STATE = globals().get("STATE") or _State()
