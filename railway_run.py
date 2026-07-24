"""Railway entrypoint: init DB, start agents, then serve dashboard."""
import os, sys, time, subprocess

os.environ["DEPLOY"] = "true"

sys.stdout.write("[RAILWAY] === Super Agent 24/7 ===\n")
sys.stdout.write(f"[RAILWAY] Python: {sys.version}\n")
sys.stdout.flush()

try:
    from db.init_db import init_database
    from config.settings import load_config
    cfg = load_config()
    init_database(cfg.get("data_dir", "data"))
    sys.stdout.write("[RAILWAY] DB initialized\n")
    sys.stdout.flush()
except Exception as e:
    sys.stdout.write(f"[RAILWAY] DB init: {e}\n")
    sys.stdout.flush()

pid = os.fork()
if pid == 0:
    import signal
    signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
    signal.signal(signal.SIGINT, lambda *a: os._exit(0))
    sys.stdout.write("[RAILWAY] Agent child process starting...\n")
    sys.stdout.flush()
    try:
        from master.orchestrator import Orchestrator
        orch = Orchestrator()
        sys.stdout.write(f"[RAILWAY] {len(orch.agents)} agents loaded\n")
        sys.stdout.flush()
        orch.run()
    except Exception as e:
        sys.stdout.write(f"[RAILWAY] Agent error (will retry): {e}\n")
        sys.stdout.flush()
        while True:
            time.sleep(60)
    os._exit(0)
else:
    sys.stdout.write(f"[RAILWAY] Agent PID: {pid}, starting gunicorn...\n")
    sys.stdout.flush()
    time.sleep(3)
    proc = subprocess.Popen([
        "gunicorn",
        "--bind", "0.0.0.0:8080",
        "--workers", "2", "--threads", "4",
        "--timeout", "120",
        "--access-logfile", "-",
        "--error-logfile", "-",
        "dashboard_app:app",
    ])
    proc.wait()
