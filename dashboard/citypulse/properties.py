"""Properties page — the valued Paris inventory: map, filters, sortable table,
and a full property dossier (value drivers + investment outlook) per listing."""
from __future__ import annotations

import json
import math
import re

import pandas as pd
import plotly.graph_objects as go
import reflex as rx

from citypulse import charts
from citypulse.data import PROJECT_ROOT, eaqi_band, load_listings, load_market
from citypulse.ui import (
    BLUE, BORDER, CARD_BG, HAIRLINE, INK, INK_2, MUTED, RED, STATUS, card, kpi_tile, navbar, page, panel,
)

CENTER = {"lat": 48.8566, "lon": 2.3522}
PAGE_SIZE = 20

PRICE_BANDS = {
    "Any price": (0, math.inf),
    "Under 300k €": (0, 300_000),
    "300k – 500k €": (300_000, 500_000),
    "500k – 800k €": (500_000, 800_000),
    "800k – 1.2M €": (800_000, 1_200_000),
    "1.2M – 2M €": (1_200_000, 2_000_000),
    "Over 2M €": (2_000_000, math.inf),
}
ROOMS = {"Any rooms": 0, "1+ rooms": 1, "2+ rooms": 2, "3+ rooms": 3, "4+ rooms": 4, "5+ rooms": 5}
SCHOOL = {"School: any": None, "School ≤ 150 m": 150, "School ≤ 300 m": 300, "School ≤ 500 m": 500}
METRO = {"Metro: any": None, "Metro ≤ 150 m": 150, "Metro ≤ 300 m": 300, "Metro ≤ 500 m": 500}
PARK = {"Park: any": None, "Park ≤ 150 m": 150, "Park ≤ 300 m": 300, "Park ≤ 500 m": 500}
TRAIN = {"Train/RER: any": None, "Train ≤ 500 m": 500, "Train ≤ 1 km": 1000, "Train ≤ 1.5 km": 1500}
TYPES = ["All types", "Appartement", "Maison"]

SORTABLE = {
    "arr": "arr_num", "zone": "zone_name", "type": "property_type", "surface": "surface_m2",
    "rooms": "rooms", "asking": "asking_eur", "fair": "fair_value_eur", "gap": "value_gap_pct",
    "m2": "asking_price_m2", "school": "dist_school_m", "metro": "dist_subway_m",
    "train": "dist_train_m", "park": "dist_park_m", "score": "opportunity_score",
}

SCORE_LABELS = {
    "value_gap": ("Price vs fair value", 35),
    "momentum": ("Zone price momentum", 25),
    "accessibility": ("Metro & train access", 20),
    "daily_life": ("Schools, parks, shops", 10),
    "environment": ("Traffic & air quality", 10),
}


# ---------------------------------------------------------------- formatting
def eur(v) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:,.0f} €".replace(",", " ")


def eur_short(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v / 1e6:.2f}M €" if v >= 1e6 else f"{v / 1e3:.0f}k €"


def meters(v) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v / 1000:.1f} km" if v >= 1000 else f"{v:.0f} m"


def walk(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return f"{max(1, round(v / 80))} min walk"


def name_or(v, default: str = "–") -> str:
    return default if v is None or (isinstance(v, float) and math.isnan(v)) or v == "" else str(v)


def gap_label(gap: float) -> str:
    if abs(gap) < 0.5:
        return "at fair value"
    return f"{abs(gap):.0f}% {'below' if gap > 0 else 'above'} fair value"


# ------------------------------------------------------------ value drivers
_MEDIAN_RE = re.compile(r"vs market median ([\d.]+)")


def humanize_driver(driver: dict, r: pd.Series) -> dict | None:
    """Turn a model driver into a sentence a buyer understands."""
    key, effect = driver["driver"], driver.get("effect_pct")
    # month_index is common to every listing (valuation date); property_type is a
    # baseline effect vs houses that reads as noise in a single-home dossier
    if effect is None or key == "month_index" or key.startswith("property_type="):
        return None
    m = _MEDIAN_RE.search(driver.get("detail", ""))
    med = float(m.group(1)) if m else None
    med_m = meters(med) if med is not None else "–"
    templates = {
        "dist_subway_m": ("Metro access", f"{name_or(r['subway_name'], 'Nearest metro')} is {meters(r['dist_subway_m'])} away "
                                          f"(typical Paris home: {med_m})"),
        "dist_train_m": ("Train / RER access", f"{name_or(r['train_name'], 'Nearest station')} is {meters(r['dist_train_m'])} away "
                                               f"(typical: {med_m})"),
        "dist_school_m": ("School nearby", f"{name_or(r['school_name'], 'Nearest school')} is {meters(r['dist_school_m'])} away "
                                           f"(typical: {med_m})"),
        "dist_park_m": ("Green space", f"{name_or(r['park_name'], 'Nearest park')} is {meters(r['dist_park_m'])} away (typical: {med_m})"),
        "n_schools_500m": ("School density", f"{int(r['n_schools_500m'])} schools within 500 m (typical: {med:.0f})" if med is not None else ""),
        "n_parks_500m": ("Park density", f"{int(r['n_parks_500m'])} parks within 500 m (typical: {med:.0f})" if med is not None else ""),
        "n_supermarkets_500m": ("Shops nearby", f"{int(r['n_supermarkets_500m'])} supermarkets within 500 m (typical: {med:.0f})" if med is not None else ""),
        "zone_traffic_occupancy": ("Road traffic", f"Road occupancy {r['zone_traffic_occupancy']:.1f}% in this zone "
                                                   f"(city median {med:.1f}%), live induction-loop sensors — in Paris busy roads track "
                                                   f"centrality, which buyers pay for" if med is not None else ""),
        "zone_eaqi": ("Air quality", f"European AQI {r['zone_eaqi']:.0f} in this zone (city median {med:.0f})" if med is not None else ""),
        "surface_m2": ("Size", f"{r['surface_m2']:.0f} m² (typical sale: {med:.0f} m²) — larger homes trade at a different €/m²" if med is not None else ""),
        "rooms": ("Layout", f"{int(r['rooms'])} rooms (typical: {med:.0f})" if med is not None else ""),
    }
    if key in templates:
        label, sentence = templates[key]
    elif key.startswith("zone="):
        label, sentence = "Neighbourhood", f"Location premium of the {r['zone_name']} zone vs the Paris average"
    elif key.startswith("property_type="):
        label, sentence = "Property type", f"{r['property_type']} — fixed effect vs other property types"
    else:
        label, sentence = key, driver.get("detail", "")
    return {"label": label, "sentence": sentence, "effect": f"{effect:+.1f}%", "raw": effect}


# --------------------------------------------------------------------- state
class PropertyState(rx.State):
    f_zone: str = "All zones"
    f_arr: str = "All arrondissements"
    f_type: str = "All types"
    f_price: str = "Any price"
    f_rooms: str = "Any rooms"
    f_school: str = "School: any"
    f_metro: str = "Metro: any"
    f_train: str = "Train/RER: any"
    f_park: str = "Park: any"
    f_undervalued: bool = False
    sort_key: str = "score"
    sort_desc: bool = True
    page_index: int = 0

    zone_options: list[str] = []
    arr_options: list[str] = []
    rows: list[dict[str, str]] = []
    map_ids: list[str] = []
    fig_map: go.Figure = go.Figure()
    # bumped on every new map figure: the plot remounts instead of updating in
    # place, so a map still loading its basemap style is never mutated
    # (plotly's maplibre layer throws "Style is not done loading" and the page dies)
    map_rev: int = 0
    total: int = 0
    range_text: str = ""
    has_prev: bool = False
    has_next: bool = False
    k_count: str = "–"
    k_median_m2: str = "–"
    k_undervalued: str = "–"
    k_best: str = "–"
    k_best_sub: str = ""
    as_of: str = ""
    model_note: str = ""

    detail_open: bool = False
    selected_id: str = ""
    d: dict[str, str] = {}
    d_token: dict[str, str] = {}
    d_drivers_up: list[dict[str, str]] = []
    d_drivers_down: list[dict[str, str]] = []
    d_scores: list[dict[str, str]] = []
    d_proj: list[dict[str, str]] = []
    d_life: list[dict[str, str]] = []
    d_thesis: list[str] = []
    fig_trend: go.Figure = go.Figure()

    # ---- loading & filtering ------------------------------------------------
    def load_page(self):
        df = load_listings()
        self.zone_options = ["All zones"] + sorted(df["zone_name"].dropna().unique().tolist())
        arrs = df.drop_duplicates("arrondissement").sort_values("arr_num")["arrondissement"].tolist()
        self.arr_options = ["All arrondissements"] + arrs
        self.as_of = str(df["valuation_as_of"].iloc[0])
        self.model_note = (
            f"Fair values from model {df['model_name'].iloc[0]} "
            f"(median error ±{df['model_median_ape_pct'].iloc[0]:.0f}% on held-out sales), as of {self.as_of}."
        )
        self._apply()

    def refresh(self):
        load_listings(force=True)
        self.load_page()

    def _filtered(self) -> pd.DataFrame:
        df = load_listings()
        if self.f_zone != "All zones":
            df = df[df["zone_name"] == self.f_zone]
        if self.f_arr != "All arrondissements":
            df = df[df["arrondissement"] == self.f_arr]
        if self.f_type != "All types":
            df = df[df["property_type"] == self.f_type]
        lo, hi = PRICE_BANDS[self.f_price]
        df = df[(df["asking_eur"] >= lo) & (df["asking_eur"] < hi)]
        if ROOMS[self.f_rooms]:
            df = df[df["rooms"] >= ROOMS[self.f_rooms]]
        for value, mapping, col in ((self.f_school, SCHOOL, "dist_school_m"),
                                    (self.f_metro, METRO, "dist_subway_m"),
                                    (self.f_train, TRAIN, "dist_train_m"),
                                    (self.f_park, PARK, "dist_park_m")):
            limit = mapping[value]
            if limit is not None:
                df = df[df[col] <= limit]
        if self.f_undervalued:
            df = df[df["gap_significant"] & (df["value_gap_pct"] > 0)]
        return df.sort_values(SORTABLE[self.sort_key], ascending=not self.sort_desc, na_position="last")

    def _apply(self):
        df = self._filtered()
        self.total = len(df)
        max_page = max(0, (self.total - 1) // PAGE_SIZE)
        self.page_index = min(self.page_index, max_page)

        self.k_count = f"{self.total:,}"
        self.k_median_m2 = "–" if df.empty else f"{df['asking_price_m2'].median():,.0f} €".replace(",", " ")
        n_under = int((df["gap_significant"] & (df["value_gap_pct"] > 0)).sum())
        self.k_undervalued = f"{n_under:,}"
        if df.empty:
            self.k_best, self.k_best_sub = "–", ""
        else:
            best = df.loc[df["opportunity_score"].idxmax()]
            self.k_best = f"{best['opportunity_grade']} · {best['opportunity_score']:.0f}/100"
            self.k_best_sub = f"{best['address']}, {best['arrondissement']}"

        self.map_ids = df["tx_id"].tolist()
        self.fig_map = charts.build_property_map(df, CENTER, self.selected_id or None)
        self.map_rev += 1

        start = self.page_index * PAGE_SIZE
        end = min(start + PAGE_SIZE, self.total)
        self.range_text = f"{start + 1 if self.total else 0}–{end} of {self.total:,}"
        self.has_prev = self.page_index > 0
        self.has_next = end < self.total
        page_df = df.iloc[start:end]
        self.rows = [self._row(r) for _, r in page_df.iterrows()]

    @staticmethod
    def _row(r: pd.Series) -> dict[str, str]:
        gap = float(r["value_gap_pct"])
        return {
            "id": r["tx_id"],
            "address": r["address"],
            "arr": r["arrondissement"],
            "zone": r["zone_name"],
            "type": "Apt" if r["property_type"] == "Appartement" else "House",
            "surface": f"{r['surface_m2']:.0f} m²",
            "rooms": "–" if pd.isna(r["rooms"]) else f"{int(r['rooms'])}",
            "asking": eur_short(r["asking_eur"]),
            "fair": eur_short(r["fair_value_eur"]),
            "m2": f"{r['asking_price_m2']:,.0f}".replace(",", " "),
            "gap": f"{gap:+.0f}%",
            "gap_color": BLUE if gap > 0 else RED,
            "gap_sig": "1" if bool(r["gap_significant"]) else "0",
            "school": meters(r["dist_school_m"]),
            "metro": meters(r["dist_subway_m"]),
            "train": meters(r["dist_train_m"]),
            "park": meters(r["dist_park_m"]),
            "score": f"{r['opportunity_score']:.0f}",
            "grade": r["opportunity_grade"],
        }

    # ---- filter setters (each re-applies, back to page 1) --------------------
    def _set(self, field: str, value):
        setattr(self, field, value)
        self.page_index = 0
        self._apply()

    def set_f_zone(self, v: str): self._set("f_zone", v)
    def set_f_arr(self, v: str): self._set("f_arr", v)
    def set_f_type(self, v: str): self._set("f_type", v)
    def set_f_price(self, v: str): self._set("f_price", v)
    def set_f_rooms(self, v: str): self._set("f_rooms", v)
    def set_f_school(self, v: str): self._set("f_school", v)
    def set_f_metro(self, v: str): self._set("f_metro", v)
    def set_f_train(self, v: str): self._set("f_train", v)
    def set_f_park(self, v: str): self._set("f_park", v)
    def set_f_undervalued(self, v: bool): self._set("f_undervalued", v)

    def reset_filters(self):
        self.f_zone, self.f_arr, self.f_type = "All zones", "All arrondissements", "All types"
        self.f_price, self.f_rooms = "Any price", "Any rooms"
        self.f_school, self.f_metro, self.f_train = "School: any", "Metro: any", "Train/RER: any"
        self.f_park = "Park: any"
        self.f_undervalued = False
        self.page_index = 0
        self._apply()

    def sort_by(self, key: str):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key = key
            self.sort_desc = key in ("score", "gap", "fair", "asking", "surface", "rooms", "m2")
        self.page_index = 0
        self._apply()

    def next_page(self):
        if (self.page_index + 1) * PAGE_SIZE < self.total:
            self.page_index += 1
            self._apply()

    def prev_page(self):
        if self.page_index > 0:
            self.page_index -= 1
            self._apply()

    # ---- detail dossier --------------------------------------------------------
    def map_click(self, points: list[dict]):
        if not points:
            return
        pt = points[0]
        if pt.get("curveNumber", 0) != 0:
            return
        idx = pt.get("pointIndex")
        if idx is not None and 0 <= idx < len(self.map_ids):
            self.open_detail(self.map_ids[idx])

    def set_detail_open(self, value: bool):
        self.detail_open = value

    def open_detail(self, tx_id: str):
        df = load_listings()
        hit = df[df["tx_id"] == tx_id]
        if hit.empty:
            return
        r = hit.iloc[0]
        self.selected_id = tx_id
        gap = float(r["value_gap_pct"])
        band = float(r["model_median_ape_pct"])
        eaqi_label, _ = eaqi_band(r["zone_eaqi"])
        self.d = {
            "id": r["tx_id"],
            "address": r["address"],
            "where": f"{r['arrondissement']} arrondissement · {r['zone_name']} zone · {r['postal_code']} Paris",
            "facts": f"{'Apartment' if r['property_type'] == 'Appartement' else 'House'} · {r['surface_m2']:.0f} m² · "
                     f"{'–' if pd.isna(r['rooms']) else int(r['rooms'])} room{'' if r['rooms'] == 1 else 's'}",
            "asking": eur(r["asking_eur"]),
            "asking_m2": f"{r['asking_price_m2']:,.0f} €/m²".replace(",", " "),
            "fair": eur(r["fair_value_eur"]),
            "fair_m2": f"{r['fair_price_m2']:,.0f} €/m²".replace(",", " "),
            "gap": gap_label(gap),
            "gap_color": BLUE if gap > 0 else RED,
            "gap_icon": "▲" if gap > 0 else "▼",
            "gap_note": (f"Beyond the model's ±{band:.0f}% error band — the discount is likely real."
                         if gap > band else
                         f"Above fair value by more than the ±{band:.0f}% error band — negotiate or pass."
                         if gap < -band else
                         f"Within the model's ±{band:.0f}% error band — treat as fairly priced."),
            "grade": r["opportunity_grade"],
            "score": f"{r['opportunity_score']:.0f}",
            "traffic": f"{r['zone_traffic_occupancy']:.1f}% road occupancy",
            "air": f"EAQI {r['zone_eaqi']:.0f} · {eaqi_label}",
            "momentum": f"{r['zone_yoy'] * 100:+.1f}%",
            "growth": f"{r['growth_base_pct']:+.1f}% / yr",
            "proj_base": eur(r["proj_base_eur"]),
            "proj_gain": f"{r['proj_base_gain_pct']:+.0f}%",
            "model": r["model_name"],
            "model_err": f"±{band:.0f}%",
            "as_of": r["valuation_as_of"],
            "sha": r["appraisal_sha256"],
            "sold_on": pd.to_datetime(r["sold_on"]).strftime("%d %b %Y"),
        }

        drivers = [h for d in json.loads(r["drivers_json"]) if (h := humanize_driver(d, r)) and h["sentence"]]
        max_abs = max((abs(d["raw"]) for d in drivers), default=1) or 1
        for d in drivers:
            d["width"] = f"{max(4, abs(d['raw']) / max_abs * 100):.0f}%"
        up = sorted((d for d in drivers if d["raw"] > 0.05), key=lambda d: -d["raw"])
        down = sorted((d for d in drivers if d["raw"] < -0.05), key=lambda d: d["raw"])
        strip = lambda ds: [{k: v for k, v in d.items() if k != "raw"} for d in ds[:6]]
        self.d_drivers_up, self.d_drivers_down = strip(up), strip(down)

        self.d_scores = [
            {"label": label, "weight": f"{w}%", "value": f"{r[f'score_{k}']:.0f}",
             "width": f"{max(2, r[f'score_{k}']):.0f}%"}
            for k, (label, w) in SCORE_LABELS.items()
        ]
        self.d_proj = [
            {"name": name, "value": eur(r[f"proj_{key}_eur"]),
             "rate": f"{(r['growth_base_pct'] + delta):+.1f}% / yr",
             "gain": f"{((r[f'proj_{key}_eur'] / r['asking_eur']) - 1) * 100:+.0f}% vs asking"}
            for name, key, delta in (("Bear", "bear", -2.5), ("Base", "base", 0.0), ("Bull", "bull", 2.5))
        ]
        self.d_life = [
            {"icon": "graduation-cap", "label": "Nearest school", "name": name_or(r["school_name"]),
             "dist": meters(r["dist_school_m"]), "walk": walk(r["dist_school_m"])},
            {"icon": "train-front", "label": "Nearest metro", "name": name_or(r["subway_name"]),
             "dist": meters(r["dist_subway_m"]), "walk": walk(r["dist_subway_m"])},
            {"icon": "train-track", "label": "Nearest train / RER", "name": name_or(r["train_name"]),
             "dist": meters(r["dist_train_m"]), "walk": walk(r["dist_train_m"])},
            {"icon": "trees", "label": "Nearest park", "name": name_or(r["park_name"]),
             "dist": meters(r["dist_park_m"]), "walk": walk(r["dist_park_m"])},
        ]
        self.d["within"] = (f"Within 500 m: {int(r['n_schools_500m'])} schools · {int(r['n_parks_500m'])} parks · "
                            f"{int(r['n_supermarkets_500m'])} supermarkets")

        thesis = []
        if gap > band:
            thesis.append(f"Priced {gap:.0f}% below our fair-value estimate — more than the model's typical error, "
                          f"so the discount is a genuine signal.")
        elif gap < -band:
            thesis.append(f"Priced {abs(gap):.0f}% above fair value — the premium exceeds model error; "
                          f"a buyer should negotiate.")
        else:
            thesis.append("Priced close to fair value — returns depend on market momentum, not on buying cheap.")
        thesis.append(f"{r['zone_name']} zone prices moved {r['zone_yoy'] * 100:+.1f}% over the last full year; "
                      f"the base case blends that momentum with a +2.0%/yr long-run Paris anchor.")
        if r["dist_subway_m"] <= 250:
            thesis.append(f"Exceptional transit: {name_or(r['subway_name'], 'the')} metro {meters(r['dist_subway_m'])} away "
                          f"supports rental demand and resale liquidity.")
        if r["score_environment"] < 35:
            thesis.append("Weaker on environment: the zone carries above-average road traffic or air pollution.")
        self.d_thesis = thesis

        # on-chain status (present once the tokenization engine has run)
        self.d_token = {}
        tokens_path = PROJECT_ROOT / "data" / "chain" / "tokens.parquet"
        if tokens_path.exists():
            tok = pd.read_parquet(tokens_path)
            hit_t = tok[tok["listing_id"] == tx_id]
            if not hit_t.empty:
                t = hit_t.iloc[0]
                holders = json.loads(t["holders_json"])
                top = sorted(holders.items(), key=lambda kv: -kv[1])
                self.d_token = {
                    "deed": t["token_id"][:16] + "…",
                    "minted": pd.to_datetime(t["minted_at"]).strftime("%d %b %Y %H:%M UTC"),
                    "shares": f"{int(t['shares_supply']):,} shares · {int(t['n_holders'])} holders"
                              f" · free float {t['free_float_pct']:.0f}%",
                    "px": "no trades yet" if pd.isna(t["last_share_price_eur"]) else
                          f"last share price {t['last_share_price_eur']:,.2f} € · "
                          f"implied market cap {t['market_cap_eur']:,.0f} €".replace(",", " "),
                    "holders": " · ".join(f"{k} {100 * v / t['shares_supply']:.0f}%" for k, v in top[:4]),
                    "oracle": f"oracle fair value {t['onchain_fair_eur']:,.0f} €".replace(",", " ")
                              + f" · {int(t['n_appraisals'])} appraisal(s) anchored",
                }

        mk = load_market()
        self.fig_trend = charts.build_property_trend(
            mk["market"], r["zone"], r["zone_name"], r["property_type"],
            float(r["asking_price_m2"]), float(r["fair_price_m2"]),
        )
        self.fig_map = charts.build_property_map(self._filtered(), CENTER, tx_id)
        self.map_rev += 1
        self.detail_open = True


# ------------------------------------------------------------------------ UI
def filter_select(items, value, handler, width="auto") -> rx.Component:
    return rx.select(items, value=value, on_change=handler, size="2", width=width)


def filter_bar() -> rx.Component:
    S = PropertyState
    return card(
        rx.hstack(
            filter_select(S.zone_options, S.f_zone, S.set_f_zone),
            filter_select(S.arr_options, S.f_arr, S.set_f_arr),
            filter_select(TYPES, S.f_type, S.set_f_type),
            filter_select(list(PRICE_BANDS), S.f_price, S.set_f_price),
            filter_select(list(ROOMS), S.f_rooms, S.set_f_rooms),
            filter_select(list(SCHOOL), S.f_school, S.set_f_school),
            filter_select(list(METRO), S.f_metro, S.set_f_metro),
            filter_select(list(TRAIN), S.f_train, S.set_f_train),
            filter_select(list(PARK), S.f_park, S.set_f_park),
            rx.hstack(
                rx.switch(checked=S.f_undervalued, on_change=S.set_f_undervalued, size="1"),
                rx.text("Undervalued only", size="2", color=INK_2),
                align="center", spacing="2",
            ),
            rx.button("Reset", on_click=S.reset_filters, size="2", variant="ghost"),
            wrap="wrap", spacing="2", align="center",
        ),
        width="100%", padding="12px", margin_top="12px",
    )


def sort_header(label: str, key: str, align: str = "left") -> rx.Component:
    S = PropertyState
    arrow = rx.cond(S.sort_key == key, rx.cond(S.sort_desc, " ↓", " ↑"), "")
    return rx.table.column_header_cell(
        rx.text(label, arrow, size="1", weight="medium", color=INK_2, white_space="nowrap"),
        on_click=S.sort_by(key),
        cursor="pointer",
        text_align=align,
        _hover={"background_color": "rgba(11,11,11,0.04)"},
    )


def grade_chip(grade, size: str = "22px") -> rx.Component:
    return rx.center(
        rx.text(grade, weight="bold", size="1", color="white"),
        width=size, height=size, border_radius="6px",
        background_color=rx.match(
            grade, ("A", "#0d366b"), ("B", "#256abf"), ("C", "#5598e7"), ("D", "#86b6ef"), "#b7d3f6",
        ),
    )


def gap_cell(row) -> rx.Component:
    return rx.hstack(
        rx.box(width="8px", height="8px", border_radius="2px", background_color=row["gap_color"]),
        rx.text(row["gap"], size="2", color=INK,
                weight=rx.cond(row["gap_sig"] == "1", "bold", "regular")),
        align="center", spacing="1", justify="end",
    )


def table_row(row) -> rx.Component:
    num = {"text_align": "right", "white_space": "nowrap"}
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                rx.text(row["address"], size="2", weight="medium", color=INK),
                rx.text(row["arr"], " · ", row["zone"], size="1", color=MUTED),
                spacing="0",
            )
        ),
        rx.table.cell(rx.text(row["type"], size="2", color=INK_2)),
        rx.table.cell(rx.text(row["surface"], size="2"), style=num),
        rx.table.cell(rx.text(row["rooms"], size="2"), style=num),
        rx.table.cell(rx.text(row["asking"], size="2", weight="medium"), style=num),
        rx.table.cell(rx.text(row["fair"], size="2", color=INK_2), style=num),
        rx.table.cell(gap_cell(row), style=num),
        rx.table.cell(rx.text(row["m2"], size="2", color=INK_2), style=num),
        rx.table.cell(rx.text(row["school"], size="2"), style=num),
        rx.table.cell(rx.text(row["metro"], size="2"), style=num),
        rx.table.cell(rx.text(row["train"], size="2"), style=num),
        rx.table.cell(rx.text(row["park"], size="2"), style=num),
        rx.table.cell(
            rx.hstack(grade_chip(row["grade"]), rx.text(row["score"], size="2"),
                      spacing="2", align="center", justify="end"),
            style=num,
        ),
        on_click=PropertyState.open_detail(row["id"]),
        cursor="pointer",
        _hover={"background_color": "rgba(42,120,214,0.06)"},
    )


def listings_table() -> rx.Component:
    S = PropertyState
    return panel(
        rx.hstack(
            rx.text("Property valuations", size="3", weight="bold", color=INK),
            rx.text("click a column to sort · click a row for the full dossier", size="1", color=MUTED),
            rx.spacer(),
            rx.text(S.range_text, size="1", color=INK_2),
            rx.button("‹ Prev", on_click=S.prev_page, size="1", variant="soft", disabled=~S.has_prev),
            rx.button("Next ›", on_click=S.next_page, size="1", variant="soft", disabled=~S.has_next),
            align="center", spacing="3", width="100%", margin_bottom="8px",
        ),
        rx.box(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        sort_header("Address", "arr"),
                        sort_header("Type", "type"),
                        sort_header("Size", "surface", "right"),
                        sort_header("Rooms", "rooms", "right"),
                        sort_header("Asking", "asking", "right"),
                        sort_header("Fair value", "fair", "right"),
                        sort_header("Gap", "gap", "right"),
                        sort_header("€/m²", "m2", "right"),
                        sort_header("School", "school", "right"),
                        sort_header("Metro", "metro", "right"),
                        sort_header("Train/RER", "train", "right"),
                        sort_header("Park", "park", "right"),
                        sort_header("Opportunity", "score", "right"),
                    )
                ),
                rx.table.body(rx.foreach(S.rows, table_row)),
                variant="ghost", size="1", width="100%",
            ),
            overflow_x="auto", width="100%",
        ),
        rx.cond(S.total == 0, rx.text("No property matches these filters.", size="2", color=MUTED, padding="16px")),
        rx.text(S.model_note, " Inventory: recent single-dwelling DVF sales (real address, surface, rooms, "
                "recorded price shown as asking); non-market transfers screened out.",
                size="1", color=MUTED, margin_top="10px"),
        tone="violet",
    )


# ---- dossier (detail popup) ----------------------------------------------------
def section(title: str, *children, **kwargs) -> rx.Component:
    return rx.box(
        rx.text(title, size="1", weight="bold", color="#1c5cab", text_transform="uppercase",
                letter_spacing="0.06em", margin_bottom="8px"),
        *children,
        border_top=f"1px solid {HAIRLINE}", padding_top="14px", width="100%", **kwargs,
    )


def driver_row(d, color: str) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(d["label"], size="2", weight="medium", color=INK),
            rx.spacer(),
            rx.text(d["effect"], size="2", weight="bold", color=INK),
            width="100%",
        ),
        rx.box(rx.box(height="6px", width=d["width"], background_color=color, border_radius="3px"),
               width="100%", background_color="rgba(11,11,11,0.05)", border_radius="3px", margin_y="4px"),
        rx.text(d["sentence"], size="1", color=INK_2),
        width="100%", margin_bottom="10px",
    )


def life_tile(item) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.match(
                item["icon"],
                ("graduation-cap", rx.icon("graduation-cap", size=16, color=INK_2)),
                ("train-front", rx.icon("train-front", size=16, color=INK_2)),
                ("train-track", rx.icon("train-track", size=16, color=INK_2)),
                rx.icon("trees", size=16, color=INK_2),
            ),
            rx.text(item["label"], size="1", color=MUTED),
            spacing="2", align="center",
        ),
        rx.text(item["name"], size="2", weight="medium", color=INK, margin_top="4px"),
        rx.text(item["dist"], " · ", item["walk"], size="1", color=INK_2),
        border=BORDER, border_radius="8px", padding="10px", flex="1", min_width="180px",
    )


def score_bar(s) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(s["label"], size="1", color=INK),
            rx.text("weight ", s["weight"], size="1", color=MUTED),
            rx.spacer(),
            rx.text(s["value"], "/100", size="1", weight="bold", color=INK),
            width="100%",
        ),
        rx.box(rx.box(height="6px", width=s["width"], background_color="#2a78d6", border_radius="3px"),
               width="100%", background_color="rgba(11,11,11,0.05)", border_radius="3px", margin_top="3px"),
        width="100%", margin_bottom="8px",
    )


def proj_tile(p) -> rx.Component:
    return rx.box(
        rx.text(p["name"], " case", size="1", color=MUTED),
        rx.text(p["value"], size="3", weight="bold", color=INK),
        rx.text(p["rate"], size="1", color=INK_2),
        rx.text(p["gain"], size="1", color=INK_2),
        border=BORDER, border_radius="8px", padding="10px", flex="1", min_width="140px",
    )


def dossier() -> rx.Component:
    S = PropertyState
    d = S.d
    header = rx.hstack(
        rx.vstack(
            rx.dialog.title(d["address"], size="6", color=INK, margin="0"),
            rx.text(d["where"], size="2", color=INK_2),
            rx.text(d["facts"], " · last recorded sale ", d["sold_on"], size="2", color=MUTED),
            spacing="1", align="start",
        ),
        rx.spacer(),
        rx.hstack(
            grade_chip(d["grade"], size="44px"),
            rx.vstack(
                rx.text("Opportunity", size="1", color=MUTED),
                rx.text(d["score"], "/100", size="4", weight="bold", color=INK),
                spacing="0",
            ),
            align="center", spacing="2",
        ),
        rx.dialog.close(rx.icon_button(rx.icon("x"), variant="ghost", size="2")),
        align="start", width="100%",
    )
    price_strip = rx.hstack(
        rx.box(rx.text("Asking price", size="1", color=MUTED),
               rx.text(d["asking"], size="6", weight="bold", color=INK),
               rx.text(d["asking_m2"], size="1", color=INK_2), flex="1"),
        rx.box(rx.text("Fair value (model)", size="1", color=MUTED),
               rx.text(d["fair"], size="6", weight="bold", color=INK),
               rx.text(d["fair_m2"], " · as of ", d["as_of"], size="1", color=INK_2), flex="1"),
        rx.box(
            rx.hstack(rx.text(d["gap_icon"], color=d["gap_color"], size="3"),
                      rx.text(d["gap"], size="3", weight="bold", color=INK), align="center", spacing="1"),
            rx.text(d["gap_note"], size="1", color=INK_2),
            flex="1.4",
        ),
        spacing="5", width="100%", align="start", wrap="wrap",
    )
    drivers = section(
        "What drives this value",
        rx.text("Each factor's effect on €/m² versus a typical Paris home, from the valuation model.",
                size="1", color=MUTED, margin_bottom="10px"),
        rx.grid(
            rx.box(rx.text("Pushing the value up", size="2", weight="bold", color=INK, margin_bottom="8px"),
                   rx.foreach(S.d_drivers_up, lambda x: driver_row(x, "#2a78d6"))),
            rx.box(rx.text("Holding the value back", size="2", weight="bold", color=INK, margin_bottom="8px"),
                   rx.foreach(S.d_drivers_down, lambda x: driver_row(x, "#e66767"))),
            columns=rx.breakpoints(initial="1", md="2"), spacing="5", width="100%",
        ),
    )
    life = section(
        "Daily life & accessibility",
        rx.hstack(rx.foreach(S.d_life, life_tile), wrap="wrap", spacing="2", width="100%"),
        rx.text(d["within"], size="1", color=INK_2, margin_top="8px"),
        rx.hstack(
            rx.hstack(rx.icon("car", size=14, color=INK_2), rx.text(d["traffic"], size="1", color=INK_2),
                      spacing="1", align="center"),
            rx.hstack(rx.icon("wind", size=14, color=INK_2), rx.text(d["air"], size="1", color=INK_2),
                      spacing="1", align="center"),
            rx.text("— live city sensors for this zone", size="1", color=MUTED),
            spacing="4", margin_top="4px", wrap="wrap",
        ),
    )
    market = section(
        "Market context",
        rx.plotly(data=S.fig_trend, width="100%"),
    )
    outlook = section(
        "Investment outlook",
        rx.grid(
            rx.box(
                rx.text("Opportunity score breakdown", size="2", weight="bold", color=INK, margin_bottom="8px"),
                rx.foreach(S.d_scores, score_bar),
            ),
            rx.box(
                rx.text("3-year appraisal outlook", size="2", weight="bold", color=INK, margin_bottom="8px"),
                rx.hstack(rx.foreach(S.d_proj, proj_tile), spacing="2", wrap="wrap", width="100%"),
                rx.text("Base growth ", d["growth"], ": zone momentum (", d["momentum"],
                        " last year) blended 50/50 with a +2%/yr long-run Paris anchor; bear/bull ±2.5 pp/yr. "
                        "Indicative scenarios, not investment advice.",
                        size="1", color=MUTED, margin_top="8px"),
            ),
            columns=rx.breakpoints(initial="1", md="2"), spacing="5", width="100%",
        ),
        rx.box(
            rx.text("Thesis", size="2", weight="bold", color=INK, margin_top="10px", margin_bottom="4px"),
            rx.foreach(S.d_thesis, lambda t: rx.hstack(rx.text("•", color=MUTED), rx.text(t, size="2", color=INK_2),
                                                       spacing="2", align="start")),
        ),
    )
    onchain = rx.cond(
        S.d_token.length() > 0,
        section(
            "On-chain status",
            rx.hstack(
                rx.icon("link", size=14, color=BLUE),
                rx.text("Tokenized — deed ", rx.code(S.d_token["deed"]), " minted ", S.d_token["minted"],
                        size="2", color=INK),
                spacing="2", align="center",
            ),
            rx.text(S.d_token["shares"], size="1", color=INK_2, margin_top="4px"),
            rx.text(S.d_token["px"], size="1", color=INK_2),
            rx.text("Cap table: ", S.d_token["holders"], size="1", color=INK_2),
            rx.text(S.d_token["oracle"], size="1", color=MUTED, margin_top="2px"),
        ),
        section(
            "On-chain status",
            rx.text(
                "Not tokenized yet. Grade A/B properties are eligible for deed minting and "
                "fractionalization on the property chain — see the Tokens page.",
                size="1", color=INK_2,
            ),
        ),
    )
    provenance = section(
        "Provenance",
        rx.text("Listing ", rx.code(d["id"]), " · model ", d["model"], " (median error ", d["model_err"],
                ") · valuation as of ", d["as_of"], size="1", color=INK_2),
        rx.text("Appraisal sha256 ", rx.code(d["sha"]), size="1", color=INK_2, margin_top="2px",
                word_break="break-all"),
        rx.text("Content-addressed appraisal — the payload a smart contract anchors when this property is tokenized.",
                size="1", color=MUTED, margin_top="2px"),
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(header, price_strip, drivers, life, market, outlook, onchain, provenance,
                      spacing="4", width="100%"),
            max_width="1040px", width="95vw", max_height="90vh", overflow_y="auto",
            background_color=CARD_BG, padding="24px",
        ),
        open=S.detail_open,
        on_open_change=S.set_detail_open,
    )


@rx.page(route="/", title="CityPulse — Paris properties", on_load=PropertyState.load_page)
def properties_page() -> rx.Component:
    S = PropertyState
    return page(
        navbar(S.refresh),
        panel(
            rx.hstack(
                kpi_tile("Properties matching", S.k_count, sub="real addresses · DVF", tone="blue"),
                kpi_tile("Median asking €/m²", S.k_median_m2, tone="aqua"),
                kpi_tile("Undervalued beyond model error", S.k_undervalued, sub="fair value > asking + error band", tone="violet"),
                kpi_tile("Best opportunity", S.k_best, sub=S.k_best_sub, tone="orange"),
                spacing="3", width="100%", wrap="wrap",
            ),
            filter_bar(),
            title="Search the Paris market",
            subtitle="filters apply to the map and the table",
        ),
        panel(
            rx.plotly(data=S.fig_map, width="100%", on_click=S.map_click, key=S.map_rev.to_string()),
            title="Fair value vs asking price",
            tone="aqua",
            subtitle="grey = fairly priced · blue = below fair value · red = above · click a dot for its dossier",
        ),
        listings_table(),
        dossier(),
    )
