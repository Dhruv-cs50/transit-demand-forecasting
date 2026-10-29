# Caltrain Ridership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forecast Caltrain systemwide monthly average weekday ridership with the four BART models, show it on the site with the per-station annual figures, and accept new months through the cloud bucket — without moving any BART number.

**Architecture:** Hand-verified monthly figures extracted from Caltrain's Executive Director reports become a small tracked CSV; a separate store builder adds method-period flags and an electrification step; a separate benchmark reuses the BART model functions with the step as exogenous input and writes its own leaderboard; the export adds Caltrain JSON files; the site gets a Caltrain section.

**Tech Stack:** Python 3.14 (`~/.venvs/tdf-py314`, `requirements-lock.txt`), pandas, statsmodels SARIMAX, Prophet, Chronos-1; `pypdf` for extraction (add an exact pin to the lock); React site.

**Execution:** subagent-driven (user, 2026-10-28): a fresh implementer per task, a fresh reviewer before the next task, a whole-branch review at the end. Starts 2026-11-04; the route-assistant and Caltrain plans run as two parallel lanes.

**Spec:** `docs/superpowers/specs/2026-10-28-route-assistant-and-caltrain-design.md` (section 5, plus 6–8, 11).

## Global Constraints

- Branch `feature/nov15`; nothing merges to `main` without the user's approval; site changes go to the Firebase preview channel only.
- BART artifacts must not change: leaderboard `d0d66f03…`, results `8f708b71…`, LaTeX `849f1672…`, tracked store `6cde32d4…`, all existing `website/data/*.json` byte-identical. Every task that touches shared code re-checks this.
- Scope (a): one systemwide monthly series (average weekday ridership, "AWR"); per-station figures are annual and descriptive only, never modelled.
- 2020–21 excluded. Method-change months flagged: April 2020 and June 2022. Electrification is a level-shift indicator from the full-service launch month, confirmed from Caltrain's own documents and stored in `configs/caltrain.yaml`.
- Every number on the site comes from data files; the site says the figures are Caltrain's estimates from a fare-media sales model, not passenger counts.
- Reproducible: seeded models; two benchmark runs byte-identical.

## Review Focus

1. **A monthly report missing, or with a revised figure for an earlier month:** keep the first-published value, record the revision in a `revised_from` column, never silently overwrite. → Task 1 `test_revision_kept_and_recorded`.
2. **A month whose PDF text does not match the extraction pattern** (layout changed): the extractor fails loudly for that month instead of returning a wrong number. → Task 1 `test_unmatched_layout_raises`.
3. **The electrification month falling inside a holdout window:** a model must never see post-launch data before its fit cutoff except through the indicator; windows where the step lies after the cutoff use the indicator's known future value (it is a known schedule change). → Task 3 `test_step_known_future_and_no_leak`.
4. **Too few points for a window** (a fit with < 24 usable months): skip that model-window cell with an explicit "insufficient history" entry, never a silent zero. → Task 3 `test_insufficient_history_cell`.
5. **A new month uploaded to the bucket that is not after the last month:** rejected by the ingest check. → Task 5 `test_non_increasing_month_rejected`.

---

### Task 1: Extract and verify the monthly series

**Files:**
- Create: `machine_learning_files/caltrain_reports.py`, `data/caltrain/report_index.csv` (month, report URL), `data/caltrain/awr_monthly.csv`, `data/caltrain/MANIFEST.md`, `configs/caltrain.yaml`
- Test: `tests/test_caltrain_reports.py` (fixtures: text extracted from two real reports, committed as `.txt`)

**Interfaces:**
- Produces:
  - `def extract_awr(pdf_text: str, month: str) -> int` — the "Average Weekday Ridership" value for `month` (`"YYYY-MM"`); raises `ExtractionError` when the expected label and month are not found.
  - `def build_series(index_csv: Path, cache_dir: Path) -> pd.DataFrame` — downloads each report once into `cache_dir` (gitignored), records sha256, returns columns `month, awr, report_url, sha256, revised_from`.
  - `data/caltrain/awr_monthly.csv` with those columns, hand-checked: `MANIFEST.md` lists every month with the page where the value appears and a "checked by hand" mark.
  - `configs/caltrain.yaml`: `electrification_start: "YYYY-MM"` (confirmed from a Caltrain document cited in `MANIFEST.md`), `method_changes` (the changes Caltrain documents, each cited in `MANIFEST.md`: `["2019-02", "2020-04", "2023-11", "2025-01"]`; amended 2026-10-29, the original `2022-06` had no source), `exclude: ["2020-01".."2021-12"]`, `train_start: "2022-01"`, and the holdout windows (Task 3).

- [ ] **Step 1:** Collect report URLs from caltrain.com into `report_index.csv` (target Jan 2019 onward); download; save the extracted text of two reports with different layouts as fixtures.
- [ ] **Step 2:** Tests: `test_extract_known_value` (fixture → the value printed in that PDF); `test_unmatched_layout_raises`; `test_revision_kept_and_recorded`. Run, expect FAIL.
- [ ] **Step 3:** Implement; build the CSV; hand-check every row against its PDF and complete `MANIFEST.md`. Confirm and record the electrification launch month.
- [ ] **Step 4:** Run tests, expect PASS. Commit `data(caltrain): hand-verified monthly AWR series`.

### Task 2: Per-station annual table and the Caltrain store

**Files:**
- Create: `data/caltrain/station_annual.csv`, `machine_learning_files/caltrain_store.py`, `data/processed/caltrain_store.parquet` (committed, like the BART store)
- Test: `tests/test_caltrain_store.py`

**Interfaces:**
- Consumes: `awr_monthly.csv`, `configs/caltrain.yaml`.
- Produces:
  - `station_annual.csv`: `fiscal_year, station, avg_midweek_boardings, report_url` from each annual report FY2019–FY2026, hand-checked (listed in `MANIFEST.md`).
  - `def build_caltrain_store(cfg: dict) -> pd.DataFrame` — monthly rows, columns `timestamp` (month start), `station_id="CALTRAIN_SYSTEM"`, `ridership` (= AWR, so the BART model functions apply unchanged), `method_period` = the latest `method_changes` entry at or before the row's month (e.g. `2023-11`), plus one 0/1 step column per change inside training (`method_2023_11`, `method_2025_01`) so the model reads the Jan 2025 +21% counting change as a level shift, not demand, `electrified` (0/1 from `electrification_start`); 2020–21 rows dropped. Writes the parquet; prints its sha256.

- [ ] **Step 1:** Tests: `test_excludes_2020_2021`; `test_method_period_boundaries` (2023-10 vs 2023-11 and 2024-12 vs 2025-01); `test_electrified_step` (0 before, 1 from the configured month); `test_columns_match_bart_contract` (`timestamp`, `station_id`, `ridership` present). Run, expect FAIL.
- [ ] **Step 2:** Implement; transcribe and check the annual table; build and commit the store.
- [ ] **Step 3:** Run tests, expect PASS. Re-run the BART gate's byte checks (store, website JSON) — unchanged. Commit `feat(caltrain): store with method periods and electrification step`.

### Task 3: Caltrain benchmark across windows

**Files:**
- Create: `models/caltrain/benchmark.py`
- Output (gitignored, like `evaluation/outputs/`): `evaluation/outputs/caltrain/leaderboard.csv`, `windows.csv`, `forecasts_<model>.parquet`
- Test: `tests/test_caltrain_benchmark.py`

**Interfaces:**
- Consumes: the store (Task 2); `models.baselines.arima.fit_station(station_df, station_id, freq, use_auto=False, exog=…)` and `predict_station(fit, last_train_ts, horizon_steps, freq, confidence=0.80, exog_future=…)`; `models.baselines.prophet_baseline.fit_station(station_df, station_id, cfg)` / `predict_station(model, horizon_steps, last_ds, freq)`; `models.baselines.benchmarks.seasonal_naive_forecast(train_df, test_df, freq)` and `compute_metrics(actuals, preds, model_name, …)`; the Chronos-1 zero-shot path in `models/chronos2/predict.py` (`Predictor`; read how `benchmarks.py` calls it and call it the same way, univariate).
- Produces: `def run_caltrain_benchmark(store: pd.DataFrame, cfg: dict) -> pd.DataFrame` — one row per window × model: `window, model, wape, mae, n, coverage_own_band, status` (`ok` or `insufficient history`). SARIMA gets `exog=[electrified]`; Prophet gets an added regressor `electrified` (its documented changepoint alternative is the regressor, simpler and equivalent here); seasonal naive and Chronos-1 run univariate. Windows: the latest three half-years that have ≥ 24 usable months before their cutoff and complete actuals, configured in `configs/caltrain.yaml`; the latest is the test window, scored once after the choices are frozen.

- [ ] **Step 1:** Tests: `test_step_known_future_and_no_leak` (no `ridership` after the cutoff reaches any fit; `exog_future` equals the configured schedule); `test_insufficient_history_cell`; `test_two_runs_identical` (two calls → identical frames); `test_bart_outputs_untouched` (the function writes only under `evaluation/outputs/caltrain/`). Run, expect FAIL.
- [ ] **Step 2:** Implement. Run the benchmark twice; outputs byte-identical.
- [ ] **Step 3:** Run tests, expect PASS. Record the window × model table in the commit message. Commit `feat(caltrain): four-model benchmark across half-year windows`.

### Task 4: Export and site section

**Files:**
- Modify: `scripts/export_website_data.py` (add Caltrain outputs inside the existing all-or-nothing staging), `website/sections.jsx`, `website/charts.jsx`, `website/index.html` (cache-busters, nav link)
- Create: `website/data/caltrain_series.json`, `caltrain_forecast.json`, `caltrain_leaderboard.json`, `caltrain_station_annual.json` (generated)
- Test: `tests/test_export_caltrain.py`

**Interfaces:**
- Produces JSON contracts:
  - `caltrain_series.json`: `[{month, awr, method_period, electrified}]`
  - `caltrain_forecast.json`: `{model, fit_through, rows: [{month, p10, p50, p90}]}` for the best model on the test window (by WAPE)
  - `caltrain_leaderboard.json`: rows of Task 3's table, plus `source` and `scored_split`
  - `caltrain_station_annual.json`: rows of `station_annual.csv`
- Site: a "Caltrain" section after the BART results — the monthly series with method-change and electrification markers, the forecast with its band, the window × model table, the per-station annual table, and the estimate-not-count note. All text derived from these files.

- [ ] **Step 1:** Tests: `test_caltrain_files_written_with_contract`; `test_existing_bart_json_byte_identical`; `test_export_refuses_when_caltrain_outputs_missing` (nothing published). Run, expect FAIL.
- [ ] **Step 2:** Implement the export; run it; then build the section. Verify in a browser at 1440, 1280 and 375 px; JSX parses (`npx esbuild@0.24.0 --loader:.jsx=jsx`).
- [ ] **Step 3:** Run tests, expect PASS. Commit `feat(site): Caltrain section`.

### Task 5: Cloud folder for new months

**Files:**
- Modify: `machine_learning_files/cloud_ingest.py`, `configs/ingest.yaml`
- Test: `tests/test_cloud_ingest_caltrain.py`

**Interfaces:**
- Consumes: Task 1's CSV schema; the existing `cloud_store.Store` and `cloud_ingest` staging.
- Produces: the ingest job also stages `raw/caltrain/awr_monthly.csv` (uploaded by hand after each report), checks it, rebuilds the Caltrain store with `build_caltrain_store`, and publishes it beside the BART store under `processed/runs/<run_id>/caltrain_store.parquet`, listed in `manifest.json`. Checks: every month already in the committed CSV is present with an identical value (revisions go through `revised_from`, Task 1); months strictly increasing; no month after the last closed month. A failed Caltrain check fails the run, like the BART gate.

- [ ] **Step 1:** Tests: `test_caltrain_csv_staged_and_published`; `test_non_increasing_month_rejected`; `test_changed_history_rejected`; `test_bart_gate_unchanged` (the existing BART gate result is identical with and without the Caltrain file). Run, expect FAIL.
- [ ] **Step 2:** Implement. Run the full ingest suite on `~/.venvs/tdf-api-py311`. Dry-run the job locally against a `file:///` seed that includes `raw/caltrain/`.
- [ ] **Step 3:** Commit `feat(ingest): raw/caltrain folder in the cloud job`. Deploying the updated job happens with the preview review, not before.

### Task 6: Gate and preview

- [ ] **Step 1:** Run the full BART gate (S7-13 set) on a clean archive of `feature/nov15`: all BART hashes unchanged; Caltrain benchmark two runs identical; pytest on 3.14 and the 3.11 suites pass; JSX parses.
- [ ] **Step 2:** Deploy the site to the `nov15-preview` Firebase channel (shared with the route-assistant plan). Hand the preview to the user; merge to `main` only on approval.
