"""Railway entrypoint: init DB, start agents, then exec gunicorn."""
import os, sys, time

os.environ["DEPLOY"] = "true"
os.environ["RAILWAY_RUN"] = "1"

print("[RAILWAY] Super Agent startup...", flush=True)

try:
    from db.init_db import init_database
    from config.settings import load_config
    cfg = load_config()
    init_database(cfg.get("data_dir", "data"))
    print("[RAILWAY] DB initialized", flush=True)
except Exception as e:
    print(f"[RAILWAY] DB init: {e}", flush=True)

# Fork: child runs agents, parent exec's gunicorn
pid = os.fork()
if pid == 0:
    # Child process: run agents forever
    import signal
    signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
    signal.signal(signal.SIGINT, lambda *a: os._exit(0))
    try:
        from master.orchestrator import Orchestrator
        orch = Orchestrator()
        print(f"[RAILWAY] Loaded {len(orch.agents)} agents, running...", flush=True)
        orch.run()
    except Exception as e:
        print(f"[RAILWAY] Agent error: {e}", flush=True)
        while True:
            time.sleep(60)
    os._exit(0)
else:
    # Parent process: start dashboard
    time.sleep(3)
    print("[RAILWAY] Starting gunicorn dashboard...", flush=True)
    os.execvp("gunicorn", [
        "gunicorn",
        "--bind", "0.0.0.0:8080",
        "--workers", "2",
        "--threads", "4",
        "--timeout", "120",
        "--access-logfile", "-",
        "--error-logfile", "-",
        "dashboard_app:app",
    ])
