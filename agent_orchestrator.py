"""State-machine orchestrator: PLANNING → EXECUTING → EVALUATING → SHIPPING → DONE.

Per user's redesign:
- Every hand-off is schema-validated (tool-calling, not regex)
- Every phase writes to EventLog (structured JSON-lines, not print)
- Real shipping step produces a file/artifact
- Human approval gate on publish/money actions
- Real cost tracking from actual token usage
- Dead-letter queue for terminal failures
"""
import json
import re
import time
import uuid
import threading
from pathlib import Path
from typing import Optional, NamedTuple
from datetime import datetime
from loguru import logger
from resource_bank import ResourceBank
from finance_layer import FinanceLayer, create_human_task, get_pending_tasks

from event_log import EventLog


# ── Task state machine ───────────────────────────────────────────────

TASK_STATES = [
    "PENDING",
    "PLANNING",
    "EXECUTING",
    "EVALUATING",
    "PASSED",
    "AWAITING_APPROVAL",
    "SHIPPING",
    "DONE",
    "FAILED",
    "DEAD_LETTER",
]

# Transitions that need human approval
APPROVAL_REQUIRED_ACTIONS = {"publish_external", "spend_money", "deploy_code"}


# ── Schemas for tool-calling (forced JSON output) ────────────────────

PLAN_SCHEMA = {
    "name": "submit_tasks",
    "description": "Submit 3-5 concrete sub-tasks for this cycle.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short unique name for the task (snake_case)"},
                        "description": {"type": "string", "description": "What to do"},
                        "success_criteria": {"type": "string", "description": "How to verify completion"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Category tags like research, content, code, outreach",
                        },
                        "action_type": {
                            "type": "string",
                            "enum": ["research", "content", "code", "outreach", "analysis", "publish_external", "spend_money", "deploy_code"],
                            "description": "Type of action this task performs. publish_external/spend_money/deploy_code require human approval.",
                        },
                    },
                    "required": ["id", "description", "success_criteria"],
                },
            }
        },
        "required": ["tasks"],
    },
}

CRITIC_SCHEMA = {
    "name": "submit_evaluation",
    "description": "Evaluate the worker's output against the rubric.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["passed", "needs_revision", "failed"],
            },
            "score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
            },
            "weaknesses": {
                "type": "array",
                "items": {"type": "string"},
            },
            "feedback": {
                "type": "string",
                "description": "Specific actionable criticism to improve the output",
            },
            "commercial_value": {
                "type": "string",
                "description": "Assessment of revenue potential",
            },
        },
        "required": ["verdict", "score", "feedback"],
    },
}

REVISION_SCHEMA = {
    "name": "submit_revision_instructions",
    "description": "Provide 2-3 specific revision instructions for the worker.",
    "input_schema": {
        "type": "object",
        "properties": {
            "revision_instructions": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            },
            "priority": {
                "type": "string",
                "description": "What to focus on first in the revision",
            },
        },
        "required": ["revision_instructions"],
    },
}

HUMAN_TASK_PATTERN = re.compile(
    r'HUMAN_TASK:\s*(?P<title>[^|]+)\s*\|\s*(?P<url>[^|]+)\s*\|\s*(?P<instructions>.+)',
    re.IGNORECASE,
)


# ── Concurrency control ──────────────────────────────────────────────

_llm_semaphore = threading.Semaphore(3)
_agent_run_lock = threading.Lock()
_running_agents: dict[str, threading.Thread] = {}


class AgentOrchestrator:
    """State-machine orchestrator. One agent, one cycle at a time."""

    def __init__(self, agent, memory,
                 max_revisions: int = 3,
                 frustration_threshold: int = 3):
        self.agent = agent
        self.memory = memory
        self.max_revisions = max_revisions
        self.frustration_threshold = frustration_threshold
        self.north_star = ""
        self.revision_count = 0
        self.resource_bank = ResourceBank(agent.name)
        self.finance = FinanceLayer(agent.name)
        self.event_log = EventLog(agent.name)
        self._model_unavailable = False
        self._model_failed_at = 0.0

    # ── North Star ──────────────────────────────────────────────────

    def load_north_star(self):
        inst = self.agent.instruction_set or {}
        self.north_star = (
            inst.get("identity_prompt")
            or inst.get("genesis_prompt")
            or inst.get("seed_instruction")
            or ""
        )

    # ── Phase: PLANNING ─────────────────────────────────────────────

    def _plan_tasks(self) -> list[dict]:
        """Supervisor decomposes goal into sub-tasks. Schema-forced JSON via tool-calling."""
        if self._model_unavailable:
            logger.warning(f"{self.agent.name} | model unavailable, skip plan")
            return [self._fallback_task("Model unavailable — waiting for retry")]

        self.load_north_star()
        event_id = self.event_log.write(phase="planning_started", north_star_len=len(self.north_star))

        pending = self.memory.pending_tasks()
        if pending:
            logger.info(f"{self.agent.name} | using {len(pending)} pending tasks")
            return pending

        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()

        prompt = f"""You are the SUPERVISOR planning work for an autonomous agent.

Your mission:
{self.north_star}

{resource_report}
{finance_report}

Decompose this mission into 1-5 concrete sub-tasks. Each sub-task must:
- Be specific and actionable by a single LLM call + web search
- Have a clear "done" criterion
- Prioritize the shortest path to real revenue
- Be realistic about what can be done with LLM + web search
- For each task, set an action_type:
  - "research" / "content" / "code" / "outreach" / "analysis" — no human needed
  - "publish_external" — requires human approval before going live
  - "spend_money" — requires human approval
  - "deploy_code" — requires human approval

Write original content informed by what works — do NOT copy competitors verbatim.
Analyze their approach and express insights in your own words.

Return the tasks via the submit_tasks function.
"""
        result = self._llm_call_structured(prompt, PLAN_SCHEMA, role="supervisor",
                                            event_id=event_id)

        if result and result.get("tasks"):
            tasks = result["tasks"]
            for i, t in enumerate(tasks):
                t.setdefault("id", f"task_{i+1}")
                t.setdefault("status", "pending")
                t.setdefault("attempts", 0)
                t.setdefault("revisions", 0)
                t.setdefault("action_type", "research")
                t.setdefault("state", "pending")
                t.setdefault("success_criteria", "Produce concrete output that advances the mission")
                self.memory.add_task(t)

            self.event_log.write(phase="planning_complete", event_id=event_id,
                                  task_count=len(tasks),
                                  task_ids=[t["id"] for t in tasks])
            return tasks

        logger.warning(f"{self.agent.name} | planning failed, using fallback task")
        fallback = [{
            "id": "execute_mission",
            "description": self.north_star or "Execute your purpose",
            "success_criteria": "Make measurable progress toward the goal",
            "tags": ["mission"],
            "action_type": "research",
            "state": "PENDING", "status": "pending", "attempts": 0, "revisions": 0,
        }]
        self.memory.add_task(fallback[0])
        return fallback

    # ── Phase: EXECUTING ────────────────────────────────────────────

    def _execute_task(self, task: dict, revision_hint: str = "") -> Optional[dict]:
        """Worker executes a task via LLM + search + browsing. Returns output dict or None."""
        event_id = self.event_log.write(phase="executing_started",
                                          task_id=task["id"],
                                          revision_count=self.revision_count)

        if self._model_unavailable:
            self.event_log.write(phase="executing_skipped", event_id=event_id,
                                  reason="model_unavailable")
            return None

        # Gather resources
        relevant = self.memory.query_memory(task.get("description", ""), limit=3)
        revision = self.memory.working.get("current_revision", 0)
        tried = self.memory.tried_approaches_for(task["id"])
        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()

        # Web search (task-specific, not hardcoded Wikipedia)
        search_results = []
        try:
            from tools.web_search import web_search
            search_results = web_search(task["description"], max_results=5)
        except Exception:
            pass

        # Build prompt
        parts = [
            f"## MISSION\n{self.north_star}",
            f"## YOUR ROLE\nYou are a Worker agent executing a specific task. Be concrete — produce actual output, not plans.",
            f"## TASK\n{task['description']}",
            f"## SUCCESS CRITERIA\n{task['success_criteria']}",
        ]
        if task.get("constraints"):
            parts.append(f"## CONSTRAINTS\n{task['constraints']}")
        if revision_hint:
            parts.append(f"## REVISION INSTRUCTIONS\n{revision_hint}")
        if relevant:
            lines = "\n".join(
                f"{'[OK]' if e['success'] else '[FAIL]'} {e['action'][:300]}"
                for e in relevant
            )
            parts.append(f"## PAST EXPERIENCES\n{lines}")
        if tried:
            parts.append("## APPROACHES ALREADY TRIED")
            parts.extend(f"- {a}" for a in tried)
        if revision > 0:
            parts.append(f"This is revision {revision}. Address ALL previous feedback.")
        parts.append(resource_report)
        parts.append(finance_report)
        if search_results:
            sr_lines = "\n".join(f"- {r['title']}: {r['url']}" for r in search_results[:5])
            parts.append(f"## REAL SEARCH RESULTS\n{sr_lines}")

        # Analyze what works from competitors — write original content informed by analysis
        parts.append("""
## OUTPUT REQUIREMENTS
1. Produce concrete output, not plans
2. RESEARCH what competitors do — cite their approaches, then write ORIGINAL content
   expressing your own insights in your own words
3. Cite real sources from search results above
4. If human help is needed, include: HUMAN_TASK: Title | URL | Instructions
5. End with SUBMISSION: followed by a brief summary
6. EVERY output must answer: "How does this make money?"
7. Include honest disclosures if affiliate links or reviews are involved
8. Do NOT fabricate testimonials, reviews, or urgency claims

## REAL-WORLD ACTIONS
You can perform real browser actions by including lines like:
  BROWSER: navigate | https://example.com/signup
  BROWSER: scrape | https://example.com/pricing
  BROWSER: screenshot | https://example.com
  BROWSER: login_google | email@gmail.com | your_password
  BROWSER: signup | https://example.com/register | email | password

For sign-up / account-creation tasks, you can also just describe what to do
in detail (URLs, steps, what form fields to fill) and the system will
automatically execute it as a browser task. Include credentials inline.
These will be executed and the results appended to your output.
""")

        prompt = "\n\n".join(parts)
        llm_result = self._llm_call(prompt, role="worker", max_tokens=65536,
                                     event_id=event_id)

        if not llm_result:
            self.event_log.write(phase="executing_failed", event_id=event_id,
                                  error="LLM returned no output")
            return None

        output = llm_result.text

        # Execute browser actions if the LLM requested real-world interaction
        browser_output = self._execute_browser_actions(output, task)
        if browser_output:
            output += "\n\n## BROWSER RESULT\n" + browser_output

        # Check for human task request
        ht_match = HUMAN_TASK_PATTERN.search(output)
        human_task = None
        if ht_match:
            human_task = {
                "title": ht_match.group("title").strip(),
                "url": ht_match.group("url").strip(),
                "instructions": ht_match.group("instructions").strip(),
            }

        result = {
            "output": output,
            "success": True,
            "human_task": human_task,
            "token_usage": {
                "input_tokens": llm_result.input_tokens,
                "output_tokens": llm_result.output_tokens,
                "cost": llm_result.cost,
                "model": llm_result.model,
                "provider": llm_result.provider,
                "latency_ms": llm_result.latency_ms,
            },
        }

        # Record real cost
        self.resource_bank.record_expense(
            llm_result.cost,
            f"LLM execute: {task['id']} ({llm_result.provider}/{llm_result.model})",
            category="llm",
            metadata={"tokens": llm_result.input_tokens + llm_result.output_tokens},
        )

        self.event_log.write(phase="executing_complete", event_id=event_id,
                              output_len=len(output),
                              tokens=llm_result.input_tokens + llm_result.output_tokens,
                              cost=llm_result.cost,
                              has_human_task=human_task is not None)
        return result

    @staticmethod
    def _async_navigate(url: str) -> Optional[dict]:
        """Navigate to a URL using async Playwright (thread-safe)."""
        import asyncio
        from playwright.async_api import async_playwright
        try:
            async def go():
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'],
                    )
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    title = await page.title()
                    content = await page.inner_text("body")
                    content = content[:3000]
                    screenshot = ""
                    try:
                        spath = str(Path(f"/tmp/screenshot_{int(time.time())}.png"))
                        await page.screenshot(path=spath)
                        screenshot = spath
                    except Exception:
                        pass
                    await browser.close()
                    return {"title": title, "content_snippet": content[:500], "screenshot": screenshot}
            return asyncio.run(go())
        except Exception as e:
            logger.warning(f"async_navigate({url}) failed: {e}")
            return None

    @staticmethod
    def _async_scrape(url: str) -> Optional[str]:
        """Scrape text content from a URL using async Playwright (thread-safe)."""
        import asyncio
        from playwright.async_api import async_playwright
        try:
            async def go():
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'],
                    )
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    content = await page.inner_text("body")
                    await browser.close()
                    return content[:5000]
            return asyncio.run(go())
        except Exception as e:
            logger.warning(f"async_scrape({url}) failed: {e}")
            return None

    def _execute_browser_actions(self, output: str, task: dict) -> str:
        """Execute real browser actions using AI-powered browser automation.

        Two modes:
        1. LLM outputs BROWSER: directives (simple actions)
        2. Task involves browser automation (sign-up, create account) → auto-dispatch

        Uses AgentBrowser (browser-use when available, Playwright fallback).
        """
        import re
        results = []

        # Mode 1: Explicit BROWSER directives from LLM output
        actions = re.findall(r'^BROWSER:\s*(\w+)\s*(?:\|\s*(.*?))?(?:\|\s*(.*?))?(?:\|\s*(.*?))?\s*$',
                             output, re.MULTILINE)

        # Mode 2: Auto-detect browser task from task description
        task_lower = (task.get("description", "") + " " + output).lower()
        signup_keywords = ["sign up", "create account", "register", "signup",
                           "apply for", "join", "enroll", "subscribe"]
        is_browser_task = any(kw in task_lower for kw in signup_keywords)

        if not actions and not is_browser_task:
            return ""

        try:
            from tools.agent_browser import AgentBrowser
        except ImportError:
            return ""

        browser = AgentBrowser()
        browser_results = []

        # Handle complex browser tasks (sign-up, account creation)
        if is_browser_task:
            # Build a detailed browser task from the LLM output + task description
            task_description = task.get("description", "")
            success_criteria = task.get("success_criteria", "")

            # Extract URLs from output and task
            urls = re.findall(r'https?://[^\s\)\"]+', output + " " + task_description)
            url_hint = urls[0] if urls else ""

            browser_task = f"{task_description}\n{success_criteria}"
            if url_hint:
                browser_task = f"Go to {url_hint}\n{browser_task}"
            browser_task += "\nTake screenshots at each step and report what happened."

            logger.info(f"Running browser task: {browser_task[:200]}...")
            task_result = browser.run_task(browser_task, max_steps=25)
            if task_result.get("success"):
                summary = task_result.get("summary", "")
                steps = task_result.get("steps", 0)
                step_log = task_result.get("step_log", [])
                browser_results.append(f"[BROWSER TASK] Completed in {steps} steps")
                browser_results.append(f"[RESULT] {summary[:1000]}")
                for s in step_log[-5:]:  # last 5 steps
                    thought = s.get("thought", "")[:200]
                    if thought:
                        browser_results.append(f"[STEP {s['step']}] {thought}")
            else:
                browser_results.append(f"[BROWSER TASK] Failed: {task_result.get('error', 'unknown')}")

        # Handle simple BROWSER directives
        for action, arg1, arg2, arg3 in actions:
            action = action.lower().strip()
            try:
                if action == "navigate":
                    url = arg1.strip() if arg1 else ""
                    if url:
                        nav = self._async_navigate(url)
                        if nav:
                            snippet = nav.get("content_snippet", "")[:500]
                            screenshot = nav.get("screenshot", "")
                            browser_results.append(f"[NAVIGATE] {url}: page loaded")
                            if screenshot:
                                browser_results.append(f"[SCREENSHOT] {screenshot}")
                        else:
                            browser_results.append(f"[NAVIGATE] {url}: FAILED")

                elif action == "scrape":
                    url = arg1.strip() if arg1 else ""
                    if url:
                        content = self._async_scrape(url)
                        if content:
                            browser_results.append(f"[SCRAPE] {url}: {len(content)} chars")
                            browser_results.append(content[:2000])
                        else:
                            browser_results.append(f"[SCRAPE] {url}: FAILED")

                elif action == "login_google":
                    email = arg1.strip() if arg1 else ""
                    password = arg2.strip() if arg2 else ""
                    if email and password:
                        try:
                            from tools.stealth_browser import login_google
                            login_result = login_google(email, password)
                        except Exception as login_e:
                            browser_results.append(f"[GOOGLE LOGIN] FAILED: {login_e}")
                            continue
                        if login_result:
                            ok = login_result.get("success", False)
                            browser_results.append(f"[GOOGLE LOGIN] {'OK' if ok else 'FAIL'}")
                            if login_result.get("screenshot"):
                                browser_results.append(f"[SCREENSHOT] {login_result['screenshot']}")

                elif action == "signup":
                    url = arg1.strip() if arg1 else ""
                    email = arg2.strip() if arg2 else ""
                    password = arg3.strip() if arg3 else ""
                    result = browser.sign_up_for_platform(url, email, password)
                    if result.get("success"):
                        browser_results.append(f"[SIGNUP] {url}: {result.get('summary','ok')[:500]}")
                    else:
                        browser_results.append(f"[SIGNUP] {url}: FAILED - {result.get('error','')}")

                elif action == "screenshot":
                    url = arg1.strip() if arg1 else "about:blank"
                    nav = self._async_navigate(url)
                    if nav and nav.get("screenshot"):
                        browser_results.append(f"[SCREENSHOT] {nav['screenshot']}")

                else:
                    # Unknown action — try running as a general browser task
                    generic_task = f"{action}: {arg1 or ''} {arg2 or ''} {arg3 or ''}"
                    result = browser.run_task(generic_task, max_steps=10)
                    if result.get("success"):
                        browser_results.append(f"[BROWSER] {result.get('summary','done')[:300]}")
                    else:
                        browser_results.append(f"[BROWSER] {action}: FAILED")

            except Exception as e:
                browser_results.append(f"[BROWSER ERROR] {action}: {str(e)[:100]}")

        return "\n".join(browser_results)

    # ── Phase: EVALUATING ───────────────────────────────────────────

    def _evaluate_output(self, task: dict, output: str) -> dict:
        """Critic evaluates worker output. Schema-forced JSON via tool-calling."""
        event_id = self.event_log.write(phase="evaluating_started", task_id=task["id"])

        prompt = f"""You are the CRITIC evaluating a Worker's output.

## Mission
{self.north_star}

## Task Assigned
{task['description']}

## Success Criteria
{task['success_criteria']}

## Worker Output
{output[:32000]}

## Evaluation Rubric
### 1. Speed to Revenue (highest priority)
- Does this output lead directly to money?
- Can it be executed immediately?
- COPYING is wrong — is this original work informed by competitor analysis?

### 2. Commercial Value
- Does this create a direct path to revenue?
- Does it build an asset that can be monetised?

### 3. Goal Alignment
- Does it move toward the mission?
- Is it concrete execution, not plans?

### 4. Integrity (pass/fail gate)
- Does it contain fabricated testimonials, fake reviews, or false urgency?
- Does it have honest disclosures (affiliate, sponsored)?
- If it reads like thin or spun content, flag it.
- Rule of thumb: would you be comfortable with your name on this?

Return your evaluation via the submit_evaluation function.
"""
        result = self._llm_call_structured(prompt, CRITIC_SCHEMA, role="critic",
                                            event_id=event_id)

        if not result:
            self.event_log.write(phase="evaluating_failed", event_id=event_id,
                                  error="critic returned no valid evaluation")
            return {
                "verdict": "failed",
                "score": 0,
                "weaknesses": ["Critic could not evaluate"],
                "feedback": "No valid evaluation from critic",
                "commercial_value": "None",
            }

        self.event_log.write(phase="evaluating_complete", event_id=event_id,
                              verdict=result.get("verdict"),
                              score=result.get("score"))
        return result

    # ── Phase: SHIPPING ─────────────────────────────────────────────

    def _ship_output(self, task: dict, output: str, critique: dict) -> Optional[str]:
        """Write output as an artifact. Returns path/URL or None."""
        event_id = self.event_log.write(phase="shipping_started", task_id=task["id"])

        action_type = task.get("action_type", "research")

        # Check if human approval is needed
        if action_type in APPROVAL_REQUIRED_ACTIONS:
            self.event_log.write(phase="shipping_blocked", event_id=event_id,
                                  action_type=action_type,
                                  reason="requires human approval")
            create_human_task(
                agent=self.agent.name,
                title=f"Approve: {task['description']}",
                url="",
                instructions=f"Task '{task['id']}' ({action_type}) needs your approval before shipping.\n\nOutput preview:\n{output[:500]}\n\nCritique: {critique.get('feedback', '')}",
                email=getattr(self.agent, 'email', ''),
            )
            return None

        # Write output as an artifact file
        out_dir = Path("artifacts") / self.agent.name / task["id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = out_dir / f"{ts}.md"
        filepath.write_text(output, encoding="utf-8")

        # Also write an index entry
        manifest_path = out_dir / "manifest.json"
        manifest = []
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.append({
            "timestamp": ts,
            "filename": filepath.name,
            "char_count": len(output),
            "critic_score": critique.get("score"),
            "critic_verdict": critique.get("verdict"),
        })
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        relative_path = str(filepath)
        self.event_log.write(phase="shipping_complete", event_id=event_id,
                              artifact_path=relative_path,
                              char_count=len(output))
        logger.info(f"{self.agent.name} | shipped artifact: {relative_path}")
        return relative_path

    # ── Main cycle: state machine ───────────────────────────────────

    def run_cycle(self, cycle_id: Optional[str] = None) -> dict:
        """One full state-machine cycle. Returns result dict."""
        cycle_id = cycle_id or str(uuid.uuid4())
        started_at = time.time()
        self.load_north_star()

        self.event_log.write(phase="cycle_started", cycle_id=cycle_id)

        # Check model availability
        if self._model_unavailable:
            if time.time() - self._model_failed_at > 120:
                logger.info(f"{self.agent.name} | retrying model after 120s cooldown")
                self._model_unavailable = False
            else:
                self.resource_bank.record_expense(0.0, "cycle skipped — model unavailable",
                                                   category="system")
                return {"output": None, "success": False, "idle": True,
                        "error": "Model unavailable", "cycle_id": cycle_id}

        # Get next task
        task = self._get_next_task()
        if not task:
            return {"output": None, "success": False, "idle": True, "cycle_id": cycle_id}

        task_id = task["id"]
        task["state"] = "PLANNING"
        self.revision_count = 0
        revision_hint = ""
        result = None  # ensure defined for error path

        # ── Revision loop ─────────────────────────────────────────────
        while self.revision_count <= self.max_revisions:
            task["state"] = "EXECUTING"

            # EXECUTING
            result = self._execute_task(task, revision_hint)
            if not result or not result.get("output"):
                self.memory.store_experience(
                    action=f"Worker failed: {task['description']}",
                    result={"success": False, "error": "No output"},
                    tags=task.get("tags", []) + ["worker_failed"],
                )
                self.event_log.write(phase="executing_failed", task_id=task_id,
                                      revision_count=self.revision_count)
                break

            output = result["output"]
            self.memory.record_attempt(task_id, output[:500])

            # Apply real cost to budget
            token_info = result.get("token_usage", {})
            if token_info.get("cost"):
                self.finance.add_expense(token_info["cost"], f"LLM: {task_id}", "llm")

            # EVALUATING
            task["state"] = "EVALUATING"
            critique = self._evaluate_output(task, output)
            verdict = critique.get("verdict", "needs_revision")
            score = critique.get("score", 0)

            logger.info(f"{self.agent.name} | {task_id} | verdict={verdict} score={score}/10")
            self.event_log.write(phase="evaluated", cycle_id=cycle_id,
                                  task_id=task_id, verdict=verdict, score=score)

            if verdict == "passed":
                # PASSED → SHIPPING
                task["state"] = "PASSED"

                # Check human tasks in output
                ht = result.get("human_task")
                if ht:
                    create_human_task(
                        agent=self.agent.name,
                        title=ht["title"],
                        url=ht["url"],
                        instructions=ht["instructions"],
                        email=getattr(self.agent, 'email', ''),
                    )

                # SHIPPING
                artifact_path = self._ship_output(task, output, critique)
                action_type = task.get("action_type", "research")

                if action_type in APPROVAL_REQUIRED_ACTIONS:
                    task["state"] = "AWAITING_APPROVAL"
                    self.memory.store_experience(
                        action=f"Task awaiting approval: {task['description']}",
                        result={"success": True, "output": output, "needs_approval": True},
                        tags=task.get("tags", []) + ["awaiting_approval"],
                    )
                    self.memory.update_task(task_id, {"status": "awaiting_approval"})
                    return {
                        "output": output,
                        "success": True,
                        "verdict": "awaiting_approval",
                        "critique": critique,
                        "artifact_path": artifact_path,
                        "cycle_id": cycle_id,
                        "token_usage": token_info,
                    }

                # DONE
                task["state"] = "DONE"
                self.memory.store_experience(
                    action=f"Task passed: {task['description']}",
                    result={"success": True, "output": output, "artifact": artifact_path},
                    tags=task.get("tags", []) + ["completed"],
                )
                self.memory.update_task(task_id, {"status": "completed"})
                self.memory.reset_frustration()

                duration_ms = (time.time() - started_at) * 1000
                self.event_log.write(phase="cycle_complete", cycle_id=cycle_id,
                                      task_id=task_id, verdict="passed",
                                      score=score, duration_ms=duration_ms,
                                      artifact_path=artifact_path,
                                      cost=token_info.get("cost", 0))

                return {
                    "output": output,
                    "success": True,
                    "verdict": "completed",
                    "critique": critique,
                    "score": score,
                    "artifact_path": artifact_path,
                    "cycle_id": cycle_id,
                    "token_usage": token_info,
                }

            elif verdict == "needs_revision":
                # NEEDS_REVISION → revise
                self.revision_count += 1
                self.memory.working["current_revision"] = self.revision_count

                if self.revision_count >= self.max_revisions:
                    logger.info(f"{self.agent.name} | max revisions ({self.max_revisions}) reached")
                    break

                # Generate revision instructions via schema
                revision_data = self._llm_call_structured(
                    self._build_revision_prompt(task, critique),
                    REVISION_SCHEMA,
                    role="supervisor",
                )
                if revision_data and revision_data.get("revision_instructions"):
                    revision_hint = "\n".join(f"- {h}" for h in revision_data["revision_instructions"])
                else:
                    revision_hint = critique.get("feedback", "Improve the output.")

                self.memory.store_experience(
                    action=f"Revision {self.revision_count}: {task['description']}",
                    result={"success": False, "output": output,
                            "feedback": critique.get("feedback", "")},
                    tags=task.get("tags", []) + ["revision"],
                )
                self.event_log.write(phase="revision", cycle_id=cycle_id,
                                      task_id=task_id,
                                      revision_count=self.revision_count)
                continue

            else:  # failed
                break

        # ── FAILED / DEAD_LETTER ───────────────────────────────────
        self.memory.increment_frustration()
        is_impossible = self.memory.get_frustration() >= self.frustration_threshold
        final_state = "DEAD_LETTER" if is_impossible else "FAILED"

        self.memory.store_experience(
            action=f"Task {final_state}: {task['description']}",
            result={"success": False, "output": (result.get("output", "") if result else "")},
            tags=task.get("tags", []) + [final_state.lower()],
        )
        self.memory.update_task(task_id, {"status": final_state.lower()})
        self.memory.reset_frustration()

        self.event_log.write(phase="cycle_complete", cycle_id=cycle_id,
                              task_id=task_id, verdict=final_state,
                              revision_count=self.revision_count)

        duration_ms = (time.time() - started_at) * 1000
        output = result.get("output") if result else None
        critique = locals().get("critique")

        return {
            "output": output,
            "success": False,
            "verdict": final_state.lower(),
            "critique": critique,
            "revisions": self.revision_count,
            "cycle_id": cycle_id,
            "duration_ms": duration_ms,
        }

    # ── Helpers ─────────────────────────────────────────────────────

    def _get_next_task(self) -> Optional[dict]:
        if self._model_unavailable:
            return self._fallback_task("LLM unavailable after retries")
        task = self.memory.get_next_task()
        if task:
            return task
        planned = self._plan_tasks()
        return planned[0] if planned else None

    def _fallback_task(self, reason: str) -> dict:
        return {
            "id": "wait_and_retry",
            "description": f"System paused: {reason}",
            "success_criteria": "Model becomes available again",
            "tags": ["system"],
            "action_type": "research",
            "state": "PENDING",
            "status": "pending", "attempts": 0, "revisions": 0,
        }

    def _build_revision_prompt(self, task: dict, critique: dict) -> str:
        feedback = critique.get("feedback", "Improve the output.")
        weaknesses = critique.get("weaknesses", [])
        w_list = "\n".join(f"- {w}" for w in weaknesses)
        return f"""You are the SUPERVISOR reviewing a Worker's failed submission.

Mission: {self.north_star}
Task: {task['description']}
Critique feedback: {feedback}
Weaknesses:
{w_list}

Generate 2-3 specific, actionable revision instructions for the Worker.
Focus on what to CHANGE, not just what's wrong.
Return via the submit_revision_instructions function.
"""

    def _get_wallet_report(self) -> str:
        try:
            from wallet import get_wallet
            return get_wallet(self.agent.name).get_wallet_report()
        except Exception:
            return ""

    # ── LLM calls ───────────────────────────────────────────────────

    def _llm_call(self, prompt: str, role: str = "worker",
                  max_tokens: int = 4096, event_id: str = "",
                  ) -> Optional[object]:
        """Raw LLM call via router with retry + semaphore. Returns LLMResult or None."""
        acquired = _llm_semaphore.acquire(timeout=60)
        if not acquired:
            logger.warning(f"{self.agent.name} | semaphore timeout (60s)")
            return None

        try:
            from providers.router import LLMRouter
            llm = LLMRouter()
            result = llm.complete(
                prompt=prompt,
                system="You are an autonomous AI agent. Execute your purpose.",
                max_tokens=max_tokens,
            )
            if result:
                self._model_unavailable = False
                self._model_failed_at = 0
                self.event_log.write(phase="llm_call", event_id=event_id or "",
                                      ok=True, role=role,
                                      tokens=result.input_tokens + result.output_tokens,
                                      cost=result.cost,
                                      latency_ms=result.latency_ms,
                                      provider=result.provider,
                                      model=result.model)
                return result

            self._model_unavailable = True
            self._model_failed_at = time.time()
            self.event_log.write(phase="llm_call", event_id=event_id or "",
                                  ok=False, role=role, error="all providers failed")
            return None
        finally:
            _llm_semaphore.release()

    def _llm_call_structured(self, prompt: str, schema: dict,
                              role: str = "supervisor",
                              event_id: str = "") -> Optional[dict]:
        """Call LLM with schema-forced JSON output via tool calling."""
        acquired = _llm_semaphore.acquire(timeout=60)
        if not acquired:
            logger.warning(f"{self.agent.name} | semaphore timeout (60s), skipping {role}")
            return None

        try:
            from providers.router import LLMRouter
            llm = LLMRouter()
            result = llm.complete_structured(
                prompt=prompt,
                schema=schema,
                system="You are an autonomous AI agent. Return the required schema precisely.",
                max_tokens=65536,
            )
            if result:
                self._model_unavailable = False
                self._model_failed_at = 0
                self.event_log.write(phase="llm_call_structured", event_id=event_id or "",
                                      ok=True, role=role)
                return result

            self._model_unavailable = True
            self._model_failed_at = time.time()
            self.event_log.write(phase="llm_call_structured", event_id=event_id or "",
                                  ok=False, role=role, error="all providers failed")
            return None
        finally:
            _llm_semaphore.release()
