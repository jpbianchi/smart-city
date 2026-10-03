"""Road-traffic poller — Paris permanent induction-loop counters.

  python -m smartcity.ingest.traffic --hours 3     # recent window (poller)
  python -m smartcity.ingest.traffic --hours 168   # bootstrap a week of history

Source: opendata.paris.fr dataset `comptages-routiers-permanents` (~3,700
road-segment sensors; active ones report hourly flow `q` [veh/h] and
occupancy `k` [%]). The Explore v2.1 *exports* endpoint streams every row
matching a filter, so one call covers a whole window; overlapping windows
are deduplicated on (sensor, hour) in the silver transform.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import requests

from smartcity.ingest.bronze import write_bronze_file

EXPORT_URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    "comptages-routiers-permanents/exports/csv"
)
FIELDS = ["iu_ac", "libelle", "t_1h", "q", "k", "etat_trafic", "geo_point_2d"]
TIMEOUT = 180


def poll_traffic(hours: int = 3) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "select": ",".join(FIELDS),
        "where": f"q is not null and t_1h >= date'{since}'",
        "delimiter": ";",
    }
    resp = requests.get(EXPORT_URL, params=params, timeout=TIMEOUT,
                        headers={"User-Agent": "CityPulse/1.0"})
    resp.raise_for_status()
    n_rows = max(resp.text.count("\n") - 1, 0)
    write_bronze_file("traffic", resp.content, "csv", resp.url,
                      meta={"window_hours": hours, "rows": n_rows})
    return n_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Paris road-traffic counters")
    parser.add_argument("--hours", type=int, default=3, help="lookback window")
    args = parser.parse_args()
    n = poll_traffic(args.hours)
    print(f"traffic: {n:,} readings over last {args.hours}h")


if __name__ == "__main__":
    main()
