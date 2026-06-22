# Daily Updates

## 2026-06-22

### Bug Fixes

**Timezone handling — systematic `tz_localize` → `tz_convert` correction (HIGH severity)**

`tz_localize(None)` raises an error when called on a timezone-aware Series/Timestamp. The correct method to strip timezone info from an already-aware object is `tz_convert(None)`. This bug was present in four files and would cause runtime crashes whenever timezone-aware timestamps flowed through the pipeline.

- `machine_learning_files/merge_pipeline.py` — fixed 4 occurrences (event timestamps, weather timestamps, base timestamps, train/val/test split timestamps)
- `scripts/export_website_data.py` — fixed 2 occurrences (`export_ridership_actuals` and `export_model_comparison`)
- `evaluation/validators.py` — fixed 1 occurrence in `check_station_coverage`; added a guard so the conversion only runs when the column is actually timezone-aware

**Dead code / always-zero counter in `Processing/feature_engineering.py` (MEDIUM severity)**

`n_new = n_features - len(df.columns)` always evaluated to 0 because both sides reference the same object at the same point in time. Fixed by capturing the initial column count (`n_input_cols`) at the top of `build_features` before any transformations run, so the log line now correctly reports how many columns were added.

### Files Changed

| File | Change |
|------|--------|
| `machine_learning_files/merge_pipeline.py` | 4× `tz_localize(None)` → `tz_convert(None)` |
| `scripts/export_website_data.py` | 2× `tz_localize(None)` → `tz_convert(None)` |
| `evaluation/validators.py` | Added tz-aware guard + `tz_convert(None)` |
| `Processing/feature_engineering.py` | Capture `n_input_cols` before transforms; fix `n_new` counter |
