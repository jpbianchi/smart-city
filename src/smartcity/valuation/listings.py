"""Build the property inventory shown in the dashboard.

  python -m smartcity.valuation.listings [--per-arrondissement 120]

Inventory = the most recent real single-dwelling DVF sales (real address,
surface, rooms, recorded price), stratified across Paris' 20 arrondissements.
For each property:

  asking_eur     the recorded DVF transaction price (real)
  fair_value_eur the valuation model's estimate as of the latest market month
  value_gap_pct  (fair - asking) / asking  -> positive = priced below fair value
  opportunity    0-100 score from five transparent components (see SCORE_WEIGHTS)
  projection     3-year base/bear/bull value from zone momentum blended with a
                 long-run anchor (indicative — assumptions shipped with the row)
  appraisal_sha  sha256 of the canonical appraisal document (tokenization seam)

All formulas live here, separate from the ML model: the model answers "what
is it worth", this module answers "is it a good investment".
"""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from smartcity.config import DATA_DIR, GOLD_DIR
from smartcity.valuation.features import ALL_FEATURES, latest_month_index, load_training_frame
from smartcity.valuation.models import DEFAULT_MODEL, ValuationModel

VALUATION_DIR = DATA_DIR / "valuation"
OUT_PATH = VALUATION_DIR / "listings.parquet"

SCORE_WEIGHTS = {
    "value_gap": 0.35,      # priced below model fair value
    "momentum": 0.25,       # zone price trend, last full year
    "accessibility": 0.20,  # metro + train proximity
    "daily_life": 0.10,     # school + park proximity, shops nearby
    "environment": 0.10,    # road-traffic burden + air quality
}
LONG_RUN_GROWTH = 0.02      # nominal Paris long-run anchor, per year
MOMENTUM_BLEND = 0.5        # weight of recent zone trend vs long-run anchor
SCENARIO_SPREAD = 0.025     # bear/bull = base -/+ 2.5 pp per year
HORIZON_YEARS = 3
MAX_PLAUSIBLE_GAP = 40.0    # % — beyond this, treat the recorded price as non-market


def arrondissement(postal_code: str) -> str:
    try:
        n = int(str(postal_code)[-2:])
    except ValueError:
        return "?"
    if str(postal_code) == "75116":
        n = 16
    return "1er" if n == 1 else f"{n}e"


def _decay(dist_m: pd.Series, scale_m: float) -> pd.Series:
    return 100 * np.exp(-dist_m.fillna(5000) / scale_m)


def _minmax_inverse(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or hi == lo:
        return pd.Series(50.0, index=s.index)
    return 100 * (hi - s) / (hi - lo)


def zone_momentum() -> pd.DataFrame:
    """YoY change of zone median EUR/m2 between the last two years, per type."""
    m = pd.read_parquet(GOLD_DIR / "zone_market")
    last = int(m["year"].max())
    a = m[m["year"] == last].set_index(["zone", "property_type"])["median_price_m2"]
    b = m[m["year"] == last - 1].set_index(["zone", "property_type"])["median_price_m2"]
    yoy = ((a / b) - 1).rename("zone_yoy").reset_index()
    return yoy


def build(per_arrondissement: int = 120, model_name: str = DEFAULT_MODEL) -> pd.DataFrame:
    model_dir = VALUATION_DIR / model_name
    model = ValuationModel.load(model_dir)
    manifest = json.loads((model_dir / "manifest.json").read_text())
    band_pct = manifest["metrics"]["median_ape_pct"]

    df = load_training_frame()
    df["arrondissement"] = df["postal_code"].map(arrondissement)
    df = df[df["address"].fillna("").str.len() > 3]

    # most recent 12 months of sales, stratified by arrondissement, deterministic
    cutoff = pd.to_datetime(df["sold_on"]).max() - pd.DateOffset(months=12)
    recent = df[pd.to_datetime(df["sold_on"]) > cutoff].copy()
    recent["_h"] = recent["tx_id"].map(lambda s: hashlib.md5(s.encode()).hexdigest())
    apartments = recent[recent["property_type"] == "Appartement"]
    sampled = (
        apartments.sort_values("_h")
        .groupby("arrondissement", group_keys=False)
        .head(per_arrondissement)
    )
    # houses are ~1% of Paris sales: keep all of them, or a stratified sample has none
    houses = recent[recent["property_type"] == "Maison"]
    inv = pd.concat([sampled, houses]).drop(columns="_h").reset_index(drop=True)

    # fair value as of the latest market month
    X = inv.copy()
    X["month_index"] = latest_month_index()
    inv["fair_price_m2"] = model.predict(X[ALL_FEATURES]).round(0)
    inv["fair_value_eur"] = (inv["fair_price_m2"] * inv["surface_m2"]).round(-3)
    inv["asking_eur"] = inv["price_eur"].round(0)
    inv["asking_price_m2"] = inv["price_m2"]
    inv["value_gap_pct"] = ((inv["fair_value_eur"] / inv["asking_eur"]) - 1) * 100
    # DVF also records non-market transfers (family sales, viager, partial
    # ownership); a recorded price this far from fair value is not a bargain.
    inv = inv[inv["value_gap_pct"].between(-MAX_PLAUSIBLE_GAP, MAX_PLAUSIBLE_GAP)].copy()
    X = X.loc[inv.index]
    inv = inv.reset_index(drop=True)
    X = X.reset_index(drop=True)
    inv["gap_significant"] = inv["value_gap_pct"].abs() > band_pct

    # --- opportunity components (each 0-100) -------------------------------
    inv = inv.merge(zone_momentum(), on=["zone", "property_type"], how="left")
    inv["zone_yoy"] = inv["zone_yoy"].fillna(0.0)
    comp = pd.DataFrame(index=inv.index)
    comp["value_gap"] = ((inv["value_gap_pct"].clip(-25, 25) + 25) * 2)
    comp["momentum"] = ((inv["zone_yoy"] * 100).clip(-10, 10) + 10) * 5
    comp["accessibility"] = 0.6 * _decay(inv["dist_subway_m"], 500) + 0.4 * _decay(inv["dist_train_m"], 1500)
    comp["daily_life"] = (
        0.4 * _decay(inv["dist_school_m"], 400)
        + 0.3 * _decay(inv["dist_park_m"], 400)
        + 0.3 * (inv["n_supermarkets_500m"].clip(0, 10) * 10)
    )
    comp["environment"] = 0.5 * _minmax_inverse(inv["zone_traffic_occupancy"]) + 0.5 * _minmax_inverse(inv["zone_eaqi"])
    comp = comp.clip(0, 100).round(0)
    for c in comp.columns:
        inv[f"score_{c}"] = comp[c]
    inv["opportunity_score"] = sum(comp[c] * w for c, w in SCORE_WEIGHTS.items()).round(0)
    inv["opportunity_grade"] = pd.cut(
        inv["opportunity_score"], [-1, 30, 45, 60, 75, 101], labels=["E", "D", "C", "B", "A"]
    ).astype(str)

    # --- 3-year projection -----------------------------------------------------
    g = MOMENTUM_BLEND * inv["zone_yoy"].clip(-0.08, 0.08) + (1 - MOMENTUM_BLEND) * LONG_RUN_GROWTH
    inv["growth_base_pct"] = (g * 100).round(1)
    for name, delta in (("bear", -SCENARIO_SPREAD), ("base", 0.0), ("bull", SCENARIO_SPREAD)):
        inv[f"proj_{name}_eur"] = (inv["fair_value_eur"] * (1 + g + delta) ** HORIZON_YEARS).round(-3)
    inv["proj_base_gain_pct"] = ((inv["proj_base_eur"] / inv["asking_eur"]) - 1) * 100

    # --- per-property explanation + content hash ---------------------------------
    breakdowns, hashes = [], []
    for _, r in X.iterrows():
        bd = model.explain(r[ALL_FEATURES].to_dict())
        breakdowns.append(json.dumps(bd, default=float))
    inv["drivers_json"] = breakdowns
    for _, r in inv.iterrows():
        doc = {
            "listing_id": r["tx_id"],
            "address": r["address"],
            "surface_m2": float(r["surface_m2"]),
            "fair_value_eur": float(r["fair_value_eur"]),
            "model": manifest["model"],
            "data_fingerprint": manifest["data_fingerprint"],
        }
        canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
        hashes.append(hashlib.sha256(canonical.encode()).hexdigest())
    inv["appraisal_sha256"] = hashes
    inv["model_name"] = manifest["model"]
    inv["model_median_ape_pct"] = band_pct
    inv["valuation_as_of"] = pd.to_datetime(df["sold_on"]).max().strftime("%b %Y")

    keep = [
        "tx_id", "address", "postal_code", "arrondissement", "zone", "property_type",
        "surface_m2", "rooms", "lat", "lon", "sold_on",
        "asking_eur", "asking_price_m2", "fair_value_eur", "fair_price_m2",
        "value_gap_pct", "gap_significant",
        "subway_name", "dist_subway_m", "train_name", "dist_train_m",
        "school_name", "dist_school_m", "park_name", "dist_park_m",
        "n_schools_500m", "n_parks_500m", "n_supermarkets_500m",
        "zone_traffic_occupancy", "zone_eaqi", "zone_yoy",
        "opportunity_score", "opportunity_grade",
        *[f"score_{c}" for c in SCORE_WEIGHTS],
        "growth_base_pct", "proj_bear_eur", "proj_base_eur", "proj_bull_eur", "proj_base_gain_pct",
        "drivers_json", "appraisal_sha256", "model_name", "model_median_ape_pct", "valuation_as_of",
    ]
    out = inv[keep].copy()
    VALUATION_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the valued property inventory")
    parser.add_argument("--per-arrondissement", type=int, default=120)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    out = build(args.per_arrondissement, args.model)
    print(f"{OUT_PATH}: {len(out)} properties")
    print(out["opportunity_grade"].value_counts().sort_index().to_string())
    print(f"undervalued beyond model error: {int((out['gap_significant'] & (out['value_gap_pct'] > 0)).sum())}")


if __name__ == "__main__":
    main()
