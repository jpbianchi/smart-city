"""Seed and exercise the share marketplace.

  python -m smartcity.tokenization.market --seed

Seeding, per tokenized property: the registry offers 40% of the shares at the
oracle's fair value per share, then the three demo investors fill parts of the
book (deterministic pseudo-random sizes, keyed on the property id, so re-runs
are reproducible). One property also gets a secondary resale at +4% to show
price discovery on top of the primary issuance.
"""
from __future__ import annotations

import argparse

from smartcity.tokenization.chain import accounts, contract, get_w3, send

PRIMARY_FRACTION = 0.40     # shares offered at issuance
RESALE_PREMIUM = 1.04


def _buy(w3, market, eur, offer_id: int, amount: int, price: int, buyer: str) -> None:
    send(eur.functions.approve(market.address, amount * price), buyer)
    send(market.functions.buy(offer_id, amount), buyer)


def seed() -> None:
    w3 = get_w3()
    acc = accounts()
    deed = contract(w3, "PropertyDeed")
    shares = contract(w3, "PropertyShares")
    oracle = contract(w3, "AppraisalOracle")
    market = contract(w3, "Marketplace")
    eur = contract(w3, "EurStable")

    for role in ("registry", "investor_a", "investor_b", "investor_c"):
        if not shares.functions.isApprovedForAll(acc[role], market.address).call():
            send(shares.functions.setApprovalForAll(market.address, True), acc[role])

    investors = [acc["investor_a"], acc["investor_b"], acc["investor_c"]]
    n_tokens = deed.functions.totalSupply().call()
    existing_offers = market.functions.offerCount().call()
    if existing_offers:
        print(f"market already has {existing_offers} offers; seeding only new properties")

    offered = set()
    for i in range(existing_offers):
        o = market.functions.offers(i).call()
        offered.add(o[1])

    seeded = 0
    for i in range(n_tokens):
        token_id = deed.functions.allTokens(i).call()
        if token_id in offered:
            continue
        supply = shares.functions.totalSupply(token_id).call()
        if supply == 0:
            continue
        appraisal = oracle.functions.latest(token_id).call()
        fair_cents = appraisal[1]
        price_per_share = max(1, fair_cents // supply)

        amount = int(supply * PRIMARY_FRACTION)
        offer_id = send(
            market.functions.createOffer(token_id, amount, price_per_share), acc["registry"]
        )["logs"] and market.functions.offerCount().call() - 1

        # deterministic fills: split ~60% of the offer across the investors
        h = token_id
        remaining = amount
        for k, buyer in enumerate(investors):
            take = min(remaining, 50 + (h >> (8 * k)) % 120)
            if take <= 0:
                continue
            _buy(w3, market, eur, offer_id, take, price_per_share, buyer)
            remaining -= take

        # one secondary resale on every 4th property: investor A relists at +4%
        if i % 4 == 0:
            bal = shares.functions.balanceOf(token_id, investors[0]).call()
            if bal > 20:
                resale_price = int(price_per_share * RESALE_PREMIUM)
                rid = send(
                    market.functions.createOffer(token_id, bal // 2, resale_price), investors[0]
                ) and market.functions.offerCount().call() - 1
                _buy(w3, market, eur, rid, bal // 4, resale_price, investors[1])
        seeded += 1
    print(f"seeded market for {seeded} properties "
          f"({market.functions.offerCount().call()} offers total)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the property share marketplace")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    if args.seed:
        seed()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
