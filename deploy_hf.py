"""Deploy to Hugging Face Spaces via API.

Usage: python deploy_hf.py
Requires: huggingface_hub installed, HF_TOKEN env var set.
"""

import os
import sys
import json
from pathlib import Path

HF_TOKEN = os.getenv("HF_TOKEN", "")
SPACE_NAME = "super-agent-7-july-2026"
SPACE_TITLE = "Super Agent 7 July 2026"
USERNAME = "Calebchomba"

SECRETS = {
    "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
    "OPENROUTER_API_KEY_2": os.getenv("OPENROUTER_API_KEY_2", ""),
    "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
    "DEPLOY": "true",
    "PORT": "8080",
}

ROOT = Path(__file__).parent


def main():
    from huggingface_hub import HfApi, create_repo, upload_folder
    from huggingface_hub.utils import HfHubHTTPError

    api = HfApi(token=HF_TOKEN)

    # Step 1: Create the Space
    print(f"Creating Space: {SPACE_NAME}")
    try:
        space_id = f"{USERNAME}/{SPACE_NAME}"
        create_repo(
            space_id,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
            token=HF_TOKEN,
        )
        print(f"  Space ready: https://huggingface.co/spaces/{space_id}")
    except HfHubHTTPError as e:
        print(f"  Space creation error: {e}")
        # Might already exist, continue
    except Exception as e:
        print(f"  Error: {e}")
        # Try without username (if using org)
        space_id = SPACE_NAME

    # Step 2: Set secrets
    print("Setting secrets...")
    for key, value in SECRETS.items():
        try:
            # HF Spaces API for secrets via huggingface_hub
            api.add_space_secret(space_id, key, value, token=HF_TOKEN)
            print(f"  {key}: set")
        except Exception as e:
            print(f"  {key}: {e}")

    # Step 3: Upload all files
    print("Uploading files...")
    try:
        upload_folder(
            folder_path=str(ROOT),
            repo_id=space_id,
            repo_type="space",
            token=HF_TOKEN,
            ignore_patterns=[
                "__pycache__/", "*.pyc", ".env", ".git/",
                "data/", "*.db", "*.db-journal", "*.db-wal",
                ".DS_Store", ".vscode/", ".idea/",
            ],
        )
        print("  Upload complete!")
    except Exception as e:
        print(f"  Upload error: {e}")
        return

    # Step 4: Build the Space (trigger rebuild)
    print("Triggering build...")
    try:
        api.restart_space(space_id, token=HF_TOKEN)
        print("  Build triggered!")
    except Exception as e:
        print(f"  Build trigger: {e}")

    space_url = f"https://huggingface.co/spaces/{space_id}"
    print(f"\n=== DEPLOYMENT COMPLETE ===")
    print(f"Space URL: {space_url}")
    print(f"Direct app: {space_url.replace('spaces/', 'spaces/')}")
    print(f"\nNext steps:")
    print(f"1. Visit {space_url} to check build logs")
    print(f"2. Set up cron-job.org to ping {space_url.replace('huggingface.co/spaces/', 'huggingface.co/spaces/')} every 5 min")
    print(f"3. Open Telegram and message @saba_agentic_bot to test notifications")


if __name__ == "__main__":
    main()
