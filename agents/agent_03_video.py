import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class VideoAgent(BaseAgent):
    """Video content monetization: YouTube, TikTok, Instagram Reels, Twitch."""

    def __init__(self, identity: dict = None):
        super().__init__("VideoCreator", identity)
        self.content = ContentGenerator()
        self.topics = [
            "AI side hustles that actually work",
            "How I automated my entire workflow",
            "Best free AI tools 2026",
            "Make money online with AI agents",
            "Python automation for beginners",
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("YouTube AdSense, YouTube Memberships, TikTok Creator Fund, "
                "Instagram Reels bonus, Twitch subscriptions, "
                "Sponsored videos, Affiliate marketing through video")

    def build(self) -> dict:
        topic = self.topics[self.idx % len(self.topics)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"video_script_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        script = self.content.video_script(topic, "youtube", 120)
        if script:
            with open(filepath, "w") as f:
                f.write(f"# Video Script: {topic}\n\n{script}\n")
            return {"file": filepath, "summary": f"Video script: {topic}", "revenue": 0.0, "method": "video_content"}
        return None
