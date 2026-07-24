"""Run agents + dashboard together in Railway container (24/7 mode)."""
import os, sys, threading, time, logging

os.environ.setdefault("DEPLOY", "true")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("superagent")

log.info("=== Super Agent: Initializing (24/7 mode) ===")

try:
    from db.init_db import init_database
    from config.settings import load_config
    config = load_config()
    log.info("Initializing databases...")
    init_database(config.get("data_dir", "data"))
    log.info("Database ready")
except Exception as e:
    log.error(f"DB init failed: {e}")
    # Continue anyway - dashboard can still serve

def run_agents_forever():
    """Start agents and keep them running 24/7."""
    log.info("Starting agent orchestrator...")
    max_retries = 100
    retries = 0
    while retries < max_retries:
        try:
            from master.orchestrator import Orchestrator
            orch = Orchestrator()
            log.info(f"Orchestrator created with {len(orch.agents)} agents")
            orch.run()
            log.warning("Orchestrator stopped unexpectedly")
        except Exception as e:
            retries += 1
            log.error(f"Agent orchestrator error (attempt {retries}/{max_retries}): {e}")
            time.sleep(10)
    log.error("Agent orchestrator failed after max retries")

agent_thread = threading.Thread(target=run_agents_forever, daemon=True, name="agent-runner")
agent_thread.start()
log.info("Agent thread started in background")

time.sleep(2)

log.info("Starting gunicorn dashboard server on port 8080...")

from dashboard_app import app

if __name__ == "__main__":
    import gunicorn.app.base
    gunicorn.SERVER_SOFTWARE = "super-agent"

    class AgentGunicorn(gunicorn.app.base.BaseApplication):
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
        "accesslog": "-",
        "errorlog": "-",
        "capture_output": True,
    }
    log.info("Dashboard starting...")
    try:
        AgentGunicorn(app, options).run()
    except Exception as e:
        log.error(f"Gunicorn error: {e}")
        # Keep container alive
        while True:
            time.sleep(60)
