"""Tests for base agent functionality."""

import os
import sys
import shutil
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.base_agent import BaseAgent

class TestAgent(BaseAgent):
    def get_income_methods(self) -> str:
        return "Test method only"

    def think(self, context: dict) -> str:
        return "ACTION: Test action\nOBSERVATION: test\n!remember self test entry category=test importance=1"

    def act(self, decision: str) -> dict:
        return {"success": True, "action": "test", "method": "testing",
                "details": "test action completed", "revenue": 0.0,
                "summary": "Test cycle completed"}

def test_base_agent_init():
    agent = TestAgent("TestBot")
    assert agent.name == "TestBot"
    assert agent.cycle_count == 0
    assert agent.llm is not None
    agent.close()

def test_base_agent_system_prompt():
    tmpdir = tempfile.mkdtemp()
    try:
        agent = TestAgent("TestBot", memory_dir=tmpdir, log_dir=tmpdir)
        prompt = agent.build_system_prompt()
        assert "TestBot" in prompt
        assert "CORE MEMORY" in prompt
        assert "test method only" in prompt.lower() or "Test method only" in prompt
        agent.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_base_agent_cycle():
    tmpdir = tempfile.mkdtemp()
    try:
        agent = TestAgent("TestBot", memory_dir=tmpdir, log_dir=tmpdir)
        result = agent.run_cycle()
        assert result["success"] == True
        assert result["action"] == "test"
        assert agent.cycle_count == 1
        agent.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_memory_commands():
    tmpdir = tempfile.mkdtemp()
    try:
        agent = TestAgent("TestBot", memory_dir=tmpdir, log_dir=tmpdir)
        agent._process_memory_commands("!remember self important_note Hello World category=test importance=5")
        context = agent.memory.build_core_context()
        assert "Hello World" in context
        agent.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    test_base_agent_init()
    test_base_agent_system_prompt()
    test_base_agent_cycle()
    test_memory_commands()
    print("All base agent tests passed!")
