"""
ingestion/fetch_pems_roads.py
──────────────────────────────
Downloads Caltrans PeMS (Performance Measurement System) freeway sensor data
for District 4 (Bay Area). Provides road traffic context for transit forecasting.

Why road data matters for transit forecasting:
  - Heavy freeway congestion → commuters shift to BART/Caltrain
  - Accidents on 101/280/880 → ridership spikes at nearby stations
  - Event-driven traffic jams around SAP Center → more VTA riders

PeMS provides:
  - 5-minute flow (vehicles/5min), speed (mph), occupancy (%)
  - 325+ sensors covering I-101, I-280, I-880, I-580, US-101, SR-85
  - Historical data going back to 2001

Note: PeMS requires a free account at pems.dot.ca.gov
The PEMS-BAY ML-ready dataset (2017, 325 sensors) is also directly downloadable.

Usage:
    python ingestion/fetch_pems_roads.py --mode pems_bay    # ML-ready dataset
    python ingestion/fetch_pems_roads.py --mode live        # live API (needs login)
    python ingestion/fetch_pems_roads.py --mode stations    # station metadata only
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fetch_pems_roads")

RAW_DIR     = Path("data/raw/roads")
CONFIG_PATH = Path("configs/sources.yaml")

# Key Bay Area freeway segments near transit hubs
KEY_SEGMENTS = {
    "101_san_jose":  {"lat": 37.3382, "lng": -121.8863, "near": "DIRIDON"},
    "280_cupertino": {"lat": 37.3230, "lng": -122.0322, "near": "BERY"},
    "880_oakland":   {"lat": 37.7748, "lng": -122.2193, "near": "19TH"},
    "101_sf":        {"lat": 37.7749, "lng": -122.4194, "near": "EMBR"},
    "580_castro":    {"lat": 37.6879, "lng": -122.0843, "near": "CAST"},
}

# PEMS-BAY pre-processed ML dataset (public, no login needed)
PEMS_BAY_URL = (
    "https://raw.githubusercontent.com/george-j-ste/"
    "Augmented-PEMS-BAY/main/data/PEMS_BAY.csv"
)


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── PEMS-BAY ML-ready dataset ──────────────────────────────────────────────────

def fetch_pems_bay_dataset() -> pd.DataFrame:
    """
    Download the pre-processed PEMS-BAY dataset directly from GitHub.

    This is the fastest path to road traffic data — no login required.
    325 Bay Area sensors, Jan–Jun 2017, 5-min intervals.
    Speed + occupancy per sensor, plus a pre-built adjacency matrix.

    Returns a tidy DataFrame: timestamp, sensor_id, speed_mph, occupancy_pct
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = RAW_DIR / "pems_bay_raw.csv"

    if cache.exists():
        log.info(f"Loading cached PEMS-BAY dataset from {cache}")
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
    else:
        log.info(f"Downloading PEMS-BAY dataset from GitHub …")
        try:
            resp = requests.get(PEMS_BAY_URL, timeout=120, stream=True)
            resp.raise_for_status()
            cache.write_bytes(resp.content)
            log.info(f"  Downloaded {len(resp.content)/1e6:.1f} MB → {cache}")
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
        except Exception as e:
            log.error(f"PEMS-BAY download failed: {e}")
            log.info("Falling back to synthetic road data for development …")
            return _synthetic_road_data()

    # Melt from wide (sensors as columns) to long format
    df.index.name = "timestamp"
    df = df.reset_index()
    df_long = df.melt(
        id_vars=["timestamp"],
        var_name="sensor_id",
        value_name="speed_mph",
    )
    df_long["timestamp"] = pd.to_datetime(df_long["timestamp"])
    df_long = df_long.dropna(subset=["speed_mph"])

    # Add congestion flags
    df_long["is_congested"]   = df_long["speed_mph"] < 35
    df_long["is_stop_n_go"]   = df_long["speed_mph"] < 15
    df_long["congestion_level"] = pd.cut(
        df_long["speed_mph"],
        bins=[0, 15, 35, 55, 999],
        labels=["stop_and_go", "slow", "moderate", "free_flow"],
        include_lowest=True,
    ).astype(str)

    out = RAW_DIR / "pems_bay_processed.parquet"
    df_long.to_parquet(out, index=False)
    log.info(f"PEMS-BAY processed: {len(df_long):,} rows → {out}")
    return df_long


# ── Caltrans PeMS live API ─────────────────────────────────────────────────────

class PeMSClient:
    """
    Thin client for the Caltrans PeMS data API.
    Requires a free account at https://pems.dot.ca.gov

    Note: PeMS uses a cookie-based session rather than API keys.
    You must log in through the browser first and export cookies,
    or use the bulk download scripts provided by Caltrans.
    """

    BASE = "https://pems.dot.ca.gov"

    def __init__(self, username: str, password: str):
        self.session = requests.Session()
        self._login(username, password)

    def _login(self, username: str, password: str) -> None:
        """Authenticate with PeMS."""
        resp = self.session.post(
            f"{self.BASE}/",
            data={
                "username": username,
                "password": password,
                "login":    "Login",
            },
            timeout=30,
        )
        if "logout" not in resp.text.lower():
            raise ValueError("PeMS login failed — check credentials")
        log.info("✅ PeMS login successful")

    def get_station_metadata(self, district: int = 4) -> pd.DataFrame:
        """Download station metadata for a PeMS district."""
        resp = self.session.get(
            f"{self.BASE}/",
            params={
                "report_form": "1",
                "dnode":       "Freeway",
                "content":     "station_dumps",
                "tab":         "dq_export",
                "export_type": "text",
                "district_id": district,
                "type":        "meta",
            },
            timeout=60,
        )
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text), sep="\t", on_bad_lines="skip")
        log.info(f"Loaded {len(df):,} PeMS station records for District {district}")
        return df

    def get_5min_data(
        self,
        start: date,
        end: date,
        district: int = 4,
    ) -> pd.DataFrame:
        """
        Download 5-minute aggregated detector data for a date range.
        PeMS serves one file per day — we walk through the range.
        """
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        all_frames = []
        cur = start

        while cur <= end:
            out = RAW_DIR / f"pems_d{district}_{cur.strftime('%Y_%m_%d')}.parquet"
            if out.exists():
                log.info(f"  Already downloaded: {out.name}")
                all_frames.append(pd.read_parquet(out))
                cur += __import__("datetime").timedelta(days=1)
                continue

            log.info(f"  Downloading PeMS data for {cur} …")
            try:
                resp = self.session.get(
                    f"{self.BASE}/",
                    params={
                        "report_form": "1",
                        "dnode":       "Freeway",
                        "content":     "loops",
                        "tab":         "dq_export",
                        "export_type": "text",
                        "district_id": district,
                        "start_time":  cur.strftime("%m/%d/%Y"),
                        "end_time":    cur.strftime("%m/%d/%Y"),
                        "tod":         "all",
                        "tod_name":    "All Day",
                        "lane_type":   "ML",
                        "q":           "flow",
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                from io import StringIO
                df = pd.read_csv(StringIO(resp.text), sep=",", on_bad_lines="skip")
                df["date"] = cur
                df.to_parquet(out, index=False)
                all_frames.append(df)
                log.info(f"    → {len(df):,} rows")
            except Exception as e:
                log.warning(f"    Failed for {cur}: {e}")

            time.sleep(1)   # be polite to PeMS
            cur += __import__("datetime").timedelta(days=1)

        if not all_frames:
            return pd.DataFrame()

        combined = pd.concat(all_frames, ignore_index=True)
        return self._clean_5min(combined)

    @staticmethod
    def _clean_5min(df: pd.DataFrame) -> pd.DataFrame:
        """Standardise column names and add congestion flags."""
        rename = {}
        for col in df.columns:
            lc = col.lower()
            if "lane" in lc:
                # Per-lane columns (e.g. "Lane 1 Flow", "Lane 2 Avg Speed") also
                # match the flow/speed/occ substrings below — skip them so only
                # the aggregate station-level columns get renamed, avoiding
                # duplicate target column names (same collision class as the
                # "station"/"station length" fix below).
                continue
            if "flow" in lc or "volume" in lc:
                rename[col] = "flow_veh_5min"
            elif "speed" in lc:
                rename[col] = "speed_mph"
            elif "occ" in lc:
                rename[col] = "occupancy_pct"
            elif "timestamp" in lc or "time" in lc:
                rename[col] = "timestamp"
            elif lc == "station":
                rename[col] = "sensor_id"

        df = df.rename(columns=rename)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        if "speed_mph" in df.columns:
            df["is_congested"]    = df["speed_mph"] < 35
            df["is_stop_n_go"]    = df["speed_mph"] < 15

        return df.dropna(subset=["timestamp"] if "timestamp" in df.columns else [])


# ── Synthetic fallback ─────────────────────────────────────────────────────────

def _synthetic_road_data() -> pd.DataFrame:
    """
    Generate synthetic road data for development when PeMS isn't available.
    Mimics realistic Bay Area freeway patterns including event-day slowdowns.
    """
    import numpy as np
    np.random.seed(42)

    timestamps = pd.date_range("2022-01-01", "2024-06-30", freq="5min")
    n = len(timestamps)
    h = timestamps.hour.values
    dow = timestamps.dayofweek.values

    # Speed varies by hour/day
    base_speed = np.where(
        dow < 5,
        np.where((h>=7)&(h<=9), 25, np.where((h>=16)&(h<=19), 22,
        np.where((h>=10)&(h<=15), 45, 65))),
        55
    )
    speed = np.maximum(5, base_speed + np.random.normal(0, 5, n))

    rows = []
    for seg_name in KEY_SEGMENTS:
        rows.append(pd.DataFrame({
            "timestamp":        timestamps,
            "sensor_id":        seg_name,
            "speed_mph":        np.round(speed + np.random.normal(0, 2, n), 1),
            "flow_veh_5min":    np.maximum(0, (65 - speed) * 2 + np.random.normal(0, 5, n)).astype(int),
            "occupancy_pct":    np.clip(np.random.beta(2, 5, n) * 100, 0, 100).round(1),
            "is_congested":     speed < 35,
            "is_stop_n_go":     speed < 15,
            "near_station":     KEY_SEGMENTS[seg_name]["near"],
            "lat":              KEY_SEGMENTS[seg_name]["lat"],
            "lng":              KEY_SEGMENTS[seg_name]["lng"],
        }))

    df = pd.concat(rows, ignore_index=True)
    out = RAW_DIR / "pems_synthetic.parquet"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    log.info(f"Synthetic road data: {len(df):,} rows → {out}")
    return df


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch Caltrans PeMS road data")
    parser.add_argument(
        "--mode",
        choices=["pems_bay", "live", "stations", "synthetic"],
        default="pems_bay",
        help="pems_bay=ML-ready dataset (no login), live=API (needs login), synthetic=dev data",
    )
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end",   default=date.today().isoformat())
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.mode == "pems_bay":
        log.info("Fetching PEMS-BAY ML-ready dataset (no login required) …")
        df = fetch_pems_bay_dataset()
        if not df.empty:
            print(f"\n✅ PEMS-BAY loaded: {len(df):,} rows | {df['sensor_id'].nunique()} sensors")
            print(df.head())

    elif args.mode == "synthetic":
        log.info("Generating synthetic road data for development …")
        df = _synthetic_road_data()
        print(f"\n✅ Synthetic data: {len(df):,} rows")

    elif args.mode == "stations":
        log.info("Fetching PeMS station metadata (requires login) …")
        cfg = load_config()
        username = input("PeMS username: ")
        password = __import__("getpass").getpass("PeMS password: ")
        client = PeMSClient(username, password)
        meta = client.get_station_metadata(district=cfg["pems"]["district"])
        out = RAW_DIR / "pems_stations.csv"
        meta.to_csv(out, index=False)
        log.info(f"Station metadata saved → {out}")

    elif args.mode == "live":
        log.info("Fetching live PeMS data (requires login) …")
        cfg = load_config()
        username = input("PeMS username: ")
        password = __import__("getpass").getpass("PeMS password: ")
        client = PeMSClient(username, password)
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end   = datetime.strptime(args.end,   "%Y-%m-%d").date()
        df = client.get_5min_data(start, end, district=cfg["pems"]["district"])
        if not df.empty:
            out = RAW_DIR / f"pems_live_{args.start}_{args.end}.parquet"
            df.to_parquet(out, index=False)
            log.info(f"Live PeMS data saved → {out}")


if __name__ == "__main__":
    main()
