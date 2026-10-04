"""Connection layer for the local property chain (Anvil, chain id 31337).

Run the node from the repo root:
  ~/.foundry/bin/anvil --state data/chain/anvil-state.json --chain-id 31337

Accounts use Anvil's standard unlocked dev accounts — fine for a demo chain,
and exactly the part a production deployment swaps for an HSM/KMS signer.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from web3 import Web3

from smartcity.config import DATA_DIR, PROJECT_ROOT

RPC_URL = "http://127.0.0.1:8545"
CHAIN_DIR = DATA_DIR / "chain"
DEPLOYMENT_PATH = CHAIN_DIR / "deployment.json"
ARTIFACTS = PROJECT_ROOT / "chain" / "out"

# Anvil's first dev accounts, by role (addresses are deterministic).
ROLES = ["registry", "oracle", "investor_a", "investor_b", "investor_c"]
ROLE_LABELS = {
    "registry": "City Land Registry",
    "oracle": "CityPulse Valuation Oracle",
    "investor_a": "Investor A",
    "investor_b": "Investor B",
    "investor_c": "Investor C",
}


def get_w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise ConnectionError(
            f"No chain at {RPC_URL} — start it with:\n"
            "  ~/.foundry/bin/anvil --state data/chain/anvil-state.json --chain-id 31337"
        )
    return w3


@lru_cache(maxsize=1)
def accounts() -> dict[str, str]:
    """role -> unlocked address, taken from the running node."""
    addrs = get_w3().eth.accounts
    return {role: addrs[i] for i, role in enumerate(ROLES)}


def load_artifact(name: str) -> dict:
    path = ARTIFACTS / f"{name}.sol" / f"{name}.json"
    art = json.loads(path.read_text())
    return {"abi": art["abi"], "bytecode": art["bytecode"]["object"]}


def deployment() -> dict:
    if not DEPLOYMENT_PATH.exists():
        raise FileNotFoundError("No deployment.json — run: python -m smartcity.tokenization.deploy")
    return json.loads(DEPLOYMENT_PATH.read_text())


def contract(w3: Web3, name: str):
    dep = deployment()
    return w3.eth.contract(address=dep["contracts"][name], abi=load_artifact(name)["abi"])


def send(fn, sender: str) -> dict:
    """Transact from an unlocked account and wait for the receipt."""
    tx_hash = fn.transact({"from": sender})
    receipt = fn.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
    if receipt["status"] != 1:
        raise RuntimeError(f"tx reverted: {tx_hash.hex()}")
    return receipt
