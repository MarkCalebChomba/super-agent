#!/bin/bash
set -e
echo "=== SUPER AGENT STARTING ==="
echo "[1/3] Initializing database..."
python -c "from db.init_db import init_database; from config.settings import load_config; init_database(load_config().get('data_dir','data')); print('DB OK')" 2>&1
echo "[2/3] Starting agents in background..."
python -c "
import threading, time, sys
def run():
    try:
        from master.orchestrator import Orchestrator
        o = Orchestrator()
        print(f'Agents: {len(o.agents)} loaded')
        o.run()
    except Exception as e:
        print(f'Agent error: {e}', file=sys.stderr)
t = threading.Thread(target=run, daemon=True)
t.start()
print('Agent thread started')
time.sleep(2)
print('Agents should be running now')
" 2>&1 &
echo "[3/3] Starting dashboard server..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - dashboard_app:app
