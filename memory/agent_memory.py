import uuid
from typing import Optional, Callable
from datetime import datetime
from loguru import logger
from .memory_store import MemoryStore
from .consolidator import MemoryConsolidator

class AgentMemory:
    """Hermes-style memory system for each agent.
    
    Architecture:
    - Core Memory: compact, always injected into system prompt (< 2000 tokens)
    - Session History: full detail, searchable via FTS5
    - Skills: procedural memory (extracted from successful sessions)
    - Consolidation: auto-trims and summarizes when near capacity
    
    The memory is divided into targets:
    - self: agent's internal notes (what it learned, what works)
    - user: human's profile, preferences, instructions
    - task: current project/task context
    - environment: platform info, API keys, constraints
    - strategy: money-making strategies being tested
    """

    def __init__(self, agent_name: str, db_dir: str = "data/memory"):
        self.agent_name = agent_name
        self.store = MemoryStore(agent_name, db_dir)
        self.consolidator = MemoryConsolidator(self.store, agent_name)
        self._current_session: Optional[str] = None

    def start_session(self) -> str:
        self._current_session = str(uuid.uuid4())[:8]
        return self._current_session

    @property
    def session_id(self) -> str:
        if not self._current_session:
            self.start_session()
        return self._current_session

    # === Memory Recording ===

    def remember(self, target: str, content: str, category: str = "general", importance: int = 1):
        """Save something to core memory (always available in prompt)."""
        self.store.add_core(target, content, category, importance)
        logger.debug(f"Memory saved [{self.agent_name}].{target}: {content[:60]}...")
        self.consolidator.check_and_consolidate()

    def replace_memory(self, target: str, old_text: str, new_text: str):
        """Update an existing memory entry."""
        self.store.replace_core(old_text, new_text, target)

    def forget(self, target: str, content_containing: str):
        """Remove a memory entry."""
        self.store.remove_core(content_containing, target)

    def log_agent_turn(self, role: str, content: str, summary: Optional[str] = None):
        """Log a single turn in the current session."""
        self.store.log_session(self.session_id, role, content, summary)
        # After enough turns, extract skills & consolidate
        self._maybe_extract_and_summarize()

    def _maybe_extract_and_summarize(self):
        """Periodically extract skills and create summaries."""
        cur = self.store._conn.execute(
            "SELECT COUNT(*) as cnt FROM session_history WHERE session_id = ?",
            (self.session_id,)
        )
        count = cur.fetchone()["cnt"]
        if count == 20:  # every 20 turns
            self.consolidator.extract_skill_from_session(self.session_id)
        if count % 50 == 0:
            self.consolidator.summarize_session_group([self.session_id])

    # === Memory Recall ===

    def build_core_context(self) -> str:
        """Build the core memory context block for the system prompt.
        This is ALWAYS included — Hermes-style persistent context.
        """
        all_mem = self.store.get_all_core()
        parts = []

        for target, entries in all_mem.items():
            if not entries:
                continue
            lines = [
                f"[{entry['category']}] {entry['content']}" 
                for entry in entries
            ]
            parts.append(f"[{target.upper()}]\n" + "\n".join(lines))

        skills = self.store.get_skills(min_success_rate=0.5)
        if skills:
            skill_lines = [f"  - {s['name']}: {s['description']} (success rate: {s['success_rate']:.0%})" for s in skills[:5]]
            parts.append(f"[SKILLS]\n" + "\n".join(skill_lines))

        return "\n\n".join(parts) if parts else "[No core memory yet]"

    def search_past(self, query: str) -> str:
        """Search all past sessions for context (Hermes session_search equivalent).
        Use when the agent needs to remember something from long ago.
        """
        return self.store.search_with_summary(
            query, 
            lambda prompt: self._llm_summarize(prompt)
        )

    def _llm_summarize(self, text: str) -> str:
        """Default summarizer using LLM router."""
        from providers.router import LLMRouter
        llm = LLMRouter()
        return llm.complete(text, agent_type="general",
            system="Summarize concisely. Extract key facts only.")

    def set_llm_summarizer(self, summarizer_fn: Callable):
        """Override the summarizer (useful when agent already has LLM access)."""
        self._user_summarizer = summarizer_fn
        self.store.search_with_summary = lambda q, _, limit: (
            self.store.search_with_summary(q, summarizer_fn, limit)
        )

    # === Skills ===

    def record_skill_use(self, skill_name: str, success: bool):
        self.store.record_skill_outcome(skill_name, success)
        self.consolidator.check_and_consolidate()

    def get_proven_skills(self) -> list[dict]:
        return self.store.get_skills(min_success_rate=0.5)

    # === State Summary ===

    def close(self):
        self.store.close()

    def get_memory_stats(self) -> dict:
        return {
            "agent": self.agent_name,
            "core_token_estimate": self.store.core_memory_token_estimate(),
            "core_limit": MemoryConsolidator.TOKEN_LIMIT,
            "percent_used": self.store.core_memory_token_estimate() / MemoryConsolidator.TOKEN_LIMIT,
            "skills_count": len(self.store.get_skills()),
        }
