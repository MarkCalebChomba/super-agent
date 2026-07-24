"""Unified captcha solver — CapSolver primary, 2Captcha fallback.

Supports reCAPTCHA v2/v3, hCaptcha, FunCaptcha, Cloudflare Turnstile.

Usage:
    solver = CaptchaSolver()
    token = solver.solve("https://example.com", site_key="6Lc...", captcha_type="recaptcha_v2")
    # inject token into page via JavaScript
"""

import os
import time
import json
import requests
from loguru import logger


class CaptchaSolver:
    """Solve captchas via CapSolver (AI, fast) then 2Captcha (human fallback)."""

    CAPSOLVER_BASE = "https://api.capsolver.com"
    TWOCAPTCHA_BASE = "https://2captcha.com"

    def __init__(self):
        self.capsolver_key = os.getenv("CAPSOLVER_API_KEY", "")
        self.twocaptcha_key = os.getenv("TWOCAPTCHA_API_KEY", "")
        self._capsolver_ok = bool(self.capsolver_key)
        self._twocaptcha_ok = bool(self.twocaptcha_key)

    @property
    def available(self) -> bool:
        return self._capsolver_ok or self._twocaptcha_ok

    def solve(self, page_url: str, site_key: str = None, captcha_type: str = "recaptcha_v2",
              page_action: str = None, api_domain: str = None, **kwargs) -> str | None:
        """Solve a captcha and return the token.

        Args:
            page_url: URL of the page with the captcha
            site_key: Site key (extracted from page)
            captcha_type: One of: recaptcha_v2, recaptcha_v3, hcaptcha, fun captcha, turnstile
            page_action: Action parameter (reCAPTCHA v3)
            api_domain: Custom API domain if applicable

        Returns:
            Token string or None if all solvers fail
        """
        if self._capsolver_ok:
            token = self._solve_capsolver(page_url, site_key, captcha_type, page_action, api_domain, **kwargs)
            if token:
                return token
            logger.warning("CapSolver failed, falling back to 2Captcha")

        if self._twocaptcha_ok:
            token = self._solve_twocaptcha(page_url, site_key, captcha_type, page_action, api_domain, **kwargs)
            if token:
                return token

        logger.error("All captcha solvers failed")
        return None

    def detect_and_solve(self, page) -> str | None:
        """Detect captcha on the current page and solve it automatically.

        Injects the solved token into the page's captcha field.
        """
        captcha_info = self._detect_captcha(page)
        if not captcha_info:
            logger.info("No captcha detected on page")
            return None

        logger.info(f"Detected captcha: {captcha_info}")
        token = self.solve(**captcha_info)
        if not token:
            return None

        self._inject_token(page, captcha_info["captcha_type"], token)
        return token

    def _detect_captcha(self, page) -> dict | None:
        """Detect which captcha is on the page and extract its parameters."""
        try:
            recaptcha = page.query_selector("iframe[src*='recaptcha'], div.g-recaptcha")
            if recaptcha:
                site_key = page.evaluate(
                    "() => { const el = document.querySelector('.g-recaptcha'); "
                    "return el ? el.getAttribute('data-sitekey') : null; }"
                )
                if not site_key:
                    site_key = page.evaluate(
                        "() => { const el = document.querySelector('script[src*=\"recaptcha/api\"]'); "
                        "return el ? null : null; }"
                    )
                if not site_key:
                    site_key = page.evaluate(
                        "() => { const el = document.querySelector('[data-sitekey]'); "
                        "return el ? el.getAttribute('data-sitekey') : null; }"
                    )
                if site_key:
                    return {"page_url": page.url, "site_key": site_key, "captcha_type": "recaptcha_v2"}

            turnstile = page.query_selector("iframe[src*='turnstile'], div.cf-turnstile")
            if turnstile:
                site_key = page.evaluate(
                    "() => { const el = document.querySelector('.cf-turnstile'); "
                    "return el ? el.getAttribute('data-sitekey') : null; }"
                )
                if site_key:
                    return {"page_url": page.url, "site_key": site_key, "captcha_type": "turnstile"}

            hcaptcha = page.query_selector("iframe[src*='hcaptcha'], div.h-captcha")
            if hcaptcha:
                site_key = page.evaluate(
                    "() => { const el = document.querySelector('.h-captcha'); "
                    "return el ? el.getAttribute('data-sitekey') : null; }"
                )
                if site_key:
                    return {"page_url": page.url, "site_key": site_key, "captcha_type": "hcaptcha"}

            funcaptcha = page.query_selector("iframe[src*='funcaptcha']")
            if funcaptcha:
                site_key = page.evaluate(
                    "() => { const iframe = document.querySelector('iframe[src*=\"funcaptcha\"]'); "
                    "if (!iframe) return null; "
                    "const match = iframe.src.match(/pk=([A-Za-z0-9_-]+)/); "
                    "return match ? match[1] : null; }"
                )
                if site_key:
                    return {"page_url": page.url, "site_key": site_key, "captcha_type": "funcaptcha"}

            return None
        except Exception as e:
            logger.debug(f"Captcha detection error: {e}")
            return None

    def _inject_token(self, page, captcha_type: str, token: str):
        """Inject the solved captcha token into the page."""
        try:
            if captcha_type == "recaptcha_v2":
                js = (
                    "document.querySelector('#g-recaptcha-response') && "
                    "(document.querySelector('#g-recaptcha-response').innerHTML = '{0}'); "
                    "if (typeof ___grecaptcha_cfg !== 'undefined') { "
                    "Object.values(___grecaptcha_cfg.clients).forEach(client => { "
                    "Object.values(client).forEach(item => { "
                    "if (item && typeof item.callback === 'function') { "
                    "item.callback('{0}'); } }); }); } return true;"
                ).format(token)
                page.evaluate(js)
                logger.info("Injected reCAPTCHA v2 token")

            elif captcha_type == "turnstile":
                js = (
                    "const el = document.querySelector('[name=\"cf-turnstile-response\"]'); "
                    "if (el) el.value = '{0}'; "
                    "window.turnstileCallback && window.turnstileCallback('{0}'); "
                    "return true;"
                ).format(token)
                page.evaluate(js)
                logger.info("Injected Turnstile token")

            elif captcha_type == "hcaptcha":
                js = (
                    "const el = document.querySelector('[name=\"h-captcha-response\"]'); "
                    "if (el) el.value = '{0}'; "
                    "if (typeof hcaptcha !== 'undefined') { "
                    "hcaptcha.setResponse('{0}'); } "
                    "return true;"
                ).format(token)
                page.evaluate(js)
                logger.info("Injected hCaptcha token")

            self._trigger_submit(page, captcha_type)
        except Exception as e:
            logger.error(f"Token injection error: {e}")

    def _trigger_submit(self, page, captcha_type: str):
        """Try to trigger form submission after token injection."""
        try:
            if captcha_type == "recaptcha_v2":
                page.evaluate(
                    "() => { const btn = document.querySelector('button[type=\"submit\"], input[type=\"submit\"]'); "
                    "if (btn) btn.click(); return true; }"
                )
        except Exception:
            pass

    def _solve_capsolver(self, page_url: str, site_key: str, captcha_type: str,
                         page_action: str = None, api_domain: str = None, **kwargs) -> str | None:
        """Solve via CapSolver API."""
        task_type_map = {
            "recaptcha_v2": "ReCaptchaV2Task",
            "recaptcha_v3": "ReCaptchaV3Task",
            "hcaptcha": "HCaptchaTask",
            "turnstile": "AntiTurnstileTaskProxyLess",
            "funcaptcha": "FunCaptchaTask",
        }
        task_type = task_type_map.get(captcha_type)
        if not task_type:
            logger.error(f"Unsupported captcha type for CapSolver: {captcha_type}")
            return None

        task = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        if page_action:
            task["pageAction"] = page_action
        if api_domain:
            task["apiDomain"] = api_domain
        if kwargs.get("proxy"):
            task["proxy"] = kwargs["proxy"]

        payload = {
            "clientKey": self.capsolver_key,
            "task": task,
        }

        try:
            resp = requests.post(f"{self.CAPSOLVER_BASE}/createTask", json=payload, timeout=30)
            data = resp.json()
            if data.get("errorId") != 0:
                logger.error(f"CapSolver createTask error: {data.get('errorDescription', data)}")
                return None

            task_id = data["taskId"]
            logger.info(f"CapSolver task created: {task_id}")

            for _ in range(60):
                time.sleep(3)
                result = requests.post(f"{self.CAPSOLVER_BASE}/getTaskResult", json={
                    "clientKey": self.capsolver_key,
                    "taskId": task_id,
                }, timeout=15)
                result_data = result.json()
                if result_data.get("status") == "ready":
                    return result_data["solution"].get("gRecaptchaResponse") or result_data["solution"].get("token")
                if result_data.get("errorId") != 0:
                    logger.error(f"CapSolver error: {result_data}")
                    return None

            logger.warning("CapSolver timed out")
            return None
        except Exception as e:
            logger.error(f"CapSolver request error: {e}")
            return None

    def _solve_twocaptcha(self, page_url: str, site_key: str, captcha_type: str,
                          page_action: str = None, api_domain: str = None, **kwargs) -> str | None:
        """Solve via 2Captcha API (human fallback)."""
        method_map = {
            "recaptcha_v2": "userrecaptcha",
            "recaptcha_v3": "userrecaptcha",
            "hcaptcha": "hcaptcha",
            "turnstile": "turnstile",
            "funcaptcha": "funcaptcha",
        }
        method = method_map.get(captcha_type)
        if not method:
            logger.error(f"Unsupported captcha type for 2Captcha: {captcha_type}")
            return None

        params = {
            "key": self.twocaptcha_key,
            "method": method,
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }
        if page_action:
            params["action"] = page_action
        if api_domain:
            params["domain"] = api_domain
        if captcha_type == "recaptcha_v3":
            params["version"] = "v3"

        try:
            resp = requests.post(f"{self.TWOCAPTCHA_BASE}/in.php", data=params, timeout=30)
            data = resp.json()
            if data.get("status") != 1:
                logger.error(f"2Captcha create error: {data}")
                return None

            captcha_id = data["request"]
            logger.info(f"2Captcha task created: {captcha_id}")

            for _ in range(120):
                time.sleep(5)
                result = requests.get(f"{self.TWOCAPTCHA_BASE}/res.php", params={
                    "key": self.twocaptcha_key,
                    "action": "get",
                    "id": captcha_id,
                    "json": 1,
                }, timeout=15)
                result_data = result.json()
                if result_data.get("status") == 1:
                    return result_data["request"]
                if result_data.get("request") != "CAPCHA_NOT_READY":
                    logger.error(f"2Captcha error: {result_data}")
                    return None

            logger.warning("2Captcha timed out")
            return None
        except Exception as e:
            logger.error(f"2Captcha request error: {e}")
            return None
