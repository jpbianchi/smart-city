"""CityPulse — live smart-city dashboard over the ontology.

Run from the dashboard/ directory:  reflex run
Page 1 (/)          city map: live station telemetry x zone air quality
Page 2 (/ontology)  ontology explorer: schema, zone traversals, entity lookup
"""
from __future__ import annotations

import plotly.graph_objects as go
import reflex as rx

from citypulse import charts
from citypulse.data import eaqi_band, load_snapshot

PAGE_BG = "#f9f9f7"
CARD_BG = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
BORDER = "1px solid rgba(11,11,11,0.10)"
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}


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
    entity_input: str = "aq:montmartre"
    entity_title: str = ""
    entity_rows: list[list] = []
    entity_links: list[str] = []

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

        center = {"lat": 48.8566, "lon": 2.3522}
        self.fig_map = charts.build_city_map(snap["stations"], snap["sensors"], center)
        self.fig_zone_bar = charts.build_zone_bar(snap["zone_agg"])

        m = snap["manifest"].get("counts", {})
        object_types = ["Zone", "BikeStation", "AirQualitySensor", "Observation"]
        self.manifest_rows = [[t, f"{m.get(t, 0):,}"] for t in object_types]
        self.link_rows = [
            ["locatedIn", "BikeStation → Zone", f"{m.get('locatedIn', 0):,}"],
            ["monitors", "AirQualitySensor → Zone", f"{m.get('monitors', 0):,}"],
            ["observedBy", "Observation → entity", f"{m.get('observedBy', 0):,}"],
        ]
        self.zone_names = sorted(snap["zone_agg"]["name"].tolist())
        self.select_zone(self.selected_zone)

    def select_zone(self, name: str):
        self.selected_zone = name
        snap = self._snapshot()
        row = snap["zone_agg"][snap["zone_agg"]["name"] == name]
        if row.empty:
            return
        r = row.iloc[0]
        slug = r["zone"]
        self.zone_summary = (
            f"{int(r['n_stations'])} stations · {int(r['bikes'])} bikes available"
            f" · capacity {int(r['capacity'])}"
        )
        if r.notna().get("eaqi", False):
            label, _ = eaqi_band(r["eaqi"])
            self.zone_air = (
                f"EAQI {r['eaqi']:.0f} ({label}) · PM2.5 {r['pm2_5']:.1f} µg/m³"
                f" · NO₂ {r['no2']:.1f} µg/m³"
            )
        else:
            self.zone_air = "no air-quality reading yet"
        stations = snap["onto"].stations_in_zone(f"zone:{slug}")
        top = stations.sort_values("bikes_available", ascending=False).head(12)
        self.station_rows = [
            [
                s["name"],
                int(s["bikes_available"]) if s.notna()["bikes_available"] else 0,
                int(s["docks_available"]) if s.notna()["docks_available"] else 0,
                int(s["capacity"]) if s.notna()["capacity"] else 0,
            ]
            for _, s in top.iterrows()
        ]
        self.fig_zone_history = charts.build_zone_history(snap["zone_hourly"], slug, name)

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
        title = obj.get("name", self.entity_input)
        self.entity_title = f"{title}  ·  {otype}"
        self.entity_rows = [[k, str(v)] for k, v in obj.items() if k not in ("name",)]
        links: list[str] = []
        oid = self.entity_input.strip()
        for ltype in ("locatedIn", "monitors"):
            out = onto.linked_to(ltype, oid)
            for _, lrow in out.iterrows():
                links.append(f"{ltype} → {lrow['to_id']}")
        n_obs = len(onto.linked_from("observedBy", oid))
        if n_obs:
            links.append(f"observedBy ← {n_obs} observations")
        self.entity_links = links or ["no links"]


# ---------------------------------------------------------------------------- UI
def kpi_tile(label: str, value, sub=None, accent: str | None = None) -> rx.Component:
    children = [
        rx.text(label, size="1", color=MUTED, weight="medium"),
        rx.heading(value, size="7", color=INK),
    ]
    if sub is not None:
        dot = (
            rx.box(width="8px", height="8px", border_radius="50%", background_color=accent)
            if accent is not None
            else rx.fragment()
        )
        children.append(rx.hstack(dot, rx.text(sub, size="1", color=INK_2), align="center", spacing="1"))
    return rx.box(
        rx.vstack(*children, spacing="1", align="start"),
        background_color=CARD_BG, border=BORDER, border_radius="10px", padding="16px", flex="1",
    )


def card(*children, **kwargs) -> rx.Component:
    return rx.box(*children, background_color=CARD_BG, border=BORDER, border_radius="10px", padding="16px", **kwargs)


def navbar() -> rx.Component:
    return rx.hstack(
        rx.heading("CityPulse", size="5", color=INK),
        rx.text("Paris · Vélib' + air quality, live", size="2", color=MUTED),
        rx.spacer(),
        rx.link("Map", href="/", color=INK_2),
        rx.link("Ontology", href="/ontology", color=INK_2),
        rx.button("Refresh", on_click=State.load, size="1", variant="outline"),
        align="center", spacing="4", width="100%", padding_y="12px",
    )


@rx.page(route="/", title="CityPulse — Paris", on_load=State.load)
def index() -> rx.Component:
    return rx.box(
        rx.vstack(
            navbar(),
            rx.hstack(
                kpi_tile("Stations renting", State.stations_online, sub=f"last report " + State.last_report),
                kpi_tile("Bikes available now", State.bikes_available),
                kpi_tile("Docks free now", State.docks_available),
                kpi_tile("Air quality (EAQI)", State.eaqi_value, sub=State.eaqi_label, accent=State.eaqi_color),
                spacing="3", width="100%",
            ),
            card(
                rx.text("Live station fill × zone air quality", size="2", color=INK_2, margin_bottom="8px"),
                rx.plotly(data=State.fig_map, width="100%"),
                width="100%",
            ),
            card(
                rx.text("Bikes available by zone", size="2", color=INK_2, margin_bottom="8px"),
                rx.plotly(data=State.fig_zone_bar, width="100%"),
                width="100%",
            ),
            spacing="3", width="100%", max_width="1200px", margin="0 auto", padding="0 20px 40px",
        ),
        background_color=PAGE_BG, min_height="100vh",
    )


@rx.page(route="/ontology", title="CityPulse — Ontology", on_load=State.load)
def ontology() -> rx.Component:
    return rx.box(
        rx.vstack(
            navbar(),
            rx.hstack(
                card(
                    rx.heading("Object types", size="3", color=INK, margin_bottom="8px"),
                    rx.data_table(data=State.manifest_rows, columns=["object type", "count"]),
                    rx.heading("Link types", size="3", color=INK, margin_top="16px", margin_bottom="8px"),
                    rx.data_table(data=State.link_rows, columns=["link", "signature", "count"]),
                    flex="1",
                ),
                card(
                    rx.heading("Entity lookup", size="3", color=INK, margin_bottom="8px"),
                    rx.hstack(
                        rx.input(
                            value=State.entity_input, on_change=State.set_entity_input,
                            placeholder="station:16107 · aq:montmartre · zone:bercy", width="100%",
                        ),
                        rx.button("Resolve", on_click=State.lookup_entity, size="2"),
                        width="100%",
                    ),
                    rx.text(State.entity_title, size="2", weight="bold", color=INK, margin_top="8px"),
                    rx.foreach(State.entity_links, lambda l: rx.text(l, size="1", color=INK_2)),
                    rx.data_table(data=State.entity_rows, columns=["property", "value"]),
                    flex="1",
                ),
                spacing="3", width="100%", align="start",
            ),
            card(
                rx.hstack(
                    rx.heading("Zone traversal", size="3", color=INK),
                    rx.select(State.zone_names, value=State.selected_zone, on_change=State.select_zone),
                    align="center", spacing="3",
                ),
                rx.text(State.zone_summary, size="2", color=INK, margin_top="6px"),
                rx.text(State.zone_air, size="2", color=INK_2),
                rx.hstack(
                    rx.box(
                        rx.text("Top stations (locatedIn → this zone)", size="1", color=MUTED, margin_bottom="4px"),
                        rx.data_table(data=State.station_rows, columns=["station", "bikes", "docks", "capacity"]),
                        flex="1",
                    ),
                    rx.box(rx.plotly(data=State.fig_zone_history, width="100%"), flex="1"),
                    spacing="3", width="100%", align="start", margin_top="10px",
                ),
                width="100%",
            ),
            spacing="3", width="100%", max_width="1200px", margin="0 auto", padding="0 20px 40px",
        ),
        background_color=PAGE_BG, min_height="100vh",
    )


app = rx.App(
    style={"font_family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "background": PAGE_BG},
    stylesheets=["/styles.css"],
)
