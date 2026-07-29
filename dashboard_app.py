"""Super Agent Dashboard — monitor, control, chat with all agents."""
import os, json, time, threading, sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, abort
from live_tracker import get_all as get_live_data, update as update_live
from loguru import logger

app = Flask(__name__)

@app.errorhandler(404)
def api_404(e):
    return jsonify({"error": "not found"}), 404

@app.errorhandler(405)
def api_405(e):
    return jsonify({"error": "method not allowed"}), 405

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
    store = get_store()
    agent = store.get_agent(name)
    if not agent:
        agent = {"agent_name": name, "status": "unknown", "current_task": "",
                 "income_methods": "", "error_count": 0, "total_revenue": 0.0,
                 "class_path": "", "created_at": "", "last_active": ""}
    build_count = get_build_count(name)
    latest_build = get_latest_build(name)
    build_preview = ""
    if latest_build:
        fp = BUILD_DIR / name / latest_build
        if fp.exists():
            build_preview = fp.read_text(errors="replace")[:5000]
    recent_builds = []
    d = BUILD_DIR / name
    if d.exists():
        for f in sorted(d.iterdir(), key=os.path.getmtime, reverse=True)[:10]:
            try:
                c = f.read_text(errors="replace")
                recent_builds.append({"filename": f.name, "timestamp": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(), "preview": c, "size": f.stat().st_size})
            except: pass
    logs = []
    try:
        db = DATA_DIR / f"{name}.db"
        if db.exists():
            c = sqlite3.connect(str(db))
            c.row_factory = sqlite3.Row
            logs = [dict(r) for r in c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 100").fetchall()]
            c.close()
    except: pass
    resource_usage = {"avg_mem": 0, "tok": 0, "api": 0}
    inbox = []
    mail_count = 0
    try:
        inbox = store.get_agent_mail(name)
        mail_count = sum(1 for m in inbox if not m.get("read"))
    except: pass
    try: plans = store.get_agent_plans(name, 20)
    except: plans = []
    return render_template("agent_detail.html", agent=agent, build_count=build_count,
                           latest_build=latest_build, build_preview=build_preview,
                           recent_builds=recent_builds, logs=logs,
                           resource_usage=resource_usage, inbox=inbox,
                           mail_count=mail_count, plans=plans,
                           now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/analysis")
def analysis_page():
    return render_template("analysis.html", now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

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

@app.route("/api/agents/start-all", methods=["POST"])
def api_agents_start_all():
    store = get_store()
    agents = store.get_all_agents()
    results = {}
    for a in agents:
        name = a["agent_name"]
        if name not in _agent_threads or not _agent_threads[name].is_alive():
            results[name] = start_agent_thread(name)
        else:
            results[name] = {"success": False, "error": "already running"}
    return jsonify(results)

@app.route("/api/agents/stop-all", methods=["POST"])
def api_agents_stop_all():
    store = get_store()
    agents = store.get_all_agents()
    results = {}
    for a in agents:
        name = a["agent_name"]
        results[name] = stop_agent_thread(name)
    return jsonify(results)

# ── Agent Data API ────────────────────────────────────────────────

@app.route("/api/agent/<name>/chat")
def api_agent_chat(name):
    limit = request.args.get("limit", 50, type=int)
    role = request.args.get("role") or None
    store = get_store()
    return jsonify(store.get_chat_history(name, limit, role=role))

@app.route("/api/agent/<name>/instructions")
def api_agent_instructions(name):
    inst = get_inst(name)
    if not inst: return jsonify({"error": "not found"}), 404
    return jsonify(inst)

@app.route("/api/agent/<name>/resources")
def api_agent_resources(name):
    try:
        from resource_bank import ResourceBank
        bank = ResourceBank(name)
        return jsonify({
            "balance": bank.balance,
            "total_revenue": bank.total_revenue,
            "total_costs": bank.total_costs,
            "capabilities": {k: v.get("available") for k, v in bank.capabilities.items()},
            "accounts": {k: v.get("status") for k, v in bank.accounts.items()},
            "tools": {k: v.get("available") for k, v in bank.tools.items()},
            "income_log": bank.income_log[-10:],
            "expense_log": bank.expense_log[-10:],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/finance")
def api_finance():
    try:
        from finance_layer import get_all_finance_summary
        return jsonify(get_all_finance_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/finance/<name>")
def api_finance_agent(name):
    try:
        from finance_layer import FinanceLayer, get_pending_tasks, get_all_tasks
        fl = FinanceLayer(name)
        return jsonify({
            "balance": fl.balance,
            "total_earned": fl.total_earned,
            "total_spent": fl.total_spent,
            "accounts": fl.accounts,
            "transactions": fl.transactions[-20:],
            "pending_tasks": get_pending_tasks(name),
            "all_tasks": get_all_tasks(name, limit=10),
            "finance_report": fl.get_finance_report(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/human-tasks")
def api_human_tasks():
    try:
        from finance_layer import get_pending_tasks, get_all_tasks
        agent = request.args.get("agent", "")
        return jsonify({
            "pending": get_pending_tasks(agent) if not agent else get_pending_tasks(),
            "recent": get_all_tasks(agent, limit=20),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/human-tasks/<task_id>/complete", methods=["POST"])
def api_complete_task(task_id):
    from finance_layer import complete_human_task
    ok = complete_human_task(task_id)
    if ok:
        return jsonify({"success": True})
    return jsonify({"error": "task not found"}), 404

@app.route("/api/wallet")
def api_wallet():
    try:
        from wallet import get_all_wallet_summary
        return jsonify(get_all_wallet_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/wallet/<name>")
def api_wallet_agent(name):
    try:
        from wallet import Wallet
        w = Wallet(name)
        return jsonify({
            "credits": w.credits,
            "crypto_address": w.crypto_address,
            "credit_history": w.credit_history[-20:],
            "report": w.get_wallet_report(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@app.route("/api/agent/<name>/tasks")
def api_agent_tasks(name):
    try:
        p = DATA_DIR / "memory" / name / "tasks.json"
        if not p.exists(): return jsonify([])
        tasks = json.loads(p.read_text())
        for t in tasks:
            t.setdefault("status", "pending")
        return jsonify(tasks)
    except: return jsonify([])

@app.route("/api/agent/<name>/analysis")
def api_agent_analysis(name):
    """Aggregated performance stats, memory stats, task stats, score history."""
    result = {
        "cycles": 0, "successes": 0, "failures": 0,
        "tasks_pending": 0, "tasks_completed": 0, "tasks_impossible": 0,
        "experiences": 0, "avg_score": 0,
        "scores": [], "revisions": [], "recent_outputs": [],
    }
    # Performance from instruction file
    inst = get_inst(name)
    if inst and "performance" in inst:
        p = inst["performance"]
        result["cycles"] = p.get("cycles_run", 0)
        result["successes"] = p.get("successful_outputs", 0)
        result["failures"] = p.get("failed_outputs", 0)
    # Task queue from memory JSON
    try:
        tp = DATA_DIR / "memory" / name / "tasks.json"
        if tp.exists():
            tasks = json.loads(tp.read_text())
            for t in tasks:
                s = t.get("status", "pending")
                if s == "completed": result["tasks_completed"] += 1
                elif s in ("impossible", "failed"): result["tasks_impossible"] += 1
                else: result["tasks_pending"] += 1
    except: pass
    # Experiences from memory JSON
    try:
        ep = DATA_DIR / "memory" / name / "experiences.json"
        if ep.exists():
            exps = json.loads(ep.read_text())
            result["experiences"] = len(exps)
            scores = [e.get("score", 0) for e in exps if isinstance(e.get("score"), (int, float))]
            if scores:
                result["avg_score"] = round(sum(scores) / len(scores), 1)
            result["recent_outputs"] = [
                {"action": e.get("action","")[:150], "success": e.get("success",False),
                 "timestamp": e.get("timestamp","")} for e in exps[-10:]
            ]
    except: pass
    # Scores from chat history role=critic (critique output contains score)
    try:
        store = get_store()
        chat = store.get_chat_history(name, 100, role="critic")
        for c in chat:
            out = c.get("output_response", "") or ""
            import re
            m = re.search(r'"score"\s*:\s*(\d+)', out)
            if m:
                result["scores"].append(int(m.group(1)))
    except: pass
    # Revisions from chat history role=supervisor
    try:
        sup = store.get_chat_history(name, 100, role="supervisor")
        result["revisions"] = [{"created_at": s.get("created_at",""), "input_len": len(s.get("input_prompt","") or "")} for s in sup[-10:]]
    except: pass
    return jsonify(result)

@app.route("/api/analysis/agents")
def api_analysis_agents():
    """Cross-agent comparison summary."""
    store = get_store()
    agents = store.get_all_agents()
    result = []
    for a in agents:
        name = a["agent_name"]
        # Load instruction performance
        inst = get_inst(name)
        perf = inst.get("performance", {}) if inst else {}
        # Load experiences count
        exp_count = 0
        try:
            ep = DATA_DIR / "memory" / name / "experiences.json"
            if ep.exists(): exp_count = len(json.loads(ep.read_text()))
        except: pass
        # Task stats
        pending = completed = impossible = 0
        try:
            tp = DATA_DIR / "memory" / name / "tasks.json"
            if tp.exists():
                for t in json.loads(tp.read_text()):
                    s = t.get("status","pending")
                    if s == "completed": completed += 1
                    elif s in ("impossible","failed"): impossible += 1
                    else: pending += 1
        except: pass
        # Chat by role
        from master.system_store import SystemStore
        s = SystemStore()
        crit_chat = s.get_chat_history(name, 1, role="critic")
        sup_chat = s.get_chat_history(name, 1, role="supervisor")
        result.append({
            "name": name,
            "status": a.get("status","?"),
            "cycles": perf.get("cycles_run", 0),
            "successes": perf.get("successful_outputs", 0),
            "failures": perf.get("failed_outputs", 0),
            "experiences": exp_count,
            "tasks_pending": pending,
            "tasks_completed": completed,
            "tasks_impossible": impossible,
            "has_critic": bool(crit_chat),
            "has_supervisor": bool(sup_chat),
            "last_critic": crit_chat[0]["created_at"] if crit_chat else "",
            "last_supervisor": sup_chat[0]["created_at"] if sup_chat else "",
        })
    return jsonify(result)

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

@app.route("/api/event-log")
def api_event_log():
    agent = request.args.get("agent", "")
    phase = request.args.get("phase", "")
    limit = request.args.get("limit", 100, type=int)
    try:
        from event_log import EventLog
        names = [agent] if agent else [a["agent_name"] for a in get_store().get_all_agents()]
        events = []
        for name in names:
            el = EventLog(name)
            for e in el.read(limit):
                if phase and e.get("phase") != phase:
                    continue
                events.append(e)
        events.sort(key=lambda e: e.get("ts", 0), reverse=True)
        return jsonify(events[:limit])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

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

# ── Startup initialization (runs on import, including gunicorn) ──

_startup_done = False

def _init_startup():
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    # Seed agents from instructions/ directory
    seed_agents()
    # Configurable agent count — default 1 (per user's redesign)
    max_agents = int(os.getenv("AGENT_COUNT", "1"))
    started = 0
    # Start all agent threads so they actually run, not just sit registered
    try:
        store = get_store()
        agents = store.get_all_agents()
        for a in agents[:max_agents] if max_agents > 0 else agents:
            name = a["agent_name"]
            if name not in _agent_threads or not _agent_threads[name].is_alive():
                logger.info(f"Auto-starting agent: {name}")
                result = start_agent_thread(name)
                started += 1
                if not result.get("success"):
                    logger.warning(f"Failed to auto-start {name}: {result.get('error', 'unknown')}")
        if started < len(agents):
            logger.info(f"Started {started}/{len(agents)} agents (AGENT_COUNT={max_agents})")
    except Exception as e:
        logger.error(f"auto-start agents failed: {e}")
    # Restore persistent data from Hugging Face Hub (if configured)
    try:
        from storage.hf_sync import pull_all, push_all
        pull_all()
        # Periodic sync every 60s — push agent memories & builds to HF
        def _sync_loop():
            while True:
                time.sleep(60)
                try:
                    push_all()
                except Exception:
                    pass
        t = threading.Thread(target=_sync_loop, daemon=True)
        t.start()
        logger.info("HF storage sync thread started (every 60s)")
    except Exception as e:
        logger.info("HF storage not configured: {}", e)

_init_startup()

# ── Main ──────────────────────────────────────────────────────────

def run_dashboard(port=8080, debug=False):
    print(f"Dashboard running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False, threaded=True)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_dashboard(port)
