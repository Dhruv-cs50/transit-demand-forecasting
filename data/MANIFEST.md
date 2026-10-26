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
| `feature_store.parquet` | 3,000 (50 stations × 60 months) | 2019-01 → 2025-12, no 2020–21 | `aa02436d44b5de83d77fab87036c046d0ca02983b9d8cbe807c37f9ad714f241` |

Built from the 60 workbooks plus the weather and events archives listed under
[Covariate archives](#covariate-archives), with the code at the commit that last
changed this file. A rebuild from the same inputs gives the same bytes in the
environment that built it: Python 3.14.0, pandas 3.0.6, numpy 2.5.4, pyarrow
26.0.0. `machine_learning_files/requirements.txt` sets only lower bounds, and
other library versions can write different bytes, so outside that environment
compare values (`pandas.testing.assert_frame_equal`), not the hash. Its
`ridership` column is identical, row for row, to the stores behind the
published leaderboard; SARIMA trained on it through `val_end` scores the
published 3.21% WAPE (`tests/test_api.py` checks this). Rebuilding with the steps
below overwrites it — commit the result only when the change is intended.

Weather covers every store month, 2019 and 2022–2025, with no gaps. It is
observed weather, so for the Jul–Dec 2025 test window it is hindsight, not a
forecast.

The events archive starts on 2019-09-17, so it misses the Sharks' 2018–19
home games: the regular season through April 2019 and the playoff games that
ran into May 2019. Those five months read as months without a game
(`is_game_day` false, `hours_to_event` 0.0), the same as an off-season month.
That is a gap in the data, not an observation. From Sep 2019 on, game days mark
Jan–Apr and Sep–Dec, 8 store months a year: 1,800 of the 3,000 station-months
have `is_game_day` true. (The archive flags no playoff games; the Sharks made no
playoffs in 2022–2025.)

No ranked model reads these columns: SARIMA, Prophet and SeasonalNaive are
univariate, and the Chronos-1 zero-shot path falls back to univariate.

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

The store's weather and event columns come from four raw files, also not in
git. Put them under `data/raw/weather/` and `data/raw/events/` before
rebuilding. `merge_pipeline.py` reads every `weather_all_stations_*.parquet`
and `events_*.parquet` there. With any of them missing, the rebuild still runs,
but the weather columns come out NaN and the event columns false for the
missing years, and the bytes differ from the committed store. It also reads
the newest `weather_forecast_*.parquet` (a 7-day-ahead forecast). There is none
in the folder the committed store was built from, and holding one changes the
store. Both sources are free and need no key. The 2024–2025 files were fetched
on 2026-10-24.

| File | Contents | SHA-256 |
|---|---|---|
| `weather_all_stations_2019-01-01_2023-12-31.parquet` | Open-Meteo hourly weather, 2019–2023, 306,768 rows (`fetch_weather_openmeteo.py`) | `3ae3ce7280077bc6b05ef6f2d9b65310d2c44574f6f9a957d6f8474a9f83a4a9` |
| `weather_all_stations_2024-01-01_2025-12-31.parquet` | Open-Meteo hourly weather (archive API), 2024–2025, 122,808 rows | `c60b28184932a21d734b7f03536c5f0cb7afd957ac5d177c77d0c157f80ce72e` |
| `events_2019-01-01_2023-12-31.parquet` | 174 San Jose Sharks home games at SAP Center, Sep 2019 → Dec 2023 (Jan–May 2019 missing, see above), from the NHL API (`fetch_events.py`) | `23748ca287ec18900a44b0cc6b1ad5dcc392a15afe140f5bd7b1bb3637c8ca27` |
| `events_2024-01-01_2025-12-31.parquet` | 93 Sharks home games, Jan 2024 → Dec 2025, from the NHL API | `4c8203738470dc1dcf417a368726530f06338241a336f08619c6c057c0e87c08` |

### How the archives were fetched

Also gitignored, under `data/raw/weather/` and `data/raw/events/`. `merge_pipeline.py` loads
every `weather_all_stations_*.parquet` and every `events_*.parquet`, so the two date ranges below
are read together; they do not overlap.

| Range | Fetched | Command |
|---|---|---|
| 2019-01-01 → 2023-12-31 | before this manifest (file dates 2026-05-07) | `fetch_weather_openmeteo.py` / `fetch_events.py` defaults of that time |
| 2024-01-01 → 2025-12-31 | **2026-10-24T11:06:49Z** | `fetch_weather_openmeteo.py --start 2024-01-01 --end 2025-12-31`, `fetch_events.py --start 2024-01-01 --end 2025-12-31` |

Weather: Open-Meteo archive API, hourly, 7 locations (`configs/sources.yaml`
`weather.station_coords`), no key. 2024–25: 17,544 hourly rows per location (731 days × 24), no
missing values; same columns and dtypes as the 2019–2023 file. Events: San Jose Sharks home games
from the NHL API (`api-web.nhle.com`), no key. 2019–2023: 174 games (163 regular season, 11
preseason); 2024–25: 93 games (86 regular season, 7 preseason). Ticketmaster (concerts, other
venues) needs a key, which this project does not have, so no other events are in either archive.

The per-location `weather_<location>_<range>.parquet` files are the fetcher's intermediate
outputs; the pipeline reads only the `weather_all_stations_*` files. Open-Meteo's archive is a
reanalysis that can be revised, so a re-fetch may not match these hashes byte for byte.

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
| Open-Meteo weather | none | `fetch_weather_openmeteo.py`; 7 station locations, hourly; archived 2019–2025 (above) |
| NHL schedule (Sharks) | none | `fetch_events.py`; home games at SAP Center, archived Sep 2019 → Dec 2025 (above) |
| Ticketmaster events | free Ticketmaster key | not set, so `fetch_events.py` skips it; no concerts or other venues in the store |
| 511 SF Bay transit | free 511 key | **not currently used** — `merge_pipeline.py:95` is a placeholder |
