"""Valuation models behind one swappable interface.

Every model implements ValuationModel (fit / predict / explain / save / load)
and is registered in MODELS. The rest of the system — training CLI, appraisal
API, dashboard — only ever talks to the interface, so replacing ridge
regression with gradient boosting, a GNN over the ontology, or an external
oracle is a one-file change plus a registry entry.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from smartcity.valuation.features import (
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET,
)


class ValuationModel(ABC):
    """Contract every valuation algorithm must satisfy."""

    name: str = "abstract"

    @abstractmethod
    def fit(self, df: pd.DataFrame) -> None:
        """Train on a frame containing ALL_FEATURES + TARGET."""

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predicted EUR/m2 for each row (same feature columns as fit)."""

    @abstractmethod
    def explain(self, x: dict) -> list[dict]:
        """Per-driver breakdown for one feature dict: [{driver, detail, effect_pct}]."""

    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, out_dir / "model.joblib")

    @staticmethod
    def load(out_dir: Path) -> "ValuationModel":
        return joblib.load(out_dir / "model.joblib")


class ComparablesBaseline(ValuationModel):
    """Median EUR/m2 of recent comparable sales in the same zone — the honest
    floor every fancier model must beat."""

    name = "comparables"
    RECENT_YEARS = 2

    def fit(self, df: pd.DataFrame) -> None:
        recent = df[df["year"] >= df["year"].max() - self.RECENT_YEARS]
        self.table_ = recent.groupby(["zone", "property_type"])[TARGET].agg(["median", "count"])
        self.zone_table_ = recent.groupby("zone")[TARGET].median()
        self.global_ = float(recent[TARGET].median())

    def _lookup(self, zone: str, ptype: str) -> tuple[float, str]:
        if (zone, ptype) in self.table_.index:
            row = self.table_.loc[(zone, ptype)]
            return float(row["median"]), f"{int(row['count'])} comparable sales in zone"
        if zone in self.zone_table_.index:
            return float(self.zone_table_.loc[zone]), "zone median (all property types)"
        return self.global_, "citywide median (no zone comparables)"

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.array([self._lookup(r["zone"], r["property_type"])[0] for _, r in X.iterrows()])

    def explain(self, x: dict) -> list[dict]:
        value, basis = self._lookup(x["zone"], x["property_type"])
        return [{"driver": "comparables", "detail": basis, "effect_pct": None,
                 "anchor_price_m2": round(value)}]


class HedonicRidge(ValuationModel):
    """Transparent hedonic regression: ridge on log(EUR/m2) with zone and
    property-type effects plus the ontology-derived numeric features."""

    name = "hedonic_ridge"

    def fit(self, df: pd.DataFrame) -> None:
        from sklearn.compose import ColumnTransformer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        self.pre_ = ColumnTransformer([
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ])
        self.pipe_ = Pipeline([("pre", self.pre_), ("ridge", Ridge(alpha=1.0))])
        self.pipe_.fit(df[ALL_FEATURES], np.log(df[TARGET]))
        self.num_medians_ = df[NUMERIC_FEATURES].median().to_dict()
        self.feature_names_ = self.pipe_.named_steps["pre"].get_feature_names_out()
        self.coefs_ = self.pipe_.named_steps["ridge"].coef_

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        X = X.copy()
        for col, med in self.num_medians_.items():
            X[col] = pd.to_numeric(X[col], errors="coerce").fillna(med)
        return np.exp(self.pipe_.predict(X[ALL_FEATURES]))

    def explain(self, x: dict) -> list[dict]:
        """Approximate per-driver effect: coefficient x standardized deviation
        from the market median, as a % impact on EUR/m2."""
        scaler = self.pipe_.named_steps["pre"].named_transformers_["num"]
        out = []
        for i, col in enumerate(NUMERIC_FEATURES):
            val = x.get(col)
            if val is None:
                continue
            z = (float(val) - scaler.mean_[i]) / scaler.scale_[i]
            coef = self.coefs_[list(self.feature_names_).index(f"num__{col}")]
            effect = (np.exp(coef * z) - 1) * 100
            out.append({"driver": col, "detail": f"{val} vs market median {round(self.num_medians_[col], 1)}",
                        "effect_pct": round(float(effect), 1)})
        for col in CATEGORICAL_FEATURES:
            fname = f"cat__{col}_{x.get(col)}"
            if fname in self.feature_names_:
                coef = self.coefs_[list(self.feature_names_).index(fname)]
                out.append({"driver": f"{col}={x.get(col)}", "detail": "fixed effect",
                            "effect_pct": round(float((np.exp(coef) - 1) * 100), 1)})
        out.sort(key=lambda d: -abs(d["effect_pct"] or 0))
        return out


MODELS: dict[str, type[ValuationModel]] = {
    ComparablesBaseline.name: ComparablesBaseline,
    HedonicRidge.name: HedonicRidge,
}
DEFAULT_MODEL = HedonicRidge.name
