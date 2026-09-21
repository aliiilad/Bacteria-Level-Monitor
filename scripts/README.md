# scripts/

Reusable Python scripts — chiefly the data pipeline that turns the raw exports
in `../data/raw/` into the modelling tables in `../data/processed/`:

- `surfrider_raw.csv` + `weather_openmeteo_raw.csv`  →  `samples.csv` →
  `samples_beaches.csv` → `samples_beaches_weather.csv`, plus `beaches.csv`.

Run scripts from the repo root so the relative `data/` paths resolve.
