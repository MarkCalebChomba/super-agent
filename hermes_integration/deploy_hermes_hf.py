"""Deploy Hermes Agent to Hugging Face Spaces.
Creates a Space that runs Hermes as a hosted API, giving all
Smart Agents remote access to Hermes's LLM + research tools.

Usage:
    python -m hermes_integration.deploy_hermes_hf

Requires: huggingface_hub, HF_TOKEN env var.
"""

import os
import sys
import json
from pathlib import Path

HF_TOKEN = os.getenv("HF_TOKEN", "")
USERNAME = os.getenv("HF_USERNAME", "Calebchomba")
SPACE_NAME = "hermes-agent"
ROOT = Path(__file__).parent.parent


def main():
    if not HF_TOKEN:
        print("ERROR: HF_TOKEN environment variable not set")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi, create_repo, upload_folder
        from huggingface_hub.utils import HfHubHTTPError
    except ImportError:
        print("ERROR: huggingface_hub not installed. pip install huggingface_hub")
        sys.exit(1)

    api = HfApi(token=HF_TOKEN)
    space_id = f"{USERNAME}/{SPACE_NAME}"

    print(f"Creating/updating Space: {space_id}")
    try:
        create_repo(
            space_id,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
            token=HF_TOKEN,
        )
        print(f"  Space ready: https://huggingface.co/spaces/{space_id}")
    except Exception as e:
        print(f"  Space error: {e}")

    secrets = {
        "HF_TOKEN": HF_TOKEN,
    }
    print("Setting secrets...")
    for key, value in secrets.items():
        try:
            api.add_space_secret(space_id, key, value, token=HF_TOKEN)
        except Exception as e:
            print(f"  {key}: {e}")

    files_to_upload = [
        "hermes_hf/app.py",
        "hermes_hf/Dockerfile",
        "hermes_hf/requirements.txt",
        "hermes_integration/agent_skills.py",
        "hermes_integration/__init__.py",
    ]

    print("Uploading files...")
    for local_path in files_to_upload:
        full_path = ROOT / local_path
        if not full_path.exists():
            print(f"  WARNING: {local_path} not found, skipping")
            continue
        repo_path = local_path.replace("hermes_hf/", "") if local_path.startswith("hermes_hf/") else local_path
        try:
            api.upload_file(
                path_or_fileobj=str(full_path),
                path_in_repo=repo_path,
                repo_id=space_id,
                repo_type="space",
                token=HF_TOKEN,
            )
            print(f"  {local_path} -> {repo_path}")
        except Exception as e:
            print(f"  {local_path}: {e}")

    print("Triggering build...")
    try:
        api.restart_space(space_id, token=HF_TOKEN)
        print("  Build triggered!")
    except Exception as e:
        print(f"  Build trigger: {e}")

    print(f"\n=== DEPLOYMENT COMPLETE ===")
    print(f"Space: https://huggingface.co/spaces/{space_id}")
    print(f"API:   https://{space_id.replace('/', '-')}.hf.space/api/eval")
    print(f"\nAfter build completes, set:")
    print(f"  HERMES_HF_URL=https://{space_id.replace('/', '-')}.hf.space")
    print(f"in your .env file. All agents will route through Hermes.")


if __name__ == "__main__":
    main()
