"""Data access for the dashboard: reads gold tables + the ontology."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pandas as pd  # noqa: E402

from smartcity.config import GOLD_DIR, zones  # noqa: E402
from smartcity.ontology.query import Ontology  # noqa: E402

# European AQI bands -> (label, status role)
EAQI_BANDS = [
    (20, "Good", "good"),
    (40, "Fair", "good"),
    (60, "Moderate", "warning"),
    (80, "Poor", "serious"),
    (10_000, "Very poor", "critical"),
]


def eaqi_band(value: float | None) -> tuple[str, str]:
    if value is None or pd.isna(value):
        return ("n/a", "warning")
    for ceiling, label, role in EAQI_BANDS:
        if value <= ceiling:
            return (label, role)
    return ("Very poor", "critical")


def load_snapshot() -> dict:
    """Everything the dashboard needs, as plain python structures + DFs."""
    onto = Ontology.load()
    stations = onto.objects["BikeStation"].reset_index(drop=True)
    sensors = onto.objects["AirQualitySensor"].reset_index(drop=True)
    zone_meta = {z["slug"]: z for z in zones()}

    zone_hourly = pd.read_parquet(GOLD_DIR / "zone_hourly")

    reported = pd.to_datetime(stations["reported_at"])
    avg_eaqi = float(sensors["eaqi"].mean()) if not sensors.empty else None
    kpis = {
        "stations_online": int(stations["is_renting"].fillna(False).sum()),
        "stations_total": len(stations),
        "bikes_available": int(stations["bikes_available"].fillna(0).sum()),
        "docks_available": int(stations["docks_available"].fillna(0).sum()),
        "avg_eaqi": round(avg_eaqi, 1) if avg_eaqi is not None else None,
        "last_report": reported.max().strftime("%H:%M UTC") if reported.notna().any() else "–",
    }

    # per-zone aggregates for the bar chart / explorer
    zone_agg = (
        stations.groupby("zone")
        .agg(
            n_stations=("object_id", "count"),
            bikes=("bikes_available", "sum"),
            capacity=("capacity", "sum"),
        )
        .reset_index()
    )
    zone_agg["name"] = zone_agg["zone"].map(lambda s: zone_meta[s]["name"])
    zone_agg = zone_agg.merge(
        sensors[["zone", "eaqi", "pm2_5", "no2"]], on="zone", how="left"
    ).sort_values("bikes", ascending=True)

    return {
        "onto": onto,
        "stations": stations,
        "sensors": sensors,
        "zone_agg": zone_agg,
        "zone_hourly": zone_hourly,
        "zone_meta": zone_meta,
        "kpis": kpis,
        "manifest": onto.manifest,
    }


def load_market() -> dict:
    """Zone-level market view for the valuation page."""
    market = pd.read_parquet(GOLD_DIR / "zone_market")
    zone_meta = {z["slug"]: z for z in zones()}
    recent = market[(market["year"] >= market["year"].max() - 1)
                    & (market["property_type"] == "Appartement")]
    latest = (
        recent.groupby("zone")
        .agg(median_price_m2=("median_price_m2", "mean"), n_sales=("n_sales", "sum"))
        .reset_index()
    )
    latest["name"] = latest["zone"].map(lambda s: zone_meta[s]["name"])
    latest["lat"] = latest["zone"].map(lambda s: zone_meta[s]["lat"])
    latest["lon"] = latest["zone"].map(lambda s: zone_meta[s]["lon"])
    return {"market": market, "latest": latest, "zone_meta": zone_meta}
