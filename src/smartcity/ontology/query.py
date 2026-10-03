"""Read API over the materialized ontology: load objects, follow links.

Usage:
    from smartcity.ontology.query import Ontology
    onto = Ontology.load()
    z = onto.get("zone:montmartre")
    stations = onto.linked_from("locatedIn", to_id="zone:montmartre")
    obs = onto.observations_for("station:17026")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from smartcity.config import ONTOLOGY_DIR

OBJECT_FILES = {
    "Zone": ("zone", "zone_id"),
    "BikeStation": ("bike_station", "object_id"),
    "AirQualitySensor": ("air_quality_sensor", "object_id"),
    "Observation": ("observation", "observation_id"),
}
LINK_FILES = {"locatedIn": "located_in", "monitors": "monitors", "observedBy": "observed_by"}


@dataclass
class Ontology:
    objects: dict[str, pd.DataFrame] = field(default_factory=dict)
    links: dict[str, pd.DataFrame] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Ontology":
        o = cls()
        for otype, (fname, pk) in OBJECT_FILES.items():
            path = ONTOLOGY_DIR / "objects" / f"{fname}.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                df = df.set_index(pk, drop=False)
                o.objects[otype] = df
        for ltype, fname in LINK_FILES.items():
            path = ONTOLOGY_DIR / "links" / f"{fname}.parquet"
            if path.exists():
                o.links[ltype] = pd.read_parquet(path)
        mpath = ONTOLOGY_DIR / "manifest.json"
        if mpath.exists():
            o.manifest = json.loads(mpath.read_text())
        return o

    # -- object access -------------------------------------------------------
    def type_of(self, object_id: str) -> str | None:
        for otype, df in self.objects.items():
            if object_id in df.index:
                return otype
        return None

    def get(self, object_id: str) -> dict | None:
        otype = self.type_of(object_id)
        if otype is None:
            return None
        row = self.objects[otype].loc[object_id]
        d = {k: v for k, v in row.items() if pd.notna(v)}
        d["__type__"] = otype
        return d

    # -- link traversal -------------------------------------------------------
    def linked_from(self, link_type: str, to_id: str) -> pd.DataFrame:
        """Objects on the FROM side of a link pointing at to_id."""
        lt = self.links.get(link_type)
        if lt is None:
            return pd.DataFrame()
        return lt[lt["to_id"] == to_id]

    def linked_to(self, link_type: str, from_id: str) -> pd.DataFrame:
        """Link rows whose FROM side is from_id."""
        lt = self.links.get(link_type)
        if lt is None:
            return pd.DataFrame()
        return lt[lt["from_id"] == from_id]

    # -- convenience traversals (the demo queries) ----------------------------
    def stations_in_zone(self, zone_id: str) -> pd.DataFrame:
        ids = self.linked_from("locatedIn", zone_id)["from_id"]
        return self.objects["BikeStation"].loc[self.objects["BikeStation"].index.intersection(ids)]

    def sensor_for_zone(self, zone_id: str) -> dict | None:
        rows = self.linked_from("monitors", zone_id)
        if rows.empty:
            return None
        return self.get(rows.iloc[0]["from_id"])

    def observations_for(self, object_id: str, metric: str | None = None) -> pd.DataFrame:
        obs_ids = self.linked_from("observedBy", object_id)["from_id"]
        obs = self.objects.get("Observation")
        if obs is None or obs_ids.empty:
            return pd.DataFrame()
        out = obs.loc[obs.index.intersection(obs_ids)].sort_values("observed_at")
        if metric:
            out = out[out["metric"] == metric]
        return out

    def zone_context(self, zone_id: str) -> dict:
        """One multi-hop query: a zone, its stations, its sensor, latest air."""
        zone = self.get(zone_id)
        stations = self.stations_in_zone(zone_id)
        sensor = self.sensor_for_zone(zone_id)
        return {
            "zone": zone,
            "n_stations": len(stations),
            "bikes_available": int(stations["bikes_available"].fillna(0).sum()) if not stations.empty else 0,
            "sensor": sensor,
        }


if __name__ == "__main__":
    onto = Ontology.load()
    print("manifest:", json.dumps(onto.manifest.get("counts", {}), indent=2))
    zid = "zone:montmartre"
    ctx = onto.zone_context(zid)
    print(f"\n{zid}: {ctx['n_stations']} stations, {ctx['bikes_available']} bikes available")
    if ctx["sensor"]:
        print(f"air quality (EAQI): {ctx['sensor'].get('eaqi')}  pm2.5: {ctx['sensor'].get('pm2_5')}")
