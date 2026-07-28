"""Finance Layer — tracks accounts, balances, human tasks, and real transactions.

No hardcoded platforms. The LLM decides what accounts it needs.
When it needs human help (signup, captcha, verification), it creates a
HumanTask with a clickable link. The user does the task and marks it done.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger


FINANCE_DIR = Path("data") / "finance"
HUMAN_TASKS_FILE = Path("data") / "human_tasks.json"


class HumanTask:
    """A request for the human to do something (sign up, verify, etc.)."""

    def __init__(self, agent: str, title: str, url: str,
                 instructions: str, email: str = "",
                 task_type: str = "signup"):
        self.id = f"{agent}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_type}"
        self.agent = agent
        self.title = title
        self.url = url
        self.instructions = instructions
        self.email = email
        self.task_type = task_type
        self.status = "pending"
        self.created_at = datetime.now().isoformat()
        self.completed_at = None

    def to_dict(self):
        return {
            "id": self.id, "agent": self.agent, "title": self.title,
            "url": self.url, "instructions": self.instructions,
            "email": self.email, "task_type": self.task_type,
            "status": self.status, "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


def _load_tasks() -> list[dict]:
    if HUMAN_TASKS_FILE.exists():
        try:
            return json.loads(HUMAN_TASKS_FILE.read_text())
        except Exception:
            pass
    return []


def _save_tasks(tasks: list[dict]):
    HUMAN_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_TASKS_FILE.write_text(json.dumps(tasks, indent=2, default=str))


def create_human_task(agent: str, title: str, url: str,
                      instructions: str, email: str = "",
                      task_type: str = "signup") -> dict:
    """Create a human-in-the-loop task. Returns the task dict."""
    task = HumanTask(agent, title, url, instructions, email, task_type)
    tasks = _load_tasks()
    tasks.append(task.to_dict())
    _save_tasks(tasks)
    logger.info(f"Human task created: {task.title} for {agent} -> {url}")
    return task.to_dict()


def complete_human_task(task_id: str) -> bool:
    tasks = _load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = "completed"
            t["completed_at"] = datetime.now().isoformat()
            _save_tasks(tasks)
            return True
    return False


def get_pending_tasks(agent: str = None) -> list[dict]:
    tasks = _load_tasks()
    pending = [t for t in tasks if t["status"] == "pending"]
    if agent:
        pending = [t for t in pending if t["agent"] == agent]
    return sorted(pending, key=lambda t: t["created_at"], reverse=True)


def get_all_tasks(agent: str = None, limit: int = 50) -> list[dict]:
    tasks = _load_tasks()
    if agent:
        tasks = [t for t in tasks if t["agent"] == agent]
    return sorted(tasks, key=lambda t: t["created_at"], reverse=True)[:limit]


class FinanceLayer:
    """Per-agent finance: dynamic accounts, real transactions, human tasks."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        FINANCE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = FINANCE_DIR / f"{agent_name}.json"
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
        else:
            data = {}
        self.accounts = data.get("accounts", {})
        self.transactions = data.get("transactions", [])
        self.balance = data.get("balance", 0.0)
        self.total_earned = data.get("total_earned", 0.0)
        self.total_spent = data.get("total_spent", 0.0)
        self.revenue_target = data.get("revenue_target", 100.0)
        self.metadata = data.get("metadata", {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        })

    def save(self):
        self.metadata["last_updated"] = datetime.now().isoformat()
        data = {
            "accounts": self.accounts,
            "transactions": self.transactions,
            "balance": self.balance,
            "total_earned": self.total_earned,
            "total_spent": self.total_spent,
            "revenue_target": self.revenue_target,
            "metadata": self.metadata,
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    # ── Dynamic account management ─────────────────────────────────

    def register_account(self, platform: str, username: str = "",
                         details: dict = None):
        """Record that the human created an account on a platform."""
        self.accounts[platform.lower()] = {
            "username": username,
            "status": "active",
            "registered_at": datetime.now().isoformat(),
            "details": details or {},
        }
        logger.info(f"Finance: {self.agent_name} now has {platform} account")
        self.save()

    def has_account(self, platform: str) -> bool:
        return platform.lower() in self.accounts

    def get_active_accounts(self) -> list[dict]:
        return [
            {"platform": p, **a} for p, a in self.accounts.items()
            if a.get("status") == "active"
        ]

    def suggest_signup(self, platform: str, signup_url: str) -> dict:
        """Create a human task asking the user to sign up on a platform.

        Returns the task dict with the URL the user should visit.
        """
        from email_pool import get_email
        email = get_email(self.agent_name) or "Agent needs an email assigned"
        instructions = (
            f"Go to {signup_url} and sign up using:\n"
            f"  Email: {email}\n"
            f"  Password: markchomba\n"
            f"(password is same for all accounts)\n"
            f"After signing up, come back and mark this task complete."
        )
        return create_human_task(
            agent=self.agent_name,
            title=f"Sign up for {platform}",
            url=signup_url,
            instructions=instructions,
            email=email,
            task_type="signup",
        )

    # ── Transactions ───────────────────────────────────────────────

    def add_income(self, amount: float, source: str,
                   platform: str = "", description: str = ""):
        self.balance += amount
        self.total_earned += amount
        self.transactions.append({
            "type": "income", "amount": amount, "source": source,
            "platform": platform, "description": description,
            "timestamp": datetime.now().isoformat(),
        })
        self.save()

    def add_expense(self, amount: float, purpose: str, category: str = "operation"):
        self.balance -= amount
        self.total_spent += amount
        self.transactions.append({
            "type": "expense", "amount": amount, "purpose": purpose,
            "category": category, "timestamp": datetime.now().isoformat(),
        })
        self.save()

    # ── Reporting ──────────────────────────────────────────────────

    def get_finance_report(self) -> str:
        lines = ["## FINANCE STATUS"]
        lines.append(f"Balance: ${self.balance:.2f}")
        lines.append(f"Total Earned: ${self.total_earned:.2f}")
        lines.append(f"Total Spent: ${self.total_spent:.2f}")

        active = self.get_active_accounts()
        if active:
            lines.append("Active accounts: " + ", ".join(a["platform"] for a in active))
        else:
            lines.append("Active accounts: NONE")

        # Pending human tasks
        pending = get_pending_tasks(self.agent_name)
        if pending:
            lines.append("Tasks waiting for you:")
            for t in pending:
                lines.append(f"  ☐ {t['title']} -> {t['url']}")

        recent = self.transactions[-5:] if self.transactions else []
        if recent:
            lines.append("Recent transactions:")
            for t in reversed(recent):
                sign = "+" if t["type"] == "income" else "-"
                lines.append(f"  {sign}${t['amount']:.2f} — {t.get('source', t.get('purpose', ''))}")

        return "\n".join(lines)


# ── Top-level exports ──────────────────────────────────────────────

def get_finance(agent_name: str) -> FinanceLayer:
    return FinanceLayer(agent_name)


def get_all_finance_summary() -> dict:
    agents = {}
    total_balance = 0.0
    total_earned = 0.0
    for f in FINANCE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            name = f.stem
            agents[name] = {
                "balance": data.get("balance", 0),
                "total_earned": data.get("total_earned", 0),
                "accounts": list(data.get("accounts", {}).keys()),
                "tx_count": len(data.get("transactions", [])),
            }
            total_balance += data.get("balance", 0)
            total_earned += data.get("total_earned", 0)
        except Exception:
            pass
    return {
        "agents": agents,
        "total_balance": total_balance,
        "total_earned": total_earned,
        "agent_count": len(agents),
    }
