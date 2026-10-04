"""Tokenize properties from the valued inventory onto the chain.

  python -m smartcity.tokenization.tokenize --grades A B --limit 24
  python -m smartcity.tokenization.tokenize --listing "tx:2025-...:75116..."

Per property, three on-chain steps mirroring a real issuance:
  1. the land registry mints the title deed NFT (tokenId = keccak(listing id),
     tokenURI = sha256 of the appraisal document that justified the issuance),
  2. the registry escrows the deed in PropertyShares and receives 1,000 shares,
  3. the valuation oracle posts the appraisal commitment (doc sha256, fair
     value, model training-data fingerprint, as-of month).

Idempotent: a listing whose deed already exists is skipped.
"""
from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from smartcity.config import DATA_DIR
from smartcity.tokenization.chain import accounts, contract, get_w3, send

LISTINGS_PATH = DATA_DIR / "valuation" / "listings.parquet"


def as_of_month(label: str) -> int:
    return int(datetime.strptime(label, "%b %Y").strftime("%Y%m"))


def pick(df: pd.DataFrame, grades: list[str], limit: int) -> pd.DataFrame:
    sel = df[df["opportunity_grade"].isin(grades)]
    return sel.sort_values("opportunity_score", ascending=False).head(limit)


def model_fingerprint(model_name: str) -> bytes:
    import json
    manifest = DATA_DIR / "valuation" / model_name / "manifest.json"
    if manifest.exists():
        return bytes.fromhex(json.loads(manifest.read_text())["data_fingerprint"])
    return bytes(32)


def tokenize(rows: pd.DataFrame) -> int:
    w3 = get_w3()
    acc = accounts()
    deed = contract(w3, "PropertyDeed")
    shares = contract(w3, "PropertyShares")
    oracle = contract(w3, "AppraisalOracle")

    # one-time operator approval so the escrow can pull the registry's deeds
    if not deed.functions.isApprovedForAll(acc["registry"], shares.address).call():
        send(deed.functions.setApprovalForAll(shares.address, True), acc["registry"])

    minted = 0
    for _, r in rows.iterrows():
        token_id = deed.functions.tokenIdFor(r["tx_id"]).call()
        if deed.functions.ownerOf(token_id).call() != "0x" + "0" * 40:
            print(f"  skip (already on-chain): {r['address']}")
            continue
        send(
            deed.functions.mint(
                r["tx_id"], f"{r['address']}, {r['postal_code']} Paris",
                int(round(r["surface_m2"] * 10)), r["appraisal_sha256"],
            ),
            acc["registry"],
        )
        send(shares.functions.fractionalize(token_id), acc["registry"])
        send(
            oracle.functions.post(
                token_id,
                bytes.fromhex(r["appraisal_sha256"]),
                int(round(r["fair_value_eur"] * 100)),
                model_fingerprint(r["model_name"]),
                as_of_month(r["valuation_as_of"]),
            ),
            acc["oracle"],
        )
        minted += 1
        print(f"  tokenized: {r['address']} ({r['arrondissement']}) "
              f"fair {r['fair_value_eur']:,.0f} € → deed {hex(token_id)[:14]}…, 1000 shares")
    return minted


def main() -> None:
    parser = argparse.ArgumentParser(description="Tokenize valued properties on-chain")
    parser.add_argument("--grades", nargs="*", default=["A", "B"])
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--listing", help="tokenize one specific listing id")
    args = parser.parse_args()

    df = pd.read_parquet(LISTINGS_PATH)
    rows = df[df["tx_id"] == args.listing] if args.listing else pick(df, args.grades, args.limit)
    if rows.empty:
        print("nothing to tokenize")
        return
    n = tokenize(rows)
    print(f"tokenized {n} properties")


if __name__ == "__main__":
    main()
