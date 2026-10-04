"""Index on-chain state back into the data platform (a mini block explorer).

  python -m smartcity.tokenization.index

Reads contract state + event logs from the chain and writes:

  data/chain/tokens.parquet  one row per tokenized property: deed, shares,
                             holder breakdown, latest on-chain appraisal,
                             implied market cap, trade stats
  data/chain/events.parquet  human-readable event feed (mints, issuances,
                             trades, appraisals) with tx hashes

The ontology build consumes these to materialize the Asset / PropertyToken /
Appraisal objects — on-chain state becomes ontology objects, same as any
other ingested source.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from smartcity.tokenization.chain import CHAIN_DIR, accounts, contract, deployment, get_w3

SHARE_DENOM = 1_000


def _label_map() -> dict[str, str]:
    dep = deployment()
    labels = {v["address"]: v["label"] for v in dep["accounts"].values()}
    labels[dep["contracts"]["PropertyShares"]] = "Share escrow"
    labels[dep["contracts"]["Marketplace"]] = "Marketplace"
    return labels


def build_index() -> tuple[pd.DataFrame, pd.DataFrame]:
    w3 = get_w3()
    acc = accounts()
    dep = deployment()
    from_block = dep["deploy_block"]
    labels = _label_map()
    name_of = lambda a: labels.get(a, a[:10] + "…")

    deed = contract(w3, "PropertyDeed")
    shares = contract(w3, "PropertyShares")
    oracle = contract(w3, "AppraisalOracle")
    market = contract(w3, "Marketplace")

    def fetch(c, event, **arg_filters):
        return getattr(c.events, event).get_logs(from_block=from_block, argument_filters=arg_filters or None)

    minted = fetch(deed, "DeedMinted")
    frax = {e["args"]["id"]: e for e in fetch(shares, "Fractionalized")}
    transfers = fetch(shares, "TransferSingle")
    appraisals = fetch(oracle, "AppraisalPosted")
    offers_created = fetch(market, "OfferCreated")
    fills = fetch(market, "OfferFilled")

    block_ts: dict[int, datetime] = {}

    def ts(block: int) -> datetime:
        if block not in block_ts:
            block_ts[block] = datetime.fromtimestamp(w3.eth.get_block(block)["timestamp"], tz=timezone.utc)
        return block_ts[block]

    # ---- tokens table ---------------------------------------------------------
    rows = []
    for e in minted:
        token_id = e["args"]["tokenId"]
        prop = deed.functions.properties(token_id).call()
        listing_id, address, surface_x10, appraisal_sha = prop
        supply = shares.functions.totalSupply(token_id).call()

        holders: dict[str, int] = {}
        for t in transfers:
            if t["args"]["id"] != token_id:
                continue
            a = t["args"]
            if a["from"] != "0x" + "0" * 40:
                holders[a["from"]] = holders.get(a["from"], 0) - a["value"]
            if a["to"] != "0x" + "0" * 40:
                holders[a["to"]] = holders.get(a["to"], 0) + a["value"]
        holders = {name_of(k): v for k, v in holders.items() if v > 0}

        app = oracle.functions.latest(token_id).call()
        doc_sha, fair_cents, fingerprint, as_of, posted_at = app
        prop_fills = [f for f in fills if f["args"]["propertyId"] == token_id]
        last_price = None
        for f in sorted(prop_fills, key=lambda f: f["blockNumber"]):
            last_price = f["args"]["paidEurCents"] / f["args"]["amount"]
        traded_shares = sum(f["args"]["amount"] for f in prop_fills)
        volume_eur = sum(f["args"]["paidEurCents"] for f in prop_fills) / 100
        open_offers = []
        for i in range(market.functions.offerCount().call()):
            o = market.functions.offers(i).call()
            if o[1] == token_id and o[4] and o[2] > 0:
                open_offers.append({"seller": name_of(o[0]), "amount": o[2], "price_cents": o[3]})

        rows.append({
            "token_id": hex(token_id),
            "listing_id": listing_id,
            "chain_address_label": address,
            "surface_m2": surface_x10 / 10,
            "appraisal_sha256": appraisal_sha,
            "minted_at": ts(e["blockNumber"]),
            "mint_tx": e["transactionHash"].to_0x_hex(),
            "shares_supply": supply,
            "holders_json": pd.io.json.ujson_dumps(holders),
            "n_holders": len(holders),
            "free_float_pct": round(100 * (1 - holders.get("City Land Registry", 0) / supply), 1) if supply else 0.0,
            "onchain_fair_eur": fair_cents / 100,
            "appraisal_as_of": int(as_of),
            "n_appraisals": oracle.functions.count(token_id).call(),
            "last_share_price_eur": None if last_price is None else last_price / 100,
            "market_cap_eur": None if last_price is None else last_price / 100 * supply,
            "traded_shares": traded_shares,
            "volume_eur": volume_eur,
            "open_offers_json": pd.io.json.ujson_dumps(open_offers),
        })
    tokens = pd.DataFrame(rows)

    # ---- event feed -------------------------------------------------------------
    deed_by_id = {r["token_id"]: r["chain_address_label"] for r in rows}
    feed = []

    def add(e, kind: str, detail: str, actor: str):
        feed.append({
            "block": e["blockNumber"], "at": ts(e["blockNumber"]), "kind": kind,
            "property": deed_by_id.get(hex(e["args"].get("tokenId", e["args"].get("id", e["args"].get("propertyId", 0)))), ""),
            "detail": detail, "actor": actor, "tx": e["transactionHash"].to_0x_hex(),
        })

    for e in minted:
        add(e, "Deed minted", f"title deed issued · appraisal sha {e['args']['appraisalSha'][:12]}…",
            "City Land Registry")
    for e in frax.values():
        add(e, "Fractionalized", f"deed escrowed → {e['args']['shares']} shares issued", name_of(e["args"]["by"]))
    for e in appraisals:
        add(e, "Appraisal anchored",
            f"fair value {e['args']['fairValueEurCents'] / 100:,.0f} € (as of {e['args']['asOfMonth']})",
            "CityPulse Valuation Oracle")
    for e in offers_created:
        add(e, "Offer listed",
            f"{e['args']['amount']} shares @ {e['args']['pricePerShareEurCents'] / 100:,.2f} €",
            name_of(e["args"]["seller"]))
    for e in fills:
        add(e, "Shares traded",
            f"{e['args']['amount']} shares for {e['args']['paidEurCents'] / 100:,.2f} €",
            name_of(e["args"]["buyer"]))
    events = pd.DataFrame(feed).sort_values(["block", "kind"], ascending=[False, True]).reset_index(drop=True)

    CHAIN_DIR.mkdir(parents=True, exist_ok=True)
    tokens.to_parquet(CHAIN_DIR / "tokens.parquet", index=False)
    events.to_parquet(CHAIN_DIR / "events.parquet", index=False)
    return tokens, events


def main() -> None:
    tokens, events = build_index()
    print(f"data/chain/tokens.parquet: {len(tokens)} tokenized properties")
    print(f"data/chain/events.parquet: {len(events)} events")
    if not tokens.empty:
        t = tokens.iloc[0]
        print(f"sample: {t['chain_address_label']} · {t['n_holders']} holders · "
              f"free float {t['free_float_pct']}% · on-chain fair {t['onchain_fair_eur']:,.0f} €")


if __name__ == "__main__":
    main()
