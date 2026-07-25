"""Multi-tiered persistent memory for agents.

Working memory (in-memory): current task context, conversation, frustration state
Long-term memory (JSON file): past experiences, successes, failures
North Star: the original goal injected into every prompt
"""
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
from loguru import logger


class AgentMemory:
    """Persistent memory for an agent with keyword-based retrieval."""

    def __init__(self, agent_name: str, data_dir: str = "data"):
        self.agent_name = agent_name
        self.memory_dir = Path(data_dir) / "memory" / agent_name
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memories_file = self.memory_dir / "experiences.json"
        self.task_file = self.memory_dir / "tasks.json"

        self.working = {
            "current_task": None,
            "conversation": [],
            "frustration": 0,
            "attempts": {},
            "tried_approaches": {},
        }

        self.experiences = self._load_json(self.memories_file, [])
        self.task_queue = self._load_json(self.task_file, [])

    # ── Persistence ────────────────────────────────────────────────

    def _load_json(self, path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return default

    def _save_json(self, path: Path, data):
        path.write_text(json.dumps(data, indent=2, default=str))

    def save_all(self):
        self._save_json(self.memories_file, self.experiences)
        self._save_json(self.task_file, self.task_queue)

    # ── Long-term memory ───────────────────────────────────────────

    def store_experience(self, action: str, result: dict, tags: list[str] = None):
        self.experiences.append({
            "timestamp": datetime.now().isoformat(),
            "action": action or "",
            "success": result.get("success", False),
            "output": (result.get("output") or result.get("error") or "")[:1000],
            "tags": tags or [],
        })
        self._save_json(self.memories_file, self.experiences)

    def query_memory(self, query: str, limit: int = 5) -> list[dict]:
        """Find relevant past experiences by keyword matching."""
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for exp in self.experiences:
            score = 0
            action = exp.get("action") or ""
            output = exp.get("output") or ""
            text = (action + " " + output).lower()
            for word in query_words:
                if word in text:
                    score += 1
            for tag in exp.get("tags", []):
                if tag.lower() in query_lower:
                    score += 2
            if score > 0:
                scored.append((score, exp))

        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:limit]]

    # ── Task queue ─────────────────────────────────────────────────

    def add_task(self, task: dict):
        task.setdefault("created_at", datetime.now().isoformat())
        task.setdefault("status", "pending")
        task.setdefault("attempts", 0)
        self.task_queue.append(task)
        self._save_json(self.task_file, self.task_queue)

    def get_next_task(self) -> Optional[dict]:
        for t in self.task_queue:
            if t.get("status") == "pending":
                return t
        return None

    def update_task(self, task_id: str, updates: dict):
        for t in self.task_queue:
            if t.get("id") == task_id:
                t.update(updates)
                break
        self._save_json(self.task_file, self.task_queue)

    def pending_tasks(self) -> list[dict]:
        return [t for t in self.task_queue if t.get("status") == "pending"]

    def completed_tasks(self) -> list[dict]:
        return [t for t in self.task_queue if t.get("status") == "completed"]

    # ── Frustration / tenacity ─────────────────────────────────────

    def get_frustration(self) -> int:
        return self.working["frustration"]

    def increment_frustration(self, amount: int = 1):
        self.working["frustration"] += amount

    def reset_frustration(self):
        self.working["frustration"] = 0

    def record_attempt(self, task_id: str, approach: str):
        self.working["attempts"][task_id] = self.working["attempts"].get(task_id, 0) + 1
        approaches = self.working["tried_approaches"].setdefault(task_id, [])
        if approach not in approaches:
            approaches.append(approach)

    def attempts_for(self, task_id: str) -> int:
        return self.working["attempts"].get(task_id, 0)

    def tried_approaches_for(self, task_id: str) -> list[str]:
        return self.working["tried_approaches"].get(task_id, [])

    # ── Working memory ─────────────────────────────────────────────

    def add_to_conversation(self, role: str, content: str):
        self.working["conversation"].append({
            "role": role, "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self.working["conversation"]) > 50:
            self.working["conversation"] = self.working["conversation"][-50:]
