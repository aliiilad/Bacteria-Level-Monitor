# Working Plan — Oahu Water Quality Predictor

Working plan for the Congressional App Challenge entry. Project context lives in
[`CLAUDE.md`](./CLAUDE.md); this file tracks **what we're doing, who's doing it, and in what
order.** Right now we are building the **model only** — the Streamlit app comes later.

## Current status
- [x] BWTF Oahu data downloaded (report 44 export).
- [x] `samples.csv` built — one row per sample, labeled. **3,678 rows, 32.9% unsafe,
      2001–2026, 64 sites.**
- [x] Pick the beaches + year range to train on. **Done — see "Selected beaches" below.**
- [x] Evaluation harness — `evaluate.py`. **Test window widened to 2024–2026** (see
      "Evaluation harness" below).
- [ ] **Freeze the feature-column list** — proposal below under "Next moves", awaiting
      Person B's yes/no.
- [ ] Weather join → `training.csv`. **Person B — status unknown as of 2026-09-09.**
- [x] Flash-flood-warning baseline — `baseline.py` + `warnings.csv`. **Number to beat:
      recall 0.09 / precision 0.71 (24h)** — see "Flash-flood baseline" below.
- [ ] First classifier + evaluation vs. baseline.
- [ ] Merge `claude/wizardly-darwin-l9bj9n` into `main` (open a PR) — `main` has none of the
      harness / baseline work.
- [ ] (later) Streamlit app.

## Next moves (written 2026-09-09, end of day)
**Where we are:** both Person-A tasks are done (harness + baseline). The number to beat is
**recall 0.09 / precision 0.71** (see "Flash-flood baseline"). Everything now waits on
**`training.csv`**, which is Person B's weather join. Person A is free.

### Three decisions needed first (a minute each)
1. **Person B — has the NOAA rainfall join started? Yes / no.** If no, Person A takes it
   (it's the critical path; see "If Person A takes the rainfall join" below).
2. **Freeze the feature-column list.** Proposed v1 — all computable from one NOAA daily
   rainfall station plus `samples.csv`:

   | column | type | meaning |
   |---|---|---|
   | `site_id` | categorical | which beach (from `samples.csv`) |
   | `rain_24h`, `rain_48h`, `rain_72h`, `rain_7d` | mm | cumulative rainfall in the window ending the local day *before* the sample date — strictly pre-sample, no leakage |
   | `days_since_rain_gt_10mm` | int | dry-spell length; captures "first flush" after a dry stretch |
   | `month` | int 1–12 | season / trade-wind vs. Kona storm regime |
   | `ff_24h` | 0/1 | the flash-flood-warning flag from `baseline.csv` — the state's signal as a feature |
   | `unsafe` | 0/1 | **label** |

   Keep `sample_id`, `date`, `datetime_utc` as pass-through columns for joining and
   splitting. **Deferred to v2:** temp, tide, wave height, wind, nearest-station-per-beach.
   Yes / no / edits → then this table becomes the contract and gets moved to "The shared
   interfaces".
3. **Merge the branch into `main`?** Recommend opening a PR so the history is reviewable.

### Person A — next unblocked moves (pick in order)
- **`train.py` skeleton, now, against a dummy `training.csv`.** Reads `training.csv`, uses
  `evaluate.time_split`, fits `HistGradientBoostingClassifier` + logistic regression on the
  frozen columns, saves `model.pkl`, prints the harness table with the flash-flood baseline
  and site-base-rate rows alongside, plus `recall_at_precision` at 0.71. When the real
  `training.csv` lands, one command produces the checkpoint-3 comparison table.
- **If Person A takes the rainfall join** (decision 1 = "no"): pull NOAA GHCN-Daily for a
  Honolulu station (start: Honolulu Intl Airport `USW00022521`; daily `PRCP` in tenths of
  mm). Keyless CSV download at
  `https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00022521.csv`
  (or `https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/USW00022521.csv.gz`) —
  unverified from the sandbox, run locally like `fetch_warnings.py`. Then a `features.py`
  that emits `training.csv` with the v1 columns. One station is coarse for an island with
  Oahu's rainfall gradient; nearest-station-per-beach is the v2 upgrade.
- **Side actions (non-technical, any time):** confirm the exact 2026 CAC deadline and that
  our district is hosting (congressionalappchallenge.us); email the Surfrider Oahu BWTF
  coordinator (contact on the report page).

### Person B — what to know before building the join
- Use `evaluate.time_split` for any split; never touch 2024+ while designing features.
- **Gotcha:** `datetime_utc` mixes `...:00Z` and `...:00.000Z` — parse with
  `pd.to_datetime(..., utc=True, format="ISO8601")` or it errors. pandas 3 also returns
  tz-aware timestamps as object arrays; `baseline.py`'s `to_utc` / `_ns` helpers show the fix.
- Rainfall windows must end *before* the sample, using `datetime_utc` (samples are ~8–10am
  HST, so "the day before" in local time is the safe cut).
- The `ff_24h` column comes from `baseline.csv` (`sample_id` join key) — don't recompute it.

## Selected beaches (training scope)
**Decision:** train on **swimming beaches only** (excluding stream mouths, boat ramps, canals,
and sensor points, even though several of those are the biggest bacteria hotspots). The app
predicts *ocean swim safety*, so the training sites should be places people actually swim.
Filtered set lives in **`samples_beaches.csv`** (same schema as `samples.csv`).

- **Year range: 2018+.** Pre-2018 is sparse and gappy (~92 samples total across 2001–2016);
  2018 onward is ~180–560 samples/yr. Each site simply starts when its record starts.
- **9 sampling points across 7–8 popular beaches, all four regions**, chosen for sample count,
  coverage through 2025–2026 (so the time-split has recent test data), and a spread of risk
  levels so the single "site"-aware model has both safe and unsafe examples to learn from:

  | Beach (region) | n (2018+) | unsafe % |
  |---|---|---|
  | Kahaluʻu Beach (East) | 183 | 87% |
  | Magic Island / Ala Moana — Canoe Launch (South) | 167 | 40% |
  | Magic Island / Ala Moana — Bowls (South) | 167 | 17% |
  | Waialae Beach Park (South) | 146 | 27% |
  | Kaʻalāwai / Cromwell's (South) | 163 | 10% |
  | Pūpūkea tidepools / Shark's Cove (North) | 162 | 11% |
  | Kaiaka Bay (North) | 91 | 42% |
  | Kailua Beach Park (East) | 111 | 8% |
  | Pōkaʻi Bay – Inside (West) | 77 | 7% |

  **Totals: 1,267 samples, 29.9% unsafe.** Time split (decided, see "Evaluation harness"):
  train (2018–2023) 785 samples / 242 unsafe; test (2024–2026) 482 samples / 137 unsafe.

- **Count: sticking with these 9 for now; may adjust the number later.** Candidate additional
  swim beaches if we want more (all excluded for now): Wailupe Beach Park (S, 127/18%) and
  Pililāʻau (W, 46/13%) are the clean adds; South Kāneʻohe Bay + Kaimalino (Windward, ~25%)
  and Chocolates (N surf break, 66%) carry more signal but stretch the "swim beach" label.

- **Notes / honest limits:**
  - Magic Island Bowls + Canoe Launch are two sampling points at the *same* place (Ala Moana);
    keep both for signal, but present them as one beach on the app map.
  - Recent-year unsafe counts are thin for the low-risk beaches — with a 2024–2026 test
    window it's still only Pūpūkea 3, Pōkaʻi 3, Cromwell's 4, Kailua 6, Waialae 8. Recall/AUC
    on the test split lean on Kahaluʻu (58 of the 137 test positives), Canoe Launch (22) and
    Kaiaka (21). Always read the per-site table (`--per-site`) alongside the headline number.
  - West side (Pōkaʻi) is the thinnest and lowest-risk; kept only for island-wide map coverage.
    Drop it if it drags the model.

- **Reference table:** `beaches.csv` — one row per selected beach (site_id, beach_name,
  region, full_site_name, lat/lon, n_samples, n_unsafe, unsafe_pct, first_year, last_year).
  A compact lookup for the app map/markers and a human-readable summary of the pick.

## The shared interfaces
Everything the two of us hand back and forth is one of these three files. Agree on their
columns before diverging, and don't change a schema without telling the other person.

1. **`samples.csv`** — one row per BWTF sample. *Done.*
   `sample_id, site_id, site_name, latitude, longitude, date, datetime_utc,
   enterococcus, ent_modifier, unsafe`
   `unsafe = 1` when enterococcus > 130 MPN/100 mL (Hawaii DOH). `date` is the local
   Honolulu collection date (join key); `datetime_utc` is the exact timestamp (use it to
   guarantee weather features come strictly *before* the sample).
2. **feature-column list** — the agreed set of model input columns. Freeze this early.
3. **`training.csv`** — `samples.csv` + the weather feature columns. One row per sample =
   features + `unsafe`. This is what the model trains on.

## Evaluation harness (`evaluate.py`) — done
The shared scoreboard. It owns the split and the metrics so nobody re-decides them.

- **Split: train = 2018–2023, test = 2024–2026** (`TEST_START_YEAR = 2024`). Widened from
  2025+ because 2025–2026 alone left the low-risk beaches with 2–4 positives each. Test set
  is now 482 rows / 137 unsafe. Test years are off-limits for feature design and model
  selection.
- **Metrics per scorer:** recall, precision, ROC-AUC, specificity, F1, % of days flagged,
  confusion matrix (tp/fp/fn/tn), plus bootstrap 95% CIs on recall and AUC. `compare()`
  puts model and baseline(s) in one table; `per_site()` breaks recall/precision out by beach.
- **Scorer contract (for Person B and the baseline):** given the test rows, return one score
  per row — a model returns `predict_proba(X)[:, 1]`, a baseline returns 0/1 flags. Pass to
  `evaluate_scores(test.unsafe, scores, name=...)`. Default flag threshold 0.5.
- **Built-in reference scorers** (fit on train only): `site base rate` (P = that site's
  training unsafe rate — *no weather*), `always unsafe`, `random`.
- **Bar to clear, before any weather:** `python evaluate.py` gives site-base-rate
  **AUC 0.82 [0.78, 0.86], recall 0.42, precision 0.89**. Site identity alone is that
  predictive (it essentially flags Kahaluʻu every day and nothing else). The model must beat
  this *and* the flash-flood baseline, and the win has to show up on the non-Kahaluʻu sites.

## Flash-flood baseline (`baseline.py` + `fetch_warnings.py`) — done
Reconstructs what the state's Brown Water Advisory would have said on each sample day.

**Result (test set 2024–2026, 482 samples / 137 unsafe):**

| scorer | recall | precision | ROC-AUC | days flagged | tp / fp / fn |
|---|--:|--:|--:|--:|---|
| **FF.W baseline, 24h** (the state's method) | **0.09** [0.04, 0.14] | **0.71** | 0.54 | 3.5% | 12 / 5 / 125 |
| FF.W baseline, 48h | 0.15 [0.10, 0.22] | 0.70 | 0.56 | 6.2% | 21 / 9 / 116 |
| FF.W + FA.Y (flood advisories too), 48h | 0.21 | 0.55 | 0.57 | 11% | 29 / 24 / 108 |
| site base rate (no weather) | 0.42 | 0.89 | 0.82 | 13.5% | 58 / 7 / 79 |

- **Reading it:** the state's trigger is *right* when it fires — across all years, 71% of
  samples taken within 24h of a flash-flood warning were unsafe vs. 29% otherwise — but it
  fires so rarely (95 warnings in 8.5 years, ~3 h long each) that it **misses 91% of unsafe
  days.** That gap is the whole pitch. Widening to 48h or adding flood advisories buys a
  little recall at a precision cost; none of it gets past 0.21.
- **What "beat the baseline" means concretely:** the model must reach **recall well above
  0.15 while holding precision ≥ ~0.70** (use `evaluate.recall_at_precision` — it sweeps the
  model's threshold to the baseline's precision so a probability and a 0/1 flag compare
  fairly), **and** AUC > 0.82 (the site-base-rate bar), with the gain visible on the
  non-Kahaluʻu beaches. Quote the 24h number as the official comparison; show 48h as the
  generous reading.
- **Warnings data:** `warnings.csv` — 437 events for Honolulu County 2018-01 → 2026-09
  (95 Flash Flood Warnings FF.W, 342 Flood Advisories FA.Y; IEM returned no FA.W / FF.A).
  Per-year FF.W ranges 2–28. Durations median ~3 h. One zero-length FA.Y (harmless).

- **Definition:** `flag = 1` if an NWS **Flash Flood Warning (FF.W) for Oahu** was active at
  any point in the **24h before the sample time** (interval overlap with `[t − 24h, t]`,
  using `datetime_utc`; a warning issued *after* the sample never counts). **48h** is reported
  alongside. `--events FF.W FA.W FA.Y` gives a looser "any flood warning/advisory" variant.
- **Data:** `warnings.csv` (`phenomena, significance, event, issue_utc, expire_utc, wfo,
  eventid`), pulled from the Iowa Environmental Mesonet NWS VTEC archive by
  `fetch_warnings.py` (Honolulu County, UGC `HIC003`, WFO `HFO`, 2018+). Run it **locally** —
  the cloud sandbox's network policy blocks IEM/NOAA. Commit `warnings.csv` once it exists.
- **Output:** `baseline.csv` (`sample_id, ff_24h, ff_48h`) — joinable into `training.csv` and
  fed to `evaluate.py` next to the model. The script also prints the comparison table with
  the site-base-rate scorer.
- **Known limits (say them in the app):** FF.W is island-wide in our reconstruction even
  though NWS polygons can cover only part of Oahu; warnings are rare vs. ~30% unsafe
  samples, so expect high precision / low recall — that gap is the pitch.
- **Verified:** overlap logic unit-tested (inside / straddling / boundary / future-issued /
  empty) and run end-to-end on synthetic warnings.

## Who does what (both of us on the model for now)
We're both on the data & model track. It splits cleanly into two halves that meet at
`training.csv`.

### Person A — labels, baseline, evaluation — *all done; see "Next moves"*
- **Beach/year selection.** From `samples.csv`, decide the 5–8 well-sampled popular beaches
  and the year range (likely **2018+** — earlier years are sparse and have gaps). Produce
  the filtered sample set the model uses.
- **Flash-flood baseline.** *Logic done — `baseline.py`, see below. Needs `warnings.csv`.*
- **Evaluation harness.** *Done — `evaluate.py`, see above.*

### Person B — weather data + feature engineering
- **NOAA rainfall source.** Pick a station (or two) near the beaches; work out how to pull
  historical rainfall (and temp) for the sample date range.
- **The join (the hard part).** For each row in `samples.csv`, compute weather features from
  the window *before* the sample only — **no future leakage.** Priority feature:
  **antecedent rainfall (24 / 48 / 72h cumulative)**, expected to dominate. Add temp; add
  tide / wave / wind later if easy.
- **`training.csv`.** Emit `samples.csv` + feature columns. Agree the column list with
  Person A and freeze it.
- **First-cut model.** Fit `HistGradientBoostingClassifier` and logistic regression on
  `training.csv`; hand the fitted model to Person A's eval harness.

## Sequencing
1. **Together, first:** agree the frozen feature-column list. (`samples.csv` already exists.)
2. **Parallel:** A builds the baseline + eval harness; B builds the weather join + training
   table. Neither blocks the other.
3. **First checkpoint:** run B's model through A's harness against A's baseline on a
   time-based split. That one comparison table is our "does this work" answer — reached
   before writing any app code.
4. Iterate on features and model; keep the time split honest.

## Ground rules
- **No leakage.** Every weather feature is strictly pre-sample. Test years are never touched
  during feature design or model selection.
- **Time-based split, always.** No random shuffling across years. Use `evaluate.time_split`;
  don't roll your own.
- **Beat the baseline on recall / AUC**, and be honest about limits (biweekly sampling
  under-represents storm days; small dataset).
- **Disclose AI-tool use** (CAC rule); the code must be genuinely ours.

## Later (not started)
- Streamlit app: beach map, live weather fetch, risk gauge, plain-language "why",
  limitations note. Built against a dummy model first, then wired to the saved `model.pkl`.
- Deploy to Streamlit Community Cloud for a public URL.
- Side action: email the Surfrider Oahu BWTF coordinator (helps the CAC "inspiration"
  answer, may unlock cleaner data).
