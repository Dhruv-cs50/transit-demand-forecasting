# Daily Updates Log

---

## 2026-06-04

### Bug Fixes

**Critical — `Processing/feature_engineering.py` (lines 441–442)**
- `n_new = n_features - len(df.columns)` always evaluated to zero because both sides of the subtraction were the same expression.
- Fix: captured `n_input_cols = len(df.columns)` before any transformations run, then computed `n_new = n_features - n_input_cols`.
- Also updated the log line to print `+{n_new} new` so new-feature counts are visible.

**Warning — `Processing/feature_engineering.py` (line 154) — `is_rain_onset`**
- The `df["is_rain_onset"]` assignment chained a nested `groupby` and `transform` in a single expression, making the logic opaque and the intermediate result inaccessible.
- Refactored into two steps: compute `_prev_raining` first, then apply the boolean mask. Semantics are identical; readability and debuggability are improved.

### Code Quality

- No logic changes to model training, inference, or data ingestion.
- All fixes are in `Processing/feature_engineering.py`.

### Known Issues (not yet fixed)

- **Prophet WAPE 176%**: Prophet's extreme error rate on monthly data is suspicious. Likely causes: yearly seasonality overfitting with <36 training months, and unscaled regressors. Worth testing `yearly_seasonality=False` and `standardize=True` on all regressors.
- **Event-feature data leakage**: `add_event_features()` does not enforce a hard cutoff between known past and future events at train/test split boundaries. Low risk for public game schedules, but should be documented explicitly.
- **No sample data committed**: `data/` is gitignored. New contributors must run all fetchers before the pipeline can execute locally. Consider committing a small fixture (e.g. 3-month, 5-station BART slice) under `transit_eda/data/`.

---

<!-- Append new entries above this line in reverse-chronological order (newest first). -->
