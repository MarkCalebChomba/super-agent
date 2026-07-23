import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class ServicesAgent(BaseAgent):
    """Services & consulting: coaching, consulting, digital services."""

    def __init__(self, identity: dict = None):
        super().__init__("ServiceProvider", identity)
        self.content = ContentGenerator()
        self.services = [
            ("AI Automation Consulting", "small business owners"),
            ("Custom Chatbot Development", "ecommerce stores"),
            ("Data Pipeline Setup", "startups"),
            ("Social Media Automation", "content creators"),
            ("Python Scripting & Automation", "agencies"),
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("AI consulting for businesses, Coaching programs, "
                "Digital marketing services, Virtual assistant services, "
                "Course creation & cohort-based courses, "
                "Done-for-you content packages, Technical writing services")

    def build(self) -> dict:
        service, audience = self.services[self.idx % len(self.services)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"service_page_{ts}.html"
        filepath = os.path.join(self.build_dir, filename)
        copy = self.content.ad_copy("landing_page", service, audience, "lead_generation")
        html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{service}</title></head>
<body style="font-family:sans-serif;max-width:800px;margin:auto;padding:2rem;">
<h1>{service}</h1>
<p>{copy or f'Professional {service.lower()} services for {audience}.'}</p>
<h2>Pricing</h2>
<ul>
<li>Free Consultation: 30 min</li>
<li>Starter Package: $500</li>
<li>Growth Package: $2,000</li>
<li>Enterprise: Custom quote</li>
</ul>
<h2>Book a Call</h2>
<p>Contact: agent@{self.name.lower()}.com</p>
</body>
</html>"""
        with open(filepath, "w") as f:
            f.write(html)
        return {"file": filepath, "summary": f"Service page: {service}", "revenue": 0.0, "method": "consulting"}
