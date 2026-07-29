"""AI-powered browser automation for agents.
Uses browser-use when available, falls back to Playwright directly.
The agent can perform real sign-ups, form-filling, and account creation.
"""
import json
import time
import random
import re
from pathlib import Path
from typing import Optional
from loguru import logger

# Try to import browser-use (primary driver)
try:
    from browser_use import Agent as BrowserAgent
    from browser_use.controller.service import Controller as BrowserController
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

# Always need Playwright (fallback + browser-use uses it too)
from playwright.sync_api import Page, BrowserContext

from tools.stealth_browser import (
    _get_browser, new_context, random_delay, human_type,
    navigate_to_url, scrape_url, login_google, login_and_collect,
)


SCREENSHOTS_DIR = Path("data") / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class AgentBrowser:
    """AI-powered browser that can autonomously perform multi-step web tasks.

    Uses browser-use for complex workflows (sign-ups, form-filling, account creation).
    Falls back to direct Playwright for simple actions (navigate, scrape, screenshot).
    """

    def __init__(self, llm_config: Optional[dict] = None):
        self.llm_config = llm_config or {
            "model": "deepseek-ai/deepseek-v4-flash",
            "provider": "nvidia",
            "api_key": "",  # set via env
            "base_url": "https://integrate.api.nvidia.com/v1",
        }
        self._context: Optional[BrowserContext] = None

    # ── browser-use integration ─────────────────────────────────────

    def run_task(self, task: str, max_steps: int = 20) -> dict:
        """Run a complex browser task using browser-use AI agent.

        The agent autonomously navigates pages, fills forms, clicks buttons,
        and interacts with websites to complete the given task.

        Example tasks:
        - "Go to amazon.com/associates and sign up for the affiliate program"
        - "Navigate to shareasale.com, search for 'web hosting', note the top 3 programs"
        - "Log into the Fiverr dashboard and check new messages"

        Returns dict with success, summary, screenshot_path, and step_log.
        """
        if BROWSER_USE_AVAILABLE:
            return self._run_via_browser_use(task, max_steps)
        return self._run_via_playwright(task, max_steps)

    def _run_via_browser_use(self, task: str, max_steps: int) -> dict:
        """Use browser-use Agent for autonomous browser control."""
        pw, browser = _get_browser()
        context = new_context()
        try:
            controller = BrowserController()
            agent = BrowserAgent(
                task=task,
                controller=controller,
                llm=self._make_llm_config(),
                browser=browser,
                use_vision=True,
                max_steps=max_steps,
            )
            result = agent.run()
            steps_log = []
            for hist in result.history or []:
                steps_log.append({
                    "step": hist.step_number,
                    "action": hist.action or "",
                    "thought": hist.thought or "",
                })
            summary = result.extracted_content or "Task completed by browser agent"
            return {
                "success": True,
                "summary": summary,
                "steps": len(steps_log),
                "step_log": steps_log,
                "agent": "browser-use",
            }
        except Exception as e:
            logger.error(f"browser-use task failed: {e}")
            return {"success": False, "error": str(e), "agent": "browser-use"}
        finally:
            try:
                context.close()
            except Exception:
                pass

    def _run_via_playwright(self, task: str, max_steps: int) -> dict:
        """Fallback: use direct Playwright for simpler tasks.

        This interprets the task and executes basic browser actions.
        """
        task_lower = task.lower()
        context = new_context()
        page = context.new_page()
        results = []

        try:
            # Extract URLs from the task
            urls = re.findall(r'https?://[^\s\)\"]+', task)

            if "login" in task_lower:
                if "google" in task_lower:
                    email_match = re.search(r'[\w\.-]+@[\w\.-]+', task)
                    email = email_match.group() if email_match else ""
                    password_match = re.search(r'password[:\s]+(\S+)', task, re.IGNORECASE)
                    password = password_match.group(1) if password_match else ""
                    if email and password:
                        result = login_google(email, password)
                        context.close()
                        return result or {"success": False, "error": "Google login failed"}
                platform_match = re.search(r'(fiverr|upwork|medium|gumroad)', task_lower)
                if platform_match:
                    platform = platform_match.group(1)
                    email_match = re.search(r'[\w\.-]+@[\w\.-]+', task)
                    email = email_match.group() if email_match else ""
                    password_match = re.search(r'password[:\s]+(\S+)', task, re.IGNORECASE)
                    password = password_match.group(1) if password_match else ""
                    if email and password:
                        result = login_and_collect(platform, email, password)
                        context.close()
                        return result or {"success": False, "error": f"Login to {platform} failed"}

            # Navigate to URLs and scrape content
            for url in urls[:3]:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    random_delay(2, 4)
                    title = page.title()
                    content = page.inner_text("body")[:3000]
                    screenshot = str(SCREENSHOTS_DIR / f"visit_{int(time.time())}.png")
                    try:
                        page.screenshot(path=screenshot)
                    except Exception:
                        screenshot = ""
                    results.append({
                        "url": url, "title": title,
                        "content_snippet": content[:500],
                        "screenshot": screenshot,
                    })
                except Exception as e:
                    results.append({"url": url, "error": str(e)[:80]})

            context.close()
            return {
                "success": len(results) > 0,
                "results": results,
                "summary": f"Visited {len(results)} URLs, extracted content",
                "agent": "playwright-direct",
            }

        except Exception as e:
            logger.error(f"Playwright fallback failed: {e}")
            try:
                context.close()
            except Exception:
                pass
            return {"success": False, "error": str(e)[:200]}

    # ── Helper: Sign-up / account creation ──────────────────────────

    def sign_up_for_platform(self, platform_url: str,
                              email: str, password: str,
                              profile_data: dict = None) -> dict:
        """Autonomous sign-up: navigate to platform, fill registration form, submit.

        Uses browser-use agent for the multi-step form-filling workflow.
        """
        task_parts = [
            f"Go to {platform_url}",
            f"Click the sign up or register button",
            f"Fill in the registration form with:",
            f"- Email: {email}",
            f"- Password: {password}",
        ]
        if profile_data:
            for key, val in profile_data.items():
                task_parts.append(f"- {key}: {val}")
        task_parts.append("Submit the registration form")
        task_parts.append("Wait for the confirmation page to load")
        task_parts.append("Take a screenshot of the result")
        task = "\n".join(task_parts)
        return self.run_task(task, max_steps=30)

    def extract_data_from_page(self, url: str, description: str) -> dict:
        """Navigate to a URL and extract data based on a description.

        Example: extract affiliate program details, pricing, commission rates.
        """
        task = f"Go to {url}\n{description}\nExtract the requested information and return it."
        return self.run_task(task, max_steps=10)

    # ── LLM config for browser-use ──────────────────────────────────

    def _make_llm_config(self):
        """Create LLM configuration dict for browser-use Agent."""
        return {
            "model": self.llm_config.get("model", "deepseek-ai/deepseek-v4-flash"),
            "provider": self.llm_config.get("provider", "nvidia"),
            "api_key": self.llm_config.get("api_key", ""),
            "base_url": self.llm_config.get("base_url", "https://integrate.api.nvidia.com/v1"),
            "temperature": self.llm_config.get("temperature", 0.1),
            "max_tokens": self.llm_config.get("max_tokens", 4096),
        }

    def cleanup(self):
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None


# ── Module-level convenience ────────────────────────────────────────

_agent_browser: Optional[AgentBrowser] = None


def get_agent_browser() -> AgentBrowser:
    global _agent_browser
    if _agent_browser is None:
        _agent_browser = AgentBrowser()
    return _agent_browser


def browser_task(task: str, max_steps: int = 20) -> dict:
    """One-shot convenience: run a browser task and return result."""
    return get_agent_browser().run_task(task, max_steps)


def browser_signup(platform_url: str, email: str, password: str,
                    profile_data: dict = None) -> dict:
    """One-shot convenience: sign up for a platform."""
    return get_agent_browser().sign_up_for_platform(
        platform_url, email, password, profile_data
    )
