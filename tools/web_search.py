"""Web search tool — finds real, working resources on the web.

Primary: Firecrawl API (search + scrape)
Fallback: Tavily → WebResearch (Google/Bing scraping)
"""
import os
import time
import json
from typing import Optional
from loguru import logger
import requests


_SEARCH_CACHE = {}
_FIRECRAWL_BASE = "https://api.firecrawl.dev/v2"


def _firecrawl_search(query: str, max_results: int = 5) -> Optional[list[dict]]:
    """Search via Firecrawl API."""
    key = os.getenv("FIRECRAWL_API_KEY", "")
    if not key:
        return None
    try:
        resp = requests.post(
            f"{_FIRECRAWL_BASE}/search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"query": query, "maxResults": max_results, "scrapeOptions": {"formats": ["markdown"]}},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return [
                {"url": r.get("url", ""), "title": r.get("title", ""),
                 "snippet": r.get("description", "") or r.get("content", "")[:300]}
                for r in data.get("data", [])
            ]
        logger.debug(f"Firecrawl search: {resp.status_code}")
    except Exception as e:
        logger.debug(f"Firecrawl search failed: {e}")
    return None


def _tavily_search(query: str, max_results: int = 5) -> Optional[list[dict]]:
    """Search via Tavily API."""
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return None
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": max_results},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            return [
                {"url": r.get("url", ""), "title": r.get("title", ""),
                 "snippet": r.get("content", "")[:300]}
                for r in data.get("results", [])
            ]
    except Exception as e:
        logger.debug(f"Tavily search failed: {e}")
    return None


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web for real, working resources.

    Tries Firecrawl → Tavily → WebResearch fallback.
    Results cached for 5 minutes.
    """
    cache_key = f"ws:{query}:{max_results}"
    if cache_key in _SEARCH_CACHE:
        age = time.time() - _SEARCH_CACHE[cache_key]["ts"]
        if age < 300:
            return _SEARCH_CACHE[cache_key]["results"]

    results = _firecrawl_search(query, max_results)
    if not results:
        results = _tavily_search(query, max_results)
    if not results:
        try:
            from tools.web_research import WebResearch
            wr = WebResearch()
            items = wr.search_existing_content(query, n=max_results)
            results = [
                {"url": r["url"], "title": r["title"], "snippet": r.get("snippet", "")}
                for r in items
            ]
        except Exception as e:
            logger.debug(f"WebResearch fallback failed: {e}")

    _SEARCH_CACHE[cache_key] = {"ts": time.time(), "results": results or []}
    return results or []


def firecrawl_scrape(url: str) -> Optional[str]:
    """Scrape a URL to clean markdown via Firecrawl."""
    key = os.getenv("FIRECRAWL_API_KEY", "")
    if not key:
        return None
    try:
        resp = requests.post(
            f"{_FIRECRAWL_BASE}/scrape",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"]},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("markdown", "")
    except Exception as e:
        logger.debug(f"Firecrawl scrape failed: {e}")
    return None


def find_github_repos(topic: str, max_results: int = 5) -> list[dict]:
    """Find real GitHub repositories for a given topic."""
    return web_search(f"github {topic} repository", max_results)


def find_freelance_gigs(query: str, max_results: int = 5) -> list[dict]:
    """Find freelance gigs on Fiverr, Upwork, etc."""
    return web_search(f"site:fiverr.com OR site:upwork.com {query} freelance", max_results)


def find_tutorials(topic: str) -> list[dict]:
    """Find tutorials on a topic."""
    return web_search(f"{topic} tutorial guide 2026", max_results=5)
