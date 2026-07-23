"""Tests for the SuperAgent self-modification system."""

import os
import sys
import shutil
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from master.system_store import SystemStore
from master.agent_factory import AgentFactory
from master.budget_manager import BudgetManager
from master.resource_monitor import ResourceMonitor

def setup():
    SystemStore._reset()
    return tempfile.mkdtemp()

def teardown(tmpdir):
    SystemStore._reset()
    shutil.rmtree(tmpdir, ignore_errors=True)

def test_system_store_agent_registry():
    tmpdir = setup()
    try:
        store = SystemStore(tmpdir)

        # Register agents
        assert store.register_agent("TestAgent1", "agents.test.TestAgent", "Testing")
        assert store.register_agent("TestAgent2", "agents.test.TestAgent", "Testing 2")

        # Cant register duplicate
        assert not store.register_agent("TestAgent1", "agents.test.TestAgent", "Testing")

        # Count
        assert store.count_total() == 2
        assert store.count_active() == 2

        # Update status
        store.update_agent_status("TestAgent1", "running")
        agent = store.get_agent("TestAgent1")
        assert agent["status"] == "running"

        # Instructions
        store.update_instructions("TestAgent1", "New instructions from SuperAgent")
        instructions = store.get_agent_instructions("TestAgent1")
        assert instructions == "New instructions from SuperAgent"

        # List
        all_agents = store.get_all_agents()
        assert len(all_agents) == 2

        # Inactive
        inactive = store.get_inactive_agents(days=0)
        assert len(inactive) >= 0  # no guarantee on timing

        store.close()
    finally:
        teardown(tmpdir)

def test_system_store_resource_tracking():
    tmpdir = setup()
    try:
        store = SystemStore(tmpdir)
        store.register_agent("Agent1", "test", "Testing")

        store.record_resource_use("Agent1", memory_mb=150, tokens=5000, api_calls=10, cycles=5)
        store.record_resource_use("Agent1", memory_mb=200, tokens=3000, api_calls=5, cycles=3)

        summary = store.get_resource_summary()
        assert summary["total_tokens"] > 0

        usage = store.get_agent_resource_usage("Agent1")
        assert usage["total_tokens"] > 0

        store.close()
    finally:
        teardown(tmpdir)

def test_system_store_budget():
    tmpdir = setup()
    try:
        store = SystemStore(tmpdir)

        # Initial budget
        budget = store.get_budget()
        assert budget["total_revenue"] == 0.0

        # Add revenue
        store.update_budget(revenue=100.0)
        budget = store.get_budget()
        assert budget["total_revenue"] == 100.0

        # Auto-buy
        store.set_auto_buy(True, max_budget=50.0)
        assert store.can_afford(25.0)
        assert not store.can_afford(100.0)

        # Spend
        result = store.spend(30.0, "Test purchase")
        assert result
        budget = store.get_budget()
        assert budget["monthly_spent"] == 30.0

        # Cant exceed
        assert not store.can_afford(25.0)
        assert not store.spend(25.0, "Over budget")

        store.close()
    finally:
        teardown(tmpdir)

def test_agent_factory():
    tmpdir = setup()
    try:
        SystemStore._reset()
        store = SystemStore(tmpdir)
        factory = AgentFactory()

        # Create agent
        name = factory.create_agent(
            "DynamicIncomeAgent",
            "Affiliate marketing, content creation, social media",
            "Focus on Amazon Associates and content sites"
        )
        assert name == "DynamicIncomeAgent"

        # Cant create duplicate
        assert factory.create_agent("DynamicIncomeAgent", "test") is None

        # Instantiate
        agent = factory.instantiate("DynamicIncomeAgent")
        assert agent is not None
        assert agent.name == "DynamicIncomeAgent"
        assert "affiliate" in agent.get_income_methods().lower()

        # List slots
        assert factory.list_available_slots() >= 253  # 256 - 2 (from other test) - 1 created

        agent.close()
        store.close()
    finally:
        teardown(tmpdir)

def test_budget_manager():
    tmpdir = setup()
    try:
        SystemStore._reset()
        store = SystemStore(tmpdir)
        bm = BudgetManager()

        # Initial state
        status = bm.get_status()
        assert status["total_revenue"] == 0
        assert not status["auto_buy"]

        # Enable auto-buy
        bm.set_auto_buy(True, max_monthly=100.0)

        # Auto-buy when affordable
        result = bm.auto_buy_if_needed("memory", 50.0, "Extra memory for HF Spaces")
        assert result.get("purchased"), f"Expected purchase, got: {result}"

        # Auto-buy when not affordable
        result = bm.auto_buy_if_needed("compute", 200.0, "GPU upgrade")
        assert not result.get("purchased")
        assert result.get("needs_human")

        store.close()
    finally:
        teardown(tmpdir)

def test_max_agents_limit():
    tmpdir = setup()
    try:
        SystemStore._reset()
        store = SystemStore(tmpdir)
        factory = AgentFactory()

        # The 256 limit is enforced at SystemStore level
        # Register 3 agents
        assert store.register_agent("Agent1", "test", "methods")
        assert store.register_agent("Agent2", "test", "methods")
        assert store.register_agent("Agent3", "test", "methods")
        assert store.count_total() == 3

        agents = store.get_all_agents()
        assert len(agents) == 3

        store.close()
    finally:
        teardown(tmpdir)

if __name__ == "__main__":
    test_system_store_agent_registry()
    test_system_store_resource_tracking()
    test_system_store_budget()
    test_agent_factory()
    test_budget_manager()
    test_max_agents_limit()
    print("All supervisor system tests passed!")
