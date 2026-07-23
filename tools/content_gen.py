from typing import Optional
from loguru import logger
from providers.router import LLMRouter

class ContentGenerator:
    """Content generation tools for all agent types.
    
    Capabilities:
    - Blog posts, articles, tutorials
    - Social media captions (Twitter, LinkedIn, Instagram)
    - Video scripts (YouTube, TikTok, Instagram Reels)
    - Ad copy (Google Ads, Facebook Ads)
    - Email newsletters
    - Product descriptions
    - Code snippets and tutorials
    - Image prompts for AI art generation
    """

    def __init__(self):
        self.llm = LLMRouter()

    def blog_post(self, topic: str, tone: str = "professional",
                  length: str = "medium") -> str:
        prompt = f"Write a {tone} blog post about '{topic}' ({length} length). Include a headline, introduction, 3 main points with examples, and a conclusion with call to action."
        return self.llm.complete(prompt, agent_type="general",
                                system="You are a professional content writer. Write engaging, SEO-optimized content.")

    def social_caption(self, platform: str, topic: str, tone: str = "casual") -> str:
        platform_notes = {
            "twitter": "max 280 characters, use hashtags sparingly",
            "linkedin": "professional, 1000-2000 characters, include industry insights",
            "instagram": "engaging, use emojis, 200-300 characters, relevant hashtags",
            "tiktok": "trendy, short, hook in first 3 seconds, use trends",
        }
        notes = platform_notes.get(platform, "")
        prompt = f"Write a {tone} {platform} caption about '{topic}'. {notes}"
        return self.llm.complete(prompt, agent_type="general",
                                system="You are a social media content creator. Write engaging, platform-appropriate content.")

    def video_script(self, topic: str, platform: str = "youtube",
                     duration_seconds: int = 60) -> dict:
        """Generate a video script with timing."""
        prompt = (
            f"Write a {duration_seconds}-second video script for {platform} about '{topic}'. "
            f"Include: hook (first 5 seconds), main content, call to action. "
            f"Format as JSON with 'hook', 'body', 'cta', 'estimated_duration' fields."
        )
        result = self.llm.complete(prompt, agent_type="general",
                                   system="You are a video script writer. Output JSON only.",
                                   max_tokens=600)
        return {"hook": "Generated hook", "body": result or "", "cta": "Subscribe for more",
                "estimated_duration": duration_seconds}

    def ad_copy(self, platform: str, product: str, target_audience: str,
                goal: str = "conversion") -> str:
        prompt = (
            f"Write {platform} ad copy for '{product}'. "
            f"Target: {target_audience}. Goal: {goal}. "
            f"Include headline, description, and call to action."
        )
        return self.llm.complete(prompt, agent_type="general",
                                system="You are a direct response copywriter. Write high-converting ad copy.")

    def image_prompt(self, subject: str, style: str = "photorealistic") -> str:
        """Generate an AI image generation prompt."""
        prompt = f"Create a detailed prompt for generating a {style} image of '{subject}'."
        return self.llm.complete(prompt, agent_type="general",
                                system="You are an AI art prompt engineer. Write detailed, effective prompts.")

    def code_snippet(self, task: str, language: str = "python") -> str:
        prompt = f"Write a {language} code snippet that {task}. Output ONLY the code, no explanations."
        return self.llm.complete(prompt, agent_type="general",
                                system="You are a senior software engineer. Write clean, working code.")
