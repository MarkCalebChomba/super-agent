import os
import json
from typing import Optional, Callable
from loguru import logger
import requests

class TelegramBot:
    """Telegram bot for human notification.
    
    All messages pass through SupervisorFilter before reaching here.
    The human (Ultimate Agent) receives only high-priority items.
    """

    BASE = "https://api.telegram.org/bot"

    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.base_url = f"{self.BASE}{self.token}" if self.token else ""
        self._notification_callback: Optional[Callable] = None

    def send(self, message: str, parse_mode: str = "Markdown") -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured — cannot send message")
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"Telegram sent: {message[:80]}...")
                return True
            logger.error(f"Telegram error: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
        return False

    def send_notification(self, log_entry: dict) -> bool:
        """Send a formatted notification to human based on a log entry."""
        agent = log_entry.get("agent_name", "unknown")
        level = log_entry.get("level", 0)
        msg = log_entry.get("message", "")
        category = log_entry.get("category", "general")
        reason = log_entry.get("_filter_reason", "")

        emoji = "🚨" if level >= 50 else "⚠️" if level >= 40 else "💰" if level == 45 else "ℹ️"
        filter_tag = f"\n*Why:* {reason}" if reason else ""

        text = (
            f"{emoji} *[{agent}]* {category}\n"
            f"{msg}{filter_tag}\n"
            f"_Use /approve or /reject to respond_"
        )
        return self.send(text)

    def send_daily_summary(self, agent_summaries: list[dict]):
        """Send a daily summary of all agent activities."""
        lines = ["📊 *Daily Agent Summary*\n"]
        for s in agent_summaries:
            lines.append(
                f"*{s['agent_name']}* — {s.get('actions_taken', 0)} actions, "
                f"{s.get('revenue', 0)} revenue, "
                f"{s.get('errors', 0)} errors"
            )
        self.send("\n".join(lines))

    def send_video_draft(self, agent_name: str, title: str, script_preview: str,
                         platform: str, estimated_revenue: float = 0):
        """Notify human that a video draft is ready for review."""
        text = (
            f"🎬 *Video Draft Ready — {agent_name}*\n"
            f"*Title:* {title}\n"
            f"*Platform:* {platform}\n"
            f"*Estimated Revenue:* ${estimated_revenue:.2f}\n"
            f"*Preview:* {script_preview[:300]}...\n"
            f"_Use /approve to publish or /reject to discard_"
        )
        self.send(text)

    def set_notification_callback(self, callback: Callable):
        """Set a callback for incoming messages from human."""
        self._notification_callback = callback

    def poll_updates(self, offset: int = 0) -> int:
        """Poll for incoming messages from human. Returns new offset."""
        if not self.token:
            return offset
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            if resp.status_code == 200:
                updates = resp.json().get("result", [])
                for update in updates:
                    if "message" in update and self._notification_callback:
                        self._notification_callback(update["message"])
                    offset = update["update_id"] + 1
        except Exception as e:
            logger.debug(f"Telegram poll error: {e}")
        return offset
