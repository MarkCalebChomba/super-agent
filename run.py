"""Start agents then serve dashboard (24/7)."""
import os, sys, subprocess, time

os.environ["DEPLOY"] = "true"

sys.stdout.write("[RAILWAY] Starting Super Agent...\n")
sys.stdout.flush()

# Init DB
sys.stdout.write("[RAILWAY] Initializing database...\n")
sys.stdout.flush()
try:
    from db.init_db import init_database
    from config.settings import load_config
    init_database(load_config().get("data_dir", "data"))
    sys.stdout.write("[RAILWAY] Database ready\n")
    sys.stdout.flush()
except Exception as e:
    sys.stdout.write(f"[RAILWAY] DB init warning: {e}\n")
    sys.stdout.flush()

# Write agent startup script to file
with open("/tmp/start_agents.py", "w") as f:
    f.write("""import sys, os
os.environ['DEPLOY'] = 'true'
sys.stdout.write('[AGENT] Starting...\\n')
sys.stdout.flush()
try:
    from master.orchestrator import Orchestrator
    from db.init_db import init_database
    from config.settings import load_config
    init_database(load_config().get('data_dir', 'data'))
    orch = Orchestrator()
    sys.stdout.write(f'[AGENT] {len(orch.agents)} agents loaded, running...\\n')
    sys.stdout.flush()
    orch.run()
except Exception as e:
    sys.stderr.write(f'[AGENT] FAILED: {e}\\n')
    sys.stderr.flush()
    import traceback
    traceback.print_exc()
""")

# Start agents in background
sys.stdout.write("[RAILWAY] Launching agent process...\n")
sys.stdout.flush()
agent_proc = subprocess.Popen(
    [sys.executable, "-u", "/tmp/start_agents.py"],
    stdout=open("/tmp/agent_stdout.log", "w"),
    stderr=subprocess.STDOUT,
)
sys.stdout.write(f"[RAILWAY] Agent PID: {agent_proc.pid}\n")
sys.stdout.flush()
time.sleep(3)

# Read back agent startup messages
try:
    with open("/tmp/agent_stdout.log") as f:
        agent_out = f.read()
        if agent_out:
            sys.stdout.write(f"[RAILWAY] Agent output: {agent_out.strip()}\n")
            sys.stdout.flush()
except:
    pass

# Start dashboard
sys.stdout.write("[RAILWAY] Starting gunicorn...\n")
sys.stdout.flush()
proc = subprocess.Popen([
    "gunicorn",
    "--bind", "0.0.0.0:8080",
    "--workers", "2", "--threads", "4",
    "--timeout", "120",
    "--access-logfile", "-",
    "--error-logfile", "-",
    "dashboard_app:app",
])
sys.stdout.write(f"[RAILWAY] Gunicorn PID: {proc.pid}\n")
sys.stdout.flush()
proc.wait()
