"""Tokens page — the on-chain property registry: tokenized assets, share
ownership, anchored appraisals and the live transaction feed from the local
EVM chain (Anvil), indexed by smartcity.tokenization.index."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import reflex as rx

from citypulse.data import PROJECT_ROOT
from citypulse.ui import (
    BLUE, BORDER, CARD_BG, HAIRLINE, INK, INK_2, MUTED, card, kpi_tile, navbar, page, panel,
)

CHAIN_DIR = PROJECT_ROOT / "data" / "chain"


def _eur(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v / 1e6:.2f}M €" if v >= 1e6 else f"{v:,.0f} €".replace(",", " ")


class TokenState(rx.State):
    chain_ok: bool = False
    chain_note: str = ""
    k_tokens: str = "–"
    k_mcap: str = "–"
    k_volume: str = "–"
    k_anchored: str = "–"
    contract_rows: list[list] = []
    token_rows: list[dict[str, str]] = []
    event_rows: list[dict[str, str]] = []
    holder_open_id: str = ""
    holder_rows: list[list] = []
    holder_title: str = ""

    def load_page(self):
        tokens_path = CHAIN_DIR / "tokens.parquet"
        if not tokens_path.exists():
            self.chain_ok = False
            self.chain_note = (
                "No on-chain data yet. Start the chain and run the tokenization engine — "
                "see the Tokenization section of the README."
            )
            return
        self.chain_ok = True
        tok = pd.read_parquet(tokens_path)
        ev = pd.read_parquet(CHAIN_DIR / "events.parquet")
        dep = json.loads((CHAIN_DIR / "deployment.json").read_text())

        self.k_tokens = f"{len(tok)}"
        self.k_mcap = _eur(tok["market_cap_eur"].fillna(tok["onchain_fair_eur"]).sum())
        self.k_volume = _eur(tok["volume_eur"].sum())
        self.k_anchored = f"{int(tok['n_appraisals'].sum())}"
        self.chain_note = (
            f"Local EVM chain · id {dep['chain_id']} · {len(dep['contracts'])} contracts · "
            f"indexed from block {dep['deploy_block']}"
        )
        self.contract_rows = [[name, addr] for name, addr in dep["contracts"].items()]

        tok = tok.sort_values("market_cap_eur", ascending=False, na_position="last")
        self.token_rows = [
            {
                "id": r["token_id"],
                "deed": r["token_id"][:12] + "…",
                "address": r["chain_address_label"].removesuffix(" Paris"),
                "surface": f"{r['surface_m2']:.0f} m²",
                "shares": f"{int(r['shares_supply']):,}",
                "holders": f"{int(r['n_holders'])}",
                "float": f"{r['free_float_pct']:.0f}%",
                "share_px": "–" if pd.isna(r["last_share_price_eur"]) else f"{r['last_share_price_eur']:,.2f} €",
                "fair": _eur(r["onchain_fair_eur"]),
                "mcap": _eur(r["market_cap_eur"]),
                "volume": _eur(r["volume_eur"]),
                "sha": r["appraisal_sha256"][:10] + "…",
            }
            for _, r in tok.iterrows()
        ]
        self.event_rows = [
            {
                "at": r["at"].strftime("%d %b %H:%M"),
                "kind": r["kind"],
                "property": (r["property"] or "").removesuffix(" Paris"),
                "detail": r["detail"],
                "actor": r["actor"],
                "tx": r["tx"][:14] + "…",
            }
            for _, r in ev.head(60).iterrows()
        ]

    def show_holders(self, token_id: str):
        tok = pd.read_parquet(CHAIN_DIR / "tokens.parquet")
        hit = tok[tok["token_id"] == token_id]
        if hit.empty:
            return
        r = hit.iloc[0]
        if self.holder_open_id == token_id:  # toggle off
            self.holder_open_id = ""
            self.holder_rows = []
            return
        holdings = pd.read_parquet(CHAIN_DIR / "holdings.parquet")
        parties = pd.read_parquet(CHAIN_DIR / "parties.parquet").set_index("party_id")["label"]
        h = holdings[holdings["token_id"] == token_id].sort_values("shares", ascending=False)
        self.holder_open_id = token_id
        self.holder_title = f"Cap table — {r['chain_address_label']}"
        self.holder_rows = [
            [parties.get(x["party_id"], x["party_id"]), f"{int(x['shares']):,} shares", f"{x['pct']:.1f}%"]
            for _, x in h.iterrows()
        ]


def token_row(row) -> rx.Component:
    num = {"text_align": "right", "white_space": "nowrap"}
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                rx.text(row["address"], size="2", weight="medium", color=INK),
                rx.text("deed ", rx.code(row["deed"]), " · appraisal ", rx.code(row["sha"]),
                        size="1", color=MUTED),
                spacing="0",
            )
        ),
        rx.table.cell(rx.text(row["surface"], size="2"), style=num),
        rx.table.cell(rx.text(row["shares"], size="2"), style=num),
        rx.table.cell(rx.text(row["holders"], size="2"), style=num),
        rx.table.cell(rx.text(row["float"], size="2"), style=num),
        rx.table.cell(rx.text(row["share_px"], size="2"), style=num),
        rx.table.cell(rx.text(row["fair"], size="2", color=INK_2), style=num),
        rx.table.cell(rx.text(row["mcap"], size="2", weight="medium"), style=num),
        rx.table.cell(rx.text(row["volume"], size="2", color=INK_2), style=num),
        on_click=TokenState.show_holders(row["id"]),
        cursor="pointer",
        _hover={"background_color": "rgba(42,120,214,0.06)"},
    )


def event_row(row) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(row["at"], size="1", color=MUTED, white_space="nowrap")),
        rx.table.cell(rx.badge(row["kind"], variant="soft", size="1")),
        rx.table.cell(rx.text(row["property"], size="1", color=INK)),
        rx.table.cell(rx.text(row["detail"], size="1", color=INK_2)),
        rx.table.cell(rx.text(row["actor"], size="1", color=INK_2, white_space="nowrap")),
        rx.table.cell(rx.code(row["tx"], size="1")),
    )


def pipeline_card() -> rx.Component:
    steps = [
        ("file-check", "1 · Appraise", "The valuation engine prices the property from the city ontology and emits a content-hashed appraisal document (sha256)."),
        ("scroll-text", "2 · Mint deed", "The land registry mints an ERC-721 title deed; tokenId = keccak of the official parcel id, tokenURI = the appraisal hash."),
        ("layers", "3 · Fractionalize", "The deed is escrowed in the shares contract, which issues 1,000 fungible shares; the deed exits escrow only against 100% of them."),
        ("radio-tower", "4 · Anchor appraisal", "The oracle contract stores the appraisal commitment — anyone holding the JSON can verify exactly what a trade relied on."),
        ("arrow-right-left", "5 · Trade", "Fixed-price offers settle atomically in a EUR stablecoin: payment and shares move in one transaction, with a public audit trail."),
    ]
    return panel(
        rx.grid(
            *[
                card(
                    rx.hstack(rx.icon(icon, size=16, color=BLUE), rx.text(title, size="2", weight="bold", color=INK),
                              spacing="2", align="center"),
                    rx.text(body, size="1", color=INK_2, margin_top="4px"),
                    padding="12px",
                )
                for icon, title, body in steps
            ],
            columns=rx.breakpoints(initial="1", sm="2", lg="5"), spacing="2", width="100%",
        ),
        title="How a property reaches the chain",
        subtitle="appraise → mint → fractionalize → anchor → trade",
    )


@rx.page(route="/tokens", title="CityPulse — Property tokens", on_load=TokenState.load_page)
def tokens_page() -> rx.Component:
    S = TokenState
    return page(
        navbar(S.load_page),
        rx.cond(
            S.chain_ok,
            rx.fragment(
                panel(
                    rx.hstack(
                        kpi_tile("Tokenized properties", S.k_tokens, sub="ERC-721 deeds, escrowed & fractionalized", tone="violet"),
                        kpi_tile("On-chain market cap", S.k_mcap, sub="last share price × supply", tone="blue"),
                        kpi_tile("Traded volume", S.k_volume, sub="EURd settled on the marketplace", tone="aqua"),
                        kpi_tile("Appraisals anchored", S.k_anchored, sub="sha256 commitments via oracle", tone="orange"),
                        spacing="3", width="100%", wrap="wrap",
                    ),
                    title="Property chain at a glance",
                    tone="violet",
                    subtitle=S.chain_note,
                ),
                pipeline_card(),
                panel(
                    card(
                        rx.box(
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        *[rx.table.column_header_cell(
                                            rx.text(h, size="1", weight="medium", color=INK_2),
                                            text_align="left" if h == "Property" else "right")
                                          for h in ["Property", "Size", "Shares", "Holders", "Free float",
                                                    "Share price", "Oracle fair value", "Market cap", "Volume"]]
                                    )
                                ),
                                rx.table.body(rx.foreach(S.token_rows, token_row)),
                                variant="ghost", size="1", width="100%",
                            ),
                            overflow_x="auto", width="100%",
                        ),
                        width="100%",
                    ),
                    rx.cond(
                        S.holder_open_id != "",
                        card(
                            rx.text(S.holder_title, size="2", weight="bold", color=INK, margin_bottom="6px"),
                            rx.data_table(data=S.holder_rows, columns=["holder", "shares", "ownership"]),
                            width="100%", margin_top="10px",
                        ),
                    ),
                    title="Tokenized registry",
                    tone="violet",
                    subtitle="click a row for its cap table",
                ),
                panel(
                    rx.hstack(
                        card(
                            rx.text("Event feed", size="2", weight="bold", color=INK, margin_bottom="8px"),
                            rx.box(
                                rx.table.root(
                                    rx.table.body(rx.foreach(S.event_rows, event_row)),
                                    variant="ghost", size="1", width="100%",
                                ),
                                overflow_x="auto", max_height="420px", overflow_y="auto", width="100%",
                            ),
                            flex="2", min_width="0",
                        ),
                        card(
                            rx.text("Deployment", size="2", weight="bold", color=INK, margin_bottom="8px"),
                            rx.foreach(
                                S.contract_rows,
                                lambda c: rx.box(
                                    rx.text(c[0], size="2", weight="medium", color=INK),
                                    rx.code(c[1], size="1", word_break="break-all"),
                                    border_top=f"1px solid {HAIRLINE}", padding_y="6px",
                                ),
                            ),
                            rx.text(
                                "Demo chain (Anvil). The contracts are chain-agnostic Solidity 0.8 — the same "
                                "deployment targets any EVM network, public or permissioned.",
                                size="1", color=MUTED, margin_top="8px",
                            ),
                            flex="1", min_width="0",
                        ),
                        spacing="3", width="100%", align="start", wrap="wrap",
                    ),
                    title="On-chain activity",
                    tone="aqua",
                    subtitle="mints, appraisals, offers and trades, newest first",
                ),
            ),
            panel(rx.text(S.chain_note, size="2", color=INK_2), title="Property chain", tone="violet"),
        ),
    )
