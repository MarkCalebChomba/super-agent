"""Run agents + dashboard together in Railway container."""
import os, sys, threading, time

os.environ.setdefault("DEPLOY", "true")

print("=== Super Agent: Initializing ===")

from db.init_db import init_database
from config.settings import load_config

config = load_config()
print("Initializing databases...")
init_database(config.get("data_dir", "data"))

def run_agents():
    """Start all agents in a background thread."""
    print("Starting all agents...")
    try:
        from master.orchestrator import Orchestrator
        orch = Orchestrator()
        orch.run()
    except Exception as e:
        print(f"Agent runtime error: {e}")
        # Keep thread alive
        while True:
            time.sleep(60)

agent_thread = threading.Thread(target=run_agents, daemon=True)
agent_thread.start()
print("Agents running in background")

time.sleep(2)

print("Starting dashboard server...")
from dashboard_app import app

if __name__ == "__main__":
    import gunicorn.app.base

    class StandaloneApp(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                self.cfg.set(key, value)

        def load(self):
            return self.application

    options = {
        "bind": "0.0.0.0:8080",
        "workers": 2,
        "threads": 4,
        "timeout": 120,
        "loglevel": "info",
    }
    print(f"Dashboard: http://0.0.0.0:8080")
    StandaloneApp(app, options).run()
