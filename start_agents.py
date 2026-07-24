"""Start all agents in a separate process (used by entrypoint.sh)."""
import sys, os, time, importlib
sys.stdout.write("[AGENT_PROC] Starting agent process...\n")
sys.stdout.flush()
os.environ["DEPLOY"] = "true"
try:
    from db.init_db import init_database
    from config.settings import load_config, get_identity
    config = load_config()
    init_database(config.get("data_dir", "data"))
    from master.orchestrator import Orchestrator
    orch = Orchestrator()
    # Load agents
    for name in config.get("agents_enabled", []):
        entry = None
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
        }.get(name)
        if not entry:
            sys.stdout.write(f"[AGENT_PROC] Unknown agent: {name}\n")
            sys.stdout.flush()
            continue
        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        agent = cls(identity=get_identity(name))
        orch.register_agent(name, agent)
        sys.stdout.write(f"[AGENT_PROC] Loaded: {name}\n")
        sys.stdout.flush()
    sys.stdout.write(f"[AGENT_PROC] {len(orch.agents)} agents loaded, starting...\n")
    sys.stdout.flush()
    orch.run()
except Exception as e:
    sys.stderr.write(f"[AGENT_PROC] CRASHED: {e}\n")
    sys.stderr.flush()
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()
