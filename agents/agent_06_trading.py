from .base_agent import BaseAgent
from tools.wallet_tools import WalletTools

class TradingAgent(BaseAgent):
    """Crypto & stock trading, DeFi yield farming, arbitrage."""

    def __init__(self, identity: dict = None):
        super().__init__("CryptoTrader", identity)
        self.wallet = WalletTools()
        self.trades = []

    def get_income_methods(self) -> str:
        return ("Crypto spot trading, DeFi yield farming (Aave, Compound), "
                "Liquidity provision (Uniswap), Arbitrage, "
                "Staking, Memecoin trading, NFT flipping")

    def think(self, context: dict) -> str:
        return ("!remember self checking DeFi yield opportunities category=plan importance=3\n"
                "ACTION: Check ETH balance and evaluate Aave lending rates\n"
                "!remember self ETH balance checked, considering Aave USDC pool at 8% APY category=action")

    def act(self, decision: str) -> dict:
        balance = self.wallet.get_balance("ethereum", "0xAgentWallet")
        return {"success": True, "action": "balance_check", "method": "defi",
                "details": f"ETH balance: {balance}", "revenue": 0.0,
                "summary": f"Wallet balance checked: {balance} ETH"}
