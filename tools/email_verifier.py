"""Disposable email verification for self-provisioning accounts.

Uses the free mail.tm API (no signup required) to:
1. Create a temporary inbox
2. Wait for verification emails
3. Extract confirmation links / codes

This lets agents auto-verify accounts after signing up on platforms.
"""

import os
import time
import re
import requests
from loguru import logger


class EmailVerifier:
    """Temp email inbox via mail.tm for receiving verification emails."""

    API_BASE = "https://api.mail.tm"

    def __init__(self):
        self._token = None
        self._account_id = None
        self._email = None

    def create_inbox(self, email_prefix: str = "agent") -> str | None:
        """Create a temporary email inbox and return the address."""
        try:
            domains_resp = requests.get(f"{self.API_BASE}/domains", timeout=10)
            domains = domains_resp.json().get("hydra:member", [])
            if not domains:
                logger.error("No mail.tm domains available")
                return None
            domain = domains[0]["domain"]

            import uuid
            local_part = f"{email_prefix}_{uuid.uuid4().hex[:8]}"
            password = "AgentTemp123!"

            account_resp = requests.post(f"{self.API_BASE}/accounts", json={
                "address": f"{local_part}@{domain}",
                "password": password,
            }, timeout=10)

            if account_resp.status_code not in (200, 201):
                logger.error(f"mail.tm account creation failed: {account_resp.text}")
                return None

            account_data = account_resp.json()
            self._account_id = account_data.get("id")
            self._email = account_data.get("address")

            token_resp = requests.post(f"{self.API_BASE}/token", json={
                "address": self._email,
                "password": password,
            }, timeout=10)
            if token_resp.status_code != 200:
                logger.error(f"mail.tm token failed: {token_resp.text}")
                return None

            self._token = token_resp.json().get("token")
            logger.info(f"Created temp inbox: {self._email}")
            return self._email
        except Exception as e:
            logger.error(f"mail.tm create_inbox error: {e}")
            return None

    def wait_for_verification(self, sender_hint: str = None, timeout: int = 120,
                              poll_interval: int = 5) -> dict | None:
        """Wait for a verification email and return its content.

        Args:
            sender_hint: Optional partial match on sender address
            timeout: Max seconds to wait
            poll_interval: Seconds between inbox checks

        Returns:
            dict with subject, text_body, html_body, from_address, or None
        """
        if not self._token:
            logger.error("No inbox created yet")
            return None

        headers = {"Authorization": f"Bearer {self._token}"}
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                resp = requests.get(f"{self.API_BASE}/messages", headers=headers, timeout=10)
                if resp.status_code != 200:
                    time.sleep(poll_interval)
                    continue

                messages = resp.json().get("hydra:member", [])
                for msg in messages:
                    from_addr = msg.get("from", {}).get("address", "")
                    if sender_hint and sender_hint.lower() not in from_addr.lower():
                        continue

                    msg_id = msg.get("id")
                    detail = requests.get(f"{self.API_BASE}/messages/{msg_id}", headers=headers, timeout=10)
                    if detail.status_code != 200:
                        continue

                    detail_data = detail.json()
                    subject = detail_data.get("subject", "")
                    text_body = ""
                    html_body = ""

                    for part in detail_data.get("textParts", []):
                        text_body += part.get("content", "")

                    for part in detail_data.get("htmlParts", []):
                        html_body += part.get("content", "")

                    logger.info(f"Got email: {subject} from {from_addr}")
                    return {
                        "subject": subject,
                        "text_body": text_body,
                        "html_body": html_body,
                        "from_address": from_addr,
                        "message_id": msg_id,
                    }

                time.sleep(poll_interval)
            except Exception as e:
                logger.debug(f"mail.tm poll error: {e}")
                time.sleep(poll_interval)

        logger.warning(f"No verification email received within {timeout}s")
        return None

    def extract_verification_link(self, email_body: str) -> str | None:
        """Extract a verification/confirmation link from an email body."""
        patterns = [
            r'https?://[^\s"\'<>]+(?:verify|confirm|activate|validate)[^\s"\'<>]*',
            r'https?://[^\s"\'<>]+(?:email|account)[^\s"\'<>]*(?:verify|confirm|activate)[^\s"\'<>]*',
            r'<a[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>.*?(?:verify|confirm|activate)',
        ]
        for pattern in patterns:
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                url = match.group(1) if match.lastindex else match.group(0)
                url = url.replace("&amp;", "&")
                logger.info(f"Extracted verification link: {url}")
                return url
        return None

    def extract_verification_code(self, email_body: str) -> str | None:
        """Extract a 4-8 digit verification code from an email."""
        match = re.search(r'\b(\d{4,8})\b', email_body)
        if match:
            code = match.group(1)
            logger.info(f"Extracted verification code: {code}")
            return code
        return None

    def cleanup(self):
        """Delete the temp account."""
        if self._account_id and self._token:
            try:
                requests.delete(
                    f"{self.API_BASE}/accounts/{self._account_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=10,
                )
                logger.info(f"Cleaned up temp inbox {self._email}")
            except Exception:
                pass
