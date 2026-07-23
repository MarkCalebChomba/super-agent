from loguru import logger
from providers.router import LLMRouter

class MemoryConsolidator:
    """Hermes-style memory consolidation.
    When core memory approaches capacity, consolidate:
    - Merge related entries
    - Remove outdated facts
    - Compress verbose entries
    - Summarize session groups
    """

    TOKEN_LIMIT = 1800
    CONSOLIDATION_THRESHOLD = 0.75  # consolidate when >75% full

    def __init__(self, memory_store, agent_name: str):
        self.store = memory_store
        self.agent_name = agent_name
        self.llm = LLMRouter()

    def check_and_consolidate(self):
        """Check if memory needs consolidation and do it."""
        current = self.store.core_memory_token_estimate()
        if current < self.TOKEN_LIMIT * self.CONSOLIDATION_THRESHOLD:
            return False

        logger.info(f"Consolidating memory [{self.agent_name}]: {current}/{self.TOKEN_LIMIT} tokens")
        self._consolidate()
        self.store.trim_core_to_limit(self.TOKEN_LIMIT)
        return True

    def _consolidate(self):
        all_mem = self.store.get_all_core()
        for target, entries in all_mem.items():
            if len(entries) <= 1:
                continue

            content = "\n".join(f"- [{e['category']}] {e['content']}" for e in entries)
            prompt = (
                f"Below are memory entries for target '{target}'. "
                f"Consolidate them into a single concise paragraph. "
                f"Remove redundant or outdated information. "
                f"Keep all unique, important facts:\n\n{content}"
            )
            consolidated = self.llm.complete(prompt, agent_type="general",
                system="You are a memory consolidation AI. Output only the consolidated text, no explanations.")
            if consolidated:
                for e in entries:
                    self.store.remove_core(e["content"][:30], target)
                self.store.add_core(target, consolidated, category="consolidated", importance=3)
                logger.info(f"Consolidated {len(entries)} entries for [{self.agent_name}].{target}")

    def summarize_session_group(self, session_ids: list[str]) -> str:
        """Summarize a group of related sessions into a persistent memory."""
        sessions_data = []
        for sid in session_ids:
            cur = self.store._conn.execute(
                "SELECT role, content, summary FROM session_history WHERE session_id = ? ORDER BY id",
                (sid,)
            )
            for row in cur.fetchall():
                sessions_data.append(f"[{row['role']}]: {row['content'][:200]}")

        if not sessions_data:
            return ""

        context = "\n".join(sessions_data[-20:])  # last 20 messages
        summary = self.llm.complete(
            f"Summarize what happened in these sessions. Extract: key actions taken, "
            f"results achieved, lessons learned, and context for future reference:\n\n{context}",
            agent_type="general",
            system="You are a session summarizer. Output a concise, dense summary."
        )
        if summary:
            self.store.save_summary("session_group", summary)
            self.store.add_core("self", f"Session summary: {summary[:200]}",
                               category="session_summary", importance=2)
        return summary

    def extract_skill_from_session(self, session_id: str):
        """Extract a reusable skill/procedure from a successful session."""
        cur = self.store._conn.execute(
            "SELECT role, content FROM session_history WHERE session_id = ? AND role = 'agent' ORDER BY id",
            (session_id,)
        )
        actions = [r["content"][:500] for r in cur.fetchall()]
        if len(actions) < 3:
            return

        context = "\n".join(actions[-10:])
        skill_def = self.llm.complete(
            f"From these agent actions, extract a reusable skill: name it, describe what it does, "
            f"and write a step-by-step procedure:\n\n{context}",
            agent_type="general",
            system="You are a skill extraction AI. Output: NAME: <name>\nDESCRIPTION: <desc>\nPROCEDURE: <steps>"
        )
        if skill_def:
            lines = skill_def.strip().split("\n")
            name = ""
            description = ""
            procedure = ""
            for line in lines:
                if line.startswith("NAME:"):
                    name = line.replace("NAME:", "").strip()
                elif line.startswith("DESCRIPTION:"):
                    description = line.replace("DESCRIPTION:", "").strip()
                elif line.startswith("PROCEDURE:"):
                    procedure = line.replace("PROCEDURE:", "").strip()

            if name:
                self.store.add_skill(name, description, procedure)
                logger.info(f"Extracted skill [{self.agent_name}]: {name}")
