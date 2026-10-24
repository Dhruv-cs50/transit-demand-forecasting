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
| `feature_store.parquet` | 3,000 (50 stations × 60 months) | 2019-01 → 2025-12, no 2020–21 | `9a7771080c592a1206c4d7553d78012157df958d3a6bda279895a2151a323cea` |

Built from the 60 workbooks plus the weather and events archives listed under
[Covariate archives](#covariate-archives), with the code at the commit that last
changed this file. A rebuild from the same inputs gives the same bytes. Its
`ridership` column is identical, row for row, to the stores behind the
published leaderboard; SARIMA trained on it through `val_end` scores the
published 3.21% WAPE (`tests/test_api.py` checks this). Rebuilding with the steps
below overwrites it — commit the result only when the change is intended.

Weather and events cover 2019–2023 only. In 2024 and 2025, every weather column
is NaN and `is_game_day`/`is_sharks_game` are false. So the training year 2024
and the Jul–Dec 2025 test window carry neither. No ranked model reads these
columns: SARIMA, Prophet and SeasonalNaive are univariate, and the Chronos-1
zero-shot path falls back to univariate.

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

## Covariate archives

The store's weather and event columns come from two raw archives, also not in
git. Put them under `data/raw/weather/` and `data/raw/events/` before
rebuilding. `merge_pipeline.py` reads every `weather_all_stations_*.parquet`
and `events_*.parquet` there. Without them the rebuild still runs, but the
weather columns come out NaN and the event columns false, and the bytes differ
from the committed store.

| File | Contents | SHA-256 |
|---|---|---|
| `weather_all_stations_2019-01-01_2023-12-31.parquet` | Open-Meteo hourly weather, 2019–2023, 306,768 rows (`fetch_weather_openmeteo.py`) | `3ae3ce7280077bc6b05ef6f2d9b65310d2c44574f6f9a957d6f8474a9f83a4a9` |
| `events_2019-01-01_2023-12-31.parquet` | 174 San Jose Sharks home games at SAP Center, Sep 2019 → Dec 2023, from the NHL API (`fetch_events.py`) | `23748ca287ec18900a44b0cc6b1ad5dcc392a15afe140f5bd7b1bb3637c8ca27` |

## Rebuilding

```bash
python machine_learning_files/bart_od_from_xlsx.py --zips /path/to/*.zip   # or --dir /path/to/workbooks
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
| NHL events | none | Sharks home games, archived for 2019–2023 (above); no event data for 2024–2025, so `is_game_day` and `is_sharks_game` are false there |
| Ticketmaster events | free Ticketmaster key | absent here; no concerts or other venues in the store |
| 511 SF Bay transit | free 511 key | **not currently used** — `merge_pipeline.py:95` is a placeholder |
