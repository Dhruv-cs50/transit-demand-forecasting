# Daily Updates

Running log of bugs fixed, improvements made, and observations noted each session.

---

## 2026-06-01

### Bugs Fixed

**`Processing/feature_engineering.py`**
- `build_features()` was computing `n_new = n_features - len(df.columns)` after enrichment had already run, making `n_new` always `0`. Fixed by capturing `n_input_cols = len(df.columns)` before the pipeline and computing `n_new = n_features - n_input_cols`. Log message now reports `+N new` columns correctly.

**`evaluation/validators.py` — `check_missing_windows()`**
- `grp.loc[idx - 1, "timestamp"]` used the original DataFrame integer index to find the preceding row, which fails silently (returns `"unknown"`) when the group's index values are non-consecutive (e.g. `[0, 5, 100]`). Fixed by adding `reset_index(drop=True)` after `sort_values("timestamp")` so positional and label indices align, then guarding with `if idx > 0`.

**`machine_learning_files/api.py` — `_run_forecast()`**
- `pd.Timestamp(as_of, tz="America/Los_Angeles")` raised an unhandled exception for malformed date strings, causing a 500 instead of an informative error. Wrapped in `try/except` that re-raises as `ValueError` (caught upstream as HTTP 404).

**`machine_learning_files/fetch_events.py` — `enrich_events()`**
- `df.get("game_type", pd.Series("", index=df.index)) == "3"` is error-prone when `game_type` column is absent (non-NHL rows). Replaced with an explicit `if "game_type" in df.columns` branch for clarity and safety.
- API key guard was checking `== "YOUR_TICKETMASTER_API_KEY"` but not guarding against `None` or empty string. Added `not tm_key or` prefix.

**`evaluation/metrics.py` — `wape()`**
- Returned `float("nan")` when all actuals are near-zero. Downstream code (model comparison tables, CSV exports) propagated NaN silently. Changed to return `0.0`, which is the mathematically correct WAPE when both errors and actuals are negligible.

### Notes
- No new features or refactors — fixes only.
- All changes are backwards-compatible; no API or schema changes.
