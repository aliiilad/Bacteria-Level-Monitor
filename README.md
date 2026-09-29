# Oahu Water Quality Predictor

Predicting, for a given Oahu beach and day, the **probability that the ocean is unsafe to
swim in** — i.e. that enterococcus fecal-indicator bacteria exceed the Hawaii Department of
Health threshold (**> 130 MPN/100 mL**) — from weather and environmental conditions.

An entry for the **[Congressional App Challenge](https://www.congressionalappchallenge.us/)**.
The goal is a polished, usable app that beats the state's naive baseline (a Brown Water
Advisory issued only when a flash-flood warning is active).

> **Status: in progress.** We're building the model first; the app comes later. See
> [`PLAN.md`](./PLAN.md) for the live task list.

## Why it matters

Ocean bacteria spikes — mostly driven by rainfall washing runoff into the sea — can make
popular swimming spots unsafe for a day or two, but official advisories are coarse and lag
reality. Lab testing is only biweekly, so most days have no measurement at all. A model that
turns **live weather** into a same-day risk estimate fills that gap.

## Data

- **Source:** Surfrider Blue Water Task Force (BWTF), Oahu —
  [report 44](https://bwtf.surfrider.org/report/44), via the page's "Download Data" export.
- **Each sample:** site, date, enterococcus (MPN/100 mL), and a Low/Med/High indication.
- **Label:** `unsafe = 1` when enterococcus **> 130 MPN/100 mL** (Hawaii DOH standard).
- **Raw archive:** 3,678 samples, 2001–2026, 63 sites (32.9% unsafe).

## Selected beaches

The model trains on **9 popular swimming beaches, 2018 onward** (earlier years are too sparse).
Stream mouths, boat ramps, and canals — often the biggest bacteria hotspots — are excluded,
because the app predicts *ocean swim safety* at places people actually swim.

**1,267 samples, 29.9% unsafe**, spread across all four regions and a wide range of risk
levels. Full rationale and the per-beach table are in [`PLAN.md`](./PLAN.md).

| Beach | Region | Samples | Unsafe % |
|---|---|--:|--:|
| Kahaluʻu Beach | East | 183 | 87% |
| Magic Island – Canoe Launch (Ala Moana) | South | 167 | 40% |
| Magic Island – Bowls (Ala Moana) | South | 167 | 17% |
| Waialae Beach Park | South | 146 | 27% |
| Kaʻalāwai / Cromwell's | South | 163 | 10% |
| Pūpūkea tidepools / Shark's Cove | North | 162 | 11% |
| Kaiaka Bay | North | 91 | 42% |
| Kailua Beach Park | East | 111 | 8% |
| Pōkaʻi Bay (Inside) | West | 77 | 7% |

## Repository

| Path | What it is |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Project context (goal, data, decisions already made). |
| [`PLAN.md`](./PLAN.md) | Live working plan — tasks, ownership, shared file schemas. |
| `data/raw/surfrider_raw.csv` | Raw Surfrider BWTF export (report 44) — the unprocessed source. |
| `data/raw/weather_openmeteo_raw.csv` | Raw Open-Meteo daily weather pull (per-beach locations + daily series). |
| `data/processed/samples.csv` | One row per BWTF sample, cleaned and labeled. The full archive. |
| `data/processed/samples_beaches.csv` | `samples.csv` filtered to the 9 selected beaches (2018+). Training scope. |
| `ui/` | Streamlit app (`streamlit run ui/app.py`). `risk_model.py` scores beaches from `models/model.json` using today's Open-Meteo forecast. |
| `models/model.json` | App model: weights, feature scaling, and 2025–26 test metrics. Written by `scripts/build_dataset.py`. |
| `.streamlit/config.toml` | Dark theme that matches `ui/style.css`. |
| `data/processed/samples_beaches_weather.csv` | `samples_beaches.csv` joined with antecedent-weather features. |
| `data/processed/beaches.csv` | One row per selected beach: location, sample counts, unsafe %. Map/reference table. |
| `notebooks/` | Jupyter / Colab notebooks (EDA, cleaning, modelling). |
| `scripts/` | Reusable Python scripts — chiefly the raw → processed data pipeline. |

## Approach

- **Model:** one probabilistic classifier → P(enterococcus > 130), with "site" as a feature.
  The probability is both the risk score (0–100%) and, thresholded, the safe/unsafe flag.
  scikit-learn `HistGradientBoostingClassifier`, with logistic regression as an interpretable
  comparison. (Classical ML — the dataset is a few thousand rows, not deep-learning scale.)
- **Features:** live weather, dominated by **antecedent rainfall** (24/48/72h cumulative)
  joined strictly *before* each sample to avoid leakage; plus temp, and later tide/wave/wind.
- **Evaluation:** time-based split (train older years, test recent) comparing the model against
  the reconstructed flash-flood-warning baseline on recall, precision, and ROC-AUC.
- **App (later):** a Streamlit app — beach map, live weather fetch, risk gauge, plain-language
  "why", and an honest limitations note — deployed for a public URL.

## Roadmap

See [`PLAN.md`](./PLAN.md) for detail. In short: freeze the feature-column list → weather join
(`training.csv`) and flash-flood baseline → first classifier and evaluation → wire the model
into a Streamlit app.

## Honest limitations

Biweekly lab sampling under-represents storm days, and the dataset is small — so the model is a
decision *aid*, not a guarantee. Always follow official advisories, and when in doubt, stay out
of the water for ~48–72 hours after heavy rain.

---

*Built by a two-person team for the Congressional App Challenge. Per CAC rules, our use of AI
tools during development is disclosed; the code and design are our own.*
