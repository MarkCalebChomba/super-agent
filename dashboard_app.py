"""Full-featured Flask dashboard for agent system monitoring and control.

Endpoints:
    GET  /              - Main dashboard (all agents, resources, plans)
    GET  /agent/<name>  - Per-agent detail (logs, plan, inbox, files)
    POST /api/advise    - Send advice to an agent
    GET  /api/agents    - JSON: all agents
    GET  /api/health    - JSON: system health
"""

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

DATA_DIR = Path("data")
LOG_DIR = DATA_DIR / "logs"
BUILD_DIR = Path("build_output")


def get_central_log():
    db = LOG_DIR / "central_log.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def get_system_db():
    db = DATA_DIR / "system.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def get_revenue_db():
    db = DATA_DIR / "revenue.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def get_build_count(agent_name: str) -> int:
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        return len([f for f in agent_dir.iterdir() if f.is_file()])
    return 0


def get_latest_build(agent_name: str) -> str:
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        files = sorted(agent_dir.iterdir(), key=os.path.getmtime, reverse=True)
        if files:
            return files[0].name
    return ""


def get_build_preview(agent_name: str) -> str:
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        files = sorted(agent_dir.iterdir(), key=os.path.getmtime, reverse=True)
        if files:
            try:
                content = files[0].read_text(errors="replace")
                return content[:300]
            except Exception:
                return "(binary or unreadable)"
    return ""


def get_agent_logs(agent_name: str, limit: int = 50) -> list:
    cl = get_central_log()
    if not cl:
        return []
    rows = cl.execute(
        "SELECT level, message, timestamp FROM central_log WHERE agent_name = ? ORDER BY id DESC LIMIT ?",
        (agent_name, limit)
    ).fetchall()
    cl.close()
    return [dict(r) for r in rows]


def get_all_recent_logs(limit: int = 30) -> list:
    cl = get_central_log()
    if not cl:
        return []
    rows = cl.execute(
        "SELECT agent_name, level, message, timestamp FROM central_log ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    cl.close()
    return [dict(r) for r in rows]


def get_resource_summary() -> dict:
    db = get_system_db()
    if not db:
        return {}
    row = db.execute("""
        SELECT COUNT(DISTINCT agent_name) as active_agents,
               COALESCE(SUM(memory_mb), 0) as total_memory,
               COALESCE(SUM(tokens_used), 0) as total_tokens,
               COALESCE(SUM(api_calls), 0) as total_api_calls
        FROM resource_usage WHERE timestamp >= datetime('now', '-24 hours')
    """).fetchone()
    db.close()
    return dict(row) if row else {}


# === HTML ROUTES ===

@app.route("/")
def index():
    db = get_system_db()
    agents_data = []
    if db:
        rows = db.execute("SELECT * FROM agent_registry ORDER BY created_at ASC").fetchall()
        for r in rows:
            d = dict(r)
            d["build_count"] = get_build_count(d["agent_name"])
            d["latest_build"] = get_latest_build(d["agent_name"])
            agents_data.append(d)
        db.close()

    # Inbox summary
    inbox = []
    if db:
        rows = db.execute(
            "SELECT agent_name, COUNT(*) as unread FROM agent_inbox WHERE read = 0 GROUP BY agent_name ORDER BY unread DESC"
        ).fetchall()
        inbox = [dict(r) for r in rows]

    logs = get_all_recent_logs(20)
    resources = get_resource_summary()
    plans = []
    if db:
        rows = db.execute(
            "SELECT agent_name, content, created_at FROM agent_plans WHERE plan_type = 'current' AND status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        plans = [dict(r) for r in rows]
        db.close()

    revenue = {"total": 0.0, "24h": 0.0, "7d": 0.0}
    rdb = get_revenue_db()
    if rdb:
        revenue["total"] = rdb.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events").fetchone()[0]
        revenue["24h"] = rdb.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-24 hours')").fetchone()[0]
        revenue["7d"] = rdb.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-7 days')").fetchone()[0]
        rdb.close()

    return render_template("dashboard.html",
        agents=agents_data,
        inbox=inbox,
        logs=logs,
        resources=resources,
        plans=plans,
        revenue=revenue,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


@app.route("/agent/<name>")
def agent_detail(name):
    db = get_system_db()
    agent = None
    plans = []
    inbox = []
    mail_count = 0
    if db:
        row = db.execute("SELECT * FROM agent_registry WHERE agent_name = ?", (name,)).fetchone()
        if row:
            agent = dict(row)
        plans = [dict(r) for r in db.execute(
            "SELECT * FROM agent_plans WHERE agent_name = ? ORDER BY created_at DESC LIMIT 20", (name,)
        ).fetchall()]
        inbox = [dict(r) for r in db.execute(
            "SELECT * FROM agent_inbox WHERE agent_name = ? ORDER BY created_at DESC LIMIT 20", (name,)
        ).fetchall()]
        mail_count = db.execute(
            "SELECT COUNT(*) as c FROM agent_inbox WHERE agent_name = ? AND read = 0", (name,)
        ).fetchone()["c"]
        db.close()

    if not agent:
        return "Agent not found", 404

    logs = get_agent_logs(name, 100)
    build_count = get_build_count(name)
    latest_build = get_latest_build(name)
    build_preview = get_build_preview(name)
    resource_usage = {}
    db = get_system_db()
    if db:
        row = db.execute(
            "SELECT COALESCE(AVG(memory_mb),0) as avg_mem, COALESCE(SUM(tokens_used),0) as tok, COALESCE(SUM(api_calls),0) as api FROM resource_usage WHERE agent_name = ? AND timestamp >= datetime('now', '-24 hours')",
            (name,)
        ).fetchone()
        resource_usage = dict(row) if row else {}
        db.close()

    return render_template("agent_detail.html",
        agent=agent,
        logs=logs,
        plans=plans,
        inbox=inbox,
        mail_count=mail_count,
        build_count=build_count,
        latest_build=latest_build,
        build_preview=build_preview,
        resource_usage=resource_usage,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


@app.route("/agent/<name>/send_advice", methods=["POST"])
def send_advice(name):
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("agent_detail", name=name))
    db = get_system_db()
    if db:
        db.execute(
            "INSERT INTO agent_inbox (agent_name, sender, message, priority) VALUES (?, ?, ?, ?)",
            (name, "human", message, 5)
        )
        db.commit()
        db.close()
    return redirect(url_for("agent_detail", name=name))


# === API ROUTES ===

@app.route("/api/health")
def api_health():
    return "OK"


@app.route("/api/status")
def api_status():
    db = get_system_db()
    agents = []
    if db:
        agents = [dict(r) for r in db.execute("SELECT agent_name, status, error_count, COALESCE(total_revenue,0) as rev FROM agent_registry").fetchall()]
        db.close()
    return jsonify({
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": agents,
    })


@app.route("/api/agents")
def api_agents():
    db = get_system_db()
    if not db:
        return jsonify([])
    agents = []
    for r in db.execute("SELECT * FROM agent_registry ORDER BY created_at ASC").fetchall():
        d = dict(r)
        d["build_count"] = get_build_count(d["agent_name"])
        d["latest_build"] = get_latest_build(d["agent_name"])
        agents.append(d)
    db.close()
    return jsonify(agents)


@app.route("/api/advise", methods=["POST"])
def api_advise():
    data = request.get_json(force=True)
    agent_name = data.get("agent_name", "").strip()
    message = data.get("message", "").strip()
    if not agent_name or not message:
        return jsonify({"error": "agent_name and message required"}), 400
    db = get_system_db()
    if db:
        db.execute(
            "INSERT INTO agent_inbox (agent_name, sender, message, priority) VALUES (?, ?, ?, ?)",
            (agent_name, "human", message, 5)
        )
        db.commit()
        db.close()
    return jsonify({"success": True, "sent_to": agent_name})


@app.route("/api/logs")
def api_logs():
    limit = request.args.get("limit", 50, type=int)
    agent = request.args.get("agent", "")
    if agent:
        logs = get_agent_logs(agent, limit)
    else:
        logs = get_all_recent_logs(limit)
    return jsonify(logs)


@app.route("/api/plans")
def api_plans():
    db = get_system_db()
    if not db:
        return jsonify([])
    rows = db.execute(
        "SELECT agent_name, content, created_at FROM agent_plans WHERE plan_type = 'current' AND status = 'active' ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# === MAIN ===

def run_dashboard(port: int = 8080, debug: bool = False):
    print(f"Dashboard running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_dashboard(port)
