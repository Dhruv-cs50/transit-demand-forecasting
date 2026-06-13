"""
ingestion/fetch_weather_openmeteo.py
─────────────────────────────────────
Fetches historical and forecast weather data from Open-Meteo for each
transit station defined in configs/sources.yaml.

Open-Meteo is free, requires no API key, and provides:
  - Historical data back to 1940 (archive API)
  - 7-day forecast (forecast API)
  - Hourly resolution: precipitation, temperature, wind, cloud cover, weather code

Output: data/raw/weather/weather_{station}_{start}_{end}.parquet

Usage:
    python ingestion/fetch_weather_openmeteo.py
    python ingestion/fetch_weather_openmeteo.py --start 2020-01-01 --end 2024-12-31
    python ingestion/fetch_weather_openmeteo.py --forecast   # next 7 days
"""

import argparse
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fetch_weather")

RAW_DIR = Path("data/raw/weather")
CONFIG_PATH = Path("configs/sources.yaml")

# Open-Meteo WMO weather code → human-readable label + is_raining flag
# See: https://open-meteo.com/en/docs#weathervariables
WEATHER_CODE_MAP = {
    0:  ("Clear sky",         False),
    1:  ("Mainly clear",      False),
    2:  ("Partly cloudy",     False),
    3:  ("Overcast",          False),
    45: ("Foggy",             False),
    48: ("Icy fog",           False),
    51: ("Light drizzle",     True),
    53: ("Moderate drizzle",  True),
    55: ("Dense drizzle",     True),
    61: ("Slight rain",       True),
    63: ("Moderate rain",     True),
    65: ("Heavy rain",        True),
    71: ("Slight snow",       False),
    73: ("Moderate snow",     False),
    75: ("Heavy snow",        False),
    77: ("Snow grains",       False),
    80: ("Slight showers",    True),
    81: ("Moderate showers",  True),
    82: ("Violent showers",   True),
    85: ("Slight snow shower",False),
    86: ("Heavy snow shower", False),
    95: ("Thunderstorm",      True),
    96: ("Thunderstorm/hail", True),
    99: ("Heavy thunderstorm",True),
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


class OpenMeteoClient:
    """Fetches weather from Open-Meteo — no API key required."""

    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    HOURLY_VARS = [
        "precipitation",
        "temperature_2m",
        "windspeed_10m",
        "weathercode",
        "cloudcover",
        "relativehumidity_2m",
    ]

    def __init__(self):
        self.session = requests.Session()

    def _fetch(self, url: str, params: dict, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                log.warning(f"Request failed (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def get_historical(
        self,
        lat: float,
        lng: float,
        start: date,
        end: date,
        timezone: str = "America/Los_Angeles",
    ) -> pd.DataFrame:
        """Fetch historical hourly weather for a lat/lng between start and end."""
        params = {
            "latitude": lat,
            "longitude": lng,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(self.HOURLY_VARS),
            "timezone": timezone,
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "precipitation_unit": "inch",
        }
        data = self._fetch(self.ARCHIVE_URL, params)
        return self._to_dataframe(data, lat, lng)

    def get_forecast(
        self,
        lat: float,
        lng: float,
        days: int = 7,
        timezone: str = "America/Los_Angeles",
    ) -> pd.DataFrame:
        """Fetch the next `days` days of hourly forecast for a lat/lng."""
        params = {
            "latitude": lat,
            "longitude": lng,
            "forecast_days": days,
            "hourly": ",".join(self.HOURLY_VARS),
            "timezone": timezone,
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "precipitation_unit": "inch",
        }
        data = self._fetch(self.FORECAST_URL, params)
        return self._to_dataframe(data, lat, lng)

    def _to_dataframe(self, data: dict, lat: float, lng: float) -> pd.DataFrame:
        hourly = data.get("hourly", {})
        if not hourly or not hourly.get("time"):
            raise ValueError(f"Open-Meteo returned empty hourly data for ({lat}, {lng})")

        df = pd.DataFrame(hourly)
        df["timestamp"] = pd.to_datetime(df["time"])
        df = df.drop(columns=["time"])

        # Rename columns for clarity
        df = df.rename(columns={
            "precipitation":        "precip_in",
            "temperature_2m":       "temp_f",
            "windspeed_10m":        "windspeed_mph",
            "weathercode":          "weather_code",
            "cloudcover":           "cloud_cover_pct",
            "relativehumidity_2m":  "humidity_pct",
        })

        # Decode weather codes
        df["weather_desc"] = df["weather_code"].map(
            lambda c: WEATHER_CODE_MAP.get(int(c), ("Unknown", False))[0]
        )
        df["is_raining"] = df["weather_code"].map(
            lambda c: WEATHER_CODE_MAP.get(int(c), ("Unknown", False))[1]
        )

        # Convert inches to mm as well (useful for model features)
        df["precip_mm"] = df["precip_in"] * 25.4

        # Tag with coordinates
        df["lat"] = lat
        df["lng"] = lng

        return df[[
            "timestamp", "temp_f", "precip_in", "precip_mm",
            "windspeed_mph", "cloud_cover_pct", "humidity_pct",
            "weather_code", "weather_desc", "is_raining",
            "lat", "lng",
        ]]


# ── Orchestration ──────────────────────────────────────────────────────────────

def fetch_historical_all_stations(
    client: OpenMeteoClient,
    station_coords: dict,
    start: date,
    end: date,
) -> None:
    """Pull historical weather for every station in the config."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_frames = []

    for station_name, coords in station_coords.items():
        lat, lng = coords["lat"], coords["lng"]
        out_path = RAW_DIR / f"weather_{station_name}_{start}_{end}.parquet"

        if out_path.exists():
            log.info(f"Already exists: {out_path.name} — skipping")
            all_frames.append(pd.read_parquet(out_path))
            continue

        log.info(f"Fetching historical weather for {station_name} ({lat}, {lng}) …")
        try:
            df = client.get_historical(lat, lng, start, end)
            df["station"] = station_name
            df.to_parquet(out_path, index=False)
            all_frames.append(df)
            log.info(f"  → {len(df):,} hourly rows → {out_path.name}")
        except Exception as e:
            log.error(f"  Failed for {station_name}: {e}")

        time.sleep(0.5)  # Open-Meteo has a generous rate limit but be polite

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        out = RAW_DIR / f"weather_all_stations_{start}_{end}.parquet"
        combined.to_parquet(out, index=False)
        log.info(f"\nAll stations combined: {len(combined):,} rows → {out}")


def fetch_forecast_all_stations(
    client: OpenMeteoClient,
    station_coords: dict,
) -> None:
    """Pull the 7-day forecast for every station. Used by the nightly serving pipeline."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_frames = []
    run_ts = datetime.utcnow().strftime("%Y%m%d_%H%M")

    for station_name, coords in station_coords.items():
        lat, lng = coords["lat"], coords["lng"]
        log.info(f"Fetching forecast for {station_name} …")
        try:
            df = client.get_forecast(lat, lng, days=7)
            df["station"] = station_name
            all_frames.append(df)
        except Exception as e:
            log.error(f"  Failed for {station_name}: {e}")
        time.sleep(0.3)

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        out = RAW_DIR / f"weather_forecast_{run_ts}.parquet"
        combined.to_parquet(out, index=False)
        log.info(f"Forecast saved: {len(combined):,} rows → {out}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Open-Meteo weather data")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--forecast", action="store_true", help="Fetch 7-day forecast only")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_config()
    station_coords = cfg["weather"]["station_coords"]
    client = OpenMeteoClient()

    if args.forecast:
        fetch_forecast_all_stations(client, station_coords)
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        fetch_historical_all_stations(client, station_coords, start, end)


if __name__ == "__main__":
    main()
