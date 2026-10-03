"""Feature definitions and assembly for property valuation.

The feature contract lives HERE, not inside any model: every feature is
derived from the ontology/gold layer (graph traversals and geospatial
aggregates), and every model consumes the same frame. Swapping the ML
algorithm never touches this file; adding a data source extends it.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd

from smartcity.config import GOLD_DIR, haversine_km, nearest_zone

TARGET = "price_m2"
NUMERIC_FEATURES = [
    "surface_m2",
    "rooms",
    "dist_subway_m",
    "n_schools_500m",
    "n_parks_500m",
    "n_supermarkets_500m",
    "zone_traffic_occupancy",
    "zone_eaqi",
    "month_index",
]
CATEGORICAL_FEATURES = ["zone", "property_type"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def load_training_frame() -> pd.DataFrame:
    """The gold feature matrix, with rows a model can safely learn from."""
    df = pd.read_parquet(GOLD_DIR / "transaction_features")
    df = df.dropna(subset=[TARGET, "surface_m2", "zone", "property_type"])
    df["rooms"] = df["rooms"].fillna(0)
    df["dist_subway_m"] = df["dist_subway_m"].fillna(df["dist_subway_m"].median())
    for col in ("zone_traffic_occupancy", "zone_eaqi"):
        df[col] = df[col].fillna(df[col].median())
    return df


def build_query_features(lat: float, lon: float, surface_m2: float, rooms: int,
                         property_type: str) -> dict:
    """Assemble the same features for an arbitrary location at appraisal time.

    Mirrors the pipeline's geospatial derivations (nearest zone, nearest
    subway, 500m amenity counts, zone ambient indicators) in pandas, against
    the gold tables.
    """
    zone = nearest_zone(lat, lon)

    amen = pd.read_parquet(GOLD_DIR / "amenities")
    d_km = amen.apply(lambda a: haversine_km(lat, lon, a["lat"], a["lon"]), axis=1)
    amen = amen.assign(d_km=d_km)
    subway = amen[amen["kind"] == "subway_station"]
    nearest_subway = subway.loc[subway["d_km"].idxmin()] if not subway.empty else None
    within = amen[amen["d_km"] <= 0.5]

    traffic = pd.read_parquet(GOLD_DIR / "zone_traffic_hourly")
    ztraffic = traffic[traffic["zone"] == zone]["avg_occupancy_pct"].mean()
    zh = pd.read_parquet(GOLD_DIR / "zone_hourly")
    zeaqi = zh[zh["zone"] == zone]["eaqi"].mean()

    now = datetime.now(timezone.utc)
    month_index = (now.year - 2021) * 12 + (now.month - 1)

    return {
        "lat": lat,
        "lon": lon,
        "zone": zone,
        "property_type": property_type,
        "surface_m2": float(surface_m2),
        "rooms": int(rooms),
        "dist_subway_m": round(float(nearest_subway["d_km"]) * 1000, 0) if nearest_subway is not None else None,
        "nearest_subway": None if nearest_subway is None else (nearest_subway["name"] or nearest_subway["osm_id"]),
        "n_schools_500m": int((within["kind"] == "school").sum()),
        "n_parks_500m": int((within["kind"] == "park").sum()),
        "n_supermarkets_500m": int((within["kind"] == "supermarket").sum()),
        "zone_traffic_occupancy": None if math.isnan(ztraffic) else round(float(ztraffic), 2),
        "zone_eaqi": None if pd.isna(zeaqi) else round(float(zeaqi), 1),
        "month_index": month_index,
    }
