"""
models/baselines/scheduler.py
──────────────────────────────
Nightly pipeline scheduler — keeps the Live demo on your website fresh.

Runs every night at 2am (configurable):
  1. Pull fresh transit data from 511 API
  2. Pull weather forecast from Open-Meteo (7 days ahead)
  3. Pull upcoming events from NHL + Ticketmaster
  4. Merge into feature store
  5. Validate data quality
  6. Run Chronos-2 batch forecast for next 24 hours
  7. Write forecasts to database / cache for the API to serve

This is what keeps the "+34% vs typical" card on your website accurate
rather than stale.

Usage:
    # Run once manually:
    python models/baselines/scheduler.py

    # Set up as a cron job (runs nightly at 2am):
    crontab -e
    # Add: 0 2 * * * cd /path/to/project && python models/baselines/scheduler.py

    # Or run as an APScheduler loop (keeps process alive):
    python models/baselines/scheduler.py --loop
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("scheduler")

CONFIG_PATH   = Path("configs/model.yaml")
PROCESSED_DIR = Path("data/processed")
FORECAST_DIR  = Path("models/chronos2/outputs/nightly")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── Step runners ───────────────────────────────────────────────────────────────

def run_step(name: str, script: str, args: list[str] = None) -> bool:
    """Run a pipeline step as a subprocess. Returns True if successful."""
    cmd = [sys.executable, script] + (args or [])
    log.info(f"\n{'─'*55}")
    log.info(f"▶  {name}")
    log.info(f"   cmd: {' '.join(cmd)}")

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = time.time() - start

        if result.returncode == 0:
            log.info(f"   ✅ Done in {elapsed:.0f}s")
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-5:]:
                    log.info(f"      {line}")
            return True
        else:
            log.error(f"   ❌ Failed (exit {result.returncode}) in {elapsed:.0f}s")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    log.error(f"      {line}")
            return False

    except subprocess.TimeoutExpired:
        log.error(f"   ❌ Timed out after 600s")
        return False
    except Exception as e:
        log.error(f"   ❌ Exception: {e}")
        return False


# ── Inline steps (faster — no subprocess overhead) ────────────────────────────

def step_fetch_weather() -> bool:
    """Pull the 7-day weather forecast for all station locations."""
    try:
        from machine_learning_files.fetch_weather_openmeteo import (
            OpenMeteoClient, fetch_forecast_all_stations, load_config
        )
        cfg = load_config()
        client = OpenMeteoClient()
        station_coords = cfg["weather"]["station_coords"]
        fetch_forecast_all_stations(client, station_coords)
        return True
    except Exception as e:
        log.error(f"Weather fetch failed: {e}")
        return False


def step_fetch_events() -> bool:
    """Pull upcoming events for the next 30 days."""
    try:
        from datetime import date
        from machine_learning_files.fetch_events import fetch_all
        today = date.today()
        end   = today + timedelta(days=30)
        fetch_all(today, end)
        return True
    except Exception as e:
        log.error(f"Events fetch failed: {e}")
        return False


def step_validate() -> bool:
    """Run data quality checks on the merged feature store."""
    try:
        from evaluation.validators import validate_feature_store, ValidationMode

        path = PROCESSED_DIR / "feature_store_enriched.parquet"
        if not path.exists():
            path = PROCESSED_DIR / "feature_store.parquet"
        if not path.exists():
            log.error("Feature store not found")
            return False

        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        results = validate_feature_store(df, mode=ValidationMode.LENIENT)

        errors = [r for r in results if r.severity.value == "ERROR"]
        warnings = [r for r in results if r.severity.value == "WARNING"]
        log.info(f"  Validation: {len(errors)} errors | {len(warnings)} warnings")

        if errors:
            for e in errors:
                log.error(f"  ❌ {e}")
            return False
        return True
    except Exception as e:
        log.error(f"Validation failed: {e}")
        return False


def step_forecast() -> bool:
    """Run batch forecast for all stations and save to nightly output dir."""
    try:
        from models.chronos2.predict import Predictor

        FORECAST_DIR.mkdir(parents=True, exist_ok=True)
        run_ts = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = FORECAST_DIR / f"forecasts_{run_ts}.parquet"
        latest_path = FORECAST_DIR / "forecasts_latest.parquet"

        predictor = Predictor()
        preds = predictor.forecast_all_stations(
            horizon_hours=24,
            output_path=output_path,
        )

        if preds.empty:
            log.error("No forecasts generated")
            return False

        # Symlink / copy as "latest" for the API to serve
        if latest_path.exists():
            latest_path.unlink()
        import shutil
        shutil.copy2(output_path, latest_path)

        log.info(
            f"  Forecast: {len(preds):,} rows | "
            f"{preds['station_id'].nunique()} stations | "
            f"saved to {output_path.name}"
        )
        return True
    except Exception as e:
        log.error(f"Forecast step failed: {e}")
        return False


# ── Full nightly pipeline ──────────────────────────────────────────────────────

class NightlyPipeline:
    """
    Orchestrates all nightly steps with error tracking and reporting.
    Designed to be resilient — a failure in one step doesn't halt others
    (except validation failure halts the forecast step).
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.results: dict[str, bool] = {}
        self.started_at = datetime.now()

    def run(self) -> bool:
        log.info(f"\n{'═'*55}")
        log.info(f"  NIGHTLY PIPELINE — {self.started_at.strftime('%Y-%m-%d %H:%M')}")
        log.info(f"{'═'*55}")

        # Step 1 — Weather forecast (always needed for covariates)
        log.info("\n[1/5] Fetching weather forecast …")
        self.results["weather"] = step_fetch_weather()

        # Step 2 — Events (needed for game-night covariate)
        log.info("\n[2/5] Fetching upcoming events …")
        self.results["events"] = step_fetch_events()

        # Step 3 — Merge pipeline (rebuild feature store with fresh data)
        log.info("\n[3/5] Rebuilding feature store …")
        self.results["merge"] = run_step(
            "Merge pipeline",
            "machine_learning_files/merge_pipeline.py",
        )

        # Step 4 — Validate (gate before forecast)
        log.info("\n[4/5] Validating data quality …")
        self.results["validate"] = step_validate()

        if not self.results["validate"]:
            log.error("Validation failed — skipping forecast to avoid serving bad data")
            self.results["forecast"] = False
            self._report()
            return False

        # Step 5 — Forecast
        log.info("\n[5/5] Running batch forecast …")
        self.results["forecast"] = step_forecast()

        self._report()
        return all(self.results.values())

    def _report(self) -> None:
        elapsed = (datetime.now() - self.started_at).total_seconds()
        n_ok    = sum(1 for v in self.results.values() if v)
        n_total = len(self.results)

        log.info(f"\n{'═'*55}")
        log.info(f"  PIPELINE COMPLETE — {elapsed:.0f}s | {n_ok}/{n_total} steps OK")
        log.info(f"{'═'*55}")
        for step, ok in self.results.items():
            icon = "✅" if ok else "❌"
            log.info(f"  {icon}  {step}")

        if self.results.get("forecast"):
            latest = FORECAST_DIR / "forecasts_latest.parquet"
            if latest.exists():
                preds = pd.read_parquet(latest)
                log.info(f"\n  Live demo ready: {len(preds):,} forecast rows")
                log.info(f"  Stations: {sorted(preds['station_id'].unique())}")


# ── APScheduler loop ───────────────────────────────────────────────────────────

def run_loop(cfg: dict) -> None:
    """
    Keep process alive and run nightly at the configured cron time.
    Alternative to system cron — useful for cloud deployments.
    """
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        log.error("APScheduler not installed. Run: pip install apscheduler")
        log.info("Falling back to a simple sleep loop …")
        _simple_loop(cfg)
        return

    cron = cfg.get("serving", {}).get("nightly_refresh_cron", "0 2 * * *")
    parts = cron.split()
    minute, hour = parts[0], parts[1]

    scheduler = BlockingScheduler(timezone="America/Los_Angeles")
    scheduler.add_job(
        lambda: NightlyPipeline(cfg).run(),
        "cron",
        hour=int(hour),
        minute=int(minute),
        id="nightly_pipeline",
    )
    log.info(f"Scheduler started — running daily at {hour}:{minute} PT")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped by user")


def _simple_loop(cfg: dict) -> None:
    """Fallback loop using time.sleep — no external dependency."""
    while True:
        now = datetime.now()
        # Run at 2am
        target = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        log.info(f"Waiting {wait_secs/3600:.1f}h until next run at {target.strftime('%H:%M')} …")
        time.sleep(wait_secs)
        NightlyPipeline(cfg).run()


# ── Standalone ─────────────────────────────────────────────────────────────────

def main():
    parser = __import__("argparse").ArgumentParser(description="Run nightly pipeline")
    parser.add_argument("--loop", action="store_true",
                        help="Keep running on a schedule (default: run once and exit)")
    parser.add_argument("--step", default=None,
                        choices=["weather", "events", "merge", "validate", "forecast"],
                        help="Run a single step only")
    args = parser.parse_args()

    cfg = load_config()

    if args.step:
        step_fn = {
            "weather":  step_fetch_weather,
            "events":   step_fetch_events,
            "validate": step_validate,
            "forecast": step_forecast,
            "merge":    lambda: run_step("Merge", "machine_learning_files/merge_pipeline.py"),
        }[args.step]
        ok = step_fn()
        sys.exit(0 if ok else 1)

    if args.loop:
        run_loop(cfg)
    else:
        ok = NightlyPipeline(cfg).run()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
