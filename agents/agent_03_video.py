from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator
from tools.social_tools import SocialTools

class VideoAgent(BaseAgent):
    """Video content monetization: YouTube, TikTok, Instagram Reels, Twitch."""

    def __init__(self, identity: dict = None):
        super().__init__("VideoCreator", identity)
        self.content = ContentGenerator()
        self.social = SocialTools(identity)
        self.drafts = []

    def get_income_methods(self) -> str:
        return ("YouTube AdSense, YouTube Memberships, TikTok Creator Fund, "
                "Instagram Reels bonus, Twitch subscriptions, "
                "Sponsored videos, Affiliate marketing through video")

    def think(self, context: dict) -> str:
        return ("!remember self creating YouTube video on AI automation category=plan importance=3\n"
                "ACTION: Write video script for YouTube Short about AI side hustles\n"
                "CTA: Human review needed for video draft before publishing\n"
                "!remember self Video script written for AI side hustles Short category=content")

    def act(self, decision: str) -> dict:
        script = self.content.video_script("AI side hustles that actually work", "youtube", 60)
        self.drafts.append(script)
        from master.telegram_bot import TelegramBot
        bot = TelegramBot()
        bot.send_video_draft(self.name, "AI Side Hustles That Actually Work",
                             str(script.get("body", "")[:200]),
                             "YouTube", estimated_revenue=5.00)
        return {"success": True, "action": "script_written", "method": "video_content",
                "details": "Video script draft ready for human review",
                "revenue": 0.0, "summary": "Video script created, sent for human review"}
