import random
import json
from pathlib import Path
from typing import Optional

class FingerprintGenerator:
    """Generates realistic browser fingerprints for anti-detection.
    
    Used by Camoufox or undetected-chromedriver to spoof:
    - User agent (varies by OS)
    - Screen resolution
    - WebGL vendor/renderer
    - Timezone
    - Language
    - Platform
    """

    DESKTOP_RESOLUTIONS = [
        (1920, 1080), (1366, 768), (1536, 864), (1440, 900),
        (1680, 1050), (1280, 720), (2560, 1440),
    ]

    USER_AGENTS = {
        "windows": [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        ],
        "macos": [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        ],
        "linux": [
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ],
    }

    WEBGL_VENDORS = [
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)"),
    ]

    TIMEZONES = [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
        "Europe/London", "Europe/Berlin", "Europe/Paris", "Asia/Tokyo",
        "Asia/Shanghai", "Australia/Sydney", "Asia/Dubai",
    ]

    LANGUAGES = [
        "en-US,en;q=0.9", "en-GB,en;q=0.8", "en-CA,en;q=0.9",
        "de-DE,de;q=0.9,en;q=0.5", "fr-FR,fr;q=0.9,en;q=0.5",
        "ja-JP,ja;q=0.9,en;q=0.4", "zh-CN,zh;q=0.9,en;q=0.4",
    ]

    def __init__(self, identity: dict = None):
        self.identity = identity or {}
        self.fingerprint = self.generate(identity)

    def generate(self, identity: dict = None) -> dict:
        os_type = (identity or {}).get("os", random.choice(["windows", "macos", "linux"]))
        width, height = random.choice(self.DESKTOP_RESOLUTIONS)

        fp = {
            "user_agent": random.choice(self.USER_AGENTS.get(os_type, self.USER_AGENTS["windows"])),
            "screen_width": width,
            "screen_height": height,
            "timezone": random.choice(self.TIMEZONES),
            "language": random.choice(self.LANGUAGES),
            "platform": os_type,
            "webgl_vendor": random.choice(self.WEBGL_VENDORS)[0],
            "webgl_renderer": random.choice(self.WEBGL_VENDORS)[1],
            "device_memory": random.choice([4, 8, 16, 32]),
            "hardware_concurrency": random.choice([4, 6, 8, 12, 16]),
            "do_not_track": True,
            "color_depth": 24,
            "pixel_ratio": random.choice([1, 1.25, 1.5, 2]),
        }
        return fp

    def rotate(self):
        """Generate a new fingerprint."""
        self.fingerprint = self.generate(self.identity)

    def get_camoufox_args(self) -> list[str]:
        """Get command-line args for Camoufox browser launch."""
        fp = self.fingerprint
        return [
            f"--user-agent={fp['user_agent']}",
            f"--window-size={fp['screen_width']},{fp['screen_height']}",
            f"--lang={fp['language'].split(',')[0]}",
            f"--timezone={fp['timezone']}",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-gpu",
        ]

    def get_puppeteer_extra_args(self) -> dict:
        """Get args for undetected-chromedriver / puppeteer-extra."""
        fp = self.fingerprint
        return {
            "user_agent": fp["user_agent"],
            "viewport": {"width": fp["screen_width"], "height": fp["screen_height"]},
            "locale": fp["language"].split(",")[0],
            "timezone_id": fp["timezone"],
            "webgl_vendor": fp["webgl_vendor"],
            "webgl_renderer": fp["webgl_renderer"],
        }
