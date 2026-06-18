# Daily Updates

A running log of daily automated checks, bug fixes, and improvements.

---

## 2026-06-18

### Bug Fixes

**1. Timezone handling crash — `merge_pipeline.py`** (4 locations)

`tz_localize(None)` was called on already timezone-aware Series, which raises a `TypeError` at runtime. Fixed all four occurrences by replacing with `tz_convert(None)`, which correctly strips the timezone info from an aware datetime Series.

- `compute_event_features()` line 185 — `ev_ts` strip
- `compute_event_features()` line 191 — `ts_series` strip
- `build_feature_store()` line 270 — `wdf["timestamp"]` strip
- `build_feature_store()` line 286 — `base_ts` strip
- `make_splits()` line 340 — `ts` strip

**2. Timezone handling crash — `scripts/export_website_data.py`** (2 locations)

Same `tz_localize(None)` → `tz_convert(None)` fix in the website export script:

- `export_ridership_actuals()` line 158 — per-row `Timestamp` strip
- `export_model_comparison()` line 221 — Series strip on `actuals["timestamp"]`

**3. Dead-code variable — `Processing/feature_engineering.py`** (line 442)

`n_new = n_features - len(df.columns)` always computed `0` (subtracting the same
length from itself). The variable was never referenced afterward. Removed the
dead assignment; the log message on the next line already reports total feature
count correctly.

### Summary

| File | Changes |
|------|---------|
| `machine_learning_files/merge_pipeline.py` | 5× `tz_localize` → `tz_convert` |
| `scripts/export_website_data.py` | 2× `tz_localize` → `tz_convert` |
| `Processing/feature_engineering.py` | Removed dead `n_new` assignment |

No logic changes — purely correctness fixes for crashes and dead code.
