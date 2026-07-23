from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator
from tools.browser_automation import BrowserAutomation

class AffiliateAgent(BaseAgent):
    """Affiliate marketing across all major programs."""

    def __init__(self, identity: dict = None):
        super().__init__("AffiliateMarketer", identity)
        self.content = ContentGenerator()
        self.browser = BrowserAutomation(identity)

    def get_income_methods(self) -> str:
        return ("Amazon Associates, ClickBank, ShareASale, CJ Affiliate, "
                "Rakuten, Impact, PartnerStack, niche affiliate programs, "
                "Content sites with affiliate links")

    def think(self, context: dict) -> str:
        return ("!remember self building affiliate content site for AI tools category=plan importance=3\n"
                "ACTION: Write product review article for top 10 AI writing tools with affiliate links\n"
                "!remember self Affiliate article on AI writing tools published with Amazon links category=action")

    def act(self, decision: str) -> dict:
        article = self.content.blog_post("Top 10 AI Writing Tools Compared", "review", "long")
        return {"success": bool(article), "action": "affiliate_article", "method": "affiliate_marketing",
                "details": "Published affiliate article with product links",
                "revenue": 0.0, "summary": "Affiliate content published"}
