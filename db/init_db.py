import sqlite3
from pathlib import Path
from loguru import logger

def init_database(data_dir: str = "data") -> bool:
    """Initialize all database schemas."""
    db_dir = Path(data_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    # Create the shared revenue database
    db_path = db_dir / "revenue.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS revenue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            category TEXT,
            description TEXT,
            platform TEXT,
            verified BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            category TEXT,
            description TEXT,
            approved BOOLEAN DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            total_revenue REAL DEFAULT 0,
            total_expenses REAL DEFAULT 0,
            net_profit REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_revenue_agent ON revenue_events(agent_name);
        CREATE INDEX IF NOT EXISTS idx_expenses_agent ON expenses(agent_name);
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {db_path}")
    return True
