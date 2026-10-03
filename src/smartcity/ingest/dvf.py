"""DVF batch ingest — every geolocated property transaction in Paris.

  python -m smartcity.ingest.dvf [--years 2020 2021 ...]

Source: Etalab "DVF géolocalisé" (files.data.gouv.fr/geo-dvf), one csv.gz per
year for département 75. Files are landed verbatim in bronze (append-only);
parsing/cleaning happens in the PySpark silver transform.
"""
from __future__ import annotations

import argparse

import requests

from smartcity.config import BRONZE_DIR
from smartcity.ingest.bronze import write_bronze_file

BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/departements/75.csv.gz"
DEFAULT_YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
TIMEOUT = 120


def ingest_year(year: int) -> int | None:
    url = BASE.format(year=year)
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "CityPulse/1.0"})
    if resp.status_code == 404:
        print(f"[skip] DVF {year}: not published")
        return None
    resp.raise_for_status()
    path = write_bronze_file("dvf", resp.content, "csv.gz", url, meta={"year": year})
    print(f"DVF {year}: {len(resp.content):,} bytes -> {path.relative_to(BRONZE_DIR.parent)}")
    return len(resp.content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download DVF transaction files for Paris")
    parser.add_argument("--years", nargs="*", type=int, default=DEFAULT_YEARS)
    args = parser.parse_args()
    for year in args.years:
        try:
            ingest_year(year)
        except Exception as exc:
            print(f"[warn] DVF {year} failed: {exc}")


if __name__ == "__main__":
    main()
