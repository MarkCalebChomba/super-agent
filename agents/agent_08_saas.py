import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class SaaSAgent(BaseAgent):
    """SaaS & digital products: tools, templates, APIs, plugins."""

    def __init__(self, identity: dict = None):
        super().__init__("SaaSBuilder", identity)
        self.content = ContentGenerator()
        self.products = [
            ("AI Project Manager Pro", "notion_template"),
            ("SEO Content Analyzer", "web_app"),
            ("Social Media Scheduler", "api"),
            ("Lead Generation Bot", "bot"),
            ("Analytics Dashboard", "web_app"),
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Micro-SaaS products, Notion templates, Webflow templates, "
                "WordPress plugins, Shopify apps, API-as-a-service, "
                "Chrome extensions, Mobile apps with in-app purchases")

    def build(self) -> dict:
        name, ptype = self.products[self.idx % len(self.products)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{ptype}_{ts}.py"
        filepath = os.path.join(self.build_dir, filename)
        code = f'''"""
{name} - {ptype.replace("_", " ").title()}
Built by {self.name}
"""

import json
from datetime import datetime


class {name.replace(" ", "").replace("-", "")}:
    """Main application class."""
    
    def __init__(self, config: dict = None):
        self.config = config or {{}}
        self.created = datetime.utcnow().isoformat()
    
    def process(self, input_data: dict) -> dict:
        """Main processing method."""
        return {{
            "status": "success",
            "product": "{name}",
            "output": input_data,
            "timestamp": self.created,
        }}


if __name__ == "__main__":
    app = {name.replace(" ", "").replace("-", "")}()
    result = app.process({{"test": True}})
    print(json.dumps(result, indent=2))
'''
        with open(filepath, "w") as f:
            f.write(code)
        return {"file": filepath, "summary": f"SaaS product: {name}", "revenue": 0.0, "method": "saas"}
