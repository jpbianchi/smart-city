"""Export the ontology as JSON-LD using the W3C SOSA/SSN vocabulary.

  python -m smartcity.ontology.export_jsonld

Produces data/ontology/city_graph.jsonld — the same graph, expressed in the
standard sensing vocabulary (sosa:Sensor / sosa:Observation /
sosa:FeatureOfInterest) that NGSI-LD, SAREF4City and the OASC/Microsoft
smart-city ontologies build on. Zero dependencies: JSON-LD is just JSON
with an @context.
"""
from __future__ import annotations

import json

import pandas as pd

from smartcity.config import ONTOLOGY_DIR

CONTEXT = {
    "sosa": "http://www.w3.org/ns/sosa/",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "city": "https://example.org/smartcity/",
}

MAX_OBSERVATIONS = 2000  # keep the export readable


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
