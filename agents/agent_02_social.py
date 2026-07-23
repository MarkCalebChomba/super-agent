import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class SocialMediaAgent(BaseAgent):
    """Social media monetization: Twitter, Instagram, TikTok, LinkedIn, Pinterest."""

    def __init__(self, identity: dict = None):
        super().__init__("SocialMediaMonetizer", identity)
        self.content = ContentGenerator()
        self.platforms = ["twitter", "instagram", "linkedin", "tiktok", "pinterest"]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Twitter/X monetization, Instagram sponsorships, TikTok Creator Fund, "
                "LinkedIn premium content, Pinterest affiliate pins, "
                "Brand deals across all platforms")

    def build(self) -> dict:
        platform = self.platforms[self.idx % len(self.platforms)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{platform}_post_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        caption = self.content.social_caption(platform, "Making money with AI agents")
        if caption:
            with open(filepath, "w") as f:
                f.write(f"Platform: {platform}\n\n{caption}\n")
            return {"file": filepath, "summary": f"{platform} post draft", "revenue": 0.0, "method": "social_media"}
        return None
