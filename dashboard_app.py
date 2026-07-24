"""Interactive Flask dashboard — real-time agent monitoring and control.

Endpoints:
    GET  /                    - Main dashboard
    GET  /agent/<name>        - Per-agent detail page
    POST /agent/<name>/advise - Send advice to an agent
    GET  /api/status          - JSON: system overview
    GET  /api/agents          - JSON: all agents
    GET  /api/logs            - JSON: filtered logs
    GET  /api/agent/<name>    - JSON: single agent detail
    POST /api/agent/<name>/start  - Start an agent
    POST /api/agent/<name>/stop   - Stop an agent
    POST /api/agent/<name>/restart- Restart an agent
"""

import os
import json
import time
import subprocess
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

DATA_DIR = Path("data")
LOG_DIR = DATA_DIR / "logs"
BUILD_DIR = Path("build_output")

_running_agents = {}


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


def get_build_count(agent_name):
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        return len([f for f in agent_dir.iterdir() if f.is_file()])
    return 0


def get_latest_build(agent_name):
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        files = sorted(agent_dir.iterdir(), key=os.path.getmtime, reverse=True)
        if files:
            return files[0].name
    return ""


def get_build_preview(agent_name):
    agent_dir = BUILD_DIR / agent_name
    if agent_dir.exists():
        files = sorted(agent_dir.iterdir(), key=os.path.getmtime, reverse=True)
        if files:
            try:
                return files[0].read_text(errors="replace")[:300]
            except Exception:
                return "(binary)"
    return ""


def get_recent_logs(agent_name=None, level=None, limit=50, since=None):
    cl = get_central_log()
    if not cl:
        return []
    query = "SELECT id, agent_name, level, message, timestamp FROM central_log"
    params = []
    conditions = []
    if agent_name:
        conditions.append("agent_name = ?")
        params.append(agent_name)
    if level:
        conditions.append("level = ?")
        params.append(level)
    if since:
        conditions.append("timestamp > ?")
        params.append(since)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    try:
        rows = cl.execute(query, params).fetchall()
        cl.close()
        return [dict(r) for r in rows]
    except Exception:
        cl.close()
        return []


def get_unread_counts():
    db = get_system_db()
    if not db:
        return {}
    try:
        rows = db.execute(
            "SELECT agent_name, COUNT(*) as unread FROM agent_inbox WHERE read = 0 GROUP BY agent_name"
        ).fetchall()
        db.close()
        return {r["agent_name"]: r["unread"] for r in rows}
    except Exception:
        db.close()
        return {}


def get_active_plans():
    db = get_system_db()
    if not db:
        return []
    try:
        rows = db.execute(
            "SELECT agent_name, content, created_at FROM agent_plans WHERE plan_type = 'current' AND status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        db.close()
        return []


# === HTML ROUTES ===

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/agent/<name>")
def agent_detail(name):
    return render_template("agent_detail.html", agent_name=name)


@app.route("/agent/<name>/advise", methods=["POST"])
def send_advice(name):
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("agent_detail", name=name))
    db = get_system_db()
    if db:
        try:
            db.execute(
                "INSERT INTO agent_inbox (agent_name, sender, message, priority) VALUES (?, ?, ?, ?)",
                (name, "human", message, 5)
            )
            db.commit()
            db.close()
        except Exception:
            db.close()
    return redirect(url_for("agent_detail", name=name))


# === API ROUTES ===

@app.route("/api/status")
def api_status():
    db = get_system_db()
    agents = []
    if db:
        try:
            for r in db.execute("SELECT agent_name, status, error_count, COALESCE(total_revenue,0) as rev FROM agent_registry").fetchall():
                d = dict(r)
                d["running"] = d["agent_name"] in _running_agents
                agents.append(d)
            db.close()
        except Exception:
            db.close()
    return jsonify({
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": agents,
        "running_count": len(_running_agents),
    })


@app.route("/api/agents")
def api_agents():
    db = get_system_db()
    agents = []
    if db:
        try:
            for r in db.execute("SELECT * FROM agent_registry ORDER BY created_at ASC").fetchall():
                d = dict(r)
                d["build_count"] = get_build_count(d["agent_name"])
                d["latest_build"] = get_latest_build(d["agent_name"])
                d["running"] = d["agent_name"] in _running_agents
                agents.append(d)
            db.close()
        except Exception:
            db.close()
    unread = get_unread_counts()
    for a in agents:
        a["unread"] = unread.get(a["agent_name"], 0)
    return jsonify(agents)


@app.route("/api/agent/<name>")
def api_agent(name):
    db = get_system_db()
    agent = None
    plans = []
    inbox = []
    if db:
        try:
            row = db.execute("SELECT * FROM agent_registry WHERE agent_name = ?", (name,)).fetchone()
            if row:
                agent = dict(row)
            plans = [dict(r) for r in db.execute(
                "SELECT * FROM agent_plans WHERE agent_name = ? ORDER BY created_at DESC LIMIT 20", (name,)
            ).fetchall()]
            inbox = [dict(r) for r in db.execute(
                "SELECT * FROM agent_inbox WHERE agent_name = ? ORDER BY created_at DESC LIMIT 20", (name,)
            ).fetchall()]
            db.close()
        except Exception:
            db.close()
    if not agent:
        return jsonify({"error": "not found"}), 404
    agent["running"] = name in _running_agents
    agent["build_count"] = get_build_count(name)
    agent["latest_build"] = get_latest_build(name)
    agent["build_preview"] = get_build_preview(name)
    return jsonify({
        "agent": agent,
        "plans": plans,
        "inbox": inbox,
    })


@app.route("/api/logs")
def api_logs():
    limit = request.args.get("limit", 50, type=int)
    agent = request.args.get("agent", "")
    level = request.args.get("level", "")
    since = request.args.get("since", "")
    logs = get_recent_logs(
        agent_name=agent or None,
        level=int(level) if level else None,
        limit=limit,
        since=since or None,
    )
    return jsonify(logs)


@app.route("/api/unread")
def api_unread():
    return jsonify(get_unread_counts())


@app.route("/api/plans")
def api_plans():
    return jsonify(get_active_plans())


@app.route("/api/agent/<name>/start", methods=["POST"])
def api_start_agent(name):
    if name in _running_agents:
        return jsonify({"success": False, "error": "Already running"})
    try:
        proc = subprocess.Popen(
            ["python", "main.py", "--agent", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        _running_agents[name] = {"process": proc, "started_at": time.time()}
        return jsonify({"success": True, "message": f"{name} started"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/agent/<name>/stop", methods=["POST"])
def api_stop_agent(name):
    if name not in _running_agents:
        return jsonify({"success": False, "error": "Not running"})
    try:
        _running_agents[name]["process"].terminate()
        _running_agents[name]["process"].wait(timeout=10)
        del _running_agents[name]
        return jsonify({"success": True, "message": f"{name} stopped"})
    except Exception as e:
        try:
            _running_agents[name]["process"].kill()
        except Exception:
            pass
        _running_agents.pop(name, None)
        return jsonify({"success": True, "message": f"{name} killed"})


@app.route("/api/agent/<name>/restart", methods=["POST"])
def api_restart_agent(name):
    api_stop_agent(name)
    time.sleep(1)
    return api_start_agent(name)


@app.route("/api/advise", methods=["POST"])
def api_advise():
    data = request.get_json(force=True)
    agent_name = data.get("agent_name", "").strip()
    message = data.get("message", "").strip()
    if not agent_name or not message:
        return jsonify({"error": "agent_name and message required"}), 400
    db = get_system_db()
    if db:
        try:
            db.execute(
                "INSERT INTO agent_inbox (agent_name, sender, message, priority) VALUES (?, ?, ?, ?)",
                (agent_name, "human", message, 5)
            )
            db.commit()
            db.close()
        except Exception:
            db.close()
    return jsonify({"success": True, "sent_to": agent_name})


def run_dashboard(port=8080, debug=False):
    print(f"Dashboard running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)


# === Auto-start agents (24/7 Railway mode) ===
import sys as _sys
import threading as _thr

def _bootstrap():
    import time as _time
    _sys.stderr.write("[SuperAgent] Bootstrapping agents...\n")
    _sys.stderr.flush()
    try:
        from db.init_db import init_database
        from config.settings import load_config
        cfg = load_config()
        init_database(cfg.get("data_dir", "data"))
        _sys.stderr.write("[SuperAgent] DB initialized\n")
        _sys.stderr.flush()

        from master.orchestrator import Orchestrator
        orch = Orchestrator()
        _sys.stderr.write(f"[SuperAgent] Orchestrator: {len(orch.agents)} agents\n")
        _sys.stderr.flush()
        orch.run()
    except Exception as e:
        _sys.stderr.write(f"[SuperAgent] FATAL: {e}\n")
        _sys.stderr.flush()
        while True:
            _time.sleep(60)

if os.environ.get("DEPLOY") == "true":
    _t = _thr.Thread(target=_bootstrap, daemon=True)
    _t.start()

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_dashboard(port)
