# Input data manifest

The raw BART ridership data is **not in git** (`data/raw/` is gitignored, and
the workbooks are large). It also cannot be re-fetched automatically: bart.gov
sits behind a Cloudflare bot challenge and answers automated requests with
HTTP 403. See
[`machine_learning_files/bart_od_from_xlsx.py`](../machine_learning_files/bart_od_from_xlsx.py).

This manifest exists so anyone can confirm they hold the same inputs that
produced the published numbers.

## Committed feature store

`data/processed/feature_store.parquet` **is in git** (the rest of
`data/processed/` is not). `Dockerfile.api` bakes it into the serving image, and
without it neither the image nor the API can be built from a clean clone.

| File | Rows | Months | SHA-256 |
|---|---|---|---|
| `feature_store.parquet` | 3,000 (50 stations × 60 months) | 2019-01 → 2025-12, no 2020–21 | `d9135f03f1bd77093353ff39e11185e59dfed50e296fcddedf9dfabf3763c238` |

Its `ridership` column is identical, row for row, to the stores behind the
published leaderboard; SARIMA trained on it through `val_end` scores the
published 3.21% WAPE (`tests/test_api.py` checks this). Rebuilding with the steps
below overwrites it — commit the result only when the change is intended.

## Source archives

Retrieved by hand from bart.gov on **2026-10-21** (browser session; a human
request clears the bot challenge).

| Archive | Workbooks | SHA-256 |
|---|---|---|
| `Ridership Report 2019.zip` | 12 | `599465433bb1f5c28503fe36d4345ae5d3820e7d1fd34aea287e2d961b2b6c92` |
| `BART Ridership 2022.zip` | 12 | `5c8b402b1614843634c5e8eba86b87e1e168582649481f690ea4726d1ffa930f` |
| `Ridership 2023 (2).zip` | 12 | `a90b928f6c84ddbde3f9555f6d23f7b8ace54665003947ab49bd1838a4ea3cce` |
| `Ridership 2024.zip` | 12 | `b4b66414acda2ea6ce26ba68d3bd2f048cc158d3936c3c17cdbd026bf047a666` |
| `Ridership 2025 (1).zip` | 12 | `247fb1502bbdbe6dd5e609f421f7bdce5fbeb51143d589de59a009d50127d200` |

**60 monthly workbooks**, named `Ridership_YYYYMM.xlsx`, covering
**2019-01 → 2025-12**.

**2020 and 2021 are absent** — BART did not publish OD workbooks for those
years in this series. The feature store therefore jumps 2019 → 2022 across a
~2.9x ridership collapse, which is why `configs/model.yaml` sets
`train_start: 2022-01-01`: training across that discontinuity is what made the
Prophet baseline diverge.

Verify your copies with:

```bash
shasum -a 256 "Ridership Report 2019.zip" "BART Ridership 2022.zip" \
              "Ridership 2023 (2).zip" "Ridership 2024.zip" \
              "Ridership Report 2025 (1).zip"
```

## Workbook format

Two vintages, both handled:

| | 2019–2023 | 2024–2025 |
|---|---|---|
| Sheet names | `Total Trips OD`, `Avg Weekday OD`, `Avg Saturday OD`, `Avg Sunday OD` | `Total Trips`, `Average Weekday`, `Average Saturday`, `Average Sunday` |
| Station-code header | row 1 | row 4 |

Rows are exit stations, columns entry stations, cells are riders. Station codes
are two letters, plus the numeric `12`, `16`, `19`, `24` (12th St, 16th St
Mission, 19th St, 24th St Mission) — **50 stations** throughout.
`machine_learning_files/bart_stations.py` maps each code to its station name.

## Verified sheet semantics

The three `Avg` sheets give average riders on a single day of that type;
`Total Trips` is the month's actual count. Confirmed against BART's own
identity rather than assumed from the labels:

```
avg_weekday x n_weekdays + avg_sat x n_saturdays + avg_sun x n_sundays  ==  total_trips
```

| Vintage | Months | Identity ratio |
|---|---|---|
| 2019–2023 | 36 | min 1.0000, median **1.0000** |
| 2024–2025 | 24 | median 1.0199, max 1.0783 |

Exact for the older vintage. The small excess in newer months is holidays
running weekend service on a weekday.

**`ridership` in the feature store is the `Total Trips` block summed over
destinations, keyed on the entry station** — i.e. monthly boardings. See
`load_bart()` in
[`machine_learning_files/merge_pipeline.py`](../machine_learning_files/merge_pipeline.py).

## Rebuilding

```bash
python machine_learning_files/bart_od_from_xlsx.py --zips /path/to/*.zip
python machine_learning_files/merge_pipeline.py
python Processing/feature_engineering.py
```

Produces 60 monthly parquets → 3,000 station-month rows (60 x 50).

`machine_learning_files/bart_od_from_csv.py` is a fallback that builds months
from the checked-in `transit_eda/data/bart_clean.csv`. That CSV contains only
the three `Avg` sheets, so it **cannot** define the `Total Trips` target;
`load_bart()` raises if any month lacks exactly one Total block.

## Other sources

| Source | Key needed | Notes |
|---|---|---|
| Open-Meteo weather | none | `fetch_weather_openmeteo.py`; 7 station locations, hourly |
| Ticketmaster / NHL events | free Ticketmaster key | absent here, so `is_game_day`, `is_sharks_game`, `is_sharks_game_window` are constant zero |
| 511 SF Bay transit | free 511 key | **not currently used** — `merge_pipeline.py:95` is a placeholder |
