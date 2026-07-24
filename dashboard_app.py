"""Super Agent Dashboard — monitor, control, chat with all agents."""
import os, json, time, threading, sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, abort
from live_tracker import get_all as get_live_data, update as update_live
from loguru import logger

app = Flask(__name__)
DATA_DIR = Path("data")
BUILD_DIR = Path("build_output")
_agent_threads = {}
_agent_instances = {}

def get_store():
    from master.system_store import SystemStore
    return SystemStore()

def seed_agents():
    """Auto-register agents from instructions/ directory on first run."""
    store = get_store()
    existing = store.get_all_agents()
    if existing:
        return
    inst_dir = Path("instructions")
    if not inst_dir.exists():
        logger.warning("instructions/ directory not found at {}", inst_dir.resolve())
        return
    count = 0
    for f in sorted(inst_dir.glob("*.json")):
        name = f.stem
        if name == "Hermes":
            continue
        try:
            inst = json.loads(f.read_text())
            income = inst.get("income_methods", inst.get("genesis_context", {}).get("primary_income", ""))
            ok = store.register_agent(name, "evolving_agent.EvolvingAgent", income_methods=income)
            if ok:
                count += 1
            else:
                logger.warning("Failed to register {}", name)
        except Exception as e:
            logger.error("Error registering {}: {}", name, e)
    if count:
        logger.info("Seeded {} agents from instructions/", count)

def get_sys_db():
    p = DATA_DIR / "system.db"
    if not p.exists(): return None
    c = sqlite3.connect(str(p)); c.row_factory = sqlite3.Row; return c

def get_inst(path: str) -> dict:
    p = Path("instructions") / f"{path}.json"
    if p.exists(): return json.loads(p.read_text())
    if "/" in path:
        sub = path.split("/")[-1]
        p2 = Path("instructions") / f"{sub}.json"
        if p2.exists(): return json.loads(p2.read_text())
    return {}

def get_build_count(a: str) -> int:
    d = BUILD_DIR / a
    return len([f for f in d.iterdir() if f.is_file()]) if d.exists() else 0

def get_latest_build(a: str) -> str:
    d = BUILD_DIR / a
    if d.exists():
        fs = sorted(d.iterdir(), key=os.path.getmtime, reverse=True)
        return fs[0].name if fs else ""
    return ""

# ── Agent Thread Manager ──────────────────────────────────────────

def start_agent_thread(name: str) -> dict:
    if name in _agent_threads and _agent_threads[name].is_alive():
        return {"success": False, "error": "already running"}
    inst = get_inst(name)
    if not inst:
        return {"success": False, "error": "no instruction set"}
    try:
        from evolving_agent import EvolvingAgent
        agent = EvolvingAgent(name)
        _agent_instances[name] = agent

        def _run():
            try:
                store = get_store()
                store.update_agent_status(name, "running")
                agent.run_loop()
            except Exception:
                pass
            finally:
                if name in _agent_threads:
                    del _agent_threads[name]
                if name in _agent_instances:
                    del _agent_instances[name]
                try: store.update_agent_status(name, "idle")
                except: pass

        t = threading.Thread(target=_run, daemon=True, name=f"agent-{name}")
        t.start()
        _agent_threads[name] = t
        return {"success": True, "status": "started"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def stop_agent_thread(name: str) -> dict:
    if name not in _agent_instances and name not in _agent_threads:
        return {"success": False, "error": "not running"}
    if name in _agent_instances:
        try:
            _agent_instances[name].running = False
        except: pass
    try:
        store = get_store()
        store.update_agent_status(name, "stopped")
    except: pass
    return {"success": True, "status": "stopped"}

# ── Log stream ring buffer ────────────────────────────────────────

_log_buffer = []
_log_buffer_lock = threading.Lock()
_MAX_LOG = 500

def append_log(agent: str, level: str, msg: str):
    entry = {"agent": agent, "level": level, "msg": msg, "ts": datetime.now().isoformat()}
    with _log_buffer_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > _MAX_LOG:
            _log_buffer[:50] = []

# Intercept loguru
try:
    from loguru import logger as _loguru
    class _DashboardSink:
        def write(self, msg): pass
        def __call__(self, message):
            try:
                r = message.record
                append_log(r.get("name","system"), r["level"].name, r["message"])
            except: pass
    _loguru.add(_DashboardSink(), level="DEBUG")
except: pass

# ── HTML Routes ───────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html", now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/agent/<name>")
def agent_detail(name):
    return render_template("agent_detail.html", agent_name=name, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/build/<name>/<path:filename>")
def view_build(name, filename):
    fp = BUILD_DIR / name / filename
    if not fp.exists(): abort(404)
    try: content = fp.read_text(errors="replace")
    except: content = "(binary)"
    return render_template("build_view.html", agent_name=name, filename=filename, content=content, ext=fp.suffix, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

# ── Agent Control API ─────────────────────────────────────────────

@app.route("/api/agent/<name>/start", methods=["POST"])
def api_agent_start(name):
    return jsonify(start_agent_thread(name))

@app.route("/api/agent/<name>/stop", methods=["POST"])
def api_agent_stop(name):
    return jsonify(stop_agent_thread(name))

@app.route("/api/agent/<name>/restart", methods=["POST"])
def api_agent_restart(name):
    stop_agent_thread(name)
    time.sleep(0.5)
    return jsonify(start_agent_thread(name))

# ── Agent Data API ────────────────────────────────────────────────

@app.route("/api/agent/<name>/chat")
def api_agent_chat(name):
    limit = request.args.get("limit", 50, type=int)
    store = get_store()
    return jsonify(store.get_chat_history(name, limit))

@app.route("/api/agent/<name>/instructions")
def api_agent_instructions(name):
    inst = get_inst(name)
    if not inst: return jsonify({"error": "not found"}), 404
    return jsonify(inst)

@app.route("/api/agent/<name>/memory")
def api_agent_memory(name):
    try:
        db = DATA_DIR / "memory" / f"{name}_memory.db"
        if not db.exists(): return jsonify([])
        c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM memory ORDER BY id DESC LIMIT 100").fetchall()
        c.close()
        return jsonify([dict(r) for r in rows])
    except: return jsonify([])

# ── System API ────────────────────────────────────────────────────

@app.route("/api/agents")
def api_agents():
    store = get_store()
    seed_agents()
    agents = store.get_all_agents()
    live = get_live_data()
    for a in agents:
        a["build_count"] = get_build_count(a["agent_name"])
        a["latest_build"] = get_latest_build(a["agent_name"])
        l = live.get(a["agent_name"], {})
        a["live_input"] = l.get("input", "")
        a["live_output"] = l.get("output", "")
        a["thread_alive"] = a["agent_name"] in _agent_threads and _agent_threads[a["agent_name"]].is_alive()
    return jsonify(agents)

@app.route("/api/live")
def api_live():
    store = get_store()
    agents = store.get_all_agents()
    live = get_live_data()
    for a in agents:
        l = live.get(a["agent_name"], {})
        a["live_input"] = l.get("input", "")
        a["live_output"] = l.get("output", "")
        a["running"] = a["agent_name"] in _agent_threads and _agent_threads[a["agent_name"]].is_alive()
    inbox_count = 0
    try: inbox_count = store.get_inbox_summary()
    except: pass
    return jsonify({
        "agents": agents,
        "timestamp": datetime.now().isoformat(),
        "threads": {n: t.is_alive() for n, t in _agent_threads.items()},
    })

@app.route("/api/status")
def api_status():
    store = get_store()
    return jsonify({
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "agents": store.get_all_agents(),
        "threads": {n: t.is_alive() for n, t in _agent_threads.items()},
    })

@app.route("/api/logs")
def api_logs():
    limit = request.args.get("limit", 100, type=int)
    agent = request.args.get("agent", "")
    level = request.args.get("level", "")
    with _log_buffer_lock:
        logs = list(_log_buffer)
    if agent: logs = [l for l in logs if l["agent"] == agent]
    if level: logs = [l for l in logs if l["level"] == level]
    return jsonify(logs[-limit:])

@app.route("/api/builds/<name>")
def api_builds(name):
    d = BUILD_DIR / name
    if not d.exists(): return jsonify([])
    fs = sorted(d.iterdir(), key=os.path.getmtime, reverse=True)[:20]
    r = []
    for f in fs:
        try:
            c = f.read_text(errors="replace")[:500]
            r.append({"filename": f.name, "timestamp": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(), "preview": c, "size": f.stat().st_size})
        except: r.append({"filename": f.name, "preview": "", "size": 0})
    return jsonify(r)

@app.route("/api/advise", methods=["POST"])
def api_advise():
    data = request.get_json(force=True)
    an = data.get("agent_name", "").strip()
    msg = data.get("message", "").strip()
    if not an or not msg: return jsonify({"error": "agent_name and message required"}), 400
    store = get_store()
    store.send_to_agent(an, "human", msg, 5)
    return jsonify({"success": True, "sent_to": an})

@app.route("/api/plans")
def api_plans():
    store = get_store()
    return jsonify(store.get_all_current_plans())

@app.route("/api/revenue")
def api_revenue():
    rdb = DATA_DIR / "revenue.db"
    if not rdb.exists(): return jsonify({"total": 0, "24h": 0, "7d": 0})
    c = sqlite3.connect(str(rdb))
    t = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events").fetchone()[0]
    h = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-24 hours')").fetchone()[0]
    w = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue_events WHERE timestamp >= datetime('now', '-7 days')").fetchone()[0]
    c.close()
    return jsonify({"total": t, "24h": h, "7d": w})

@app.route("/api/health")
def api_health():
    return "OK"

@app.route("/api/debug/seed")
def api_debug_seed():
    """Force re-seed and return debug info."""
    store = get_store()
    before = store.get_all_agents()
    seed_agents()
    after = store.get_all_agents()
    inst_dir = Path("instructions")
    files = list(inst_dir.glob("*.json")) if inst_dir.exists() else []
    return jsonify({
        "before_seed": before,
        "after_seed": after,
        "instructions_dir_exists": inst_dir.exists(),
        "instructions_dir_path": str(inst_dir.resolve()),
        "json_files": [f.name for f in files],
        "system_db_exists": Path("data/system.db").exists(),
        "system_db_path": str(Path("data/system.db").resolve()),
        "cwd": str(Path.cwd()),
    })

# ── SSE Stream ────────────────────────────────────────────────────

@app.route("/api/stream/logs")
def stream_logs():
    def gen():
        seen = set()
        while True:
            try:
                with _log_buffer_lock:
                    for entry in _log_buffer:
                        eid = id(entry)
                        if eid not in seen:
                            seen.add(eid)
                            yield f"data: {json.dumps(entry)}\n\n"
                time.sleep(0.5)
            except GeneratorExit:
                break
    return Response(gen(), mimetype="text/event-stream")

# ── Main ──────────────────────────────────────────────────────────

def run_dashboard(port=8080, debug=False):
    print(f"Dashboard running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False, threaded=True)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_dashboard(port)
