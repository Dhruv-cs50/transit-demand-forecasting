# Interval calibration (P10/P90)

**Status (Sprint 5).** Calibrations that weight recent errors were measured
on data up to `val_end`, under a rule fixed on the sprint board (6daa610)
before any of their numbers existed.
- **Two models change:** SeasonalNaive gets a calibrated band for the first
  time, and Prophet moves from one half-year of errors to a rolling pool.
- **SARIMA and Chronos-1 keep their Sprint 4 entries:** no candidate
  qualified for them.
- **Point metrics are unchanged.** P50 is never read for writing.
- **Test result (scored once):**
  - SeasonalNaive: 94.3% → **83.7%**, tails 3.3% / 13.0%. It is now inside
    75–85%.
  - Prophet: 74.7% → **74.0%**, with a slightly worse interval score.
  - SARIMA and Chronos-1 are unchanged at 96.7% and 72.7%.
  - Details in [Test result](#test-result-scored-once).

Sprint 4's single-window calibration (PR #138) follows unchanged under
[Sprint 4](#sprint-4--one-validation-window-pr-138).

## Sprint 5 — calibrations that track recent errors

### Decision

| Model | Sprint 4 interval | Sprint 5 interval (`configs/model.yaml`) | 2024-H2: coverage (below P10 / above P90) | 2025-H1: coverage (below / above) | Deployed band, fit on data to 2025-06-30 |
|---|---|---|---|---|---|
| SeasonalNaive | own ±20% band | `rolling_hl6 asym_relative/horizon` | 81.3% (4.7% / 14.0%) | 81.0% (4.0% / 15.0%) | P50 × (1 − 0.013…0.015, 1 + 0.169…0.170), by month ahead |
| SARIMA | own band | own band: no candidate qualified | — | — | — |
| Prophet | split-conformal `scaled/horizon` | `rolling_hl6 relative/pooled` | 84.0% (11.3% / 4.7%) | 84.7% (4.3% / 11.0%) | P50 × (1 ± 0.0789) |
| Chronos-1 zero-shot | split-conformal `relative/pooled` | unchanged: no candidate qualified | 84.0% (0.3% / 15.7%) | 84.3% (0.7% / 15.0%) | P50 × (1 ± 0.1539) |

- `rolling_hl6` is a weighted split-conformal quantile over forecasts from
  every monthly origin from 2023-12-31 to one month before the forecast
  origin. Weights halve every 6 months of age.
- Chronos-1's two coverage columns are its Sprint 4 method. That method
  fails 2024-H2 by 0.7 points in the upper tail, but the rule keeps a
  model's entry when nothing qualifies.
- The deployed bands were computed by `evaluation/interval_study.py` from
  data up to `val_end`, before the test split was scored.
  `benchmarks.py` must log the same quantiles.

**SeasonalNaive is calibrated for the first time.**
- Its errors are skewed: 2025 actuals ran above the same month a year
  earlier. The band therefore reaches about 17% above P50 and 1.5% below.
- It is less than half as wide as the own ±20% band (18.4% vs 40% of P50
  on 2025-H1). Its interval score falls from 37.6 to 22.4.
- It qualifies on 2025-H1 with exactly 15.0% of misses above P90, the
  limit. Chronos-1 also sat on that boundary in Sprint 4, and then missed
  on test.
- Coverage is uneven by month: December 2024 covered 46%, June 2025 54%.

**Prophet's Sprint 4 method fails the stricter rule.**
- On 2024-H2 it covers 70.3%, with 22.7% of misses below P10.
- The new band is a flat ±8.6–8.7% of P50 on the two validation windows.
  The deployed band is ±7.9%, because the errors of early 2025 were
  smaller.

**The winner is not clearly better than its neighbours.**
- Prophet's two qualifiers score 22.98 (`rolling_hl6 relative/pooled`) and
  23.10 (`aci_origin relative/pooled`).
- The non-eligible single-window `scaled/pooled` would have qualified at
  22.77.
- Differences this small are within the noise of 300-row windows whose
  misses cluster by month.

**SARIMA's errors change sign between the windows.**
- On 2024-H2 its misses fall above P90 (own band: 19.3% above). On 2025-H1
  they fall below P10 (7.3% below, 1.7% above).
- No band fit on earlier errors passes both.
- The asymmetric methods put 75–77% of 2024-H2's actuals above P90. Their
  pool there comes from 24–29-observation fits, the weakness named with the
  rule.

**Chronos-1 came closest without qualifying.**
- `rolling_hl6 asym_relative/horizon` covers 80.7% on 2024-H2 but 86.7% on
  2025-H1, 1.7 points over the band.

**Updating the band inside the window did not help.**
- `aci_window` and `monthly_recal` (measured, not eligible) would have
  qualified only for Prophet. They score 23.02 and 22.96, about the same as
  the winner's 22.98.
- Neither would have rescued SARIMA or Chronos-1.

### Rule

Fixed on `docs/sprint-board.md` in 6daa610 (2026-10-24 03:18:18), before the
study code existed (122fc9c) or ran. The rule:

> A candidate qualifies for a model if, on **both** 2024-H2 and 2025-H1,
> coverage is 75–85% and neither tail has more than 15% misses. Qualifiers
> rank by the mean of their two interval scores. If one non-incumbent
> candidate qualifies for all four models, the one with the lowest mean score
> across models is used for all; otherwise each model takes its own
> lowest-scoring qualifier; a model with no qualifier keeps its current
> entry.

No candidate qualified for every model, so the choice is per model. Interval
score is the Winkler score at α = 0.2, summed and divided by total actual
ridership, as in Sprint 4. Lower is better.

**Three implementation choices the rule text does not specify.** They were
added in the review fix round, after results were seen. None changes the
outcome: no eligible score is infinite, no qualifiers tie, and the decision is
identical.
- A window only passes if its interval score is finite, so an infinite band
  never qualifies.
- Ranking uses the unrounded mean score.
- Ties break by candidate name.

`interval_study.py` stops if `configs/model.yaml` carries anything other than
the validated choice, or the incumbent where nothing qualified. It also stops
if the config moves windows B and V.

**Eligible candidates, 10 per model, settings fixed with the rule:**
- `incumbent`: Sprint 4's entry, fit on the previous half-year (SARIMA and
  SeasonalNaive: their own band).
- `rolling_hl6`: score {`scaled`, `relative`, `asym_relative`} × group
  {`pooled`, `horizon`}.
- `aci_origin`: adaptive conformal inference (Gibbs & Candès 2021), step 0.1,
  run over the pool's monthly batches. Score {`scaled`, `relative`,
  `asym_relative`}, pooled; one α per tail for `asym_relative`.

**Measured and reported, not eligible:**
- `rolling_eq`: the pool with equal weights.
- `single`: Sprint 4's other single-window variants.
- `aci_window` and `monthly_recal`: these revise the band during the scored
  window using that window's own earlier actuals, which a band published at
  the forecast origin cannot use.

### Protocol

| Step | Study, window B | Study, window V | Leaderboard (`benchmarks.py`) |
|---|---|---|---|
| Forecast origin T | 2024-06-30 | 2024-12-31 | 2025-06-30 (`val_end`) |
| Scored | 2024-H2 | 2025-H1 (validation) | 2025-H2 (test) |
| Pool origins | 2023-12-31 … 2024-05-31 (6) | 2023-12-31 … 2024-11-30 (12) | 2023-12-31 … 2025-05-31 (18) |
| Pool rows per model (target ≤ T) | 1,050 | 2,850 | 4,650 |

- **First origin.** 2023-12-31 is the first origin every model can use as
  deployed:
  - SARIMA's airline model needs 24 observations;
  - Prophet drops its yearly term under 18;
  - Chronos's 24-month context would otherwise reach the 2019 rows.
- **How each origin is forecast.** Through the code path `benchmarks.py`
  uses for that model. The store it sees is cut at min(origin + 6 months, T).
- **What the study reads.** `interval_study.py` cuts the store at `val_end`
  when it reads it, and asserts that every scored and pool timestamp is on or
  before `val_end`.
- **Store-cut check.** In each window, 5 origins have a forecast window that
  runs past T, so their store is actually cut. A forecast cut at T must equal
  the uncut forecast from the same origin wherever both exist, and must exist
  for every target on or before T; otherwise the study stops. Rows compared
  per model and window:
  - SARIMA, Prophet and Chronos-1: 1,500 (750 with target ≤ T).
  - SeasonalNaive: 750. A cut store has no rows after T for it to forecast.
  - The largest difference was 0.0 everywhere.
- **Horizon.** Each pool row carries `horizon` = months from its origin to
  its target. The fit raises an error if the column is missing or
  inconsistent. Dense-ranking timestamps, which is how a single window
  counts horizon, would mis-group a pool of several origins.
- **Weighted quantile** (Barber et al. 2023). Weight 0.5^(age/6), with age in
  months from the target to T, and the scored point weighted 1. The quantile
  is the smallest score s with Σ_(s_i ≤ s) w_i ≥ level·(Σ w_i + 1). With unit
  weights (every w_i = 1) this is exactly Sprint 4's split-conformal quantile
  (tested).
- **ACI over origins.** Monthly target batches are taken in order. Each band
  uses the conformal quantile of earlier-target rows at level 1 − α, then α
  moves by 0.1·(0.2 − miss rate). α is clipped to [1/(n+1), 0.5] so the
  quantile stays finite. The final α sets the level on the whole pool.

### Validation results, eligible candidates

Coverage, misses and interval score are in %. Each model's rows are sorted by
mean score. All three tables are written by `interval_study.py`
(`evaluation/outputs/interval_study/adaptive_tables.md`). The same values are
in `adaptive_rule_all.csv`.

| Model | Candidate | B coverage % | B below / above % | B score | V coverage % | V below / above % | V score | Mean score | Qualifies |
|---|---|---:|---|---:|---:|---|---:|---:|---|
| SeasonalNaive | rolling_hl6 asym_relative/pooled | 88 | 5.67 / 6.33 | 24.03 | 81 | 4 / 15 | 21.71 | 22.87 | no |
| SeasonalNaive | rolling_hl6 asym_relative/horizon | 81.33 | 4.67 / 14 | 24.72 | 81 | 4 / 15 | 22.36 | 23.54 | **yes** |
| SeasonalNaive | aci_origin asym_relative/pooled | 90.67 | 1 / 8.33 | 28.32 | 78.67 | 3.67 / 17.67 | 23.35 | 25.84 | no |
| SeasonalNaive | aci_origin relative/pooled | 81 | 1 / 18 | 28.91 | 69.67 | 1.67 / 28.67 | 32.54 | 30.72 | no |
| SeasonalNaive | aci_origin scaled/pooled | 81 | 1 / 18 | 28.91 | 69.67 | 1.67 / 28.67 | 32.54 | 30.72 | no |
| SeasonalNaive | rolling_hl6 relative/pooled | 83.67 | 1 / 15.33 | 29.42 | 72.67 | 1.67 / 25.67 | 32.15 | 30.78 | no |
| SeasonalNaive | rolling_hl6 scaled/pooled | 83.67 | 1 / 15.33 | 29.42 | 72.67 | 1.67 / 25.67 | 32.15 | 30.78 | no |
| SeasonalNaive | rolling_hl6 relative/horizon | 75.33 | 1 / 23.67 | 30.22 | 72.33 | 1.67 / 26 | 32.63 | 31.42 | no |
| SeasonalNaive | rolling_hl6 scaled/horizon | 75.33 | 1 / 23.67 | 30.22 | 72.33 | 1.67 / 26 | 32.63 | 31.42 | no |
| SeasonalNaive | incumbent | 97.67 | 0 / 2.33 | 39.47 | 96 | 0 / 4 | 37.6 | 38.53 | no |
| SARIMA | rolling_hl6 relative/pooled | 85.33 | 0.67 / 14 | 27.71 | 88 | 8.33 / 3.67 | 24.06 | 25.88 | no |
| SARIMA | aci_origin relative/pooled | 87.67 | 0.33 / 12 | 28.25 | 88 | 8.33 / 3.67 | 24.04 | 26.14 | no |
| SARIMA | rolling_hl6 relative/horizon | 83.33 | 0.33 / 16.33 | 29.78 | 88.33 | 9.67 / 2 | 24.27 | 27.02 | no |
| SARIMA | incumbent | 80.33 | 0.33 / 19.33 | 29.35 | 91 | 7.33 / 1.67 | 25.26 | 27.3 | no |
| SARIMA | aci_origin scaled/pooled | 92 | 0 / 8 | 35.46 | 90.67 | 7.33 / 2 | 25.02 | 30.24 | no |
| SARIMA | rolling_hl6 scaled/pooled | 92.67 | 0 / 7.33 | 35.59 | 91.67 | 6.67 / 1.67 | 26.07 | 30.83 | no |
| SARIMA | rolling_hl6 scaled/horizon | 92.67 | 0 / 7.33 | 37.34 | 89.33 | 9.33 / 1.33 | 25.62 | 31.48 | no |
| SARIMA | rolling_hl6 asym_relative/pooled | 22.67 | 0.33 / 77 | 62.21 | 87 | 7 / 6 | 23.35 | 42.78 | no |
| SARIMA | aci_origin asym_relative/pooled | 23.67 | 0.33 / 76 | 61.6 | 89.67 | 7 / 3.33 | 24.94 | 43.27 | no |
| SARIMA | rolling_hl6 asym_relative/horizon | 24.67 | 0.33 / 75 | 65.99 | 88 | 7.33 / 4.67 | 22.97 | 44.48 | no |
| Prophet | rolling_hl6 relative/horizon | 87.67 | 8.33 / 4 | 24.35 | 85.67 | 4.33 / 10 | 21.3 | 22.83 | no |
| Prophet | rolling_hl6 relative/pooled | 84 | 11.33 / 4.67 | 24.66 | 84.67 | 4.33 / 11 | 21.3 | 22.98 | **yes** |
| Prophet | rolling_hl6 scaled/horizon | 86.33 | 9.67 / 4 | 23.9 | 88 | 3 / 9 | 22.07 | 22.98 | no |
| Prophet | aci_origin relative/pooled | 84 | 11.33 / 4.67 | 24.68 | 85 | 4.33 / 10.67 | 21.52 | 23.1 | **yes** |
| Prophet | rolling_hl6 asym_relative/pooled | 82.67 | 5.67 / 11.67 | 22.91 | 72.67 | 3.67 / 23.67 | 24.18 | 23.54 | no |
| Prophet | rolling_hl6 scaled/pooled | 84.33 | 11 / 4.67 | 24.9 | 86.67 | 4 / 9.33 | 22.32 | 23.61 | no |
| Prophet | aci_origin scaled/pooled | 84.67 | 11 / 4.33 | 24.99 | 88 | 3.67 / 8.33 | 22.75 | 23.87 | no |
| Prophet | incumbent | 70.33 | 22.67 / 7 | 27.46 | 82 | 4 / 14 | 20.31 | 23.88 | no |
| Prophet | rolling_hl6 asym_relative/horizon | 78.33 | 4.67 / 17 | 23.98 | 73.67 | 3.33 / 23 | 24.81 | 24.4 | no |
| Prophet | aci_origin asym_relative/pooled | 85.67 | 0 / 14.33 | 30.5 | 76.67 | 1.67 / 21.67 | 26.06 | 28.28 | no |
| Chronos-1 | rolling_hl6 asym_relative/horizon | 80.67 | 8.33 / 11 | 27.03 | 86.67 | 3 / 10.33 | 28.08 | 27.56 | no |
| Chronos-1 | rolling_hl6 asym_relative/pooled | 77.67 | 7.67 / 14.67 | 29.76 | 90.67 | 3 / 6.33 | 26.78 | 28.27 | no |
| Chronos-1 | aci_origin asym_relative/pooled | 83.67 | 3 / 13.33 | 30.19 | 92 | 3 / 5 | 28.91 | 29.55 | no |
| Chronos-1 | rolling_hl6 relative/horizon | 79 | 0 / 21 | 37.3 | 79 | 0.67 / 20.33 | 37.3 | 37.3 | no |
| Chronos-1 | rolling_hl6 scaled/horizon | 70 | 1 / 29 | 41.69 | 82.33 | 1.33 / 16.33 | 34.36 | 38.02 | no |
| Chronos-1 | rolling_hl6 scaled/pooled | 66.67 | 1 / 32.33 | 43.82 | 83 | 1.33 / 15.67 | 33.54 | 38.68 | no |
| Chronos-1 | aci_origin scaled/pooled | 67.67 | 0.67 / 31.67 | 43.66 | 86.33 | 1.33 / 12.33 | 33.86 | 38.76 | no |
| Chronos-1 | rolling_hl6 relative/pooled | 76.67 | 0.33 / 23 | 40.72 | 82 | 0.67 / 17.33 | 37.14 | 38.93 | no |
| Chronos-1 | aci_origin relative/pooled | 78.33 | 0.33 / 21.33 | 40.74 | 83.33 | 0.67 / 16 | 37.19 | 38.97 | no |
| Chronos-1 | incumbent | 84 | 0.33 / 15.67 | 41.45 | 84.33 | 0.67 / 15 | 37.28 | 39.36 | no |

### Diagnostics (measured, not eligible)

| Model | Candidate | B coverage % | B below / above % | B score | V coverage % | V below / above % | V score | Mean score | Qualifies |
|---|---|---:|---|---:|---:|---|---:|---:|---|
| SeasonalNaive | monthly_recal asym_relative/pooled | 84.33 | 8 / 7.67 | 23.97 | 79.33 | 5 / 15.67 | 21.42 | 22.7 | no |
| SeasonalNaive | aci_window asym_relative/pooled | 86.33 | 6.67 / 7 | 23.96 | 80.33 | 4.67 / 15 | 21.58 | 22.77 | no |
| SeasonalNaive | rolling_eq asym_relative/pooled | 87.67 | 6.33 / 6 | 24.03 | 84 | 4 / 12 | 21.58 | 22.8 | no |
| SeasonalNaive | rolling_eq asym_relative/horizon | 79.67 | 6.33 / 14 | 24.85 | 81.33 | 4 / 14.67 | 22.64 | 23.74 | **yes** |
| SeasonalNaive | aci_window relative/pooled | 83 | 1 / 16 | 29.45 | 72.33 | 1.67 / 26 | 32.32 | 30.88 | no |
| SeasonalNaive | aci_window scaled/pooled | 83 | 1 / 16 | 29.45 | 72.33 | 1.67 / 26 | 32.32 | 30.88 | no |
| SeasonalNaive | monthly_recal relative/pooled | 81.67 | 1 / 17.33 | 29.48 | 72.33 | 1.67 / 26 | 32.31 | 30.9 | no |
| SeasonalNaive | monthly_recal scaled/pooled | 81.67 | 1 / 17.33 | 29.48 | 72.33 | 1.67 / 26 | 32.31 | 30.9 | no |
| SeasonalNaive | rolling_eq relative/pooled | 87.67 | 1 / 11.33 | 30.76 | 74.33 | 1.67 / 24 | 31.88 | 31.32 | no |
| SeasonalNaive | rolling_eq scaled/pooled | 87.67 | 1 / 11.33 | 30.76 | 74.33 | 1.67 / 24 | 31.88 | 31.32 | no |
| SeasonalNaive | rolling_eq relative/horizon | 75.33 | 1 / 23.67 | 30.42 | 73 | 1.33 / 25.67 | 33.06 | 31.74 | no |
| SeasonalNaive | rolling_eq scaled/horizon | 75.33 | 1 / 23.67 | 30.42 | 73 | 1.33 / 25.67 | 33.06 | 31.74 | no |
| SARIMA | monthly_recal relative/pooled | 78.33 | 1 / 20.67 | 26.98 | 88.33 | 8.33 / 3.33 | 24.07 | 25.52 | no |
| SARIMA | aci_window relative/pooled | 82.33 | 0.67 / 17 | 27.59 | 86 | 10 / 4 | 23.55 | 25.57 | no |
| SARIMA | rolling_eq relative/pooled | 83.67 | 0.67 / 15.67 | 27.42 | 88.33 | 8.33 / 3.33 | 24.27 | 25.84 | no |
| SARIMA | rolling_eq relative/horizon | 83.67 | 0.33 / 16 | 29.85 | 90 | 8.33 / 1.67 | 24.66 | 27.26 | no |
| SARIMA | monthly_recal scaled/pooled | 89.67 | 0 / 10.33 | 30.57 | 90.67 | 7.33 / 2 | 25.11 | 27.84 | no |
| SARIMA | aci_window scaled/pooled | 92.67 | 0 / 7.33 | 34.4 | 90 | 8 / 2 | 24.92 | 29.66 | no |
| SARIMA | rolling_eq scaled/pooled | 92 | 0 / 8 | 35.53 | 93.33 | 6.33 / 0.33 | 27.54 | 31.54 | no |
| SARIMA | aci_window asym_relative/pooled | 62.67 | 0.33 / 37 | 40.11 | 85.33 | 7.33 / 7.33 | 23.2 | 31.66 | no |
| SARIMA | rolling_eq scaled/horizon | 92.67 | 0 / 7.33 | 37.42 | 91 | 8 / 1 | 26.34 | 31.88 | no |
| SARIMA | monthly_recal asym_relative/pooled | 39.33 | 0.67 / 60 | 47.33 | 87 | 6.33 / 6.67 | 23.52 | 35.42 | no |
| SARIMA | rolling_eq asym_relative/pooled | 22.67 | 0.33 / 77 | 61.72 | 86.67 | 6 / 7.33 | 23.38 | 42.55 | no |
| SARIMA | rolling_eq asym_relative/horizon | 23 | 0.33 / 76.67 | 66.53 | 87.33 | 5.67 / 7 | 23.03 | 44.78 | no |
| Prophet | rolling_eq scaled/horizon | 85 | 10.67 / 4.33 | 23.49 | 87.67 | 3 / 9.33 | 21.81 | 22.65 | no |
| Prophet | rolling_eq relative/horizon | 87 | 9 / 4 | 24.41 | 85 | 4.33 / 10.67 | 21.16 | 22.78 | no |
| Prophet | rolling_eq relative/pooled | 83.33 | 11.67 / 5 | 24.56 | 83.67 | 5 / 11.33 | 21.12 | 22.84 | **yes** |
| Prophet | monthly_recal relative/pooled | 81.67 | 12.33 / 6 | 24.8 | 82.67 | 5.33 / 12 | 21.13 | 22.96 | **yes** |
| Prophet | aci_window relative/pooled | 81.67 | 12.33 / 6 | 24.86 | 82.67 | 5.33 / 12 | 21.18 | 23.02 | **yes** |
| Prophet | monthly_recal asym_relative/pooled | 75 | 9 / 16 | 24.37 | 80 | 4 / 16 | 22.34 | 23.36 | no |
| Prophet | aci_window asym_relative/pooled | 78 | 9 / 13 | 24.31 | 78.67 | 4 / 17.33 | 22.52 | 23.42 | no |
| Prophet | monthly_recal scaled/pooled | 84.33 | 11 / 4.67 | 24.99 | 85.67 | 4 / 10.33 | 21.89 | 23.44 | no |
| Prophet | rolling_eq asym_relative/pooled | 82.67 | 8.33 / 9 | 22.95 | 72.67 | 4 / 23.33 | 23.93 | 23.44 | no |
| Prophet | rolling_eq scaled/pooled | 84.33 | 11 / 4.67 | 24.77 | 86.67 | 4 / 9.33 | 22.15 | 23.46 | no |
| Prophet | aci_window scaled/pooled | 83.67 | 11.33 / 5 | 25.1 | 85.67 | 4 / 10.33 | 22.03 | 23.56 | no |
| Prophet | rolling_eq asym_relative/horizon | 77.67 | 5.33 / 17 | 24.31 | 71.33 | 3.33 / 25.33 | 25.32 | 24.82 | no |
| Chronos-1 | rolling_eq asym_relative/horizon | 80.33 | 8.67 / 11 | 26.98 | 86.67 | 3 / 10.33 | 26.91 | 26.94 | no |
| Chronos-1 | rolling_eq asym_relative/pooled | 75.67 | 10 / 14.33 | 29.87 | 90.33 | 3.33 / 6.33 | 26.03 | 27.95 | no |
| Chronos-1 | aci_window asym_relative/pooled | 75 | 10.67 / 14.33 | 30.67 | 88.67 | 3.33 / 8 | 26.12 | 28.4 | no |
| Chronos-1 | monthly_recal asym_relative/pooled | 71.67 | 10.33 / 18 | 31.33 | 90.33 | 3.33 / 6.33 | 26.31 | 28.82 | no |
| Chronos-1 | rolling_eq relative/horizon | 79.67 | 0 / 20.33 | 37.32 | 77 | 0.67 / 22.33 | 37.44 | 37.38 | no |
| Chronos-1 | rolling_eq scaled/horizon | 70 | 1 / 29 | 41.77 | 81 | 1.33 / 17.67 | 34.12 | 37.94 | no |
| Chronos-1 | rolling_eq scaled/pooled | 66.67 | 1 / 32.33 | 43.76 | 82.67 | 1.33 / 16 | 33.51 | 38.64 | no |
| Chronos-1 | rolling_eq relative/pooled | 77.67 | 0.33 / 22 | 40.72 | 82 | 0.67 / 17.33 | 37.14 | 38.93 | no |
| Chronos-1 | aci_window scaled/pooled | 70.33 | 0.67 / 29 | 44.65 | 81 | 1.33 / 17.67 | 33.81 | 39.23 | no |
| Chronos-1 | aci_window relative/pooled | 76 | 0.33 / 23.67 | 41.47 | 79.33 | 0.67 / 20 | 37.47 | 39.47 | no |
| Chronos-1 | monthly_recal relative/pooled | 71.67 | 0.33 / 28 | 42.09 | 83 | 0.67 / 16.33 | 37.25 | 39.67 | no |
| Chronos-1 | monthly_recal scaled/pooled | 65.67 | 1 / 33.33 | 45.67 | 83 | 1.33 / 15.67 | 33.67 | 39.67 | no |

Sprint 4's single-window variants, scored on both windows (B calibrated on
2024-H1, V on 2024-H2). A per-station quantile rests on 6 scores, so its
asymmetric band is infinite and has no interval score (—):

| Model | Candidate | B coverage % | B below / above % | B score | V coverage % | V below / above % | V score | Mean score | Qualifies |
|---|---|---:|---|---:|---:|---|---:|---:|---|
| SeasonalNaive | single asym_relative/pooled | 84.33 | 13 / 2.67 | 26.16 | 79.33 | 4 / 16.67 | 21.96 | 24.06 | no |
| SeasonalNaive | single asym_relative/horizon | 67.33 | 18.33 / 14.33 | 29.78 | 73.33 | 4.33 / 22.33 | 22.16 | 25.97 | no |
| SeasonalNaive | single relative/pooled | 90.67 | 1 / 8.33 | 33.34 | 72.67 | 1.67 / 25.67 | 32.15 | 32.75 | no |
| SeasonalNaive | single scaled/pooled | 90.67 | 1 / 8.33 | 33.34 | 72.67 | 1.67 / 25.67 | 32.15 | 32.75 | no |
| SeasonalNaive | single relative/horizon | 77.33 | 0.67 / 22 | 34.96 | 69.33 | 2 / 28.67 | 31.35 | 33.16 | no |
| SeasonalNaive | single scaled/horizon | 77.33 | 0.67 / 22 | 34.96 | 69.33 | 2 / 28.67 | 31.35 | 33.16 | no |
| SeasonalNaive | single relative/station | 92.67 | 1 / 6.33 | 35.73 | 74.67 | 0 / 25.33 | 33.77 | 34.75 | no |
| SeasonalNaive | single scaled/station | 92.67 | 1 / 6.33 | 35.73 | 74.67 | 0 / 25.33 | 33.77 | 34.75 | no |
| SeasonalNaive | single asym_relative/station | 100 | 0 / 0 | — | 100 | 0 / 0 | — | — | no |
| SARIMA | single relative/horizon | 91.33 | 0.33 / 8.33 | 31.26 | 78.33 | 20 / 1.67 | 26.01 | 28.64 | no |
| SARIMA | single relative/pooled | 95 | 0.33 / 4.67 | 34.14 | 90.33 | 7 / 2.67 | 25.3 | 29.72 | no |
| SARIMA | single relative/station | 95.33 | 0.33 / 4.33 | 36.32 | 91.33 | 6.33 / 2.33 | 26.81 | 31.56 | no |
| SARIMA | single scaled/horizon | 96 | 0 / 4 | 40.09 | 75 | 21.67 / 3.33 | 25.86 | 32.98 | no |
| SARIMA | single scaled/pooled | 97.33 | 0 / 2.67 | 41.59 | 90.67 | 7.33 / 2 | 25.08 | 33.34 | no |
| SARIMA | single scaled/station | 91 | 0.67 / 8.33 | 43.53 | 93.33 | 5 / 1.67 | 30.19 | 36.86 | no |
| SARIMA | single asym_relative/horizon | 14.67 | 0.33 / 85 | 74.28 | 49 | 50 / 1 | 30.87 | 52.58 | no |
| SARIMA | single asym_relative/pooled | 15 | 0 / 85 | 77.29 | 53.33 | 45.33 / 1.33 | 33.46 | 55.38 | no |
| SARIMA | single asym_relative/station | 100 | 0 / 0 | — | 100 | 0 / 0 | — | — | no |
| Prophet | single scaled/pooled | 84 | 11 / 5 | 24.65 | 83.33 | 4.67 / 12 | 20.89 | 22.77 | **yes** |
| Prophet | single relative/pooled | 86.33 | 9.67 / 4 | 25.12 | 81.33 | 5.67 / 13 | 20.77 | 22.94 | no |
| Prophet | single scaled/horizon | 70.33 | 22.67 / 7 | 27.46 | 82 | 4 / 14 | 20.31 | 23.88 | no |
| Prophet | single relative/horizon | 76 | 17.67 / 6.33 | 28.7 | 78.33 | 5.33 / 16.33 | 20.44 | 24.57 | no |
| Prophet | single asym_relative/pooled | 84.67 | 11.67 / 3.67 | 26.11 | 71.67 | 4.33 / 24 | 23.79 | 24.95 | no |
| Prophet | single relative/station | 92.33 | 3.67 / 4 | 28.56 | 90.33 | 1.67 / 8 | 24.31 | 26.44 | no |
| Prophet | single scaled/station | 88 | 7.67 / 4.33 | 28.14 | 94 | 0.67 / 5.33 | 28.8 | 28.47 | no |
| Prophet | single asym_relative/horizon | 46 | 36 / 18 | 33.5 | 51 | 5.33 / 43.67 | 30.67 | 32.08 | no |
| Prophet | single asym_relative/station | 100 | 0 / 0 | — | 100 | 0 / 0 | — | — | no |
| Chronos-1 | single asym_relative/pooled | 68.67 | 22.67 / 8.67 | 32.62 | 91.33 | 3.67 / 5 | 25.76 | 29.19 | no |
| Chronos-1 | single asym_relative/horizon | 72.67 | 17.33 / 10 | 30.37 | 69 | 4.33 / 26.67 | 33.21 | 31.79 | no |
| Chronos-1 | single relative/pooled | 84 | 0.33 / 15.67 | 41.45 | 84.33 | 0.67 / 15 | 37.28 | 39.36 | no |
| Chronos-1 | single scaled/pooled | 66.33 | 1 / 32.67 | 44 | 90.33 | 1 / 8.67 | 35.15 | 39.58 | no |
| Chronos-1 | single relative/station | 87 | 0.33 / 12.67 | 41.58 | 92.33 | 0.33 / 7.33 | 39.88 | 40.73 | no |
| Chronos-1 | single relative/horizon | 85 | 0 / 15 | 39.05 | 64.33 | 2 / 33.67 | 44.63 | 41.84 | no |
| Chronos-1 | single scaled/horizon | 68 | 1 / 31 | 43.39 | 65 | 1.67 / 33.33 | 44.27 | 43.83 | no |
| Chronos-1 | single scaled/station | 72 | 1.67 / 26.33 | 46.05 | 89.33 | 0.67 / 10 | 46.47 | 46.26 | no |
| Chronos-1 | single asym_relative/station | 100 | 0 / 0 | — | 100 | 0 / 0 | — | — | no |

### Test result (scored once)

**Run.** `models/baselines/benchmarks.py` at 7cdfd11, the commit that
recorded the choice, on the rebuilt pinned env. Scored on the 2025-H2
holdout, n = 300 per model.

**Gates:**
- Two consecutive runs gave byte-identical leaderboard, results and LaTeX
  files.
- WAPE, MAE, RMSE, MAPE, sMAPE, MASE, n, n_expected and `Coverage_raw_%` are
  identical to PR #138's leaderboard on every slice (`assert_frame_equal`).
- The quantiles `benchmarks.py` logged equal the ones the study computed
  before the run: SeasonalNaive q_hi − q_lo 0.1829–0.1840, Prophet
  q = 0.0789, n = 4,650 each.

| Model | Interval now | Own band | Before (PR #138) | **Now** | Below P10 / above P90 | Width, % of P50 (before → now) | Interval score % (before → now) | Coverage by month, Jul–Dec | Validation (2024-H2 / 2025-H1) |
|---|---|---:|---:|---:|---|---|---|---|---|
| SeasonalNaive | `rolling_hl6 asym_relative/horizon` | 94.33% | 94.33% | **83.67%** | 3.3% / 13.0% | 40.0 → 18.3 | 38.69 → 24.27 | 80 88 88 90 82 74 | 81.3% / 81.0% |
| Prophet | `rolling_hl6 relative/pooled` | 46.00% | 74.67% | **74.00%** | 13.0% / 13.0% | 15.1 → 15.8 | 22.14 → 23.26 | 92 90 52 54 74 82 | 84.0% / 84.7% |
| SARIMA | own band (unchanged) | 96.67% | 96.67% | 96.67% | 1.0% / 2.3% | — | — | — | — |
| Chronos-1 zero-shot | `relative/pooled`, Sprint 4 (unchanged) | 51.00% | 72.67% | 72.67% | 0.0% / 27.3% | — | — | — | — |

**Where the extra columns come from.** `scripts/interval_test_breakdown.py`
computes the tails, widths, scores and by-month columns for SeasonalNaive and
Prophet:
- It rebuilds each band with `evaluation/calibration.py` from the forecasts
  `interval_study.py` cached. The review checked that this is the same pool
  `benchmarks.py` builds, row for row.
- It never fits a model, and it stops on a missing bound.
- The new band must reproduce the leaderboard's Coverage_% exactly, and the
  band each model published before must reproduce PR #138's 94.33% and
  74.67%, or the script stops.

SARIMA's and Chronos-1's rows are Sprint 4's.

**SeasonalNaive works on test.**
- It covers 83.7%, with 3.3% below P10 and 13.0% above P90, inside every
  limit of the rule.
- Its band is less than half as wide as before, and its interval score falls
  by 37%.
- It is the only model whose calibrated test band is in 75–85% with both
  tails within 15%.

**Prophet did not improve.**
- Coverage fell from 74.67% to 74.00%, and the interval score worsened from
  22.14 to 23.26.
- Its misses are now even (13.0% each side, instead of 10.0% / 15.3%), but
  September and October covered 52% and 54%.
- Validation predicted 84–85%, so test fell about 10–11 points short. That
  is a larger drop than Sprint 4's for Prophet (82.0% → 74.7%, 7.3 points).
- The recency weights narrowed the band just before errors grew. The pool
  through June 2025 gave ±7.9%, while 80% of the test errors were within
  ±8.4% of P50. On 2025-H1 the same method used ±8.7%.

**Prophet keeps the new method.** The rule chose it before the test was
scored. Switching back on the strength of this result would choose a method
on the test split.

**The website wording stays "not calibrated".** Sprint 4's rule changes it
only if every model's test coverage is 75–85%, and Prophet (74.0%), Chronos-1
(72.7%) and SARIMA (96.7%) are not. The site's coverage range stays 73–97%.
`website/data/model_comparison.json` carries the new Coverage_pct and
Interval_method for SeasonalNaive and Prophet.

### Not covered

- **SARIMA and Chronos-1 are still not calibrated to the rule.**
  - SARIMA's errors change sign between half-years.
  - Chronos-1's band misses the upper tail.
  - A next step for either would be a bias correction of the band that is
    re-estimated each month. That stays within "P50 unchanged", but it is a
    new candidate set and needs a new rule.
- **The serving path is still not calibrated.** The API and
  `forecasts.json` still publish raw bands.
- **Each window is a single forecast origin.** Its misses cluster by month,
  so a 300-row window carries far less information than 300 independent
  rows. Two windows halve the luck of one, but they do not remove it.

### Reproduce

```bash
python -m unittest tests.test_calibration tests.test_adaptive_calibration tests.test_benchmark_calibration
python evaluation/interval_study.py          # writes evaluation/outputs/interval_study/adaptive_*.csv
python models/baselines/benchmarks.py
```

## Sprint 4 — one validation window (PR #138)

In Sprint 4 each model's method was chosen on validation data only and
committed (215449c) before the test split was scored with it. The test result
is in [Test result](#test-result-scored-once-1):
- **Prophet and Chronos-1 improve sharply:** 46.0% → 74.7% and 51.0% → 72.7%
  coverage. Both still fall short of the 75–85% band.
- **SARIMA and SeasonalNaive keep their own over-wide bands:** 96.7% and 94.3%.
- **Point metrics are unchanged.**

### Decision

| Model | Raw coverage, validation | Interval method (`configs/model.yaml`) | Calibrated coverage, validation | Misses below P10 / above P90 | Deployed quantile (fit on 2025-H1) |
|---|---:|---|---:|---|---|
| SeasonalNaive | 96.0% | none: no method passed validation | — | 0.0% / 4.0% (raw) | — |
| SARIMA | 91.0% | none: no method passed validation | — | 7.3% / 1.7% (raw) | — |
| Prophet | 54.3% | split-conformal `scaled`, per horizon | 82.0% | 4.0% / 14.0% | half-widths × 1.30, 1.06, 1.79, 1.92, 2.49, 1.83 for months 1–6 |
| Chronos-1 zero-shot | 49.3% | split-conformal `relative`, pooled | 84.3% | 0.7% / 15.0% | P50 × (1 ± 0.1539) |

Validation means: calibrated on 2024-H2 forecasts, scored on the 2025-H1
validation split, 300 station-months per model. P50 is never changed, so
WAPE, MAE and every other point metric are identical with or without
calibration.

- **No single method qualified for all four models.** The rule was fixed
  before any number was seen (see below), so the fallback is a per-model
  choice.
- **Prophet and Chronos-1 get split-conformal bands.** On test these reach
  74.7% and 72.7%, short of 80% (see Test result). Both were badly over-confident
  (54% and 49% raw coverage on validation). Prophet's winner, `scaled/horizon` (interval
  score 20.31), edges the next qualifiers, `relative/pooled` (20.77) and
  `scaled/pooled` (20.89), by less than the noise in a 300-row window. It was taken because the rule says lowest interval score,
  not because it looks better. Chronos-1 qualifies only under
  `relative/pooled`, and sits on the boundary: 84.3% coverage, upper-tail
  misses exactly 15.0%.
- **SARIMA and SeasonalNaive keep their own bands.** No method passed
  validation for either, so their leaderboard Coverage_% is raw and errs wide
  (both over-cover on validation and on test).
- **The binding problem is drift between half-years, not the method.**
  Inside 2025-H1, station-fold cross-validation (calibrate on 40 stations,
  score the other 10, no time shift) gives 79–83% coverage for every pooled
  and per-horizon method on every model, though not always with even tails.
  The same methods fail when errors from one half-year are applied to the
  next:
  - SARIMA's 2024-H2 errors fit its band (pooled scaled q = 0.99), but by
    2025-H1 the band over-covers (91%), so a quantile from the earlier window
    does not shrink it. The per-horizon variants reach 75–78% but put 20–22%
    of misses below P10, which fails the tail limit.
  - SeasonalNaive's 2024-H2 errors were small (pooled relative q = 0.119,
    i.e. ±11.9%), while 2025-H1 actuals ran above last year's. The upper tail
    takes 25–29% of misses under every symmetric method. The asymmetric
    pooled method reaches 79.3%, but 16.7% of misses fall above P90, so it
    fails.

### Selection rule

**As fixed on the sprint board (056bd7b), before any validation number was
seen:**

> a method qualifies if every model lands in 75–85% validation coverage with
> neither tail above 15% misses; among qualifiers the lowest mean interval
> score wins, one method for all four models preferred. Prophet MCMC is
> measured and reported, not eligible.

The plan the user approved said, also before any number: "if none qualifies,
I'll document a per-model choice." Sensitivity checks were declared not to be
selection evidence.

**As applied, once no method qualified for every model.** Each model took its
own lowest-interval-score qualifier, and a model with none kept its own band.
This form of the fallback was written after the validation numbers were seen.
It is the most literal reading of the rule, not a choice among alternatives.

Interval score is the Winkler score at α = 0.2, `(P90 − P10) + 10·(P10 − y)·[y < P10] + 10·(y − P90)·[y > P90]`,
summed and divided by total actual ridership. Lower is better: it rewards a
narrow band and penalises misses.

### Protocol

The leaderboard calibrates on 2025-H1 and applies the result to 2025-H2. The
study runs the same procedure one half-year earlier, so it never needs the
test split:

| Step | Leaderboard (`models/baselines/benchmarks.py`) | Study (`evaluation/interval_study.py`) |
|---|---|---|
| Calibration forecasts | 2025-H1, fit ends 2024-12-31 | 2024-H2, fit ends 2024-06-30 |
| Scored forecasts | 2025-H2, fit ends 2025-06-30 | 2025-H1, fit ends 2024-12-31 |

- `interval_study.py` cuts the feature store at `val_end` when it reads it and
  asserts that every scored timestamp is on or before `val_end`.
- Every forecast comes from the code path `benchmarks.py` uses for that model,
  with only the forecast origin changed.
- Chronos reads its own feature store from disk, and passes the rows after
  the forecast origin to the model as future covariates. The study, and
  `benchmarks.py` for its validation run, hand it a store that ends with the
  forecast window, so no later row reaches the forecast.
  - chronos-t5-small ignores covariates. A one-off development check found
    forecasts from the full store and the cut store bit-identical for three
    stations. The review found the same for all 300 validation rows.
  - A covariate-aware checkpoint would not be indifferent. That is why the
    store is cut anyway.
- Each model's 2025-H1 forecasts in the study come from the same training
  data as the validation forecasts `benchmarks.py` makes at run time. The
  deployed quantiles in the Decision table were therefore fit from validation
  data alone, before the test split was scored.

Conformal quantile: the ⌈(n+1)·0.8⌉-th smallest calibration score. A
per-station quantile has n = 6, so ⌈7·0.8⌉ = 6 and each station's band
becomes its single worst calibration miss. The asymmetric per-station variant
needs ⌈7·0.9⌉ = 7 > 6 scores for each tail, so its band is infinite.

Methods (`evaluation/calibration.py`):
- `scaled`: rescales the model's own half-widths.
  Score `max((P50 − y)/(P50 − P10), (y − P50)/(P90 − P50))`.
- `relative`: ignores the model's band.
  Score `|y − P50| / P50`, band `P50·(1 ± q)`.
- `asym_relative`: calibrates each tail at 10% separately.
  Score `(y − P50) / P50`.

Groups: `pooled` (one quantile), `horizon` (one per forecast month, 50 rows
each), `station` (one per station, 6 rows each).

### Validation results, all methods

Calibrated on 2024-H2, scored on 2025-H1. Width is the mean of
(P90 − P10)/P50.

| Model | Method | Coverage % | Below P10 % | Above P90 % | Width % of P50 | Interval score % | Coverage by month (Jan–Jun) |
|---|---|---|---|---|---|---|---|
| SeasonalNaive | raw | 96 | 0 | 4 | 40 | 37.60 | 98 98 98 98 98 86 |
| SeasonalNaive | scaled/pooled | 72.67 | 1.67 | 25.67 | 23.89 | 32.15 | 84 92 84 48 88 40 |
| SeasonalNaive | scaled/horizon | 69.33 | 2 | 28.67 | 21.64 | 31.35 | 86 82 88 72 52 36 |
| SeasonalNaive | scaled/station | 74.67 | 0 | 25.33 | 27.16 | 33.77 | 80 100 80 56 84 48 |
| SeasonalNaive | relative/pooled | 72.67 | 1.67 | 25.67 | 23.89 | 32.15 | 84 92 84 48 88 40 |
| SeasonalNaive | relative/horizon | 69.33 | 2 | 28.67 | 21.64 | 31.35 | 86 82 88 72 52 36 |
| SeasonalNaive | relative/station | 74.67 | 0 | 25.33 | 27.16 | 33.77 | 80 100 80 56 84 48 |
| SeasonalNaive | asym_relative/pooled | 79.33 | 4 | 16.67 | 17.32 | 21.96 | 86 96 84 68 86 56 |
| SeasonalNaive | asym_relative/horizon | 73.33 | 4.33 | 22.33 | 15.13 | 22.16 | 90 84 86 80 54 46 |
| SeasonalNaive | asym_relative/station | 100 | 0 | 0 | ∞ | — | 100 100 100 100 100 100 |
| SARIMA | raw | 91 | 7.33 | 1.67 | 23.05 | 25.26 | 88 92 88 96 86 96 |
| SARIMA | scaled/pooled | 90.67 | 7.33 | 2 | 22.83 | 25.08 | 88 92 88 96 86 94 |
| SARIMA | scaled/horizon | 75 | 21.67 | 3.33 | 19.54 | 25.86 | 98 34 88 96 58 76 |
| SARIMA | scaled/station | 93.33 | 5 | 1.67 | 31.31 | 30.19 | 94 88 94 96 92 96 |
| SARIMA | relative/pooled | 90.33 | 7 | 2.67 | 21.82 | 25.30 | 98 94 90 92 84 84 |
| SARIMA | relative/horizon | 78.33 | 20 | 1.67 | 20.23 | 26.01 | 98 30 90 94 66 92 |
| SARIMA | relative/station | 91.33 | 6.33 | 2.33 | 26.59 | 26.81 | 98 92 94 92 86 86 |
| SARIMA | asym_relative/pooled | 53.33 | 45.33 | 1.33 | 14.63 | 33.46 | 80 12 44 82 38 64 |
| SARIMA | asym_relative/horizon | 49 | 50 | 1 | 14.39 | 30.87 | 56 20 24 68 66 60 |
| SARIMA | asym_relative/station | 100 | 0 | 0 | ∞ | — | 100 100 100 100 100 100 |
| Prophet | raw | 54.33 | 13.33 | 32.33 | 9.34 | 23.41 | 72 74 50 44 34 52 |
| Prophet | scaled/pooled | 83.33 | 4.67 | 12 | 17.66 | 20.89 | 94 94 84 80 66 82 |
| Prophet | scaled/horizon | 82 | 4 | 14 | 16.91 | 20.31 | 74 92 76 86 96 68 |
| Prophet | scaled/station | 94 | 0.67 | 5.33 | 29.08 | 28.80 | 96 100 92 96 90 90 |
| Prophet | relative/pooled | 81.33 | 5.67 | 13 | 15.47 | 20.77 | 86 94 78 76 74 80 |
| Prophet | relative/horizon | 78.33 | 5.33 | 16.33 | 14.37 | 20.44 | 70 86 78 78 90 68 |
| Prophet | relative/station | 90.33 | 1.67 | 8 | 23.24 | 24.31 | 90 96 88 90 90 88 |
| Prophet | asym_relative/pooled | 71.67 | 4.33 | 24 | 14.96 | 23.79 | 82 94 64 56 70 64 |
| Prophet | asym_relative/horizon | 51 | 5.33 | 43.67 | 10.04 | 30.67 | 56 54 10 78 38 70 |
| Prophet | asym_relative/station | 100 | 0 | 0 | ∞ | — | 100 100 100 100 100 100 |
| Chronos-1 | raw | 49.33 | 1.33 | 49.33 | 19.54 | 41.44 | 50 80 16 24 64 62 |
| Chronos-1 | scaled/pooled | 90.33 | 1 | 8.67 | 35.83 | 35.15 | 96 96 92 82 92 84 |
| Chronos-1 | scaled/horizon | 65 | 1.67 | 33.33 | 29.88 | 44.27 | 16 96 98 98 40 42 |
| Chronos-1 | scaled/station | 89.33 | 0.67 | 10 | 48.91 | 46.47 | 98 98 82 84 92 82 |
| Chronos-1 | relative/pooled | 84.33 | 0.67 | 15 | 33.73 | 37.28 | 92 94 84 66 82 88 |
| Chronos-1 | relative/horizon | 64.33 | 2 | 33.67 | 26.32 | 44.63 | 26 94 86 94 32 54 |
| Chronos-1 | relative/station | 92.33 | 0.33 | 7.33 | 42.15 | 39.88 | 98 98 92 84 90 92 |
| Chronos-1 | asym_relative/pooled | 91.33 | 3.67 | 5 | 23.63 | 25.76 | 98 90 92 84 88 96 |
| Chronos-1 | asym_relative/horizon | 69 | 4.33 | 26.67 | 17.33 | 33.21 | 38 86 88 94 36 72 |
| Chronos-1 | asym_relative/station | 100 | 0 | 0 | ∞ | — | 100 100 100 100 100 100 |


Selection summary across the four models:

| Method | Group | Every model qualifies | Mean interval score % | Worst gap from 80 (pts) |
|---|---|---|---|---|
| asym_relative | pooled | False | 26.24 | 26.67 |
| scaled | pooled | False | 28.32 | 10.67 |
| relative | pooled | False | 28.88 | 10.33 |
| asym_relative | horizon | False | 29.23 | 31 |
| scaled | horizon | False | 30.45 | 15 |
| relative | horizon | False | 30.61 | 15.67 |
| relative | station | False | 31.19 | 12.33 |
| scaled | station | False | 34.81 | 14 |
| asym_relative | station | False | — | 20 |

### Prophet with full posterior sampling (`mcmc_samples`)

**Why the earlier attempt errored.** The run that was meant to measure
`mcmc_samples=200` died in the diagnostic script, not in Prophet. Prophet fit
and predicted normally (about 2 s per station). The script then read
`m.params['sigma_obs'][0][0]`. Under MAP fitting that array has shape (1, 1);
under MCMC it is 1-D, one value per draw (400 draws for 4 chains × 100), so
the second index raised `IndexError: invalid index to scalar variable.`
The error never surfaced because the script's stderr went to `/dev/null`.

**Measured now** on 2025-H1, fit ending 2024-12-31: `mcmc_samples=400`
(4 chains × 200 post-warmup draws). The Stan seed is passed through
`fit(seed=…)` to cmdstanpy, because `np.random.seed` does not reach Stan.
Results:
- 0 divergent transitions;
- 97.8 s for 50 stations;
- two fits of the same station were bit-identical.

| Variant | Coverage % | Below P10 % | Above P90 % | Width % of P50 | Interval score % | WAPE % |
|---|---|---|---|---|---|---|
| MCMC, own P50 | 78.67 | 3.67 | 17.67 | 17.14 | 22.53 | 5.46 |
| MCMC offsets on MAP P50 | 82.33 | 5 | 12.67 | 17.03 | 20.26 | 4.58 |


In MCMC mode Prophet builds `yhat` from posterior-mean parameters instead of
the MAP fit. P50 moves by 1.66% on average and up to 12.16% for one
station-month, and WAPE gets worse (4.58% → 5.46% on validation). MCMC
therefore cannot replace the leaderboard model without changing point
forecasts. The hybrid row re-anchors MCMC's P10/P90 offsets on the MAP P50.
It would qualify (82.3%, interval score 20.26, just under the chosen
method's 20.31), but MCMC was declared ineligible before measuring and is
not adopted. Its other costs are 98 s of sampling per run, and a band that
mixes two fits.

### Sensitivity checks (not used for selection)

**Two calibration windows (2024-H1 + 2024-H2), scored on 2025-H1.** SARIMA's
airline model gets exactly its 24-observation minimum on the 2024-H1 fit, so
its first window does not represent the deployed fit.

| Model | Method | Coverage % | Below P10 % | Above P90 % |
|---|---|---|---|---|
| SeasonalNaive | scaled/pooled | 81 | 1.33 | 17.67 |
| SeasonalNaive | scaled/horizon | 77.67 | 1.33 | 21 |
| SeasonalNaive | scaled/station | 81.67 | 1.67 | 16.67 |
| SeasonalNaive | relative/pooled | 81 | 1.33 | 17.67 |
| SeasonalNaive | relative/horizon | 77.67 | 1.33 | 21 |
| SeasonalNaive | relative/station | 81.67 | 1.67 | 16.67 |
| SeasonalNaive | asym_relative/pooled | 86.33 | 4.33 | 9.33 |
| SeasonalNaive | asym_relative/horizon | 79.67 | 5 | 15.33 |
| SeasonalNaive | asym_relative/station | 88.33 | 2.67 | 9 |
| SARIMA | scaled/pooled | 96.67 | 3 | 0.33 |
| SARIMA | scaled/horizon | 95 | 4.33 | 0.67 |
| SARIMA | scaled/station | 95.67 | 4.33 | 0 |
| SARIMA | relative/pooled | 94 | 4.67 | 1.33 |
| SARIMA | relative/horizon | 93 | 6 | 1 |
| SARIMA | relative/station | 93 | 6.67 | 0.33 |
| SARIMA | asym_relative/pooled | 93.67 | 3.67 | 2.67 |
| SARIMA | asym_relative/horizon | 93.33 | 4.33 | 2.33 |
| SARIMA | asym_relative/station | 91.33 | 6.33 | 2.33 |
| Prophet | scaled/pooled | 85.33 | 4 | 10.67 |
| Prophet | scaled/horizon | 83.33 | 4.67 | 12 |
| Prophet | scaled/station | 90.33 | 3.33 | 6.33 |
| Prophet | relative/pooled | 84 | 5 | 11 |
| Prophet | relative/horizon | 85.67 | 3.33 | 11 |
| Prophet | relative/station | 89 | 3.67 | 7.33 |
| Prophet | asym_relative/pooled | 84.67 | 4.33 | 11 |
| Prophet | asym_relative/horizon | 73 | 4.67 | 22.33 |
| Prophet | asym_relative/station | 88.67 | 3.67 | 7.67 |
| Chronos-1 | scaled/pooled | 83 | 1.33 | 15.67 |
| Chronos-1 | scaled/horizon | 81 | 1.33 | 17.67 |
| Chronos-1 | scaled/station | 87 | 1.33 | 11.67 |
| Chronos-1 | relative/pooled | 85.67 | 0.67 | 13.67 |
| Chronos-1 | relative/horizon | 82 | 1 | 17 |
| Chronos-1 | relative/station | 89.33 | 0.67 | 10 |
| Chronos-1 | asym_relative/pooled | 90.33 | 4.67 | 5 |
| Chronos-1 | asym_relative/horizon | 86.67 | 4.33 | 9 |
| Chronos-1 | asym_relative/station | 92.67 | 2.67 | 4.67 |


**Station-fold cross-validation inside 2025-H1.** Five folds of 10 stations;
each fold is calibrated on the other 40. There is no time shift, so this is
optimistic by construction.

| Model | Method | Coverage % | Below P10 % | Above P90 % |
|---|---|---|---|---|
| SeasonalNaive | scaled/pooled | 81 | 1.33 | 17.67 |
| SeasonalNaive | scaled/horizon | 79.67 | 1.33 | 19 |
| SeasonalNaive | relative/pooled | 81 | 1.33 | 17.67 |
| SeasonalNaive | relative/horizon | 79.67 | 1.33 | 19 |
| SeasonalNaive | asym_relative/pooled | 81.67 | 9 | 9.33 |
| SeasonalNaive | asym_relative/horizon | 83 | 6.33 | 10.67 |
| SARIMA | scaled/pooled | 80 | 15 | 5 |
| SARIMA | scaled/horizon | 80.33 | 13.33 | 6.33 |
| SARIMA | relative/pooled | 79.33 | 13.67 | 7 |
| SARIMA | relative/horizon | 79.33 | 13.67 | 7 |
| SARIMA | asym_relative/pooled | 80.33 | 10 | 9.67 |
| SARIMA | asym_relative/horizon | 81.67 | 9.67 | 8.67 |
| Prophet | scaled/pooled | 79.33 | 6 | 14.67 |
| Prophet | scaled/horizon | 80.33 | 6.33 | 13.33 |
| Prophet | relative/pooled | 81 | 5.33 | 13.67 |
| Prophet | relative/horizon | 80.33 | 7 | 12.67 |
| Prophet | asym_relative/pooled | 80.33 | 10.33 | 9.33 |
| Prophet | asym_relative/horizon | 79.33 | 9.67 | 11 |
| Chronos-1 | scaled/pooled | 79.67 | 1.33 | 19 |
| Chronos-1 | scaled/horizon | 80.67 | 1 | 18.33 |
| Chronos-1 | relative/pooled | 79.33 | 0.67 | 20 |
| Chronos-1 | relative/horizon | 79.33 | 0.67 | 20 |
| Chronos-1 | asym_relative/pooled | 82.33 | 7 | 10.67 |
| Chronos-1 | asym_relative/horizon | 83.33 | 6.67 | 10 |


### Test result (scored once)

`models/baselines/benchmarks.py` at 215449c, pinned env, 2025-H2 holdout,
n = 300 per model. Two consecutive runs gave a byte-identical leaderboard,
and so did a third after the review fixes (same configuration, re-run only to
confirm the leaderboard did not move).
WAPE, MAE, RMSE, MAPE, sMAPE, MASE and n are identical to the uncalibrated
leaderboard, and `Coverage_raw_%` reproduces its coverage exactly.

| Model | Interval | Coverage, own band | Coverage, published | Below P10 / above P90 | Width, % of P50 | Coverage by month (Jul–Dec) | Validation coverage of the same method |
|---|---|---:|---:|---|---|---|---:|
| SARIMA | own band | 96.67% | 96.67% | 1.0% / 2.3% | — | — | — |
| Prophet | scaled/horizon | 46.00% | **74.67%** | 10.0% / 15.3% | 8.7% → 15.1% | 92 66 60 58 86 86 | 82.0% |
| Chronos-1 zero-shot | relative/pooled | 51.00% | **72.67%** | 0.0% / 27.3% | 18.6% → 30.8% | 98 82 62 10 96 88 | 84.3% |
| SeasonalNaive | own band | 94.33% | 94.33% | — | — | — | — |

Where the extra columns come from:
- The tail, width and by-month columns were recomputed from this run's saved
  forecast files with `evaluation/calibration.py`. The recomputed coverage
  matches the leaderboard exactly.
- SARIMA's split is of its own band.
- SeasonalNaive's forecasts are not written to disk, so its split is not
  shown.

Reading:
- **Calibration helped but did not reach nominal.** It moved both
  over-confident models 21–29 points toward 80%. Each lost 7–12 points between
  validation and test, the same half-year drift that ruled out SARIMA and
  SeasonalNaive.
- **Chronos-1 under-forecasts the test window.** All its misses fall above
  P90, and October 2025 alone covers 10% (5 of 50 stations). A symmetric band
  cannot fix a biased median, and the median may not change.
- **Prophet's misses fall in both tails** (10.0% below P10, 15.3% above
  P90). Its shortfall is mostly width, not bias.
- **Website wording stays "not calibrated".** The pre-declared rule changes
  it only if every model is in 75–85%. Only the coverage range figure is
  updated (46–97% → 73–97%).

### Not covered

- Serving-path intervals are not calibrated. `forecasts.json` (the
  Embarcadero chart on the website) and the API (`machine_learning_files/api.py`,
  `models/chronos2/predict.py`) still publish the model's own band.
- `website/api-demo.html` labels raw Chronos-1 output "P10/P90 = 80%
  prediction interval". Raw Chronos-1 covered 51.0% on test. Follow-up.
- Drift between half-years is the limit on any one-window calibration. A
  calibration that tracks recent errors, such as adaptive conformal or a
  rolling window, would be the next thing to measure for SARIMA and
  SeasonalNaive. It is not attempted here.

### Reproduce

```bash
python -m unittest tests.test_calibration tests.test_benchmark_calibration
python evaluation/interval_study.py --refresh
python models/baselines/benchmarks.py
```

The study writes `evaluation/outputs/interval_study/validation_*.csv`, which
the tables above were taken from. Pinned env: Python 3.14.0, pandas 3.0.6,
statsmodels 0.15.0, prophet 1.5.0, chronos-forecasting 2.3.2.