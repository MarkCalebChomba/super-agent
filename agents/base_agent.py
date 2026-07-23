import time
import json
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

from providers.router import LLMRouter
from memory.agent_memory import AgentMemory
from log_system.agent_logger import AgentLogger, LogLevel

class BaseAgent(ABC):
    """Base class for all income-generating agents.
    
    Every agent inherits:
    - Hermes-style memory (core + session + skills)
    - Structured logging with CTA support
    - LLM routing with provider fallback
    - Anti-detection stealth context
    - Loop cycle (think -> act -> observe -> reflect)
    """

    def __init__(self, agent_name: str, identity: dict = None,
                 memory_dir: str = "data/memory", log_dir: str = "data/logs"):
        self.name = agent_name
        self.identity = identity or {}
        self.memory = AgentMemory(agent_name, memory_dir)
        self.log = AgentLogger(agent_name, log_dir)
        self.llm = LLMRouter()
        self.running = False
        self.cycle_count = 0
        self.max_idle_cycles = 10  # consolidate memory after N idle cycles

    def build_system_prompt(self) -> str:
        """Build the full system prompt with core memory injected."""
        core = self.memory.build_core_context()
        skills = self.memory.get_proven_skills()
        skills_str = ""
        if skills:
            skills_str = "\n\n[PROVEN SKILLS]\n" + "\n".join(
                f"- {s['name']}: {s['description']}" for s in skills[:5]
            )

        return f"""You are {self.name}, an autonomous AI agent.

[CORE MEMORY]
{core}
{skills_str}

[IDENTITY]
{json.dumps(self.identity, indent=2)}

[INSTRUCTIONS]
You operate in cycles: Think -> Act -> Observe -> Reflect.
- Think: analyze situation, plan next action
- Act: execute a concrete action (API call, post, trade, etc.)
- Observe: report what happened
- Reflect: what did you learn? update memory

You have a memory system. Use these tools:
- !remember <target> <content> [category] [importance] — save to core memory
- !recall <query> — search past sessions
- !forget <text> — remove a memory
- !skill <name> <description> <procedure> — save a reusable skill

Available income methods: {self.get_income_methods()}

Output format each cycle:
ACTION: <what you are doing>
OBSERVATION: <what happened>
MEMO: <what you learned, use !remember syntax>
CTA: <only if you need human help>"""

    @abstractmethod
    def get_income_methods(self) -> str:
        """Return the income methods this agent specializes in."""
        pass

    @abstractmethod
    def think(self, context: dict) -> str:
        """Decide what to do next based on current context."""
        pass

    @abstractmethod
    def act(self, decision: str) -> dict:
        """Execute the decided action. Returns observation dict."""
        pass

    def reflect(self, observation: dict):
        """Learn from the action outcome. Update memory."""
        success = observation.get("success", False)
        revenue = observation.get("revenue", 0)
        error = observation.get("error")

        if revenue > 0:
            self.memory.remember("self", f"Earned ${revenue} from {observation.get('method', 'unknown')}",
                                category="revenue", importance=5)
            self.log.revenue(f"Revenue: ${revenue}", amount=revenue,
                           category=observation.get("method", "general"))

        if error:
            self.memory.remember("self", f"Error in {observation.get('action', 'unknown')}: {error}",
                                category="error", importance=3)
            self.log.error(f"Action failed: {error}", category="error",
                          data={"action": observation.get("action"), "error": error})

        if success:
            self.log.action(f"{observation.get('action', 'unknown')} successful",
                          category=observation.get("method", "general"),
                          data={"details": observation.get("details")})

    def run_cycle(self, context: dict = None) -> dict:
        """One full think-act-observe-reflect cycle."""
        self.cycle_count += 1
        context = context or {}

        # 1. Think
        decision = self.think(context)
        self.log.debug(f"Decision: {decision[:100]}...", category="thinking")

        # Handle memory commands in decision
        self._process_memory_commands(decision)

        # Check for CTA
        if "[CTA]" in decision or "CTA:" in decision:
            self.log.cta(f"Agent needs help: {decision[:200]}",
                        category="cta", data={"decision": decision})

        # 2. Act
        observation = self.act(decision)
        self.memory.log_agent_turn("agent", decision,
                                   summary=observation.get("summary"))

        # 3. Reflect
        self.reflect(observation)
        self.memory.log_agent_turn("system",
            f"Observation: {json.dumps(observation, default=str)[:200]}")

        # Auto-consolidate if idle
        if self.cycle_count % self.max_idle_cycles == 0:
            self.memory.consolidator.check_and_consolidate()

        return observation

    def _process_memory_commands(self, text: str):
        """Parse and execute !remember, !recall, !forget commands."""
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("!remember "):
                parts = line.replace("!remember ", "", 1).split(" ", 2)
                if len(parts) >= 2:
                    target = parts[0]
                    content = parts[1] if len(parts) == 2 else parts[2]
                    category = "general"
                    importance = 1
                    self.memory.remember(target, content, category, importance)
            elif line.startswith("!recall "):
                query = line.replace("!recall ", "", 1)
                results = self.memory.search_past(query)
                logger.info(f"Memory recall [{self.name}]: {results[:200]}")
            elif line.startswith("!forget "):
                text_to_forget = line.replace("!forget ", "", 1)
                self.memory.forget("self", text_to_forget)

    def run_loop(self, max_cycles: int = None):
        """Run agent indefinitely or until max_cycles."""
        self.running = True
        logger.info(f"Agent [{self.name}] started")

        try:
            while self.running:
                if max_cycles and self.cycle_count >= max_cycles:
                    break
                self.run_cycle()
                time.sleep(2)  # rate limiting
        except KeyboardInterrupt:
            logger.info(f"Agent [{self.name}] stopped by user")
        except Exception as e:
            logger.error(f"Agent [{self.name}] crashed: {e}")
            self.log.cta(f"Agent crashed: {e}", category="system_error")
        finally:
            self.running = False
            self.memory.store.close()
            self.log.close()
            logger.info(f"Agent [{self.name}] stopped after {self.cycle_count} cycles")

    def stop(self):
        self.running = False

    def close(self):
        """Clean up resources."""
        self.memory.close()
        self.log.close()
