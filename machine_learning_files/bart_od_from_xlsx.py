#!/usr/bin/env python3
"""
machine_learning_files/bart_od_from_xlsx.py
───────────────────────────────────────────
Build the per-month BART OD parquet files from BART's own Ridership_YYYYMM.xlsx
workbooks, read from local zips or a directory.

Why this exists rather than fetch_bart_od.py
────────────────────────────────────────────
`fetch_bart_od.py` cannot produce these files, for two independent reasons:

1. bart.gov answers every candidate URL with HTTP 403 behind a Cloudflare bot
   challenge, so nothing downloads.
2. Its `parse_bart_od_excel()` does not match the real workbook format. It uses
   `header=0`, but the sheets carry a two-row header (row 0 is a banner, row 1
   holds the entry-station codes), and it filters codes against STATION_NAMES,
   which is keyed by four-letter BART API codes (EMBR, MLBR) while the
   workbooks use two-letter codes (EM, MB) plus the numeric 12/16/19/24. Run
   against a real workbook it returns **zero rows** — and returns rather than
   raises, so the caller would have written empty parquet files and counted
   them as success.

So the workbooks must be fetched by hand (a browser session clears the bot
challenge) and converted here.

Station names come from the station table, `bart_stations.py`, whose
CODE_TO_NAME is keyed by the workbooks' own two-letter codes. (This module
used to map through STATION_NAMES, which never matched a workbook code, so
parquets built before the table carry the code as the name.)

Sheet semantics, verified not assumed
─────────────────────────────────────
Each workbook has four sheets: `Avg Weekday OD`, `Avg Saturday OD`,
`Avg Sunday OD`, `Total Trips OD`. The first three are average riders on a day
of that type; the last is the month's actual trip count. BART's own identity
holds **exactly** on every month checked:

    avg_weekday x n_weekdays + avg_sat x n_saturdays + avg_sun x n_sundays
        == total_trips_od          (ratio 1.0000)

All four sheets are written through, with `day_type` carrying the sheet name, so
downstream code can choose its target. `merge_pipeline.load_bart()` currently
drops any `day_type` containing "total" and sums the remaining three — which
yields a sum of daily averages, not a monthly quantity. Choosing the target is
deliberately left to that module.

Usage
─────
    python machine_learning_files/bart_od_from_xlsx.py --zips ~/Downloads/*.zip
    python machine_learning_files/bart_od_from_xlsx.py --dir path/to/xlsx
"""

from __future__ import annotations

import argparse
import glob
import logging
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from bart_stations import CODE_TO_NAME  # two-letter workbook code -> name
except ImportError:  # keep usable if the table moves; build() then warns
    CODE_TO_NAME = {}  # that every code is missing from it

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bart_od_from_xlsx")

OUT_DIR = Path("data/raw/transit/bart")
MONTH_RE = re.compile(r"Ridership_(\d{4})(\d{2})\.xlsx$", re.IGNORECASE)

# Labels that appear in the station rows/columns but are aggregates, not stations.
AGGREGATE_LABELS = {"EXITS", "ENTRIES", "TOTAL", "TOTALS", "GRAND TOTAL", "NAN", ""}

STATION_CODE_RE = re.compile(r"^[A-Z]{2}$")
NUMERIC_CODES = {"12", "16", "19", "24"}   # 12th St, 16th St, 19th St, 24th St


def _clean_code(value) -> str | None:
    """Normalise a station code cell. Numeric codes (12, 16, 19, 24) arrive from
    Excel as floats and must not become '12.0'."""
    if pd.isna(value):
        return None
    code = str(value).strip().upper()
    if code.endswith(".0"):
        code = code[:-2]
    if not code or code in AGGREGATE_LABELS:
        return None
    return code


def _is_station_code(code: str | None) -> bool:
    """BART station codes are two letters, plus the numeric 12/16/19/24."""
    return bool(code) and (STATION_CODE_RE.match(code) or code in NUMERIC_CODES)


def _find_header_row(raw: pd.DataFrame, max_scan: int = 12) -> int | None:
    """Locate the row holding the entry-station codes.

    The header is not at a fixed offset: workbooks up to 2023 put the codes on
    row 1, while the 2024 format onwards adds banner, date and '# of Exits' rows
    and puts them on row 4. Rather than hardcode either, pick the row in the
    first `max_scan` with the most recognisable station codes.
    """
    best_row, best_count = None, 0
    for r in range(min(max_scan, raw.shape[0])):
        count = sum(1 for c in range(1, raw.shape[1])
                    if _is_station_code(_clean_code(raw.iloc[r, c])))
        if count > best_count:
            best_row, best_count = r, count
    # A real OD header carries dozens of codes; anything less is a stray label.
    return best_row if best_count >= 10 else None


def parse_sheet(path: Path, sheet: str) -> pd.DataFrame:
    """One sheet of an OD pivot table to long form.

    Rows are exit stations, columns are entry stations.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)

    header_row = _find_header_row(raw)
    if header_row is None:
        return pd.DataFrame(columns=["origin", "destination", "riders"])

    entry_cols = {}
    for c in range(1, raw.shape[1]):
        code = _clean_code(raw.iloc[header_row, c])
        if _is_station_code(code):
            entry_cols[c] = code

    records = []
    for r in range(header_row + 1, raw.shape[0]):
        exit_code = _clean_code(raw.iloc[r, 0])
        if not _is_station_code(exit_code):
            continue
        for c, entry_code in entry_cols.items():
            riders = pd.to_numeric(raw.iloc[r, c], errors="coerce")
            if pd.notna(riders):
                records.append((entry_code, exit_code, float(riders)))

    return pd.DataFrame(records, columns=["origin", "destination", "riders"])


def parse_workbook(path: Path, year: int, month: int) -> pd.DataFrame:
    """All sheets of one workbook, long form, with day_type and period."""
    frames = []
    for sheet in pd.ExcelFile(path).sheet_names:
        df = parse_sheet(path, sheet)
        if df.empty:
            log.warning(f"  {path.name}: sheet '{sheet}' produced no rows")
            continue
        df["day_type"] = sheet.strip()
        frames.append(df)

    if not frames:
        raise ValueError(f"{path.name}: no parseable sheets")

    out = pd.concat(frames, ignore_index=True)
    out["year"] = year
    out["month"] = month
    out["period"] = pd.Timestamp(year=year, month=month, day=1)
    # A code missing from the table keeps the code as its name; build() warns.
    out["origin_name"] = out["origin"].map(CODE_TO_NAME).fillna(out["origin"])
    out["destination_name"] = out["destination"].map(CODE_TO_NAME).fillna(out["destination"])
    return out


def collect_workbooks(zips: list[str], directory: str | None, workdir: Path) -> list[Path]:
    """Expand zips into workdir and gather every Ridership_YYYYMM.xlsx."""
    found: list[Path] = []

    for pattern in zips or []:
        for zpath in glob.glob(pattern):
            with zipfile.ZipFile(zpath) as zf:
                members = [m for m in zf.namelist() if MONTH_RE.search(m)]
                if not members:
                    log.warning(f"{Path(zpath).name}: no Ridership_YYYYMM.xlsx inside")
                    continue
                zf.extractall(workdir, members=members)
                log.info(f"{Path(zpath).name}: {len(members)} workbook(s)")
    found.extend(Path(p) for p in glob.glob(str(workdir / "**" / "*.xlsx"), recursive=True))

    if directory:
        found.extend(Path(p) for p in
                     glob.glob(str(Path(directory) / "**" / "*.xlsx"), recursive=True))

    return sorted({p for p in found if MONTH_RE.search(p.name)})


def build(zips, directory, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        workbooks = collect_workbooks(zips, directory, Path(tmp))
        if not workbooks:
            log.error("No Ridership_YYYYMM.xlsx workbooks found")
            return 0

        log.info(f"Converting {len(workbooks)} workbook(s) → {out_dir}")
        written = 0
        summary = []
        unknown_codes: set[str] = set()
        for path in workbooks:
            m = MONTH_RE.search(path.name)
            year, month = int(m.group(1)), int(m.group(2))
            try:
                df = parse_workbook(path, year, month)
            except Exception as e:
                log.error(f"  {path.name}: {type(e).__name__}: {e}")
                continue
            unknown_codes |= (set(df["origin"]) | set(df["destination"])) - set(CODE_TO_NAME)

            cols = ["period", "year", "month", "day_type", "origin", "origin_name",
                    "destination", "destination_name", "riders"]
            df[cols].to_parquet(out_dir / f"bart_od_{year}_{month:02d}.parquet", index=False)
            written += 1

            total = df.loc[df["day_type"].str.contains("total", case=False), "riders"].sum()
            summary.append((f"{year}-{month:02d}", len(df), total))

        for period, rows, total in summary[:3]:
            log.info(f"  {period}: {rows:,} rows | total trips {total:,.0f}")
        if len(summary) > 3:
            log.info(f"  … and {len(summary) - 3} more month(s)")

        months = sorted(s[0] for s in summary)
        if months:
            log.info(f"Wrote {written} month(s): {months[0]} → {months[-1]}")
        if unknown_codes:
            log.warning(
                f"{len(unknown_codes)} workbook station code(s) not in "
                f"bart_stations.py, named by their code: {sorted(unknown_codes)}"
            )
        return written


def main():
    p = argparse.ArgumentParser(description="Build BART OD parquets from xlsx workbooks")
    p.add_argument("--zips", nargs="*", default=[],
                   help="zip archives containing Ridership_YYYYMM.xlsx")
    p.add_argument("--dir", default=None, help="directory of .xlsx workbooks")
    p.add_argument("--out", default=str(OUT_DIR))
    args = p.parse_args()

    if not args.zips and not args.dir:
        p.error("pass --zips and/or --dir")

    if build(args.zips, args.dir, Path(args.out)) == 0:
        # Never exit 0 having produced nothing; that is how the original fetcher
        # hid its own failure.
        log.error("No parquet files written")
        sys.exit(1)


if __name__ == "__main__":
    main()
