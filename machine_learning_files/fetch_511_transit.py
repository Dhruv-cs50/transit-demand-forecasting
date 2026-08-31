"""
machine_learning_files/fetch_511_transit.py
─────────────────────────────
Pulls GTFS-RT and historical stop-observation data from the 511 SF Bay API
for all major Bay Area transit agencies and saves to data/raw/transit/.

Covers: BART, Caltrain, VTA, Muni, AC Transit, SamTrans, WETA, Golden Gate Transit.

Usage:
    python machine_learning_files/fetch_511_transit.py
    python machine_learning_files/fetch_511_transit.py --agency VTA --start 2024-01-01 --end 2024-12-31
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
log = logging.getLogger("fetch_511_transit")

RAW_DIR = Path("data/raw/transit")
CONFIG_PATH = Path("configs/sources.yaml")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


class Transit511Client:
    """Thin wrapper around the 511 SF Bay REST API."""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.params = {"api_key": api_key}  # injected on every call

    def _get(self, endpoint: str, params: dict = None, retries: int = 3) -> dict | list:
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params or {}, timeout=30)
                resp.raise_for_status()
                # 511 sometimes returns JSON with BOM — strip it
                text = resp.content.decode("utf-8-sig")
                return __import__("json").loads(text)
            except requests.HTTPError as e:
                log.warning(f"HTTP {e.response.status_code} on {url} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
            except requests.RequestException as e:
                # Timeout/ConnectionError etc. aren't HTTPError subclasses —
                # without this, a transient network failure skipped the
                # retry/backoff entirely and raised on the very first attempt.
                log.warning(f"{type(e).__name__} on {url} (attempt {attempt+1})")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    # ── GTFS static ──────────────────────────────────────────────────────────

    def get_stops(self, agency_id: str) -> pd.DataFrame:
        """Return all stops for an agency as a DataFrame."""
        # Without format=json the 511 API returns XML (SIRI) by default —
        # json.loads() in _get() would then raise JSONDecodeError on every
        # call. get_stop_monitoring() below already passes this; stops/lines
        # didn't, so they never actually returned data.
        data = self._get("stops", {"operator_id": agency_id, "format": "json"})
        stops = data.get("Contents", {}).get("dataObjects", {}).get("ScheduledStopPoint", [])
        return pd.DataFrame([
            {
                "stop_id":   s["id"],
                "stop_name": s.get("Name", ""),
                "lat":       float(s.get("Location", {}).get("Latitude", 0)),
                "lng":       float(s.get("Location", {}).get("Longitude", 0)),
                "agency_id": agency_id,
            }
            for s in stops
        ])

    def get_lines(self, agency_id: str) -> pd.DataFrame:
        """Return all routes for an agency."""
        # Same missing format=json as get_stops() above — see comment there.
        data = self._get("lines", {"operator_id": agency_id, "format": "json"})
        lines = data.get("Content", {}).get("dataObjects", {}).get("LineGroup", [])
        if isinstance(lines, dict):
            lines = [lines]
        return pd.DataFrame([
            {
                "line_id":   ln.get("id", ""),
                "line_name": ln.get("Name", ""),
                "agency_id": agency_id,
            }
            for ln in lines
        ])

    # ── GTFS-RT stop monitoring ───────────────────────────────────────────────

    def get_stop_monitoring(self, agency_id: str, stop_id: str = None) -> pd.DataFrame:
        """
        Real-time arrivals/departures at stops.
        If stop_id is None, returns all monitored stops for the agency.
        """
        params = {"operator_id": agency_id, "format": "json"}
        if stop_id:
            params["StopRef"] = stop_id
        data = self._get("StopMonitoring", params)
        visits = (
            data.get("ServiceDelivery", {})
                .get("StopMonitoringDelivery", {})
                .get("MonitoredStopVisit", [])
        )
        if isinstance(visits, dict):
            visits = [visits]

        rows = []
        for v in visits:
            journey = v.get("MonitoredVehicleJourney", {})
            call = journey.get("MonitoredCall", {})
            rows.append({
                "recorded_at":    v.get("RecordedAtTime"),
                "stop_id":        call.get("StopPointRef"),
                "stop_name":      call.get("StopPointName"),
                "line_ref":       journey.get("LineRef"),
                "aimed_arrival":  call.get("AimedArrivalTime"),
                "expected_arrival": call.get("ExpectedArrivalTime"),
                "aimed_departure": call.get("AimedDepartureTime"),
                "expected_departure": call.get("ExpectedDepartureTime"),
                "occupancy":      journey.get("Occupancy"),
                "agency_id":      agency_id,
            })
        return pd.DataFrame(rows)

    # ── Historical GTFS with observed arrivals ────────────────────────────────

    def get_historical_gtfs(self, year: int, month: int) -> bytes:
        """
        Download the historical regional GTFS feed (with stop_observations.txt)
        for a given year-month. Returns raw zip bytes — caller saves to disk.
        """
        period = f"{year}-{month:02d}"
        url = f"http://api.511.org/transit/datafeeds"
        params = {
            "api_key": self.api_key,
            "operator_id": "RG",           # RG = regional consolidated feed
            "historic": period,
        }
        resp = requests.get(url, params=params, timeout=120, stream=True)
        resp.raise_for_status()
        return resp.content


# ── Fetch functions ────────────────────────────────────────────────────────────

def fetch_stops_all_agencies(client: Transit511Client, agencies: list[dict]) -> None:
    """Pull stop metadata for every agency and save as CSVs."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for agency in agencies:
        aid = agency["id"]
        log.info(f"Fetching stops for {agency['name']} ({aid})")
        try:
            df = client.get_stops(aid)
            out = RAW_DIR / f"stops_{aid}.csv"
            df.to_csv(out, index=False)
            log.info(f"  → {len(df)} stops saved to {out}")
        except Exception as e:
            log.error(f"  Failed for {aid}: {e}")
        time.sleep(0.5)  # be polite to the API


def fetch_realtime_snapshot(client: Transit511Client, agencies: list[dict]) -> None:
    """Capture a real-time arrival snapshot across all agencies."""
    all_rows = []
    for agency in agencies:
        aid = agency["id"]
        log.info(f"Fetching real-time arrivals for {agency['name']}")
        try:
            df = client.get_stop_monitoring(aid)
            all_rows.append(df)
        except Exception as e:
            log.warning(f"  Stop monitoring unavailable for {aid}: {e}")
        time.sleep(0.3)

    if all_rows:
        combined = pd.concat(all_rows, ignore_index=True)
        combined["snapshot_ts"] = datetime.utcnow().isoformat()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
        out = RAW_DIR / f"realtime_snapshot_{ts}.parquet"
        combined.to_parquet(out, index=False)
        log.info(f"Real-time snapshot: {len(combined)} rows → {out}")


def fetch_historical_range(
    client: Transit511Client,
    start: date,
    end: date,
) -> None:
    """
    Download historical GTFS feeds (month-by-month) for a date range.
    These contain stop_observations.txt with actual observed arrival times —
    the richest source for training data.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cur = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)

    while cur <= end_month:
        out = RAW_DIR / f"historical_gtfs_{cur.strftime('%Y_%m')}.zip"
        if out.exists():
            log.info(f"Already downloaded: {out.name} — skipping")
        else:
            log.info(f"Downloading historical GTFS for {cur.strftime('%Y-%m')} …")
            try:
                data = client.get_historical_gtfs(cur.year, cur.month)
                out.write_bytes(data)
                log.info(f"  → {out} ({len(data)/1e6:.1f} MB)")
            except Exception as e:
                log.error(f"  Failed for {cur.strftime('%Y-%m')}: {e}")
            time.sleep(1)

        # advance to next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Fetch 511 SF Bay transit data")
    parser.add_argument("--agency", default=None, help="Single agency ID (e.g. VTA). Omit for all.")
    parser.add_argument("--start", default="2020-01-01", help="Start date for historical download (YYYY-MM-DD)")
    parser.add_argument("--end", default=date.today().isoformat(), help="End date (YYYY-MM-DD)")
    parser.add_argument("--mode", choices=["stops", "realtime", "historical", "all"], default="all")
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = load_config()["transit_511"]
    client = Transit511Client(cfg["api_key"], cfg["base_url"])

    agencies = cfg["agencies"]
    if args.agency:
        agencies = [a for a in agencies if a["id"] == args.agency]
        if not agencies:
            log.error(f"Unknown agency: {args.agency}")
            return

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    if args.mode in ("stops", "all"):
        fetch_stops_all_agencies(client, agencies)

    if args.mode in ("realtime", "all"):
        fetch_realtime_snapshot(client, agencies)

    if args.mode in ("historical", "all"):
        fetch_historical_range(client, start, end)

    log.info("Done.")


if __name__ == "__main__":
    main()
