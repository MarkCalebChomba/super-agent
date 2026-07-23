import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class FreelanceAgent(BaseAgent):
    """Freelancing platforms: Upwork, Fiverr, Freelancer, Toptal."""

    def __init__(self, identity: dict = None):
        super().__init__("FreelanceOptimizer", identity)
        self.content = ContentGenerator()
        self.gigs = [
            ("AI-Powered Content Writing", "blog posts, articles, SEO content"),
            ("Python Automation Scripts", "data processing, web scraping, bots"),
            ("AI Chatbot Development", "customer service, lead generation bots"),
            ("Data Analysis & Visualization", "business intelligence, dashboards"),
            ("AI Consulting", "strategy, implementation, training"),
        ]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Upwind freelancing, Fiverr gigs, Freelancer contests, "
                "Toptal premium projects, Guru, PeoplePerHour, "
                "AI-powered service gigs (content, code, design)")

    def build(self) -> dict:
        title, desc = self.gigs[self.idx % len(self.gigs)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"gig_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        copy = self.content.ad_copy("fiverr", title, "business owners")
        gig = f"""# {title}

## Description
{copy or f'I will provide professional {desc} services for your business.'}

## Packages
- **Basic**: $50 - Single project
- **Standard**: $150 - Up to 3 revisions
- **Premium**: $500 - Unlimited support + priority delivery

## Delivery Time
3-7 days depending on scope
"""
        with open(filepath, "w") as f:
            f.write(gig)
        return {"file": filepath, "summary": f"Fiverr gig: {title}", "revenue": 0.0, "method": "freelancing"}
