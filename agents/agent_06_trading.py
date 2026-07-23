import os
import time
from .base_agent import BaseAgent
from tools.wallet_tools import WalletTools

class TradingAgent(BaseAgent):
    """Crypto & stock trading, DeFi yield farming, arbitrage."""

    def __init__(self, identity: dict = None):
        super().__init__("CryptoTrader", identity)
        self.wallet = WalletTools()
        self.idx = 0

    def get_income_methods(self) -> str:
        return ("Crypto spot trading, DeFi yield farming (Aave, Compound), "
                "Liquidity provision (Uniswap), Arbitrage, "
                "Staking, Memecoin trading, NFT flipping")

    def build(self) -> dict:
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"yield_report_{ts}.md"
        filepath = os.path.join(self.build_dir, filename)
        balance = self.wallet.get_balance("ethereum", "0xAgentWallet")
        report = f"""# Yield Farming Report - {ts}

## Portfolio
- ETH Balance: {balance:.4f} ETH
- USDC Balance: 0.00

## Opportunities
| Protocol | Asset | APY | Risk |
|----------|-------|-----|------|
| Aave     | USDC  | 8%  | Low  |
| Compound | ETH   | 3.5%| Low  |
| Uniswap  | ETH/USDC | 12% | Med |
| Lido     | stETH | 4.2%| Low  |

## Recommendation
Deposit USDC into Aave for 8% APY (lowest risk).
"""
        with open(filepath, "w") as f:
            f.write(report)
        return {"file": filepath, "summary": f"Yield report generated", "revenue": 0.0, "method": "defi"}
