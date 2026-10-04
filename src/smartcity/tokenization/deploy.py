"""Deploy the property-tokenization contracts to the local chain.

  python -m smartcity.tokenization.deploy

Idempotent-by-intent: refuses to overwrite an existing deployment unless
--force, because token/appraisal state on the old contracts would be orphaned.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from smartcity.tokenization.chain import (
    CHAIN_DIR, DEPLOYMENT_PATH, ROLE_LABELS, accounts, get_w3, load_artifact,
)

EUR_FUNDING_CENTS = 5_000_000_00  # 5M EURd per investor


def deploy_one(w3, name: str, sender: str, *args) -> str:
    art = load_artifact(name)
    factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    tx = factory.constructor(*args).transact({"from": sender})
    receipt = w3.eth.wait_for_transaction_receipt(tx, timeout=30)
    print(f"  {name}: {receipt.contractAddress}")
    return receipt.contractAddress


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy tokenization contracts")
    parser.add_argument("--force", action="store_true", help="redeploy over an existing deployment")
    args = parser.parse_args()
    if DEPLOYMENT_PATH.exists() and not args.force:
        print(f"already deployed ({DEPLOYMENT_PATH}); use --force to redeploy")
        return

    w3 = get_w3()
    acc = accounts()
    print("deploying as:", {r: a[:10] + "…" for r, a in acc.items()})

    eur = deploy_one(w3, "EurStable", acc["registry"])
    deed = deploy_one(w3, "PropertyDeed", acc["registry"])
    shares = deploy_one(w3, "PropertyShares", acc["registry"], deed)
    oracle = deploy_one(w3, "AppraisalOracle", acc["oracle"])
    market = deploy_one(w3, "Marketplace", acc["registry"], eur, shares)

    # fund the demo investors with settlement EUR
    eur_c = w3.eth.contract(address=eur, abi=load_artifact("EurStable")["abi"])
    for role in ("investor_a", "investor_b", "investor_c"):
        tx = eur_c.functions.mint(acc[role], EUR_FUNDING_CENTS).transact({"from": acc["registry"]})
        w3.eth.wait_for_transaction_receipt(tx, timeout=30)
    print(f"  funded 3 investors with {EUR_FUNDING_CENTS / 100:,.0f} EURd each")

    CHAIN_DIR.mkdir(parents=True, exist_ok=True)
    DEPLOYMENT_PATH.write_text(json.dumps({
        "chain_id": w3.eth.chain_id,
        "rpc_url": "http://127.0.0.1:8545",
        "deployed_at": datetime.now(timezone.utc).isoformat(),
        "deploy_block": w3.eth.block_number,
        "contracts": {
            "EurStable": eur, "PropertyDeed": deed, "PropertyShares": shares,
            "AppraisalOracle": oracle, "Marketplace": market,
        },
        "accounts": {role: {"address": addr, "label": ROLE_LABELS[role]}
                     for role, addr in accounts().items()},
    }, indent=2))
    print(f"wrote {DEPLOYMENT_PATH}")


if __name__ == "__main__":
    main()
