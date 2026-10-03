"""Air-quality poller — one virtual sensor per city zone (Open-Meteo, no key).

All zone centers are fetched in a single batched request; the response is a
list with one entry per zone, which we tag with the zone slug before landing.
"""
from __future__ import annotations

import requests

from smartcity.config import load_city_config, zones
from smartcity.ingest.bronze import write_bronze

TIMEOUT = 20


def poll_air_quality() -> int:
    cfg = load_city_config()["feeds"]["air_quality"]
    zs = zones()
    params = {
        "latitude": ",".join(str(z["lat"]) for z in zs),
        "longitude": ",".join(str(z["lon"]) for z in zs),
        "current": ",".join(cfg["variables"]),
    }
    resp = requests.get(cfg["base_url"], params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    results = resp.json()
    if isinstance(results, dict):  # single-location responses are not wrapped in a list
        results = [results]
    for zone, entry in zip(zs, results):
        entry["zone"] = zone["slug"]
    write_bronze("air_quality", results, resp.url)
    return len(results)
