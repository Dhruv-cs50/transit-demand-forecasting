# Results in detail

The headline table is in the [README](../README.md#results). This page holds the
detail behind it: how the numbers were produced, the interval calibration, the
Chronos caveats, the covariate experiment, and what was superseded.

## How the table is produced

One `models/baselines/benchmarks.py` run against BART's actual monthly trip
counts, scored on **Jul–Dec 2025**: 300 station-months (50 stations × 6 forecast
steps), the same 300 for every model. Each row of
`website/data/model_comparison.json` carries `source` and `scored_split`, so any
figure traces to the run that made it.

| Model | MAE | WAPE | Coverage (nominal 80%) | Model's own band | Interval | Predictions |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| SARIMA airline (0,1,1)(0,1,1,12) | 3,086 | 3.21% | 96.7% | 96.7% | own band (no method passed validation) | 300 |
| Prophet (per-station) | 5,526 | 5.75% | 74.0% | 46.0% | rolling-origin conformal, fit on data to Jun 2025 | 300 |
| Chronos-1 zero-shot (`chronos-t5-small`) | 9,321 | 9.70% | 84.7% | 51.0% | bias-shifted rolling-origin conformal, fit on data to Jun 2025 | 300 |
| Seasonal naive | 10,333 | 10.75% | 83.7% | 94.3% | rolling-origin conformal (asymmetric), fit on data to Jun 2025 | 300 |

**What was and was not tuned on the test window.** No model, order or setting
was chosen on Jul–Dec 2025, so the point forecasts (P50, WAPE, MAE) are untuned
to it. The interval methods are not: they were revised after the test window had
been scored three times (Sprints 4–6, see
[interval-calibration.md](interval-calibration.md)), so read the coverage
column, Chronos-1's 84.7% especially, with that in mind.

**Reproducibility.** Prophet and Chronos both sample, so `configs/model.yaml`
seeds them (`prophet.seed`, `chronos2.seed`). Unseeded, Chronos moved between
8.06% and 9.70% WAPE and Prophet's coverage between 44% and 46% across otherwise
identical runs. Two consecutive runs of the table are byte-identical
(leaderboard, results, LaTeX and saved calibrators; the only byte difference is
a `generated_at` timestamp in intermediate Chronos parquets, never published).

## SARIMA across three half-years

The same specification, refit at each origin:

| Window | Fit through | WAPE | Coverage |
| --- | --- | ---: | ---: |
| Jul–Dec 2024 | Jun 2024 | 6.36% | 80.3% |
| Jan–Jun 2025 | Dec 2024 | 4.27% | 91.0% |
| **Jul–Dec 2025 (test)** | Jun 2025 | **3.21%** | 96.7% |

Read it as 3.2–6.4%. On the test window SARIMA beats Prophet at 46 and seasonal
naive at 48 of 50 stations (paired Wilcoxon vs Prophet p ≈ 8e-21); its error does
not grow with the horizon (2.6 / 2.5 / 3.3 / 3.5 / 4.4 / 2.9% for months 1–6);
bias is −0.47%; per-station median WAPE 2.55%, 90th percentile 5.2%. The largest
miss is Coliseum (17.9%: the August 2025 forecast was 37% high after an
Aug–Sep 2024 spike), then Pittsburg Center (+11.8%) and Downtown Berkeley
(−9.75%, after +24% year-over-year growth in 2025). Source:
[review-2026-10-28.md](review-2026-10-28.md).

## All four models across three half-years

`models/baselines/backtest_windows.py` reruns every model with the benchmark's
own code at three origins (`evaluation/outputs/backtest_windows.csv`, exported
to `website/data/backtest_windows.json`). Same 50 stations, same 6 steps, 300
station-months per cell; the Jul–Dec 2025 rows equal the leaderboard exactly.

| Model | Jul–Dec 2024 WAPE | Jan–Jun 2025 WAPE | Jul–Dec 2025 WAPE | Stations SARIMA beats (of 50), per window |
| --- | ---: | ---: | ---: | --- |
| SARIMA | 6.36% | **4.27%** | **3.21%** | — |
| Prophet | **5.36%** | 4.58% | 5.75% | 12 / 25 / 46 |
| Chronos-1 zero-shot | 8.92% | 9.60% | 9.70% | 38 / 41 / 49 |
| Seasonal naive | 6.62% | 8.17% | 10.75% | 27 / 42 / 48 |

Jul–Dec 2024 is not a clean holdout: Prophet's `yearly_fourier_order` and
SARIMA's airline order were both selected by inspecting it
(`configs/model.yaml`). On the two clean windows SARIMA has the lowest WAPE;
on the tuned window Prophet is a point lower. Coverage here uses each model's
own uncalibrated band, because the calibrators are fit on data to Jun 2025 and
applying them to 2024 would leak.

## Interval calibration

Point accuracy is sound; interval calibration is not finished. Seasonal naive's
and Chronos-1's P10–P90 bands landed in 75–85% on the holdout; Prophet's and
SARIMA's did not, and that is a single six-month window.

- **Seasonal naive:** its band is fit to recent errors, a weighted conformal
  quantile over forecasts from every month since December 2023, wider above P50
  than below. It covers 83.7%. Its own ±20% band covered 94.3% at more than
  twice the width.
- **Prophet:** its own band was far too narrow (46%). Widened with a conformal
  quantile fit on the rolling pool, one symmetric quantile for every month
  ahead, it reaches 74.0%, still short of 80% (74.7% under the earlier
  single-window method).
- **Chronos-1:** it under-forecasts; with a band widened around P50 its misses
  all fell above P90 (72.7%). Its band is re-centred on its recent median error
  for each month ahead (about 3.5% above P50 one month out, 9–10% further out)
  and widened by a conformal quantile. It covers 84.7%, with 5.3% of actuals
  below P10 and 10.0% above P90, at 70% of the earlier width. October 2025 still
  covered only 56%.
- **SARIMA:** its own band is too wide (96.7%). No calibration method passed
  validation for it, so it is published unchanged, and every API response says
  so.
- Calibration never touches the point forecast: WAPE and MAE are identical with
  or without it.

Each method was chosen on data up to June 2025 only, under a rule fixed before
measuring. The comparison, the validation numbers each choice rests on, and why
an earlier Prophet MCMC attempt failed are in
[interval-calibration.md](interval-calibration.md).

**What is published where.** The API serves SARIMA's own band and labels it in
each response. `website/data/forecasts_sarima.json` carries SARIMA's test
forecasts with that band (the site's default view);
`website/data/forecasts.json` carries Chronos-1's bias-shifted band behind a
toggle. Each Chronos record keeps the model's own bounds as `p10_raw`/`p90_raw`
and an `interval_method` label matching the leaderboard's. See
[interval-calibration.md § Serving](interval-calibration.md#serving).

## Chronos caveats

- The pinned checkpoint is `amazon/chronos-t5-small`, which is Chronos-**1**.
  Earlier material called it "Chronos-2"; the leaderboard label is now derived
  from the checkpoint so it cannot drift again. (The config key is still
  `chronos2`.)
- It runs **univariate**. `ChronosPipeline.predict_df` takes no `future_df`, so
  the covariate path in `zero_shot.py` falls back to no covariates for every
  station. The 9.70% is a no-covariate result.

## Weather and Sharks games do not improve the forecast

A separate, pre-registered experiment (`models/baselines/covariate_experiment.py`,
write-up in [covariate-experiment.md](covariate-experiment.md)) adds them to
SARIMA as `exog` and changes nothing else. On the test window, weather (using the
weather actually observed, a best case) raises WAPE from 3.21% to 3.79%, worse at
42 of 50 stations; Sharks home games give 3.19%, a difference the paired test
cannot tell from noise (p = 0.54), and 4.63% against 4.27% on the validation
window (paired p = 0.20). These are experiment rows, not leaderboard rows.

## What the benchmark refuses to publish

If `chronos-forecasting` is absent, the predictor falls back to seasonal naive,
and the row is omitted rather than credited to Chronos. Any model whose WAPE
exceeds 100% (worse than forecasting a flat zero) is rejected outright.

## Superseded figures

Earlier published figures (Prophet 176.3%, SARIMA 22.5%, and an AutoETS 14.2%
that was hand-entered, never computed) are superseded. At the time,
`benchmarks.py` could not execute at all (it failed on import), so no
leaderboard existed and the website export silently scored a different split.
The AutoGluon/AutoETS code, which never produced a result, was removed in
Sprint 8. The audit trail is in `updates/` and
[sprint-board.md](sprint-board.md).
