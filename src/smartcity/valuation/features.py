"""Feature definitions and assembly for property valuation.

The feature contract lives HERE, not inside any model: every feature is
derived from the ontology/gold layer (graph traversals and geospatial
aggregates), and every model consumes the same frame. Swapping the ML
algorithm never touches this file; adding a data source extends it.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from smartcity.config import GOLD_DIR, nearest_zone

TARGET = "price_m2"
NUMERIC_FEATURES = [
    "surface_m2",
    "rooms",
    "dist_subway_m",
    "dist_train_m",
    "dist_school_m",
    "dist_park_m",
    "n_schools_500m",
    "n_parks_500m",
    "n_supermarkets_500m",
    "zone_traffic_occupancy",
    "zone_eaqi",
    "month_index",
]
CATEGORICAL_FEATURES = ["zone", "property_type"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# amenity kind -> column prefix used in the gold feature matrix
NEAREST_KINDS = {"subway_station": "subway", "train_station": "train",
                 "school": "school", "park": "park"}
COUNT_KINDS = {"school": "n_schools_500m", "park": "n_parks_500m",
               "supermarket": "n_supermarkets_500m"}
EARTH_KM = 6371.0


def load_training_frame() -> pd.DataFrame:
    """The gold feature matrix, with rows a model can safely learn from."""
    df = pd.read_parquet(GOLD_DIR / "transaction_features")
    df = df.dropna(subset=[TARGET, "surface_m2", "zone", "property_type"])
    df["rooms"] = df["rooms"].fillna(0)
    for col in NUMERIC_FEATURES:
        if df[col].isna().any():
            df[col] = df[col].fillna(df[col].median())
    return df


@lru_cache(maxsize=1)
def latest_month_index() -> int:
    """Most recent month covered by transaction data.

    Appraisals are stated "as of" this month: a linear time trend must not be
    extrapolated past the data it was fitted on.
    """
    df = pd.read_parquet(GOLD_DIR / "transaction_features", columns=["month_index"])
    return int(df["month_index"].max())


@lru_cache(maxsize=1)
def _amenity_index():
    from sklearn.neighbors import BallTree

    amen = pd.read_parquet(GOLD_DIR / "amenities")
    trees = {}
    for kind in set(NEAREST_KINDS) | set(COUNT_KINDS):
        sub = amen[amen["kind"] == kind].reset_index(drop=True)
        if not sub.empty:
            trees[kind] = (BallTree(np.radians(sub[["lat", "lon"]].to_numpy()), metric="haversine"), sub)
    return trees


@lru_cache(maxsize=1)
def _zone_ambient() -> tuple[dict, dict]:
    traffic = pd.read_parquet(GOLD_DIR / "zone_traffic_hourly")
    zh = pd.read_parquet(GOLD_DIR / "zone_hourly")
    return (traffic.groupby("zone")["avg_occupancy_pct"].mean().round(2).to_dict(),
            zh.groupby("zone")["eaqi"].mean().round(1).to_dict())


def build_query_features(lat: float, lon: float, surface_m2: float, rooms: int,
                         property_type: str) -> dict:
    """Assemble the same features for an arbitrary location at appraisal time.

    Mirrors the pipeline's geospatial derivations (nearest zone, nearest
    metro/train/school/park, 500m amenity counts, zone ambient indicators).
    """
    zone = nearest_zone(lat, lon)
    point = np.radians([[lat, lon]])
    feats: dict = {"lat": lat, "lon": lon, "zone": zone, "property_type": property_type,
                   "surface_m2": float(surface_m2), "rooms": int(rooms)}

    for kind, (tree, sub) in _amenity_index().items():
        if kind in NEAREST_KINDS:
            short = NEAREST_KINDS[kind]
            dist, idx = tree.query(point, k=1)
            row = sub.iloc[int(idx[0, 0])]
            feats[f"dist_{short}_m"] = round(float(dist[0, 0]) * EARTH_KM * 1000, 0)
            feats[f"{short}_name"] = row["name"] or None
        if kind in COUNT_KINDS:
            feats[COUNT_KINDS[kind]] = int(tree.query_radius(point, r=0.5 / EARTH_KM, count_only=True)[0])

    traffic, eaqi = _zone_ambient()
    feats["zone_traffic_occupancy"] = traffic.get(zone)
    feats["zone_eaqi"] = eaqi.get(zone)
    feats["month_index"] = latest_month_index()
    return feats
