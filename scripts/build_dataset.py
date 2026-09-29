#!/usr/bin/env python3
"""End-to-end pipeline for the Oahu Water Quality Predictor.

Automates the workflow in notebooks/U02_L050_LRProject.ipynb (Parts 3-7) as a
single non-interactive script: it reads the two raw exports, cleans and labels
the samples, filters to the training beaches, joins antecedent-weather features
with no future leakage, writes the processed tables, then fits the baseline and
the two linear-regression models by hand-written gradient descent and prints the
evaluation table with weights in real units. Each step runs the same code as its
notebook cell; the exploratory cells (Part 2, 3b-ii, 3b-iii, 4.2b, 4.3b) and the
plots stay in the notebook only.

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
# The app model only uses inputs the app can get from the Open-Meteo forecast before the
# day starts: no tide (not in the forecast) and no same-day rain (not known yet).
APP_FEATURES = ["rain_prev_7days", "days_since_rain", "temp_mean", "wind_max"]
TEST_FROM_YEAR = 2025  # time-based split: train 2018-2024, test 2025-2026


# --------------------------------------------------------------------------- #
# Part 3 — clean the raw Surfrider export into labeled samples
# --------------------------------------------------------------------------- #
def clean_samples(raw_path: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_path)

    # --- 3a Duplicates ---
    print("Exact duplicate rows:", df.duplicated().sum())
    print("Duplicate sample ids:", df["sample id"].duplicated().sum())
    # every row gets its own random sample id, so look for the same site on the same day instead
    lab = df[df["Enterococcus (mpn/100mL)"].notna()]
    same_day = lab[lab.duplicated(["site id", "collection date"], keep=False)]
    print("Rows sharing a site + date with another row:", len(same_day),
          "in", same_day.groupby(["site id", "collection date"]).ngroups, "groups")
    # same count = ONE sample entered twice -> drop the extra copy;
    # different counts = two REAL measurements -> keep both
    entered_twice = lab.duplicated(["site id", "collection date", "Enterococcus (mpn/100mL)"])
    df = df.drop(entered_twice[entered_twice].index)
    print("Dropped", int(entered_twice.sum()), "double-entered rows ->", df.shape)

    # --- 3b Missing values: keep the columns we use, drop rows with no bacteria reading ---
    keep = {
        "sample id": "sample_id", "site id": "site_id", "site name": "site_name",
        "latitude": "latitude", "longitude": "longitude", "collection date": "date",
        "stored collectionTime": "datetime_utc",
        "Enterococcus (mpn/100mL)": "enterococcus", "Enterococcus modifier": "ent_modifier",
        "tide": "tide",
    }
    samples = df[list(keep)].rename(columns=keep)
    samples = samples[samples["enterococcus"].notna()].copy()

    # --- 3c Outliers + typing + label ---
    ent_num = pd.to_numeric(samples["enterococcus"], errors="coerce")
    print("Negative or zero counts:", int((ent_num <= 0).sum()))
    # '<' / '>' modifiers are detection-limit codes; kept at their reported value
    print(samples.assign(ent=ent_num).groupby("ent_modifier")["ent"].agg(["count", "min", "max"]))
    samples["enterococcus"] = ent_num.astype(int)
    samples["date"]         = pd.to_datetime(samples["date"], format="mixed").dt.strftime("%Y-%m-%d")
    samples["unsafe"]       = (samples["enterococcus"] > UNSAFE_THRESHOLD).astype(int)

    return samples[["sample_id", "site_id", "site_name", "latitude", "longitude",
                    "date", "datetime_utc", "enterococcus", "ent_modifier", "tide", "unsafe"]]


# --------------------------------------------------------------------------- #
# Part 4.1 — filter to the swim-beach training scope
# --------------------------------------------------------------------------- #
def filter_beaches(samples: pd.DataFrame) -> pd.DataFrame:
    samples = samples.copy()
    samples["year"] = samples["date"].str[:4].astype(int)
    return (samples[samples.site_id.isin(BEACH_SITE_IDS) & (samples.year >= 2018)]
            .drop(columns="year").reset_index(drop=True))


# --------------------------------------------------------------------------- #
# Part 4.2/4.3 — parse Open-Meteo, join antecedent-weather features (no leakage)
# --------------------------------------------------------------------------- #
def load_daily_weather(weather_path: Path) -> dict[int, pd.DataFrame]:
    """Return {location_id: daily DataFrame indexed by date} with a dry-day streak."""
    lines = weather_path.read_text(encoding="utf-8").splitlines()
    blank = lines.index("")                       # metadata block, blank line, then the daily series
    daily = pd.read_csv(io.StringIO("\n".join(lines[blank + 1:])))
    daily.columns = [c.split(" (")[0] for c in daily.columns]   # 'rain_sum (mm)' -> 'rain_sum'
    daily = daily.rename(columns={"rain_sum": "rain", "temperature_2m_mean": "temp",
                                  "wind_speed_10m_max": "wind"})
    daily["time"] = pd.to_datetime(daily["time"])
    # precipitation_sum = rain + snowfall and Oʻahu gets no snow, so we only ever use rain_sum
    print("rain_sum == precipitation_sum on every day:", (daily["rain"] == daily["precipitation_sum"]).all())
    daily = daily.sort_values(["location_id", "time"]).reset_index(drop=True)

    # Precompute a "consecutive dry days" streak per location (dry = rain < 1 mm).
    daily["dry"]        = daily["rain"] < 1.0
    daily["_grp"]       = (~daily["dry"]).groupby(daily.location_id).cumsum()   # new block after each rainy day
    daily["dry_streak"] = daily.groupby(["location_id", "_grp"]).cumcount()     # 0 on rainy day, 1,2,... when dry
    return {lid: g.set_index("time").sort_index() for lid, g in daily.groupby("location_id")}


def load_weather_points(weather_path: Path) -> dict[int, list[float]]:
    """Return {location_id: [lat, lon]} from the metadata block above the daily series."""
    lines = weather_path.read_text(encoding="utf-8").splitlines()
    meta = pd.read_csv(io.StringIO("\n".join(lines[:lines.index("")])))
    return {int(r.location_id): [float(r.latitude), float(r.longitude)] for r in meta.itertuples()}


def join_weather(samples_beaches: pd.DataFrame, by_loc: dict) -> pd.DataFrame:
    def weather_features(site_id, date):
        g   = by_loc[SITE_TO_LOC[int(site_id)]]
        d   = pd.Timestamp(date)
        ym1 = d - pd.Timedelta(days=1)
        same = g.loc[d] if d in g.index else None
        prev7 = g.loc[d - pd.Timedelta(days=7): ym1]           # the 7 days before the sample
        return pd.Series({
            "rain_same_day":   same.rain if same is not None else np.nan,
            "rain_prev_7days": round(prev7.rain.sum(), 1),
            "days_since_rain": float(g.loc[ym1, "dry_streak"]) if ym1 in g.index else np.nan,
            "temp_mean":       same.temp if same is not None else np.nan,
            "wind_max":        same.wind if same is not None else np.nan,
        })

    feats = samples_beaches.apply(lambda r: weather_features(r.site_id, r.date), axis=1)
    return pd.concat([samples_beaches, feats], axis=1)


# --------------------------------------------------------------------------- #
# Part 4.4 — per-beach reference table
# --------------------------------------------------------------------------- #
def build_beaches_table(samples_beaches: pd.DataFrame, existing: Path | None) -> pd.DataFrame:
    sb = samples_beaches.copy(); sb["year"] = sb.date.str[:4].astype(int)
    agg = (sb.groupby("site_id")
             .agg(latitude=("latitude", "first"), longitude=("longitude", "first"),
                  n_samples=("unsafe", "size"), n_unsafe=("unsafe", "sum"),
                  first_year=("year", "min"), last_year=("year", "max"))
             .reset_index())
    agg["unsafe_pct"] = (agg.n_unsafe / agg.n_samples * 100).round(1)
    print(agg.to_string())
    # The descriptive labels (beach_name, region, full_site_name) are editorial —
    # reuse them from the committed beaches.csv if it is available.
    if existing and existing.exists():
        labels = pd.read_csv(existing)[["site_id", "beach_name", "region", "full_site_name"]]
        agg = labels.merge(agg, on="site_id", how="right")
    return agg


# --------------------------------------------------------------------------- #
# Part 4.5 — encode, scale, build X_train_A / X_train_B and y
# --------------------------------------------------------------------------- #
def build_matrices(samples_beaches_weather: pd.DataFrame):
    # Drop rows missing any model input (weather or tide) -> consistent drop-not-impute policy.
    inputs  = ["rain_same_day", "rain_prev_7days", "days_since_rain", "temp_mean", "wind_max", "tide"]
    dropped = samples_beaches_weather[samples_beaches_weather[inputs].isna().any(axis=1)]
    model_df = samples_beaches_weather.dropna(subset=inputs).copy()
    print(f"Dropped {len(dropped)} of {len(samples_beaches_weather)} rows; missing per input:",
          dropped[inputs].isna().sum()[lambda s: s > 0].to_dict())
    print(f"mean log1p(ent): all rows {np.log1p(samples_beaches_weather.enterococcus).mean():.3f}"
          f" | kept {np.log1p(model_df.enterococcus).mean():.3f}"
          f" | dropped {np.log1p(dropped.enterococcus).mean():.3f}")

    # y is its OWN dataframe (not a column inside X), aligned to model_df's index.
    y = pd.DataFrame({"y": np.log1p(model_df["enterococcus"].to_numpy())}, index=model_df.index)

    # 4a Encode: site_id and tide are nominal -> one-hot, drop_first avoids the dummy-variable trap
    # (reference = site 1197 and tide "high").
    X_site = pd.get_dummies(model_df[["site_id"]].astype(str), drop_first=True)   # nominal
    X_tide = pd.get_dummies(model_df[["tide"]], prefix="tide", drop_first=True)   # nominal
    print(f"site_id: {model_df.site_id.nunique()} levels -> {X_site.shape[1]} columns added")
    print(f"tide   : {model_df.tide.nunique()} levels -> {X_tide.shape[1]} columns added")
    cont   = ["rain_same_day", "days_since_rain", "temp_mean", "wind_max"]        # A: without rain_prev_7days
    X_train_A = pd.concat([X_site, X_tide, model_df[cont]], axis=1)
    X_train_B = pd.concat([X_site, X_tide, model_df[cont + ["rain_prev_7days"]]], axis=1)  # B: + engineered

    # 4b Scale -- range of every column after cleaning + encoding, BEFORE scaling:
    scale_cols = cont + ["rain_prev_7days"]
    print(pd.concat([X_site, X_tide, model_df[scale_cols]], axis=1).astype(float)
            .agg(["min", "max"]).T.to_string())

    # Standardize (z-score) the continuous columns; one-hot columns stay 0/1.
    mu, sigma = model_df[scale_cols].mean(), model_df[scale_cols].std()
    for Xt in (X_train_A, X_train_B):
        for c in [c for c in scale_cols if c in Xt]:
            Xt[c] = (model_df[c] - mu[c]) / sigma[c]      # from the raw values, so re-running is safe

    # STORE the scaler's numbers: a new row must be scaled with exactly these values before predicting.
    scaler = pd.DataFrame({"mean": mu, "std": sigma})
    print("\nScaler (kept in `scaler` / `mu` / `sigma`):\n", scaler.round(3).to_string())
    print("\nAfter scaling:\n", X_train_B[scale_cols].agg(["mean", "std", "min", "max"]).T.round(2).to_string())

    # Verify the merge: same rows, aligned index, y separate.
    for name, d in [("X_train_A", X_train_A), ("X_train_B", X_train_B), ("y", y)]:
        print(f"{name}.shape = {d.shape}")
    print("Same row count & aligned index:",
          len(X_train_A) == len(X_train_B) == len(y) and X_train_A.index.equals(y.index))

    print("Correlation between the continuous inputs:")
    print(model_df[scale_cols].corr().round(2).to_string())
    return X_train_A, X_train_B, y, sigma


# --------------------------------------------------------------------------- #
# Part 5 — gradient descent (hand-written, vectorized)
# --------------------------------------------------------------------------- #
def compute_cost(X, y, w, b):
    """X (m,n), y (m,), w (n,), b float -> float"""
    m = X.shape[0]
    err = X @ w + b - y          # residual for every row at once
    return (err @ err) / (2 * m) # mean squared error, halved

def compute_gradient(X, y, w, b):
    """-> dj_dw (n,), dj_db (float)"""
    m = X.shape[0]
    err = X @ w + b - y          # (m,)
    dj_dw = (X.T @ err) / m      # (n,) — one slope per feature
    dj_db = err.mean()           # scalar
    return dj_dw, dj_db

def gradient_descent(X, y, w_in, b_in, alpha, num_iters):
    """-> w (n,), b (float), J_history (list)"""
    w = w_in.astype(float).copy()
    b = float(b_in)
    J_history = []
    for _ in range(num_iters):
        dj_dw, dj_db = compute_gradient(X, y, w, b)
        w = w - alpha * dj_dw    # step downhill on every weight
        b = b - alpha * dj_db
        J_history.append(compute_cost(X, y, w, b))
    return w, b, J_history


# --------------------------------------------------------------------------- #
# Parts 6 & 7 — fit the three models and report
# --------------------------------------------------------------------------- #
def train_and_report(X_train_A, X_train_B, y, sigma, alpha, num_iters):
    # Feature matrices as plain float arrays (one-hot columns come out as bool).
    XA = X_train_A.to_numpy(dtype=float)
    XB = X_train_B.to_numpy(dtype=float)
    y_vec = y["y"].to_numpy(dtype=float)           # target array, pulled from the y DataFrame (Part 4.5)

    # --- Baseline: NO features -> predict the mean of y for every row ---
    baseline_J = ((y_vec - y_vec.mean()) ** 2).mean() / 2

    # --- Model A: site + tide + weather, WITHOUT the engineered feature ---
    wA, bA, histA = gradient_descent(XA, y_vec, np.zeros(XA.shape[1]), 0.0,
                                     alpha=alpha, num_iters=num_iters)
    JA = compute_cost(XA, y_vec, wA, bA)

    # --- Model B: same, PLUS rain_prev_7days ---
    wB, bB, histB = gradient_descent(XB, y_vec, np.zeros(XB.shape[1]), 0.0,
                                     alpha=alpha, num_iters=num_iters)
    JB = compute_cost(XB, y_vec, wB, bB)

    print(f"baseline J = {baseline_J:.4f}")
    print(f"Model A  J = {JA:.4f}")
    print(f"Model B  J = {JB:.4f}")

    print("\nModel A weights:\n", pd.Series(wA, index=X_train_A.columns).round(3).to_string())
    print("\nModel B weights:\n", pd.Series(wB, index=X_train_B.columns).round(3).to_string())

    # J = half the mean squared error, in (log units)^2. sqrt(2J) = RMSE is back in the units of y.
    print("\n=== Part 7 — model evaluation (training cost) ===")
    rows = [("Baseline", "none",                  baseline_J),
            ("Model A",  "original only",         JA),
            ("Model B",  "original + engineered", JB)]
    print(f"{'model':10s} {'features':22s} {'J':>8s} {'cost removed':>14s} {'RMSE (y units)':>15s}")
    for name, feats, J in rows:
        print(f"{name:10s} {feats:22s} {J:8.4f} {1 - J/baseline_J:14.4f} {np.sqrt(2 * J):15.3f}")

    # Weights back in REAL units: continuous weight per real unit = w / sigma; dummies were never
    # scaled, so their weight means "this level vs. the reference level". y is log1p(count), so
    # exp(weight) is the factor the bacteria count gets multiplied by.
    units = {"rain_same_day": "mm", "days_since_rain": "day", "temp_mean": "°C",
             "wind_max": "km/h", "rain_prev_7days": "mm"}
    for name, X, w, b in [("Model A", X_train_A, wA, bA), ("Model B", X_train_B, wB, bB)]:
        print(f"\n{name}: intercept b = {b:.3f}  (reference beach and tide, average weather "
              f"-> about {np.expm1(b):.0f} MPN/100mL)")
        for col, wv in zip(X.columns, w):
            if col in units:
                per = wv / sigma[col]
                print(f"  {col:16s} {per:+.4f} per {units[col]:4s} -> count x{np.exp(per):.3f}")
            else:
                print(f"  {col:16s} {wv:+.3f} vs reference -> count x{np.exp(wv):.2f}")
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
    print("\nUnsafe % by tide within these 9 beaches:")
    print((samples_beaches.groupby("tide")["unsafe"].mean() * 100).round(1).to_string())

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
    X_train_A, X_train_B, y, sigma = build_matrices(sbw)

    print("\n=== Part 6 — fit baseline, Model A, Model B ===")
    train_and_report(X_train_A, X_train_B, y, sigma, args.alpha, args.iters)

    print("\n=== Part 8 — app model (time split) -> model.json ===")
    points = load_weather_points(args.raw_dir / "weather_openmeteo_raw.csv")
    model = train_app_model(sbw, points, args.alpha, args.iters)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.model_out.write_text(json.dumps(model, indent=2) + "\n")
    print(f"wrote {args.model_out}")


if __name__ == "__main__":
    main()
