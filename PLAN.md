# Working Plan — Oahu Water Quality Predictor

Working plan for the Congressional App Challenge entry. Project context lives in
[`CLAUDE.md`](./CLAUDE.md); this file tracks **what we're doing, who's doing it, and in what
order.** Right now we are building the **model only** — the Streamlit app comes later.

## Current status
- [x] BWTF Oahu data downloaded (report 44 export).
- [x] `samples.csv` built — one row per sample, labeled. **3,678 rows, 32.9% unsafe,
      2001–2026, 64 sites.**
- [ ] Pick the beaches + year range to train on.
- [ ] Weather join → `training.csv`.
- [ ] Flash-flood-warning baseline.
- [ ] First classifier + evaluation vs. baseline.
- [ ] (later) Streamlit app.

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

## Who does what (both of us on the model for now)
We're both on the data & model track. It splits cleanly into two halves that meet at
`training.csv`.

### Person A — labels, baseline, evaluation
- **Beach/year selection.** From `samples.csv`, decide the 5–8 well-sampled popular beaches
  and the year range (likely **2018+** — earlier years are sparse and have gaps). Produce
  the filtered sample set the model uses.
- **Flash-flood baseline.** For each sample (date + site), reconstruct whether a flash-flood
  warning / brown-water advisory was active, and score its recall / precision on `unsafe`.
  *This is the number we have to beat — build it early.* If historical NWS warnings are hard
  to pull, approximate with a heavy-rainfall threshold and document the assumption.
- **Evaluation harness.** A reusable script: takes a fitted model + test set, reports
  recall, precision, ROC-AUC, and a confusion matrix, side-by-side with the baseline, on a
  **time-based split** (older years train, recent years test).

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
- **Time-based split, always.** No random shuffling across years.
- **Beat the baseline on recall / AUC**, and be honest about limits (biweekly sampling
  under-represents storm days; small dataset).
- **Disclose AI-tool use** (CAC rule); the code must be genuinely ours.

## Later (not started)
- Streamlit app: beach map, live weather fetch, risk gauge, plain-language "why",
  limitations note. Built against a dummy model first, then wired to the saved `model.pkl`.
- Deploy to Streamlit Community Cloud for a public URL.
- Side action: email the Surfrider Oahu BWTF coordinator (helps the CAC "inspiration"
  answer, may unlock cleaner data).
