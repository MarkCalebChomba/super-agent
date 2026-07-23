import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class AffiliateAgent(BaseAgent):
    """Affiliate marketing across all major programs."""

    def __init__(self, identity: dict = None):
        super().__init__("AffiliateMarketer", identity)
        self.content = ContentGenerator()
        self.products = [
            "Top 10 AI Writing Tools",
            "Best AI coding assistants compared",
            "AI image generators review",
            "Best productivity tools 2026",
            "Email marketing platforms guide",
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Amazon Associates, ClickBank, ShareASale, CJ Affiliate, "
                "Rakuten, Impact, PartnerStack, niche affiliate programs, "
                "Content sites with affiliate links")

    def build(self) -> dict:
        product = self.products[self.idx % len(self.products)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"affiliate_article_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        article = self.content.blog_post(product, "review", "long")
        if article:
            with open(filepath, "w") as f:
                f.write(f"# {product}\n\n{article}\n\n---\n*Affiliate links included*\n")
            return {"file": filepath, "summary": f"Affiliate article: {product}", "revenue": 0.0, "method": "affiliate_marketing"}
        return None
