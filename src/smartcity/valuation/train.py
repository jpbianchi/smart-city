"""Train and evaluate a valuation model; persist a versioned artifact.

  python -m smartcity.valuation.train                  # default model
  python -m smartcity.valuation.train --model comparables

Time-based split (train on past years, test on the latest) because a
valuation model is only honest if it prices sales it has never seen, from a
period after its training data. Artifacts land in data/valuation/<model>/
with a manifest (features, metrics, data fingerprint) — the provenance a
future tokenization layer can anchor on-chain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np

from smartcity.config import DATA_DIR
from smartcity.valuation.features import ALL_FEATURES, TARGET, load_training_frame
from smartcity.valuation.models import DEFAULT_MODEL, MODELS

VALUATION_DIR = DATA_DIR / "valuation"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a property valuation model")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))
    args = parser.parse_args()

    df = load_training_frame()
    test_year = int(df["year"].max())
    train, test = df[df["year"] < test_year], df[df["year"] == test_year]
    print(f"train: {len(train):,} sales (≤{test_year - 1})  test: {len(test):,} sales ({test_year})")

    model = MODELS[args.model]()
    model.fit(train)

    pred = model.predict(test)
    err = pred - test[TARGET].to_numpy()
    mae = float(np.mean(np.abs(err)))
    mape = float(np.mean(np.abs(err) / test[TARGET].to_numpy())) * 100
    median_ape = float(np.median(np.abs(err) / test[TARGET].to_numpy())) * 100
    metrics = {"mae_eur_m2": round(mae), "mape_pct": round(mape, 1),
               "median_ape_pct": round(median_ape, 1), "n_test": len(test), "test_year": test_year}
    print("metrics:", metrics)

    out_dir = VALUATION_DIR / args.model
    model.save(out_dir)
    fingerprint = hashlib.sha256(
        f"{len(df)}|{df['sold_on'].max()}|{df['tx_id'].iloc[:100].str.cat()}".encode()
    ).hexdigest()
    manifest = {
        "model": args.model,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": ALL_FEATURES,
        "target": TARGET,
        "train_rows": len(train),
        "metrics": metrics,
        "data_fingerprint": fingerprint,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"artifact: {out_dir}")


if __name__ == "__main__":
    main()
