"""Proxy rotation manager for stealth browser operations.

Loads proxies from env var or file and rotates them to avoid
IP-based blocking during account signups and content publishing.
"""

import os
import json
import random
from pathlib import Path
from typing import Optional
from loguru import logger


class ProxyManager:
    """Round-robin proxy rotation for stealth browser sessions."""

    PROXY_FILE = Path("data") / "proxies.json"

    def __init__(self):
        self._proxies = []
        self._index = 0
        self._load_proxies()

    def _load_proxies(self):
        """Load proxies from file or env var."""
        if self.PROXY_FILE.exists():
            try:
                with open(self.PROXY_FILE) as f:
                    raw = json.load(f)
                self._proxies = [p if isinstance(p, str) else p.get("url") for p in raw]
                logger.info(f"Loaded {len(self._proxies)} proxies from file")
                return
            except Exception as e:
                logger.debug(f"Proxy file load error: {e}")

        env_proxies = os.getenv("PROXY_LIST", "")
        if env_proxies:
            self._proxies = [p.strip() for p in env_proxies.split(",") if p.strip()]
            logger.info(f"Loaded {len(self._proxies)} proxies from env")

        if not self._proxies:
            logger.info("No proxies configured — will use direct connection")

    @property
    def available(self) -> bool:
        return len(self._proxies) > 0

    def get_next(self) -> Optional[str]:
        """Get the next proxy in round-robin order."""
        if not self._proxies:
            return None
        proxy = self._proxies[self._index % len(self._proxies)]
        self._index += 1
        return proxy

    def get_random(self) -> Optional[str]:
        """Get a random proxy."""
        if not self._proxies:
            return None
        return random.choice(self._proxies)

    def get_playwright_proxy(self) -> Optional[dict]:
        """Get proxy formatted for Playwright/Camoufox context."""
        proxy_url = self.get_random()
        if not proxy_url:
            return None
        return {"server": proxy_url}

    def add_proxy(self, url: str):
        """Add a new proxy to the pool and persist."""
        self._proxies.append(url)
        self._save()

    def _save(self):
        """Persist proxy list to file."""
        self.PROXY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.PROXY_FILE, "w") as f:
                json.dump(self._proxies, f, indent=2)
        except Exception as e:
            logger.debug(f"Proxy save error: {e}")

    def remove_proxy(self, url: str):
        """Remove a proxy from the pool."""
        if url in self._proxies:
            self._proxies.remove(url)
            self._save()

    def mark_bad(self, url: str):
        """Remove a proxy that failed."""
        self.remove_proxy(url)
        logger.warning(f"Removed bad proxy: {url}")
