"""Hugging Face Hub storage backend — persists data/ and build_output/ across Railway deploys.

Uses a HF dataset repo as a simple blob store. Falls back gracefully if HF token is missing.
"""
import os
import io
import json
import time
from pathlib import Path
from datetime import datetime
from loguru import logger

HF_REPO = os.getenv("HF_STORAGE_REPO", "MarkCalebChomba/super-agent-data")
HF_TOKEN = os.getenv("HF_TOKEN", "")
LOCAL_DIRS = ["data", "build_output"]

_hf_available = None


def _check_hf() -> bool:
    global _hf_available
    if _hf_available is not None:
        return _hf_available
    if not HF_TOKEN:
        logger.warning("HF_TOKEN not set — HF storage disabled")
        _hf_available = False
        return False
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=HF_TOKEN)
        api.repo_info(HF_REPO, repo_type="dataset")
        _hf_available = True
        logger.info("HF storage backend ready: {}", HF_REPO)
    except Exception:
        try:
            from huggingface_hub import HfApi
            api = HfApi(token=HF_TOKEN)
            api.create_repo(HF_REPO, repo_type="dataset", exist_ok=True, private=True)
            _hf_available = True
            logger.info("Created HF dataset repo: {}", HF_REPO)
        except Exception as e:
            logger.warning("HF storage unavailable (will use local only): {}", e)
            _hf_available = False
    return _hf_available


def _hfa() -> object:
    from huggingface_hub import HfApi
    return HfApi(token=HF_TOKEN)


def pull_all():
    """Download all tracked directories from HF Hub to local."""
    if not _check_hf():
        return
    api = _hfa()
    for rel_dir in LOCAL_DIRS:
        local = Path(rel_dir)
        local.mkdir(parents=True, exist_ok=True)
        try:
            files = api.list_repo_tree(HF_REPO, repo_type="dataset", path=rel_dir)
            for f in files:
                if hasattr(f, "path") and not getattr(f, "is_directory", False):
                    rel_path = f.path
                    local_path = local / Path(rel_path).relative_to(rel_dir)
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    api.hf_hub_download(
                        HF_REPO, repo_type="dataset", filename=rel_path,
                        local_dir=str(local.parent), local_dir_use_symlinks=False,
                        force_download=True,
                    )
            logger.info("HF sync: pulled {} files from {}", len(list(local.rglob("*"))), rel_dir)
        except Exception as e:
            logger.debug("HF sync: no remote files for {} ({}): {}", rel_dir, type(e).__name__, e)


def push_all():
    """Upload all tracked directories from local to HF Hub."""
    if not _check_hf():
        return
    api = _hfa()
    api.upload_folder(
        repo_id=HF_REPO,
        repo_type="dataset",
        folder_path="data",
        path_in_repo="data",
        ignore_patterns=["*.db-wal", "*.db-shm", "__pycache__"],
        delete_patterns=["*.db-wal", "*.db-shm"],
    )
    if Path("build_output").exists():
        api.upload_folder(
            repo_id=HF_REPO,
            repo_type="dataset",
            folder_path="build_output",
            path_in_repo="build_output",
            ignore_patterns=["__pycache__"],
        )
    logger.info("HF sync: pushed data/ and build_output/ to {}", HF_REPO)


def push_file(local_path: str):
    """Upload a single file to HF Hub."""
    if not _check_hf():
        return
    p = Path(local_path)
    if not p.exists():
        return
    rel = str(p.as_posix())
    try:
        api = _hfa()
        api.upload_file(
            repo_id=HF_REPO,
            repo_type="dataset",
            path_or_fileobj=str(p),
            path_in_repo=rel,
        )
    except Exception as e:
        logger.debug("HF sync: failed to push {}: {}", local_path, e)
