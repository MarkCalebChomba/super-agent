import importlib
import types
from typing import Optional, Type
from loguru import logger

from agents.base_agent import BaseAgent
from master.system_store import SystemStore
from providers.router import LLMRouter

class DynamicAgentError(Exception):
    """Raised when dynamic agent creation fails."""

class DynamicAgentWrapper(BaseAgent):
    """Generic wrapper agent created dynamically by SuperAgent.
    
    The SuperAgent defines the income methods, instructions, and behavior
    at creation time. All dynamic agents share this wrapper class but
    differ in their instructions/methods stored in SystemStore.
    """

    def __init__(self, agent_name: str, income_methods: str = "",
                 instructions: str = "", identity: dict = None,
                 memory_dir: str = "data/memory", log_dir: str = "data/logs"):
        super().__init__(agent_name, identity, memory_dir, log_dir)
        self._income_methods = income_methods
        self._custom_instructions = instructions
        self.llm = LLMRouter()

    def get_income_methods(self) -> str:
        return self._income_methods

    def build_system_prompt(self) -> str:
        """Override to inject custom instructions from SuperAgent."""
        base = super().build_system_prompt()
        if self._custom_instructions:
            store = SystemStore()
            custom = store.get_agent_instructions(self.name)
            if custom:
                base += f"\n\n[CUSTOM INSTRUCTIONS FROM SUPERAGENT]\n{custom}"
        return base

    def build(self) -> dict:
        store = SystemStore()
        custom = store.get_agent_instructions(self.name)
        instructions = custom or self._custom_instructions or "Explore and execute your income methods."
        ts = __import__("time").strftime("%Y%m%d_%H%M%S")

        prompt = (
            f"Your income methods: {self._income_methods}\n\n"
            f"Instructions: {instructions}\n\n"
            f"Generate a practical tool or asset for your income method. "
            f"Output a simple Python script, HTML page, or content draft. "
            f"Be specific and produce real working code or content."
        )
        output = self.llm.complete(prompt, agent_type=self.name.split("_")[0] if "_" in self.name else "general",
                                   system=self.build_system_prompt(),
                                   max_tokens=2048)
        if output:
            import os
            filename = f"build_{ts}.py"
            filepath = os.path.join(self.build_dir, filename)
            with open(filepath, "w") as f:
                f.write(output)
            return {"file": filepath, "summary": f"Dynamic build: {output[:80]}...", "revenue": 0.0,
                    "method": self._income_methods[:50]}
        return None


class AgentFactory:
    """Creates, registers, and launches new agents at runtime.
    
    Called by SuperAgent when it decides a new income stream needs coverage.
    """

    WRAPPER_PATH = "master.agent_factory.DynamicAgentWrapper"

    def __init__(self):
        self.store = SystemStore()

    def create_agent(self, name: str, income_methods: str,
                     instructions: str = "", identity: dict = None) -> Optional[str]:
        """Create a new agent and register it. Returns agent name or None."""
        if self.store.count_total() >= SystemStore.MAX_AGENTS:
            logger.warning(f"Cannot create {name}: at max {SystemStore.MAX_AGENTS} agents")
            return None

        if self.store.get_agent(name):
            logger.warning(f"Agent {name} already exists")
            return None

        # Generate unique name if needed (SuperAgent should provide unique names)
        success = self.store.register_agent(
            name, self.WRAPPER_PATH,
            income_methods=income_methods,
            instructions=instructions
        )
        if not success:
            return None

        logger.info(f"Dynamic agent created: {name} — {income_methods}")
        self.store._log_auto_action("create_agent", name, income_methods)
        return name

    def instantiate(self, name: str, identity: dict = None) -> Optional[BaseAgent]:
        """Create an in-memory agent instance from registry entry."""
        entry = self.store.get_agent(name)
        if not entry:
            logger.error(f"Agent {name} not found in registry")
            return None

        agent = DynamicAgentWrapper(
            agent_name=name,
            income_methods=entry.get("income_methods", ""),
            instructions=entry.get("instructions", ""),
            identity=identity,
        )
        return agent

    def generate_agent_code_llm(self, name: str, income_methods: str) -> str:
        """Use LLM to generate a dedicated agent class file (for persistent agents)."""
        llm = LLMRouter()
        code = llm.complete(
            f"Generate a Python class for an agent named '{name}' that generates income via: {income_methods}.\n\n"
            f"The class must inherit from BaseAgent (from agents.base_agent).\n"
            f"Implement get_income_methods(), think(context), act(decision).\n"
            f"Use tools from tools.content_gen, tools.social_tools, tools.browser_automation, etc.\n"
            f"Make it concrete and action-oriented. Output ONLY the Python code, no markdown.",
            agent_type="general",
            system="You are an AI agent generator. Write production-quality Python agent classes."
        )
        return code or ""

    def save_agent_class(self, name: str, code: str) -> bool:
        """Save a generated agent class to disk."""
        from pathlib import Path
        agents_dir = Path("agents")
        agents_dir.mkdir(exist_ok=True)
        filepath = agents_dir / f"agent_dynamic_{name.lower().replace(' ', '_')}.py"

        with open(filepath, "w") as f:
            f.write(f"# Auto-generated by SuperAgent\n# {name}\n\n")
            f.write(code)

        logger.info(f"Agent class saved: {filepath}")
        self.store._log_auto_action("save_agent_class", name, str(filepath))
        return True

    def list_available_slots(self) -> int:
        return SystemStore.MAX_AGENTS - self.store.count_total()

    def stop_agent(self, name: str, orch):
        """Stop and remove an agent."""
        if hasattr(orch, 'stop_agent'):
            orch.stop_agent(name)
        self.store.update_agent_status(name, "stopped")
        logger.info(f"Agent {name} stopped by SuperAgent")
        self.store._log_auto_action("stop_agent", name, "Stopped by SuperAgent")
