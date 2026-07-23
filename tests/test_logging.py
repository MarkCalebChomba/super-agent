"""Tests for the logging system."""

import os
import sys
import shutil
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from log_system.agent_logger import AgentLogger, LogLevel
from log_system.central_log import CentralLog

def test_agent_logger():
    CentralLog._reset()
    tmpdir = tempfile.mkdtemp()
    try:
        log = AgentLogger("test_agent", tmpdir)
        log.info("Test info message")
        log.action("Test action taken")
        log.warning("Test warning")
        log.error("Test error")
        log.revenue("Test revenue", amount=10.50)
        log.cta("Test CTA — human attention needed")

        recent = log.get_recent(limit=10)
        assert len(recent) >= 5

        ctas = log.get_cta_pending()
        assert len(ctas) >= 1

        log.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_central_log():
    CentralLog._reset()
    central = CentralLog()
    central.receive("agent1", 20, "test message", "general")
    central.receive("agent1", 50, "URGENT: needs human", "cta", {"requires_human": True})

    ctas = central.get_unreviewed_ctas()
    assert len(ctas) >= 1

    health = central.get_agent_health()
    agent_names = [h["agent_name"] for h in health]
    assert "agent1" in agent_names

    central.mark_reviewed(ctas[0]["id"], "test")
    ctas_after = central.get_unreviewed_ctas()
    # Our just-reviewed CTA should no longer appear
    reviewed_ids = {c["id"] for c in ctas_after}
    assert ctas[0]["id"] not in reviewed_ids

if __name__ == "__main__":
    test_agent_logger()
    test_central_log()
    print("All logging tests passed!")
