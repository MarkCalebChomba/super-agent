from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class ServicesAgent(BaseAgent):
    """Services & consulting: coaching, consulting, digital services."""

    def __init__(self, identity: dict = None):
        super().__init__("ServiceProvider", identity)
        self.content = ContentGenerator()

    def get_income_methods(self) -> str:
        return ("AI consulting for businesses, Coaching programs, "
                "Digital marketing services, Virtual assistant services, "
                "Course creation & cohort-based courses, "
                "Done-for-you content packages, Technical writing services")

    def think(self, context: dict) -> str:
        return ("!remember self creating AI consulting service offer category=plan importance=3\n"
                "ACTION: Write landing page copy for 'AI Automation Consulting' service\n"
                "!remember self Service page created: AI Automation Consulting for SMBs at $500/session category=action")

    def act(self, decision: str) -> dict:
        copy = self.content.ad_copy("landing_page", "AI Automation Consulting",
                                    "small business owners", "lead_generation")
        return {"success": True, "action": "service_created", "method": "consulting",
                "details": f"Landing page: {copy[:80] if copy else 'AI Consulting'}",
                "revenue": 0.0, "summary": "AI consulting service offer created"}
