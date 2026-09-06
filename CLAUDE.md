# CLAUDE.md — Oahu Water Quality Predictor (Congressional App Challenge)

This file carries project context into any Claude Code conversation (local or cloud).
Commit it at the repo root.

## What this project is
An entry for the **Congressional App Challenge (CAC)** — a middle/high-school app
competition. The app predicts, for a given Oahu beach and day, the **probability that ocean
water is unsafe to swim in** (enterococcus fecal-indicator bacteria above the safety
threshold), from weather/environmental conditions. Trained on Surfrider **Blue Water Task
Force (BWTF)** biweekly bacteria data. Goal: beat the state's naive baseline (Brown Water
Advisory issued only when a flash-flood warning is active).

- Team: **2 people, comfortable in Python**, project just starting.
- Timeline: ~8 weeks from early Sept 2026. Confirm the exact 2026 CAC deadline and that the
  team's congressional district is hosting (congressionalappchallenge.us). 2025 deadline was
  Oct 30.
- CAC judging weights: quality of idea, implementation (UX/design), coding skill — a
  polished, usable app matters as much as model accuracy. AI-tool use allowed **but must be
  disclosed**; code must be genuinely the team's own.

## Data (confirmed accessible 2026-09-05)
- Source: **Surfrider BWTF, Oahu — report 44**: https://bwtf.surfrider.org/report/44
- Use the page's built-in **"Download Data"** export — no scraping/API keys. (Backend is AWS
  AppSync GraphQL; ignore it, the export button is the simple path.)
- Columns per sample: **Site, Date, Enterococcus (MPN/100 mL), Indication** (Low/Med/High).
- Label thresholds (site's own Key = Hawaii DOH standard): Low 0–35, Medium 36–130,
  **High >130**. So **"unsafe" = enterococcus > 130 MPN/100 mL**.
- ~24 sites, biweekly, ~500–600 samples/yr, multi-year archive (~2016–present). A few
  thousand labeled samples → **classical ML, not deep learning**.
- Biweekly lab data → download once/occasionally, NOT live. Only **weather** is live in the
  app: NOAA rainfall/temp, tides, NDBC buoys (waves/wind), NWS forecast for inference.
  **Antecedent rainfall (24/48/72h cumulative) is the dominant predictor.** Also check
  Hawaii DOH Clean Water Branch for overlapping samples.

## Decisions already made
- **Stack:** Python end-to-end. scikit-learn `HistGradientBoostingClassifier` (logistic
  regression as interpretable comparison). **Streamlit** app, deployed on Streamlit Community
  Cloud for a live public URL.
- **Model framing:** one **probabilistic classifier** → P(enterococcus > 130). The
  probability is both the **risk score (0–100% gauge)** and, thresholded, the **safe/unsafe
  flag**. Regression on the raw count is a stretch goal only.
- **Scope:** train on ~5–8 well-sampled popular Oahu beaches; single model with "site" as a
  feature; map shows all sites, "not enough data" where records are thin.
- **Evaluation:** time-based split (train older years, test recent). Compare model vs.
  reconstructed flash-flood-warning baseline on recall / precision / ROC-AUC. Success =
  beating the baseline on recall/AUC. Be honest about limits (biweekly sampling
  under-represents storm days; small dataset).

## Suggested 2-person work split
- **Person A — data & model:** BWTF export → NOAA weather join (the hard part: join weather
  in the window *before* each sample, no future leakage) → training table → classifier →
  evaluation. Saves `model.pkl`.
- **Person B — app & product:** Streamlit app (beach map, live weather fetch, risk gauge,
  plain-language "why", limitations note). Build against a dummy model first.
- Two shared interfaces: the agreed **feature-column list** and the saved **`model.pkl`**.

## Suggested build order
1. Download BWTF data, look at it: total samples, best-recorded beaches, % unsafe (>130).
2. Person A: NOAA rainfall join → `training.csv` (one row/sample = features + unsafe 0/1).
3. Person B: runnable Streamlit app with placeholder gauge, deployed to a public URL.
4. Person A: first classifier vs. flash-flood baseline on a time-based split.
5. Wire real `model.pkl` into the app → walking skeleton, then improve both halves.

Side actions: email the Surfrider Oahu BWTF coordinator (contact on the report page); it
helps the CAC "inspiration" answer and may unlock cleaner data.
