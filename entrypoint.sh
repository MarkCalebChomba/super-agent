#!/bin/bash
set -e
echo "ENTRYPOINT ACTIVE $(date)"

# Init DB
python -u -c "
import sys
sys.stdout.write('Initializing DB...\n')
sys.stdout.flush()
from db.init_db import init_database
from config.settings import load_config
init_database(load_config().get('data_dir', 'data'))
sys.stdout.write('DB ready\n')
sys.stdout.flush()
"

# Start agents in background
echo "Starting agents in background..."
python -u /app/start_agents.py &
echo "Agent PID: $!"

# Start gunicorn (hardcode port, Railway env var may not expand)
echo "Starting gunicorn on 0.0.0.0:8080..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile - dashboard_app:app
