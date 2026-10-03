"""Hydrate the ontology from gold datasets.

  python -m smartcity.ontology.build

Reads schema.yml (the declared model) and the gold parquet tables, and
materializes object and link tables under data/ontology/:

  objects/zone.parquet, bike_station.parquet, air_quality_sensor.parquet,
          observation.parquet
  links/located_in.parquet, monitors.parquet, observed_by.parquet
  manifest.json  (counts + build time, displayed by the dashboard)

The point: the graph is DERIVED from pipelines, never hand-edited — re-run
ingestion + pipeline + build and the ontology updates itself.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from smartcity.config import GOLD_DIR, ONTOLOGY_DIR, zones

SCHEMA_PATH = Path(__file__).parent / "schema.yml"
OBSERVATION_WINDOW_HOURS = 48  # keep the Observation object set demo-sized


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return yaml.safe_load(f)


def _write(df: pd.DataFrame, kind: str, name: str) -> int:
    out = ONTOLOGY_DIR / kind
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{name}.parquet", index=False)
    return len(df)


def build() -> dict:
    station_state = pd.read_parquet(GOLD_DIR / "station_state")
    zone_hourly = pd.read_parquet(GOLD_DIR / "zone_hourly")
    observations = pd.read_parquet(GOLD_DIR / "observations")
    counts: dict[str, int] = {}

    # ---- objects: Zone ------------------------------------------------------
    zone_df = pd.DataFrame(
        [
            {"zone_id": f"zone:{z['slug']}", "slug": z["slug"], "name": z["name"],
             "lat": z["lat"], "lon": z["lon"]}
            for z in zones()
        ]
    )
    counts["Zone"] = _write(zone_df, "objects", "zone")

    # ---- objects: BikeStation ----------------------------------------------
    st = station_state.copy()
    st["object_id"] = "station:" + st["station_id"].astype(str)
    bike_station = st[
        ["object_id", "station_id", "name", "lat", "lon", "capacity",
         "bikes_available", "bikes_mechanical", "bikes_ebike", "docks_available",
         "fill_ratio", "is_renting", "reported_at", "zone"]
    ]
    counts["BikeStation"] = _write(bike_station, "objects", "bike_station")

    # ---- objects: AirQualitySensor (latest reading per zone) ----------------
    aq = zone_hourly.dropna(subset=["eaqi"]).sort_values("hour")
    aq_latest = aq.groupby("zone").tail(1)
    zmeta = zone_df.set_index("slug")
    sensor = pd.DataFrame(
        {
            "object_id": "aq:" + aq_latest["zone"],
            "sensor_id": "aq:" + aq_latest["zone"],
            "name": "AQ " + aq_latest["zone"].map(zmeta["name"]),
            "lat": aq_latest["zone"].map(zmeta["lat"]),
            "lon": aq_latest["zone"].map(zmeta["lon"]),
            "pm2_5": aq_latest["pm2_5"],
            "pm10": aq_latest["pm10"],
            "no2": aq_latest["no2"],
            "o3": aq_latest["o3"],
            "eaqi": aq_latest["eaqi"],
            "observed_at": aq_latest["hour"],
            "zone": aq_latest["zone"],
        }
    )
    counts["AirQualitySensor"] = _write(sensor, "objects", "air_quality_sensor")

    # ---- objects: Observation (recent window) -------------------------------
    obs = observations.copy()
    cutoff = obs["observed_at"].max() - pd.Timedelta(hours=OBSERVATION_WINDOW_HOURS)
    obs = obs[obs["observed_at"] >= cutoff]
    obs["observation_id"] = (
        obs["entity_id"] + "|" + obs["metric"] + "|"
        + obs["observed_at"].astype("int64").astype(str)
    )
    observation = obs[["observation_id", "entity_id", "entity_type", "metric", "value", "observed_at"]]
    counts["Observation"] = _write(observation, "objects", "observation")

    # ---- links ---------------------------------------------------------------
    located_in = pd.DataFrame(
        {"from_id": bike_station["object_id"], "to_id": "zone:" + bike_station["zone"]}
    )
    counts["locatedIn"] = _write(located_in, "links", "located_in")

    monitors = pd.DataFrame(
        {"from_id": sensor["object_id"], "to_id": "zone:" + sensor["zone"]}
    )
    counts["monitors"] = _write(monitors, "links", "monitors")

    observed_by = pd.DataFrame(
        {
            "from_id": observation["observation_id"],
            "to_id": observation["entity_id"],
            "to_type": observation["entity_type"],
        }
    )
    counts["observedBy"] = _write(observed_by, "links", "observed_by")

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "schema": str(SCHEMA_PATH.name),
        "counts": counts,
    }
    with open(ONTOLOGY_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    m = build()
    print(json.dumps(m, indent=2))
