from .base_agent import BaseAgent
from tools.social_tools import SocialTools
from tools.content_gen import ContentGenerator

class SocialMediaAgent(BaseAgent):
    """Social media monetization: Twitter, Instagram, TikTok, LinkedIn, Pinterest."""

    def __init__(self, identity: dict = None):
        super().__init__("SocialMediaMonetizer", identity)
        self.social = SocialTools(identity)
        self.content = ContentGenerator()

    def get_income_methods(self) -> str:
        return ("Twitter/X monetization, Instagram sponsorships, TikTok Creator Fund, "
                "LinkedIn premium content, Pinterest affiliate pins, "
                "Brand deals across all platforms")

    def think(self, context: dict) -> str:
        return ("!remember self testing Twitter monetization category=plan importance=3\n"
                "ACTION: Post viral-optimized Twitter thread about making money online\n"
                "!remember self Twitter thread posted on money-making strategies category=action")

    def act(self, decision: str) -> dict:
        caption = self.content.social_caption("twitter", "How I make money with AI agents")
        if caption:
            result = self.social.post_text("twitter", caption)
            return {"success": result.get("success", False), "action": "twitter_post",
                    "method": "social_media", "details": caption[:60] + "...",
                    "revenue": 0.0, "summary": f"Twitter post published"}
        return {"success": False, "action": "twitter_post", "error": "caption generation failed"}
