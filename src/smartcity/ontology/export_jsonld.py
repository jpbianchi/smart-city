"""Export the ontology as JSON-LD using the W3C SOSA/SSN vocabulary.

  python -m smartcity.ontology.export_jsonld

Produces data/ontology/city_graph.jsonld — the same graph, expressed in
standard vocabularies: W3C SOSA/SSN for sensing (sosa:Sensor /
sosa:Observation / sosa:FeatureOfInterest — the basis of NGSI-LD, SAREF4City
and the OASC/Microsoft smart-city ontologies) and schema.org for the real-
estate side (schema:Place amenities, schema:SellAction property sales).
Zero dependencies: JSON-LD is just JSON with an @context.
"""
from __future__ import annotations

import json

import pandas as pd

from smartcity.config import ONTOLOGY_DIR

CONTEXT = {
    "sosa": "http://www.w3.org/ns/sosa/",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "schema": "https://schema.org/",
    "city": "https://example.org/smartcity/",
}

MAX_OBSERVATIONS = 2000  # keep the export readable
MAX_TRANSACTIONS = 5000  # most recent sales; the full set lives in the parquet ontology


def _node(id_: str, type_: str, label: str | None = None, **props) -> dict:
    node = {"@id": f"city:{id_}", "@type": type_}
    if label is not None:
        node["rdfs:label"] = label
    node.update({k: v for k, v in props.items() if v is not None and not pd.isna(v)})
    return node


def export() -> int:
    objects = ONTOLOGY_DIR / "objects"
    zones = pd.read_parquet(objects / "zone.parquet")
    stations = pd.read_parquet(objects / "bike_station.parquet")
    sensors = pd.read_parquet(objects / "air_quality_sensor.parquet")
    observations = pd.read_parquet(objects / "observation.parquet").tail(MAX_OBSERVATIONS)
    traffic = pd.read_parquet(objects / "traffic_sensor.parquet")
    amenities = pd.read_parquet(objects / "amenity.parquet")
    transactions = (pd.read_parquet(objects / "property_transaction.parquet")
                    .sort_values("sold_on").tail(MAX_TRANSACTIONS))
    links = ONTOLOGY_DIR / "links"
    ns = pd.read_parquet(links / "nearest_station.parquet")
    nearest = dict(zip(ns["from_id"], zip(ns["to_id"], ns["dist_m"])))

    graph: list[dict] = []
    for _, z in zones.iterrows():
        graph.append(_node(z.zone_id, "sosa:FeatureOfInterest", z["name"],
                           **{"geo:lat": z.lat, "geo:long": z.lon}))
    for _, s in stations.iterrows():
        graph.append(_node(s.object_id, "sosa:Platform", s["name"],
                           **{"geo:lat": s.lat, "geo:long": s.lon,
                              "city:capacity": int(s.capacity) if pd.notna(s.capacity) else None,
                              "city:locatedIn": {"@id": f"city:zone:{s.zone}"}}))
    for _, s in sensors.iterrows():
        graph.append(_node(s.object_id, "sosa:Sensor", s["name"],
                           **{"geo:lat": s.lat, "geo:long": s.lon,
                              "sosa:observes": {"@id": f"city:zone:{s.zone}"}}))
    for _, s in traffic.iterrows():
        graph.append(_node(s.object_id, "sosa:Sensor", s["name"],
                           **{"geo:lat": s.lat, "geo:long": s.lon,
                              "city:monitorsRoad": {"@id": f"city:zone:{s.zone}"}}))
    for _, a in amenities.iterrows():
        graph.append(_node(a.object_id, "schema:Place", a["name"] if pd.notna(a["name"]) else None,
                           **{"geo:lat": a.lat, "geo:long": a.lon, "city:kind": a.kind,
                              "city:amenityIn": {"@id": f"city:zone:{a.zone}"}}))
    for _, t in transactions.iterrows():
        near = nearest.get(t.tx_id)
        graph.append(_node(
            t.tx_id, "schema:SellAction", t.address,
            **{"geo:lat": t.lat, "geo:long": t.lon,
               "schema:price": float(t.price_eur), "schema:priceCurrency": "EUR",
               "schema:endTime": str(t.sold_on), "city:surfaceM2": float(t.surface_m2),
               "city:propertyType": t.property_type,
               "city:transactionIn": {"@id": f"city:zone:{t.zone}"},
               "city:nearestStation": None if near is None else
                   {"@id": f"city:{near[0]}", "city:distanceM": float(near[1])}}))
    for _, o in observations.iterrows():
        graph.append(
            _node(o.observation_id, "sosa:Observation",
                  **{"sosa:madeBySensor": {"@id": f"city:{o.entity_id}"},
                     "sosa:observedProperty": {"@id": f"city:metric:{o.metric}"},
                     "sosa:hasSimpleResult": float(o.value),
                     "sosa:resultTime": o.observed_at.isoformat()})
        )

    doc = {"@context": CONTEXT, "@graph": graph}
    out = ONTOLOGY_DIR / "city_graph.jsonld"
    with open(out, "w") as f:
        json.dump(doc, f, indent=1, default=str)
    print(f"{out}: {len(graph)} nodes")
    return len(graph)


if __name__ == "__main__":
    export()
