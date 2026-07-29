"""AI-powered browser automation for agents.
Uses browser-use when available, falls back to Playwright directly.
All Playwright operations run via asyncio to avoid greenlet thread-safety issues.
"""
import asyncio
import json
import os
import time
import random
import re
from pathlib import Path
from typing import Optional
from loguru import logger


SCREENSHOTS_DIR = Path("data") / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class AgentBrowser:
    """AI-powered browser that can autonomously perform multi-step web tasks.

    Uses browser-use for complex workflows (sign-ups, form-filling, account creation).
    Falls back to direct Playwright for simple actions (navigate, scrape, screenshot).
    All Playwright calls are bridged through asyncio for thread-safety.
    """

    def __init__(self, llm_config: Optional[dict] = None, tier: str = "cheap"):
        self.tier = tier
        self.llm_config = llm_config or self._default_llm_config(tier)
        self._browser_use_available = self._check_browser_use()

    def _check_browser_use(self) -> bool:
        try:
            from browser_use import Agent as BrowserAgent
            from browser_use.controller.service import Controller as BrowserController
            return True
        except ImportError:
            return False

    # ── Public API ───────────────────────────────────────────────────

    def run_task(self, task: str, max_steps: int = 20) -> dict:
        """Run a complex browser task.

        Uses browser-use when available, falls back to direct Playwright.
        """
        if self._browser_use_available:
            return asyncio.run(self._run_via_browser_use_async(task, max_steps))
        return asyncio.run(self._run_via_playwright_async(task, max_steps))

    def sign_up_for_platform(self, platform_url: str,
                              email: str, password: str,
                              profile_data: dict = None) -> dict:
        """Autonomous sign-up: navigate to platform, fill registration form, submit."""
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

    def extract_data_from_page(self, url: str, description: str, tier: str = "cheap") -> dict:
        """Navigate to a URL and extract data based on a description (uses Gemini by default)."""
        task = f"Go to {url}\n{description}\nExtract the requested information and return it."
        return self.run_task(task, max_steps=10)

    @staticmethod
    def _default_llm_config(tier: str = "cheap") -> dict:
        """Pick the right model for browser-use based on tier.
        cheap = Gemini 2.5 Flash (fast, free, good for extraction)
        powerful = NVIDIA DeepSeek V4 Flash (smart, for complex navigation)
        """
        if tier == "cheap":
            return {
                "model": "gemini-2.5-flash",
                "provider": "gemini",
                "api_key": os.environ.get("GEMINI_API_KEY", ""),
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "temperature": 0.1,
                "max_tokens": 4096,
            }
        return {
            "model": "deepseek-ai/deepseek-v4-flash",
            "provider": "nvidia",
            "api_key": os.environ.get("NVIDIA_API_KEY", ""),
            "base_url": "https://integrate.api.nvidia.com/v1",
            "temperature": 0.1,
            "max_tokens": 4096,
        }

    def cleanup(self):
        pass

    # ── browser-use path (async) ────────────────────────────────────

    async def _run_via_browser_use_async(self, task: str, max_steps: int) -> dict:
        """Use browser-use Agent for autonomous browser control (async)."""
        from playwright.async_api import async_playwright
        from browser_use import Agent as BrowserAgent
        from browser_use.controller.service import Controller as BrowserController

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox'],
            )
            context = await browser.new_context()
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
                result = await agent.run()
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
                    await context.close()
                    await browser.close()
                except Exception:
                    pass

    # ── Playwright fallback path (async) ────────────────────────────

    async def _run_via_playwright_async(self, task: str, max_steps: int) -> dict:
        """Fallback: use direct Playwright for simpler tasks (async)."""
        from playwright.async_api import async_playwright

        task_lower = task.lower()
        results = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox'],
            )
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Extract URLs from the task
                urls = re.findall(r'https?://[^\s\)\"]+', task)

                # Navigate to URLs and scrape content
                for url in urls[:3]:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(random.uniform(2, 4))
                        title = await page.title()
                        content = await page.inner_text("body")
                        content = content[:3000]
                        screenshot = str(SCREENSHOTS_DIR / f"visit_{int(time.time())}.png")
                        try:
                            await page.screenshot(path=screenshot)
                        except Exception:
                            screenshot = ""
                        results.append({
                            "url": url, "title": title,
                            "content_snippet": content[:500],
                            "screenshot": screenshot,
                        })
                    except Exception as e:
                        results.append({"url": url, "error": str(e)[:80]})

                await context.close()
                await browser.close()
                return {
                    "success": len(results) > 0,
                    "results": results,
                    "summary": f"Visited {len(results)} URLs, extracted content",
                    "agent": "playwright-async",
                }

            except Exception as e:
                logger.error(f"Playwright async fallback failed: {e}")
                try:
                    await context.close()
                    await browser.close()
                except Exception:
                    pass
                return {"success": False, "error": str(e)[:200]}

    # ── LLM config for browser-use ──────────────────────────────────

    def _make_llm_config(self):
        """Create LLM configuration dict for browser-use Agent.
        Uses Gemini (cheap/fast) by default for browser extraction/summary.
        Only uses NVIDIA (expensive/smart) for complex decision-making tasks.
        """
        return self.llm_config
