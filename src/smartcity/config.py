"""Project configuration: paths, city config, geo helpers."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "city.yml"
DATA_DIR = PROJECT_ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
ONTOLOGY_DIR = DATA_DIR / "ontology"


@lru_cache(maxsize=1)
def load_city_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def zones() -> list[dict]:
    return load_city_config()["zones"]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_zone(lat: float, lon: float) -> str:
    """Assign a point to its nearest zone center. Returns the zone slug."""
    best_slug, best_d = None, float("inf")
    for z in zones():
        d = haversine_km(lat, lon, z["lat"], z["lon"])
        if d < best_d:
            best_slug, best_d = z["slug"], d
    return best_slug
