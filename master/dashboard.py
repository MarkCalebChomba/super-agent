"""Terminal dashboard for monitoring agent system status."""

import os
import sqlite3
from pathlib import Path
from datetime import datetime
from loguru import logger

def get_central_log():
    db = Path("data/logs/central_log.db")
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn

def get_system_db():
    db = Path("data/system.db")
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn

def print_dashboard():
    """Print a dashboard to stdout."""
    width = 70

    print("=" * width)
    print(f"  SUPER AGENT SYSTEM DASHBOARD")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * width)

    # Agent Summary
    print(f"\n{' AGENTS ':=^{width}}")
    sys_db = get_system_db()
    if sys_db:
        cur = sys_db.execute("SELECT agent_name, status, error_count, total_revenue FROM agent_registry ORDER BY created_at ASC")
        agents = cur.fetchall()
        if agents:
            print(f"  {'NAME':<25} {'STATUS':<12} {'ERRORS':<8} {'REVENUE':<10}")
            print(f"  {'-'*25} {'-'*12} {'-'*8} {'-'*10}")
            for a in agents:
                name = a["agent_name"][:24]
                status = a["status"][:11]
                errs = a["error_count"]
                rev = a["total_revenue"]
                print(f"  {name:<25} {status:<12} {errs:<8} ${rev:<7.2f}")
        else:
            print("  No agents registered")
    else:
        print("  System DB not found (is the system running?)")

    # Recent Activity
    print(f"\n{' RECENT ACTIVITY ':=^{width}}")
    cl = get_central_log()
    if cl:
        cur = cl.execute(
            "SELECT agent_name, level, message, timestamp FROM central_log ORDER BY id DESC LIMIT 10"
        )
        logs = cur.fetchall()
        if logs:
            for log in logs:
                level_str = {10: "DEBUG", 20: "INFO", 25: "ACTN", 30: "WARN", 40: "ERR", 45: "REV", 50: "CTA"}.get(log["level"], "?")
                msg = log["message"][:50]
                ts = log["timestamp"][:19] if log["timestamp"] else ""
                print(f"  [{ts}] {log['agent_name']:<20} {level_str:<5} {msg}")
        else:
            print("  No recent logs")
    else:
        print("  Central log not found")

    # Revenue Summary
    print(f"\n{' REVENUE ':=^{width}}")
    rt_db = Path("data/revenue.db")
    if rt_db.exists():
        conn = sqlite3.connect(str(rt_db))
        cur = conn.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events")
        total = cur.fetchone()[0]
        # Last 24h
        cur = conn.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-24 hours')")
        last24 = cur.fetchone()[0]
        # Last 7 days
        cur = conn.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-7 days')")
        last7 = cur.fetchone()[0]
        conn.close()
        print(f"  All time:   ${total:.2f}")
        print(f"  Last 7 days: ${last7:.2f}")
        print(f"  Last 24h:    ${last24:.2f}")
    else:
        print("  No revenue data yet")

    # Resources
    print(f"\n{' RESOURCES ':=^{width}}")
    if sys_db:
        cur = sys_db.execute("""
            SELECT COALESCE(SUM(memory_mb),0) as mem,
                   COALESCE(SUM(tokens_used),0) as tokens,
                   COALESCE(SUM(api_calls),0) as api
            FROM resource_usage WHERE timestamp >= datetime('now', '-24 hours')
        """)
        r = cur.fetchone()
        if r:
            print(f"  Memory:      {r['mem']:.0f} MB (24h)")
            print(f"  Tokens:      {r['tokens']} (24h)")
            print(f"  API calls:   {r['api']} (24h)")

        # Budget
        cur = sys_db.execute("SELECT * FROM budget ORDER BY id DESC LIMIT 1")
        b = cur.fetchone()
        if b:
            net = b["total_revenue"] - b["total_expenses"]
            print(f"  Budget:      ${net:.2f} net (rev ${b['total_revenue']:.2f} - exp ${b['total_expenses']:.2f})")
            print(f"  Auto-buy:    {'ON' if b['auto_buy_enabled'] else 'OFF'} (${b['max_monthly_budget']:.0f}/mo, ${b['monthly_spent']:.2f} spent)")

    # SuperAgent Actions
    if sys_db:
        cur = sys_db.execute("SELECT action_type, target, details, timestamp FROM auto_actions ORDER BY id DESC LIMIT 5")
        actions = cur.fetchall()
        print(f"\n{' SUPERAGENT ACTIONS ':=^{width}}")
        if actions:
            for a in actions:
                tgt = a['target'] if a['target'] else ''
                det = str(a['details']) if a['details'] else ''
                print(f"  [{a['timestamp'][:19]}] {a['action_type']}: {tgt[:30]} - {det[:40]}")
        else:
            print("  No SuperAgent actions yet")
        sys_db.close()

    if cl:
        cl.close()

    print(f"\n{'=' * width}")
    print(f"  Refresh by running: python main.py --status")
    print(f"  Web dashboard:      http://localhost:8080/")
    print(f"{'=' * width}")
