"""GBFS poller — real-time bike-share telemetry (Vélib' Métropole, Paris).

GBFS is the open standard used by 1500+ shared-mobility systems; station_status
is genuine IoT telemetry (dock sensors reporting bikes/docks every ~60s).
"""
from __future__ import annotations

import requests

from smartcity.config import load_city_config
from smartcity.ingest.bronze import write_bronze

TIMEOUT = 20


def poll_station_information() -> int:
    url = load_city_config()["feeds"]["gbfs"]["station_information"]
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    write_bronze("gbfs_station_information", payload, url)
    return len(payload["data"]["stations"])


def poll_station_status() -> int:
    url = load_city_config()["feeds"]["gbfs"]["station_status"]
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    write_bronze("gbfs_station_status", payload, url)
    return len(payload["data"]["stations"])
