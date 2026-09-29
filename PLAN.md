# Working Plan — Oahu Water Quality Predictor

Working plan for the Congressional App Challenge entry. Project context lives in
[`CLAUDE.md`](./CLAUDE.md); this file tracks **what we're doing, who's doing it, and in what
order.** The model is done and the app runs locally with live weather. What's left is
deploying it, filling the gaps below, and making a 3-minute video.

**Person A** owns the model and data. **Person B** owns the app. The same plan is also on a
shared tick list: <https://claude.ai/artifact/JPhJCuFypuYq3ujDb6uiAe> (private; the owner
invites the teammate as an Editor). Tick items there as you go, and update the boxes here at
the end of each week.

## Deadline
- **Our target: submit Friday, Oct 23, 2026.** That leaves the weekend as a buffer.
- **Hard deadline: Monday, Oct 26, 2026, 12:00pm ET = 6:00am HST.** In Hawaiʻi that's before
  school on Monday, so treat Sunday night as the real cutoff.
- **Video:** 3 minutes max. It must cover purpose, intended audience, tools and languages, and
  what the app does.
- **AI rule:** AI tools are allowed only if disclosed, and the technical work must be
  significantly our own. Most commits so far came from Claude sessions, so before submitting,
  each of us should have written or reworked real parts of the code and be able to explain
  every line on camera.

## Current status (Sep 29)
- [x] BWTF Oahu data downloaded (report 44 export), cleaned and labeled. The pipeline now
      also drops 11 double-entered samples.
- [x] 9 swim beaches picked, 2018 onward (see "Selected beaches" below).
- [x] Weather join: Open-Meteo daily weather per beach, antecedent-rain features.
- [x] Class notebook (`notebooks/U02_L050_LRProject.ipynb`): linear regression on
      log(enterococcus) by our own gradient descent. Runs top to bottom.
- [x] App model: same method with only inputs the app can get live, tested on 2025–26,
      exported to `models/model.json` by `scripts/build_dataset.py` (Part 8).
- [x] Streamlit app "Kai Check" (`ui/app.py`): live Open-Meteo weather, risk gauge, "why"
      bars, what-if sliders, map, and a fallback when the weather fetch fails.
- [ ] Deployed to a public URL.
- [ ] Gaps: stale processed data, limitations and "how it works" content, README.
- [ ] Video and submission.

## Where the model stands
The app model trains on 2018–2024 and is tested on 2025–26 samples it never saw (293 samples,
89 unsafe). "Unsafe" = enterococcus > 130 MPN/100 mL.

| Approach | Unsafe caught (recall) | Flagged that were unsafe (precision) | AUC |
|---|--:|--:|--:|
| Flash-flood stand-in (≥ 25 mm rain that day)\* | 4% | 67% (only 6 flagged) | – |
| App model, flags at 50% | 55% | 83% | 0.87 |
| **App model, flags at 30%** | **80%** | 63% | **0.87** |

App-model numbers are from `models/model.json`. \*The stand-in comes from the Sep 27 check on
the same split, before the duplicate cleanup; it isn't in the script yet (a week 1 task).

- **Video headline:** the model catches 80% of unsafe water; a flash-flood rule catches 4%.
- The flash-flood stand-in uses Open-Meteo rainfall, not real NWS warnings. Call it an
  approximation.
- The beach does most of the work: in the Sep 27 check, beach alone scored 0.82 AUC and
  weather added about 0.05. Say so.

## How the app model works
Built by `scripts/build_dataset.py` (Part 8), saved in `models/model.json`, and scored by
`ui/risk_model.py`.

| Input | Column | Unit | Live source (Open-Meteo forecast API) |
|---|---|---|---|
| Beach | `site_id` | one of 9 sites | Picked in the app |
| 7-day rain | `rain_prev_7days` | mm, the 7 days before today | Sum of daily `rain_sum` |
| Days since rain | `days_since_rain` | days (rain < 1 mm counts as dry) | Count back through daily `rain_sum` |
| Temperature | `temp_mean` | °C, today's mean | `temperature_2m_mean` |
| Wind | `wind_max` | km/h, today's max | `wind_speed_10m_max` |

```
ŷ    = b + beach offset + Σ wᵢ · (xᵢ − meanᵢ) / spreadᵢ    predicted ln(1 + enterococcus)
risk = 1 − Φ((ln 131 − ŷ) / σ),  σ ≈ 1.42                  chance of more than 130 MPN/100 mL
```

- **Why no tide or same-day rain:** tide isn't in the forecast, and same-day rain includes rain
  after the 6–10am sample time. Dropping both didn't hurt test accuracy.
- **Bands in the app:** under 30% lower risk · 30–60% caution · over 60% likely unsafe.
- **Guard rails:** inputs are clamped to the training range and the displayed risk is capped
  at 99%. The app fetches weather at the same grid points the training data came from, and
  caches it for an hour.

## Week-by-week plan
Weeks run Monday to Sunday, Hawaiʻi time. Items already done on `main` are ticked.

### Week 1 · Sep 28 – Oct 4 · Fix the model and get a public URL
**Person A — model & data**
- [x] Drop `rain_same_day` and `tide` from the app model (`APP_FEATURES` in
      `scripts/build_dataset.py`).
- [x] Turn the prediction into a risk % (`ui/risk_model.py`).
- [x] Save `models/model.json` and print the 2025–26 test results (Part 8).
- [ ] Re-run `python scripts/build_dataset.py` and commit `data/processed/`. Those files are
      still from Sep 21: no `tide` column and no duplicate cleanup. The app reads
      `beaches.csv` for its "X of Y samples" line, so the numbers on screen are stale.
- [ ] Add the flash-flood stand-in to Part 8's printout, so the 80% versus 4% claim can be
      reproduced from the repo.

**Person B — app & product**
- [x] Streamlit app with map and gauge (`ui/app.py`), with `ui/requirements.txt`.
- [ ] Deploy to Streamlit Community Cloud (entry point `ui/app.py`) and share the public URL.
- [ ] Show the two Magic Island sampling points as one pin. They currently draw as two
      overlapping dots.

**Together**
- [ ] Update `README.md` and `CLAUDE.md` to describe what we actually built. The README still
      says the app comes later and describes a gradient-boosting classifier. Judges will read
      the repo.

### Week 2 · Oct 5 – 11 · Live weather in, real risk out
**Person A — model & data**
- [x] Fetch live weather from Open-Meteo (30 past days, one request for all beaches).
- [x] Build the four inputs the same way training did.
- [x] Clamp inputs to the training range and cap the displayed risk at 99%.
- [ ] Compare live forecast weather with the historical weather the model trained on, for a
      few recent days at 2–3 beaches. If rain totals differ a lot, note it in the limitations.

**Person B — app & product**
- [x] Gauge with lower risk / caution / likely unsafe labels (30% / 60%).
- [x] "Why" bars for each factor, plus a biggest-factor sentence.
- [x] Each beach's track record ("X of Y samples over the limit"), which explains why
      Kahaluʻu (87%) almost always shows red.
- [x] "Try different weather" sliders, so we can demo a high-risk beach on a sunny day.
- [ ] A real limitations section. The footer's "Limitations" and "About the team" links land
      on the footer with nothing behind them. Cover biweekly testing, the small dataset, and
      that this is not an official advisory.

### Week 3 · Oct 12 – 18 · Polish the app and start the story
**Person A — model & data**
- [ ] "How it works" section with the 80% versus 4% chart. The "how the model works" link
      currently lands on the footer.
- [ ] Email the Surfrider Oʻahu BWTF coordinator. It helps the CAC "inspiration" answer.

**Person B — app & product**
- [ ] Check the layout on a phone.
- [x] Clear message when the weather fetch fails (falls back to a typical day), and an
      hourly weather cache.
- [ ] README with screenshots, the live URL, and the AI disclosure.

### Week 4 · Oct 19 – 23 · Record the video and submit on Friday
**Person A — model & data**
- [ ] Finish the video script, following the outline below.

**Person B — app & product**
- [ ] Record the video on the live app.

**Together**
- [ ] Submit on the CAC portal by Friday, Oct 23.

## Any time before the deadline
- [ ] Confirm our congressional district is taking part in 2026 (district map on
      congressionalappchallenge.us).
- [ ] Register both teammates on the CAC student portal.
- [ ] Keep a running log of what AI tools did, for the required disclosure.
- [ ] Make sure we can both explain every line of code on camera.

## Video outline (3:00 max)
| Time | Beat | What to show |
|---|---|---|
| 0:00 – 0:20 | Hook | Bacteria tests happen every two weeks. Rain happens any day. Most days, nobody knows if the water is safe. |
| 0:20 – 1:50 | Live demo | Pick a beach, read the gauge and the "why" bars, then use "Try different weather" to show a beach turning red. |
| 1:50 – 2:30 | How it works | Surfrider samples, Open-Meteo weather, our own gradient descent. Show the chart: 80% caught versus 4%. |
| 2:30 – 3:00 | Limits and tools | Biweekly sampling, a small dataset, not an official advisory. Name Python, pandas, Streamlit, and the AI tools we used. |

## Selected beaches (training scope)
**Decision:** train on **swimming beaches only** (excluding stream mouths, boat ramps, canals,
and sensor points, even though several of those are the biggest bacteria hotspots). The app
predicts *ocean swim safety*, so the training sites should be places people actually swim.
Filtered set lives in **`samples_beaches.csv`** (same schema as `samples.csv`).

- **Year range: 2018+.** Pre-2018 is sparse and gappy (~92 samples total across 2001–2016);
  2018 onward is ~180–560 samples/yr. Each site simply starts when its record starts.
- **9 sampling points across 7–8 popular beaches, all four regions**, chosen for sample count,
  coverage through 2025–2026 (so the time-split has recent test data), and a spread of risk
  levels so the single "site"-aware model has both safe and unsafe examples to learn from.
  Counts below match the committed `beaches.csv`. They'll shift by a few samples once the
  pipeline is re-run on the newer export with the duplicate cleanup (week 1 task).

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

  **Totals: 1,267 samples, 29.9% unsafe.**

- **Candidate additional swim beaches** (all excluded for now): Wailupe Beach Park (S,
  127/18%) and Pililāʻau (W, 46/13%) are the clean adds; South Kāneʻohe Bay + Kaimalino
  (Windward, ~25%) and Chocolates (N surf break, 66%) carry more signal but stretch the "swim
  beach" label.

- **Notes / honest limits:**
  - Magic Island Bowls + Canoe Launch are two sampling points at the *same* place (Ala Moana);
    keep both for signal, but present them as one beach on the app map.
  - Recent-year (2025–2026) unsafe counts are thin for the low-risk beaches (Cromwell's 2,
    Pūpūkea 2, Waialae 3, Kailua 4, Pōkaʻi 2), so test recall and AUC lean on the high-risk
    sites.
  - West side (Pōkaʻi) is the thinnest and lowest-risk; kept for island-wide map coverage.

- **Reference table:** `beaches.csv` — one row per selected beach (site_id, beach_name,
  region, full_site_name, lat/lon, n_samples, n_unsafe, unsafe_pct, first_year, last_year).
  The app reads it for the beach list, map, and track-record line.

## Shared files
Don't change a schema without telling the other person.

1. **`data/processed/samples.csv`** — one row per BWTF sample.
   `sample_id, site_id, site_name, latitude, longitude, date, datetime_utc,
   enterococcus, ent_modifier, tide, unsafe`
   `unsafe = 1` when enterococcus > 130 MPN/100 mL (Hawaii DOH). `date` is the local
   Honolulu collection date (join key); `datetime_utc` is the exact timestamp.
   (The committed copy predates the `tide` column until the pipeline is re-run.)
2. **`data/processed/samples_beaches_weather.csv`** — the 9-beach samples plus weather
   features: `rain_same_day, rain_prev_7days, days_since_rain, temp_mean, wind_max`.
   The app model uses only the last four.
3. **`data/processed/beaches.csv`** — one row per beach; read by the app.
4. **`models/model.json`** — the app model: intercept, beach offsets, feature weights and
   scaling, `residual_sd`, weather grid points, and 2025–26 test metrics.

## Ground rules
- **No leakage.** Every weather feature uses only what was known at sample time. That's why
  the app model has no `rain_same_day`: it includes rain after the morning sample.
- **Time-based split, always.** Train on older years, test on 2025–26. No random shuffling.
- **Be honest about limits.** Biweekly sampling under-represents storm days, the dataset is
  small, and the beach itself explains most of the risk.
- **Disclose AI-tool use** (CAC rule); the code must be genuinely ours.

## Sources
- [2026 CAC rules (PDF)](https://www.congressionalappchallenge.us/wp-content/uploads/2026/05/2026-CAC-Rules.pdf)
- [Congressional App Challenge](https://www.congressionalappchallenge.us/): district map and student portal
- [Surfrider Blue Water Task Force, Oʻahu report 44](https://bwtf.surfrider.org/report/44)
- [Open-Meteo forecast API docs](https://open-meteo.com/en/docs)
