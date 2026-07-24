"""Web research tool for finding and extracting existing content.
Inspired by ALwrity's research layer and blogging-with-langchain's research node.
Finds existing high-performing articles instead of generating from scratch.
"""

import re
import time
import json
from typing import Optional
from urllib.parse import urlparse
from loguru import logger
import requests
from bs4 import BeautifulSoup


class WebResearch:
    """Finds and extracts existing content from the web.
    
    Capabilities:
    - Search for best existing articles on any topic
    - Extract and clean article content from URLs
    - Identify top-performing content by social signals
    - Curate source materials for adaptation
    """

    SEARCH_ENGINES = {
        "google": "https://www.google.com/search?q={q}&num={n}",
        "bing": "https://www.bing.com/search?q={q}&count={n}",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._cache = {}

    def search_existing_content(self, topic: str, n: int = 5) -> list[dict]:
        """Find existing high-performing articles on a topic.
        
        Returns list of {url, title, snippet, source} dicts.
        """
        cache_key = f"search:{topic}:{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query = f"{topic} best articles guide tutorial 2026"
        results = []

        for engine, url_template in self.SEARCH_ENGINES.items():
            try:
                url = url_template.format(q=requests.utils.quote(query), n=n)
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                items = self._parse_search_results(soup, engine)
                results.extend(items[:n])
            except Exception as e:
                logger.debug(f"Search engine {engine} failed: {e}")

            time.sleep(1)

        seen = set()
        unique = []
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                unique.append(r)

        self._cache[cache_key] = unique[:n * 2]
        return unique[:n * 2]

    def _parse_search_results(self, soup: BeautifulSoup, engine: str) -> list[dict]:
        items = []
        if engine == "google":
            for g in soup.select("div.g"):
                link = g.select_one("a[href]")
                snippet = g.select_one("span.aCOpRe, div.VwiC3b")
                if link:
                    href = link.get("href", "")
                    if href.startswith("/url?q="):
                        href = href.split("/url?q=")[1].split("&")[0]
                    if href and not href.startswith("http"):
                        continue
                    items.append({
                        "url": href,
                        "title": link.get_text(strip=True) or "",
                        "snippet": snippet.get_text(strip=True) if snippet else "",
                        "source": "google",
                    })
        elif engine == "bing":
            for li in soup.select("li.b_algo"):
                link = li.select_one("a[href]")
                snippet = li.select_one(".b_caption p")
                if link:
                    items.append({
                        "url": link.get("href", ""),
                        "title": link.get_text(strip=True) or "",
                        "snippet": snippet.get_text(strip=True) if snippet else "",
                        "source": "bing",
                    })
        return items

    def extract_article(self, url: str) -> Optional[dict]:
        """Extract and clean article content from a URL.
        
        Returns {url, title, content, word_count, domain} or None.
        """
        cache_key = f"extract:{url}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            title = ""
            for sel in ["h1", "title", "meta[property='og:title']"]:
                el = soup.select_one(sel)
                if el:
                    title = el.get("content", el.get_text(strip=True))
                    break

            content_parts = []
            for sel in ["article", "main", ".post-content", ".entry-content",
                        ".article-body", "#content", "body"]:
                el = soup.select_one(sel)
                if el:
                    for p in el.select("p, h2, h3, h4, li, blockquote"):
                        text = p.get_text(strip=True)
                        if len(text) > 20:
                            content_parts.append(text)
                    break

            if not content_parts:
                for p in soup.select("p"):
                    text = p.get_text(strip=True)
                    if len(text) > 20:
                        content_parts.append(text)

            content = "\n\n".join(content_parts)
            word_count = len(content.split())

            if word_count < 50:
                return None

            result = {
                "url": url,
                "title": title or url,
                "content": content[:10000],
                "word_count": word_count,
                "domain": urlparse(url).netloc,
            }
            self._cache[cache_key] = result
            return result
        except Exception as e:
            logger.debug(f"Extract failed for {url}: {e}")
            return None

    def find_best_sources(self, topic: str, n: int = 3) -> list[dict]:
        """Find and extract the best N sources on a topic.
        
        Combines search + extraction in one call.
        Returns list of {url, title, content, word_count, domain}.
        """
        results = self.search_existing_content(topic, n=n * 3)
        articles = []
        for r in results:
            article = self.extract_article(r["url"])
            if article and article["word_count"] > 200:
                articles.append(article)
            if len(articles) >= n:
                break
            time.sleep(0.5)
        return articles

    def search_trending_topics(self) -> list[str]:
        """Discover trending content topics from web."""
        queries = [
            "trending topics in AI 2026",
            "best side hustles 2026",
            "popular blog topics 2026",
        ]
        topics = set()
        for q in queries:
            results = self.search_existing_content(q, n=3)
            for r in results:
                snippet = r.get("snippet", "")
                words = [w for w in snippet.split() if len(w) > 4]
                topics.update(words[:10])
            time.sleep(1)
        return list(topics)[:10]

    def clear_cache(self):
        self._cache.clear()
