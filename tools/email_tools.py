import os
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
from loguru import logger

class EmailTools:
    """Email tools for agent use.
    
    Supports Gmail, Outlook, and custom SMTP/IMAP.
    Agents can read incoming verification emails and send outreach.
    """

    PROVIDERS = {
        "gmail": {"smtp": "smtp.gmail.com", "imap": "imap.gmail.com"},
        "outlook": {"smtp": "smtp.office365.com", "imap": "outlook.office365.com"},
        "yahoo": {"smtp": "smtp.mail.yahoo.com", "imap": "imap.mail.yahoo.com"},
    }

    def __init__(self, email_addr: str = None, password: str = None, provider: str = "gmail"):
        self.email = email_addr
        self.password = password
        self.provider = provider

    def _get_smtp(self):
        info = self.PROVIDERS.get(self.provider, self.PROVIDERS["gmail"])
        server = smtplib.SMTP(info["smtp"], 587)
        server.starttls()
        server.login(self.email, self.password)
        return server

    def _get_imap(self):
        info = self.PROVIDERS.get(self.provider, self.PROVIDERS["gmail"])
        server = imaplib.IMAP4_SSL(info["imap"])
        server.login(self.email, self.password)
        return server

    def send_email(self, to: str, subject: str, body: str) -> bool:
        try:
            server = self._get_smtp()
            msg = MIMEMultipart()
            msg["From"] = self.email
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent to {to}: {subject[:50]}")
            return True
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    def check_inbox(self, sender: str = None, search: str = None) -> List[dict]:
        """Check inbox for verification emails or specific messages."""
        emails = []
        try:
            server = self._get_imap()
            server.select("INBOX")
            criteria = "ALL"
            if sender:
                criteria = f'(FROM "{sender}")'
            if search:
                criteria = f'(BODY "{search}")'

            status, messages = server.search(None, criteria)
            if status != "OK":
                return emails

            for num in messages[0].split()[-10:]:  # last 10
                status, data = server.fetch(num, "(RFC822)")
                if status != "OK":
                    continue
                raw = email.message_from_bytes(data[0][1])

                body = ""
                if raw.is_multipart():
                    for part in raw.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = raw.get_payload(decode=True).decode(errors="ignore")

                emails.append({
                    "from": raw["From"],
                    "subject": raw["Subject"],
                    "date": raw["Date"],
                    "body": body[:500],
                })

            server.logout()
        except Exception as e:
            logger.error(f"Inbox check failed: {e}")
        return emails

    def get_verification_link(self) -> Optional[str]:
        """Search for a verification email and extract the link."""
        emails = self.check_inbox(search="verify|confirm|activate")
        import re
        for em in emails:
            urls = re.findall(r'https?://[^\s"\'<>]+', em.get("body", ""))
            if urls:
                return urls[0]
        return None

    def close(self):
        pass
