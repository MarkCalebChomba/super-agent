"""Hermes HF Client — connects Smart Agents to Hermes hosted on Hugging Face.
All agents get Hermes's LLM routing, web search, and research tools remotely.
"""

import os
import json
import time
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError
from loguru import logger


class HermesHFClient:
    """Client for Hermes Agent hosted on Hugging Face Spaces.
    
    All agents route through this for LLM calls + integrated research tools.
    Falls back to local providers if HF is unreachable.
    """

    def __init__(self, space_url: Optional[str] = None):
        self.space_url = space_url or os.getenv(
            "HERMES_HF_URL",
            "https://calebchomba-hermes-agent.hf.space"
        )
        self.api_url = f"{self.space_url.rstrip('/')}/api/eval"
        self.health_url = f"{self.space_url.rstrip('/')}/health"
        self._available = None

    def check_health(self) -> dict:
        """Check if the HF Hermes instance is alive."""
        try:
            req = Request(self.health_url, method="GET")
            with urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}

    @property
    def available(self) -> bool:
        if self._available is None:
            health = self.check_health()
            self._available = health.get("status") == "ok"
        return self._available

    def complete(self, prompt: str, system: str = "",
                 agent_name: str = "default",
                 max_tokens: int = 4096,
                 tools: list[str] = None) -> Optional[str]:
        """Send a completion request to HF Hermes.
        
        Hermes handles: model selection, web search, tool execution,
        memory recall — all remotely.
        """
        payload = json.dumps({
            "prompt": prompt[:8000],
            "system": system[:1000],
            "agent_name": agent_name,
            "max_tokens": max_tokens,
            "tools": tools or [],
        }).encode()

        try:
            req = Request(
                self.api_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
                return result.get("output")
        except URLError as e:
            logger.debug(f"HF Hermes unreachable: {e.reason}")
            self._available = False
            return None
        except Exception as e:
            logger.debug(f"HF Hermes error: {e}")
            return None

    def research_topic(self, topic: str, agent_name: str = "researcher") -> Optional[str]:
        """Use Hermes's built-in web search + research tools.
        
        This replaces the local WebResearch tool which was blocked.
        Hermes has Firecrawl-powered web search via Nous Portal.
        """
        system = (
            "You are a research assistant with web search capability. "
            "Search the web for the BEST existing articles on the given topic. "
            "Return the top 3-5 sources with: title, URL, key findings. "
            "Only return real, verified sources you found via search."
        )
        return self.complete(
            prompt=f"Research: {topic}",
            system=system,
            agent_name=agent_name,
        )

    def extract_article(self, url: str) -> Optional[str]:
        """Use Hermes's article extraction capabilities."""
        return self.complete(
            prompt=f"Extract and summarize the content from this URL: {url}",
            system="You extract article content from URLs. Return the title, main content, and key points.",
            agent_name="extractor",
        )

    def get_skills(self) -> list[str]:
        """Get list of agent skills loaded on HF Hermes."""
        try:
            health = self.check_health()
            return health.get("agents", [])
        except Exception:
            return []

    def reset_connection(self):
        """Force re-check health on next call."""
        self._available = None
