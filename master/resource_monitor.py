import os
import threading
from typing import Optional
from loguru import logger
from master.system_store import SystemStore

class ResourceMonitor:
    """Tracks per-agent and shared resource usage.
    
    Monitored resources:
    - Memory (per-agent, total)
    - Token consumption (per-agent, total)
    - API call rates
    - Agent count vs limit
    
    When resources run low, notifies SuperAgent which can:
    - Scale down low-value agents
    - Buy more resources if budget available
    """

    MEMORY_WARN_MB = 400      # warn if any agent > 400 MB
    MEMORY_CRITICAL_MB = 800  # critical threshold
    TOTAL_MEMORY_LIMIT_MB = 14000  # 14 GB (~16 GB HF Spaces with overhead)
    API_CALL_RATE_WARN = 50   # API calls/min warning
    TOKEN_WARN = 50000        # token warning per hour

    def __init__(self, check_interval: int = 60):
        self.store = SystemStore()
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True,
                                        name="resource-monitor")
        self._thread.start()
        logger.info("Resource monitor started")

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        while self._running:
            try:
                self.check_all()
                import time
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Resource monitor error: {e}")
                import time
                time.sleep(self.check_interval * 2)

    def check_all(self) -> dict:
        """Run all resource checks. Returns alerts dict."""
        alerts = {"memory": [], "tokens": [], "api": [], "agents": []}

        # 1. Agent count
        total = self.store.count_total()
        active = self.store.count_active()
        if total >= SystemStore.MAX_AGENTS * 0.9:
            alerts["agents"].append(
                f"Agent count at {total}/{SystemStore.MAX_AGENTS} ({(total/SystemStore.MAX_AGENTS)*100:.0f}%)"
            )

        # 2. Memory per agent
        high_mem = self.store.get_high_resource_agents(self.MEMORY_WARN_MB)
        for agent in high_mem:
            level = "critical" if agent["avg_memory"] > self.MEMORY_CRITICAL_MB else "warning"
            alerts["memory"].append(
                f"[{level}] {agent['agent_name']}: {agent['avg_memory']:.0f} MB"
            )

        # 3. Total memory estimate
        summary = self.store.get_resource_summary()
        if summary.get("total_memory", 0) > self.TOTAL_MEMORY_LIMIT_MB:
            alerts["memory"].append(
                f"[critical] Total memory {summary['total_memory']:.0f} MB exceeds limit"
            )

        # 4. API call rate
        if summary.get("total_api_calls", 0) > self.API_CALL_RATE_WARN * 60 * 24:
            alerts["api"].append(
                f"High API usage: {summary['total_api_calls']} calls/24h"
            )

        # 5. Token usage
        if summary.get("total_tokens", 0) > self.TOKEN_WARN * 24:
            alerts["tokens"].append(
                f"High token usage: {summary['total_tokens']} tokens/24h"
            )

        for level_key in alerts:
            for alert in alerts[level_key]:
                level = "critical" if "critical" in alert else "warning"
                log_fn = logger.warning if level == "warning" else logger.error
                log_fn(f"Resource alert: {alert}")

        return alerts

    def get_agent_memory_usage(self, pid: int = None) -> float:
        """Estimate memory usage of current process in MB."""
        try:
            import psutil
            process = psutil.Process(pid or os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0

    def record_agent_usage(self, agent_name: str, tokens: int = 0,
                            api_calls: int = 0, cycles: int = 0):
        memory = self.get_agent_memory_usage()
        self.store.record_resource_use(
            agent_name,
            memory_mb=memory / max(self.store.count_active(), 1),  # rough split
            tokens=tokens,
            api_calls=api_calls,
            cycles=cycles
        )

    def get_system_health(self) -> dict:
        summary = self.store.get_resource_summary()
        total = self.store.count_total()
        active = self.store.count_active()
        budget = self.store.get_budget()

        return {
            "agents": {"total": total, "active": active, "max": SystemStore.MAX_AGENTS,
                       "available_slots": SystemStore.MAX_AGENTS - total},
            "resources": {
                "total_memory_mb": summary.get("total_memory", 0),
                "total_tokens_24h": summary.get("total_tokens", 0),
                "total_api_calls_24h": summary.get("total_api_calls", 0),
            },
            "budget": {
                "total_revenue": budget.get("total_revenue", 0),
                "total_expenses": budget.get("total_expenses", 0),
                "auto_buy_enabled": bool(budget.get("auto_buy_enabled")),
                "monthly_remaining": budget.get("max_monthly_budget", 50) - budget.get("monthly_spent", 0),
            },
            "alerts": self.check_all(),
        }
