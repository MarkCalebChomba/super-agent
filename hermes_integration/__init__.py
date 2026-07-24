"""Hermes Agent integration for the Smart Agent System.
Hermes (github.com/NousResearch/hermes-agent, 219k★) is a self-improving
AI agent with built-in learning loops, skill creation, and persistent memory.

This module provides:
- HermesRunner: install, manage, and execute Hermes tasks
- HermesSkillBridge: import/export skills between Hermes and Smart Agents
- install_hermes(): one-shot installer for Windows/macOS/Linux
"""

from .hermes_runner import HermesRunner, HermesSkillBridge, install_hermes

__all__ = ["HermesRunner", "HermesSkillBridge", "install_hermes"]
