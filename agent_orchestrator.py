"""Plan ⭢ Act ⭢ Observe execution loop with tenacity and memory.

Architecture:
  Planner  — breaks North Star goal into actionable task queue
  Executor — runs each task via LLM with memory-context augmentation
  Evaluator — checks result, decides: completed / retry / impossible
  Tenacity — dynamic retries with varied approaches, frustration threshold

Memory tiers:
  Working — current task, conversation buffer, frustration state (in-memory)
  Long-term — experiences stored as JSON files (keyword-retrievable)
  North Star — original goal injected into every LLM call
"""
import json
import time
from datetime import datetime
from typing import Optional
from loguru import logger


class AgentOrchestrator:
    """Plan ⭢ Act ⭢ Observe loop for a single agent."""

    def __init__(self, agent, memory,
                 max_attempts_per_task: int = 5,
                 frustration_threshold: int = 3):
        self.agent = agent
        self.memory = memory
        self.max_attempts = max_attempts_per_task
        self.frustration_threshold = frustration_threshold
        self.north_star = ""

    # ── North Star ─────────────────────────────────────────────────

    def load_north_star(self):
        inst = self.agent.instruction_set or {}
        self.north_star = (
            inst.get("identity_prompt")
            or inst.get("genesis_prompt")
            or inst.get("seed_instruction")
            or ""
        )

    # ── PLAN: task queue ───────────────────────────────────────────

    def plan_phase(self) -> list[dict]:
        """Break the North Star goal into actionable tasks via LLM."""
        self.load_north_star()

        pending = self.memory.pending_tasks()
        if pending:
            return pending

        prompt = f"""You are an AI agent with this mission:

{self.north_star}

Break this mission into 3-5 concrete, actionable tasks. Each task must:
- Be specific and measurable
- Have clear success criteria
- Be achievable with text generation and reasoning

Return ONLY a JSON array of objects, each with:
  "id": unique name like "task_research"
  "description": what to do
  "success_criteria": how to know it's done
  "tags": ["keyword1", "keyword2"]

Example:
[{{"id":"task_analyze_market","description":"Research current market conditions to identify opportunities","success_criteria":"Top 3 opportunities identified with reasoning","tags":["research","analysis"]}}]
"""
        output = self._call_llm(prompt)
        if output:
            try:
                tasks = json.loads(output)
                if isinstance(tasks, list):
                    for t in tasks:
                        t.setdefault("dependencies", [])
                        t.setdefault("status", "pending")
                        t.setdefault("attempts", 0)
                        self.memory.add_task(t)
                    return tasks
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse LLM task plan for {self.agent.name}")

        fallback = [{
            "id": "execute_mission",
            "description": self.north_star or "Execute your purpose",
            "success_criteria": "Make measurable progress toward the goal",
            "tags": ["mission"],
            "dependencies": [],
            "status": "pending",
            "attempts": 0,
        }]
        self.memory.add_task(fallback[0])
        return fallback

    # ── ACT: execute a task ────────────────────────────────────────

    def act_phase(self, task: dict) -> dict:
        """Execute a single task via LLM, augmented with memory context."""
        relevant = self.memory.query_memory(task.get("description", ""), limit=3)
        frustration = self.memory.get_frustration()
        attempts = self.memory.attempts_for(task["id"])
        tried = self.memory.tried_approaches_for(task["id"])

        # Build context blocks
        parts = [f"## YOUR MISSION (North Star)\n{self.north_star}"]

        parts.append(f"## CURRENT TASK\n{task['description']}")
        parts.append(f"## SUCCESS CRITERIA\n{task['success_criteria']}")

        if relevant:
            mem = "\n".join(
                f"{'✓' if e['success'] else '✗'} {e['action'][:100]}"
                for e in relevant
            )
            parts.append(f"## RELEVANT PAST EXPERIENCES\n{mem}")

        if tried:
            parts.append("## APPROACHES ALREADY TRIED (do not repeat)")
            parts.extend(f"- {a}" for a in tried)

        if frustration > 0:
            parts.append(
                f"\nNOTE: You have failed {frustration} time(s). "
                f"Try a COMPLETELY DIFFERENT approach."
            )
        if attempts >= self.frustration_threshold:
            parts.append("\nWARNING: This is your last attempt before giving up on this task.")

        parts.append("""## INSTRUCTIONS
1. Execute the task using your knowledge and reasoning
2. Provide concrete output — not just plans or ideas
3. If you hit a roadblock, try a different angle
4. End with one of:
   "TASK COMPLETE: <summary>" if you succeeded
   "TASK FAILED: <reason>" if you cannot complete it
   "PARTIAL: <what you achieved>" if you made progress

## OUTPUT
""")

        prompt = "\n\n".join(parts)
        result_text = self._call_llm(prompt)

        if result_text:
            upper = result_text.upper()
            success = "TASK COMPLETE" in upper
            partial = "PARTIAL" in upper
            return {
                "output": result_text,
                "success": success,
                "partial": partial,
            }
        return {"output": None, "success": False, "error": "LLM returned no output"}

    # ── OBSERVE / EVALUATE ─────────────────────────────────────────

    def evaluate_phase(self, task: dict, result: dict) -> str:
        """Return verdict: 'completed', 'retry', 'impossible', or 'partial'."""
        if result.get("success"):
            self.memory.store_experience(
                action=f"Task completed: {task['description']}",
                result=result,
                tags=task.get("tags", []) + ["completed"],
            )
            self.memory.update_task(task["id"], {"status": "completed"})
            self.memory.reset_frustration()
            return "completed"

        if result.get("partial"):
            self.memory.store_experience(
                action=f"Partial progress on: {task['description']}",
                result=result,
                tags=task.get("tags", []) + ["partial"],
            )
            self.memory.reset_frustration()
            return "partial"

        # Failure
        self.memory.increment_frustration()
        self.memory.record_attempt(task["id"], (result.get("output") or "")[:150])
        self.memory.store_experience(
            action=f"Attempt {self.memory.attempts_for(task['id'])}: {task['description']}",
            result=result,
            tags=task.get("tags", []) + ["failed"],
        )

        if self.memory.get_frustration() >= self.frustration_threshold:
            self.memory.update_task(task["id"], {"status": "impossible"})
            self.memory.reset_frustration()
            return "impossible"

        return "retry"

    # ── ADAPT ──────────────────────────────────────────────────────

    def adapt_phase(self, task: dict, result: dict, verdict: str):
        """After evaluation, decide what to do next."""
        if verdict in ("completed", "partial"):
            return

        if verdict == "impossible":
            summary = self._call_llm(
                f"Task failed after exhausting approaches.\n\n"
                f"Task: {task['description']}\n"
                f"Last result: {(result.get('output') or '')[:500]}\n\n"
                f"Summarize what was learned and what could be tried differently with new resources:"
            )
            if summary:
                self.memory.store_experience(
                    action=f"Post-mortem: {task['description']}",
                    result={"success": False, "output": summary},
                    tags=["postmortem", "failed"],
                )
            return

        # retry — generate a different micro-approach
        micro = self._call_llm(
            f"Task failed. Generate ONE different approach.\n\n"
            f"Task: {task['description']}\n"
            f"Previous result: {(result.get('output') or '')[:300]}\n\n"
            f"Return a JSON object with:\n"
            f'  {{"approach": "what to do differently", "reason": "why this might work"}}'
        )
        if micro:
            try:
                plan = json.loads(micro)
                subtask = {
                    "id": f"{task['id']}_retry_{self.memory.attempts_for(task['id'])}",
                    "description": plan.get("approach", task["description"]),
                    "success_criteria": plan.get("reason", task.get("success_criteria", "")),
                    "tags": task.get("tags", []) + ["retry"],
                    "dependencies": task.get("dependencies", []),
                    "status": "pending",
                    "attempts": 0,
                }
                self.memory.add_task(subtask)
            except json.JSONDecodeError:
                pass

    # ── Main cycle ─────────────────────────────────────────────────

    def get_next_action(self) -> Optional[dict]:
        task = self.memory.get_next_task()
        if task:
            return task
        planned = self.plan_phase()
        return planned[0] if planned else None

    def run_cycle(self) -> dict:
        """One full Plan ⭢ Act ⭢ Observe ⭢ Adapt cycle."""
        self.load_north_star()

        task = self.get_next_action()
        if not task:
            return {"output": None, "success": False, "idle": True}

        self.memory.working["current_task"] = task

        result = self.act_phase(task)
        verdict = self.evaluate_phase(task, result)
        self.adapt_phase(task, result, verdict)

        result["verdict"] = verdict
        result["task_id"] = task["id"]
        return result

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call the agent's LLM execution path."""
        return self.agent._execute_via_hermes(prompt).get("output")
