"""Doc page: what CityPulse is, for a first-time (non-technical) visitor.

Static narrative; the headline counts are read from the ontology manifest at
compile time so they always match the data actually behind the dashboard.
"""
from __future__ import annotations

import json

import reflex as rx

from citypulse.data import PROJECT_ROOT
from citypulse.ui import INK, INK_2, MUTED, TONES, card, kpi_tile, navbar, page, panel


def _counts() -> dict:
    try:
        return json.loads((PROJECT_ROOT / "data" / "ontology" / "manifest.json").read_text())["counts"]
    except (OSError, KeyError, ValueError):
        return {}


def _n(counts: dict, key: str) -> str:
    return f"{counts[key]:,}" if key in counts else "–"


def _para(text: str, **kwargs) -> rx.Component:
    return rx.text(text, size="2", color=INK_2, line_height="1.65", **kwargs)


def _point(icon: str, title: str, body: str, tone: str = "blue") -> rx.Component:
    main, tint, deep = TONES[tone]
    return card(
        rx.hstack(
            rx.center(rx.icon(icon, size=16, color=main), width="30px", height="30px",
                      border_radius="8px", background_color=tint, flex_shrink="0"),
            rx.text(title, size="2", weight="bold", color=deep),
            spacing="2", align="center",
        ),
        rx.text(body, size="2", color=INK_2, line_height="1.6", margin_top="8px"),
        padding="14px",
    )


def _flow(steps: list[tuple[str, str]], tone: str) -> rx.Component:
    main, tint, deep = TONES[tone]
    items: list[rx.Component] = []
    for i, (label, sub) in enumerate(steps):
        if i:
            items.append(rx.icon("chevron-right", size=16, color=MUTED, flex_shrink="0"))
        items.append(rx.box(
            rx.text(label, size="2", weight="bold", color=deep),
            rx.text(sub, size="1", color=INK_2),
            background_color=tint, border=f"1px solid {main}40", border_radius="10px",
            padding="8px 12px",
        ))
    return rx.hstack(*items, align="center", spacing="2", wrap="wrap", width="100%", margin_top="12px")


def _page_card(label: str, href: str, icon: str, tone: str, body: str) -> rx.Component:
    main, tint, deep = TONES[tone]
    return rx.link(
        card(
            rx.hstack(
                rx.center(rx.icon(icon, size=16, color="white"), width="30px", height="30px",
                          border_radius="8px", background_color=main, flex_shrink="0"),
                rx.text(label, size="3", weight="bold", color=deep),
                rx.spacer(),
                rx.icon("arrow-up-right", size=16, color=MUTED),
                align="center", spacing="2", width="100%",
            ),
            rx.text(body, size="2", color=INK_2, line_height="1.6", margin_top="8px"),
            padding="14px", height="100%", border_left=f"4px solid {main}",
            _hover={"box_shadow": f"0 0 0 2px {main}55"},
        ),
        href=href, underline="none", height="100%",
    )


@rx.page(route="/doc", title="CityPulse — About the project")
def doc_page() -> rx.Component:
    c = _counts()
    n_types = sum(1 for k in c if k[0].isupper())  # object types are capitalised, link types not
    return page(
        navbar(),
        # ------------------------------------------------------------------ hero
        panel(
            rx.heading("From city sensors to tokenized real estate", size="7", color=INK),
            _para(
                "CityPulse is a working smart-city data platform for Paris. It streams real "
                "measurements from the city's own infrastructure (road-traffic loops, air-quality "
                "stations, bike-share docks), combines them with every official property sale and "
                "the city's amenities, and organises it all into a live digital model of the city. "
                "On top of that model it values homes, and then issues those homes as tokenized "
                "assets on a blockchain: a title deed, 1,000 tradable shares, an on-chain "
                "valuation oracle and a marketplace that settles instantly.",
                margin_top="10px",
            ),
            _para(
                "It is built the way enterprise smart-city platforms (such as Palantir Foundry) are "
                "built: connectors land raw data, distributed pipelines refine it, an ontology turns "
                "tables into connected real-world objects, and applications such as this dashboard "
                "run on that ontology. All city and property data is real open data; the investors "
                "and share trades on the chain are simulated to demonstrate the market.",
                margin_top="8px",
            ),
            rx.grid(
                kpi_tile("Property sales", _n(c, "PropertyTransaction"), sub="official DVF records, 2021–2025", tone="blue"),
                kpi_tile("Road-traffic sensors", _n(c, "TrafficSensor"), sub="induction loops, hourly", tone="aqua"),
                kpi_tile("Bike-share stations", _n(c, "BikeStation"), sub="Vélib' live docks", tone="aqua"),
                kpi_tile("City amenities", _n(c, "Amenity"), sub="metro, RER, schools, parks, shops", tone="orange"),
                kpi_tile("Sensor observations", _n(c, "Observation"), sub="time-stamped, in the ontology", tone="violet"),
                kpi_tile("Tokenized properties", _n(c, "PropertyToken"), sub=f"{_n(c, 'ShareTrade')} share trades settled", tone="magenta"),
                columns=rx.breakpoints(initial="1", sm="2", md="3", lg="6"), spacing="3", width="100%",
                margin_top="16px",
            ),
            tone="blue",
        ),
        # ------------------------------------------------------- smart city layer
        panel(
            _para(
                "A smart city is only as smart as its ability to connect what its sensors measure "
                "with the decisions people make. CityPulse covers that whole chain, end to end:"
            ),
            _flow([
                ("Sense", "IoT feeds & open data"),
                ("Land", "raw, append-only zone"),
                ("Refine", "PySpark pipelines"),
                ("Model", "city ontology"),
                ("Decide", "valuation & apps"),
            ], "aqua"),
            rx.grid(
                _point("radio-tower", "Live urban sensing",
                       f"{_n(c, 'TrafficSensor')} road-traffic induction loops report flow and occupancy "
                       "every hour; air-quality stations report PM2.5, NO₂ and the European Air Quality "
                       f"Index per district; {_n(c, 'BikeStation')} bike-share stations report dock "
                       "availability in real time. Collectors poll these feeds on a schedule.", "aqua"),
                _point("layers", "Lakehouse data platform",
                       "Raw readings are stored untouched as an audit trail, then PySpark pipelines clean, "
                       "type and deduplicate them and run geospatial joins: every sale, sensor and amenity "
                       "is placed in its district, and every home is linked to its nearest metro, RER "
                       "station, school and park.", "aqua"),
                _point("network", "City ontology (digital twin)",
                       f"The refined data becomes a graph of real-world objects ({n_types} object types: "
                       "districts, sensors, sales, amenities, tokens, investors) and the "
                       "links between them. The ontology is derived from the pipelines, never edited by "
                       "hand, so it always reflects the latest data.", "violet"),
                _point("badge-check", "Open standards",
                       "The graph exports to JSON-LD using W3C SOSA/SSN, the sensing vocabulary behind "
                       "NGSI-LD and SAREF4City, plus schema.org for places and sales. That makes it "
                       "interoperable with standard smart-city platforms rather than a closed silo.", "violet"),
                _point("map-pinned", "Location intelligence",
                       "Each home is described by what the city measures around it: walking distance to "
                       "transit, schools and parks within 500 m, the district's road-traffic load and its "
                       "air quality. These urban signals are exactly what drives its value.", "orange"),
                _point("scale", "Explainable valuation",
                       "A hedonic model prices every home from those city signals, with a per-driver "
                       "explanation. It was tested honestly on 28,958 sales from 2025 that it never saw "
                       "during training: median error 15%, in line with what a public sales register "
                       "without floor or condition data allows.", "orange"),
                columns=rx.breakpoints(initial="1", md="2", lg="3"), spacing="3", width="100%",
                margin_top="14px",
            ),
            title="Smart-city technology",
            subtitle="sensing → data platform → ontology → decisions",
            tone="aqua",
        ),
        # ------------------------------------------------------- tokenization layer
        panel(
            _para(
                "Tokenization turns ownership of a real asset into a digital token on a blockchain. "
                "For real estate this means a property can be split into small, freely tradable "
                "shares, settled in seconds instead of weeks, with every transfer recorded in a "
                "public, tamper-proof ledger. CityPulse implements the full lifecycle with five smart "
                "contracts written in Solidity. The demo runs them on a local Ethereum-compatible "
                "chain; the same contracts deploy unchanged to any EVM network:"
            ),
            _flow([
                ("Appraise", "city-data valuation"),
                ("Mint", "title deed NFT"),
                ("Fractionalize", "1,000 shares"),
                ("Anchor", "valuation oracle"),
                ("Trade", "instant settlement"),
                ("Index", "back into the ontology"),
            ], "violet"),
            rx.grid(
                _point("file-badge", "Digital title deed",
                       "Each property is minted as a unique token (ERC-721) whose identifier is derived "
                       "from the official land-registry parcel id, so the blockchain and the city "
                       "ontology refer to the same real asset.", "violet"),
                _point("pie-chart", "Fractional ownership",
                       "The deed is locked in escrow and 1,000 fungible shares are issued against it. "
                       "The deed can only leave escrow if someone gathers 100% of the shares. A 500k€ "
                       "apartment becomes 1,000 shares of 500€.", "violet"),
                _point("shield-check", "Valuation oracle",
                       "The city-data valuation is anchored on-chain: a cryptographic fingerprint of "
                       "each appraisal, its fair value and the model that produced it. Personal data "
                       "stays off-chain (GDPR); only its proof is public, so anyone can verify a price.",
                       "magenta"),
                _point("arrow-left-right", "Atomic marketplace",
                       "Investors list and buy shares at a fixed price. Payment, in a euro stablecoin "
                       "(a demo stand-in for a regulated one), "
                       "and shares move in a single transaction or not at all: no counterparty risk and "
                       "no settlement delay.", "magenta"),
                _point("refresh-ccw", "Chain ↔ city data, one model",
                       "An indexer reads the contracts' events back into the data platform, where they "
                       "become ontology objects (tokens, investors, holdings, offers, trades). One graph "
                       "walk goes from the original sale to the appraisal, the deed and today's cap table.",
                       "blue"),
                _point("trending-up", "Why it matters",
                       "For a city developer, tokenization means fractional access to prime real estate, "
                       "faster capital recycling, liquidity for traditionally illiquid assets and a "
                       "transparent registry, all on the same data platform that already runs the city.",
                       "blue"),
                columns=rx.breakpoints(initial="1", md="2", lg="3"), spacing="3", width="100%",
                margin_top="14px",
            ),
            title="Real-world asset tokenization",
            subtitle="property → deed → shares → oracle → market",
            tone="violet",
        ),
        # ----------------------------------------------------------- page guide
        panel(
            rx.grid(
                _page_card("Properties", "/", "building-2", "blue",
                           "The investment view: a map and sortable table of 2,213 real Paris homes "
                           "with asking price, model fair value and how far apart they are. Filter by "
                           "district, type, budget, rooms and distance to transit, schools and parks. "
                           "Click a home for its full dossier: value drivers in plain language, nearby "
                           "amenities with walking times, live traffic and air quality, price trend, "
                           "opportunity score, 3-year projections and, if tokenized, its on-chain status."),
                _page_card("Tokens", "/tokens", "coins", "violet",
                           "The blockchain explorer: every tokenized property with its deed, share "
                           "supply, last traded price and market value; the cap table of who owns how "
                           "many shares; and a live feed of mints, appraisals, offers and trades."),
                _page_card("Data sources", "/sources", "database", "aqua",
                           "The data catalog: each feed's provider, licence, update frequency, coverage "
                           "and freshness, plus exactly which ontology objects and valuation signals it "
                           "feeds. Click any sensor on the map to see its reading history."),
                _page_card("Ontology", "/ontology", "network", "orange",
                           "The city's digital model: how many objects and links of each type it holds, "
                           "a lookup that resolves any object and follows its links, and a district view "
                           "combining sales, sensors, amenities, air quality and hourly traffic."),
                _page_card("Appraise", "/appraise", "calculator", "magenta",
                           "Price any home: choose a district, type, surface and rooms, and get a fair "
                           "value with the contribution of each city signal, next to a price map and the "
                           "district's price trend."),
                columns=rx.breakpoints(initial="1", md="2", lg="3"), spacing="3", width="100%",
            ),
            title="What each page shows",
            subtitle="click a card to open the page",
            tone="orange",
        ),
        max_width="1200px",
    )
