import time
import random
from typing import Optional
from loguru import logger
from stealth.browser import StealthBrowser

class BrowserAutomation:
    """Browser automation tools for agent use."""

    def __init__(self, identity: dict = None):
        self.browser = StealthBrowser(identity=identity)

    def visit(self, url: str) -> Optional[str]:
        """Visit a URL and return page content."""
        result = self.browser.http_get(url)
        if result and result["status"] == 200:
            return result["text"]
        return None

    def post_form(self, url: str, data: dict) -> bool:
        """Submit a form via POST."""
        result = self.browser.http_post(url, data=data)
        return result is not None and result["status"] in (200, 201, 302)

    def login(self, url: str, username: str, password: str,
              username_field: str = "username", password_field: str = "password",
              submit_selector: str = "button[type=submit]") -> bool:
        """Automate login on a website using browser."""
        if self.browser.browser is None:
            logger.warning("No browser available for login automation")
            return False
        try:
            page = self.browser.new_page()
            if not page:
                return False
            page.goto(url)
            time.sleep(random.uniform(2, 4))
            page.fill(f"input[name={username_field}]", username)
            page.fill(f"input[name={password_field}]", password)
            page.click(submit_selector)
            time.sleep(random.uniform(3, 5))
            return True
        except Exception as e:
            logger.error(f"Login automation failed: {e}")
            return False

    def scrape(self, url: str, selector: str = None) -> Optional[str]:
        """Scrape content from a page."""
        content = self.visit(url)
        if content and selector:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, "html.parser")
                elements = soup.select(selector)
                return "\n".join(e.get_text(strip=True) for e in elements)
            except ImportError:
                pass
        return content

    def close(self):
        self.browser.close()
