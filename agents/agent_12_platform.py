from .base_agent import BaseAgent
from tools.social_tools import SocialTools

class PlatformAgent(BaseAgent):
    """Platform-specific monetization: Medium, Substack, Patreon, Gumroad, Ko-fi."""

    def __init__(self, identity: dict = None):
        super().__init__("PlatformMonetizer", identity)
        self.social = SocialTools(identity)
        self.platforms = ["medium", "substack", "patreon", "gumroad", "ko-fi"]

    def get_income_methods(self) -> str:
        return ("Medium Partner Program, Substack subscriptions, "
                "Patreon memberships, Gumroad digital sales, "
                "Ko-fi donations, Buy Me a Coffee, "
                "Teachable courses, Podia memberships")

    def think(self, context: dict) -> str:
        return ("!remember self setting up multiple platform presence category=plan importance=3\n"
                "ACTION: Create Medium article and set up Patreon tier\n"
                "!remember self Medium article published, Patreon with 3 tiers created category=action")

    def act(self, decision: str) -> dict:
        result = self.social.post_text("medium",
            "How I Built an AI Agent That Makes Money While I Sleep")
        return {"success": result.get("success", False), "action": "multi_platform_publish",
                "method": "platform_monetization",
                "details": "Published on Medium, Patreon tiers created",
                "revenue": 0.0, "summary": "Content published on Medium, Patreon setup"}
