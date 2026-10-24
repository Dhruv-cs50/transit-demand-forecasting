# Sprint board

## Sprint 4c — Label the bands the serving path publishes (opened 2026-10-24)

(Named 4c, ids S4c.x: Sprint 4 (#138) and Sprint 4b (#139) ids are taken.)

**Goal.** The API and `website/data/forecasts.json` each say which P10/P90 band
they return, and neither calls a raw band an 80% interval. Branch
`feat/serve-interval-bands`: `feat/interval-calibration` (#138) with
`fix/api-serve-forecasts` (#137) and `fix/bart-station-table` (#139) merged in.
Conflicts resolved as the hand-over notes say: both board sections kept, #137's
`api.py` taken.

**User's decisions, 2026-10-24** (on the plan, before any code):
- The API keeps serving SARIMA. SARIMA's `calibration.models` method is `none`,
  so the API returns SARIMA's own band, labelled as not calibrated.
- `forecasts.json` (Chronos-1 zero-shot, Jul–Dec 2025) publishes the calibrated
  band. That is the band `model_comparison.json`'s `Coverage_pct` scores. The
  model's own bounds stay alongside as `p10_raw`/`p90_raw`.
- The branch stacks on all three open PRs.

**Rules.**
- P50 is never changed.
- Calibrators are fitted only where `benchmarks.py` fits them: on the
  validation split, from a fit ending at `train_end`.
- The test split is read for one thing only, a consistency check: the exported
  band's coverage must equal the leaderboard's. Nothing is tuned on it.

**Gates.**
- Leaderboard unchanged: WAPE 3.21/5.75/9.70/10.75, `Coverage_%`
  96.67/74.67/72.67/94.33, n=300.
- `forecasts.json` P50 byte-identical to #139's (087adcb).
- Exported coverage equals the leaderboard's.
- Unit tests pass; `py_compile` and JSX parse pass.

**Environment.** `/tmp/tdf-venv` was damaged by the macOS /tmp cleanup:
`pyvenv.cfg` and package files are gone. This sprint uses a private rebuild
with the same 66 pins, plus pytest, fastapi 0.162 and httpx for the tests. The
pins come from the adaptive-calibration session's freeze list.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4c.0 | Integration base: merge #137 and #139 into #138 | orchestrator | — | 40 tests pass on the merged base | done (ef43cca, 9f3c132) — 40 passed |
| S4c.1 | `evaluation/calibration.py`: save/load a calibrator losslessly, plus `serve_band` (config → band + label). `benchmarks.py` persists each fitted calibrator | systems-architect (orchestrator) | S4c.0 | fit → save → load → apply is bit-identical for scaled/horizon, relative/pooled and asym_relative/station. P50 unchanged. Method `none` → raw + label. Method configured but no file → refused | done (4044162) — `tests/test_serve_band.py` 23 tests; 49 calibration tests pass |
| S4c.2 | `export_forecasts`: apply the saved Chronos calibrator; records carry `p10_raw`/`p90_raw`/`interval_method`; refuse on a label, checkpoint or coverage mismatch with the leaderboard | implementer | S4c.1 | New export tests pass; records stay a list | done (f1af3c7) — 21 new tests (fail before, pass after); suite 87 pass. Real export into scratch: 300 records, coverage 72.67 calibrated / 51.0 raw = leaderboard; P50 and raw bounds equal #139's file. Extra refusal kept (orchestrator ruling): an exported (station, month) matching more than one store row |
| S4c.3 | API: `model` and `interval` fields in `/forecast`, band from `serve_band`; 503 when a configured calibrator is missing; `Dockerfile.api` copies `evaluation/calibration.py` | implementer | S4c.1 | `tests/test_api.py` passes, including the existing P50 checks and new interval checks | done (9dec6c3) — `tests/test_api.py` 17 pass (6 new; existing P50 checks 415137/487928 intact); suite 87 pass. `/health` also carries the label. Not built in Docker (disk 96%); `evaluation/calibration.py` checked on Python 3.11 + pandas 2.2.3 |
| S4c.4 | Wording: `api-demo.html` shows the API's label; README, `machine_learning_files/README.md`, `sections.jsx`/`charts.jsx` copy, and a serving section in `docs/interval-calibration.md` | implementer | S4c.1 (field names) | No raw band called an 80% interval; JSX parses | done (416b866, ec7ad2e; cache-bust bump by orchestrator) — esbuild parses both JSX files; `node --check` on api-demo's script; text rendered in node with old and new forecasts.json. Orchestrator rulings: keep the added label under sections.jsx's live-API card; keep the replacement of two #138 sentences that became false (README "still serve the models' own bands", interval-calibration.md "Not covered" bullets) |
| S4c.5 | Regenerate `forecasts.json` from a full benchmark run + export | orchestrator | S4c.2 | Gates above | done (c1d3097) — benchmark on 8c05ddd reproduced the leaderboard exactly (WAPE 3.21/5.75/9.70/10.75; Coverage_% 96.67/74.67/72.67/94.33; raw 96.67/46.00/51.00/94.33; n=300); Chronos q=0.15389. Export: forecasts.json P50 identical to 087adcb for all 300 records; p10_raw/p90_raw = old p10/p90; band = P50×(1∓q); coverage from the file 72.67 / raw 51.00. Other four website/data files byte-identical |
| S4c.6 | Review, audit, PR (not merged) | code-reviewer, delivery-auditor, orchestrator | S4c.5 | No BLOCKER open; audit clean; PR open | in progress — R1 code: 0 BLOCKER, 1 MAJOR, 7 MINOR (spec pass, quality approve-with-changes; leaderboard and website/data reproduced byte for byte). R1 copy: 1 BLOCKER, 2 MAJOR, 8 MINOR (spec not met until F1). Fix round S4c.6a/S4c.6b done; updated #138 (626b829) merged in 80c1314 (docs only). R2 code: spec PASS, quality APPROVE, 0 BLOCKER/MAJOR, 4 MINOR + 3 nits; 29/33 mutants killed. R2 copy: spec MET, quality APPROVED WITH MINORS, 2 MINOR + 4 nits. Orchestrator closed R2 copy N1–N6 (1885366) and R2 code N1–N4 (ebed3df; 3 new tests fail on the previous code); R2 code N5–N7 nits left. Suite 116 pass. Rerun at ebed3df: leaderboard CSV and both calibrators byte-identical to the first run; export byte-identical in all five website/data files. Delivery audit dispatched |
| S4c.6a | Code fix round: code F1 (`reason: ~` must stay raw; boolean decision), F2 (any unreadable calibrator → CalibratorUnavailable), F3 (benchmarks clears old calibrators per run; serve_band checks fit_end vs train_end), F4 (a failed save does not change the leaderboard), F8 test gaps, nit (checkpoint-mismatch flag instead of reason-text match). Deferred: F5, F6 (latent while SARIMA is `none`); F7 kept by design (NaN band → no traceable coverage → refuse) | implementer | S4c.6 R1 | Tests pass; leaderboard and website/data byte-identical on a rerun | done (16075eb; test_api fit_end patch in 78da15a) — suite 112 pass; 14 tests + 24 subtests fail on the pre-fix code; 8/8 mutants killed. Benchmark rerun: leaderboard, LaTeX, results and both calibrators byte-identical to the first run; export byte-identical in all five files. Orchestrator approved its four calls: whitespace-only reason = unset; run-start clearing fails fast; `{e!r}` in the unreadable-file message; the test_api patch |
| S4c.6b | Copy fix round: copy F1 (api-demo header claim conditional on API version), F2 (export refusal wording: forecasts.json withheld, other files still written, exit 1), F3/F4/F5 (plain-language band note with caveat; Results chart subtitle names the band), F6 ("split-conformal band", not "calibrated", for a 72.7% band), F7 (503 also for a stale calibrator), F9 (escape API error text and date fallback). Deferred: F8 (replace spliced README example after a new image is deployed), F10, F11 | implementer | S4c.6 R1 | JSX parses; `node --check`; R2 copy pass | done (15ee5d0; orchestrator follow-ups in 78da15a: export/run_pipeline wording, Serving section fit_end + run-start clearing) — esbuild + `node --check` pass; node harness over old/new data. Cache-bust stays v=10 (branch never deployed). Deferred to PR follow-ups: `BAND_FIT_WINDOW` constant in sections.jsx, F8, F10, F11 |

## Sprint 4 — Calibrate the P10/P90 intervals (opened 2026-10-22)

**Goal.** Bring every leaderboard model's P10–P90 coverage to ~80% on the
2025-H2 holdout without changing a point forecast. The method is chosen on the
validation split only (2025-H1); the test split is scored once, after the
choice is committed. Branch `feat/interval-calibration`, stacked on
`sprint3/pr-backlog` (PR #136 open).

**Starting state** (pinned env, leaderboard byte-identical to the S3.8 gate):
test coverage SARIMA 96.67%, Prophet 46.0%, Chronos-1 51.0%, SeasonalNaive
94.33%, n=300.

**Decision rules, fixed before any validation number was seen** (user's
defaults, 2026-10-22): a method qualifies if every model lands in 75–85%
validation coverage with neither tail above 15% misses; among qualifiers the
lowest mean interval score wins, one method for all four models preferred.
Prophet MCMC is measured and reported, not eligible. The website's "not
calibrated" wording changes only if every model's calibrated test coverage is
in 75–85%. Serving-path intervals (API, `forecasts.json`) are out of scope.

**Gates.** `Coverage_raw_%` reproduces SARIMA 96.67 / Prophet 46.0 / Chronos-1 51.0 / SeasonalNaive 94.33; WAPE, MAE,
RMSE, MAPE, sMAPE, MASE and n identical to the starting leaderboard; two runs
byte-identical; unit tests pass; `py_compile` and JSX parse pass.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4.1 | Find why the earlier `mcmc_samples=200` run errored | orchestrator | — | Error reproduced and explained | done — the fit succeeded; the diagnostic read `params['sigma_obs'][0][0]`, which raises `IndexError` under MCMC (1-D, 400 draws). Reproduced in a scratch run (not committed); the earlier command, in the Sprint 3 subagent transcript, sent stderr to `/dev/null`. Recorded in `docs/interval-calibration.md` (215449c) |
| S4.2 | `evaluation/calibration.py`: fit/apply split-conformal, P50 untouched | implementer (orchestrator) | — | `tests/test_calibration.py` passes | done (056bd7b) — 16 tests pass |
| S4.3 | `evaluation/interval_study.py`: validation-only comparison of methods | implementer (orchestrator) | S4.2 | Data cut at `val_end` and asserted; table written | done (904c449) — study run on pinned env; no single method qualifies, see S4.4. A full refit from a clean copy at 215449c reproduced all four result CSVs byte-identical |
| S4.4 | Choose the method by the fixed rule; config + write-up committed before any test run | orchestrator | S4.3 | Commit precedes the S4.5 run | done (215449c, committed 20:30:24; first calibrated run started 20:30:35) — no single method qualified; per model: Prophet `scaled/horizon`, Chronos-1 `relative/pooled`, SARIMA and SeasonalNaive none (no method passed). Website wording therefore stays "not calibrated" (rule needs every model) |
| S4.5 | Wire the chosen method into `benchmarks.py`; run the gates; score test once | implementer (orchestrator) | S4.4 | All gates green | done — wiring in 215449c; test scored once at 215449c, result recorded in `docs/interval-calibration.md` (bf80b8f). Gates below |
| S4.6 | README, website wording, `model_comparison.json` | orchestrator | S4.5 | Wording follows the fixed rule | done (65db1c1) — "not calibrated" kept per rule; range 46–97% → 73–97%; README table gains own-band and interval columns; export carries `Coverage_raw_pct` and `Interval_method` |
| S4.7 | Review the sprint diff | code-reviewer | S4.6 | No BLOCKER open | done — 0 BLOCKER, 1 MAJOR (LaTeX table mixed calibrated and raw coverage unlabelled), 10 MINOR; spec PASS, quality PASS with findings. Findings and their disposition are in the fix-round list below and in the PR description. Fix round in 3dff990; third run byte-identical |
| S4.8 | Audit board against git; open PR (not merged) | delivery-auditor, orchestrator | S4.7 | Audit clean; PR open | in progress — audit on 32a75df..3dff990: 0 HIGH, 1 MEDIUM, 8 LOW, all addressed in this commit. Push and PR are authorized by the task brief ("Branch + PR, do not merge") and the user's "Go ahead with the defaults" on the plan, which included opening a PR stacked on `sprint3/pr-backlog`. Branch first pushed at 65db1c1, before review; re-pushed at 5c7036a with the fix round. Done: PR #138 opened against `sprint3/pr-backlog` (mergeable, not merged; retarget to `main` after #136 merges) |

**Gate results (S4.5, 2026-10-22, pinned env, code at 215449c).**

| Gate | Result |
|---|---|
| Point metrics | WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected identical to the starting leaderboard (`assert_frame_equal`); existing column order unchanged |
| Raw coverage | `Coverage_raw_%` = 96.67 / 46.0 / 51.0 / 94.33, the starting coverage exactly |
| Determinism | Two consecutive runs: leaderboard and results CSVs byte-identical |
| Calibrated test coverage (scored once) | Prophet 74.67%, Chronos-1 72.67% (calibrated); SARIMA 96.67%, SeasonalNaive 94.33% (own band). Validation predicted 82.0% / 84.3% for the two calibrated models |
| Website rule | Not every model is in 75–85%, so "not calibrated" stays; only the range figure changes (46–97% → 73–97%) |
| Tests / compile / JSX | 17 unit tests pass; `py_compile` passes on every touched .py; `sections.jsx` and `charts.jsx` parse (TypeScript 5.9.3) |
| After the review fix round | Same configuration re-run: leaderboard and results CSVs byte-identical to the scored run; Chronos validation forecasts identical with the store cut at `val_end`; 28 unit tests pass |

**Review fix round (S4.7).**
- Fixed in code:
  - the LaTeX table now carries `Coverage_raw_%` and `Interval_method` and a caption note (MAJOR);
  - horizon is counted before missing actuals are dropped;
  - a zero P50 with an infinite quantile gives [0, inf], not NaN;
  - the study no longer crashes when `asym_relative` is configured;
  - the Chronos entry carries `validated_for`, so another checkpoint keeps its own band;
  - the Chronos calibration run gets a store cut at `val_end`;
  - `describe()` labels asymmetric spans correctly.
- Wording:
  - the false comment "the leaderboard still rejects" a missing bound is corrected;
  - the doc's runner-up and three-station-check text are corrected;
  - board rows cite hashes.
- Tests: `tests/test_benchmark_calibration.py` added (3dff990).
- Not changed: `accept_model_rows` does not reject a model with missing interval bounds (NaN coverage, still ranked). That is `main`'s behaviour; left as a question for the user. The study's private `_store` swap is kept, restored in `finally`.

## Sprint 4b — One BART station table (opened 2026-10-22)

(Named 4b, with ids S4b.x, because the parallel interval-calibration branch, PR #138, also adds a "Sprint 4" with S4.x ids. Board-only commit messages on this branch say "S4.x"; they mean these stories.)

**Goal.** One authoritative table (BART 2-letter code → name → website id →
weather location), sourced from repo data, used by the export, the
`merge_pipeline` weather mapping, feature engineering and the website. Closes the
Sprint 3 follow-up "Station-level website JSON exports empty".

**Branch.** `fix/bart-station-table`, cut from `origin/sprint3/pr-backlog` @
`32a75df` because PR #136 is still open; the PR targets that branch.

**Starting state** (measured 2026-10-22):

| Fact | Value |
|---|---|
| Store / workbook codes | 50 two-letter codes (`12 16 19 24 AN AS BE BF … WS`); the workbooks carry no names |
| `fetch_bart_od.STATION_NAMES` | 50 four-letter BART API codes → names; the only name source |
| 2-letter → name link | The only full table is `website/data/stations_meta.json` from `c5f5891` (2026-05-07): 47 of 50 named, BF/ML/WP left as codes. The same commit's 2-letter export map carries name comments (e.g. `"BF": "bayp"  # Bay Fair`), and `32a75df`'s `KEY_STATIONS` pairs 5 codes with names; all are from the same period, so this counts as one source. No commit ever held a 2-letter → name dict in code |
| Export on this code | `stations_ridership.json` `{}`, `ridership_actuals.json` `[]`, `stations_meta.json` names = codes, `website_id` null (0 of 50 mapped) |
| Committed `forecasts.json`, `ridership_actuals.json` | From `c5f5891`, ~4.3× the current Total-Trips target (EM 2023-12: 1.23M committed vs 286k in the store) |
| Same 4-letter gap elsewhere | `HUB_STATIONS` (`is_hub_station` always False); `sections.jsx` `KEY_STATIONS.id`, `api-demo.html` fallback list, `api.py` examples and `predict.py --station` send 4-letter ids the store rejects |
| Map page | `transit-demo.html` never reads `stations_ridership.json`; the export's `baseAM`/`basePM` are normalized × 1.05 / 0.95, not measured |

**Gates.** Leaderboard identical to this branch's baseline run on `32a75df`
(expected SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75,
n=300) or each delta named; store target identical, every other column delta
named; the three station JSONs non-empty for all 50 stations;
`model_comparison.json` identical; website served locally renders the map,
forecast table and calibration chart from the new files; `py_compile` and JSX parse.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4b.0 | Baseline: rebuild store, benchmarks and export on unmodified `32a75df` | orchestrator | — | Leaderboard and export recorded | done — 3.21 / 5.75 / 9.70 / 10.75, n=300; `model_comparison.json` byte-identical to the committed file; station exports 0 / 0 / 50 unnamed |
| S4b.1 | `machine_learning_files/bart_stations.py`: the table, helpers, `--check` | implementer | user decisions | `--check` passes against `sources.yaml`, `transit-demo.html` and the store; names equal the pre-change `STATION_NAMES` | done (af10e82) — `--check` OK: 50 stations, 41 website ids, 6 weather stations. `STATION_NAMES` now re-exports the table, so `--check` cannot compare against it; the names were checked equal to a dump taken before the edit (S4b.1 report step 2) and re-verified by the S4b.7 audit |
| S4b.2 | Pipeline consumers: `bart_od_from_xlsx.py`, `bart_od_from_csv.py`, `merge_pipeline.py`, `feature_engineering.py`, `api.py`, `predict.py` | implementer | S4b.1 | Rebuilt store: names for 50, per-station weather for the six mapped stations, `is_hub_station` true for the hub set | done (8c92631, 39827b9) |
| S4b.3 | Export: 2-letter `station_id` for all 50, new `stations_meta`/`stations_ridership` schema, `forecasts.json` from the benchmark's Chronos-1 run | implementer | S4b.1 | Export from rebuilt store: 50/50 in each station file | done (4bad2ef) |
| S4b.4 | Website: one id style, map reads `stations_ridership.json`, copy matches the new data | implementer | S4b.3 schema (fixed in this board) | JSX parses; local render shows data | done (ce83caa) |
| S4b.5 | Full rerun, regenerate `website/data/`, run gates | orchestrator | S4b.2–S4b.4 | All gates green or deltas named | done — gate2 on f606498 ALL PASS, export byte-identical to gate1 (two independent runs); `website/data/` regenerated from gate2 in 087adcb; served locally and checked in headless Chrome: forecast table (EM: 12 actual months, then Jul–Dec 2025 actual beside P10/P50/P90), calibration chart with actuals, all 50 stations in the picker, map with 41 of 41 BART nodes on real levels. Earlier: gate1 on ce83caa ALL PASS: leaderboard, all result slices and Chronos preds identical to baseline; store deltas only `station_name`, the six stations' weather (+ `temp_deviation`, `is_rain_onset`, `precip_intensity`, `weather_discomfort`), `is_hub_station` on the ten hubs; export 50/50/3,000/300, `model_comparison.json` identical |
| S4b.6 | Review the branch diff | code-reviewer | S4b.5 | No BLOCKER open | done — R1 on ce83caa: spec PASS, quality changes requested; 1 BLOCKER (index-page map copy contradicts the map's new caption), 2 MAJOR (refused forecasts exit 0 and leave the stale file; map's "ons/hr" invented unit beside real boardings), 11 MINOR. Fix round: F1 adf65b6 (refused forecasts exit 1, inputs checked before writes, forecasts tied to the leaderboard row's n, no silent station drop, docs), F2 f606498 (index map copy, unitless load index, tie-break, forecast months from data, late live response dropped, parallel fetch, cache-busters). R2 scoped review of ce83caa..087adcb: spec PASS, quality PASS, 0 BLOCKER / 0 MAJOR / 3 MINOR (N1-N3, ruled below); R1 items closed except two residuals the briefs allowed |
| S4b.7 | Audit board against git | delivery-auditor | S4b.6 | No unresolved disagreement | done — 0 HIGH, 2 MEDIUM, 7 LOW (D1–D9), all wording on this board; corrected in the commit that marks this done. Commits, file sets, gates, `--check`, trailers and the clean tree all agree |
| S4b.8 | Push, open PR against `sprint3/pr-backlog` (no merge) | orchestrator | S4b.7 | PR open | done — PR #139 (https://github.com/Dhruv-cs50/transit-demand-forecasting/pull/139), mergeable, clean; the merge is the user's |

S4b.2, S4b.3 and S4b.4 touch disjoint files and run in parallel after S4b.1.

### Rulings (Sprint 4b)

- **2026-10-22, the user's answers at the Go Ahead gate:**
  1. ML = Milpitas (`MLPT`), WP = Pittsburg/Bay Point (`PITT`), and the
     website `pit` node belongs to WP. The repo cannot pair these alone:
     elimination leaves exactly those two codes for those two names, and ML's
     all-zero 2019 matches BE (Berryessa). Recorded in the table as
     user-confirmed, not repo-sourced. `c5f5891` had given `pit` to PC; that
     mapping is dropped.
  2. `forecasts.json` is regenerated from the benchmark's Chronos-1 zero-shot
     predictions for Jul–Dec 2025 (the leaderboard run), replacing the stale May file.
  3. `HUB_STATIONS` is re-keyed through the table in this PR.
- BF → Bay Fair (`BAYF`): `c5f5891`'s map comment, the `transit-demo.html` node
  `bayp` "Bay Fair", and the four-letter map at `32a75df` (`BAYF → bayp`, deleted in 4bad2ef) all agree.
- Weather keeps the six name-matched locations (EM, MB, FM, BE, SO, 19). No
  nearest-location assignment: that would be a modeling change nobody asked for.
- `stations_ridership.json` averages the latest 12 store months. Averaging over
  2019 and 2022–25 mixes levels across the ~2.9× COVID break, and counts BE and
  ML's pre-opening zeros. `baseAM`/`basePM` are dropped: they are not measured.
- F1: with `--allow-val-fallback` and no leaderboard the export now exits 1,
  because forecasts cannot be tied to a scored run. The fallback is opt-in and
  off by default. Cost if wrong: a fallback run needs `|| true`.
- F2: the BARTForecasts heading's "6-month" is derived from `forecasts.json`, so
  the empty-forecasts text cannot contradict it.
- Sibling PRs, all against `sprint3/pr-backlog`: trial merges of this branch with
  #138 (interval calibration) conflict only in this board file; with #137 (API
  serving) only in `machine_learning_files/api.py`, where both sides set the
  examples to `EM` — take #137's file. #137 commits `data/processed/feature_store.parquet`
  built before this branch. Against this branch's store it differs in
  `station_name` and the six stations' weather, and also in ways this branch did
  not cause (the same differences appear against the `32a75df` baseline store):
  it was built without the events archive (`is_game_day`/`is_sharks_game` never
  true vs 1,000 rows here; `game_start_hour`/`hours_to_event` all NaN), and the
  other 44 stations' regional weather differs slightly (`temp_f` up to 0.0034 °F,
  `is_raining` up to 0.0047). Rebuild and commit it after both merge.
- #138 interaction: #138 writes `chronos2_zeroshot_preds.parquet` before it
  calibrates intervals, so after both merge `forecasts.json` carries Chronos's
  raw P10/P90 while `model_comparison.json`'s `Coverage_pct` may score the
  calibrated band. Reconcile at the second merge (publish the calibrated band,
  or label the raw one).

- R2 N3: commit 087adcb's subject says "full pipeline run". The steps that ran
  were `bart_od_from_xlsx.py`, `merge_pipeline.py`, `feature_engineering.py`,
  `models/baselines/benchmarks.py`, then the export with `--out-dir` into a
  scratch directory, whose five files were copied into `website/data/`.
  `zero_shot.py`, `arima.py`/`prophet_baseline.py` standalone runs, the validator
  and fine-tuning from `run_pipeline.sh` did not run. `zero_shot.py`, the
  standalone baselines and the validator feed none of the five files;
  `finetune.py`, had it run, would have added an `AutoGluon_Ensemble` row to the
  leaderboard (`benchmarks.py:535-551`), which `model_comparison.json` would
  then publish. Not rewritten, because later commits sit on top.

### Follow-ups (Sprint 4b, found here, not fixed here)

- Published model claims that no run supports: the hero says Chronos-1 is
  "enriched with weather and events data" (`sections.jsx:92`), and the site
  shows feature-importance values (the `shap` list, `sections.jsx:285-293`). The review found
  the zero-shot path never passes covariates: under chronos-forecasting 2.3.2
  `predict_df(future_df=…)` raises TypeError and the code falls back to
  univariate (50 "Falling back to univariate mode" lines per run). No ranked
  model reads weather, events or `is_hub_station`.
- `models/baselines/fetch_pems_roads.py:49-52` `near` values are four-letter (module unwired).
- `website/data/*.json` fetches carry no cache-buster (`app.yaml` caches 1 day).
- Hard-coded years that go stale on the next refresh: "2019 and 2022–2025" for
  actuals; "Jul–Dec 2025 test split" labels beside `model_comparison.json`.
- Dark mode: `index.html` sets `--primary` inline, so P50 values and forecast
  month labels render navy on the dark background.
- R2 N1: `website/app.yaml`'s `url: /` handler sets no expiration, so `index.html`
  is cached for a day and returning visitors keep the old `?v=` cache-busters
  until a reload.
- R2 N2: when the `forecasts.json` fetch fails (network error, 5xx), the
  forecast section says "No forecasts are published" (`sections.jsx` ~:687,
  ~:787-795, ~:911-913).
- The lede says the forecasts are "the predictions scored in the model
  comparison below" without checking that `model_comparison.json` has the
  Chronos row (the export now refuses to publish forecasts in that case).
- F1 concern 5 (pre-existing): with `--allow-val-fallback` and no validation
  split, `export_model_comparison` raises `SystemExit(1)` after the station and
  actuals files were written.
- F1 concern 6 (pre-existing): an unexpected exception inside
  `export_forecasts` (e.g. a corrupt parquet) aborts before
  `model_comparison.json` is written (non-zero exit either way).
- The "Live demo" nav label and "Where is the rush, right now?" heading
  (`sections.jsx:39`, `:373-375`) suggest live data; the map shows 2025 average
  levels shaped by an illustrative curve.
- Google Maps answers `BillingNotEnabledMapError` for the page's key (seen in
  local headless runs: "can't load Google Maps correctly", development
  watermark). That is a billing setting on the Maps project; whether the
  deployed page is affected is unverified.

## Sprint 3 — Clear the open-PR backlog (opened 2026-10-22)

**Goal.** Every still-valid fix in the 104 open PRs reaches `main` through one
reviewed consolidation PR. Every other PR is closed with a written disposition.
Sprint 2's published numbers do not move unless a named change explains it.

**Starting state** (measured 2026-10-22 against `origin/main` @ `cb7da6d`):

| Fact | Value |
|---|---|
| Open PRs | 104, all drafts from the daily `claude/nifty-goodall-*` audit routine |
| Conflict with `main` | 87; the 17 clean ones are mostly log-only |
| Linear chains | #84→#116 (33 PRs, tip #116); #62→#65; #118→#119 |
| Already-merged cumulative tips | #26, #38, #42, #83 (#83 carried the fixes of #43–#82 by content; by ancestry it contains #68–#82) |
| Hunks across non-contained tips | 979: 123 already on main, 84 logs, 415 apply, 336 stale, 21 new root-level log files |

**Gates for closing the sprint.** Leaderboard bit-identical to Sprint 2
(SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75, n=300) or
each delta traced to a named change; website export no worse than `main`
(`model_comparison.json` identical; the station JSONs already export empty on
`main` because of the 4-letter vs 2-letter code gap, a known Sprint 2 follow-up);
`py_compile` passes on every touched file; JSX parses.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S3.1 | Map chains, conflicts and hunk residue for all 104 PRs | orchestrator | — | Tables in this board's starting state | done (recorded in 6c82330) |
| S3.2a | Triage: `api.py`, `scheduler.py`, `Dockerfile.api`, `requirements.txt` | principal-engineer | S3.1 | Ruling per item in report | done — 61 items: KEEP_116 18, ADAPT_116 1, PORT 6 (incl. #122 reworked) — rulings committed in 6b9f48e |
| S3.2b | Triage: `predict.py`, `finetune.py`, `zero_shot.py` | principal-engineer | S3.1 | Ruling per item in report | done — 86 items: KEEP_116 26, ADAPT_116 1, REJECT_116 5, PORT 3, rest closable — rulings committed in 6b9f48e |
| S3.2c | Triage: `merge_pipeline.py`, `validators.py`, `fetch_bart_od.py` | principal-engineer | S3.1 | Ruling per item in report | done — 63 items: KEEP_116 14, ADAPT_116 4, REJECT_116 3, PORT 1 (H58, from #12) — rulings committed in 6b9f48e |
| S3.2d | Triage: `feature_engineering.py`, other `fetch_*`, `fetch_pems_roads.py`, `run_pipeline.sh` | principal-engineer | S3.1 | Ruling per item in report | done — 57 items: KEEP_116 21, ADAPT_116 2 (H232, H233), PORT 0, REJECT 4 (2 unverified) — rulings committed in 6b9f48e |
| S3.2e | Triage: `benchmarks`, `ablation`, `metrics`, `prophet_baseline`, `arima`, `export_website_data` | principal-engineer | S3.1 | Ruling per item; #135 checked against #132 | done — 70 items: KEEP_116 25, ADAPT_116 7, REJECT_116 4, PORT 2; leaderboard recomputed from saved forecasts, unchanged; #135 compatible but closable — rulings committed in 6b9f48e |
| S3.2f | Triage: website JSX/CSS/JSON, README, `docs/`, EDA notebook | principal-engineer | S3.1 | Ruling per item in report | done — 60 items: KEEP_116 31, ADAPT_116 6, REJECT_116 6, PORT 6 — rulings committed in 6b9f48e |
| S3.3 | Identify the routine that opens a PR daily | orchestrator | — | Routine named, with a pause/reconfigure proposal | done (recorded in ded24a6) — remote routine "Test" (`trig_01ML7Tvxyi698UL1sgXPRXa4`), daily 13:00 UTC since 2026-05-03; proposal goes to the user, not changed by us |
| — | **Gate: push, PR closes and the routine change wait for the user** | orchestrator | S3.2*, S3.3 | User's explicit yes | done — 2026-10-22 the user said yes to all three: push and open the PR once review has no open BLOCKER; close the 61 after they merge; pause the routine |
| S3.4 | Merge #116 into this branch; resolve conflicts toward Sprint 2; revert rejected hunks | implementer | Gate | Diff matches S3.2 rulings | done (f919788 merge, ports 7386f5a 42471da 276a21c aa16f59 5e126ec) — rulings checker 0 unexplained failures, invariants 32/32 |
| S3.5 | Merge the log-only PRs | orchestrator | S3.4 | Each merges; only `updates/*.md` change | done (8ce12dc, octopus of 10; 7d3b491, #118 added after the audit) |
| S3.6 | Port KEEP fixes from superseded old PRs, credited to source PR | implementer | S3.5 | One commit per cluster | done — folded into S3.4's port commits |
| S3.7 | Review the whole consolidation diff against `origin/main` | code-reviewer | S3.6 | No BLOCKER open | done — R1: 0 BLOCKER, 2 MAJOR, fixed in 825df57. R2: 2 BLOCKER and 2 MAJOR, fixed in a565f4b, c7de29c and a317cdf. Scoped re-review: all closed except R2-M1 and a B2 residual, fixed in 5cef2c5, 39349b2 and cf728d5. Final scoped review of those three: all approved, 0 BLOCKER/MAJOR, 5 MINOR (listed under follow-ups) |
| S3.8 | Run the sprint gates | orchestrator | S3.7 | All four gates green | done on 8608710 (gate3): leaderboard identical, n = n_expected = 300, 0 rejected, two runs byte-identical; store target identical; export identical; py_compile and JSX re-run by the auditor: pass. Rerun required if the final review changes code |
| S3.9 | Audit board against git | delivery-auditor | S3.8 | No unresolved disagreement | done — 10 disagreements (1 MEDIUM, 9 LOW), all addressed in this board revision and 7d3b491; started before S3.8 closed |
| S3.10 | Open consolidation PR; after the user merges it, close the superseded list | orchestrator | S3.9 | Needs user's yes for the closes | in progress — PR #136 opened (mergeable, clean); routine paused 2026-10-22; 60 close comments prepared; closes run after the user merges #136 |

## Rulings

- `.claude/` was gitignored wholesale. Narrowed to `.claude/*` plus
  `!.claude/agents/` so agent definitions are tracked and local settings stay
  out. Cost if wrong: one `.gitignore` line.
- Root cause of the backlog: the routine's prompt ("check for bugs, prepare
  improvements, create a file for the day's updates") gives it no rule for what
  to do when its previous PR is unmerged, so it opens a new one every day and
  carries the old one forward. Changing the routine is the user's call.
- #116 must never be merged as-is (S3.2c, executed): its side of the
  `merge_pipeline.py` conflict drops Sprint 2's `combined[is_total]` filter, so all
  four BART day-type blocks would be summed; and its new parquet-read helper
  deletes files on any read error, which deleted every BART parquet file when no
  parquet engine was installed. Resolve the conflict to `main`'s side and land the
  S3.2c patches P1–P3 inside the merge commit itself.

## Triage result (S3.2, 397 content-unique items, all ruled)

Every item, its source PRs, ruling, reason and evidence: `docs/sprint3-triage-rulings.jsonl`
(one JSON object per line; item ids such as `H23` are the ones cited in commit messages and PR close comments).

| Ruling | Count |
|---|---|
| KEEP_116 | 135 |
| ADAPT_116 | 21 |
| REJECT_116 | 18 |
| PORT (from older PRs) | 18 |
| SUPERSEDED | 130 |
| OBSOLETE | 12 |
| REJECT | 63 |

## Merge plan (built locally; push, PR closes and the routine change waited for the user's yes, given 2026-10-22)

On `sprint3/pr-backlog`, in this order:

1. **Merge #116** (brings #84–#115 by ancestry). Conflicts in `merge_pipeline.py`,
   `benchmarks.py`, `arima.py`, `prophet_baseline.py`, `README.md`,
   `sections.jsx`, `model_comparison.json` resolve to `main`. The 18 REJECT_116
   reverts and 21 ADAPT_116 replacements land **inside the merge commit**, so no
   commit on the branch's first-parent line has the data-deleting or
   day-type-summing state. #116's own commits stay reachable through the merge's
   second parent, as history.
2. **Port the 18 PORT items**, one commit per cluster, each crediting its source PRs.
3. **Merge the log-only PRs**: #56, #57, #66, #67, #117, #118, #120, #121, #123, #124, #126.
   (#67 also touches two code files, but its changes there are already on `main`;
   merging it changed only its log.)
4. Review, gates, audit, push, open the consolidation PR.

User merges the consolidation PR with **"Create a merge commit"** (not squash or
rebase), which marks #84–#116 and the eleven log-only PRs merged, as happened to
#131–#133 when #134 landed. The remaining 60 PRs are closed with a per-PR
disposition comment, only on the user's yes.

- #122 is not merged as a PR: its second hunk would revert #116's NaN handling.
  Its validate-before-load idea is ported, reworked (S3.2a H392).
- #128's doc text is replaced: it recommends `bart_od_from_csv.py`, whose output
  `load_transit` rejects; the working path is `bart_od_from_xlsx.py` (S3.2f P5).
- #135 only deletes a blank line and its log calls the backlog solved: closed.
- #119's bare-except fix is ported in the form from #17 (H84), not #119's (H391).
- S3.4 and S3.6 merged into one story: the composer applied the PORT items as
  per-cluster commits right after the merge commit, so a separate dispatch would
  only have re-read the same reports.
- Gate environment pinned: /tmp/tdf-venv — Python 3.14.0, pandas 3.0.6, numpy 2.5.4,
  statsmodels 0.15.0, prophet 1.5.0, torch 2.14.1, chronos-forecasting 2.3.2.
- Baseline for the store gate: `main`'s code rebuilds a feature store identical to
  Sprint 2's (3,000 rows, both files, `assert_frame_equal`).
- The 33 `updates/*.md` logs that arrive with #116 and the 10 log-only PRs are
  kept verbatim: dated records of what the routine reported, not current claims.

## Gate results (S3.8, 2026-10-22, pinned env above)

| Gate | Result |
|---|---|
| Leaderboard | Identical to `main` on every metric: SARIMA 3.21 / Prophet 5.75 / Chronos-1 9.70 / SeasonalNaive 10.75 WAPE%, n=300. Adds a MASE column (0.3677 / 0.6585 / 1.1105 / 1.2311). Two runs byte-identical. |
| Feature store | Rebuilt from the same raw files by `main` and by this branch: target identical (0 rows added or lost, max abs diff 0, 50/50 stations). Differences, each traced: new `precip_in`, `humidity_pct` columns (#91); `is_rain_onset` false on 250 rainy months that follow a rainy month (bool-upcast fix, #102: `main` flagged every rainy month as an onset); `hours_to_next_event`/`hours_since_last_event` NaN instead of 0.0 when there are no events (#90: 0.0 meant "event now"); splits now cut from the enriched store (H233). |
| Website export | All five JSON files byte-identical between `main`'s code and this branch; `model_comparison.json` identical to the committed file. Station JSONs export empty on both (known gap). |
| py_compile / JSX | 20 changed .py files compile; both changed .jsx files parse (TypeScript 5.9.3). |
- Review R2 BLOCKER B1 (introduced by #116's metrics hunks): rows with a NaN
  prediction were dropped, so a model that skipped its hardest stations scored
  better (WAPE 2.0 vs 14.86 in the reviewer's repro) and still ranked first.
  Ruling: a missing actual is left out; a missing prediction or interval bound
  where an actual exists makes the metric NaN, and `accept_model_rows` rejects a
  NaN or missing WAPE loudly. Cost if wrong: a model with a legitimately partial
  forecast is excluded instead of scored on what it forecast.
- Review R2 BLOCKER B2 (already on `main`): published text claiming a forecast
  cache baked into the Docker image, a SARIMA(2,1,2) label, 2023 or "validation"
  captions over 2025-H2 test data, and "Chronos-2". Fixed here as one text-only
  commit marked as not from any backlog PR, because this branch's own new text
  contradicts it. The Docker 503 itself is a follow-up.
- B1 extended in a fix round: `compute_metrics` inner-joined predictions onto
  actuals, so a model that omitted rows (rather than emitting NaN) was scored on
  its chosen subset (probe: n=240, WAPE 2.0, accepted). Pre-existing on `main` and
  live (SARIMA, Prophet and SeasonalNaive skip short-history stations). Same rule:
  scored on every test row or rejected, with the missing stations named.
- Review R1 M2 (pre-existing): `scheduler.py` could not import repo packages when
  run as documented. The deferred X1 one-line fix is included after all, because
  #116's ruled scheduler steps (H330, H350) cannot run without it.
- After the fixes, the leaderboard CSV gains an `n_expected` column (appended, so
  existing columns keep their order) and the console/LaTeX tables label MASE
  "in-sample". The CSV column `MASE` and every value are unchanged.
- S3.4's invariant checker now reports 29/32, all three expected: "X1 NOT included"
  is intentionally false (R1 M2 ruling), and two `benchmarks.py` pattern checks are
  stale after 5cef2c5 moved the LaTeX code into `leaderboard_latex()`. At runtime the
  CSV is still written first (`to_csv` at :610) and the LaTeX call (:618) is still
  inside `try/except ImportError`.
- Nine triaged items were rewritten by review fixes (H247–H252, H313, H319, H320);
  each carries a `post_review` note in `docs/sprint3-triage-rulings.jsonl`.
- Store-gate footnotes: `precip_mm` differs only by float noise (max 1.4e-17);
  `forecasts.json` compares identical because the export skips it when no forecast
  run exists, so that comparison is vacuous.
- B1's omission rule covers `benchmarks.py`, which produces the published
  leaderboard. `evaluation/metrics.py` `compute_all_metrics` and `zero_shot.py`
  `evaluate_predictions` still inner-merge and report `n = len(merged)`; neither
  feeds a published number (follow-up).

## Follow-ups (found during this sprint, not caused by the backlog, not fixed here)

- The Docker image ships no forecast cache and no chronos, so `/forecast` returns 503 for known stations; the 503 message still suggests retrying without `as_of`.
- Station-level website JSON exports empty: `export_website_data.py` and `STATION_TO_WEATHER_STATION` use 4-letter station codes; the store uses BART's 2-letter codes. Per-station weather never applies for the same reason.
- `ridership_daily_est` is the monthly Total / 22 and is published, overstating daily riders.
- The raw weather archive ends 2023-12, so 2024-25 weather covariates are NaN.
- Prediction intervals are uncalibrated: Prophet 46%, SARIMA 96.7% against nominal 80%.
- The benchmark test window has no upper bound (`benchmarks.py`), so one more month of data or one failed station fit gets a model rejected; the export then publishes only the survivors.
- Diebold-Mariano tests still run against models the leaderboard rejected; duplicate prediction rows are not checked.
- "Chronos-2" wording remains in code comments (`feature_engineering.py`, `models/`, `zero_shot.py`, `run_pipeline.sh`).
- `fetch_pems_roads.py` deletes the PEMS-BAY CSV on a read error and falls back to synthetic data (standalone module, no automated caller).
- `.gcloudignore:2-3` still says forecast outputs "must be baked into Dockerfile.api".
- `machine_learning_files/README.md:109` still points to `fetch_bart_od.py` for "No BART OD files found" (the working path is `bart_od_from_xlsx.py`).
- `compute_all_metrics` (`evaluation/metrics.py`) and `zero_shot.evaluate_predictions` inner-merge forecasts onto actuals and report `n = len(merged)` (unpublished paths).
- Results tile (`sections.jsx`): a failed fetch of `model_comparison.json` shows "loading…" forever; on a WAPE tie it names one model while Benchmarks highlights every tied row; the lede, MAE tile and footnote are still hard-coded beside the now data-driven tile. Commit 39349b2's message says "text/comment changes only", which is not accurate (it adds the fetch and hooks for that tile).
- `benchmarks.py:585-592` carries a stale history comment.
