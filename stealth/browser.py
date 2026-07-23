import os
import time
import random
from typing import Optional
from loguru import logger

class StealthBrowser:
    """Browser abstraction with anti-detection.
    
    Supports Camoufox (primary), undetected-chromedriver (fallback),
    and curl_cffi (HTTP-level fingerprinting).
    
    At $0 budget, curl_cffi is used for API-level operations.
    Camoufox/undetected for full browser automation.
    """

    def __init__(self, identity: dict = None, use_camoufox: bool = False):
        self.identity = identity or {}
        self.use_camoufox = use_camoufox and self._camoufox_available()
        self.browser = None
        self._setup()

    def _camoufox_available(self) -> bool:
        try:
            import camoufox
            return True
        except ImportError:
            logger.info("Camoufox not installed, using undetected-chromedriver")
            return False

    def _setup(self):
        if self.use_camoufox:
            from .fingerprint import FingerprintGenerator
            fp = FingerprintGenerator(self.identity)
            try:
                from camoufox import Camoufox
                self.browser = Camoufox(headless=True, options=fp.get_camoufox_args())
                logger.info("Camoufox initialized")
            except Exception as e:
                logger.warning(f"Camoufox init failed: {e}, falling back")
                self.use_camoufox = False
                self._setup_undetected()
        else:
            self._setup_undetected()

    def _setup_undetected(self):
        try:
            import undetected_chromedriver as uc
            from .fingerprint import FingerprintGenerator
            fp = FingerprintGenerator(self.identity)
            options = uc.ChromeOptions()
            for arg in fp.get_camoufox_args():
                options.add_argument(arg)
            options.add_argument("--headless=new")
            self.browser = uc.Chrome(options=options)
            logger.info("undetected-chromedriver initialized")
        except Exception as e:
            logger.warning(f"undetected-chromedriver failed: {e}, using requests only")
            self.browser = None

    def new_page(self):
        """Get a new page/tab from the browser."""
        if self.browser is None:
            return None
        try:
            if hasattr(self.browser, "new_page"):
                return self.browser.new_page()
            elif hasattr(self.browser, "new_tab"):
                return self.browser.new_tab()
        except Exception as e:
            logger.warning(f"New page failed: {e}")
        return None

    def http_get(self, url: str, headers: dict = None) -> Optional[dict]:
        """HTTP GET with curl_cffi fingerprinting."""
        try:
            import curl_cffi.requests as curl
            fp = curl.Session()
            resp = fp.get(url, headers=headers or {}, impersonate="chrome120",
                          timeout=30)
            return {"status": resp.status_code, "text": resp.text, "headers": dict(resp.headers)}
        except ImportError:
            import requests
            resp = requests.get(url, headers=headers or {}, timeout=30)
            return {"status": resp.status_code, "text": resp.text, "headers": dict(resp.headers)}
        except Exception as e:
            logger.error(f"HTTP GET failed: {e}")
            return None

    def http_post(self, url: str, data: dict = None, headers: dict = None) -> Optional[dict]:
        try:
            import curl_cffi.requests as curl
            fp = curl.Session()
            resp = fp.post(url, json=data, headers=headers or {}, impersonate="chrome120",
                           timeout=30)
            return {"status": resp.status_code, "text": resp.text, "headers": dict(resp.headers)}
        except ImportError:
            import requests
            resp = requests.post(url, json=data, headers=headers or {}, timeout=30)
            return {"status": resp.status_code, "text": resp.text, "headers": dict(resp.headers)}
        except Exception as e:
            logger.error(f"HTTP POST failed: {e}")
            return None

    def screenshot(self, url: str, output_path: str) -> bool:
        """Take a screenshot of a URL (for verification)."""
        if self.browser is None:
            logger.warning("No browser available for screenshot")
            return False
        try:
            page = self.new_page()
            if page:
                page.goto(url)
                time.sleep(random.uniform(2, 4))
                page.screenshot(path=output_path)
                return True
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
        return False

    def close(self):
        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                logger.debug(f"Browser close: {e}")
