# Site claims audit — model and data claims vs code and runs

**User decisions (2026-10-24):** correct the copy; covariate work is a separate proposal (leaderboard untouched);
remove the `shap` and station-mix cards; remove the EDA section until its plots are regenerated; remove the
report/slides links and the report citation; keep the About bio (confirmed accurate). Items marked
"**Your call**" below were settled by these answers.

Branch `fix/site-model-claims`, cut from `origin/sprint3/pr-backlog` @ `32a75df` (main @ `cb7da6d` is its
ancestor; #136 is still open, so the backlog branch is current). Line numbers are on that base.

**Evidence run.** The gate2 run from PR #139's sprint (`f606498`, pinned env: Python 3.14.0, pandas 3.0.6,
chronos-forecasting 2.3.2): `bart_od_from_xlsx.py` → `merge_pipeline.py` → `feature_engineering.py` →
`models/baselines/benchmarks.py`. Its leaderboard equals the published one on every metric
(SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75 WAPE %, n = 300). Re-derive any row below by
rebuilding the store and running the benchmark as in `docs/sprint-board.md` S4b.5.

## The covariate question

| Fact | Evidence |
|---|---|
| Chronos-1 never sees a covariate | `zero_shot.py:162-181` calls `predict_df(…, future_df=…)` inside `try`; `except TypeError` re-runs univariate. In chronos-forecasting 2.3.2, `ChronosPipeline` (t5) inherits `BaseChronosPipeline.predict_df`, whose signature has no `future_df` ("any other columns … will be ignored"); only `Chronos2Pipeline.predict_df` accepts one. The gate2 log has 50 `Falling back to univariate mode` lines, one per station. |
| No other ranked model reads one | `arima.py:146` `SARIMAX(series, order, seasonal_order)`, no `exog`. `prophet_baseline.py:46-50,120` builds a US federal holiday calendar in code; no regressors. `benchmarks.py:63-105` seasonal naive copies last year's value. |
| The covariates are empty where it matters | Feature store (3,000 rows): every weather column is 100% NaN for 2024 and 2025 (raw archive `weather_*_2019-01-01_2023-12-31.parquet`). The event archive is 174 Sharks home games at SAP Center, 2019–2023; `is_game_day` is true on 200/400/400 rows in 2019/2022/2023 and on 0 rows in 2024–25. So the whole test window (Jul–Dec 2025) and the 2024 training year carry no weather and no events. |
| Several "covariates" are artifacts of monthly rows | `hour_of_day` is 0 on every row; `day_of_week`, `is_weekend`, `is_holiday` describe the 1st of the month (the row timestamp). |

## Claims, evidence, proposed change

`sections.jsx` unless noted. "Fixed by #139" = already corrected on PR #139's branch; not edited here.

| # | Where | Claim on the site | Evidence | Proposed change |
|---|---|---|---|---|
| 1 | :91-94 hero lede | Chronos-1 "enriched with weather and events data to capture seasonal and surge patterns" | Covariate table above | Name the four scored models; say no ranked model uses weather or event data yet |
| 2 | :87 hero h1 | "stop by stop, hour by hour" | Target is monthly station totals (`configs/model.yaml` freq `MS`) | "station by station, month by month" |
| 3 | :112 hero card | "STATION · 12TH ST — 3.2% WAPE" | 3.21% is the 300-row network WAPE; 12th St's own SARIMA WAPE is 3.52% | Label "ALL 50 STATIONS" (number unchanged) |
| 4 | :136 tile | "Point forecasts calibrated; intervals are not" | Nothing calibrates a point forecast; coverage 46–97% (leaderboard) | "Intervals not calibrated" |
| 5 | :159 Method 01 | "Open-Meteo hourly weather and a Bay Area events calendar" | Weather aggregated to months, ends 2023; events = Sharks schedule 2019–2023 | Say monthly weather + Sharks schedule, 2019–2023 only |
| 6 | :160 Method 02 | "holiday and school-calendar flags … known-future inputs"; "event covariates are currently constant zero" | No school column; events nonzero 2019–2023, zero 2024–25; nothing reads them | List what exists, the 2023 cut-off, and that no ranked model reads them |
| 7 | :171 Method h2 | "from raw APC feed to a per-stop forecast" | Data is BART monthly OD workbooks; no APC data | "from BART's monthly ridership reports to a per-station forecast" |
| 8 | :172 Method lede | "reproducible end-to-end from a single Makefile … every artifact checksummed and version-pinned" | No Makefile, no checksums anywhere in the repo (template text, f9b8585) | `scripts/run_pipeline.sh` chains the steps; seeded benchmark, two runs bit-identical (README, board S3.8) |
| 9 | :198-203, :236-251 Dataset | "Network composition" bars 44 / 32 / 14 / 10 "% of station-months" | Hand-entered in c5f5891; no code computes them. The 4 core SF stations are 8% of station-months (29.3% of 2025 boardings) | Remove the card |
| 10 | :216 Dataset lede | "fused with Open-Meteo weather and a curated Bay Area events calendar" | As 5 | Same correction as 5 |
| 11 | :233 Dataset | "No future leakage — covariates rely only on data observable at prediction time" | No model uses covariates; future weather would be observed, not forecast | "Every model is fit only on data before the test window" (`benchmarks.py:429,461,477`, `train_cutoff=val_end`) |
| 12 | :204-208, :254-266 feature catalog | 12 "known-future covariates", incl. "Hour of day", "Is post-COVID period", "Station OD volume"; "influence ordering is illustrative" | `hour_of_day` constant; no post-COVID or OD-volume column | Show only columns that exist and vary; footnote: 2019–2023 coverage, unused by ranked models, influence not measured |
| 13 | :284-293, :335-354 Results | "Top known-future covariates" bars 0.46 … 0.15, "illustrative from ablation study" | Values from template f9b8585 (labels "Boardings lag-24h", "Stop embedding"); relabelled 77ee1aa. `Processing/ablation.py` needs a fine-tuned AutoGluon predictor, which has never existed | Remove the card (and the unused `cm` constant) |
| 14 | :39, :98, :373, :375 | "Live demo", "Try the live demo", "Where is the rush, right now?" | Map shows 12-month average levels × illustrative curves (#139 lede); nothing is live | "Map demo", "Try the map demo", a heading with no "right now" |
| 15 | :363-381 Demo features + lede | "see how the model adjusts boardings", "updates in real time" | — | Fixed by #139 |
| 16 | :451 Rec 01 | "event covariates are currently constant zero, because the pipeline has no Ticketmaster key" | As 6 | Sharks schedule ends 2023, no Ticketmaster key, nothing reads it; extending both archives is the prerequisite |
| 17 | :453 Rec 03 | "BART's 511 API supports near-real-time OD pulls" | `fetch_511_transit.py` pulls GTFS-RT stop monitoring and historical stop observations (arrival times), not OD counts; `merge_pipeline.py:129` placeholder | Describe what 511 provides; value for this target unmeasured |
| 18 | :524-544 EDA section | 7 plots and captions ("COVID crash (2020)", "Diridon-area stations spike ~40%", "Lag features dominate", …) | All 7 PNGs made 2026-05-11 from a superseded 1,800-row store (~4× today's Total-Trips target). 04 shows game nights *lower*, all at hour 0; 01 has no 2020–21 data; 03 groups by the weekday of the 1st; 05 has only a "Dry" bucket; 10 has no lag features; 02/06 orderings hold but values are ~4× | **Your call** — see question |
| 19 | :626-628 Resources | "Repo · MIT license"; "Chronos-1 fine-tuning" | No LICENSE file; fine-tuning never run (README "AutoETS" note) | Drop "MIT license"; list what the repo runs |
| 20 | :631 Resources | Open-Meteo "used for weather covariates — hourly granularity" | Monthly aggregates, 2019–2023, unused by ranked models | Say so |
| 21 | :100, :514, :626-627 | "Project report (PDF)", "Section 6 of the project report", "Report · 38 pages", "Slides · 22 slides" — all `href="#"` | Template text (f9b8585); no report or slides in the repo | **Your call** — see question |
| 22 | :606-610 About | "Previously: data intern at a Bay Area mobility startup; TA for CS 122; two summers building inference pipelines on AWS" | Template text (f9b8585) | **Your call** — personal, not edited without you |
| 22a | :160 Method 02 tool tag | "scikit-learn" | No tracked Python file imports `sklearn` (`git grep`) | Tag removed |
| 22b | :629 Resources notebook card | "COVID recovery patterns, and the case for temporal splits" | The notebook has summary stats, seasonality, missing-data, correlation plots; no temporal-split discussion; its saved plots are the superseded ones in 18 | Describe its contents; say the plots are due to be regenerated |
| 22c | :289 Results interval caption | "zero-shot forecast · Jan–Jun 2024" | — | Fixed by #139 |
| 23 | README:15 | "trains statistical and machine-learning forecasting models" | Chronos runs zero-shot; AutoGluon never ran | "fits statistical models and runs a pretrained foundation model zero-shot" |
| 24 | README:22 | "External covariates from Open-Meteo weather and NHL/Ticketmaster event schedules" | As covariate table | Add coverage (2019–2023) and "no ranked model uses them yet" |
| 25 | README:23 | Model comparison includes "AutoGluon time-series models" | README:55-58 itself: no AutoGluon row has ever been produced | Drop AutoGluon from the comparison list |
| 26 | README:137 | "AutoGluon and Chronos require Python 3.11" | The published benchmark ran Chronos on Python 3.14.0 | "AutoGluon needs Python < 3.14" |
| 27 | README:162 | BART OD data "is fetched directly" | README:394 and `data/MANIFEST.md`: bart.gov returns 403; workbooks are downloaded by hand | Point to the manual download |
| 28 | README:383 | "Weather and event data are currently aggregated to the monthly modeling cadence" | True, incomplete | Add the 2023 cut-off and that no ranked model reads them |

## Checked and supported (unchanged)

Leaderboard figures everywhere (3.2 / 5.8 / 9.7 / 10.8 %, MAE 3,086 / 5,526, n = 300), coverage 46–97%,
3,000 station-months (2019 + 2022–2025), splits 1,800 / 300 / 300 with train Jan 2022–Dec 2024, 6-month horizon
(all models fit through `val_end` 2025-06), Embarcadero highest volume, SARIMA (0,1,1)(0,1,1,12), Rec 02's
"runs univariate", README's Chronos caveat (:60-67), "All OD pairs" (the target sums every OD pair by origin,
`merge_pipeline.py:213`). `index.html`: no model claims (only the `?v=` cache-buster changes).

## Not covered here

`charts.jsx` captions (data-driven, checked), `transit-demo.html`, `api-demo.html`, README API/Docker text (PR #137),
the coverage tile (PR #138), and the forecast section (#139 and the website-freshness session).
