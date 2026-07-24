#!/bin/bash
set -e

echo "=== Super Agent Startup ==="

# Initialize the database
python main.py --init-db 2>/dev/null || echo "DB already initialized"

# Start all agents in background
echo "Starting agents in background..."
python main.py --deploy &
AGENT_PID=$!
echo "Agent system PID: $AGENT_PID"

# Start dashboard with gunicorn
echo "Starting dashboard..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 4 dashboard_app:app --timeout 120
