"""Data catalog: every source feeding the ontology and the valuation.

Each entry documents provenance (provider, licence, cadence, endpoint), what
the source measures, and exactly where it is used downstream (valuation
features, ontology objects/links). `load_points` and `load_series` give a
uniform view of each source's records for the dashboard.
"""
from __future__ import annotations

import pandas as pd

from smartcity.config import BRONZE_DIR, GOLD_DIR, SILVER_DIR, haversine_km, zones

SOURCES: dict[str, dict] = {
    "traffic": {
        "name": "Road traffic counters",
        "kind": "IoT sensor network",
        "provider": "Ville de Paris — Direction de la Voirie",
        "dataset": "comptages-routiers-permanents",
        "url": "https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents/",
        "licence": "ODbL",
        "cadence": "Hourly, polled every 30 min",
        "method": "Permanent induction loops embedded in the road surface; each counts vehicles "
                  "(flow, veh/h) and measures the share of time the loop is occupied (occupancy %).",
        "measures": "Flow (vehicles/hour), occupancy (%), traffic state (fluid → saturated)",
        "feeds_features": ["zone_traffic_occupancy"],
        "feeds_ontology": ["TrafficSensor", "Observation", "monitorsRoad", "observedBy"],
        "metric": "Occupancy %",
    },
    "air": {
        "name": "Air quality",
        "kind": "Environmental model (virtual sensors)",
        "provider": "Open-Meteo · Copernicus CAMS European air-quality model",
        "dataset": "air-quality API",
        "url": "https://open-meteo.com/en/docs/air-quality-api",
        "licence": "CC BY 4.0",
        "cadence": "Hourly, polled every 60 s",
        "method": "Model grid (~11 km) sampled at each district center — one virtual sensor per zone. "
                  "Not a physical station; documented as such in the ontology.",
        "measures": "PM2.5, PM10, NO₂, O₃ (µg/m³), European AQI",
        "feeds_features": ["zone_eaqi"],
        "feeds_ontology": ["AirQualitySensor", "Observation", "monitors", "observedBy"],
        "metric": "European AQI",
    },
    "dvf": {
        "name": "Property transactions (DVF)",
        "kind": "Official register",
        "provider": "DGFiP · Etalab — Demandes de Valeurs Foncières, geolocated",
        "dataset": "geo-dvf, département 75, 2021–2025",
        "url": "https://files.data.gouv.fr/geo-dvf/",
        "licence": "Licence Ouverte 2.0",
        "cadence": "Semi-annual release, batch ingest",
        "method": "Every notarised property sale in France. Cleaned to single-dwelling market sales "
                  "(block sales and non-market transfers removed).",
        "measures": "Price, surface, rooms, type, date, address, coordinates",
        "feeds_features": ["price_m2 (training target)", "zone comparables", "property inventory"],
        "feeds_ontology": ["PropertyTransaction", "transactionIn", "nearestStation"],
        "metric": "€/m²",
    },
    "subway_station": {
        "name": "Metro stations",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'node["station"="subway"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:station%3Dsubway",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Every metro station node in greater Paris.",
        "measures": "Location, name",
        "feeds_features": ["dist_subway_m"],
        "feeds_ontology": ["Amenity", "amenityIn", "nearestStation"],
        "metric": None,
    },
    "train_station": {
        "name": "Train & RER stations",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'node["railway"="station"]["station"!="subway"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:railway%3Dstation",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Mainline, RER and Transilien stations (metro excluded).",
        "measures": "Location, name",
        "feeds_features": ["dist_train_m"],
        "feeds_ontology": ["Amenity", "amenityIn"],
        "metric": None,
    },
    "school": {
        "name": "Schools",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'nwr["amenity"="school"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dschool",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Nursery, primary and secondary schools (nodes and building outlines, as centroids).",
        "measures": "Location, name",
        "feeds_features": ["dist_school_m", "n_schools_500m"],
        "feeds_ontology": ["Amenity", "amenityIn"],
        "metric": None,
    },
    "park": {
        "name": "Parks & gardens",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'nwr["leisure"="park"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:leisure%3Dpark",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Public parks, squares and gardens (polygons reduced to their centroid).",
        "measures": "Location, name",
        "feeds_features": ["dist_park_m", "n_parks_500m"],
        "feeds_ontology": ["Amenity", "amenityIn"],
        "metric": None,
    },
    "supermarket": {
        "name": "Supermarkets",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'nwr["shop"="supermarket"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:shop%3Dsupermarket",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Supermarkets and grocery chains.",
        "measures": "Location, name",
        "feeds_features": ["n_supermarkets_500m"],
        "feeds_ontology": ["Amenity", "amenityIn"],
        "metric": None,
    },
    "hospital": {
        "name": "Hospitals",
        "kind": "Points of interest",
        "provider": "OpenStreetMap contributors (Overpass API)",
        "dataset": 'nwr["amenity"="hospital"]',
        "url": "https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dhospital",
        "licence": "ODbL",
        "cadence": "Batch snapshot",
        "method": "Hospitals and clinics.",
        "measures": "Location, name",
        "feeds_features": [],
        "feeds_ontology": ["Amenity", "amenityIn"],
        "metric": None,
    },
}

DVF_MAP_SAMPLE = 4000  # the full 146k sales are summarized; the map shows a sample


def load_points(source: str) -> pd.DataFrame:
    """Uniform record view: id, name, lat, lon, zone, value (metric or NaN), detail."""
    if source == "traffic":
        df = pd.read_parquet(GOLD_DIR / "traffic_sensors")
        return pd.DataFrame({
            "id": "traffic:" + df["sensor_id"].astype(str),
            "name": df["name"].str.replace("_", " "),
            "lat": df["lat"], "lon": df["lon"], "zone": df["zone"],
            "value": df["last_occupancy_pct"],
            "detail": "flow " + df["last_flow_vph"].map("{:.0f} veh/h".format)
                      + " · " + df["last_state"].fillna("–"),
            "updated": pd.to_datetime(df["last_seen"]),
        })
    if source == "air":
        obs = pd.read_parquet(SILVER_DIR / "air_quality").sort_values("observed_at")
        last = obs.groupby("zone").tail(1).set_index("zone")
        zmeta = {z["slug"]: z for z in zones()}
        rows = []
        for slug, z in zmeta.items():
            r = last.loc[slug] if slug in last.index else None
            rows.append({
                "id": f"aq:{slug}", "name": f"AQ {z['name']}", "lat": z["lat"], "lon": z["lon"],
                "zone": slug,
                "value": None if r is None else r["eaqi"],
                "detail": "–" if r is None else f"PM2.5 {r['pm2_5']:.1f} · NO₂ {r['no2']:.1f} µg/m³",
                "updated": None if r is None else pd.to_datetime(r["observed_at"]),
            })
        return pd.DataFrame(rows)
    if source == "dvf":
        df = pd.read_parquet(GOLD_DIR / "transactions",
                             columns=["tx_id", "address", "lat", "lon", "zone", "price_m2",
                                      "price_eur", "surface_m2", "sold_on"])
        return pd.DataFrame({
            "id": df["tx_id"], "name": df["address"], "lat": df["lat"], "lon": df["lon"],
            "zone": df["zone"], "value": df["price_m2"],
            "detail": df["price_eur"].map(lambda v: f"{v:,.0f} €".replace(",", " "))
                      + " · " + df["surface_m2"].map("{:.0f} m²".format),
            "updated": pd.to_datetime(df["sold_on"]),
        })
    amen = pd.read_parquet(GOLD_DIR / "amenities")
    df = amen[amen["kind"] == source]
    return pd.DataFrame({
        "id": "poi:" + df["osm_id"], "name": df["name"].fillna("(unnamed)"),
        "lat": df["lat"], "lon": df["lon"], "zone": df["zone"],
        "value": float("nan"), "detail": "OSM " + df["osm_id"], "updated": pd.NaT,
    })


def snapshot_date(source: str) -> str:
    """Latest bronze landing date for a source (freshness of batch snapshots)."""
    feed = {"traffic": "traffic", "air": "air_quality", "dvf": "dvf"}.get(source, "amenities")
    dates = sorted(p.name.split("=", 1)[1] for p in (BRONZE_DIR / f"feed={feed}").glob("date=*"))
    return dates[-1] if dates else "–"


def coverage(points: pd.DataFrame) -> dict:
    """Spatial footprint of a source."""
    if points.empty:
        return {"zones_covered": 0, "extent": "–", "density": "–"}
    lat0, lat1 = points["lat"].min(), points["lat"].max()
    lon0, lon1 = points["lon"].min(), points["lon"].max()
    ns = haversine_km(lat0, lon0, lat1, lon0)
    ew = haversine_km(lat0, lon0, lat0, lon1)
    area = max(ns * ew, 1e-6)
    return {
        "zones_covered": int(points["zone"].nunique()),
        "extent": f"{ew:.1f} × {ns:.1f} km",
        "density": f"{len(points) / area:.1f} / km²",
        "bbox": (lat0, lon0, lat1, lon1),
    }


def load_series(source: str, record_id: str) -> pd.DataFrame:
    """Time series for one sensor: columns observed_at, metric, value."""
    if source == "traffic":
        sensor = record_id.split(":", 1)[1]
        df = pd.read_parquet(SILVER_DIR / "traffic_readings",
                             columns=["sensor_id", "observed_at", "flow_vph", "occupancy_pct"],
                             filters=[("sensor_id", "=", sensor)])
        return df.sort_values("observed_at")
    if source == "air":
        zone = record_id.split(":", 1)[1]
        df = pd.read_parquet(SILVER_DIR / "air_quality", filters=[("zone", "=", zone)])
        return df.sort_values("observed_at")
    return pd.DataFrame()
