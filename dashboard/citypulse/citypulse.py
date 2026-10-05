"""CityPulse — live smart-city dashboard over the ontology.

Run from the dashboard/ directory:  reflex run
Page /doc        about the project: smart-city and tokenization story, page guide
Page /           properties: valued inventory, map, sortable table, detail popup
Page /sources    data-source catalog: provenance, coverage, per-sensor drill-down
Page /ontology   ontology explorer: schema, zone traversals, entity lookup
Page /appraise   appraise any property from ontology-derived features
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import reflex as rx
from granian.utils.proxies import wrap_asgi_with_proxy_headers

from citypulse import charts
from citypulse.data import eaqi_band, load_market, load_snapshot
from smartcity.config import GOLD_DIR, zones
from citypulse.ui import BORDER, CARD_BG, INK, INK_2, MUTED, PAGE_BG, PAGE_GRADIENT, STATUS, card, kpi_tile, navbar, panel



class State(rx.State):
    # KPIs
    stations_online: str = "–"
    bikes_available: str = "–"
    docks_available: str = "–"
    eaqi_value: str = "–"
    eaqi_label: str = ""
    eaqi_color: str = STATUS["warning"]
    last_report: str = "–"

    # figures
    fig_map: go.Figure = go.Figure()
    fig_zone_bar: go.Figure = go.Figure()
    fig_zone_history: go.Figure = go.Figure()

    # ontology page
    manifest_rows: list[list] = []
    link_rows: list[list] = []
    zone_names: list[str] = []
    selected_zone: str = "Montmartre"
    zone_summary: str = ""
    zone_air: str = ""
    station_rows: list[list] = []
    entity_input: str = "zone:montmartre"
    entity_title: str = ""
    entity_rows: list[list] = []
    entity_links: list[str] = []

    # valuation page
    fig_market: go.Figure = go.Figure()
    fig_market_trend: go.Figure = go.Figure()
    val_zone: str = "Montmartre"
    val_type: str = "Appartement"
    val_surface: str = "62"
    val_rooms: str = "3"
    val_estimate: str = ""
    val_price_m2: str = ""
    val_model_info: str = ""
    val_features: str = ""
    val_breakdown: list[list] = []
    val_error: str = ""

    def _snapshot(self):
        return load_snapshot()

    def load(self):
        snap = self._snapshot()
        k = snap["kpis"]
        self.stations_online = f"{k['stations_online']:,} / {k['stations_total']:,}"
        self.bikes_available = f"{k['bikes_available']:,}"
        self.docks_available = f"{k['docks_available']:,}"
        label, role = eaqi_band(k["avg_eaqi"])
        self.eaqi_value = "–" if k["avg_eaqi"] is None else f"{k['avg_eaqi']:.0f}"
        self.eaqi_label = label
        self.eaqi_color = STATUS[role]
        self.last_report = k["last_report"]


        m = snap["manifest"].get("counts", {})
        object_types = ["Zone", "PropertyTransaction", "Amenity", "TrafficSensor",
                        "BikeStation", "AirQualitySensor", "Observation",
                        "Asset", "PropertyToken", "Appraisal",
                        "Party", "Holding", "ShareOffer", "ShareTrade"]
        self.manifest_rows = [[t, f"{m[t]:,}"] for t in object_types if t in m]
        self.link_rows = [
            ["locatedIn", "BikeStation → Zone", f"{m.get('locatedIn', 0):,}"],
            ["monitors", "AirQualitySensor → Zone", f"{m.get('monitors', 0):,}"],
            ["observedBy", "Observation → entity", f"{m.get('observedBy', 0):,}"],
            ["transactionIn", "PropertyTransaction → Zone", f"{m.get('transactionIn', 0):,}"],
            ["nearestStation", "PropertyTransaction → Amenity", f"{m.get('nearestStation', 0):,}"],
            ["amenityIn", "Amenity → Zone", f"{m.get('amenityIn', 0):,}"],
            ["monitorsRoad", "TrafficSensor → Zone", f"{m.get('monitorsRoad', 0):,}"],
        ] + [
            [name, sig, f"{m[name]:,}"]
            for name, sig in (
                ("tokenizes", "PropertyToken → Asset"),
                ("deedOf", "Asset → PropertyTransaction"),
                ("valuedBy", "PropertyToken → Appraisal"),
                ("holds", "Party → Holding"),
                ("holdingOf", "Holding → PropertyToken"),
                ("offers", "Party → ShareOffer"),
                ("offerFor", "ShareOffer → PropertyToken"),
                ("buyer", "ShareTrade → Party"),
                ("seller", "ShareTrade → Party"),
                ("fills", "ShareTrade → ShareOffer"),
                ("tradeOf", "ShareTrade → PropertyToken"),
            )
            if name in m
        ]
        self.zone_names = sorted(z["name"] for z in zones())
        self.select_zone(self.selected_zone)

    def select_zone(self, name: str):
        self.selected_zone = name
        zone = next((z for z in zones() if z["name"] == name), None)
        if zone is None:
            return
        slug, zid = zone["slug"], f"zone:{zone['slug']}"
        onto = self._snapshot()["onto"]
        ctx = onto.zone_context(zid)
        sales = onto.transactions_in_zone(zid, since_year=2025)
        apts = sales[sales["property_type"] == "Appartement"]
        amen = onto.objects["Amenity"]
        amen = amen.loc[amen.index.intersection(onto.linked_from("amenityIn", zid)["from_id"])]
        kinds = amen["kind"].value_counts()
        self.zone_summary = (
            f"{len(sales):,} sales in 2025 · median "
            f"{(apts['price_m2'].median() if not apts.empty else float('nan')):,.0f} €/m² (apartments) · "
            f"{ctx['n_road_sensors']} road-traffic sensors · "
            f"{kinds.get('subway_station', 0)} metro · {kinds.get('train_station', 0)} train/RER · "
            f"{kinds.get('school', 0)} schools · {kinds.get('park', 0)} parks"
        ).replace(",", " ")
        sensor = ctx["sensor"]
        if sensor and sensor.get("eaqi") is not None:
            label, _ = eaqi_band(sensor["eaqi"])
            self.zone_air = (f"Air quality: EAQI {sensor['eaqi']:.0f} ({label}) · PM2.5 "
                             f"{sensor['pm2_5']:.1f} µg/m³ · NO₂ {sensor['no2']:.1f} µg/m³")
        else:
            self.zone_air = "Air quality: no reading yet"
        recent = sales.sort_values("sold_on", ascending=False).head(12)
        self.station_rows = [
            [s["address"], pd.to_datetime(s["sold_on"]).strftime("%d %b %Y"),
             f"{s['surface_m2']:.0f} m²", f"{s['price_eur']:,.0f} €".replace(",", " "),
             f"{s['price_m2']:,.0f}".replace(",", " ")]
            for _, s in recent.iterrows()
        ]
        traffic = pd.read_parquet(GOLD_DIR / "zone_traffic_hourly")
        traffic = traffic[traffic["zone"] == slug].rename(columns={"hour": "observed_at"}).sort_values("observed_at")
        self.fig_zone_history = charts.build_series(
            traffic, "avg_flow_vph", f"Road traffic — avg vehicles/hour per sensor, {name}", "veh/h")

    def load_valuation(self):
        self.load()
        mk = load_market()
        center = {"lat": 48.8566, "lon": 2.3522}
        self.fig_market = charts.build_market_map(mk["latest"], center)
        self.select_val_zone(self.val_zone)

    def select_val_zone(self, name: str):
        self.val_zone = name
        mk = load_market()
        slug = next((s for s, z in mk["zone_meta"].items() if z["name"] == name), None)
        if slug:
            self.fig_market_trend = charts.build_market_trend(
                mk["market"], slug, name, self.val_type
            )

    def set_val_type(self, value: str):
        self.val_type = value
        self.select_val_zone(self.val_zone)

    def set_val_surface(self, value: str):
        self.val_surface = value

    def set_val_rooms(self, value: str):
        self.val_rooms = value

    def run_appraisal(self):
        from smartcity.valuation.appraise import appraise

        self.val_error = ""
        try:
            surface = float(self.val_surface)
            rooms = int(self.val_rooms)
        except ValueError:
            self.val_error = "surface and rooms must be numbers"
            return
        mk = load_market()
        zone = next((z for z in mk["zone_meta"].values() if z["name"] == self.val_zone), None)
        if zone is None:
            self.val_error = f"unknown zone {self.val_zone}"
            return
        try:
            doc = appraise(zone["lat"], zone["lon"], surface, rooms, self.val_type, save=True)
        except Exception as exc:
            self.val_error = f"appraisal failed: {exc}"
            return
        est = doc["estimate"]
        f = doc["features"]
        m = doc["model"]
        self.val_estimate = f"{est['total_eur']:,.0f} €"
        self.val_price_m2 = f"{est['price_m2_eur']:,.0f} €/m²"
        self.val_model_info = (
            f"model {m['name']} · median error {m['metrics']['median_ape_pct']}% "
            f"on {m['metrics']['n_test']:,} held-out {m['metrics']['test_year']} sales"
            f" · doc {doc['sha256'][:12]}…"
        )
        self.val_features = (
            f"{f['zone']} · metro {f.get('subway_name') or '–'} at {f['dist_subway_m']:.0f}m · "
            f"{f['n_schools_500m']} schools / {f['n_parks_500m']} parks / "
            f"{f['n_supermarkets_500m']} shops within 500m · "
            f"traffic occ. {f['zone_traffic_occupancy']}% · EAQI {f['zone_eaqi']}"
        )
        self.val_breakdown = [
            [b["driver"], b["detail"], "" if b.get("effect_pct") is None else f"{b['effect_pct']:+.1f}%"]
            for b in doc["breakdown"][:9]
        ]

    def set_entity_input(self, value: str):
        self.entity_input = value

    def lookup_entity(self):
        snap = self._snapshot()
        onto = snap["onto"]
        obj = onto.get(self.entity_input.strip())
        if obj is None:
            self.entity_title = f"object '{self.entity_input}' not found"
            self.entity_rows, self.entity_links = [], []
            return
        otype = obj.pop("__type__")
        title = obj.get("name") or obj.get("label") or obj.get("address") or self.entity_input
        self.entity_title = f"{title}  ·  {otype}"
        self.entity_rows = [[k, str(v)] for k, v in obj.items() if k not in ("name",)]
        links: list[str] = []
        oid = self.entity_input.strip()
        for ltype in onto.links:
            out = onto.linked_to(ltype, oid)
            for _, lrow in out.head(5).iterrows():
                extra = f" ({lrow['dist_m']:.0f} m)" if "dist_m" in lrow and pd.notna(lrow["dist_m"]) else ""
                links.append(f"{ltype} → {lrow['to_id']}{extra}")
            n_in = len(onto.linked_from(ltype, oid))
            if n_in:
                links.append(f"{ltype} ← {n_in:,} objects")
        self.entity_links = links or ["no links"]


# ---------------------------------------------------------------------------- UI
@rx.page(route="/ontology", title="CityPulse — Ontology", on_load=State.load)
def ontology() -> rx.Component:
    return rx.box(
        rx.vstack(
            navbar(State.load),
            rx.hstack(
                panel(
                    rx.heading("Object types", size="3", color=INK, margin_bottom="8px"),
                    rx.data_table(data=State.manifest_rows, columns=["object type", "count"]),
                    rx.heading("Link types", size="3", color=INK, margin_top="16px", margin_bottom="8px"),
                    rx.data_table(data=State.link_rows, columns=["link", "signature", "count"]),
                    flex="1", tone="orange",
                ),
                panel(
                    rx.heading("Entity lookup", size="3", color=INK, margin_bottom="8px"),
                    rx.hstack(
                        rx.input(
                            value=State.entity_input, on_change=State.set_entity_input,
                            placeholder="zone:montmartre · aq:bercy · traffic:6998 · tx:… · poi:node/…", width="100%",
                        ),
                        rx.button("Resolve", on_click=State.lookup_entity, size="2"),
                        width="100%",
                    ),
                    rx.text(State.entity_title, size="2", weight="bold", color=INK, margin_top="8px"),
                    rx.foreach(State.entity_links, lambda l: rx.text(l, size="1", color=INK_2)),
                    rx.data_table(data=State.entity_rows, columns=["property", "value"]),
                    flex="1", tone="violet",
                ),
                spacing="3", width="100%", align="start",
            ),
            panel(
                rx.hstack(
                    rx.heading("Zone traversal", size="3", color=INK),
                    rx.text("one zone → its sales, sensors and amenities, by following links", size="1", color=MUTED),
                    rx.select(State.zone_names, value=State.selected_zone, on_change=State.select_zone),
                    align="center", spacing="3",
                ),
                rx.text(State.zone_summary, size="2", color=INK, margin_top="6px"),
                rx.text(State.zone_air, size="2", color=INK_2),
                rx.hstack(
                    rx.box(
                        rx.text("Latest sales (transactionIn → this zone)", size="1", color=MUTED, margin_bottom="4px"),
                        rx.data_table(data=State.station_rows, columns=["address", "sold", "size", "price", "€/m²"]),
                        flex="1",
                    ),
                    rx.box(rx.plotly(data=State.fig_zone_history, width="100%"), flex="1"),
                    spacing="3", width="100%", align="start", margin_top="10px",
                ),
                width="100%", tone="aqua",
            ),
            spacing="3", width="100%", max_width="1200px", margin="0 auto", padding="0 20px 40px",
        ),
        background=PAGE_GRADIENT, background_attachment="fixed", min_height="100vh",
    )


@rx.page(route="/appraise", title="CityPulse — Appraise", on_load=State.load_valuation)
def appraise_page() -> rx.Component:
    return rx.box(
        rx.vstack(
            navbar(State.load),
            rx.hstack(
                panel(
                    rx.heading("Appraise a property", size="3", color=INK, margin_bottom="4px"),
                    rx.text(
                        "Every input below becomes a walk in the city ontology: "
                        "zone market comparables, distance to the nearest metro, "
                        "amenities within 500m, road-traffic and air-quality burden.",
                        size="1", color=MUTED,
                    ),
                    rx.hstack(
                        rx.select(State.zone_names, value=State.val_zone, on_change=State.select_val_zone),
                        rx.select(["Appartement", "Maison"], value=State.val_type, on_change=State.set_val_type),
                        spacing="2", margin_top="10px",
                    ),
                    rx.hstack(
                        rx.input(value=State.val_surface, on_change=State.set_val_surface, width="110px"),
                        rx.text("m²", size="1", color=MUTED),
                        rx.input(value=State.val_rooms, on_change=State.set_val_rooms, width="80px"),
                        rx.text("rooms", size="1", color=MUTED),
                        rx.button("Appraise", on_click=State.run_appraisal, size="2"),
                        align="center", spacing="2", margin_top="8px",
                    ),
                    rx.cond(
                        State.val_error != "",
                        rx.text(State.val_error, size="1", color="#d03b3b", margin_top="6px"),
                    ),
                    rx.cond(
                        State.val_estimate != "",
                        rx.vstack(
                            rx.heading(State.val_estimate, size="8", color=INK, margin_top="10px"),
                            rx.text(State.val_price_m2, size="3", color=INK_2),
                            rx.text(State.val_features, size="1", color=INK_2),
                            rx.text(State.val_model_info, size="1", color=MUTED),
                            rx.text("Value drivers (vs market median)", size="1", color=MUTED, margin_top="8px"),
                            rx.data_table(data=State.val_breakdown, columns=["driver", "detail", "effect"]),
                            spacing="1", align="start",
                        ),
                    ),
                    flex="1", tone="magenta",
                ),
                panel(
                    rx.text("Median €/m² by zone — apartments, last 2 years", size="2", color=INK_2, margin_bottom="8px"),
                    rx.plotly(data=State.fig_market, width="100%"),
                    rx.plotly(data=State.fig_market_trend, width="100%"),
                    flex="1",
                ),
                spacing="3", width="100%", align="start",
            ),
            spacing="3", width="100%", max_width="1200px", margin="0 auto", padding="0 20px 40px",
        ),
        background=PAGE_GRADIENT, background_attachment="fixed", min_height="100vh",
    )


from citypulse import doc_page, properties, sources_page, tokens  # noqa: E402,F401  (register pages)

app = rx.App(
    style={"font_family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "background": PAGE_BG},
    stylesheets=["/styles.css"],
    # Behind Tailscale Funnel the app sees plain http from 127.0.0.1; trust its
    # X-Forwarded-Proto so redirects (e.g. /doc -> /doc/) keep the https scheme.
    api_transformer=wrap_asgi_with_proxy_headers,
)
