"""Multi-agent hierarchy: Supervisor -> Worker -> Critic workflow loop.

Architecture:
  Supervisor — holds the North Star, decomposes goals into sub-tasks,
              delegates to Workers, reviews Critic feedback, issues revisions
  Worker    — executes a sub-task via LLM and submits output
  Critic    — evaluates Worker output against a strict rubric:
              1. Technical/quality standards
              2. Commercial / monetisation value
              3. Progress toward the primary goal
              Returns: passed | needs_revision | failed

Workflow:
  1. Supervisor decomposes goal -> task queue
  2. Supervisor assigns next task to Worker
  3. Worker executes -> submits output
  4. Critic reviews output against rubric
  5. If passed -> Supervisor updates context, moves to next task
  6. If needs_revision -> Supervisor generates specific feedback,
     Worker revises (loop up to max_revisions)
  7. If failed -> task marked impossible, Supervisor logs lesson
"""
import json
import time
from typing import Optional
from datetime import datetime
from loguru import logger


CRITIC_RUBRIC = """## Value Assessment Protocol

Evaluate the submitted work against these criteria:

### 1. Technical Standards (pass/fail)
- Is the output well-reasoned and logically sound?
- Does it demonstrate competence in the domain?
- Is it actionable, not just theoretical?

### 2. Commercial Value (pass/fail)
- Does this create a DIRECT path to revenue or cost reduction?
- Does this build an ASSET that can be monetised later?
- Is there a clear "who would pay for this" answer?
- If copied from an existing source, is it personalised enough to be competitive?

### 3. Goal Alignment (pass/fail)
- Does this move us closer to the primary mission?
- Is it focused on execution rather than planning?
- Does it avoid scope creep / irrelevant tangents?

### Output Rules
- You MUST return valid JSON with exactly these fields:
  {"verdict":"passed|needs_revision|failed","score":0-10,"strengths":[],"weaknesses":[],"feedback":"specific actionable criticism","commercial_value":"explanation of revenue potential"}
"""


class AgentOrchestrator:
    """Supervisor -> Worker -> Critic loop for a single agent."""

    def __init__(self, agent, memory,
                 max_revisions: int = 3,
                 frustration_threshold: int = 3):
        self.agent = agent
        self.memory = memory
        self.max_revisions = max_revisions
        self.frustration_threshold = frustration_threshold
        self.north_star = ""
        self.revision_count = 0

    # ── North Star ─────────────────────────────────────────────────

    def load_north_star(self):
        inst = self.agent.instruction_set or {}
        self.north_star = (
            inst.get("identity_prompt")
            or inst.get("genesis_prompt")
            or inst.get("seed_instruction")
            or ""
        )

    # ── SUPERVISOR: Plan ───────────────────────────────────────────

    def supervisor_plan(self) -> list[dict]:
        """Break goal into actionable sub-tasks."""
        self.load_north_star()

        pending = self.memory.pending_tasks()
        if pending:
            return pending

        prompt = f"""You are the SUPERVISOR. Your mission:

{self.north_star}

Decompose this mission into 3-5 concrete sub-tasks. Each sub-task must:

1. Be specific and actionable by a Worker agent
2. Have a clear "done" criterion
3. Produce a tangible output (research, analysis, plan, asset)
4. For scripts/code: instruct the worker to FIND existing solutions on GitHub, YouTube, TikTok, or marketplaces rather than writing from scratch. The worker should personalise and monetise what already works.
5. For content: instruct to find high-performing examples and adapt them.

Return ONLY a JSON array of objects:
  {{"id":"task_unique_name","description":"what to do","success_criteria":"how to verify","tags":["tag1","tag2"],"constraints":"any specific constraints"}}

Example:
[{{"id":"research_market","description":"Research top-performing affiliate programs for crypto trading","success_criteria":"List of 5 programs with commission rates and requirements","tags":["research","affiliate"],"constraints":"Focus on programs that pay in crypto"}}]
"""
        output = self._call_llm(prompt)
        if output:
            try:
                tasks = json.loads(output)
                if isinstance(tasks, list):
                    for t in tasks:
                        t.setdefault("status", "pending")
                        t.setdefault("attempts", 0)
                        t.setdefault("revisions", 0)
                        self.memory.add_task(t)
                    return tasks
            except json.JSONDecodeError:
                logger.warning(f"Supervisor plan parse failed for {self.agent.name}")

        fallback = [{
            "id": "execute_mission",
            "description": self.north_star or "Execute your purpose",
            "success_criteria": "Make measurable progress toward the goal",
            "tags": ["mission"],
            "status": "pending", "attempts": 0, "revisions": 0,
        }]
        self.memory.add_task(fallback[0])
        return fallback

    # ── SUPERVISOR: Generate revision feedback ─────────────────────

    def supervisor_revise(self, task: dict, critique: dict) -> str:
        """Supervisor generates specific revision instructions."""
        feedback = critique.get("feedback", "Improve the output.")
        weaknesses = critique.get("weaknesses", [])
        w_list = "\n".join(f"- {w}" for w in weaknesses)

        prompt = f"""You are the SUPERVISOR reviewing a Worker's failed submission.

Mission: {self.north_star}
Task: {task['description']}
Critique feedback: {feedback}
Weaknesses identified:
{w_list}

Generate 2-3 specific, actionable revision instructions for the Worker.
Focus on what to CHANGE, not just what's wrong.
Consider how existing solutions (GitHub, YouTube, tutorials) could be adapted.
Return a JSON object:
  {{"revision_instructions":["instruction 1","instruction 2","instruction 3"],"priority":"what to focus on first"}}
"""
        result = self._call_llm(prompt)
        if result:
            try:
                return json.loads(result).get("revision_instructions", [result])
            except json.JSONDecodeError:
                return [result]
        return ["Improve the output based on the critique feedback."]

    # ── WORKER: Execute ────────────────────────────────────────────

    def worker_execute(self, task: dict, revision_hint: str = "") -> dict:
        """Worker executes a sub-task and submits output."""
        relevant = self.memory.query_memory(task.get("description", ""), limit=3)
        revision = self.memory.working.get("current_revision", 0)
        tried = self.memory.tried_approaches_for(task["id"])

        parts = [f"## MISSION (North Star)\n{self.north_star}"]
        parts.append(f"## YOUR ROLE\nYou are a Worker agent executing a specific task.")
        parts.append(f"## TASK\n{task['description']}")
        parts.append(f"## SUCCESS CRITERIA\n{task['success_criteria']}")

        if task.get("constraints"):
            parts.append(f"## CONSTRAINTS\n{task['constraints']}")

        if revision_hint:
            parts.append(f"## REVISION INSTRUCTIONS\n{revision_hint}")

        if relevant:
            mem = "\n".join(
                f"{'✓' if e['success'] else '✗'} {e['action'][:120]}"
                for e in relevant
            )
            parts.append(f"## PAST EXPERIENCES\n{mem}")

        if tried:
            parts.append("## APPROACHES ALREADY TRIED (avoid repeating)")
            parts.extend(f"- {a}" for a in tried)

        if revision > 0:
            parts.append(f"\nThis is revision {revision}. Make sure your output addresses ALL previous feedback.")

        parts.append("""## OUTPUT REQUIREMENTS
1. Provide concrete output — not just plans or ideas
2. If relevant: cite existing solutions, sources, or market data
3. End with SUBMISSION: followed by a brief summary of what you produced

## OUTPUT
""")

        prompt = "\n\n".join(parts)
        result_text = self._call_llm(prompt)
        if result_text:
            return {"output": result_text, "success": True}
        return {"output": None, "success": False, "error": "Worker returned no output"}

    # ── CRITIC: Evaluate ───────────────────────────────────────────

    def critic_evaluate(self, task: dict, output: str) -> dict:
        """Critic evaluates Worker output against rubric."""
        prompt = f"""You are the CRITIC. Your job is to evaluate the Worker's output against a strict rubric.

## Mission
{self.north_star}

## Task Assigned
{task['description']}

## Success Criteria
{task['success_criteria']}

## Worker Output
{output[:4000]}

{CRITIC_RUBRIC}
"""
        result = self._call_llm(prompt)
        if result:
            try:
                critique = json.loads(result)
                critique.setdefault("verdict", "needs_revision")
                critique.setdefault("score", 5)
                critique.setdefault("weaknesses", [])
                critique.setdefault("feedback", "Review the output.")
                return critique
            except (json.JSONDecodeError, TypeError):
                # If LLM didn't return valid JSON, extract verdict heuristically
                upper = result.upper()
                if "PASS" in upper:
                    return {"verdict": "passed", "score": 7, "weaknesses": [],
                            "feedback": result[:300], "commercial_value": "See output"}
                return {"verdict": "needs_revision", "score": 5,
                        "weaknesses": ["Output format incorrect"],
                        "feedback": result[:300], "commercial_value": "Not assessed"}
        return {"verdict": "failed", "score": 0,
                "weaknesses": ["Critic could not evaluate"],
                "feedback": "No output to evaluate", "commercial_value": "None"}

    # ── Main workflow loop ─────────────────────────────────────────

    def get_next_task(self) -> Optional[dict]:
        task = self.memory.get_next_task()
        if task:
            return task
        planned = self.supervisor_plan()
        return planned[0] if planned else None

    def run_cycle(self) -> dict:
        """One full Supervisor -> Worker -> Critic workflow cycle."""
        self.load_north_star()

        task = self.get_next_task()
        if not task:
            return {"output": None, "success": False, "idle": True}

        self.memory.working["current_task"] = task
        self.revision_count = 0
        revision_hint = ""

        # Revision loop
        while self.revision_count <= self.max_revisions:
            # WORKER: execute
            result = self.worker_execute(task, revision_hint)
            if not result.get("output"):
                self.memory.store_experience(
                    action=f"Worker failed: {task['description']}",
                    result={"success": False, "error": "No output"},
                    tags=task.get("tags", []) + ["worker_failed"],
                )
                break

            # CRITIC: evaluate
            critique = self.critic_evaluate(task, result["output"])
            logger.info(f"{self.agent.name} | {task['id']} | "
                        f"verdict={critique.get('verdict')} "
                        f"score={critique.get('score')}/10")

            verdict = critique.get("verdict", "needs_revision")

            if verdict == "passed":
                # SUCCESS: task complete
                self.memory.store_experience(
                    action=f"Task passed: {task['description']}",
                    result={"success": True, "output": result["output"]},
                    tags=task.get("tags", []) + ["completed"],
                )
                self.memory.update_task(task["id"], {"status": "completed"})
                self.memory.reset_frustration()
                result["critique"] = critique
                result["verdict"] = "completed"
                return result

            elif verdict == "needs_revision":
                # REVISE: supervisor generates feedback, worker retries
                self.revision_count += 1
                self.memory.working["current_revision"] = self.revision_count
                self.memory.record_attempt(task["id"], result["output"][:150])

                if self.revision_count >= self.max_revisions:
                    logger.info(f"{self.agent.name} | max revisions ({self.max_revisions}) reached")
                    break

                # Supervisor generates revision instructions
                revision_hint_list = self.supervisor_revise(task, critique)
                if isinstance(revision_hint_list, list):
                    revision_hint = "\n".join(f"- {h}" for h in revision_hint_list)
                else:
                    revision_hint = str(revision_hint_list)

                self.memory.store_experience(
                    action=f"Revision {self.revision_count}: {task['description']}",
                    result={"success": False, "output": result["output"],
                            "feedback": critique.get("feedback", "")},
                    tags=task.get("tags", []) + ["revision"],
                )
                continue

            else:  # failed
                break

        # FAILED after all revisions
        self.memory.increment_frustration()
        self.memory.store_experience(
            action=f"Task failed after {self.revision_count} revisions: {task['description']}",
            result={"success": False, "output": result.get("output", "")},
            tags=task.get("tags", []) + ["failed"],
        )
        self.memory.update_task(task["id"], {"status": "impossible"})
        self.memory.reset_frustration()

        return {
            "output": result.get("output"),
            "success": False,
            "verdict": "impossible" if self.memory.get_frustration() >= self.frustration_threshold else "failed",
            "critique": critique if 'critique' in locals() else None,
            "revisions": self.revision_count,
        }

    def _call_llm(self, prompt: str) -> Optional[str]:
        return self.agent._execute_via_hermes(prompt).get("output")
