# Interval calibration (P10/P90)

**Status:** each model's method was chosen on validation data only and
committed (215449c) before the test split was scored with it. The test result
is in [Test result](#test-result-scored-once):
- **Prophet and Chronos-1 improve sharply:** 46.0% → 74.7% and 51.0% → 72.7%
  coverage. Both still fall short of the 75–85% band.
- **SARIMA and SeasonalNaive keep their own over-wide bands:** 96.7% and 94.3%.
- **Point metrics are unchanged.**

## Decision

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

## Selection rule

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

## Protocol

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

## Validation results, all methods

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

## Prophet with full posterior sampling (`mcmc_samples`)

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

## Sensitivity checks (not used for selection)

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


## Test result (scored once)

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

## Not covered

- Serving-path intervals are not calibrated. `forecasts.json` (the
  Embarcadero chart on the website) and the API (`machine_learning_files/api.py`,
  `models/chronos2/predict.py`) still publish the model's own band.
- `website/api-demo.html` labels raw Chronos-1 output "P10/P90 = 80%
  prediction interval". Raw Chronos-1 covered 51.0% on test. Follow-up.
- Drift between half-years is the limit on any one-window calibration. A
  calibration that tracks recent errors, such as adaptive conformal or a
  rolling window, would be the next thing to measure for SARIMA and
  SeasonalNaive. It is not attempted here.

## Reproduce

```bash
python -m unittest tests.test_calibration tests.test_benchmark_calibration
python evaluation/interval_study.py --refresh
python models/baselines/benchmarks.py
```

The study writes `evaluation/outputs/interval_study/validation_*.csv`, which
the tables above were taken from. Pinned env: Python 3.14.0, pandas 3.0.6,
statsmodels 0.15.0, prophet 1.5.0, chronos-forecasting 2.3.2.
