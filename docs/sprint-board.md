# Sprint board

## Sprint 6 — Bias-shifted bands for SARIMA and Chronos-1 (opened 2026-10-25)

**Goal.** Measure, on data up to `val_end` only, whether a band whose
centre is shifted by a recency-weighted estimate of the model's bias,
re-estimated at every monthly forecast origin, can calibrate SARIMA and
Chronos-1. Neither got a qualifying calibration in Sprint 5 (PR #145). P50,
and so every point metric, stays identical. Branch
`feat/adaptive-bias-calibration`, cut from PR #145's tip (1e27507), PR
against `feat/adaptive-interval-calibration` (stacked: #136 → #138 → #145).

**Integrity constraints.**
- *The band is fixed at the forecast origin T.* "Re-estimated each month"
  means re-estimated at each monthly forecast origin. Nothing updates inside
  the scored window: that is what `aci_window` and `monthly_recal` did, which
  Sprint 5 ruled ineligible, and at test time it would read 2025-H2 actuals.
- *Only SARIMA and Chronos-1 are eligible.* SeasonalNaive's and Prophet's
  Sprint 5 entries already have a scored test result; choosing for them again
  now would be choosing with the test split in view. The new candidates are
  scored for them as diagnostics only, and their entries stay whatever the
  numbers say.
- *Where the idea came from.* It was prompted partly by a test-split fact
  already published in Sprint 5: Chronos-1's test misses are 0% below P10 and
  27.3% above P90. The validation evidence for a bias shift, which is what
  this sprint rests on: Chronos-1's Sprint 4 band misses 0.33% / 15.67%
  (below / above) on 2024-H2 and 0.67% / 15% on 2025-H1, nearly all above;
  SARIMA's own band misses 0.33% / 19.33% on 2024-H2 and 7.33% / 1.67% on
  2025-H1, a sign flip.

**Decision rules, fixed before any new number was seen** (user's "go",
2026-10-25, on the plan's three recommendations: six candidates, choice per
model, the fit function in `evaluation/calibration.py` from the start).

*Data, windows, pools.* Exactly Sprint 5's: windows **B** = 2024-H2 from
origin T = 2024-06-30 (pool origins 2023-12-31 … 2024-05-31) and **V** =
2025-H1 from T = 2024-12-31 (pool origins 2023-12-31 … 2024-11-30); pool
rows are those whose target is on or before T, each with explicit `horizon`
and `age` = months from target to T; the store a forecast sees is cut at
min(origin + 6 months, T); the store is cut at `val_end` on read and
asserted; the store-cut check as in Sprint 5.

*Notation.* r = (y − P50) / P50 for every pool row.
- **Bias** m(t) over a set of rows: the lower weighted median of r over the
  pool rows resolved by t (origin before t, target on or before t), weights
  0.5^(age_t / h_b), age_t = months from target to t. Lower weighted median:
  sort r ascending; the smallest r_(k) with Σ_(j ≤ k) w_(j) ≥ 0.5 · Σ w.
- **Width** w: Sprint 5's weighted split-conformal quantile at level 0.8 of
  the scores s_i = |r_i − m_i|, weights 0.5^(age_T / 6), the scored point
  weighted 1: the smallest s with Σ_(s_i ≤ s) w_i ≥ 0.8 · (Σ w_i + 1), +∞ if
  none.
- **Band** at T: P10 = P50 · (1 + m − w), P90 = P50 · (1 + m + w), then
  ordered and floored exactly as `apply_conformal` does (P10 ≤ P50 ≤ P90,
  P10 ≥ 0). The ordering clip only ever widens a band; the rows where it
  binds are counted and reported. The band is stored as an `asym_relative`
  calibrator q = (m − w, m + w), so `apply_conformal` applies it unchanged
  and never writes P50.
- **Bias half-life** h_b ∈ {1, 3} months. The width keeps Sprint 5's 6
  months. With h_b = 6 the pooled candidate would be close to
  `rolling_hl6 asym_relative/pooled`, which already failed both models.

*Eligible candidates, 7 per model (SARIMA, Chronos-1), settings fixed now:*
- `shift_hl1 relative/pooled`, `shift_hl3 relative/pooled`: m = m(T) over
  all pool rows; every s_i = |r_i − m|; one width.
- `shift_hl1 relative/horizon`, `shift_hl3 relative/horizon`: per horizon
  h = 1 … 6, m_h = m(T) over the pool rows at horizon h, s_i = |r_i − m_h|,
  width w_h from those rows; a scored row at horizon h uses (m_h, w_h).
- `shift_origin_hl1 relative/pooled`, `shift_origin_hl3 relative/pooled`:
  each pool row i from origin o_i is scored against the bias that would have
  been estimated at its own origin, m_i = m(o_i) over the pool rows resolved
  by o_i; s_i = |r_i − m_i|. Rows from an origin with no resolved row (the
  first, 2023-12-31) have no score and are left out of the width. The band
  uses m(T) over all pool rows. The width therefore includes how far the
  bias moved between estimate and target. Pooled only: on B no horizon-6 row
  has an earlier horizon-6 bias, so a per-horizon version is infinite there
  by construction.
- `incumbent`: the current `configs/model.yaml` entry, as in Sprint 5:
  SARIMA its own band; Chronos-1 split-conformal `relative/pooled` fit on the
  previous half-year.

*Measured and reported, not eligible:* the same six candidates for
SeasonalNaive and Prophet.

*Qualification and choice.* A candidate qualifies for a model if, on
**both** B and V, coverage is 75–85%, neither tail has more than 15% misses
and the interval score is finite (Sprint 5's test, `rule_table`). Interval
score: Winkler, α = 0.2, summed and divided by total ridership. Each eligible
model takes its own qualifier with the lowest mean of its B and V interval
scores (unrounded; ties by candidate name). There is no "one method for
every model" clause: the two models' errors behave in opposite ways. A model
with no qualifier keeps its current entry.

*Expectation, stated before measuring.* SARIMA may well fail: at T_V its
most recent errors are 2024-H2 under-forecasts, so a shift that follows them
pushes 2025-H1's band up, while 2025-H1 missed low. A non-qualifier is a
valid result. No candidate is added after a number exists.

*Known weaknesses, accepted with the rule.* B's pool has 6 origins (5 for
`shift_origin`, whose first origin has no bias), its horizon-6 group rests on
50 rows from one origin, and SARIMA's B pool comes from 24–29-observation
fits (as in Sprint 5).

*Test.* Scored once, after the choice is committed, and only if SARIMA's or
Chronos-1's entry changes. Deployed mirror of the study one step later:
T = `val_end`, pool origins 2023-12-31 … 2025-05-31, pool targets ≤
`val_end`, forecasts made after the test forecasts. A chosen candidate goes
into `configs/model.yaml` under a new method name, `shift_relative`, so a
reader that ignores `scheme` (PR #144's `serve_band`, `sprint4d/store-rebuild`)
stops instead of fitting a split band nobody chose. If nothing changes, the
leaderboard is rerun at the unchanged configuration and must be
byte-identical to PR #145's; that run chooses nothing and publishes nothing
new. The website's "not calibrated" wording follows Sprint 4's rule
(unchanged): it changes only if every model's calibrated test coverage is
75–85%, and Prophet's 74.0% already fails it.

**Gates.** Point metrics (WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected)
identical to PR #145's leaderboard; `Coverage_raw_%` = 96.67 / 46.0 / 51.0 /
94.33; SeasonalNaive and Prophet `Coverage_%` unchanged (83.67 / 74.00); two
runs byte-identical; after the study change, Sprint 5's seven `adaptive_*`
outputs and PR #138's four validation CSVs byte-identical; unit tests pass;
`py_compile` passes.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S6.1 | Rebuild env (outside `/tmp`) and store; reproduce Sprint 5's study outputs | orchestrator | — | Store `assert_frame_equal` to PR #145's; unchanged study's outputs byte-identical | in progress |
| S6.2 | Fix the rule and candidate definitions before measuring | orchestrator | — | Board committed before any new number | done (this commit) |
| S6.3 | `evaluation/calibration.py`: weighted median, `fit_shift_conformal` (bias at T or at each origin) | implementer | S6.2 | Tests written first, fail, then pass | todo |
| S6.4 | `evaluation/interval_study.py`: `shift_study` with its own outputs, per-model rule, config check layered over Sprint 5's | implementer | S6.3 | Sprint 5 / PR #138 outputs byte-identical; tests | todo |
| S6.5 | Run the study; apply the rule; write-up; commit the choice before any test run | orchestrator | S6.1, S6.4 | Commit precedes S6.6's run | todo |
| S6.6 | If a model qualifies: config + `benchmarks.py` wiring, score test once; else rerun the leaderboard unchanged | implementer | S6.5 | All gates green | todo |
| S6.7 | Review the sprint diff | code-reviewer | S6.6 | No BLOCKER open | todo |
| S6.8 | Audit board against git; push; open PR against `feat/adaptive-interval-calibration` (not merged) | delivery-auditor, orchestrator | S6.7 | Audit clean; PR open | todo |

## Sprint 5 — Interval calibration that tracks recent errors (opened 2026-10-24)

**Goal.** Close the gap PR #138 left (test coverage Prophet 74.7%, Chronos-1
72.7%; SARIMA 96.7% and SeasonalNaive 94.3% on their own bands) with
calibrations that weight recent errors, without changing a point forecast.
Methods are measured on data up to `val_end` only; the test split is scored
once, and only if a model's method changes. Branch
`feat/adaptive-interval-calibration`, stacked on `feat/interval-calibration`
(PR #138 open).

**Environment.** `/tmp/tdf-venv` was found damaged on 2026-10-24 (files
removed by macOS's `/tmp` cleanup at 00:36; `import pandas` fails). Every
gate in this sprint runs on a private rebuild with the same 68 pinned
packages (Python 3.14.0, pandas 3.0.6, numpy 2.5.4, statsmodels 0.15.0,
prophet 1.5.0, torch 2.14.1, chronos-forecasting 2.3.2). The feature store
rebuilt from `data/raw` is identical to PR #138's (`assert_frame_equal`, both
files), and `interval_study.py --refresh` on the rebuild reproduces PR #138's
four validation CSVs byte-identical.

**Decision rules, fixed before any new number was seen** (user's "go ahead
with the defaults", 2026-10-24):

*Calibration data.* Rolling monthly forecast origins from 2023-12-31, each
forecasting 6 months through the code path `benchmarks.py` uses for that
model. 2023-12-31 is the first origin every model can use as deployed:
SARIMA's airline model needs 24 observations, Prophet drops its yearly term
under 18, and Chronos's 24-month context would otherwise reach 2019 rows. For
a window scored from origin T, the calibration pool is every row from origins
2023-12-31 … T − 1 month whose target month is on or before T. Each row
carries `horizon` = months from its origin to its target (an explicit column,
required whenever origins are pooled) and `age` = months from its target to
T. The store a forecast sees is cut at min(origin + 6 months, T).

*Scored windows* (both before `val_end`; the store is cut at `val_end` and
asserted, as in PR #138): **B** = 2024-H2 from origin 2024-06-30 (pool: 6
origins), **V** = 2025-H1 from origin 2024-12-31 (pool: 12 origins), 300
station-months per model each.

*Eligible candidates, 10 per model, settings fixed now:*
- `incumbent`: the model's current `configs/model.yaml` entry (Prophet
  `scaled/horizon`, Chronos-1 `relative/pooled`, each fit on the previous
  half-year as in PR #138; SARIMA and SeasonalNaive their own band).
- `rolling_hl6` × score {`scaled`, `relative`, `asym_relative`} × group
  {`pooled`, `horizon`} (6): weighted split-conformal quantile (Barber et al.
  2023) over the pool, weight 0.5^(age/6), the scored point weighted 1. The
  quantile is the smallest score s with Σ_{s_i ≤ s} w_i ≥ level·(Σ w_i + 1),
  +∞ if none. `asym_relative` calibrates each tail at 0.1 as in PR #138.
- `aci_origin` × score {`scaled`, `relative`, `asym_relative`}, pooled (3):
  adaptive conformal inference (Gibbs & Candès 2021) over monthly batches.
  For each target month m from the second month in the pool through T, in
  order: the band for the batch (pool rows whose target is m) uses the
  unweighted conformal quantile of the pool rows whose target is before m, at
  level 1 − α_m; err_m = the batch's miss rate; α_{m+1} = α_m + 0.1·(0.2 −
  err_m). α starts at 0.2 and is clipped to [1/(n+1), 0.5], n = rows in that
  quantile's pool, so the quantile stays finite. `asym_relative` runs one α per
  tail, starting at 0.1 and targeting 0.1. The scored window's band uses the
  final α on the whole pool.

*Measured and reported, not eligible:* `rolling_eq` (equal weights, 3 scores
× 2 groups); PR #138's other single-window variants; and two methods that
revise the band inside the scored window with that window's earlier actuals,
which a band fixed at the forecast origin cannot use, both pooled, 3 scores
each: `aci_window` (scored month k uses `rolling_hl6`'s weighted quantile at
level 1 − α_k, α_1 = 0.2 or 0.1 per tail, updated after each month with that
month's miss rate as in `aci_origin`) and `monthly_recal` (`rolling_hl6`
refit before each scored month with every row resolved by then from origins
≤ T, ages counted from the latest resolved month).

*Qualification and choice.* A candidate qualifies for a model if, on **both**
B and V, coverage is 75–85% and neither tail has more than 15% misses.
Qualifiers rank by the mean of their B and V interval scores (Winkler, α =
0.2, summed and divided by total ridership, as in PR #138). If one
non-incumbent candidate qualifies for all four models, the one with the
lowest mean score across models is used for all; otherwise each model takes
its own lowest-scoring qualifier; a model with no qualifier keeps its current
entry. Prophet MCMC stays ineligible. Known weakness, accepted with the rule:
SARIMA's B pool comes from 24–29-observation fits and horizon 6 from a single
origin, and Prophet's and SARIMA's settings were picked by inspecting 2024-H2,
so B can fail a model for reasons that do not apply to the deployed fit (it
then keeps its current entry).

*Test.* Scored once, after the choice is committed, only if some model's
method changes. Deployed mirror of the study one step later: origins
2023-12-31 … 2025-05-31, pool targets ≤ `val_end`, forecasts made after the
test forecasts. The website's "not calibrated" wording changes only if every
model's calibrated test coverage is 75–85% (Sprint 4 rule, unchanged).

**Gates.** Point metrics (WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected)
identical to PR #138's leaderboard; `Coverage_raw_%` = 96.67 / 46.0 / 51.0 /
94.33; two runs byte-identical; unit tests pass; `py_compile` passes.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S5.1 | Rebuild env and store; reproduce PR #138's validation CSVs | orchestrator | — | Four CSVs byte-identical | done — see Environment above |
| S5.2 | Fix the rule and candidate definitions before measuring | orchestrator | S5.1 | Board committed before any new number | done (6daa610, committed 03:18:18; no Sprint 5 number existed until the S5.4 run after 122fc9c) |
| S5.3 | `evaluation/calibration.py`: weighted quantile, rolling-pool fit (explicit horizon required), ACI | implementer (orchestrator) | S5.2 | Tests written first, pass | done (a244698) — 19 new tests in `tests/test_adaptive_calibration.py`, written and failing first; 47 calibration tests pass |
| S5.4 | `evaluation/interval_study.py`: rolling origins, windows B and V, eligible and diagnostic candidates, selection by the S5.2 rule | implementer (orchestrator) | S5.3 | Store cut at `val_end` and asserted; CSVs written | done — code committed (122fc9c) before its first run; store-cut check 0.0 (made strict in the S5.7 fix round); PR #138's four CSVs still byte-identical. One diagnostic bug found in the results and fixed (2589ed8: `aci_window` clipped α to the row count, not the total weight); every eligible result and the decision byte-identical before and after |
| S5.5 | Apply the rule; write-up; commit the choice before any test run | orchestrator | S5.4 | Commit precedes S5.6's run | done (7cdfd11, committed 03:40:53; first test run started 03:41) — no candidate qualified for every model; per model: SeasonalNaive `rolling_hl6 asym_relative/horizon`, Prophet `rolling_hl6 relative/pooled`; SARIMA and Chronos-1 no qualifier, Sprint 4 entries kept. Deployed quantiles computed from data to `val_end` in the study: SeasonalNaive q_lo −0.0129…−0.0150, q_hi 0.1686…0.1700 by horizon; Prophet q = 0.0789 (n = 4,650 each) |
| S5.6 | If a method changes: wire into `benchmarks.py`, gates, score test once | implementer (orchestrator) | S5.5 | All gates green | done — `scheme: rolling` wired for SeasonalNaive and Prophet with 5 tests written first (7cdfd11); test scored once at 7cdfd11: SeasonalNaive 94.33% → 83.67%, Prophet 74.67% → 74.00%, SARIMA 96.67% and Chronos-1 72.67% unchanged. Gates below. Write-up, README and `model_comparison.json` follow the result; website wording stays "not calibrated" by Sprint 4's rule |
| S5.7 | Review the sprint diff | code-reviewer | S5.6 | No BLOCKER open | done — review of 292f0aa..8e269c2: spec PASS, 0 BLOCKER, 3 MAJOR, 10 MINOR; no published number wrong. Fix round 3eb7b2c; scoped re-review of it: spec PASS, quality PASS, 3 MINOR, closed in fix round 2 (below) |
| S5.8 | Audit board against git; push; open PR against `feat/interval-calibration` (not merged) | delivery-auditor, orchestrator | S5.7 | Audit clean; PR open | done — audit of 292f0aa..bfd8362: 1 MEDIUM, 3 LOW, none changing a choice or a number; all four addressed in this commit (a Sprint 5 row that a string replace had also inserted into Sprint 4's gate table is removed; study re-run and test-split access wording made exact; #138's two later doc commits, 29c5c18 and 626b829, merged in at a303f20; fixes in 5d0254a). Done: branch pushed with an explicit refspec (its upstream had been PR #138's branch, which stays at 626b829); PR #145 opened against `feat/interval-calibration` (stacked: #136 → #138 → #145), not merged |

**Gate results (S5.6, 2026-10-24, rebuilt pinned env, code at 7cdfd11).**

| Gate | Result |
|---|---|
| Point metrics | WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected identical to PR #138's leaderboard on every slice (`assert_frame_equal`); column and row order unchanged |
| Raw coverage | `Coverage_raw_%` = 96.67 / 46.0 / 51.0 / 94.33 |
| Determinism | Two consecutive runs: leaderboard, results CSV and LaTeX byte-identical |
| Deployed quantiles | Logged by `benchmarks.py` equal to the study's pre-test values (SeasonalNaive q_hi − q_lo 0.1829–0.1840, Prophet q = 0.0789, n = 4,650) |
| Calibrated test coverage (scored once) | SeasonalNaive 83.67% (3.3% / 13.0%), Prophet 74.00% (13.0% / 13.0%); SARIMA 96.67%, Chronos-1 72.67% unchanged. `scripts/interval_test_breakdown.py` reproduces both new coverages and PR #138's previous ones exactly |
| Website rule | Not every model in 75–85%: "not calibrated" stays; range 73–97% unchanged |
| Tests / compile | 53 calibration tests pass; `py_compile` passes on every touched .py |
| Test-split access | Three `benchmarks.py` runs, all at the chosen configuration: run 1 scored (7cdfd11), run 2 its determinism check, run 3 a confirmation after the review fix round. `scripts/interval_test_breakdown.py` reads the test split to describe that result and chooses nothing. `scripts/export_website_data.py` ran once (03:48, after the scored run) and loads the full store for the station JSONs; only `model_comparison.json`, built from the leaderboard, was committed |
| After the review fix round | Same configuration re-run: leaderboard and results CSV byte-identical to the scored run; LaTeX differs only by the corrected caption; the breakdown script reproduces every test figure; 62 unit tests pass (65 after fix round 2) |

**Review fix round (S5.7).** None of these changes the decision or a published
test number; the study re-run after them gives identical values for every
existing candidate row and an identical `adaptive_decision.yaml`.
- MAJOR, fixed:
  - the LaTeX caption, the `calibrate_intervals` docstring and an export
    comment still said "split-conformal, fit on the validation split";
  - README overclaimed ("dependable 80% interval" on one window) and said
    Prophet uses "the same method" as seasonal naive (only the scheme is
    shared);
  - the store-cut check used `nanmax` and could not fail. It now stops on a
    missing forecast at or before T and on any difference, and reports rows
    actually compared (fix round 2: only origins whose window runs past T,
    5 per window; 1,500 rows, or 750 for SeasonalNaive).
- MINOR, fixed:
  - the selection rule moved into `rule_table` / `apply_rule` with 8 tests:
    an infinite band (NaN score) never qualifies, ties break by name, sorting
    is stable;
  - `scheme: rolling` without `half_life` now fails loudly instead of meaning
    equal weights (test added);
  - the breakdown script stops instead of refitting when a cached forecast is
    missing, and stops on a missing bound; its description is corrected;
  - doc numbers: monthly_recal 22.96 (not 22.97), "unit weights" (not
    "equal"), Prophet's Sprint 4 drop was 7.3 points;
  - `station` added to the single-window diagnostics, as the rule's "other
    single-window variants" includes it;
  - `--refresh` refits each forecast once per run;
  - dead code removed;
  - deployed calibrators written to `deployed_calibrators.yaml`;
  - the doc's tables are written by `interval_study.py` (`adaptive_tables.md`);
  - this table moved below the story table.
- Fix round 2, after the scoped re-review (3 MINOR):
  - the study pins windows B and V (`SPRINT5_WINDOWS`) and stops if the
    config moves them;
  - `check_config_matches_decision` stops the study if a `configs/model.yaml`
    entry is not the validated choice (or the incumbent where nothing
    qualified): method, group, scheme, half_life and first_origin. 3 tests;
  - the study's deployed block requires `half_life`, as `benchmarks.py` does;
  - the store-cut counts exclude origins whose cut changes nothing;
  - the doc's Rule section names the three implementation choices added after
    results (finite score, unrounded mean, ties by name).
  - Study re-run: 6 of the 7 adaptive output files byte-identical;
    `adaptive_checks.csv` changed as intended (new `origins_cut` column, the
    corrected counts); PR #138's four validation CSVs unchanged. (bfd8362's
    commit message says "all six output files", which is imprecise in the
    same way.)
- Disclosed, not changed:
  - `benchmarks.py` does not itself check the config against the study; the
    study does;
  - tests and implementation landed in the same commits (a244698, 7cdfd11),
    so "tests written first" rests on the session record: each new test file
    was run and failed before the implementation existed;
  - the 1e-9 clip margin came after results were seen, and only touches the
    `aci_window` diagnostic (2589ed8).

**Follow-ups (Sprint 5, not fixed here).**
- SARIMA's errors change sign between half-years and Chronos-1's band misses
  its upper tail; neither has a qualifying calibration. A monthly
  re-estimated bias correction of the band (P50 untouched) would be a new
  candidate set under a new rule.
- `interval_study.py` caches forecasts by model family and origin only. A
  different Chronos-1 checkpoint would reuse chronos-t5-small's forecasts
  under the new label (pre-existing, from PR #138).
- Month arithmetic (`origin + DateOffset(months=6)`) assumes month-start
  timestamps, which the store has.
- SeasonalNaive's test forecast covers every row after `val_end`. If the
  store grows past 2025-12, `group: horizon` has no quantile for horizon 7 and
  beyond, and its coverage goes NaN (loudly).
- The serving path (API, `forecasts.json`) still publishes raw bands.
- `/tmp/tdf-venv` should be rebuilt, or moved out of `/tmp`; anything there
  is removed after 3 days without access.

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
