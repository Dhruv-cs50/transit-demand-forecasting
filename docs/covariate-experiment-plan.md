# Do weather and event covariates improve the monthly BART forecast? — plan

**Status: approved by the user, 2026-10-24.** Choices: the three SARIMAX arms only; a separate
experiment table (not the leaderboard); stacked on PR #139; the lag-gap fix as its own small PR.
The decision rule below was committed before any covariate arm was scored. Branch
`feat/covariate-benchmark`, cut from `origin/fix/bart-station-table` @ `7598107` (first drafted on
`origin/sprint3/pr-backlog` @ `32a75df`).

## The question, and how the run answers it

Today no ranked model reads a covariate (PR #141, `docs/site-claims-audit.md`, "The covariate
question"). The experiment adds covariates to the leaderboard's best model and changes nothing
else, so any difference in score is the covariates' doing.

**Decision rule, fixed before any score is seen.** An arm "improves the forecast" only if all three
hold:

1. its test WAPE (Jul–Dec 2025, n = 300) is below SARIMA's on the same run;
2. **station-clustered paired test** against SARIMA gives p < 0.05: for each of the 50 stations,
   the mean over the 6 test months of |error SARIMA| − |error arm|, then a one-sample t-test on
   those 50 numbers;
3. it is also below SARIMA on the validation window (fit through Dec 2024, scored Jan–Jun 2025).

Otherwise the copy says "no measurable improvement". Every arm is reported; none is picked after
the fact; no covariate choice is tuned on the test window.

Reported alongside, not used to decide: the row-level Diebold–Mariano test already in
`benchmarks.py:281` (a t-test on 300 absolute-error differences, which treats rows that share
months and stations as independent, so its p-value is optimistic) and the number of stations where
each arm wins. **Code needed:** `benchmarks.py:571` only runs DM when an `AutoGluon_Ensemble` row
exists, so both tests have to be wired in for the new arms.

## Facts the plan rests on (checked in this session)

| Fact | Evidence |
|---|---|
| Weather for 2024–25 is fetchable, free, no key | Open-Meteo archive returned hourly data for 2025-12-30/31 at Embarcadero |
| The Sharks schedule is fetchable, free, no key | `fetch_events.py` uses the NHL API (`api-web.nhle.com`), not Ticketmaster. 2024-25 season: 45 home games; 2025-26: 24 home games by 2025-12-31 |
| Ticketmaster only adds non-Sharks events | `fetch_events.py:298-306`. Not needed here. Whether its Discovery API serves past events at all was not verified |
| Today's event archive | 174 Sharks home games (163 regular season, 11 preseason); in store years 2019 / 2022 / 2023: 26 / 46 / 41 |
| Events are network-wide | `merge_pipeline.py:366-431` counts events per month and gives every station the same value. A per-station fit can still learn a per-station effect |
| On the backlog base no station gets its own weather | From code: `merge_pipeline.py:85-92` keys the map on four-letter codes (`EMBR`…), while the store's `station_id`s are two-letter (`12`, `16`, …, `AN`, `BE`; read from the gate2 store). So all 50 stations get the 7-location regional mean. PR #139 maps 6 stations |
| No ranked model, and no planned arm, reads a lag column | SARIMA, Prophet, seasonal naive read `ridership`; Chronos reads `ridership` plus the list in `zero_shot.py:121-126`, which has no lag column |
| Every leaderboard row reaches the site, and the site crowns the lowest WAPE | `export_website_data.py` `export_model_comparison()` copies each overall leaderboard row into `website/data/model_comparison.json`; #140's `sections.jsx:282` takes the minimum-WAPE row as "best model" |
| Filling 2024–25 events adds slice rows | `benchmarks.py:251-264` writes a `game_day` slice row whenever `is_game_day` is true in the test window. Today `benchmark_results.csv` has only `overall` and `holiday` slices; Oct–Dec 2025 will add `game_day` rows for every model. Nothing published reads `benchmark_results.csv` |
| A full benchmark run takes about 2.5 minutes | `bench1.log` (calibration session, 2026-10-24): 03:41:12 → 03:43:48 |

## Steps, cheapest first

| # | Step | Work | Network / compute | Effect on what exists |
|---|---|---|---|---|
| 0 | Rebuild the pinned env outside `/tmp` | **done**: `~/.venvs/tdf-py314`, the gate env's 66 pins plus pip and setuptools, from the pip cache (`OK pandas 3.0.6, torch 2.14.1`, `Chronos2Pipeline` imports) | none | none |
| 1a | Weather 2024–25 | `fetch_weather_openmeteo.py --start 2024-01-01 --end 2025-12-31`. Keeps the 2019–2023 file, so those years are unchanged. SHA-256 and fetch date go in `data/MANIFEST.md` | 7 requests, seconds | overall rows of the 4 models: unchanged (to verify by re-run) |
| 1b | Sharks games 2024–25 | `fetch_events.py --start 2024-01-01 --end 2025-12-31`. Ticketmaster skipped, so "events" stays Sharks home games only | 3 requests | overall rows unchanged (to verify); new `game_day` slice rows in `benchmark_results.csv` |
| 2 | Lag gap fix | `add_lag_features` shifts by calendar month instead of by row: a 2022 row whose lag falls in 2020–21 gets NaN instead of a 2019 value. Unit test on a gapped series. **Off the critical path:** no arm reads lags | none | leaderboard unchanged (to verify). Makes #141's feature-catalog footnote ("rows back", 2020–21 gap) stale |
| 3 | Covariate model | SARIMAX with `exog` on the same per-station SARIMA (0,1,1)(0,1,1,12), same training window (Jan 2022 – Jun 2025). Exog standardised with each station's training-window mean and SD. About 60 lines in `arima.py` | 3 extra SARIMA passes, ~1 min each | adds arms only |
| 4 | Score and publish | One seeded run on the published split. One validation run: `val_end` overridden to 2024-12-31 **in memory** (not in `configs/model.yaml`) and the store truncated to ≤ 2025-06-30, so the test slice is exactly 6 months (otherwise `accept_model_rows` rejects every 6-step model). Evidence doc, both tests, per-station wins. Site and README copy only for what the run shows | ~4 benchmark runs in all | see "Where the rows go" |

### The arms (step 3)

Covariate set fixed now, the same for every model family:

| Row label | Covariates (store columns) |
|---|---|
| `SARIMA` (control, existing 3.21 %) | none; must reproduce exactly |
| `SARIMAX + weather (observed)` | monthly mean `temp_f`, `precip_mm` |
| `SARIMAX + Sharks games` | Sharks home games in the month (`hours_to_event`, which counts every event in the archive; the archive holds only Sharks home games) |
| `SARIMAX + weather (observed) + Sharks games` | all three |

**Why SARIMAX first.** It is the 3.21 % model with one change, so it answers the question
directly. Prophet (5.75 %) with regressors would answer it for a weaker model; skip unless asked.

**Optional: Chronos-2.** `amazon/chronos-2` through `Chronos2Pipeline`, the only pipeline in
chronos-forecasting 2.3.2 whose `predict_df` takes `future_df`. Two rows, univariate and with the
covariates above, because a Chronos-2 row alone mixes a new checkpoint with new inputs. It must
**not** use `zero_shot.py`'s default list, which feeds a constant `hour_of_day` and calendar flags
that describe the 1st of the month. Cost: about 0.5 GB downloaded once from Hugging Face (not in
the local cache), about 80 lines in `predict.py` and `zero_shot.py`, a few CPU minutes. It adds a
new foundation-model result whatever the covariates do.

## Where the rows go (needs a decision)

An observed-weather row is not a forecast anyone could have made on 30 June 2025. If it lands on
the leaderboard as it stands, the export copies it into `model_comparison.json` and the site could
crown it "best model".

- **Separate experiment table (recommended).** Arms go to `evaluation/outputs/covariate_experiment.csv`
  with the control, both tests and the validation scores. The leaderboard, the export and the site's
  best-model pick stay as they are. The site gets one short "Do weather and events help?" result
  in the copy. An arm that passes the rule and is deployable (Sharks games only) can be promoted to
  the leaderboard afterwards, as its own decision.
- **Leaderboard rows with a label.** Arms go on the leaderboard; the export marks rows using
  observed weather, and `sections.jsx` excludes them from "best model". More code, touching #140's
  logic.

## Two caveats the published copy must carry

**Observed weather is a perfect forecast.** The weather rows use what was later observed, so they
are an upper bound: if they do not beat SARIMA, no real weather forecast would. If they do, the gain
is not deployable as it stands. A deployable version would use climatology, which is the same every
year and which SARIMA's yearly differencing would largely cancel. The Sharks schedule is close to
known in advance (the NHL publishes it in summer, around this forecast origin).

**Expected effect is small.** Jul–Sep are near-dry in the Bay Area; monthly means smooth out the
rainy days; SAP Center is about 3 miles from the nearest BART station; and a monthly game count
follows the NHL season, which a yearly seasonal model already captures. The validation window
(Jan–Jun, the wet season) is where weather has its best chance. The run decides, not this prior.

## Interactions with open work

- **#139** changes which weather 6 stations get. Rows scored on the backlog would not reproduce on
  the store after #139 merges. Recommended: stack on #139's branch. Gate2 ran on #139's store and
  matched 3.21 %, so the control reproduces there.
- **Sprint 4d reconcile** (local branch `sprint4d/store-rebuild`, not pushed) merges #137/#138/#139.
  Its store is byte-identical to #139's gate2 store, so numbers scored on #139 carry over; rebase
  onto it when it is pushed.
- **#138** calibrates P10/P90 per model. Stacked on #139 the new rows report the raw bands,
  labelled as raw.
- **#141** rewrites the site's covariate copy, and its feature catalog describes the lag gap that
  step 2 fixes. Copy edits here go on top of its text.

## Cost summary

No keys, no paid services. Network: 7 Open-Meteo and 3 NHL requests (plus ~0.5 GB from Hugging
Face if Chronos-2 is in). Compute: minutes. Work: about five agent dispatches (two implementers,
one or two reviews, one audit at the sprint boundary).

## Not in scope (follow-ups)

- A weekday-count covariate. Monthly Total Trips is a sum over days (MANIFEST's identity
  `avg_weekday × n_weekdays + …`), so the number of weekdays in a month is a known-in-advance input
  that may matter more than weather. It is a calendar covariate, not weather or events.
- `add_weather_features` rolls `precip_3hr_sum`/`6hr`/`24hr` over monthly rows, so they are 3-, 6-
  and 24-month sums with the same 2020–21 gap problem. Nothing reads them.
