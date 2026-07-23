import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class ContentAgent(BaseAgent):
    """Content creation & monetization: blogs, newsletters, courses, ebooks."""

    def __init__(self, identity: dict = None):
        super().__init__("ContentCreator", identity)
        self.content = ContentGenerator()
        self.topics = [
            "AI tools for productivity",
            "How to make money with AI agents",
            "Best free AI tools in 2026",
            "Automating your workflow with Python",
            "Side hustles that actually work",
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Blogging (AdSense/Mediavine), Newsletter (Substack, Beehiiv), "
                "Online courses (Udemy, Gumroad), eBooks (Amazon KDP), "
                "Medium Partner Program, Ghostwriting, Sponsored content")

    def build(self) -> dict:
        topic = self.topics[self.idx % len(self.topics)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"blog_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        post = self.content.blog_post(topic)
        if post:
            with open(filepath, "w") as f:
                f.write(f"# {topic}\n\n{post}\n")
            return {"file": filepath, "summary": f"Blog post: {topic}", "revenue": 0.0, "method": "blogging"}
        return None
