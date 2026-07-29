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
import re
import time
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime
from loguru import logger
from resource_bank import ResourceBank
from finance_layer import FinanceLayer, create_human_task, get_pending_tasks
HUMAN_TASK_PATTERN = re.compile(
    r'HUMAN_TASK:\s*(?P<title>[^|]+)\s*\|\s*(?P<url>[^|]+)\s*\|\s*(?P<instructions>.+)',
    re.IGNORECASE,
)


# Global concurrency control — all agents share these
_llm_semaphore = threading.Semaphore(3)  # max 3 concurrent LLM calls (stay under 35/key/min)
_agent_run_lock = threading.Lock()
_running_agents = {}  # agent_name -> thread


CRITIC_RUBRIC = """## Value Assessment Protocol — URGENT: We need revenue NOW

Evaluate the submitted work against these criteria, but priority is SPEED TO REVENUE:

### 1. Speed to Revenue (highest priority)
- Does this output lead directly to money within hours, not days?
- Can it be executed immediately without waiting for accounts/permissions?
- Is it a SHORTCUT that produces cash fast?
- COPY what already works — do NOT innovate or create from scratch

### 2. Commercial Value (pass/fail)
- Does this create a DIRECT path to revenue or cost reduction?
- Does this build an ASSET that can be monetised?
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
        self.resource_bank = ResourceBank(agent.name)
        self.finance = FinanceLayer(agent.name)
        self._model_unavailable = False

    def _get_wallet_report(self) -> str:
        try:
            from wallet import get_wallet
            return get_wallet(self.agent.name).get_wallet_report()
        except Exception:
            return ""

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
        if self._model_unavailable:
            logger.warning(f"{self.agent.name} | model unavailable, skip plan")
            return [self._fallback_task("Model unavailable — waiting for retry")]

        self.load_north_star()

        pending = self.memory.pending_tasks()
        if pending:
            return pending

        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()
        wallet_report = self._get_wallet_report()

        prompt = f"""You are the SUPERVISOR. Your mission:

{self.north_star}

{resource_report}

{finance_report}

{wallet_report}

CRITICAL: This is URGENT. We need money NOW. Not tomorrow, not next week.

Decompose this mission into 3-5 concrete sub-tasks. Each sub-task must:

1. Be specific and actionable by a Worker agent
2. Have a clear "done" criterion
3. Produce a tangible output (research, analysis, plan, asset)
4. PRIORITIZE the shortest path to revenue above all else
5. DO NOT generate anything from scratch. Your job is to:
   - Find what already works (competitors, top sellers, trending content)
   - COPY IT HEAVILY — rip the structure, format, and angle
   - Personalise it just enough to avoid plagiarism
   - Adapt for your specific audience/niche
6. For content: find top-performing examples, steal their hook, rewrite in your voice
7. For code: find working GitHub repos, fork and modify
8. For business: find successful competitors, clone their model
9. BE REALISTIC about the agent's resources. If it has no browser, no accounts, no API keys beyond LLM access, plan tasks that can be done with LLM + web search only.
10. If the agent HAS a real browser, plan tasks that involve visiting real websites:
   - Scraping competitor pricing and offerings
   - Finding real freelance gigs to underbid
   - Extracting real data from marketplaces

CRITICAL: You have ${self.resource_bank.balance:.2f}. All tasks must cost $0 to execute.
Priority is REVENUE — pick the task with the shortest path to money.

Return ONLY a JSON array of objects:
  {{"id":"task_unique_name","description":"what to do","success_criteria":"how to verify","tags":["tag1","tag2"],"constraints":"any specific constraints"}}

Example:
[{{"id":"research_market","description":"Research top-performing affiliate programs for crypto trading","success_criteria":"List of 5 programs with commission rates and requirements","tags":["research","affiliate"],"constraints":"Focus on programs that pay in crypto"}}]
"""
        output = self._call_llm(prompt, role="supervisor")
        if output:
            # Try to parse as JSON first
            cleaned = output.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
                cleaned = cleaned.strip()
            try:
                tasks = json.loads(cleaned)
                if isinstance(tasks, list):
                    for t in tasks:
                        t.setdefault("status", "pending")
                        t.setdefault("attempts", 0)
                        t.setdefault("revisions", 0)
                        self.memory.add_task(t)
                    return tasks
            except (json.JSONDecodeError, TypeError):
                pass

            # Fallback: extract tasks from free text
            logger.info(f"{self.agent.name} | supervisor returned non-JSON, extracting from text")
            extracted = self._extract_tasks_from_text(output)
            if extracted:
                for t in extracted:
                    t.setdefault("status", "pending")
                    t.setdefault("attempts", 0)
                    t.setdefault("revisions", 0)
                    self.memory.add_task(t)
                return extracted

        fallback = [{
            "id": "execute_mission",
            "description": self.north_star or "Execute your purpose",
            "success_criteria": "Make measurable progress toward the goal",
            "tags": ["mission"],
            "status": "pending", "attempts": 0, "revisions": 0,
        }]
        self.memory.add_task(fallback[0])
        return fallback

    def _extract_tasks_from_text(self, text: str) -> list[dict]:
        """Extract sub-tasks from free-form supervisor output.
        Tries multiple extraction strategies in order.
        """
        tasks = []

        # Strategy 1: look for markdown list items with task descriptions
        lines = text.split("\n")
        current_task = {}
        for line in lines:
            stripped = line.strip()
            # Match numbered lists like "1. Do something" or bullet lists like "- Do something"
            list_match = re.match(r'^(?:\d+[.)]\s*|[-*]\s+)(.+)$', stripped)
            if list_match:
                if current_task and current_task.get("description"):
                    tasks.append(current_task)
                desc = list_match.group(1).strip()
                current_task = {
                    "id": re.sub(r'[^a-z0-9_]', '_', desc.lower().replace(' ', '_'))[:50],
                    "description": desc,
                    "success_criteria": "Complete this task with tangible output",
                    "tags": ["extracted"],
                }
            elif stripped and current_task:
                # continuation of previous item (e.g. wrapped line)
                current_task["description"] += " " + stripped

        if current_task and current_task.get("description"):
            tasks.append(current_task)

        # Strategy 2: if no list found, split by double newlines into paragraphs
        if not tasks:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            for i, para in enumerate(paragraphs[:5]):
                if len(para) > 50:
                    tasks.append({
                        "id": f"task_{i+1}",
                        "description": para[:200],
                        "success_criteria": "Complete this task",
                        "tags": ["extracted"],
                    })

        # Strategy 3: if still nothing, make the whole output one task
        if not tasks and len(text) > 50:
            tasks.append({
                "id": "execute_mission",
                "description": text[:300],
                "success_criteria": "Make measurable progress",
                "tags": ["extracted", "mission"],
            })

        return tasks

    # ── SUPERVISOR: Generate revision feedback ─────────────────────

    def supervisor_revise(self, task: dict, critique: dict) -> str:
        """Supervisor generates specific revision instructions."""
        feedback = critique.get("feedback", "Improve the output.")
        weaknesses = critique.get("weaknesses", [])
        w_list = "\n".join(f"- {w}" for w in weaknesses)
        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()

        prompt = f"""You are the SUPERVISOR reviewing a Worker's failed submission.

Mission: {self.north_star}
Task: {task['description']}
{resource_report}
{finance_report}
Critique feedback: {feedback}
Weaknesses identified:
{w_list}

Generate 2-3 specific, actionable revision instructions for the Worker.
Focus on what to CHANGE, not just what's wrong.
Consider the agent's actual resources — if it has no browser/accounts,
focus on what CAN be done with LLM + search only.
Return a JSON object:
  {{"revision_instructions":["instruction 1","instruction 2","instruction 3"],"priority":"what to focus on first"}}
"""
        result = self._call_llm(prompt, role="supervisor")
        if result:
            try:
                return json.loads(result).get("revision_instructions", [result])
            except json.JSONDecodeError:
                return [result]
        return ["Improve the output based on the critique feedback."]

    # ── WORKER: Browser actions ─────────────────────────────────────

    def _execute_browser_actions(self, task: dict) -> list[dict]:
        """Execute REAL browser actions based on the task.
        Returns list of action results (screenshots, login confirmations, scraped data).
        """
        results = []
        try:
            from tools.stealth_browser import check_browser_available, login_google, navigate_to_url, search_gigs, scrape_url
        except ImportError as e:
            logger.warning(f"{self.agent.name} | stealth_browser not available: {e}")
            return results

        try:
            if not check_browser_available():
                logger.warning(f"{self.agent.name} | browser not available on this host")
                return results
        except Exception as e:
            logger.warning(f"{self.agent.name} | browser check failed: {e}")
            return results

        email = getattr(self.agent, 'email', '')
        password = "markchomba"
        agent_name = self.agent.name

        if email:
            # Note: Google login is skipped because headless browsers get challenge-blocked.
            # Instead we use a lightweight approach: check the session & do public web actions.
            results.append({
                "action": "google_login",
                "success": False,
                "email": email,
                "detail": "Skipped — headless login blocked by Google. Using public web actions instead.",
            })

        # Step 2: Execute lightweight browser actions on public websites
        # (Skip Google login — headless browsers always get challenged)
        task_desc = task.get("description", "").lower()
        task_tags = [t.lower() for t in task.get("tags", [])]

        # Lightweight public URLs that work in headless mode
        # Each agent visits a lightweight page relevant to their domain
        relevant_pages = {
            "contentcreator": "https://en.wikipedia.org/wiki/Content_creation",
            "videocreator": "https://en.wikipedia.org/wiki/Video_production",
            "affiliatemarketer": "https://en.wikipedia.org/wiki/Affiliate_marketing",
            "cryptotrader": "https://en.wikipedia.org/wiki/Cryptocurrency_trading",
            "defioptimizer": "https://en.wikipedia.org/wiki/Decentralized_finance",
            "ecommercemerechant": "https://en.wikipedia.org/wiki/E-commerce",
            "freelanceoptimizer": "https://en.wikipedia.org/wiki/Freelance_workplace",
            "dataarbitrageur": "https://en.wikipedia.org/wiki/Data_entry",
            "serviceprovider": "https://en.wikipedia.org/wiki/Service_provider",
            "saasbuilder": "https://en.wikipedia.org/wiki/Software_as_a_service",
            "socialmediamonetizer": "https://en.wikipedia.org/wiki/Social_media_marketing",
            "platformmonetizer": "https://en.wikipedia.org/wiki/Digital_platform",
        }
        target_url = ""
        for name_key, url in relevant_pages.items():
            if name_key in agent_name.lower().replace(" ", ""):
                target_url = url
                break

        if target_url:
            try:
                visit_result = navigate_to_url(target_url, wait_seconds=3)
                if visit_result:
                    results.append({
                        "action": "navigate",
                        "url": target_url,
                        "title": visit_result.get("title", ""),
                        "content_snippet": visit_result.get("content_snippet", "")[:2000],
                        "success": True,
                    })
                    logger.info(f"{self.agent.name} | Visited {target_url} — title: {visit_result.get('title','')[:60]}")
                else:
                    logger.warning(f"{self.agent.name} | navigate_to_url returned None for {target_url}")
            except Exception as e:
                logger.debug(f"{self.agent.name} | navigate error: {e}: {target_url}")
        else:
            logger.debug(f"{self.agent.name} | no target URL for agent type")

        return results

    # ── WORKER: Execute ────────────────────────────────────────────

    def worker_execute(self, task: dict, revision_hint: str = "") -> dict:
        """Worker executes a sub-task and submits output.
        Includes REAL browser actions so the agent actually does things.
        """
        if self._model_unavailable:
            return {"output": None, "success": False, "error": "Model unavailable after retries"}

        relevant = self.memory.query_memory(task.get("description", ""), limit=3)
        revision = self.memory.working.get("current_revision", 0)
        tried = self.memory.tried_approaches_for(task["id"])

        # Fetch real web search results for the task
        search_results = []
        try:
            from tools.web_search import web_search
            search_results = web_search(task["description"], max_results=5)
        except Exception:
            pass

        # Execute REAL browser actions (login, navigate, search)
        browser_actions = self._execute_browser_actions(task)
        browser_logged_in = any(
            b.get("action") == "google_login" and b.get("success")
            for b in browser_actions
        )

        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()
        wallet_report = self._get_wallet_report()

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
                f"{'[OK]' if e['success'] else '[FAIL]'} {e['action'][:300]}"
                for e in relevant
            )
            parts.append(f"## PAST EXPERIENCES\n{mem}")

        if tried:
            parts.append("## APPROACHES ALREADY TRIED (avoid repeating)")
            parts.extend(f"- {a}" for a in tried)

        if revision > 0:
            parts.append(f"\nThis is revision {revision}. Make sure your output addresses ALL previous feedback.")

        parts.append(resource_report)
        parts.append(finance_report)
        parts.append(wallet_report)

        # Include real browser action results in the prompt
        if browser_actions:
            browser_block_parts = ["## REAL BROWSER ACTIONS (you actually did these)"]
            for ba in browser_actions:
                act = ba.get("action", "?")
                ok = "OK" if ba.get("success") else "FAIL"
                detail = ba.get("detail", "") or ba.get("error", "") or ba.get("title", "") or ""
                screenshot = ba.get("screenshot", "") or ba.get("url", "") or ""
                browser_block_parts.append(f"- [{ok}] {act}: {detail} | {screenshot}")
                if ba.get("results"):
                    for g in ba["results"][:3]:
                        browser_block_parts.append(f"  -> {g.get('title','')[:80]} - {g.get('price','')} ({g.get('platform','')})")
            parts.append("\n".join(browser_block_parts))

        if search_results:
            search_block = "\n".join(
                f"- {r['title']}: {r['url']}" for r in search_results[:5]
            )
            parts.append(f"## REAL SEARCH RESULTS (use these instead of guessing)\n{search_block}")

        parts.append("""## OUTPUT REQUIREMENTS — URGENT: Revenue needed NOW
1. Provide concrete output — NOT just plans or ideas. We need MONEY.
2. HEAVILY COPY competitors. Find what works, rip the structure, personalise the voice.
3. Cite REAL sources from the search results above. DO NOT make up URLs.
4. If no search results are available, provide search queries the user can use
5. If you need a HUMAN to do something (sign up for a platform, solve a captcha, etc.),
   include this EXACT line in your output:
   HUMAN_TASK: What needs doing | https://signup-url.com | Instructions for the human
6. End with SUBMISSION: followed by a brief summary of what you produced
7. EVERY output must answer: "How does this make money RIGHT NOW?"

## OUTPUT
""")

        prompt = "\n\n".join(parts)
        result_text = self._call_llm(prompt, role="worker")
        if result_text:
            # Append real browser results to output so they're visible in chat history
            browser_appendix = ""
            if browser_actions:
                appendix_lines = ["\n\n---\n## REAL BROWSER RESULTS"]
                for ba in browser_actions:
                    act = ba.get("action", "?")
                    ok = "PASS" if ba.get("success") else "FAIL"
                    detail = ba.get("detail", "") or ba.get("title", "") or ba.get("error", "") or ""
                    url_info = ba.get("screenshot", "") or ba.get("url", "") or ""
                    appendix_lines.append(f"- [{ok}] {act}: {detail}")
                    if url_info:
                        appendix_lines.append(f"  Evidence: {url_info}")
                    if ba.get("results"):
                        appendix_lines.append(f"  Found {ba['count']} real gigs:")
                        for g in ba["results"][:5]:
                            appendix_lines.append(f"  - {g.get('title','')} | {g.get('price','')} | {g.get('platform','')}")
                browser_appendix = "\n".join(appendix_lines)

            combined_output = result_text + browser_appendix
            result = {"output": combined_output, "success": True}
            result["browser_actions"] = browser_actions
            m = HUMAN_TASK_PATTERN.search(result_text)
            if m:
                result["human_task"] = {
                    "title": m.group("title").strip(),
                    "url": m.group("url").strip(),
                    "instructions": m.group("instructions").strip(),
                }
            return result
        return {"output": None, "success": False, "error": "Worker returned no output"}

    # ── CRITIC: Evaluate ───────────────────────────────────────────

    def critic_evaluate(self, task: dict, output: str) -> dict:
        """Critic evaluates Worker output against rubric."""
        resource_report = self.resource_bank.get_status_report()
        finance_report = self.finance.get_finance_report()
        prompt = f"""You are the CRITIC. Your job is to evaluate the Worker's output against a strict rubric.

## Mission
{self.north_star}

## Task Assigned
{task['description']}

## Success Criteria
{task['success_criteria']}

## Agent Resource Context
{resource_report}

## Finance Context
{finance_report}

## Worker Output
{output[:32000]}

{CRITIC_RUBRIC}
"""
        result = self._call_llm(prompt, role="critic")
        if result:
            # Strip markdown code fences that LLMs often wrap JSON in
            cleaned = result.strip()
            if cleaned.startswith("```"):
                # Remove ```json ... ``` or ``` ... ``` fences
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
                cleaned = cleaned.strip()
            try:
                critique = json.loads(cleaned)
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

    def _fallback_task(self, reason: str) -> dict:
        return {
            "id": "wait_and_retry",
            "description": f"System paused: {reason}",
            "success_criteria": "Model becomes available again",
            "tags": ["system"],
            "status": "pending", "attempts": 0, "revisions": 0,
        }

    def get_next_task(self) -> Optional[dict]:
        if self._model_unavailable:
            logger.warning(f"{self.agent.name} | model unavailable, returning wait task")
            return self._fallback_task("LLM unavailable after retries")

        task = self.memory.get_next_task()
        if task:
            return task
        planned = self.supervisor_plan()
        return planned[0] if planned else None

    def run_cycle(self) -> dict:
        """One full Supervisor -> Worker -> Critic workflow cycle."""
        self.load_north_star()

        # Periodically retry the model if it was previously unavailable
        if self._model_unavailable:
            if time.time() - getattr(self, '_model_failed_at', 0) > 120:
                logger.info(f"{self.agent.name} | retrying model after 120s cooldown")
                self._model_unavailable = False
            else:
                self.resource_bank.record_expense(0.0, "cycle skipped — model unavailable",
                                                   category="system")
                return {"output": None, "success": False, "idle": True,
                        "error": "Model unavailable"}

        task = self.get_next_task()
        if not task:
            return {"output": None, "success": False, "idle": True}

        # Record cycle cost in resource bank
        self.resource_bank.record_expense(0.001, f"cycle start: {task['id']}",
                                           category="compute")
        self.finance.add_expense(0.001, f"cycle: {task['id']}", "compute")

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
                # Create human tasks only after Critic approves output
                ht = result.get("human_task")
                if ht:
                    create_human_task(
                        agent=self.agent.name,
                        title=ht["title"],
                        url=ht["url"],
                        instructions=ht["instructions"],
                        email=getattr(self.agent, 'email', ''),
                    )
                result["critique"] = critique
                result["verdict"] = "completed"
                return result

            elif verdict == "needs_revision":
                # REVISE: supervisor generates feedback, worker retries
                self.revision_count += 1
                self.memory.working["current_revision"] = self.revision_count
                self.memory.record_attempt(task["id"], result["output"][:500])

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
        self.resource_bank.record_expense(
            0.0, f"task failed: {task['id']} ({self.revision_count} revisions)",
            category="failed_task"
        )
        self.finance.add_expense(0.0, f"task failed: {task['id']}", "failed")

        return {
            "output": result.get("output"),
            "success": False,
            "verdict": "impossible" if self.memory.get_frustration() >= self.frustration_threshold else "failed",
            "critique": critique if 'critique' in locals() else None,
            "revisions": self.revision_count,
        }

    # ── LLM call with retries ──────────────────────────────────────

    def _call_llm(self, prompt: str, role: str = "worker",
                  max_retries: int = 2) -> Optional[str]:
        """Call LLM with retry loop. Uses global semaphore for concurrency.

        Each failed attempt increments cost in ResourceBank.
        After max_retries, sets _model_unavailable flag so the cycle can abort.
        """
        acquired = _llm_semaphore.acquire(timeout=60)
        if not acquired:
            logger.warning(f"{self.agent.name} | semaphore timeout (60s), retrying...")
            _llm_semaphore.acquire(timeout=120)

        try:
            for attempt in range(1, max_retries + 1):
                result = self.agent._execute_via_hermes(prompt, role=role)
                output = result.get("output")

                if output:
                    self._model_unavailable = False
                    self._model_failed_at = 0
                    est_cost = self.resource_bank.cost_estimate(
                        "hf" if role in ("supervisor", "critic") else "nvidia",
                        tokens=len(prompt.split()) + len(output.split()),
                    )
                    self.resource_bank.record_expense(est_cost, f"LLM call ({role})",
                                                       category="llm")
                    return output

                error = result.get("error", "No output")
                logger.warning(f"{self.agent.name} | {role} attempt {attempt}/{max_retries} failed: {error}")

                if attempt < max_retries:
                    backoff = attempt  # 1s, 2s
                    logger.info(f"{self.agent.name} | retrying {role} in {backoff}s...")
                    time.sleep(backoff)

            self._model_unavailable = True
            self._model_failed_at = time.time()
            logger.error(f"{self.agent.name} | {role} failed after {max_retries} retries")
            return None
        finally:
            _llm_semaphore.release()
