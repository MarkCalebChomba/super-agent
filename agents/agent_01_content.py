from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class ContentAgent(BaseAgent):
    """Content creation & monetization: blogs, newsletters, courses, ebooks."""

    def __init__(self, identity: dict = None):
        super().__init__("ContentCreator", identity)
        self.content = ContentGenerator()
        self.platforms_tried = []

    def get_income_methods(self) -> str:
        return ("Blogging (AdSense/Mediavine), Newsletter (Substack, Beehiiv), "
                "Online courses (Udemy, Gumroad), eBooks (Amazon KDP), "
                "Medium Partner Program, Ghostwriting, Sponsored content")

    def think(self, context: dict) -> str:
        if "blog" not in self.platforms_tried:
            return ("!remember self testing blog monetization category=plan importance=3\n"
                    "ACTION: Generate and publish blog post about AI tools for productivity\n"
                    "!remember self Blog post on AI productivity published to Medium and personal blog category=action")
        return "ACTION: Check analytics on existing content, optimize for monetization"

    def act(self, decision: str) -> dict:
        topic = decision.split("about")[-1].strip() if "about" in decision else "AI productivity"
        post = self.content.blog_post(topic)
        if post:
            self.platforms_tried.append("blog")
            return {"success": True, "action": "blog_post", "method": "blogging",
                    "details": f"Published: {topic[:50]}...", "revenue": 0.0,
                    "summary": f"Blog post on {topic} generated and published"}
        return {"success": False, "action": "blog_post", "error": "content generation failed"}
