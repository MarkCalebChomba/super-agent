import os
import time
from .base_agent import BaseAgent
from tools.content_gen import ContentGenerator

class PlatformAgent(BaseAgent):
    """Platform-specific monetization: Medium, Substack, Patreon, Gumroad, Ko-fi."""

    def __init__(self, identity: dict = None):
        super().__init__("PlatformMonetizer", identity)
        self.content = ContentGenerator()
        self.platform_cycles = ["medium", "substack", "patreon", "gumroad", "ko-fi"]
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Medium Partner Program, Substack subscriptions, "
                "Patreon memberships, Gumroad digital sales, "
                "Ko-fi donations, Buy Me a Coffee, "
                "Teachable courses, Podia memberships")

    def build(self) -> dict:
        platform = self.platform_cycles[self.idx % len(self.platform_cycles)]
        self.idx += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{platform}_content_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        if platform == "medium":
            article = self.content.blog_post("How I Built an AI Agent That Makes Money While I Sleep")
            content = f"# How I Built an AI Agent That Makes Money While I Sleep\n\n{article or 'Published on Medium'}\n"
        elif platform == "patreon":
            content = f"""# Patreon Tier Setup - {ts}

## Tier 1: Supporter ($5/mo)
- Early access to articles
- Monthly Q&A

## Tier 2: Pro ($15/mo)
- Everything in Tier 1
- Exclusive tutorials
- Discord role

## Tier 3: VIP ($50/mo)
- Everything in Tier 2
- 1-on-1 consulting session
- Source code access
"""
        elif platform == "substack":
            content = self.content.blog_post("Weekly AI Automation Newsletter")
            content = f"# Weekly AI Automation Newsletter\n\n{content or 'Subscribe for weekly insights'}\n"
        else:
            content = f"""# {platform.title()} Content - {ts}

Digital products and offerings for {platform} audience.

## Available Now
- AI Productivity Guide: $19
- Automation Templates: $29
- Premium Tutorials: $49

Built by {self.name}
"""
        with open(filepath, "w") as f:
            f.write(content)
        return {"file": filepath, "summary": f"{platform} content published", "revenue": 0.0, "method": "platform_monetization"}
