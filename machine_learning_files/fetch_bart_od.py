"""
ingestion/fetch_bart_od.py
──────────────────────────
Downloads BART monthly origin-destination (OD) ridership XLS files
from bart.gov, going back as far as 2005. Converts to tidy parquet files
in data/raw/transit/bart/.

Each monthly OD file contains: (origin_station, dest_station, hour, riders)
disaggregated across all station pairs and hours of the day.

Usage:
    python ingestion/fetch_bart_od.py
    python ingestion/fetch_bart_od.py --start 2020 --end 2024
"""

import argparse
import io
import logging
import time
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("fetch_bart_od")

RAW_DIR = Path("data/raw/transit/bart")

# BART publishes OD files at predictable URLs
# Pattern: https://www.bart.gov/sites/default/files/docs/ridership/DATE-DATE_Ridership_2025.xls
# The structure changed over the years so we handle multiple formats.
BART_OD_BASE = "https://www.bart.gov/sites/default/files/docs/ridership"

# Known filename patterns by year range (BART changes format occasionally)
# We attempt both .xls and .xlsx
YEAR_MONTH_FORMAT = {
    range(2005, 2013): "{year}/Ridership_{month_name}_{year}.xls",
    range(2013, 2020): "{year_month_dash}_Ridership_{year}.xlsx",
    range(2020, 2027): "{year_month_dash}_Ridership_{year}.xlsx",
}

# BART station abbreviation → full name mapping (subset of all 50 stations)
STATION_NAMES = {
    "12TH": "12th St. Oakland City Center",
    "16TH": "16th St. Mission",
    "19TH": "19th St. Oakland",
    "24TH": "24th St. Mission",
    "ANTC": "Antioch",
    "ASHB": "Ashby",
    "BALB": "Balboa Park",
    "BAYF": "Bay Fair",
    "BERY": "Berryessa/North San José",
    "CAST": "Castro Valley",
    "CIVC": "Civic Center/UN Plaza",
    "COLS": "Coliseum",
    "COLM": "Colma",
    "CONC": "Concord",
    "DALY": "Daly City",
    "DBRK": "Downtown Berkeley",
    "DUBL": "Dublin/Pleasanton",
    "DELN": "El Cerrito Del Norte",
    "PLZA": "El Cerrito Plaza",
    "EMBR": "Embarcadero",
    "FRMT": "Fremont",
    "FTVL": "Fruitvale",
    "GLEN": "Glen Park",
    "HAYW": "Hayward",
    "LAFY": "Lafayette",
    "LAKE": "Lake Merritt",
    "MCAR": "MacArthur",
    "MLBR": "Millbrae",
    "MLPT": "Milpitas",
    "MONT": "Montgomery St.",
    "NBRK": "North Berkeley",
    "NCON": "North Concord/Martinez",
    "OAKL": "Oakland International Airport",
    "ORIN": "Orinda",
    "PITT": "Pittsburg/Bay Point",
    "PCTR": "Pittsburg Center",
    "PHIL": "Pleasant Hill/Contra Costa Centre",
    "POWL": "Powell St.",
    "RICH": "Richmond",
    "ROCK": "Rockridge",
    "SBRN": "San Bruno",
    "SFIA": "SFO",
    "SANL": "San Leandro",
    "SHAY": "South Hayward",
    "SSAN": "South San Francisco",
    "UCTY": "Union City",
    "WARM": "Warm Springs/South Fremont",
    "WCRK": "Walnut Creek",
    "WDUB": "West Dublin/Pleasanton",
    "WOAK": "West Oakland",
}


def build_url_candidates(year: int, month: int) -> list[str]:
    """
    Return a list of candidate URLs to try for a given year/month,
    since BART's URL scheme has changed over time.
    """
    month_name = pd.Timestamp(year=year, month=month, day=1).strftime("%B")  # "January"
    ym_dash = f"{year}-{month:02d}"  # "2024-01"

    candidates = [
        f"{BART_OD_BASE}/{ym_dash}_Ridership_{year}.xlsx",
        f"{BART_OD_BASE}/{year}/Ridership_{month_name}_{year}.xlsx",
        f"{BART_OD_BASE}/{ym_dash}_Ridership_{year}.xls",
        f"{BART_OD_BASE}/{year}/Ridership_{month_name}_{year}.xls",
    ]
    return candidates


def download_month(year: int, month: int) -> pd.DataFrame | None:
    """
    Try each candidate URL for a given month.
    Returns a tidy DataFrame or None if all attempts fail.
    """
    for url in build_url_candidates(year, month):
        try:
            log.debug(f"  Trying {url}")
            resp = requests.get(url, timeout=60)
            if resp.status_code == 200:
                try:
                    parsed = parse_bart_od_excel(resp.content, year, month)
                except Exception as e:
                    # A 200 with a non-Excel body (e.g. bart.gov soft-404 HTML)
                    # would otherwise blow up the whole multi-year batch job.
                    log.debug(f"  {url} returned 200 but failed to parse: {e}")
                    continue
                log.info(f"  ✓ {url}")
                return parsed
        except requests.RequestException:
            continue
    log.warning(f"  No file found for {year}-{month:02d}")
    return None


def parse_bart_od_excel(content: bytes, year: int, month: int) -> pd.DataFrame:
    """
    Parse a BART OD Excel file into a tidy long-form DataFrame.

    BART OD files are pivot tables: rows = origin stations, columns = destination
    stations (one sheet per weekday/Saturday/Sunday), with ridership counts.

    Returns columns: year, month, day_type, origin, destination, riders
    """
    xl = pd.ExcelFile(io.BytesIO(content))
    frames = []

    for sheet_name in xl.sheet_names:
        # BART's OD workbooks include a "Total Trips"/"Total Trips OD" sheet
        # alongside the Weekday/Saturday/Sunday averages — it holds the
        # monthly TOTAL across all day types, not another day type to add on
        # top of them. transit_eda/notebooks/eda_complete.py hit this same
        # sheet in real downloaded files and explicitly excludes it before
        # any cross-day-type analysis. This loop had no such exclusion, so
        # merge_pipeline.py::load_transit()'s groupby(...)["riders"].sum()
        # (which collapses all day_types together) would add the "Total"
        # sheet's already-aggregated monthly figure on top of the
        # Weekday+Saturday+Sunday sums for the same station-month, inflating
        # the ridership target the whole pipeline trains against.
        if "total trips" in sheet_name.strip().lower():
            log.debug(f"  Skipping monthly-total sheet '{sheet_name}'")
            continue
        try:
            df = xl.parse(sheet_name, header=0, index_col=0)
            # Drop summary rows/cols (BART includes totals)
            df = df.dropna(how="all").dropna(axis=1, how="all")

            # Normalize index/column names (strip whitespace, uppercase)
            df.index = df.index.astype(str).str.strip().str.upper()
            df.columns = df.columns.astype(str).str.strip().str.upper()

            # Keep only known station codes
            valid_origins = [i for i in df.index if i in STATION_NAMES]
            valid_dests = [c for c in df.columns if c in STATION_NAMES]
            df = df.loc[valid_origins, valid_dests]

            # Melt to long form
            long = df.reset_index().melt(
                id_vars=df.index.name or "index",
                var_name="destination",
                value_name="riders",
            )
            long.columns = ["origin", "destination", "riders"]
            long["riders"] = pd.to_numeric(long["riders"], errors="coerce").fillna(0).astype(int)
            long["day_type"] = sheet_name.strip()
            frames.append(long)
        except Exception as e:
            log.debug(f"  Skipping sheet '{sheet_name}': {e}")

    if not frames:
        raise ValueError("No parseable sheets found in BART OD file")

    result = pd.concat(frames, ignore_index=True)
    result["year"] = year
    result["month"] = month
    result["period"] = pd.Timestamp(year=year, month=month, day=1)

    # Add human-readable station names
    result["origin_name"] = result["origin"].map(STATION_NAMES)
    result["destination_name"] = result["destination"].map(STATION_NAMES)

    return result


def fetch_all(start_year: int, end_year: int) -> None:
    """Download and save all months in the given year range."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_frames = []

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            period = pd.Timestamp(year=year, month=month, day=1)
            if period > pd.Timestamp.now():
                log.info(f"Skipping future period {year}-{month:02d}")
                continue

            out_path = RAW_DIR / f"bart_od_{year}_{month:02d}.parquet"
            if out_path.exists():
                log.info(f"Already downloaded {out_path.name} — loading from cache")
                all_frames.append(pd.read_parquet(out_path))
                continue

            log.info(f"Downloading BART OD for {year}-{month:02d} …")
            df = download_month(year, month)
            if df is not None:
                df.to_parquet(out_path, index=False)
                all_frames.append(df)
                log.info(f"  → {len(df):,} rows saved to {out_path.name}")
            time.sleep(0.8)  # throttle requests

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        out = RAW_DIR / "bart_od_all.parquet"
        combined.to_parquet(out, index=False)
        log.info(f"\nConsolidated dataset: {len(combined):,} rows → {out}")
        print(combined.describe())


def parse_args():
    parser = argparse.ArgumentParser(description="Download BART OD ridership data")
    parser.add_argument("--start", type=int, default=2019, help="Start year (default: 2019)")
    parser.add_argument("--end", type=int, default=pd.Timestamp.now().year, help="End year (default: current)")
    return parser.parse_args()


def main():
    args = parse_args()
    log.info(f"Fetching BART OD ridership from {args.start} to {args.end}")
    fetch_all(args.start, args.end)


if __name__ == "__main__":
    main()
