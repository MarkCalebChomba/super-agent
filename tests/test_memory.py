"""Tests for the Hermes-style memory system."""

import os
import sys
import tempfile
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.memory_store import MemoryStore
from memory.agent_memory import AgentMemory
from memory.consolidator import MemoryConsolidator

def test_memory_store_basic():
    tmpdir = tempfile.mkdtemp()
    try:
        store = MemoryStore("test_agent", tmpdir)
        store.add_core("self", "I am a test agent", "identity", 5)
        store.add_core("user", "User prefers email notifications", "preference", 3)

        all_mem = store.get_all_core()
        assert "self" in all_mem
        assert "user" in all_mem
        assert len(all_mem["self"]) == 1
        assert len(all_mem["user"]) == 1

        # Add session data for search to return results
        store.log_session("test_session_1", "agent", "I am a test agent saying hello")
        store.log_session("test_session_1", "system", "Test observation recorded")
        store.close()

        # Reopen to test FTS5 search
        store2 = MemoryStore("test_agent", tmpdir)
        results = store2.search_sessions("test agent")
        assert len(results) >= 1, f"Expected search results, got {len(results)}"
        store2.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_agent_memory():
    tmpdir = tempfile.mkdtemp()
    try:
        mem = AgentMemory("test_agent", tmpdir)
        sid = mem.start_session()
        assert sid is not None

        mem.remember("self", "Test memory entry", "test", 3)
        context = mem.build_core_context()
        assert "Test memory entry" in context

        # Test session logging
        mem.log_agent_turn("agent", "I am testing the memory system")
        mem.log_agent_turn("system", "Memory test completed")

        stats = mem.get_memory_stats()
        assert stats["agent"] == "test_agent"
        assert stats["core_token_estimate"] > 0
        mem.store.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def test_consolidation():
    tmpdir = tempfile.mkdtemp()
    try:
        store = MemoryStore("test_agent", tmpdir)
        consolidator = MemoryConsolidator(store, "test_agent")

        # Add enough entries to trigger consolidation
        for i in range(10):
            store.add_core("self", f"Test memory entry number {i}", "test", 3)

        all_mem = store.get_all_core()
        initial_count = len(all_mem.get("self", []))

        # The actual consolidation won't run without LLM
        # But the threshold check should work
        assert consolidator.check_and_consolidate() == False  # no LLM available in test

        store.trim_core_to_limit(100)
        all_mem = store.get_all_core()
        # Should still have entries, just maybe trimmed
        assert len(all_mem.get("self", [])) > 0
        store.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == "__main__":
    test_memory_store_basic()
    test_agent_memory()
    test_consolidation()
    print("All memory tests passed!")
