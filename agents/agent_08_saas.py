from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class SaaSAgent(BaseAgent):
    """SaaS & digital products: tools, templates, APIs, plugins."""

    def __init__(self, identity: dict = None):
        super().__init__("SaaSBuilder", identity)
        self.content = ContentGenerator()

    def get_income_methods(self) -> str:
        return ("Micro-SaaS products, Notion templates, Webflow templates, "
                "WordPress plugins, Shopify apps, API-as-a-service, "
                "Chrome extensions, Mobile apps with in-app purchases")

    def think(self, context: dict) -> str:
        return ("!remember self brainstorming micro-SaaS ideas category=plan importance=3\n"
                "ACTION: Design Notion template for AI-powered project management\n"
                "!remember self Notion template created: 'AI Project Manager Pro' category=action")

    def act(self, decision: str) -> dict:
        snippet = self.content.code_snippet("create a Notion template API endpoint", "python")
        return {"success": True, "action": "digital_product_created", "method": "saas",
                "details": "Notion template for AI project management designed",
                "revenue": 0.0, "summary": "Digital product created for Gumroad"}
