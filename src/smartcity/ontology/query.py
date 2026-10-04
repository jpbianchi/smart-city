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
    "TrafficSensor": ("traffic_sensor", "object_id"),
    "Amenity": ("amenity", "object_id"),
    "PropertyTransaction": ("property_transaction", "tx_id"),
    "Asset": ("asset", "asset_id"),
    "PropertyToken": ("property_token", "token_id"),
    "Appraisal": ("appraisal", "appraisal_id"),
    "Party": ("party", "party_id"),
    "Holding": ("holding", "holding_id"),
    "ShareOffer": ("share_offer", "offer_id"),
    "ShareTrade": ("share_trade", "trade_id"),
}
LINK_FILES = {
    "locatedIn": "located_in",
    "monitors": "monitors",
    "observedBy": "observed_by",
    "monitorsRoad": "monitors_road",
    "amenityIn": "amenity_in",
    "transactionIn": "transaction_in",
    "nearestStation": "nearest_station",
    "tokenizes": "tokenizes",
    "deedOf": "deed_of",
    "valuedBy": "valued_by",
    "holds": "holds",
    "holdingOf": "holding_of",
    "offers": "offers",
    "offerFor": "offer_for",
    "buyer": "buyer",
    "seller": "seller",
    "fills": "fills",
    "tradeOf": "trade_of",
}


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

    def transactions_in_zone(self, zone_id: str, property_type: str | None = None,
                             since_year: int | None = None) -> pd.DataFrame:
        """Comparables query: sales linked to a zone, optionally filtered."""
        ids = self.linked_from("transactionIn", zone_id)["from_id"]
        tx = self.objects.get("PropertyTransaction")
        if tx is None or ids.empty:
            return pd.DataFrame()
        out = tx.loc[tx.index.intersection(ids)]
        if property_type:
            out = out[out["property_type"] == property_type]
        if since_year:
            out = out[out["year"] >= since_year]
        return out

    def zone_context(self, zone_id: str) -> dict:
        """One multi-hop query: a zone, its stations, sensors, market, air."""
        zone = self.get(zone_id)
        stations = self.stations_in_zone(zone_id)
        sensor = self.sensor_for_zone(zone_id)
        road_sensors = self.linked_from("monitorsRoad", zone_id)
        amenities = self.linked_from("amenityIn", zone_id)
        tx = self.transactions_in_zone(zone_id, since_year=2024)
        return {
            "zone": zone,
            "n_stations": len(stations),
            "bikes_available": int(stations["bikes_available"].fillna(0).sum()) if not stations.empty else 0,
            "sensor": sensor,
            "n_road_sensors": len(road_sensors),
            "n_amenities": len(amenities),
            "n_recent_sales": len(tx),
            "median_price_m2": float(tx["price_m2"].median()) if not tx.empty else None,
        }

    # -- on-chain traversals ------------------------------------------------------
    def _one(self, link_type: str, from_id: str) -> str | None:
        rows = self.linked_to(link_type, from_id)
        return None if rows.empty else rows.iloc[0]["to_id"]

    def _label(self, party_id: str) -> str:
        p = self.get(party_id)
        return p["label"] if p else party_id

    def token_lineage(self, token_id: str) -> dict:
        """Full provenance of one tokenized property, by following links only:
        DVF sale -> appraisal -> asset -> token -> offers -> trades (with parties)."""
        token = self.get(token_id)
        asset_id = self._one("tokenizes", token_id)
        sale_id = self._one("deedOf", asset_id) if asset_id else None
        appraisal_id = self._one("valuedBy", token_id)
        offer_ids = self.linked_from("offerFor", token_id)["from_id"]
        trade_ids = self.linked_from("tradeOf", token_id)["from_id"]
        offers = self.objects["ShareOffer"].loc[offer_ids] if not offer_ids.empty else pd.DataFrame()
        trades = self.objects["ShareTrade"].loc[trade_ids].sort_values("block") if not trade_ids.empty else pd.DataFrame()
        holders = self.linked_from("holdingOf", token_id)["from_id"]
        return {
            "token": token,
            "asset": self.get(asset_id) if asset_id else None,
            "dvf_sale": self.get(sale_id) if sale_id else None,
            "zone": self._one("transactionIn", sale_id) if sale_id else None,
            "appraisal": self.get(appraisal_id) if appraisal_id else None,
            "offers": [
                {**o, "seller": self._label(o["seller_party_id"])}
                for o in offers.to_dict("records")
            ],
            "trades": [
                {**t, "buyer": self._label(t["buyer_party_id"]), "seller": self._label(t["seller_party_id"])}
                for t in trades.to_dict("records")
            ],
            "cap_table": [
                {"holder": self._label(h["party_id"]), "shares": int(h["shares"]), "pct": float(h["pct"])}
                for h in self.objects["Holding"].loc[holders].sort_values("shares", ascending=False).to_dict("records")
            ] if not holders.empty else [],
        }

    def party_exposure(self, party_id: str) -> pd.DataFrame:
        """What a party owns, where, and what it is worth at the oracle's fair value:
        Party -holds-> Holding -holdingOf-> Token -tokenizes-> Asset -deedOf->
        PropertyTransaction -transactionIn-> Zone, and Token -valuedBy-> Appraisal."""
        hold_ids = self.linked_to("holds", party_id)["to_id"]
        if hold_ids.empty:
            return pd.DataFrame()
        h = self.objects["Holding"].loc[hold_ids][["holding_id", "token_id", "shares", "pct"]]
        h = h.merge(self.links["tokenizes"].rename(columns={"from_id": "token_id", "to_id": "asset_id"}), on="token_id")
        h = h.merge(self.links["deedOf"].rename(columns={"from_id": "asset_id", "to_id": "tx_id"}), on="asset_id")
        h = h.merge(self.links["valuedBy"].rename(columns={"from_id": "token_id", "to_id": "appraisal_id"}), on="token_id")
        sales = self.objects["PropertyTransaction"][["tx_id", "address", "postal_code", "zone"]].reset_index(drop=True)
        apps = self.objects["Appraisal"][["appraisal_id", "fair_value_eur"]].reset_index(drop=True)
        h = h.merge(sales, on="tx_id").merge(apps, on="appraisal_id")
        h["exposure_eur"] = (h["fair_value_eur"] * h["pct"] / 100).round(0)
        return h.sort_values("exposure_eur", ascending=False)[
            ["address", "postal_code", "zone", "shares", "pct", "fair_value_eur", "exposure_eur", "token_id"]
        ].reset_index(drop=True)


if __name__ == "__main__":
    onto = Ontology.load()
    print("manifest:", json.dumps(onto.manifest.get("counts", {}), indent=2))
    zid = "zone:montmartre"
    ctx = onto.zone_context(zid)
    print(f"\n{zid}: {ctx['n_stations']} stations, {ctx['bikes_available']} bikes available")
    if ctx["sensor"]:
        print(f"air quality (EAQI): {ctx['sensor'].get('eaqi')}  pm2.5: {ctx['sensor'].get('pm2_5')}")
