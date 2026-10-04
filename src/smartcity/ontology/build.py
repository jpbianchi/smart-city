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
    traffic_sensors = pd.read_parquet(GOLD_DIR / "traffic_sensors")
    amenities = pd.read_parquet(GOLD_DIR / "amenities")
    transactions = pd.read_parquet(GOLD_DIR / "transactions")
    tx_features = pd.read_parquet(
        GOLD_DIR / "transaction_features", columns=["tx_id", "subway_id", "dist_subway_m"]
    )
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

    # ---- objects: TrafficSensor ---------------------------------------------
    ts = traffic_sensors.copy()
    ts["object_id"] = "traffic:" + ts["sensor_id"].astype(str)
    sensor_objs = ts[["object_id", "sensor_id", "name", "lat", "lon", "last_flow_vph",
                      "last_occupancy_pct", "last_state", "last_seen", "zone"]]
    counts["TrafficSensor"] = _write(sensor_objs, "objects", "traffic_sensor")

    # ---- objects: Amenity ------------------------------------------------------
    am = amenities.copy()
    am["object_id"] = "poi:" + am["osm_id"].astype(str)
    amenity_objs = am[["object_id", "osm_id", "kind", "name", "lat", "lon", "zone"]]
    counts["Amenity"] = _write(amenity_objs, "objects", "amenity")

    # ---- objects: PropertyTransaction ------------------------------------------
    tx = transactions.copy()
    tx_objs = tx[["tx_id", "address", "property_type", "price_eur", "surface_m2", "rooms",
                  "price_m2", "sold_on", "year", "postal_code", "lat", "lon", "zone"]]
    counts["PropertyTransaction"] = _write(tx_objs, "objects", "property_transaction")

    # ---- links ---------------------------------------------------------------
    located_in = pd.DataFrame(
        {"from_id": bike_station["object_id"], "to_id": "zone:" + bike_station["zone"]}
    )
    counts["locatedIn"] = _write(located_in, "links", "located_in")

    monitors_road = pd.DataFrame(
        {"from_id": sensor_objs["object_id"], "to_id": "zone:" + sensor_objs["zone"]}
    )
    counts["monitorsRoad"] = _write(monitors_road, "links", "monitors_road")

    amenity_in = pd.DataFrame(
        {"from_id": amenity_objs["object_id"], "to_id": "zone:" + amenity_objs["zone"]}
    )
    counts["amenityIn"] = _write(amenity_in, "links", "amenity_in")

    transaction_in = pd.DataFrame(
        {"from_id": tx_objs["tx_id"], "to_id": "zone:" + tx_objs["zone"]}
    )
    counts["transactionIn"] = _write(transaction_in, "links", "transaction_in")

    nearest_station = (
        tx_features.dropna(subset=["subway_id"])
        .rename(columns={"tx_id": "from_id"})
        .assign(to_id=lambda d: "poi:" + d["subway_id"].astype(str))
        [["from_id", "to_id", "dist_subway_m"]]
        .rename(columns={"dist_subway_m": "dist_m"})
    )
    counts["nearestStation"] = _write(nearest_station, "links", "nearest_station")

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

    # ---- on-chain layer: Asset / PropertyToken / Appraisal ---------------------
    # Derived from the chain indexer (data/chain/*.parquet) exactly like any
    # other source; absent until something has been tokenized.
    chain_tokens = GOLD_DIR.parent / "chain" / "tokens.parquet"
    if chain_tokens.exists():
        tok = pd.read_parquet(chain_tokens)
        asset = pd.DataFrame({
            "asset_id": "asset:" + tok["listing_id"].str.removeprefix("tx:"),
            "listing_id": tok["listing_id"],
            "address": tok["chain_address_label"],
            "surface_m2": tok["surface_m2"],
        })
        counts["Asset"] = _write(asset, "objects", "asset")

        token = pd.DataFrame({
            "token_id": tok["token_id"],
            "listing_id": tok["listing_id"],
            "shares_supply": tok["shares_supply"],
            "n_holders": tok["n_holders"],
            "free_float_pct": tok["free_float_pct"],
            "last_share_price_eur": tok["last_share_price_eur"],
            "market_cap_eur": tok["market_cap_eur"],
            "minted_at": tok["minted_at"],
            "mint_tx": tok["mint_tx"],
        })
        counts["PropertyToken"] = _write(token, "objects", "property_token")

        appraisal = pd.DataFrame({
            "appraisal_id": "appraisal:" + tok["appraisal_sha256"].str[:16],
            "sha256": tok["appraisal_sha256"],
            "fair_value_eur": tok["onchain_fair_eur"],
            "as_of_month": tok["appraisal_as_of"],
        })
        counts["Appraisal"] = _write(appraisal, "objects", "appraisal")

        counts["tokenizes"] = _write(
            pd.DataFrame({"from_id": token["token_id"], "to_id": asset["asset_id"]}),
            "links", "tokenizes",
        )
        counts["deedOf"] = _write(
            pd.DataFrame({"from_id": asset["asset_id"], "to_id": tok["listing_id"]}),
            "links", "deed_of",
        )
        counts["valuedBy"] = _write(
            pd.DataFrame({"from_id": token["token_id"], "to_id": appraisal["appraisal_id"]}),
            "links", "valued_by",
        )

        # ---- market activity: who holds what, who offered, who traded ------------
        chain_dir = chain_tokens.parent
        parties = pd.read_parquet(chain_dir / "parties.parquet")
        holdings = pd.read_parquet(chain_dir / "holdings.parquet")
        offers = pd.read_parquet(chain_dir / "offers.parquet")
        trades = pd.read_parquet(chain_dir / "trades.parquet")

        counts["Party"] = _write(parties, "objects", "party")
        counts["Holding"] = _write(holdings, "objects", "holding")
        counts["ShareOffer"] = _write(offers, "objects", "share_offer")
        counts["ShareTrade"] = _write(trades, "objects", "share_trade")

        link_specs = {
            "holds": ("holds", holdings, "party_id", "holding_id"),
            "holdingOf": ("holding_of", holdings, "holding_id", "token_id"),
            "offers": ("offers", offers, "seller_party_id", "offer_id"),
            "offerFor": ("offer_for", offers, "offer_id", "token_id"),
            "buyer": ("buyer", trades, "trade_id", "buyer_party_id"),
            "seller": ("seller", trades, "trade_id", "seller_party_id"),
            "fills": ("fills", trades, "trade_id", "offer_id"),
            "tradeOf": ("trade_of", trades, "trade_id", "token_id"),
        }
        for link, (fname, df, src, dst) in link_specs.items():
            counts[link] = _write(
                pd.DataFrame({"from_id": df[src].to_numpy(), "to_id": df[dst].to_numpy()}),
                "links", fname,
            )

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
