"""Evaluation harness — the shared scoreboard for every model and baseline.

Owns two things nobody else should re-decide:
  1. the TIME-BASED SPLIT (train = years before TEST_START_YEAR, test = that year onward),
  2. the METRICS we report (recall, precision, ROC-AUC, confusion matrix), model and
     baseline side by side.

Any "scorer" plugs in the same way: given the test rows, return one score per row.
  - a model returns P(unsafe) in [0, 1]  (e.g. clf.predict_proba(X)[:, 1])
  - a baseline returns 0/1 flags         (e.g. flash-flood warning active on that day)
Scores are thresholded (default 0.5) to get the safe/unsafe flag for recall/precision;
ROC-AUC uses the raw scores.

Usage from code:
    from evaluate import time_split, evaluate_scores, compare, recall_at_precision
    train, test = time_split(df)                       # df must have `date` + `unsafe`
    r_model = evaluate_scores(test.unsafe, p_model, name="HistGB")
    r_base  = evaluate_scores(test.unsafe, ff_flag,  name="Flash-flood baseline")
    print(compare([r_model, r_base]))
    # binary baseline vs probabilistic model, apples to apples: model recall at the
    # baseline's precision
    print(recall_at_precision(test.unsafe, p_model, target_precision=r_base["precision"]))

Usage from the shell (demo on samples_beaches.csv with dummy scorers):
    python evaluate.py
    python evaluate.py --test-start-year 2025 --per-site
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, roc_auc_score

# Test window = 2024–2026. Widened from 2025+ because the low-risk beaches only had 2–4
# unsafe samples in 2025–2026; 2024+ gives 482 test rows / 137 unsafe. See PLAN.md.
TEST_START_YEAR = 2024
THRESHOLD = 0.5
SAMPLES_PATH = "samples_beaches.csv"


# ---------------------------------------------------------------------------- split

def time_split(df: pd.DataFrame, test_start_year: int = TEST_START_YEAR):
    """Split on calendar year of `date`. Older years train, `test_start_year`+ test.

    Never shuffle across years — this is the only split we use.
    """
    year = pd.to_datetime(df["date"]).dt.year
    train = df[year < test_start_year].copy()
    test = df[year >= test_start_year].copy()
    if train.empty or test.empty:
        raise ValueError(f"time_split: empty side with test_start_year={test_start_year}")
    return train, test


def describe_split(train: pd.DataFrame, test: pd.DataFrame) -> str:
    def _fmt(name, d):
        yrs = pd.to_datetime(d["date"]).dt.year
        return (f"{name}: {yrs.min()}–{yrs.max()}  n={len(d)}  unsafe={int(d['unsafe'].sum())} "
                f"({d['unsafe'].mean():.1%})")
    return _fmt("train", train) + "\n" + _fmt("test ", test)


# -------------------------------------------------------------------------- metrics

def evaluate_scores(y_true, y_score, name: str = "scorer", threshold: float = THRESHOLD,
                    n_boot: int = 500, seed: int = 0) -> dict:
    """Score one scorer on one set. Returns a flat dict of metrics.

    y_true : 0/1 unsafe labels.
    y_score: P(unsafe) or 0/1 flags, same length/order as y_true.
    Bootstrap 95% CIs are reported for recall and AUC (set n_boot=0 to skip).
    """
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    if y_true.shape != y_score.shape:
        raise ValueError(f"{name}: y_true {y_true.shape} vs y_score {y_score.shape}")
    if np.isnan(y_score).any():
        raise ValueError(f"{name}: NaN in scores")

    y_pred = (y_score >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    out = {
        "scorer": name,
        "n": int(len(y_true)),
        "n_unsafe": int(y_true.sum()),
        "recall": _safe_div(tp, tp + fn),          # unsafe days we catch — the one that matters
        "precision": _safe_div(tp, tp + fp),       # when we say unsafe, how often we're right
        "specificity": _safe_div(tn, tn + fp),     # safe days we leave open
        "f1": _safe_div(2 * tp, 2 * tp + fp + fn),
        "roc_auc": _auc(y_true, y_score),
        "flagged_pct": float(y_pred.mean()),       # share of days we'd close the beach
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "threshold": threshold,
    }

    if n_boot:
        rng = np.random.default_rng(seed)
        rec, auc = [], []
        idx_all = np.arange(len(y_true))
        for _ in range(n_boot):
            idx = rng.choice(idx_all, size=len(idx_all), replace=True)
            yt, ys, yp = y_true[idx], y_score[idx], y_pred[idx]
            pos = yt == 1
            if pos.any():
                rec.append(yp[pos].mean())
            a = _auc(yt, ys)
            if a is not None:
                auc.append(a)
        out["recall_ci"] = _ci(rec)
        out["roc_auc_ci"] = _ci(auc)
    return out


def evaluate_model(model, X_test, y_test, name: str = "model", **kw) -> dict:
    """Convenience: fitted sklearn classifier with predict_proba -> evaluate_scores."""
    p = model.predict_proba(X_test)[:, 1]
    return evaluate_scores(y_test, p, name=name, **kw)


def recall_at_precision(y_true, y_score, target_precision: float) -> dict:
    """Fair model-vs-binary-baseline comparison: sweep the model's threshold and report the
    best recall it reaches while keeping precision >= target (e.g. the baseline's 0.71).
    Returns {'recall', 'precision', 'threshold', 'flagged_pct'}; recall 0 if unreachable."""
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    best = {"recall": 0.0, "precision": None, "threshold": None, "flagged_pct": 0.0}
    for thr in np.unique(y_score):
        pred = y_score >= thr
        tp = int((pred & (y_true == 1)).sum())
        prec = _safe_div(tp, int(pred.sum()))
        rec = _safe_div(tp, int(y_true.sum()))
        if prec is not None and prec >= target_precision and rec > best["recall"]:
            best = {"recall": rec, "precision": prec, "threshold": float(thr),
                    "flagged_pct": float(pred.mean())}
    return best


def per_site(test: pd.DataFrame, y_score, name: str = "scorer",
             threshold: float = THRESHOLD) -> pd.DataFrame:
    """Recall/precision per site on the test set. Beaches with few positives are noisy —
    read `n_unsafe` before trusting the row."""
    rows = []
    y_score = np.asarray(y_score, dtype=float)
    for site, g in test.groupby("site_name", sort=True):
        idx = test.index.get_indexer(g.index)
        r = evaluate_scores(g["unsafe"], y_score[idx], name=name, threshold=threshold, n_boot=0)
        rows.append({"site": site, "n": r["n"], "n_unsafe": r["n_unsafe"],
                     "recall": r["recall"], "precision": r["precision"],
                     "flagged_pct": r["flagged_pct"]})
    return pd.DataFrame(rows).set_index("site")


def compare(results: list[dict]) -> pd.DataFrame:
    """Side-by-side table, one row per scorer. Pass model + baseline(s) together."""
    cols = ["scorer", "n", "n_unsafe", "recall", "recall_ci", "precision", "roc_auc",
            "roc_auc_ci", "specificity", "f1", "flagged_pct", "tp", "fp", "fn", "tn"]
    df = pd.DataFrame(results)
    return df[[c for c in cols if c in df.columns]].set_index("scorer")


def print_report(results: list[dict], train=None, test=None) -> None:
    if train is not None and test is not None:
        print(describe_split(train, test), "\n")
    table = compare(results)
    fmt = {c: "{:.3f}".format for c in ("recall", "precision", "roc_auc", "specificity",
                                       "f1", "flagged_pct")}
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(table.to_string(formatters=fmt, na_rep="-"))


# ------------------------------------------------------------- reference scorers
# Weather-free baselines every real model must beat. Fitted on TRAIN only.

def site_base_rate_scorer(train: pd.DataFrame):
    """P(unsafe) = that site's unsafe rate in the training years. A model that can't beat
    this has learned nothing from the weather."""
    rates = train.groupby("site_id")["unsafe"].mean()
    prior = train["unsafe"].mean()
    return lambda test: test["site_id"].map(rates).fillna(prior).to_numpy()


def always_unsafe_scorer(test: pd.DataFrame):
    """Close every beach every day. Recall 1.0, precision = base rate."""
    return np.ones(len(test))


def random_scorer(test: pd.DataFrame, seed: int = 0):
    """Coin flip. AUC ~0.5; the floor."""
    return np.random.default_rng(seed).random(len(test))


# ------------------------------------------------------------------------ helpers

def _safe_div(a, b):
    return float(a) / b if b else None


def _auc(y_true, y_score):
    if len(np.unique(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, y_score))


def _ci(vals):
    if not vals:
        return None
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return f"[{lo:.2f}, {hi:.2f}]"


# ---------------------------------------------------------------------------- demo

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--samples", default=SAMPLES_PATH)
    ap.add_argument("--test-start-year", type=int, default=TEST_START_YEAR)
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--per-site", action="store_true", help="also print per-site table")
    args = ap.parse_args()

    df = pd.read_csv(args.samples, parse_dates=["date"])
    train, test = time_split(df, args.test_start_year)

    scorers = {
        "site base rate (no weather)": site_base_rate_scorer(train),
        "always unsafe": always_unsafe_scorer,
        "random": random_scorer,
    }
    results = [evaluate_scores(test["unsafe"], fn(test), name=n, threshold=args.threshold)
               for n, fn in scorers.items()]
    print_report(results, train, test)

    if args.per_site:
        print("\nper-site — site base rate (no weather):")
        with pd.option_context("display.width", 200):
            print(per_site(test, scorers["site base rate (no weather)"](test),
                           threshold=args.threshold).to_string(float_format="{:.2f}".format))


if __name__ == "__main__":
    main()
