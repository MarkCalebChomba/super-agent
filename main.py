#!/usr/bin/env python3
"""Internet Smart Agent — autonomous multi-agent system for online income generation.

Each agent starts from a seed instruction and grows itself over time.
Agents are instruction sets (JSON), not Python classes.
Agents prefer existing open-source tools and modify them rather than building from scratch.

Usage:
    python main.py                          # Run all agents
    python main.py --agent ContentCreator   # Run a single agent
    python main.py --list                   # List available agents
    python main.py --needs                  # Show pending resource requests
"""

import os
import sys
import json
import time
import signal
from pathlib import Path
from datetime import datetime
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from evolving_agent import EvolvingAgent


AGENTS_DIR = Path("instructions")
DATA_DIR = Path("data")
AGENT_NEEDS = DATA_DIR / "agent_needs.json"


def list_agents():
    """List all available agent instruction sets."""
    if not AGENTS_DIR.exists():
        print("No agents directory found. Create instruction files in instructions/")
        return

    agents = sorted(AGENTS_DIR.glob("*.json"))
    if not agents:
        print("No agent instruction files found.")
        return

    print(f"\n{'='*60}")
    print("  AVAILABLE AGENTS")
    print(f"{'='*60}")
    for agent_file in agents:
        name = agent_file.stem
        try:
            with open(agent_file) as f:
                data = json.load(f)
            seed = data.get("seed_instruction", "No seed instruction")
            instructions = len(data.get("instructions", []))
            evolutions = len(data.get("evolutions", []))
            sub_agents = list(data.get("sub_agents", {}).keys())
            perf = data.get("performance", {})

            print(f"\n  {name}")
            print(f"     Seed: {seed[:80]}...")
            print(f"     Learned instructions: {instructions} | Evolutions: {evolutions}")
            if sub_agents:
                print(f"     Sub-agents: {', '.join(sub_agents)}")
            print(f"     Cycles: {perf.get('cycles_run', 0)} | Successes: {perf.get('successful_outputs', 0)} | Failures: {perf.get('failed_outputs', 0)}")
        except json.JSONDecodeError:
            print(f"\n  {name} (invalid JSON)")
    print()


def show_needs():
    """Show pending resource requests from agents."""
    if not AGENT_NEEDS.exists():
        print("No agent needs file found.")
        return

    with open(AGENT_NEEDS) as f:
        needs = json.load(f)

    pending = [n for n in needs if n.get("status") == "pending"]
    if not pending:
        print("No pending resource requests.")
        return

    print(f"\n{'='*60}")
    print(f"  PENDING RESOURCE REQUESTS ({len(pending)})")
    print(f"{'='*60}")
    for need in pending:
        print(f"\n  [{need.get('priority', 'normal').upper()}] {need['agent']} needs: {need['resource']}")
        print(f"     Requested: {need.get('requested_at', 'unknown')}")
        print(f"     Message: {need.get('message', '')}")
        guide = need.get("provision_guide", {})
        if guide.get("steps"):
            print(f"     Provision steps:")
            for i, step in enumerate(guide["steps"], 1):
                print(f"       {i}. {step}")
        if guide.get("env_template"):
            print(f"     Env template:")
            for k, v in guide["env_template"].items():
                print(f"       {k}={v}")
    print()


def mark_provisioned(resource_id: str = None):
    """Mark a resource request as provisioned (manual intervention complete)."""
    if not AGENT_NEEDS.exists():
        print("No agent needs file.")
        return

    with open(AGENT_NEEDS) as f:
        needs = json.load(f)

    if resource_id:
        for need in needs:
            if need.get("resource") == resource_id and need["status"] == "pending":
                need["status"] = "provisioned"
                need["provisioned_at"] = datetime.now().isoformat()
                print(f"Marked {need['agent']}'s {resource_id} as provisioned")
    else:
        mark_all = input("Mark ALL pending requests as provisioned? (y/N): ").lower()
        if mark_all == "y":
            for need in needs:
                if need["status"] == "pending":
                    need["status"] = "provisioned"
                    need["provisioned_at"] = datetime.now().isoformat()
            print("All pending requests marked as provisioned")

    with open(AGENT_NEEDS, "w") as f:
        json.dump(needs, f, indent=2)


def init_default_agents():
    """Initialize default agent instruction files if they don't exist."""
    default_seeds = {
        "ContentCreator": "Make money by creating and publishing content across platforms",
        "SocialMediaMonetizer": "Make money by building and monetizing social media audiences",
        "VideoCreator": "Make money by creating and monetizing video content",
        "EcommerceMerchant": "Make money by selling products through e-commerce",
        "AffiliateMarketer": "Make money through affiliate marketing commissions",
        "CryptoTrader": "Make money through cryptocurrency trading and DeFi",
        "FreelanceOptimizer": "Make money by selling services on freelance platforms",
        "SaaSBuilder": "Make money by building and selling software products",
        "DeFiOptimizer": "Make money through decentralized finance yield optimization",
        "DataArbitrageur": "Make money through data arbitrage and market inefficiencies",
        "ServiceProvider": "Make money by providing digital services and consulting",
        "PlatformMonetizer": "Make money by building and monetizing digital platforms",
        "Hermes": "Make money by orchestrating and coordinating other agents",
    }

    created = []
    for name, seed in default_seeds.items():
        agent_path = AGENTS_DIR / f"{name}.json"
        if not agent_path.exists():
            agent = EvolvingAgent(name, seed)
            created.append(name)
            logger.info(f"Initialized agent: {name}")

    if created:
        print(f"Initialized {len(created)} new agents: {', '.join(created)}")


def run_single(agent_name: str, max_cycles: int = None):
    """Run a single agent."""
    agent_path = AGENTS_DIR / f"{agent_name}.json"
    if not agent_path.exists():
        print(f"Agent '{agent_name}' not found. Available agents:")
        list_agents()
        return

    print(f"\nStarting agent: {agent_name}")
    agent = EvolvingAgent(agent_name)
    agent.run_loop(max_cycles=max_cycles)


def run_all():
    """Run all agents sequentially with idle-time handling."""
    agents = sorted(AGENTS_DIR.glob("*.json"))
    if not agents:
        print("No agents found. Run --init first or create instruction files.")
        return

    print(f"\nStarting {len(agents)} agents...")
    instances = []

    for agent_file in agents:
        name = agent_file.stem
        try:
            agent = EvolvingAgent(name)
            instances.append(agent)
            logger.info(f"Loaded agent: {name}")
        except Exception as e:
            logger.error(f"Failed to load agent {name}: {e}")

    logger.info(f"Running {len(instances)} agents sequentially")
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.info("Shutdown signal received, stopping agents...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while running:
            for agent in instances:
                if not running:
                    break
                try:
                    result = agent.run_cycle()
                    if result.get("idle"):
                        logger.info(f"{agent.name}: waiting for resources")
                    elif result.get("success"):
                        logger.info(f"{agent.name}: completed successfully")
                    else:
                        logger.info(f"{agent.name}: no output this cycle")
                except Exception as e:
                    logger.error(f"{agent.name} cycle error: {e}")
                time.sleep(2)
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
    finally:
        for agent in instances:
            agent.stop()
        logger.info("All agents stopped")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Internet Smart Agent System")
    parser.add_argument("--agent", type=str, help="Run a specific agent by name")
    parser.add_argument("--list", action="store_true", help="List all agents")
    parser.add_argument("--needs", action="store_true", help="Show pending resource requests")
    parser.add_argument("--provision", type=str, nargs="?", const=True, help="Mark resource(s) as provisioned")
    parser.add_argument("--init", action="store_true", help="Initialize default agent instruction files")
    parser.add_argument("--cycles", type=int, default=None, help="Max cycles for single agent run")
    args = parser.parse_args()

    if args.list:
        list_agents()
    elif args.needs:
        show_needs()
    elif args.provision:
        resource_id = args.provision if isinstance(args.provision, str) else None
        mark_provisioned(resource_id)
    elif args.init:
        init_default_agents()
    elif args.agent:
        run_single(args.agent, max_cycles=args.cycles)
    else:
        run_all()


if __name__ == "__main__":
    main()
