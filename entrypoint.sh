#!/bin/bash
set -e
echo "=== SUPER AGENT 24/7 ==="
echo "[1] Init DB..."
python -c "from db.init_db import init_database; from config.settings import load_config; init_database(load_config().get('data_dir','data'))" 2>&1
echo "[2] Start agents in background..."
python -u -c "
import sys, threading, time
sys.stdout.write('[AGENT] Loading agents...\n')
sys.stdout.flush()
try:
    from master.orchestrator import Orchestrator
    orch = Orchestrator()
    sys.stdout.write(f'[AGENT] {len(orch.agents)} agents loaded\n')
    sys.stdout.flush()
    # Monitor agents in a thread
    def _run():
        orch.start_all()
        orch.run()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(5)
    sys.stdout.write('[AGENT] Agents running\n')
    sys.stdout.flush()
except Exception as e:
    sys.stdout.write(f'[AGENT] FAILED: {e}\n')
    sys.stdout.flush()
" 2>&1 &
echo "[3] Starting dashboard server..."
exec "$@"
