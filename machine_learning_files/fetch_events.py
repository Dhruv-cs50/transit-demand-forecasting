"""
ingestion/fetch_events.py
─────────────────────────
Fetches Bay Area event schedules from:
  1. NHL API  — San Jose Sharks games (free, no key required)
  2. Ticketmaster Discovery API — concerts, sports at SAP Center,
     Chase Center, Oracle Park, Levi's Stadium

Produces a unified events DataFrame:
  timestamp_start, timestamp_end, venue, event_name, event_type,
  is_sharks_game, expected_attendance, lat, lng

Output: data/raw/events/events_{start}_{end}.parquet

Usage:
    python ingestion/fetch_events.py
    python ingestion/fetch_events.py --start 2020-01-01 --end 2024-12-31
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
log = logging.getLogger("fetch_events")

RAW_DIR = Path("data/raw/events")
CONFIG_PATH = Path("configs/sources.yaml")

VENUE_COORDS = {
    "sap_center":    {"lat": 37.3327, "lng": -121.9010, "city": "San Jose"},
    "chase_center":  {"lat": 37.7681, "lng": -122.3877, "city": "San Francisco"},
    "oracle_park":   {"lat": 37.7786, "lng": -122.3893, "city": "San Francisco"},
    "levis_stadium": {"lat": 37.4033, "lng": -121.9694, "city": "Santa Clara"},
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── NHL API ────────────────────────────────────────────────────────────────────

class NHLClient:
    """Fetches Sharks schedule from the free NHL stats API."""

    BASE = "https://api-web.nhle.com/v1"

    def __init__(self):
        self.session = requests.Session()

    def get_schedule(self, team: str, start: date, end: date) -> pd.DataFrame:
        """
        Pull full schedule for a team between start and end.
        Uses the season schedule endpoint — walks through seasons as needed.
        """
        rows = []
        # Determine which seasons overlap with the date range
        seasons = self._seasons_in_range(start, end)

        for season in seasons:
            log.info(f"  Fetching NHL schedule for {team}, season {season}")
            url = f"{self.BASE}/club-schedule-season/{team}/{season}"
            try:
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                games = resp.json().get("games", [])
                for g in games:
                    game_date = datetime.strptime(g["gameDate"], "%Y-%m-%d").date()
                    if not (start <= game_date <= end):
                        continue
                    # startTimeUTC is in ISO format
                    start_utc = pd.to_datetime(g.get("startTimeUTC"))
                    start_local = start_utc.tz_convert("America/Los_Angeles") if start_utc.tzinfo else start_utc

                    rows.append({
                        "game_id":         g.get("id"),
                        "timestamp_start": start_local,
                        "timestamp_end":   start_local + pd.Timedelta(hours=3),  # avg game ~2.5hrs
                        "event_name":      f"Sharks vs {g.get('awayTeam', {}).get('abbrev', 'OPP')}",
                        "event_type":      "NHL Hockey",
                        "venue":           "sap_center",
                        "is_sharks_game":  True,
                        "home_or_away":    "home" if g.get("homeTeam", {}).get("abbrev") == team else "away",
                        "game_type":       g.get("gameType", ""),  # 1=preseason, 2=regular, 3=playoff
                        "season":          season,
                        "lat":             VENUE_COORDS["sap_center"]["lat"],
                        "lng":             VENUE_COORDS["sap_center"]["lng"],
                    })
            except Exception as e:
                log.warning(f"  Failed for season {season}: {e}")
            time.sleep(0.3)

        df = pd.DataFrame(rows)
        # Only home games matter for transit impact
        if not df.empty:
            df = df[df["home_or_away"] == "home"].copy()
        return df

    @staticmethod
    def _seasons_in_range(start: date, end: date) -> list[str]:
        """NHL seasons span two calendar years (e.g. 20232024 = 2023-24 season)."""
        seasons = set()
        year = start.year
        while year <= end.year + 1:
            season = f"{year}{year+1}"
            # This season starts ~Oct of year and ends ~June of year+1
            season_start = date(year, 10, 1)
            season_end = date(year + 1, 7, 1)
            if season_start <= end and season_end >= start:
                seasons.add(season)
            year += 1
        return sorted(seasons)


# ── Ticketmaster API ───────────────────────────────────────────────────────────

class TicketmasterClient:
    """Fetches event schedules from the Ticketmaster Discovery API."""

    BASE = "https://app.ticketmaster.com/discovery/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def get_events_for_venue(
        self,
        venue_id: str,
        venue_name: str,
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """
        Fetch all events at a given venue ID between start and end.
        Ticketmaster paginates in pages of 200.
        """
        rows = []
        page = 0
        page_size = 200

        while True:
            params = {
                "apikey":      self.api_key,
                "venueId":     venue_id,
                "startDateTime": f"{start.isoformat()}T00:00:00Z",
                "endDateTime":   f"{end.isoformat()}T23:59:59Z",
                "size":        page_size,
                "page":        page,
                "sort":        "date,asc",
            }
            try:
                resp = self.session.get(f"{self.BASE}/events", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.warning(f"  Ticketmaster request failed for {venue_name} page {page}: {e}")
                break

            embedded = data.get("_embedded", {})
            events = embedded.get("events", [])
            total_pages = data.get("page", {}).get("totalPages", 1)

            for ev in events:
                dates = ev.get("dates", {}).get("start", {})
                dt_str = dates.get("dateTime") or dates.get("localDate")
                if not dt_str:
                    continue

                try:
                    ts_start = pd.to_datetime(dt_str).tz_convert("America/Los_Angeles") \
                        if "T" in dt_str else pd.to_datetime(dt_str)
                except Exception:
                    continue

                # Estimate event duration by type
                classification = ev.get("classifications", [{}])[0]
                segment = classification.get("segment", {}).get("name", "")
                event_type = classification.get("genre", {}).get("name", segment or "Other")
                duration_hrs = {"Sports": 3.0, "Music": 3.0, "Arts & Theatre": 2.5}.get(segment, 2.5)

                priceRanges = ev.get("priceRanges", [{}])
                avg_price = None
                if priceRanges:
                    prices = [p.get("max") for p in priceRanges if p.get("max")]
                    avg_price = sum(prices) / len(prices) if prices else None

                rows.append({
                    "event_id":        ev.get("id"),
                    "timestamp_start": ts_start,
                    "timestamp_end":   ts_start + pd.Timedelta(hours=duration_hrs),
                    "event_name":      ev.get("name", ""),
                    "event_type":      event_type,
                    "segment":         segment,
                    "venue":           venue_name,
                    "is_sharks_game":  False,
                    "avg_ticket_price": avg_price,
                    "lat":             VENUE_COORDS.get(venue_name, {}).get("lat"),
                    "lng":             VENUE_COORDS.get(venue_name, {}).get("lng"),
                })

            page += 1
            if page >= total_pages:
                break
            time.sleep(0.25)  # Ticketmaster rate limit: 5000 req/day on free tier

        return pd.DataFrame(rows)

    def get_all_venues(self, venue_cfg: dict, start: date, end: date) -> pd.DataFrame:
        frames = []
        for venue_name, venue_id in venue_cfg.items():
            log.info(f"  Fetching Ticketmaster events for {venue_name} …")
            df = self.get_events_for_venue(venue_id, venue_name, start, end)
            if not df.empty:
                frames.append(df)
                log.info(f"    → {len(df)} events")
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── Feature enrichment ─────────────────────────────────────────────────────────

def enrich_events(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived columns that become model covariates:
      - is_game_day (bool)
      - game_start_hour (int, local time)
      - hours_until_event (float, relative to each timestamp row —
        computed at join time in feature_engineering.py, not here)
      - is_weekend_event
      - is_playoff
    """
    if df.empty:
        return df

    df = df.copy()
    df["timestamp_start"] = pd.to_datetime(df["timestamp_start"])
    df["is_game_day"] = True
    df["game_start_hour"] = df["timestamp_start"].dt.hour
    df["is_weekend_event"] = df["timestamp_start"].dt.dayofweek >= 5
    # game_type comes from the NHL API as an int (1=preseason, 2=regular,
    # 3=playoff) — comparing to the string "3" was always False.
    df["is_playoff"] = pd.to_numeric(
        df.get("game_type", pd.Series(pd.NA, index=df.index)), errors="coerce"
    ) == 3

    return df


# ── Orchestration ──────────────────────────────────────────────────────────────

def fetch_all(start: date, end: date) -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    frames = []

    # 1. Sharks (NHL)
    log.info("=== Fetching Sharks schedule (NHL API) ===")
    nhl_client = NHLClient()
    sharks_df = nhl_client.get_schedule(
        team=cfg["nhl"]["sharks_team_id"],
        start=start,
        end=end,
    )
    if not sharks_df.empty:
        log.info(f"  {len(sharks_df)} home Sharks games found")
        frames.append(sharks_df)

    # 2. Ticketmaster (concerts, other sports)
    log.info("=== Fetching Ticketmaster events ===")
    tm_key = cfg["ticketmaster"]["api_key"]
    if tm_key == "YOUR_TICKETMASTER_API_KEY":
        log.warning("  Ticketmaster API key not set — skipping Ticketmaster data")
    else:
        tm_client = TicketmasterClient(tm_key)
        tm_df = tm_client.get_all_venues(cfg["ticketmaster"]["venues"], start, end)
        if not tm_df.empty:
            frames.append(tm_df)

    if not frames:
        log.warning("No event data retrieved")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = enrich_events(combined)
    combined = combined.sort_values("timestamp_start").reset_index(drop=True)

    out = RAW_DIR / f"events_{start}_{end}.parquet"
    combined.to_parquet(out, index=False)
    log.info(f"\nTotal events: {len(combined):,} → {out}")
    log.info(f"  Sharks home games: {combined['is_sharks_game'].sum()}")
    log.info(f"  Other events:      {(~combined['is_sharks_game']).sum()}")

    return combined


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch Bay Area event schedules")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    return parser.parse_args()


def main():
    args = parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    fetch_all(start, end)


if __name__ == "__main__":
    main()
