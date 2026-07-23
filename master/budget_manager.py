from typing import Optional
from loguru import logger
from master.system_store import SystemStore
from db.revenue_tracker import RevenueTracker

class BudgetManager:
    """Manages the system budget — tracks revenue, auto-buys resources.
    
    Auto-buy flow:
    1. Resource monitor detects low memory/API quota
    2. Notifies SuperAgent
    3. SuperAgent decides to scale up
    4. BudgetManager checks if funds available
    5. If yes and auto-buy enabled → executes purchase
    6. If no → notifies human for approval
    """

    def __init__(self):
        self.store = SystemStore()
        self.revenue = RevenueTracker()

    def sync_revenue(self):
        """Pull latest revenue from RevenueTracker into budget."""
        pnl = self.revenue.get_pnl(days=30)
        self.store.update_budget(revenue=pnl["revenue"], expenses=pnl["expenses"])
        logger.debug(f"Budget synced: ${pnl['revenue']} revenue, ${pnl['expenses']} expenses")

    def get_status(self) -> dict:
        budget = self.store.get_budget()
        return {
            "total_revenue": budget["total_revenue"],
            "total_expenses": budget["total_expenses"],
            "net": budget["total_revenue"] - budget["total_expenses"],
            "monthly_remaining": budget["max_monthly_budget"] - budget["monthly_spent"],
            "auto_buy": bool(budget["auto_buy_enabled"]),
        }

    def auto_buy_if_needed(self, resource_type: str, cost: float,
                            description: str) -> dict:
        """Try to auto-purchase resources. Returns decision dict."""
        if not self.store.can_afford(cost):
            return {
                "purchased": False,
                "reason": f"Insufficient budget (need ${cost}, remaining: ${self.store.get_budget()['max_monthly_budget'] - self.store.get_budget()['monthly_spent']})",
                "needs_human": True,
            }

        if not self.store.get_budget()["auto_buy_enabled"]:
            return {
                "purchased": False,
                "reason": "Auto-buy disabled",
                "needs_human": True,
            }

        success = self.store.spend(cost, description)
        if success:
            logger.info(f"Auto-buy: ${cost} for {resource_type} — {description}")
            self.store._log_auto_action("auto_buy", resource_type,
                                        f"${cost}: {description}")
            return {"purchased": True, "amount": cost, "resource": resource_type}
        return {"purchased": False, "reason": "Purchase failed", "needs_human": False}

    def request_human_approval(self, cost: float, reason: str) -> str:
        """Format a CTA message for human budget approval."""
        return (
            f"💰 Budget Approval Needed\n"
            f"Cost: ${cost:.2f}\n"
            f"Reason: {reason}\n"
            f"Current balance: ${self.store.get_budget()['total_revenue'] - self.store.get_budget()['total_expenses']:.2f}\n"
            f"Reply /approve or /reject"
        )

    def set_auto_buy(self, enabled: bool, max_monthly: float = 50.0):
        self.store.set_auto_buy(enabled, max_monthly)
        logger.info(f"Auto-buy {'enabled' if enabled else 'disabled'} (max ${max_monthly}/month)")
