# Do weather and event covariates improve the monthly BART forecast?

**No.** Adding weather, Sharks home games, or both to the leaderboard's SARIMA did not improve the
forecast on either window. Observed weather made it measurably worse.

The plan, with the decision rule, is in `docs/covariate-experiment-plan.md`. The rule was committed
in `81b2089` (2026-10-24T11:01:10Z); the code that scored the arms is `d39e2fb`
(2026-10-24T11:29:19Z); the first scored run started at 2026-10-24T11:29:42Z. No arm was scored
before the rule existed, and nothing was tuned after.

## Result

Each arm is SARIMA (0,1,1)(0,1,1,12) per station, the 3.21 % leaderboard model, with the listed
store columns as `exog`, standardised with each station's training-window mean and SD. Nothing else
differs. n = 300 station-months in every row (50 stations × 6 months).

**Test** (fit Jan 2022 – Jun 2025, scored Jul – Dec 2025, the leaderboard's split):

| Model | Covariates | WAPE % | MAE | Raw 80 % band coverage % | Paired test vs SARIMA: mean d, p | Stations better / worse | Row-level DM p | Verdict |
|---|---|---:|---:|---:|---|---|---:|---|
| SARIMA (control) | none | 3.21 | 3,086 | 96.7 | — | — | — | — |
| SARIMAX + weather (observed) | `temp_f`, `precip_mm` | 3.79 | 3,645 | 94.7 | −559, **0.0005** | 8 / 42 | 0.0000 | no measurable improvement |
| SARIMAX + Sharks games | `hours_to_event` | 3.19 | 3,063 | 96.7 | +23, 0.54 | 28 / 22 | 0.55 | no measurable improvement |
| SARIMAX + weather (observed) + Sharks games | all three | 4.12 | 3,957 | 92.0 | −871, **0.00001** | 9 / 41 | 0.0000 | no measurable improvement |

**Validation** (fit Jan 2022 – Dec 2024, scored Jan – Jun 2025, the wet season):

| Model | WAPE % | MAE | Raw 80 % band coverage % | Paired test vs SARIMA: mean d, p | Stations better / worse | Row-level DM p |
|---|---:|---:|---:|---|---|---:|
| SARIMA (control) | 4.27 | 3,809 | 91.0 | — | — | — |
| SARIMAX + weather (observed) | 4.67 | 4,170 | 86.3 | −361, 0.13 | 7 / 43 | 0.024 |
| SARIMAX + Sharks games | 4.63 | 4,134 | 88.0 | −326, 0.20 | 17 / 33 | 0.047 |
| SARIMAX + weather (observed) + Sharks games | 5.27 | 4,706 | 81.3 | −898, 0.015 | 9 / 41 | 0.0001 |

*Paired test* is the pre-registered decision statistic. For each station, d is the mean over its 6
months of (|SARIMA error| − |arm error|), in riders. Then a one-sample t-test runs on the 50
stations. Positive d means the arm is better. *Row-level DM* is `benchmarks.py`'s Diebold–Mariano
test on the 300 rows. It treats rows that share months and stations as independent, so its p-value
is optimistic; it is reported, not used to decide. Coverage is each model's own SARIMAX band,
uncalibrated.

## Against the rule

An arm "improves" only if (1) its test WAPE is below SARIMA's, (2) the paired test gives p < 0.05
with d > 0, and (3) its validation WAPE is below SARIMA's.

- **Weather (observed):** fails all three. It is worse on test at 42 of 50 stations (p = 0.0005), and
  worse on validation.
- **Sharks games:** meets (1) by 0.02 points (3.19 against 3.21), fails (2) (p = 0.54, 28 stations
  better and 22 worse), and fails (3) (4.63 against 4.27).
- **Both:** fails all three, and is the worst row on both windows.

## What this does and does not show

- **The weather rows are a best case and still lose.** They use the weather later observed in each
  forecast month, which no forecast made on 30 June 2025 could have known. A real weather forecast
  would do no better.
- **Shown:** for this target (monthly station totals) and this model (per-station SARIMA with 36–42
  training months), these covariates in this form do not help. That holds both in a dry window
  (Jul–Dec) and in a wet one (Jan–Jun).
- **Not shown:**
  - whether weather or events matter at a daily or hourly grain;
  - whether a model that pools one effect across stations would gain;
  - whether events other than Sharks games matter. No other events are in the archive: Ticketmaster
    needs a key this project does not have.
- **Why the weather arms are worse was not measured.** One candidate is that 2–3 extra coefficients
  per station, estimated from so few months, mostly fit noise.
- **Weather locations.** 6 stations (EM, MB, FM, BE, SO, 19) take weather from their own location;
  the other 44 take the 7-location regional mean (PR #139's station table).

## Where it is published

- **Leaderboard and site best-model pick: unchanged.** At the user's decision (2026-10-24), the arms
  are a separate experiment table (`evaluation/outputs/covariate_experiment.csv`), never leaderboard
  rows. `export_website_data.py` copies every leaderboard row to the site, which labels the lowest
  WAPE "best model". The leaderboard CSV from this run is byte-identical to the one before the
  covariates existed.
- **SARIMA control matches the leaderboard.** Its 300 forecasts equal the leaderboard SARIMA's
  forecasts from the same run exactly.

## Reproduce

Inputs:
- BART workbooks per `data/MANIFEST.md`.
- Covariate archives 2019–2023 and 2024–2025 per `data/MANIFEST.md` ("Covariate archives").
- Python env: the gate env's 66 pins, Python 3.14.0.

```bash
python machine_learning_files/bart_od_from_xlsx.py --dir <workbooks>
python machine_learning_files/merge_pipeline.py
python Processing/feature_engineering.py
python models/baselines/covariate_experiment.py      # this table
python models/baselines/benchmarks.py                # the unchanged leaderboard
```

| Artifact | SHA-256 |
|---|---|
| `data/processed/feature_store.parquet` | `aa02436d44b5de83d77fab87036c046d0ca02983b9d8cbe807c37f9ad714f241` |
| `data/processed/feature_store_enriched.parquet` | `03e160d5f3cfea55e10dfdd0b43be41c76ee20d8e3977391a988f101906d2504` |
| `evaluation/outputs/covariate_experiment.csv` | `0bf4ab0ce8f3035902774045b6becc9945d3b37bf8997e51e17a210612a60a19` |
| `evaluation/outputs/covariate_experiment_stations.csv` | `57894d4ef6a01f2f8f598f5883a2a886ecb0458328ed1dcc3403becb6296f702` |

Two consecutive runs of `covariate_experiment.py` on that store wrote byte-identical CSVs. SARIMA's
maximum-likelihood fit has no random step. Open-Meteo's archive is a reanalysis that can be revised,
so a later re-fetch of the weather may not match these hashes byte for byte.
