#!/usr/bin/env python3
"""Internet Smart Agent — autonomous multi-agent system for online income generation.

Usage:
    python main.py                    # Run all agents with orchestrator
    python main.py --agent Content    # Run a single agent
    python main.py --list             # List available agents
    python main.py --init-db          # Initialize databases only
"""

import os
import sys
import threading
import argparse
from loguru import logger

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config.settings import load_config, get_identity
from db.init_db import init_database


def start_health_server(port: int = 8080):
    """Start health server in a daemon thread for cron-job.org pings."""
    try:
        from health_server import run_health_server
        import threading
        thread = threading.Thread(target=run_health_server, args=(port,),
                                  daemon=True, name="health-server")
        thread.start()
        logger.info(f"Health server running on port {port}")
        return thread
    except Exception as e:
        logger.warning(f"Health server not started: {e}")


def get_agent_class(name: str):
    mapping = {
        "ContentCreator": ("agents.agent_01_content", "ContentAgent"),
        "SocialMediaMonetizer": ("agents.agent_02_social", "SocialMediaAgent"),
        "VideoCreator": ("agents.agent_03_video", "VideoAgent"),
        "EcommerceMerchant": ("agents.agent_04_ecommerce", "EcommerceAgent"),
        "AffiliateMarketer": ("agents.agent_05_affiliate", "AffiliateAgent"),
        "CryptoTrader": ("agents.agent_06_trading", "TradingAgent"),
        "FreelanceOptimizer": ("agents.agent_07_freelance", "FreelanceAgent"),
        "SaaSBuilder": ("agents.agent_08_saas", "SaaSAgent"),
        "DeFiOptimizer": ("agents.agent_09_crypto_defi", "DeFiAgent"),
        "DataArbitrageur": ("agents.agent_10_data_arbitrage", "DataArbitrageAgent"),
        "ServiceProvider": ("agents.agent_11_services", "ServicesAgent"),
        "PlatformMonetizer": ("agents.agent_12_platform", "PlatformAgent"),
    }
    return mapping.get(name)


def list_agents():
    from config.settings import load_config
    config = load_config()
    print("Available agents:")
    for name in config.get("agent_names", []):
        print(f"  - {name}")


def run_agent(agent_name: str):
    entry = get_agent_class(agent_name)
    if not entry:
        logger.error(f"Unknown agent: {agent_name}")
        return

    module_path, class_name = entry
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    identity = get_identity(agent_name)
    agent = cls(identity=identity)

    logger.info(f"Running single agent: {agent_name}")
    agent.run_loop(max_cycles=20)


def run_all(deploy: bool = False):
    from master.orchestrator import Orchestrator
    config = load_config()

    logger.info("Initializing databases...")
    init_database(config.get("data_dir", "data"))

    # Start health server for deployment
    if deploy:
        start_health_server(port=int(os.getenv("PORT", "8080")))

    orch = Orchestrator()

    for name in config.get("agents_enabled", []):
        entry = get_agent_class(name)
        if not entry:
            logger.warning(f"Unknown agent in config: {name}")
            continue

        module_path, class_name = entry
        import importlib
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            identity = get_identity(name)
            agent = cls(identity=identity)
            orch.register_agent(name, agent)
        except Exception as e:
            logger.error(f"Failed to load agent {name}: {e}")

    logger.info(f"Starting orchestrator with {len(orch.agents)} agents")
    orch.run()


def main():
    parser = argparse.ArgumentParser(description="Internet Smart Agent System")
    parser.add_argument("--agent", type=str, help="Run a specific agent by name")
    parser.add_argument("--list", action="store_true", help="List all agents")
    parser.add_argument("--init-db", action="store_true", help="Initialize databases only")
    parser.add_argument("--deploy", action="store_true", help="Deployment mode (starts health server)")
    parser.add_argument("--status", action="store_true", help="Show system dashboard")
    parser.add_argument("--dashboard", action="store_true", help="Start web dashboard server")
    args = parser.parse_args()

    if args.list:
        list_agents()
    elif args.init_db:
        config = load_config()
        init_database(config.get("data_dir", "data"))
        logger.info("Databases initialized successfully")
    elif args.status:
        from master.dashboard import print_dashboard
        print_dashboard()
    elif args.dashboard:
        port = int(os.getenv("PORT", "8080"))
        logger.info(f"Starting web dashboard on port {port}...")
        from health_server import run_health_server
        run_health_server(port=port)
    elif args.agent:
        run_agent(args.agent)
    else:
        run_all(deploy=args.deploy or os.getenv("DEPLOY", "").lower() == "true")


if __name__ == "__main__":
    main()
