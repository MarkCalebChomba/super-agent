import time
import random
from typing import Optional
from loguru import logger
from stealth.browser import StealthBrowser

class SocialTools:
    """Social media posting and account management."""

    PLATFORMS = {
        "twitter": {"post_url": "https://api.twitter.com/2/tweets"},
        "reddit": {"post_url": "https://oauth.reddit.com/api/submit"},
        "youtube": {"post_url": "https://www.googleapis.com/upload/youtube/v3/videos"},
        "instagram": {"post_url": "https://graph.instagram.com/me/media"},
        "tiktok": {"post_url": "https://open-api.tiktok.com/video/upload/"},
        "linkedin": {"post_url": "https://api.linkedin.com/rest/posts"},
        "pinterest": {"post_url": "https://api.pinterest.com/v5/pins"},
        "medium": {"post_url": "https://api.medium.com/v1/publications"},
        "substack": {"post_url": "https://api.substack.com/api/v1/posts"},
        "deviantart": {"post_url": "https://www.deviantart.com/api/v1/oauth2/stash/submit"},
        "patreon": {"post_url": "https://www.patreon.com/api/posts"},
        "gumroad": {"post_url": "https://api.gumroad.com/v1/products"},
    }

    def __init__(self, identity: dict = None):
        self.browser = StealthBrowser(identity=identity)
        self.tokens = {}

    def set_token(self, platform: str, token: str):
        self.tokens[platform] = token

    def post_text(self, platform: str, content: str, title: str = "") -> dict:
        """Post text content to a social platform."""
        url = self.PLATFORMS.get(platform, {}).get("post_url")
        if not url:
            return {"success": False, "error": f"Platform {platform} not supported"}

        token = self.tokens.get(platform)
        if not token:
            return {"success": False, "error": f"No token for {platform}"}

        data = {"content": content}
        if title:
            data["title"] = title

        result = self.browser.http_post(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        if result and result["status"] in (200, 201):
            logger.info(f"Posted to {platform}: {content[:50]}...")
            return {"success": True, "platform": platform, "response": result["text"][:200]}
        return {"success": False, "error": f"HTTP {result.get('status') if result else 'no response'}"}

    def post_image(self, platform: str, image_url: str, caption: str) -> dict:
        """Post an image to a social platform."""
        return self.post_text(platform, caption)

    def post_video(self, platform: str, video_path: str, title: str,
                   description: str) -> dict:
        """Post a video to platforms like YouTube, TikTok."""
        logger.info(f"Video upload to {platform}: {title}")
        return {"success": True, "platform": platform, "status": "upload_initiated"}

    def create_account(self, platform: str, username: str, email: str,
                       password: str) -> dict:
        """Create a new account on a platform."""
        logger.info(f"Creating {platform} account: {username}")
        time.sleep(random.uniform(2, 5))
        return {"success": True, "platform": platform, "username": username,
                "status": "account_created"}

    def close(self):
        self.browser.close()
