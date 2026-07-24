import sqlite3
import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime
from loguru import logger

class SystemStore:
    """Global shared database for system-wide state.
    
    Tables:
    - agent_registry: all agents ever created (up to 256 limit)
    - agent_instructions: per-agent system prompt overrides
    - resource_usage: per-agent resource tracking
    - budget: revenue, expenses, auto-buy decisions
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_dir: str = "data"):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_dir: str = "data"):
        if self._initialized:
            return
        self._initialized = True
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "system.db"
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
            CREATE TABLE IF NOT EXISTS agent_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT UNIQUE NOT NULL,
                class_path TEXT NOT NULL,
                status TEXT DEFAULT 'registered',
                income_methods TEXT,
                instructions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                error_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS resource_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                memory_mb REAL DEFAULT 0,
                tokens_used INTEGER DEFAULT 0,
                api_calls INTEGER DEFAULT 0,
                cycle_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS budget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_revenue REAL DEFAULT 0.0,
                total_expenses REAL DEFAULT 0.0,
                auto_buy_enabled BOOLEAN DEFAULT 0,
                max_monthly_budget REAL DEFAULT 50.0,
                monthly_spent REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS auto_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action_type TEXT NOT NULL,
                target TEXT,
                details TEXT,
                success BOOLEAN DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS agent_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                priority INTEGER DEFAULT 1,
                read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                plan_type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_registry_status ON agent_registry(status);
            CREATE INDEX IF NOT EXISTS idx_resource_agent ON resource_usage(agent_name);
            CREATE INDEX IF NOT EXISTS idx_inbox_agent ON agent_inbox(agent_name);
            CREATE INDEX IF NOT EXISTS idx_plans_agent ON agent_plans(agent_name);
        """)
        self._conn.commit()

    # === AGENT REGISTRY ===

    MAX_AGENTS = 256

    def register_agent(self, name: str, class_path: str,
                       income_methods: str = "", instructions: str = "") -> bool:
        if self.count_active() >= self.MAX_AGENTS:
            logger.warning(f"Agent registry full ({self.MAX_AGENTS}) — cannot register {name}")
            return False
        if self.get_agent(name):
            logger.warning(f"Agent {name} already registered")
            return False
        try:
            self._conn.execute(
                "INSERT INTO agent_registry (agent_name, class_path, status, income_methods, instructions) VALUES (?, ?, ?, ?, ?)",
                (name, class_path, "registered", income_methods, instructions)
            )
            self._conn.commit()
            logger.info(f"Agent registered: {name} ({class_path})")
            return True
        except Exception as e:
            logger.error(f"Failed to register agent {name}: {e}")
            return False

    def update_agent_status(self, name: str, status: str):
        self._conn.execute(
            "UPDATE agent_registry SET status = ?, last_active = CURRENT_TIMESTAMP WHERE agent_name = ?",
            (status, name)
        )
        self._conn.commit()

    def record_agent_error(self, name: str):
        self._conn.execute(
            "UPDATE agent_registry SET error_count = error_count + 1 WHERE agent_name = ?",
            (name,)
        )
        self._conn.commit()

    def record_agent_revenue(self, name: str, amount: float):
        self._conn.execute(
            "UPDATE agent_registry SET total_revenue = total_revenue + ? WHERE agent_name = ?",
            (amount, name)
        )
        self._conn.commit()

    def get_all_agents(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_registry ORDER BY created_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_agent(self, name: str) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_registry WHERE agent_name = ?", (name,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_agent_instructions(self, name: str) -> Optional[str]:
        cur = self._conn.execute(
            "SELECT instructions FROM agent_registry WHERE agent_name = ?", (name,)
        )
        row = cur.fetchone()
        return row["instructions"] if row and row["instructions"] else None

    def update_instructions(self, name: str, instructions: str):
        """SuperAgent can override any agent's system prompt instructions."""
        self._conn.execute(
            "UPDATE agent_registry SET instructions = ? WHERE agent_name = ?",
            (instructions, name)
        )
        self._conn.commit()
        self._log_auto_action("edit_instructions", name, f"Instructions updated: {instructions[:100]}...")

    def remove_agent(self, name: str):
        self._conn.execute("DELETE FROM agent_registry WHERE agent_name = ?", (name,))
        self._conn.execute("DELETE FROM resource_usage WHERE agent_name = ?", (name,))
        self._conn.commit()

    def count_active(self) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_registry WHERE status != 'stopped'"
        )
        return cur.fetchone()["cnt"]

    def count_total(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) as cnt FROM agent_registry")
        return cur.fetchone()["cnt"]

    def get_inactive_agents(self, days: int = 7) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_registry WHERE last_active IS NULL OR last_active < datetime('now', ?)",
            (f'-{days} days',)
        )
        return [dict(r) for r in cur.fetchall()]

    # === RESOURCE TRACKING ===

    def record_resource_use(self, name: str, memory_mb: float = 0,
                             tokens: int = 0, api_calls: int = 0, cycles: int = 0):
        self._conn.execute(
            "INSERT INTO resource_usage (agent_name, memory_mb, tokens_used, api_calls, cycle_count) VALUES (?, ?, ?, ?, ?)",
            (name, memory_mb, tokens, api_calls, cycles)
        )
        self._conn.commit()

    def get_resource_summary(self) -> dict:
        """Get aggregate resource usage across all agents (last 24h)."""
        cur = self._conn.execute("""
            SELECT COUNT(DISTINCT agent_name) as active_agents,
                   COALESCE(SUM(memory_mb), 0) as total_memory,
                   COALESCE(SUM(tokens_used), 0) as total_tokens,
                   COALESCE(SUM(api_calls), 0) as total_api_calls
            FROM resource_usage
            WHERE timestamp >= datetime('now', '-24 hours')
        """)
        return dict(cur.fetchone())

    def get_agent_resource_usage(self, name: str, hours: int = 24) -> dict:
        cur = self._conn.execute("""
            SELECT COALESCE(AVG(memory_mb), 0) as avg_memory,
                   COALESCE(MAX(memory_mb), 0) as peak_memory,
                   COALESCE(SUM(tokens_used), 0) as total_tokens,
                   COALESCE(SUM(api_calls), 0) as total_api_calls
            FROM resource_usage
            WHERE agent_name = ? AND timestamp >= datetime('now', ?)
        """, (name, f'-{hours} hours'))
        return dict(cur.fetchone())

    def get_high_resource_agents(self, threshold_mb: float = 500) -> list[dict]:
        """Find agents using more than threshold MB."""
        cur = self._conn.execute("""
            SELECT agent_name, AVG(memory_mb) as avg_memory
            FROM resource_usage
            WHERE timestamp >= datetime('now', '-1 hour')
            GROUP BY agent_name
            HAVING avg_memory > ?
            ORDER BY avg_memory DESC
        """, (threshold_mb,))
        return [dict(r) for r in cur.fetchall()]

    # === BUDGET ===

    def get_budget(self) -> dict:
        cur = self._conn.execute(
            "SELECT * FROM budget ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        # Default
        return {
            "total_revenue": 0.0, "total_expenses": 0.0,
            "auto_buy_enabled": False, "max_monthly_budget": 50.0,
            "monthly_spent": 0.0
        }

    def update_budget(self, revenue: float = 0, expenses: float = 0):
        current = self.get_budget()
        self._conn.execute(
            "INSERT INTO budget (total_revenue, total_expenses, auto_buy_enabled, max_monthly_budget, monthly_spent) VALUES (?, ?, ?, ?, ?)",
            (current["total_revenue"] + revenue,
             current["total_expenses"] + expenses,
             current["auto_buy_enabled"],
             current["max_monthly_budget"],
             current["monthly_spent"])
        )
        self._conn.commit()

    def set_auto_buy(self, enabled: bool, max_budget: float = 50.0):
        current = self.get_budget()
        self._conn.execute(
            "INSERT INTO budget (total_revenue, total_expenses, auto_buy_enabled, max_monthly_budget, monthly_spent) VALUES (?, ?, ?, ?, ?)",
            (current["total_revenue"], current["total_expenses"],
             1 if enabled else 0, max_budget, current["monthly_spent"])
        )
        self._conn.commit()
        self._log_auto_action("toggle_auto_buy", f"enabled={enabled}", f"Max monthly: ${max_budget}")

    def can_afford(self, cost: float) -> bool:
        budget = self.get_budget()
        if not budget.get("auto_buy_enabled"):
            return False
        remaining = budget["max_monthly_budget"] - budget["monthly_spent"]
        return cost <= remaining

    def spend(self, amount: float, description: str) -> bool:
        if not self.can_afford(amount):
            return False
        current = self.get_budget()
        self._conn.execute(
            "INSERT INTO budget (total_revenue, total_expenses, auto_buy_enabled, max_monthly_budget, monthly_spent) VALUES (?, ?, ?, ?, ?)",
            (current["total_revenue"], current["total_expenses"] + amount,
             current["auto_buy_enabled"], current["max_monthly_budget"],
             current["monthly_spent"] + amount)
        )
        self._conn.commit()
        self._log_auto_action("budget_spend", description, f"${amount}")
        return True

    # === AUTO ACTIONS LOG ===

    def _log_auto_action(self, action_type: str, target: str, details: str = ""):
        self._conn.execute(
            "INSERT INTO auto_actions (action_type, target, details) VALUES (?, ?, ?)",
            (action_type, target, details)
        )
        self._conn.commit()

    def get_recent_actions(self, limit: int = 20) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM auto_actions ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    # === AGENT INBOX (human/SuperAgent -> agent messages) ===

    def send_to_agent(self, agent_name: str, sender: str, message: str, priority: int = 1):
        self._conn.execute(
            "INSERT INTO agent_inbox (agent_name, sender, message, priority) VALUES (?, ?, ?, ?)",
            (agent_name, sender, message, priority)
        )
        self._conn.commit()
        logger.info(f"Inbox: {sender} -> {agent_name}: {message[:80]}")

    def get_agent_mail(self, agent_name: str) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_inbox WHERE agent_name = ? AND read = 0 ORDER BY priority DESC, created_at ASC",
            (agent_name,)
        )
        return [dict(r) for r in cur.fetchall()]

    def mark_mail_read(self, msg_id: int):
        self._conn.execute("UPDATE agent_inbox SET read = 1 WHERE id = ?", (msg_id,))
        self._conn.commit()

    def get_inbox_summary(self) -> list[dict]:
        cur = self._conn.execute("""
            SELECT agent_name, COUNT(*) as unread
            FROM agent_inbox WHERE read = 0
            GROUP BY agent_name ORDER BY unread DESC
        """)
        return [dict(r) for r in cur.fetchall()]

    # === AGENT PLANS ===

    def set_plan(self, agent_name: str, plan_type: str, content: str):
        self._conn.execute(
            "INSERT INTO agent_plans (agent_name, plan_type, content, status) VALUES (?, ?, ?, 'active')",
            (agent_name, plan_type, content)
        )
        self._conn.commit()

    def get_agent_plans(self, agent_name: str, limit: int = 10) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM agent_plans WHERE agent_name = ? ORDER BY created_at DESC LIMIT ?",
            (agent_name, limit)
        )
        return [dict(r) for r in cur.fetchall()]

    def get_all_current_plans(self) -> list[dict]:
        cur = self._conn.execute("""
            SELECT agent_name, content, created_at
            FROM agent_plans WHERE plan_type = 'current' AND status = 'active'
            ORDER BY created_at DESC
        """)
        return [dict(r) for r in cur.fetchall()]

    def complete_plan(self, agent_name: str, plan_id: int):
        self._conn.execute(
            "UPDATE agent_plans SET status = 'completed' WHERE id = ? AND agent_name = ?",
            (plan_id, agent_name)
        )
        self._conn.commit()
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    @classmethod
    def _reset(cls):
        with cls._lock:
            if cls._instance:
                cls._instance.close()
                cls._instance = None
