"""Structured event log — append-only JSON-lines per agent.
Every phase writes to it. Tail the file instead of reading source code.
"""
import json
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional


class EventLog:
    """Per-agent append-only event log. Thread-safe, JSON-lines format."""

    def __init__(self, agent_name: str, log_dir: str = "data/event_logs"):
        self.agent_name = agent_name
        self._lock = threading.Lock()
        self._path = Path(log_dir) / agent_name / f"{datetime.now().strftime('%Y%m%d')}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, phase: str, ok: bool = True, **fields) -> str:
        """Append one structured event. Returns the event_id."""
        event = {
            "event_id": str(uuid.uuid4()),
            "ts": time.time(),
            "ts_human": datetime.utcnow().isoformat() + "Z",
            "agent": self.agent_name,
            "phase": phase,
            "ok": ok,
            **fields,
        }
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        return event["event_id"]

    def read(self, limit: int = 100) -> list[dict]:
        """Read recent events (newest first)."""
        if not self._path.exists():
            return []
        with self._lock:
            lines = self._path.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(l) for l in lines if l.strip()]
        return events[-limit:][::-1]

    def read_by_phase(self, phase: str, limit: int = 50) -> list[dict]:
        return [e for e in self.read(limit * 5) if e.get("phase") == phase][:limit]

    def stats(self) -> dict:
        """Quick aggregate: count by phase, ok/fail per phase."""
        events = self.read(5000)
        counts = {}
        for e in events:
            p = e.get("phase", "?")
            ok = e.get("ok", True)
            counts.setdefault(p, {"ok": 0, "fail": 0})
            counts[p]["ok" if ok else "fail"] += 1
        return {"total": len(events), "by_phase": counts}
