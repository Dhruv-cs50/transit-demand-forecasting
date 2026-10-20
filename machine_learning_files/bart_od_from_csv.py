#!/usr/bin/env python3
"""
machine_learning_files/bart_od_from_csv.py
──────────────────────────────────────────
Build the per-month BART OD parquet files that merge_pipeline.py expects,
from the checked-in data/bart_clean.csv instead of bart.gov.

Why this exists
───────────────
fetch_bart_od.py downloads monthly OD workbooks from bart.gov. That host now
sits behind a Cloudflare bot challenge: every candidate URL returns HTTP 403
with an "Enable JavaScript and cookies to continue" interstitial, so the
fetcher retrieves nothing. It also exits 0 while doing so, which is why the
failure went unnoticed.

data/bart_clean.csv is already in the repository and carries the same OD
records (year, month, day_type, origin, destination, riders), so the pipeline
can be fed from it and the feature store rebuilt without touching bart.gov.

This is a reproducibility shim, not a replacement for the real fetcher: it can
only cover months already present in the CSV. Use fetch_bart_od.py when
bart.gov is reachable (e.g. from a browser session or an allow-listed host) to
extend coverage.

Usage
─────
    python machine_learning_files/bart_od_from_csv.py
    python machine_learning_files/bart_od_from_csv.py --start 2019 --end 2024
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_bart_od import STATION_NAMES  # single source of truth for code -> name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bart_od_from_csv")

# transit_eda/data/ is the tracked location; data/ is where some working copies
# keep it. Checked in order so a clean checkout works without arguments.
CSV_CANDIDATES = [
    Path("transit_eda/data/bart_clean.csv"),
    Path("data/bart_clean.csv"),
]
OUT_DIR = Path("data/raw/transit/bart")


def resolve_csv() -> Path | None:
    return next((p for p in CSV_CANDIDATES if p.exists()), None)

# merge_pipeline.load_bart() groups on these, so all four must be present.
REQUIRED = ["period", "origin", "origin_name", "riders"]


def build(csv_path: Path, out_dir: Path, start: int, end: int) -> int:
    if not csv_path.exists():
        log.error(f"{csv_path} not found — nothing to convert")
        return 0

    # Several BART station codes are numeric strings ("12" for 12th St Oakland,
    # "16"/"24" for the Mission stations, "19" for 19th St). Left to infer,
    # pandas turns those into floats and the codes become "12.0", which matches
    # nothing downstream. The published station_ids are plain "12", so these
    # must stay strings.
    df = pd.read_csv(csv_path, dtype={"origin": str, "destination": str})
    missing = {"year", "month", "origin", "riders"} - set(df.columns)
    if missing:
        log.error(f"{csv_path} is missing expected columns: {sorted(missing)}")
        return 0

    # The CSV was itself written from a frame whose code column had already
    # been coerced to float, so the numeric codes arrive as "12.0"/"19.0".
    # Published station_ids are "12"/"19", so strip the artefact.
    for col in ("origin", "destination"):
        if col in df.columns:
            df[col] = df[col].str.replace(r"^(\d+)\.0$", r"\1", regex=True)

    df["riders"] = pd.to_numeric(df["riders"], errors="coerce")
    bad_riders = df["riders"].isna().sum()
    if bad_riders:
        log.warning(f"Dropping {bad_riders} rows with non-numeric riders")
        df = df.dropna(subset=["riders"])

    df = df[(df["year"] >= start) & (df["year"] <= end)]
    if df.empty:
        log.warning(f"No rows in {start}-{end}")
        return 0

    # load_bart() drops any day_type containing "total" to avoid summing a
    # workbook's own monthly total on top of its per-day-type sheets. Assert the
    # assumption rather than trusting it silently.
    if "day_type" in df.columns:
        totals = df["day_type"].str.contains("total", case=False, na=False).sum()
        if totals:
            log.warning(f"{totals} 'Total' day_type rows present — load_bart will drop them")

    df["period"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01"
    )
    df["origin_name"] = df["origin"].map(STATION_NAMES).fillna(df["origin"])

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for (year, month), group in df.groupby(["year", "month"], sort=True):
        cols = [c for c in ["period", "origin", "origin_name", "destination",
                            "day_type", "riders"] if c in group.columns]
        out = out_dir / f"bart_od_{year}_{int(month):02d}.parquet"
        group[cols].to_parquet(out, index=False)
        written += 1

    stations = df.loc[df["origin"].astype(str).str.len() <= 4, "origin"].nunique()
    log.info(f"Wrote {written} monthly parquet files → {out_dir}")
    log.info(f"  {len(df):,} OD rows | {stations} station codes (<=4 chars) | "
             f"{df['period'].min().date()} → {df['period'].max().date()}")
    unmapped = df.loc[~df["origin"].isin(STATION_NAMES), "origin"].nunique()
    if unmapped:
        log.info(f"  {unmapped} origin codes had no STATION_NAMES entry (name = code)")
    return written


def main():
    p = argparse.ArgumentParser(description="Build BART OD parquets from bart_clean.csv")
    p.add_argument("--csv", default=None, help="defaults to the first of "
                   + ", ".join(str(c) for c in CSV_CANDIDATES) + " that exists")
    p.add_argument("--out", default=str(OUT_DIR))
    p.add_argument("--start", type=int, default=2019)
    p.add_argument("--end", type=int, default=pd.Timestamp.now().year)
    args = p.parse_args()

    csv_path = Path(args.csv) if args.csv else resolve_csv()
    if csv_path is None:
        log.error("bart_clean.csv not found in "
                  + ", ".join(str(c) for c in CSV_CANDIDATES))
        sys.exit(1)

    written = build(csv_path, Path(args.out), args.start, args.end)
    if written == 0:
        # Unlike fetch_bart_od.py, do not exit 0 having produced nothing.
        log.error("No files written")
        sys.exit(1)


if __name__ == "__main__":
    main()
