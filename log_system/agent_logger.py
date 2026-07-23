import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from enum import IntEnum
from loguru import logger

class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    ACTION = 25   # a concrete action taken
    WARNING = 30
    ERROR = 40
    REVENUE = 45  # revenue-related event
    CTA = 50      # call to action (needs human attention)

class AgentLogger:
    """Per-agent structured logger.
    
    Log levels:
    - DEBUG (10): verbose details
    - INFO (20): normal operational info
    - ACTION (25): concrete actions taken (posted, traded, bought, sold)
    - WARNING (30): potential issues
    - ERROR (40): failures
    - REVENUE (45): revenue/expense events
    - CTA (50): CALL TO ACTION - needs human attention
    
    Not every log is a CTA. Only critical issues, approvals, or decisions get CTA level.
    """

    def __init__(self, agent_name: str, db_dir: str = "data/logs"):
        self.agent_name = agent_name
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"{agent_name}_log.db"
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level INTEGER NOT NULL,
                category TEXT DEFAULT 'general',
                message TEXT NOT NULL,
                data JSON,
                session_id TEXT,
                memory_saved BOOLEAN DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_log_level ON agent_log(level);
            CREATE INDEX IF NOT EXISTS idx_log_category ON agent_log(category);
            CREATE INDEX IF NOT EXISTS idx_log_timestamp ON agent_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_log_cta ON agent_log(level) WHERE level >= 50;
        """)
        self._conn.commit()

    def log(self, level: LogLevel, message: str, category: str = "general",
            data: dict = None, session_id: str = None):
        data_json = json.dumps(data) if data else None
        self._conn.execute(
            "INSERT INTO agent_log (level, category, message, data, session_id) VALUES (?, ?, ?, ?, ?)",
            (level, message, category, data_json, session_id)
        )
        self._conn.commit()

        # Also send to central log
        self._send_to_central(level, message, category, data, session_id)

        # Log to console at appropriate level
        log_map = {
            LogLevel.DEBUG: logger.debug,
            LogLevel.INFO: logger.info,
            LogLevel.ACTION: logger.info,
            LogLevel.WARNING: logger.warning,
            LogLevel.ERROR: logger.error,
            LogLevel.REVENUE: logger.info,
            LogLevel.CTA: logger.critical,
        }
        log_map.get(level, logger.info)(f"[{self.agent_name}] {message}")

    def debug(self, msg: str, **kwargs):
        self.log(LogLevel.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs):
        self.log(LogLevel.INFO, msg, **kwargs)

    def action(self, msg: str, **kwargs):
        """A concrete action was taken (posted, traded, etc.)."""
        self.log(LogLevel.ACTION, msg, **kwargs)

    def warning(self, msg: str, **kwargs):
        self.log(LogLevel.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs):
        self.log(LogLevel.ERROR, msg, **kwargs)

    def revenue(self, msg: str, amount: float = 0, currency: str = "USD", **kwargs):
        """Revenue or expense event."""
        data = kwargs.pop("data", {})
        data["amount"] = amount
        data["currency"] = currency
        self.log(LogLevel.REVENUE, msg, data=data, **kwargs)

    def cta(self, msg: str, **kwargs):
        """CALL TO ACTION — needs human attention.
        This gets filtered by SuperAgent before reaching human.
        """
        data = kwargs.pop("data", {})
        data["requires_human"] = True
        self.log(LogLevel.CTA, msg, data=data, **kwargs)

    def _send_to_central(self, level: LogLevel, message: str, category: str,
                          data: dict, session_id: str):
        """Push log entry to the central log database."""
        try:
            from log_system.central_log import CentralLog
            cl = CentralLog()
            cl.receive(self.agent_name, int(level), message, category, data, session_id)
        except Exception as e:
            logger.debug(f"Failed to send to central log: {e}")

    def get_recent(self, limit: int = 50, min_level: int = 0) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_log WHERE level >= ? ORDER BY timestamp DESC LIMIT ?",
            (min_level, limit)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_cta_pending(self) -> list[dict]:
        """Get all CTA-level logs that haven't been resolved."""
        cur = self._conn.execute(
            "SELECT * FROM agent_log WHERE level >= 50 ORDER BY timestamp DESC LIMIT 20"
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
        # Close central log as well
        try:
            from log_system.central_log import CentralLog
            cl = CentralLog()
            cl.close()
        except Exception:
            pass
