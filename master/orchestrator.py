import time
import json
import threading
from typing import Optional
from loguru import logger

from log_system.central_log import CentralLog
from log_system.supervisor_filter import SupervisorFilter
from master.telegram_bot import TelegramBot
from master.system_store import SystemStore
from master.super_agent import SuperAgent
from master.agent_factory import AgentFactory
from master.resource_monitor import ResourceMonitor

class Orchestrator:
    """The Master — launches agents, monitors logs, runs SuperAgent.
    
    Orchestrator responsibilities:
    - Agent lifecycle management (start/stop/restart)
    - Central log + SupervisorFilter for human notification
    - SuperAgent background meta-agent for self-modification
    - SystemStore for agent registry, instructions, resources, budget
    - Telegram integration for human interface
    """

    def __init__(self):
        self.agents = {}
        self.threads = {}
        self.central = CentralLog()
        self.supervisor_filter = SupervisorFilter()
        self.telegram = TelegramBot()
        self.store = SystemStore()
        self.factory = AgentFactory()
        self.monitor = ResourceMonitor()
        self.super_agent = SuperAgent()
        self.super_agent.set_orchestrator(self)

        self.running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._super_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._last_notified_ids = set()

    def register_agent(self, name: str, agent_instance):
        """Register an agent with the orchestrator and SystemStore."""
        self.agents[name] = agent_instance

        # Ensure agent is in SystemStore registry
        existing = self.store.get_agent(name)
        if not existing:
            self.store.register_agent(
                name,
                agent_instance.__class__.__module__ + "." + agent_instance.__class__.__name__,
                income_methods=getattr(agent_instance, 'get_income_methods', lambda: "")()
            )
        self.store.update_agent_status(name, "registered")
        logger.info(f"Registered agent: {name}")

    def start_agent(self, name: str):
        """Launch an agent in a background thread."""
        if name not in self.agents:
            logger.error(f"Agent {name} not registered")
            return
        agent = self.agents[name]
        thread = threading.Thread(target=agent.run_loop, daemon=True,
                                  name=f"agent-{name}")
        thread.start()
        self.threads[name] = thread
        self.store.update_agent_status(name, "running")
        logger.info(f"Started agent: {name}")

    def start_all(self):
        """Start all registered agents + SuperAgent + monitors."""
        self.running = True
        for name in self.agents:
            self.start_agent(name)
        self._start_super_agent()
        self._start_monitor()
        self._start_telegram_poll()
        logger.info(f"All agents launched. SuperAgent active, max {SystemStore.MAX_AGENTS} agents")

    def stop_agent(self, name: str):
        if name in self.agents:
            self.agents[name].stop()
            self.store.update_agent_status(name, "stopped")
            logger.info(f"Stopped agent: {name}")

    def stop_all(self):
        self.running = False
        self.super_agent.stop()
        for name in self.agents:
            self.stop_agent(name)
        logger.info("All agents stopped")

    def _start_super_agent(self):
        """Launch SuperAgent in a background thread."""
        self._super_thread = threading.Thread(
            target=self.super_agent.run_loop, daemon=True,
            name="super-agent"
        )
        self._super_thread.start()
        logger.info("SuperAgent thread launched")

    def _start_monitor(self):
        """Background thread that checks central log and filters notifications."""
        def monitor_loop():
            logger.info("Monitor loop started")
            while self.running:
                try:
                    logs = self.central.get_logs_for_supervisor(limit=20)
                    new_logs = [l for l in logs if l["id"] not in self._last_notified_ids]
                    if new_logs:
                        to_notify = self.supervisor_filter.filter_logs(new_logs)
                        for entry in to_notify:
                            self.telegram.send_notification(entry)
                            self.central.mark_reviewed(
                                entry["id"],
                                reviewed_by="supervisor",
                                notes=entry.get("_filter_reason", "")
                            )
                            self._last_notified_ids.add(entry["id"])
                    time.sleep(15)
                except Exception as e:
                    logger.error(f"Monitor error: {e}")
                    time.sleep(30)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True,
                                                name="orchestrator-monitor")
        self._monitor_thread.start()

    def _start_telegram_poll(self):
        """Background thread that polls Telegram for human responses."""
        def poll_loop():
            offset = 0
            while self.running:
                try:
                    offset = self.telegram.poll_updates(offset)
                    time.sleep(3)
                except Exception as e:
                    logger.error(f"Telegram poll error: {e}")
                    time.sleep(10)

        self._poll_thread = threading.Thread(target=poll_loop, daemon=True,
                                              name="telegram-poll")
        self._poll_thread.start()

    def get_health_report(self) -> dict:
        """Get combined health from central log + resource monitor."""
        agent_health = self.central.get_agent_health()
        try:
            sys_health = self.monitor.get_system_health()
        except Exception:
            sys_health = {"resources": {}, "budget": {}}

        return {
            "total_agents": len(self.agents),
            "active_threads": sum(1 for t in self.threads.values() if t.is_alive()),
            "agent_health": agent_health,
            "unreviewed_ctas": len(self.central.get_unreviewed_ctas()),
            "system": sys_health,
        }

    def send_daily_report(self):
        """Generate and send daily summary to human."""
        summaries = []
        for name in self.agents:
            logs = self.central.get_recent_by_agent(name, limit=100)
            actions = [l for l in logs if l["level"] == 25]
            revenues = [l for l in logs if l["level"] == 45]
            errors = [l for l in logs if l["level"] >= 40]
            summaries.append({
                "agent_name": name,
                "actions_taken": len(actions),
                "revenue": sum(json.loads(r.get("data", "{}") or "{}").get("amount", 0) for r in revenues),
                "errors": len(errors),
            })
        self.telegram.send_daily_summary(summaries)

    def run(self):
        """Main orchestrator entry point. Starts everything and self-heals."""
        logger.info("Orchestrator starting...")
        self.start_all()
        consecutive_failures = {}
        try:
            while self.running:
                time.sleep(30)
                health = self.get_health_report()
                active = health.get('active_threads', 0)
                total = health.get('total_agents', 0)

                # Self-heal: restart dead agent threads
                for name, thread in list(self.threads.items()):
                    if not thread.is_alive() and name in self.agents:
                        agent = self.agents[name]
                        if agent.running:
                            logger.warning(f"Agent [{name}] thread dead — restarting")
                            new_thread = threading.Thread(target=agent.run_loop, daemon=True,
                                                          name=f"agent-{name}")
                            new_thread.start()
                            self.threads[name] = new_thread
                            self.store.update_agent_status(name, "running")
                            consecutive_failures[name] = consecutive_failures.get(name, 0) + 1
                            if consecutive_failures[name] > 5:
                                logger.error(f"Agent [{name}] crashed 5+ times — stopping")
                                self.stop_agent(name)
                        else:
                            # Agent finished normally (e.g. max cycles)
                            self.store.update_agent_status(name, "idle")

                # Restart super agent if dead
                if self._super_thread and not self._super_thread.is_alive():
                    logger.warning("SuperAgent thread dead — restarting")
                    self._start_super_agent()

                logger.info(f"Health: {active}/{total} agents | "
                           f"{health.get('system', {}).get('agents', {}).get('available_slots', '?')} slots free")
        except KeyboardInterrupt:
            logger.info("Orchestrator stopping...")
        finally:
            self.stop_all()
