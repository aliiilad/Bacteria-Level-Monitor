"""Flash-flood-warning baseline — what the state's Brown Water Advisory would have said.

For each sample, flag = 1 if an NWS warning for Oahu was active at any point in the W hours
before the sample time (interval overlap with [t - W, t]). Default W = 24h; 48h also
reported. Warning intervals come from `warnings.csv` (see fetch_warnings.py).

    python baseline.py                     # FF.W (flash flood warning), 24h + 48h
    python baseline.py --events FF.W FA.W  # looser: flash flood OR areal flood warning
    python baseline.py --per-site

Writes `baseline.csv` (sample_id + one column per window) so the flags can be joined into
training.csv or fed straight to evaluate.py alongside a model.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from evaluate import (SAMPLES_PATH, TEST_START_YEAR, THRESHOLD, evaluate_scores, per_site,
                      print_report, site_base_rate_scorer, time_split)

WARNINGS_PATH = "warnings.csv"
WINDOWS_H = (24, 48)
DEFAULT_EVENTS = ("FF.W",)


def to_utc(s: pd.Series) -> pd.Series:
    """Parse ISO-8601 strings (with or without fractional seconds / 'Z') to tz-aware UTC."""
    return pd.to_datetime(s, utc=True, format="ISO8601")


def _ns(s: pd.Series) -> np.ndarray:
    """tz-aware UTC series -> naive datetime64[ns] ndarray (so numpy timedelta math works)."""
    return s.dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")


def load_warnings(path: str = WARNINGS_PATH, events=DEFAULT_EVENTS) -> pd.DataFrame:
    w = pd.read_csv(path)
    w = w[w["event"].isin(events)].copy()
    w["issue_utc"] = to_utc(w["issue_utc"])
    w["expire_utc"] = to_utc(w["expire_utc"])
    bad = w["expire_utc"] < w["issue_utc"]
    if bad.any():
        raise ValueError(f"{bad.sum()} warnings expire before they issue")
    return w.sort_values("issue_utc").reset_index(drop=True)


def warning_active_flags(sample_times: pd.Series, warnings: pd.DataFrame,
                         window_h: int) -> np.ndarray:
    """1 if any warning interval overlaps [t - window_h, t]. Strictly backward-looking —
    a warning issued after the sample never counts."""
    t = _ns(to_utc(sample_times))
    start = t - np.timedelta64(window_h, "h")
    iss = _ns(to_utc(warnings["issue_utc"]))
    exp = _ns(to_utc(warnings["expire_utc"]))
    # overlap(a, b) <=> a.start <= b.end and b.start <= a.end
    hit = (iss[None, :] <= t[:, None]) & (exp[None, :] >= start[:, None])
    return hit.any(axis=1).astype(int)


def build_baseline(samples: pd.DataFrame, warnings: pd.DataFrame,
                   windows=WINDOWS_H) -> pd.DataFrame:
    out = samples[["sample_id"]].copy()
    for w in windows:
        out[f"ff_{w}h"] = warning_active_flags(samples["datetime_utc"], warnings, w)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--samples", default=SAMPLES_PATH)
    ap.add_argument("--warnings", default=WARNINGS_PATH)
    ap.add_argument("--events", nargs="+", default=list(DEFAULT_EVENTS),
                    help="warning types that count, e.g. FF.W FA.W FA.Y")
    ap.add_argument("--windows", nargs="+", type=int, default=list(WINDOWS_H))
    ap.add_argument("--test-start-year", type=int, default=TEST_START_YEAR)
    ap.add_argument("--per-site", action="store_true")
    ap.add_argument("--out", default="baseline.csv")
    args = ap.parse_args()

    samples = pd.read_csv(args.samples, parse_dates=["date"])
    warnings = load_warnings(args.warnings, args.events)
    print(f"{len(warnings)} warnings of type {args.events} "
          f"({warnings.issue_utc.min().date()} .. {warnings.issue_utc.max().date()})\n")

    flags = build_baseline(samples, warnings, args.windows)
    flags.to_csv(args.out, index=False)
    print(f"wrote {args.out}; flag rate: "
          + ", ".join(f"{c}={flags[c].mean():.1%}" for c in flags.columns if c != "sample_id")
          + "\n")

    train, test = time_split(samples, args.test_start_year)
    test_flags = flags.set_index("sample_id").loc[test["sample_id"]]
    tag = "+".join(args.events)
    results = [evaluate_scores(test["unsafe"], test_flags[f"ff_{w}h"].to_numpy(),
                               name=f"{tag} baseline, {w}h") for w in args.windows]
    results.append(evaluate_scores(test["unsafe"], site_base_rate_scorer(train)(test),
                                   name="site base rate (no weather)"))
    print_report(results, train, test)

    if args.per_site:
        for w in args.windows:
            print(f"\nper-site — {tag} baseline, {w}h:")
            with pd.option_context("display.width", 200):
                print(per_site(test, test_flags[f"ff_{w}h"].to_numpy(), threshold=THRESHOLD)
                      .to_string(float_format="{:.2f}".format))


if __name__ == "__main__":
    main()
