import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger

class RevenueTracker:
    """Tracks revenue and expenses across all agents."""

    def __init__(self, db_path: str = "data/revenue.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @property
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record_revenue(self, agent_name: str, amount: float, currency: str = "USD",
                       category: str = "", description: str = "", platform: str = ""):
        conn = self._conn
        conn.execute(
            "INSERT INTO revenue_events (agent_name, amount, currency, category, description, platform) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_name, amount, currency, category, description, platform)
        )
        conn.commit()
        conn.close()
        logger.info(f"Revenue recorded: {agent_name} earned {amount} {currency}")

    def record_expense(self, agent_name: str, amount: float, currency: str = "USD",
                       category: str = "", description: str = ""):
        conn = self._conn
        conn.execute(
            "INSERT INTO expenses (agent_name, amount, currency, category, description) VALUES (?, ?, ?, ?, ?)",
            (agent_name, amount, currency, category, description)
        )
        conn.commit()
        conn.close()
        logger.info(f"Expense recorded: {agent_name} spent {amount} {currency}")

    def get_total_revenue(self, days: int = 30) -> float:
        conn = self._conn
        cur = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM revenue_events WHERE timestamp >= datetime('now', ?)",
            (f'-{days} days',)
        )
        total = cur.fetchone()[0]
        conn.close()
        return total

    def get_pnl(self, days: int = 30) -> dict:
        conn = self._conn
        revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM revenue_events WHERE timestamp >= datetime('now', ?)",
            (f'-{days} days',)
        ).fetchone()[0]
        expenses = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE timestamp >= datetime('now', ?)",
            (f'-{days} days',)
        ).fetchone()[0]
        conn.close()
        return {"revenue": revenue, "expenses": expenses, "net": revenue - expenses}
