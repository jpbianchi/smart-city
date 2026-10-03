"""Amenity batch ingest — value-driving POIs from OpenStreetMap (Overpass).

  python -m smartcity.ingest.amenities

One query per amenity kind over greater Paris; ways/relations come back with
a computed center, so everything lands as point features.
"""
from __future__ import annotations

import time

import requests

from smartcity.ingest.bronze import write_bronze

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
BBOX = "48.80,2.22,48.91,2.42"  # greater Paris, matches the Vélib' footprint
TIMEOUT = 180
HEADERS = {"User-Agent": "CityPulse/1.0 (smart-city portfolio project)"}

QUERIES = {
    "subway_station": f'node["station"="subway"]({BBOX});',
    "school": f'nwr["amenity"="school"]({BBOX});',
    "park": f'nwr["leisure"="park"]({BBOX});',
    "supermarket": f'nwr["shop"="supermarket"]({BBOX});',
    "hospital": f'nwr["amenity"="hospital"]({BBOX});',
}


def fetch_kind(kind: str, clause: str) -> int:
    query = f"[out:json][timeout:120];({clause});out center tags;"
    last_exc: Exception | None = None
    for attempt, url in enumerate(OVERPASS_URLS * 2):
        try:
            resp = requests.post(url, data={"data": query}, timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            break
        except Exception as exc:  # 504s are routine on public Overpass instances
            last_exc = exc
            time.sleep(5 * (attempt + 1))
    else:
        raise last_exc
    elements = resp.json().get("elements", [])
    features = []
    for el in elements:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        features.append({
            "osm_id": f"{el['type']}/{el['id']}",
            "kind": kind,
            "name": el.get("tags", {}).get("name"),
            "lat": lat,
            "lon": lon,
        })
    write_bronze("amenities", {"kind": kind, "features": features}, url)
    return len(features)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch value-driving POIs from OpenStreetMap")
    parser.add_argument("--kinds", nargs="*", default=list(QUERIES), choices=list(QUERIES))
    args = parser.parse_args()
    for kind in args.kinds:
        n = fetch_kind(kind, QUERIES[kind])
        print(f"amenities/{kind}: {n} features")
        time.sleep(2)  # be polite to the public Overpass instances


if __name__ == "__main__":
    main()
