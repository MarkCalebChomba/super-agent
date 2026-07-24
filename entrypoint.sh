#!/bin/bash
set -e
echo "=== SUPER AGENT 24/7 ==="
echo "[1] Initializing DB..."
python -c "
import sys
sys.stdout.write('Running DB init...\n')
sys.stdout.flush()
from db.init_db import init_database
from config.settings import load_config
init_database(load_config().get('data_dir','data'))
sys.stdout.write('DB OK\n')
sys.stdout.flush()
" 2>&1
echo "[2] Starting agents in background..."
python -c "
import sys, threading, time
def run():
    try:
        from master.orchestrator import Orchestrator
        o = Orchestrator()
        sys.stdout.write(f'Agents: {len(o.agents)}\n')
        sys.stdout.flush()
        o.run()
    except Exception as e:
        sys.stderr.write(f'Agent failed: {e}\n')
        sys.stderr.flush()
        time.sleep(10)
t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(2)
sys.stdout.write('Agents running\n')
" &
echo "[3] Starting dashboard..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - dashboard_app:app
