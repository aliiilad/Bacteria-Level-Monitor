#!/usr/bin/env python3
"""End-to-end pipeline for the Oahu Water Quality Predictor.

Automates the workflow in notebooks/U02_L050_LRProject.ipynb (Parts 3-7) as a
single non-interactive script: it reads the two raw exports, cleans and labels
the samples, filters to the training beaches, joins antecedent-weather features
with no future leakage, writes the processed tables, then fits the baseline and
the two linear-regression models by hand-written gradient descent and prints the
evaluation table with weights in real units.

Run from the repo root:
    python scripts/build_dataset.py
    python scripts/build_dataset.py --raw-dir data/raw --out-dir data/processed

Inputs  (data/raw/):   surfrider_raw.csv, weather_openmeteo_raw.csv
Outputs (data/processed/): samples.csv, samples_beaches.csv,
                           samples_beaches_weather.csv, beaches.csv
        (models/):         model.json — the app model, read by ui/app.py
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

# The 9 swim beaches we train on, and each beach's nearest Open-Meteo grid cell.
BEACH_SITE_IDS = [858, 859, 776, 861, 777, 8894, 780, 1197, 8916]
SITE_TO_LOC = {858: 2, 859: 3, 776: 4, 861: 5, 777: 0, 8894: 1, 780: 6, 1197: 6, 8916: 8}
UNSAFE_THRESHOLD = 130  # Hawaii DOH: enterococcus > 130 MPN/100 mL is unsafe
WEATHER_COLS = ["rain_same_day", "rain_prev_7days", "days_since_rain", "temp_mean", "wind_max"]
# The app model only uses inputs the app can get from the Open-Meteo forecast before the
# day starts: no tide (not in the forecast) and no same-day rain (not known yet).
APP_FEATURES = ["rain_prev_7days", "days_since_rain", "temp_mean", "wind_max"]
TEST_FROM_YEAR = 2025  # time-based split: train 2018-2024, test 2025-2026


# --------------------------------------------------------------------------- #
# Part 3 — clean the raw Surfrider export into labeled samples
# --------------------------------------------------------------------------- #
def clean_samples(raw_path: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_path)
    keep = {
        "sample id": "sample_id", "site id": "site_id", "site name": "site_name",
        "latitude": "latitude", "longitude": "longitude", "collection date": "date",
        "stored collectionTime": "datetime_utc",
        "Enterococcus (mpn/100mL)": "enterococcus", "Enterococcus modifier": "ent_modifier",
        "tide": "tide",
    }
    s = df[list(keep)].rename(columns=keep)
    s = s[s["enterococcus"].notna()].copy()          # drop rows with no bacteria reading
    # same site + date + count = one sample entered twice (notebook Part 3a); different counts
    # on the same day are real replicate measurements and are kept
    s = s[~s.duplicated(["site_id", "date", "enterococcus"])]
    s["enterococcus"] = pd.to_numeric(s["enterococcus"], errors="coerce").astype(int)
    s["date"] = pd.to_datetime(s["date"], format="mixed").dt.strftime("%Y-%m-%d")
    s["unsafe"] = (s["enterococcus"] > UNSAFE_THRESHOLD).astype(int)
    return s[["sample_id", "site_id", "site_name", "latitude", "longitude",
              "date", "datetime_utc", "enterococcus", "ent_modifier", "tide", "unsafe"]]


# --------------------------------------------------------------------------- #
# Part 4.1 — filter to the swim-beach training scope
# --------------------------------------------------------------------------- #
def filter_beaches(samples: pd.DataFrame) -> pd.DataFrame:
    year = samples["date"].str[:4].astype(int)
    keep = samples["site_id"].isin(BEACH_SITE_IDS) & (year >= 2018)
    return samples[keep].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Part 4.2/4.3 — parse Open-Meteo, join antecedent-weather features (no leakage)
# --------------------------------------------------------------------------- #
def load_daily_weather(weather_path: Path) -> dict[int, pd.DataFrame]:
    """Return {location_id: daily DataFrame indexed by date} with a dry-day streak."""
    lines = weather_path.read_text(encoding="utf-8").splitlines()
    blank = lines.index("")                          # metadata block, blank line, then series
    daily = pd.read_csv(io.StringIO("\n".join(lines[blank + 1:])))
    daily.columns = [c.split(" (")[0] for c in daily.columns]    # 'rain_sum (mm)' -> 'rain_sum'
    daily = daily.rename(columns={"rain_sum": "rain", "temperature_2m_mean": "temp",
                                  "wind_speed_10m_max": "wind"})
    daily["time"] = pd.to_datetime(daily["time"])
    daily = daily.sort_values(["location_id", "time"]).reset_index(drop=True)
    # consecutive dry days (rain < 1 mm): resets to 0 on each rainy day
    daily["dry"] = daily["rain"] < 1.0
    daily["_grp"] = (~daily["dry"]).groupby(daily.location_id).cumsum()
    daily["dry_streak"] = daily.groupby(["location_id", "_grp"]).cumcount()
    return {lid: g.set_index("time").sort_index() for lid, g in daily.groupby("location_id")}


def load_weather_points(weather_path: Path) -> dict[int, list[float]]:
    """Return {location_id: [lat, lon]} from the metadata block above the daily series."""
    lines = weather_path.read_text(encoding="utf-8").splitlines()
    meta = pd.read_csv(io.StringIO("\n".join(lines[:lines.index("")])))
    return {int(r.location_id): [float(r.latitude), float(r.longitude)] for r in meta.itertuples()}


def join_weather(samples_beaches: pd.DataFrame, by_loc: dict) -> pd.DataFrame:
    def features(site_id, date):
        g = by_loc[SITE_TO_LOC[int(site_id)]]
        d = pd.Timestamp(date)
        ym1 = d - pd.Timedelta(days=1)
        same = g.loc[d] if d in g.index else None
        prev7 = g.loc[d - pd.Timedelta(days=7):ym1]          # only days strictly before d
        return pd.Series({
            "rain_same_day": same.rain if same is not None else np.nan,
            "rain_prev_7days": round(prev7.rain.sum(), 1),
            "days_since_rain": float(g.loc[ym1, "dry_streak"]) if ym1 in g.index else np.nan,
            "temp_mean": same.temp if same is not None else np.nan,
            "wind_max": same.wind if same is not None else np.nan,
        })
    feats = samples_beaches.apply(lambda r: features(r.site_id, r.date), axis=1)
    return pd.concat([samples_beaches, feats], axis=1)


# --------------------------------------------------------------------------- #
# Part 4.4 — per-beach reference table
# --------------------------------------------------------------------------- #
def build_beaches_table(samples_beaches: pd.DataFrame, existing: Path | None) -> pd.DataFrame:
    sb = samples_beaches.copy()
    sb["year"] = sb["date"].str[:4].astype(int)
    agg = (sb.groupby("site_id")
             .agg(latitude=("latitude", "first"), longitude=("longitude", "first"),
                  n_samples=("unsafe", "size"), n_unsafe=("unsafe", "sum"),
                  first_year=("year", "min"), last_year=("year", "max"))
             .reset_index())
    agg["unsafe_pct"] = (agg["n_unsafe"] / agg["n_samples"] * 100).round(1)
    # The descriptive labels (beach_name, region, full_site_name) are editorial —
    # reuse them from the committed beaches.csv if it is available.
    if existing and existing.exists():
        labels = pd.read_csv(existing)[["site_id", "beach_name", "region", "full_site_name"]]
        agg = labels.merge(agg, on="site_id", how="right")
    return agg


# --------------------------------------------------------------------------- #
# Part 4.5 — encode, scale, build X_train_A / X_train_B and y
# --------------------------------------------------------------------------- #
def build_matrices(sbw: pd.DataFrame):
    model_df = sbw.dropna(subset=WEATHER_COLS + ["tide"]).copy()
    y = np.log1p(model_df["enterococcus"].to_numpy(dtype=float))
    X_site = pd.get_dummies(model_df[["site_id"]].astype(str), drop_first=True)
    X_tide = pd.get_dummies(model_df[["tide"]], prefix="tide", drop_first=True)
    cont = ["rain_same_day", "days_since_rain", "temp_mean", "wind_max"]   # A: no engineered feature
    X_A = pd.concat([X_site, X_tide, model_df[cont]], axis=1)
    X_B = pd.concat([X_site, X_tide, model_df[cont + ["rain_prev_7days"]]], axis=1)  # B: + engineered
    scale_cols = cont + ["rain_prev_7days"]
    mu, sigma = model_df[scale_cols].mean(), model_df[scale_cols].std()
    for X in (X_A, X_B):
        for c in [c for c in scale_cols if c in X]:
            X[c] = (X[c] - mu[c]) / sigma[c]
    return X_A, X_B, y, mu, sigma, scale_cols


# --------------------------------------------------------------------------- #
# Part 5 — gradient descent (hand-written, vectorized)
# --------------------------------------------------------------------------- #
def compute_cost(X, y, w, b):
    err = X @ w + b - y
    return (err @ err) / (2 * X.shape[0])


def compute_gradient(X, y, w, b):
    err = X @ w + b - y
    return (X.T @ err) / X.shape[0], err.mean()


def gradient_descent(X, y, w_in, b_in, alpha, num_iters):
    w = w_in.astype(float).copy()
    b = float(b_in)
    J_history = []
    for _ in range(num_iters):
        dj_dw, dj_db = compute_gradient(X, y, w, b)
        w = w - alpha * dj_dw
        b = b - alpha * dj_db
        J_history.append(compute_cost(X, y, w, b))
    return w, b, J_history


# --------------------------------------------------------------------------- #
# Parts 6 & 7 — fit the three models and report
# --------------------------------------------------------------------------- #
def train_and_report(X_A, X_B, y, mu, sigma, scale_cols, alpha, num_iters):
    XA, XB = X_A.to_numpy(dtype=float), X_B.to_numpy(dtype=float)
    baseline_J = ((y - y.mean()) ** 2).mean() / 2
    wA, bA, _ = gradient_descent(XA, y, np.zeros(XA.shape[1]), 0.0, alpha, num_iters)
    wB, bB, _ = gradient_descent(XB, y, np.zeros(XB.shape[1]), 0.0, alpha, num_iters)
    JA, JB = compute_cost(XA, y, wA, bA), compute_cost(XB, y, wB, bB)

    print("\n=== Part 6/7 — model evaluation (training cost) ===")
    print(f"{'model':10s} {'features':22s} {'J':>8s} {'cost removed':>14s}")
    for name, feats, J in [("Baseline", "none", baseline_J),
                           ("Model A", "original only", JA),
                           ("Model B", "original + engineered", JB)]:
        print(f"{name:10s} {feats:22s} {J:8.4f} {1 - J / baseline_J:14.4f}")

    print("\n=== Model B weights in real units (reference = dropped dummy level) ===")
    for name, wv in zip(X_B.columns, wB):
        if name in scale_cols:
            per_unit = wv / sigma[name]                     # undo standardization
            print(f"  {name:16s}: +1 unit -> x{np.exp(per_unit):.3f} on the bacteria count")
        else:
            print(f"  {name:16s}: this level vs reference -> x{np.exp(wv):.3f} on the count")
    print(f"  intercept b = {bB:.3f}")
    return {"baseline_J": baseline_J, "JA": JA, "JB": JB}


# --------------------------------------------------------------------------- #
# Part 8 — the app model: time-split fit, evaluation, export to model.json
# --------------------------------------------------------------------------- #
def normal_cdf(z):
    return 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))


def risk_from_log_count(y_hat, sd):
    """P(enterococcus > 130) when ln(1 + count) ~ Normal(y_hat, sd)."""
    return 1 - normal_cdf((math.log1p(UNSAFE_THRESHOLD) - y_hat) / sd)


def roc_auc(labels, scores):
    """Chance a random unsafe sample scores higher than a random safe one (ties count 1/2)."""
    pos, neg = scores[labels == 1], scores[labels == 0]
    greater = (pos[:, None] > neg[None, :]).sum()
    ties = (pos[:, None] == neg[None, :]).sum()
    return (greater + 0.5 * ties) / (len(pos) * len(neg))


def train_app_model(sbw: pd.DataFrame, points: dict, alpha, num_iters) -> dict:
    df = sbw.dropna(subset=APP_FEATURES).copy()
    is_test = df["date"].str[:4].astype(int) >= TEST_FROM_YEAR
    train, test = df[~is_test], df[is_test]

    sites = sorted(df["site_id"].unique())
    ref_site = sites[0]                              # reference level, offset 0

    def design(part, mu, spread):
        X_site = np.column_stack([(part["site_id"] == s).to_numpy(float) for s in sites[1:]])
        X_cont = ((part[APP_FEATURES] - mu) / spread).to_numpy(float)
        return np.hstack([X_site, X_cont])

    mu, spread = train[APP_FEATURES].mean(), train[APP_FEATURES].std()
    X_tr, X_te = design(train, mu, spread), design(test, mu, spread)
    y_tr = np.log1p(train["enterococcus"].to_numpy(float))
    w, b, _ = gradient_descent(X_tr, y_tr, np.zeros(X_tr.shape[1]), 0.0, alpha, num_iters)
    sd = float(np.std(y_tr - (X_tr @ w + b)))        # spread of training residuals

    labels = test["unsafe"].to_numpy()
    risk = risk_from_log_count(X_te @ w + b, sd)
    auc = roc_auc(labels, risk)
    print(f"train {len(train)} samples | test {len(test)} samples, {labels.sum()} unsafe | "
          f"residual sd {sd:.3f} | test AUC {auc:.3f}")
    metrics = {}
    for cut in (0.3, 0.5):
        flag = risk >= cut
        recall = (flag & (labels == 1)).sum() / labels.sum()
        precision = (flag & (labels == 1)).sum() / max(flag.sum(), 1)
        metrics[f"flag_at_{int(cut * 100)}"] = {"recall": round(float(recall), 3),
                                                "precision": round(float(precision), 3)}
        print(f"  flag at {cut:.0%}: caught {recall:.0%} of unsafe, {precision:.0%} of flags were unsafe")

    n_sites = len(sites) - 1
    return {
        "description": "Linear regression on ln(1 + enterococcus), fit by hand-written "
                       "gradient descent. risk = 1 - Phi((ln(131) - y_hat) / residual_sd).",
        "target": "ln(1 + enterococcus MPN/100 mL)",
        "unsafe_threshold": UNSAFE_THRESHOLD,
        "train_years": [int(train["date"].min()[:4]), int(train["date"].max()[:4])],
        "intercept": float(b),
        "reference_site_id": int(ref_site),
        "site_offsets": {str(int(s)): (0.0 if s == ref_site else float(w[i - 1]))
                         for i, s in enumerate(sites)},
        "features": {f: {"weight": float(w[n_sites + i]), "mean": float(mu[f]),
                         "spread": float(spread[f]), "min": float(train[f].min()),
                         "max": float(train[f].max())}
                     for i, f in enumerate(APP_FEATURES)},
        "residual_sd": sd,
        # Open-Meteo grid point each beach's training weather came from; the app
        # fetches its live forecast at the same point so features match training.
        "weather_points": {str(int(s)): points[SITE_TO_LOC[int(s)]] for s in sites},
        "test": {"years": [TEST_FROM_YEAR, int(test["date"].max()[:4])], "n": int(len(test)),
                 "n_unsafe": int(labels.sum()), "auc": round(float(auc), 3), **metrics},
    }


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default="data/raw", type=Path)
    ap.add_argument("--out-dir", default="data/processed", type=Path)
    ap.add_argument("--model-out", default="models/model.json", type=Path)
    ap.add_argument("--alpha", default=0.3, type=float, help="gradient-descent learning rate")
    ap.add_argument("--iters", default=3000, type=int, help="gradient-descent iterations")
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("=== Part 3 — clean raw Surfrider export ===")
    samples = clean_samples(args.raw_dir / "surfrider_raw.csv")
    samples.to_csv(args.out_dir / "samples.csv", index=False)
    print(f"samples.csv: {samples.shape} | unsafe {samples.unsafe.mean() * 100:.1f}%")

    print("\n=== Part 4.1 — filter to 9 swim beaches (2018+) ===")
    samples_beaches = filter_beaches(samples)
    samples_beaches.to_csv(args.out_dir / "samples_beaches.csv", index=False)
    print(f"samples_beaches.csv: {samples_beaches.shape} | unsafe {samples_beaches.unsafe.mean() * 100:.1f}%")

    print("\n=== Part 4.2/4.3 — join antecedent-weather features ===")
    by_loc = load_daily_weather(args.raw_dir / "weather_openmeteo_raw.csv")
    sbw = join_weather(samples_beaches, by_loc)
    sbw.to_csv(args.out_dir / "samples_beaches_weather.csv", index=False)
    print(f"samples_beaches_weather.csv: {sbw.shape}")

    print("\n=== Part 4.4 — per-beach reference table ===")
    beaches = build_beaches_table(samples_beaches, args.out_dir / "beaches.csv")
    beaches.to_csv(args.out_dir / "beaches.csv", index=False)
    print(f"beaches.csv: {beaches.shape}")

    print("\n=== Part 4.5 — encode + scale + build X_train_A/B, y ===")
    X_A, X_B, y, mu, sigma, scale_cols = build_matrices(sbw)
    print(f"X_train_A {X_A.shape} | X_train_B {X_B.shape} | y {y.shape}")

    train_and_report(X_A, X_B, y, mu, sigma, scale_cols, args.alpha, args.iters)

    print("\n=== Part 8 — app model (time split) -> model.json ===")
    points = load_weather_points(args.raw_dir / "weather_openmeteo_raw.csv")
    model = train_app_model(sbw, points, args.alpha, args.iters)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.model_out.write_text(json.dumps(model, indent=2) + "\n")
    print(f"wrote {args.model_out}")


if __name__ == "__main__":
    main()
