# scripts/

Reusable Python scripts — chiefly the data pipeline that turns the raw exports
in `../data/raw/` into the modelling tables in `../data/processed/`:

- `surfrider_raw.csv` + `weather_openmeteo_raw.csv`  →  `samples.csv` →
  `samples_beaches.csv` → `samples_beaches_weather.csv`, plus `beaches.csv`.

Run scripts from the repo root so the relative `data/` paths resolve.

It also fits the **app model** on a time split (train 2018–2024, test 2025–26), prints its
test recall, precision and AUC, and writes `../models/model.json`, which `ui/app.py` reads.
Re-run it whenever the data or model changes, then commit the new `model.json`.
