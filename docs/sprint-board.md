# Sprint board

## Sprint 4g — Site copy matches the 2019–2025 covariate archives (opened 2026-10-26)

(4g: 4e and 4f are taken on the base; #143's EDA sprint becomes 4h.)

**Goal.** #141 and #142 wrote "weather and Sharks archives end in 2023" into the site and README.
#147 then rebuilt the tracked store (`aa02436d…`) with 2024–25 weather and Sharks games, so the
merged page contradicted its own data. Correct that copy to what `data/MANIFEST.md` and the
store say. No model or number change.

**Branch.** `fix/site-copy-archives-2024-25`, cut from `origin/sprint3/pr-backlog` @ `bde247f`.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4g.1 | Correct every "ends 2023" claim in `website/` and `README.md` | orchestrator | — | grep finds none; each new sentence traces to `data/MANIFEST.md`, the store or model code; render shows 0 console errors | done (f5db1eb) |
| S4g.2 | Push; open PR (no merge) | orchestrator | S4g.1 | PR open with claim → evidence table | done — PR #154 (https://github.com/Dhruv-cs50/transit-demand-forecasting/pull/154), not merged |

## Sprint 4h — EDA section rebuilt from the current store (opened 2026-10-24)

(4h: 4d is the reconcile session's; 4e, 4f and 4g were taken by the time this merged.)

**Goal.** Close Sprint 4c's follow-up "Regenerate the EDA plots from the current store": rewrite
`transit_eda/notebooks/eda_complete.ipynb` for monthly station rows, regenerate the PNGs, and
restore the site's EDA section with captions that state only what each plot shows.

**Branch.** `fix/eda-from-store`, cut from `origin/fix/site-model-claims` @ `0938526` (#141, the
only branch without `EDAViz`). PR targets it. None of #139/#140/#141 had merged.

**Store.** Rebuilt with #139's pipeline (`origin/fix/bart-station-table` @ `7598107`) from the 60
hand-downloaded workbooks plus the weather and Sharks-schedule files used by the gate runs:
`feature_store.parquet` sha256 `9a7771080c592a1206c4d7553d78012157df958d3a6bda279895a2151a323cea`,
byte-identical to #139's gate2 store. Fresh venv (Python 3.14.0, pandas 3.0.6, matplotlib 3.11.2).

**Rebased onto the merged backlog (2026-10-26).** #141 merged and the PR now targets
`sprint3/pr-backlog`, where #147 tracks a store rebuilt with 2024–25 weather and Sharks games
(`aa02436d…`, see `data/MANIFEST.md`). `ridership` and `station_name` are identical to `9a777108…`,
so plots 01–03 and their captions are unchanged. The notebook was rerun on `aa02436d…`: plot 04
and its caption now show weather in every month and the schedule from 2019-09-17 to 2025-12-31,
and section 5 now covers three year pairs. `sections.jsx?v=13` (the base has 12).

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4h.1 | Rebuild the store | orchestrator | — | sha256 equals #139's gate2 store | done — `9a777108…` |
| S4h.2 | Rewrite the notebook; regenerate PNGs | orchestrator | S4h.1 | Executes with 0 errors; every caption claim asserted; image outputs byte-identical to the PNGs; rerun gives identical PNGs | done (13f265f; caption fixes 41b712a, 828ffa5) |
| S4h.3 | Restore `EDAViz`, nav link, mount; `?v=13` (12 at first; #142 also took 12) | orchestrator | S4h.2 | Notebook's site check passes; local render: 4 tabs, every image loads, 0 console errors | done (3cb7a1d; 41b712a, 828ffa5; v=13 in 23766b4). Sprint-boundary delivery audit pending: skipped at 93% of the 5-hour plan window |
| S4h.4 | Review the diff | code-reviewer | S4h.3 | No BLOCKER open | done — R1: spec PASS, quality changes requested; 0 BLOCKER, 3 MAJOR (games claim overreached; seasonality range driven by 2022; this board lost the Sprint 4c heading), 7 MINOR. Fix round 41b712a: all fixed except MINOR 7's no-CI point, which is now documented in the notebook and the code comment. Scoped re-review R2: spec PASS, quality PASS; its two optional MINORs (ambiguous growth sentence, this row's wording) fixed in the next commit |
| S4h.5 | Push; open PR (no merge) | orchestrator | S4h.4 | PR open with claim → evidence table | done — PR #143 (https://github.com/Dhruv-cs50/transit-demand-forecasting/pull/143), base `fix/site-model-claims`, not merged (the user's call) |

### Rulings (Sprint 4h)

- **Kept:** network level (with the 2020–21 gap drawn as missing, not a crash), seasonality,
  station ranking, coverage map. **Dropped:** hour-of-day, day-of-week, game-night spike, rain
  scatter, hourly decomposition, event proximity, correlation heatmap: they need daily or hourly
  rows (notebook section 6).
- **Weather and games vs YoY not plotted.** On the 2019–23 store only 2022→23 had both:
  rain r = 0.82 over 12 months, confounded with the recovery (YoY +51.4% in January, +9.8% in
  December); games r = −0.05. On `aa02436d…` there are three pairs (2022→23, 2023→24, 2024→25):
  rain r = +0.82, −0.27, +0.26; games r = −0.05, +0.41, +0.20. Neither keeps one sign, which the
  notebook asserts. Printed in notebook section 5, not published as a plot.
- **Sharks schedule window comes from the raw files** (2019-09-17 to 2025-12-31 on `aa02436d…`), because the
  store's game flags are `False` both for no game and for no data.
- **The seven old PNGs are deleted** (Sprint 4c kept them only so this regeneration could diff
  against them; they stay in git history at `0938526`). New filenames, so no cached old image
  is served at a reused URL.
- **Review R1 fixes (S4h.4):** the games result is reported as "cannot be separated", not "no
  relationship"; the seasonality range is quoted without 2022, whose wider row is attributed in
  part to growth within 2022 (Jan vs Dec YoY, asserted "widest"); a like-for-like 48-station share
  is added to plot 01; unasserted trend words ("climbs", "fell") replaced by endpoint values; the
  site check pairs each caption with its file instead of a substring search; legend "No source
  data"; the lede's notebook path wraps at 375 px.

## Sprint 4d — Reconcile what #137, #138 and #139 publish together (opened 2026-10-24)

(Named 4d, ids S4d.x. S4, S4b, S4c and Sprint 5, the adaptive-calibration branch, are taken.)

**Goal.** One tracked feature store that carries #139's station names, per-station
weather and the event features #137's store lacked. One published P10/P90 band
whose coverage is the one `model_comparison.json` reports. `website/data/`
regenerated from that state, with gate evidence.

**Branch.** `sprint4d/store-rebuild`, stacked on `feat/serve-interval-bands`
(Sprint 4c, PR #144) @ 9674f2d. The PR targets that branch.

**User's decisions, 2026-10-24.**
- #137, #138 and #139 were still open on GitHub, so they are merged locally rather
  than waiting for the GitHub merges.
- The published band was already decided in Sprint 4c: `forecasts.json` carries
  the calibrated band, with the raw bounds alongside. This sprint does not build
  a second export. It stacks on Sprint 4c instead.
- The store is built from everything in the canonical raw folder
  (`~/Desktop/transit-demand-forecasting/data/raw`). At 04:07 that folder gained
  2024–2025 weather and Sharks-game files, fetched by the covariate-experiment
  session. Asked after the final gate run showed the rebuild no longer matched
  the 2019–2023 store committed in S4d.1. The alternative was to keep that store
  and tell rebuilders to leave the new files out; it was turned down.

**Gates** (Sprint 4b method: scratch copy of the commit, workbooks via
`bart_od_from_xlsx.py --dir`, the raw weather/events folder, then
`merge_pipeline`, `feature_engineering`, `benchmarks`, export):
- Leaderboard: WAPE 3.21/5.75/9.70/10.75; `Coverage_%` 96.67/74.67/72.67/94.33;
  `Coverage_raw_%` 96.67/46.0/51.0/94.33; n=300.
- Export: 50/50/3,000/300.
- `forecasts.json`: P50 identical to 087adcb; the exported band's coverage equals
  the Chronos row's `Coverage_%` (72.67).
- Two runs byte-identical.
- Tracked store equals the rebuild.
- Site renders.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4d.0 | Merge #137, #138 and #139 locally | orchestrator | — | Tree matches Sprint 4c's merged base | done — `reconcile/store-intervals` 8ce9c97 (conflicts resolved as Sprint 4c did: both board sections kept, #137's `api.py`). Its tree differs from `feat/serve-interval-bands` @ f1af3c7 only in Sprint 4c's own files. The branch was then re-cut onto Sprint 4c at the user's choice |
| S4d.1 | Rebuild `data/processed/feature_store.parquet` with the merged code from the full raw inputs; commit it; update `data/MANIFEST.md` | orchestrator | S4d.0 | Target identical to #137's store; every other delta named; `tests/` pass | done — first from the 2019–2023 archives (5dbd586, run A), then from the full 2019–2025 folder (3fa3d80; runs D–G) |
| S4d.2 | Rebase onto Sprint 4c's final tip | orchestrator | Sprint 4c S4c.5–S4c.6 | Clean rebase; `tests/` pass | done — 9674f2d, no conflicts; 116 tests pass |
| S4d.3 | Two full gate runs on the stacked tip; regenerate `website/data/` | orchestrator | S4d.2 | Gates above | done — runs D and E on e847db3: every gate passes except "tracked store equals the rebuild", which is what led to the input decision above. Runs F and G on 3fa3d80 (the store commit): ALL PASS, including the tracked store. The export is byte-identical to the committed `website/data/`, so no data file changes |
| S4d.4 | Serve the site locally; check the forecast table, calibration chart, map and model comparison render | orchestrator | S4d.3 | Screens recorded | done — see "Site check" below |
| S4d.5 | Review the diff; open PR against `feat/serve-interval-bands` (not merged) | code-reviewer, orchestrator | S4d.4 | No BLOCKER; PR open | done — PR #147 (https://github.com/Dhruv-cs50/transit-demand-forecasting/pull/147) against `feat/serve-interval-bands`, mergeable, not merged; the merge is the user's. scoped re-review of 07b6c3e: spec PASS, quality PASS; findings 1, 2 and 5–7 closed, 3, 4 and 9 correctly deferred. Two new MINOR fixed in the commit that marks this done: the 2019 gap runs to May (playoffs), and two "this commit" references now name 3fa3d80. 116 tests pass on 07b6c3e (pytest, pinned env). R1: review of 9674f2d..3fa3d80: spec FAIL on two MANIFEST statements, quality PASS; 0 BLOCKER, 3 MAJOR, 6 MINOR. Fixed in 07b6c3e: the MANIFEST claimed events covered every store month (Jan–May 2019 is a gap) and same bytes in any environment (now pinned to the build environment); its inputs now include `weather_forecast_*`; this board's drift and float-noise wording; F/G recorded. Not fixed here (other PRs' files, listed under follow-ups): the stale site copy (MAJOR) and the hindsight-weather wording (MINOR) in `sections.jsx`, and the zip name in the MANIFEST's verify command (MINOR, pre-existing) |
| S4d.6 | Audit board against git | delivery-auditor | S4d.5 | No unresolved disagreement | blocked (audit started, then stopped unfinished when the usage limit was reached; rerun it before closing the sprint) |

**Final store (3fa3d80), SHA-256 `aa02436d…`, vs #137's committed store (`d9135f03…`).**
- Same 3,000 keys; `ridership` identical; same 27 columns in order.
- `station_name`: set on every row.
- Weather:
  - every column is filled on all 3,000 station-months (#137: NaN on all 1,200 in 2024–2025);
  - EM, MB, FM, BE, SO and 19 get their own location's weather;
  - the other 44 stations' 2019–2023 regional weather differs slightly (`temp_f` on 1,584 rows, at most 0.0034 °F; `is_raining` on 176 rows, at most 0.0047; `precip_*` float noise), as #139 recorded.
- Events:
  - `is_game_day` and `is_sharks_game` are true on 1,800 rows (#137: 0): 200 in 2019, 400 in each later year. The events archive starts 2019-09-17, so the 2018–19 season's home games (Jan–Apr 2019, plus playoff games in May 2019) are missing and read as no game;
  - `game_start_hour` is set on those 1,800;
  - `hours_to_event` is set on all 3,000 (#137: all NaN).
- The earlier 2019–2023 build (`9a777108…`) is byte-identical to #139's gate2 store. That was checked by SHA-256 against `gate2/data/processed/feature_store.parquet` in the #139 session's scratchpad (`…/d23f3905-…/scratchpad/gate2`, may be cleaned); runs A and B reproduce it. It differs from this one in 2024–2025 (the weather columns and the 800 new game-day rows) and in float noise in 2019–2023: `precip_mm` on 3 rows and `precip_in` on 47, at most 2.8e-17.

**Gate runs (2026-10-24; pinned env rebuilt from the 66 pins, plus pytest, fastapi 0.162 and httpx for tests).**

| Run | Code | Raw weather/events | Result |
|---|---|---|---|
| A | 8ce9c97 (merge only, no Sprint 4c) | 2019–2023 | Leaderboard as the gates; export byte-identical to the merged branch's `website/data/`, where `forecasts.json` still held Chronos-1's raw band (51.0% coverage) beside `Coverage_pct` 72.67. That mismatch is what Sprint 4c fixes |
| B, C | 12a440a (Sprint 4c f1af3c7 + store) | 2019–2023 | All gates pass. Export byte-identical to Sprint 4c's `website/data/` at 4ead3f0 |
| D, E | e847db3 (Sprint 4c 9674f2d + store) | 2019–2025 | All gates pass except "tracked store equals the rebuild" (`aa02436d…` vs the committed `9a777108…`). Leaderboard, results, LaTeX, both stores, both calibrators, Chronos preds (ignoring `generated_at`) and all five exports are byte-identical across the two runs. Export: 50/50/3,000/300, byte-identical to the committed `website/data/`. `forecasts.json`: P50 and `p10_raw`/`p90_raw` equal 087adcb's P50 and raw band; coverage computed from the published file is 72.67 for the band (= `Coverage_%`) and 51.0 for the raw band (= `Coverage_raw_%`) |

**Site check (S4d.4, served from `website/` at e847db3, built-in browser).**
- The forecast table shows the calibrated band: EM Jul 2025 is 367k / 434k / 501k, matching `forecasts.json` (raw 382k–462k kept as `p10_raw`/`p90_raw`).
- The section copy says the band held 72.7% of station-months, matching `model_comparison.json`.
- The Results "Intervals" chart draws the same band, labelled "not a validated 80% interval".
- The Model comparison and Benchmarks tables render the 4 scored models, and the comparison shows n=300.
- The station picker lists 50 stations.
- The map page reads `stations_ridership.json` and lists 41 BART stations. Its Google base map fails with `BillingNotEnabledMapError`, as already recorded in Sprint 4b.
- No console errors on the index page.

**Follow-ups (not this sprint's files).**
- Stale site copy now that the store has 2019–2025 weather and events (owner: the #141 copy update, which the covariate-experiment session plans):
  - `website/sections.jsx:160` (Method 02) and `:487` (Rec 01) say the event covariates are "currently constant zero";
  - #141's "available for 2019–2023 only";
  - #143's EDA hand-over (built on `9a777108…`).
- `website/sections.jsx:233` ("covariates rely only on data observable at prediction time") and `:160` ("known-future inputs"): the store's weather in the test window is observed, i.e. hindsight. No ranked model reads it, so no published number leaks.
- Refetch the Sharks 2018–19 season (regular season and playoffs) so Jan–May 2019 game days stop reading as "no game". This changes the raw inputs and the store again.
- The gate environment's 66 pins live outside git (`~/.venvs/tdf-py314-req.txt`, the side-session notes); the MANIFEST names the four versions that decide the bytes.
- `data/MANIFEST.md` verify command names "Ridership Report 2025 (1).zip", while its table names "Ridership 2025 (1).zip" (pre-existing, bcd3b76; the store here was built with `--dir`).
- #142 changes `Processing/feature_engineering.py`, which writes the untracked enriched store. The tracked store is unaffected.
- #145 (adaptive calibration) adds `scheme: rolling`, which #144's `calibrate_intervals`/`serve_band` do not read. Whichever of the two lands second must carry it through.

## Sprint 4c — Label the bands the serving path publishes (opened 2026-10-24)

(Named 4c, ids S4c.x: Sprint 4 (#138) and Sprint 4b (#139) ids are taken. PR #141, branch `fix/site-model-claims`, also calls its sprint "Sprint 4c" with ids S4c.1–S4c.5. Both branches were pushed before this was noticed, so commit messages keep the ids: S4c.x on `feat/serve-interval-bands` means this section.)

**Status: closed 2026-10-24, PR #144 open (not merged).**

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
| S4c.1 | `evaluation/calibration.py`: save/load a calibrator losslessly, plus `serve_band` (config → band + label). `benchmarks.py` persists each fitted calibrator | systems-architect (orchestrator) | S4c.0 | fit → save → load → apply is bit-identical for scaled/horizon, relative/pooled and asym_relative/station. P50 unchanged. Method `none` → raw + label. Method configured but no file → refused | done (4044162) — `tests/test_serve_band.py` 21 tests; 49 calibration tests pass |
| S4c.2 | `export_forecasts`: apply the saved Chronos calibrator; records carry `p10_raw`/`p90_raw`/`interval_method`; refuse on a label, checkpoint or coverage mismatch with the leaderboard | implementer | S4c.1 | New export tests pass; records stay a list | done (f1af3c7) — 21 new tests (fail before, pass after); suite 87 pass. Real export into scratch: 300 records, coverage 72.67 calibrated / 51.0 raw = leaderboard; P50 and raw bounds equal #139's file. Extra refusal kept (orchestrator ruling): an exported (station, month) matching more than one store row |
| S4c.3 | API: `model` and `interval` fields in `/forecast`, band from `serve_band`; 503 when a configured calibrator is missing; `Dockerfile.api` copies `evaluation/calibration.py` | implementer | S4c.1 | `tests/test_api.py` passes, including the existing P50 checks and new interval checks | done (9dec6c3) — `tests/test_api.py` 17 pass (5 new; existing P50 checks 415137/487928 intact); suite 87 pass. `/health` also carries the label. Not built in Docker (disk 96%); `evaluation/calibration.py` checked on Python 3.11 + pandas 2.2.3 |
| S4c.4 | Wording: `api-demo.html` shows the API's label; README, `machine_learning_files/README.md`, `sections.jsx`/`charts.jsx` copy, and a serving section in `docs/interval-calibration.md` | implementer | S4c.1 (field names) | No raw band called an 80% interval; JSX parses | done (416b866, ec7ad2e; cache-bust bump by orchestrator in 1b1c8db, raised to v=12 in the audit fix) — 416b866 also edits `docs/ARCHITECTURE.md` (API/Dockerfile rows), outside the brief's file list; accurate and covered by both copy reviews.  esbuild parses both JSX files; `node --check` on api-demo's script; text rendered in node with old and new forecasts.json. Orchestrator rulings: keep the added label under sections.jsx's live-API card; keep the replacement of two #138 sentences that became false (README "still serve the models' own bands", interval-calibration.md "Not covered" bullets) |
| S4c.5 | Regenerate `forecasts.json` from a full benchmark run + export | orchestrator | S4c.2 | Gates above | done (c1d3097) — benchmark on 8c05ddd reproduced the leaderboard exactly (WAPE 3.21/5.75/9.70/10.75; Coverage_% 96.67/74.67/72.67/94.33; raw 96.67/46.00/51.00/94.33; n=300); Chronos q=0.15389. Export: forecasts.json P50 identical to 087adcb for all 300 records; p10_raw/p90_raw = old p10/p90; band = P50×(1∓q); coverage from the file 72.67 / raw 51.00. Other four website/data files byte-identical |
| S4c.6 | Review, audit, PR (not merged) | code-reviewer, delivery-auditor, orchestrator | S4c.5 | No BLOCKER open; audit clean; PR open | done — R1 code: 0 BLOCKER, 1 MAJOR, 7 MINOR (spec pass, quality approve-with-changes; leaderboard and website/data reproduced byte for byte). R1 copy: 1 BLOCKER, 2 MAJOR, 8 MINOR (spec not met until F1). Fix round S4c.6a/S4c.6b done; updated #138 (626b829) merged in 80c1314 (docs only). R2 code: spec PASS, quality APPROVE, 0 BLOCKER/MAJOR, 3 MINOR (N1–N3) + 4 nits (N4–N7); 29/33 mutants killed. R2 copy: spec MET, quality APPROVED WITH MINORS, 2 MINOR + 4 nits. Orchestrator closed R2 copy N1–N6 (1885366) and R2 code N1–N4 (ebed3df; 3 new tests fail on the previous code); R2 code N5–N7 nits left (N4 closed with N1–N3). Suite 116 pass. Rerun at ebed3df: leaderboard CSV and both calibrators byte-identical to the first run; export byte-identical in all five website/data files. Delivery audit: 0 HIGH, 1 MEDIUM, 7 LOW — M1 cache-bust raised to `sections.jsx?v=12` (above #140's v=10 and #141's v=11; at merge, the highest version wins); L7 `__main__` guard moved to the end of `tests/test_serve_band.py`; L1–L6 board corrections, all in 2619609. Done: PR #144 opened against `feat/interval-calibration` (not merged; retarget to `main` after #136–#139 merge). Push and PR were authorized by the task brief ("branch + PR, not merged") |
| S4c.6a | Code fix round: code F1 (`reason: ~` must stay raw; boolean decision), F2 (any unreadable calibrator → CalibratorUnavailable), F3 (benchmarks clears old calibrators per run; serve_band checks fit_end vs train_end), F4 (a failed save does not change the leaderboard), F8 test gaps, nit (checkpoint-mismatch flag instead of reason-text match). Deferred: F5, F6 (latent while SARIMA is `none`); F7 kept by design (NaN band → no traceable coverage → refuse) | implementer | S4c.6 R1 | Tests pass; leaderboard and website/data byte-identical on a rerun | done (16075eb; test_api fit_end patch in 78da15a) — suite 112 pass; 14 tests + 24 subtests fail on the pre-fix code; 8/8 mutants killed. Benchmark rerun: leaderboard, LaTeX, results and both calibrators byte-identical to the first run; export byte-identical in all five files. Orchestrator approved its four calls: whitespace-only reason = unset; run-start clearing fails fast; `{e!r}` in the unreadable-file message; the test_api patch |
| S4c.6b | Copy fix round: copy F1 (api-demo header claim conditional on API version), F2 (export refusal wording: forecasts.json withheld, other files still written, exit 1), F3/F4/F5 (plain-language band note with caveat; Results chart subtitle names the band), F6 ("split-conformal band", not "calibrated", for a 72.7% band), F7 (503 also for a stale calibrator), F9 (escape API error text and date fallback). Deferred: F8 (replace spliced README example after a new image is deployed), F10, F11 | implementer | S4c.6 R1 | JSX parses; `node --check`; R2 copy pass | done (15ee5d0; orchestrator follow-ups in 78da15a: export/run_pipeline wording, Serving section fit_end + run-start clearing) — esbuild + `node --check` pass; node harness over old/new data. Cache-bust stays v=10 (branch never deployed). Deferred to PR follow-ups: `BAND_FIT_WINDOW` constant in sections.jsx, F8, F10, F11 |

## Sprint 4f — Lags count calendar months, not rows (opened 2026-10-24)

(Named 4f: 4 to 4e are taken by sibling branches. Split out of Sprint 4e, the covariate
experiment on `feat/covariate-benchmark`, by the user's decision of 2026-10-24.)

**Goal.** `Processing/feature_engineering.py` `add_lag_features` shifts each station's series by
rows, so early-2022 rows take their lags and rolling windows from 2019 across the 2020–21 gap.
Shift by calendar month instead: a lag that lands in a month with no data is empty, and a rolling
window counts only the months in it that have data against its `min_periods`.
Update the site copy (#141's feature catalog) that describes the old behaviour.

**Branch.** `fix/lag-calendar-months`, cut from `origin/fix/site-model-claims` @ `0938526` (PR #141),
because #141's copy describes the gap. The PR targets that branch.

**Gates.** Leaderboard CSV byte-identical before and after (no ranked model reads a lag column);
the enriched store differs only in the lag/rolling columns, on rows whose window reaches 2020–21
(each delta counted); unit tests pass; `py_compile` and JSX parse pass.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4f.1 | Calendar-month lags and rolling windows (monthly branch only; sub-monthly path unchanged) + unit test + catalog copy + cache-buster | implementer | — | Gates above | done (535039d, f702310, ca7915e) — 14 tests pass (8 fail on the old code); before/after on canonical 2019–23 inputs: leaderboard CSV, `benchmark_results.csv` and base store byte-identical (3.21 / 5.75 / 9.70 / 10.75, n = 300); enriched store: only the 8 lag/rolling columns change, 2,100 cells, all 2022 (1,700 become empty), plus 2,028 `rolling_std_3mo` cells 2022-04..2025-12 that differ by ≤ 1.0e-11 relative (pandas' running-variance rounding restarts across the empty months); TypeScript 5.9.3 parses `sections.jsx` with 0 diagnostics |
| S4f.2 | Review the diff | code-reviewer | S4f.1 | No BLOCKER open | done — R1 on ca7915e: quality PASS; spec PASS with 1 MAJOR (F1: footnote and audit note said rolling windows reaching 2020–21 are left empty, but 400 of the 2,100 changed cells are partial-window values; cause: this board's goal line, now corrected), 2 MINOR (F2: 2,028 float-noise `rolling_std_3mo` cells outside 2022 breach the gate's wording; accepted deviation, nothing reads the column and every published output is byte-identical; F3: NaN/NaT/single-row cases untested), 2 NIT (F4 stale line ref in the audit note; F5 `Int64` → float64, as specified). Fix round: dd3ce96 (F1, F4), 92383c7 (F3); orchestrator checked the diff: 15 tests pass, footnote now says lags land empty and windows use the months that have data. F5 no action |
| S4f.3 | Delivery audit | delivery-auditor | S4f.2 | Board matches git | todo — run jointly with Sprint 4e's audit |

## Sprint 4c — Every site claim traces to a run (opened 2026-10-24)

(Named 4c, ids S4c.x, because #138 adds a "Sprint 4" and #139 a "Sprint 4b".)

**Goal.** Close #139's follow-up "Published model claims that no run supports": every model or
data claim in `website/sections.jsx`, `website/index.html` and `README.md` either traces to code
or a run output, or is corrected or removed. No model or leaderboard change.

**Branch.** `fix/site-model-claims`, cut from `origin/sprint3/pr-backlog` @ `32a75df` (#136
open, so the backlog branch is current; `main` @ `cb7da6d` is its ancestor). PR targets it.

**Evidence.** Claim-by-claim table with evidence: `docs/site-claims-audit.md`. Run evidence is
#139's gate2 run on `f606498` (leaderboard identical to the published one).

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4c.1 | Audit every model/data claim against code and run outputs | orchestrator | — | Table with evidence per claim | done — 28 claims (+3 found while editing), `docs/site-claims-audit.md` |
| S4c.2 | User decisions: covariates, EDA, report links, bio | orchestrator | S4c.1 | Answers recorded | done — 2026-10-24, recorded in the audit doc header |
| S4c.3 | Apply the approved text fixes | orchestrator | S4c.2 | JSX/HTML parse; local render shows the changes, no console errors | done (97b7c99; cache-buster v=11 in ffbf274) — TypeScript 5.9.3 parse OK; served locally: EDA and `shap` gone, Dataset grid one full-width card, 0 console errors |
| S4c.4 | Review the diff against the audit table | code-reviewer | S4c.3 | No BLOCKER open | done — R1: spec PASS, quality changes requested; 0 BLOCKER, 2 MAJOR (Method lede and README:43 named `run_pipeline.sh` as the reproduction path; it cannot reproduce the table), 11 MINOR. Fix round in 7ab033a: both MAJOR fixed; MINOR fixed except the pull quote (kept: the user chose to re-attribute it) and README's `.venv311` line (follow-up, adjacent to #137's hunk). Re-parsed and re-rendered: 0 console errors |
| S4c.5 | Trial-merge with #137, #138, #139, #140; push; open PR (no merge) | orchestrator | S4c.4 | PR open, conflicts listed | done — PR #141 (https://github.com/Dhruv-cs50/transit-demand-forecasting/pull/141), not merged (the user's call). #137 clean; #138 board only; #139 board + `index.html` `?v=` line; #140 board + two `sections.jsx` hunks (keep #140's `bestNote`/`wapeSub`, drop `cm`/`shap`; keep the `EDAViz` deletion) |

### Rulings (Sprint 4c)

- **Covariates, 2026-10-24, the user:** correct the copy now; making the covariate path real
  is a separate proposal. Evidence: Chronos-1 (`ChronosPipeline`) cannot take `future_df`
  (50 fallback lines per run); SARIMA, Prophet and seasonal naive read no covariates; and the
  weather and Sharks archives end 2023-12, so the test window has neither.
- **EDA section removed** until its plots are regenerated from the current store. The seven
  PNGs stay in `website/data/eda_plots/`, unreferenced, so the regeneration can diff against them.
- **Report/slides links and the report citation removed** (no report or slides in the repo).
  **About bio kept**: the user confirmed it.
- **Post-review changes, 2026-10-24, the user:** keep all (Method lede and README reproduce
  text, Rec 01 title and Recs lede, lag pills in rows, tag/notebook card, ↓ tile marker, nav "Demo",
  `.shap*` CSS removal).
- Replacements trace to code or are removals: no number computed in scratch is published
  (e.g. 12th St's own WAPE, 3.52%, is not on the page; the hero card is relabelled instead).

### Follow-ups (Sprint 4c, found here, not fixed here)

- Make the covariate path real: a covariate-capable checkpoint (Chronos-2) plus 2024–25
  weather and an event source beyond 2023. Changes the leaderboard; the user's call.
- (Addressed by Sprint 4h.) Regenerate the EDA plots from the current store; the notebook groups monthly rows by day
  and hour (`hour_of_day` is constant 0), so several plots need rewriting, not just rerunning.
- Lag and rolling features are row shifts per station (`feature_engineering.py:497-500`), so
  early-2022 rows lag into 2019 across the 2020–21 gap. No ranked model reads them today;
  fix before any covariate model does.
- README Known Limitations says `run_pipeline.sh` "assumes `.venv311/bin/python` exists"; it
  falls back to `python3`. Left because the line sits next to #137's edit of the following line.
- Headline metrics (hero cards, `HeroOrbit`, AtAGlance, Results lede/tiles, Benchmarks lede,
  Rec 02) trace to today's run but are hard-coded, so they go stale on the next refresh. Derive
  them with #140's `useSiteData`/`comparisonSplit` helpers once #140 merges.
- `/tmp/tdf-venv` is broken (macOS tmp cleanup deleted `numpy/__init__.py` and `pyvenv.cfg`);
  any rerun of the gates needs a fresh pinned env.


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

## Sprint 4e — Do weather and event covariates help? (opened 2026-10-24)

(Named 4e: 4, 4b, 4c and 4d are taken by sibling branches.)

**Goal.** Answer, with a scored run, whether weather and Sharks-game covariates improve the
monthly forecast. Plan and decision rule: `docs/covariate-experiment-plan.md`, committed
(81b2089) before any covariate arm was scored.

**User decisions (2026-10-24).** SARIMAX arms only (no Chronos-2, no Prophet regressors); arms go
to a separate experiment table, not the leaderboard, so the export and the site's best-model pick
stay as they are; stack on PR #139 (`fix/bart-station-table`); the lag-gap fix ships as its own
small PR (Sprint 4f, branch `fix/lag-calendar-months`, stacked on #141).

**Branch.** `feat/covariate-benchmark`, cut from `origin/fix/bart-station-table` @ `7598107`. PR #146 (base `fix/bart-station-table`).
Pinned env rebuilt outside `/tmp`: `~/.venvs/tdf-py314` (the gate env's 66 pins + pip 26.2.1 /
setuptools 84.2.1, plus pytest for the unit tests).

**Gates.** Control SARIMA reproduces 3.21 % (n = 300) and equals the leaderboard's SARIMA row on the
same run; the four leaderboard overall rows are unchanged by the 2024–25 data (each delta named
otherwise); `model_comparison.json` unchanged; unit tests pass; `py_compile` passes.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4e.0 | Baseline: rebuild store and run benchmarks on unmodified `7598107` | orchestrator | — | Leaderboard 3.21 / 5.75 / 9.70 / 10.75, n = 300 | done — run0: leaderboard CSV byte-identical to #139's gate2; base store SHA-256 `9a7771080c59…a323cea`, byte-identical to gate2's and to Sprint 4d's rebuilt store |
| S4e.1 | Fetch weather and Sharks games for 2024–25; record hashes in `data/MANIFEST.md`; rebuild; compare | orchestrator | S4e.0 | 2024–25 weather and game months non-null; leaderboard overall rows unchanged or each delta named | done — fetched 2026-10-24T11:06:49Z: 7 × 17,544 hourly rows, no nulls; 93 Sharks home games; copied (new filenames only) into the canonical `~/Desktop/transit-demand-forecasting/data/raw/`; hashes in `data/MANIFEST.md`. run1 vs run0: leaderboard CSV byte-identical; the 8 existing `benchmark_results.csv` rows identical; 12 new slice rows (`game_day`, `sharks_game` n=200, `rainy_day` n=100, per model). Store (SHA-256 `aa02436d44b5…f241`): weather columns filled for 1,200 rows (2024–25), event columns for 800 (16 game months × 50); 2019–23 `precip_mm`/`precip_in` differ by ≤ 2.6e-16 relative (summation order), every other 2019–23 cell identical |
| S4e.2 | SARIMAX `exog` in `arima.py` (default path unchanged) + `models/baselines/covariate_experiment.py` (control + 3 arms, test and validation windows, station-clustered test, row-level DM, per-station wins, decision) | implementer | plan | Unit tests pass; with no exog the SARIMA forecasts are identical to before | done (0263048, 8586b62, d39e2fb) — built in a scratch copy: a hook blocked the implementer's writes here, because the orchestrator's shell had moved its primary directory to the 4f worktree at dispatch; the orchestrator read and applied its patch (SHA-256 `19a5341f…cd903`). 48 tests pass. No-exog control forecasts equal the unmodified code's exactly on both windows (300 rows each); smoke run on the gate2 store: control 3.21 % test / 4.27 % validation, both weather arms rejected loudly (NaN 2024–25 exog). Orchestrator added the `not scored` verdict for rejected arms (d39e2fb) |
| S4e.3 | Scored run; evidence `docs/covariate-experiment.md`; README result | orchestrator | S4e.1, S4e.2 | Every number in the doc traces to the run's CSV/log | done — run2 on d39e2fb (started 11:29:42Z, after the rule 81b2089 and the code): **no arm improves.** Test WAPE: SARIMA 3.21, +weather 3.79 (paired p 0.0005, 42/50 stations worse), +Sharks 3.19 (p 0.54), +both 4.12; validation 4.27 / 4.67 / 4.63 / 5.27. Control's 300 forecasts equal the leaderboard SARIMA's exactly; leaderboard CSV byte-identical to run0/run1; rerun of the experiment byte-identical (CSV SHA-256 `0bf4ab0c…0a19`). Evidence `docs/covariate-experiment.md`; README paragraph |
| S4e.4 | Review the branch diff | code-reviewer | S4e.2 | No BLOCKER open | done — R1 on dc9069e (whole diff, numbers re-derived from run2): spec PASS, quality PASS; 0 BLOCKER, 1 MAJOR (doc called Jul–Dec dry and Jan–Jun wet; the store shows 0.35 vs 0.39 summed mean hourly mm, Nov–Dec as wet as Feb–Mar), 6 MINOR (direction clause d > 0 not in the plan's text; smoke run not disclosed in the doc; "measurably worse" unqualified for validation; "would do no better" too strong; WAPE compared at 2 dp; zero-filled event counts look like data), hygiene (`evaluation/outputs/` neither tracked nor ignored; DM "0.0000"). Leakage, decision code, every number, hashes, commit times, control = leaderboard, default path, no site writes: checked correct. Fix round in the doc and README (this commit); zero-fill guard and `evaluation/outputs/` ignore are follow-ups |
| S4e.5 | Delivery audit at sprint close (joint with S4f.3) | delivery-auditor | S4e.3, S4e.4 | Board matches git |todo — deferred: 5-hour usage at 96 % when PR #146 opened |
| S4e.6 | Site copy on #141's text: archives now through 2025; Method 01/02, catalog footnote, Rec 01 answered by this run | orchestrator | S4e.3, #142 | Copy traces to `docs/covariate-experiment.md`; JSX parses | done in Sprint 4g (PR #154): Method 02, catalog footnote and Rec 01 cite the experiment; Method 01 and the lede give the 2019–2025 coverage |


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
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): `website/data/*.json` fetches carry no cache-buster (`app.yaml` caches 1 day).
  Now every data fetch uses `cache: 'no-cache'` (one shared loader in
  `charts.jsx` for the index page), and `app.yaml` serves `data/*.json` with
  `expiration: "0s"`.
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): Hard-coded years that go stale on the next refresh: "2019 and 2022–2025" for
  actuals; "Jul–Dec 2025 test split" labels beside `model_comparison.json`.
  The actuals' years come from `ridership_actuals.json`. The split name comes
  from `scored_split`, and the window comes from the `forecasts.json` months,
  but only when those forecasts are the scored Chronos run. Sentences that also
  carry hard-coded metrics were left alone (see below).
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): Dark mode: `index.html` sets `--primary` inline, so P50 values and forecast
  month labels render navy on the dark background. `--primary`/`--accent` are
  set inline only for a colour picked in the Tweaks panel. Text on
  primary/accent buttons is `var(--bg)`, so it keeps contrast on the lighter
  dark-theme colours.
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): R2 N1: `website/app.yaml`'s `url: /` handler sets no expiration, so `index.html`
  is cached for a day and returning visitors keep the old `?v=` cache-busters
  until a reload. `/` and `/*.html` now use `expiration: "0s"`. This is unverified
  until deploy: check with `curl -I`.
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): R2 N2: when the `forecasts.json` fetch fails (network error, 5xx), the
  forecast section says "No forecasts are published" (`sections.jsx` ~:687,
  ~:787-795, ~:911-913). A failed load (network, non-2xx, bad JSON, non-array)
  now has its own copy in the forecast section, the Intervals chart, the WAPE
  chart, the Results tile and the Benchmarks table, separate from an empty file.
- **Addressed on `fix/website-followups`** (PR #140, stacked on #139; not merged): The lede says the forecasts are "the predictions scored in the model
  comparison below" without checking that `model_comparison.json` has the
  Chronos row (the export now refuses to publish forecasts in that case). The
  clause now appears only when the comparison has exactly one Chronos row and
  its `n_predictions` equals the number of published forecasts.
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

### Follow-ups found on `fix/website-followups` (not fixed there)

- Headline metrics and their windows are still hard-coded and will go stale on the
  next refresh: Hero float cards (3.2%, MAE 3,086, "Jul–Dec 2025 holdout"),
  `HeroOrbit`'s 3.2% (`charts.jsx`), AtAGlance (3.2% vs 5.8%, 300
  station-months, "2019 + 2022–2025"), Method's "2019 + 2022–2025", the Dataset
  split labels, the Results lede, the error-band tiles (3.1k / 5.5k / 46–97% /
  "test period Jul–Dec 2025") and their SARIMA line, the Benchmarks lede, and
  Rec 02 (9.7% / 10.8%). Each sentence mixes a year with a metric, so deriving
  only the year could produce a false sentence; they belong with the
  published-claims audit.
- `styles.css` has no `?v=` and is cached for `default_expiration` (1 day).
- Coral buttons ("Fetch Live from API", the active EDA tab) put light text on
  `--accent`, about 3:1 contrast in the light theme. This predates the branch.
- Every page load requests `/favicon.ico`, which does not exist (a 404 in the
  console).

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
