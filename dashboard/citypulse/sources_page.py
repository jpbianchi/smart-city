"""Data sources page — the catalog of every feed behind the ontology and the
valuation: provenance, coverage, downstream usage, and per-record drill-down."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import reflex as rx

from citypulse import charts
from citypulse.ui import BLUE, BORDER, CARD_BG, HAIRLINE, INK, INK_2, MUTED, card, navbar, page, panel
from smartcity.catalog import (
    DVF_MAP_SAMPLE, SOURCES, coverage, load_points, load_series, snapshot_date,
)
from smartcity.config import zones

CENTER = {"lat": 48.8566, "lon": 2.3522}
ZONE_NAMES = {z["slug"]: z["name"] for z in zones()}
_points_cache: dict[str, pd.DataFrame] = {}


def _points(key: str) -> pd.DataFrame:
    if key not in _points_cache:
        _points_cache[key] = load_points(key)
    return _points_cache[key]


def _map_points(key: str) -> pd.DataFrame:
    pts = _points(key)
    if key == "dvf" and len(pts) > DVF_MAP_SAMPLE:
        pts = pts.sample(DVF_MAP_SAMPLE, random_state=7)
    if SOURCES[key]["metric"]:
        pts = pts.assign(_missing=pts["value"].isna()).sort_values("_missing", kind="stable").drop(columns="_missing")
    return pts.reset_index(drop=True)


class SourceState(rx.State):
    source_key: str = "traffic"
    source_cards: list[dict[str, str]] = []
    meta: dict[str, str] = {}
    feature_chips: list[str] = []
    onto_chips: list[str] = []
    fig_map: go.Figure = go.Figure()
    # bumped on every new map figure: the plot remounts instead of updating in
    # place, so a map still loading its basemap style is never mutated
    # (plotly's maplibre layer throws "Style is not done loading" and the page dies)
    map_rev: int = 0
    fig_zones: go.Figure = go.Figure()
    map_ids: list[str] = []
    n_valued: int = 0
    map_note: str = ""

    sel: dict[str, str] = {}
    has_sel: bool = False
    has_series: bool = False
    fig_s1: go.Figure = go.Figure()
    fig_s2: go.Figure = go.Figure()

    def load_page(self):
        self.source_cards = [
            {"key": k, "name": s["name"], "kind": s["kind"], "count": f"{len(_points(k)):,}"}
            for k, s in SOURCES.items()
        ]
        self.select_source(self.source_key)

    def select_source(self, key: str):
        self.source_key = key
        s = SOURCES[key]
        pts = _points(key)
        cov = coverage(pts)
        if pts["updated"].notna().any():
            last = pd.to_datetime(pts["updated"]).max()
            fresh = last.strftime("%d %b %Y %H:%M") if key != "dvf" else f"sales through {last:%b %Y}"
        else:
            fresh = f"snapshot {snapshot_date(key)}"
        self.meta = {
            "name": s["name"], "kind": s["kind"], "provider": s["provider"], "dataset": s["dataset"],
            "url": s["url"], "licence": s["licence"], "cadence": s["cadence"], "method": s["method"],
            "measures": s["measures"], "records": f"{len(pts):,}",
            "zones": f"{cov['zones_covered']} / {len(ZONE_NAMES)}", "extent": cov["extent"],
            "density": cov["density"], "fresh": fresh,
            "unused": "" if s["feeds_features"] else
                      "Ingested and in the ontology, not yet a valuation feature (candidate: distance to hospital).",
        }
        self.feature_chips = s["feeds_features"]
        self.onto_chips = s["feeds_ontology"]

        mpts = _map_points(key)
        self.map_ids = mpts["id"].tolist()
        self.n_valued = int(mpts["value"].notna().sum()) if s["metric"] else len(mpts)
        self.map_note = (f"Showing a random {len(mpts):,} of {len(pts):,} sales — statistics use all of them."
                         if len(mpts) < len(pts) else f"All {len(pts):,} records shown.")
        self.fig_map = charts.build_source_map(mpts, s["metric"], cov.get("bbox"), CENTER,
                                               big_markers=(key == "air"))
        self.map_rev += 1
        self.fig_zones = charts.build_zone_counts(pts, ZONE_NAMES)
        self.sel, self.has_sel, self.has_series = {}, False, False

    def map_click(self, points: list[dict]):
        if not points or points[0].get("curveNumber", 0) not in (0, 1):
            return
        idx = points[0].get("pointIndex")
        if idx is not None and points[0].get("curveNumber") == 1:
            idx += self.n_valued
        if idx is None or not 0 <= idx < len(self.map_ids):
            return
        self.select_record(self.map_ids[idx])

    def select_record(self, record_id: str):
        key = self.source_key
        mpts = _map_points(key)
        hit = mpts[mpts["id"] == record_id]
        if hit.empty:
            return
        r = hit.iloc[0]
        metric = SOURCES[key]["metric"]
        self.sel = {
            "name": str(r["name"]), "id": record_id,
            "zone": ZONE_NAMES.get(r["zone"], r["zone"]),
            "coords": f"{r['lat']:.5f}, {r['lon']:.5f}",
            "detail": str(r["detail"]),
            "value": "" if not metric or pd.isna(r["value"]) else f"{metric}: {r['value']:,.1f}".replace(",", " "),
            "updated": "" if pd.isna(r["updated"]) else pd.to_datetime(r["updated"]).strftime("%d %b %Y %H:%M"),
        }
        self.has_sel = True
        series = load_series(key, record_id)
        self.has_series = not series.empty
        if key == "traffic" and not series.empty:
            self.fig_s1 = charts.build_series(series, "flow_vph", "Flow — vehicles per hour", "veh/h")
            self.fig_s2 = charts.build_series(series, "occupancy_pct", "Road occupancy", "%")
        elif key == "air" and not series.empty:
            self.fig_s1 = charts.build_series(series, "eaqi", "European AQI", "")
            self.fig_s2 = charts.build_series(series, "pm2_5", "PM2.5", "µg/m³")
        mpts_sel = charts.build_source_map(mpts, metric, coverage(_points(key)).get("bbox"), CENTER,
                                           big_markers=(key == "air"), selected_id=record_id)
        self.fig_map = mpts_sel
        self.map_rev += 1


# ------------------------------------------------------------------------ UI
def source_button(c) -> rx.Component:
    S = SourceState
    active = S.source_key == c["key"]
    return rx.box(
        rx.text(c["name"], size="2", weight="bold", color=INK),
        rx.hstack(
            rx.text(c["kind"], size="1", color=MUTED),
            rx.spacer(),
            rx.text(c["count"], size="1", color=INK_2, weight="medium"),
            width="100%",
        ),
        on_click=S.select_source(c["key"]),
        cursor="pointer", width="100%", padding="10px 12px", border_radius="8px",
        border=rx.cond(active, f"1.5px solid {BLUE}", BORDER),
        background_color=rx.cond(active, "rgba(42,120,214,0.06)", CARD_BG),
        _hover={"background_color": "rgba(42,120,214,0.04)"},
    )


def stat(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(label, size="1", color=MUTED),
        rx.text(value, size="3", weight="bold", color=INK),
        border=BORDER, border_radius="8px", padding="8px 12px", flex="1", min_width="120px",
    )


def chip(text) -> rx.Component:
    return rx.badge(text, variant="soft", color_scheme="blue", size="2", radius="full")


def meta_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="1", color=MUTED, width="90px", flex_shrink="0"),
        rx.text(value, size="2", color=INK),
        align="start", spacing="3", width="100%",
    )


def source_detail() -> rx.Component:
    S = SourceState
    m = S.meta
    return card(
        rx.hstack(
            rx.heading(m["name"], size="5", color=INK),
            rx.badge(m["kind"], variant="outline", color_scheme="gray"),
            align="center", spacing="3", wrap="wrap",
        ),
        rx.text(m["method"], size="2", color=INK_2, margin_top="6px"),
        rx.vstack(
            meta_row("Provider", m["provider"]),
            meta_row("Dataset", rx.code(m["dataset"])),
            meta_row("Measures", m["measures"]),
            meta_row("Licence", m["licence"]),
            meta_row("Cadence", m["cadence"]),
            meta_row("Source", rx.link(m["url"], href=m["url"], is_external=True, size="2")),
            spacing="2", width="100%", margin_top="12px",
        ),
        rx.hstack(
            stat("Records", m["records"]),
            stat("Zones covered", m["zones"]),
            stat("Coverage extent", m["extent"]),
            stat("Density", m["density"]),
            stat("Freshness", m["fresh"]),
            spacing="2", width="100%", wrap="wrap", margin_top="14px",
        ),
        rx.box(
            rx.text("Feeds valuation features", size="1", color=MUTED, margin_bottom="6px"),
            rx.cond(
                S.feature_chips.length() > 0,
                rx.hstack(rx.foreach(S.feature_chips, chip), wrap="wrap", spacing="2"),
                rx.text(m["unused"], size="2", color=INK_2),
            ),
            margin_top="14px",
        ),
        rx.box(
            rx.text("Materialized in the ontology as", size="1", color=MUTED, margin_bottom="6px"),
            rx.hstack(rx.foreach(S.onto_chips, chip), wrap="wrap", spacing="2"),
            margin_top="10px",
        ),
        width="100%",
    )


def record_panel() -> rx.Component:
    S = SourceState
    s = S.sel
    return card(
        rx.text("Selected record", size="2", weight="bold", color=INK, margin_bottom="6px"),
        rx.cond(
            S.has_sel,
            rx.vstack(
                rx.heading(s["name"], size="4", color=INK),
                rx.text(s["detail"], size="2", color=INK_2),
                rx.cond(s["value"] != "", rx.text(s["value"], size="2", weight="medium", color=INK)),
                rx.text("Zone ", s["zone"], " · ", s["coords"], size="1", color=MUTED),
                rx.cond(s["updated"] != "", rx.text("Last reading ", s["updated"], size="1", color=MUTED)),
                rx.text("Ontology id ", rx.code(s["id"]), size="1", color=MUTED),
                rx.cond(
                    S.has_series,
                    rx.box(
                        rx.plotly(data=S.fig_s1, width="100%"),
                        rx.plotly(data=S.fig_s2, width="100%"),
                        width="100%", margin_top="6px",
                    ),
                ),
                spacing="1", align="start", width="100%",
            ),
            rx.text("Click any point on the map to inspect that sensor or record — "
                    "traffic and air-quality sensors show their reading history.",
                    size="2", color=MUTED),
        ),
        flex="1", min_width="320px",
    )


@rx.page(route="/sources", title="CityPulse — Data sources", on_load=SourceState.load_page)
def sources_page() -> rx.Component:
    S = SourceState
    return page(
        navbar(S.load_page),
        panel(
            rx.hstack(
                rx.vstack(rx.foreach(S.source_cards, source_button), spacing="2", width="260px", flex_shrink="0"),
                source_detail(),
                spacing="3", width="100%", align="start",
            ),
            title="Data sources",
            tone="aqua",
            subtitle="every feed behind the ontology and the valuation — provenance, coverage, downstream use",
        ),
        panel(
            rx.text(S.map_note, size="1", color=MUTED, margin_bottom="8px"),
            rx.plotly(data=S.fig_map, width="100%", on_click=S.map_click, key=S.map_rev.to_string()),
            title="Coverage map",
            subtitle="grey frame = spatial extent of the source · click any point to inspect it",
        ),
        panel(
            rx.hstack(
                card(
                    rx.text("Records per zone", size="2", weight="bold", color=INK, margin_bottom="6px"),
                    rx.plotly(data=S.fig_zones, width="100%"),
                    flex="1", min_width="320px",
                ),
                record_panel(),
                spacing="3", width="100%", align="start", wrap="wrap",
            ),
            title="Drill-down",
            tone="orange",
            subtitle="distribution across zones and the selected sensor or record",
        ),
    )
