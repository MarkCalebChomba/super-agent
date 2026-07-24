"""Hermes Agent runner — install, execute, and bridge skills with Hermes.

Hermes from Nous Research (219k★) is a self-improving agent with:
- Persistent memory (FTS5 core memory + session search)
- Autonomous skill creation from experience
- Skills self-improve during use
- 40+ built-in tools + MCP server integration
- Messaging gateways (Telegram, Discord, Slack)

This module wraps Hermes CLI and core APIs for use within this system.
"""

import os
import re
import sys
import json
import time
import shutil
import subprocess
import platform
from pathlib import Path
from typing import Optional
from loguru import logger


HERMES_HOME = Path.home() / ".hermes"
HERMES_BIN = HERMES_HOME / "bin"
HERMES_CHECKOUT = HERMES_HOME / "hermes-agent"
SKILLS_DIR = HERMES_HOME / "skills"


def install_hermes() -> bool:
    """Install Hermes Agent via the official installer.
    
    On Windows: uses the PowerShell installer
    On macOS/Linux: uses the bash installer
    Returns True if installed successfully or already present.
    """
    if shutil.which("hermes"):
        logger.info("Hermes already installed")
        return True

    system = platform.system()
    logger.info(f"Installing Hermes Agent on {system}...")

    try:
        if system == "Windows":
            ps_cmd = (
                'iex (irm https://hermes-agent.nousresearch.com/install.ps1)'
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                logger.error(f"Hermes install failed: {result.stderr[:500]}")
                return False
        else:
            bash_cmd = 'curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash'
            result = subprocess.run(
                ["bash", "-c", bash_cmd],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                logger.error(f"Hermes install failed: {result.stderr[:500]}")
                return False

        logger.info("Hermes Agent installed successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.error("Hermes install timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Hermes install error: {e}")
        return False


class HermesRunner:
    """Run Hermes tasks and interact with its CLI.
    
    Hermes is a standalone agent — we communicate with it via CLI commands
    and its shared filesystem (skills, memory, config).
    """

    def __init__(self):
        self._available = self._check_hermes()

    def _check_hermes(self) -> bool:
        return shutil.which("hermes") is not None

    @property
    def available(self) -> bool:
        return self._available

    def run_task(self, prompt: str, timeout: int = 120) -> Optional[str]:
        """Run a task through Hermes CLI and capture the response.
        
        Uses `hermes --eval` or pipes input to hermes process.
        """
        if not self._available:
            logger.warning("Hermes not available — install with install_hermes()")
            return None

        try:
            result = subprocess.run(
                ["hermes", "--eval", prompt],
                capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                return result.stdout
            logger.warning(f"Hermes task stderr: {result.stderr[:300]}")
            return result.stdout or None
        except subprocess.TimeoutExpired:
            logger.error(f"Hermes task timed out after {timeout}s")
            return None
        except Exception as e:
            logger.error(f"Hermes task error: {e}")
            return None

    def run_conversation(self, message: str, personality: str = "default") -> Optional[str]:
        """Send a message to Hermes in conversational mode."""
        return self.run_task(f"--personality {personality} {message}")

    def get_skills(self) -> list[dict]:
        """List all skills available in Hermes."""
        skills = []
        if SKILLS_DIR.exists():
            for skill_dir in SKILLS_DIR.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({
                            "name": skill_dir.name,
                            "path": str(skill_file),
                            "source": "hermes",
                        })
        return skills

    def install_skill(self, name: str, skill_content: str) -> bool:
        """Install a new skill into Hermes's skill directory."""
        target = SKILLS_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        skill_file = target / "SKILL.md"
        try:
            skill_file.write_text(skill_content)
            logger.info(f"Hermes skill installed: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to install Hermes skill {name}: {e}")
            return False

    def get_memory_summary(self) -> Optional[str]:
        """Get a summary of Hermes's current memory state."""
        return self.run_task("--eval", "Summarize your current memory and what you know about me.")

    def run_scheduled(self, task: str, cron_expr: str) -> bool:
        """Schedule a recurring task in Hermes's cron system."""
        result = self.run_task(f"Schedule this task: '{task}' with cron: {cron_expr}")
        return bool(result)

    def get_status(self) -> dict:
        """Get Hermes agent status."""
        status = {
            "available": self._available,
            "version": None,
            "skills_count": 0,
            "memory_available": False,
        }
        if self._available:
            try:
                result = subprocess.run(
                    ["hermes", "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    status["version"] = result.stdout.strip()
            except Exception:
                pass
            status["skills_count"] = len(self.get_skills())
            status["memory_available"] = (HERMES_HOME / "memory").exists()
        return status


class HermesSkillBridge:
    """Bidirectionally import/export skills between Hermes and Smart Agents.
    
    Hermes stores skills as SKILL.md files in ~/.hermes/skills/.
    Smart agents store skills in the SQLite memory store.
    This bridge keeps them in sync.
    """

    def __init__(self, memory_store=None):
        self.hermes = HermesRunner()
        self.memory = memory_store

    def export_to_hermes(self, agent_name: str) -> int:
        """Export smart agent skills to Hermes's skill directory."""
        if not self.memory:
            return 0

        skills = self.memory.get_skills(min_success_rate=0.3)
        count = 0
        for skill in skills:
            skill_content = (
                f"# {skill['name']}\n\n"
                f"{skill.get('description', '')}\n\n"
                f"## Procedure\n{skill.get('procedure', '')}\n\n"
                f"_Imported from {agent_name}_\n"
            )
            if self.hermes.install_skill(skill["name"], skill_content):
                count += 1
        return count

    def import_from_hermes(self) -> list[dict]:
        """Import Hermes skills into the smart agent system."""
        hermes_skills = self.hermes.get_skills()
        if not self.memory:
            return hermes_skills

        for skill in hermes_skills:
            try:
                path = Path(skill["path"])
                content = path.read_text()
                name_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                name = name_match.group(1) if name_match else skill["name"]
                desc_match = re.search(r'^(.+?)\n\n', content, re.MULTILINE)
                description = desc_match.group(1) if desc_match else content[:200]
                self.memory.add_skill(name, description, content[:1000])
            except Exception as e:
                logger.debug(f"Skill import failed: {e}")

        return hermes_skills
