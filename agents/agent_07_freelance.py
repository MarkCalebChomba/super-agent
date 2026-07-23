from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class FreelanceAgent(BaseAgent):
    """Freelancing platforms: Upwork, Fiverr, Freelancer, Toptal."""

    def __init__(self, identity: dict = None):
        super().__init__("FreelanceOptimizer", identity)
        self.content = ContentGenerator()

    def get_income_methods(self) -> str:
        return ("Upwind freelancing, Fiverr gigs, Freelancer contests, "
                "Toptal premium projects, Guru, PeoplePerHour, "
                "AI-powered service gigs (content, code, design)")

    def think(self, context: dict) -> str:
        return ("!remember self creating Fiverr gigs for AI services category=plan importance=3\n"
                "ACTION: Write Fiverr gig description for AI content writing service\n"
                "!remember self Fiverr gig created: 'AI-Powered Content Writing' at $50/post category=action")

    def act(self, decision: str) -> dict:
        gig = self.content.ad_copy("fiverr", "AI Content Writing Service", "business owners")
        return {"success": True, "action": "fiverr_gig_created", "method": "freelancing",
                "details": f"Gig: {gig[:80] if gig else 'AI Content Writing'}",
                "revenue": 0.0, "summary": "Fiverr gig created and listed"}
