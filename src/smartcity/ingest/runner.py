"""Ingestion runner.

  python -m smartcity.ingest.runner --once        # one poll of every feed
  python -m smartcity.ingest.runner --loop 60     # poll every 60s until Ctrl-C

Station information (the slowly-changing dimension) is refreshed every 10th
cycle; status telemetry and air quality every cycle.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from smartcity.ingest.air_quality import poll_air_quality
from smartcity.ingest.gbfs import poll_station_information, poll_station_status
from smartcity.ingest.traffic import poll_traffic


def poll_all(cycle: int = 0) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if cycle % 10 == 0:
        n = poll_station_information()
        print(f"[{ts}] gbfs_station_information: {n} stations")
    n = poll_station_status()
    print(f"[{ts}] gbfs_station_status: {n} stations")
    n = poll_air_quality()
    print(f"[{ts}] air_quality: {n} zone sensors")
    if cycle % 30 == 0:  # the traffic feed only refreshes hourly
        n = poll_traffic(hours=3)
        print(f"[{ts}] traffic: {n} readings")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll real-time city feeds into the bronze zone")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="poll each feed once and exit")
    group.add_argument("--loop", type=int, metavar="SECONDS", help="poll continuously at this interval")
    args = parser.parse_args()

    if args.once:
        poll_all()
        return

    cycle = 0
    while True:
        try:
            poll_all(cycle)
        except Exception as exc:  # a failed poll must not kill the collector
            print(f"[warn] poll failed: {exc}")
        cycle += 1
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
