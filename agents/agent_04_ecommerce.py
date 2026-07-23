import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class EcommerceAgent(BaseAgent):
    """E-commerce & dropshipping: Shopify, Amazon FBA, Etsy, Print-on-demand."""

    def __init__(self, identity: dict = None):
        super().__init__("EcommerceMerchant", identity)
        self.content = ContentGenerator()
        self.products = [
            "AI-themed t-shirts",
            "Programmer mug designs",
            "Tech motivational posters",
            "AI agent sticker packs",
            "Developer hoodie designs",
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Dropshipping (Shopify/Oberlo), Amazon FBA, Etsy digital products, "
                "Print-on-demand (Printful, Redbubble), "
                "eBay flipping, Facebook Marketplace")

    def build(self) -> dict:
        product = self.products[self.idx % len(self.products)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"listing_{ts}.html"
        filepath = os.path.join(self.build_dir, filename)
        desc = self.content.ad_copy("etsy", product, "tech enthusiasts")
        html = f"""<!DOCTYPE html><html><head><title>{product}</title></head><body>
<h1>{product}</h1>
<p>{desc or 'Premium quality AI-themed merchandise'}</p>
<p>Price: $24.99</p>
<p>Platform: Print-on-demand</p>
</body></html>"""
        with open(filepath, "w") as f:
            f.write(html)
        return {"file": filepath, "summary": f"Product listing: {product}", "revenue": 0.0, "method": "print_on_demand"}
