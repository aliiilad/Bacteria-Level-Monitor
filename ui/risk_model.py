"""Score beaches with the trained model in models/model.json.

The model predicts y_hat = ln(1 + enterococcus). Its residuals are roughly normal with spread
`residual_sd`, so the chance the count is above 130 MPN/100 mL is
    risk = 1 - Phi((ln(131) - y_hat) / residual_sd)

Weather features are computed exactly like scripts/build_dataset.py does for training:
    rain_prev_7days  sum of daily rain over the 7 days before today (mm)
    days_since_rain  dry days (rain < 1 mm) in a row, counting back from yesterday
    temp_mean        today's mean temperature (°C)
    wind_max         today's max wind speed (km/h)
"""
import json
import math
from pathlib import Path

import requests

MODEL_PATH = Path(__file__).parent.parent / "models" / "model.json"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARS = ["rain_sum", "temperature_2m_mean", "wind_speed_10m_max"]
DRY_DAY_MM = 1.0
MAX_RISK = 0.99


def load_model(path=MODEL_PATH):
    return json.loads(Path(path).read_text())


def fetch_daily_weather(points):
    """Fetch the last 30 days + today for each (lat, lon) in one Open-Meteo request.
    Returns {(lat, lon): daily dict}, where each daily list ends with today (Honolulu time)."""
    points = sorted(set(points))
    resp = requests.get(FORECAST_URL, timeout=10, params={
        "latitude": ",".join(str(lat) for lat, _ in points),
        "longitude": ",".join(str(lon) for _, lon in points),
        "daily": ",".join(DAILY_VARS),
        "timezone": "Pacific/Honolulu",
        "past_days": 30,
        "forecast_days": 1,
    })
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):  # one location comes back as an object, several as a list
        data = [data]
    return {pt: loc["daily"] for pt, loc in zip(points, data)}


def features_from_daily(daily):
    """Turn one location's daily series (last entry = today) into model features."""
    past_rain = [r or 0.0 for r in daily["rain_sum"][:-1]]  # days before today
    days_since_rain = 0
    for rain in reversed(past_rain):
        if rain >= DRY_DAY_MM:
            break
        days_since_rain += 1
    temp, wind = daily["temperature_2m_mean"][-1], daily["wind_speed_10m_max"][-1]
    if temp is None or wind is None:
        raise ValueError("forecast is missing today's temperature or wind")
    return {
        "rain_prev_7days": round(sum(past_rain[-7:]), 1),
        "days_since_rain": float(days_since_rain),
        "temp_mean": float(temp),
        "wind_max": float(wind),
    }


def typical_features(model):
    """An average training day — used when live weather is unavailable."""
    return {name: f["mean"] for name, f in model["features"].items()}


def predict(model, site_id, features):
    """Return (risk 0–0.99, {factor: push on the log count vs. an average beach and day})."""
    offsets = model["site_offsets"]
    avg_offset = sum(offsets.values()) / len(offsets)
    pushes = {"beach": offsets[str(site_id)] - avg_offset}
    y_hat = model["intercept"] + avg_offset + pushes["beach"]
    for name, f in model["features"].items():
        x = min(max(features[name], f["min"]), f["max"])  # stay inside the training range
        pushes[name] = f["weight"] * (x - f["mean"]) / f["spread"]
        y_hat += pushes[name]
    z = (math.log1p(model["unsafe_threshold"]) - y_hat) / model["residual_sd"]
    risk = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return min(risk, MAX_RISK), pushes
