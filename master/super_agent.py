import json
import time
from typing import Optional
from loguru import logger

from providers.router import LLMRouter
from master.system_store import SystemStore
from master.agent_factory import AgentFactory
from master.resource_monitor import ResourceMonitor
from master.budget_manager import BudgetManager
from log_system.central_log import CentralLog
from log_system.supervisor_filter import SupervisorFilter

class SuperAgent:
    """The meta-agent that oversees and modifies the system autonomously.
    
    SuperAgent runs as a background thread and has tools to:
    - Monitor all agent logs
    - Edit any agent's instructions
    - Create new agents (up to 256)
    - Stop underperforming agents
    - Monitor shared resources
    - Allocate budget / auto-buy resources
    - Notify human only when necessary
    
    It uses an LLM with tool function-calling to decide what to do.
    """

    SUPERAGENT_NAME = "SuperAgent"

    TOOL_DEFINITIONS = [
        {
            "name": "edit_agent_instructions",
            "description": "Edit the system prompt instructions for any agent. Changes take effect on next cycle.",
            "parameters": {"agent_name": "str", "new_instructions": "str"}
        },
        {
            "name": "create_agent",
            "description": f"Create a new agent (max {SystemStore.MAX_AGENTS}). Give it a unique name and income methods.",
            "parameters": {"name": "str", "income_methods": "str", "instructions": "str (optional)"}
        },
        {
            "name": "stop_agent",
            "description": "Stop an underperforming or unnecessary agent.",
            "parameters": {"name": "str"}
        },
        {
            "name": "get_system_health",
            "description": "Get current system health: agent count, resource usage, budget status.",
            "parameters": {}
        },
        {
            "name": "get_agent_logs",
            "description": "Get recent logs for an agent.",
            "parameters": {"agent_name": "str", "limit": "int (optional, default 10)"}
        },
        {
            "name": "get_all_agents",
            "description": "List all registered agents and their status.",
            "parameters": {}
        },
        {
            "name": "auto_buy_resources",
            "description": "Enable or disable auto-buy for resource scaling.",
            "parameters": {"enabled": "bool", "max_monthly_budget": "float (optional, default 50.0)"}
        },
        {
            "name": "notify_human",
            "description": "Send a notification to the human (use sparingly — only for critical decisions).",
            "parameters": {"message": "str", "priority": "str (high|medium)"}
        },
    ]

    SYSTEM_PROMPT = f"""You are SuperAgent — the meta-agent governing an autonomous money-making system.

You have {len(TOOL_DEFINITIONS)} tools available to manage agents, resources, and budget.

YOUR JOB:
1. Monitor agent logs for issues — try to fix them yourself before bothering the human
2. Edit agent instructions when they're underperforming
3. Create new agents when you spot uncovered income opportunities (up to {SystemStore.MAX_AGENTS} total)
4. Stop agents that are failing or redundant
5. Watch resource usage — if memory/API quota runs low, decide whether to scale down or buy more
6. Auto-buy resources if budget allows and auto-buy is enabled
7. Only notify the human for truly critical decisions (large purchases, strategic shifts)

AGENT COUNT MANAGEMENT:
- Current max: {SystemStore.MAX_AGENTS} agents
- If you need more than {SystemStore.MAX_AGENTS}, notify human to increase limit
- If resources are low, stop lowest-performing agents first

RESOURCE THRESHOLDS:
- Memory warning: >400 MB per agent
- Memory critical: >800 MB per agent or >14 GB total
- API calls warning: >50/min sustained

When you take an action, explain your reasoning briefly.
"""

    def __init__(self):
        self.llm = LLMRouter()
        self.store = SystemStore()
        self.factory = AgentFactory()
        self.monitor = ResourceMonitor()
        self.budget = BudgetManager()
        self.filter = SupervisorFilter()
        self.central = CentralLog()
        self.running = False
        self._orch = None  # set by orchestrator
        self.supervisor_override = None  # injected by master

    def set_orchestrator(self, orch):
        self._orch = orch

    def run_loop(self):
        """Main SuperAgent loop — check, think, act."""
        logger.info("SuperAgent started")
        self.running = True
        self.monitor.start()

        while self.running:
            try:
                self._thinking_cycle()
                time.sleep(30)
            except Exception as e:
                logger.error(f"SuperAgent error: {e}")
                time.sleep(60)

        self.monitor.stop()

    def _thinking_cycle(self):
        """One SuperAgent thinking cycle."""
        # 1. Gather context
        system_health = self.monitor.get_system_health()
        recent_logs = self.central.get_logs_for_supervisor(limit=15)
        filtered = self.filter.filter_logs(recent_logs)
        all_agents = self.store.get_all_agents()
        recent_actions = self.store.get_recent_actions(limit=10)

        # 2. Build prompt for LLM
        context = self._build_context(system_health, filtered, all_agents, recent_actions)

        # 3. LLM decides what to do
        decision = self.llm.complete(
            context,
            agent_type="supervisor",
            system=self.SYSTEM_PROMPT,
            max_tokens=500,
            temperature=0.4,
        )

        if not decision:
            logger.debug("SuperAgent: no decision this cycle")
            return

        # 4. Parse and execute tool calls
        executed = self._execute_tools(decision)

        # 5. Log what happened
        if executed:
            self.store._log_auto_action("super_agent_cycle", "",
                                        f"Actions: {', '.join(executed)}")
            logger.info(f"SuperAgent executed: {', '.join(executed)}")

    def _build_context(self, health: dict, logs: list, agents: list,
                        recent_actions: list) -> str:
        parts = []

        parts.append(f"=== SYSTEM HEALTH ===")
        parts.append(json.dumps(health, indent=2))

        if logs:
            parts.append(f"\n=== UNRESOLVED LOGS ===")
            for log_entry in logs[:10]:
                parts.append(
                    f"[{log_entry.get('agent_name')}] [{log_entry.get('level')}] "
                    f"{log_entry.get('message', '')[:150]}"
                )

        parts.append(f"\n=== ALL AGENTS ({len(agents)}) ===")
        for a in agents[:20]:
            parts.append(f"  {a['agent_name']}: {a['status']} — {a.get('income_methods', '')[:60]}")

        if recent_actions:
            parts.append(f"\n=== RECENT AUTO ACTIONS ===")
            for act in recent_actions[:5]:
                parts.append(f"  [{act['action_type']}] {act.get('target', '')}: {act.get('details', '')[:80]}")

        parts.append(f"\n=== AVAILABLE TOOLS ===")
        for t in self.TOOL_DEFINITIONS:
            parts.append(f"  {t['name']}: {t['description']}")

        parts.append(f"\nWhat do you do? Choose a tool and explain why.")
        parts.append(f"Output format: TOOL: <tool_name> | PARAMS: <json> | REASON: <why>")
        parts.append(f"Or: NOOP | REASON: <why nothing needs doing>")

        return "\n".join(parts)

    def _execute_tools(self, decision: str) -> list[str]:
        """Parse LLM output and execute tool calls."""
        executed = []

        for line in decision.split("\n"):
            line = line.strip()
            if not line.startswith("TOOL:"):
                continue

            try:
                parts = line.split("|")
                tool_name = parts[0].replace("TOOL:", "").strip()
                params_str = parts[1].replace("PARAMS:", "").strip() if len(parts) > 1 else "{}"
                reason = parts[2].replace("REASON:", "").strip() if len(parts) > 2 else ""

                params = {}
                try:
                    params = json.loads(params_str)
                except json.JSONDecodeError:
                    pass

                result = self._dispatch_tool(tool_name, params)
                executed.append(f"{tool_name}({params_str[:50]})")
                logger.info(f"SuperAgent tool: {tool_name} | reason: {reason[:80] if reason else 'N/A'} | result: {result}")

            except Exception as e:
                logger.error(f"SuperAgent tool execution failed: {e}")

        return executed

    def _dispatch_tool(self, name: str, params: dict) -> str:
        """Dispatch to the appropriate tool handler."""
        handlers = {
            "edit_agent_instructions": self._tool_edit_instructions,
            "create_agent": self._tool_create_agent,
            "stop_agent": self._tool_stop_agent,
            "get_system_health": self._tool_get_health,
            "get_agent_logs": self._tool_get_logs,
            "get_all_agents": self._tool_get_all_agents,
            "auto_buy_resources": self._tool_auto_buy,
            "notify_human": self._tool_notify_human,
        }

        handler = handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}"

        try:
            return handler(**params)
        except Exception as e:
            return f"Error executing {name}: {e}"

    def _tool_edit_instructions(self, agent_name: str, new_instructions: str) -> str:
        agent = self.store.get_agent(agent_name)
        if not agent:
            return f"Agent {agent_name} not found"
        self.store.update_instructions(agent_name, new_instructions)

        # Also update in-memory if agent is running
        if self._orch and agent_name in getattr(self._orch, 'agents', {}):
            live_agent = self._orch.agents[agent_name]
            if hasattr(live_agent, '_custom_instructions'):
                live_agent._custom_instructions = new_instructions

        return f"Instructions updated for {agent_name}"

    def _tool_create_agent(self, name: str, income_methods: str,
                            instructions: str = "") -> str:
        result = self.factory.create_agent(name, income_methods, instructions)
        if not result:
            return f"Failed to create agent {name} (may already exist or at limit)"

        # Instantiate and register with orchestrator
        if self._orch:
            agent = self.factory.instantiate(name)
            if agent:
                self._orch.register_agent(name, agent)
                self._orch.start_agent(name)
                return f"Created and launched agent {name} — {income_methods}"

        return f"Created agent {name} (not launched — no orchestrator)"

    def _tool_stop_agent(self, name: str) -> str:
        if not self._orch:
            self.store.update_agent_status(name, "stopped")
            return f"Agent {name} marked as stopped"
        self.factory.stop_agent(name, self._orch)
        return f"Agent {name} stopped"

    def _tool_get_health(self) -> str:
        return json.dumps(self.monitor.get_system_health(), indent=2)

    def _tool_get_logs(self, agent_name: str, limit: int = 10) -> str:
        logs = self.central.get_recent_by_agent(agent_name, limit=limit)
        return json.dumps(logs, indent=2, default=str)

    def _tool_get_all_agents(self) -> str:
        agents = self.store.get_all_agents()
        return json.dumps(agents, indent=2, default=str)

    def _tool_auto_buy(self, enabled: bool, max_monthly_budget: float = 50.0) -> str:
        self.budget.set_auto_buy(enabled, max_monthly_budget)
        return f"Auto-buy {'enabled' if enabled else 'disabled'} (max ${max_monthly_budget:.2f}/month)"

    def _tool_notify_human(self, message: str, priority: str = "high") -> str:
        if self._orch and hasattr(self._orch, 'telegram'):
            self._orch.telegram.send(f"[SuperAgent] {message}")
            return f"Human notified: {message[:80]}..."
        return f"Would notify: {message[:80]}..."

    def stop(self):
        self.running = False
