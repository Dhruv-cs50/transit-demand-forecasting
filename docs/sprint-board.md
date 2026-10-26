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
runs byte-identical; after the study change, Sprint 5's seven outputs (six
`adaptive_*` files, and `deployed_calibrators.yaml` except for a model whose
entry Sprint 6 changes) and PR #138's four validation CSVs byte-identical;
unit tests pass; `py_compile` passes.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S6.1 | Rebuild env (outside `/tmp`) and store; reproduce Sprint 5's study outputs | orchestrator | — | Store `assert_frame_equal` to PR #145's; unchanged study's outputs byte-identical | done — see Environment below |
| S6.2 | Fix the rule and candidate definitions before measuring | orchestrator | — | Board committed before any new number | done (this commit) |
| S6.3 | `evaluation/calibration.py`: weighted median, `fit_shift_conformal` (bias at T or at each origin) | implementer | S6.2 | Tests written first, fail, then pass | done — tests d787b16 (committed failing: `ImportError: cannot import name 'fit_shift_conformal'`), implementation e175f79; additions only to `calibration.py` |
| S6.4 | `evaluation/interval_study.py`: `shift_study` with its own outputs, per-model rule, config check layered over Sprint 5's | implementer | S6.3 | Sprint 5 / PR #138 outputs byte-identical; tests | done — tests 36e0607 (committed failing: `ImportError: cannot import name 'SHIFT_CANDIDATES'`), implementation e2397f8; 124 tests pass; old vs new module on synthetic pools: 63 equivalence checks pass; on real data the 10 Sprint 5 / PR #138 files are byte-identical (S6.5 run) |
| S6.5 | Run the study; apply the rule; write-up; commit the choice before any test run | orchestrator | S6.1, S6.4 | Commit precedes S6.6's run | done (this commit) — Chronos-1 `shift_hl1 relative/horizon`; SARIMA no qualifier, own band kept. See S6.5 notes below |
| S6.6a | `shift_relative` through #144's path: `interval_plan` label and `band_method`, `calibrate_intervals` fit + save (provenance `method_config`, `bias_half_life`, `bias_at`), `serve_band` checks; Chronos-1 rolling pool in `run_benchmarks`; tests first; the implementer runs no benchmark, export or API | implementer | S6.5, merge ea6bde4 | 229+ tests pass; saved calibrator served identically | in progress (dispatched 2026-10-25) |
| S6.6b | `scripts/interval_test_breakdown.py` describes Chronos-1's band too (reproduces the leaderboard's coverage and Sprint 4's 72.67); not run by the implementer | implementer | S6.5 | py_compile; SN/Prophet output unchanged by reading | in progress (dispatched 2026-10-25, parallel with S6.6a: file sets disjoint) |
| S6.6c | Score the test split once; determinism rerun; gates; breakdown; export `model_comparison.json` + `forecasts.json`; README and write-up | orchestrator | S6.6a, S6.6b, the merged study re-verification | All gates green; logged calibrator equals the study's deployed one at full precision | todo |
| S6.7 | Review the sprint diff | code-reviewer | S6.6 | No BLOCKER open | todo |
| S6.8 | Audit board against git; push; open PR against `feat/adaptive-interval-calibration` (not merged) | delivery-auditor, orchestrator | S6.7 | Audit clean; PR open | todo |

**S6.5 notes (validation only, 2026-10-25).**
- First Sprint 6 numbers: the study at e2397f8, started 20:19:50. It
  computed the decision and stopped at `check_config_matches_shift_decision`
  before writing anything, because `configs/model.yaml` did not yet carry
  Chronos-1's validated entry (Sprint 5's pattern: the config must hold the
  choice before outputs are written). The tables were then printed by a
  read-only scratch script that calls `shift_study` alone (validation data,
  writes nothing in the repo), to check them before the config changed.
- Checks on those tables: the SARIMA and Chronos-1 incumbent rows equal
  Sprint 5's exactly; 300 rows per window have no origin bias in the
  `shift_origin` candidates (the first origin's), as designed; the 12
  `invalid value encountered in multiply` warnings are Sprint 5's (same
  count in the unchanged study's run), none from `shift_study`.
- Decision, by the rule: Chronos-1 `shift_hl1 relative/horizon` (the only
  qualifier: B 82.33%, 3.0 / 14.67; V 83.33%, 2.0 / 14.67; mean score
  29.02); SARIMA keep current entry (no qualifier).
- Config: Chronos `{method: shift_relative, group: horizon, scheme: rolling,
  half_life: 6, bias_half_life: 1, bias_at: as_of, first_origin:
  "2023-12-31", validated_for: "amazon/chronos-t5-small"}`. Study rerun
  20:23:00: same decision; it fit Chronos-1 from origins 2025-01-31 …
  2025-05-31 with the store cut at `val_end` (the deployed pool's five new
  origins); Sprint 5's six `adaptive_*` files and PR #138's four CSVs
  byte-identical to PR #145's; `deployed_calibrators.yaml` differs only in
  Chronos-1's entry. 124 unit tests pass with the new config.
- Deployed Chronos-1 calibrator (full precision kept for the S6.6 parity
  gate): n = 4,650; bias by horizon 1–6 = 0.034851, 0.100458, 0.096520,
  0.103179, 0.090771, 0.089513; width = 0.086624, 0.111627, 0.106900,
  0.110687, 0.111075, 0.114898; no clipped horizon.

**Merge of PR #145's moved base (ea6bde4, after S6.5, before any test-split access).**
- The Sprint 5 session moved `feat/adaptive-interval-calibration` to
  1c5d0b1 while S6.5 ran: it merges `sprint3/pr-backlog` (#138, #144's
  saved calibrators with `interval_plan` / `serve_band`, #147's store with
  2019–2025 weather and events). Merged at ea6bde4; one conflict
  (`evaluation/calibration.py`, both sides appended a section; both kept).
- The tracked store is now `aa02436d…`; the enriched store rebuilt from it
  with `Processing/feature_engineering.py` is byte-identical (SHA-256
  `60df3541…`) to the Sprint 5 session's post-merge build, and `ridership`
  equals the pre-merge store's on all 3,000 rows.
- 229 tests pass on the merge (the pinned env plus pytest 9.1.1, fastapi
  0.162.0 and httpx 0.28.1 for tests only; `pip freeze` still contains all
  68 pins unchanged).
- Sprint 6's study ran on the pre-merge base. Re-run on the merge with
  `--refresh` (20:33–20:40, all 108 forecasts refit on the new store): all
  17 outputs (six `adaptive_*`, `deployed_calibrators.yaml`, four
  `validation_*`, six `shift_*`) byte-identical to the S6.5 run's, so the
  decision and the deployed Chronos-1 calibrator stand. Of the 108 refit
  forecast files, 107 are byte-identical and one (`Prophet_MCMC`,
  2024-12-31, not used by Sprint 6) has identical values and differs only in
  its recorded fit time (28.9 s vs 29.1 s).
- Under #144's flow, `shift_relative` must also be labelled, saved and
  served (the website export calls `serve_band` for Chronos-1), so S6.6 is
  split into S6.6a / S6.6b / S6.6c. The stopped S6.6 dispatch had changed no
  file.
- Gate reference after the merge: the Sprint 5 session's post-merge run
  (leaderboard byte-identical to PR #145's scored run; results CSV gains the
  `game_day` / `rainy_day` slices #147's data populates).

**Environment (S6.1, 2026-10-25; produces no Sprint 6 number).**
- Venv `~/.venvs/tdf-pinned`, outside `/tmp`, rebuilt from the pip cache
  with the 68 pins Sprint 5 recorded; `pip freeze --all` equals the pin list
  exactly (Python 3.14.0, pandas 3.0.6, numpy 2.5.4, statsmodels 0.15.0,
  prophet 1.5.0, torch 2.14.1, chronos-forecasting 2.3.2).
- `data/raw` copied from the `interval-calibration` worktree: its 69 files'
  SHA-256 equal PR #145's worktree's. Store rebuilt with
  `machine_learning_files/merge_pipeline.py` and
  `Processing/feature_engineering.py`; both stores and the three splits
  `assert_frame_equal` to PR #145's.
- PR #145's 206 cached forecasts copied. The study at 1e27507, run from a
  clean export, refit nothing and reproduced all 11 outputs (Sprint 5's six
  `adaptive_*` files and `deployed_calibrators.yaml`, PR #138's four
  `validation_*.csv`) byte-identical.
- Spot refit in this env of each model's 2024-12-31 forecast (window V):
  300/300 rows, largest difference from the cache 0.0 for all four models.
- Reference leaderboard for the gates: PR #145's, written 04:15:31 on
  2026-10-24 by `benchmarks.py` as at 3eb7b2c (unchanged at 1e27507).

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
| Test-split access | Five `benchmarks.py` runs, all at the chosen configuration: run 1 scored (7cdfd11), run 2 its determinism check, run 3 a confirmation after the review fix round, run 4 a confirmation after merging `sprint3/pr-backlog` (working tree, see below), run 5 the same confirmation on a clean checkout of bdda3b7. `scripts/interval_test_breakdown.py` reads the test split to describe that result and chooses nothing. `scripts/export_website_data.py` ran once (03:48, after the scored run) and loads the full store for the station JSONs; only `model_comparison.json`, built from the leaderboard, was committed |
| After the review fix round | Same configuration re-run: leaderboard and results CSV byte-identical to the scored run; LaTeX differs only by the corrected caption; the breakdown script reproduces every test figure; 62 unit tests pass (65 after fix round 2) |
| After merging `sprint3/pr-backlog` (084e5a1: #138, #144's saved calibrators and `serve_band`, #147's store with 2019–2025 weather/events) | `scheme` carried through `interval_plan`, `calibrate_intervals`' save path and `serve_band` (rolling calibrators record `fit_end` = `val_end`); enriched store rebuilt from the tracked store (`aa02436d…`); `interval_study.py --refresh` refit on it: all 11 outputs byte-identical to the old store's; run 4: leaderboard and LaTeX byte-identical to run 3, results CSV identical on every existing row plus `game_day` / `rainy_day` slices that #147's 2025 weather and events populate; SeasonalNaive and Prophet calibrators saved (fit_end 2025-06-30, scheme rolling, half-life 6) and served by `serve_band`; 170 tests pass |
| Correction: the merge as pushed was broken | 084e5a1 left out `evaluation/calibration.py` (its `interval_plan` returned no `scheme`), so the pushed heads 084e5a1 and d37bfd1 raised `KeyError: 'scheme'` in `calibrate_intervals` and failed 20 tests on a clean checkout (found by the PR #138 session). The row above was measured on the working tree, which had the change. Fixed in bdda3b7. Verified on a clean `git worktree` of bdda3b7 (enriched store rebuilt from the tracked `aa02436d…`): 170 tests pass (153 without `test_api`); run 5's leaderboard, results CSV and LaTeX byte-identical to run 4, leaderboard byte-identical to the scored run 1; quantiles and saved calibrators as above. Rule adopted: verify from a clean checkout of the pushed commit, never the working tree |

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
- Regenerate the EDA plots from the current store; the notebook groups monthly rows by day
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

**Branch.** `feat/covariate-benchmark`, cut from `origin/fix/bart-station-table` @ `7598107`.
Pinned env rebuilt outside `/tmp`: `~/.venvs/tdf-py314` (the gate env's 66 pins + pip 26.2.1 /
setuptools 84.2.1, plus pytest for the unit tests).

**Gates.** Control SARIMA reproduces 3.21 % (n = 300) and equals the leaderboard's SARIMA row on the
same run; the four leaderboard overall rows are unchanged by the 2024–25 data (each delta named
otherwise); `model_comparison.json` unchanged; unit tests pass; `py_compile` passes.

| ID | Goal | Role | Depends on | Acceptance check | State |
|---|---|---|---|---|---|
| S4e.0 | Baseline: rebuild store and run benchmarks on unmodified `7598107` | orchestrator | — | Leaderboard 3.21 / 5.75 / 9.70 / 10.75, n = 300 | done — run0: leaderboard CSV byte-identical to #139's gate2; base store SHA-256 `9a7771080c59…a323cea`, byte-identical to gate2's and to Sprint 4d's rebuilt store |
| S4e.1 | Fetch weather and Sharks games for 2024–25; record hashes in `data/MANIFEST.md`; rebuild; compare | orchestrator | S4e.0 | 2024–25 weather and game months non-null; leaderboard overall rows unchanged or each delta named | done — fetched 2026-10-24T11:06:49Z: 7 × 17,544 hourly rows, no nulls; 93 Sharks home games; copied (new filenames only) into the canonical `~/Desktop/transit-demand-forecasting/data/raw/`; hashes in `data/MANIFEST.md`. run1 vs run0: leaderboard CSV byte-identical; the 8 existing `benchmark_results.csv` rows identical; 12 new slice rows (`game_day`, `sharks_game` n=200, `rainy_day` n=100, per model). Store (SHA-256 `aa02436d44b5…f241`): weather columns filled for 1,200 rows (2024–25), event columns for 800 (16 game months × 50); 2019–23 `precip_mm`/`precip_in` differ by ≤ 2.6e-16 relative (summation order), every other 2019–23 cell identical |
| S4e.2 | SARIMAX `exog` in `arima.py` (default path unchanged) + `models/baselines/covariate_experiment.py` (control + 3 arms, test and validation windows, station-clustered test, row-level DM, per-station wins, decision) | implementer | plan | Unit tests pass; with no exog the SARIMA forecasts are identical to before | in progress |
| S4e.3 | Scored run; evidence `docs/covariate-experiment.md`; README result | orchestrator | S4e.1, S4e.2 | Every number in the doc traces to the run's CSV/log | todo |
| S4e.4 | Review the branch diff | code-reviewer | S4e.2 | No BLOCKER open | todo |
| S4e.5 | Delivery audit at sprint close | delivery-auditor | S4e.3, S4e.4 | Board matches git | todo |


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
