#!/bin/bash
set -e
echo "ENTRYPOINT ACTIVE $(date)"
>&2 echo "ENTRYPOINT ACTIVE STDERR $(date)"

echo "Init DB..."
python -u -c "import sys; sys.stdout.write('DB INIT OK\n'); sys.stdout.flush()" 2>&1

echo "Starting agents in background..."
python -u /app/start_agents.py &
APID=$!
echo "Agent PID: $APID"

echo "Execing gunicorn..."
exec "$@"
