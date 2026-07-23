import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger

class CentralLog:
    """Central log database. Master agent reads this to monitor all agents.
    
    Every agent pushes logs here. Master queries this to:
    - Monitor agent health
    - Detect patterns across agents
    - Find CTA-worthy events (then passes through SupervisorFilter)
    - Generate P&L reports
    
    Not every log is a CTA — most are just informational.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_dir: str = "data/logs"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_dir: str = "data/logs"):
        if self._initialized:
            return
        self._initialized = True
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "central_log.db"
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS central_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                message TEXT NOT NULL,
                data JSON,
                session_id TEXT,
                reviewed BOOLEAN DEFAULT 0,
                reviewed_by TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_central_agent ON central_log(agent_name);
            CREATE INDEX IF NOT EXISTS idx_central_level ON central_log(level);
            CREATE INDEX IF NOT EXISTS idx_central_cta ON central_log(level) WHERE level >= 50;
            CREATE INDEX IF NOT EXISTS idx_central_category ON central_log(category);
            CREATE INDEX IF NOT EXISTS idx_central_timestamp ON central_log(timestamp);
        """)
        self._conn.commit()

    def receive(self, agent_name: str, level: int, message: str, category: str = "general",
                data: dict = None, session_id: str = None):
        data_json = json.dumps(data) if data else None
        self._conn.execute(
            "INSERT INTO central_log (agent_name, level, category, message, data, session_id) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_name, level, category, message, data_json, session_id)
        )
        self._conn.commit()

    # === Master query methods ===

    def get_unreviewed_ctas(self) -> list[dict]:
        """Get CTA-level logs not yet reviewed by master/human."""
        cur = self._conn.execute(
            "SELECT * FROM central_log WHERE level >= 50 AND reviewed = 0 ORDER BY timestamp DESC LIMIT 50"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_recent_by_agent(self, agent_name: str, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM central_log WHERE agent_name = ? ORDER BY timestamp DESC LIMIT ?",
            (agent_name, limit)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_recent_global(self, limit: int = 100, min_level: int = 0) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM central_log WHERE level >= ? ORDER BY timestamp DESC LIMIT ?",
            (min_level, limit)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_errors(self, hours: int = 24) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM central_log WHERE level >= 40 AND timestamp >= datetime('now', ?)",
            (f'-{hours} hours',)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_action_summary(self, hours: int = 24) -> list[dict]:
        """Get all ACTION-level logs (concrete actions taken across all agents)."""
        cur = self._conn.execute(
            """SELECT agent_name, category, COUNT(*) as count, GROUP_CONCAT(message, ' | ') as examples
               FROM central_log
               WHERE level = 25 AND timestamp >= datetime('now', ?)
               GROUP BY agent_name, category
               ORDER BY count DESC""",
            (f'-{hours}',)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_revenue_summary(self, hours: int = 168) -> list[dict]:
        """Get revenue events across all agents."""
        cur = self._conn.execute(
            """SELECT agent_name, COUNT(*) as events, GROUP_CONCAT(message, ' || ') as details
               FROM central_log
               WHERE level = 45 AND timestamp >= datetime('now', ?)
               GROUP BY agent_name
               ORDER BY events DESC""",
            (f'-{hours}',)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_logs_for_supervisor(self, limit: int = 30) -> list[dict]:
        """Get logs that the SupervisorFilter should evaluate for human notification."""
        cur = self._conn.execute(
            """SELECT * FROM central_log
               WHERE (level >= 40 OR level = 50)
               AND reviewed = 0
               ORDER BY level DESC, timestamp DESC
               LIMIT ?""",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def mark_reviewed(self, log_id: int, reviewed_by: str = "master", notes: str = ""):
        self._conn.execute(
            "UPDATE central_log SET reviewed = 1, reviewed_by = ?, notes = ? WHERE id = ?",
            (reviewed_by, notes, log_id)
        )
        self._conn.commit()

    def get_agent_health(self) -> list[dict]:
        """Health summary per agent: error count, last activity, CTA count."""
        cur = self._conn.execute("""
            SELECT agent_name,
                   COUNT(*) as total_logs,
                   SUM(CASE WHEN level >= 40 THEN 1 ELSE 0 END) as errors,
                   SUM(CASE WHEN level >= 50 THEN 1 ELSE 0 END) as ctas,
                   MAX(timestamp) as last_active
            FROM central_log
            WHERE timestamp >= datetime('now', '-24 hours')
            GROUP BY agent_name
            ORDER BY errors DESC
        """)
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    @classmethod
    def _reset(cls):
        """Reset singleton for testing."""
        with cls._lock:
            if cls._instance:
                cls._instance.close()
                cls._instance = None
