"""Email pool — one email per agent, all share password 'markchomba'.

Each agent claims one email on init. If an agent needs extra accounts,
it can draw from the pool. The pool file persists so assignments survive
restarts.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger


POOL_FILE = Path("data") / "email_pool.json"
PASSWORD = "markchomba"

ALL_EMAILS = [
    "pkrshots@gmail.com",
    "mc5608487@gmail.com",
    "peterndege59@gmail.com",
    "nyagakipchoge@gmail.com",
    "profwajakoyah@gmail.com",
    "holyscientist42@gmail.com",
    "ndegecaleb28@gmail.com",
    "lilianewangare@gmail.com",
    "juniormacharia21@gmail.com",
    "partycrusher07@gmail.com",
    "p9453471@gmail.com",
    "maxi34663@gmail.com",
]


def _load_pool() -> dict:
    """Load pool state: {email: assigned_agent_or_null}."""
    if POOL_FILE.exists():
        try:
            return json.loads(POOL_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_pool(pool: dict):
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(json.dumps(pool, indent=2))


def get_available_emails() -> list[str]:
    pool = _load_pool()
    taken = set(pool.keys())
    return [e for e in ALL_EMAILS if e not in taken]


def assign_email(agent_name: str) -> Optional[str]:
    """Assign an email to an agent. Returns the email or None if pool exhausted."""
    pool = _load_pool()
    # Check if agent already has one
    for email, owner in pool.items():
        if owner == agent_name:
            return email
    # Assign first available
    available = get_available_emails()
    if not available:
        logger.warning(f"No emails left for {agent_name}")
        return None
    email = available[0]
    pool[email] = agent_name
    _save_pool(pool)
    logger.info(f"Assigned {email} to {agent_name}")
    return email


def release_email(agent_name: str):
    """Release an agent's email back to the pool."""
    pool = _load_pool()
    to_release = [e for e, o in pool.items() if o == agent_name]
    for email in to_release:
        del pool[email]
    _save_pool(pool)


def list_assignments() -> dict:
    """Return {agent_name: email} for all assignments."""
    pool = _load_pool()
    rev = {}
    for email, owner in pool.items():
        rev[owner] = email
    return rev


def get_email(agent_name: str) -> Optional[str]:
    """Get the email assigned to an agent."""
    return list_assignments().get(agent_name)


def get_all_emails() -> list[str]:
    return list(ALL_EMAILS)
