import time
import json
import os
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

from providers.router import LLMRouter
from memory.agent_memory import AgentMemory
from log_system.agent_logger import AgentLogger, LogLevel

class BaseAgent(ABC):
    """Base class for build-oriented agents.

    Instead of think->act->reflect cycles that burn LLM tokens on planning,
    agents focus on BUILDING real output files (bots, websites, scripts).
    """

    BUILD_DIR = "build_output"

    def __init__(self, agent_name: str, identity: dict = None,
                 memory_dir: str = "data/memory", log_dir: str = "data/logs"):
        self.name = agent_name
        self.identity = identity or {}
        self.memory = AgentMemory(agent_name, memory_dir)
        self.log = AgentLogger(agent_name, log_dir)
        self.llm = LLMRouter()
        self.running = False
        self.cycle_count = 0
        self.build_dir = os.path.join(self.BUILD_DIR, agent_name)
        os.makedirs(self.build_dir, exist_ok=True)

    @abstractmethod
    def get_income_methods(self) -> str:
        pass

    def build(self) -> dict:
        """Override this. Create a real output file.

        Returns: {"file": "path/to/file", "summary": "what was built", "revenue": 0.0}
        Return None/empty dict to skip this cycle.
        """
        return None

    def run_cycle(self, context: dict = None) -> dict:
        """One build cycle. No plan logging, no memory overhead."""
        self.cycle_count += 1
        result = self.build()
        if result and result.get("file"):
            self.log.action(f"Built: {os.path.basename(result['file'])}",
                          category="build", data=result)
        if result and result.get("revenue", 0) > 0:
            self.log.revenue(f"Revenue: ${result['revenue']:.2f}",
                           amount=result["revenue"],
                           category=result.get("method", "general"))
        if self.cycle_count % 50 == 0:
            self.memory.consolidator.check_and_consolidate()
        return result or {}

    def run_loop(self, max_cycles: int = None):
        self.running = True
        logger.info(f"Agent [{self.name}] started")
        try:
            while self.running:
                if max_cycles and self.cycle_count >= max_cycles:
                    break
                result = self.run_cycle()
                time.sleep(2)
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
        self.memory.close()
        self.log.close()
