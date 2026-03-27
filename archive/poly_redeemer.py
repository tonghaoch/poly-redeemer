#!/usr/bin/env python3
"""poly-redeemer — Automatic Polymarket CTF position redeemer.

Supports both proxy wallet and EOA modes.
- Proxy wallet: EOA → ProxyWalletFactory.proxy() → ProxyWallet → CTF contract
- EOA: EOA → CTF contract directly
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

# ── Constants ──────────────────────────────────────────────────────────────────

CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
USDC_ADDRESS = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
NEG_RISK_ADAPTER = Web3.to_checksum_address("0xC5d563A36AE78145C45a50134d48A1215220f80a")

# Polymarket ProxyWalletFactory — EOA calls this to forward calls through the proxy wallet.
# https://github.com/Polymarket/proxy-factories/tree/main/packages/proxy-factory
PROXY_WALLET_FACTORY = Web3.to_checksum_address("0xaB45c5A4B0c941a2F231C04C3f49182e1A254052")

CHAIN_ID = 137
DATA_API = "https://data-api.polymarket.com"
PARENT_COLLECTION_ID = bytes(32)  # 0x00...00
CALL_TYPE_CALL = 1  # ProxyWalletLib.CallType.CALL
MAX_UINT256 = 2**256 - 1

TZ_UTC8 = timezone(timedelta(hours=8))

# ── ABIs ──────────────────────────────────────────────────────────────────────

CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    },
    {
        "name": "payoutDenominator",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getOutcomeSlotCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

NEG_RISK_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "amounts", "type": "uint256[]"},
        ],
        "outputs": [],
    },
]

# ProxyWalletFactory.proxy(ProxyCall[]) — forwards calls through the user's proxy wallet.
# ProxyCall = (uint8 typeCode, address to, uint256 value, bytes data)
FACTORY_ABI = [
    {
        "name": "proxy",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "typeCode", "type": "uint8"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"},
                ],
            }
        ],
        "outputs": [{"name": "returnValues", "type": "bytes[]"}],
    },
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def ts() -> str:
    """Timestamp prefix in UTC+8."""
    return datetime.now(TZ_UTC8).strftime("%H:%M:%S")


def short_hex(hex_str: str, n: int = 10) -> str:
    """Shorten a hex string for display: '0x5f01b35cab...'"""
    if len(hex_str) > n + 2:
        return hex_str[: n + 2] + "..."
    return hex_str


def to_condition_bytes(condition_id: str) -> bytes:
    """Convert '0x...' hex string to 32-byte bytes for contract calls."""
    return bytes.fromhex(condition_id.removeprefix("0x"))


# ── RedeemablePosition ─────────────────────────────────────────────────────────

class RedeemablePosition:
    """A position confirmed redeemable on-chain."""

    __slots__ = ("condition_id", "size", "neg_risk", "title", "outcome",
                 "asset_id", "outcome_count")

    def __init__(self, condition_id: str, size: float, neg_risk: bool,
                 title: str, outcome: str, asset_id: str, outcome_count: int):
        self.condition_id = condition_id
        self.size = size
        self.neg_risk = neg_risk
        self.title = title
        self.outcome = outcome
        self.asset_id = asset_id
        self.outcome_count = outcome_count

    def label(self) -> str:
        return f"{self.title} {self.outcome}"

    def __repr__(self) -> str:
        return (f"  {self.label()} — {self.size:.6f} shares, "
                f"condition={short_hex(self.condition_id)}, "
                f"neg_risk={str(self.neg_risk).lower()}")


# ── Scanner ────────────────────────────────────────────────────────────────────

class Scanner:
    """Scan for redeemable positions via Polymarket Data API + on-chain verification."""

    def __init__(self, user_address: str, w3: Web3, ctf_contract):
        self.user_address = user_address
        self.w3 = w3
        self.ctf = ctf_contract

    def scan(self) -> list[RedeemablePosition]:
        """Query Data API for redeemable positions, verify each on-chain."""
        resp = requests.get(
            f"{DATA_API}/positions",
            params={"user": self.user_address, "redeemable": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        if not raw:
            return []

        positions = []
        for item in raw:
            condition_id = item.get("conditionId", "")
            if not condition_id:
                continue

            cid_bytes = to_condition_bytes(condition_id)

            # On-chain verification: payoutDenominator > 0 means market is resolved
            try:
                payout_denom = self.ctf.functions.payoutDenominator(cid_bytes).call()
            except Exception as e:
                print(f"[{ts()}] Warning: payoutDenominator failed for "
                      f"{short_hex(condition_id)}: {e}")
                continue
            if payout_denom == 0:
                continue

            # Query outcome count for dynamic index_sets / amounts construction
            try:
                outcome_count = self.ctf.functions.getOutcomeSlotCount(cid_bytes).call()
            except Exception:
                outcome_count = 2  # fallback to binary

            positions.append(RedeemablePosition(
                condition_id=condition_id,
                size=float(item.get("size", 0)),
                neg_risk=bool(item.get("negRisk", False)),
                title=item.get("title", "Unknown"),
                outcome=item.get("outcome", "?"),
                asset_id=item.get("asset", ""),
                outcome_count=outcome_count,
            ))

        return positions


# ── Redeemer ───────────────────────────────────────────────────────────────────

class Redeemer:
    """Execute on-chain CTF redeemPositions transactions."""

    def __init__(self, w3: Web3, account, ctf_contract, neg_risk_contract,
                 use_proxy: bool = False):
        self.w3 = w3
        self.account = account
        self.ctf = ctf_contract
        self.neg_risk = neg_risk_contract
        self.use_proxy = use_proxy
        if use_proxy:
            self.factory = w3.eth.contract(
                address=PROXY_WALLET_FACTORY, abi=FACTORY_ABI)

    # ── Transaction helpers ────────────────────────────────────────────────

    def _send_tx(self, tx_func, gas: int) -> tuple[str, int]:
        """Sign, send, and wait for a transaction. Returns (tx_hash_hex, block_number).
        Raises on failure."""
        priority_fee = self.w3.to_wei(30, "gwei")
        base_fee = self.w3.eth.gas_price
        max_fee = max(base_fee * 2, priority_fee)

        nonce = self.w3.eth.get_transaction_count(self.account.address)
        tx = tx_func.build_transaction({
            "chainId": CHAIN_ID,
            "from": self.account.address,
            "nonce": nonce,
            "gas": gas,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] != 1:
            raise RuntimeError(
                f"tx reverted (tx=0x{tx_hash.hex()}, block={receipt['blockNumber']})")

        return tx_hash.hex(), receipt["blockNumber"]

    # ── Calldata builders ──────────────────────────────────────────────────

    def _build_redeem_func(self, pos: RedeemablePosition):
        """Build the contract function call for redeeming a position.
        Returns (target_address, encoded_calldata) for proxy mode,
        or a ContractFunction for direct mode."""
        cid_bytes = to_condition_bytes(pos.condition_id)
        n = pos.outcome_count

        if pos.neg_risk:
            amounts = [MAX_UINT256] * n
            return self.neg_risk.functions.redeemPositions(cid_bytes, amounts)
        else:
            index_sets = [1 << i for i in range(n)]
            return self.ctf.functions.redeemPositions(
                USDC_ADDRESS, PARENT_COLLECTION_ID, cid_bytes, index_sets)

    def _build_redeem_calldata(self, pos: RedeemablePosition) -> tuple[str, bytes]:
        """Build encoded calldata for proxy mode. Returns (target_address, calldata)."""
        cid_bytes = to_condition_bytes(pos.condition_id)
        n = pos.outcome_count

        if pos.neg_risk:
            amounts = [MAX_UINT256] * n
            data = self.neg_risk.encode_abi(
                "redeemPositions", args=[cid_bytes, amounts])
            return NEG_RISK_ADAPTER, data
        else:
            index_sets = [1 << i for i in range(n)]
            data = self.ctf.encode_abi(
                "redeemPositions",
                args=[USDC_ADDRESS, PARENT_COLLECTION_ID, cid_bytes, index_sets])
            return CTF_ADDRESS, data

    # ── Redeem paths ───────────────────────────────────────────────────────

    def _redeem_via_factory(self, pos: RedeemablePosition) -> tuple[str, int]:
        """Redeem through ProxyWalletFactory.proxy() → ProxyWallet → CTF."""
        target, calldata = self._build_redeem_calldata(pos)
        proxy_call = (CALL_TYPE_CALL, target, 0, calldata)
        tx_func = self.factory.functions.proxy([proxy_call])
        return self._send_tx(tx_func, gas=500_000)

    def _redeem_direct(self, pos: RedeemablePosition) -> tuple[str, int]:
        """Redeem directly from EOA → CTF."""
        tx_func = self._build_redeem_func(pos)
        return self._send_tx(tx_func, gas=300_000)

    # ── Public interface ───────────────────────────────────────────────────

    def redeem(self, pos: RedeemablePosition) -> tuple[str | None, int | None]:
        """Redeem a single position. Returns (tx_hash, block_number) or (None, None)."""
        try:
            if self.use_proxy:
                return self._redeem_via_factory(pos)
            else:
                return self._redeem_direct(pos)
        except Exception as e:
            print(f"[{ts()}] Redeem failed for {pos.label()}: {e}")
            return None, None

    def redeem_all(self, positions: list[RedeemablePosition]) -> int:
        """Redeem all positions sequentially. Returns count of successful redeems."""
        success = 0
        for pos in positions:
            print(f"[{ts()}] Redeeming {pos.label()}... ", end="", flush=True)
            tx_hash, block = self.redeem(pos)
            if tx_hash:
                print(f"tx=0x{tx_hash[:8]}... \u2713 (block {block})")
                success += 1
            else:
                print("\u2717 failed")
        return success


# ── CLI ────────────────────────────────────────────────────────────────────────

def load_config() -> tuple[Web3, Account, str, bool]:
    """Load .env, validate config, initialize web3 + account.

    Returns (w3, account, scan_address, use_proxy).
    """
    load_dotenv()

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        print("Error: POLYMARKET_PRIVATE_KEY not set in .env")
        sys.exit(1)

    rpc_url = os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"Error: Cannot connect to RPC at {rpc_url}")
        sys.exit(1)

    account = Account.from_key(private_key)

    # Validate and checksum proxy wallet address
    raw_proxy = os.environ.get("PROXY_WALLET_ADDRESS", "").strip()
    if raw_proxy:
        try:
            proxy_address = Web3.to_checksum_address(raw_proxy)
        except ValueError:
            print(f"Error: PROXY_WALLET_ADDRESS is not a valid address: {raw_proxy}")
            sys.exit(1)
    else:
        proxy_address = None

    scan_address = proxy_address if proxy_address else account.address
    use_proxy = proxy_address is not None
    return w3, account, scan_address, use_proxy


def main():
    parser = argparse.ArgumentParser(description="Polymarket CTF auto-redeemer")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous mode: scan and redeem in a loop")
    parser.add_argument("--interval", type=int, default=20,
                        help="Scan interval in seconds for watch mode (default: 20)")
    args = parser.parse_args()

    w3, account, scan_address, use_proxy = load_config()

    mode = "proxy" if use_proxy else "EOA"
    print(f"[{ts()}] Mode: {mode}")
    print(f"[{ts()}] EOA: {account.address}")
    if use_proxy:
        print(f"[{ts()}] Proxy wallet: {scan_address}")
        print(f"[{ts()}] Factory: {PROXY_WALLET_FACTORY}")
    print(f"[{ts()}] Scan address: {scan_address}")
    print(f"[{ts()}] RPC connected, chain_id={w3.eth.chain_id}")

    ctf = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
    neg_risk = w3.eth.contract(address=NEG_RISK_ADAPTER, abi=NEG_RISK_ABI)

    scanner = Scanner(scan_address, w3, ctf)
    redeemer = Redeemer(w3, account, ctf, neg_risk, use_proxy)

    if args.watch:
        print(f"[{ts()}] Watch mode (interval={args.interval}s). Ctrl+C to stop.")
        try:
            while True:
                _run_once(scanner, redeemer, watch=True)
                print(f"[{ts()}] [Watch] Next scan in {args.interval}s. (Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n[{ts()}] Stopped.")
    else:
        _run_once(scanner, redeemer, watch=False)


def _run_once(scanner: Scanner, redeemer: Redeemer, watch: bool):
    """Single scan + redeem cycle."""
    prefix = "[Watch] " if watch else ""
    print(f"[{ts()}] {prefix}Querying redeemable positions...")

    try:
        positions = scanner.scan()
    except Exception as e:
        print(f"[{ts()}] {prefix}Scan error: {e}")
        return

    if not positions:
        print(f"[{ts()}] {prefix}Scanning... found 0 redeemable.")
        return

    print(f"[{ts()}] {prefix}Found {len(positions)} redeemable position(s):")
    for pos in positions:
        print(repr(pos))

    success = redeemer.redeem_all(positions)
    print(f"[{ts()}] Done. Redeemed {success}/{len(positions)} positions.")


if __name__ == "__main__":
    main()
