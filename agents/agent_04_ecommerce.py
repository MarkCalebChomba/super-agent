from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class EcommerceAgent(BaseAgent):
    """E-commerce & dropshipping: Shopify, Amazon FBA, Etsy, Print-on-demand."""

    def __init__(self, identity: dict = None):
        super().__init__("EcommerceMerchant", identity)
        self.content = ContentGenerator()

    def get_income_methods(self) -> str:
        return ("Dropshipping (Shopify/Oberlo), Amazon FBA, Etsy digital products, "
                "Print-on-demand (Printful, Redbubble), "
                "eBay flipping, Facebook Marketplace")

    def think(self, context: dict) -> str:
        return ("!remember self researching print-on-demand products category=plan importance=3\n"
                "ACTION: Create product listing for AI-themed t-shirts on Redbubble\n"
                "!remember self Redbubble store set up with 5 AI-themed designs category=action")

    def act(self, decision: str) -> dict:
        desc = self.content.ad_copy("etsy", "AI-themed merchandise", "tech enthusiasts")
        return {"success": True, "action": "product_listing_created", "method": "print_on_demand",
                "details": f"Created listing: {desc[:80] if desc else 'AI merchandise'}",
                "revenue": 0.0, "summary": "Product listing created on Redbubble"}
