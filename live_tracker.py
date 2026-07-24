"""In-memory live tracking for agent input/output streaming.
Shared between agent system and dashboard to avoid DB latency.
"""

import threading
import time
from typing import Optional

_live_data = {}
_lock = threading.Lock()


def update(agent_name: str, input_text: str = None, output_text: str = None):
    with _lock:
        if agent_name not in _live_data:
            _live_data[agent_name] = {"input": "", "output": "", "updated": 0}
        if input_text is not None:
            _live_data[agent_name]["input"] = input_text
        if output_text is not None:
            _live_data[agent_name]["output"] = output_text
        _live_data[agent_name]["updated"] = time.time()


def get(agent_name: str) -> dict:
    with _lock:
        return _live_data.get(agent_name, {"input": "", "output": "", "updated": 0})


def get_all() -> dict:
    with _lock:
        return dict(_live_data)


def clear():
    with _lock:
        _live_data.clear()
