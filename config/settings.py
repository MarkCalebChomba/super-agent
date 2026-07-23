import os
import json
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path(__file__).parent
IDENTITIES_DIR = CONFIG_DIR / "identities"

def load_config() -> dict:
    """Load application configuration from environment and JSON config."""
    config_path = CONFIG_DIR / "app_config.json"
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)

    # Environment overrides
    config.setdefault("openrouter_key", os.getenv("OPENROUTER_API_KEY", ""))
    config.setdefault("groq_key", os.getenv("GROQ_API_KEY", ""))
    config.setdefault("telegram_token", os.getenv("TELEGRAM_BOT_TOKEN", ""))
    config.setdefault("telegram_chat_id", os.getenv("TELEGRAM_CHAT_ID", ""))
    config.setdefault("agent_names", [
        "ContentCreator", "SocialMediaMonetizer", "VideoCreator",
        "EcommerceMerchant", "AffiliateMarketer", "CryptoTrader",
        "FreelanceOptimizer", "SaaSBuilder", "DeFiOptimizer",
        "DataArbitrageur", "ServiceProvider", "PlatformMonetizer",
    ])
    config.setdefault("max_cycles_per_agent", 0)  # 0 = unlimited
    config.setdefault("data_dir", "data")
    return config

def get_identity(name: str) -> Optional[dict]:
    """Load identity file for an agent."""
    identity_file = IDENTITIES_DIR / f"{name}.json"
    if identity_file.exists():
        with open(identity_file) as f:
            return json.load(f)
    return None

def save_identity(name: str, identity: dict):
    IDENTITIES_DIR.mkdir(parents=True, exist_ok=True)
    identity_file = IDENTITIES_DIR / f"{name}.json"
    with open(identity_file, "w") as f:
        json.dump(identity, f, indent=2)
