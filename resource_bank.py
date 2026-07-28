"""ResourceBank — tracks money, capabilities, accounts, and tools for each agent.

The agent starts with $0, no accounts, no browser. The Supervisor plans
within real constraints. Every API call is logged as a cost. Every
monetization attempt tracks estimated income. The agent knows exactly
what it has and what it still needs to survive.
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger


BANK_DIR = Path("data") / "resource_bank"


class ResourceBank:
    """Per-agent financial & capability ledger.

    Persisted to data/resource_bank/{agent_name}.json .
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        BANK_DIR.mkdir(parents=True, exist_ok=True)
        self.path = BANK_DIR / f"{agent_name}.json"
        self._load()

    # ── Persistence ────────────────────────────────────────────────

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
        else:
            data = {}
        self.balance = data.get("balance", 0.0)
        self.total_revenue = data.get("total_revenue", 0.0)
        self.total_costs = data.get("total_costs", 0.0)
        self.income_log = data.get("income_log", [])
        self.expense_log = data.get("expense_log", [])
        self.capabilities = data.get("capabilities", {})
        self.accounts = data.get("accounts", {})
        self.tools = data.get("tools", {})
        self.metadata = data.get("metadata", {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        })

    def save(self):
        self.metadata["last_updated"] = datetime.now().isoformat()
        data = {
            "balance": self.balance,
            "total_revenue": self.total_revenue,
            "total_costs": self.total_costs,
            "income_log": self.income_log,
            "expense_log": self.expense_log,
            "capabilities": self.capabilities,
            "accounts": self.accounts,
            "tools": self.tools,
            "metadata": self.metadata,
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    # ── Money tracking ─────────────────────────────────────────────

    def record_income(self, amount: float, source: str,
                      description: str = "", metadata: dict = None):
        self.balance += amount
        self.total_revenue += amount
        self.income_log.append({
            "amount": amount,
            "source": source,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        self.save()
        logger.info(f"{self.agent_name} +${amount:.2f} from {source}")

    def record_expense(self, amount: float, purpose: str,
                       category: str = "api", metadata: dict = None):
        self.balance -= amount
        self.total_costs += amount
        self.expense_log.append({
            "amount": amount,
            "purpose": purpose,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        self.save()
        logger.info(f"{self.agent_name} -${amount:.2f} for {purpose}")

    def cost_estimate(self, provider: str = "hf", tokens: int = 0) -> float:
        costs = {"hf": 0.0, "nvidia": 0.0001, "openrouter": 0.00015}
        return costs.get(provider, 0.0) * max(tokens, 1000) / 1000

    # ── Capability tracking ────────────────────────────────────────

    def add_capability(self, name: str, available: bool = True,
                       details: dict = None):
        self.capabilities[name] = {
            "available": available,
            "details": details or {},
            "added_at": datetime.now().isoformat(),
        }
        self.save()

    def has_capability(self, name: str) -> bool:
        cap = self.capabilities.get(name, {})
        return cap.get("available", False)

    def remove_capability(self, name: str):
        self.capabilities.pop(name, None)
        self.save()

    # ── Account tracking ───────────────────────────────────────────

    def register_account(self, platform: str, username: str = "",
                         status: str = "pending", details: dict = None):
        self.accounts[platform] = {
            "username": username,
            "status": status,
            "details": details or {},
            "registered_at": datetime.now().isoformat(),
        }
        self.save()

    def has_account(self, platform: str) -> bool:
        acc = self.accounts.get(platform, {})
        return acc.get("status") == "active"

    # ── Tool tracking ──────────────────────────────────────────────

    def add_tool(self, name: str, available: bool = True,
                 config: dict = None):
        self.tools[name] = {
            "available": available,
            "config": config or {},
            "added_at": datetime.now().isoformat(),
        }
        self.save()

    def has_tool(self, name: str) -> bool:
        tool = self.tools.get(name, {})
        return tool.get("available", False)

    # ── Status reporting ───────────────────────────────────────────

    def get_status_report(self) -> str:
        lines = ["## RESOURCE STATUS"]
        lines.append(f"Balance: ${self.balance:.2f}")
        lines.append(f"Total Revenue: ${self.total_revenue:.2f}")
        lines.append(f"Total Costs: ${self.total_costs:.2f}")

        caps_avail = [n for n, c in self.capabilities.items() if c.get("available")]
        if caps_avail:
            lines.append(f"Capabilities: {', '.join(sorted(caps_avail))}")
        else:
            lines.append("Capabilities: none yet")

        # Real browser status - critical for planning
        has_browser = self.has_capability("real_browser")
        if has_browser:
            lines.append("REAL BROWSER: YES — can visit websites, login, extract data")
        else:
            lines.append("REAL BROWSER: NO — research only, cannot do web actions")

        acts = [f"{p}({a['status']})" for p, a in self.accounts.items()]
        if acts:
            lines.append(f"Accounts: {', '.join(acts)}")
        else:
            lines.append("Accounts: none — need to sign up for platforms")

        tools_avail = [n for n, t in self.tools.items() if t.get("available")]
        if tools_avail:
            lines.append(f"Tools: {', '.join(sorted(tools_avail))}")
        else:
            lines.append("Tools: LLM only — no browser, no search, no API keys yet")

        recent = self.income_log[-3:] if self.income_log else []
        if recent:
            lines.append("Recent income:")
            for inc in recent:
                lines.append(f"  +${inc['amount']:.2f} — {inc['source']}")

        return "\n".join(lines)

    def is_profitable(self) -> bool:
        return self.total_revenue > self.total_costs

    def is_viable(self) -> bool:
        return self.balance >= 0 and self.has_capability("llm_access")
