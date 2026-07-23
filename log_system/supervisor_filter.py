import json
from typing import Optional
from loguru import logger
from providers.router import LLMRouter

class SupervisorFilter:
    """LLM-powered gate that filters what reaches the human.
    
    Not every error or CTA is worth interrupting the human. This filter
    uses an LLM to decide: is this actually important enough to notify?
    
    Flow:
    1. Agent logs CTA/ERROR to central log
    2. Master periodically calls filter_logs()
    3. SupervisorFilter asks LLM: "Should human see this?"
    4. Only logs that pass get sent to Telegram
    """

    SYSTEM_PROMPT = """You are the SuperAgent — the gatekeeper between autonomous agents and the human.

Your job: decide which messages are important enough to interrupt the human.

HIGH priority (ALWAYS notify):
- Revenue earned or lost (any amount)
- Account banned or restricted
- API key expired or invalid
- Budget approval needed (any amount over $1)
- Human decision required to proceed
- New revenue stream discovered
- Video/content draft ready for review
- Opportunity that requires quick human input

MEDIUM priority (notify if slow period):
- Multiple errors in same agent (3+ in 10 min)
- Strategy not working after 5+ attempts
- New skill/pattern discovered

LOW priority (DO NOT notify, just log):
- Single errors that will be retried
- Expected failures (rate limits, captchas)
- Routine actions completed
- Debug info
- Status updates without action items

Respond with JSON only:
{"priority": "high|medium|low", "reason": "one-sentence explanation", "should_notify": true|false}"""

    def __init__(self):
        self.llm = LLMRouter()

    def should_notify(self, log_entry: dict) -> dict:
        """Evaluate a single log entry. Returns decision dict."""
        level = log_entry.get("level", 0)
        msg = log_entry.get("message", "")

        # Pre-filter: skip LLM for trivial logs entirely
        if level <= 20:
            return {"priority": "low", "reason": "routine log, skipped", "should_notify": False}
        if 25 <= level <= 30 and "successful" in msg:
            return {"priority": "low", "reason": "routine success, skipped", "should_notify": False}

        # For ERROR (40) and CTAs (50+), use LLM but with rate limiting
        prompt = f"""Agent: {log_entry.get('agent_name', 'unknown')}
Level: {level}
Category: {log_entry.get('category', 'general')}
Message: {msg}
Data: {json.dumps(log_entry.get('data', {}))}"""

        try:
            result = self.llm.complete(
                prompt,
                agent_type="general",
                system=self.SYSTEM_PROMPT,
                max_tokens=150,
                temperature=0.3,
            )
            if result:
                cleaned = result.strip().replace("```json", "").replace("```", "").strip()
                return json.loads(cleaned)
        except Exception as e:
            logger.warning(f"SupervisorFilter LLM error: {e}")

        # Fallback: only notify on CRITICAL+ (50)
        return {
            "priority": "high" if level >= 50 else "low",
            "reason": "fallback decision (LLM error)",
            "should_notify": level >= 50,
        }

    def filter_logs(self, log_entries: list[dict]) -> list[dict]:
        """Filter a batch of logs. Returns only those that should notify human."""
        notify_queue = []
        for entry in log_entries:
            decision = self.should_notify(entry)
            if decision.get("should_notify"):
                entry["_filter_reason"] = decision.get("reason", "")
                entry["_filter_priority"] = decision.get("priority", "low")
                notify_queue.append(entry)
                logger.info(f"SuperAgent approved notification: {decision.get('reason', '')}")
        return notify_queue
