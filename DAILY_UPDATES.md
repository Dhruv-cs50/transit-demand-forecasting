# Daily Updates Log

---

## 2026-06-10

### Bugs Fixed

#### 1. `Processing/feature_engineering.py` — `n_new` always zero (logic error)
- **Line 421 / 442:** `n_new = n_features - len(df.columns)` was subtracting the *same* (post-transform) column count from itself, always yielding 0.
- **Fix:** Captured `n_cols_before = len(df.columns)` before transformations run, then computed `n_new = n_features - n_cols_before`. Updated the log message to print the correct delta.

#### 2. `machine_learning_files/merge_pipeline.py` — `tz_localize(None)` on timezone-aware Series (4 sites)
- **Lines 185, 191, 269–270, 285–286, 339–340:** All five used `dt.tz_localize(None)` inside a branch that only executes when `dt.tz is not None` (i.e., when the Series *is* timezone-aware). Calling `tz_localize` on an already-aware Series raises `TypeError`; the correct call is `tz_convert(None)` to strip the timezone.
- **Fix:** Replaced all five occurrences of `tz_localize(None)` (under `if dt.tz is not None`) with `tz_convert(None)`.

#### 3. `machine_learning_files/zero_shot.py` — crash when `context_hours` is `None`
- **Line 99:** `pd.Timedelta(hours=context_hours)` raises `ValueError` when `context_hours` is `None`, which happens when `context_length_hours` is absent from `configs/model.yaml`.
- **Fix:** Changed the `else` branch to `elif context_hours is not None`, and added a final `else: context_df = past` fallback that uses all available history.

#### 4. `machine_learning_files/api.py` — unsafe column indexing for quantile columns
- **Lines 190–192:** `float(row[q_cols["pXX"]])` was evaluated unconditionally before the `if q_cols["pXX"]` guard, so a `None` key would raise `KeyError`.
- **Fix:** Replaced `row[q_cols[...]]` with `row.get(q_cols[...], float("nan"))` so a missing column returns `nan` safely.

### Summary
| File | Severity | Type |
|------|----------|------|
| `Processing/feature_engineering.py` | Low | Logic error (always-zero counter) |
| `machine_learning_files/merge_pipeline.py` | Critical | Runtime crash on timezone-aware data |
| `machine_learning_files/zero_shot.py` | High | Runtime crash on missing config key |
| `machine_learning_files/api.py` | Medium | Runtime crash on missing quantile columns |
