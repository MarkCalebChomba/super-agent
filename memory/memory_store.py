import sqlite3
import json
import os
import threading
from pathlib import Path
from typing import Optional, Any
from datetime import datetime
from loguru import logger

class MemoryStore:
    """SQLite-backed persistent memory store with FTS5 full-text search.
    One store per agent. Follows Hermes agent memory architecture.
    """

    def __init__(self, agent_name: str, db_dir: str = "data/memory"):
        self.agent_name = agent_name
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"{agent_name}_memory.db"
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self):
        """Thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        conn = self._conn
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS core_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL DEFAULT 'self',
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS session_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                content, summary, session_id,
                content='session_history', content_rowid='id'
            );

            CREATE TABLE IF NOT EXISTS consolidated_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary_type TEXT NOT NULL,
                content TEXT NOT NULL,
                date_range_start TIMESTAMP,
                date_range_end TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                procedure TEXT,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TRIGGER IF NOT EXISTS core_memory_updated
                AFTER UPDATE ON core_memory
            BEGIN
                UPDATE core_memory SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END;
        """)
        conn.commit()

    # === CORE MEMORY (always in prompt, < 2000 tokens) ===

    def get_core_memory(self, target: str = "self") -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, target, content, category, importance, updated_at "
            "FROM core_memory WHERE target = ? ORDER BY importance DESC, updated_at DESC",
            (target,)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_all_core(self) -> dict[str, list[dict]]:
        all_mem = {}
        for target in ("self", "user", "task", "environment", "strategy"):
            entries = self.get_core_memory(target)
            if entries:
                all_mem[target] = entries
        return all_mem

    def add_core(self, target: str, content: str, category: str = "general", importance: int = 1):
        self._conn.execute(
            "INSERT INTO core_memory (target, content, category, importance) VALUES (?, ?, ?, ?)",
            (target, content, category, importance)
        )
        self._conn.commit()

    def replace_core(self, old_text: str, new_text: str, target: str = "self"):
        cur = self._conn.execute(
            "SELECT id FROM core_memory WHERE target = ? AND content LIKE ? LIMIT 1",
            (target, f"%{old_text}%")
        )
        row = cur.fetchone()
        if row:
            self._conn.execute("UPDATE core_memory SET content = ? WHERE id = ?", (new_text, row["id"]))
            self._conn.commit()
            return True
        return False

    def remove_core(self, content_containing: str, target: str = "self"):
        self._conn.execute(
            "DELETE FROM core_memory WHERE target = ? AND content LIKE ?",
            (target, f"%{content_containing}%")
        )
        self._conn.commit()

    def core_memory_token_estimate(self) -> int:
        """Rough estimate of core memory token count."""
        cur = self._conn.execute("SELECT content FROM core_memory")
        total = sum(len(r["content"]) // 4 for r in cur.fetchall())
        return total

    def trim_core_to_limit(self, max_tokens: int = 1800):
        """If core memory exceeds limit, remove lowest importance entries."""
        current = self.core_memory_token_estimate()
        if current <= max_tokens:
            return
        cur = self._conn.execute(
            "SELECT id, content, importance FROM core_memory ORDER BY importance ASC, updated_at ASC"
        )
        for row in cur.fetchall():
            if self.core_memory_token_estimate() <= max_tokens:
                break
            tokens = len(row["content"]) // 4
            self._conn.execute("DELETE FROM core_memory WHERE id = ?", (row["id"],))
            logger.info(f"Trimmed core memory [{self.agent_name}]: removed entry ({tokens} tokens)")

    # === SESSION HISTORY ===

    def log_session(self, session_id: str, role: str, content: str, summary: str = None):
        self._conn.execute(
            "INSERT INTO session_history (session_id, role, content, summary) VALUES (?, ?, ?, ?)",
            (session_id, role, content, summary)
        )
        self._conn.execute(
            "INSERT INTO session_fts (content, summary, session_id) VALUES (?, ?, ?)",
            (content, summary or "", session_id)
        )
        self._conn.commit()

    def search_sessions(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across all session history (Hermes session_search equivalent)."""
        try:
            cur = self._conn.execute(
                """SELECT DISTINCT s.id, s.session_id, s.role, s.content, s.summary, s.timestamp
                   FROM session_fts f JOIN session_history s ON f.rowid = s.id
                   WHERE session_fts MATCH ? ORDER BY s.timestamp DESC LIMIT ?""",
                (query, limit)
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"FTS search failed [{self.agent_name}]: {e}")
            return []

    def search_with_summary(self, query: str, llm_summarizer: callable, limit: int = 10) -> str:
        """Search sessions and summarize results using LLM. Hermes-style."""
        sessions = self.search_sessions(query, limit)
        if not sessions:
            return ""
        context = "\n\n".join(
            f"[{s['session_id']}] {s['role']}: {s['content'][:300]}"
            for s in sessions
        )
        return llm_summarizer(
            f"These are past session records related to the query '{query}'. "
            f"Summarize what was discussed and any relevant outcomes:\n\n{context}"
        )

    # === SKILLS (Hermes-style procedural memory) ===

    def add_skill(self, name: str, description: str, procedure: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO skills (name, description, procedure) VALUES (?, ?, ?)",
            (name, description, procedure)
        )
        self._conn.commit()

    def record_skill_outcome(self, name: str, success: bool):
        col = "success_count" if success else "fail_count"
        self._conn.execute(f"UPDATE skills SET {col} = {col} + 1, updated_at = CURRENT_TIMESTAMP WHERE name = ?", (name,))
        self._conn.commit()

    def get_skills(self, min_success_rate: float = 0.0) -> list[dict]:
        cur = self._conn.execute(
            """SELECT * FROM (
                SELECT name, description, procedure, success_count, fail_count,
                       CASE WHEN (success_count + fail_count) > 0
                            THEN CAST(success_count AS FLOAT) / (success_count + fail_count)
                            ELSE 0 END as success_rate
                FROM skills
            ) WHERE success_rate >= ?
            ORDER BY success_count DESC""",
            (min_success_rate,)
        )
        return [dict(r) for r in cur.fetchall()]

    # === CONSOLIDATED SUMMARIES ===

    def save_summary(self, summary_type: str, content: str, start: str = None, end: str = None):
        self._conn.execute(
            "INSERT INTO consolidated_summary (summary_type, content, date_range_start, date_range_end) VALUES (?, ?, ?, ?)",
            (summary_type, content, start, end)
        )
        self._conn.commit()

    def get_latest_summary(self, summary_type: str) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT * FROM consolidated_summary WHERE summary_type = ? ORDER BY created_at DESC LIMIT 1",
            (summary_type,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
