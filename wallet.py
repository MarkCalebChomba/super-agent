"""HD Wallet System — BIP44 per-transaction addresses + on-chain verification.

Architecture follows Kryptoke:
- BIP39 mnemonic master seed (MASTER_SEED_PHRASE env var or generated)
- BIP44 path: m/44'/60'/0'/0/{index} (EVM — works on ETH, BSC, Polygon, etc.)
- Per-invoice addresses: each invoice gets a unique HD index
- Payment verification via public RPC (Etherscan API when key available)
"""

import os, json, time, hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
import struct, hmac

from eth_account import Account
from mnemonic import Mnemonic

Account.enable_unaudited_hdwallet_features()

WALLET_DIR = Path("data") / "wallets"
MASTER_SEED_FILE = WALLET_DIR / "master_seed.txt"
INVOICE_INDEX_FILE = WALLET_DIR / "invoice_counter.json"
INVOICES_FILE = WALLET_DIR / "invoices.json"


def _get_mnemonic() -> str:
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    env_phrase = os.getenv("MASTER_SEED_PHRASE")
    if env_phrase:
        return env_phrase
    if MASTER_SEED_FILE.exists():
        return MASTER_SEED_FILE.read_text().strip()
    mnemo = Mnemonic("english")
    mnemonic = mnemo.generate(strength=256)
    MASTER_SEED_FILE.write_text(mnemonic)
    logger.info("Master seed mnemonic generated")
    return mnemonic


def _get_next_invoice_index() -> int:
    INVOICE_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    idx = int(INVOICE_INDEX_FILE.read_text().strip()) if INVOICE_INDEX_FILE.exists() else 100
    INVOICE_INDEX_FILE.write_text(str(idx + 1))
    return idx


def _get_invoice_store() -> dict:
    if INVOICES_FILE.exists():
        return json.loads(INVOICES_FILE.read_text())
    return {"invoices": [], "next_id": 1}


def _save_invoice_store(store: dict):
    INVOICES_FILE.write_text(json.dumps(store, indent=2, default=str))


def derive_account(index: int) -> tuple[str, bytes]:
    mnemonic = _get_mnemonic()
    path = f"m/44'/60'/0'/0/{index}"
    acct = Account.from_mnemonic(mnemonic, account_path=path)
    return acct.address, acct.key


def _deterministic_index(agent_name: str) -> int:
    """Deterministic agent index from name (stable across restarts)."""
    h = hashlib.sha256(agent_name.encode()).digest()
    return int.from_bytes(h[:4], "big") % 93 + 1  # 1-93


def derive_agent_address(agent_name: str, agent_index_map: dict = None) -> str:
    idx = agent_index_map.get(agent_name) if agent_index_map else None
    if idx is None:
        idx = _deterministic_index(agent_name)
    addr, _ = derive_account(idx)
    return addr


# ── Invoice management ────────────────────────────────────────────

def create_invoice(agent_name: str, client_name: str, amount_usd: float,
                   description: str = "", chain: str = "BSC", asset: str = "USDT") -> dict:
    idx = _get_next_invoice_index()
    address, priv_key = derive_account(idx)
    store = _get_invoice_store()
    invoice = {
        "id": store["next_id"],
        "hd_index": idx,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agent": agent_name, "client": client_name,
        "amount_usd": amount_usd, "description": description,
        "chain": chain, "asset": asset,
        "address": address,
        "private_key": priv_key.hex(),
        "status": "pending",
        "paid_amount": "0", "paid_tx_hash": None,
        "paid_at": None, "confirmed": False,
    }
    store["invoices"].append(invoice)
    store["next_id"] += 1
    _save_invoice_store(store)
    logger.info(f"Invoice #{invoice['id']}: ${amount_usd} → {address}")
    return invoice


def get_invoice(invoice_id: int) -> Optional[dict]:
    store = _get_invoice_store()
    for inv in store["invoices"]:
        if inv["id"] == invoice_id:
            return inv
    return None


def get_pending_invoices(agent: str = None) -> list[dict]:
    store = _get_invoice_store()
    invoices = [inv for inv in store["invoices"] if inv["status"] == "pending"]
    if agent:
        invoices = [inv for inv in invoices if inv["agent"] == agent]
    return invoices


def mark_invoice_paid(invoice_id: int, tx_hash: str = None, amount: str = None):
    store = _get_invoice_store()
    for inv in store["invoices"]:
        if inv["id"] == invoice_id:
            inv["status"] = "paid"
            inv["paid_tx_hash"] = tx_hash
            inv["paid_amount"] = amount or inv["paid_amount"]
            inv["paid_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_invoice_store(store)


def confirm_invoice(invoice_id: int):
    store = _get_invoice_store()
    for inv in store["invoices"]:
        if inv["id"] == invoice_id:
            inv["confirmed"] = True
            break
    _save_invoice_store(store)


# ── Payment verification: Etherscan V2 + RPC fallback ─────────────

CHAIN_IDS = {"ETH": 1, "Ethereum": 1, "BSC": 56, "BNB": 56,
             "Polygon": 137, "MATIC": 137, "Arbitrum": 42161,
             "Optimism": 10, "Base": 8453}

TOKEN_ADDRESSES = {
    (56, "USDT"): "0x55d398326f99059fF775485246999027B3197955",
    (56, "USDC"): "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    (1, "USDT"): "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    (1, "USDC"): "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    (137, "USDT"): "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
}


def _rpc_call(rpc_url: str, method: str, params: list) -> dict:
    import requests
    try:
        resp = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "method": method, "params": params, "id": 1
        }, timeout=15)
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"RPC call failed: {e}")
        return {}


def _rpc_url(chain_id: int) -> str | None:
    env_map = {1: "ETH_RPC_URL", 56: "BSC_RPC_URL", 137: "POLYGON_RPC_URL",
               42161: "ARBITRUM_RPC_URL", 10: "OPTIMISM_RPC_URL", 8453: "BASE_RPC_URL"}
    key = env_map.get(chain_id)
    return os.getenv(key) if key else None


def check_balance(address: str, chain_id: int = 56, asset: str = "USDT") -> float:
    rpc = _rpc_url(chain_id)
    if not rpc:
        return 0.0
    token = TOKEN_ADDRESSES.get((chain_id, asset))
    if token:
        data = "0x70a08231" + address[2:].zfill(64)
        result = _rpc_call(rpc, "eth_call", [{"to": token, "data": data}, "latest"])
        if "result" in result:
            raw = int(result["result"], 16)
            return raw / (10 ** (6 if asset in ("USDT", "USDC") else 18))
    else:
        result = _rpc_call(rpc, "eth_getBalance", [address, "latest"])
        if "result" in result:
            return int(result["result"], 16) / 1e18
    return 0.0


def _etherscan_tx(chain_id: int, address: str, asset: str) -> list[dict]:
    """Fetch incoming token txs via Etherscan V2 unified API."""
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        return []
    import requests
    action = "tokentx" if asset in ("USDT", "USDC") else "txlist"
    try:
        resp = requests.get(
            f"https://api.etherscan.io/v2/api",
            params={"chainid": chain_id, "module": "account",
                    "action": action, "address": address,
                    "sort": "desc", "apikey": api_key},
            timeout=15
        )
        data = resp.json()
        if data.get("status") == "1" and isinstance(data.get("result"), list):
            return data["result"]
        return []
    except Exception as e:
        logger.warning(f"Etherscan API failed: {e}")
        return []


def verify_payment(invoice_id: int, min_balance: float = None) -> dict:
    inv = get_invoice(invoice_id)
    if not inv:
        return {"found": False, "error": "Invoice not found"}
    if inv["status"] == "paid":
        return {"found": True, "already_paid": True, "tx_hash": inv["paid_tx_hash"]}

    expected = min_balance or inv["amount_usd"]
    chain_id = CHAIN_IDS.get(inv.get("chain", "BSC"), 56)
    address = inv["address"]
    asset = inv["asset"]

    # Phase 1: Try Etherscan V2 for transaction history
    txs = _etherscan_tx(chain_id, address, asset)
    for tx in txs:
        if tx.get("to", "").lower() == address.lower():
            try:
                val = float(tx.get("value", 0)) / (10 ** int(tx.get("tokenDecimal", 18)))
                if val >= expected * 0.99:
                    mark_invoice_paid(invoice_id, tx_hash=tx.get("hash"), amount=str(val))
                    confirmations = tx.get("confirmations", "0")
                    logger.info(f"Invoice #{invoice_id} PAID via {tx.get('hash')}")
                    return {"found": True, "tx_hash": tx.get("hash"),
                            "amount": val, "confirmations": confirmations}
            except (ValueError, TypeError):
                continue

    # Phase 2: Fallback to direct RPC balance check
    balance = check_balance(address, chain_id, asset)
    if balance >= expected * 0.99:
        mark_invoice_paid(invoice_id, amount=str(balance))
        logger.info(f"Invoice #{invoice_id} PAID via RPC balance ({balance})")
        return {"found": True, "balance": balance}

    return {"found": False, "balance": balance, "note": "No payment detected"}


# ── Per-agent wallet ──────────────────────────────────────────────

class Wallet:
    def __init__(self, agent_name: str, agent_index: int = None):
        self.agent_name = agent_name
        WALLET_DIR.mkdir(parents=True, exist_ok=True)
        self.path = WALLET_DIR / f"{agent_name}.json"
        self._load()

        if agent_index is not None:
            self.agent_hd_index = agent_index
        else:
            self.agent_hd_index = _deterministic_index(agent_name)

        self.address, self.priv_key = derive_account(self.agent_hd_index)

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except Exception:
                data = {}
        else:
            data = {}
        self.credits = data.get("credits", 0.0)
        self.credit_history = data.get("credit_history", [])

    def save(self):
        data = {"credits": self.credits, "credit_history": self.credit_history}
        self.path.write_text(json.dumps(data, indent=2, default=str))

    def add_credits(self, amount: float, source: str, description: str = ""):
        self.credits += amount
        self.credit_history.append({
            "type": "credit", "amount": amount, "source": source,
            "description": description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    def spend_credits(self, amount: float, purpose: str):
        self.credits -= amount
        self.credit_history.append({
            "type": "debit", "amount": amount, "purpose": purpose,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.save()

    def create_invoice(self, client: str, amount: float, desc: str = "",
                       chain: str = "BSC", asset: str = "USDT") -> dict:
        return create_invoice(self.agent_name, client, amount, desc, chain, asset)

    def get_wallet_report(self) -> str:
        lines = ["## WALLET STATUS"]
        lines.append(f"In-app credits: ${self.credits:.2f}")
        lines.append(f"HD Wallet: {self.address} (path: m/44'/60'/0'/0/{self.agent_hd_index})")
        lines.append(f"Explorer: https://bscscan.com/address/{self.address}")
        lines.append("")
        invoices = get_pending_invoices(self.agent_name)
        if invoices:
            lines.append("Pending Invoices:")
            for inv in invoices:
                lines.append(f"  #{inv['id']}: ${inv['amount_usd']} {inv['asset']}")
                lines.append(f"    Address: {inv['address']}")
                lines.append(f"    Explorer: https://bscscan.com/address/{inv['address']}")
        lines.append("")
        lines.append("Payment: in-app credits or crypto (fresh address per invoice)")
        return "\n".join(lines)

    def get_payment_message(self, invoice: dict = None) -> str:
        if invoice:
            c = invoice.get("chain", "BSC")
            chain_id = CHAIN_IDS.get(c, 56)
            explorer = {1: "https://etherscan.io", 56: "https://bscscan.com",
                        137: "https://polygonscan.com", 42161: "https://arbiscan.io",
                        10: "https://optimistic.etherscan.io", 8453: "https://basescan.org"}.get(chain_id, "https://bscscan.com")
            return (
                f"Invoice #{invoice['id']}: ${invoice['amount_usd']} {invoice['asset']}\n"
                f"Send to: {invoice['address']}\n"
                f"Chain: {c} (chain ID: {chain_id})\n"
                f"Explorer: {explorer}/address/{invoice['address']}\n"
                f"I'll auto-confirm via Etherscan once the tx appears."
            )
        return f"Send crypto to HD wallet: {self.address} (BSC preferred)"
    
    def verify_invoice(self, invoice_id: int) -> dict:
        return verify_payment(invoice_id)


def get_wallet(agent_name: str, agent_index: int = None) -> Wallet:
    return Wallet(agent_name, agent_index)


def get_all_wallet_summary() -> dict:
    agents = {}
    total_credits = 0.0
    for f in WALLET_DIR.glob("*.json"):
        try:
            name = f.stem
            wallet = Wallet(name)
            agents[name] = {
                "credits": wallet.credits,
                "address": wallet.address,
                "hd_index": wallet.agent_hd_index,
                "tx_count": len(wallet.credit_history),
            }
            total_credits += wallet.credits
        except Exception:
            pass
    return {"agents": agents, "total_credits": total_credits,
            "agent_count": len(agents)}
