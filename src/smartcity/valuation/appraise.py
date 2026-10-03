"""Appraise a property anywhere in Paris from the ontology's features.

  python -m smartcity.valuation.appraise --lat 48.8846 --lon 2.3382 \
      --surface 62 --rooms 3 --type Appartement

Returns a self-contained, content-hashed appraisal document: inputs, the
graph-derived features, the estimate, the per-driver breakdown, and the
model manifest it was produced by. The sha256 makes the document tamper-
evident — the exact payload a smart contract can anchor when properties are
tokenized (future_types in ontology/schema.yml).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from smartcity.config import DATA_DIR
from smartcity.valuation.features import build_query_features
from smartcity.valuation.models import DEFAULT_MODEL, ValuationModel

VALUATION_DIR = DATA_DIR / "valuation"


def appraise(lat: float, lon: float, surface_m2: float, rooms: int,
             property_type: str, model_name: str = DEFAULT_MODEL,
             save: bool = False) -> dict:
    model_dir = VALUATION_DIR / model_name
    model = ValuationModel.load(model_dir)
    manifest = json.loads((model_dir / "manifest.json").read_text())

    feats = build_query_features(lat, lon, surface_m2, rooms, property_type)
    price_m2 = float(model.predict(pd.DataFrame([feats]))[0])
    doc = {
        "inputs": {"lat": lat, "lon": lon, "surface_m2": surface_m2,
                   "rooms": rooms, "property_type": property_type},
        "features": feats,
        "estimate": {"price_m2_eur": round(price_m2), "total_eur": round(price_m2 * surface_m2)},
        "breakdown": model.explain(feats),
        "model": {"name": manifest["model"], "trained_at": manifest["trained_at"],
                  "metrics": manifest["metrics"], "data_fingerprint": manifest["data_fingerprint"]},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)
    doc["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    if save:
        out = VALUATION_DIR / "appraisals"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{doc['sha256'][:16]}.json").write_text(json.dumps(doc, indent=2, default=str))
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Appraise a Paris property")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--surface", type=float, required=True)
    parser.add_argument("--rooms", type=int, default=2)
    parser.add_argument("--type", dest="ptype", default="Appartement",
                        choices=["Appartement", "Maison"])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    doc = appraise(args.lat, args.lon, args.surface, args.rooms, args.ptype,
                   model_name=args.model, save=args.save)
    print(json.dumps(doc, indent=2, default=str))


if __name__ == "__main__":
    main()
